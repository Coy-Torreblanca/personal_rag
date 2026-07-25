"""30ai centralized logging utilities.

Provides structured JSON logging, context propagation, and FastAPI integration
for consistent observability across all services.
"""

import logging
import sys

from .config import LogConfig, get_log_config
from .middleware import RequestLogMiddleware, RequestTimingMiddleware, add_logging_middleware

# Re-export for convenience
__all__ = [
    "LogConfig",
    "get_log_config",
    "get_logger",
    "setup_logging",
    "RequestLogMiddleware",
    "RequestTimingMiddleware",
    "add_logging_middleware",
]

# Module-level logger cache
_loggers: dict[str, logging.Logger] = {}


def setup_logging(config: LogConfig | None = None) -> None:
    """Configure the root logger for the application.

    Args:
        config: A ``LogConfig`` instance. If ``None``, configuration is
            loaded from environment variables via ``get_log_config()``.
    """
    if config is None:
        config = get_log_config()

    # Remove all existing handlers from the root logger
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(config.level)

    handler: logging.Handler
    if config.use_json:
        try:
            from pythonjsonlogger import jsonlogger

            handler = logging.StreamHandler(sys.stdout)
            formatter = jsonlogger.JsonFormatter(
                fmt="%(asctime)s %(name)s %(levelname)s %(message)s",
                datefmt="%Y-%m-%dT%H:%M:%S%z",
                rename_fields={"asctime": "timestamp", "name": "logger", "levelname": "level"},
            )
            handler.setFormatter(formatter)
        except ImportError:
            # Fall back to standard logging if python-json-logger is not installed
            handler = _create_standard_handler(config)
    else:
        handler = _create_standard_handler(config)

    root_logger.addHandler(handler)

    # Quiet noisy third-party loggers
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("boto3").setLevel(logging.WARNING)
    logging.getLogger("botocore").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)


def _create_standard_handler(config: LogConfig) -> logging.Handler:
    """Create a standard (non-JSON) console handler."""
    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler.setFormatter(formatter)
    return handler


def get_logger(name: str) -> logging.Logger:
    """Get (or create) a logger with the given *name*.

    Args:
        name: The logger name, typically ``__name__``.

    Returns:
        A configured ``logging.Logger`` instance.
    """
    if name in _loggers:
        return _loggers[name]

    logger = logging.getLogger(name)
    _loggers[name] = logger
    return logger


# Convenience: call ``setup_logging()`` on first import so that any subsequent
# ``get_logger(...)`` call works with sensible defaults.
setup_logging()
