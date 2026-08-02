"""Tests for GET /api/documents/search — semantic document search.

Two layers are covered:

* route-level tests (the ``TestSearchDocuments`` class) that mock
  ``query_documents`` at the router boundary;
* unit tests for ``document_search._get_chunks`` (the ``TestGetChunks``
  class) that mock the database session and exercise the vector-search /
  neighbour-merge logic, including the PROCESSED-only document filter and
  dangling-chunk handling.

All external API calls (OpenAI embeddings, Cohere re-ranker, vector store)
are mocked so that tests run without any cloud infrastructure.
"""

import logging
from datetime import datetime
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from database.models import Document, DocumentChunk, DocumentStatus
from httpx import AsyncClient
from sqlmodel import Session as SQLModelSession

import src.document_search as document_search

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_document(**overrides) -> Document:
    """Build a ``Document`` instance with safe defaults.

    The returned object has realistic field values so that serialisation
    in the API response model can be exercised without a real database.
    """
    now = datetime.now()
    defaults = {
        "id": uuid4(),
        "organization_id": uuid4(),
        "user_id": uuid4(),
        "filename": "annual-report.pdf",
        "file_type": "application/pdf",
        "file_size": 204800,
        "s3_key": "org-id/annual-report.pdf",
        "status": DocumentStatus.PROCESSED,
        "created_at": now,
        "updated_at": now,
    }
    defaults.update(overrides)
    return Document(**defaults)


def make_search_result(document: Document, relevance: float = 0.95) -> dict:
    """Build a mock result dict matching ``QueryDocumentResult``.

    This is the structure that ``document_routes.query_documents`` is
    expected to return — a list of dicts with ``"document"`` and
    ``"relevance"`` keys.
    """
    return {"document": document, "relevance": relevance}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _mock_query_documents():
    """Replace ``query_documents`` with a mock in the document routes module.

    This prevents tests from making real API calls to OpenAI / Cohere /
    vector store.  Individual tests can customise the return value by
    accessing the mock via the ``query_documents_mock`` fixture.
    """
    from unittest.mock import patch

    with patch("src.document_routes.query_documents") as mock:
        # Default: return an empty result set so that tests expecting no
        # results pass without extra setup.
        mock.return_value = []
        yield mock


@pytest.fixture
def query_documents_mock(_mock_query_documents: MagicMock) -> MagicMock:
    """Return the mocked ``query_documents`` for per-test configuration.

    Example::

        def test_search_happy_path(query_documents_mock):
            doc = make_document(filename="report.pdf")
            query_documents_mock.return_value = [
                make_search_result(doc, relevance=0.87),
            ]
    """
    return _mock_query_documents


# ---------------------------------------------------------------------------
# GET /api/documents/search
# ---------------------------------------------------------------------------


class TestSearchDocuments:
    """``GET /api/documents/search?query=...`` — semantic document search."""

    # ── Happy path ──────────────────────────────────────────────────────

    async def test_returns_search_results(
        self,
        async_client: AsyncClient,
        query_documents_mock: MagicMock,
    ) -> None:
        """Happy path — returns a list of ``DocumentSearchResult`` items."""
        doc = make_document(filename="q4-report.pdf")
        query_documents_mock.return_value = [
            make_search_result(doc, relevance=0.87),
        ]

        resp = await async_client.get(
            "/api/documents/search",
            params={"query": "quarterly earnings report"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        item = data[0]
        assert item["filename"] == "q4-report.pdf"
        assert item["relevance"] == 0.87

    async def test_includes_all_expected_fields(
        self,
        async_client: AsyncClient,
        query_documents_mock: MagicMock,
    ) -> None:
        """Every ``DocumentSearchResult`` field should be present in the response."""
        doc = make_document()
        query_documents_mock.return_value = [make_search_result(doc, relevance=0.72)]

        resp = await async_client.get(
            "/api/documents/search",
            params={"query": "test"},
        )
        assert resp.status_code == 200
        item = resp.json()[0]

        # All model fields must be present and correctly typed.
        assert item["id"] == str(doc.id)
        assert item["organization_id"] == str(doc.organization_id)
        assert item["user_id"] == str(doc.user_id)
        assert item["filename"] == doc.filename
        assert item["s3_key"] == doc.s3_key
        assert item["file_type"] == doc.file_type
        assert item["file_size"] == doc.file_size
        assert item["status"] == doc.status.value
        # datetime fields are serialised as ISO-8601 strings by FastAPI
        assert item["created_at"] is not None
        assert item["updated_at"] is not None
        assert item["relevance"] == 0.72

    # ── Empty / edge-case results ──────────────────────────────────────

    async def test_empty_results_when_no_chunks_match(
        self,
        async_client: AsyncClient,
        query_documents_mock: MagicMock,
    ) -> None:
        """When no chunks match, return an empty list (not an error)."""
        query_documents_mock.return_value = []

        resp = await async_client.get(
            "/api/documents/search",
            params={"query": "something that does not exist"},
        )
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_multiple_results_preserves_relevance_order(
        self,
        async_client: AsyncClient,
        query_documents_mock: MagicMock,
    ) -> None:
        """Results are returned in descending relevance order."""
        doc_a = make_document(filename="high-relevance.pdf")
        doc_b = make_document(filename="low-relevance.pdf")
        query_documents_mock.return_value = [
            make_search_result(doc_a, relevance=0.99),
            make_search_result(doc_b, relevance=0.45),
        ]

        resp = await async_client.get(
            "/api/documents/search",
            params={"query": "test"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert data[0]["filename"] == "high-relevance.pdf"
        assert data[0]["relevance"] == 0.99
        assert data[1]["filename"] == "low-relevance.pdf"
        assert data[1]["relevance"] == 0.45

    async def test_single_result(
        self,
        async_client: AsyncClient,
        query_documents_mock: MagicMock,
    ) -> None:
        """A single result should still be wrapped in a list."""
        doc = make_document()
        query_documents_mock.return_value = [make_search_result(doc, relevance=0.50)]

        resp = await async_client.get(
            "/api/documents/search",
            params={"query": "single"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["relevance"] == 0.50

    # ── Input validation (handled by FastAPI / Pydantic) ────────────────

    @pytest.mark.parametrize(
        "params, expected_status",
        [
            # Missing ``query`` param entirely.
            ({}, 422),
            # Empty string (min_length=1).
            ({"query": ""}, 422),
            # Just whitespace is technically a valid non-empty string, but
            # the Cohere / OpenAI layers will receive it.  We test that the
            # route doesn't crash.
            ({"query": "   "}, 200),
        ],
    )
    async def test_query_parameter_validation(
        self,
        async_client: AsyncClient,
        query_documents_mock: MagicMock,
        params: dict,
        expected_status: int,
    ) -> None:
        """FastAPI validates ``query`` according to ``Query(...)`` constraints."""
        resp = await async_client.get("/api/documents/search", params=params)
        assert resp.status_code == expected_status

    async def test_query_too_long_returns_422(
        self,
        async_client: AsyncClient,
    ) -> None:
        """Queries exceeding 500 characters should be rejected."""
        long_query = "a" * 501
        resp = await async_client.get(
            "/api/documents/search",
            params={"query": long_query},
        )
        assert resp.status_code == 422

    async def test_query_exactly_500_chars_is_accepted(
        self,
        async_client: AsyncClient,
        query_documents_mock: MagicMock,
    ) -> None:
        """The boundary of 500 characters should be accepted."""
        query = "a" * 500
        query_documents_mock.return_value = [make_search_result(make_document())]
        resp = await async_client.get(
            "/api/documents/search",
            params={"query": query},
        )
        assert resp.status_code == 200

    # ── Error handling ─────────────────────────────────────────────────

    async def test_service_unavailable_on_connection_error(
        self,
        async_client: AsyncClient,
        query_documents_mock: MagicMock,
    ) -> None:
        """If the search backend raises an exception, return 503."""
        query_documents_mock.side_effect = ConnectionError("OpenAI API timed out")

        resp = await async_client.get(
            "/api/documents/search",
            params={"query": "quarterly report"},
        )
        assert resp.status_code == 503
        assert "unavailable" in resp.json()["detail"].lower()

    async def test_service_unavailable_on_value_error(
        self,
        async_client: AsyncClient,
        query_documents_mock: MagicMock,
    ) -> None:
        """A ``ValueError`` from the search layer also results in a 503."""
        query_documents_mock.side_effect = ValueError("Invalid embedding dimension")

        resp = await async_client.get(
            "/api/documents/search",
            params={"query": "corrupted data"},
        )
        assert resp.status_code == 503
        assert "unavailable" in resp.json()["detail"].lower()

    # ── Relevance clamping ──────────────────────────────────────────────

    @pytest.mark.parametrize(
        "raw_relevance, expected_clamped",
        [
            (0.5, 0.5),      # Within [0, 1] — unchanged.
            (1.0, 1.0),      # Upper boundary.
            (0.0, 0.0),      # Lower boundary.
            (1.5, 1.0),      # Above 1 — clamped to 1.0.
            (-0.1, 0.0),     # Below 0 — clamped to 0.0.
        ],
    )
    async def test_relevance_clamping(
        self,
        async_client: AsyncClient,
        query_documents_mock: MagicMock,
        raw_relevance: float,
        expected_clamped: float,
    ) -> None:
        """Relevance scores are clamped to the ``[0, 1]`` range."""
        doc = make_document()
        query_documents_mock.return_value = [
            make_search_result(doc, relevance=raw_relevance),
        ]

        resp = await async_client.get(
            "/api/documents/search",
            params={"query": "clamping"},
        )
        assert resp.status_code == 200
        assert resp.json()[0]["relevance"] == expected_clamped

    async def test_missing_relevance_defaults_to_zero(
        self,
        async_client: AsyncClient,
        query_documents_mock: MagicMock,
    ) -> None:
        """If ``query_documents`` omits ``relevance``, treat it as 0.0."""
        doc = make_document()
        # Return a dict *without* the "relevance" key.
        query_documents_mock.return_value = [{"document": doc}]

        resp = await async_client.get(
            "/api/documents/search",
            params={"query": "missing field"},
        )
        assert resp.status_code == 200
        assert resp.json()[0]["relevance"] == 0.0

    # ── Document with nullable fields ───────────────────────────────────

    async def test_handles_nullable_fields(
        self,
        async_client: AsyncClient,
        query_documents_mock: MagicMock,
    ) -> None:
        """Fields like ``s3_key``, ``file_size``, ``created_at`` can be null."""
        doc = make_document(
            s3_key=None,
            file_size=None,
            created_at=None,
            updated_at=None,
        )
        query_documents_mock.return_value = [make_search_result(doc, relevance=0.60)]

        resp = await async_client.get(
            "/api/documents/search",
            params={"query": "nullable"},
        )
        assert resp.status_code == 200
        item = resp.json()[0]
        assert item["s3_key"] is None
        assert item["file_size"] is None
        assert item["created_at"] is None
        assert item["updated_at"] is None

    # ── Different document statuses ─────────────────────────────────────

    @pytest.mark.parametrize(
        "status",
        [
            DocumentStatus.UPLOADING,
            DocumentStatus.UPLOADED,
            DocumentStatus.PROCESSING,
            DocumentStatus.PROCESSED,
            DocumentStatus.ERROR,
        ],
    )
    async def test_all_document_statuses_are_serialised(
        self,
        async_client: AsyncClient,
        query_documents_mock: MagicMock,
        status: DocumentStatus,
    ) -> None:
        """Every ``DocumentStatus`` value should serialise without error."""
        doc = make_document(status=status)
        query_documents_mock.return_value = [make_search_result(doc, relevance=0.50)]

        resp = await async_client.get(
            "/api/documents/search",
            params={"query": "status test"},
        )
        assert resp.status_code == 200
        assert resp.json()[0]["status"] == status.value


# ---------------------------------------------------------------------------
# Unit tests for document_search._get_chunks
# ---------------------------------------------------------------------------


class TestGetChunks:
    """Unit tests for ``document_search._get_chunks`` with a mocked session.

    ``_get_chunks`` obtains its session via ``contextmanager(get_db)()``
    where ``get_db`` is the module-level import from ``database.session``.
    Tests monkeypatch ``document_search.get_db`` with a plain generator
    function (NOT a ``@contextmanager``-decorated one, which would be
    double-wrapped) yielding a ``MagicMock`` session whose ``exec`` returns
    the three result sets in call order:

    1. initial vector-search chunks,
    2. parent documents (already filtered to ``PROCESSED`` by the query),
    3. neighbour chunks.
    """

    LOGGER_NAME = "src.document_search"

    @staticmethod
    def _make_chunk(doc_id: UUID, index: int, content: str) -> DocumentChunk:
        """Build a ``DocumentChunk`` with the minimum required fields."""
        return DocumentChunk(
            document_id=doc_id,
            organization_id=uuid4(),
            chunk_index=index,
            content=content,
        )

    @staticmethod
    def _fake_get_db(session: MagicMock):
        """Generator-function stand-in for ``database.session.get_db``."""

        def _gen():
            yield session

        return _gen

    def _run(
        self,
        monkeypatch: pytest.MonkeyPatch,
        session: MagicMock,
        vector: list[float] | None = None,
    ) -> list[dict]:
        """Patch ``get_db`` and invoke ``_get_chunks``."""
        monkeypatch.setattr(document_search, "get_db", self._fake_get_db(session))
        return document_search._get_chunks(vector or [0.1] * 8)

    def _new_session(self, *results: list) -> MagicMock:
        """Session whose ``exec`` returns each result set in call order.

        ``db.exec(...)`` returns a result object with an ``.all()`` method
        (mirroring ``sqlmodel.Session.exec``), so each entry is wrapped in
        a mock exposing ``all()``.
        """
        session = MagicMock(spec=SQLModelSession)
        exec_results = []
        for rows in results:
            result = MagicMock()
            result.all.return_value = rows
            exec_results.append(result)
        session.exec.side_effect = exec_results
        return session

    # ── Happy path ──────────────────────────────────────────────────────

    def test_returns_merged_chunks_for_processed_document(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Neighbours are merged (prepend/append) into their parent chunk."""
        doc = make_document(status=DocumentStatus.PROCESSED)
        initial = [
            self._make_chunk(doc.id, 0, "A"),
            self._make_chunk(doc.id, 5, "E"),
        ]
        aux = [
            self._make_chunk(doc.id, 1, "B"),   # successor of chunk 0
            self._make_chunk(doc.id, 4, "D"),   # predecessor of chunk 5
            self._make_chunk(doc.id, 6, "F"),   # successor of chunk 5
        ]
        session = self._new_session(initial, [doc], aux)

        with caplog.at_level(logging.INFO, logger=self.LOGGER_NAME):
            result = self._run(monkeypatch, session)

        # Order follows the initial vector-search ranking.
        assert len(result) == 2
        assert result[0]["document"].id == doc.id
        assert result[0]["chunk_content"] == "AB"
        assert result[1]["chunk_content"] == "DEF"

        # Vector search → document fetch → neighbour fetch.
        assert session.exec.call_count == 3

        # The doc-fetch query must have filtered on PROCESSED status.
        doc_stmt = session.exec.call_args_list[1].args[0]
        assert "status" in str(doc_stmt)

    # ── Dangling chunks (missing / non-PROCESSED parents) ───────────────

    def test_skips_dangling_chunks_and_logs_warning(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Chunks of non-PROCESSED documents are dropped with a warning, and
        their neighbours are excluded from the aux-chunk query."""
        good_doc = make_document(status=DocumentStatus.PROCESSED)
        bad_doc = make_document(status=DocumentStatus.ERROR)
        initial = [
            self._make_chunk(good_doc.id, 0, "A"),
            self._make_chunk(bad_doc.id, 0, "X"),
        ]
        # The DB query only returns PROCESSED documents — exactly what the
        # real ``select(Document).where(status == PROCESSED)`` would return.
        aux = [self._make_chunk(good_doc.id, 1, "B")]
        session = self._new_session(initial, [good_doc], aux)

        with caplog.at_level(logging.WARNING, logger=self.LOGGER_NAME):
            result = self._run(monkeypatch, session)

        assert len(result) == 1
        assert result[0]["chunk_content"] == "AB"

        # A warning must have been emitted for the dangling chunk.
        warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert any(str(bad_doc.id) in w.getMessage() for w in warnings)

        # The aux-chunk query must not reference the dangling document.
        aux_stmt = session.exec.call_args_list[2].args[0]
        pairs = next(iter(aux_stmt.compile().params.values()))
        assert all(doc_id != bad_doc.id for doc_id, _ in pairs)
        assert all(doc_id == good_doc.id for doc_id, _ in pairs)

    def test_returns_empty_when_all_chunks_dangle(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """When no parent document is PROCESSED the result is empty and the
        neighbour fetch is skipped entirely (no wasted DB round-trip)."""
        ghost_doc = make_document(status=DocumentStatus.UPLOADED)
        initial = [self._make_chunk(ghost_doc.id, 0, "A")]
        session = self._new_session(initial, [])

        with caplog.at_level(logging.WARNING, logger=self.LOGGER_NAME):
            result = self._run(monkeypatch, session)

        assert result == []
        # Only the vector search and the document fetch ran.
        assert session.exec.call_count == 2
        assert any("dangling" in r.getMessage() for r in caplog.records)

    def test_returns_empty_when_no_initial_chunks(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """No vector hits → empty result, single DB query."""
        session = self._new_session([])

        with caplog.at_level(logging.INFO, logger=self.LOGGER_NAME):
            result = self._run(monkeypatch, session)

        assert result == []
        assert session.exec.call_count == 1

    # ── Neighbour edge cases ────────────────────────────────────────────

    def test_single_chunk_without_neighbours_is_unchanged(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A lone chunk with no adjacent chunks keeps its raw content."""
        doc = make_document(status=DocumentStatus.PROCESSED)
        initial = [self._make_chunk(doc.id, 0, "solo")]
        session = self._new_session(initial, [doc], [])

        result = self._run(monkeypatch, session)

        assert len(result) == 1
        assert result[0]["chunk_content"] == "solo"

    def test_shared_neighbour_merged_into_both_parents(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A neighbour between two initial chunks (indexes 0 and 2) is
        merged into *both* parents — the known duplication edge case
        documented in ``_get_chunks``."""
        doc = make_document(status=DocumentStatus.PROCESSED)
        initial = [
            self._make_chunk(doc.id, 0, "0"),
            self._make_chunk(doc.id, 2, "2"),
        ]
        aux = [self._make_chunk(doc.id, 1, "1")]
        session = self._new_session(initial, [doc], aux)

        result = self._run(monkeypatch, session)

        assert [r["chunk_content"] for r in result] == ["01", "12"]
