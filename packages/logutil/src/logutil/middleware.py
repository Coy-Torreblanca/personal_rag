"""FastAPI middleware for structured request logging."""

import logging
import time
import uuid
from typing import Callable

from fastapi import FastAPI, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger("api.request")


class RequestLogMiddleware(BaseHTTPMiddleware):
    """Middleware that assigns a unique ``X-Request-ID`` to every request."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id

        # Attach the request ID to the response headers
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id

        return response


class RequestTimingMiddleware(BaseHTTPMiddleware):
    """Middleware that logs the duration of each request.

    This should be registered *after* ``RequestLogMiddleware`` so that the
    ``X-Request-ID`` header is already available.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start = time.monotonic()
        response = await call_next(request)
        duration = time.monotonic() - start

        logger.info(
            "request completed",
            extra={
                "request_id": getattr(request.state, "request_id", None),
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": round(duration * 1000, 1),
            },
        )
        return response


def add_logging_middleware(app: FastAPI) -> None:
    """Register both request-id and timing middleware on the FastAPI app.

    The order is important: request-id first, timing second so that the
    timing middleware can read the request ID from ``request.state``.
    """
    app.add_middleware(RequestLogMiddleware)
    app.add_middleware(RequestTimingMiddleware)
