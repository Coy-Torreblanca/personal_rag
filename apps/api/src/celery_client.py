"""Minimal Celery producer for the API.

This is intentionally lightweight — just enough to push tasks to the broker.
The actual task implementations live in apps/workers.
"""
import os

from celery import Celery

celery = Celery(
    "30ai_api",
    broker=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
)
