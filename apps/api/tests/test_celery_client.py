"""Tests for the Celery client module (``src.celery_client``).

The ``celery`` singleton is tested here by checking its configuration rather
than actually connecting to a broker, which avoids needing a running Redis.
"""

import os
from unittest.mock import patch

from src.celery_client import celery


class TestCeleryConfiguration:
    """Verify that the Celery app is configured as expected."""

    def test_app_name(self) -> None:
        """The Celery app should be named ``30ai_api``."""
        assert celery.main == "30ai_api"

    def test_default_broker_url(self) -> None:
        """When ``REDIS_URL`` is unset the broker should fall back to the default."""
        with patch.dict(os.environ, {}, clear=True):
            # Re-import to pick up the environment change (or just check .conf)
            from importlib import reload
            import src.celery_client as cc

            reload(cc)
            assert "redis://localhost:6379/0" in cc.celery.conf.broker_url

    def test_broker_url_from_env(self) -> None:
        """When ``REDIS_URL`` is set the broker should use it."""
        with patch.dict(os.environ, {"REDIS_URL": "redis://redis.example.com:6380/1"}):
            from importlib import reload
            import src.celery_client as cc

            reload(cc)
            assert cc.celery.conf.broker_url == "redis://redis.example.com:6380/1"

    def test_importable(self) -> None:
        """The module should be importable without raising."""
        from src.celery_client import celery as c
        assert c is not None
