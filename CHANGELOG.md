# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- Fix dual-license resolution ranking `public_domain` as less permissive than `permissive` (was picking MIT over CC0 — legally backwards)
- Prevent empty filepaths from being appended to generated report list when Jinja2 template rendering fails
- Normalize cache keys in resolver so "Requests" and "requests" share one cache entry (PEP 503 compliance)
- Fix `normalize_package_name` regex to collapse consecutive separators and include underscores in character class
- Replace all `X | Y` union syntax with `Optional`/`Union` for Python 3.9 compatibility
- Add `logger.warning` for unparseable dependency strings in scanner
- Wrap report file writes in `try/except OSError` to prevent raw tracebacks
- Track multiple license IDs per package in obligation rollup
- Capture `time.time()` once in cache TTL check to avoid race window
- Sort glob results when finding venv site-packages directory
- Pass formatted date to markdown template for human-readable dates
- Make `--init` call `sys.exit(0)` explicitly for consistency

### Added

- Ambiguous names YAML field structure validation test
- `LicenseInfo.additional_spdx_ids` list independence test
- PEP 503 consecutive-separator normalization tests
- Missing `Args`/`Returns` sections in docstrings

## [1.0.0] - 2026-03-01

### Added

- **Dependency scanner** — parses `pyproject.toml` and `requirements.txt` for direct dependencies
- **Transitive dependency scanning** — scans all installed packages in your virtual environment by default (`--no-deep` to opt out)
- **License resolver** — queries PyPI JSON API in parallel with disk caching (7-day TTL)
- **License classifier** — matches license strings against a curated SPDX knowledge base of 40+ licenses
- **Risk analyzer** — evaluates license compatibility against five project types (proprietary, internal, SaaS, open-source permissive, open-source copyleft)
- **Custom policy engine** — allow, deny, or flag licenses for review with YAML policy files (`--policy`, `--init`)
- **Four output formats** — terminal (with color and tables), Markdown, HTML, and JSON
- **AI executive summary** — optional plain-English summary powered by Claude or OpenAI (`--summary`)
- **CI mode** — machine-friendly output with exit codes: 0 (clean), 1 (critical), 2 (warnings only)
- **Obligation rollup** — groups license obligations across all dependencies
- **Dual-license handling** — detects `OR` expressions and picks the most permissive option
- **Compatibility matrix** — evaluates copyleft licenses per project type (GPL is critical in proprietary, clean in copyleft)
- **Verbose mode** — detailed progress output for debugging (`--verbose`)

[1.0.0]: https://github.com/admiral-cs/license-comply/releases/tag/v1.0.0
