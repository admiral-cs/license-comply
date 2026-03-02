# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in license-comply, please report it through [GitHub's private vulnerability reporting](https://github.com/admiral-cs/license-comply/security/advisories/new). This ensures the issue is handled confidentially before any public disclosure.

**Please do not open a public issue for security vulnerabilities.**

## What Counts as a Security Issue

**Report as a security vulnerability:**

- Code execution or injection through crafted dependency names, license strings, or input files
- Path traversal when reading `pyproject.toml`, `requirements.txt`, or cache files
- Sensitive data exposure (API keys, file paths, or environment variables leaking into reports)
- Cache poisoning that could cause incorrect license classifications for other users
- Vulnerabilities in how the tool handles network requests to PyPI

**Report as a regular bug (open a GitHub issue):**

- Incorrect license classifications or risk assessments
- Crashes or errors during normal operation
- Formatting issues in generated reports
- Missing or outdated entries in the license knowledge base

## Scope

This policy covers the license-comply tool itself — its source code, dependencies, and behavior. It does not cover the accuracy of legal information in generated reports, which is addressed in [LEGAL-DISCLAIMER.md](LEGAL-DISCLAIMER.md).

## Response Timeline

- **Acknowledgment:** I aim to respond within 7 days of your report
- **Assessment:** I aim to assess severity within 14 days
- **Fix (if confirmed):** I aim to release a fix within 30 days, depending on severity and complexity

## Supported Versions

| Version | Supported |
|---------|-----------|
| 1.0.x   | Yes       |
| < 1.0   | No        |
