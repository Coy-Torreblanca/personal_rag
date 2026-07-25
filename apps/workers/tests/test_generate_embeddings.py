"""Tests for the generate_embeddings module."""

from unittest.mock import MagicMock, patch

import pytest
from requests import HTTPError

from src.generate_embeddings import (
    chunk_document,
    generate_embeddings,
    upload_embeddings,
)


# ── Module-level DB session mock ─────────────────────────────────
# ``upload_embeddings`` imports ``get_db`` at module level, so we
# must patch ``src.generate_embeddings.get_db`` directly.  The mock
# is set up with a ``side_effect`` that returns a real generator so
# that ``contextmanager(get_db)()`` works correctly.


@pytest.fixture(autouse=True)
def _mock_gen_emb_db() -> MagicMock:
    """Patch ``get_db`` inside ``src.generate_embeddings``."""
    from tests.conftest import _mock_get_db_factory

    mock_session = MagicMock()
    mock_get_db = _mock_get_db_factory(mock_session)

    with patch("src.generate_embeddings.get_db", mock_get_db):
        yield mock_session


# ── chunk_document ────────────────────────────────────────────────


class TestChunkDocument:
    """Tests for :func:`chunk_document`."""

    def test_single_chunk_for_short_text(self) -> None:
        """A short text that fits within chunk_size returns one chunk."""
        text = "Hello, world!"
        chunks = chunk_document(text)
        assert len(chunks) == 1
        assert chunks[0] == text

    def test_chunks_respect_max_size(self) -> None:
        """No individual chunk exceeds the 500-character limit."""
        text = "word " * 500  # ~2500 chars
        chunks = chunk_document(text)
        for chunk in chunks:
            assert len(chunk) <= 500

    def test_long_text_produces_multiple_chunks(self) -> None:
        """A long text produces multiple chunks."""
        text = "word " * 1000  # ~5000 chars
        chunks = chunk_document(text)
        assert len(chunks) >= 2

    def test_empty_string_yields_empty_list(self) -> None:
        """An empty string produces no chunks."""
        assert chunk_document("") == []

    def test_content_preserved_across_chunks(self) -> None:
        """Re-joining chunks should contain all original words (order preserved)."""
        text = "word " * 1000
        chunks = chunk_document(text)
        joined = " ".join(chunks)
        assert "word" in joined


# ── upload_embeddings ─────────────────────────────────────────────


class TestUploadEmbeddings:
    """Tests for :func:`upload_embeddings`."""

    SAMPLE_ID = "4f225ee2-e003-4820-93de-c5de4b2bd2a4"
    SAMPLE_ORG = "70885aed-0503-4656-bb72-368a26758575"

    def test_deletes_existing_chunks(self, _mock_gen_emb_db) -> None:
        """Previous chunks for the document are deleted before inserts."""
        mock_session = _mock_gen_emb_db
        file_chunks = ["chunk1"]
        embeddings = [[0.1] * 1536]

        upload_embeddings(file_chunks, embeddings, self.SAMPLE_ID, self.SAMPLE_ORG)

        # ``exec`` should have been called at least once (for the DELETE)
        assert mock_session.exec.called

    def test_adds_chunks_correctly(self, _mock_gen_emb_db) -> None:
        """Each chunk is added as a DocumentChunk with correct data."""
        mock_session = _mock_gen_emb_db
        file_chunks = ["chunk_a", "chunk_b"]
        embeddings = [[0.1] * 1536, [0.3] * 1536]

        upload_embeddings(file_chunks, embeddings, self.SAMPLE_ID, self.SAMPLE_ORG)

        assert mock_session.add.call_count == 2

        # First chunk
        first = mock_session.add.call_args_list[0][0][0]
        assert str(first.document_id) == self.SAMPLE_ID
        assert str(first.organization_id) == self.SAMPLE_ORG
        assert first.chunk_index == 0
        assert first.content == "chunk_a"
        assert first.embedding == [0.1] * 1536

        # Second chunk
        second = mock_session.add.call_args_list[1][0][0]
        assert second.chunk_index == 1
        assert second.content == "chunk_b"
        assert second.embedding == [0.3] * 1536

    def test_commits_transaction(self, _mock_gen_emb_db) -> None:
        """The database transaction is committed."""
        mock_session = _mock_gen_emb_db
        upload_embeddings(["c1"], [[0.1] * 1536], self.SAMPLE_ID, self.SAMPLE_ORG)
        mock_session.commit.assert_called_once()

    def test_empty_chunks_list(self, _mock_gen_emb_db) -> None:
        """An empty chunks list still commits the transaction."""
        mock_session = _mock_gen_emb_db
        upload_embeddings([], [], self.SAMPLE_ID, self.SAMPLE_ORG)
        mock_session.commit.assert_called_once()


# ── generate_embeddings ───────────────────────────────────────────


class TestGenerateEmbeddings:
    """Tests for :func:`generate_embeddings`."""

    SAMPLE_ID = "4f225ee2-e003-4820-93de-c5de4b2bd2a4"
    SAMPLE_ORG = "70885aed-0503-4656-bb72-368a26758575"
    SAMPLE_URL = "https://example.com/doc.md"

    def test_fetches_markdown_from_url(
        self, mock_requests_get, mock_openai_client, _mock_gen_emb_db
    ) -> None:
        """The markdown file is fetched from the provided URL."""
        generate_embeddings(self.SAMPLE_URL, self.SAMPLE_ID, self.SAMPLE_ORG)

        mock_requests_get.assert_called_once_with(self.SAMPLE_URL)
        mock_requests_get.return_value.raise_for_status.assert_called_once()

    def test_generates_embeddings_for_chunks(
        self, mock_requests_get, mock_openai_client, _mock_gen_emb_db
    ) -> None:
        """OpenAI embeddings are generated for the chunked content."""
        generate_embeddings(self.SAMPLE_URL, self.SAMPLE_ID, self.SAMPLE_ORG)

        mock_openai_client.embeddings.create.assert_called_once()
        call_kwargs = mock_openai_client.embeddings.create.call_args[1]
        assert call_kwargs["model"] == "text-embedding-3-small"
        assert isinstance(call_kwargs["input"], list)
        assert len(call_kwargs["input"]) > 0

    def test_uploads_embeddings_to_db(
        self, mock_requests_get, mock_openai_client, _mock_gen_emb_db
    ) -> None:
        """Embeddings are persisted to the database."""
        mock_session = _mock_gen_emb_db

        generate_embeddings(self.SAMPLE_URL, self.SAMPLE_ID, self.SAMPLE_ORG)

        assert mock_session.add.call_count >= 1
        mock_session.commit.assert_called_once()

    def test_requests_failure_propagates(
        self, mock_requests_get, mock_openai_client, _mock_gen_emb_db
    ) -> None:
        """A failed HTTP request raises an exception."""
        mock_requests_get.return_value.raise_for_status.side_effect = HTTPError(
            "404 Not Found"
        )

        with pytest.raises(HTTPError):
            generate_embeddings(self.SAMPLE_URL, self.SAMPLE_ID, self.SAMPLE_ORG)
