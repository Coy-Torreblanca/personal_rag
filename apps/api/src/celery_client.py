"""Minimal Celery producer for the API.

This is intentionally lightweight — just enough to push tasks to the broker.
The actual task implementations live in apps/workers.
"""
import os

from celery import Celery

from logutil import get_logger

logger = get_logger(__name__)

celery = Celery(
    "30ai_api",
    broker=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
)

logger.info("Celery client initialized with broker=%s", celery.conf.broker_url)
