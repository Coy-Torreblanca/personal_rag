"""Tests for the document and processing-job management routes.

All S3, database, and Celery interactions are mocked so that tests run
without any external infrastructure.
"""

import unittest
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from database.models import (
    Document,
    DocumentChunk,
    DocumentStatus,
    ProcessingJob,
    ProcessingJobStatus,
)
from httpx import AsyncClient
from s3.exceptions import S3Error
from sqlalchemy import Delete

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
        self, async_client: AsyncClient, db_session: MagicMock, r2_client: MagicMock
    ) -> None:
        """Happy path — returns a presigned URL payload with a job_id."""
        org_id = uuid4()
        user_id = uuid4()

        resp = await async_client.get(
            "/api/documents/upload-url/my-doc.pdf",
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

        # The presigned URL must be signed for the org-prefixed key with the
        # client's content type (required for the CORS preflight to match).
        r2_client.generate_presigned_url.assert_called_once_with(
            key=f"{org_id}/my-doc.pdf",
            expiration=3600,
            method="PUT",
            inline=False,
            content_type="application/pdf",
        )

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

    async def test_prevents_concurrent_processing(
        self, async_client: AsyncClient, db_session: MagicMock
    ) -> None:
        """Return 400 if a doc with this key already has an active (non-failed, non-completed) job."""
        org_id = uuid4()
        user_id = uuid4()
        key = f"{org_id}/my-doc.pdf"

        existing_doc = make_document(
            organization_id=org_id,
            s3_key=key,
        )

        # Make ``db.exec(select(Document).where(...))`` iterate over the
        # existing document.
        db_session.exec.return_value.__iter__.return_value = iter([existing_doc])

        # Simulate an active (PENDING) job found for that document.
        db_session.scalar.return_value = 1

        resp = await async_client.get(
            "/api/documents/upload-url/my-doc.pdf",
            params={
                "organization_id": str(org_id),
                "user_id": str(user_id),
                "content_type": "application/pdf",
            },
        )
        assert resp.status_code == 400
        assert "already being processed" in resp.json()["detail"]

    async def test_allows_upload_when_previous_jobs_completed(
        self, async_client: AsyncClient, db_session: MagicMock
    ) -> None:
        """Allow upload when the only existing jobs are COMPLETED or FAILED."""
        org_id = uuid4()
        user_id = uuid4()
        key = f"{org_id}/my-doc.pdf"

        existing_doc = make_document(
            organization_id=org_id,
            s3_key=key,
        )

        # Make ``db.exec(select(Document).where(...))`` iterate over the
        # existing document.
        db_session.exec.return_value.__iter__.return_value = iter([existing_doc])

        # No active jobs — only completed/failed ones.
        db_session.scalar.return_value = 0

        resp = await async_client.get(
            "/api/documents/upload-url/my-doc.pdf",
            params={
                "organization_id": str(org_id),
                "user_id": str(user_id),
                "content_type": "application/pdf",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        # The superseded document must be marked STALE.
        assert existing_doc.status == DocumentStatus.STALE

    async def test_marks_existing_document_stale_on_reupload(
        self, async_client: AsyncClient, db_session: MagicMock
    ) -> None:
        """A superseded doc (no active jobs) is marked STALE on re-upload."""
        org_id = uuid4()
        user_id = uuid4()
        key = f"{org_id}/my-doc.pdf"

        existing_doc = make_document(
            organization_id=org_id,
            s3_key=key,
            status=DocumentStatus.PROCESSED,
        )

        # Make ``db.exec(select(Document).where(...))`` iterate over the
        # existing document.
        db_session.exec.return_value.__iter__.return_value = iter([existing_doc])

        # No active jobs — only completed/failed ones.
        db_session.scalar.return_value = 0

        resp = await async_client.get(
            "/api/documents/upload-url/my-doc.pdf",
            params={
                "organization_id": str(org_id),
                "user_id": str(user_id),
                "content_type": "application/pdf",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True

        # The superseded document must be transitioned to STALE...
        assert existing_doc.status == DocumentStatus.STALE

        # ...and the transition is folded into the new Document's commit
        # (doc + stale = commit 1, job = commit 2) — no extra transaction.
        assert db_session.commit.call_count == 2

    async def test_marks_all_superseded_documents_stale_keeps_error(
        self, async_client: AsyncClient, db_session: MagicMock
    ) -> None:
        """ERROR docs keep their status; other docs sharing the key go STALE."""
        org_id = uuid4()
        user_id = uuid4()
        key = f"{org_id}/my-doc.pdf"

        error_doc = make_document(
            organization_id=org_id, s3_key=key, status=DocumentStatus.ERROR
        )
        uploaded_doc = make_document(
            organization_id=org_id, s3_key=key, status=DocumentStatus.UPLOADED
        )
        already_stale_doc = make_document(
            organization_id=org_id, s3_key=key, status=DocumentStatus.STALE
        )

        db_session.exec.return_value.__iter__.return_value = iter(
            [error_doc, uploaded_doc, already_stale_doc]
        )
        db_session.scalar.return_value = 0

        resp = await async_client.get(
            "/api/documents/upload-url/my-doc.pdf",
            params={
                "organization_id": str(org_id),
                "user_id": str(user_id),
                "content_type": "application/pdf",
            },
        )
        assert resp.status_code == 200

        # ERROR documents stay ERROR (the failure remains visible)...
        assert error_doc.status == DocumentStatus.ERROR
        # ...everything else pointing at the overwritten key becomes STALE.
        assert uploaded_doc.status == DocumentStatus.STALE
        assert already_stale_doc.status == DocumentStatus.STALE

    async def test_presign_failure_does_not_mark_stale(
        self,
        async_client: AsyncClient,
        db_session: MagicMock,
        r2_client: MagicMock,
    ) -> None:
        """A failed presign must not transition documents to STALE."""
        org_id = uuid4()
        user_id = uuid4()
        key = f"{org_id}/my-doc.pdf"

        existing_doc = make_document(
            organization_id=org_id,
            s3_key=key,
            status=DocumentStatus.PROCESSED,
        )
        db_session.exec.return_value.__iter__.return_value = iter([existing_doc])
        db_session.scalar.return_value = 0

        r2_client.generate_presigned_url.side_effect = S3Error("Network error")

        resp = await async_client.get(
            "/api/documents/upload-url/my-doc.pdf",
            params={
                "organization_id": str(org_id),
                "user_id": str(user_id),
                "content_type": "application/pdf",
            },
        )
        assert resp.status_code == 500

        # The "presign before persist" invariant must hold even when stale
        # candidates exist: no status transition, no writes at all.
        assert existing_doc.status == DocumentStatus.PROCESSED
        assert db_session.add.call_args_list == []
        assert db_session.commit.call_args_list == []

    async def test_presign_failure_returns_500_and_creates_no_records(
        self,
        async_client: AsyncClient,
        db_session: MagicMock,
        r2_client: MagicMock,
    ) -> None:
        """If presigning fails, return 500 without creating any records."""
        org_id = uuid4()
        user_id = uuid4()

        r2_client.generate_presigned_url.side_effect = S3Error("Network error")

        resp = await async_client.get(
            "/api/documents/upload-url/my-doc.pdf",
            params={
                "organization_id": str(org_id),
                "user_id": str(user_id),
                "content_type": "application/pdf",
            },
        )
        assert resp.status_code == 500
        assert "Failed to generate upload URL" in resp.json()["detail"]

        # Records are only persisted after the presigned URL succeeds, so a
        # failure must not create (or delete) anything — the key stays
        # unlocked and free of orphaned jobs.
        assert db_session.add.call_args_list == []
        assert db_session.commit.call_args_list == []
        assert db_session.delete.call_args_list == []

    async def test_presign_happens_before_persist(
        self,
        async_client: AsyncClient,
        db_session: MagicMock,
        r2_client: MagicMock,
    ) -> None:
        """The presigned URL is generated before any DB records are created.

        Guards the ordering invariant that prevents orphaned
        Document/ProcessingJob pairs when presigning fails.
        """
        org_id = uuid4()
        user_id = uuid4()

        events: list[str] = []
        real_side_effect = r2_client.generate_presigned_url.side_effect

        def _recording_presign(**kwargs):
            """Record the presign event, then delegate to the default mock."""
            events.append("presign")
            return real_side_effect(**kwargs)

        def _recording_add(*args, **kwargs):
            """Record the db.add event."""
            events.append("add")

        r2_client.generate_presigned_url.side_effect = _recording_presign
        db_session.add.side_effect = _recording_add

        resp = await async_client.get(
            "/api/documents/upload-url/my-doc.pdf",
            params={
                "organization_id": str(org_id),
                "user_id": str(user_id),
                "content_type": "application/pdf",
            },
        )
        assert resp.status_code == 200

        # The very first recorded event must be the presign call; DB writes
        # (two ``add`` calls: Document + ProcessingJob) only happen after.
        assert events[0] == "presign"
        assert events[1:] == ["add", "add"]


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

    async def test_rejects_missing_file_in_r2(
        self, async_client: AsyncClient, db_session: MagicMock, r2_client: MagicMock
    ) -> None:
        """Return 400 if the source file hasn't been uploaded to R2 yet."""
        job_id = uuid4()
        doc = make_document(status=DocumentStatus.UPLOADED, s3_key="some/key.pdf")
        job = make_processing_job(
            id=job_id, document_id=doc.id, status=ProcessingJobStatus.PENDING
        )

        db_session.get.side_effect = self._make_get_side_effect(job_id, job, doc)

        # Simulate file not found in R2.
        r2_client.file_exists.return_value = False

        resp = await async_client.post(f"/api/documents/{job_id}/process")
        assert resp.status_code == 400
        assert "not been uploaded" in resp.json()["detail"].lower()

    async def test_presign_failure_returns_500_and_keeps_job_pending(
        self,
        async_client: AsyncClient,
        db_session: MagicMock,
        r2_client: MagicMock,
    ) -> None:
        """If presigning fails, return 500 without mutating job state."""
        job_id = uuid4()
        doc = make_document(status=DocumentStatus.UPLOADED, s3_key="some/key.pdf")
        job = make_processing_job(
            id=job_id, document_id=doc.id, status=ProcessingJobStatus.PENDING
        )

        db_session.get.side_effect = self._make_get_side_effect(job_id, job, doc)

        r2_client.generate_presigned_url.side_effect = S3Error("Network error")

        resp = await async_client.post(f"/api/documents/{job_id}/process")
        assert resp.status_code == 500
        assert "Failed to prepare document processing" in resp.json()["detail"]

        # Statuses must not have been transitioned.
        assert job.status == ProcessingJobStatus.PENDING
        assert doc.status == DocumentStatus.UPLOADED

    async def test_presign_uses_download_and_upload_keys(
        self,
        async_client: AsyncClient,
        db_session: MagicMock,
        r2_client: MagicMock,
    ) -> None:
        """Presigned URLs are generated for the source (GET) and .md output (PUT)."""
        job_id = uuid4()
        doc = make_document(status=DocumentStatus.UPLOADED, s3_key="some/key.pdf")
        job = make_processing_job(
            id=job_id, document_id=doc.id, status=ProcessingJobStatus.PENDING
        )

        db_session.get.side_effect = self._make_get_side_effect(job_id, job, doc)

        resp = await async_client.post(f"/api/documents/{job_id}/process")
        assert resp.status_code == 200

        # The source file existence check runs first.
        r2_client.file_exists.assert_called_once_with(key="some/key.pdf")

        # Two presigned URLs: a GET for the original and a PUT for the
        # processed Markdown output.
        assert r2_client.generate_presigned_url.call_count == 2
        r2_client.generate_presigned_url.assert_any_call(
            key="some/key.pdf",
            expiration=3600,
            method="GET",
            inline=False,
        )
        r2_client.generate_presigned_url.assert_any_call(
            key="some/key.pdf.md",
            expiration=3600,
            method="PUT",
            inline=False,
        )


# ---------------------------------------------------------------------------
# GET /api/documents/{document_id}/download
# ---------------------------------------------------------------------------


class TestDownloadDocument:
    """``GET /api/documents/{document_id}/download`` — presigned GET URL."""

    async def test_returns_presigned_download_url(
        self, async_client: AsyncClient, db_session: MagicMock
    ) -> None:
        """Happy path — returns a presigned GET URL and the original filename."""
        doc_id = uuid4()
        doc = make_document(
            id=doc_id,
            filename="report.pdf",
            s3_key="org-id/report.pdf",
        )
        db_session.get.return_value = doc

        resp = await async_client.get(f"/api/documents/{doc_id}/download")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["url"] == "https://test-bucket.r2.dev/test-key"
        assert data["filename"] == "report.pdf"
        assert data["method"] == "GET"
        assert data["expires_in"] == 3600
        assert data["key"] == "test-key"
        assert "GET" in data["message"]

    async def test_returns_404_for_missing_document(
        self, async_client: AsyncClient, db_session: MagicMock
    ) -> None:
        """If the document does not exist, return 404."""
        db_session.get.return_value = None
        resp = await async_client.get(f"/api/documents/{uuid4()}/download")
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Document not found"

    async def test_returns_404_when_file_missing_in_r2(
        self,
        async_client: AsyncClient,
        db_session: MagicMock,
        r2_client: MagicMock,
    ) -> None:
        """If the object was never uploaded, return 404 instead of signing a dead URL."""
        doc_id = uuid4()
        doc = make_document(id=doc_id, s3_key="org-id/report.pdf")
        db_session.get.return_value = doc

        r2_client.file_exists.return_value = False

        resp = await async_client.get(f"/api/documents/{doc_id}/download")
        assert resp.status_code == 404
        assert "not been uploaded" in resp.json()["detail"].lower()

        # No URL may be signed for an object that does not exist.
        r2_client.generate_presigned_url.assert_not_called()

    async def test_presign_uses_document_key(
        self,
        async_client: AsyncClient,
        db_session: MagicMock,
        r2_client: MagicMock,
    ) -> None:
        """The presigned URL is signed for the document's own S3 key with GET."""
        doc_id = uuid4()
        doc = make_document(id=doc_id, s3_key="org-id/report.pdf")
        db_session.get.return_value = doc

        resp = await async_client.get(f"/api/documents/{doc_id}/download")
        assert resp.status_code == 200

        # Existence is verified first, then the URL is signed for the same key.
        r2_client.file_exists.assert_called_once_with(key="org-id/report.pdf")
        r2_client.generate_presigned_url.assert_called_once_with(
            key="org-id/report.pdf",
            expiration=3600,
            method="GET",
            inline=False,
        )

    async def test_invalid_document_id_returns_422(
        self, async_client: AsyncClient
    ) -> None:
        """A non-UUID path segment must be rejected by FastAPI validation."""
        resp = await async_client.get("/api/documents/not-a-uuid/download")
        assert resp.status_code == 422

    async def test_missing_s3_key_returns_500(
        self, async_client: AsyncClient, db_session: MagicMock
    ) -> None:
        """If the document has no ``s3_key``, return 500."""
        doc_id = uuid4()
        doc = make_document(id=doc_id, s3_key=None)  # type: ignore[arg-type]
        db_session.get.return_value = doc

        resp = await async_client.get(f"/api/documents/{doc_id}/download")
        assert resp.status_code == 500
        assert "s3 key" in resp.json()["detail"].lower()

    async def test_missing_bucket_name_returns_500(
        self, async_client: AsyncClient, db_session: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If ``BUCKET_NAME`` is unset, return 500."""
        monkeypatch.delenv("BUCKET_NAME", raising=False)

        doc_id = uuid4()
        doc = make_document(id=doc_id, s3_key="org-id/report.pdf")
        db_session.get.return_value = doc

        resp = await async_client.get(f"/api/documents/{doc_id}/download")
        assert resp.status_code == 500
        assert "No bucket name configured" in resp.json()["detail"]

    async def test_presign_failure_returns_500(
        self,
        async_client: AsyncClient,
        db_session: MagicMock,
        r2_client: MagicMock,
    ) -> None:
        """If presigning fails, return a meaningful 500 instead of a bare traceback."""
        doc_id = uuid4()
        doc = make_document(id=doc_id, s3_key="org-id/report.pdf")
        db_session.get.return_value = doc

        r2_client.generate_presigned_url.side_effect = S3Error("Network error")

        resp = await async_client.get(f"/api/documents/{doc_id}/download")
        assert resp.status_code == 500
        assert "Failed to generate download URL" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# GET /api/documents/{document_id}
# ---------------------------------------------------------------------------


class TestGetDocument:
    """``GET /api/documents/{document_id}`` — metadata + summary + markdown."""

    async def test_returns_metadata_summary_and_markdown(
        self,
        async_client: AsyncClient,
        db_session: MagicMock,
        r2_client: MagicMock,
    ) -> None:
        """Happy path — returns full metadata, summary, and markdown content."""
        doc_id = uuid4()
        doc = make_document(
            id=doc_id,
            filename="report.pdf",
            s3_key="org-id/report.pdf",
            summary="A dense summary of the report.",
            status=DocumentStatus.PROCESSED,
        )
        db_session.get.return_value = doc
        r2_client.download_bytes.return_value.content = (
            b"# Report\n\nKey findings..."
        )

        resp = await async_client.get(f"/api/documents/{doc_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == str(doc_id)
        assert data["filename"] == "report.pdf"
        assert data["status"] == "processed"
        assert data["summary"] == "A dense summary of the report."
        assert data["markdown_content"] == "# Report\n\nKey findings..."

        # Non-text sources are read from ``<s3_key>.md``.
        r2_client.download_bytes.assert_called_once_with(
            key="org-id/report.pdf.md"
        )

    async def test_reads_original_key_for_text_files(
        self,
        async_client: AsyncClient,
        db_session: MagicMock,
        r2_client: MagicMock,
    ) -> None:
        """Plain-text sources are already markdown — read from the original key."""
        doc_id = uuid4()
        doc = make_document(
            id=doc_id,
            filename="notes.md",
            s3_key="org-id/notes.md",
            file_type="text/markdown",
            summary=None,
        )
        db_session.get.return_value = doc
        r2_client.download_bytes.return_value.content = b"# Notes\n\nBody"

        resp = await async_client.get(f"/api/documents/{doc_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["markdown_content"] == "# Notes\n\nBody"
        assert data["summary"] is None
        r2_client.download_bytes.assert_called_once_with(key="org-id/notes.md")

    async def test_reads_original_key_for_txt_files(
        self,
        async_client: AsyncClient,
        db_session: MagicMock,
        r2_client: MagicMock,
    ) -> None:
        """A ``.txt`` source is already markdown — read from the original key."""
        doc_id = uuid4()
        doc = make_document(
            id=doc_id,
            filename="notes.txt",
            s3_key="org-id/notes.txt",
            file_type="text/plain",
        )
        db_session.get.return_value = doc
        r2_client.download_bytes.return_value.content = b"Plain text body"

        resp = await async_client.get(f"/api/documents/{doc_id}")
        assert resp.status_code == 200
        assert resp.json()["markdown_content"] == "Plain text body"
        r2_client.download_bytes.assert_called_once_with(key="org-id/notes.txt")

    async def test_returns_null_markdown_on_unexpected_download_error(
        self,
        async_client: AsyncClient,
        db_session: MagicMock,
        r2_client: MagicMock,
    ) -> None:
        """Unexpected storage errors (timeouts, ...) degrade to ``null`` too."""
        doc_id = uuid4()
        doc = make_document(
            id=doc_id,
            s3_key="org-id/report.pdf",
            summary="Summary survives the failure.",
        )
        db_session.get.return_value = doc
        r2_client.download_bytes.side_effect = ConnectionError("boom")

        resp = await async_client.get(f"/api/documents/{doc_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["summary"] == "Summary survives the failure."
        assert data["markdown_content"] is None

    async def test_returns_404_for_missing_document(
        self, async_client: AsyncClient, db_session: MagicMock
    ) -> None:
        """If the document does not exist, return 404."""
        db_session.get.return_value = None
        resp = await async_client.get(f"/api/documents/{uuid4()}")
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Document not found"

    async def test_returns_null_markdown_when_download_fails(
        self,
        async_client: AsyncClient,
        db_session: MagicMock,
        r2_client: MagicMock,
    ) -> None:
        """Missing/unavailable markdown degrades to ``null``, not a 500."""
        doc_id = uuid4()
        doc = make_document(
            id=doc_id,
            s3_key="org-id/report.pdf",
            summary="Summary is still available.",
        )
        db_session.get.return_value = doc
        r2_client.download_bytes.side_effect = S3Error("Object not found")

        resp = await async_client.get(f"/api/documents/{doc_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["summary"] == "Summary is still available."
        assert data["markdown_content"] is None

    async def test_returns_null_markdown_without_s3_key(
        self, async_client: AsyncClient, db_session: MagicMock
    ) -> None:
        """A document with no S3 key skips the object-storage fetch entirely."""
        doc_id = uuid4()
        doc = make_document(id=doc_id, s3_key=None)  # type: ignore[arg-type]
        db_session.get.return_value = doc

        resp = await async_client.get(f"/api/documents/{doc_id}")
        assert resp.status_code == 200
        assert resp.json()["markdown_content"] is None

    async def test_invalid_document_id_returns_422(
        self, async_client: AsyncClient
    ) -> None:
        """A non-UUID path segment must be rejected by FastAPI validation."""
        resp = await async_client.get("/api/documents/not-a-uuid")
        assert resp.status_code == 422

    async def test_returns_null_markdown_without_bucket_name(
        self,
        async_client: AsyncClient,
        db_session: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Missing ``BUCKET_NAME`` degrades markdown to ``null``."""
        monkeypatch.delenv("BUCKET_NAME", raising=False)

        doc_id = uuid4()
        doc = make_document(
            id=doc_id,
            s3_key="org-id/report.pdf",
            summary="Summary from the database.",
        )
        db_session.get.return_value = doc

        resp = await async_client.get(f"/api/documents/{doc_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["summary"] == "Summary from the database."
        assert data["markdown_content"] is None

    async def test_decodes_non_utf8_content_with_replacement_chars(
        self,
        async_client: AsyncClient,
        db_session: MagicMock,
        r2_client: MagicMock,
    ) -> None:
        """Non-UTF-8 bytes decode to U+FFFD replacement chars, never a 500."""
        doc_id = uuid4()
        doc = make_document(id=doc_id, s3_key="org-id/report.pdf")
        db_session.get.return_value = doc
        # "café" encoded as latin-1 — invalid UTF-8.
        r2_client.download_bytes.return_value.content = b"caf\xe9"

        resp = await async_client.get(f"/api/documents/{doc_id}")
        assert resp.status_code == 200
        assert resp.json()["markdown_content"] == "caf\ufffd"

    async def test_unknown_extension_reads_suffixed_markdown_key(
        self,
        async_client: AsyncClient,
        db_session: MagicMock,
        r2_client: MagicMock,
    ) -> None:
        """Unmapped extensions (FileType.OTHER) use the ``<s3_key>.md`` key."""
        doc_id = uuid4()
        doc = make_document(
            id=doc_id,
            filename="report.xyz",
            s3_key="org-id/report.xyz",
        )
        db_session.get.return_value = doc
        r2_client.download_bytes.return_value.content = b"# Report"

        resp = await async_client.get(f"/api/documents/{doc_id}")
        assert resp.status_code == 200
        assert resp.json()["markdown_content"] == "# Report"
        r2_client.download_bytes.assert_called_once_with(
            key="org-id/report.xyz.md"
        )

    async def test_document_id_route_does_not_shadow_search_route(
        self,
        async_client: AsyncClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``/documents/search`` must still resolve after adding ``{document_id}``.

        Regression guard: FastAPI matches routes in declaration order, so a
        new ``/documents/{document_id}`` route could shadow the
        same-segment-count ``/documents/search`` route ("search" would be
        rejected as a malformed UUID with 422) if it were ever registered
        before it.
        """
        monkeypatch.setattr(
            "src.document_routes.query_documents",
            lambda query: [],
        )

        resp = await async_client.get(
            "/api/documents/search", params={"query": "hello"}
        )
        assert resp.status_code == 200
        assert resp.json() == []


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

    async def test_deletes_processed_md_file(
        self,
        async_client: AsyncClient,
        db_session: MagicMock,
        r2_client: MagicMock,
    ) -> None:
        """When a processed ``.md`` file exists, it should also be deleted."""
        doc_id = uuid4()
        doc = make_document(id=doc_id, s3_key="org/doc.pdf")
        db_session.get.return_value = doc

        resp = await async_client.delete(f"/api/documents/{doc_id}")
        assert resp.status_code == 200

        # The original file and the .md file should both be deleted.
        expected_calls = [
            unittest.mock.call(key="org/doc.pdf"),
            unittest.mock.call(key="org/doc.pdf.md"),
        ]
        r2_client.delete_file.assert_has_calls(expected_calls, any_order=False)
        assert r2_client.delete_file.call_count == 2

    async def test_skips_missing_processed_md_file(
        self,
        async_client: AsyncClient,
        db_session: MagicMock,
        r2_client: MagicMock,
    ) -> None:
        """If the processed ``.md`` file does not exist, deletion still succeeds."""
        doc_id = uuid4()
        doc = make_document(id=doc_id, s3_key="org/doc.pdf")
        db_session.get.return_value = doc

        # Make the second delete_file call (for .md) raise S3Error.
        r2_client.delete_file.side_effect = [
            MagicMock(success=True),  # original file — succeeds
            S3Error("File not found"),  # .md file — not found
        ]

        resp = await async_client.delete(f"/api/documents/{doc_id}")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    async def test_s3_error_on_original_file_raises_500(
        self,
        async_client: AsyncClient,
        db_session: MagicMock,
        r2_client: MagicMock,
    ) -> None:
        """If the original file delete fails, a 500 is returned."""
        doc_id = uuid4()
        doc = make_document(id=doc_id, s3_key="org/doc.pdf")
        db_session.get.return_value = doc

        r2_client.delete_file.side_effect = S3Error("Network error")

        resp = await async_client.delete(f"/api/documents/{doc_id}")
        assert resp.status_code == 500
        assert "Error deleting the target file" in resp.json()["detail"]

    async def test_bulk_deletes_jobs_and_chunks_before_document(
        self, async_client: AsyncClient, db_session: MagicMock
    ) -> None:
        """Child rows are removed with scoped bulk DELETEs, then the document.

        Verifies the exact SQL that replaced the old load-and-delete loop:
        one ``DELETE`` per child table filtered by ``document_id``, the
        parent removed via the ORM, and a single commit for the whole batch.
        """
        doc_id = uuid4()
        doc = make_document(id=doc_id, s3_key=None)  # skip the R2 path
        db_session.get.return_value = doc

        resp = await async_client.delete(f"/api/documents/{doc_id}")
        assert resp.status_code == 200

        # The delete route issues exactly two statements via ``exec``: the
        # bulk deletes for jobs and chunks.
        exec_calls = [call.args[0] for call in db_session.exec.call_args_list]
        bulk_deletes = [stmt for stmt in exec_calls if isinstance(stmt, Delete)]
        assert len(bulk_deletes) == 2

        job_delete = next(
            stmt
            for stmt in bulk_deletes
            if stmt.table.name == ProcessingJob.__tablename__
        )
        chunk_delete = next(
            stmt
            for stmt in bulk_deletes
            if stmt.table.name == DocumentChunk.__tablename__
        )
        # Both statements must be scoped to the deleted document so we never
        # touch another document's rows.
        assert job_delete.whereclause.compare(ProcessingJob.document_id == doc_id)
        assert chunk_delete.whereclause.compare(
            DocumentChunk.document_id == doc_id
        )

        db_session.delete.assert_called_once_with(doc)
        db_session.commit.assert_called_once()

    async def test_delete_logs_affected_row_counts(
        self,
        async_client: AsyncClient,
        db_session: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """The debug log reports how many jobs/chunks were deleted."""
        doc_id = uuid4()
        doc = make_document(id=doc_id, s3_key=None)
        db_session.get.return_value = doc

        # Give each bulk delete its own affected-row count (the route reads
        # ``CursorResult.rowcount`` off the exec result).
        job_result = MagicMock(rowcount=2)
        chunk_result = MagicMock(rowcount=17)
        db_session.exec.side_effect = [job_result, chunk_result]

        with caplog.at_level("DEBUG", logger="src.document_routes"):
            resp = await async_client.delete(f"/api/documents/{doc_id}")

        assert resp.status_code == 200
        assert (
            "Deleted 2 processing job(s) and 17 chunk(s) for document"
            in caplog.text
        )

    async def test_db_failure_rolls_back_and_returns_500(
        self, async_client: AsyncClient, db_session: MagicMock
    ) -> None:
        """If the commit fails, the whole batch rolls back and a 500 is returned."""
        doc_id = uuid4()
        doc = make_document(id=doc_id, s3_key=None)
        db_session.get.return_value = doc
        db_session.commit.side_effect = RuntimeError("DB connection lost")

        resp = await async_client.delete(f"/api/documents/{doc_id}")

        assert resp.status_code == 500
        assert "Document deletion failed" in resp.json()["detail"]
        # Jobs/chunks/document deletes must not be persisted half-way.
        db_session.rollback.assert_called_once()


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
