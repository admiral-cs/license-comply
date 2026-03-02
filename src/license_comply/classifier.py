"""
License classifier for license-comply.

This module takes raw license strings from PyPI and matches them to known
licenses in the knowledge base. It's the bridge between the messy real-world
data (whatever the package author typed as their license) and the clean,
structured data our analyzer needs.

How it fits in the pipeline:
    scanner.py → resolver.py → classifier.py → analyzer.py → reporter.py

The matching strategy is deliberately simple and deterministic — no fuzzy
matching or ML. We use:
  1. Case-insensitive comparison
  2. Classifier prefix stripping (e.g., "License :: OSI Approved :: MIT License" → "MIT License")
  3. Whitespace normalization
  4. Dual-license OR splitting (e.g., "MIT OR Apache-2.0" → pick most permissive)
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from license_comply.models import LicenseCategory, LicenseInfo
from license_comply.utils import load_knowledge

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level cache for the license knowledge base
# ---------------------------------------------------------------------------

# We load the knowledge base once and reuse it for all classifications.
# This avoids reading and parsing the YAML file for every single package.
# The underscore prefix signals that this is a private module variable.
_license_db: Optional[list[dict]] = None


def _get_license_db() -> list[dict]:
    """Load the license knowledge base (cached after first call).

    Returns:
        The list of license definitions from licenses.yaml.
    """
    global _license_db
    if _license_db is None:
        data = load_knowledge("licenses.yaml")
        _license_db = data["licenses"]
    return _license_db


# ---------------------------------------------------------------------------
# Permissiveness ranking for dual-license resolution
# ---------------------------------------------------------------------------

# When a package is dual-licensed (e.g., "MIT OR GPL-3.0"), we pick the
# most permissive option. This ranking defines that order — lower numbers
# are more permissive (better for the user).
_PERMISSIVENESS_RANK: dict[str, int] = {
    "public_domain": 1,  # No restrictions at all — most permissive
    "permissive": 2,  # Attribution required — slightly more restrictive
    "weak_copyleft": 3,
    "strong_copyleft": 4,
    "non_software": 5,
    "unknown": 6,
    "proprietary": 7,
}


# ---------------------------------------------------------------------------
# License string normalization helpers
# ---------------------------------------------------------------------------

# PyPI classifiers follow this pattern:
#   "License :: OSI Approved :: MIT License"
#   "License :: OSI Approved :: Apache Software License"
# We want just the last part: "MIT License", "Apache Software License"
_CLASSIFIER_PREFIX_PATTERN = re.compile(
    r"^License\s*::\s*(?:OSI Approved\s*::\s*|DFSG approved\s*::\s*|"
    r"Other/Proprietary License\s*::\s*|Public Domain\s*::\s*)?",
    re.IGNORECASE,
)


def _normalize_license_string(raw: str) -> str:
    """Normalize a raw license string for matching.

    Applies four transformations:
      1. Strip PyPI classifier prefixes (e.g., "License :: OSI Approved :: ")
      1.5. Strip trailing parenthetical abbreviations (e.g., "(MPL 2.0)")
      2. Normalize whitespace (collapse multiple spaces, strip edges)
      3. Convert to lowercase for case-insensitive matching

    Many PyPI classifiers include a redundant abbreviation in parentheses at
    the end, e.g., "Mozilla Public License 2.0 (MPL 2.0)". The knowledge base
    only stores the full name without the abbreviation, so we strip it. About
    32 PyPI classifiers use this pattern.

    Args:
        raw: The raw license string from PyPI.

    Returns:
        A cleaned, lowercase string ready for matching.
    """
    # Step 1: Strip classifier prefix if present
    cleaned = _CLASSIFIER_PREFIX_PATTERN.sub("", raw)

    # Step 1.5: Strip trailing parenthetical abbreviation
    # Many PyPI classifiers include a redundant abbreviation in parentheses,
    # e.g., "Mozilla Public License 2.0 (MPL 2.0)" → "Mozilla Public License 2.0"
    # The regex only matches parentheticals at the END of the string, so license
    # names that legitimately contain parentheses mid-string won't be affected.
    cleaned = re.sub(r"\s*\([^)]*\)\s*$", "", cleaned)

    # Step 2: Normalize whitespace
    cleaned = " ".join(cleaned.split())

    # Step 3: Lowercase for case-insensitive matching
    cleaned = cleaned.lower().strip()

    return cleaned


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def classify_license(license_info: LicenseInfo) -> LicenseInfo:
    """Classify a single package's license by matching it to the knowledge base.

    Takes a LicenseInfo object (with declared_license set by the resolver)
    and fills in the spdx_id and category fields by matching against known
    licenses.

    If the license string contains " OR " (SPDX dual-license syntax), both
    sides are classified independently and the most permissive option is chosen.

    Args:
        license_info: A LicenseInfo object with declared_license set.

    Returns:
        The same LicenseInfo object with spdx_id and category updated.
        Returns UNKNOWN category if no match is found.
    """
    raw_license = license_info.declared_license

    # If there's no license string at all, it's unknown
    if not raw_license or raw_license.strip() == "":
        license_info.category = LicenseCategory.UNKNOWN
        return license_info

    # Check for conjunctive licensing with the SPDX "AND" operator.
    # AND means you must comply with ALL listed licenses.
    # We check for AND before OR because if both appear in the same
    # expression, it requires a full SPDX expression parser (deferred
    # to v1.1). We treat AND+OR as UNKNOWN with a logged warning.
    has_and = bool(re.search(r"\s+[Aa][Nn][Dd]\s+", raw_license))
    has_or = bool(re.search(r"\s+[Oo][Rr]\s+", raw_license))

    if has_and and has_or:
        # Mixed AND/OR expressions need a full SPDX parser — deferred to v1.1
        logger.warning(
            "License expression '%s' for package '%s' contains both AND and OR "
            "operators. A full SPDX expression parser is needed (deferred to v1.1). "
            "Treating as UNKNOWN.",
            raw_license,
            license_info.package_name,
        )
        license_info.category = LicenseCategory.UNKNOWN
        return license_info

    if has_and:
        return _classify_conjunctive_license(license_info, raw_license)

    # Check for dual-licensing with the SPDX "OR" operator.
    # This should be case-insensitive because real-world license strings
    # use variations like "MIT or Apache-2.0" and "MIT Or Apache-2.0".
    if has_or:
        return _classify_dual_license(license_info, raw_license)

    # Single license — try to match it
    spdx_id, category, classification_note = _match_license_string(raw_license)
    license_info.spdx_id = spdx_id
    license_info.category = category
    license_info.classification_note = classification_note

    return license_info


def classify_licenses(license_infos: list[LicenseInfo]) -> list[LicenseInfo]:
    """Classify a list of packages' licenses.

    Convenience function that calls classify_license() on each item.

    Args:
        license_infos: A list of LicenseInfo objects to classify.

    Returns:
        The same list with spdx_id and category fields updated.
    """
    for info in license_infos:
        classify_license(info)
    return license_infos


# ---------------------------------------------------------------------------
# Internal matching logic
# ---------------------------------------------------------------------------


def _match_license_string(
    raw: str,
) -> tuple[Optional[str], LicenseCategory, Optional[str]]:
    """Try to match a raw license string against the knowledge base.

    Uses a four-pass matching strategy:
      1. Exact match against known names (case-insensitive, normalized)
      2. Space-collapsed match (catches "GPL v3" → "GPLv3")
      3. Exact match against ambiguous_names (case-insensitive, normalized)
      4. Space-collapsed match against ambiguous_names

    Passes 3-4 are fallbacks for strings like "GNU General Public License"
    that could refer to any GPL version. When matched via ambiguous_names,
    the function returns a classification_note warning about the ambiguity.

    Args:
        raw: A raw license string (single license, not dual-licensed).

    Returns:
        A 3-tuple of (spdx_id, LicenseCategory, classification_note).
        classification_note is None for unambiguous matches, or a warning
        string for ambiguous matches. If no match is found, returns
        (None, LicenseCategory.UNKNOWN, None).
    """
    normalized = _normalize_license_string(raw)
    license_db = _get_license_db()

    # --- Pass 1: Exact match against known names ---
    for license_def in license_db:
        # Check if the normalized string matches any of the known names
        for known_name in license_def["names"]:
            if normalized == known_name.lower().strip():
                spdx_id = license_def["spdx_id"]
                # Wrap in try/except to handle typos in the YAML category field
                # (e.g., "permisive" instead of "permissive"). Falls back to
                # UNKNOWN, which triggers the stricter analysis — safe default.
                try:
                    category = LicenseCategory(license_def["category"])
                except ValueError:
                    logger.warning(
                        "Invalid category '%s' for license %s in knowledge base, "
                        "treating as UNKNOWN",
                        license_def["category"],
                        spdx_id,
                    )
                    category = LicenseCategory.UNKNOWN
                return spdx_id, category, None

    # --- Pass 2: Space-collapsed match against known names ---
    # Strip all spaces from both input and known names before comparing.
    # This catches variations like "GPL v3" matching "GPLv3", or
    # "LGPL v2.1" matching "LGPLv2.1", which are common in the wild.
    normalized_no_spaces = normalized.replace(" ", "")
    for license_def in license_db:
        for known_name in license_def["names"]:
            if normalized_no_spaces == known_name.lower().strip().replace(" ", ""):
                spdx_id = license_def["spdx_id"]
                try:
                    category = LicenseCategory(license_def["category"])
                except ValueError:
                    logger.warning(
                        "Invalid category '%s' for license %s in knowledge base, "
                        "treating as UNKNOWN",
                        license_def["category"],
                        spdx_id,
                    )
                    category = LicenseCategory.UNKNOWN
                return spdx_id, category, None

    # --- Pass 3: Exact match against ambiguous_names ---
    # Some license entries have an "ambiguous_names" list for strings that
    # could refer to multiple versions (e.g., "GNU General Public License"
    # could mean GPL-2.0 or GPL-3.0). We match these as a fallback and
    # attach a classification_note to warn the user about the ambiguity.
    for license_def in license_db:
        for ambiguous_name in license_def.get("ambiguous_names", []):
            if normalized == ambiguous_name.lower().strip():
                spdx_id = license_def["spdx_id"]
                try:
                    category = LicenseCategory(license_def["category"])
                except ValueError:
                    category = LicenseCategory.UNKNOWN
                note = (
                    f"Ambiguous license string '{raw}' was matched to {spdx_id}, "
                    f"but this string may be ambiguous. "
                    f"Verify the exact license in the package's LICENSE file."
                )
                return spdx_id, category, note

    # --- Pass 4: Space-collapsed match against ambiguous_names ---
    for license_def in license_db:
        for ambiguous_name in license_def.get("ambiguous_names", []):
            if normalized_no_spaces == ambiguous_name.lower().strip().replace(" ", ""):
                spdx_id = license_def["spdx_id"]
                try:
                    category = LicenseCategory(license_def["category"])
                except ValueError:
                    category = LicenseCategory.UNKNOWN
                note = (
                    f"Ambiguous license string '{raw}' was matched to {spdx_id}, "
                    f"but this string may be ambiguous. "
                    f"Verify the exact license in the package's LICENSE file."
                )
                return spdx_id, category, note

    # No match found
    return None, LicenseCategory.UNKNOWN, None


def _classify_dual_license(
    license_info: LicenseInfo,
    raw_license: str,
) -> LicenseInfo:
    """Handle dual-licensed packages (e.g., "MIT OR Apache-2.0").

    Splits on " OR ", classifies each side independently, and picks the
    most permissive result. This is the correct legal interpretation — when
    a package offers you a choice of licenses, you pick the one that works
    best for your situation.

    Args:
        license_info: The LicenseInfo object to update.
        raw_license: The raw dual-license string.

    Returns:
        The LicenseInfo with spdx_id and category set to the most permissive option.
    """
    parts = re.split(r"\s+[Oo][Rr]\s+", raw_license)

    best_spdx_id: Optional[str] = None
    best_category = LicenseCategory.UNKNOWN
    best_rank = _PERMISSIVENESS_RANK.get("unknown", 99)
    best_note: Optional[str] = None

    for part in parts:
        part = part.strip()
        if not part:
            continue

        spdx_id, category, note = _match_license_string(part)
        rank = _PERMISSIVENESS_RANK.get(category.value, 99)

        # Lower rank = more permissive = better
        if rank < best_rank:
            best_spdx_id = spdx_id
            best_category = category
            best_rank = rank
            best_note = note

    license_info.spdx_id = best_spdx_id
    license_info.category = best_category
    license_info.classification_note = best_note

    return license_info


def _classify_conjunctive_license(
    license_info: LicenseInfo,
    raw_license: str,
) -> LicenseInfo:
    """Handle conjunctive licenses (e.g., "PSF-2.0 AND BSD-3-Clause").

    SPDX AND means you must comply with ALL listed licenses. We classify
    each part, pick the most restrictive as the primary license (since
    compliance with the strictest license dominates), and store the rest
    in additional_spdx_ids / additional_categories.

    If any component is unknown, we still set the most restrictive known
    component as primary to preserve as much information as possible.

    Args:
        license_info: The LicenseInfo object to update.
        raw_license: The raw conjunctive license string.

    Returns:
        The LicenseInfo with primary set to the most restrictive component,
        and additional components stored in the additional_* fields.
    """
    parts = re.split(r"\s+[Aa][Nn][Dd]\s+", raw_license)

    # Classify each component
    classified_parts: list[tuple[Optional[str], LicenseCategory, Optional[str]]] = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        spdx_id, category, note = _match_license_string(part)
        classified_parts.append((spdx_id, category, note))

    if not classified_parts:
        license_info.category = LicenseCategory.UNKNOWN
        return license_info

    # Sort by restrictiveness: higher rank = MORE restrictive.
    # For AND, we want the most restrictive as primary.
    # Reverse the permissiveness rank: higher number = more restrictive.
    def restrictiveness(item: tuple[Optional[str], LicenseCategory, Optional[str]]) -> int:
        return _PERMISSIVENESS_RANK.get(item[1].value, 99)

    classified_parts.sort(key=restrictiveness, reverse=True)

    # Most restrictive becomes primary
    primary_spdx_id, primary_category, primary_note = classified_parts[0]
    license_info.spdx_id = primary_spdx_id
    license_info.category = primary_category
    license_info.classification_note = primary_note

    # Rest go into additional fields
    for spdx_id, category, _note in classified_parts[1:]:
        if spdx_id is not None:
            license_info.additional_spdx_ids.append(spdx_id)
            license_info.additional_categories.append(category)

    return license_info
