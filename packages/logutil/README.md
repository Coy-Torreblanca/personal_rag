# logutil

Centralized logging utilities for the 30ai platform.

## Features

- **`get_logger(name)` / `setup_logging()`** — consistent structured
  (JSON) or plain-text logging configured from environment variables
  (`LOG_LEVEL`, `LOG_JSON`, `LOG_LOCATION`). See `src/logutil/config.py`.
- **`logutil.middleware`** — ASGI middleware for request correlation and
  timing:
  - `RequestLogMiddleware` assigns a unique `X-Request-ID` to every
    request, stores it on `request.state.request_id`, echoes it on the
    response, and emits a `request started` DEBUG record.
  - `RequestTimingMiddleware` emits a structured `request completed`
    INFO record (request ID, method, path, status code, duration) and an
    ERROR record with a stack trace when a handler raises.
  - `add_logging_middleware(app)` registers both in the correct order.

## Installation

The core package has **no FastAPI dependency**:

```bash
uv add logutil                    # logging only (no middleware)
uv add "logutil[fastapi]"         # + middleware support (pulls Starlette via FastAPI)
```

The middleware module imports **Starlette only** at runtime — FastAPI is
used purely for type annotations (`TYPE_CHECKING`) — so it works on plain
Starlette applications as well.

## Usage (FastAPI)

```python
from fastapi import FastAPI
from logutil import setup_logging, get_logger
from logutil.middleware import add_logging_middleware

setup_logging()
logger = get_logger(__name__)

app = FastAPI()
add_logging_middleware(app)   # request-ID + timing logging
```

With JSON logging enabled (`LOG_JSON=1`), each completion record looks
like:

```json
{"timestamp": "...", "logger": "api.request", "level": "INFO",
 "message": "request completed", "request_id": "...",
 "method": "GET", "path": "/health", "status_code": 200,
 "duration_ms": 12.3}
```

## Notes

- Middleware ordering matters: `RequestLogMiddleware` must be added
  *first* so the request ID exists before the timing middleware finishes
  awaiting the response.
- If a handler raises, the 500 response is produced by Starlette's
  server-error middleware *above* `RequestLogMiddleware`, so the
  `X-Request-ID` header is not attached to it; the failure is still fully
  correlated in the logs via the timing middleware's records.

## Development

```bash
uv sync            # install the dev group (pytest, httpx, starlette)
uv run pytest      # run the test suite
```

The test suite runs the middleware against plain Starlette applications to
prove there is no runtime FastAPI dependency.
