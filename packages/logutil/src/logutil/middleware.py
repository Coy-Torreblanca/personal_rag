"""ASGI middleware for structured request logging.

This module provides two ``BaseHTTPMiddleware`` subclasses that attach a
unique ``X-Request-ID`` to every response and log request timing with
structured ``extra`` fields, plus a convenience ``add_logging_middleware``
helper for FastAPI applications.

Dependencies
------------
The runtime imports here are **Starlette-only**; FastAPI itself is used
purely for type annotations (``TYPE_CHECKING``) and is never imported at
runtime.  Starlette is pulled in transitively by FastAPI, so applications
that use this middleware should depend on ``logutil[fastapi]`` (see
``pyproject.toml``).  The middleware also works on any plain Starlette app.

Middleware ordering
-------------------
``RequestLogMiddleware`` must be registered *before*
``RequestTimingMiddleware`` (i.e. added first) so that the request ID is
available on ``request.state`` when the timing middleware runs.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import TYPE_CHECKING

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = logging.getLogger("api.request")


class RequestLogMiddleware(BaseHTTPMiddleware):
    """Assign a unique ``X-Request-ID`` to every request and response.

    The ID is generated up-front and stored on ``request.state`` so that
    downstream middleware (e.g. ``RequestTimingMiddleware``) and handlers
    can correlate log records.

    Note on error responses: if the downstream handler raises, Starlette's
    server-error middleware builds the 500 response *above* this middleware,
    so the header cannot be attached to it from here.  In that case the
    failure is logged (with the request ID) by ``RequestTimingMiddleware``
    instead — see its docstring.
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id

        logger.debug(
            "request started",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
            },
        )

        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id

        return response


class RequestTimingMiddleware(BaseHTTPMiddleware):
    """Log the duration of each request together with correlation fields.

    Register this *after* ``RequestLogMiddleware`` so the ``X-Request-ID``
    is already available on ``request.state``.  If the downstream handler
    raises, the exception is re-raised (so Starlette's error middleware
    still produces a 500) but a completion record with ``status_code=500``
    and an ERROR record with the stack trace are emitted first — failed
    requests must not silently disappear from the logs.
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        start = time.monotonic()
        status_code = 500  # Assumed failure; overwritten on success.
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        except Exception:
            logger.error(
                "request raised an unhandled exception",
                exc_info=True,
                extra={
                    "request_id": getattr(request.state, "request_id", None),
                    "method": request.method,
                    "path": request.url.path,
                },
            )
            raise
        finally:
            duration = time.monotonic() - start
            logger.info(
                "request completed",
                extra={
                    "request_id": getattr(request.state, "request_id", None),
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": status_code,
                    "duration_ms": round(duration * 1000, 1),
                },
            )


def add_logging_middleware(app: FastAPI) -> None:
    """Register request-id and timing middleware on a FastAPI app.

    Order matters: ``RequestLogMiddleware`` is added first so that the
    timing middleware can read the request ID from ``request.state``.

    Parameters
    ----------
    app : FastAPI
        The application to instrument.  Any object exposing
        ``add_middleware`` works at runtime; the annotation is FastAPI for
        documentation purposes.
    """
    app.add_middleware(RequestLogMiddleware)
    app.add_middleware(RequestTimingMiddleware)
