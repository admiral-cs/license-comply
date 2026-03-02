"""
Tests for the analyzer module (compatibility analysis).

These tests verify that the analyzer correctly applies compatibility rules
and organizational policy to determine risk levels for each package. This
is the most important module to test thoroughly — if the analysis is wrong,
the entire tool produces misleading results.

Key behaviors tested:
  - Category-level compatibility rules (GPL in proprietary = critical, etc.)
  - Policy overrides (allow list, deny list, review list)
  - Special rules (AGPL in SaaS)
  - Obligation rollup grouping
  - Finding generation with explanations and recommendations
"""

from __future__ import annotations

from typing import Optional

from license_comply.analyzer import analyze
from license_comply.models import (
    LicenseCategory,
    LicenseInfo,
    ProjectType,
    RiskLevel,
)

# ---------------------------------------------------------------------------
# Helper: create a LicenseInfo with specific fields set
# ---------------------------------------------------------------------------


def _make_info(
    name: str,
    spdx_id: Optional[str] = None,
    category: LicenseCategory = LicenseCategory.UNKNOWN,
) -> LicenseInfo:
    """Create a LicenseInfo for testing with the given classification."""
    return LicenseInfo(
        package_name=name,
        declared_license=spdx_id or "Unknown",
        spdx_id=spdx_id,
        category=category,
    )


# ===========================================================================
# Category-level compatibility tests
# ===========================================================================


class TestCompatibilityRules:
    """Tests for the category-level compatibility rules."""

    def test_gpl3_flagged_critical_in_proprietary_project(self) -> None:
        """GPL-3.0 in a proprietary project should be critical (strong copyleft).

        The compatibility matrix says strong_copyleft + proprietary = critical.
        This is correct — distributing proprietary software that incorporates
        GPL code violates the GPL. The policy no longer overrides this.
        """
        infos = [_make_info("flask-admin", "GPL-3.0-only", LicenseCategory.STRONG_COPYLEFT)]
        result = analyze(infos, ProjectType.PROPRIETARY, "/test")

        assert result.findings[0].risk_level == RiskLevel.CRITICAL
        # Should come from compatibility matrix, not a policy override
        assert result.findings[0].policy_violated is None

    def test_mit_passes_in_all_project_types(self) -> None:
        """MIT should be clean in every project type (it's in the allow list)."""
        for project_type in ProjectType:
            infos = [_make_info("requests", "MIT", LicenseCategory.PERMISSIVE)]
            result = analyze(infos, project_type, "/test")
            assert result.findings[0].risk_level == RiskLevel.CLEAN, (
                f"MIT should be clean for {project_type.value}, "
                f"got {result.findings[0].risk_level.value}"
            )

    def test_gpl3_notice_in_copyleft_project_no_project_license(self) -> None:
        """GPL-3.0 in a copyleft project without --project-license should be notice.

        The compatibility matrix says strong_copyleft + open-source-copyleft = clean,
        but without --project-license the analyzer upgrades to NOTICE because it
        can't verify that the specific copyleft licenses are compatible.
        """
        infos = [_make_info("some-pkg", "GPL-3.0-only", LicenseCategory.STRONG_COPYLEFT)]
        result = analyze(infos, ProjectType.OPEN_SOURCE_COPYLEFT, "/test")

        assert result.findings[0].risk_level == RiskLevel.NOTICE
        assert result.findings[0].policy_violated is None

    def test_unknown_license_flagged_critical_by_default(self) -> None:
        """An unknown license should be critical by default (safest assumption)."""
        infos = [_make_info("mystery-pkg", None, LicenseCategory.UNKNOWN)]
        result = analyze(infos, ProjectType.PROPRIETARY, "/test")

        assert result.findings[0].risk_level == RiskLevel.CRITICAL

    def test_lgpl_flagged_warning_in_proprietary_project(self) -> None:
        """LGPL in a proprietary project should be a warning (weak copyleft).

        The compatibility matrix says weak_copyleft + proprietary = warning.
        This is the same result as before, but now it comes from the matrix
        rather than the policy's review list.
        """
        infos = [_make_info("chardet", "LGPL-3.0-only", LicenseCategory.WEAK_COPYLEFT)]
        result = analyze(infos, ProjectType.PROPRIETARY, "/test")

        assert result.findings[0].risk_level == RiskLevel.WARNING
        # Should come from compatibility matrix, not a policy override
        assert result.findings[0].policy_violated is None

    def test_permissive_licenses_clean_in_internal_project(self) -> None:
        """Permissive licenses should be clean for internal projects."""
        infos = [_make_info("requests", "MIT", LicenseCategory.PERMISSIVE)]
        result = analyze(infos, ProjectType.INTERNAL, "/test")

        assert result.findings[0].risk_level == RiskLevel.CLEAN

    def test_gpl3_notice_in_copyleft_project_without_project_license(self) -> None:
        """GPL-3.0 in a copyleft project without --project-license should be notice.

        The compatibility matrix says strong_copyleft + copyleft = clean, but
        when --project-license is not specified, we can't verify exact license
        compatibility (e.g., GPL-2.0-only vs GPL-3.0-only are incompatible).
        The analyzer upgrades CLEAN to NOTICE to suggest using --project-license.
        """
        infos = [_make_info("gpl-pkg", "GPL-3.0-only", LicenseCategory.STRONG_COPYLEFT)]
        result = analyze(infos, ProjectType.OPEN_SOURCE_COPYLEFT, "/test")

        assert result.findings[0].risk_level == RiskLevel.NOTICE
        assert result.findings[0].policy_violated is None

    def test_agpl_notice_in_copyleft_project_without_project_license(self) -> None:
        """AGPL-3.0 in a copyleft project without --project-license should be notice.

        AGPL is strong copyleft, and the compatibility matrix says
        strong_copyleft + open-source-copyleft = clean. But without
        --project-license, the analyzer upgrades to NOTICE to suggest
        enabling precise conflict detection.
        """
        infos = [_make_info("agpl-pkg", "AGPL-3.0-only", LicenseCategory.STRONG_COPYLEFT)]
        result = analyze(infos, ProjectType.OPEN_SOURCE_COPYLEFT, "/test")

        assert result.findings[0].risk_level == RiskLevel.NOTICE
        assert result.findings[0].policy_violated is None

    def test_gpl_notice_in_internal_project(self) -> None:
        """GPL in an internal project should be notice level.

        Internal projects are not distributed, so copyleft obligations
        don't trigger. The compatibility matrix returns 'notice' for
        strong_copyleft + internal.
        """
        infos = [_make_info("gpl-pkg", "GPL-3.0-only", LicenseCategory.STRONG_COPYLEFT)]
        result = analyze(infos, ProjectType.INTERNAL, "/test")

        assert result.findings[0].risk_level == RiskLevel.NOTICE
        assert result.findings[0].policy_violated is None


# ===========================================================================
# Special rules tests
# ===========================================================================


class TestSpecialRules:
    """Tests for special rules that override category-level defaults."""

    def test_agpl_flagged_critical_in_saas_project(self) -> None:
        """AGPL in a SaaS project should be critical (network clause).

        This now comes from the special rules in compatibility.yaml (AGPL +
        SaaS = critical) rather than the policy deny list. The special rule
        exists because AGPL's network-use clause specifically targets SaaS.
        """
        infos = [_make_info("agpl-pkg", "AGPL-3.0-only", LicenseCategory.STRONG_COPYLEFT)]
        result = analyze(infos, ProjectType.SAAS, "/test")

        assert result.findings[0].risk_level == RiskLevel.CRITICAL
        # Should come from special rules, not a policy override
        assert result.findings[0].policy_violated is None


# ===========================================================================
# Policy override tests
# ===========================================================================


class TestPolicyOverrides:
    """Tests for organizational policy overrides."""

    def test_policy_allow_list_overrides_category_rules(self) -> None:
        """A license in the allow list should always be clean."""
        # Apache-2.0 is in the default allow list
        infos = [_make_info("some-pkg", "Apache-2.0", LicenseCategory.PERMISSIVE)]
        result = analyze(infos, ProjectType.PROPRIETARY, "/test")

        assert result.findings[0].risk_level == RiskLevel.CLEAN
        assert result.findings[0].policy_violated == "Allowed by organizational policy"

    def test_policy_deny_list_overrides_category_rules(self) -> None:
        """A license in the deny list should always be critical.

        SSPL-1.0 is in the default deny list. Even if it were somehow
        compatible by category, the policy deny list overrides that.
        """
        infos = [_make_info("sspl-pkg", "SSPL-1.0", LicenseCategory.PROPRIETARY)]
        result = analyze(infos, ProjectType.OPEN_SOURCE_COPYLEFT, "/test")

        assert result.findings[0].risk_level == RiskLevel.CRITICAL
        assert result.findings[0].policy_violated == "Blocked by organizational policy"

    def test_policy_review_list_generates_warning(self) -> None:
        """A license in the review list should be flagged as warning.

        CC-BY-SA-4.0 is in the default review list. It's a non-software
        license with share-alike (copyleft) terms, so the policy flags
        it for manual review regardless of project type.
        """
        infos = [_make_info("cc-pkg", "CC-BY-SA-4.0", LicenseCategory.NON_SOFTWARE)]
        result = analyze(infos, ProjectType.INTERNAL, "/test")

        assert result.findings[0].risk_level == RiskLevel.WARNING
        assert "review" in result.findings[0].policy_violated.lower()


# ===========================================================================
# Obligation rollup tests
# ===========================================================================


class TestObligationRollup:
    """Tests for the obligation rollup feature."""

    def test_obligation_rollup_groups_by_obligation(self) -> None:
        """Obligations shared by multiple packages should be grouped together."""
        infos = [
            _make_info("requests", "MIT", LicenseCategory.PERMISSIVE),
            _make_info("flask", "BSD-3-Clause", LicenseCategory.PERMISSIVE),
        ]
        result = analyze(infos, ProjectType.PROPRIETARY, "/test")

        # Both MIT and BSD-3-Clause require including copyright notices,
        # so there should be a grouped obligation for that
        obligations = result.obligation_rollup
        assert len(obligations) > 0

        # Find an obligation that has both packages
        copyright_obligations = [o for o in obligations if "copyright" in o.obligation.lower()]
        assert len(copyright_obligations) > 0

    def test_obligation_rollup_includes_package_names(self) -> None:
        """Each obligation should list which packages require it."""
        infos = [_make_info("requests", "MIT", LicenseCategory.PERMISSIVE)]
        result = analyze(infos, ProjectType.PROPRIETARY, "/test")

        for obligation in result.obligation_rollup:
            assert len(obligation.packages) > 0
            assert len(obligation.license_ids) > 0

    def test_unknown_packages_excluded_from_rollup(self) -> None:
        """Packages with unknown licenses should not appear in the rollup."""
        infos = [_make_info("mystery", None, LicenseCategory.UNKNOWN)]
        result = analyze(infos, ProjectType.PROPRIETARY, "/test")

        assert len(result.obligation_rollup) == 0

    def test_obligation_rollup_includes_and_components(self) -> None:
        """Obligations from all AND components should be included in the rollup.

        For conjunctive (AND) licenses, you must comply with ALL components.
        So the rollup should include obligations from both the primary and
        additional licenses.
        """
        # Create a LicenseInfo with AND components: GPL-3.0-only AND MIT
        info = LicenseInfo(
            package_name="dual-pkg",
            declared_license="GPL-3.0-only AND MIT",
            spdx_id="GPL-3.0-only",
            category=LicenseCategory.STRONG_COPYLEFT,
            additional_spdx_ids=["MIT"],
            additional_categories=[LicenseCategory.PERMISSIVE],
        )
        result = analyze([info], ProjectType.OPEN_SOURCE_COPYLEFT, "/test")

        # Should include obligations from both GPL-3.0-only and MIT
        all_license_ids = []
        for obligation in result.obligation_rollup:
            all_license_ids.extend(obligation.license_ids)

        assert "GPL-3.0-only" in all_license_ids, "Missing GPL-3.0-only obligations"
        assert "MIT" in all_license_ids, "Missing MIT obligations from AND component"


# ===========================================================================
# ScanResult metadata tests
# ===========================================================================


class TestScanResultMetadata:
    """Tests for the metadata on the ScanResult."""

    def test_scan_result_has_correct_total_packages(self) -> None:
        """The total_packages count should match the input."""
        infos = [
            _make_info("pkg-a", "MIT", LicenseCategory.PERMISSIVE),
            _make_info("pkg-b", "Apache-2.0", LicenseCategory.PERMISSIVE),
        ]
        result = analyze(infos, ProjectType.PROPRIETARY, "/test")

        assert result.total_packages == 2

    def test_scan_result_has_timestamp(self) -> None:
        """The scan result should have a non-empty timestamp."""
        infos = [_make_info("pkg", "MIT", LicenseCategory.PERMISSIVE)]
        result = analyze(infos, ProjectType.PROPRIETARY, "/test")

        assert result.scan_timestamp != ""

    def test_scan_result_has_tool_version(self) -> None:
        """The scan result should include the tool version."""
        infos = [_make_info("pkg", "MIT", LicenseCategory.PERMISSIVE)]
        result = analyze(infos, ProjectType.PROPRIETARY, "/test")

        assert result.tool_version == "1.0.1"

    def test_findings_have_explanations(self) -> None:
        """Every finding should have a non-empty explanation and recommendation."""
        infos = [
            _make_info("clean-pkg", "MIT", LicenseCategory.PERMISSIVE),
            _make_info("risky-pkg", "GPL-3.0-only", LicenseCategory.STRONG_COPYLEFT),
        ]
        result = analyze(infos, ProjectType.PROPRIETARY, "/test")

        for finding in result.findings:
            assert finding.explanation != "", f"Missing explanation for {finding.package_name}"
            assert finding.recommendation != "", (
                f"Missing recommendation for {finding.package_name}"
            )


# ===========================================================================
# Empty findings tests
# ===========================================================================


class TestEmptyFindings:
    """Tests for analyzing an empty list of packages."""

    def test_empty_findings_list_produces_empty_result(self) -> None:
        """Analyzing zero packages should return a ScanResult with no findings.

        This is an edge case that can happen if a project has no dependencies
        (e.g., an empty requirements.txt). The analyzer should handle it
        gracefully rather than crashing.
        """
        result = analyze([], ProjectType.PROPRIETARY, "/test")

        assert result.total_packages == 0
        assert result.findings == []


# ===========================================================================
# Stress test — many packages at once
# ===========================================================================


class TestStressTest:
    """Tests for analyzing a larger number of packages at once."""

    def test_25_packages_analyzed_correctly(self) -> None:
        """The analyzer should handle 25 packages without errors.

        This creates a realistic mix: 20 MIT (permissive), 3 GPL-3.0
        (strong copyleft), and 2 unknown. We verify the total count and
        that findings are generated for every single package.
        """
        # Build a list of 25 LicenseInfo objects with a realistic mix
        infos = []

        # 20 MIT packages (permissive)
        for i in range(20):
            infos.append(_make_info(f"mit-pkg-{i}", "MIT", LicenseCategory.PERMISSIVE))

        # 3 GPL-3.0 packages (strong copyleft)
        for i in range(3):
            infos.append(
                _make_info(f"gpl-pkg-{i}", "GPL-3.0-only", LicenseCategory.STRONG_COPYLEFT)
            )

        # 2 unknown packages
        for i in range(2):
            infos.append(_make_info(f"unknown-pkg-{i}", None, LicenseCategory.UNKNOWN))

        result = analyze(infos, ProjectType.PROPRIETARY, "/test")

        # Total packages should match
        assert result.total_packages == 25

        # Every package should have a finding
        assert len(result.findings) == 25

        # Count findings by risk level to verify the mix is analyzed correctly
        clean_count = sum(1 for f in result.findings if f.risk_level == RiskLevel.CLEAN)
        warning_count = sum(1 for f in result.findings if f.risk_level == RiskLevel.WARNING)
        critical_count = sum(1 for f in result.findings if f.risk_level == RiskLevel.CRITICAL)

        # MIT is in the allow list → 20 clean
        assert clean_count == 20
        # No warnings in this mix (GPL is now critical in proprietary)
        assert warning_count == 0
        # GPL-3.0 (strong copyleft) + proprietary = critical → 3
        # Unknown licenses default to critical → 2
        # Total: 5 critical
        assert critical_count == 5


# ===========================================================================
# New license category tests
# ===========================================================================


class TestNewLicenseCategories:
    """Tests for specific licenses added in the expanded knowledge base.

    These verify that the default policy's allow/deny/review lists correctly
    handle SSPL, Boost, and CDDL licenses.
    """

    def test_sspl_denied_by_default_policy(self) -> None:
        """SSPL-1.0 should be critical because it's in the deny list.

        SSPL is a proprietary/source-available license created by MongoDB.
        The default policy blocks it because its terms are incompatible
        with most commercial and open-source workflows.
        """
        infos = [_make_info("mongo-pkg", "SSPL-1.0", LicenseCategory.PROPRIETARY)]
        result = analyze(infos, ProjectType.PROPRIETARY, "/test")

        assert result.findings[0].risk_level == RiskLevel.CRITICAL
        assert result.findings[0].policy_violated == "Blocked by organizational policy"

    def test_boost_allowed_by_default_policy(self) -> None:
        """BSL-1.0 (Boost Software License) should be clean because it's in the allow list.

        The Boost license is extremely permissive — even simpler than MIT.
        The default policy allows it unconditionally.
        """
        infos = [_make_info("boost-pkg", "BSL-1.0", LicenseCategory.PERMISSIVE)]
        result = analyze(infos, ProjectType.PROPRIETARY, "/test")

        assert result.findings[0].risk_level == RiskLevel.CLEAN
        assert result.findings[0].policy_violated == "Allowed by organizational policy"

    def test_cddl_flagged_warning_in_proprietary_via_matrix(self) -> None:
        """CDDL-1.0 in a proprietary project should be warning via compatibility matrix.

        CDDL is a weak copyleft license (file-level copyleft, like MPL).
        The compatibility matrix says weak_copyleft + proprietary = warning.
        It's no longer in the policy review list — the matrix handles it.
        """
        infos = [_make_info("cddl-pkg", "CDDL-1.0", LicenseCategory.WEAK_COPYLEFT)]
        result = analyze(infos, ProjectType.PROPRIETARY, "/test")

        assert result.findings[0].risk_level == RiskLevel.WARNING
        # Should come from compatibility matrix, not a policy override
        assert result.findings[0].policy_violated is None


# ===========================================================================
# License conflict detection tests
# ===========================================================================


class TestLicenseConflicts:
    """Tests for license-to-license conflict detection.

    These verify that specific license incompatibilities are detected when
    --project-license is provided. The category-level matrix can't see
    these conflicts — it needs to know the exact license.
    """

    def test_gpl2_conflicts_with_gpl3_project(self) -> None:
        """GPL-2.0-only dependency in a GPL-3.0-only project should be critical.

        GPL-2.0-only and GPL-3.0-only are incompatible. The "only" suffix
        means exactly that version — GPL-2.0-only code cannot be relicensed
        under GPL-3.0.
        """
        infos = [_make_info("gpl2-pkg", "GPL-2.0-only", LicenseCategory.STRONG_COPYLEFT)]
        result = analyze(
            infos,
            ProjectType.OPEN_SOURCE_COPYLEFT,
            "/test",
            project_license="GPL-3.0-only",
        )

        assert result.findings[0].risk_level == RiskLevel.CRITICAL
        assert "conflict" in result.findings[0].policy_violated.lower()

    def test_cddl_conflicts_with_gpl3_project(self) -> None:
        """CDDL-1.0 dependency in a GPL-3.0-only project should be critical.

        CDDL and GPL have conflicting copyleft requirements — each requires
        derivative works to be licensed under itself.
        """
        infos = [_make_info("cddl-pkg", "CDDL-1.0", LicenseCategory.WEAK_COPYLEFT)]
        result = analyze(
            infos,
            ProjectType.OPEN_SOURCE_COPYLEFT,
            "/test",
            project_license="GPL-3.0-only",
        )

        assert result.findings[0].risk_level == RiskLevel.CRITICAL
        assert "conflict" in result.findings[0].policy_violated.lower()

    def test_gpl2_or_later_no_conflict_with_gpl3(self) -> None:
        """GPL-2.0-or-later should NOT conflict with GPL-3.0-only.

        The "or-later" suffix means the licensee can choose to comply under
        GPL-3.0, so there's no incompatibility. Only "GPL-2.0-only" conflicts.
        """
        infos = [_make_info("gpl2plus-pkg", "GPL-2.0-or-later", LicenseCategory.STRONG_COPYLEFT)]
        result = analyze(
            infos,
            ProjectType.OPEN_SOURCE_COPYLEFT,
            "/test",
            project_license="GPL-3.0-only",
        )

        # Should be clean (strong_copyleft + copyleft = clean, no conflict)
        assert result.findings[0].risk_level == RiskLevel.CLEAN
        assert result.findings[0].policy_violated is None

    def test_no_conflict_without_project_license(self) -> None:
        """Conflict detection should be skipped when --project-license is not set.

        Without knowing the project's license, we can't check for conflicts.
        The normal compatibility matrix applies, but the copyleft compatibility
        notice (Priority 5.5) upgrades CLEAN to NOTICE since no --project-license
        is specified to verify exact compatibility.
        """
        infos = [_make_info("gpl2-pkg", "GPL-2.0-only", LicenseCategory.STRONG_COPYLEFT)]
        result = analyze(
            infos,
            ProjectType.OPEN_SOURCE_COPYLEFT,
            "/test",
            # No project_license — should skip conflict check
        )

        # Should be notice (copyleft compatibility notice applies)
        assert result.findings[0].risk_level == RiskLevel.NOTICE
        assert result.findings[0].policy_violated is None

    def test_project_license_stored_in_scan_result(self) -> None:
        """The project_license should be stored in the ScanResult."""
        infos = [_make_info("pkg", "MIT", LicenseCategory.PERMISSIVE)]
        result = analyze(
            infos,
            ProjectType.OPEN_SOURCE_COPYLEFT,
            "/test",
            project_license="GPL-3.0-only",
        )

        assert result.project_license == "GPL-3.0-only"


# ===========================================================================
# Remediation steps tests
# ===========================================================================


class TestRemediationSteps:
    """Tests for the remediation steps feature.

    Remediation steps are actionable next steps attached to each finding.
    They tell users exactly what to do to investigate and resolve an issue.
    Steps are generated from templates and filtered based on available
    context (e.g., URLs are only included when they exist).
    """

    def test_critical_copyleft_has_remediation_steps(self) -> None:
        """GPL in a proprietary project should produce at least 2 steps.

        Strong copyleft in a proprietary project is one of the most serious
        findings. The steps should guide the user toward finding alternatives
        or consulting legal counsel.
        """
        infos = [_make_info("gpl-pkg", "GPL-3.0-only", LicenseCategory.STRONG_COPYLEFT)]
        result = analyze(infos, ProjectType.PROPRIETARY, "/test")

        steps = result.findings[0].remediation_steps
        assert len(steps) >= 2, f"Expected at least 2 steps, got {len(steps)}"

    def test_critical_unknown_has_remediation_steps(self) -> None:
        """Unknown license should produce steps about checking for a LICENSE file.

        When a package has no identifiable license, the steps should guide the
        user to investigate the source repository and contact the maintainer.
        """
        infos = [_make_info("mystery-pkg", None, LicenseCategory.UNKNOWN)]
        result = analyze(infos, ProjectType.PROPRIETARY, "/test")

        steps = result.findings[0].remediation_steps
        assert len(steps) >= 2
        # At least one step should mention contacting the maintainer or replacing
        assert any("maintainer" in s.lower() or "replace" in s.lower() for s in steps)

    def test_warning_weak_copyleft_has_remediation_steps(self) -> None:
        """LGPL in a proprietary project should mention dynamic linking.

        Weak copyleft licenses like LGPL are generally safe if the library is
        used without modification via standard Python imports (dynamic linking).
        The steps should guide the user to verify this.
        """
        infos = [_make_info("chardet", "LGPL-3.0-only", LicenseCategory.WEAK_COPYLEFT)]
        result = analyze(infos, ProjectType.PROPRIETARY, "/test")

        steps = result.findings[0].remediation_steps
        assert len(steps) >= 2
        # Should mention dynamic linking / standard imports
        assert any("dynamic" in s.lower() or "import" in s.lower() for s in steps)

    def test_clean_has_no_remediation_steps(self) -> None:
        """MIT in a proprietary project should have zero remediation steps.

        Clean findings mean everything is fine — no action needed, so the
        remediation_steps list should be empty.
        """
        infos = [_make_info("requests", "MIT", LicenseCategory.PERMISSIVE)]
        result = analyze(infos, ProjectType.PROPRIETARY, "/test")

        assert result.findings[0].remediation_steps == []

    def test_steps_include_source_url_when_available(self) -> None:
        """When source_url is available, it should appear in the steps.

        Steps that reference {source_url} should be included and properly
        formatted when the LicenseInfo has a source URL.
        """
        info = LicenseInfo(
            package_name="gpl-pkg",
            declared_license="GPL-3.0-only",
            spdx_id="GPL-3.0-only",
            category=LicenseCategory.STRONG_COPYLEFT,
            source_url="https://github.com/example/gpl-pkg",
        )
        result = analyze([info], ProjectType.PROPRIETARY, "/test")

        steps = result.findings[0].remediation_steps
        # At least one step should contain the source URL
        assert any("https://github.com/example/gpl-pkg" in s for s in steps)

    def test_steps_skip_url_when_missing(self) -> None:
        """When source_url is missing, URL-dependent steps should be skipped.

        Steps with a required_context_key of "source_url" should NOT appear
        if the LicenseInfo has no source URL. This prevents instructions
        like "Check the repository at " with a blank URL.
        """
        info = LicenseInfo(
            package_name="gpl-pkg",
            declared_license="GPL-3.0-only",
            spdx_id="GPL-3.0-only",
            category=LicenseCategory.STRONG_COPYLEFT,
            source_url=None,
        )
        result = analyze([info], ProjectType.PROPRIETARY, "/test")

        steps = result.findings[0].remediation_steps
        # No step should reference a source URL pattern
        for step in steps:
            assert "source_url" not in step, f"Unformatted template found: {step}"
            # Should not end with an empty URL reference
            assert not step.rstrip().endswith("at"), f"Step ends with dangling 'at': {step}"

    def test_steps_include_pypi_url_when_available(self) -> None:
        """When pypi_url is available, it should appear in relevant steps.

        Steps that reference {pypi_url} should be included when the
        LicenseInfo has a PyPI URL.
        """
        info = LicenseInfo(
            package_name="mystery-pkg",
            declared_license="Unknown",
            spdx_id=None,
            category=LicenseCategory.UNKNOWN,
            pypi_url="https://pypi.org/project/mystery-pkg/",
        )
        result = analyze([info], ProjectType.PROPRIETARY, "/test")

        steps = result.findings[0].remediation_steps
        # At least one step should contain the PyPI URL
        assert any("https://pypi.org/project/mystery-pkg/" in s for s in steps)

    def test_notice_has_lightweight_steps(self) -> None:
        """GPL in an internal project should have 1-2 lightweight steps.

        Internal projects don't distribute code, so copyleft doesn't fully
        trigger. The steps should be about verifying deployment model and
        documenting usage, not about replacing the dependency.
        """
        infos = [_make_info("gpl-pkg", "GPL-3.0-only", LicenseCategory.STRONG_COPYLEFT)]
        result = analyze(infos, ProjectType.INTERNAL, "/test")

        steps = result.findings[0].remediation_steps
        assert 1 <= len(steps) <= 2, f"Expected 1-2 steps, got {len(steps)}"


# ===========================================================================
# CC-BY-NC special rule tests
# ===========================================================================


class TestCcByNcSpecialRules:
    """Tests for CC-BY-NC licenses which have special rules in compatibility.yaml.

    The non-commercial restriction makes these CRITICAL for proprietary and
    SaaS projects, even though the default non_software category would only
    give a warning.
    """

    def test_cc_by_nc_critical_in_proprietary(self) -> None:
        """CC-BY-NC-4.0 in a proprietary project should be critical.

        The special rule overrides the default non_software → warning,
        because the non-commercial restriction directly prohibits
        commercial use.
        """
        infos = [_make_info("nc-data", "CC-BY-NC-4.0", LicenseCategory.NON_SOFTWARE)]
        result = analyze(infos, ProjectType.PROPRIETARY, "/test")

        assert result.findings[0].risk_level == RiskLevel.CRITICAL

    def test_cc_by_nc_critical_in_saas(self) -> None:
        """CC-BY-NC-4.0 in a SaaS project should be critical."""
        infos = [_make_info("nc-data", "CC-BY-NC-4.0", LicenseCategory.NON_SOFTWARE)]
        result = analyze(infos, ProjectType.SAAS, "/test")

        assert result.findings[0].risk_level == RiskLevel.CRITICAL

    def test_cc_by_nc_sa_critical_in_proprietary(self) -> None:
        """CC-BY-NC-SA-4.0 in a proprietary project should be critical."""
        infos = [_make_info("nc-sa-data", "CC-BY-NC-SA-4.0", LicenseCategory.NON_SOFTWARE)]
        result = analyze(infos, ProjectType.PROPRIETARY, "/test")

        assert result.findings[0].risk_level == RiskLevel.CRITICAL

    def test_cc_by_nc_warning_in_internal(self) -> None:
        """CC-BY-NC-4.0 in an internal project should fall through to warning.

        No special rule exists for CC-BY-NC + internal, so the default
        non_software + internal = notice from the compatibility matrix applies.
        """
        infos = [_make_info("nc-data", "CC-BY-NC-4.0", LicenseCategory.NON_SOFTWARE)]
        result = analyze(infos, ProjectType.INTERNAL, "/test")

        # non_software + internal = notice (from compatibility matrix)
        assert result.findings[0].risk_level == RiskLevel.NOTICE


# ===========================================================================
# EUPL-1.2 tests
# ===========================================================================


class TestEupl:
    """Tests for EUPL-1.2 (strong copyleft) in various project types."""

    def test_eupl_critical_in_proprietary(self) -> None:
        """EUPL-1.2 in a proprietary project should be critical (strong copyleft)."""
        infos = [_make_info("eu-pkg", "EUPL-1.2", LicenseCategory.STRONG_COPYLEFT)]
        result = analyze(infos, ProjectType.PROPRIETARY, "/test")

        assert result.findings[0].risk_level == RiskLevel.CRITICAL


# ===========================================================================
# Copyleft compatibility notice tests
# ===========================================================================


class TestCopyleftCompatibilityNotice:
    """Tests for the copyleft compatibility notice (Priority 5.5).

    When a copyleft project uses a strong copyleft dependency without
    --project-license, the analyzer upgrades CLEAN to NOTICE to suggest
    using --project-license for precise conflict detection.
    """

    def test_copyleft_dep_notice_without_project_license(self) -> None:
        """Strong copyleft + copyleft project + no --project-license → NOTICE.

        The explanation should mention --project-license.
        """
        infos = [_make_info("gpl-pkg", "GPL-3.0-only", LicenseCategory.STRONG_COPYLEFT)]
        result = analyze(infos, ProjectType.OPEN_SOURCE_COPYLEFT, "/test")

        finding = result.findings[0]
        assert finding.risk_level == RiskLevel.NOTICE
        assert "--project-license" in finding.explanation

    def test_copyleft_dep_clean_with_project_license(self) -> None:
        """Strong copyleft + copyleft project + matching --project-license → CLEAN.

        When --project-license is provided and there's no conflict, the
        finding should be CLEAN (no upgrade to NOTICE needed).
        """
        infos = [_make_info("gpl-pkg", "GPL-3.0-only", LicenseCategory.STRONG_COPYLEFT)]
        result = analyze(
            infos,
            ProjectType.OPEN_SOURCE_COPYLEFT,
            "/test",
            project_license="GPL-3.0-only",
        )

        assert result.findings[0].risk_level == RiskLevel.CLEAN

    def test_permissive_dep_unaffected_by_copyleft_notice(self) -> None:
        """Permissive deps in copyleft projects should still be CLEAN.

        The copyleft notice only applies to strong_copyleft dependencies.
        Permissive licenses are always clean regardless.
        """
        infos = [_make_info("some-pkg", "BSD-3-Clause", LicenseCategory.PERMISSIVE)]
        result = analyze(infos, ProjectType.OPEN_SOURCE_COPYLEFT, "/test")

        assert result.findings[0].risk_level == RiskLevel.CLEAN


# ===========================================================================
# SSPL end-to-end deny list verification
# ===========================================================================


class TestSsplDenyList:
    """End-to-end verification that SSPL is denied across project types."""

    def test_sspl_critical_in_saas(self) -> None:
        """SSPL-1.0 in a SaaS project should be critical (deny list).

        SSPL is in the default deny list, so it's always critical
        regardless of the compatibility matrix result.
        """
        infos = [_make_info("sspl-pkg", "SSPL-1.0", LicenseCategory.PROPRIETARY)]
        result = analyze(infos, ProjectType.SAAS, "/test")

        assert result.findings[0].risk_level == RiskLevel.CRITICAL
        assert result.findings[0].policy_violated == "Blocked by organizational policy"


# ===========================================================================
# Project license validation tests
# ===========================================================================


class TestProjectLicenseValidation:
    """Tests for --project-license validation warnings.

    The analyzer warns about clear contradictions between --project-license
    and --project-type, but does not block execution.
    """

    def test_permissive_license_copyleft_type_logs_warning(self, caplog) -> None:
        """MIT license + copyleft project type should log a mismatch warning.

        This is a clear contradiction — MIT is permissive, so the project
        type should be open-source-permissive, not copyleft.
        """
        import logging

        with caplog.at_level(logging.WARNING):
            infos = [_make_info("pkg", "MIT", LicenseCategory.PERMISSIVE)]
            analyze(
                infos,
                ProjectType.OPEN_SOURCE_COPYLEFT,
                "/test",
                project_license="MIT",
            )

        assert any("permissive" in record.message.lower() for record in caplog.records)

    def test_copyleft_license_permissive_type_logs_warning(self, caplog) -> None:
        """GPL-3.0-only license + permissive project type should log a warning.

        This is a clear contradiction — GPL is copyleft, so the project
        type should be open-source-copyleft, not permissive.
        """
        import logging

        with caplog.at_level(logging.WARNING):
            infos = [_make_info("pkg", "MIT", LicenseCategory.PERMISSIVE)]
            analyze(
                infos,
                ProjectType.OPEN_SOURCE_PERMISSIVE,
                "/test",
                project_license="GPL-3.0-only",
            )

        assert any("copyleft" in record.message.lower() for record in caplog.records)

    def test_matching_license_and_type_no_warning(self, caplog) -> None:
        """GPL-3.0-only license + copyleft project type should NOT warn.

        When the license and type match, no warning should be generated.
        """
        import logging

        with caplog.at_level(logging.WARNING):
            infos = [_make_info("pkg", "GPL-3.0-only", LicenseCategory.STRONG_COPYLEFT)]
            analyze(
                infos,
                ProjectType.OPEN_SOURCE_COPYLEFT,
                "/test",
                project_license="GPL-3.0-only",
            )

        # Filter to only our validation warnings (exclude policy SPDX warnings)
        validation_warnings = [r for r in caplog.records if "Did you mean" in r.message]
        assert len(validation_warnings) == 0


# ===========================================================================
# Classification note in findings tests
# ===========================================================================


class TestClassificationNoteInFindings:
    """Tests that classification_note from the classifier appears in findings."""

    def test_classification_note_appears_in_explanation(self) -> None:
        """When classification_note is set, it should appear in the explanation."""
        info = LicenseInfo(
            package_name="ambiguous-pkg",
            declared_license="GNU General Public License",
            spdx_id="GPL-2.0-only",
            category=LicenseCategory.STRONG_COPYLEFT,
            classification_note="Ambiguous license string — could be GPL-2.0 or GPL-3.0",
        )
        result = analyze([info], ProjectType.PROPRIETARY, "/test")

        assert "Ambiguous" in result.findings[0].explanation

    def test_no_classification_note_no_extra_text(self) -> None:
        """When classification_note is None, explanation should not contain 'Note:'."""
        info = LicenseInfo(
            package_name="clear-pkg",
            declared_license="GPL-3.0-only",
            spdx_id="GPL-3.0-only",
            category=LicenseCategory.STRONG_COPYLEFT,
            classification_note=None,
        )
        result = analyze([info], ProjectType.PROPRIETARY, "/test")

        assert "Note:" not in result.findings[0].explanation
