"""
Tests for the utils module (shared helper functions).

These tests verify that our utility functions correctly:
  - Resolve paths to bundled knowledge base and template files
  - Load and parse YAML files safely
  - Produce friendly error messages when things go wrong

We use pytest's `tmp_path` fixture to create temporary files for testing.
This is a built-in pytest feature that gives each test its own temporary
directory, automatically cleaned up after the test finishes.
"""

import os

import pytest

from license_comply.utils import (
    get_knowledge_path,
    get_template_path,
    load_knowledge,
    load_yaml,
    normalize_package_name,
)

# ===========================================================================
# Tests for get_knowledge_path()
# ===========================================================================


class TestGetKnowledgePath:
    """Tests for resolving paths to knowledge base files."""

    def test_returns_path_for_existing_file(self) -> None:
        """Should return the full path when the file exists."""
        path = get_knowledge_path("licenses.yaml")
        assert os.path.isfile(path), f"Path should point to a real file: {path}"

    def test_path_ends_with_correct_filename(self) -> None:
        """The returned path should end with the requested filename."""
        path = get_knowledge_path("licenses.yaml")
        assert path.endswith("licenses.yaml")

    def test_path_contains_knowledge_directory(self) -> None:
        """The path should include the 'knowledge' directory."""
        path = get_knowledge_path("licenses.yaml")
        assert "knowledge" in path

    def test_works_for_all_knowledge_files(self) -> None:
        """All three knowledge base files should be resolvable."""
        for filename in ("licenses.yaml", "compatibility.yaml", "default_policy.yaml"):
            path = get_knowledge_path(filename)
            assert os.path.isfile(path), f"File not found: {filename}"

    def test_raises_for_nonexistent_file(self) -> None:
        """Should raise FileNotFoundError with a helpful message for missing files."""
        with pytest.raises(FileNotFoundError, match="Knowledge base file not found"):
            get_knowledge_path("does_not_exist.yaml")

    def test_error_message_includes_hint(self) -> None:
        """The error message should include a hint about reinstalling."""
        with pytest.raises(FileNotFoundError, match="pip install"):
            get_knowledge_path("nonexistent.yaml")


# ===========================================================================
# Tests for get_template_path()
# ===========================================================================


class TestGetTemplatePath:
    """Tests for resolving paths to template files."""

    def test_raises_for_nonexistent_template(self) -> None:
        """Should raise FileNotFoundError for missing templates."""
        with pytest.raises(FileNotFoundError, match="Template file not found"):
            get_template_path("does_not_exist.jinja2")

    def test_path_contains_templates_directory(self) -> None:
        """Template paths should include the 'templates' directory."""
        # Verify the path
        # points to the correct location inside the templates directory.
        path = get_template_path("report.md.jinja2")
        assert "templates" in path
        assert os.path.exists(path)


# ===========================================================================
# Tests for load_yaml()
# ===========================================================================


class TestLoadYaml:
    """Tests for YAML file loading and parsing."""

    def test_loads_valid_yaml_file(self, tmp_path: os.PathLike) -> None:
        """Should parse a valid YAML file into a Python dictionary."""
        # Create a temporary YAML file with known content
        yaml_file = tmp_path / "test.yaml"
        yaml_file.write_text("name: test\nvalue: 42\n")

        result = load_yaml(str(yaml_file))

        assert result == {"name": "test", "value": 42}

    def test_loads_nested_yaml(self, tmp_path: os.PathLike) -> None:
        """Should handle nested YAML structures (dicts within dicts)."""
        yaml_file = tmp_path / "nested.yaml"
        yaml_file.write_text("parent:\n  child: value\n  list:\n    - one\n    - two\n")

        result = load_yaml(str(yaml_file))

        assert result["parent"]["child"] == "value"
        assert result["parent"]["list"] == ["one", "two"]

    def test_raises_for_missing_file(self) -> None:
        """Should raise FileNotFoundError with a clear message."""
        with pytest.raises(FileNotFoundError, match="YAML file not found"):
            load_yaml("/nonexistent/path/to/file.yaml")

    def test_raises_for_invalid_yaml_syntax(self, tmp_path: os.PathLike) -> None:
        """Should raise ValueError for files with bad YAML syntax."""
        yaml_file = tmp_path / "bad.yaml"
        # Invalid YAML: a colon in an unquoted value causes a parse error
        yaml_file.write_text("key: [unclosed bracket\n")

        with pytest.raises(ValueError, match="Invalid YAML syntax"):
            load_yaml(str(yaml_file))

    def test_raises_for_empty_file(self, tmp_path: os.PathLike) -> None:
        """Should raise ValueError for an empty YAML file."""
        yaml_file = tmp_path / "empty.yaml"
        yaml_file.write_text("")

        with pytest.raises(ValueError, match="empty"):
            load_yaml(str(yaml_file))

    def test_raises_for_non_dict_yaml(self, tmp_path: os.PathLike) -> None:
        """Should raise ValueError if the YAML root is a list instead of a dict."""
        yaml_file = tmp_path / "list.yaml"
        yaml_file.write_text("- item1\n- item2\n")

        with pytest.raises(ValueError, match="unexpected format"):
            load_yaml(str(yaml_file))

    def test_error_message_includes_filepath(self, tmp_path: os.PathLike) -> None:
        """Error messages should include the file path for debugging."""
        yaml_file = tmp_path / "bad.yaml"
        yaml_file.write_text("")

        with pytest.raises(ValueError, match="bad.yaml"):
            load_yaml(str(yaml_file))


# ===========================================================================
# Tests for load_knowledge()
# ===========================================================================


class TestLoadKnowledge:
    """Tests for the convenience function that loads knowledge base files."""

    def test_loads_licenses_yaml(self) -> None:
        """Should successfully load and parse licenses.yaml."""
        data = load_knowledge("licenses.yaml")
        assert "licenses" in data
        assert isinstance(data["licenses"], list)

    def test_loads_compatibility_yaml(self) -> None:
        """Should successfully load and parse compatibility.yaml."""
        data = load_knowledge("compatibility.yaml")
        assert "rules" in data

    def test_loads_default_policy_yaml(self) -> None:
        """Should successfully load and parse default_policy.yaml."""
        data = load_knowledge("default_policy.yaml")
        assert "policy" in data

    def test_raises_for_nonexistent_knowledge_file(self) -> None:
        """Should raise FileNotFoundError for files not in the knowledge directory."""
        with pytest.raises(FileNotFoundError):
            load_knowledge("nonexistent.yaml")


# ===========================================================================
# Tests for normalize_package_name()
# ===========================================================================


class TestNormalizePackageName:
    """Tests for PEP 503 package name normalization.

    PyPI treats hyphens, underscores, and dots as equivalent in package names,
    and comparisons are case-insensitive. This normalization function ensures
    we can reliably match names from different sources (dependency files vs
    installed packages).
    """

    def test_hyphens_become_underscores(self) -> None:
        """Hyphens should be converted to underscores."""
        assert normalize_package_name("charset-normalizer") == "charset_normalizer"

    def test_dots_become_underscores(self) -> None:
        """Dots should be converted to underscores."""
        assert normalize_package_name("zope.interface") == "zope_interface"

    def test_uppercase_becomes_lowercase(self) -> None:
        """Names should be lowercased."""
        assert normalize_package_name("Jinja2") == "jinja2"

    def test_mixed_separators_and_case(self) -> None:
        """Should handle all transformations at once."""
        assert normalize_package_name("My-Cool.Package") == "my_cool_package"

    def test_already_normalized_name_unchanged(self) -> None:
        """A name that's already normalized should pass through unchanged."""
        assert normalize_package_name("requests") == "requests"

    def test_multiple_hyphens(self) -> None:
        """Multiple consecutive or scattered hyphens should all be converted."""
        assert normalize_package_name("my-cool-package") == "my_cool_package"

    def test_consecutive_separators_collapsed(self) -> None:
        """Runs of separators should collapse to a single underscore (PEP 503)."""
        assert normalize_package_name("my--package") == "my_package"
        assert normalize_package_name("my.-package") == "my_package"
        assert normalize_package_name("my_.package") == "my_package"

    def test_underscores_remain_underscores(self) -> None:
        """Underscores are the canonical separator — should be unchanged."""
        assert normalize_package_name("my_package") == "my_package"

    def test_consecutive_underscores_collapsed(self) -> None:
        """Double underscores should collapse to a single underscore."""
        assert normalize_package_name("my__package") == "my_package"
