"""
Tests for the classifier module (license string matching).

These tests verify that the classifier correctly matches raw license strings
from PyPI to known licenses in the knowledge base. The classifier is critical
to the tool's accuracy — if it misidentifies a license, the entire analysis
will be wrong.

Key behaviors tested:
  - Exact matching against known license names
  - Case-insensitive matching
  - PyPI classifier prefix stripping
  - Whitespace normalization
  - Dual-license OR splitting (picking most permissive)
  - Unknown license handling
"""

from license_comply.classifier import classify_license, classify_licenses
from license_comply.models import LicenseCategory, LicenseInfo

# ---------------------------------------------------------------------------
# Helper to create a LicenseInfo with just a declared_license string
# ---------------------------------------------------------------------------


def _make_license_info(declared_license: str) -> LicenseInfo:
    """Create a LicenseInfo object with only the declared_license set.

    This simulates what the resolver produces — just the raw license string,
    with classification not yet done.
    """
    return LicenseInfo(package_name="test-package", declared_license=declared_license)


# ===========================================================================
# Basic classification tests
# ===========================================================================


class TestBasicClassification:
    """Tests for straightforward license matching."""

    def test_mit_classified_as_permissive(self) -> None:
        """MIT License should be classified as permissive."""
        info = _make_license_info("MIT License")
        result = classify_license(info)
        assert result.spdx_id == "MIT"
        assert result.category == LicenseCategory.PERMISSIVE

    def test_gpl3_classified_as_strong_copyleft(self) -> None:
        """GPL-3.0 should be classified as strong copyleft."""
        info = _make_license_info("GPL-3.0-only")
        result = classify_license(info)
        assert result.spdx_id == "GPL-3.0-only"
        assert result.category == LicenseCategory.STRONG_COPYLEFT

    def test_agpl_classified_as_strong_copyleft(self) -> None:
        """AGPL-3.0 should be classified as strong copyleft."""
        info = _make_license_info("AGPL-3.0-only")
        result = classify_license(info)
        assert result.spdx_id == "AGPL-3.0-only"
        assert result.category == LicenseCategory.STRONG_COPYLEFT

    def test_lgpl_classified_as_weak_copyleft(self) -> None:
        """LGPL-3.0 should be classified as weak copyleft."""
        info = _make_license_info("LGPL-3.0-only")
        result = classify_license(info)
        assert result.spdx_id == "LGPL-3.0-only"
        assert result.category == LicenseCategory.WEAK_COPYLEFT

    def test_apache_classified_as_permissive(self) -> None:
        """Apache-2.0 should be classified as permissive."""
        info = _make_license_info("Apache-2.0")
        result = classify_license(info)
        assert result.spdx_id == "Apache-2.0"
        assert result.category == LicenseCategory.PERMISSIVE

    def test_bsd3_classified_as_permissive(self) -> None:
        """BSD-3-Clause should be classified as permissive."""
        info = _make_license_info("BSD-3-Clause")
        result = classify_license(info)
        assert result.spdx_id == "BSD-3-Clause"
        assert result.category == LicenseCategory.PERMISSIVE

    def test_mpl_classified_as_weak_copyleft(self) -> None:
        """MPL-2.0 should be classified as weak copyleft."""
        info = _make_license_info("MPL-2.0")
        result = classify_license(info)
        assert result.spdx_id == "MPL-2.0"
        assert result.category == LicenseCategory.WEAK_COPYLEFT

    def test_unknown_license_string_classified_as_unknown(self) -> None:
        """An unrecognized license string should be classified as UNKNOWN."""
        info = _make_license_info("Some Custom License v42")
        result = classify_license(info)
        assert result.spdx_id is None
        assert result.category == LicenseCategory.UNKNOWN


# ===========================================================================
# Normalization tests
# ===========================================================================


class TestNormalization:
    """Tests for license string normalization (case, whitespace, prefixes)."""

    def test_classification_is_case_insensitive(self) -> None:
        """License matching should work regardless of capitalization."""
        info = _make_license_info("mit license")
        result = classify_license(info)
        assert result.spdx_id == "MIT"
        assert result.category == LicenseCategory.PERMISSIVE

    def test_handles_license_string_with_extra_whitespace(self) -> None:
        """Should handle strings with leading, trailing, or extra spaces."""
        info = _make_license_info("  MIT   License  ")
        result = classify_license(info)
        assert result.spdx_id == "MIT"
        assert result.category == LicenseCategory.PERMISSIVE

    def test_strips_classifier_prefix(self) -> None:
        """Should strip PyPI classifier prefixes like 'License :: OSI Approved ::'."""
        info = _make_license_info("License :: OSI Approved :: MIT License")
        result = classify_license(info)
        assert result.spdx_id == "MIT"
        assert result.category == LicenseCategory.PERMISSIVE

    def test_strips_classifier_prefix_apache(self) -> None:
        """Should handle the Apache variant of the classifier prefix."""
        info = _make_license_info("License :: OSI Approved :: Apache Software License")
        result = classify_license(info)
        assert result.spdx_id == "Apache-2.0"
        assert result.category == LicenseCategory.PERMISSIVE

    def test_strips_classifier_prefix_case_insensitive(self) -> None:
        """Classifier prefix stripping should also be case-insensitive."""
        info = _make_license_info("license :: osi approved :: MIT License")
        result = classify_license(info)
        assert result.spdx_id == "MIT"
        assert result.category == LicenseCategory.PERMISSIVE


# ===========================================================================
# Parenthetical suffix stripping tests
# ===========================================================================


class TestParentheticalSuffixStripping:
    """Tests that trailing parenthetical abbreviations are stripped from classifiers.

    Many PyPI trove classifiers include a redundant abbreviation in parentheses
    at the end, e.g., "Mozilla Public License 2.0 (MPL 2.0)". The knowledge
    base stores the full name without the abbreviation, so the classifier must
    strip it during normalization. About 32 PyPI classifiers use this pattern.
    """

    def test_strips_parenthetical_suffix_mpl(self) -> None:
        """The exact certifi case: MPL 2.0 classifier with '(MPL 2.0)' suffix.

        PyPI returns: "License :: OSI Approved :: Mozilla Public License 2.0 (MPL 2.0)"
        After prefix stripping: "Mozilla Public License 2.0 (MPL 2.0)"
        After parenthetical stripping: "Mozilla Public License 2.0"
        """
        info = _make_license_info("License :: OSI Approved :: Mozilla Public License 2.0 (MPL 2.0)")
        result = classify_license(info)
        assert result.spdx_id == "MPL-2.0"
        assert result.category == LicenseCategory.WEAK_COPYLEFT

    def test_strips_parenthetical_suffix_gpl(self) -> None:
        """GPL v3 classifier with '(GPLv3)' suffix should still match."""
        info = _make_license_info(
            "License :: OSI Approved :: GNU General Public License v3 (GPLv3)"
        )
        result = classify_license(info)
        assert result.spdx_id == "GPL-3.0-only"
        assert result.category == LicenseCategory.STRONG_COPYLEFT

    def test_parenthetical_in_middle_preserved(self) -> None:
        """Parentheses in the middle of a string should NOT be stripped.

        This is a defensive test: the regex only targets trailing parentheticals.
        A hypothetical license name like 'Foo (Bar) License' should keep (Bar).
        Since 'Foo (Bar) License' isn't in the knowledge base, it should be UNKNOWN.
        """
        info = _make_license_info("Foo (Bar) License")
        result = classify_license(info)
        # The parenthetical is NOT at the end, so it's preserved. The full string
        # "foo (bar) license" won't match anything → UNKNOWN, proving we didn't
        # over-strip.
        assert result.category == LicenseCategory.UNKNOWN


# ===========================================================================
# Dual-license (OR) tests
# ===========================================================================


class TestDualLicense:
    """Tests for dual-license handling with the SPDX OR operator."""

    def test_dual_license_or_picks_most_permissive(self) -> None:
        """When given 'MIT OR GPL-3.0', should pick MIT (more permissive)."""
        info = _make_license_info("MIT OR GPL-3.0-only")
        result = classify_license(info)
        assert result.spdx_id == "MIT"
        assert result.category == LicenseCategory.PERMISSIVE

    def test_dual_license_gpl_or_apache(self) -> None:
        """When given 'GPL-3.0 OR Apache-2.0', should pick Apache (permissive)."""
        info = _make_license_info("GPL-3.0-only OR Apache-2.0")
        result = classify_license(info)
        assert result.spdx_id == "Apache-2.0"
        assert result.category == LicenseCategory.PERMISSIVE

    def test_dual_license_preserves_declared_license(self) -> None:
        """The original dual-license string should be kept in declared_license."""
        info = _make_license_info("MIT OR Apache-2.0")
        result = classify_license(info)
        assert result.declared_license == "MIT OR Apache-2.0"

    def test_dual_license_both_unknown(self) -> None:
        """If both sides of OR are unknown, result should be UNKNOWN."""
        info = _make_license_info("CustomA OR CustomB")
        result = classify_license(info)
        assert result.category == LicenseCategory.UNKNOWN


# ===========================================================================
# Edge case tests
# ===========================================================================


class TestEdgeCases:
    """Tests for edge cases and special inputs."""

    def test_empty_string_classified_as_unknown(self) -> None:
        """An empty license string should be classified as UNKNOWN."""
        info = _make_license_info("")
        result = classify_license(info)
        assert result.category == LicenseCategory.UNKNOWN

    def test_none_license_classified_as_unknown(self) -> None:
        """A None declared_license should be classified as UNKNOWN."""
        info = LicenseInfo(package_name="test-package", declared_license=None)
        result = classify_license(info)
        assert result.category == LicenseCategory.UNKNOWN

    def test_classify_licenses_batch(self) -> None:
        """classify_licenses() should process a list of LicenseInfo objects."""
        infos = [
            _make_license_info("MIT"),
            _make_license_info("GPL-3.0-only"),
            _make_license_info("Unknown Thing"),
        ]
        results = classify_licenses(infos)

        assert results[0].category == LicenseCategory.PERMISSIVE
        assert results[1].category == LicenseCategory.STRONG_COPYLEFT
        assert results[2].category == LicenseCategory.UNKNOWN

    def test_classify_preserves_other_fields(self) -> None:
        """Classification should not overwrite fields other than spdx_id and category."""
        info = LicenseInfo(
            package_name="my-package",
            declared_license="MIT License",
            pypi_url="https://pypi.org/project/my-package/",
            source_url="https://github.com/user/my-package",
        )
        result = classify_license(info)
        assert result.package_name == "my-package"
        assert result.pypi_url == "https://pypi.org/project/my-package/"
        assert result.source_url == "https://github.com/user/my-package"
        assert result.spdx_id == "MIT"

    def test_recognizes_alternative_license_names(self) -> None:
        """Should match common alternative names (e.g., 'The MIT License')."""
        variations = [
            ("MIT", "MIT"),
            ("The MIT License", "MIT"),
            ("Apache License 2.0", "Apache-2.0"),
            ("Apache Software License", "Apache-2.0"),
            ("BSD License", "BSD-3-Clause"),
            ("GNU General Public License v3.0", "GPL-3.0-only"),
            ("GPLv3", "GPL-3.0-only"),
        ]
        for raw_name, expected_spdx in variations:
            info = _make_license_info(raw_name)
            result = classify_license(info)
            assert result.spdx_id == expected_spdx, (
                f"'{raw_name}' should match '{expected_spdx}', but got '{result.spdx_id}'"
            )


# ===========================================================================
# Dual-license case-insensitive OR tests
# ===========================================================================


class TestDualLicenseCaseInsensitive:
    """Tests that the OR operator in dual-license strings is case-insensitive."""

    def test_lowercase_or_splits_dual_license(self) -> None:
        """Lowercase 'or' should split a dual-license string and pick most permissive."""
        info = _make_license_info("MIT or Apache-2.0")
        result = classify_license(info)
        assert result.spdx_id == "MIT"
        assert result.category == LicenseCategory.PERMISSIVE

    def test_mixed_case_or_splits_dual_license(self) -> None:
        """Mixed case 'Or' should split a dual-license string and pick most permissive."""
        info = _make_license_info("MIT Or GPL-3.0-only")
        result = classify_license(info)
        assert result.spdx_id == "MIT"
        assert result.category == LicenseCategory.PERMISSIVE

    def test_uppercase_or_still_works(self) -> None:
        """Uppercase 'OR' (standard SPDX syntax) should still pick most permissive."""
        info = _make_license_info("MIT OR Apache-2.0")
        result = classify_license(info)
        assert result.spdx_id == "MIT"
        assert result.category == LicenseCategory.PERMISSIVE


# ===========================================================================
# Plus (+) suffix variant tests
# ===========================================================================


class TestPlusSuffixVariants:
    """Tests that the '+' suffix aliases map to the correct '-or-later' entries."""

    def test_gpl2_plus_matches_or_later(self) -> None:
        """'GPL-2.0+' should match the 'GPL-2.0-or-later' knowledge base entry."""
        info = _make_license_info("GPL-2.0+")
        result = classify_license(info)
        assert result.spdx_id == "GPL-2.0-or-later"
        assert result.category == LicenseCategory.STRONG_COPYLEFT

    def test_gpl3_plus_matches_or_later(self) -> None:
        """'GPL-3.0+' should match the 'GPL-3.0-or-later' knowledge base entry."""
        info = _make_license_info("GPL-3.0+")
        result = classify_license(info)
        assert result.spdx_id == "GPL-3.0-or-later"
        assert result.category == LicenseCategory.STRONG_COPYLEFT

    def test_lgpl21_plus_matches_or_later(self) -> None:
        """'LGPL-2.1+' should match the 'LGPL-2.1-or-later' knowledge base entry."""
        info = _make_license_info("LGPL-2.1+")
        result = classify_license(info)
        assert result.spdx_id == "LGPL-2.1-or-later"
        assert result.category == LicenseCategory.WEAK_COPYLEFT

    def test_lgpl3_plus_matches_or_later(self) -> None:
        """'LGPL-3.0+' should match the 'LGPL-3.0-or-later' knowledge base entry."""
        info = _make_license_info("LGPL-3.0+")
        result = classify_license(info)
        assert result.spdx_id == "LGPL-3.0-or-later"
        assert result.category == LicenseCategory.WEAK_COPYLEFT

    def test_agpl3_plus_matches_or_later(self) -> None:
        """'AGPL-3.0+' should match the 'AGPL-3.0-or-later' knowledge base entry."""
        info = _make_license_info("AGPL-3.0+")
        result = classify_license(info)
        assert result.spdx_id == "AGPL-3.0-or-later"
        assert result.category == LicenseCategory.STRONG_COPYLEFT


# ===========================================================================
# Space-in-name fallback matching tests
# ===========================================================================


class TestSpaceInLicenseName:
    """Tests that the space-collapsing fallback matches license name variants."""

    def test_gpl_space_v3_matches_gplv3(self) -> None:
        """'GPL v3' should match GPL-3.0-only via space-collapsing fallback."""
        info = _make_license_info("GPL v3")
        result = classify_license(info)
        assert result.spdx_id == "GPL-3.0-only"
        assert result.category == LicenseCategory.STRONG_COPYLEFT

    def test_gpl_space_v2_matches_gplv2(self) -> None:
        """'GPL v2' should match GPL-2.0-only via space-collapsing fallback."""
        info = _make_license_info("GPL v2")
        result = classify_license(info)
        assert result.spdx_id == "GPL-2.0-only"
        assert result.category == LicenseCategory.STRONG_COPYLEFT

    def test_lgpl_space_v3_matches(self) -> None:
        """'LGPL v3' should not crash (testing space-collapsing robustness)."""
        info = _make_license_info("LGPL v3")
        result = classify_license(info)
        # The space-collapsing fallback should find a match for "LGPLv3"
        assert result.spdx_id == "LGPL-3.0-only"
        assert result.category == LicenseCategory.WEAK_COPYLEFT


# ===========================================================================
# -or-later vs -only distinction tests
# ===========================================================================


class TestOrLaterVsOnly:
    """Tests that '-or-later' and '-only' variants produce different SPDX IDs."""

    def test_gpl2_only_and_or_later_are_different(self) -> None:
        """'GPL-2.0-only' and 'GPL-2.0-or-later' should produce distinct SPDX IDs."""
        only_info = _make_license_info("GPL-2.0-only")
        only_result = classify_license(only_info)
        assert only_result.spdx_id == "GPL-2.0-only"
        assert only_result.category == LicenseCategory.STRONG_COPYLEFT

        later_info = _make_license_info("GPL-2.0-or-later")
        later_result = classify_license(later_info)
        assert later_result.spdx_id == "GPL-2.0-or-later"
        assert later_result.category == LicenseCategory.STRONG_COPYLEFT

        assert only_result.spdx_id != later_result.spdx_id

    def test_gpl3_only_and_or_later_are_different(self) -> None:
        """'GPL-3.0-only' and 'GPL-3.0-or-later' should produce distinct SPDX IDs."""
        only_info = _make_license_info("GPL-3.0-only")
        only_result = classify_license(only_info)
        assert only_result.spdx_id == "GPL-3.0-only"
        assert only_result.category == LicenseCategory.STRONG_COPYLEFT

        later_info = _make_license_info("GPL-3.0-or-later")
        later_result = classify_license(later_info)
        assert later_result.spdx_id == "GPL-3.0-or-later"
        assert later_result.category == LicenseCategory.STRONG_COPYLEFT

        assert only_result.spdx_id != later_result.spdx_id

    def test_lgpl21_only_and_or_later_are_different(self) -> None:
        """'LGPL-2.1-only' and 'LGPL-2.1-or-later' should produce distinct SPDX IDs."""
        only_info = _make_license_info("LGPL-2.1-only")
        only_result = classify_license(only_info)
        assert only_result.spdx_id == "LGPL-2.1-only"
        assert only_result.category == LicenseCategory.WEAK_COPYLEFT

        later_info = _make_license_info("LGPL-2.1-or-later")
        later_result = classify_license(later_info)
        assert later_result.spdx_id == "LGPL-2.1-or-later"
        assert later_result.category == LicenseCategory.WEAK_COPYLEFT

        assert only_result.spdx_id != later_result.spdx_id

    def test_agpl3_only_and_or_later_are_different(self) -> None:
        """'AGPL-3.0-only' and 'AGPL-3.0-or-later' should produce distinct SPDX IDs."""
        only_info = _make_license_info("AGPL-3.0-only")
        only_result = classify_license(only_info)
        assert only_result.spdx_id == "AGPL-3.0-only"
        assert only_result.category == LicenseCategory.STRONG_COPYLEFT

        later_info = _make_license_info("AGPL-3.0-or-later")
        later_result = classify_license(later_info)
        assert later_result.spdx_id == "AGPL-3.0-or-later"
        assert later_result.category == LicenseCategory.STRONG_COPYLEFT

        assert only_result.spdx_id != later_result.spdx_id


# ===========================================================================
# New license recognition tests
# ===========================================================================


class TestNewLicenses:
    """Tests that newly added licenses are correctly recognized and categorized."""

    def test_sspl_classified_as_proprietary(self) -> None:
        """SSPL-1.0 should be classified as proprietary (not OSI-approved)."""
        info = _make_license_info("SSPL-1.0")
        result = classify_license(info)
        assert result.spdx_id == "SSPL-1.0"
        assert result.category == LicenseCategory.PROPRIETARY

    def test_elastic_classified_as_proprietary(self) -> None:
        """Elastic-2.0 should be classified as proprietary (not OSI-approved)."""
        info = _make_license_info("Elastic-2.0")
        result = classify_license(info)
        assert result.spdx_id == "Elastic-2.0"
        assert result.category == LicenseCategory.PROPRIETARY

    def test_bsl11_classified_as_proprietary(self) -> None:
        """BSL-1.1 (Business Source License) should be classified as proprietary."""
        info = _make_license_info("BSL-1.1")
        result = classify_license(info)
        assert result.spdx_id == "BSL-1.1"
        assert result.category == LicenseCategory.PROPRIETARY

    def test_cddl_classified_as_weak_copyleft(self) -> None:
        """CDDL-1.0 should be classified as weak copyleft (file-level copyleft)."""
        info = _make_license_info("CDDL-1.0")
        result = classify_license(info)
        assert result.spdx_id == "CDDL-1.0"
        assert result.category == LicenseCategory.WEAK_COPYLEFT

    def test_boost_classified_as_permissive(self) -> None:
        """BSL-1.0 (Boost Software License) should be classified as permissive."""
        info = _make_license_info("BSL-1.0")
        result = classify_license(info)
        assert result.spdx_id == "BSL-1.0"
        assert result.category == LicenseCategory.PERMISSIVE


# ===========================================================================
# Missing license recognition tests
# ===========================================================================


class TestMissingLicenses:
    """Tests that previously-missing licenses are now correctly recognized.

    These licenses are used by real-world packages but were missing from
    the knowledge base, causing them to be classified as UNKNOWN (critical
    risk) — a false alarm. Each test verifies that the license is now
    recognized and placed in the correct category.
    """

    def test_python_2_0_classified_as_permissive(self) -> None:
        """Python-2.0 (used by CPython) should be classified as permissive."""
        info = _make_license_info("Python-2.0")
        result = classify_license(info)
        assert result.spdx_id == "Python-2.0"
        assert result.category == LicenseCategory.PERMISSIVE

    def test_hpnd_classified_as_permissive(self) -> None:
        """HPND (Historical Permission Notice and Disclaimer) should be permissive."""
        info = _make_license_info("HPND")
        result = classify_license(info)
        assert result.spdx_id == "HPND"
        assert result.category == LicenseCategory.PERMISSIVE

    def test_mit_0_classified_as_permissive(self) -> None:
        """MIT-0 (MIT No Attribution) should be classified as permissive."""
        info = _make_license_info("MIT-0")
        result = classify_license(info)
        assert result.spdx_id == "MIT-0"
        assert result.category == LicenseCategory.PERMISSIVE

    def test_postgresql_classified_as_permissive(self) -> None:
        """PostgreSQL License should be classified as permissive."""
        info = _make_license_info("PostgreSQL")
        result = classify_license(info)
        assert result.spdx_id == "PostgreSQL"
        assert result.category == LicenseCategory.PERMISSIVE

    def test_unicode_dfs_2016_classified_as_permissive(self) -> None:
        """Unicode-DFS-2016 should be classified as permissive."""
        info = _make_license_info("Unicode-DFS-2016")
        result = classify_license(info)
        assert result.spdx_id == "Unicode-DFS-2016"
        assert result.category == LicenseCategory.PERMISSIVE


# ===========================================================================
# Conjunctive (AND) license tests
# ===========================================================================


class TestConjunctiveLicense:
    """Tests for conjunctive license handling with the SPDX AND operator.

    SPDX AND means you must comply with ALL listed licenses. The classifier
    picks the most restrictive as the primary and stores the rest in
    additional_spdx_ids.
    """

    def test_and_picks_most_restrictive_as_primary(self) -> None:
        """'PSF-2.0 AND BSD-3-Clause' should pick PSF-2.0 as primary (both permissive).

        When both are the same category, either could be primary. The important
        thing is that both are captured.
        """
        info = _make_license_info("PSF-2.0 AND BSD-3-Clause")
        result = classify_license(info)
        # Both are permissive, so primary is permissive
        assert result.category == LicenseCategory.PERMISSIVE
        assert result.spdx_id is not None
        # One should be primary, the other in additional
        all_ids = [result.spdx_id] + result.additional_spdx_ids
        assert "PSF-2.0" in all_ids
        assert "BSD-3-Clause" in all_ids

    def test_and_with_mixed_categories_picks_most_restrictive(self) -> None:
        """'MIT AND GPL-3.0-only' should pick GPL-3.0-only as primary (most restrictive)."""
        info = _make_license_info("MIT AND GPL-3.0-only")
        result = classify_license(info)
        # GPL-3.0 is strong copyleft (more restrictive than MIT's permissive)
        assert result.spdx_id == "GPL-3.0-only"
        assert result.category == LicenseCategory.STRONG_COPYLEFT
        # MIT should be in additional
        assert "MIT" in result.additional_spdx_ids

    def test_and_preserves_declared_license(self) -> None:
        """The original AND expression should be kept in declared_license."""
        info = _make_license_info("PSF-2.0 AND BSD-3-Clause")
        result = classify_license(info)
        assert result.declared_license == "PSF-2.0 AND BSD-3-Clause"

    def test_and_with_unknown_component(self) -> None:
        """If one AND component is unknown, it becomes the most restrictive.

        UNKNOWN has the highest restrictiveness rank, so it becomes primary.
        The known component is still captured in additional fields.
        """
        info = _make_license_info("MIT AND SomeCustomLicense")
        result = classify_license(info)
        # Unknown is most restrictive, so it becomes primary
        assert result.category == LicenseCategory.UNKNOWN
        # MIT should be in additional
        assert "MIT" in result.additional_spdx_ids

    def test_and_case_insensitive(self) -> None:
        """The AND operator should be case-insensitive."""
        info = _make_license_info("MIT and Apache-2.0")
        result = classify_license(info)
        assert result.category == LicenseCategory.PERMISSIVE
        all_ids = [result.spdx_id] + result.additional_spdx_ids
        assert "MIT" in all_ids
        assert "Apache-2.0" in all_ids

    def test_mixed_and_or_treated_as_unknown(self) -> None:
        """An expression with both AND and OR should be treated as UNKNOWN.

        Full SPDX expression parsing is deferred to v1.1.
        """
        info = _make_license_info("MIT AND Apache-2.0 OR GPL-3.0-only")
        result = classify_license(info)
        assert result.category == LicenseCategory.UNKNOWN


# ===========================================================================
# New license entries from legal review
# ===========================================================================


class TestLegalReviewLicenses:
    """Tests for licenses added based on legal review feedback.

    These verify that each new license is correctly recognized by its SPDX ID,
    alternative names, and placed in the right category.
    """

    def test_cc_by_nc_4_classified_as_non_software(self) -> None:
        """CC-BY-NC-4.0 should be classified as non_software."""
        info = _make_license_info("CC-BY-NC-4.0")
        result = classify_license(info)
        assert result.spdx_id == "CC-BY-NC-4.0"
        assert result.category == LicenseCategory.NON_SOFTWARE

    def test_cc_by_nc_4_alternative_name(self) -> None:
        """Creative Commons Attribution-NonCommercial 4.0 should match CC-BY-NC-4.0."""
        info = _make_license_info("Creative Commons Attribution-NonCommercial 4.0")
        result = classify_license(info)
        assert result.spdx_id == "CC-BY-NC-4.0"
        assert result.category == LicenseCategory.NON_SOFTWARE

    def test_cc_by_nc_sa_4_classified_as_non_software(self) -> None:
        """CC-BY-NC-SA-4.0 should be classified as non_software."""
        info = _make_license_info("CC-BY-NC-SA-4.0")
        result = classify_license(info)
        assert result.spdx_id == "CC-BY-NC-SA-4.0"
        assert result.category == LicenseCategory.NON_SOFTWARE

    def test_eupl_12_classified_as_strong_copyleft(self) -> None:
        """EUPL-1.2 should be classified as strong copyleft."""
        info = _make_license_info("EUPL-1.2")
        result = classify_license(info)
        assert result.spdx_id == "EUPL-1.2"
        assert result.category == LicenseCategory.STRONG_COPYLEFT

    def test_eupl_alternative_name(self) -> None:
        """European Union Public License 1.2 should match EUPL-1.2."""
        info = _make_license_info("European Union Public License 1.2")
        result = classify_license(info)
        assert result.spdx_id == "EUPL-1.2"
        assert result.category == LicenseCategory.STRONG_COPYLEFT

    def test_mpl_11_classified_as_weak_copyleft(self) -> None:
        """MPL-1.1 should be classified as weak copyleft."""
        info = _make_license_info("MPL-1.1")
        result = classify_license(info)
        assert result.spdx_id == "MPL-1.1"
        assert result.category == LicenseCategory.WEAK_COPYLEFT

    def test_artistic_10_classified_as_weak_copyleft(self) -> None:
        """Artistic-1.0 should be classified as weak copyleft."""
        info = _make_license_info("Artistic-1.0")
        result = classify_license(info)
        assert result.spdx_id == "Artistic-1.0"
        assert result.category == LicenseCategory.WEAK_COPYLEFT

    def test_artistic_10_alternative_name(self) -> None:
        """'The Artistic License' should match Artistic-1.0."""
        info = _make_license_info("The Artistic License")
        result = classify_license(info)
        assert result.spdx_id == "Artistic-1.0"
        assert result.category == LicenseCategory.WEAK_COPYLEFT

    def test_cpal_classified_as_weak_copyleft(self) -> None:
        """CPAL-1.0 should be classified as weak copyleft."""
        info = _make_license_info("CPAL-1.0")
        result = classify_license(info)
        assert result.spdx_id == "CPAL-1.0"
        assert result.category == LicenseCategory.WEAK_COPYLEFT


# ===========================================================================
# Ambiguous name matching tests
# ===========================================================================


class TestAmbiguousNameMatching:
    """Tests for the ambiguous name matching feature.

    Some license strings like "GNU General Public License" could refer to
    GPL-2.0 or GPL-3.0. The classifier matches these as a fallback to
    GPL-2.0-only and sets a classification_note warning about the ambiguity.
    """

    def test_ambiguous_gnu_gpl_matches_gpl2_with_note(self) -> None:
        """'GNU General Public License' should match GPL-2.0-only with a note.

        This is an ambiguous string that could mean GPL-2.0 or GPL-3.0.
        The classifier defaults to GPL-2.0-only (the older, more common
        version when no version is specified) and attaches a warning note.
        """
        info = _make_license_info("GNU General Public License")
        result = classify_license(info)
        assert result.spdx_id == "GPL-2.0-only"
        assert result.category == LicenseCategory.STRONG_COPYLEFT
        assert result.classification_note is not None
        assert "ambiguous" in result.classification_note.lower()

    def test_ambiguous_gnu_gpl_parenthetical_matches_with_note(self) -> None:
        """'GNU General Public License (GPL)' should match GPL-2.0-only with a note."""
        info = _make_license_info("GNU General Public License (GPL)")
        result = classify_license(info)
        assert result.spdx_id == "GPL-2.0-only"
        assert result.category == LicenseCategory.STRONG_COPYLEFT
        assert result.classification_note is not None

    def test_unambiguous_gpl3_has_no_classification_note(self) -> None:
        """'GNU General Public License v3.0' should match without a note.

        Version-specific names like "v3.0" are unambiguous and should NOT
        set a classification_note.
        """
        info = _make_license_info("GNU General Public License v3.0")
        result = classify_license(info)
        assert result.spdx_id == "GPL-3.0-only"
        assert result.category == LicenseCategory.STRONG_COPYLEFT
        assert result.classification_note is None

    def test_unambiguous_mit_has_no_classification_note(self) -> None:
        """MIT should match without a classification_note."""
        info = _make_license_info("MIT")
        result = classify_license(info)
        assert result.spdx_id == "MIT"
        assert result.classification_note is None
