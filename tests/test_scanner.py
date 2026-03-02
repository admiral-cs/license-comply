"""
Tests for the scanner module (dependency file reader).

These tests verify that the scanner correctly reads and parses both
pyproject.toml and requirements.txt files, extracting package names
and version specifiers into PackageInfo objects.

We use pytest's `tmp_path` fixture to create temporary project directories
with sample dependency files. This keeps tests isolated — each test gets
its own fresh temporary directory.
"""

import os
from unittest.mock import MagicMock, patch

import pytest

from license_comply.models import PackageInfo
from license_comply.scanner import find_dependency_file, scan_dependencies, scan_installed_packages

# ===========================================================================
# Tests for find_dependency_file()
# ===========================================================================


class TestFindDependencyFile:
    """Tests for auto-detecting the dependency file in a project."""

    def test_finds_pyproject_toml(self, tmp_path: os.PathLike) -> None:
        """Should find pyproject.toml when it exists."""
        (tmp_path / "pyproject.toml").write_text("[project]\n")
        result = find_dependency_file(str(tmp_path))
        assert result.endswith("pyproject.toml")

    def test_finds_requirements_txt(self, tmp_path: os.PathLike) -> None:
        """Should find requirements.txt when pyproject.toml doesn't exist."""
        (tmp_path / "requirements.txt").write_text("requests\n")
        result = find_dependency_file(str(tmp_path))
        assert result.endswith("requirements.txt")

    def test_prefers_pyproject_toml_over_requirements_txt(self, tmp_path: os.PathLike) -> None:
        """When both files exist, should prefer pyproject.toml (modern standard)."""
        (tmp_path / "pyproject.toml").write_text("[project]\n")
        (tmp_path / "requirements.txt").write_text("requests\n")
        result = find_dependency_file(str(tmp_path))
        assert result.endswith("pyproject.toml")

    def test_uses_explicit_file_when_given(self, tmp_path: os.PathLike) -> None:
        """The --file flag should override auto-detection."""
        custom_file = tmp_path / "deps.txt"
        custom_file.write_text("flask\n")
        result = find_dependency_file(str(tmp_path), explicit_file=str(custom_file))
        assert result.endswith("deps.txt")

    def test_raises_clear_error_for_missing_file(self, tmp_path: os.PathLike) -> None:
        """Should raise FileNotFoundError with a helpful message."""
        with pytest.raises(FileNotFoundError, match="Could not find"):
            find_dependency_file(str(tmp_path))

    def test_raises_for_nonexistent_explicit_file(self) -> None:
        """Should raise FileNotFoundError when --file points to a missing file."""
        with pytest.raises(FileNotFoundError, match="Dependency file not found"):
            find_dependency_file(".", explicit_file="/nonexistent/deps.txt")


# ===========================================================================
# Tests for requirements.txt parsing
# ===========================================================================


class TestRequirementsTxtParsing:
    """Tests for parsing requirements.txt files."""

    def test_reads_simple_requirements_file(self, tmp_path: os.PathLike) -> None:
        """Should parse a basic requirements file with one package per line."""
        req_file = tmp_path / "requirements.txt"
        req_file.write_text("requests\nflask\nclick\n")

        packages = scan_dependencies(str(req_file))

        names = [p.name for p in packages]
        assert names == ["requests", "flask", "click"]

    def test_handles_version_specifiers(self, tmp_path: os.PathLike) -> None:
        """Should extract version specifiers from pinned dependencies."""
        req_file = tmp_path / "requirements.txt"
        req_file.write_text("requests==2.31.0\nflask>=3.0.0\nclick>=8.0,<9.0\n")

        packages = scan_dependencies(str(req_file))

        assert packages[0] == PackageInfo(name="requests", version_spec="==2.31.0")
        assert packages[1] == PackageInfo(name="flask", version_spec=">=3.0.0")
        assert packages[2] == PackageInfo(name="click", version_spec=">=8.0,<9.0")

    def test_ignores_comments_and_blank_lines(self, tmp_path: os.PathLike) -> None:
        """Should skip lines starting with # and empty lines."""
        req_file = tmp_path / "requirements.txt"
        req_file.write_text("# This is a comment\n\nrequests\n  \n# Another comment\nflask\n")

        packages = scan_dependencies(str(req_file))

        names = [p.name for p in packages]
        assert names == ["requests", "flask"]

    def test_handles_extras_syntax(self, tmp_path: os.PathLike) -> None:
        """Should handle packages with extras like requests[security]."""
        req_file = tmp_path / "requirements.txt"
        req_file.write_text("requests[security]>=2.0\ncelery[redis]\n")

        packages = scan_dependencies(str(req_file))

        # The extras are stripped — we just need the package name
        assert packages[0].name == "requests"
        assert packages[0].version_spec == ">=2.0"
        assert packages[1].name == "celery"

    def test_handles_inline_comments(self, tmp_path: os.PathLike) -> None:
        """Should strip inline comments from dependency lines."""
        req_file = tmp_path / "requirements.txt"
        req_file.write_text("requests>=2.0  # HTTP library\nflask  # Web framework\n")

        packages = scan_dependencies(str(req_file))

        assert packages[0] == PackageInfo(name="requests", version_spec=">=2.0")
        assert packages[1] == PackageInfo(name="flask", version_spec=None)

    def test_follows_recursive_requirements(self, tmp_path: os.PathLike) -> None:
        """Should follow -r references to include packages from other files."""
        # Create the main requirements file that references another
        main_req = tmp_path / "requirements.txt"
        main_req.write_text("requests\n-r base.txt\n")

        # Create the referenced file
        base_req = tmp_path / "base.txt"
        base_req.write_text("flask\nclick\n")

        packages = scan_dependencies(str(main_req))

        names = [p.name for p in packages]
        assert "requests" in names
        assert "flask" in names
        assert "click" in names

    def test_ignores_non_dependency_flags(self, tmp_path: os.PathLike) -> None:
        """Should skip pip flags like --index-url and --trusted-host."""
        req_file = tmp_path / "requirements.txt"
        req_file.write_text(
            "--index-url https://pypi.org/simple\n"
            "--trusted-host pypi.org\n"
            "requests\n"
            "--extra-index-url https://private.pypi.com\n"
            "flask\n"
        )

        packages = scan_dependencies(str(req_file))

        names = [p.name for p in packages]
        assert names == ["requests", "flask"]

    def test_handles_circular_references_gracefully(self, tmp_path: os.PathLike) -> None:
        """Should not infinite-loop if two files reference each other."""
        file_a = tmp_path / "a.txt"
        file_b = tmp_path / "b.txt"
        file_a.write_text("requests\n-r b.txt\n")
        file_b.write_text("flask\n-r a.txt\n")

        # This should complete without hanging
        packages = scan_dependencies(str(file_a))

        names = [p.name for p in packages]
        assert "requests" in names
        assert "flask" in names


# ===========================================================================
# Tests for pyproject.toml parsing
# ===========================================================================


class TestPyprojectTomlParsing:
    """Tests for parsing pyproject.toml files."""

    def test_reads_pyproject_toml_dependencies(self, tmp_path: os.PathLike) -> None:
        """Should parse the [project.dependencies] list from pyproject.toml."""
        toml_file = tmp_path / "pyproject.toml"
        toml_file.write_text(
            "[project]\n"
            'name = "my-project"\n'
            "dependencies = [\n"
            '    "requests>=2.28.0",\n'
            '    "flask>=3.0.0",\n'
            '    "click",\n'
            "]\n"
        )

        packages = scan_dependencies(str(toml_file))

        assert packages[0] == PackageInfo(name="requests", version_spec=">=2.28.0")
        assert packages[1] == PackageInfo(name="flask", version_spec=">=3.0.0")
        assert packages[2] == PackageInfo(name="click", version_spec=None)

    def test_handles_environment_markers(self, tmp_path: os.PathLike) -> None:
        """Should strip environment markers (e.g., ; python_version < '3.11')."""
        toml_file = tmp_path / "pyproject.toml"
        toml_file.write_text(
            "[project]\ndependencies = [\n    \"tomli>=2.0; python_version < '3.11'\",\n]\n"
        )

        packages = scan_dependencies(str(toml_file))

        assert packages[0].name == "tomli"
        assert packages[0].version_spec == ">=2.0"

    def test_returns_empty_list_when_no_dependencies(self, tmp_path: os.PathLike) -> None:
        """Should return an empty list if [project.dependencies] is missing."""
        toml_file = tmp_path / "pyproject.toml"
        toml_file.write_text('[project]\nname = "empty-project"\n')

        packages = scan_dependencies(str(toml_file))

        assert packages == []

    def test_handles_extras_in_pyproject(self, tmp_path: os.PathLike) -> None:
        """Should handle packages with extras like requests[security]."""
        toml_file = tmp_path / "pyproject.toml"
        toml_file.write_text('[project]\ndependencies = [\n    "requests[security]>=2.0",\n]\n')

        packages = scan_dependencies(str(toml_file))

        assert packages[0].name == "requests"
        assert packages[0].version_spec == ">=2.0"


# ===========================================================================
# Tests for edge cases and error handling
# ===========================================================================


class TestScannerEdgeCases:
    """Tests for error handling and unusual inputs."""

    def test_raises_for_nonexistent_file(self) -> None:
        """Should raise FileNotFoundError for a missing file."""
        with pytest.raises(FileNotFoundError, match="Dependency file not found"):
            scan_dependencies("/nonexistent/requirements.txt")

    def test_raises_for_unsupported_format(self, tmp_path: os.PathLike) -> None:
        """Should raise ValueError for unsupported file formats."""
        json_file = tmp_path / "deps.json"
        json_file.write_text("{}")

        with pytest.raises(ValueError, match="Unsupported dependency file format"):
            scan_dependencies(str(json_file))

    def test_empty_requirements_returns_empty_list(self, tmp_path: os.PathLike) -> None:
        """Should return an empty list for an empty requirements file."""
        req_file = tmp_path / "requirements.txt"
        req_file.write_text("")

        packages = scan_dependencies(str(req_file))

        assert packages == []


# ===========================================================================
# Tests for URL-based requirements in requirements.txt
# ===========================================================================


class TestUrlRequirements:
    """Tests for parsing URL-based requirements (git+, svn+, https, etc.).

    Some requirements.txt files contain direct URLs to package sources
    instead of PyPI package names. The scanner should extract the package
    name from the #egg= fragment, or silently skip the line if no egg
    fragment is present.
    """

    def test_url_with_egg_fragment_extracts_package_name(self, tmp_path: os.PathLike) -> None:
        """A git+https URL with #egg=mypackage should produce PackageInfo(name='mypackage')."""
        req_file = tmp_path / "requirements.txt"
        req_file.write_text("git+https://github.com/user/repo.git#egg=mypackage\n")

        packages = scan_dependencies(str(req_file))

        assert len(packages) == 1
        assert packages[0] == PackageInfo(name="mypackage")

    def test_url_without_egg_logs_warning_and_skips(self, tmp_path: os.PathLike) -> None:
        """A bare URL without #egg= should be silently dropped (empty list)."""
        req_file = tmp_path / "requirements.txt"
        req_file.write_text("https://example.com/package.tar.gz\n")

        packages = scan_dependencies(str(req_file))

        assert packages == []

    def test_mixed_url_and_regular_requirements(self, tmp_path: os.PathLike) -> None:
        """A file mixing regular packages and URL-based packages should parse all of them."""
        req_file = tmp_path / "requirements.txt"
        req_file.write_text("requests\ngit+https://github.com/user/repo.git#egg=mypkg\nflask\n")

        packages = scan_dependencies(str(req_file))

        names = [p.name for p in packages]
        assert len(names) == 3
        assert "requests" in names
        assert "mypkg" in names
        assert "flask" in names

    def test_svn_url_with_egg_fragment(self, tmp_path: os.PathLike) -> None:
        """An svn+ URL with #egg= should extract the package name correctly."""
        req_file = tmp_path / "requirements.txt"
        req_file.write_text("svn+http://example.com/repo#egg=svnpkg\n")

        packages = scan_dependencies(str(req_file))

        assert len(packages) == 1
        assert packages[0] == PackageInfo(name="svnpkg")


# ===========================================================================
# Tests for comment stripping in requirements.txt
# ===========================================================================


class TestCommentWithoutSpace:
    """Tests for stripping inline comments from requirement lines.

    The standard format is '# comment' with a space before the hash, but
    some files in the wild have comments without a preceding space. The
    scanner handles both cases.
    """

    def test_comment_without_preceding_space(self, tmp_path: os.PathLike) -> None:
        """'requests>=2.0#comment' should parse as name='requests', version='>=2.0'."""
        req_file = tmp_path / "requirements.txt"
        req_file.write_text("requests>=2.0#comment\n")

        packages = scan_dependencies(str(req_file))

        assert len(packages) == 1
        assert packages[0].name == "requests"
        assert packages[0].version_spec == ">=2.0"

    def test_comment_with_space_still_works(self, tmp_path: os.PathLike) -> None:
        """'requests>=2.0 # comment' should still parse correctly (standard format)."""
        req_file = tmp_path / "requirements.txt"
        req_file.write_text("requests>=2.0 # comment\n")

        packages = scan_dependencies(str(req_file))

        assert len(packages) == 1
        assert packages[0].name == "requests"
        assert packages[0].version_spec == ">=2.0"


# ===========================================================================
# Tests for malformed pyproject.toml
# ===========================================================================


class TestMalformedToml:
    """Tests for handling invalid pyproject.toml files.

    When a pyproject.toml file contains invalid TOML syntax, the scanner
    should raise a ValueError with a helpful error message rather than
    letting the raw parser exception bubble up.
    """

    def test_invalid_toml_raises_value_error(self, tmp_path: os.PathLike) -> None:
        """Invalid TOML syntax should raise ValueError with a helpful message."""
        toml_file = tmp_path / "pyproject.toml"
        # Write intentionally broken TOML (unclosed bracket, bad syntax)
        toml_file.write_text("[project\nname = broken toml!!!\n")

        with pytest.raises(ValueError, match="Could not parse pyproject.toml"):
            scan_dependencies(str(toml_file))


# ===========================================================================
# Tests for scan_installed_packages() — virtual environment scanning
# ===========================================================================


def _make_mock_distribution(name: str) -> MagicMock:
    """Create a mock Distribution object with a given package name.

    importlib.metadata.distributions() returns Distribution objects that
    have a .metadata property (an email.Message-like object). We mock
    the .metadata.get("Name") call to return the desired package name.
    """
    dist = MagicMock()
    dist.metadata = {"Name": name}
    return dist


class TestScanInstalledPackages:
    """Tests for scanning installed packages from a virtual environment.

    These tests use mocking to simulate different venv configurations
    without actually creating or activating real virtual environments.
    """

    def test_returns_empty_when_no_venv_found(self, tmp_path: os.PathLike) -> None:
        """When no .venv or venv directory exists and no venv is active, return []."""
        # tmp_path is an empty directory — no venv to find
        with patch("license_comply.scanner.sys") as mock_sys:
            # Simulate no active venv (prefix == base_prefix)
            mock_sys.prefix = "/usr/local"
            mock_sys.base_prefix = "/usr/local"
            mock_sys.version_info = (3, 11, 0)

            result = scan_installed_packages(str(tmp_path))

        assert result == []

    def test_detects_active_venv(self, tmp_path: os.PathLike) -> None:
        """When a venv is active (sys.prefix != sys.base_prefix), scan it."""
        # Create a fake site-packages directory at the active venv prefix
        venv_dir = tmp_path / "fake_venv"
        site_packages = venv_dir / "lib" / "python3.11" / "site-packages"
        site_packages.mkdir(parents=True)

        mock_dists = [
            _make_mock_distribution("requests"),
            _make_mock_distribution("urllib3"),
        ]

        with (
            patch("license_comply.scanner.sys") as mock_sys,
            patch("license_comply.scanner.importlib.metadata.distributions") as mock_distributions,
        ):
            # Simulate an active venv
            mock_sys.prefix = str(venv_dir)
            mock_sys.base_prefix = "/usr/local"
            mock_sys.version_info = (3, 11, 0)
            mock_distributions.return_value = mock_dists

            result = scan_installed_packages(str(tmp_path))

        names = [p.name for p in result]
        assert "requests" in names
        assert "urllib3" in names

    def test_excludes_project_itself(self, tmp_path: os.PathLike) -> None:
        """The project's own package (from pip install -e .) should be excluded."""
        # Create pyproject.toml with a project name
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text('[project]\nname = "my-cool-project"\n')

        # Create a .venv with pyvenv.cfg
        dot_venv = tmp_path / ".venv"
        dot_venv.mkdir()
        (dot_venv / "pyvenv.cfg").write_text("home = /usr/bin\n")
        site_packages = dot_venv / "lib" / "python3.11" / "site-packages"
        site_packages.mkdir(parents=True)

        mock_dists = [
            _make_mock_distribution("my-cool-project"),  # Should be excluded
            _make_mock_distribution("requests"),
        ]

        with (
            patch("license_comply.scanner.sys") as mock_sys,
            patch("license_comply.scanner.importlib.metadata.distributions") as mock_distributions,
        ):
            mock_sys.prefix = "/usr/local"
            mock_sys.base_prefix = "/usr/local"
            mock_sys.version_info = (3, 11, 0)
            mock_distributions.return_value = mock_dists

            result = scan_installed_packages(str(tmp_path))

        names = [p.name for p in result]
        assert "my-cool-project" not in names
        assert "requests" in names

    def test_name_normalization_excludes_correctly(self, tmp_path: os.PathLike) -> None:
        """Normalization should handle name variants (e.g., hyphens vs underscores)."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text('[project]\nname = "charset-normalizer"\n')

        dot_venv = tmp_path / ".venv"
        dot_venv.mkdir()
        (dot_venv / "pyvenv.cfg").write_text("home = /usr/bin\n")
        site_packages = dot_venv / "lib" / "python3.11" / "site-packages"
        site_packages.mkdir(parents=True)

        mock_dists = [
            # PyPI might report it with underscores even though we listed hyphens
            _make_mock_distribution("charset_normalizer"),
            _make_mock_distribution("requests"),
        ]

        with (
            patch("license_comply.scanner.sys") as mock_sys,
            patch("license_comply.scanner.importlib.metadata.distributions") as mock_distributions,
        ):
            mock_sys.prefix = "/usr/local"
            mock_sys.base_prefix = "/usr/local"
            mock_sys.version_info = (3, 11, 0)
            mock_distributions.return_value = mock_dists

            result = scan_installed_packages(str(tmp_path))

        names = [p.name for p in result]
        # charset_normalizer should be excluded (matches charset-normalizer after normalization)
        assert "charset_normalizer" not in names
        assert "requests" in names

    def test_empty_venv_returns_empty_list(self, tmp_path: os.PathLike) -> None:
        """A venv with pyvenv.cfg but no installed packages should return []."""
        dot_venv = tmp_path / ".venv"
        dot_venv.mkdir()
        (dot_venv / "pyvenv.cfg").write_text("home = /usr/bin\n")
        site_packages = dot_venv / "lib" / "python3.11" / "site-packages"
        site_packages.mkdir(parents=True)

        with (
            patch("license_comply.scanner.sys") as mock_sys,
            patch("license_comply.scanner.importlib.metadata.distributions") as mock_distributions,
        ):
            mock_sys.prefix = "/usr/local"
            mock_sys.base_prefix = "/usr/local"
            mock_sys.version_info = (3, 11, 0)
            mock_distributions.return_value = []  # No distributions

            result = scan_installed_packages(str(tmp_path))

        assert result == []
