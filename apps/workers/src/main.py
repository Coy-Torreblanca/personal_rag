import os
from celery import Celery

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


@celery.task(name="test")
def test():
    print("Hello from workers!")
    import time

    time.sleep(5)


if __name__ == "__main__":
    celery.start()
