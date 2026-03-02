"""
AI-powered executive summary generator for license-comply.

This module optionally generates a plain-English legal executive summary
of the scan findings using either Anthropic's Claude or OpenAI's GPT.
The summary is written in the style of a legal risk assessment memo,
suitable for sharing with a legal team.

How it fits in the pipeline:
    scanner → resolver → classifier → analyzer → [ai_summary] → reporter

This module is OPTIONAL — it only runs when the user passes the --summary
flag. The AI provider packages (anthropic, openai) are optional dependencies.
If they're not installed, the CLI catches the ImportError and skips this step.

Key design decisions:
    - Model IDs are configurable constants at the top of the file, so they're
      easy to update when new models come out.
    - API keys are read from environment variables (ANTHROPIC_API_KEY,
      OPENAI_API_KEY), following standard conventions.
    - If no API key is found, we return None with a helpful message rather
      than crashing — graceful degradation is important.
"""

from __future__ import annotations

import json
import os
from typing import Optional

from rich.console import Console

from license_comply.models import ScanResult

# ---------------------------------------------------------------------------
# AI model configuration
# ---------------------------------------------------------------------------
# Update these when newer models become available. They're intentionally at
# the top of the file so they're easy to find and change.

# Allow model overrides via environment variables so users can switch to
# newer models without waiting for a new release of this tool.
ANTHROPIC_MODEL = os.environ.get("LICENSE_COMPLY_ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
OPENAI_MODEL = os.environ.get("LICENSE_COMPLY_OPENAI_MODEL", "gpt-4o-mini")
MAX_TOKENS = 1024

# ---------------------------------------------------------------------------
# The prompt template
# ---------------------------------------------------------------------------
# This is the instruction we send to the AI model along with the scan data.
# It asks for a memo-style summary suitable for a legal team. The prompt is
# carefully worded to get useful output: specific about legal obligations,
# professional in tone, and framed as findings (not legal advice).

_PROMPT_TEMPLATE = """You are a legal technology tool assisting with open-source \
license compliance analysis. Based on the following scan results, write a concise \
executive summary suitable for a legal team.

The project is a {project_type} project with {total_packages} dependencies.

Scan findings:
{findings_json}

Write a memo-style summary that includes:
1. Overall compliance posture (one sentence assessment)
2. Critical issues requiring immediate attention (if any), with a brief explanation \
of the legal risk
3. Warnings that should be reviewed (if any)
4. Recommended next steps, in priority order

Important:
- Write in clear, professional English suitable for attorneys
- Be specific about legal obligations and risks
- Do not provide legal advice — frame findings as "this license generally requires..." \
not "you must..."
- Keep the summary under 500 words
- Do not include disclaimers about being an AI — the tool's own disclaimer handles that"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_summary(result: ScanResult, provider: str = "anthropic") -> Optional[str]:
    """Generate an AI-powered executive summary of the scan findings.

    This is the main entry point called by cli.py. It builds a prompt from the
    scan results, sends it to the chosen AI provider, and returns the response.

    Args:
        result: The complete scan result from the analyzer.
        provider: Which AI provider to use — "anthropic" or "openai".

    Returns:
        The AI-generated summary text, or None if the summary could not be
        generated (e.g., missing API key).
    """
    # Build the prompt with the scan data embedded
    prompt = _build_prompt(result)

    # Call the appropriate AI provider
    if provider == "anthropic":
        return _call_anthropic(prompt)
    elif provider == "openai":
        return _call_openai(prompt)
    else:
        # This shouldn't happen because argparse validates the choices,
        # but handle it just in case.
        console = Console(stderr=True)
        console.print(f"[red]Error: Unknown AI provider '{provider}'.[/red]")
        console.print("  Supported providers: anthropic, openai")
        return None


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------


def _build_prompt(result: ScanResult) -> str:
    """Build the AI prompt by inserting scan data into the template.

    We convert the findings into a simplified JSON structure that gives the AI
    model the key information it needs: package name, license, risk level,
    and the explanation. We don't send the full ScanResult because the AI
    doesn't need every field (like pypi_url or source_url).

    Args:
        result: The complete scan result.

    Returns:
        The fully constructed prompt string ready to send to an AI model.
    """
    # Build a simplified version of the findings for the AI prompt.
    # We include only the fields that matter for the summary — the AI doesn't
    # need URLs or internal IDs, just the legal substance.
    findings_data = []
    for finding in result.findings:
        findings_data.append(
            {
                "package": finding.package_name,
                "license": finding.license_info.spdx_id or finding.license_info.declared_license,
                "category": finding.license_info.category.value,
                "risk_level": finding.risk_level.value,
                "title": finding.title,
                "explanation": finding.explanation,
                "recommendation": finding.recommendation,
            }
        )

    # Convert the findings list to nicely formatted JSON for the prompt
    findings_json = json.dumps(findings_data, indent=2)

    # Fill in the template with the actual scan data
    return _PROMPT_TEMPLATE.format(
        project_type=result.project_type.value,
        total_packages=result.total_packages,
        findings_json=findings_json,
    )


# ---------------------------------------------------------------------------
# AI provider integrations
# ---------------------------------------------------------------------------


def _call_anthropic(prompt: str) -> Optional[str]:
    """Send the prompt to Anthropic's Claude API and return the response.

    Reads the API key from the ANTHROPIC_API_KEY environment variable.
    If the key is missing, prints a helpful message and returns None.

    Args:
        prompt: The fully constructed prompt to send.

    Returns:
        The AI-generated summary text, or None if the call failed.
    """
    console = Console(stderr=True)

    # Check for the API key in the environment
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        console.print("[yellow]AI summary skipped: No API key found for Anthropic.[/yellow]")
        console.print("  Hint: Set your API key as an environment variable:")
        console.print("    export ANTHROPIC_API_KEY=your-key-here")
        console.print("  You can get an API key at https://console.anthropic.com")
        console.print("  Or skip the AI summary by removing the --summary flag.")
        return None

    # Import the anthropic package. We do this here (not at the top of the
    # file) because it's an optional dependency. Normally cli.py catches the
    # ImportError before we even get here, but we handle it just in case.
    try:
        import anthropic
    except ImportError:
        console.print("[yellow]AI summary skipped: 'anthropic' package not installed.[/yellow]")
        console.print('  Hint: pip install "license-comply[ai]"')
        return None

    # Now make the actual API call. We separate this from the import so
    # that the except clauses can safely reference the anthropic module.
    try:
        client = anthropic.Anthropic(api_key=api_key)

        # Send the prompt to Claude. We use the "user" role for the prompt
        # because it contains the data and instructions for analysis.
        message = client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=MAX_TOKENS,
            messages=[
                {"role": "user", "content": prompt},
            ],
        )

        # The response contains a list of content blocks. For a text response,
        # there's typically one block with the text.
        return message.content[0].text

    except anthropic.AuthenticationError:
        console.print("[red]Error: Anthropic API key is invalid.[/red]")
        console.print("  Hint: Check that your ANTHROPIC_API_KEY is correct.")
        console.print("  You can get a new key at https://console.anthropic.com")
        return None
    except anthropic.APIError as error:
        console.print(f"[red]Error: Anthropic API call failed: {error}[/red]")
        console.print("  The AI summary will be skipped.")
        return None


def _call_openai(prompt: str) -> Optional[str]:
    """Send the prompt to OpenAI's API and return the response.

    Reads the API key from the OPENAI_API_KEY environment variable.
    If the key is missing, prints a helpful message and returns None.

    Args:
        prompt: The fully constructed prompt to send.

    Returns:
        The AI-generated summary text, or None if the call failed.
    """
    console = Console(stderr=True)

    # Check for the API key in the environment
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        console.print("[yellow]AI summary skipped: No API key found for OpenAI.[/yellow]")
        console.print("  Hint: Set your API key as an environment variable:")
        console.print("    export OPENAI_API_KEY=your-key-here")
        console.print("  You can get an API key at https://platform.openai.com")
        console.print("  Or skip the AI summary by removing the --summary flag.")
        return None

    # Import the openai package (optional dependency — same pattern as anthropic above).
    try:
        import openai
    except ImportError:
        console.print("[yellow]AI summary skipped: 'openai' package not installed.[/yellow]")
        console.print('  Hint: pip install "license-comply[ai]"')
        return None

    # Make the API call (separate from the import for safe error handling).
    try:
        client = openai.OpenAI(api_key=api_key)

        # Send the prompt to GPT. We use the chat completions API, which
        # expects messages in a conversation format.
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            max_tokens=MAX_TOKENS,
            messages=[
                {"role": "user", "content": prompt},
            ],
        )

        # Extract the text from the response
        return response.choices[0].message.content

    except openai.AuthenticationError:
        console.print("[red]Error: OpenAI API key is invalid.[/red]")
        console.print("  Hint: Check that your OPENAI_API_KEY is correct.")
        console.print("  You can get a new key at https://platform.openai.com")
        return None
    except openai.APIError as error:
        console.print(f"[red]Error: OpenAI API call failed: {error}[/red]")
        console.print("  The AI summary will be skipped.")
        return None
