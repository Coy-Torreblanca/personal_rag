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
def get_documents(db: Session = Depends(get_db)):
    """Get all documents."""
    documents = db.exec(select(Document)).all()
    logger.info("Retrieved %d documents", len(documents))
    return documents


@router.get("/documents/upload-url/{file_path:path}")
async def get_upload_s3_url(
    file_path: str,
    organization_id: UUID = Query(),
    user_id: UUID = Query(),
    content_type: str = Query(),
    db: Session = Depends(get_db),
):
    """
    Generate a presigned URL for uploading a document to S3/R2.

    - **file_path**: The file path/key in S3 (supports nested paths with /)
    - **content_type**: Content Type header for file upload.
    - **organization_id**: Organization ID for access validation
    - **user_id**: User ID for access validation
    - **expiration**: URL expiration time in seconds (1 - 604800, default 3600)

    Returns:
        dict: Contains the presigned URL and metadata
            - url: The presigned URL for uploading
            - bucket: The bucket name
            - key: The S3 object key
            - method: HTTP method (PUT)
            - expires_in: Expiration time in seconds
            - message: Success message
    """
    try:
        # TODO validate user has access.
        bucket_name = os.environ.get("BUCKET_NAME")

        if not bucket_name:
            logger.error("No BUCKET_NAME environment variable configured")
            raise HTTPException(status_code=500, detail="No bucket name configured")

        # Construct S3 key with organization prefix
        key = f"{organization_id}/{file_path}"

        # Create client
        client = R2Client(bucket_name=bucket_name)

        # TODO Add expiration logic.
        expiration = 3600

        # TODO - consider upserts
        ## For example we will be changing uploaded status to uploading but doc is available to user.
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

        # Create job
        job = ProcessingJob(
            document_id=doc.id,
            job_type="Upload+Embedding",
            status=ProcessingJobStatus.PENDING,
        )

        job_id = job.id

        db.add(job)
        db.commit()

        logger.debug("Created processing job %s for document %s", job_id, doc.id)

        # Generate presigned URL for PUT operation
        # TODO validate response
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
    except S3Error as e:
        logger.error("S3 operation failed for upload URL generation: %s", e)
        raise HTTPException(
            status_code=400, detail=f"S3 operation failed: {str(e)}"
        ) from e
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Presigned URL generation failed unexpectedly")
        raise HTTPException(
            status_code=500,
            detail=f"Presigned URL generation failed: {str(e)}",
        ) from e


@router.post("/documents/{job_id}/process")
def process_document(job_id: UUID, db: Session = Depends(get_db)):
    """Trigger processing for a document."""
    logger.info("Processing document for job %s", job_id)

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

    # Check if document is already being processed
    if document.status == DocumentStatus.PROCESSING:
        logger.warning("Document %s is already processing", document.id)
        raise HTTPException(status_code=400, detail=f"Document is already processing.")

    if not document.s3_key:
        logger.error("Document %s has no S3 key", document.id)
        raise HTTPException(
            status_code=500, detail=f"Could not find s3 key for document: {document.id}"
        )

    if job.status != ProcessingJobStatus.PENDING:
        logger.warning("Job %s is not pending (status=%s)", job_id, job.status.value)
        raise HTTPException(
            status_code=400, detail=f"Job is not in pending status: {job.status.value}"
        )

    # TODO - Validate that the document is uploaded.
    bucket_name = os.environ.get("BUCKET_NAME")

    if not bucket_name:
        raise HTTPException(status_code=500, detail="No bucket name configured")

    # Create client
    # TODO move presinged url generation to worker.
    client = R2Client(bucket_name=bucket_name)

    # TODO Add expiration logic.
    expiration = 3600

    # TODO validate response
    response = client.generate_presigned_url(
        key=document.s3_key,
        expiration=expiration,
        method="GET",
        inline=False,
    )

    download_url = response.url

    response = client.generate_presigned_url(
        key=document.s3_key + ".md",
        expiration=expiration,
        method="PUT",
        inline=False,
    )

    upload_url = response.url

    # Update document status
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

        # Dispatch processing to Celery worker
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
def delete_document(document_id: UUID, db: Session = Depends(get_db)):
    """Delete a document and its associated data.

    Removes the document from the database, deletes the file from S3/R2 storage,
    and removes any associated processing jobs.

    - **document_id**: The UUID of the document to delete

    Returns:
        dict: Confirmation of deletion
            - success: True if deletion was successful
            - message: Confirmation message
            - document_id: The ID of the deleted document
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
        # Delete the file from S3/R2 if it has a key
        if document.s3_key:
            try:
                client = R2Client(bucket_name=bucket_name)
                client.delete_file(key=document.s3_key)
                logger.debug("Deleted S3 file %s for document %s", document.s3_key, document_id)
            except S3Error as e:
                logger.error("Failed to delete S3 file %s: %s", document.s3_key, e)
                raise HTTPException(
                    status_code=500, detail="Error deleted the target file."
                )

        # Delete associated processing jobs
        jobs = db.exec(
            select(ProcessingJob).where(ProcessingJob.document_id == document_id)
        ).all()
        for job in jobs:
            db.delete(job)
        logger.debug("Deleted %d processing jobs for document %s", len(jobs), document_id)

        # Delete the document
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
        )


@router.get("/processing-jobs", response_model=list[ProcessingJob])
def get_processing_jobs(db: Session = Depends(get_db)):
    """Get all processing jobs."""
    jobs = db.exec(select(ProcessingJob)).all()
    logger.info("Retrieved %d processing jobs", len(jobs))
    return jobs


@router.get("/processing-jobs/{job_id}", response_model=ProcessingJob)
def get_processing_job(job_id: UUID, db: Session = Depends(get_db)):
    """Get a specific processing job."""
    job = db.get(ProcessingJob, job_id)
    if not job:
        logger.warning("Processing job not found: %s", job_id)
        raise HTTPException(status_code=404, detail="Processing job not found")
    logger.debug("Retrieved processing job %s", job_id)
    return job
