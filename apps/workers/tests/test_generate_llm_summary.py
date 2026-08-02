"""Tests for the generate_llm_summary module.

The DeepSeek client is constructed lazily (``_get_client``), so no API key is
needed at import time and every test patches ``src.generate_llm_summary._get_client``
with a fake — no network calls are ever made.
"""

from unittest.mock import MagicMock, patch

import pytest

from src.generate_llm_summary import _get_client, generate_llm_summary

SAMPLE_DOCUMENT = "# Test Document\n\nThis is the body of a test document."


# ── Mock DeepSeek client fixture ──────────────────────────────────


@pytest.fixture
def mock_deepseek_client() -> MagicMock:
    """Patch ``_get_client`` to return a fake DeepSeek client.

    The fake's ``chat.completions.create()`` returns a response with a single
    choice whose message content is a sample summary wrapped in whitespace
    (so tests can verify stripping).
    """
    with patch("src.generate_llm_summary._get_client") as mock_get_client:
        mock_client = MagicMock()
        mock_choice = MagicMock()
        mock_choice.message.content = "  A dense summary of the document.  "
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_client.chat.completions.create.return_value = mock_response
        mock_get_client.return_value = mock_client
        yield mock_client


# ── generate_llm_summary ─────────────────────────────────────────


class TestGenerateLLMSummary:
    """Tests for :func:`generate_llm_summary`."""

    def test_returns_stripped_summary(self, mock_deepseek_client) -> None:
        """The summary is returned with leading/trailing whitespace removed."""
        result = generate_llm_summary(SAMPLE_DOCUMENT)

        assert result == "A dense summary of the document."
        assert result == result.strip()

    def test_sends_document_and_system_prompt(
        self, mock_deepseek_client
    ) -> None:
        """The call uses the DeepSeek model and correct message roles."""
        generate_llm_summary(SAMPLE_DOCUMENT)

        mock_deepseek_client.chat.completions.create.assert_called_once()
        call_kwargs = mock_deepseek_client.chat.completions.create.call_args[1]

        assert call_kwargs["model"] == "deepseek-v4-flash"
        messages = call_kwargs["messages"]
        assert messages[0]["role"] == "system"
        assert messages[0]["content"]  # non-empty system prompt
        assert messages[1] == {"role": "user", "content": SAMPLE_DOCUMENT}

    def test_raises_on_empty_choices(self, mock_deepseek_client) -> None:
        """An empty ``choices`` list raises ValueError (no IndexError)."""
        mock_deepseek_client.chat.completions.create.return_value.choices = []

        with pytest.raises(ValueError, match="No summary was generated"):
            generate_llm_summary(SAMPLE_DOCUMENT)

    def test_raises_on_none_message_content(self, mock_deepseek_client) -> None:
        """A ``None`` message content (refusal) raises ValueError."""
        mock_deepseek_client.chat.completions.create.return_value.choices[
            0
        ].message.content = None

        with pytest.raises(ValueError, match="No summary was generated"):
            generate_llm_summary(SAMPLE_DOCUMENT)

    def test_raises_when_message_is_none(self, mock_deepseek_client) -> None:
        """A ``None`` message object raises ValueError, not AttributeError."""
        mock_deepseek_client.chat.completions.create.return_value.choices[
            0
        ].message = None

        with pytest.raises(ValueError, match="No summary was generated"):
            generate_llm_summary(SAMPLE_DOCUMENT)

    def test_raises_on_empty_message_content(
        self, mock_deepseek_client
    ) -> None:
        """An empty-string message content raises ValueError."""
        mock_deepseek_client.chat.completions.create.return_value.choices[
            0
        ].message.content = ""

        with pytest.raises(ValueError, match="No summary was generated"):
            generate_llm_summary(SAMPLE_DOCUMENT)

    def test_rejects_empty_document(self, mock_deepseek_client) -> None:
        """An empty document raises ValueError before any API call."""
        with pytest.raises(ValueError, match="non-empty"):
            generate_llm_summary("")

        mock_deepseek_client.chat.completions.create.assert_not_called()

    def test_rejects_whitespace_only_document(
        self, mock_deepseek_client
    ) -> None:
        """A whitespace-only document raises ValueError before any API call."""
        with pytest.raises(ValueError, match="non-empty"):
            generate_llm_summary("   \n\t  ")

        mock_deepseek_client.chat.completions.create.assert_not_called()

    def test_propagates_upstream_api_errors(
        self, mock_deepseek_client
    ) -> None:
        """Upstream API failures propagate unchanged to the caller.

        The Celery pipeline in ``main.py`` is responsible for logging and
        failing the job, so this module must not swallow API errors.
        """
        from openai import OpenAIError

        mock_deepseek_client.chat.completions.create.side_effect = OpenAIError(
            "rate limit exceeded"
        )

        with pytest.raises(OpenAIError, match="rate limit exceeded"):
            generate_llm_summary(SAMPLE_DOCUMENT)


# ── _get_client ──────────────────────────────────────────────────


class TestGetClient:
    """Tests for :func:`_get_client` (lazy client construction)."""

    def test_constructs_with_env_credentials(self, monkeypatch) -> None:
        """The client is built from the env key and DeepSeek base URL."""
        monkeypatch.setattr("src.generate_llm_summary._client", None)
        monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")

        with patch("src.generate_llm_summary.OpenAI") as mock_openai_cls:
            client = _get_client()

        mock_openai_cls.assert_called_once_with(
            api_key="test-key",
            base_url="https://api.deepseek.com",
        )
        assert client is mock_openai_cls.return_value

    def test_caches_client_across_calls(self, monkeypatch) -> None:
        """Subsequent calls reuse the same client instance."""
        monkeypatch.setattr("src.generate_llm_summary._client", None)
        monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")

        with patch("src.generate_llm_summary.OpenAI") as mock_openai_cls:
            first = _get_client()
            second = _get_client()

        assert first is second
        mock_openai_cls.assert_called_once()

    def test_raises_without_env_key(self, monkeypatch) -> None:
        """Missing DEEPSEEK_API_KEY raises KeyError at call time."""
        monkeypatch.setattr("src.generate_llm_summary._client", None)
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

        with pytest.raises(KeyError):
            _get_client()

    def test_module_import_does_not_require_api_key(self, monkeypatch) -> None:
        """Importing the module never touches the env var or network.

        This is what keeps test collection working without secrets: no
        ``OpenAI(...)`` constructor runs at import time.
        """
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        monkeypatch.setattr("src.generate_llm_summary._client", None)

        # Re-import fresh; the constructor is patched so even a stray call
        # would be harmless, but we assert it was never invoked.
        with patch("src.generate_llm_summary.OpenAI") as mock_openai_cls:
            import importlib

            import src.generate_llm_summary as module

            importlib.reload(module)

        mock_openai_cls.assert_not_called()
