"""
Tests for the CLI module (command-line interface).

These tests verify that the CLI correctly parses arguments, runs the pipeline,
and produces the expected exit codes. We test the CLI by calling main()
directly with sys.argv mocked, rather than spawning subprocesses.
"""

from __future__ import annotations

import os
import sys
from unittest.mock import patch

import pytest
import responses

from license_comply.cli import main
from license_comply.models import PackageInfo

# ---------------------------------------------------------------------------
# Helper: build a fake PyPI response for mocking
# ---------------------------------------------------------------------------


def _mock_pypi(package_name: str, license_field: str = "MIT License") -> None:
    """Register a mock PyPI response for a package."""
    responses.add(
        responses.GET,
        f"https://pypi.org/pypi/{package_name}/json",
        json={
            "info": {
                "name": package_name,
                "license": license_field,
                "classifiers": [],
                "project_urls": {},
            },
        },
        status=200,
    )


# ===========================================================================
# Argument parsing tests
# ===========================================================================


class TestArgumentParsing:
    """Tests for CLI argument parsing and validation."""

    def test_version_flag(self, capsys) -> None:
        """--version should print the version and exit."""
        with patch.object(sys, "argv", ["license-comply", "--version"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 0

        output = capsys.readouterr().out
        assert "1.0.0" in output

    def test_missing_project_type_shows_error(self, capsys) -> None:
        """Running without --project-type should show a helpful error."""
        with patch.object(sys, "argv", ["license-comply", "."]):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 1

    def test_init_creates_policy_file(self, tmp_path) -> None:
        """--init should create a .license-comply-policy.yaml file."""
        original_dir = os.getcwd()
        try:
            os.chdir(str(tmp_path))
            with patch.object(sys, "argv", ["license-comply", "--init"]):
                with pytest.raises(SystemExit) as exc_info:
                    main()
                assert exc_info.value.code == 0

            assert (tmp_path / ".license-comply-policy.yaml").exists()
        finally:
            os.chdir(original_dir)

    def test_init_does_not_overwrite_existing(self, tmp_path, capsys) -> None:
        """--init should not overwrite an existing policy file."""
        original_dir = os.getcwd()
        try:
            os.chdir(str(tmp_path))
            (tmp_path / ".license-comply-policy.yaml").write_text("existing content")

            with patch.object(sys, "argv", ["license-comply", "--init"]):
                with pytest.raises(SystemExit) as exc_info:
                    main()
                assert exc_info.value.code == 0

            # Should still have the original content
            content = (tmp_path / ".license-comply-policy.yaml").read_text()
            assert content == "existing content"
        finally:
            os.chdir(original_dir)

    @responses.activate
    def test_project_license_flag_accepted(self, tmp_path) -> None:
        """--project-license should be accepted and passed through the pipeline.

        The flag enables license-to-license conflict detection by telling
        the tool what license the project itself uses (e.g., GPL-3.0-only).
        """
        req_file = tmp_path / "requirements.txt"
        req_file.write_text("requests\n")

        _mock_pypi("requests", "MIT License")

        with patch.object(
            sys,
            "argv",
            [
                "license-comply",
                str(tmp_path),
                "--project-type",
                "open-source-copyleft",
                "--project-license",
                "GPL-3.0-only",
                "--no-cache",
                "--no-deep",
            ],
        ):
            with pytest.raises(SystemExit) as exc_info:
                main()
            # MIT is clean in a copyleft project → exit 0
            assert exc_info.value.code == 0


# ===========================================================================
# End-to-end pipeline tests
# ===========================================================================


class TestEndToEnd:
    """End-to-end tests that run the full pipeline with mocked HTTP."""

    @responses.activate
    def test_clean_project_exits_zero(self, tmp_path) -> None:
        """A project with only MIT dependencies should exit with code 0."""
        # Create a simple requirements.txt
        req_file = tmp_path / "requirements.txt"
        req_file.write_text("requests\n")

        _mock_pypi("requests", "MIT License")

        with patch.object(
            sys,
            "argv",
            [
                "license-comply",
                str(tmp_path),
                "--project-type",
                "proprietary",
                "--no-cache",
                "--no-deep",
            ],
        ):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 0

    @responses.activate
    def test_warning_project_exits_two(self, tmp_path) -> None:
        """A project with LGPL dependencies should exit with code 2 (warnings)."""
        req_file = tmp_path / "requirements.txt"
        req_file.write_text("chardet\n")

        _mock_pypi("chardet", "LGPL-3.0-only")

        with patch.object(
            sys,
            "argv",
            [
                "license-comply",
                str(tmp_path),
                "--project-type",
                "proprietary",
                "--no-cache",
                "--no-deep",
            ],
        ):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 2

    @responses.activate
    def test_critical_project_exits_one(self, tmp_path) -> None:
        """A project with AGPL dependencies should exit with code 1 (critical)."""
        req_file = tmp_path / "requirements.txt"
        req_file.write_text("agpl-pkg\n")

        _mock_pypi("agpl-pkg", "AGPL-3.0-only")

        with patch.object(
            sys,
            "argv",
            [
                "license-comply",
                str(tmp_path),
                "--project-type",
                "proprietary",
                "--no-cache",
                "--no-deep",
            ],
        ):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 1

    @responses.activate
    def test_json_output_created(self, tmp_path) -> None:
        """--format json should create a JSON report file."""
        req_file = tmp_path / "requirements.txt"
        req_file.write_text("requests\n")

        _mock_pypi("requests", "MIT License")

        output_dir = tmp_path / "output"
        output_dir.mkdir()

        with patch.object(
            sys,
            "argv",
            [
                "license-comply",
                str(tmp_path),
                "--project-type",
                "proprietary",
                "--format",
                "json",
                "--output",
                str(output_dir),
                "--no-cache",
                "--no-deep",
            ],
        ):
            with pytest.raises(SystemExit):
                main()

        assert (output_dir / "license-comply-report.json").exists()

    @responses.activate
    def test_ci_mode_suppresses_color_output(self, tmp_path, capsys) -> None:
        """--ci should produce plain text with no ANSI color escape codes."""
        req_file = tmp_path / "requirements.txt"
        req_file.write_text("requests\n")

        _mock_pypi("requests", "MIT License")

        with patch.object(
            sys,
            "argv",
            [
                "license-comply",
                str(tmp_path),
                "--project-type",
                "proprietary",
                "--ci",
                "--no-cache",
                "--no-deep",
            ],
        ):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 0

        # ANSI escape codes start with ESC (0x1b) followed by '['.
        # Rich uses these for colors and styling. CI mode should strip them all.
        output = capsys.readouterr().out
        assert "\x1b[" not in output, "CI output should not contain ANSI escape codes"

    @responses.activate
    def test_missing_dependency_file_shows_error(self, tmp_path) -> None:
        """Scanning an empty directory should show a clear error."""
        with patch.object(
            sys,
            "argv",
            ["license-comply", str(tmp_path), "--project-type", "proprietary"],
        ):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 1


# ===========================================================================
# Output format tests
# ===========================================================================


class TestOutputFormats:
    """Tests for the --format flag with different output formats.

    These verify that the CLI creates the expected report files when
    given --format markdown or --format html. Each test creates a temporary
    project directory with a requirements.txt and a separate output directory.
    """

    @responses.activate
    def test_markdown_output_created(self, tmp_path) -> None:
        """--format markdown should create a .md report file."""
        # Create a simple project with one dependency
        req_file = tmp_path / "requirements.txt"
        req_file.write_text("requests\n")

        _mock_pypi("requests", "MIT License")

        # Use a separate output directory so we can check for the file
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        with patch.object(
            sys,
            "argv",
            [
                "license-comply",
                str(tmp_path),
                "--project-type",
                "proprietary",
                "--format",
                "markdown",
                "--output",
                str(output_dir),
                "--no-cache",
                "--no-deep",
            ],
        ):
            with pytest.raises(SystemExit):
                main()

        # Check that a .md file was created in the output directory
        md_files = list(output_dir.glob("*.md"))
        assert len(md_files) > 0, "No .md report file was created"

    @responses.activate
    def test_html_output_created(self, tmp_path) -> None:
        """--format html should create a .html report file."""
        # Create a simple project with one dependency
        req_file = tmp_path / "requirements.txt"
        req_file.write_text("requests\n")

        _mock_pypi("requests", "MIT License")

        # Use a separate output directory so we can check for the file
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        with patch.object(
            sys,
            "argv",
            [
                "license-comply",
                str(tmp_path),
                "--project-type",
                "proprietary",
                "--format",
                "html",
                "--output",
                str(output_dir),
                "--no-cache",
                "--no-deep",
            ],
        ):
            with pytest.raises(SystemExit):
                main()

        # Check that a .html file was created in the output directory
        html_files = list(output_dir.glob("*.html"))
        assert len(html_files) > 0, "No .html report file was created"


# ===========================================================================
# Zero-dependency project tests
# ===========================================================================


class TestZeroDependencies:
    """Tests for projects with no dependencies at all.

    An empty requirements.txt is a valid edge case — the tool should handle
    it gracefully and exit with code 0 (no issues found).
    """

    @responses.activate
    def test_zero_dependency_project_exits_zero(self, tmp_path) -> None:
        """A project with an empty requirements.txt should exit cleanly.

        When there are no dependencies to scan, there can be no license issues,
        so the tool should either exit with code 0 or return normally (which
        is equivalent to exit code 0). The CLI returns early when no packages
        are found, so main() may not raise SystemExit at all — a normal return
        is treated as success.
        """
        # Create an empty requirements.txt (no dependencies)
        req_file = tmp_path / "requirements.txt"
        req_file.write_text("")

        with patch.object(
            sys,
            "argv",
            [
                "license-comply",
                str(tmp_path),
                "--project-type",
                "proprietary",
                "--no-cache",
                "--no-deep",
            ],
        ):
            try:
                main()
                # If main() returns normally, that's equivalent to exit code 0 — success
            except SystemExit as exc:
                # If it does raise SystemExit, the code should be 0
                assert exc.code == 0


# ===========================================================================
# Deep scanning tests
# ===========================================================================


class TestDeepScanning:
    """Tests for transitive dependency scanning via virtual environment.

    Deep scanning detects a virtual environment, reads all installed packages,
    and marks packages as transitive if they aren't in the dependency file.
    """

    @responses.activate
    def test_no_deep_flag_skips_transitive_scanning(self, tmp_path) -> None:
        """--no-deep should prevent scan_installed_packages from being called."""
        req_file = tmp_path / "requirements.txt"
        req_file.write_text("requests\n")

        _mock_pypi("requests", "MIT License")

        with (
            patch.object(
                sys,
                "argv",
                [
                    "license-comply",
                    str(tmp_path),
                    "--project-type",
                    "proprietary",
                    "--no-cache",
                    "--no-deep",
                ],
            ),
            patch("license_comply.cli.scan_installed_packages") as mock_scan_installed,
        ):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 0

        # scan_installed_packages should NOT have been called
        mock_scan_installed.assert_not_called()

    @responses.activate
    def test_deep_scanning_enabled_by_default(self, tmp_path) -> None:
        """Without --no-deep, scan_installed_packages should be called."""
        req_file = tmp_path / "requirements.txt"
        req_file.write_text("requests\n")

        _mock_pypi("requests", "MIT License")
        _mock_pypi("urllib3", "MIT License")

        # Mock scan_installed_packages to return some packages
        mock_installed = [
            PackageInfo(name="requests"),
            PackageInfo(name="urllib3"),
        ]

        with (
            patch.object(
                sys,
                "argv",
                [
                    "license-comply",
                    str(tmp_path),
                    "--project-type",
                    "proprietary",
                    "--no-cache",
                ],
            ),
            patch(
                "license_comply.cli.scan_installed_packages", return_value=mock_installed
            ) as mock_scan_installed,
        ):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 0

        # scan_installed_packages SHOULD have been called
        mock_scan_installed.assert_called_once()

    @responses.activate
    def test_transitive_packages_marked_in_json_output(self, tmp_path) -> None:
        """In JSON output, transitive packages should have is_transitive: true."""
        req_file = tmp_path / "requirements.txt"
        req_file.write_text("requests\n")

        _mock_pypi("requests", "MIT License")
        _mock_pypi("urllib3", "MIT License")

        from license_comply.models import PackageInfo

        mock_installed = [
            PackageInfo(name="requests"),
            PackageInfo(name="urllib3"),  # Transitive — not in requirements.txt
        ]

        output_dir = tmp_path / "output"
        output_dir.mkdir()

        with (
            patch.object(
                sys,
                "argv",
                [
                    "license-comply",
                    str(tmp_path),
                    "--project-type",
                    "proprietary",
                    "--format",
                    "json",
                    "--output",
                    str(output_dir),
                    "--no-cache",
                ],
            ),
            patch("license_comply.cli.scan_installed_packages", return_value=mock_installed),
        ):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 0

        import json

        json_path = output_dir / "license-comply-report.json"
        assert json_path.exists()
        data = json.loads(json_path.read_text())

        # Find the urllib3 finding — it should be marked as transitive
        urllib3_finding = next(
            (f for f in data["findings"] if f["package_name"] == "urllib3"), None
        )
        assert urllib3_finding is not None
        assert urllib3_finding["is_transitive"] is True

        # Find the requests finding — it should NOT be transitive
        requests_finding = next(
            (f for f in data["findings"] if f["package_name"] == "requests"), None
        )
        assert requests_finding is not None
        assert requests_finding["is_transitive"] is False

        # Check top-level counts
        assert data["direct_count"] == 1
        assert data["transitive_count"] == 1


# ===========================================================================
# Exit code matrix tests (Tier 4)
# ===========================================================================


class TestExitCodeMatrix:
    """Tests for the exit code logic when both critical and warning findings exist.

    Exit codes:
        0 — Clean: no critical, no warnings
        1 — Critical: at least one critical finding (even if warnings also exist)
        2 — Warnings only: no critical findings, but warnings exist
    """

    @responses.activate
    def test_mixed_critical_and_warnings_exits_one(self, tmp_path) -> None:
        """A project with both critical AND warning deps should exit 1 (critical wins)."""
        req_file = tmp_path / "requirements.txt"
        req_file.write_text("agpl-pkg\nchardet\n")

        _mock_pypi("agpl-pkg", "AGPL-3.0-only")
        _mock_pypi("chardet", "LGPL-3.0-only")

        with patch.object(
            sys,
            "argv",
            [
                "license-comply",
                str(tmp_path),
                "--project-type",
                "proprietary",
                "--no-cache",
                "--no-deep",
            ],
        ):
            with pytest.raises(SystemExit) as exc_info:
                main()
            # Critical always takes priority over warnings → exit 1
            assert exc_info.value.code == 1


# ===========================================================================
# CLI flag coverage tests (Tier 4)
# ===========================================================================


class TestCliFlagCoverage:
    """Tests for CLI flags that previously had zero test coverage."""

    @responses.activate
    def test_no_cache_flag_works(self, tmp_path) -> None:
        """--no-cache should still produce correct results without caching."""
        req_file = tmp_path / "requirements.txt"
        req_file.write_text("requests\n")

        _mock_pypi("requests", "MIT License")

        with patch.object(
            sys,
            "argv",
            [
                "license-comply",
                str(tmp_path),
                "--project-type",
                "proprietary",
                "--no-cache",
                "--no-deep",
            ],
        ):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 0

        # No cache file should have been created
        assert not (tmp_path / ".license-comply-cache.json").exists()

    @responses.activate
    def test_policy_flag_loads_custom_policy(self, tmp_path) -> None:
        """--policy should load a custom policy file and apply its rules."""
        req_file = tmp_path / "requirements.txt"
        req_file.write_text("requests\n")

        _mock_pypi("requests", "MIT License")

        # Create a custom policy that denies MIT
        policy_file = tmp_path / "my-policy.yaml"
        policy_file.write_text(
            "policy:\n"
            "  allow: []\n"
            "  deny:\n"
            "    - MIT\n"
            "  review: []\n"
            "  unknown_license_action: critical\n"
        )

        with patch.object(
            sys,
            "argv",
            [
                "license-comply",
                str(tmp_path),
                "--project-type",
                "proprietary",
                "--policy",
                str(policy_file),
                "--no-cache",
                "--no-deep",
            ],
        ):
            with pytest.raises(SystemExit) as exc_info:
                main()
            # MIT is denied by the custom policy → exit 1 (critical)
            assert exc_info.value.code == 1

    @responses.activate
    def test_output_to_nonexistent_directory(self, tmp_path) -> None:
        """--output to a non-existent directory should create it and succeed."""
        req_file = tmp_path / "requirements.txt"
        req_file.write_text("requests\n")

        _mock_pypi("requests", "MIT License")

        output_dir = tmp_path / "deep" / "nested" / "dir"

        with patch.object(
            sys,
            "argv",
            [
                "license-comply",
                str(tmp_path),
                "--project-type",
                "proprietary",
                "--format",
                "json",
                "--output",
                str(output_dir),
                "--no-cache",
                "--no-deep",
            ],
        ):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 0

        assert (output_dir / "license-comply-report.json").exists()
