"""Typed errors that adapters can map without exposing sensitive details."""

from __future__ import annotations


class RankratError(Exception):
    """Base error for expected Rankrat failures."""


class ConfigurationError(RankratError):
    """Raised when immutable deployment configuration is invalid."""


class BoundaryDeniedError(RankratError):
    """Raised when a configured account or resource is not authorized."""


class InputLimitError(RankratError):
    """Raised when an input exceeds a documented safety limit."""


class WritesDisabledError(RankratError):
    """Raised when an operator has not enabled an explicit write capability."""


class ApprovalDeniedError(RankratError):
    """Raised when a write approval is missing, mismatched, expired, or spent."""


class SchemaFetchError(RankratError):
    """Raised when a public schema URL is unsafe or cannot be safely fetched."""


class IndexNowRateLimitError(RankratError):
    """Raised when a configured IndexNow target has exhausted its request rate."""
