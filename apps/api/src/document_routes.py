import os
from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, BackgroundTasks
from sqlmodel import Session, select

from database.models import Document, ProcessingJob
from database.session import get_db

router = APIRouter(prefix="/api", tags=["documents"])


@router.get("/documents", response_model=List[Document])
def get_documents(db: Session = Depends(get_db)):
    """Get all documents."""
    documents = db.exec(select(Document)).all()
    return documents


@router.post("/documents/upload")
async def upload_document(
    file: UploadFile = File(...),
    organization_id: UUID | None = None,
    user_id: UUID | None = None,
    db: Session = Depends(get_db),
    background_tasks: BackgroundTasks = None,
):
    """Upload a document for processing."""
    # Validate file type
    allowed_types = [
        "application/pdf",
        "text/plain",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ]
    if file.content_type not in allowed_types:
        raise HTTPException(
            status_code=400,
            detail=f"File type {file.content_type} not supported. Allowed types: {', '.join(allowed_types)}",
        )

    # Read file content
    content = await file.read()
    file_size = len(content)

    # Create document record
    document = Document(
        filename=file.filename,
        file_type=file.content_type,
        file_size=file_size,
        organization_id=organization_id
        or UUID("00000000-0000-0000-0000-000000000000"),  # Default org
        user_id=user_id or UUID("00000000-0000-0000-0000-000000000000"),  # Default user
        status="uploaded",
        metadata={
            "original_filename": file.filename,
            "content_type": file.content_type,
        },
    )

    db.add(document)
    db.commit()
    db.refresh(document)

    # Store file in S3
    from packages.s3.src.s3 import R2Client
    from packages.s3.src.s3.exceptions import S3Error

    s3_key = None
    try:
        org_id = organization_id or UUID("00000000-0000-0000-0000-000000000000")
        s3_client = R2Client(bucket_name=os.getenv("S3_BUCKET_NAME", "documents"))
        s3_key = f"documents/{org_id}/{document.id}/{file.filename}"

        s3_response = s3_client.upload_bytes(
            data=content,
            key=s3_key,
            content_type=file.content_type,
            metadata={
                "document_id": str(document.id),
                "organization_id": str(org_id),
            },
        )

        document.metadata["s3_key"] = s3_key
        document.metadata["s3_bucket"] = s3_response.metadata.bucket
        db.add(document)
        db.commit()
    except S3Error as e:
        document.metadata["s3_error"] = str(e)
        db.add(document)
        db.commit()

    # Trigger background processing
    if background_tasks:
        # In a real implementation, this would call Celery
        # background_tasks.add_task(process_document_task, document.id)
        pass

    return {
        "message": "Document uploaded successfully",
        "document_id": str(document.id),
        "filename": document.filename,
        "status": document.status,
        "s3_key": s3_key,
        "file_size": file_size,
    }


@router.post("/documents/{document_id}/process")
def process_document(document_id: UUID, db: Session = Depends(get_db)):
    """Trigger processing for a document."""
    document = db.get(Document, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    # Check if document is already being processed
    if document.status in ["processing", "processed"]:
        raise HTTPException(
            status_code=400, detail=f"Document is already {document.status}"
        )

    # Update document status
    document.status = "processing"
    db.add(document)
    db.commit()

    # TODO: Send task to Celery worker
    # celery.send_task("process_document", args=[str(document_id)])

    return {
        "message": "Document processing started",
        "document_id": str(document_id),
        "status": "processing",
    }


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
