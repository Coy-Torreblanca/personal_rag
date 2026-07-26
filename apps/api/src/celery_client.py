"""Minimal Celery producer for the 30ai API service.

This module initialises a Celery application instance used exclusively for
dispatching tasks to the broker. No task implementations live here — they
are defined in ``apps/workers`` and registered dynamically at runtime.

Environment variables:
    REDIS_URL: Redis connection string used as the Celery message broker.
               Defaults to ``redis://localhost:6379/0``.
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
