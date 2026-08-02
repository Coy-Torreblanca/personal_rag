"""Tests for the main module (Celery tasks)."""

from collections.abc import Generator
from unittest.mock import MagicMock, patch

import pytest

from s3.models import FileType

from src.main import (
    _fail_job,
    celery,
    download_key,
    generate_embeddings,
    health_check,
    is_plain_text_file,
    mark_job_and_document_as_processed,
    parse_document,
    process_document,
)


# ── Module-level DB session mock ─────────────────────────────────
# ``_fail_job`` and ``process_document`` import ``get_db`` at module
# level, so we must patch ``src.main.get_db`` directly.  The mock is
# set up with a ``side_effect`` that returns a real generator so that
# ``contextmanager(get_db)()`` works correctly.


@pytest.fixture(autouse=True)
def _mock_main_db() -> Generator[MagicMock, None, None]:
    """Patch ``get_db`` inside ``src.main``."""
    from tests.conftest import _mock_get_db_factory

    mock_session = MagicMock()
    mock_get_db = _mock_get_db_factory(mock_session)

    with patch("src.main.get_db", mock_get_db):
        yield mock_session


@pytest.fixture(autouse=True)
def _mock_env_bucket() -> Generator[None, None, None]:
    """Ensure ``BUCKET_NAME`` env var is set."""
    with patch.dict("os.environ", {"BUCKET_NAME": "test-bucket"}):
        yield


@pytest.fixture(autouse=True)
def _mock_generate_embeddings_in_main() -> Generator[MagicMock, None, None]:
    """Mock the embedding pipeline within ``src.main``.

    ``src.main.generate_embeddings`` is now a *wrapper* that (a) generates
    the presigned GET URL via ``R2Client`` and (b) delegates to the imported
    ``_generate_embeddings`` (download → chunk → embed → persist). We patch
    ``src.main._generate_embeddings`` so the wrapper still runs and the
    presigned-URL logic is exercised, while real HTTP/OpenAI/DB work is
    stubbed out.
    """
    with patch("src.main._generate_embeddings") as mock_embeddings:
        yield mock_embeddings


# ── Celery Configuration ─────────────────────────────────────────


class TestCeleryConfiguration:
    """Tests for Celery app configuration."""

    def test_celery_app_name(self) -> None:
        """The Celery app is named correctly."""
        assert celery.main == "30ai_workers"

    def test_celery_config_values(self) -> None:
        """Key Celery configuration values are set."""
        assert celery.conf.task_serializer == "json"
        assert celery.conf.task_track_started is True
        assert celery.conf.task_time_limit == 30 * 60
        assert celery.conf.task_soft_time_limit == 25 * 60
        assert celery.conf.worker_prefetch_multiplier == 1


# ── Health Check ─────────────────────────────────────────────────


class TestHealthCheck:
    """Tests for the ``health_check`` task."""

    def test_returns_healthy_status(self) -> None:
        """The health check returns a healthy response."""
        result = health_check()
        assert result == {"status": "healthy", "service": "30ai-workers"}


# ── _fail_job ─────────────────────────────────────────────────────


class TestFailJob:
    """Tests for the internal ``_fail_job`` helper."""

    SAMPLE_DOC_ID = "4f225ee2-e003-4820-93de-c5de4b2bd2a4"
    SAMPLE_JOB_ID = "a1b2c3d4-e003-4820-93de-c5de4b2bd2a4"

    @staticmethod
    def _make_get_side_effect(mock_doc: MagicMock, mock_job: MagicMock):
        """Return a ``side_effect`` for ``mock_session.get`` that returns
        ``mock_doc`` when model name contains ``Document`` and
        ``mock_job`` otherwise."""
        def _get(model, id_):
            if "Document" in str(model):
                return mock_doc
            return mock_job
        return _get

    def test_sets_document_error_status(self, _mock_main_db) -> None:
        """The document status is set to ERROR."""
        mock_session = _mock_main_db
        mock_doc = MagicMock()
        mock_doc.status = MagicMock(value="uploaded")
        mock_job = MagicMock()
        mock_job.status = MagicMock(value="pending")
        mock_session.get.side_effect = self._make_get_side_effect(mock_doc, mock_job)

        _fail_job(self.SAMPLE_DOC_ID, self.SAMPLE_JOB_ID)

        assert mock_doc.status.value == "error"
        assert mock_session.commit.called

    def test_sets_job_failed_status(self, _mock_main_db) -> None:
        """The processing job status is set to FAILED."""
        mock_session = _mock_main_db
        mock_doc = MagicMock()
        mock_doc.status = MagicMock(value="uploaded")
        mock_job = MagicMock()
        mock_job.status = MagicMock(value="pending")
        mock_session.get.side_effect = self._make_get_side_effect(mock_doc, mock_job)

        _fail_job(self.SAMPLE_DOC_ID, self.SAMPLE_JOB_ID)

        assert mock_job.status.value == "failed"
        assert mock_session.commit.called

    def test_commits_changes(self, _mock_main_db) -> None:
        """The database transaction is committed."""
        mock_session = _mock_main_db
        mock_doc = MagicMock()
        mock_doc.status = MagicMock()
        mock_job = MagicMock()
        mock_job.status = MagicMock()
        mock_session.get.side_effect = self._make_get_side_effect(mock_doc, mock_job)

        _fail_job(self.SAMPLE_DOC_ID, self.SAMPLE_JOB_ID)

        mock_session.commit.assert_called_once()

    def test_handles_commit_failure(self, _mock_main_db) -> None:
        """If commit fails, the transaction is rolled back."""
        mock_session = _mock_main_db
        mock_doc = MagicMock()
        mock_doc.status = MagicMock()
        mock_job = MagicMock()
        mock_job.status = MagicMock()
        mock_session.get.side_effect = self._make_get_side_effect(mock_doc, mock_job)
        mock_session.commit.side_effect = Exception("DB error")

        _fail_job(self.SAMPLE_DOC_ID, self.SAMPLE_JOB_ID)

        mock_session.rollback.assert_called_once()

    def test_handles_missing_document(self, _mock_main_db) -> None:
        """If the document doesn't exist, the function handles it gracefully."""
        mock_session = _mock_main_db
        mock_session.get.return_value = None

        _fail_job(self.SAMPLE_DOC_ID, self.SAMPLE_JOB_ID)

        mock_session.commit.assert_called_once()


class TestFileTypeHelpers:
    """Tests for the plain-text detection and download-key helpers."""

    def test_is_plain_text_file_true_for_txt(self) -> None:
        """A ``.txt`` key is detected as plain text."""
        with patch(
            "src.main.get_file_type_from_extension",
            return_value=FileType.TXT,
        ):
            assert is_plain_text_file("documents/notes.txt") is True

    def test_is_plain_text_file_false_for_pdf(self) -> None:
        """A ``.pdf`` key is not treated as plain text."""
        with patch(
            "src.main.get_file_type_from_extension",
            return_value=FileType.PDF,
        ):
            assert is_plain_text_file("documents/report.pdf") is False

    @pytest.mark.parametrize(
        ("s3_key", "plain_text", "expected"),
        [
            # Plain-text files are served as themselves.
            ("documents/notes.txt", True, "documents/notes.txt"),
            # Docling-converted files are served as ``<key>.md``.
            ("documents/report.pdf", False, "documents/report.pdf.md"),
        ],
    )
    def test_download_key(
        self, s3_key: str, plain_text: bool, expected: str
    ) -> None:
        """The download key follows the text-file vs. converted-file rule."""
        assert download_key(s3_key, plain_text) == expected


# ── process_document ─────────────────────────────────────────────
# The task uses ``bind=True``. ``process_document.run`` has the
# signature ``(document_id, organization_id, s3_key, download_url,
# upload_url)`` — no ``self`` since it's already bound to the task
# instance.  We call ``.run`` directly to skip the Celery wrapper.
# ``_generate_embeddings`` is mocked at the module level to avoid
# real HTTP calls; the ``generate_embeddings`` wrapper (presigned URL
# generation) still runs.


class TestProcessDocument:
    """Tests for the ``process_document`` Celery task."""

    SAMPLE_DOC_ID = "4f225ee2-e003-4820-93de-c5de4b2bd2a4"
    SAMPLE_ORG_ID = "70885aed-0503-4656-bb72-368a26758575"
    SAMPLE_S3_KEY = "documents/test.pdf"
    SAMPLE_DOWNLOAD_URL = "https://example.com/download"
    SAMPLE_UPLOAD_URL = "https://example.com/upload"
    SAMPLE_JOB_ID = "a1b2c3d4-e003-4820-93de-c5de4b2bd2a4"

    def test_parses_via_modal(self, mock_modal_cls, mock_r2_client,
                              _mock_main_db) -> None:
        """The task invokes the Modal Docling parser."""
        result = process_document.run(
            self.SAMPLE_DOC_ID,
            self.SAMPLE_ORG_ID,
            self.SAMPLE_S3_KEY,
            self.SAMPLE_DOWNLOAD_URL,
            self.SAMPLE_UPLOAD_URL,
        )

        mock_modal_cls.assert_called_once_with(
            "s3-docling-ocr-pipeline", "DoclingParser"
        )
        mock_modal_cls.return_value().process_document.remote.assert_called_once_with(
            self.SAMPLE_DOWNLOAD_URL, self.SAMPLE_UPLOAD_URL
        )
        assert result["status"] == "success"

    def test_generates_presigned_url_for_markdown(
        self, mock_modal_cls, mock_r2_client, _mock_main_db
    ) -> None:
        """A presigned URL is generated for the markdown output."""
        process_document.run(
            self.SAMPLE_DOC_ID,
            self.SAMPLE_ORG_ID,
            self.SAMPLE_S3_KEY,
            self.SAMPLE_DOWNLOAD_URL,
            self.SAMPLE_UPLOAD_URL,
        )

        mock_r2_client.generate_presigned_url.assert_called_once_with(
            key=self.SAMPLE_S3_KEY + ".md",
            expiration=3600,
            method="GET",
            inline=False,
        )

    def test_updates_document_to_processed(
        self, mock_modal_cls, mock_r2_client, _mock_main_db
    ) -> None:
        """After processing, the document status is set to PROCESSED."""
        from database.models import DocumentStatus, ProcessingJobStatus

        mock_session = _mock_main_db
        mock_doc = MagicMock()
        mock_doc.status = MagicMock(value="processing")
        mock_job = MagicMock()
        mock_job.status = MagicMock(value="processing")

        def fake_get(model, id_):
            if "Document" in str(model):
                return mock_doc
            return mock_job

        mock_session.get.side_effect = fake_get

        process_document.run(
            self.SAMPLE_DOC_ID,
            self.SAMPLE_ORG_ID,
            self.SAMPLE_S3_KEY,
            self.SAMPLE_DOWNLOAD_URL,
            self.SAMPLE_UPLOAD_URL,
        )

        assert mock_doc.status.value == "processed"
        assert mock_job.status.value == "completed"
        mock_session.commit.assert_called_once()

    def test_fail_job_on_exception(
        self, mock_modal_cls, mock_r2_client, _mock_main_db
    ) -> None:
        """If an exception occurs, the job/document are marked as failed."""
        mock_session = _mock_main_db
        mock_modal_cls.side_effect = Exception("Modal unavailable")

        mock_doc = MagicMock()
        mock_doc.status = MagicMock(value="processing")
        mock_job = MagicMock()
        mock_job.status = MagicMock(value="processing")

        def fake_get(model, id_):
            if "Document" in str(model):
                return mock_doc
            return mock_job

        mock_session.get.side_effect = fake_get

        # ``process_document`` reads ``self.request.id`` for the job ID.
        # When calling ``.run()`` directly the request is not populated,
        # so we push one manually.
        process_document.push_request(id=self.SAMPLE_JOB_ID)

        with pytest.raises(Exception, match="Modal unavailable"):
            process_document.run(
                self.SAMPLE_DOC_ID,
                self.SAMPLE_ORG_ID,
                self.SAMPLE_S3_KEY,
                self.SAMPLE_DOWNLOAD_URL,
                self.SAMPLE_UPLOAD_URL,
            )

        assert mock_doc.status.value == "error"
        assert mock_job.status.value == "failed"

    # ── TXT file bypass ──────────────────────────────────────────────

    TXT_S3_KEY = "documents/notes.txt"

    def test_txt_file_skips_modal_parsing(
        self, mock_modal_cls, mock_r2_client, _mock_main_db
    ) -> None:
        """Plain-text files bypass the Modal Docling parser entirely."""
        result = process_document.run(
            self.SAMPLE_DOC_ID,
            self.SAMPLE_ORG_ID,
            self.TXT_S3_KEY,
            self.SAMPLE_DOWNLOAD_URL,
            self.SAMPLE_UPLOAD_URL,
        )

        # Text files never touch Modal — not even the ``Cls.from_name``
        # lookup happens, since there is nothing to convert.
        mock_modal_cls.assert_not_called()
        mock_modal_cls.return_value().process_document.remote.assert_not_called()

        # The result should be a success with pages=1
        assert result == {"status": "success", "pages": 1}

    def test_txt_file_generates_presigned_url_for_original_file(
        self, mock_modal_cls, mock_r2_client, _mock_main_db
    ) -> None:
        """TXT files are served as-is; no ``.md`` suffix is appended."""
        process_document.run(
            self.SAMPLE_DOC_ID,
            self.SAMPLE_ORG_ID,
            self.TXT_S3_KEY,
            self.SAMPLE_DOWNLOAD_URL,
            self.SAMPLE_UPLOAD_URL,
        )

        # The presigned URL must point at the original object because no
        # ``.md`` file is ever generated for plain-text files.
        mock_r2_client.generate_presigned_url.assert_called_once_with(
            key=self.TXT_S3_KEY,
            expiration=3600,
            method="GET",
            inline=False,
        )

    # ── Docling error handling ───────────────────────────────────────

    def test_docling_error_raises_value_error(
        self, mock_modal_cls, mock_r2_client, _mock_main_db
    ) -> None:
        """When Docling returns an error status, a ValueError is raised."""
        mock_session = _mock_main_db

        # Make the Modal call return an error
        mock_modal_cls.return_value().process_document.remote.return_value = {
            "status": "error",
            "message": "failed to fetch s3 obj: Connection refused",
        }

        mock_doc = MagicMock()
        mock_doc.status = MagicMock(value="processing")
        mock_job = MagicMock()
        mock_job.status = MagicMock(value="processing")

        def fake_get(model, id_):
            if "Document" in str(model):
                return mock_doc
            return mock_job

        mock_session.get.side_effect = fake_get

        process_document.push_request(id=self.SAMPLE_JOB_ID)

        with pytest.raises(ValueError, match="Error in parsing document in Docling"):
            process_document.run(
                self.SAMPLE_DOC_ID,
                self.SAMPLE_ORG_ID,
                self.SAMPLE_S3_KEY,
                self.SAMPLE_DOWNLOAD_URL,
                self.SAMPLE_UPLOAD_URL,
            )

        # The job/document should be marked as failed
        assert mock_doc.status.value == "error"
        assert mock_job.status.value == "failed"

    def test_docling_error_without_message_uses_default(
        self, mock_modal_cls, mock_r2_client, _mock_main_db
    ) -> None:
        """A missing ``message`` key falls back to a default error text."""
        mock_session = _mock_main_db

        mock_modal_cls.return_value().process_document.remote.return_value = {
            "status": "error",
        }

        mock_doc = MagicMock()
        mock_doc.status = MagicMock(value="processing")
        mock_job = MagicMock()
        mock_job.status = MagicMock(value="processing")

        def fake_get(model, id_):
            if "Document" in str(model):
                return mock_doc
            return mock_job

        mock_session.get.side_effect = fake_get

        process_document.push_request(id=self.SAMPLE_JOB_ID)

        with pytest.raises(ValueError, match="unknown Docling error"):
            process_document.run(
                self.SAMPLE_DOC_ID,
                self.SAMPLE_ORG_ID,
                self.SAMPLE_S3_KEY,
                self.SAMPLE_DOWNLOAD_URL,
                self.SAMPLE_UPLOAD_URL,
            )

        assert mock_doc.status.value == "error"
        assert mock_job.status.value == "failed"


# ── parse_document (pipeline stage) ──────────────────────────────


class TestParseDocumentHelper:
    """Tests for the ``parse_document`` pipeline stage."""

    SAMPLE_DOC_ID = "4f225ee2-e003-4820-93de-c5de4b2bd2a4"
    SAMPLE_S3_KEY = "documents/report.pdf"
    SAMPLE_DOWNLOAD_URL = "https://example.com/download"
    SAMPLE_UPLOAD_URL = "https://example.com/upload"

    def test_submits_non_text_file_to_docling(self, mock_modal_cls) -> None:
        """Non-text files are sent to the Modal Docling parser."""
        result = parse_document(
            self.SAMPLE_S3_KEY,
            self.SAMPLE_DOC_ID,
            self.SAMPLE_UPLOAD_URL,
            self.SAMPLE_DOWNLOAD_URL,
            is_text_file=False,
        )

        mock_modal_cls.assert_called_once_with(
            "s3-docling-ocr-pipeline", "DoclingParser"
        )
        mock_modal_cls.return_value().process_document.remote.assert_called_once_with(
            self.SAMPLE_DOWNLOAD_URL, self.SAMPLE_UPLOAD_URL
        )
        assert result == {"status": "success", "pages": 3}

    def test_normalizes_pages_to_int(self, mock_modal_cls) -> None:
        """A string ``pages`` value is coerced to an int."""
        mock_modal_cls.return_value().process_document.remote.return_value = {
            "status": "success",
            "pages": "7",
        }

        result = parse_document(
            self.SAMPLE_S3_KEY,
            self.SAMPLE_DOC_ID,
            self.SAMPLE_UPLOAD_URL,
            self.SAMPLE_DOWNLOAD_URL,
            is_text_file=False,
        )

        assert result == {"status": "success", "pages": 7}

    def test_skips_docling_for_text_file(self, mock_modal_cls) -> None:
        """Text files bypass Modal entirely — no lookup, no remote call."""
        result = parse_document(
            "documents/notes.txt",
            self.SAMPLE_DOC_ID,
            self.SAMPLE_UPLOAD_URL,
            self.SAMPLE_DOWNLOAD_URL,
            is_text_file=True,
        )

        mock_modal_cls.assert_not_called()
        assert result == {"status": "success", "pages": 1}

    def test_raises_value_error_on_docling_error(self, mock_modal_cls) -> None:
        """A Docling error status raises ValueError with the message."""
        mock_modal_cls.return_value().process_document.remote.return_value = {
            "status": "error",
            "message": "failed to fetch s3 obj: Connection refused",
        }

        with pytest.raises(ValueError, match="Connection refused"):
            parse_document(
                self.SAMPLE_S3_KEY,
                self.SAMPLE_DOC_ID,
                self.SAMPLE_UPLOAD_URL,
                self.SAMPLE_DOWNLOAD_URL,
                is_text_file=False,
            )

    def test_raises_value_error_with_default_message(self, mock_modal_cls) -> None:
        """A missing ``message`` key falls back to a default error text."""
        mock_modal_cls.return_value().process_document.remote.return_value = {
            "status": "error",
        }

        with pytest.raises(ValueError, match="unknown Docling error"):
            parse_document(
                self.SAMPLE_S3_KEY,
                self.SAMPLE_DOC_ID,
                self.SAMPLE_UPLOAD_URL,
                self.SAMPLE_DOWNLOAD_URL,
                is_text_file=False,
            )

    def test_raises_value_error_on_malformed_result(self, mock_modal_cls) -> None:
        """A non-dict Docling response is treated as a hard failure."""
        mock_modal_cls.return_value().process_document.remote.return_value = None

        with pytest.raises(ValueError, match="unexpected Docling response"):
            parse_document(
                self.SAMPLE_S3_KEY,
                self.SAMPLE_DOC_ID,
                self.SAMPLE_UPLOAD_URL,
                self.SAMPLE_DOWNLOAD_URL,
                is_text_file=False,
            )

    def test_raises_value_error_on_unexpected_status(self, mock_modal_cls) -> None:
        """An unknown status value is treated as a failure."""
        mock_modal_cls.return_value().process_document.remote.return_value = {
            "status": "pending",
        }

        with pytest.raises(ValueError, match="unknown Docling error"):
            parse_document(
                self.SAMPLE_S3_KEY,
                self.SAMPLE_DOC_ID,
                self.SAMPLE_UPLOAD_URL,
                self.SAMPLE_DOWNLOAD_URL,
                is_text_file=False,
            )


# ── generate_embeddings (wrapper in src.main) ────────────────────


class TestGenerateEmbeddingsWrapper:
    """Tests for the ``generate_embeddings`` wrapper in ``src.main``."""

    SAMPLE_DOC_ID = "4f225ee2-e003-4820-93de-c5de4b2bd2a4"
    SAMPLE_ORG_ID = "70885aed-0503-4656-bb72-368a26758575"
    SAMPLE_S3_KEY = "documents/report.pdf"

    def test_generates_url_for_converted_markdown(
        self, mock_r2_client, _mock_generate_embeddings_in_main
    ) -> None:
        """Converted files get a presigned URL for ``<key>.md``."""
        generate_embeddings(
            self.SAMPLE_S3_KEY, False, self.SAMPLE_ORG_ID, self.SAMPLE_DOC_ID
        )

        mock_r2_client.generate_presigned_url.assert_called_once_with(
            key=self.SAMPLE_S3_KEY + ".md",
            expiration=3600,
            method="GET",
            inline=False,
        )

    def test_generates_url_for_plain_text_file(
        self, mock_r2_client, _mock_generate_embeddings_in_main
    ) -> None:
        """Plain-text files get a presigned URL for the original key."""
        generate_embeddings(
            "documents/notes.txt", True, self.SAMPLE_ORG_ID, self.SAMPLE_DOC_ID
        )

        mock_r2_client.generate_presigned_url.assert_called_once_with(
            key="documents/notes.txt",
            expiration=3600,
            method="GET",
            inline=False,
        )

    def test_delegates_to_embedding_pipeline(
        self, mock_r2_client, _mock_generate_embeddings_in_main
    ) -> None:
        """The wrapper delegates with (url, document_id, organization_id)."""
        mock_r2_client.generate_presigned_url.return_value.url = (
            "https://example.com/markdown.md"
        )

        generate_embeddings(
            self.SAMPLE_S3_KEY, False, self.SAMPLE_ORG_ID, self.SAMPLE_DOC_ID
        )

        _mock_generate_embeddings_in_main.assert_called_once_with(
            "https://example.com/markdown.md",
            self.SAMPLE_DOC_ID,
            self.SAMPLE_ORG_ID,
        )

    def test_propagates_embedding_pipeline_failure(
        self, mock_r2_client, _mock_generate_embeddings_in_main
    ) -> None:
        """Failures from the embedding pipeline propagate to the caller."""
        _mock_generate_embeddings_in_main.side_effect = RuntimeError("OpenAI down")

        with pytest.raises(RuntimeError, match="OpenAI down"):
            generate_embeddings(
                self.SAMPLE_S3_KEY, False, self.SAMPLE_ORG_ID, self.SAMPLE_DOC_ID
            )


# ── mark_job_and_document_as_processed ───────────────────────────


class TestMarkJobAndDocumentAsProcessed:
    """Tests for the success-status helper."""

    SAMPLE_DOC_ID = "4f225ee2-e003-4820-93de-c5de4b2bd2a4"
    SAMPLE_JOB_ID = "a1b2c3d4-e003-4820-93de-c5de4b2bd2a4"

    @staticmethod
    def _make_get_side_effect(mock_doc: MagicMock, mock_job: MagicMock):
        """Return a ``side_effect`` for ``mock_session.get`` that returns
        ``mock_doc`` when the model name contains ``Document`` and
        ``mock_job`` otherwise."""

        def _get(model, id_):
            if "Document" in str(model):
                return mock_doc
            return mock_job

        return _get

    def test_marks_document_processed_and_job_completed(self, _mock_main_db) -> None:
        """Both rows are updated and the transaction is committed."""
        mock_session = _mock_main_db
        mock_doc = MagicMock()
        mock_doc.status = MagicMock(value="processing")
        mock_job = MagicMock()
        mock_job.status = MagicMock(value="processing")
        mock_session.get.side_effect = self._make_get_side_effect(mock_doc, mock_job)

        mark_job_and_document_as_processed(self.SAMPLE_DOC_ID, self.SAMPLE_JOB_ID)

        assert mock_doc.status.value == "processed"
        assert mock_job.status.value == "completed"
        mock_session.commit.assert_called_once()

    def test_missing_rows_still_commit(self, _mock_main_db) -> None:
        """Missing document/job rows are skipped; the transaction commits."""
        mock_session = _mock_main_db
        mock_session.get.return_value = None

        mark_job_and_document_as_processed(self.SAMPLE_DOC_ID, self.SAMPLE_JOB_ID)

        mock_session.commit.assert_called_once()

    def test_commit_failure_rolls_back_and_raises(self, _mock_main_db) -> None:
        """A failed commit rolls back and re-raises for failure handling."""
        mock_session = _mock_main_db
        mock_doc = MagicMock()
        mock_doc.status = MagicMock(value="processing")
        mock_job = MagicMock()
        mock_job.status = MagicMock(value="processing")
        mock_session.get.side_effect = self._make_get_side_effect(mock_doc, mock_job)
        mock_session.commit.side_effect = Exception("DB error")

        with pytest.raises(Exception, match="DB error"):
            mark_job_and_document_as_processed(self.SAMPLE_DOC_ID, self.SAMPLE_JOB_ID)

        mock_session.rollback.assert_called_once()
