"""Bearer authentication for intentionally exposed HTTP deployments."""

from __future__ import annotations

import hmac
import os
import stat
from pathlib import Path

from rankrat.errors import ConfigurationError

_MINIMUM_BEARER_SECRET_LENGTH = 32
_OWNER_ONLY_MODE_MASK = 0o077
_NO_FOLLOW_FLAG = getattr(os, "O_NOFOLLOW", None)


def load_bearer_secret(path: Path | None) -> str | None:
    """Load one mounted bearer secret without returning its path or value in errors."""
    if path is None:
        return None
    if _NO_FOLLOW_FLAG is None:
        raise ConfigurationError("HTTP bearer authentication requires no-follow filesystem support")
    try:
        descriptor = os.open(path, os.O_RDONLY | _NO_FOLLOW_FLAG)
        try:
            metadata = os.fstat(descriptor)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_uid != os.geteuid()
                or metadata.st_mode & _OWNER_ONLY_MODE_MASK
            ):
                raise ConfigurationError("HTTP bearer authentication file permissions are unsafe")
            with os.fdopen(descriptor, "r", encoding="utf-8") as secret_file:
                descriptor = -1
                secret = secret_file.read().strip()
        finally:
            if descriptor >= 0:
                os.close(descriptor)
    except (OSError, UnicodeError) as error:
        raise ConfigurationError("unable to load HTTP bearer authentication") from error
    if len(secret) < _MINIMUM_BEARER_SECRET_LENGTH:
        raise ConfigurationError("HTTP bearer authentication secret is too short")
    return secret


def bearer_is_valid(authorization: str | None, expected_secret: str | None) -> bool:
    """Verify the exact Bearer scheme with a constant-time secret comparison."""
    if expected_secret is None:
        return True
    if authorization is None:
        return False
    scheme, separator, presented_secret = authorization.partition(" ")
    if separator != " " or scheme != "Bearer" or not presented_secret:
        return False
    return hmac.compare_digest(presented_secret, expected_secret)
