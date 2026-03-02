"""
Tests for the reporter module (report generation).

These tests verify that the reporter produces correct output in all four
formats: terminal, markdown, HTML, and JSON. We test structure and content
rather than exact formatting (which would make tests brittle).
"""

from __future__ import annotations

import json
import os

from license_comply.models import (
    Finding,
    LicenseCategory,
    LicenseInfo,
    ObligationSummary,
    ProjectType,
    RiskLevel,
    ScanResult,
)
from license_comply.reporter import (
    _build_obligations_by_category,
    _build_obligations_by_license,
    _build_obligations_by_package,
    _format_timestamp,
    generate_report,
)

# ---------------------------------------------------------------------------
# Shared fixture: a sample ScanResult for testing
# ---------------------------------------------------------------------------


def _make_sample_result() -> ScanResult:
    """Create a sample ScanResult with a mix of findings for testing."""
    clean_info = LicenseInfo(
        package_name="requests",
        declared_license="MIT License",
        spdx_id="MIT",
        category=LicenseCategory.PERMISSIVE,
        pypi_url="https://pypi.org/project/requests/",
    )
    warning_info = LicenseInfo(
        package_name="chardet",
        declared_license="LGPL-3.0-only",
        spdx_id="LGPL-3.0-only",
        category=LicenseCategory.WEAK_COPYLEFT,
    )
    critical_info = LicenseInfo(
        package_name="gpl-pkg",
        declared_license="GPL-3.0-only",
        spdx_id="GPL-3.0-only",
        category=LicenseCategory.STRONG_COPYLEFT,
    )
    # A transitive dependency — pulled in by another package, not listed directly
    transitive_info = LicenseInfo(
        package_name="urllib3",
        declared_license="MIT License",
        spdx_id="MIT",
        category=LicenseCategory.PERMISSIVE,
        is_transitive=True,
    )

    return ScanResult(
        project_path="/test/project",
        project_type=ProjectType.PROPRIETARY,
        total_packages=4,
        direct_count=3,
        transitive_count=1,
        findings=[
            Finding(
                package_name="requests",
                license_info=clean_info,
                risk_level=RiskLevel.CLEAN,
                title="License Compatible",
                explanation="MIT is a permissive license.",
                recommendation="No action required.",
            ),
            Finding(
                package_name="chardet",
                license_info=warning_info,
                risk_level=RiskLevel.WARNING,
                title="License Review Needed",
                explanation="LGPL is weak copyleft.",
                recommendation="Review how you use this library.",
                remediation_steps=[
                    "Verify you are using chardet via standard Python imports.",
                    "Check whether you have modified chardet's source code.",
                ],
            ),
            Finding(
                package_name="gpl-pkg",
                license_info=critical_info,
                risk_level=RiskLevel.CRITICAL,
                title="License Incompatibility",
                explanation="GPL is strong copyleft.",
                recommendation="Replace this dependency.",
                policy_violated="Flagged for review",
                remediation_steps=[
                    "Search PyPI for alternative packages with a permissive license.",
                    "Consult your legal team about isolation strategies.",
                ],
            ),
            Finding(
                package_name="urllib3",
                license_info=transitive_info,
                risk_level=RiskLevel.CLEAN,
                title="License Compatible",
                explanation="MIT is a permissive license.",
                recommendation="No action required.",
            ),
        ],
        obligation_rollup=[
            ObligationSummary(
                obligation="Include copyright notice",
                packages=["requests"],
                license_ids=["MIT"],
            ),
        ],
        scan_timestamp="2026-02-24T00:00:00+00:00",
        tool_version="1.0.0",
    )


# ===========================================================================
# Terminal output tests
# ===========================================================================


class TestTerminalOutput:
    """Tests for Rich terminal output."""

    def test_terminal_output_includes_summary_counts(self, capsys) -> None:
        """Terminal output should include the summary count section."""
        result = _make_sample_result()
        generate_report(result, formats=["terminal"], ci_mode=True)

        output = capsys.readouterr().out
        assert "Total packages:" in output
        assert "4" in output

    def test_critical_findings_appear_before_warnings(self, capsys) -> None:
        """In the dependency table, critical should appear before clean."""
        result = _make_sample_result()
        generate_report(result, formats=["terminal"], ci_mode=True)

        output = capsys.readouterr().out
        # In the table, gpl-pkg (critical) should appear before requests (clean)
        gpl_pos = output.find("gpl-pkg")
        requests_pos = output.find("requests")
        assert gpl_pos < requests_pos, "Critical findings should appear before clean ones"


# ===========================================================================
# Markdown output tests
# ===========================================================================


class TestMarkdownOutput:
    """Tests for Markdown file generation."""

    def test_markdown_report_generated_successfully(self, tmp_path) -> None:
        """Should generate a .md file in the output directory."""
        result = _make_sample_result()
        files = generate_report(result, formats=["markdown"], output_dir=str(tmp_path))

        assert len(files) == 1
        assert files[0].endswith(".md")

        content = open(files[0]).read()
        assert "License Compliance Report" in content
        assert "requests" in content
        assert "gpl-pkg" in content

    def test_markdown_includes_critical_section(self, tmp_path) -> None:
        """Markdown should have a Critical Issues section when there are critical findings."""
        result = _make_sample_result()
        files = generate_report(result, formats=["markdown"], output_dir=str(tmp_path))

        content = open(files[0]).read()
        assert "Critical Issues" in content
        assert "gpl-pkg" in content


# ===========================================================================
# HTML output tests
# ===========================================================================


class TestHtmlOutput:
    """Tests for HTML file generation."""

    def test_html_report_generated_successfully(self, tmp_path) -> None:
        """Should generate a .html file with proper structure."""
        result = _make_sample_result()
        files = generate_report(result, formats=["html"], output_dir=str(tmp_path))

        assert len(files) == 1
        assert files[0].endswith(".html")

        content = open(files[0]).read()
        assert "<!DOCTYPE html>" in content
        assert "License Compliance Report" in content

    def test_html_includes_css(self, tmp_path) -> None:
        """HTML should be self-contained with embedded CSS."""
        result = _make_sample_result()
        files = generate_report(result, formats=["html"], output_dir=str(tmp_path))

        content = open(files[0]).read()
        assert "<style>" in content

    def test_html_includes_formatted_date(self, tmp_path) -> None:
        """HTML should display a human-readable date instead of raw ISO timestamp."""
        result = _make_sample_result()
        files = generate_report(result, formats=["html"], output_dir=str(tmp_path))

        content = open(files[0]).read()
        # The fixture timestamp "2026-02-24T00:00:00+00:00" → "February 24, 2026"
        assert "February 24, 2026" in content

    def test_html_overview_table_before_findings(self, tmp_path) -> None:
        """Overview table should appear before critical/warning findings."""
        result = _make_sample_result()
        files = generate_report(result, formats=["html"], output_dir=str(tmp_path))

        content = open(files[0]).read()
        table_pos = content.find("Overview")
        critical_pos = content.find("Critical Issues")
        assert table_pos < critical_pos, "Overview table should appear before critical issues"

    def test_html_findings_are_collapsible(self, tmp_path) -> None:
        """Critical and warning sections should be wrapped in <details open>."""
        result = _make_sample_result()
        files = generate_report(result, formats=["html"], output_dir=str(tmp_path))

        content = open(files[0]).read()
        # Both sections should use collapsible <details> with the "open" attribute
        assert "collapsible-section" in content
        assert "open>" in content

    def test_html_obligations_grouped_by_license(self, tmp_path) -> None:
        """Obligations section should show license grouping with 'Used by:' labels."""
        result = _make_sample_result()
        files = generate_report(result, formats=["html"], output_dir=str(tmp_path))

        content = open(files[0]).read()
        # The fixture has MIT obligation for "requests"
        assert "MIT" in content
        assert "Used by:" in content

    def test_html_header_has_navy_background(self, tmp_path) -> None:
        """Header should have the deep ink navy background color."""
        result = _make_sample_result()
        files = generate_report(result, formats=["html"], output_dir=str(tmp_path))

        content = open(files[0]).read()
        # New design uses deeper ink navy #0f172a as a CSS custom property
        assert "#0f172a" in content

    def test_html_header_metadata_grid(self, tmp_path) -> None:
        """Header should use a labeled metadata grid with Project, Type, etc."""
        result = _make_sample_result()
        files = generate_report(result, formats=["html"], output_dir=str(tmp_path))

        content = open(files[0]).read()
        assert "hero-meta-label" in content
        assert "hero-meta-value" in content

    def test_html_footer_includes_disclaimer(self, tmp_path) -> None:
        """Footer should contain the legal disclaimer text."""
        result = _make_sample_result()
        files = generate_report(result, formats=["html"], output_dir=str(tmp_path))

        content = open(files[0]).read()
        # Disclaimer moved from header to footer in the redesign
        assert "report-footer" in content
        assert "does not constitute legal advice" in content

    def test_html_obligations_has_both_views(self, tmp_path) -> None:
        """Obligations section should have both 'By License' and 'By Obligation' tabs."""
        result = _make_sample_result()
        files = generate_report(result, formats=["html"], output_dir=str(tmp_path))

        content = open(files[0]).read()
        # Tab labels
        assert "By License" in content
        assert "By Obligation" in content
        # Both panel classes should be present
        assert "panel-by-license" in content
        assert "panel-by-obligation" in content

    def test_html_packages_have_pypi_links(self, tmp_path) -> None:
        """Packages with a pypi_url should render as clickable links."""
        result = _make_sample_result()
        files = generate_report(result, formats=["html"], output_dir=str(tmp_path))

        content = open(files[0]).read()
        # The "requests" package has pypi_url set in the fixture
        assert "https://pypi.org/project/requests/" in content
        assert "pkg-link" in content

    def test_html_has_risk_distribution_bar(self, tmp_path) -> None:
        """HTML should include a risk distribution bar below summary cards."""
        result = _make_sample_result()
        files = generate_report(result, formats=["html"], output_dir=str(tmp_path))

        content = open(files[0]).read()
        assert "risk-bar" in content
        # Should have at least one colored segment
        assert "bar-critical" in content

    def test_html_summary_cards_are_clickable(self, tmp_path) -> None:
        """Summary cards should be wrapped in anchor links to their sections."""
        result = _make_sample_result()
        files = generate_report(result, formats=["html"], output_dir=str(tmp_path))

        content = open(files[0]).read()
        assert "summary-card-link" in content
        assert "#section-overview" in content
        assert "#section-critical" in content
        assert "#section-warnings" in content

    def test_html_section_renamed_to_overview(self, tmp_path) -> None:
        """The dependency table section should be titled 'Overview', not 'All Dependencies'."""
        result = _make_sample_result()
        files = generate_report(result, formats=["html"], output_dir=str(tmp_path))

        content = open(files[0]).read()
        assert "All Dependencies" not in content
        assert ">Overview<" in content


# ===========================================================================
# JSON output tests
# ===========================================================================


class TestJsonOutput:
    """Tests for JSON file generation."""

    def test_json_output_is_valid_json(self, tmp_path) -> None:
        """Should generate valid, parseable JSON."""
        result = _make_sample_result()
        files = generate_report(result, formats=["json"], output_dir=str(tmp_path))

        assert len(files) == 1
        content = open(files[0]).read()
        data = json.loads(content)  # Should not raise

        assert data["total_packages"] == 4
        assert data["project_type"] == "proprietary"
        assert len(data["findings"]) == 4

    def test_json_includes_all_finding_fields(self, tmp_path) -> None:
        """Each finding in JSON should have all expected fields."""
        result = _make_sample_result()
        files = generate_report(result, formats=["json"], output_dir=str(tmp_path))

        data = json.loads(open(files[0]).read())
        finding = data["findings"][0]

        expected_keys = {
            "package_name",
            "declared_license",
            "spdx_id",
            "category",
            "risk_level",
            "is_transitive",
            "title",
            "explanation",
            "recommendation",
            "remediation_steps",
            "policy_violated",
            "pypi_url",
            "source_url",
        }
        assert expected_keys.issubset(set(finding.keys()))

    def test_json_includes_obligation_rollup(self, tmp_path) -> None:
        """JSON should include the obligation rollup section."""
        result = _make_sample_result()
        files = generate_report(result, formats=["json"], output_dir=str(tmp_path))

        data = json.loads(open(files[0]).read())
        assert "obligation_rollup" in data
        assert len(data["obligation_rollup"]) == 1
        assert data["obligation_rollup"][0]["obligation"] == "Include copyright notice"


# ===========================================================================
# Remediation steps output tests
# ===========================================================================


class TestRemediationStepsOutput:
    """Tests that remediation steps appear correctly in all output formats.

    These verify the rendering side — that the steps stored on Finding
    objects actually make it into the terminal, JSON, markdown, and HTML
    output. The analyzer tests cover step generation; these cover display.
    """

    def test_terminal_includes_remediation_steps(self, capsys) -> None:
        """Terminal output should show 'Next steps:' with numbered items."""
        result = _make_sample_result()
        generate_report(result, formats=["terminal"], ci_mode=True)

        output = capsys.readouterr().out
        assert "Next steps:" in output
        # Should include numbered steps from the critical finding
        assert "1." in output
        assert "2." in output

    def test_json_includes_remediation_steps(self, tmp_path) -> None:
        """JSON output should include remediation_steps as a list in each finding."""
        result = _make_sample_result()
        files = generate_report(result, formats=["json"], output_dir=str(tmp_path))

        data = json.loads(open(files[0]).read())
        # The critical finding (gpl-pkg) should have remediation_steps
        critical_finding = next(f for f in data["findings"] if f["risk_level"] == "critical")
        assert "remediation_steps" in critical_finding
        assert len(critical_finding["remediation_steps"]) == 2

        # The clean finding (requests) should have an empty list
        clean_finding = next(f for f in data["findings"] if f["risk_level"] == "clean")
        assert clean_finding["remediation_steps"] == []

    def test_markdown_includes_remediation_steps(self, tmp_path) -> None:
        """Markdown output should include 'Next steps:' section."""
        result = _make_sample_result()
        files = generate_report(result, formats=["markdown"], output_dir=str(tmp_path))

        content = open(files[0]).read()
        assert "**Next steps:**" in content
        # Should include numbered steps
        assert "1." in content

    def test_html_includes_remediation_steps(self, tmp_path) -> None:
        """HTML output should include the finding-steps class with an ordered list."""
        result = _make_sample_result()
        files = generate_report(result, formats=["html"], output_dir=str(tmp_path))

        content = open(files[0]).read()
        assert "finding-steps" in content
        assert "Next steps:" in content
        assert "<ol>" in content
        assert "<li>" in content


# ===========================================================================
# Helper function tests
# ===========================================================================


class TestFormatTimestamp:
    """Tests for the _format_timestamp() helper."""

    def test_iso_timestamp_formatted_to_readable_date(self) -> None:
        """A standard ISO timestamp should become a readable date string."""
        result = _format_timestamp("2026-02-25T14:30:00+00:00")
        assert result == "February 25, 2026"

    def test_midnight_timestamp(self) -> None:
        """Midnight timestamps should also format correctly."""
        result = _format_timestamp("2026-02-24T00:00:00+00:00")
        assert result == "February 24, 2026"

    def test_fallback_on_invalid_string(self) -> None:
        """If the timestamp can't be parsed, return the raw string."""
        raw = "not-a-date"
        result = _format_timestamp(raw)
        assert result == raw

    def test_fallback_on_empty_string(self) -> None:
        """An empty string should be returned as-is without crashing."""
        result = _format_timestamp("")
        assert result == ""


class TestObligationsByLicense:
    """Tests for the _build_obligations_by_license() helper."""

    def test_single_obligation_single_license(self) -> None:
        """One obligation for one package/license should produce one group."""
        rollup = [
            ObligationSummary(
                obligation="Include copyright notice",
                packages=["requests"],
                license_ids=["MIT"],
            ),
        ]
        result = _build_obligations_by_license(rollup)

        assert len(result) == 1
        assert result[0]["license_id"] == "MIT"
        assert result[0]["packages"] == ["requests"]
        assert result[0]["obligations"] == ["Include copyright notice"]

    def test_multiple_obligations_same_license(self) -> None:
        """Multiple obligations for the same license should be grouped together."""
        rollup = [
            ObligationSummary(
                obligation="Include copyright notice",
                packages=["flask"],
                license_ids=["BSD-3-Clause"],
            ),
            ObligationSummary(
                obligation="Include license text",
                packages=["flask"],
                license_ids=["BSD-3-Clause"],
            ),
        ]
        result = _build_obligations_by_license(rollup)

        assert len(result) == 1
        assert result[0]["license_id"] == "BSD-3-Clause"
        assert result[0]["packages"] == ["flask"]
        assert len(result[0]["obligations"]) == 2

    def test_multiple_licenses_sorted_alphabetically(self) -> None:
        """Result should be sorted alphabetically by license_id."""
        rollup = [
            ObligationSummary(
                obligation="Include copyright notice",
                packages=["requests", "flask"],
                license_ids=["MIT", "BSD-3-Clause"],
            ),
        ]
        result = _build_obligations_by_license(rollup)

        assert len(result) == 2
        assert result[0]["license_id"] == "BSD-3-Clause"
        assert result[1]["license_id"] == "MIT"

    def test_empty_rollup_returns_empty_list(self) -> None:
        """An empty obligation rollup should return an empty list."""
        result = _build_obligations_by_license([])
        assert result == []


# ===========================================================================
# HTML — new features tests
# ===========================================================================


class TestHtmlByPackageTab:
    """Tests for the new 'By Package' obligation tab."""

    def test_html_has_three_obligation_tabs(self, tmp_path) -> None:
        """Obligations section should have all three tabs: By License, By Obligation, By Package."""
        result = _make_sample_result()
        files = generate_report(result, formats=["html"], output_dir=str(tmp_path))

        content = open(files[0]).read()
        assert "By License" in content
        assert "By Obligation" in content
        assert "By Package" in content

    def test_html_has_by_package_panel(self, tmp_path) -> None:
        """HTML should contain the panel-by-package div."""
        result = _make_sample_result()
        files = generate_report(result, formats=["html"], output_dir=str(tmp_path))

        content = open(files[0]).read()
        assert "panel-by-package" in content
        assert "tab-by-package" in content

    def test_html_by_package_shows_package_obligations(self, tmp_path) -> None:
        """The By Package panel should list each package with its license and obligations."""
        result = _make_sample_result()
        files = generate_report(result, formats=["html"], output_dir=str(tmp_path))

        content = open(files[0]).read()
        # The fixture has "requests" with "Include copyright notice"
        assert "obligation-package-group" in content
        assert "obligation-package-header" in content


class TestHtmlCategorizedObligations:
    """Tests for the categorized 'By Obligation' view."""

    def test_html_by_obligation_has_category_groups(self, tmp_path) -> None:
        """The By Obligation panel should group obligations by category."""
        # Create a result with obligations that have categories
        result = _make_sample_result()
        result.obligation_rollup = [
            ObligationSummary(
                obligation="Include copyright notice",
                category="notice",
                packages=["requests"],
                license_ids=["MIT"],
            ),
            ObligationSummary(
                obligation="Distribute source code under GPL",
                category="source_sharing",
                packages=["gpl-pkg"],
                license_ids=["GPL-3.0-only"],
            ),
        ]
        files = generate_report(result, formats=["html"], output_dir=str(tmp_path))

        content = open(files[0]).read()
        assert "obligation-category-group" in content
        assert "obligation-category-header" in content

    def test_html_by_obligation_shows_category_labels(self, tmp_path) -> None:
        """Category headers should show human-readable labels like 'Notice &amp; Attribution'."""
        result = _make_sample_result()
        result.obligation_rollup = [
            ObligationSummary(
                obligation="Include copyright notice",
                category="notice",
                packages=["requests"],
                license_ids=["MIT"],
            ),
        ]
        files = generate_report(result, formats=["html"], output_dir=str(tmp_path))

        content = open(files[0]).read()
        # Jinja2 with autoescape=True will render & as &amp; in the HTML
        assert "Notice &amp; Attribution" in content


class TestHtmlInteractiveFeatures:
    """Tests for the interactive HTML improvements (search, print, expand/collapse)."""

    def test_html_has_search_bar(self, tmp_path) -> None:
        """HTML should include a search/filter input for the overview table."""
        result = _make_sample_result()
        files = generate_report(result, formats=["html"], output_dir=str(tmp_path))

        content = open(files[0]).read()
        assert "table-search" in content
        assert "search-bar" in content
        assert 'placeholder="Filter packages..."' in content

    def test_html_has_print_styles(self, tmp_path) -> None:
        """HTML should include @media print CSS rules for print-friendly output."""
        result = _make_sample_result()
        files = generate_report(result, formats=["html"], output_dir=str(tmp_path))

        content = open(files[0]).read()
        assert "@media print" in content

    def test_html_has_expand_collapse_toggle(self, tmp_path) -> None:
        """When findings exist, there should be an expand/collapse all button."""
        result = _make_sample_result()
        files = generate_report(result, formats=["html"], output_dir=str(tmp_path))

        content = open(files[0]).read()
        assert "toggle-all" in content
        assert "Collapse all" in content

    def test_html_has_javascript(self, tmp_path) -> None:
        """HTML should include inline JavaScript for search and toggle features."""
        result = _make_sample_result()
        files = generate_report(result, formats=["html"], output_dir=str(tmp_path))

        content = open(files[0]).read()
        assert "<script>" in content
        assert "table-search" in content

    def test_html_table_rows_have_filterable_class(self, tmp_path) -> None:
        """Table rows should have the 'filterable-row' class for the search filter."""
        result = _make_sample_result()
        files = generate_report(result, formats=["html"], output_dir=str(tmp_path))

        content = open(files[0]).read()
        assert "filterable-row" in content


# ===========================================================================
# Helper function tests — new helpers
# ===========================================================================


class TestObligationsByPackage:
    """Tests for the _build_obligations_by_package() helper."""

    def test_single_package_single_obligation(self) -> None:
        """One obligation for one package should produce one group."""
        rollup = [
            ObligationSummary(
                obligation="Include copyright notice",
                packages=["requests"],
                license_ids=["MIT"],
            ),
        ]
        result = _build_obligations_by_package(rollup)

        assert len(result) == 1
        assert result[0]["package_name"] == "requests"
        assert result[0]["license_id"] == "MIT"
        assert result[0]["obligations"] == ["Include copyright notice"]

    def test_multiple_obligations_same_package(self) -> None:
        """Multiple obligations for one package should be grouped together."""
        rollup = [
            ObligationSummary(
                obligation="Include copyright notice",
                packages=["flask"],
                license_ids=["BSD-3-Clause"],
            ),
            ObligationSummary(
                obligation="Do not use names for endorsement",
                packages=["flask"],
                license_ids=["BSD-3-Clause"],
            ),
        ]
        result = _build_obligations_by_package(rollup)

        assert len(result) == 1
        assert result[0]["package_name"] == "flask"
        assert len(result[0]["obligations"]) == 2

    def test_multiple_packages_sorted_alphabetically(self) -> None:
        """Result should be sorted alphabetically by package_name."""
        rollup = [
            ObligationSummary(
                obligation="Include copyright notice",
                packages=["requests", "flask"],
                license_ids=["MIT", "BSD-3-Clause"],
            ),
        ]
        result = _build_obligations_by_package(rollup)

        assert len(result) == 2
        assert result[0]["package_name"] == "flask"
        assert result[1]["package_name"] == "requests"

    def test_empty_rollup_returns_empty_list(self) -> None:
        """An empty obligation rollup should return an empty list."""
        result = _build_obligations_by_package([])
        assert result == []


class TestObligationsByCategory:
    """Tests for the _build_obligations_by_category() helper."""

    def test_groups_obligations_by_category(self) -> None:
        """Obligations should be grouped by their category."""
        rollup = [
            ObligationSummary(
                obligation="Include copyright notice",
                category="notice",
                packages=["requests"],
                license_ids=["MIT"],
            ),
            ObligationSummary(
                obligation="Distribute source code",
                category="source_sharing",
                packages=["gpl-pkg"],
                license_ids=["GPL-3.0-only"],
            ),
        ]
        result = _build_obligations_by_category(rollup)

        assert len(result) == 2
        # Notice should come first (per _OBLIGATION_CATEGORY_ORDER)
        assert result[0]["category_key"] == "notice"
        assert result[0]["category_label"] == "Notice & Attribution"
        assert len(result[0]["obligations"]) == 1

        assert result[1]["category_key"] == "source_sharing"
        assert result[1]["category_label"] == "Source Code Sharing"

    def test_category_order_follows_defined_order(self) -> None:
        """Categories should appear in the order defined by _OBLIGATION_CATEGORY_ORDER."""
        rollup = [
            ObligationSummary(
                obligation="Share source",
                category="source_sharing",
                packages=["gpl-pkg"],
                license_ids=["GPL-3.0-only"],
            ),
            ObligationSummary(
                obligation="Include notice",
                category="notice",
                packages=["requests"],
                license_ids=["MIT"],
            ),
        ]
        result = _build_obligations_by_category(rollup)

        # notice comes before source_sharing in the defined order
        assert result[0]["category_key"] == "notice"
        assert result[1]["category_key"] == "source_sharing"

    def test_obligations_include_package_info(self) -> None:
        """Each obligation in a category group should include packages and license_ids."""
        rollup = [
            ObligationSummary(
                obligation="Include copyright notice",
                category="notice",
                packages=["requests", "flask"],
                license_ids=["MIT", "BSD-3-Clause"],
            ),
        ]
        result = _build_obligations_by_category(rollup)

        obligation = result[0]["obligations"][0]
        assert obligation["text"] == "Include copyright notice"
        assert obligation["packages"] == ["requests", "flask"]
        assert obligation["license_ids"] == ["MIT", "BSD-3-Clause"]

    def test_empty_rollup_returns_empty_list(self) -> None:
        """An empty obligation rollup should return an empty list."""
        result = _build_obligations_by_category([])
        assert result == []

    def test_default_category_for_missing_category(self) -> None:
        """Obligations with no category should default to 'notice'."""
        rollup = [
            ObligationSummary(
                obligation="Some obligation",
                category="",
                packages=["some-pkg"],
                license_ids=["MIT"],
            ),
        ]
        result = _build_obligations_by_category(rollup)

        assert len(result) == 1
        assert result[0]["category_key"] == "notice"


# ===========================================================================
# Transitive dependency display tests
# ===========================================================================


class TestTransitiveDisplay:
    """Tests for transitive dependency indicators across all output formats.

    When deep scanning is active, transitive dependencies should be visually
    distinguished from direct dependencies in every report format.
    """

    def test_terminal_shows_transitive_indicator(self, capsys) -> None:
        """Terminal output should show '(transitive)' for transitive packages."""
        result = _make_sample_result()
        generate_report(result, formats=["terminal"], ci_mode=True)

        output = capsys.readouterr().out
        assert "(transitive)" in output
        # Should show direct/transitive count breakdown
        assert "Direct:" in output
        assert "Transitive:" in output

    def test_json_includes_is_transitive_field(self, tmp_path) -> None:
        """JSON output should include is_transitive field for each finding."""
        result = _make_sample_result()
        files = generate_report(result, formats=["json"], output_dir=str(tmp_path))

        data = json.loads(open(files[0]).read())

        # urllib3 is transitive in our fixture
        urllib3_finding = next(
            (f for f in data["findings"] if f["package_name"] == "urllib3"), None
        )
        assert urllib3_finding is not None
        assert urllib3_finding["is_transitive"] is True

        # requests is direct
        requests_finding = next(
            (f for f in data["findings"] if f["package_name"] == "requests"), None
        )
        assert requests_finding is not None
        assert requests_finding["is_transitive"] is False

        # Top-level counts should be present
        assert data["direct_count"] == 3
        assert data["transitive_count"] == 1

    def test_html_shows_transitive_badge(self, tmp_path) -> None:
        """HTML output should include badge-transitive class for transitive packages."""
        result = _make_sample_result()
        files = generate_report(result, formats=["html"], output_dir=str(tmp_path))

        content = open(files[0]).read()
        assert "badge-transitive" in content

    def test_markdown_shows_transitive_indicator(self, tmp_path) -> None:
        """Markdown output should include *(transitive)* for transitive packages."""
        result = _make_sample_result()
        files = generate_report(result, formats=["markdown"], output_dir=str(tmp_path))

        content = open(files[0]).read()
        assert "*(transitive)*" in content
        # Summary table should show direct/transitive breakdown
        assert "Direct" in content
        assert "Transitive" in content


# ===========================================================================
# Tests for output directory creation (Fix 1.2)
# ===========================================================================


class TestOutputDirectoryCreation:
    """Tests that generate_report creates the output directory if it doesn't exist."""

    def test_report_creates_missing_output_directory(self, tmp_path) -> None:
        """Generating a report to a non-existent directory should create it."""
        result = _make_sample_result()
        nested_dir = str(tmp_path / "reports" / "2026" / "march")

        files = generate_report(result, formats=["json"], output_dir=nested_dir)

        assert len(files) == 1
        assert os.path.isfile(files[0])
        data = json.loads(open(files[0]).read())
        assert data["total_packages"] == 4


# ===========================================================================
# Tests for JSON round-trip (Tier 4)
# ===========================================================================


class TestJsonRoundTrip:
    """Verify that JSON output is valid and can be deserialized back."""

    def test_json_round_trip_preserves_all_data(self, tmp_path) -> None:
        """JSON output should serialize and deserialize with all data intact."""
        result = _make_sample_result()
        files = generate_report(result, formats=["json"], output_dir=str(tmp_path))

        data = json.loads(open(files[0]).read())

        # Verify all top-level fields
        assert data["project_path"] == "/test/project"
        assert data["project_type"] == "proprietary"
        assert data["total_packages"] == 4
        assert data["direct_count"] == 3
        assert data["transitive_count"] == 1
        assert data["tool_version"] == "1.0.0"
        assert data["scan_timestamp"] == "2026-02-24T00:00:00+00:00"

        # Verify findings have correct structure
        assert len(data["findings"]) == 4
        for finding in data["findings"]:
            assert isinstance(finding["package_name"], str)
            assert isinstance(finding["risk_level"], str)
            assert isinstance(finding["is_transitive"], bool)
            assert isinstance(finding["remediation_steps"], list)

        # Verify obligation rollup
        assert len(data["obligation_rollup"]) == 1
        assert data["obligation_rollup"][0]["obligation"] == "Include copyright notice"


# ===========================================================================
# Tests for Jinja2 template error handling (Fix 2.1)
# ===========================================================================


class TestTemplateErrorHandling:
    """Tests that Jinja2 template errors produce friendly messages, not tracebacks."""

    def test_missing_markdown_template_returns_empty_string(self, tmp_path, capsys) -> None:
        """A missing markdown template should print an error, not crash."""
        from unittest.mock import patch as mock_patch

        result = _make_sample_result()
        # Point the templates dir to an empty directory
        with mock_patch("license_comply.reporter._TEMPLATES_DIR", str(tmp_path)):
            files = generate_report(result, formats=["markdown"], output_dir=str(tmp_path))

        # Empty filepaths from error paths should NOT be appended to the list
        assert files == []

    def test_missing_html_template_returns_empty_string(self, tmp_path, capsys) -> None:
        """A missing HTML template should print an error, not crash."""
        from unittest.mock import patch as mock_patch

        result = _make_sample_result()
        with mock_patch("license_comply.reporter._TEMPLATES_DIR", str(tmp_path)):
            files = generate_report(result, formats=["html"], output_dir=str(tmp_path))

        # Empty filepaths from error paths should NOT be appended to the list
        assert files == []


# ===========================================================================
# Tests for pipe character escaping in markdown (Fix 3.3)
# ===========================================================================


# ===========================================================================
# AI disclaimer tests
# ===========================================================================


def _make_sample_result_with_ai_summary() -> ScanResult:
    """Create a sample ScanResult that includes an AI summary, for testing AI disclaimers."""
    result = _make_sample_result()
    result.ai_summary = "This is a test AI-generated summary of the compliance scan."
    return result


class TestAiDisclaimerTerminal:
    """Tests that the AI disclaimer appears in terminal output when an AI summary is present."""

    def test_terminal_shows_ai_disclaimer_when_summary_present(self, capsys) -> None:
        """Terminal output should include the AI disclaimer after the AI summary panel."""
        result = _make_sample_result_with_ai_summary()
        generate_report(result, formats=["terminal"], ci_mode=True)

        output = capsys.readouterr().out
        assert "generated by an AI language model" in output
        assert "not legal advice" in output

    def test_terminal_no_ai_disclaimer_without_summary(self, capsys) -> None:
        """Terminal output should NOT include the AI disclaimer when there is no AI summary."""
        result = _make_sample_result()
        generate_report(result, formats=["terminal"], ci_mode=True)

        output = capsys.readouterr().out
        assert "generated by an AI language model" not in output


class TestAiDisclaimerMarkdown:
    """Tests that the AI disclaimer appears in Markdown output when an AI summary is present."""

    def test_markdown_shows_ai_disclaimer_when_summary_present(self, tmp_path) -> None:
        """Markdown report should include a blockquote AI disclaimer after the summary."""
        result = _make_sample_result_with_ai_summary()
        files = generate_report(result, formats=["markdown"], output_dir=str(tmp_path))

        content = open(files[0]).read()
        assert "generated by an AI language model" in content
        assert "not legal advice" in content

    def test_markdown_no_ai_disclaimer_without_summary(self, tmp_path) -> None:
        """Markdown report should NOT include the AI disclaimer when there is no AI summary."""
        result = _make_sample_result()
        files = generate_report(result, formats=["markdown"], output_dir=str(tmp_path))

        content = open(files[0]).read()
        assert "generated by an AI language model" not in content


class TestAiDisclaimerHtml:
    """Tests that the AI disclaimer appears in HTML output when an AI summary is present."""

    def test_html_shows_ai_disclaimer_when_summary_present(self, tmp_path) -> None:
        """HTML report should include an ai-disclaimer div after the AI summary."""
        result = _make_sample_result_with_ai_summary()
        files = generate_report(result, formats=["html"], output_dir=str(tmp_path))

        content = open(files[0]).read()
        assert "ai-disclaimer" in content
        assert "generated by an AI language model" in content

    def test_html_no_ai_disclaimer_without_summary(self, tmp_path) -> None:
        """HTML report should NOT include ai-disclaimer div when there is no AI summary."""
        result = _make_sample_result()
        files = generate_report(result, formats=["html"], output_dir=str(tmp_path))

        content = open(files[0]).read()
        # The CSS class may still be in the stylesheet, but the div should not be rendered
        # Check that the actual disclaimer text is not present
        assert "generated by an AI language model" not in content


class TestAiDisclaimerJson:
    """Tests that the AI disclaimer appears in JSON output when an AI summary is present."""

    def test_json_includes_ai_disclaimer_when_summary_present(self, tmp_path) -> None:
        """JSON output should include ai_summary_disclaimer when ai_summary is set."""
        result = _make_sample_result_with_ai_summary()
        files = generate_report(result, formats=["json"], output_dir=str(tmp_path))

        data = json.loads(open(files[0]).read())
        assert data["ai_summary_disclaimer"] is not None
        assert "generated by an AI language model" in data["ai_summary_disclaimer"]

    def test_json_ai_disclaimer_is_null_without_summary(self, tmp_path) -> None:
        """JSON output should have ai_summary_disclaimer as null when no AI summary."""
        result = _make_sample_result()
        files = generate_report(result, formats=["json"], output_dir=str(tmp_path))

        data = json.loads(open(files[0]).read())
        assert data["ai_summary_disclaimer"] is None


class TestMarkdownPipeEscaping:
    """Tests that pipe characters in package names don't break markdown tables."""

    def test_pipe_in_package_name_is_escaped(self, tmp_path) -> None:
        """A | in a package name should be escaped to \\| in the markdown table."""
        from license_comply.reporter import _escape_pipe

        assert _escape_pipe("my|package") == "my\\|package"
        assert _escape_pipe("no-pipes") == "no-pipes"
        assert _escape_pipe("a|b|c") == "a\\|b\\|c"
