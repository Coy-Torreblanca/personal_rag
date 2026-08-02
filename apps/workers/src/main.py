"""
Workers - Background job processing for the 30ai platform.

This module defines Celery tasks for document processing, including:
- Health check endpoint for monitoring.
- Document processing pipeline that parses documents via Modal/Docling,
  downloads the resulting markdown, generates an LLM summary (DeepSeek) and
  embeddings (OpenAI), and updates job/document status in the database.
"""

import os
import modal
import requests
from contextlib import contextmanager
from celery import Celery


from .parse_document import APP_NAME
from .generate_embeddings import generate_embeddings as _generate_embeddings
from .generate_llm_summary import generate_llm_summary
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


def parse_document(
    s3_key: str,
    document_id: str,
    upload_url: str,
    download_url: str,
    is_text_file: bool,
) -> dict[str, str | int]:
    """Parse a document into markdown, either locally or via Modal/Docling.

    Plain-text files (``.txt``, ``.md``, ...) are already markdown-compatible,
    so they skip the Modal/Docling parser entirely — no remote class lookup,
    no network round-trip. Every other file type is handed to the
    Modal-hosted ``DoclingParser``, which downloads the original document from
    ``download_url``, converts it to markdown, and uploads the result to
    ``upload_url`` as ``<s3_key>.md``.

    Args:
        s3_key: Original object key in the bucket (used for logging only).
        document_id: UUID string of the document being parsed.
        upload_url: Presigned S3 URL where Docling uploads the markdown result.
        download_url: Presigned S3 URL from which Docling downloads the source.
        is_text_file: Whether the object is a plain-text file.

    Returns:
        A normalized dict with ``status`` (``"success"``) and ``pages`` (int).

    Raises:
        ValueError: If the Docling parser returns an error status or an
            unexpected (non-dict / missing-status) response.
    """
    # Plain-text files are already markdown-compatible: nothing to convert.
    # Returning early also avoids a pointless Modal class lookup, which can
    # itself fail if the Modal app is unreachable.
    if is_text_file:
        logger.info(
            "Skipping docling processing on file %r because it is a text file.",
            s3_key,
        )
        return {"status": "success", "pages": 1}

    # TODO Make Async and have modal make fast api call to continue processing.
    m_cls = modal.Cls.from_name(APP_NAME, "DoclingParser")

    logger.info(
        "Submitting document %s to Docling for conversion (%s).",
        document_id,
        s3_key,
    )
    result = m_cls().process_document.remote(download_url, upload_url)

    # Defensive validation: Docling is expected to return
    # ``{"status": "success" | "error", ...}``. Treat any other payload
    # (non-dict, missing status, unexpected status) as a hard failure so the
    # job is failed loudly instead of crashing on a ``KeyError`` downstream.
    if not isinstance(result, dict) or result.get("status") != "success":
        error_message = (
            result.get("message", "unknown Docling error")
            if isinstance(result, dict)
            else f"unexpected Docling response: {result!r}"
        )
        logger.error(
            "Docling parsing error for document %s: %s",
            document_id,
            error_message,
        )
        raise ValueError(f"Error in parsing document in Docling: {error_message}")

    # Normalize the success payload; ``pages`` may arrive as a string or int.
    pages = int(result.get("pages", 1))
    logger.info(
        "Docling conversion succeeded for document %s (%s pages).",
        document_id,
        pages,
    )
    return {"status": "success", "pages": pages}


def download_file_text(
    s3_key: str,
    is_text_file: bool,
    document_id: str,
) -> str:
    """Download the processed document's markdown text from R2.

    This is a thin orchestration helper that runs *before* the LLM summary
    and embedding stages of the pipeline:

    1. Resolve the markdown object key — the original object for plain-text
       files, ``<s3_key>.md`` for Docling-converted files.
    2. Generate a short-lived presigned GET URL for that object.
    3. Download the object body and return it as text.

    The downloaded text is the single source of truth for both the LLM
    summarizer (:func:`generate_llm_summary`) and the embedding pipeline
    (:func:`src.generate_embeddings.generate_embeddings`), so each stage
    fetches the content exactly once.

    Args:
        s3_key: Original object key in the bucket.
        is_text_file: Whether the object is a plain-text file.
        document_id: UUID string of the document being processed.

    Returns:
        The markdown text of the processed document.

    Raises:
        KeyError: If the ``BUCKET_NAME`` environment variable is not set.
        PresignedUrlError: If the presigned URL cannot be generated.
        requests.HTTPError: If the presigned URL returns a non-2xx response
            (e.g. an expired URL or a missing object).
    """
    logger.info("Downloading markdown content for document %s", document_id)

    # TODO Add expiration logic (e.g. derive from document size).
    expiration = 3600

    # Text files are already markdown and are downloaded as-is; files
    # converted by Docling are downloaded as ``<original>.md``.
    output_key = download_key(s3_key, is_text_file)

    client = R2Client(bucket_name=os.environ["BUCKET_NAME"])
    response = client.generate_presigned_url(
        key=output_key,
        expiration=expiration,
        method="GET",
        inline=False,
    )
    logger.info("Generated presigned GET URL for %r", output_key)

    # NOTE: presigned URLs carry credentials — log only the object key, never
    # the URL itself.
    response = requests.get(response.url, timeout=120)

    # Surface HTTP failures loudly: a 4xx/5xx from an expired or missing
    # presigned URL must fail the job, not silently embed an error page.
    response.raise_for_status()

    file_text = response.text
    logger.debug(
        "Downloaded markdown content (%d chars) for document %s",
        len(file_text),
        document_id,
    )
    return file_text


def mark_job_and_document_as_processed(
    document_id: str, job_id: str, summary: str
) -> None:
    """Mark a document and its processing job as successfully processed.

    Sets the document status to PROCESSED, persists the generated LLM
    summary on the document row, sets the processing job status to
    COMPLETED, then commits. Rows that no longer exist are skipped safely.

    Args:
        document_id: UUID string of the document to mark as processed.
        job_id: UUID string of the processing job to mark as completed.
        summary: The generated LLM summary to persist on the document row;
            displayed to end users and used for semantic search.

    Raises:
        Exception: Re-raised (after rollback) if the transaction fails, so the
            caller can run failure handling (``_fail_job``).
    """
    with contextmanager(get_db)() as db:
        try:
            doc = db.get(Document, document_id)
            if doc:
                doc.status = DocumentStatus.PROCESSED
                doc.summary = summary

            job = db.get(ProcessingJob, job_id)
            if job:
                job.status = ProcessingJobStatus.COMPLETED

            db.commit()
            logger.info(
                "Marked document %s and job %s as processed/completed.",
                document_id,
                job_id,
            )
        except Exception:
            db.rollback()
            logger.exception(
                "Failed to mark document %s / job %s as processed.",
                document_id,
                job_id,
            )
            raise


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
    2. Downloads the resulting markdown text from R2 via a presigned URL.
    3. Generates a dense LLM summary of the markdown via DeepSeek.
    4. Generates OpenAI embeddings for the markdown chunks *plus* the summary
       and persists the chunks to the database.
    5. Persists the summary on the document row and marks the document/job
       as PROCESSED/COMPLETED.

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
    logger.info("Processing document %s (job %s)", document_id, job_id)

    # Plain-text files are served directly; every other type is sent to
    # Docling, which uploads the converted result as ``<s3_key>.md``.
    is_text_file = is_plain_text_file(s3_key)

    try:
        # Stage 1 — parse the document into markdown (Modal/Docling or
        # pass-through for plain-text files).
        result = parse_document(
            s3_key=s3_key,
            document_id=document_id,
            upload_url=upload_url,
            download_url=download_url,
            is_text_file=is_text_file,
        )

        # Stage 2 — download the processed markdown text from R2 so it can be
        # summarized and embedded without a second round-trip.
        document_content = download_file_text(
            s3_key=s3_key,
            is_text_file=is_text_file,
            document_id=document_id,
        )

        # Stage 3 — generate a dense LLM summary. The summary is both
        # persisted on the document row and embedded as an extra top-level
        # chunk, so semantic search can match whole-document intent.
        summary = generate_llm_summary(document_content)
        logger.info(
            "Generated LLM summary for document %s (%d chars)",
            document_id,
            len(summary),
        )

        _generate_embeddings(document_content, document_id, organization_id, summary)

        # Stage 4 — persist the successful outcome (status + summary) on the
        # document/job rows.
        mark_job_and_document_as_processed(document_id, job_id, summary)

    except Exception:
        logger.exception(
            "Document processing failed for document=%s job=%s",
            document_id,
            job_id,
        )
        _fail_job(document_id, job_id)
        # Bare ``raise`` preserves the original traceback for Celery/error
        # reporting (``raise e`` would truncate it).
        raise

    return result


if __name__ == "__main__":
    logger.info("Starting Celery worker")
    celery.start(argv=["worker", "--loglevel=info"])
