"""
Tests for the AI summary module (ai_summary.py).

These tests verify that the AI summary feature handles all scenarios correctly:
  - Skips gracefully when no API key is set
  - Builds the prompt with the right project data
  - Handles unknown providers
  - Calls the Anthropic API correctly (mocked)
  - Calls the OpenAI API correctly (mocked)
  - Handles API errors gracefully

We use unittest.mock to simulate the AI API calls — we don't want tests to
actually call (and pay for!) real AI APIs. The mocks verify that the right
data is sent without making network requests.
"""

from __future__ import annotations

import json
import sys
from unittest.mock import MagicMock, patch

from license_comply.ai_summary import (
    _build_prompt,
    generate_summary,
)
from license_comply.models import (
    Finding,
    LicenseCategory,
    LicenseInfo,
    ProjectType,
    RiskLevel,
    ScanResult,
)

# ---------------------------------------------------------------------------
# Shared helper: create a sample ScanResult for testing
# ---------------------------------------------------------------------------


def _make_sample_result() -> ScanResult:
    """Create a small ScanResult with mixed findings for testing.

    Returns a result with 2 packages: one clean (MIT) and one critical (GPL).
    This gives the AI enough variety to work with in the prompt.
    """
    clean_info = LicenseInfo(
        package_name="requests",
        declared_license="MIT License",
        spdx_id="MIT",
        category=LicenseCategory.PERMISSIVE,
    )
    critical_info = LicenseInfo(
        package_name="gpl-pkg",
        declared_license="GPL-3.0-only",
        spdx_id="GPL-3.0-only",
        category=LicenseCategory.STRONG_COPYLEFT,
    )

    return ScanResult(
        project_path="/test/project",
        project_type=ProjectType.PROPRIETARY,
        total_packages=2,
        findings=[
            Finding(
                package_name="requests",
                license_info=clean_info,
                risk_level=RiskLevel.CLEAN,
                title="License Compatible",
                explanation="MIT is a permissive license.",
                recommendation="No action required.",
            ),
            Finding(
                package_name="gpl-pkg",
                license_info=critical_info,
                risk_level=RiskLevel.CRITICAL,
                title="Copyleft Contamination Risk",
                explanation="GPL is strong copyleft.",
                recommendation="Replace this dependency.",
            ),
        ],
        scan_timestamp="2026-02-24T00:00:00+00:00",
        tool_version="1.0.0",
    )


# ===========================================================================
# Prompt construction tests
# ===========================================================================


class TestPromptConstruction:
    """Tests for the _build_prompt helper."""

    def test_prompt_includes_project_type_and_findings(self) -> None:
        """The prompt should include the project type and the findings data.

        This is the most important test — if the prompt doesn't include the
        right data, the AI will generate a useless summary.
        """
        result = _make_sample_result()
        prompt = _build_prompt(result)

        # The prompt should mention the project type
        assert "proprietary" in prompt

        # The prompt should mention the total package count
        assert "2" in prompt

        # The prompt should include each package's findings
        assert "requests" in prompt
        assert "gpl-pkg" in prompt

        # The prompt should include risk levels
        assert "clean" in prompt
        assert "critical" in prompt

        # The prompt should include the license identifiers
        assert "MIT" in prompt
        assert "GPL-3.0-only" in prompt

    def test_prompt_contains_valid_json_findings(self) -> None:
        """The findings section of the prompt should be valid JSON.

        The AI model needs well-structured data to produce a good summary.
        If we accidentally produce malformed JSON, the AI might hallucinate.
        """
        result = _make_sample_result()
        prompt = _build_prompt(result)

        # Extract the JSON portion from the prompt by finding it between
        # "Scan findings:\n" and the next instruction section.
        # The JSON starts after "Scan findings:\n" and is a JSON array.
        findings_start = prompt.index("Scan findings:\n") + len("Scan findings:\n")
        # The JSON ends before "\n\nWrite a memo-style"
        findings_end = prompt.index("\n\nWrite a memo-style")
        findings_json = prompt[findings_start:findings_end]

        # It should be valid JSON
        data = json.loads(findings_json)

        # It should be a list with 2 entries (one per package)
        assert isinstance(data, list)
        assert len(data) == 2

        # Each entry should have the expected keys
        expected_keys = {
            "package",
            "license",
            "category",
            "risk_level",
            "title",
            "explanation",
            "recommendation",
        }
        for entry in data:
            assert expected_keys == set(entry.keys())

    def test_prompt_includes_instructions_for_legal_style(self) -> None:
        """The prompt should instruct the AI to write in legal memo style.

        This ensures the output is appropriate for sharing with legal teams.
        """
        result = _make_sample_result()
        prompt = _build_prompt(result)

        assert "executive summary" in prompt.lower()
        assert "legal team" in prompt.lower()
        assert "500 words" in prompt


# ===========================================================================
# Graceful degradation tests
# ===========================================================================


class TestGracefulDegradation:
    """Tests for handling missing API keys and unknown providers."""

    def test_summary_skipped_gracefully_when_no_anthropic_key(self) -> None:
        """When ANTHROPIC_API_KEY is not set, should return None (not crash).

        This is critical — many users won't have an API key configured.
        The tool should skip the summary with a helpful message, not blow up.
        """
        result = _make_sample_result()

        # Make sure the env var is NOT set (patch it away if it exists)
        with patch.dict("os.environ", {}, clear=True):
            summary = generate_summary(result, provider="anthropic")

        assert summary is None

    def test_summary_skipped_gracefully_when_no_openai_key(self) -> None:
        """When OPENAI_API_KEY is not set, should return None (not crash)."""
        result = _make_sample_result()

        with patch.dict("os.environ", {}, clear=True):
            summary = generate_summary(result, provider="openai")

        assert summary is None

    def test_unknown_provider_returns_none(self) -> None:
        """An unknown provider name should return None, not crash."""
        result = _make_sample_result()
        summary = generate_summary(result, provider="unknown-provider")
        assert summary is None


# ===========================================================================
# Anthropic API integration tests (mocked)
# ===========================================================================


class TestAnthropicIntegration:
    """Tests for the Anthropic (Claude) API integration.

    These tests use unittest.mock to simulate API calls. No real API
    requests are made, and no API key is needed.

    The key technique here: since ai_summary.py does `import anthropic`
    inside a function, we inject a mock module into `sys.modules` so
    that Python's import system returns our mock instead of trying to
    find the real package (which may not be installed).
    """

    def test_anthropic_call_returns_summary_text(self) -> None:
        """When the Anthropic API returns a response, we should extract the text."""
        result = _make_sample_result()

        # Create a mock response that looks like what the Anthropic API returns.
        # The real response has a `content` list with text blocks.
        mock_text_block = MagicMock()
        mock_text_block.text = "This is the AI-generated summary."

        mock_message = MagicMock()
        mock_message.content = [mock_text_block]

        # Create a mock anthropic module and inject it into sys.modules.
        # When _call_anthropic() does `import anthropic`, Python checks
        # sys.modules first — so it will find our mock there.
        mock_anthropic = MagicMock()
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_message
        mock_anthropic.Anthropic.return_value = mock_client

        with (
            patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key-123"}),
            patch.dict(sys.modules, {"anthropic": mock_anthropic}),
        ):
            summary = generate_summary(result, provider="anthropic")

        assert summary == "This is the AI-generated summary."

        # Verify the API was called with the right model and max_tokens
        call_kwargs = mock_client.messages.create.call_args
        assert call_kwargs.kwargs["model"] == "claude-sonnet-4-20250514"
        assert call_kwargs.kwargs["max_tokens"] == 1024

    def test_anthropic_auth_error_returns_none(self) -> None:
        """If the API key is invalid, should return None with a helpful message."""
        result = _make_sample_result()

        # We need real exception classes (not MagicMocks) because Python can
        # only raise actual Exception subclasses. If we used a MagicMock as
        # side_effect, it would be called rather than raised, and the test
        # would pass through without hitting the except clause.
        class MockAuthError(Exception):
            pass

        mock_anthropic = MagicMock()
        mock_anthropic.AuthenticationError = MockAuthError

        mock_client = MagicMock()
        mock_client.messages.create.side_effect = MockAuthError("Invalid API key")
        mock_anthropic.Anthropic.return_value = mock_client

        with (
            patch.dict("os.environ", {"ANTHROPIC_API_KEY": "bad-key"}),
            patch.dict(sys.modules, {"anthropic": mock_anthropic}),
        ):
            summary = generate_summary(result, provider="anthropic")

        assert summary is None

    def test_anthropic_api_error_returns_none(self) -> None:
        """If the API call fails for any reason, should return None gracefully."""
        result = _make_sample_result()

        # Both exception classes must be real Exception subclasses, because
        # Python evaluates ALL except clauses (not just the matching one).
        # If AuthenticationError is still a MagicMock, `except AuthenticationError`
        # would throw TypeError before we reach `except APIError`.
        class MockAuthError(Exception):
            pass

        class MockAPIError(Exception):
            pass

        mock_anthropic = MagicMock()
        mock_anthropic.AuthenticationError = MockAuthError
        mock_anthropic.APIError = MockAPIError

        mock_client = MagicMock()
        mock_client.messages.create.side_effect = MockAPIError("Server error")
        mock_anthropic.Anthropic.return_value = mock_client

        with (
            patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}),
            patch.dict(sys.modules, {"anthropic": mock_anthropic}),
        ):
            summary = generate_summary(result, provider="anthropic")

        assert summary is None


# ===========================================================================
# OpenAI API integration tests (mocked)
# ===========================================================================


class TestOpenAIIntegration:
    """Tests for the OpenAI (GPT) API integration.

    Same mocking technique as the Anthropic tests — we inject a mock
    module into sys.modules so the local `import openai` picks it up.
    """

    def test_openai_call_returns_summary_text(self) -> None:
        """When the OpenAI API returns a response, we should extract the text."""
        result = _make_sample_result()

        # Create a mock response that looks like what the OpenAI API returns.
        # The real response has choices[0].message.content.
        mock_message = MagicMock()
        mock_message.content = "This is the OpenAI summary."

        mock_choice = MagicMock()
        mock_choice.message = mock_message

        mock_response = MagicMock()
        mock_response.choices = [mock_choice]

        mock_openai = MagicMock()
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        mock_openai.OpenAI.return_value = mock_client

        with (
            patch.dict("os.environ", {"OPENAI_API_KEY": "test-key-456"}),
            patch.dict(sys.modules, {"openai": mock_openai}),
        ):
            summary = generate_summary(result, provider="openai")

        assert summary == "This is the OpenAI summary."

        # Verify the API was called with the right model and max_tokens
        call_kwargs = mock_client.chat.completions.create.call_args
        assert call_kwargs.kwargs["model"] == "gpt-4o-mini"
        assert call_kwargs.kwargs["max_tokens"] == 1024

    def test_openai_auth_error_returns_none(self) -> None:
        """If the API key is invalid, should return None with a helpful message."""
        result = _make_sample_result()

        class MockAuthError(Exception):
            pass

        mock_openai = MagicMock()
        mock_openai.AuthenticationError = MockAuthError

        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = MockAuthError("Invalid API key")
        mock_openai.OpenAI.return_value = mock_client

        with (
            patch.dict("os.environ", {"OPENAI_API_KEY": "bad-key"}),
            patch.dict(sys.modules, {"openai": mock_openai}),
        ):
            summary = generate_summary(result, provider="openai")

        assert summary is None

    def test_openai_api_error_returns_none(self) -> None:
        """If the API call fails for any reason, should return None gracefully."""
        result = _make_sample_result()

        class MockAuthError(Exception):
            pass

        class MockAPIError(Exception):
            pass

        mock_openai = MagicMock()
        mock_openai.AuthenticationError = MockAuthError
        mock_openai.APIError = MockAPIError

        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = MockAPIError("Server error")
        mock_openai.OpenAI.return_value = mock_client

        with (
            patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}),
            patch.dict(sys.modules, {"openai": mock_openai}),
        ):
            summary = generate_summary(result, provider="openai")

        assert summary is None
