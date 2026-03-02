"""
Tests for the knowledge base YAML files.

These tests validate that the YAML files in src/license_comply/knowledge/
parse correctly and contain the expected structure. This catches:
  - YAML syntax errors (bad indentation, missing quotes, etc.)
  - Missing required fields in license definitions
  - Mismatches between the YAML categories and our Python enums
  - Structural issues that would cause runtime errors later

Why test data files? Because YAML is easy to break with a small typo,
and these files are the foundation of the entire legal analysis. If a
license entry is malformed, the tool won't work correctly.
"""

import os

import yaml  # Third-party library for parsing YAML files

from license_comply.models import LicenseCategory, RiskLevel

# ---------------------------------------------------------------------------
# Helper: locate the knowledge base directory
# ---------------------------------------------------------------------------

# The knowledge files live inside the package: src/license_comply/knowledge/
# We use __file__ (the path to THIS test file) to navigate to them reliably,
# regardless of where pytest is run from.
KNOWLEDGE_DIR = os.path.join(
    os.path.dirname(__file__),  # tests/
    "..",  # project root
    "src",
    "license_comply",
    "knowledge",
)


def _load_yaml(filename: str) -> dict:
    """Load and parse a YAML file from the knowledge directory.

    Args:
        filename: The name of the YAML file (e.g., "licenses.yaml").

    Returns:
        The parsed YAML content as a Python dictionary.
    """
    filepath = os.path.join(KNOWLEDGE_DIR, filename)
    with open(filepath, "r", encoding="utf-8") as file:
        return yaml.safe_load(file)


# ===========================================================================
# Tests for licenses.yaml
# ===========================================================================


class TestLicensesYaml:
    """Tests that licenses.yaml is well-formed and complete."""

    def test_licenses_yaml_parses_successfully(self) -> None:
        """The YAML file should parse without any syntax errors."""
        data = _load_yaml("licenses.yaml")
        assert data is not None, "licenses.yaml parsed to None (empty file?)"

    def test_licenses_yaml_has_licenses_key(self) -> None:
        """The top-level key should be 'licenses' containing a list."""
        data = _load_yaml("licenses.yaml")
        assert "licenses" in data, "Missing top-level 'licenses' key"
        assert isinstance(data["licenses"], list), "'licenses' should be a list"

    def test_licenses_yaml_has_expected_count(self) -> None:
        """We should have all 36 licenses defined.

        Original 20 licenses + LGPL-2.1 = 21, plus 5 new -or-later variants
        (LGPL-2.1-or-later, LGPL-3.0-or-later, GPL-3.0-or-later,
        GPL-2.0-or-later, AGPL-3.0-or-later) and 5 new licenses (CDDL-1.0,
        BSL-1.0, SSPL-1.0, Elastic-2.0, BSL-1.1) = 31, plus 5 more
        (Python-2.0, HPND, MIT-0, PostgreSQL, Unicode-DFS-2016) = 36,
        plus 6 from legal review (CC-BY-NC-4.0, CC-BY-NC-SA-4.0, EUPL-1.2,
        MPL-1.1, Artistic-1.0, CPAL-1.0) = 42 total.
        """
        data = _load_yaml("licenses.yaml")
        licenses = data["licenses"]
        assert len(licenses) == 42, (
            f"Expected 42 license definitions, found {len(licenses)}. "
            "Did you add or remove a license?"
        )

    def test_each_license_has_required_fields(self) -> None:
        """Every license entry must have all six required fields."""
        data = _load_yaml("licenses.yaml")
        required_fields = {"spdx_id", "names", "category", "summary", "obligations", "risks"}

        for license_entry in data["licenses"]:
            spdx_id = license_entry.get("spdx_id", "<missing spdx_id>")
            missing = required_fields - set(license_entry.keys())
            assert not missing, f"License '{spdx_id}' is missing required fields: {missing}"

    def test_each_license_has_valid_category(self) -> None:
        """Every license category must match one of our LicenseCategory enum values."""
        data = _load_yaml("licenses.yaml")
        # Build the set of valid category strings from our Python enum
        valid_categories = {category.value for category in LicenseCategory}
        # We exclude UNKNOWN — it's for unrecognized licenses, not used in the YAML.
        # PROPRIETARY is now used for source-available licenses like SSPL, Elastic, BSL-1.1.
        yaml_valid_categories = valid_categories - {"unknown"}

        for license_entry in data["licenses"]:
            spdx_id = license_entry["spdx_id"]
            category = license_entry["category"]
            assert category in yaml_valid_categories, (
                f"License '{spdx_id}' has invalid category '{category}'. "
                f"Valid categories: {sorted(yaml_valid_categories)}"
            )

    def test_names_are_lists_of_strings(self) -> None:
        """The 'names' field should be a list of strings (not a single string)."""
        data = _load_yaml("licenses.yaml")

        for license_entry in data["licenses"]:
            spdx_id = license_entry["spdx_id"]
            names = license_entry["names"]
            assert isinstance(names, list), (
                f"License '{spdx_id}': 'names' should be a list, got {type(names).__name__}"
            )
            assert len(names) >= 1, f"License '{spdx_id}': 'names' list should not be empty"
            for name in names:
                assert isinstance(name, str), (
                    f"License '{spdx_id}': each name should be a string, got {type(name).__name__}"
                )

    def test_ambiguous_names_are_lists_when_present(self) -> None:
        """When ambiguous_names is present, it must be a list of strings.

        The classifier iterates over ambiguous_names with a for loop.
        If someone accidentally formats this as a bare string instead of a
        list, the loop would iterate over individual characters — producing
        silent incorrect behavior with no error.
        """
        data = _load_yaml("licenses.yaml")

        for license_entry in data["licenses"]:
            spdx_id = license_entry["spdx_id"]
            ambiguous_names = license_entry.get("ambiguous_names")
            if ambiguous_names is None:
                continue  # Field is optional — absence is fine
            assert isinstance(ambiguous_names, list), (
                f"License '{spdx_id}': 'ambiguous_names' must be a list, "
                f"got {type(ambiguous_names).__name__}"
            )
            for name in ambiguous_names:
                assert isinstance(name, str), (
                    f"License '{spdx_id}': each ambiguous name must be a string, "
                    f"got {type(name).__name__}"
                )

    def test_obligations_and_risks_are_lists(self) -> None:
        """The 'obligations' and 'risks' fields should be lists (can be empty)."""
        data = _load_yaml("licenses.yaml")

        for license_entry in data["licenses"]:
            spdx_id = license_entry["spdx_id"]
            assert isinstance(license_entry["obligations"], list), (
                f"License '{spdx_id}': 'obligations' should be a list"
            )
            assert isinstance(license_entry["risks"], list), (
                f"License '{spdx_id}': 'risks' should be a list"
            )

    def test_spdx_ids_are_unique(self) -> None:
        """No two licenses should have the same SPDX ID."""
        data = _load_yaml("licenses.yaml")
        spdx_ids = [entry["spdx_id"] for entry in data["licenses"]]
        duplicates = [spdx_id for spdx_id in spdx_ids if spdx_ids.count(spdx_id) > 1]
        assert not duplicates, f"Duplicate SPDX IDs found: {set(duplicates)}"

    def test_well_known_licenses_present(self) -> None:
        """The most common licenses should definitely be in the knowledge base."""
        data = _load_yaml("licenses.yaml")
        spdx_ids = {entry["spdx_id"] for entry in data["licenses"]}

        # These are the licenses you'll encounter in almost every Python project
        must_have = {"MIT", "Apache-2.0", "BSD-3-Clause", "GPL-3.0-only", "AGPL-3.0-only"}
        missing = must_have - spdx_ids
        assert not missing, f"Missing essential licenses: {missing}"

    def test_mit_is_permissive(self) -> None:
        """Sanity check: MIT should be classified as permissive."""
        data = _load_yaml("licenses.yaml")
        mit = next(
            (entry for entry in data["licenses"] if entry["spdx_id"] == "MIT"),
            None,
        )
        assert mit is not None, "MIT license not found in licenses.yaml"
        assert mit["category"] == "permissive"

    def test_gpl3_is_strong_copyleft(self) -> None:
        """Sanity check: GPL-3.0 should be classified as strong copyleft."""
        data = _load_yaml("licenses.yaml")
        gpl3 = next(
            (entry for entry in data["licenses"] if entry["spdx_id"] == "GPL-3.0-only"),
            None,
        )
        assert gpl3 is not None, "GPL-3.0-only license not found in licenses.yaml"
        assert gpl3["category"] == "strong_copyleft"


# ===========================================================================
# Tests for compatibility.yaml
# ===========================================================================


class TestCompatibilityYaml:
    """Tests that compatibility.yaml is well-formed and complete."""

    def test_compatibility_yaml_parses_successfully(self) -> None:
        """The YAML file should parse without any syntax errors."""
        data = _load_yaml("compatibility.yaml")
        assert data is not None, "compatibility.yaml parsed to None (empty file?)"

    def test_has_rules_key(self) -> None:
        """The file should have a top-level 'rules' key."""
        data = _load_yaml("compatibility.yaml")
        assert "rules" in data, "Missing top-level 'rules' key"

    def test_has_all_project_types(self) -> None:
        """Rules should cover all five project types from our ProjectType enum."""
        data = _load_yaml("compatibility.yaml")
        rules = data["rules"]

        expected_types = {
            "proprietary",
            "internal",
            "open-source-permissive",
            "open-source-copyleft",
            "saas",
        }
        actual_types = set(rules.keys())
        missing = expected_types - actual_types
        assert not missing, f"Missing project types in rules: {missing}"

    def test_each_project_type_covers_all_categories(self) -> None:
        """Every project type should have a rule for every license category."""
        data = _load_yaml("compatibility.yaml")

        # These are the categories used in compatibility rules.
        # All categories from the LicenseCategory enum except UNKNOWN
        # (which has special handling via the policy's unknown_license_action).
        expected_categories = {
            "permissive",
            "public_domain",
            "weak_copyleft",
            "strong_copyleft",
            "proprietary",
            "non_software",
            "unknown",
        }

        for project_type, category_rules in data["rules"].items():
            actual_categories = set(category_rules.keys())
            missing = expected_categories - actual_categories
            assert not missing, f"Project type '{project_type}' is missing rules for: {missing}"

    def test_all_risk_levels_are_valid(self) -> None:
        """Every risk level in the rules should match our RiskLevel enum."""
        data = _load_yaml("compatibility.yaml")
        valid_levels = {level.value for level in RiskLevel}

        for project_type, category_rules in data["rules"].items():
            for category, risk_level in category_rules.items():
                assert risk_level in valid_levels, (
                    f"Invalid risk level '{risk_level}' for "
                    f"{project_type}/{category}. Valid: {sorted(valid_levels)}"
                )

    def test_permissive_is_always_clean(self) -> None:
        """Sanity check: permissive licenses should be clean in every project type."""
        data = _load_yaml("compatibility.yaml")

        for project_type, category_rules in data["rules"].items():
            assert category_rules["permissive"] == "clean", (
                f"Permissive licenses should be 'clean' for {project_type}, "
                f"but got '{category_rules['permissive']}'"
            )

    def test_strong_copyleft_critical_in_proprietary(self) -> None:
        """Sanity check: strong copyleft should be critical in proprietary projects."""
        data = _load_yaml("compatibility.yaml")
        assert data["rules"]["proprietary"]["strong_copyleft"] == "critical"

    def test_has_special_rules(self) -> None:
        """The file should have special rules (at least AGPL overrides)."""
        data = _load_yaml("compatibility.yaml")
        assert "special_rules" in data, "Missing 'special_rules' key"
        assert isinstance(data["special_rules"], list), "'special_rules' should be a list"
        assert len(data["special_rules"]) >= 1, "Should have at least one special rule"

    def test_special_rules_have_required_fields(self) -> None:
        """Each special rule should have spdx_id, project_type, risk_level, and reason."""
        data = _load_yaml("compatibility.yaml")
        required_fields = {"spdx_id", "project_type", "risk_level", "reason"}

        for i, rule in enumerate(data["special_rules"]):
            missing = required_fields - set(rule.keys())
            assert not missing, f"Special rule #{i + 1} is missing fields: {missing}"

    def test_agpl_critical_in_saas(self) -> None:
        """The AGPL special rule should make it critical for SaaS projects."""
        data = _load_yaml("compatibility.yaml")
        agpl_saas_rules = [
            rule
            for rule in data["special_rules"]
            if rule["spdx_id"] == "AGPL-3.0-only" and rule["project_type"] == "saas"
        ]
        assert len(agpl_saas_rules) == 1, "Should have exactly one AGPL SaaS special rule"
        assert agpl_saas_rules[0]["risk_level"] == "critical"


# ===========================================================================
# Tests for default_policy.yaml
# ===========================================================================


class TestDefaultPolicyYaml:
    """Tests that default_policy.yaml is well-formed and complete."""

    def test_default_policy_yaml_parses_successfully(self) -> None:
        """The YAML file should parse without any syntax errors."""
        data = _load_yaml("default_policy.yaml")
        assert data is not None, "default_policy.yaml parsed to None (empty file?)"

    def test_has_policy_key(self) -> None:
        """The file should have a top-level 'policy' key."""
        data = _load_yaml("default_policy.yaml")
        assert "policy" in data, "Missing top-level 'policy' key"

    def test_has_required_policy_fields(self) -> None:
        """The policy should have name, description, allow, deny, review, and unknown action."""
        data = _load_yaml("default_policy.yaml")
        policy = data["policy"]
        required_fields = {
            "name",
            "description",
            "allow",
            "deny",
            "review",
            "unknown_license_action",
        }
        missing = required_fields - set(policy.keys())
        assert not missing, f"Policy is missing required fields: {missing}"

    def test_allow_deny_review_are_lists(self) -> None:
        """The allow, deny, and review fields should be lists of SPDX IDs."""
        data = _load_yaml("default_policy.yaml")
        policy = data["policy"]

        for field_name in ("allow", "deny", "review"):
            field_value = policy[field_name]
            assert isinstance(field_value, list), (
                f"'{field_name}' should be a list, got {type(field_value).__name__}"
            )
            for item in field_value:
                assert isinstance(item, str), (
                    f"Each item in '{field_name}' should be a string, got {type(item).__name__}"
                )

    def test_mit_in_allow_list(self) -> None:
        """Sanity check: MIT should be in the default allow list."""
        data = _load_yaml("default_policy.yaml")
        assert "MIT" in data["policy"]["allow"]

    def test_sspl_in_deny_list(self) -> None:
        """Sanity check: SSPL should be in the default deny list.

        AGPL was moved out of the deny list — it's now handled by the
        compatibility matrix per project type. SSPL remains because it's
        a proprietary/source-available license blocked unconditionally.
        """
        data = _load_yaml("default_policy.yaml")
        assert "SSPL-1.0" in data["policy"]["deny"]

    def test_no_overlap_between_allow_deny_review(self) -> None:
        """A license should not appear in more than one list — that would be contradictory."""
        data = _load_yaml("default_policy.yaml")
        policy = data["policy"]

        allow_set = set(policy["allow"])
        deny_set = set(policy["deny"])
        review_set = set(policy["review"])

        allow_deny = allow_set & deny_set
        assert not allow_deny, f"Licenses in both allow and deny: {allow_deny}"

        allow_review = allow_set & review_set
        assert not allow_review, f"Licenses in both allow and review: {allow_review}"

        deny_review = deny_set & review_set
        assert not deny_review, f"Licenses in both deny and review: {deny_review}"

    def test_unknown_license_action_is_valid(self) -> None:
        """The unknown_license_action should be a valid risk level."""
        data = _load_yaml("default_policy.yaml")
        action = data["policy"]["unknown_license_action"]
        valid_actions = {"critical", "warning", "notice"}
        assert action in valid_actions, (
            f"unknown_license_action '{action}' is not valid. "
            f"Must be one of: {sorted(valid_actions)}"
        )

    def test_all_policy_spdx_ids_exist_in_licenses_yaml(self) -> None:
        """Every SPDX ID in the policy should correspond to a license in licenses.yaml.

        This cross-file validation ensures the policy doesn't reference
        licenses that the tool doesn't know about.
        """
        licenses_data = _load_yaml("licenses.yaml")
        policy_data = _load_yaml("default_policy.yaml")

        known_spdx_ids = {entry["spdx_id"] for entry in licenses_data["licenses"]}
        policy = policy_data["policy"]

        all_policy_ids = set(policy["allow"]) | set(policy["deny"]) | set(policy["review"])
        unknown_ids = all_policy_ids - known_spdx_ids
        assert not unknown_ids, (
            f"Policy references unknown SPDX IDs: {unknown_ids}. "
            "These must be defined in licenses.yaml."
        )
