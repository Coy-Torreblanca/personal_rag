import os
import modal
from contextlib import contextmanager
from celery import Celery

from .process_document import APP_NAME
from database.models import Document, DocumentStatus, ProcessingJob, ProcessingJobStatus
from database.session import get_db


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


@celery.task(name="test")
def test():
    print("Hello from workers!")
    with app.run():
        modal_result = modal_hello_world.remote()
    print(f"modal says: {modal_result}")

    import time

    time.sleep(5)


if __name__ == "__main__":
    celery.start()
