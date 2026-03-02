"""
License resolver for license-comply — looks up license info from PyPI.

This module queries the PyPI JSON API to find the license for each package
in the project's dependency list. It's the step that connects the local
dependency file to the outside world.

How it fits in the pipeline:
    scanner.py → resolver.py → classifier.py → analyzer.py → reporter.py

Key features:
  - Parallel lookups using ThreadPoolExecutor (up to 10x faster)
  - Disk caching with 7-day TTL to avoid redundant API calls
  - Graceful error handling for network issues and missing packages
"""

from __future__ import annotations

import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Optional

import requests

from license_comply.models import LicenseInfo, PackageInfo
from license_comply.utils import normalize_package_name

# ---------------------------------------------------------------------------
# Configuration constants
# ---------------------------------------------------------------------------

# PyPI JSON API endpoint — returns package metadata as JSON
PYPI_API_URL = "https://pypi.org/pypi/{package_name}/json"

# Maximum number of parallel threads for PyPI lookups.
# 10 is a reasonable balance between speed and not overwhelming PyPI's servers.
MAX_WORKERS = 10

# How long cached results remain valid (in seconds).
# 7 days = 604800 seconds. After this, the cache entry is ignored and a
# fresh lookup is performed.
CACHE_TTL_SECONDS = 7 * 24 * 60 * 60  # 7 days

# Default cache file name — stored in the current working directory
CACHE_FILENAME = ".license-comply-cache.json"

# HTTP request timeout in seconds
REQUEST_TIMEOUT = 15

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def resolve_licenses(
    packages: list[PackageInfo],
    use_cache: bool = True,
    cache_dir: str = ".",
) -> list[LicenseInfo]:
    """Look up license information for a list of packages from PyPI.

    Uses parallel HTTP requests for speed and an optional disk cache to
    avoid redundant lookups. Each package is queried independently.

    Args:
        packages: List of PackageInfo objects from the scanner.
        use_cache: Whether to read/write the disk cache. Set to False
            when the user passes --no-cache.
        cache_dir: Directory where the cache file is stored.

    Returns:
        A list of LicenseInfo objects, one per package. The category field
        is not yet set — that's the classifier's job.
    """
    # Load the disk cache if enabled
    cache: dict[str, Any] = {}
    cache_path = os.path.join(cache_dir, CACHE_FILENAME)
    if use_cache:
        cache = _load_cache(cache_path)

    results: list[LicenseInfo] = []
    packages_to_fetch: list[PackageInfo] = []

    # Check the cache first for each package
    for package in packages:
        cached_entry = _get_cached_entry(cache, package.name)
        if cached_entry is not None:
            results.append(cached_entry)
        else:
            packages_to_fetch.append(package)

    # Fetch remaining packages from PyPI in parallel
    if packages_to_fetch:
        fetched = _fetch_parallel(packages_to_fetch)
        results.extend(fetched)

        # Update the cache with new results
        if use_cache:
            for info in fetched:
                _set_cached_entry(cache, info)
            _save_cache(cache, cache_path)

    return results


# ---------------------------------------------------------------------------
# PyPI API lookup
# ---------------------------------------------------------------------------


def _fetch_single(package: PackageInfo) -> LicenseInfo:
    """Fetch license information for a single package from PyPI.

    Queries the PyPI JSON API and extracts the license from three sources
    (in order of reliability):
      1. The info.license_expression field (PEP 639, proper SPDX expression)
      2. The info.classifiers list (structured, standardized)
      3. The info.license field (free-text, set by the package author)

    Many packages have migrated to license_expression (PEP 639), which
    provides a clean SPDX identifier like "MIT" or "BSD-3-Clause".

    Args:
        package: The package to look up.

    Returns:
        A LicenseInfo object with the raw license data filled in.
    """
    url = PYPI_API_URL.format(package_name=package.name)
    pypi_url = f"https://pypi.org/project/{package.name}/"

    try:
        response = requests.get(url, timeout=REQUEST_TIMEOUT)
    except requests.RequestException as error:
        logger.warning("Network error looking up %s: %s", package.name, error)
        return LicenseInfo(
            package_name=package.name,
            declared_license=None,
            pypi_url=pypi_url,
        )

    # Package not found on PyPI
    if response.status_code == 404:
        return LicenseInfo(
            package_name=package.name,
            declared_license=None,
            pypi_url=pypi_url,
        )

    # Other HTTP errors
    if response.status_code != 200:
        logger.warning("PyPI returned status %d for %s", response.status_code, package.name)
        return LicenseInfo(
            package_name=package.name,
            declared_license=None,
            pypi_url=pypi_url,
        )

    try:
        data = response.json()
    except ValueError:
        logger.warning("Invalid JSON response from PyPI for %s", package.name)
        return LicenseInfo(
            package_name=package.name,
            declared_license=None,
            pypi_url=pypi_url,
        )

    info = data.get("info", {})

    # --- Source 1: license_expression (PEP 639, newest and most standardized) ---
    # Many packages have migrated to this field, which contains a proper SPDX
    # expression like "MIT" or "Apache-2.0 OR GPL-2.0-or-later".
    license_expression = info.get("license_expression", "")
    if isinstance(license_expression, str):
        license_expression = license_expression.strip()
    else:
        license_expression = ""

    # --- Source 2: classifiers (structured, standardized) ---
    classifiers = info.get("classifiers", [])
    license_classifier = _extract_license_from_classifiers(classifiers)

    # --- Source 3: license field (free-text, least standardized) ---
    license_field = info.get("license", "")
    if isinstance(license_field, str):
        license_field = license_field.strip()
    else:
        license_field = ""

    # Pick the best available source, in order of reliability.
    # license_expression is the most standardized (proper SPDX), followed by
    # classifiers, then the free-text license field.
    if license_expression:
        declared_license = license_expression
    elif license_classifier:
        declared_license = license_classifier
    elif license_field and license_field.upper() != "UNKNOWN":
        declared_license = license_field
    else:
        declared_license = None

    # Try to find the source repository URL
    source_url = _extract_source_url(info)

    return LicenseInfo(
        package_name=package.name,
        declared_license=declared_license,
        pypi_url=pypi_url,
        source_url=source_url,
    )


def _fetch_parallel(packages: list[PackageInfo]) -> list[LicenseInfo]:
    """Fetch license info for multiple packages in parallel.

    Uses ThreadPoolExecutor to make concurrent HTTP requests. This makes
    scanning ~10x faster for typical projects (2-3 seconds instead of 20-30).

    Args:
        packages: List of packages to look up.

    Returns:
        A list of LicenseInfo objects (order may differ from input).
    """
    results: list[LicenseInfo] = []

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        # Submit all lookups at once
        future_to_package = {
            executor.submit(_fetch_single, package): package for package in packages
        }

        # Collect results as they complete
        for future in as_completed(future_to_package):
            try:
                result = future.result()
                results.append(result)
            except Exception as error:
                # If a single lookup fails catastrophically, log and continue
                package = future_to_package[future]
                logger.warning("Failed to look up %s: %s", package.name, error)
                results.append(LicenseInfo(package_name=package.name, declared_license=None))

    return results


# ---------------------------------------------------------------------------
# Helper functions for extracting data from PyPI responses
# ---------------------------------------------------------------------------


def _extract_license_from_classifiers(classifiers: list[str]) -> Optional[str]:
    """Extract the license string from PyPI classifiers.

    PyPI classifiers look like:
        "License :: OSI Approved :: MIT License"
        "License :: OSI Approved :: Apache Software License"

    We extract the full classifier string — the classifier module will
    handle stripping the prefix.

    Args:
        classifiers: The list of classifier strings from PyPI.

    Returns:
        The first license classifier found, or None if none exist.
    """
    for classifier in classifiers:
        if classifier.startswith("License :: "):
            # Skip the generic "License :: OSI Approved" without a specific license
            if classifier == "License :: OSI Approved":
                continue
            return classifier
    return None


def _extract_source_url(info: dict) -> Optional[str]:
    """Try to find the source repository URL from PyPI project info.

    PyPI packages can list their URLs in info.project_urls. We look for
    common keys that typically point to the source code.

    Args:
        info: The 'info' dict from the PyPI JSON response.

    Returns:
        The source repository URL if found, otherwise None.
    """
    project_urls = info.get("project_urls") or {}

    # Common keys for source code URLs (in order of preference)
    source_keys = ["Source", "Source Code", "Repository", "GitHub", "Homepage", "Code"]

    for key in source_keys:
        for url_key, url_value in project_urls.items():
            if url_key.lower() == key.lower() and url_value:
                return url_value

    return None


# ---------------------------------------------------------------------------
# Disk cache
# ---------------------------------------------------------------------------


def _load_cache(cache_path: str) -> dict[str, Any]:
    """Load the disk cache from a JSON file.

    If the file doesn't exist or is corrupted, returns an empty dict
    (we never crash due to cache issues).

    Args:
        cache_path: Path to the cache JSON file.

    Returns:
        The cache as a dictionary, or empty dict on any error.
    """
    if not os.path.isfile(cache_path):
        return {}

    try:
        with open(cache_path, "r", encoding="utf-8") as file:
            return json.load(file)
    except (json.JSONDecodeError, OSError) as error:
        logger.warning("Cache file is corrupted or unreadable: %s", error)
        return {}


def _save_cache(cache: dict[str, Any], cache_path: str) -> None:
    """Save the cache to a JSON file using an atomic write.

    Writes to a temporary file first, then uses os.replace() to atomically
    move it into place. This prevents cache corruption if two processes
    write simultaneously or if the process is interrupted mid-write.

    The cache is written as human-readable JSON (indented) so users can
    inspect it if they want to see what's cached.

    Args:
        cache: The cache dictionary to save.
        cache_path: Path to write the cache file.
    """
    import tempfile

    # Prune expired entries before writing to prevent unbounded cache growth.
    # Any entry older than CACHE_TTL_SECONDS is removed from the dict.
    now = time.time()
    cache = {
        key: entry
        for key, entry in cache.items()
        if now - entry.get("timestamp", 0) <= CACHE_TTL_SECONDS
    }

    # Initialize tmp_path before the try block so the except handler can
    # safely check it — prevents NameError if json.dump() raises OSError
    # before the assignment.
    tmp_path = None

    try:
        # Write to a temp file in the same directory (same filesystem),
        # then atomically replace the target. os.replace() is atomic on POSIX.
        cache_dir = os.path.dirname(cache_path) or "."
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=cache_dir,
            suffix=".tmp",
            delete=False,
        ) as tmp_file:
            # Capture the temp file path BEFORE json.dump() so it's available
            # for cleanup even if the write fails (e.g., disk full).
            tmp_path = tmp_file.name
            json.dump(cache, tmp_file, indent=2, sort_keys=True)

        os.replace(tmp_path, cache_path)
    except OSError as error:
        logger.warning("Could not write cache file: %s", error)
        # Clean up the temp file if it was created but the replace failed
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                # Temp file cleanup is best-effort; OS will reclaim eventually
                pass


def _get_cached_entry(cache: dict[str, Any], package_name: str) -> Optional[LicenseInfo]:
    """Look up a package in the cache, checking TTL.

    Args:
        cache: The loaded cache dictionary.
        package_name: The package name to look up.

    Returns:
        A LicenseInfo if a valid (non-expired) cache entry exists, otherwise None.
    """
    # Normalize the package name for cache lookup so that "Requests",
    # "requests", and "REQUESTS" all hit the same cache entry.
    normalized_name = normalize_package_name(package_name)
    entry = cache.get(normalized_name)
    if entry is None:
        return None

    # Check if the cache entry has expired.
    # Also reject future timestamps (corrupted or manually edited cache) —
    # a negative age would mean the entry never expires, which is wrong.
    # Capture time.time() once to avoid a race between the two comparisons.
    now = time.time()
    cached_time = entry.get("timestamp", 0)
    if cached_time > now:
        return None
    if now - cached_time > CACHE_TTL_SECONDS:
        return None

    return LicenseInfo(
        package_name=package_name,
        declared_license=entry.get("declared_license"),
        pypi_url=entry.get("pypi_url"),
        source_url=entry.get("source_url"),
    )


def _set_cached_entry(cache: dict[str, Any], license_info: LicenseInfo) -> None:
    """Add or update a cache entry for a package.

    Args:
        cache: The cache dictionary to update (mutated in place).
        license_info: The license info to cache.
    """
    # Store under the normalized name so lookups are case/separator-insensitive.
    cache[normalize_package_name(license_info.package_name)] = {
        "declared_license": license_info.declared_license,
        "pypi_url": license_info.pypi_url,
        "source_url": license_info.source_url,
        "timestamp": time.time(),
    }
