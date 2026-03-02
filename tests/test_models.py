"""
Tests for the data models (models.py).

Even though data classes are simple, these tests verify:
1. All models can be instantiated with expected arguments
2. Default values work correctly (e.g., LicenseInfo.category defaults to UNKNOWN)
3. Enum values match what the rest of the codebase expects
4. The `from __future__ import annotations` import works on Python 3.9
   (which is needed for the `list[str]` syntax in type hints)

These tests also serve as documentation — reading them shows you exactly
how each model is intended to be used.
"""

from license_comply.models import (
    Finding,
    LicenseCategory,
    LicenseInfo,
    ObligationSummary,
    PackageInfo,
    ProjectType,
    RiskLevel,
    ScanResult,
)

# ---------------------------------------------------------------------------
# Enum tests — verify the fixed set of values matches our spec
# ---------------------------------------------------------------------------


class TestRiskLevel:
    """Tests for the RiskLevel enum."""

    def test_has_four_levels(self):
        """RiskLevel should have exactly four values: clean, notice, warning, critical."""
        values = [level.value for level in RiskLevel]
        assert values == ["clean", "notice", "warning", "critical"]

    def test_can_create_from_string(self):
        """Should be able to create a RiskLevel from its string value."""
        assert RiskLevel("critical") == RiskLevel.CRITICAL
        assert RiskLevel("clean") == RiskLevel.CLEAN


class TestLicenseCategory:
    """Tests for the LicenseCategory enum."""

    def test_has_seven_categories(self):
        """LicenseCategory should have exactly seven values."""
        assert len(LicenseCategory) == 7

    def test_key_categories_exist(self):
        """The most commonly used categories should exist with expected values."""
        assert LicenseCategory.PERMISSIVE.value == "permissive"
        assert LicenseCategory.STRONG_COPYLEFT.value == "strong_copyleft"
        assert LicenseCategory.UNKNOWN.value == "unknown"


class TestProjectType:
    """Tests for the ProjectType enum."""

    def test_has_five_project_types(self):
        """ProjectType should have exactly five values."""
        assert len(ProjectType) == 5

    def test_values_use_kebab_case_for_compound_names(self):
        """Compound project types use kebab-case (e.g., 'open-source-permissive'),
        matching the CLI flag format."""
        assert ProjectType.OPEN_SOURCE_PERMISSIVE.value == "open-source-permissive"
        assert ProjectType.OPEN_SOURCE_COPYLEFT.value == "open-source-copyleft"


# ---------------------------------------------------------------------------
# Dataclass tests — verify construction and defaults
# ---------------------------------------------------------------------------


class TestPackageInfo:
    """Tests for the PackageInfo dataclass."""

    def test_create_with_name_only(self):
        """A package can be created with just a name (version is optional)."""
        package = PackageInfo(name="requests")
        assert package.name == "requests"
        assert package.version_spec is None

    def test_create_with_version_spec(self):
        """A package can include a version specifier."""
        package = PackageInfo(name="flask", version_spec=">=3.0.0")
        assert package.name == "flask"
        assert package.version_spec == ">=3.0.0"


class TestLicenseInfo:
    """Tests for the LicenseInfo dataclass."""

    def test_defaults_to_unknown_category(self):
        """A new LicenseInfo should default to UNKNOWN category until classified."""
        info = LicenseInfo(package_name="some-package")
        assert info.category == LicenseCategory.UNKNOWN

    def test_all_optional_fields_default_to_none(self):
        """All optional fields should be None by default."""
        info = LicenseInfo(package_name="some-package")
        assert info.declared_license is None
        assert info.spdx_id is None
        assert info.pypi_url is None
        assert info.source_url is None

    def test_create_fully_populated(self):
        """A fully populated LicenseInfo should store all values."""
        info = LicenseInfo(
            package_name="requests",
            declared_license="Apache 2.0",
            spdx_id="Apache-2.0",
            category=LicenseCategory.PERMISSIVE,
            pypi_url="https://pypi.org/project/requests/",
            source_url="https://github.com/psf/requests",
        )
        assert info.package_name == "requests"
        assert info.spdx_id == "Apache-2.0"
        assert info.category == LicenseCategory.PERMISSIVE

    def test_additional_spdx_ids_list_is_independent(self):
        """Each LicenseInfo should have its own additional_spdx_ids list.

        This guards against the mutable default argument bug — if
        'field(default_factory=list)' were ever accidentally replaced
        with a bare '= []', all instances would share one list.
        """
        info_a = LicenseInfo(package_name="package-a")
        info_b = LicenseInfo(package_name="package-b")

        info_a.additional_spdx_ids.append("MIT")
        assert len(info_a.additional_spdx_ids) == 1
        assert len(info_b.additional_spdx_ids) == 0  # Should still be empty


class TestFinding:
    """Tests for the Finding dataclass."""

    def test_create_clean_finding(self):
        """A clean finding has risk level CLEAN and no policy violation."""
        license_info = LicenseInfo(
            package_name="requests",
            spdx_id="MIT",
            category=LicenseCategory.PERMISSIVE,
        )
        finding = Finding(
            package_name="requests",
            license_info=license_info,
            risk_level=RiskLevel.CLEAN,
            title="Permissive License",
            explanation="MIT is permissive and compatible with all project types.",
            recommendation="No action required.",
        )
        assert finding.risk_level == RiskLevel.CLEAN
        assert finding.policy_violated is None

    def test_create_critical_finding_with_policy(self):
        """A critical finding can include which policy rule was violated."""
        license_info = LicenseInfo(
            package_name="some-gpl-package",
            spdx_id="GPL-3.0-only",
            category=LicenseCategory.STRONG_COPYLEFT,
        )
        finding = Finding(
            package_name="some-gpl-package",
            license_info=license_info,
            risk_level=RiskLevel.CRITICAL,
            title="Copyleft Contamination Risk",
            explanation="GPL-3.0 requires your entire project to be open-sourced.",
            recommendation="Replace with a permissively-licensed alternative.",
            policy_violated="deny list",
        )
        assert finding.risk_level == RiskLevel.CRITICAL
        assert finding.policy_violated == "deny list"


class TestObligationSummary:
    """Tests for the ObligationSummary dataclass (the rollup feature)."""

    def test_create_with_defaults(self):
        """Packages and license_ids should default to empty lists."""
        obligation = ObligationSummary(obligation="Include copyright notice")
        assert obligation.obligation == "Include copyright notice"
        assert obligation.packages == []
        assert obligation.license_ids == []

    def test_create_with_multiple_packages(self):
        """An obligation can be shared by multiple packages."""
        obligation = ObligationSummary(
            obligation="Include copyright notice",
            packages=["requests", "flask", "click"],
            license_ids=["Apache-2.0", "BSD-3-Clause", "BSD-3-Clause"],
        )
        assert len(obligation.packages) == 3
        assert "requests" in obligation.packages


class TestScanResult:
    """Tests for the ScanResult dataclass."""

    def test_create_minimal(self):
        """A ScanResult can be created with just the required fields."""
        result = ScanResult(
            project_path="./my-project",
            project_type=ProjectType.PROPRIETARY,
            total_packages=5,
        )
        assert result.project_path == "./my-project"
        assert result.project_type == ProjectType.PROPRIETARY
        assert result.total_packages == 5

    def test_defaults_are_empty(self):
        """Lists should default to empty, strings to empty, ai_summary to None."""
        result = ScanResult(
            project_path=".",
            project_type=ProjectType.INTERNAL,
            total_packages=0,
        )
        assert result.findings == []
        assert result.obligation_rollup == []
        assert result.scan_timestamp == ""
        assert result.tool_version == ""
        assert result.ai_summary is None

    def test_findings_list_is_independent(self):
        """Each ScanResult should have its own findings list (not shared).

        This is a subtle Python gotcha: if you used `findings: list = []` instead
        of `field(default_factory=list)`, ALL ScanResult instances would share the
        same list. The `default_factory` creates a new list for each instance.
        """
        result_a = ScanResult(project_path="a", project_type=ProjectType.SAAS, total_packages=0)
        result_b = ScanResult(project_path="b", project_type=ProjectType.SAAS, total_packages=0)

        # Modifying one result's findings should NOT affect the other
        result_a.findings.append(
            Finding(
                package_name="test",
                license_info=LicenseInfo(package_name="test"),
                risk_level=RiskLevel.CLEAN,
                title="Test",
                explanation="Test",
                recommendation="Test",
            )
        )
        assert len(result_a.findings) == 1
        assert len(result_b.findings) == 0  # Should still be empty
