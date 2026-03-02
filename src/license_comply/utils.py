"""
Shared utility functions for license-comply.

This module contains helper functions used by multiple other modules in the
project. Centralizing these here avoids duplication and gives us a single
place to maintain common logic.

The main utilities are:
  - YAML loading: Safely load and parse YAML files with friendly error handling.
  - Path resolution: Find bundled data files (knowledge base, templates) no
    matter where the package is installed.

Why a separate utils module? Several modules need to load YAML files
(classifier loads licenses.yaml, analyzer loads compatibility.yaml and
policy files). Rather than duplicating that logic, we put it here once
and let every module use it.
"""

from __future__ import annotations

import os
import re
from typing import Any

import yaml

# ---------------------------------------------------------------------------
# Path resolution — finding bundled files inside the installed package
# ---------------------------------------------------------------------------

# This is the absolute path to the directory containing THIS file (utils.py).
# Since utils.py lives at src/license_comply/utils.py, this points to the
# license_comply package directory. We use it as an anchor to find other
# files bundled with the package (knowledge/ and templates/ directories).
_PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))

# The knowledge base directory contains YAML files with legal data.
_KNOWLEDGE_DIR = os.path.join(_PACKAGE_DIR, "knowledge")

# The templates directory contains Jinja2 report templates.
_TEMPLATES_DIR = os.path.join(_PACKAGE_DIR, "templates")


def get_knowledge_path(filename: str) -> str:
    """Get the absolute path to a file in the knowledge base directory.

    The knowledge base files (licenses.yaml, compatibility.yaml, etc.) are
    bundled inside the installed package. This function resolves the correct
    path regardless of where the package is installed on the user's system.

    Args:
        filename: The name of the knowledge base file (e.g., "licenses.yaml").

    Returns:
        The absolute file path as a string.

    Raises:
        FileNotFoundError: If the file doesn't exist in the knowledge directory.
            This would indicate a broken installation or a typo in the filename.
    """
    filepath = os.path.join(_KNOWLEDGE_DIR, filename)

    if not os.path.isfile(filepath):
        raise FileNotFoundError(
            f"Knowledge base file not found: {filename}\n"
            f"  Expected location: {filepath}\n"
            f"  Hint: This may indicate a broken installation. "
            f"Try reinstalling with: pip install -e ."
        )

    return filepath


def get_template_path(filename: str) -> str:
    """Get the absolute path to a file in the templates directory.

    Templates are Jinja2 files used to generate reports in various formats
    (Markdown, HTML). Like knowledge base files, they're bundled with the
    installed package.

    Args:
        filename: The name of the template file (e.g., "report.md.jinja2").

    Returns:
        The absolute file path as a string.

    Raises:
        FileNotFoundError: If the file doesn't exist in the templates directory.
    """
    filepath = os.path.join(_TEMPLATES_DIR, filename)

    if not os.path.isfile(filepath):
        raise FileNotFoundError(
            f"Template file not found: {filename}\n"
            f"  Expected location: {filepath}\n"
            f"  Hint: This may indicate a broken installation. "
            f"Try reinstalling with: pip install -e ."
        )

    return filepath


# ---------------------------------------------------------------------------
# Package name normalization — PEP 503 canonical form
# ---------------------------------------------------------------------------


def normalize_package_name(name: str) -> str:
    """Normalize a Python package name to its canonical form per PEP 503.

    PyPI treats package names as case-insensitive and considers hyphens,
    underscores, and dots as equivalent. For example, these are all the
    same package: "charset-normalizer", "charset_normalizer", "Charset.Normalizer".

    This function converts any package name to a consistent canonical form
    so we can reliably compare names from different sources (dependency files
    vs installed packages).

    Args:
        name: A Python package name (e.g., "charset-normalizer").

    Returns:
        The normalized name (e.g., "charset_normalizer").
    """
    return re.sub(r"[-_.]+", "_", name).lower()


# ---------------------------------------------------------------------------
# YAML loading — safely parse YAML files with friendly error messages
# ---------------------------------------------------------------------------


def load_yaml(filepath: str) -> dict[str, Any]:
    """Load and parse a YAML file, with friendly error handling.

    This is the standard way to read YAML files throughout the project.
    It wraps Python's yaml.safe_load() with error handling that produces
    clear, actionable error messages instead of raw tracebacks.

    We use yaml.safe_load() (not yaml.load()) for security — safe_load
    only creates basic Python objects (dicts, lists, strings) and won't
    execute arbitrary code that might be embedded in a malicious YAML file.

    Args:
        filepath: The absolute path to the YAML file to load.

    Returns:
        The parsed YAML content as a Python dictionary.

    Raises:
        FileNotFoundError: If the file doesn't exist.
        ValueError: If the file contains invalid YAML syntax, or if the
            file is empty or doesn't parse to a dictionary.
    """
    # Step 1: Make sure the file exists
    if not os.path.isfile(filepath):
        raise FileNotFoundError(
            f"YAML file not found: {filepath}\n  Hint: Check that the file path is correct."
        )

    # Step 2: Read and parse the file
    try:
        with open(filepath, "r", encoding="utf-8") as file:
            data = yaml.safe_load(file)
    except yaml.YAMLError as error:
        # YAML syntax errors (bad indentation, missing quotes, etc.)
        raise ValueError(
            f"Invalid YAML syntax in: {filepath}\n"
            f"  Error details: {error}\n"
            f"  Hint: Check the file for indentation errors or missing quotes."
        ) from error

    # Step 3: Validate that we got something useful
    if data is None:
        raise ValueError(
            f"YAML file is empty: {filepath}\n  Hint: The file exists but contains no data."
        )

    if not isinstance(data, dict):
        raise ValueError(
            f"YAML file has unexpected format: {filepath}\n"
            f"  Expected a dictionary (key-value pairs) at the top level, "
            f"but got {type(data).__name__}."
        )

    return data


def load_knowledge(filename: str) -> dict[str, Any]:
    """Load a knowledge base YAML file by name.

    This is a convenience function that combines get_knowledge_path() and
    load_yaml() into a single call. It's the most common way to access
    the knowledge base throughout the codebase.

    Example:
        licenses_data = load_knowledge("licenses.yaml")
        all_licenses = licenses_data["licenses"]

    Args:
        filename: The name of the knowledge base file (e.g., "licenses.yaml").

    Returns:
        The parsed YAML content as a Python dictionary.

    Raises:
        FileNotFoundError: If the file doesn't exist.
        ValueError: If the file contains invalid YAML.
    """
    filepath = get_knowledge_path(filename)
    return load_yaml(filepath)
