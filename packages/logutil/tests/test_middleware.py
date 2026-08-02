"""Tests for ``logutil.middleware`` — request-ID and timing middleware.

These tests run against plain Starlette apps (no FastAPI) to prove the
middleware has no runtime FastAPI dependency, and cover:

* happy path: ``X-Request-ID`` header + ``request.state`` propagation
* uniqueness of request IDs across requests
* structured timing logs with correlation fields
* failure path: 500 responses, error logs with stack traces, and
  completion records with ``status_code=500``
* the ``add_logging_middleware`` registration contract
"""

import logging
import sys

import httpx
import pytest
from starlette.applications import Starlette

from logutil.middleware import (
    RequestLogMiddleware,
    RequestTimingMiddleware,
)

LOGGER_NAME = "api.request"


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestRequestIdMiddleware:
    """``RequestLogMiddleware`` — request ID assignment and propagation."""

    async def test_response_has_request_id_header(self, client: httpx.AsyncClient) -> None:
        """Every response carries an ``X-Request-ID`` header."""
        resp = await client.get("/")
        assert resp.status_code == 200
        assert resp.headers["X-Request-ID"]

    async def test_request_id_available_on_request_state(
        self, client: httpx.AsyncClient
    ) -> None:
        """The handler sees the same ID via ``request.state.request_id``."""
        resp = await client.get("/")
        assert resp.json()["request_id"] == resp.headers["X-Request-ID"]

    async def test_request_id_is_unique_per_request(
        self, client: httpx.AsyncClient
    ) -> None:
        """Two requests must never share a request ID."""
        first = await client.get("/")
        second = await client.get("/")
        assert first.headers["X-Request-ID"] != second.headers["X-Request-ID"]

    async def test_request_started_logged_at_debug(
        self, client: httpx.AsyncClient, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A DEBUG record is emitted when the request begins."""
        with caplog.at_level(logging.DEBUG, logger=LOGGER_NAME):
            resp = await client.get("/")

        started = [r for r in caplog.records if r.getMessage() == "request started"]
        assert len(started) == 1
        record = started[0]
        assert record.levelno == logging.DEBUG
        assert record.request_id == resp.headers["X-Request-ID"]
        assert record.method == "GET"
        assert record.path == "/"


# ---------------------------------------------------------------------------
# Timing middleware
# ---------------------------------------------------------------------------


class TestTimingMiddleware:
    """``RequestTimingMiddleware`` — duration logging with correlation fields."""

    async def test_completion_log_has_all_structured_fields(
        self, client: httpx.AsyncClient, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The completion record carries request_id/method/path/status/duration."""
        with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
            resp = await client.get("/")

        completed = [r for r in caplog.records if r.getMessage() == "request completed"]
        assert len(completed) == 1
        record = completed[0]

        assert record.levelno == logging.INFO
        assert record.request_id == resp.headers["X-Request-ID"]
        assert record.method == "GET"
        assert record.path == "/"
        assert record.status_code == 200
        assert isinstance(record.duration_ms, float)
        assert record.duration_ms >= 0.0

    async def test_logs_500_and_stack_trace_when_handler_raises(
        self, client: httpx.AsyncClient, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A failing handler yields a 500 response, an ERROR record with
        ``exc_info``, and a completion record with ``status_code=500``."""
        with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
            resp = await client.get("/boom")

        assert resp.status_code == 500

        completed = [r for r in caplog.records if r.getMessage() == "request completed"]
        assert len(completed) == 1
        assert completed[0].status_code == 500
        assert completed[0].request_id is not None

        errors = [
            r
            for r in caplog.records
            if r.getMessage() == "request raised an unhandled exception"
        ]
        assert len(errors) == 1
        assert errors[0].levelno == logging.ERROR
        assert errors[0].exc_info is not None  # stack trace attached

    async def test_request_id_is_none_without_log_middleware(
        self, plain_app: Starlette, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Without ``RequestLogMiddleware`` the correlation field is ``None``
        (the middleware must not crash on a missing ``request_id``)."""
        plain_app.add_middleware(RequestTimingMiddleware)

        transport = httpx.ASGITransport(app=plain_app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
                resp = await c.get("/")

        assert resp.status_code == 200
        completed = [r for r in caplog.records if r.getMessage() == "request completed"]
        assert len(completed) == 1
        assert completed[0].request_id is None


# ---------------------------------------------------------------------------
# Registration contract
# ---------------------------------------------------------------------------


class TestAddLoggingMiddleware:
    """``add_logging_middleware`` — registers both middlewares."""

    def test_registers_both_middlewares(
        self, middleware_classes: list[type]
    ) -> None:
        """Both middleware classes are present on the app."""
        assert RequestLogMiddleware in middleware_classes
        assert RequestTimingMiddleware in middleware_classes

    async def test_request_log_middleware_runs_first(
        self, client: httpx.AsyncClient, caplog: pytest.LogCaptureFixture
    ) -> None:
        """End-to-end proof of ordering: the completion log must carry the
        request ID, which is only possible if ``RequestLogMiddleware`` ran
        before the timing middleware finished awaiting the response."""
        with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
            resp = await client.get("/")

        completed = [r for r in caplog.records if r.getMessage() == "request completed"]
        assert len(completed) == 1
        assert completed[0].request_id == resp.headers["X-Request-ID"]


# ---------------------------------------------------------------------------
# No runtime FastAPI dependency
# ---------------------------------------------------------------------------


class TestNoFastApiDependency:
    """The middleware must be importable without FastAPI installed."""

    def test_middleware_module_does_not_import_fastapi(self) -> None:
        """Importing ``logutil.middleware`` must not pull FastAPI into
        ``sys.modules`` — the ``TYPE_CHECKING`` guard keeps it out of the
        runtime import graph (verified in a venv without FastAPI)."""
        import logutil.middleware  # noqa: F401  (re-import is a no-op)

        assert "fastapi" not in sys.modules

    async def test_middleware_works_on_plain_starlette_app(
        self, client: httpx.AsyncClient
    ) -> None:
        """The middleware functions on a Starlette-only application."""
        resp = await client.get("/")
        assert resp.status_code == 200
        assert resp.headers["X-Request-ID"]
