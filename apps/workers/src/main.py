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


def _fail_job(document_id: str, job_id: str):
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
            print(ee)


@celery.task(name="process_document", bind=True)
def process_document(
    self,
    document_id: str,
    organization_id: str,
    s3_key: str,
    download_url: str,
    upload_url: str,
) -> str:
    job_id: str = self.request.id

    try:
        # TODO Make Async and have modal make fast api call to continue processing.
        m_cls = modal.Cls.from_name(APP_NAME, "DoclingParser")

        result = m_cls().process_document.remote(download_url, upload_url)

        client = R2Client(bucket_name=os.environ["BUCKET_NAME"])

        # TODO Add expiration logic.
        expiration = 3600

        response = client.generate_presigned_url(
            key=s3_key + ".md",
            expiration=expiration,
            method="GET",
            inline=False,
        )

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
        _fail_job(document_id, job_id)
        raise e

    return result


if __name__ == "__main__":
    celery.start()
