"""Tests for the root and health-check endpoints defined in ``src.main``."""

import pytest
from httpx import AsyncClient


class TestRootEndpoint:
    """Verify the ``GET /`` welcome endpoint."""

    async def test_root_returns_welcome_message(self, async_client: AsyncClient) -> None:
        """It should return a 200 with a welcome message."""
        resp = await async_client.get("/")
        assert resp.status_code == 200
        data = resp.json()
        assert data == {"message": "Welcome to 30ai API"}

    async def test_root_has_correct_content_type(self, async_client: AsyncClient) -> None:
        """The response content-type should be ``application/json``."""
        resp = await async_client.get("/")
        assert resp.headers["content-type"] == "application/json"


class TestHealthEndpoint:
    """Verify the ``GET /health`` liveness probe."""

    async def test_health_returns_healthy(self, async_client: AsyncClient) -> None:
        """It should return a 200 with status ``healthy``."""
        resp = await async_client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data == {"status": "healthy"}

    async def test_health_is_available_without_auth(self, async_client: AsyncClient) -> None:
        """The health check should not require authentication."""
        resp = await async_client.get("/health")
        assert resp.status_code == 200
