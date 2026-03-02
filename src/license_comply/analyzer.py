"""
Compatibility analyzer for license-comply.

This module is the legal brain of the tool. It takes classified license info
for each package and determines whether each license is compatible with the
user's project type, based on the compatibility rules and organizational policy.

How it fits in the pipeline:
    scanner.py → resolver.py → classifier.py → analyzer.py → reporter.py

The analysis follows this priority order for each package:
  1. Policy allow list → always clean
  2. Policy deny list → always critical
  3. Policy review list → always warning
  4. Special rules (specific license + project type combos, e.g., AGPL in SaaS)
  5. Category-level compatibility rules (the general case)

After analyzing all packages, the module also builds an "obligation rollup" —
a consolidated view of what the user needs to do, grouped by obligation
rather than by package.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from license_comply import __version__
from license_comply.models import (
    Finding,
    LicenseInfo,
    ObligationSummary,
    ProjectType,
    RiskLevel,
    ScanResult,
)
from license_comply.utils import load_knowledge, load_yaml

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def analyze(
    license_infos: list[LicenseInfo],
    project_type: ProjectType,
    project_path: str,
    policy_path: Optional[str] = None,
    project_license: Optional[str] = None,
) -> ScanResult:
    """Analyze license compatibility and generate findings.

    This is the main entry point for the analyzer. It loads the compatibility
    rules and policy, evaluates each package, generates findings, and builds
    the obligation rollup.

    Args:
        license_infos: Classified license info for each package.
        project_type: How the user's project will be used.
        project_path: Path to the project being scanned.
        policy_path: Optional path to a custom policy YAML file.
            If None, uses the built-in default policy.
        project_license: Optional SPDX ID of the project's own license
            (e.g., "GPL-3.0-only"). Used for license-to-license conflict
            detection. If None, conflict checks are skipped.

    Returns:
        A complete ScanResult with findings and obligation rollup.
    """
    # Load the compatibility rules and policy
    compatibility = load_knowledge("compatibility.yaml")
    rules = compatibility["rules"]
    special_rules = compatibility.get("special_rules", [])
    license_conflicts = compatibility.get("license_conflicts", [])

    policy = _load_policy(policy_path)

    # The project type value as it appears in the YAML (e.g., "proprietary", "saas")
    project_type_key = project_type.value

    # Build a conflict lookup: dependency_spdx_id → (conflicts_with, reason)
    # Only used when project_license is provided.
    conflict_lookup: dict[str, dict] = {}
    if project_license:
        for conflict_rule in license_conflicts:
            conflict_lookup[conflict_rule["spdx_id"]] = conflict_rule

    # Validate --project-license against project type for clear contradictions
    if project_license:
        _validate_project_license(project_license, project_type)

    # Analyze each package
    findings: list[Finding] = []
    for license_info in license_infos:
        finding = _analyze_single(
            license_info=license_info,
            project_type=project_type,
            project_type_key=project_type_key,
            rules=rules,
            special_rules=special_rules,
            policy=policy,
            project_license=project_license,
            conflict_lookup=conflict_lookup,
        )
        findings.append(finding)

    # Build the obligation rollup
    obligation_rollup = _build_obligation_rollup(license_infos)

    # Assemble the final result
    return ScanResult(
        project_path=project_path,
        project_type=project_type,
        total_packages=len(license_infos),
        project_license=project_license,
        findings=findings,
        obligation_rollup=obligation_rollup,
        scan_timestamp=datetime.now(timezone.utc).isoformat(),
        tool_version=__version__,
    )


# ---------------------------------------------------------------------------
# Single-package analysis
# ---------------------------------------------------------------------------

# Human-readable titles for each risk level
_RISK_TITLES: dict[str, str] = {
    "clean": "License Compatible",
    "notice": "License Notice",
    "warning": "License Review Needed",
    "critical": "License Incompatibility",
}

# Human-readable explanations by category and risk level.
# These are templates — the actual explanation is built by combining
# the license summary from the knowledge base with context-specific text.
_CATEGORY_EXPLANATIONS: dict[str, str] = {
    "permissive": (
        "This is a permissive license with minimal restrictions. "
        "You can use this package freely in your project."
    ),
    "public_domain": (
        "This package is in the public domain or uses a public domain equivalent license. "
        "There are no restrictions on use."
    ),
    "weak_copyleft": (
        "This is a weak copyleft license. The copyleft obligation applies to the "
        "library itself, not your entire project. If you use it without modification "
        "and link dynamically (the standard way Python imports packages), you are "
        "generally safe. However, if you modify the library, those modifications "
        "must be shared under the same license."
    ),
    "strong_copyleft": (
        "This is a strong copyleft license. Distributing software that "
        "incorporates this code typically requires making the entire project's "
        "source code available under the same license terms. This is often called "
        'the "viral" or "copyleft" effect.'
    ),
    "non_software": (
        "This license was designed for creative works (text, images, data), not "
        "software. Using it for code is unusual and may create legal ambiguity."
    ),
    "proprietary": (
        "This package uses a proprietary or source-available license. These licenses "
        "may restrict commercial use, managed service offerings, or impose other "
        "conditions that differ significantly from open-source licenses."
    ),
    "unknown": (
        "No license could be identified for this package. Under copyright law, "
        "code without an explicit license is 'All Rights Reserved' by default, "
        "meaning there may be no legal right to use, modify, or distribute it."
    ),
}

# Recommendations based on risk level and category
_RECOMMENDATIONS: dict[str, dict[str, str]] = {
    "clean": {
        "default": (
            "No action typically required. Ensure you comply with any attribution requirements."
        ),
    },
    "notice": {
        "default": "Review the license obligations and ensure your project complies.",
        "strong_copyleft": (
            "For internal or SaaS use, this license generally does not require "
            "source disclosure (copyleft triggers on distribution). However, verify "
            "your deployment model does not trigger distribution obligations."
        ),
    },
    "warning": {
        "default": "Review this dependency with your legal team before shipping.",
        "weak_copyleft": (
            "Review how you use this library. If you have not modified the library's "
            "source code and Python imports it dynamically (the default), you are "
            "likely fine. If you have modified it, those changes must be shared."
        ),
        "unknown": (
            "Investigate the license for this package. Check the package's repository "
            "for a LICENSE file. If no license exists, contact the author or replace "
            "the dependency."
        ),
        "non_software": (
            "This license was not designed for software. Review whether its terms "
            "are compatible with your intended use."
        ),
    },
    "critical": {
        "default": "This dependency may need to be replaced or removed before shipping.",
        "strong_copyleft": (
            "Replace this dependency with a permissively-licensed alternative, "
            "or obtain a separate commercial license from the author if available."
        ),
        "unknown": (
            "Contact the package author to clarify the license, or replace this "
            "dependency with an alternative that has a clear, compatible license."
        ),
    },
}

# Remediation step templates organized by risk level and license category.
#
# Each entry is a list of tuples: (template_string, required_context_key).
# - template_string: A Python format string that can reference context keys
#   like {package_name}, {pypi_url}, {source_url}, {spdx_id}.
# - required_context_key: If set (not None), the step is ONLY included when
#   that key has a non-empty value in the context dict. This lets us skip
#   URL-based steps when no URL is available, avoiding broken instructions.
#
# The lookup order is: risk_level → category → list of step tuples.
# If no category-specific entry exists, the "default" entry is used.
_REMEDIATION_STEPS: dict[str, dict[str, list[tuple[str, Optional[str]]]]] = {
    "critical": {
        "strong_copyleft": [
            (
                "Search PyPI for alternative packages that provide similar "
                "functionality under a permissive license (MIT, BSD, Apache-2.0).",
                None,
            ),
            (
                "Check whether the author offers a commercial license at {source_url}",
                "source_url",
            ),
            (
                "Consult your legal team about whether isolating this dependency "
                "(e.g., as a separate service or process) could avoid copyleft obligations.",
                None,
            ),
        ],
        "unknown": [
            (
                "Check the package repository for a LICENSE or COPYING file at {source_url}",
                "source_url",
            ),
            (
                "Check the PyPI page for license metadata at {pypi_url}",
                "pypi_url",
            ),
            (
                "If no license is found, contact the maintainer of {package_name} "
                "to request that they add one.",
                None,
            ),
            (
                "If the license remains unclear, replace {package_name} with "
                "an alternative that has a clear, compatible license.",
                None,
            ),
        ],
        "proprietary": [
            (
                "Review the proprietary license terms for {package_name} to understand "
                "usage restrictions.",
                None,
            ),
            (
                "Contact the vendor to discuss licensing options at {source_url}",
                "source_url",
            ),
            (
                "Search for an open-source alternative with a permissive license.",
                None,
            ),
        ],
        "default": [
            (
                "Review the full license terms for {package_name} ({spdx_id}).",
                None,
            ),
            (
                "Consult your legal team about compatibility with your project type.",
                None,
            ),
            (
                "Search PyPI for an alternative package with a permissive license.",
                None,
            ),
        ],
    },
    "warning": {
        "weak_copyleft": [
            (
                "Verify you are using {package_name} via standard Python imports "
                "(dynamic linking) — this is the default and generally avoids "
                "copyleft obligations.",
                None,
            ),
            (
                "Check whether you have modified {package_name}'s source code. "
                "If so, those modifications must be shared under the same license.",
                None,
            ),
            (
                "Document your usage pattern (unmodified, dynamically linked) "
                "for compliance records.",
                None,
            ),
        ],
        "unknown": [
            (
                "Check the package repository for a LICENSE or COPYING file at {source_url}",
                "source_url",
            ),
            (
                "Check the PyPI page for license metadata at {pypi_url}",
                "pypi_url",
            ),
            (
                "If no license is found, contact the maintainer of {package_name} "
                "to request that they add one.",
                None,
            ),
        ],
        "non_software": [
            (
                "Verify that {package_name} actually contains software code, not just "
                "creative content (text, images, data).",
                None,
            ),
            (
                "Review the ShareAlike terms to understand how they apply to your project.",
                None,
            ),
            (
                "Consider replacing {package_name} with a package that uses a "
                "software-specific license.",
                None,
            ),
        ],
        "default": [
            (
                "Review the full license terms at {pypi_url}",
                "pypi_url",
            ),
            (
                "Discuss the usage of {package_name} ({spdx_id}) with your legal team.",
                None,
            ),
        ],
    },
    "notice": {
        "strong_copyleft": [
            (
                "Verify that your deployment model (internal use or SaaS) does not "
                "trigger distribution obligations under {spdx_id}.",
                None,
            ),
            (
                "Document that {package_name} is used internally or as a service, "
                "not distributed to end users.",
                None,
            ),
        ],
        "default": [
            (
                "Ensure copyright notices and license text for {package_name} are "
                "included in your distribution (e.g., in a NOTICES file or about page).",
                None,
            ),
        ],
    },
    "clean": {
        "default": [],
    },
}


def _build_remediation_steps(
    risk_level: RiskLevel,
    category_value: str,
    license_info: LicenseInfo,
) -> list[str]:
    """Build a list of actionable remediation steps for a finding.

    Uses the step templates from _REMEDIATION_STEPS, filtered by whether
    the required context (like URLs) is actually available. Steps are
    formatted with dynamic values from the license info.

    Args:
        risk_level: The determined risk level for this finding.
        category_value: The license category as a string (e.g., "strong_copyleft").
        license_info: The package's license info, used to fill in template values.

    Returns:
        A list of formatted step strings. Empty for clean findings.
    """
    risk_key = risk_level.value

    # Build the context dict with values from LicenseInfo that templates can reference
    context = {
        "package_name": license_info.package_name,
        "pypi_url": license_info.pypi_url or "",
        "source_url": license_info.source_url or "",
        "spdx_id": license_info.spdx_id or "Unknown",
    }

    # Look up step templates: try category-specific first, then fall back to default
    risk_templates = _REMEDIATION_STEPS.get(risk_key, {})
    step_tuples = risk_templates.get(category_value, risk_templates.get("default", []))

    # Filter and format each step
    steps: list[str] = []
    for template_str, required_key in step_tuples:
        # If a required context key is specified, skip this step when that value is empty
        if required_key and not context.get(required_key):
            continue
        steps.append(template_str.format_map(context))

    return steps


def _analyze_single(
    license_info: LicenseInfo,
    project_type: ProjectType,
    project_type_key: str,
    rules: dict,
    special_rules: list[dict],
    policy: dict,
    project_license: Optional[str] = None,
    conflict_lookup: Optional[dict] = None,
) -> Finding:
    """Analyze a single package's license compatibility.

    Applies the policy and compatibility rules to determine the risk level
    and generate a human-readable finding.

    Args:
        license_info: The classified license info for this package.
        project_type: The user's project type.
        project_type_key: The project type as a YAML key string.
        rules: The category-level compatibility rules.
        special_rules: The special rules for specific license+project combos.
        policy: The loaded policy dictionary.
        project_license: Optional SPDX ID of the project's own license.
        conflict_lookup: Optional dict of license conflict rules, keyed by
            dependency SPDX ID. Only populated when project_license is set.

    Returns:
        A Finding object with risk level, explanation, and recommendation.
    """
    spdx_id = license_info.spdx_id
    category_value = license_info.category.value
    policy_data = policy.get("policy", {})

    # --- Priority 1: Policy allow list ---
    allow_list = policy_data.get("allow", [])
    if spdx_id and spdx_id in allow_list:
        return _build_finding(
            license_info=license_info,
            risk_level=RiskLevel.CLEAN,
            category_value=category_value,
            policy_note="Allowed by organizational policy",
        )

    # --- Priority 2: Policy deny list ---
    deny_list = policy_data.get("deny", [])
    if spdx_id and spdx_id in deny_list:
        return _build_finding(
            license_info=license_info,
            risk_level=RiskLevel.CRITICAL,
            category_value=category_value,
            policy_note="Blocked by organizational policy",
        )

    # --- Priority 3: Policy review list ---
    review_list = policy_data.get("review", [])
    if spdx_id and spdx_id in review_list:
        return _build_finding(
            license_info=license_info,
            risk_level=RiskLevel.WARNING,
            category_value=category_value,
            policy_note="Flagged for review by organizational policy",
        )

    # --- Priority 4: Special rules (specific license + project type) ---
    for special_rule in special_rules:
        if (
            special_rule.get("spdx_id") == spdx_id
            and special_rule.get("project_type") == project_type_key
        ):
            risk_level = RiskLevel(special_rule["risk_level"])
            return _build_finding(
                license_info=license_info,
                risk_level=risk_level,
                category_value=category_value,
                extra_context=special_rule.get("reason", ""),
            )

    # --- Priority 4.5: License-to-license conflict detection ---
    # This checks whether the dependency's specific license conflicts with
    # the project's own license (e.g., GPL-2.0-only vs GPL-3.0-only).
    # Only runs when --project-license is provided.
    if project_license and spdx_id and conflict_lookup:
        conflict_rule = conflict_lookup.get(spdx_id)
        if conflict_rule and project_license in conflict_rule.get("conflicts_with", []):
            return _build_finding(
                license_info=license_info,
                risk_level=RiskLevel.CRITICAL,
                category_value=category_value,
                extra_context=conflict_rule.get("reason", ""),
                policy_note=f"License conflict with project license ({project_license})",
            )

    # --- Priority 5: Category-level compatibility rules ---
    project_rules = rules.get(project_type_key, {})

    # For unknown licenses, check the policy's unknown_license_action
    if category_value == "unknown":
        unknown_action = policy_data.get("unknown_license_action", "critical")
        risk_level = RiskLevel(unknown_action)
    else:
        risk_level_str = project_rules.get(category_value, "warning")
        risk_level = RiskLevel(risk_level_str)

    # --- Priority 5.5: Copyleft compatibility notice ---
    # When a copyleft project uses a strong copyleft dependency and no
    # --project-license is specified, we can't verify that the licenses
    # are actually compatible (e.g., GPL-2.0-only vs GPL-3.0-only are
    # both strong_copyleft but incompatible). Upgrade CLEAN to NOTICE
    # to suggest using --project-license for precise conflict detection.
    if (
        project_type == ProjectType.OPEN_SOURCE_COPYLEFT
        and category_value == "strong_copyleft"
        and risk_level == RiskLevel.CLEAN
        and project_license is None
    ):
        risk_level = RiskLevel.NOTICE
        return _build_finding(
            license_info=license_info,
            risk_level=risk_level,
            category_value=category_value,
            extra_context=(
                "This dependency uses a strong copyleft license, which is generally "
                "compatible with copyleft projects. However, different copyleft licenses "
                "may be incompatible with each other (e.g., GPL-2.0-only and GPL-3.0-only "
                "cannot be combined). Use --project-license to enable precise conflict "
                "detection between your project's license and this dependency."
            ),
        )

    return _build_finding(
        license_info=license_info,
        risk_level=risk_level,
        category_value=category_value,
    )


def _build_finding(
    license_info: LicenseInfo,
    risk_level: RiskLevel,
    category_value: str,
    policy_note: Optional[str] = None,
    extra_context: str = "",
) -> Finding:
    """Build a Finding object with appropriate title, explanation, and recommendation.

    Args:
        license_info: The package's license info.
        risk_level: The determined risk level.
        category_value: The license category as a string.
        policy_note: Optional note about which policy rule was triggered.
        extra_context: Optional extra context to append to the explanation.

    Returns:
        A complete Finding object.
    """
    risk_key = risk_level.value
    title = _RISK_TITLES.get(risk_key, "License Review Needed")

    # Build explanation
    explanation = _CATEGORY_EXPLANATIONS.get(category_value, "")
    if extra_context:
        explanation = f"{explanation} {extra_context}".strip()

    # Append classification note if the classifier flagged an ambiguous match
    if license_info.classification_note:
        explanation = f"{explanation} Note: {license_info.classification_note}".strip()

    # Build recommendation
    risk_recommendations = _RECOMMENDATIONS.get(risk_key, {})
    recommendation = risk_recommendations.get(
        category_value, risk_recommendations.get("default", "Review this dependency.")
    )

    # Build remediation steps — actionable next steps the user can follow
    remediation_steps = _build_remediation_steps(risk_level, category_value, license_info)

    return Finding(
        package_name=license_info.package_name,
        license_info=license_info,
        risk_level=risk_level,
        title=title,
        explanation=explanation,
        recommendation=recommendation,
        policy_violated=policy_note,
        remediation_steps=remediation_steps,
    )


# ---------------------------------------------------------------------------
# Policy loading
# ---------------------------------------------------------------------------


def _load_policy(policy_path: Optional[str]) -> dict:
    """Load the organizational policy from a file or use the default.

    Args:
        policy_path: Path to a custom policy YAML file, or None for default.

    Returns:
        The parsed policy as a dictionary.
    """
    if policy_path is not None:
        policy = load_yaml(policy_path)
    else:
        policy = load_knowledge("default_policy.yaml")

    _validate_policy_spdx_ids(policy)
    return policy


def _validate_policy_spdx_ids(policy: dict) -> None:
    """Check all SPDX IDs in the policy against the knowledge base.

    Logs a warning for any SPDX ID that doesn't match a known license.
    This catches typos like "Appache-2.0" or "GPL-3.0" (missing -only/-or-later).

    Args:
        policy: The loaded policy dictionary.
    """
    licenses_data = load_knowledge("licenses.yaml")
    known_spdx_ids = {entry["spdx_id"] for entry in licenses_data["licenses"]}

    policy_data = policy.get("policy", {})
    for list_name in ("allow", "deny", "review"):
        for spdx_id in policy_data.get(list_name, []):
            if spdx_id not in known_spdx_ids:
                logger.warning(
                    "Policy %s list contains unrecognized SPDX ID: '%s' "
                    "(possible typo — not found in licenses.yaml)",
                    list_name,
                    spdx_id,
                )


# ---------------------------------------------------------------------------
# Project license validation
# ---------------------------------------------------------------------------

# SPDX IDs categorized for --project-license validation.
# Only clear-cut cases: permissive licenses and strong copyleft licenses.
# We intentionally exclude weak copyleft, non-software, and proprietary
# licenses because their interaction with project types is nuanced.
_PERMISSIVE_SPDX_IDS = {
    "MIT",
    "Apache-2.0",
    "BSD-2-Clause",
    "BSD-3-Clause",
    "ISC",
    "MIT-0",
    "0BSD",
    "BSL-1.0",
    "PSF-2.0",
    "Python-2.0",
    "HPND",
    "PostgreSQL",
    "Unlicense",
    "CC0-1.0",
    "WTFPL",
    "Zlib",
    "Unicode-DFS-2016",
    "Artistic-2.0",
}

_COPYLEFT_SPDX_IDS = {
    "GPL-2.0-only",
    "GPL-2.0-or-later",
    "GPL-3.0-only",
    "GPL-3.0-or-later",
    "AGPL-3.0-only",
    "AGPL-3.0-or-later",
    "EUPL-1.2",
}


def _validate_project_license(
    project_license: str,
    project_type: ProjectType,
) -> None:
    """Log a warning if --project-license contradicts the project type.

    Only warns on clear contradictions:
      - Permissive license + copyleft project type
      - Copyleft license + permissive project type

    Other combinations (e.g., GPL + SaaS) are unusual but valid, so we
    don't warn about them.

    Args:
        project_license: The SPDX ID of the project's own license.
        project_type: How the user's project will be used.
    """
    is_permissive = project_license in _PERMISSIVE_SPDX_IDS
    is_copyleft = project_license in _COPYLEFT_SPDX_IDS

    if is_permissive and project_type == ProjectType.OPEN_SOURCE_COPYLEFT:
        logger.warning(
            "Project license '%s' is permissive, but project type is 'open-source-copyleft'. "
            "Did you mean --project-type open-source-permissive?",
            project_license,
        )
    elif is_copyleft and project_type == ProjectType.OPEN_SOURCE_PERMISSIVE:
        logger.warning(
            "Project license '%s' is copyleft, but project type is 'open-source-permissive'. "
            "Did you mean --project-type open-source-copyleft?",
            project_license,
        )


# ---------------------------------------------------------------------------
# Obligation rollup
# ---------------------------------------------------------------------------


def _build_obligation_rollup(license_infos: list[LicenseInfo]) -> list[ObligationSummary]:
    """Build the obligation rollup — group obligations across all packages.

    Instead of showing obligations per-package, we group them so the user sees:
      "Include copyright notice" — required by: requests (MIT), flask (BSD-3-Clause)

    This is much more useful for legal teams than reading individual findings.

    Args:
        license_infos: All classified license info objects.

    Returns:
        A list of ObligationSummary objects, one per unique obligation.
    """
    # Load the license definitions to get obligations
    licenses_data = load_knowledge("licenses.yaml")
    license_db = {entry["spdx_id"]: entry for entry in licenses_data["licenses"]}

    # Group: obligation text → {category, packages_and_licenses}
    # Each obligation entry in the YAML is an object with "text" and "category"
    # fields (e.g., {text: "Include copyright notice", category: "notice"}).
    obligation_map: dict[str, dict] = {}

    for info in license_infos:
        if info.spdx_id is None:
            continue

        # Collect obligations from the primary license
        spdx_ids_to_check = [info.spdx_id]

        # Also collect obligations from any additional AND components.
        # For conjunctive (AND) licenses, you must comply with ALL
        # components, so all their obligations apply.
        spdx_ids_to_check.extend(info.additional_spdx_ids)

        for spdx_id in spdx_ids_to_check:
            license_def = license_db.get(spdx_id)
            if license_def is None:
                continue

            for obligation_entry in license_def.get("obligations", []):
                # Each entry is a dict with "text" and "category" keys.
                # Use .get() to avoid KeyError if a YAML entry is malformed
                # (missing the "text" key). Skip entries with empty text.
                obligation_text = obligation_entry.get("text", "")
                if not obligation_text:
                    continue
                obligation_category = obligation_entry.get("category", "")

                if obligation_text not in obligation_map:
                    obligation_map[obligation_text] = {
                        "category": obligation_category,
                        "packages_and_licenses": [],
                    }
                obligation_map[obligation_text]["packages_and_licenses"].append(
                    (info.package_name, spdx_id)
                )

    # Convert to ObligationSummary objects
    rollup: list[ObligationSummary] = []
    for obligation_text, data in sorted(obligation_map.items()):
        packages = [p[0] for p in data["packages_and_licenses"]]
        license_ids = [p[1] for p in data["packages_and_licenses"]]
        rollup.append(
            ObligationSummary(
                obligation=obligation_text,
                category=data["category"],
                packages=packages,
                license_ids=license_ids,
            )
        )

    return rollup
