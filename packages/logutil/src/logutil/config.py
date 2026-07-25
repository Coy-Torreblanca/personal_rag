"""Logging configuration loaded from environment variables."""

import logging
import os
from dataclasses import dataclass, field


@dataclass
class LogConfig:
    """Centralised logging configuration.

    Attributes:
        level: The root log level (e.g. ``"DEBUG"``, ``"INFO"``).
        use_json: When ``True`` emit JSON-formatted log records intended
            for production log aggregators.  When ``False`` use a plain
            text format suitable for local development.
        include_location: When ``True`` include the file name and line
            number in each log record (useful during development).
    """

    level: str = "INFO"
    use_json: bool = False
    include_location: bool = True


_CONFIG: LogConfig | None = None


def get_log_config() -> LogConfig:
    """Return a singleton ``LogConfig``, reading from the environment on first call.

    Environment variables:

    * ``LOG_LEVEL`` — one of ``DEBUG``, ``INFO``, ``WARNING``, ``ERROR``, ``CRITICAL``
      (default ``INFO``).
    * ``LOG_JSON`` — if set to a truthy value (``1``, ``true``, ``yes``) structured
      JSON logging is enabled (default ``False``).
    * ``LOG_LOCATION`` — if set to a falsy value (``0``, ``false``, ``no``) the
      file name / line number is omitted from log records (default ``True``).
    """
    global _CONFIG
    if _CONFIG is not None:
        return _CONFIG

    _CONFIG = LogConfig(
        level=_env_str("LOG_LEVEL", "INFO").upper().strip(),
        use_json=_env_bool("LOG_JSON", False),
        include_location=_env_bool("LOG_LOCATION", True),
    )

    # Validate the log level
    valid_levels = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
    if _CONFIG.level not in valid_levels:
        _CONFIG.level = "INFO"

    return _CONFIG


# ---------------------------------------------------------------------------
# Environment helpers
# ---------------------------------------------------------------------------

_TRUTHY = frozenset({"1", "true", "yes", "on"})
_FALSY = frozenset({"0", "false", "no", "off"})


def _env_str(key: str, default: str) -> str:
    return os.environ.get(key, default)


def _env_bool(key: str, default: bool) -> bool:
    val = os.environ.get(key)
    if val is None:
        return default
    val = val.strip().lower()
    if val in _TRUTHY:
        return True
    if val in _FALSY:
        return False
    return default
