"""Structured stderr logging with secret-shaped fields redacted."""

from __future__ import annotations

import contextvars
import json
import logging
import logging.handlers
import os
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from rankrat.constants import LOG_BACKUP_COUNT, MAX_LOG_BYTES, MAX_REDACTION_DEPTH

_REDACTED = "[REDACTED]"
_SENSITIVE_NAME_PARTS = (
    "api-key",
    "api_key",
    "authorization",
    "cookie",
    "credential",
    "password",
    "secret",
    "token",
)
_STANDARD_RECORD_FIELDS = frozenset(logging.makeLogRecord({}).__dict__)
_LOG_SCOPE: contextvars.ContextVar[dict[str, str] | None] = contextvars.ContextVar(
    "rankrat_log_scope",
    default=None,
)


def _is_sensitive_name(name: str) -> bool:
    return any(part in name.lower() for part in _SENSITIVE_NAME_PARTS)


def redact(value: object, field_name: str = "", depth: int = 0) -> object:
    """Recursively redact values whose field names imply credential material."""
    if _is_sensitive_name(field_name):
        return _REDACTED
    if depth > MAX_REDACTION_DEPTH:
        return value
    if isinstance(value, Mapping):
        mapping = cast(Mapping[object, object], value)
        return {str(key): redact(item, str(key), depth + 1) for key, item in mapping.items()}
    if isinstance(value, list | tuple):
        sequence = cast(Sequence[object], value)
        return [redact(item, depth=depth + 1) for item in sequence]
    return value


def with_log_scope(**fields: str) -> contextvars.Token[dict[str, str] | None]:
    """Add request-scoped fields until the returned token is reset."""
    return _LOG_SCOPE.set({**(_LOG_SCOPE.get() or {}), **fields})


def reset_log_scope(token: contextvars.Token[dict[str, str] | None]) -> None:
    """Restore the preceding logging scope."""
    _LOG_SCOPE.reset(token)


class ScopeFilter(logging.Filter):
    """Attach context-local scope without leaking it across requests."""

    def filter(self, record: logging.LogRecord) -> bool:
        for key, value in (_LOG_SCOPE.get() or {}).items():
            setattr(record, key, value)
        return True


class JsonFormatter(logging.Formatter):
    """Render safe structured records without redirecting stdout."""

    def format(self, record: logging.LogRecord) -> str:
        fields: dict[str, object] = {
            "time": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "file": record.pathname,
            "line": record.lineno,
            "func": record.funcName,
            "msg": record.getMessage(),
        }
        extra = {
            key: value
            for key, value in record.__dict__.items()
            if key not in _STANDARD_RECORD_FIELDS
        }
        fields.update(cast(dict[str, object], redact(extra)))
        return json.dumps(fields, default=str, separators=(",", ":"))


def configure_logging(level: str, log_file: Path) -> None:
    """Configure structured stderr and owner-only rotating-file handlers."""
    log_file.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(log_file.parent, 0o700)
    log_file.touch(mode=0o600, exist_ok=True)
    os.chmod(log_file, 0o600)

    formatter = JsonFormatter()
    scope_filter = ScopeFilter()
    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setFormatter(formatter)
    stderr_handler.addFilter(scope_filter)
    file_handler = logging.handlers.RotatingFileHandler(
        log_file,
        maxBytes=MAX_LOG_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    file_handler.addFilter(scope_filter)
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(stderr_handler)
    root_logger.addHandler(file_handler)
    root_logger.setLevel(level)
    for logger_name in ("httpcore", "httpx"):
        logging.getLogger(logger_name).setLevel(logging.WARNING)


def log_event(
    logger: logging.Logger,
    level: int,
    message: str,
    **fields: Any,
) -> None:
    """Log an event through the shared redaction boundary."""
    logger.log(
        level,
        message,
        extra=cast(Mapping[str, object], redact(fields)),
    )
