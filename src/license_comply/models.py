"""
Data models used throughout license-comply.

These classes define the structure of data as it flows through the tool:
PackageInfo → LicenseInfo → Finding → ScanResult

Think of these as the "nouns" of the application — they describe the things
the tool works with. Every other module (scanner, resolver, classifier,
analyzer, reporter) produces or consumes these data structures.

We use Python's built-in `dataclass` decorator, which automatically generates
__init__, __repr__, and __eq__ methods from the field definitions. This means
less boilerplate code and clearer intent — you declare the fields, and Python
handles the plumbing.

We also use `Enum` (enumeration) for values that can only be one of a fixed
set of choices. For example, RiskLevel can only be CLEAN, NOTICE, WARNING,
or CRITICAL. Using an Enum instead of plain strings prevents bugs from typos
— Python will catch `RiskLevel.CRITCAL` as an error, but it wouldn't catch
the string "critcal".
"""

# This import makes Python treat type hints as strings, which lets us use
# modern syntax like `list[str]` on Python 3.9. Without it, we'd need to
# write `List[str]` (from the `typing` module) for 3.9 compatibility.
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

# ---------------------------------------------------------------------------
# Enums — Fixed sets of choices
# ---------------------------------------------------------------------------


class RiskLevel(Enum):
    """How risky a license finding is. Used to color-code and prioritize results.

    The risk levels form a hierarchy from least to most severe:
      CLEAN    → No issues at all
      NOTICE   → FYI — something to be aware of (e.g., attribution required)
      WARNING  → Needs attention (e.g., weak copyleft in a proprietary project)
      CRITICAL → Must be resolved before shipping (e.g., GPL in proprietary code)
    """

    CLEAN = "clean"
    NOTICE = "notice"
    WARNING = "warning"
    CRITICAL = "critical"


class LicenseCategory(Enum):
    """Broad legal categories for open-source licenses.

    Every known license is classified into one of these categories. The category
    determines the baseline risk level when combined with a project type.

    Categories (from most to least permissive):
      PERMISSIVE      → MIT, BSD, Apache — do nearly anything you want
      PUBLIC_DOMAIN   → CC0, Unlicense, 0BSD — no restrictions at all
      WEAK_COPYLEFT   → LGPL, MPL, EPL — copyleft applies to the library, not your whole project
      STRONG_COPYLEFT → GPL, AGPL — copyleft applies to your entire project if distributed
      NON_SOFTWARE    → CC-BY, CC-BY-SA — designed for creative works, not code
      PROPRIETARY     → Not open source
      UNKNOWN         → Could not determine the license
    """

    PERMISSIVE = "permissive"
    WEAK_COPYLEFT = "weak_copyleft"
    STRONG_COPYLEFT = "strong_copyleft"
    PROPRIETARY = "proprietary"
    PUBLIC_DOMAIN = "public_domain"
    NON_SOFTWARE = "non_software"
    UNKNOWN = "unknown"


class ProjectType(Enum):
    """How the user's project will be used. This fundamentally changes the legal analysis.

    The same license can be perfectly fine for one project type and a critical
    issue for another. For example:
      - GPL in a proprietary project → CRITICAL (copyleft contamination)
      - GPL in a GPL-licensed project → CLEAN (same license family)
      - GPL in an internal tool → NOTICE (copyleft only triggers on distribution)
    """

    PROPRIETARY = "proprietary"
    INTERNAL = "internal"
    OPEN_SOURCE_PERMISSIVE = "open-source-permissive"
    OPEN_SOURCE_COPYLEFT = "open-source-copyleft"
    SAAS = "saas"


# ---------------------------------------------------------------------------
# Data classes — Structured data containers
# ---------------------------------------------------------------------------


@dataclass
class PackageInfo:
    """A single Python package extracted from a dependency file.

    This is the first data structure created in the pipeline. The scanner
    reads a requirements.txt or pyproject.toml and produces a list of these.

    Attributes:
        name: The package name (e.g., "requests", "flask").
        version_spec: The version specifier, if any (e.g., ">=2.0,<3.0").
            None if the dependency is unpinned (no version specified).
    """

    name: str
    version_spec: Optional[str] = None


@dataclass
class LicenseInfo:
    """License information retrieved from PyPI for a single package.

    The resolver queries PyPI's API and fills in this structure. The classifier
    then sets the `spdx_id` and `category` fields by matching the raw license
    string against the knowledge base.

    Attributes:
        package_name: The package this license info belongs to.
        declared_license: The raw license string from PyPI (e.g., "MIT License").
            This is whatever the package author typed — it may be non-standard.
        spdx_id: The standardized SPDX identifier (e.g., "MIT", "GPL-3.0-only").
            Set by the classifier after matching. None if no match found.
        category: The legal category (permissive, copyleft, etc.).
            Set by the classifier. Defaults to UNKNOWN until classified.
        pypi_url: Link to the package on PyPI (e.g., "https://pypi.org/project/requests/").
        source_url: Link to the source repository (e.g., GitHub URL), if available.
        additional_spdx_ids: For conjunctive (AND) licenses, the SPDX IDs of
            the other license components. The primary (most restrictive) license
            is stored in `spdx_id`; the rest go here. Empty for single licenses.
        additional_categories: For conjunctive (AND) licenses, the categories of
            the other license components. Parallel to `additional_spdx_ids`.
        is_transitive: Whether this package is a transitive (indirect) dependency.
            False means it was explicitly listed in the project's dependency file.
            True means it was pulled in by another dependency. Set during deep
            scanning when a virtual environment is available.
        classification_note: An optional warning message set by the classifier when
            the license match was ambiguous. For example, a raw string like
            "GNU General Public License" could mean GPL-2.0 or GPL-3.0 — the
            classifier defaults to GPL-2.0-only but sets this note to warn
            the user about the ambiguity. None when the match is unambiguous.
    """

    package_name: str
    declared_license: Optional[str] = None
    spdx_id: Optional[str] = None
    category: LicenseCategory = LicenseCategory.UNKNOWN
    pypi_url: Optional[str] = None
    source_url: Optional[str] = None
    additional_spdx_ids: list[str] = field(default_factory=list)
    additional_categories: list[LicenseCategory] = field(default_factory=list)
    is_transitive: bool = False
    classification_note: Optional[str] = None


@dataclass
class Finding:
    """A single compliance finding — one issue (or clean bill) for one package.

    The analyzer produces one Finding per package. Each Finding includes:
    - The risk level (how bad is it?)
    - A human-readable title (what's the issue?)
    - A plain-English legal explanation (why does it matter?)
    - A concrete recommendation (what should the user do?)

    Attributes:
        package_name: Which package this finding is about.
        license_info: The full license information for this package.
        risk_level: How severe the issue is (CLEAN, NOTICE, WARNING, CRITICAL).
        title: Short description (e.g., "Copyleft Contamination Risk").
        explanation: Plain-English legal explanation of why this matters.
        recommendation: What the user should do about it.
        policy_violated: Which policy rule was triggered, if any
            (e.g., "deny list" or "review required"). None if the finding
            came from the compatibility rules rather than a policy.
        remediation_steps: Ordered list of actionable steps the user should
            take to investigate and resolve this finding. Empty for clean
            findings (no action needed). Steps may include dynamic context
            like PyPI URLs when available.
    """

    package_name: str
    license_info: LicenseInfo
    risk_level: RiskLevel
    title: str
    explanation: str
    recommendation: str
    policy_violated: Optional[str] = None
    remediation_steps: list[str] = field(default_factory=list)


@dataclass
class ObligationSummary:
    """A single obligation shared by one or more packages.

    Used for the "obligation rollup" feature — a consolidated view of what
    actions the user needs to take, grouped by obligation rather than by
    package. This is the killer feature for legal teams: instead of reading
    23 individual findings, they see a grouped summary like:

        "Include copyright notice"
          Required by: requests (MIT), flask (BSD-3-Clause), click (BSD-3-Clause)

        "Distribute modifications under LGPL"
          Required by: chardet (LGPL-3.0-only)

    Attributes:
        obligation: The obligation text (e.g., "Include copyright notice").
        category: The obligation category (e.g., "notice", "source_sharing").
            Used to group obligations by type in the HTML report.
        packages: Names of packages that require this obligation.
        license_ids: SPDX IDs of the licenses requiring this obligation.
            Parallel to `packages` — license_ids[i] is the license for packages[i].
    """

    obligation: str
    category: str = ""
    packages: list[str] = field(default_factory=list)
    license_ids: list[str] = field(default_factory=list)


@dataclass
class ScanResult:
    """The complete result of scanning and analyzing a project.

    This is the "final product" that gets passed to the reporter for output.
    It bundles together everything: the findings, the obligation rollup,
    and optional AI summary.

    Attributes:
        project_path: Path to the project that was scanned.
        project_type: How the project is used (proprietary, internal, etc.).
        project_license: The project's own license (SPDX ID), if provided
            via --project-license. Used for license-to-license conflict
            detection (e.g., GPL-2.0-only vs GPL-3.0-only).
        total_packages: Total number of packages that were scanned.
        direct_count: Number of direct dependencies (from the dependency file).
        transitive_count: Number of transitive (indirect) dependencies found
            via deep scanning. Zero when deep scanning is not active.
        findings: List of compliance findings, one per package.
        obligation_rollup: Consolidated list of obligations grouped across
            all packages. Generated by the analyzer after creating findings.
        scan_timestamp: When the scan was run, in ISO 8601 format
            (e.g., "2026-02-24T15:30:00").
        tool_version: The version of license-comply that produced this result.
        ai_summary: AI-generated executive summary text, if the user
            requested it with --summary. None otherwise.
    """

    project_path: str
    project_type: ProjectType
    total_packages: int
    direct_count: int = 0
    transitive_count: int = 0
    project_license: Optional[str] = None
    findings: list[Finding] = field(default_factory=list)
    obligation_rollup: list[ObligationSummary] = field(default_factory=list)
    scan_timestamp: str = ""
    tool_version: str = ""
    ai_summary: Optional[str] = None
