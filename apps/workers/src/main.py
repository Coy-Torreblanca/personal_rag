import os
import modal
from contextlib import contextmanager
from celery import Celery


from .parse_document import APP_NAME
from .generate_embeddings import generate_embeddings
from database.models import Document, DocumentStatus, ProcessingJob, ProcessingJobStatus
from database.session import get_db
from s3.client import R2Client


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


@celery.task(name="process_document", bind=True)
def process_document(self, document_id: str, download_url: str, upload_url: str) -> str:
    job_id = self.request.id

    try:
        m_cls = modal.Cls.from_name(APP_NAME, "DoclingParser")

        result = m_cls().process_document.remote(download_url, upload_url)

        print(result)

    except Exception as e:
        with contextmanager(get_db)() as db:
            try:
                doc = db.get(Document, document_id)
                if doc:
                    doc.status = DocumentStatus.ERROR
                job = db.get(ProcessingJob, job_id)
                if job:
                    job.status = ProcessingJobStatus.FAILED

                db.commit()
            except Exception as ee:
                db.rollback()
                print(ee)

        raise e

    with contextmanager(get_db)() as db:
        doc = db.get(Document, document_id)

        if not doc:
            raise ValueError(f"Could not find document: {document_id}")
        organization_id = str(doc.organization_id)
        s3_key = doc.s3_key

        if not s3_key:
            raise ValueError(f"No s3 key defined for document: {document_id}")

        # TODO - Validate that the document is uploaded.
    bucket_name = os.environ.get("BUCKET_NAME")

    if not bucket_name:
        raise ValueError("No bucket name configured")

    client = R2Client(bucket_name=bucket_name)

    # TODO Add expiration logic.
    expiration = 3600

    response = client.generate_presigned_url(
        key=s3_key + ".md",
        expiration=expiration,
        method="GET",
        inline=False,
    )

    generate_embeddings(response.url, document_id, organization_id)

    # TODO Make Async and have modal make fast api call to mark completed.
    with contextmanager(get_db)() as db:
        doc = db.get(Document, document_id)
        if doc:
            doc.status = DocumentStatus.PROCESSED
        job = db.get(ProcessingJob, job_id)
        if job:
            job.status = ProcessingJobStatus.COMPLETED

        db.commit()

    return result


if __name__ == "__main__":
    celery.start()
