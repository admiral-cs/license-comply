# license-comply

**Open-source license compliance analysis — risk ratings, plain-English explanations, and remediation steps for your project type.**

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/Python-3.9%2B-blue.svg)](https://www.python.org/downloads/)
[![Tests](https://github.com/admiral-cs/license-comply/actions/workflows/ci.yml/badge.svg)](https://github.com/admiral-cs/license-comply/actions/workflows/ci.yml)
[![code style: ruff](https://img.shields.io/badge/code_style-ruff-d4aa00.svg)](https://docs.astral.sh/ruff/)

> **Nature of This Tool:** license-comply is a software tool that applies a rules-based classification system to open-source license metadata. It provides general information about common open-source licenses and their typical obligations. **This tool is not a legal service.** Its output does not constitute legal advice, and use of this tool does not create an attorney-client relationship with the author or any contributor. Consult qualified legal counsel for advice specific to your situation.
>
> See [LEGAL-DISCLAIMER.md](LEGAL-DISCLAIMER.md) for full terms.

---

- [What It Does](#what-it-does) — scan, analyze, report
- [How It Compares](#how-it-compares) — vs. pip-licenses, FOSSA, ScanCode, Snyk
- [How It Works](#how-it-works) — the four-step analysis pipeline
- [Limitations](#limitations) — what this tool doesn't do
- [Quick Start](#quick-start) — install and run in 60 seconds
- [Example Output](#example-output) — see what a scan looks like
- [Features](#features) — full capability list
- [Installation](#installation) — setup options (basic, AI, dev)
- [Usage](#usage) — formats, CI mode, all flags
- [Configuration](#configuration) — custom policy files
- [Contributing](#contributing)

---

## What It Does

Scans your Python project's dependencies and identifies their open-source licenses. Analyzes license compatibility based on your project type and generates a clear compliance report. Optionally includes an AI-generated legal executive summary powered by Claude or OpenAI.

## How It Compares

Most license tools are **inventory tools** — they tell you *what* license a package uses. **license-comply** is a **compliance analysis tool** — it tells you what that license *means for your specific project*, why it matters, and what to look out for.

| | license-comply | pip-licenses | license-checker | FOSSA | ScanCode | Snyk |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| License detection | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Risk analysis by project type | ✓ | — | — | — | — | — |
| Plain-English explanations | ✓ | — | — | — | — | — |
| Remediation steps | ✓ | — | — | — | — | — |
| Custom policy rules | ✓ | Basic | Basic | ✓ | — | Enterprise |
| AI-powered executive summary | ✓ | — | — | — | — | — |
| Multi-ecosystem | Python | Python | JavaScript | Multi | Multi | Multi |
| License file scanning | — | — | — | ✓ | ✓ | ✓ |
| SBOM export | Planned | — | — | ✓ | ✓ | ✓ |
| Free & open-source | ✓ | ✓ | ✓ | Paid | ✓ | Freemium |

**The key difference:** Give two developers the same `GPL-3.0` dependency. **pip-licenses** outputs "GPL-3.0" and moves on. **license-comply** tells you whether that's a critical risk (proprietary project), perfectly fine (GPL-compatible open-source), or somewhere in between (SaaS) — and explains *why* in language a compliance team can review.

The knowledge base is grounded in open-source licensing principles, not a developer's guess.

## How It Works

1. **Dependency discovery** — Parses `pyproject.toml` or `requirements.txt` for direct dependencies. By default, also scans all installed packages in your virtual environment for transitive dependencies.
2. **License lookup** — Queries the PyPI JSON API in parallel for each package's declared license metadata — checking `license_expression` (PEP 639), classifiers, and the free-text license field, in that priority order. Results are cached locally for 7 days.
3. **Classification** — Matches license strings against a curated knowledge base of SPDX-identified licenses to categorize each as permissive, weak copyleft, strong copyleft, etc. Handles dual-licensed packages (`OR`) by selecting the most permissive option.
4. **Risk analysis** — Evaluates each license against your project type and any custom policy rules, producing findings rated clean, notice, warning, or critical — with plain-English explanations and remediation steps.

## Limitations

- **Metadata-only** — relies on license information declared in PyPI metadata, not the actual text of LICENSE files. If a package has missing or inaccurate metadata, the result may be wrong.
- **Python packages only** — does not support npm, Go modules, or other ecosystems (yet).
- **No code-copying detection** — identifies license obligations at the package level, not whether specific code snippets were copied between projects.
- **Simplified SPDX expressions** — handles `OR` (dual-license) and `AND` (conjunctive) expressions, but not complex nested expressions like `(MIT OR Apache-2.0) AND BSD-3-Clause`.

## Quick Start

```bash
git clone https://github.com/admiral-cs/license-comply.git
cd license-comply
python -m venv .venv
source .venv/bin/activate
pip install .

# Try it on the included demo project
license-comply ./demo --project-type proprietary
```

> **Note:** Not yet published to PyPI — install from source as shown above.
>
> Replace `./demo` with a path to your own project to scan its dependencies.

## Example Output

<details>
<summary>Click to expand — full terminal output for a proprietary project scan</summary>

```
license-comply v1.0.0
Scanning: ./my-project
Project type: proprietary

========================================
RESULTS SUMMARY
========================================
Total packages:  7
Clean:           4
Notice:          0
Warnings:        1
Critical:        2

                       Dependencies
┏━━━━━━━━━━┳━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━┓
┃ Package  ┃ License       ┃ Category        ┃    Risk    ┃
┡━━━━━━━━━━╇━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━┩
│ searx    │ AGPL-3.0-only │ Strong Copyleft │ ✗ CRITICAL │
├──────────┼───────────────┼─────────────────┼────────────┤
│ pylint   │ GPL-2.0-only  │ Strong Copyleft │ ✗ CRITICAL │
├──────────┼───────────────┼─────────────────┼────────────┤
│ chardet  │ LGPL-2.1-only │ Weak Copyleft   │ ⚠ WARNING  │
├──────────┼───────────────┼─────────────────┼────────────┤
│ requests │ Apache-2.0    │ Permissive      │  ✓ CLEAN   │
├──────────┼───────────────┼─────────────────┼────────────┤
│ flask    │ BSD-3-Clause  │ Permissive      │  ✓ CLEAN   │
├──────────┼───────────────┼─────────────────┼────────────┤
│ click    │ BSD-3-Clause  │ Permissive      │  ✓ CLEAN   │
├──────────┼───────────────┼─────────────────┼────────────┤
│ pydantic │ MIT           │ Permissive      │  ✓ CLEAN   │
└──────────┴───────────────┴─────────────────┴────────────┘

========================================
CRITICAL ISSUES
========================================

✗ searx (AGPL-3.0-only)
  Risk: CRITICAL — License Incompatibility
  This is a strong copyleft license. If you distribute software that
  incorporates this code, this license typically requires making the
  entire project's source code available under the same license terms.
  Action: Replace this dependency with a permissively-licensed
  alternative, or obtain a separate commercial license from the author.

✗ pylint (GPL-2.0-only)
  Risk: CRITICAL — License Incompatibility
  This is a strong copyleft license. If you distribute software that
  incorporates this code, this license typically requires making the
  entire project's source code available under the same license terms.
  Action: Replace this dependency with a permissively-licensed
  alternative, or obtain a separate commercial license from the author.

========================================
YOUR OBLIGATIONS
========================================

  • Include copyright notice, license text, and NOTICE file (if present)
    Required by: requests (Apache-2.0)

  • Include copyright notice and license text in distributions
    Required by: pydantic (MIT)

  • Do not use contributor names for endorsement without permission
    Required by: flask (BSD-3-Clause)

  ...and more
```

</details>

> *Output above is truncated for this README. The tool prints the full list of obligations.*

## Features

- **Project-type analysis** — risks are evaluated based on how you use the code (proprietary, internal, SaaS, open-source permissive, open-source copyleft)
- **Customizable policy engine** — define organizational rules for which licenses to allow, deny, or flag for review
- **Multiple output formats** — terminal (with color), Markdown, HTML, and JSON
- **AI executive summary** — optional plain-English executive summary powered by Claude or OpenAI
- **CI mode** — machine-friendly output with exit codes for build pipelines
- **SPDX identifiers** — uses standardized license identifiers throughout
- **Obligation rollup** — groups license obligations across all dependencies so you know exactly what's typically required
- **Transitive dependency scanning** — scans all installed packages in your virtual environment by default, not just direct dependencies
- **PyPI integration** — automatically looks up license metadata from the Python Package Index
- **Disk caching** — caches PyPI lookups for 7 days to avoid repeated API calls
- **Dual-license handling** — detects `OR` expressions and picks the most permissive option

## Installation

> **Note:** Not yet published to PyPI — install from source as shown above.

**Requires Python 3.9 or later.** Check with `python3 --version`. CI tests run on Python 3.9, 3.10, 3.11, and 3.12.

### Basic install

```bash
git clone https://github.com/admiral-cs/license-comply.git
cd license-comply
python -m venv .venv
source .venv/bin/activate
pip install .
```

### With AI summary support

```bash
pip install ".[ai]"
```

This installs the `anthropic` and `openai` Python packages. You'll also need an API key — set one of these environment variables:

```bash
export ANTHROPIC_API_KEY="your-key-here"   # For Claude (default)
export OPENAI_API_KEY="your-key-here"      # For OpenAI
```

### For development

```bash
pip install -e ".[dev]"
```

> The `-e` flag installs in "editable" mode — changes you make to the source code take effect immediately without reinstalling.

### Try it out

The repo includes a demo project with deliberately mixed licenses. After installing, run:

```bash
license-comply ./demo --project-type proprietary
```

## Usage

### Basic scan

```bash
# Scan a project directory (auto-detects pyproject.toml or requirements.txt)
license-comply ./my-project --project-type proprietary
```

The `--project-type` flag is required. It tells the tool how you plan to use your code, which determines what license risks apply:

| Project Type | Meaning |
|---|---|
| `proprietary` | Closed-source commercial software |
| `internal` | Used only within your organization, not distributed |
| `saas` | Software-as-a-Service (delivered over a network) |
| `open-source-permissive` | Open-source under a permissive license (MIT, Apache, etc.) |
| `open-source-copyleft` | Open-source under a copyleft license (GPL, AGPL, etc.) |

### Output formats

```bash
# Terminal output (default) — colorized with tables
license-comply ./my-project --project-type proprietary

# Markdown report — good for documentation or PRs
license-comply ./my-project --project-type proprietary --format markdown

# HTML report — shareable with non-technical stakeholders
license-comply ./my-project --project-type proprietary --format html

# JSON report — for programmatic processing
license-comply ./my-project --project-type proprietary --format json
```

You can pass `--format` multiple times to generate several reports in a single run (e.g., `--format terminal --format html`).

File reports are saved to the current directory by default. Use `--output` to change the destination:

```bash
license-comply ./my-project --project-type proprietary --format html --output ./reports
```

### AI executive summary

```bash
# Generate a legal summary using Claude (default)
license-comply ./my-project --project-type proprietary --summary

# Use OpenAI instead
license-comply ./my-project --project-type proprietary --summary --ai-provider openai
```

The AI summary provides a plain-English explanation of compliance findings, written for a compliance audience. It requires an API key (see [Installation](#with-ai-summary-support)).

### CI mode

```bash
license-comply ./my-project --project-type proprietary --ci
```

CI mode suppresses decorative output (colors, progress bars) and returns meaningful exit codes:

| Exit Code | Meaning |
|---|---|
| `0` | Clean — no critical findings, no warnings |
| `1` | Critical — at least one critical finding |
| `2` | Warnings only — no critical findings, but warnings exist |

#### GitHub Actions example

Drop this into your `.github/workflows/ci.yml` to fail the build when a new dependency introduces a license risk:

```yaml
- name: Install dependencies
  run: pip install -e ".[dev]"

- name: Check license compliance
  run: license-comply . --project-type proprietary --ci
```

Replace `proprietary` with your project type (see [Usage](#basic-scan) for the full list). The step runs after `pip install` so that `license-comply` is available on the `PATH`. If a critical dependency is found, the build fails with exit code 1; warnings produce exit code 2, which you can choose to treat as a failure or allow to pass depending on your CI configuration.

### Other options

```bash
# Point to a specific dependency file (path is relative to your current directory)
license-comply ./my-project --project-type proprietary --file requirements-prod.txt

# Use a custom policy file
license-comply ./my-project --project-type proprietary --policy my-policy.yaml

# Disable PyPI lookup caching
# PyPI's API has no published rate limits for normal usage; results are cached locally for 7 days
license-comply ./my-project --project-type proprietary --no-cache

# Verbose output (shows detailed progress)
license-comply ./my-project --project-type proprietary --verbose

# Skip transitive dependency scanning (only scan direct dependencies)
license-comply ./my-project --project-type proprietary --no-deep

# Specify your project's own license (useful for copyleft compatibility checks)
license-comply ./my-project --project-type open-source-copyleft --project-license GPL-3.0-only

# Generate multiple report formats at once
license-comply ./my-project --project-type proprietary --format terminal --format html

# Show version number
license-comply --version
```

## Configuration

You can customize which licenses your organization allows, denies, or flags for review by creating a policy file.

### Generate a starter policy

```bash
license-comply --init
```

This creates a `.license-comply-policy.yaml` file in your current directory with sensible defaults:

```yaml
policy:
  name: "Default Policy"
  description: "A sensible default policy suitable for most commercial projects."

  # Always allowed — these will never generate a finding
  allow:
    - "MIT"
    - "Apache-2.0"
    - "BSD-2-Clause"
    - "BSD-3-Clause"
    - "ISC"
    - "Unlicense"
    - "CC0-1.0"
    - "BSL-1.0"    # Boost Software License (permissive)
    - "0BSD"
    - "WTFPL"
    - "MIT-0"
    - "PSF-2.0"

  # Always blocked — these will always generate a critical finding
  deny:
    - "SSPL-1.0"
    - "Elastic-2.0"
    - "BSL-1.1"

  # Requires review — these will generate a warning
  review:
    - "CC-BY-SA-4.0"

  # What to do with unrecognized licenses: "critical", "warning", or "notice"
  unknown_license_action: "critical"
```

> **Note:** Copyleft licenses (GPL, LGPL, AGPL, MPL) are not in the deny or review lists. They are handled by the compatibility matrix, which evaluates them per project type — for example, GPL is critical in a proprietary project but clean in a copyleft project.

Edit this file to match your organization's policies, then run scans as usual — the tool will automatically detect the policy file in your project directory, or you can specify one explicitly with `--policy`.

## Roadmap

license-comply is Python-focused today. Planned for future releases:

- **npm / JavaScript support** — extend beyond Python
- **SPDX/CycloneDX export** — output reports in standard SBOM formats
- **Unknown license AI classifier** — use AI to identify licenses the knowledge base doesn't cover
- **Full SPDX expression parser** — handle complex license expressions like `(MIT OR Apache-2.0) AND BSD-3-Clause`
- **Package replacement suggestions** — recommend specific alternative packages when a dependency is flagged
- **Web interface** — browser-based dashboard for compliance reports

## Versioning

This project follows [Semantic Versioning](https://semver.org/). The current release is **v1.0.0**.

## Contributing

Issues and pull requests are welcome. Before submitting, please run:

```bash
pytest tests/ -v          # All tests should pass
ruff check src/ tests/    # No lint errors
ruff format src/ tests/   # Code is formatted
```

## Code Philosophy

The source code is intentionally over-commented. The intended audience includes lawyers and compliance professionals who may not have deep software engineering backgrounds but want to understand exactly what the tool does and why. If a comment feels obvious to you as an engineer, it's there for someone else.

## About the Author

> Built by [Sam Clearwater](https://www.linkedin.com/in/samclearwater) — a
> technology and AI lawyer with 15+ years' experience, admitted in five
> jurisdictions (California, England & Wales, Ireland, New Zealand, and
> Australia). Sam spent a decade at Google, most recently as Senior Product
> Counsel for AI at Google Research, and previously served as de facto General
> Counsel for 40+ startups at Google's internal incubator. He is co-author of
> the IAPP AIGP certification course, a Fellow of Information Privacy (FIP),
> and was named to Bloomberg Law's "40 Under 40" (2024) and a Rising Star at
> the NY Legal Awards (2025).
>
> This tool reflects the belief that legal compliance tooling should be
> accessible, transparent, and built by people who understand both the law
> and the technology.
>
> Sam's experience in open-source licensing informs the tool's knowledge base.
> Use of this tool does not establish a professional relationship with the author.

**This is a personal project. It is not affiliated with or endorsed by any employer.**

## License

[Apache 2.0](LICENSE)

