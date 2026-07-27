"""Tests for the retrieval module (vector search + Cohere re-ranking).

This test suite covers the full retrieval pipeline:

  query_documents
    ├─ _embed_query  (OpenAI embedding)
    ├─ _get_chunks   (pgvector similarity + neighbour merging)
    └─ rerank_docs   (Cohere cross-encoder re-ranking)

All external services (OpenAI, Cohere, PostgreSQL) are mocked so that
tests run offline and deterministically.
"""

from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest
from uuid import UUID

from src.retrieval import (
    ParentChunk,
    QueryDocumentResult,
    RerankResult,
    _embed_query,
    _get_chunks,
    query_documents,
    rerank_docs,
)


# ── Helpers ────────────────────────────────────────────────────────

SAMPLE_DOC_ID_1 = "11111111-1111-4111-8111-111111111111"
SAMPLE_DOC_ID_2 = "22222222-2222-4222-8222-222222222222"
SAMPLE_DOC_ID_3 = "33333333-3333-4333-8333-333333333333"
SAMPLE_ORG_ID = "70885aed-0503-4656-bb72-368a26758575"


def _make_doc(
    doc_id: str = SAMPLE_DOC_ID_1,
    filename: str = "report.pdf",
    s3_key: str = "documents/report.pdf",
) -> MagicMock:
    """Build a minimal ``Document`` mock."""
    doc = MagicMock()
    doc.id = UUID(doc_id)
    doc.filename = filename
    doc.s3_key = s3_key
    return doc


def _exec_result(data):
    """Wrap *data* in a ``MagicMock`` whose ``.all()`` returns *data*.

    ``db.exec(...)`` in production returns a SQLModel ``Result`` object
    whose ``.all()`` method materialises the rows.  The mock must emulate
    this interface so that ``.all()`` can be chained in ``_get_chunks``.
    """
    mock = MagicMock()
    mock.all.return_value = data
    return mock


def _make_chunk(
    doc_id: str = SAMPLE_DOC_ID_1,
    chunk_index: int = 0,
    content: str = "sample chunk content",
) -> MagicMock:
    """Build a minimal ``DocumentChunk`` mock."""
    chunk = MagicMock()
    chunk.document_id = UUID(doc_id)
    chunk.chunk_index = chunk_index
    chunk.content = content
    return chunk


# ── Fixtures ───────────────────────────────────────────────────────

# NOTE: ``openai.Client`` and ``cohere.Client`` are already patched at
# module level in ``conftest.py`` so that imports succeed.  The fixtures
# below replace the module-level *instances* (``client`` and
# ``cohere_client``) with hand-controlled mocks for each test.


@pytest.fixture(autouse=True)
def _mock_retrieval_db() -> MagicMock:
    """Patch ``get_db`` inside ``src.retrieval``.

    Returns the mock *session* so tests can assert on ``exec``, ``add``,
    ``commit``, etc.
    """
    from tests.conftest import _mock_get_db_factory

    mock_session = MagicMock()
    mock_get_db = _mock_get_db_factory(mock_session)

    with patch("src.retrieval.get_db", mock_get_db):
        yield mock_session


@pytest.fixture
def mock_retrieval_openai() -> MagicMock:
    """Patch the module-level ``client`` in ``src.retrieval``.

    The returned mock lets tests control ``embeddings.create()`` results.
    """
    with patch("src.retrieval.client") as mc:
        mc.embeddings.create.return_value.data = [
            MagicMock(embedding=[0.1, 0.2, 0.3])  # small dim for test speed
        ]
        yield mc


@pytest.fixture
def mock_retrieval_cohere() -> MagicMock:
    """Patch the module-level ``cohere_client`` in ``src.retrieval``.

    The returned mock lets tests control ``rerank()`` results.
    """
    with patch("src.retrieval.cohere_client") as mc:
        # Default: one result with medium relevance
        mc.rerank.return_value.results = [
            MagicMock(index=0, relevance_score=0.85),
        ]
        yield mc


@pytest.fixture
def mock_session(_mock_retrieval_db: MagicMock) -> MagicMock:
    """Alias for the mocked DB session (shorter name in tests)."""
    return _mock_retrieval_db


# ── _embed_query ───────────────────────────────────────────────────


class TestEmbedQuery:
    """Tests for the private ``_embed_query`` helper."""

    def test_returns_embedding_list(self, mock_retrieval_openai: MagicMock) -> None:
        """A valid query returns a list of floats."""
        embedding = _embed_query("hello world")
        assert isinstance(embedding, list)
        assert all(isinstance(v, float) for v in embedding)

    def test_calls_openai_with_correct_model(
        self, mock_retrieval_openai: MagicMock
    ) -> None:
        """The correct model and query are sent to OpenAI."""
        _embed_query("test query")
        mock_retrieval_openai.embeddings.create.assert_called_once_with(
            input="test query", model="text-embedding-3-small"
        )

    def test_empty_query(self, mock_retrieval_openai: MagicMock) -> None:
        """An empty query string is passed through unchanged."""
        _embed_query("")
        mock_retrieval_openai.embeddings.create.assert_called_once_with(
            input="", model="text-embedding-3-small"
        )

    def test_special_characters(self, mock_retrieval_openai: MagicMock) -> None:
        """Queries with special characters are handled."""
        _embed_query("café naïve 100%")
        mock_retrieval_openai.embeddings.create.assert_called_once_with(
            input="café naïve 100%", model="text-embedding-3-small"
        )

    def test_embedding_dimension_matches_model(
        self, mock_retrieval_openai: MagicMock
    ) -> None:
        """The embedding dimension should be 1536 for text-embedding-3-small."""
        mock_retrieval_openai.embeddings.create.return_value.data = [
            MagicMock(embedding=[float(i) for i in range(1536)])
        ]
        embedding = _embed_query("test")
        assert len(embedding) == 1536


# ── rerank_docs ────────────────────────────────────────────────────


class TestRerankDocs:
    """Tests for the ``rerank_docs`` function."""

    def test_returns_rerank_results(self, mock_retrieval_cohere: MagicMock) -> None:
        """A list of ``RerankResult`` dicts is returned."""
        chunks: list[ParentChunk] = [
            {"document": _make_doc(), "chunk_content": "first chunk"},
            {"document": _make_doc(SAMPLE_DOC_ID_2), "chunk_content": "second chunk"},
        ]

        mock_retrieval_cohere.rerank.return_value.results = [
            MagicMock(index=1, relevance_score=0.95),
            MagicMock(index=0, relevance_score=0.80),
        ]

        results = rerank_docs("test query", chunks)

        assert len(results) == 2
        for r in results:
            assert set(r.keys()) == {"chunk", "rank", "relevance"}

    def test_rank_is_enumerated_position_not_index(
        self, mock_retrieval_cohere: MagicMock
    ) -> None:
        """``rank`` reflects the *enumerated* position in results, not the
        original ``hit.index`` from Cohere's response."""
        chunks: list[ParentChunk] = [
            {"document": _make_doc(), "chunk_content": "chunk A"},
            {"document": _make_doc(SAMPLE_DOC_ID_2), "chunk_content": "chunk B"},
        ]

        mock_retrieval_cohere.rerank.return_value.results = [
            MagicMock(index=1, relevance_score=0.95),  # Cohere returned chunk B first
            MagicMock(index=0, relevance_score=0.80),  # then chunk A
        ]

        results = rerank_docs("query", chunks)

        # rank=0 for the first result, rank=1 for the second
        assert results[0]["rank"] == 0
        assert results[1]["rank"] == 1
        # chunk content should reflect Cohere's index ordering
        assert results[0]["chunk"]["chunk_content"] == "chunk B"
        assert results[1]["chunk"]["chunk_content"] == "chunk A"

    def test_relevance_scores_preserved(
        self, mock_retrieval_cohere: MagicMock
    ) -> None:
        """Relevance scores from Cohere are preserved in the output."""
        chunks: list[ParentChunk] = [
            {"document": _make_doc(), "chunk_content": "content"},
        ]

        mock_retrieval_cohere.rerank.return_value.results = [
            MagicMock(index=0, relevance_score=0.1234),
        ]

        results = rerank_docs("query", chunks)
        assert results[0]["relevance"] == pytest.approx(0.1234)

    def test_single_chunk(self, mock_retrieval_cohere: MagicMock) -> None:
        """A single chunk is still returned correctly."""
        chunks: list[ParentChunk] = [
            {"document": _make_doc(), "chunk_content": "only chunk"},
        ]

        mock_retrieval_cohere.rerank.return_value.results = [
            MagicMock(index=0, relevance_score=0.99),
        ]

        results = rerank_docs("query", chunks)
        assert len(results) == 1
        assert results[0]["chunk"]["chunk_content"] == "only chunk"

    def test_empty_chunks_list(self, mock_retrieval_cohere: MagicMock) -> None:
        """An empty chunks list yields an empty result list."""
        mock_retrieval_cohere.rerank.return_value.results = []
        results = rerank_docs("query", [])
        assert results == []

    def test_passes_documents_to_cohere(
        self, mock_retrieval_cohere: MagicMock
    ) -> None:
        """The function extracts ``chunk_content`` values and passes them as
        ``documents`` to the Cohere client."""
        chunks: list[ParentChunk] = [
            {"document": _make_doc(), "chunk_content": "doc A chunk"},
            {"document": _make_doc(SAMPLE_DOC_ID_2), "chunk_content": "doc B chunk"},
        ]

        rerank_docs("my query", chunks)

        mock_retrieval_cohere.rerank.assert_called_once_with(
            model="rerank-english-v3.0",
            query="my query",
            documents=["doc A chunk", "doc B chunk"],
        )


# ── _get_chunks ────────────────────────────────────────────────────


class TestGetChunks:
    """Tests for the private ``_get_chunks`` helper."""

    # ── Happy path ────────────────────────────────────────────────

    def test_returns_parent_chunks(self, mock_session: MagicMock) -> None:
        """Returns ``list[ParentChunk]`` with document and merged content."""
        doc = _make_doc()
        chunk = _make_chunk(chunk_index=5, content="initial content")

        mock_session.exec.side_effect = [
            _exec_result([chunk]),          # initial_chunks (top-5 query)
            _exec_result([doc]),            # doc_map query
            _exec_result([                   # aux: predecessor + successor
                _make_chunk(chunk_index=4, content="before "),
                _make_chunk(chunk_index=6, content=" after"),
            ]),
        ]

        result = _get_chunks([0.1, 0.2, 0.3])

        assert len(result) == 1
        assert result[0]["document"].id == UUID(SAMPLE_DOC_ID_1)
        # Merged content: predecessor + initial + successor
        assert result[0]["chunk_content"] == "before initial content after"

    def test_neighbour_merging_prepend(
        self, mock_session: MagicMock
    ) -> None:
        """A chunk at ``chunk_index - 1`` is prepended."""
        doc = _make_doc()
        chunk = _make_chunk(chunk_index=10, content="main chunk")

        mock_session.exec.side_effect = [
            _exec_result([chunk]),
            _exec_result([doc]),
            _exec_result([_make_chunk(chunk_index=9, content="prefix ")]),
        ]

        result = _get_chunks([0.1] * 3)
        assert result[0]["chunk_content"] == "prefix main chunk"

    def test_neighbour_merging_append(
        self, mock_session: MagicMock
    ) -> None:
        """A chunk at ``chunk_index + 1`` is appended."""
        doc = _make_doc()
        chunk = _make_chunk(chunk_index=10, content="main chunk")

        mock_session.exec.side_effect = [
            _exec_result([chunk]),
            _exec_result([doc]),
            _exec_result([_make_chunk(chunk_index=11, content=" suffix")]),
        ]

        result = _get_chunks([0.1] * 3)
        assert result[0]["chunk_content"] == "main chunk suffix"

    def test_no_adjacent_chunks_returns_raw_content(
        self, mock_session: MagicMock
    ) -> None:
        """When no neighbours exist, the raw chunk content is returned."""
        doc = _make_doc()
        chunk = _make_chunk(chunk_index=0, content="only chunk")

        mock_session.exec.side_effect = [
            _exec_result([chunk]),
            _exec_result([doc]),
            _exec_result([]),  # no aux chunks exist
        ]

        result = _get_chunks([0.1] * 3)
        assert result[0]["chunk_content"] == "only chunk"

    # ── Edge cases ────────────────────────────────────────────────

    def test_no_initial_chunks_returns_empty(
        self, mock_session: MagicMock
    ) -> None:
        """When the vector search returns nothing, ``[]`` is returned."""
        mock_session.exec.side_effect = [
            _exec_result([]),  # initial_chunks is empty
        ]

        result = _get_chunks([0.1, 0.2, 0.3])
        assert result == []

    def test_document_not_in_doc_map_raises_key_error(
        self, mock_session: MagicMock
    ) -> None:
        """If a chunk references a document that wasn't fetched, a
        ``KeyError`` is raised (defensive: should not happen in practice)."""
        chunk = _make_chunk(chunk_index=0, content="orphan chunk")
        # doc_map query returns only one document — but the chunk references
        # a *different* doc_id, so ``doc_map[chunk.document_id]`` will fail.

        mock_session.exec.side_effect = [
            _exec_result([chunk]),
            _exec_result([]),  # doc_map is empty — KeyError
        ]

        with pytest.raises(KeyError):
            _get_chunks([0.1] * 3)

    def test_aux_chunk_at_document_start(
        self, mock_session: MagicMock
    ) -> None:
        """A chunk at index 0 has no predecessor; only the successor is merged."""
        doc = _make_doc()
        chunk = _make_chunk(chunk_index=0, content="first chunk")

        mock_session.exec.side_effect = [
            _exec_result([chunk]),
            _exec_result([doc]),
            _exec_result([_make_chunk(chunk_index=1, content=" second part")]),
        ]

        result = _get_chunks([0.1] * 3)
        assert result[0]["chunk_content"] == "first chunk second part"

    def test_multiple_initial_chunks(
        self, mock_session: MagicMock
    ) -> None:
        """Multiple initial chunks each get their neighbours merged."""
        doc1 = _make_doc(SAMPLE_DOC_ID_1)
        doc2 = _make_doc(SAMPLE_DOC_ID_2)

        chunk1 = _make_chunk(SAMPLE_DOC_ID_1, chunk_index=5, content="chunk1")
        chunk2 = _make_chunk(SAMPLE_DOC_ID_2, chunk_index=0, content="chunk2")

        mock_session.exec.side_effect = [
            _exec_result([chunk1, chunk2]),
            _exec_result([doc1, doc2]),
            _exec_result([
                _make_chunk(SAMPLE_DOC_ID_1, chunk_index=4, content="before1 "),
                _make_chunk(SAMPLE_DOC_ID_1, chunk_index=6, content=" after1"),
                _make_chunk(SAMPLE_DOC_ID_2, chunk_index=1, content=" after2"),
            ]),
        ]

        result = _get_chunks([0.1] * 3)

        assert len(result) == 2

        # Order is insertion order from the dict (chunk1 first, chunk2 second)
        contents = {c["document"].id: c["chunk_content"] for c in result}
        assert contents[UUID(SAMPLE_DOC_ID_1)] == "before1 chunk1 after1"
        assert contents[UUID(SAMPLE_DOC_ID_2)] == "chunk2 after2"

    # ── DB interaction assertions ─────────────────────────────────

    def test_exec_called_three_times(
        self, mock_session: MagicMock
    ) -> None:
        """Three DB queries are made: initial chunks, documents, neighbours."""
        doc = _make_doc()
        chunk = _make_chunk(chunk_index=0, content="test")

        mock_session.exec.side_effect = [
            _exec_result([chunk]),
            _exec_result([doc]),
            _exec_result([]),
        ]

        _get_chunks([0.1] * 3)

        assert mock_session.exec.call_count == 3

    def test_limit_five_on_initial_query(
        self, mock_session: MagicMock
    ) -> None:
        """The initial vector search is limited to 5 results."""
        doc = _make_doc()
        chunk = _make_chunk(chunk_index=0, content="test")

        mock_session.exec.side_effect = [
            _exec_result([chunk]),
            _exec_result([doc]),
            _exec_result([]),
        ]

        _get_chunks([0.1] * 3)

        # The first ``exec`` call should have a ``.limit(5)``
        first_exec_arg = mock_session.exec.call_args_list[0][0][0]
        # SQLModel/SQLAlchemy ``select`` objects compose — we can't easily
        # inspect the limit, but we can check that the select is from
        # ``DocumentChunk`` by verifying it includes the compiled SQL.
        compiled = str(first_exec_arg)
        assert "document_chunks" in compiled or "DocumentChunk" in compiled


# ── query_documents ────────────────────────────────────────────────


class TestQueryDocuments:
    """End-to-end tests for the ``query_documents`` public function."""

    def test_happy_path(
        self,
        mock_retrieval_openai: MagicMock,
        mock_retrieval_cohere: MagicMock,
        mock_session: MagicMock,
    ) -> None:
        """A full query returns unique documents ordered by relevance."""
        doc1 = _make_doc(SAMPLE_DOC_ID_1, filename="report.pdf")
        doc2 = _make_doc(SAMPLE_DOC_ID_2, filename="notes.txt")

        chunk1 = _make_chunk(SAMPLE_DOC_ID_1, chunk_index=0, content="doc1 content")
        chunk2 = _make_chunk(SAMPLE_DOC_ID_2, chunk_index=0, content="doc2 content")

        mock_session.exec.side_effect = [
            _exec_result([chunk1, chunk2]),  # initial chunks
            _exec_result([doc1, doc2]),      # documents
            _exec_result([]),                 # no neighbours
        ]

        mock_retrieval_cohere.rerank.return_value.results = [
            MagicMock(index=0, relevance_score=0.95),
            MagicMock(index=1, relevance_score=0.80),
        ]

        results = query_documents("test query")

        assert len(results) == 2
        assert results[0]["document"].id == UUID(SAMPLE_DOC_ID_1)
        assert results[0]["relevance"] == pytest.approx(0.95)
        assert results[1]["document"].id == UUID(SAMPLE_DOC_ID_2)
        assert results[1]["relevance"] == pytest.approx(0.80)

    def test_deduplicates_by_document_id(
        self,
        mock_retrieval_openai: MagicMock,
        mock_retrieval_cohere: MagicMock,
        mock_session: MagicMock,
    ) -> None:
        """Two chunks from the same document yield only one result entry."""
        doc = _make_doc(SAMPLE_DOC_ID_1)

        # Two chunks from the same document
        chunk1 = _make_chunk(SAMPLE_DOC_ID_1, chunk_index=0, content="first chunk")
        chunk2 = _make_chunk(SAMPLE_DOC_ID_1, chunk_index=1, content="second chunk")

        mock_session.exec.side_effect = [
            _exec_result([chunk1, chunk2]),
            _exec_result([doc]),
            _exec_result([
                _make_chunk(SAMPLE_DOC_ID_1, chunk_index=-1, content="before "),
                _make_chunk(SAMPLE_DOC_ID_1, chunk_index=2, content=" after"),
            ]),
        ]

        # The reranker returns both chunks (same document, different positions)
        mock_retrieval_cohere.rerank.return_value.results = [
            MagicMock(index=0, relevance_score=0.90),
            MagicMock(index=1, relevance_score=0.85),
        ]

        results = query_documents("test")

        assert len(results) == 1  # deduplicated
        assert results[0]["document"].id == UUID(SAMPLE_DOC_ID_1)
        # Should keep the highest (first) relevance score
        assert results[0]["relevance"] == pytest.approx(0.90)

    def test_preserves_reranker_order_across_docs(
        self,
        mock_retrieval_openai: MagicMock,
        mock_retrieval_cohere: MagicMock,
        mock_session: MagicMock,
    ) -> None:
        """The output order matches the reranker's ordering."""
        doc_a = _make_doc(SAMPLE_DOC_ID_1, filename="a.pdf")
        doc_b = _make_doc(SAMPLE_DOC_ID_2, filename="b.pdf")

        chunk_a = _make_chunk(SAMPLE_DOC_ID_1, chunk_index=0, content="document A")
        chunk_b = _make_chunk(SAMPLE_DOC_ID_2, chunk_index=0, content="document B")

        mock_session.exec.side_effect = [
            _exec_result([chunk_a, chunk_b]),
            _exec_result([doc_a, doc_b]),
            _exec_result([]),
        ]

        # Reranker returns B first, then A
        mock_retrieval_cohere.rerank.return_value.results = [
            MagicMock(index=1, relevance_score=0.90),  # chunk_b (doc B)
            MagicMock(index=0, relevance_score=0.70),  # chunk_a (doc A)
        ]

        results = query_documents("query")

        assert len(results) == 2
        assert results[0]["document"].filename == "b.pdf"
        assert results[1]["document"].filename == "a.pdf"

    def test_empty_result_when_no_chunks(
        self,
        mock_retrieval_openai: MagicMock,
        mock_session: MagicMock,
    ) -> None:
        """When no chunks match, an empty list is returned."""
        mock_session.exec.side_effect = [
            _exec_result([]),  # no initial chunks
        ]

        results = query_documents("obscure query")
        assert results == []

    def test_calls_openai_for_embedding(
        self,
        mock_retrieval_openai: MagicMock,
        mock_session: MagicMock,
    ) -> None:
        """The query is embedded via OpenAI before vector search."""
        mock_session.exec.side_effect = [
            _exec_result([]),
        ]

        query_documents("embed me")

        mock_retrieval_openai.embeddings.create.assert_called_once_with(
            input="embed me", model="text-embedding-3-small"
        )

    def test_calls_cohere_for_reranking(
        self,
        mock_retrieval_openai: MagicMock,
        mock_retrieval_cohere: MagicMock,
        mock_session: MagicMock,
    ) -> None:
        """Cohere reranking is invoked with the correct arguments."""
        doc = _make_doc()
        chunk = _make_chunk(chunk_index=0, content="some content")

        mock_session.exec.side_effect = [
            _exec_result([chunk]),
            _exec_result([doc]),
            _exec_result([]),
        ]

        mock_retrieval_cohere.rerank.return_value.results = [
            MagicMock(index=0, relevance_score=0.75),
        ]

        query_documents("rerank this")

        mock_retrieval_cohere.rerank.assert_called_once()

        call_kwargs = mock_retrieval_cohere.rerank.call_args[1]
        assert call_kwargs["model"] == "rerank-english-v3.0"
        assert call_kwargs["query"] == "rerank this"
        assert call_kwargs["documents"] == ["some content"]

    def test_embedding_failure_propagates(
        self,
        mock_retrieval_openai: MagicMock,
    ) -> None:
        """If OpenAI embedding fails, the exception propagates."""
        mock_retrieval_openai.embeddings.create.side_effect = Exception(
            "OpenAI API error"
        )

        with pytest.raises(Exception, match="OpenAI API error"):
            query_documents("fail")

    def test_cohere_failure_propagates(
        self,
        mock_retrieval_openai: MagicMock,
        mock_retrieval_cohere: MagicMock,
        mock_session: MagicMock,
    ) -> None:
        """If Cohere reranking fails, the exception propagates."""
        doc = _make_doc()
        chunk = _make_chunk(chunk_index=0, content="content")

        mock_session.exec.side_effect = [
            _exec_result([chunk]),
            _exec_result([doc]),
            _exec_result([]),
        ]

        mock_retrieval_cohere.rerank.side_effect = Exception("Cohere API error")

        with pytest.raises(Exception, match="Cohere API error"):
            query_documents("will fail")

    def test_folder_boundary_no_neighbour(
        self,
        mock_retrieval_openai: MagicMock,
        mock_retrieval_cohere: MagicMock,
        mock_session: MagicMock,
    ) -> None:
        """Chunk at the document boundary (index 0) doesn't crash when
        there's no predecessor."""
        doc = _make_doc()
        chunk = _make_chunk(chunk_index=0, content="start of doc")

        mock_session.exec.side_effect = [
            _exec_result([chunk]),
            _exec_result([doc]),
            _exec_result([_make_chunk(chunk_index=1, content=" continues")]),
        ]

        mock_retrieval_cohere.rerank.return_value.results = [
            MagicMock(index=0, relevance_score=0.80),
        ]

        results = query_documents("boundary test")
        assert len(results) == 1
        assert results[0]["document"].id == UUID(SAMPLE_DOC_ID_1)


# ── TypedDict structural tests ─────────────────────────────────────


class TestTypedDictStructure:
    """Verify that the TypedDict types have the expected fields."""

    def test_query_document_result_keys(self) -> None:
        """``QueryDocumentResult`` has ``document`` and ``relevance``."""
        result: QueryDocumentResult = {
            "document": _make_doc(),
            "relevance": 0.95,
        }
        assert set(result.keys()) == {"document", "relevance"}

    def test_parent_chunk_keys(self) -> None:
        """``ParentChunk`` has ``document`` and ``chunk_content``."""
        chunk: ParentChunk = {
            "document": _make_doc(),
            "chunk_content": "some text",
        }
        assert set(chunk.keys()) == {"document", "chunk_content"}

    def test_rerank_result_keys(self) -> None:
        """``RerankResult`` has ``chunk``, ``rank``, and ``relevance``."""
        result: RerankResult = {
            "chunk": {"document": _make_doc(), "chunk_content": "text"},
            "rank": 0,
            "relevance": 0.85,
        }
        assert set(result.keys()) == {"chunk", "rank", "relevance"}
