import os
from typing import List, Optional
from uuid import UUID, uuid4

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    UploadFile,
    File,
    BackgroundTasks,
    Query,
)
from sqlmodel import Session, select

from database.models import Document, DocumentStatus, ProcessingJob, ProcessingJobStatus
from database.session import get_db

from s3.client import R2Client
from s3.exceptions import S3Error
from .celery_client import celery

router = APIRouter(prefix="/api", tags=["documents"])


@router.get("/documents", response_model=List[Document])
def get_documents(db: Session = Depends(get_db)):
    """Get all documents."""
    documents = db.exec(select(Document)).all()
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

        # Create job
        job = ProcessingJob(
            document_id=doc.id,
            job_type="Upload+Embedding",
            status=ProcessingJobStatus.PENDING,
        )

        job_id = job.id

        db.add(job)
        db.commit()

        # Generate presigned URL for PUT operation
        # TODO validate response
        response = client.generate_presigned_url(
            key=key,
            expiration=expiration,
            method="PUT",
            inline=False,
            content_type=content_type,
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
        raise HTTPException(
            status_code=400, detail=f"S3 operation failed: {str(e)}"
        ) from e
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Presigned URL generation failed: {str(e)}",
        ) from e


@router.post("/documents/{job_id}/process")
def process_document(job_id: UUID, db: Session = Depends(get_db)):
    """Trigger processing for a document."""
    job = db.get(ProcessingJob, job_id)

    if not job:
        raise HTTPException(
            status_code=404,
            detail="Job id provided does not correspond with any known jobs.",
        )

    document = db.get(Document, job.document_id)

    if not document:
        job.status = ProcessingJobStatus.FAILED
        db.add(job)
        db.commit()

        raise HTTPException(
            status_code=404, detail="Document associated with job not found"
        )

    # Check if document is already being processed
    if document.status == DocumentStatus.PROCESSING:
        raise HTTPException(status_code=400, detail=f"Document is already processing.")

    if not document.s3_key:
        raise HTTPException(
            status_code=500, detail=f"Could not find s3 key for document: {document.id}"
        )

    if job.status != ProcessingJobStatus.PENDING:
        raise HTTPException(
            status_code=400, detail=f"Job is not in pending status: {job.status.value}"
        )

    # TODO - Validate that the document is uploaded.
    bucket_name = os.environ.get("BUCKET_NAME")

    if not bucket_name:
        raise HTTPException(status_code=500, detail="No bucket name configured")

    # Create client
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

    # Update document status
    document.status = DocumentStatus.PROCESSING
    db.add(document)

    job.celery_task_id = str(job_id)
    job.status = ProcessingJobStatus.PROCESSING
    db.add(job)

    document_id = document.id

    try:
        db.flush()

        # Dispatch processing to Celery worker
        result = celery.send_task(
            "process_document",
            args=[str(document_id), response.url],
            task_id=str(job_id),
        )
        db.commit()

    except Exception as e:
        db.rollback()
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
    document = db.get(Document, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    bucket_name = os.environ.get("BUCKET_NAME")

    if not bucket_name:
        raise HTTPException(status_code=500, detail="No bucket name configured")

    try:
        # Delete the file from S3/R2 if it has a key
        if document.s3_key:
            try:
                client = R2Client(bucket_name=bucket_name)
                client.delete_file(key=document.s3_key)
            except S3Error as e:
                raise HTTPException(
                    status_code=500, detail="Error deleted the target file."
                )

        # Delete associated processing jobs
        jobs = db.exec(
            select(ProcessingJob).where(ProcessingJob.document_id == document_id)
        ).all()
        for job in jobs:
            db.delete(job)

        # Delete the document
        db.delete(document)
        db.commit()

        return {
            "success": True,
            "message": f"Document '{document.filename}' deleted successfully",
            "document_id": str(document_id),
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Document deletion failed: {str(e)}",
        )


@router.get("/processing-jobs", response_model=List[ProcessingJob])
def get_processing_jobs(db: Session = Depends(get_db)):
    """Get all processing jobs."""
    jobs = db.exec(select(ProcessingJob)).all()
    return jobs


@router.get("/processing-jobs/{job_id}", response_model=ProcessingJob)
def get_processing_job(job_id: UUID, db: Session = Depends(get_db)):
    """Get a specific processing job."""
    job = db.get(ProcessingJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Processing job not found")
    return job


@router.get("/test")
def test():
    result = celery.send_task(
        "test",
    )
    print(result)
