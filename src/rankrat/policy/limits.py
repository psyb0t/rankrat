"""Small, reusable guards for untrusted boundary and request input."""

from __future__ import annotations

from rankrat.constants import MAX_BOUNDARY_FILE_BYTES, MAX_HTTP_BODY_BYTES
from rankrat.errors import InputLimitError


def require_size_at_most(value: bytes, maximum: int, subject: str) -> bytes:
    """Return bounded bytes or reject them before parsing."""
    if len(value) <= maximum:
        return value
    raise InputLimitError(f"{subject} exceeds the maximum allowed size")


def require_boundary_file_size(value: bytes) -> bytes:
    """Enforce the mounted boundary document byte cap."""
    return require_size_at_most(value, MAX_BOUNDARY_FILE_BYTES, "boundary document")


def require_http_body_size(value: bytes) -> bytes:
    """Enforce the raw HTTP body byte cap."""
    return require_size_at_most(value, MAX_HTTP_BODY_BYTES, "HTTP request body")
