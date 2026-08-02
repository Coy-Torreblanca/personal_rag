"""Fixtures for the ``logutil`` package test suite.

The middleware is exercised against plain Starlette applications (no
FastAPI) on purpose: the whole point of the ``TYPE_CHECKING`` refactor is
that the middleware must work with Starlette alone.  FastAPI integration is
covered by the API service's own test suite.
"""

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from logutil.middleware import (
    add_logging_middleware,
)


def _echo_handler(request):
    """Echo the request ID back so tests can verify ``request.state``."""
    return JSONResponse({"request_id": getattr(request.state, "request_id", None)})


def _boom_handler(request):
    """Handler that always raises — used to exercise failure paths."""
    raise RuntimeError("boom")


@pytest.fixture
def plain_app() -> Starlette:
    """A bare Starlette app with no logging middleware attached."""
    return Starlette(routes=[Route("/", _echo_handler), Route("/boom", _boom_handler)])


@pytest.fixture
def instrumented_app(plain_app: Starlette) -> Starlette:
    """A Starlette app with both logging middlewares registered."""
    add_logging_middleware(plain_app)
    return plain_app


@pytest.fixture
async def client(instrumented_app: Starlette) -> AsyncIterator[AsyncClient]:
    """``httpx.AsyncClient`` wired to the instrumented app via ASGI.

    ``raise_app_exceptions`` is disabled so that tests can observe the
    500 responses produced by Starlette's server-error middleware instead
    of the exceptions propagating into the test.
    """
    transport = ASGITransport(app=instrumented_app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
def middleware_classes(instrumented_app: Starlette) -> list[type]:
    """The middleware classes registered on the instrumented app."""
    return [m.cls for m in instrumented_app.user_middleware]
