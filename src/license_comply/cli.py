"""
Command-line interface for license-comply.

This module wires everything together: it parses command-line arguments,
runs the pipeline (scan → resolve → classify → analyze → report), and
handles errors gracefully.

This is the "main" entry point — when someone types `license-comply` on
the command line, this module's main() function is what runs.

How it fits in the pipeline:
    cli.py orchestrates: scanner → resolver → classifier → analyzer → reporter
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from typing import Optional

from rich.console import Console

from license_comply import __version__
from license_comply.analyzer import analyze
from license_comply.classifier import classify_licenses
from license_comply.models import ProjectType
from license_comply.reporter import generate_report
from license_comply.resolver import resolve_licenses
from license_comply.scanner import find_dependency_file, scan_dependencies, scan_installed_packages
from license_comply.utils import get_knowledge_path, normalize_package_name

# ---------------------------------------------------------------------------
# CLI argument parsing
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for the CLI.

    Returns:
        A configured ArgumentParser ready to parse sys.argv.
    """
    parser = argparse.ArgumentParser(
        prog="license-comply",
        description=(
            "Open-source license compliance analysis — risk ratings, plain-English\n"
            "explanations, and remediation steps for your project type.\n\n"
            "Scans your Python project's dependencies, identifies their licenses,\n"
            "analyzes legal risks based on your project type, and generates a\n"
            "clear compliance report."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # Positional argument: project path
    parser.add_argument(
        "path",
        nargs="?",
        default=".",
        help="Path to the project directory (default: current directory)",
    )

    # --init: generate a starter policy file
    parser.add_argument(
        "--init",
        action="store_true",
        help="Generate a starter .license-comply-policy.yaml in the current directory",
    )

    # --project-type: required for every scan
    parser.add_argument(
        "--project-type",
        choices=[
            "proprietary",
            "internal",
            "open-source-permissive",
            "open-source-copyleft",
            "saas",
        ],
        help="How your project is used (required for scanning)",
    )

    # --project-license: optional SPDX ID of the project's own license
    parser.add_argument(
        "--project-license",
        default=None,
        help=(
            "Your project's license (SPDX ID, e.g., 'GPL-3.0-only'). "
            "Enables license-to-license conflict detection."
        ),
    )

    # --file: override auto-detection
    parser.add_argument(
        "--file",
        default=None,
        help="Path to a specific dependency file (overrides auto-detection)",
    )

    # --policy: custom policy file
    parser.add_argument(
        "--policy",
        default=None,
        help="Path to a custom policy YAML file",
    )

    # --format: output format(s)
    parser.add_argument(
        "--format",
        action="append",
        dest="formats",
        choices=["terminal", "markdown", "html", "json"],
        help="Output format (can specify multiple; default: terminal)",
    )

    # --output: where to save reports
    parser.add_argument(
        "--output",
        default=".",
        help="Directory to save report files (default: current directory)",
    )

    # --no-deep: disable transitive dependency scanning
    parser.add_argument(
        "--no-deep",
        action="store_true",
        help=(
            "Only scan direct dependencies (skip transitive/installed packages). "
            "By default, license-comply scans all packages installed in the "
            "virtual environment."
        ),
    )

    # --no-cache: disable disk caching
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Disable disk caching of PyPI license lookups",
    )

    # --summary: AI executive summary
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Generate an AI-powered executive summary (requires API key)",
    )

    # --ai-provider: which AI to use
    parser.add_argument(
        "--ai-provider",
        choices=["anthropic", "openai"],
        default="anthropic",
        help="AI provider for the summary (default: anthropic)",
    )

    # --ci: CI mode
    parser.add_argument(
        "--ci",
        action="store_true",
        help="CI mode: suppress decorative output",
    )

    # --verbose: detailed progress
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print detailed progress information",
    )

    # --version
    parser.add_argument(
        "--version",
        action="version",
        version=f"license-comply {__version__}",
    )

    return parser


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Run the license-comply CLI.

    This is the function called by the `license-comply` command and by
    `python -m license_comply`. It parses arguments, runs the pipeline,
    and exits with the appropriate code.

    Exit codes:
        0 — Clean: no critical findings, no warnings
        1 — Critical: at least one critical finding
        2 — Warnings only: no critical findings, but warnings exist
    """
    parser = _build_parser()
    args = parser.parse_args()

    console = Console(stderr=True)

    # --- Handle --init ---
    if args.init:
        _handle_init(console)
        sys.exit(0)

    # --- Validate required arguments ---
    if args.project_type is None:
        console.print("[red]Error: --project-type is required for scanning.[/red]")
        console.print(
            "  Hint: Choose one of: proprietary, internal, "
            "open-source-permissive, open-source-copyleft, saas"
        )
        console.print("  Example: license-comply . --project-type proprietary")
        sys.exit(1)

    # Default format to terminal if none specified
    formats = args.formats or ["terminal"]

    # Map string to ProjectType enum
    project_type = ProjectType(args.project_type)

    # Warn if --project-license is used without a copyleft project type
    if args.project_license and project_type != ProjectType.OPEN_SOURCE_COPYLEFT:
        console.print(
            "[yellow]Note: --project-license is most useful with "
            "--project-type open-source-copyleft.[/yellow]"
        )

    # --- Run the pipeline ---
    try:
        _run_pipeline(
            project_path=args.path,
            project_type=project_type,
            explicit_file=args.file,
            policy_path=_resolve_policy_path(args.policy, args.path),
            formats=formats,
            output_dir=args.output,
            use_cache=not args.no_cache,
            ci_mode=args.ci,
            summary=args.summary,
            ai_provider=args.ai_provider,
            verbose=args.verbose,
            project_license=args.project_license,
            no_deep=args.no_deep,
        )
    except FileNotFoundError as error:
        console.print(f"[red]Error: {error}[/red]")
        sys.exit(1)
    except ValueError as error:
        console.print(f"[red]Error: {error}[/red]")
        sys.exit(1)
    except KeyboardInterrupt:
        console.print("\n[yellow]Scan cancelled.[/yellow]")
        sys.exit(1)


def _run_pipeline(
    project_path: str,
    project_type: ProjectType,
    explicit_file: Optional[str],
    policy_path: Optional[str],
    formats: list[str],
    output_dir: str,
    use_cache: bool,
    ci_mode: bool,
    summary: bool,
    ai_provider: str,
    verbose: bool,
    project_license: Optional[str] = None,
    no_deep: bool = False,
) -> None:
    """Execute the full scan-resolve-classify-analyze-report pipeline.

    This is the core orchestration function. Each step produces data
    consumed by the next step. Calls sys.exit() at the end with the
    appropriate code (0 = clean, 1 = critical, 2 = warnings only).

    Args:
        project_path: Path to the project directory to scan.
        project_type: How the project will be used (determines risk rules).
        explicit_file: Path to a specific dependency file, or None to auto-detect.
        policy_path: Path to a custom policy YAML file, or None for built-in default.
        formats: List of output formats to generate (e.g., ["terminal", "json"]).
        output_dir: Directory where non-terminal report files are saved.
        use_cache: Whether to read/write the PyPI disk cache.
        ci_mode: When True, suppresses decorative rich output for CI pipelines.
        summary: When True, generates an AI-powered executive summary.
        ai_provider: Which AI provider to use for the summary ("anthropic" or "openai").
        verbose: When True, prints detailed progress at each pipeline step.
        project_license: The project's own SPDX license ID, for conflict detection.
        no_deep: When True, skips scanning installed venv packages (direct deps only).
    """
    console = Console(stderr=True)

    # Step 1: Find the dependency file
    if verbose:
        console.print("[dim]Finding dependency file...[/dim]")
    dep_file = find_dependency_file(project_path, explicit_file)
    if verbose:
        console.print(f"[dim]Using: {dep_file}[/dim]")

    # Step 2: Scan dependencies from the dependency file (direct deps)
    if verbose:
        console.print("[dim]Scanning dependencies...[/dim]")
    direct_packages = scan_dependencies(dep_file)
    if not direct_packages:
        console.print("[yellow]No dependencies found.[/yellow]")
        return
    if verbose:
        console.print(f"[dim]Found {len(direct_packages)} direct dependencies[/dim]")

    # Step 2.5: Deep scanning — scan all installed packages in the venv
    # This catches transitive dependencies that aren't in the dependency file
    # but are still legally binding.
    direct_names: set[str] = set()
    deep_scanning_active = False

    if not no_deep:
        installed_packages = scan_installed_packages(project_path)
        if installed_packages:
            deep_scanning_active = True
            # Build a set of normalized direct dependency names for comparison
            direct_names = {normalize_package_name(p.name) for p in direct_packages}
            # Use the installed packages as the full list to resolve
            packages = installed_packages
            if verbose:
                # Calculate transitive count by comparing installed packages
                # against direct dependencies using normalized names, rather than
                # subtracting set sizes directly (which can mismatch if a direct
                # dep isn't installed or normalization deduplicates differently).
                installed_names = {normalize_package_name(p.name) for p in installed_packages}
                overlap = direct_names & installed_names
                transitive_display = len(installed_packages) - len(overlap)
                console.print(
                    f"[dim]Deep scan: {len(installed_packages)} installed packages "
                    f"({len(overlap)} direct, "
                    f"{transitive_display} transitive)[/dim]"
                )
        else:
            packages = direct_packages
            # Print a tip about deep scanning when no venv is found
            console.print(
                "[dim]Tip: Activate a virtual environment to scan transitive "
                "dependencies too.[/dim]"
            )
    else:
        packages = direct_packages

    # Step 3: Resolve licenses from PyPI
    if verbose:
        console.print("[dim]Looking up licenses on PyPI...[/dim]")
    license_infos = resolve_licenses(
        packages, use_cache=use_cache, cache_dir=os.path.dirname(dep_file)
    )

    # Step 4: Classify licenses
    if verbose:
        console.print("[dim]Classifying licenses...[/dim]")
    classify_licenses(license_infos)

    # Step 5: Analyze compatibility
    if verbose:
        console.print("[dim]Analyzing compatibility...[/dim]")
    result = analyze(
        license_infos=license_infos,
        project_type=project_type,
        project_path=project_path,
        policy_path=policy_path,
        project_license=project_license,
    )

    # Step 5.5: Mark transitive dependencies and set counts
    # After analyze() has created findings, we tag each finding's license_info
    # as transitive if its package name is NOT in the direct dependency set.
    if deep_scanning_active:
        transitive_count = 0
        for finding in result.findings:
            normalized_name = normalize_package_name(finding.package_name)
            if normalized_name not in direct_names:
                finding.license_info.is_transitive = True
                transitive_count += 1
        result.direct_count = result.total_packages - transitive_count
        result.transitive_count = transitive_count

    # Step 5.6: AI summary (optional)
    if summary:
        try:
            from license_comply.ai_summary import generate_summary

            if verbose:
                console.print("[dim]Generating AI summary...[/dim]")
            result.ai_summary = generate_summary(result, provider=ai_provider)
        except ImportError:
            console.print("[yellow]AI summary skipped: required packages not installed.[/yellow]")
            console.print('  Hint: pip install "license-comply[ai]"')

    # Step 6: Generate reports
    generated_files = generate_report(
        result=result,
        formats=formats,
        output_dir=output_dir,
        ci_mode=ci_mode,
    )

    # Print paths to generated files
    for filepath in generated_files:
        console.print(f"Report saved to: {filepath}")

    # Exit with appropriate code
    has_critical = any(f.risk_level.value == "critical" for f in result.findings)
    has_warnings = any(f.risk_level.value == "warning" for f in result.findings)

    if has_critical:
        sys.exit(1)
    elif has_warnings:
        sys.exit(2)
    else:
        sys.exit(0)


# ---------------------------------------------------------------------------
# --init handler
# ---------------------------------------------------------------------------


def _handle_init(console: Console) -> None:
    """Generate a starter policy file in the current directory.

    Copies the default policy to .license-comply-policy.yaml so the user
    can customize it for their organization.

    Args:
        console: The Rich Console instance used to print status messages.
    """
    output_path = ".license-comply-policy.yaml"

    if os.path.isfile(output_path):
        console.print(f"[yellow]Policy file already exists: {output_path}[/yellow]")
        console.print("  Hint: Edit the existing file, or delete it and run --init again.")
        return

    source_path = get_knowledge_path("default_policy.yaml")
    shutil.copy2(source_path, output_path)
    console.print(f"[green]Created policy file: {output_path}[/green]")
    console.print("  Edit this file to customize your organization's license policy.")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_policy_path(
    explicit_policy: Optional[str],
    project_path: str,
) -> Optional[str]:
    """Resolve the policy file path.

    Priority:
      1. Explicit --policy flag
      2. .license-comply-policy.yaml in the project directory (if it exists)
      3. None (use built-in default)

    Args:
        explicit_policy: The value of --policy, or None.
        project_path: The project directory path.

    Returns:
        The path to the policy file, or None for the built-in default.
    """
    if explicit_policy is not None:
        return explicit_policy

    # Check for a policy file in the project directory
    project_policy = os.path.join(os.path.abspath(project_path), ".license-comply-policy.yaml")
    if os.path.isfile(project_policy):
        return project_policy

    return None
