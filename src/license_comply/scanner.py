"""
Dependency file reader for license-comply.

This module is the first step in the pipeline: it reads a project's dependency
file (pyproject.toml or requirements.txt) and extracts the list of packages
that need to be checked for license compliance.

How it fits in the pipeline:
    scanner.py → resolver.py → classifier.py → analyzer.py → reporter.py

The scanner supports two dependency file formats:
  1. pyproject.toml — the modern standard for Python projects (PEP 621)
  2. requirements.txt — the older but still widely used format

Auto-detection order: pyproject.toml first, then requirements.txt. The user
can override this with the --file flag.
"""

from __future__ import annotations

import glob as glob_mod
import importlib.metadata
import logging
import os
import re
import sys
from typing import Optional

from license_comply.models import PackageInfo
from license_comply.utils import normalize_package_name

logger = logging.getLogger(__name__)

# Use tomllib (built into Python 3.11+) or fall back to the tomli backport
# for Python 3.9-3.10. They have the same API — tomli is just a standalone
# copy of the same code for older Python versions.
if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomli as tomllib  # type: ignore[no-redef]
    except ImportError:
        # This shouldn't happen if the package was installed correctly,
        # because tomli is listed as a dependency for Python < 3.11.
        tomllib = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def find_dependency_file(project_path: str, explicit_file: Optional[str] = None) -> str:
    """Find the dependency file to scan in a project directory.

    If an explicit file path is given (from the --file flag), use that.
    Otherwise, look for pyproject.toml first, then requirements.txt.

    Args:
        project_path: Path to the project directory to scan.
        explicit_file: Optional explicit path to a dependency file (from --file flag).

    Returns:
        The absolute path to the dependency file.

    Raises:
        FileNotFoundError: If no dependency file can be found.
    """
    # If the user specified a file explicitly, use it
    if explicit_file is not None:
        absolute_path = os.path.abspath(explicit_file)
        if not os.path.isfile(absolute_path):
            raise FileNotFoundError(
                f"Dependency file not found: {explicit_file}\n"
                f"  Hint: Check that the file path is correct."
            )
        return absolute_path

    # Auto-detect: try pyproject.toml first (modern standard), then requirements.txt
    absolute_project = os.path.abspath(project_path)

    pyproject_path = os.path.join(absolute_project, "pyproject.toml")
    if os.path.isfile(pyproject_path):
        return pyproject_path

    requirements_path = os.path.join(absolute_project, "requirements.txt")
    if os.path.isfile(requirements_path):
        return requirements_path

    raise FileNotFoundError(
        f"Could not find pyproject.toml or requirements.txt in {project_path}\n"
        f"  Hint: Make sure you're pointing to a Python project directory, or use\n"
        f"  --file to specify the path to your dependency file."
    )


def scan_dependencies(filepath: str) -> list[PackageInfo]:
    """Read a dependency file and extract the list of packages.

    This is the main entry point for the scanner. It detects the file format
    based on the filename and delegates to the appropriate parser.

    Args:
        filepath: Path to the dependency file (pyproject.toml or requirements.txt).

    Returns:
        A list of PackageInfo objects, one per dependency found.

    Raises:
        ValueError: If the file format is not supported or can't be parsed.
        FileNotFoundError: If the file doesn't exist.
    """
    if not os.path.isfile(filepath):
        raise FileNotFoundError(
            f"Dependency file not found: {filepath}\n  Hint: Check that the file path is correct."
        )

    filename = os.path.basename(filepath).lower()

    if filename == "pyproject.toml":
        return _parse_pyproject_toml(filepath)
    elif filename.endswith(".txt"):
        return _parse_requirements_txt(filepath)
    else:
        raise ValueError(
            f"Unsupported dependency file format: {filename}\n"
            f"  Hint: license-comply supports pyproject.toml and requirements.txt files."
        )


# ---------------------------------------------------------------------------
# pyproject.toml parser
# ---------------------------------------------------------------------------

# Regular expression to parse PEP 508 dependency strings.
# Examples of what this matches:
#   "requests"                → name="requests", extras=None, version=None
#   "requests>=2.28.0"        → name="requests", extras=None, version=">=2.28.0"
#   "requests[security]>=2.0" → name="requests", extras="security", version=">=2.0"
#   "tomli>=2.0; python_version < '3.11'" → name="tomli", version=">=2.0" (marker stripped)
#
# The pattern breakdown:
#   ^([A-Za-z0-9]...)  — Package name: letters, digits, hyphens, underscores, dots
#   (\[.*?\])?         — Optional extras in square brackets (e.g., [security])
#   \s*(.+?)?          — Optional version specifier (e.g., >=2.28.0,<3.0)
#   (?:;.*)?$          — Optional environment marker (e.g., ; python_version < '3.11')
_PEP508_PATTERN = re.compile(
    r"^([A-Za-z0-9]([A-Za-z0-9._-]*[A-Za-z0-9])?)"  # Package name
    r"(\[.*?\])?"  # Optional extras
    r"\s*(.*?)"  # Optional version spec
    r"(?:\s*;.*)?$"  # Optional environment marker
)


def _parse_pyproject_toml(filepath: str) -> list[PackageInfo]:
    """Parse dependencies from a pyproject.toml file.

    Reads the [project.dependencies] list and extracts package names
    and version specifiers from PEP 508 dependency strings.

    Args:
        filepath: Path to the pyproject.toml file.

    Returns:
        A list of PackageInfo objects.

    Raises:
        ValueError: If the file can't be parsed or has no dependencies section.
    """
    if tomllib is None:
        raise ValueError(
            "Cannot parse pyproject.toml: the 'tomli' package is not installed.\n"
            "  Hint: Run: pip install tomli"
        )

    try:
        with open(filepath, "rb") as file:
            data = tomllib.load(file)
    except Exception as error:
        raise ValueError(
            f"Could not parse pyproject.toml: {filepath}\n"
            f"  Error: {error}\n"
            f"  Hint: Check that the file is valid TOML."
        ) from error

    # Navigate to [project][dependencies]
    project_section = data.get("project", {})
    dependencies = project_section.get("dependencies", [])

    if not isinstance(dependencies, list):
        raise ValueError(
            f"Invalid dependencies format in {filepath}\n"
            f"  Expected [project.dependencies] to be a list of strings."
        )

    packages = []
    for dep_string in dependencies:
        package = _parse_pep508_string(dep_string)
        if package is not None:
            packages.append(package)

    return packages


def _parse_pep508_string(dep_string: str) -> Optional[PackageInfo]:
    """Parse a single PEP 508 dependency string into a PackageInfo.

    PEP 508 is the standard format for specifying Python dependencies.
    Examples: "requests>=2.28.0", "tomli>=2.0; python_version < '3.11'"

    Args:
        dep_string: A PEP 508 dependency string.

    Returns:
        A PackageInfo object, or None if the string can't be parsed.
    """
    dep_string = dep_string.strip()
    if not dep_string:
        return None

    match = _PEP508_PATTERN.match(dep_string)
    if match is None:
        logger.warning("Could not parse dependency string (skipped): %s", dep_string)
        return None

    name = match.group(1)
    version_spec = match.group(4).strip() if match.group(4) else None

    # If version_spec is empty string, treat as None (no version constraint)
    if not version_spec:
        version_spec = None

    return PackageInfo(name=name, version_spec=version_spec)


# ---------------------------------------------------------------------------
# requirements.txt parser
# ---------------------------------------------------------------------------

# Flags in requirements.txt that are NOT package names.
# We skip these lines entirely. Examples:
#   --index-url https://pypi.org/simple
#   --extra-index-url https://private.pypi.com
#   --trusted-host private.pypi.com
_REQUIREMENTS_FLAGS = frozenset(
    {
        "--index-url",
        "--extra-index-url",
        "--trusted-host",
        "--find-links",
        "--no-index",
        "--no-binary",
        "--only-binary",
        "--prefer-binary",
        "--require-hashes",
        "--pre",
        "--constraint",
        "-c",
    }
)


def _parse_requirements_txt(
    filepath: str,
    _seen_files: Optional[set[str]] = None,
) -> list[PackageInfo]:
    """Parse dependencies from a requirements.txt file.

    Handles:
      - Package names with version specifiers (requests>=2.0)
      - Comments (lines starting with #)
      - Blank lines
      - Recursive references (-r other-requirements.txt)
      - Extras syntax (package[extra])
      - Non-dependency flags (--index-url, etc.)

    The _seen_files parameter tracks already-processed files to prevent
    infinite loops if two requirements files reference each other.

    Args:
        filepath: Path to the requirements.txt file.
        _seen_files: Internal tracker for preventing circular -r references.

    Returns:
        A list of PackageInfo objects.
    """
    # Track seen files to prevent infinite circular -r references
    if _seen_files is None:
        _seen_files = set()

    # Use realpath() instead of abspath() to resolve symlinks — this ensures
    # circular -r references are detected even through symlinked files.
    absolute_path = os.path.realpath(filepath)

    # Guard against circular references (file A includes file B which includes file A)
    if absolute_path in _seen_files:
        return []
    _seen_files.add(absolute_path)

    try:
        with open(filepath, "r", encoding="utf-8") as file:
            lines = file.readlines()
    except OSError as error:
        raise FileNotFoundError(
            f"Could not read requirements file: {filepath}\n  Error: {error}"
        ) from error

    # The directory of the current file — used to resolve relative -r paths
    base_dir = os.path.dirname(absolute_path)

    packages = []
    for line in lines:
        # Strip whitespace and inline comments
        line = line.strip()

        # Skip blank lines and comment lines
        if not line or line.startswith("#"):
            continue

        # Handle URL-based requirements BEFORE stripping inline comments,
        # because URLs contain '#' for egg fragments (e.g., #egg=mypackage)
        if line.startswith(("http://", "https://", "git+", "svn+", "hg+")):
            package = _parse_url_requirement(line)
            if package is not None:
                packages.append(package)
            continue

        # Strip inline comments (e.g., "requests>=2.0  # HTTP library").
        # We check for ' #' (space then hash) first, and if that's not found,
        # we also check for '#' without a preceding space to catch lines like
        # "requests>=2.0# HTTP library" (malformed but encountered in the wild).
        if " #" in line:
            line = line[: line.index(" #")].strip()
        elif "#" in line:
            line = line[: line.index("#")].strip()

        # Handle -r / --requirement references (recursive includes)
        if line.startswith("-r ") or line.startswith("--requirement "):
            referenced_file = line.split(None, 1)[1].strip()
            referenced_path = os.path.join(base_dir, referenced_file)
            packages.extend(_parse_requirements_txt(referenced_path, _seen_files))
            continue

        # Skip non-dependency flags (--index-url, --trusted-host, etc.)
        first_token = line.split()[0] if line.split() else ""
        if first_token.startswith("-") and first_token in _REQUIREMENTS_FLAGS:
            continue
        # Also skip any other lines starting with - that look like flags
        if first_token.startswith("--"):
            continue

        # Parse the dependency line
        package = _parse_requirement_line(line)
        if package is not None:
            packages.append(package)

    return packages


# Regular expression for parsing requirements.txt lines.
# Simpler than PEP 508 because requirements.txt doesn't have environment markers.
# Examples:
#   "requests==2.31.0"         → name="requests", version="==2.31.0"
#   "requests>=2.0,<3.0"      → name="requests", version=">=2.0,<3.0"
#   "requests[security]>=2.0" → name="requests", version=">=2.0"
#   "requests"                 → name="requests", version=None
_REQUIREMENT_LINE_PATTERN = re.compile(
    r"^([A-Za-z0-9]([A-Za-z0-9._-]*[A-Za-z0-9])?)"  # Package name
    r"(\[.*?\])?"  # Optional extras
    r"\s*(.*)?$"  # Optional version spec
)


def _parse_requirement_line(line: str) -> Optional[PackageInfo]:
    """Parse a single line from a requirements.txt file.

    Args:
        line: A single non-comment, non-blank line from requirements.txt.

    Returns:
        A PackageInfo object, or None if the line can't be parsed.
    """
    line = line.strip()
    if not line:
        return None

    match = _REQUIREMENT_LINE_PATTERN.match(line)
    if match is None:
        logger.warning("Could not parse requirement line (skipped): %s", line)
        return None

    name = match.group(1)
    version_spec = match.group(4).strip() if match.group(4) else None

    if not version_spec:
        version_spec = None

    return PackageInfo(name=name, version_spec=version_spec)


def _parse_url_requirement(line: str) -> Optional[PackageInfo]:
    """Parse a URL-based requirement line from requirements.txt.

    URL-based requirements look like:
        git+https://github.com/user/repo.git#egg=mypackage
        https://example.com/package.tar.gz#egg=mypackage

    The package name is extracted from the #egg= fragment. If no #egg=
    fragment is present, the package is silently dropped with a warning
    since we can't determine its name.

    Args:
        line: A URL-based requirement line.

    Returns:
        A PackageInfo object if the egg fragment is present, otherwise None.
    """
    if "#egg=" in line:
        # Extract package name from the #egg= fragment
        egg_part = line.split("#egg=", 1)[1]
        # The egg name might have version specifiers or extras after it
        package_name = re.split(r"[&\s]", egg_part)[0].strip()
        if package_name:
            return PackageInfo(name=package_name)

    # No #egg= fragment — we can't determine the package name
    logger.warning(
        "URL requirement without #egg= fragment (skipped): %s",
        line,
    )
    return None


# ---------------------------------------------------------------------------
# Virtual environment scanning — deep/transitive dependency detection
# ---------------------------------------------------------------------------


def _find_venv_site_packages(project_path: str) -> Optional[str]:
    """Detect a virtual environment and return its site-packages path.

    Checks for a venv in this order:
      1. Currently activated venv (sys.prefix differs from sys.base_prefix)
      2. .venv directory in the project
      3. venv directory in the project

    Once a venv prefix is found, locates the site-packages directory inside
    it using glob patterns for macOS/Linux (lib/python*/site-packages) and
    a direct path for Windows (Lib/site-packages).

    Args:
        project_path: Path to the project directory.

    Returns:
        The absolute path to the site-packages directory, or None if no
        venv was found.
    """
    absolute_project = os.path.abspath(project_path)
    venv_prefix = None

    # Check 1: Is a venv currently activated?
    # When inside a venv, sys.prefix points to the venv directory and
    # sys.base_prefix points to the system Python — they differ.
    if sys.prefix != sys.base_prefix:
        venv_prefix = sys.prefix

    # Check 2: Look for .venv/pyvenv.cfg in the project directory
    if venv_prefix is None:
        dot_venv = os.path.join(absolute_project, ".venv")
        if os.path.isfile(os.path.join(dot_venv, "pyvenv.cfg")):
            venv_prefix = dot_venv

    # Check 3: Look for venv/pyvenv.cfg in the project directory
    if venv_prefix is None:
        plain_venv = os.path.join(absolute_project, "venv")
        if os.path.isfile(os.path.join(plain_venv, "pyvenv.cfg")):
            venv_prefix = plain_venv

    if venv_prefix is None:
        return None

    # Find the site-packages directory inside the venv.
    # On macOS/Linux: <prefix>/lib/pythonX.Y/site-packages
    # On Windows:     <prefix>/Lib/site-packages
    site_packages_glob = os.path.join(venv_prefix, "lib", "python*", "site-packages")
    matches = sorted(glob_mod.glob(site_packages_glob))
    if matches:
        if len(matches) > 1:
            logger.warning(
                "Multiple site-packages directories found in venv, using: %s",
                matches[-1],
            )
        # Use the last (highest Python version) match
        return matches[-1]

    # Try Windows layout
    windows_path = os.path.join(venv_prefix, "Lib", "site-packages")
    if os.path.isdir(windows_path):
        return windows_path

    return None


def _get_project_name(project_path: str) -> Optional[str]:
    """Read the project's own name from pyproject.toml.

    When a project is installed in editable mode (pip install -e .), it
    appears in the installed packages list. We need to exclude it from
    the dependency scan, so we read [project].name from pyproject.toml.

    Args:
        project_path: Path to the project directory.

    Returns:
        The normalized project name, or None if pyproject.toml doesn't
        exist or doesn't have a [project].name field.
    """
    pyproject_path = os.path.join(os.path.abspath(project_path), "pyproject.toml")
    if not os.path.isfile(pyproject_path):
        return None

    # Use the same tomllib import logic as the pyproject.toml parser above
    if tomllib is None:
        return None

    try:
        with open(pyproject_path, "rb") as file:
            data = tomllib.load(file)
        project_name = data.get("project", {}).get("name")
        if project_name:
            return normalize_package_name(project_name)
    except (OSError, KeyError, ValueError, AttributeError):
        # If we can't read pyproject.toml, just skip exclusion
        pass

    return None


def scan_installed_packages(project_path: str) -> list[PackageInfo]:
    """Scan all packages installed in the project's virtual environment.

    This enables "deep scanning" — checking transitive dependencies in
    addition to the direct dependencies listed in the dependency file.
    Every pip-installed package is returned, which includes both direct
    and transitive dependencies.

    The function excludes the project itself (if installed via pip install -e .)
    and deduplicates packages by normalized name.

    Args:
        project_path: Path to the project directory.

    Returns:
        A list of PackageInfo objects for every installed package, or an
        empty list if no virtual environment was found.
    """
    site_packages = _find_venv_site_packages(project_path)
    if site_packages is None:
        return []

    # Read the project's own name so we can exclude it from the list
    project_name = _get_project_name(project_path)

    # Use importlib.metadata.distributions() with an explicit path to scan
    # only the venv's site-packages, not system-wide packages
    seen_names: set[str] = set()
    packages: list[PackageInfo] = []

    for dist in importlib.metadata.distributions(path=[site_packages]):
        raw_name = dist.metadata.get("Name")
        if raw_name is None:
            continue

        normalized = normalize_package_name(raw_name)

        # Skip the project itself (installed via pip install -e .)
        if project_name and normalized == project_name:
            continue

        # Deduplicate by normalized name (some distributions appear twice)
        if normalized in seen_names:
            continue
        seen_names.add(normalized)

        # Use the original (un-normalized) name for display purposes
        packages.append(PackageInfo(name=raw_name))

    return packages
