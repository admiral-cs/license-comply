# Expected Demo Output

This file shows what `license-comply` should produce when run against the demo
project. It serves as a reference so reviewers can see the intended output
quality without running the tool.

## How to Run

```bash
# Terminal output (default)
license-comply ./demo --project-type proprietary

# Markdown report
license-comply ./demo --project-type proprietary --format markdown

# Both at once (this is what `make demo` does)
license-comply ./demo --project-type proprietary --format terminal --format markdown
```

## What You Should See

### Summary

The demo project has 7 dependencies with a deliberate mix of licenses:

| Package  | License       | Category        | Risk     |
|----------|---------------|-----------------|----------|
| searx    | AGPL-3.0-only | Strong Copyleft | CRITICAL |
| pylint   | GPL-2.0-only  | Strong Copyleft | CRITICAL |
| chardet  | LGPL-2.1-only | Weak Copyleft   | WARNING  |
| requests | Apache-2.0    | Permissive      | CLEAN    |
| flask    | BSD-3-Clause  | Permissive      | CLEAN    |
| click    | BSD-3-Clause  | Permissive      | CLEAN    |
| pydantic | MIT           | Permissive      | CLEAN    |

**Totals:** 4 clean, 1 warning, 2 critical

### Why Each Package Gets Its Risk Level

**CLEAN (permissive licenses):**
- `requests` (Apache-2.0), `flask` (BSD-3-Clause), `click` (BSD-3-Clause),
  `pydantic` (MIT) — all on the default policy's allow list. These are the
  safest licenses, universally permissive with minimal obligations.

**WARNING (needs review):**
- `chardet` (LGPL-2.1) — weak copyleft. The copyleft obligation applies to the
  library itself, not your whole project. If you use it without modification
  (the normal case in Python), you're generally safe.

**CRITICAL (must resolve):**
- `searx` (AGPL-3.0) — strong copyleft. The compatibility matrix flags strong
  copyleft licenses as incompatible with proprietary projects. AGPL's network
  clause makes it especially restrictive. The tool recommends replacing it
  with a permissively-licensed alternative.
- `pylint` (GPL-2.0) — strong copyleft. The compatibility matrix flags strong
  copyleft licenses as incompatible with proprietary projects. Even though
  pylint is typically a development tool, the license analysis is based on
  the license terms themselves.

### Exit Codes

The tool uses exit codes to signal results:
- `0` = clean (no critical findings, no warnings)
- `1` = critical (at least one critical finding) — **this is what the demo produces**
- `2` = warnings only (no criticals, but warnings exist)

### Obligations Rollup

The report ends with a consolidated list of legal obligations grouped by
requirement (not by package). This is the tool's killer feature for legal
teams — instead of reading each package's obligations separately, you see:

- **Include copyright notice** — required by: flask, click (BSD-3-Clause)
- **State any modifications** — required by: requests (Apache-2.0)
- **Distribute source code under GPL-2.0** — required by: pylint (GPL-2.0-only)

...and so on. This makes it easy for a legal team to build a compliance
checklist.

## AI Summary (Optional)

If you have an API key set, you can also get an AI-generated executive summary:

```bash
# Using Anthropic (default)
ANTHROPIC_API_KEY=your-key license-comply ./demo --project-type proprietary --summary

# Using OpenAI
OPENAI_API_KEY=your-key license-comply ./demo --project-type proprietary --summary --ai-provider openai
```

Without an API key, the `--summary` flag degrades gracefully — the report
generates normally, just without the AI summary section.
