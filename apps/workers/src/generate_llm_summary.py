"""Generate LLM summaries of parsed documents via the DeepSeek API.

This module produces a dense, information-rich summary of a document's
markdown content, optimized for vector embeddings and semantic search. It is
a thin wrapper around DeepSeek's OpenAI-compatible chat-completions endpoint:
send the document text as the user message, return the model's formatted
summary.

Design notes:

* The DeepSeek client is constructed *lazily* (see ``_get_client``) so that
  importing this module never requires ``DEEPSEEK_API_KEY`` to be present —
  the key is only read when a summary is actually requested. This keeps the
  module importable during test collection, linting, and image builds, and
  mirrors the existing ``openai.Client`` gotcha documented in
  ``tests/conftest.py`` for ``generate_embeddings.py``.
* All failures are loud and explicit: empty input and missing model output
  raise ``ValueError`` with actionable messages; upstream API errors
  propagate to the caller (the Celery pipeline in ``main.py`` already logs
  and fails the job).
"""

import os

from openai import OpenAI

from logutil import get_logger

logger = get_logger(__name__)

# DeepSeek exposes an OpenAI-compatible API, so the official ``openai`` SDK
# works unchanged — we only swap the base URL and the API key source.
_BASE_URL = "https://api.deepseek.com"
_API_KEY_ENV_VAR = "DEEPSEEK_API_KEY"
_MODEL = "deepseek-v4-flash"

# The system prompt is deliberately tuned for information-dense output:
# summaries land between 150-250 words and preserve queryable entities
# (tools, acronyms, proper nouns) so the embedding vector space stays sharp.
_SYSTEM_PROMPT = """You are an expert knowledge engineer and information retrieval specialist. Your task is to generate a dense, information-rich summary of the provided document specifically optimized for vector embeddings and semantic search.

Instructions:
1. Core Focus: Capture the primary thesis, key technical concepts, specific arguments, and actionable takeaways.
2. Entity Preservation: Explicitly retain critical technical terms, proper nouns, acronyms, tools, frameworks, and domain-specific vocabulary that users are likely to query.
3. Structural Clarity: Avoid conversational filler, meta-commentary (e.g., "This document discusses..."), and vague generalizations. Write in direct, declarative prose.
4. Length Constraint: Keep the summary between 150 to 250 words to maintain high semantic density without diluting the vector space.

Output Format:
[Overview]: A 1-2 sentence high-level summary of what the document is and its primary objective.
[Key Concepts & Entities]: A comma-separated or bulleted list of essential tools, technologies, methodologies, or core subjects covered.
[Core Findings / Arguments]: A concise paragraph detailing the main technical insights, data points, or conclusions."""

# Lazily-initialized module-level client; populated on first call to
# ``_get_client()`` so import time never depends on environment variables.
_client: OpenAI | None = None


def _get_client() -> OpenAI:
    """Return the module-level DeepSeek client, constructing it on first use.

    The client is cached in the module-level ``_client`` slot after the first
    call so that subsequent summaries reuse the same connection pool. The API
    key is read from ``DEEPSEEK_API_KEY`` at call time — not at import time —
    which keeps this module importable in environments where the key is not
    configured (e.g. during test collection or linting).

    Returns:
        The configured ``OpenAI`` client pointed at DeepSeek's API.

    Raises:
        KeyError: If ``DEEPSEEK_API_KEY`` is not set in the environment.
    """
    global _client
    if _client is None:
        _client = OpenAI(
            api_key=os.environ[_API_KEY_ENV_VAR],
            base_url=_BASE_URL,
        )
        logger.debug("Initialized DeepSeek client (base_url=%s)", _BASE_URL)
    return _client


def generate_llm_summary(document_content: str) -> str:
    """Generate a dense summary of ``document_content`` via DeepSeek.

    Sends the full document text as the user turn of a chat-completions call
    (with ``_SYSTEM_PROMPT`` as the system turn) and returns the model's
    formatted summary, stripped of leading/trailing whitespace.

    Args:
        document_content: The document text (typically markdown) to summarize.

    Returns:
        The generated summary as a non-empty string.

    Raises:
        ValueError: If ``document_content`` is empty/whitespace-only, or if
            the API response contains no summary text (empty ``choices`` or
            ``None`` message content — e.g. a content-filtered response).
        openai.OpenAIError: If the upstream API call fails (network error,
            invalid key, rate limit, ...). Exceptions propagate to the caller.
    """
    # Fail fast on empty input: there is nothing to summarize, and sending an
    # empty user message would waste an API call (and tokens) for no value.
    if not document_content.strip():
        raise ValueError("document_content must be a non-empty string.")

    logger.info(
        "Generating LLM summary for document (%d chars, model=%s)",
        len(document_content),
        _MODEL,
    )

    response = _get_client().chat.completions.create(
        model=_MODEL,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": document_content},
        ],
    )

    # Defensive extraction: ``choices`` may be empty (e.g. a content-filtered
    # response) and ``message`` / ``message.content`` may be ``None`` (e.g. a
    # refusal or a malformed payload). Indexing ``choices[0]`` directly would
    # raise an obscure ``IndexError``, and accessing ``.content`` on a ``None``
    # message would raise an ``AttributeError`` — so treat any missing summary
    # as a hard, explicit failure instead.
    if response.choices and response.choices[0].message:
        summary = response.choices[0].message.content
    else:
        summary = None

    if not summary:
        logger.error("DeepSeek returned an empty summary (no content).")
        raise ValueError("No summary was generated by openai client.")

    logger.debug("Generated LLM summary (%d chars)", len(summary))
    return summary.strip()
