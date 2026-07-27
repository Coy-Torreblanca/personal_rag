"""Tests for GET /api/documents/search — semantic document search.

All external API calls (OpenAI embeddings, Cohere re-ranker, vector store)
are mocked so that tests run without any cloud infrastructure.
"""

from datetime import datetime
from uuid import UUID, uuid4
from unittest.mock import MagicMock

import pytest
from httpx import AsyncClient

from database.models import Document, DocumentStatus


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
