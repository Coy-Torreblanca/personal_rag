"""Tests for the document and processing-job management routes.

All S3, database, and Celery interactions are mocked so that tests run
without any external infrastructure.
"""

from uuid import UUID, uuid4
from unittest.mock import MagicMock

import pytest
from httpx import AsyncClient

from database.models import (
    Document,
    DocumentStatus,
    ProcessingJob,
    ProcessingJobStatus,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_document(**overrides) -> Document:
    """Build a ``Document`` instance with safe defaults."""
    defaults = {
        "id": uuid4(),
        "organization_id": uuid4(),
        "user_id": uuid4(),
        "filename": "report.pdf",
        "file_type": "application/pdf",
        "file_size": 1024,
        "s3_key": "org-id/report.pdf",
        "status": DocumentStatus.UPLOADED,
        "meta_data": {},
    }
    defaults.update(overrides)
    return Document(**defaults)


def make_processing_job(**overrides) -> ProcessingJob:
    """Build a ``ProcessingJob`` instance with safe defaults."""
    defaults = {
        "id": uuid4(),
        "document_id": uuid4(),
        "job_type": "Upload+Embedding",
        "status": ProcessingJobStatus.PENDING,
        "celery_task_id": None,
        "error_message": None,
        "meta_data": {},
        "started_at": None,
        "completed_at": None,
    }
    defaults.update(overrides)
    return ProcessingJob(**defaults)


# ---------------------------------------------------------------------------
# GET /api/documents
# ---------------------------------------------------------------------------


class TestGetDocuments:
    """``GET /api/documents`` — list all documents."""

    async def test_empty_list(self, async_client: AsyncClient, db_session: MagicMock) -> None:
        """Return an empty JSON array when no documents exist."""
        resp = await async_client.get("/api/documents")
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_returns_documents(self, async_client: AsyncClient, db_session: MagicMock) -> None:
        """Should serialise ``Document`` records."""
        doc = make_document(filename="test.pdf")
        db_session.exec.return_value.all.return_value = [doc]

        resp = await async_client.get("/api/documents")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["filename"] == "test.pdf"


# ---------------------------------------------------------------------------
# GET /api/documents/upload-url/{file_path:path}
# ---------------------------------------------------------------------------


class TestGetUploadUrl:
    """``GET /api/documents/upload-url/{file_path}`` — presigned URL generation."""

    async def test_returns_presigned_url(
        self, async_client: AsyncClient, db_session: MagicMock
    ) -> None:
        """Happy path — returns a presigned URL payload with a job_id."""
        org_id = uuid4()
        user_id = uuid4()

        resp = await async_client.get(
            f"/api/documents/upload-url/my-doc.pdf",
            params={
                "organization_id": str(org_id),
                "user_id": str(user_id),
                "content_type": "application/pdf",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["url"] == "https://test-bucket.r2.dev/test-key"
        assert data["method"] == "PUT"
        assert "job_id" in data

    async def test_missing_bucket_name_returns_500(
        self, async_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If ``BUCKET_NAME`` is unset, return 500."""
        monkeypatch.delenv("BUCKET_NAME", raising=False)

        org_id = uuid4()
        user_id = uuid4()
        resp = await async_client.get(
            "/api/documents/upload-url/doc.pdf",
            params={
                "organization_id": str(org_id),
                "user_id": str(user_id),
                "content_type": "text/plain",
            },
        )
        assert resp.status_code == 500
        assert "No bucket name configured" in resp.json()["detail"]

    async def test_missing_query_params_returns_422(
        self, async_client: AsyncClient
    ) -> None:
        """Omitting required query params should trigger a 422 validation error."""
        resp = await async_client.get("/api/documents/upload-url/doc.pdf")
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# POST /api/documents/{job_id}/process
# ---------------------------------------------------------------------------


class TestProcessDocument:
    """``POST /api/documents/{job_id}/process`` — trigger Celery processing."""

    @staticmethod
    def _make_get_side_effect(
        job_id: UUID, job: ProcessingJob, doc: Document | None = None
    ):
        """Build a ``side_effect`` for ``db_session.get``.

        Returns the job when asked for ``ProcessingJob`` with ``job_id``,
        and the document when asked for ``Document`` with the job's
        ``document_id`` (if a doc is provided).
        """

        def _get(model, pk):
            if model == ProcessingJob and pk == job_id:
                return job
            if doc is not None and model == Document and pk == doc.id:
                return doc
            return None

        return _get

    async def test_starts_processing(
        self, async_client: AsyncClient, db_session: MagicMock
    ) -> None:
        """Happy path — job and document exist, returns processing metadata."""
        job_id = uuid4()
        doc = make_document(status=DocumentStatus.UPLOADED, s3_key="some/key.pdf")
        job = make_processing_job(
            id=job_id, document_id=doc.id, status=ProcessingJobStatus.PENDING
        )

        db_session.get.side_effect = self._make_get_side_effect(job_id, job, doc)

        resp = await async_client.post(f"/api/documents/{job_id}/process")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "processing"
        assert data["document_id"] == str(doc.id)

    async def test_returns_404_for_unknown_job(
        self, async_client: AsyncClient, db_session: MagicMock
    ) -> None:
        """If the job does not exist, return 404."""
        # db_session.get returns None by default — no setup needed.
        resp = await async_client.post(f"/api/documents/{uuid4()}/process")
        assert resp.status_code == 404

    async def test_returns_404_when_document_missing(
        self, async_client: AsyncClient, db_session: MagicMock
    ) -> None:
        """If the job exists but its document is gone, return 404 and mark job failed."""
        job_id = uuid4()
        job = make_processing_job(id=job_id, document_id=uuid4())
        db_session.get.side_effect = self._make_get_side_effect(job_id, job)

        resp = await async_client.post(f"/api/documents/{job_id}/process")
        assert resp.status_code == 404
        # The endpoint mutates ``job.status`` in place.
        assert job.status == ProcessingJobStatus.FAILED

    async def test_rejects_already_processing_document(
        self, async_client: AsyncClient, db_session: MagicMock
    ) -> None:
        """If the document is already ``PROCESSING``, return 400."""
        job_id = uuid4()
        doc = make_document(status=DocumentStatus.PROCESSING)
        job = make_processing_job(id=job_id, document_id=doc.id, status=ProcessingJobStatus.PENDING)
        db_session.get.side_effect = self._make_get_side_effect(job_id, job, doc)

        resp = await async_client.post(f"/api/documents/{job_id}/process")
        assert resp.status_code == 400
        assert "already processing" in resp.json()["detail"]

    async def test_rejects_non_pending_job(
        self, async_client: AsyncClient, db_session: MagicMock
    ) -> None:
        """If the job is not ``PENDING``, return 400."""
        job_id = uuid4()
        doc = make_document(status=DocumentStatus.UPLOADED)
        job = make_processing_job(
            id=job_id, document_id=doc.id, status=ProcessingJobStatus.COMPLETED
        )
        db_session.get.side_effect = self._make_get_side_effect(job_id, job, doc)

        resp = await async_client.post(f"/api/documents/{job_id}/process")
        assert resp.status_code == 400
        assert "not in pending status" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# DELETE /api/documents/{document_id}
# ---------------------------------------------------------------------------


class TestDeleteDocument:
    """``DELETE /api/documents/{document_id}`` — remove document & artefacts."""

    async def test_deletes_existing_document(
        self, async_client: AsyncClient, db_session: MagicMock
    ) -> None:
        """Happy path — returns success payload."""
        doc_id = uuid4()
        doc = make_document(id=doc_id, filename="obsolete.pdf")
        db_session.get.return_value = doc

        resp = await async_client.delete(f"/api/documents/{doc_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["document_id"] == str(doc_id)

    async def test_returns_404_for_missing_document(
        self, async_client: AsyncClient, db_session: MagicMock
    ) -> None:
        """If the document does not exist, return 404."""
        db_session.get.return_value = None
        resp = await async_client.delete(f"/api/documents/{uuid4()}")
        assert resp.status_code == 404

    async def test_deletes_s3_file_and_jobs(
        self, async_client: AsyncClient, db_session: MagicMock
    ) -> None:
        """It should also delete the S3 object and related jobs."""
        doc_id = uuid4()
        doc = make_document(id=doc_id, s3_key="org/doc.pdf")
        db_session.get.return_value = doc

        resp = await async_client.delete(f"/api/documents/{doc_id}")
        assert resp.status_code == 200
        # The S3 delete + job cascade should complete without error.
        assert resp.json()["success"] is True


# ---------------------------------------------------------------------------
# GET /api/processing-jobs
# ---------------------------------------------------------------------------


class TestGetProcessingJobs:
    """``GET /api/processing-jobs`` — list all processing jobs."""

    async def test_empty_list(self, async_client: AsyncClient, db_session: MagicMock) -> None:
        """Return an empty JSON array when no jobs exist."""
        resp = await async_client.get("/api/processing-jobs")
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_returns_jobs(self, async_client: AsyncClient, db_session: MagicMock) -> None:
        """Should serialise ``ProcessingJob`` records."""
        job = make_processing_job(job_type="Upload+Embedding")
        db_session.exec.return_value.all.return_value = [job]

        resp = await async_client.get("/api/processing-jobs")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["job_type"] == "Upload+Embedding"


# ---------------------------------------------------------------------------
# GET /api/processing-jobs/{job_id}
# ---------------------------------------------------------------------------


class TestGetProcessingJob:
    """``GET /api/processing-jobs/{job_id}`` — single job fetch."""

    async def test_returns_404_when_not_found(
        self, async_client: AsyncClient, db_session: MagicMock
    ) -> None:
        """If the job does not exist, return 404."""
        db_session.get.return_value = None
        resp = await async_client.get(f"/api/processing-jobs/{uuid4()}")
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Processing job not found"

    async def test_returns_job_when_found(
        self, async_client: AsyncClient, db_session: MagicMock
    ) -> None:
        """It should return the matching ``ProcessingJob``."""
        job_id = uuid4()
        job = make_processing_job(id=job_id, job_type="Chunking")
        db_session.get.return_value = job

        resp = await async_client.get(f"/api/processing-jobs/{job_id}")
        assert resp.status_code == 200
        assert resp.json()["job_type"] == "Chunking"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Various edge cases for the document routes."""

    async def test_document_without_s3_key_returns_500(
        self, async_client: AsyncClient, db_session: MagicMock
    ) -> None:
        """If a document has no ``s3_key``, the process endpoint returns 500."""
        job_id = uuid4()
        doc = make_document(s3_key=None)  # type: ignore[arg-type]
        job = make_processing_job(id=job_id, document_id=doc.id, status=ProcessingJobStatus.PENDING)
        db_session.get.side_effect = lambda model, pk: (
            job if (model == ProcessingJob and pk == job_id)
            else doc if (model == Document and pk == doc.id)
            else None
        )

        resp = await async_client.post(f"/api/documents/{job_id}/process")
        assert resp.status_code == 500
        assert "s3 key" in resp.json()["detail"].lower()

    async def test_process_document_db_failure_rolls_back(
        self, async_client: AsyncClient, db_session: MagicMock
    ) -> None:
        """If ``db.flush()`` raises, the endpoint rolls back and re-raises."""
        job_id = uuid4()
        doc = make_document(status=DocumentStatus.UPLOADED, s3_key="some/key.pdf")
        job = make_processing_job(id=job_id, document_id=doc.id, status=ProcessingJobStatus.PENDING)

        db_session.get.side_effect = lambda model, pk: (
            job if (model == ProcessingJob and pk == job_id)
            else doc if (model == Document and pk == doc.id)
            else None
        )
        db_session.flush.side_effect = RuntimeError("DB connection lost")

        with pytest.raises(RuntimeError, match="DB connection lost"):
            await async_client.post(f"/api/documents/{job_id}/process")

        # ``rollback`` should have been called.
        db_session.rollback.assert_called_once()
