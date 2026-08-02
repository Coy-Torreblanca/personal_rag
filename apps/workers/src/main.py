"""
Workers - Background job processing for the 30ai platform.

This module defines Celery tasks for document processing, including:
- Health check endpoint for monitoring.
- Document processing pipeline that parses documents via Modal/Docling,
  generates embeddings, and updates job/document status in the database.
"""

import logging
import os
import modal
from contextlib import contextmanager
from celery import Celery


from .parse_document import APP_NAME
from .generate_embeddings import generate_embeddings
from database.models import Document, DocumentStatus, ProcessingJob, ProcessingJobStatus
from database.session import get_db
from s3.client import R2Client
from s3.models import FileType, get_file_type_from_extension

from logutil import get_logger

logger = get_logger(__name__)


# Create Celery application
celery = Celery(
    "30ai_workers",
    broker=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
    backend=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
)

# Configure Celery
celery.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=30 * 60,  # 30 minutes
    task_soft_time_limit=25 * 60,  # 25 minutes
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=1000,
)


@celery.task(name="health_check")
def health_check():
    """Health check task."""
    return {"status": "healthy", "service": "30ai-workers"}


def is_plain_text_file(s3_key: str) -> bool:
    """Return ``True`` when the object key refers to a plain-text file.

    Plain-text files (``.txt``, ``.md``, ``.html``, ``.yaml``, ...) are
    already markdown-compatible and do not need to be sent to the
    Modal/Docling parser. All other file types must be converted before
    embeddings can be generated.
    """
    return get_file_type_from_extension(s3_key) == FileType.TXT


def download_key(s3_key: str, plain_text: bool) -> str:
    """Return the R2 object key that should be exposed for download.

    Args:
        s3_key: Original object key in the bucket.
        plain_text: Whether the object is a plain-text file.

    Returns:
        The original key for plain-text files, otherwise ``<s3_key>.md``.
    """
    return s3_key if plain_text else f"{s3_key}.md"


def _fail_job(document_id: str, job_id: str) -> None:
    """
    Mark a document and its processing job as failed in the database.

    Sets the document status to ERROR and the processing job status to FAILED.
    If an error occurs during the update, it rolls back and logs the exception.

    Args:
        document_id: UUID string of the document to fail.
        job_id: UUID string of the processing job to fail.
    """
    with contextmanager(get_db)() as db:
        try:
            if document_id:
                doc = db.get(Document, document_id)
                if doc:
                    doc.status = DocumentStatus.ERROR
            if job_id:
                job = db.get(ProcessingJob, job_id)
                if job:
                    job.status = ProcessingJobStatus.FAILED

            db.commit()
        except Exception as ee:
            db.rollback()
            logger.error("Failed to mark job/document as failed", exc_info=ee)


@celery.task(name="process_document", bind=True)
def process_document(
    self,
    document_id: str,
    organization_id: str,
    s3_key: str,
    download_url: str,
    upload_url: str,
) -> dict[str, str | int]:
    """
    Process a document through the full pipeline: parse, embed, and persist.

    This Celery task orchestrates the document processing workflow:
    1. Determines the file type from ``s3_key``.
       - **Plain-text files** (``.txt``, ``.md``, etc.) skip the Modal/Docling
         parser and are treated as already-converted markdown.
       - **All other file types** are sent to the Modal-hosted Docling parser
         for conversion to markdown.
    2. Generates a presigned S3 URL for the resulting markdown file.
    3. Generates embeddings for the markdown content via OpenAI.
    4. Updates the document and job statuses in the database.

    Args:
        document_id: UUID string of the document to process.
        organization_id: UUID string of the owning organization.
        s3_key: The S3 object key for the original document.
        download_url: Presigned URL for downloading the original document.
        upload_url: Presigned URL for uploading the parsed markdown result.

    Returns:
        The result dict with ``status`` and ``pages`` count.

    Raises:
        ValueError: If the Docling parser returns an error status.
        Exception: If any other step fails, the job and document are marked as
            failed and the exception is re-raised.
    """
    job_id: str = self.request.id

    try:
        # TODO Make Async and have modal make fast api call to continue processing.
        m_cls = modal.Cls.from_name(APP_NAME, "DoclingParser")

        # Plain-text files are served directly; every other type is sent to
        # Docling, which uploads the converted result as ``<s3_key>.md``.
        is_text_file = is_plain_text_file(s3_key)

        if not is_text_file:
            logger.info(
                "Submitting document %s to Docling for conversion (%s).",
                document_id,
                s3_key,
            )
            result = m_cls().process_document.remote(download_url, upload_url)

            if result["status"] == "error":
                error_message = result.get("message", "unknown Docling error")
                logger.error(
                    "Docling parsing error for document %s: %s",
                    document_id,
                    error_message,
                )
                raise ValueError(
                    f"Error in parsing document in Docling: {error_message}"
                )

            logger.info(
                "Docling conversion succeeded for document %s (%s pages).",
                document_id,
                result.get("pages", 1),
            )
        else:
            logger.info(
                "Skipping docling processing on file %r because it is a text file.",
                s3_key,
            )
            result = {"status": "success", "pages": 1}

        client = R2Client(bucket_name=os.environ["BUCKET_NAME"])

        # TODO Add expiration logic.
        expiration = 3600

        # Text files are already markdown and are downloaded as-is; files
        # converted by Docling are downloaded as ``<original>.md``.
        output_key = download_key(s3_key, is_text_file)

        response = client.generate_presigned_url(
            key=output_key,
            expiration=expiration,
            method="GET",
            inline=False,
        )
        logger.info("Generated presigned GET URL for %r", output_key)

        generate_embeddings(response.url, document_id, organization_id)

        with contextmanager(get_db)() as db:
            try:
                doc = db.get(Document, document_id)
                if doc:
                    doc.status = DocumentStatus.PROCESSED
                job = db.get(ProcessingJob, job_id)
                if job:
                    job.status = ProcessingJobStatus.COMPLETED

                db.commit()

            except Exception:
                db.rollback()
                raise

    except Exception as e:
        logger.exception(
            "Document processing failed for document=%s job=%s",
            document_id,
            job_id,
        )
        _fail_job(document_id, job_id)
        raise e

    return result


if __name__ == "__main__":
    logger.info("Starting Celery worker")
    celery.start(argv=["worker", "--loglevel=info"])
