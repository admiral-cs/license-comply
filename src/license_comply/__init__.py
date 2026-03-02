"""
license-comply: Open-source license compliance analysis.

This package scans Python project dependencies, identifies their open-source
licenses, analyzes legal risks based on the project type, and generates clear
compliance reports. It optionally uses AI to generate plain-English legal
executive summaries.

Usage:
    # As a CLI command (after installation):
    license-comply ./my-project --project-type proprietary

    # As a Python module:
    python -m license_comply ./my-project --project-type proprietary
"""

# The version number lives here so it's the single source of truth.
# Other parts of the codebase (like cli.py) import it from here.
__version__ = "1.0.0"
