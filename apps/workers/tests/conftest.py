"""Shared fixtures and configuration for worker tests."""

import os
from collections.abc import Generator
from unittest.mock import MagicMock, patch

import pytest


# ── Early mock for openai.Client ─────────────────────────────────
# ``src.generate_embeddings`` calls ``openai.Client()`` at module
# level (line 12), which raises ``OpenAIError`` without credentials
# during test collection.  We patch it before any test module is
# imported so that collection succeeds.  The ``mock_openai_client``
# fixture below provides further configuration for tests that
# exercise ``generate_embeddings``.
_openai_client_patcher = patch("openai.Client", autospec=True)
_openai_client_patcher.start()


# ── Sample test data ──────────────────────────────────────────────

SAMPLE_DOCUMENT_ID = "4f225ee2-e003-4820-93de-c5de4b2bd2a4"
SAMPLE_ORGANIZATION_ID = "70885aed-0503-4656-bb72-368a26758575"
SAMPLE_S3_KEY = "documents/test-document.pdf"
SAMPLE_DOWNLOAD_URL = "https://example.com/download"
SAMPLE_UPLOAD_URL = "https://example.com/upload"
SAMPLE_MARKDOWN = (
    "# Test Document\n\nThis is a test document with some content.\n\n"
    "It has multiple paragraphs.\n\nAnd some more text here.\n\n" * 10
)
# Dense summary as produced by the DeepSeek worker stage
# (``src/generate_llm_summary.py``).
SAMPLE_SUMMARY = (
    "[Overview]: A test document used by the worker test suite.\n"
    "[Key Concepts & Entities]: pytest, Celery, R2, OpenAI.\n"
    "[Core Findings / Arguments]: Verifies the document pipeline end to end."
)


# ── Helper: build a mock ``get_db`` generator ───────────────────
# The production code uses ``contextmanager(get_db)() as db``, so
# ``get_db`` must be a generator function.  This helper returns a
# ``MagicMock`` whose ``side_effect`` is a real generator that
# yields ``session``.


def _mock_get_db_factory(session: MagicMock) -> MagicMock:
    """Return a MagicMock that behaves like ``get_db`` (a generator function)."""

    def _gen() -> Generator[MagicMock, None, None]:
        yield session

    mock = MagicMock(side_effect=_gen)
    return mock


# ── Mock OpenAI client fixture ────────────────────────────────────


@pytest.fixture
def mock_openai_client() -> Generator[MagicMock, None, None]:
    """Provide a mock OpenAI client.

    Patches ``openai.Client`` so that ``generate_embeddings``
    uses a mock client.  The fake ``.embeddings.create()`` returns
    exactly one embedding vector per input chunk (full 1536-dim
    vectors for pgvector), so tests never need to know the chunk
    count in advance and the production count-mismatch guard is
    satisfied by construction.
    """
    with patch("src.generate_embeddings.client") as mock_client:

        def _fake_create(**kwargs):
            """Return one fake embedding per input, in order."""
            n_inputs = len(kwargs["input"])
            response = MagicMock()
            response.data = [
                MagicMock(embedding=[0.1] * 1536) for _ in range(n_inputs)
            ]
            return response

        mock_client.embeddings.create.side_effect = _fake_create
        yield mock_client


# ── Mock Modal fixture ────────────────────────────────────────────


@pytest.fixture
def mock_modal_cls() -> Generator[MagicMock, None, None]:
    """Mock ``modal.Cls.from_name`` for testing ``process_document``."""
    with patch("src.main.modal.Cls.from_name") as mock_from_name:
        mock_cls_instance = MagicMock()
        # Make ``m_cls()`` return the same object so that
        # ``m_cls().process_document.remote(...)`` resolves correctly.
        mock_cls_instance.return_value = mock_cls_instance
        mock_cls_instance.process_document.remote.return_value = {
            "status": "success",
            "pages": 3,
        }
        mock_from_name.return_value = mock_cls_instance
        yield mock_from_name


# ── Mock R2 Client fixture ────────────────────────────────────────


@pytest.fixture
def mock_r2_client() -> Generator[MagicMock, None, None]:
    """Mock ``R2Client`` to return a presigned URL."""
    with patch("src.main.R2Client") as mock_r2_cls:
        mock_client = MagicMock()
        mock_client.generate_presigned_url.return_value.url = (
            "https://example.com/markdown-download.md"
        )
        mock_r2_cls.return_value = mock_client
        yield mock_client
