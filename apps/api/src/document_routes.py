"""Document and processing-job management routes.

Endpoints prefixed with ``/api`` and tagged ``documents``:

- ``GET /api/documents`` — List all documents.
- ``GET /api/documents/upload-url/{file_path:path}`` — Generate a presigned S3/R2 URL for uploading.
- ``POST /api/documents/{job_id}/process`` — Trigger document processing via Celery.
- ``DELETE /api/documents/{document_id}`` — Delete a document and its artifacts.
- ``GET /api/processing-jobs`` — List all processing jobs.
- ``GET /api/processing-jobs/{job_id}`` — Fetch a single processing job.

All endpoints depend on a SQLModel database session injected via FastAPI's
``Depends`` mechanism.
"""

import os
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select

from database.models import (
    Document,
    DocumentStatus,
    ProcessingJob,
    ProcessingJobStatus,
)
from database.session import get_db
from s3.client import R2Client
from s3.exceptions import S3Error

from .celery_client import celery

from logutil import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api", tags=["documents"])


@router.get("/documents", response_model=list[Document])
def get_documents(db: Session = Depends(get_db)) -> list[Document]:
    """Retrieve all documents.

    Args:
        db: Injected database session.

    Returns:
        List of all ``Document`` records.
    """
    documents = db.exec(select(Document)).all()
    logger.info("Retrieved %d documents", len(documents))
    return documents


@router.get("/documents/upload-url/{file_path:path}")
async def get_upload_s3_url(
    file_path: str,
    organization_id: UUID = Query(...),
    user_id: UUID = Query(...),
    content_type: str = Query(...),
    db: Session = Depends(get_db),
) -> dict:
    """Generate a presigned URL for uploading a document to S3/R2 storage.

    The endpoint creates a ``Document`` record (status ``UPLOADING``) and a
    ``ProcessingJob`` record (status ``PENDING``) before returning a
    time-limited presigned URL that the client can use to upload the file
    directly to object storage.

    Args:
        file_path: The object key path (supports nested paths via ``/``).
        organization_id: UUID of the owning organisation.
        user_id: UUID of the uploading user.
        content_type: MIME type of the file being uploaded (e.g. ``application/pdf``).
        db: Injected database session.

    Returns:
        dict containing:
            - ``success``: Always ``True`` when no error occurs.
            - ``url``: Presigned URL for a PUT request.
            - ``bucket``: Target S3/R2 bucket name.
            - ``key``: Full object key (``{organization_id}/{file_path}``).
            - ``method``: HTTP method (``PUT``).
            - ``expires_in``: URL validity duration in seconds.
            - ``message``: Human-readable success message.
            - ``job_id``: UUID of the newly created processing job.

    Raises:
        HTTPException 400: If the S3 operation fails.
        HTTPException 500: If ``BUCKET_NAME`` is not configured or an
            unexpected error occurs.
    """
    bucket_name = os.environ.get("BUCKET_NAME")

    if not bucket_name:
        logger.error("No BUCKET_NAME environment variable configured")
        raise HTTPException(status_code=500, detail="No bucket name configured")

    # Build the object key with an organisation-level prefix for multi-tenancy.
    key = f"{organization_id}/{file_path}"

    client = R2Client(bucket_name=bucket_name)
    expiration = 3600  # TODO: Make expiration configurable per request.

    # Persist a Document record so the client can track upload progress.
    doc = Document(
        organization_id=organization_id,
        user_id=user_id,
        filename=file_path,
        s3_key=key,
        status=DocumentStatus.UPLOADING,
        file_type=content_type,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    logger.info("Created document %s with key %s", doc.id, key)

    # Create a pending processing job that a worker will pick up later.
    job = ProcessingJob(
        document_id=doc.id,
        job_type="Upload+Embedding",
        status=ProcessingJobStatus.PENDING,
    )
    db.add(job)
    db.commit()

    job_id = job.id

    logger.debug("Created processing job %s for document %s", job_id, doc.id)

    # Generate the presigned URL.
    response = client.generate_presigned_url(
        key=key,
        expiration=expiration,
        method="PUT",
        inline=False,
        content_type=content_type,
    )

    logger.info(
        "Generated presigned upload URL for document %s (job %s)",
        doc.id,
        job_id,
    )

    return {
        "success": True,
        "url": response.url,
        "bucket": response.bucket,
        "key": response.key,
        "method": response.method,
        "expires_in": response.expires_in,
        "message": response.message,
        "job_id": job_id,
    }


@router.post("/documents/{job_id}/process")
def process_document(job_id: UUID, db: Session = Depends(get_db)) -> dict:
    """Trigger asynchronous document processing via Celery.

    Validates the job and its associated document, generates presigned URLs
    for downloading the source and uploading the processed result (Markdown),
    then dispatches a ``process_document`` Celery task to the worker pool.

    Args:
        job_id: UUID of the ``ProcessingJob`` to execute.
        db: Injected database session.

    Returns:
        dict containing:
            - ``message``: Confirmation text.
            - ``document_id``: UUID of the document being processed.
            - ``task_id``: Celery task ID (same as ``job_id``).
            - ``status``: Always ``"processing"``.

    Raises:
        HTTPException 400: If the document is already processing, the job is
            not pending, or validation fails.
        HTTPException 404: If the job or its document is not found.
        HTTPException 500: If ``BUCKET_NAME`` is unconfigured or any
            unexpected error occurs.
    """
    job = db.get(ProcessingJob, job_id)

    if not job:
        logger.warning("Job not found: %s", job_id)
        raise HTTPException(
            status_code=404,
            detail="Job id provided does not correspond with any known jobs.",
        )

    document = db.get(Document, job.document_id)

    if not document:
        logger.warning("Document not found for job %s, marking job as failed", job_id)
        job.status = ProcessingJobStatus.FAILED
        db.add(job)
        db.commit()
        raise HTTPException(
            status_code=404, detail="Document associated with job not found"
        )

    if document.status == DocumentStatus.PROCESSING:
        logger.warning("Document %s is already processing", document.id)
        raise HTTPException(status_code=400, detail=f"Document is already processing.")

    if not document.s3_key:
        logger.error("Document %s has no S3 key", document.id)
        raise HTTPException(
            status_code=500,
            detail=f"Could not find s3 key for document: {document.id}",
        )

    if job.status != ProcessingJobStatus.PENDING:
        logger.warning("Job %s is not pending (status=%s)", job_id, job.status.value)
        raise HTTPException(
            status_code=400,
            detail=f"Job is not in pending status: {job.status.value}",
        )

    bucket_name = os.environ.get("BUCKET_NAME")
    if not bucket_name:
        raise HTTPException(status_code=500, detail="No bucket name configured")

    client = R2Client(bucket_name=bucket_name)
    # TODO - Validate that the document is uploaded.
    expiration = 3600  # TODO: Make expiration configurable.

    # Presigned URL for downloading the original document.
    download_response = client.generate_presigned_url(
        key=document.s3_key,
        expiration=expiration,
        method="GET",
        inline=False,
    )
    download_url = download_response.url

    # Presigned URL for uploading the processed Markdown output.
    upload_response = client.generate_presigned_url(
        key=document.s3_key + ".md",
        expiration=expiration,
        method="PUT",
        inline=False,
    )
    upload_url = upload_response.url

    # Transition statuses.
    document.status = DocumentStatus.PROCESSING
    db.add(document)

    job.celery_task_id = str(job_id)
    job.status = ProcessingJobStatus.PROCESSING
    db.add(job)

    document_id = document.id
    organization_id = document.organization_id
    s3_key = document.s3_key

    try:
        db.flush()

        # Dispatch the long-running processing task to Celery workers.
        result = celery.send_task(
            "process_document",
            args=[
                str(document_id),
                str(organization_id),
                s3_key,
                download_url,
                upload_url,
            ],
            task_id=str(job_id),
        )
        db.commit()

        logger.info(
            "Dispatched document %s processing to Celery (task %s)",
            document_id,
            result.id,
        )

    except Exception as e:
        db.rollback()
        logger.exception("Failed to dispatch Celery task for document %s", document_id)
        raise e

    return {
        "message": "Document processing started",
        "document_id": str(document_id),
        "task_id": result.id,
        "status": "processing",
    }


@router.delete("/documents/{document_id}", status_code=200)
def delete_document(document_id: UUID, db: Session = Depends(get_db)) -> dict:
    """Delete a document and all associated artefacts.

    Removes the document record, its processing jobs, and the underlying
    file from S3/R2 storage.

    Args:
        document_id: UUID of the document to delete.
        db: Injected database session.

    Returns:
        dict containing:
            - ``success``: Always ``True`` on success.
            - ``message``: Human-readable confirmation.
            - ``document_id``: The deleted document's UUID.

    Raises:
        HTTPException 404: If the document does not exist.
        HTTPException 500: If ``BUCKET_NAME`` is unconfigured, the S3
            deletion fails, or an unexpected error occurs.
    """
    logger.info("Deleting document %s", document_id)
    document = db.get(Document, document_id)
    if not document:
        logger.warning("Document not found for deletion: %s", document_id)
        raise HTTPException(status_code=404, detail="Document not found")

    bucket_name = os.environ.get("BUCKET_NAME")
    if not bucket_name:
        logger.error("No BUCKET_NAME environment variable configured")
        raise HTTPException(status_code=500, detail="No bucket name configured")

    try:
        # Remove the file from object storage if it exists.
        if document.s3_key:
            try:
                client = R2Client(bucket_name=bucket_name)
                client.delete_file(key=document.s3_key)
                logger.debug(
                    "Deleted S3 file %s for document %s", document.s3_key, document_id
                )
            except S3Error as e:
                logger.error("Failed to delete S3 file %s: %s", document.s3_key, e)
                raise HTTPException(
                    status_code=500, detail="Error deleting the target file."
                ) from e

        # Cascade-delete all associated processing jobs.
        jobs = db.exec(
            select(ProcessingJob).where(ProcessingJob.document_id == document_id)
        ).all()
        for job in jobs:
            db.delete(job)
        logger.debug(
            "Deleted %d processing jobs for document %s", len(jobs), document_id
        )

        db.delete(document)
        db.commit()

        logger.info("Document %s deleted successfully", document_id)

        return {
            "success": True,
            "message": f"Document '{document.filename}' deleted successfully",
            "document_id": str(document_id),
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Document deletion failed for %s", document_id)
        raise HTTPException(
            status_code=500,
            detail=f"Document deletion failed: {str(e)}",
        ) from e


@router.get("/processing-jobs", response_model=list[ProcessingJob])
def get_processing_jobs(db: Session = Depends(get_db)) -> list[ProcessingJob]:
    """Retrieve all processing jobs.

    Args:
        db: Injected database session.

    Returns:
        List of all ``ProcessingJob`` records.
    """
    jobs = db.exec(select(ProcessingJob)).all()
    logger.info("Retrieved %d processing jobs", len(jobs))
    return jobs


@router.get("/processing-jobs/{job_id}", response_model=ProcessingJob)
def get_processing_job(job_id: UUID, db: Session = Depends(get_db)) -> ProcessingJob:
    """Retrieve a single processing job by its UUID.

    Args:
        job_id: UUID of the processing job.
        db: Injected database session.

    Returns:
        The matching ``ProcessingJob`` record.

    Raises:
        HTTPException 404: If no job with the given ID exists.
    """
    job = db.get(ProcessingJob, job_id)
    if not job:
        logger.warning("Processing job not found: %s", job_id)
        raise HTTPException(status_code=404, detail="Processing job not found")
    logger.debug("Retrieved processing job %s", job_id)
    return job
