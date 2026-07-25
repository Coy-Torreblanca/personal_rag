"""Shared fixtures and configuration for worker tests."""

from collections.abc import Generator
from unittest.mock import MagicMock, patch

import pytest


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
    uses a mock client.  The returned mock provides a
    ``.embeddings.create()`` helper that returns fake embedding data.
    """
    with patch("src.generate_embeddings.client") as mock_client:
        # Set up a fake embedding response (full 1536-dim vectors for pgvector)
        fake_embedding_data = [
            MagicMock(embedding=[0.1] * 1536),
            MagicMock(embedding=[0.2] * 1536),
            MagicMock(embedding=[0.3] * 1536),
        ]
        mock_client.embeddings.create.return_value.data = fake_embedding_data
        yield mock_client


# ── Mock requests fixture ─────────────────────────────────────────


@pytest.fixture
def mock_requests_get() -> Generator[MagicMock, None, None]:
    """Mock ``requests.get`` to return controlled markdown content."""
    with patch("src.generate_embeddings.requests.get") as mock_get:
        mock_response = MagicMock()
        mock_response.text = SAMPLE_MARKDOWN
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response
        yield mock_get


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
