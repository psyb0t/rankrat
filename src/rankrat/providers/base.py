"""Provider client contracts with no caller-controlled network destination."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import NewType, Protocol

import httpx

from rankrat.constants import MAX_INDEXNOW_URLS, MAX_PROVIDER_RESPONSE_BYTES
from rankrat.models.boundaries import Provider

MIN_PROVIDER_TIMEOUT_SECONDS = 0.1
MAX_PROVIDER_TIMEOUT_SECONDS = 30.0

AccountId = NewType("AccountId", str)
IndexNowTargetId = NewType("IndexNowTargetId", str)


AccessTokenProvider = Callable[[Path], Awaitable[str]]


class ProviderFailureCode(StrEnum):
    """Stable failure categories that are safe to surface through adapters."""

    AUTHENTICATION = "AUTHENTICATION"
    FORBIDDEN = "FORBIDDEN"
    RATE_LIMITED = "RATE_LIMITED"
    TIMEOUT = "TIMEOUT"
    UNAVAILABLE = "UNAVAILABLE"
    INVALID_RESPONSE = "INVALID_RESPONSE"


class ProviderOperationError(Exception):
    """A typed, redaction-safe provider error without an upstream payload."""

    def __init__(
        self,
        code: ProviderFailureCode,
        message: str,
        detail: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.detail = detail


async def read_limited_response(
    response: httpx.Response,
    *,
    description: str,
    maximum_bytes: int = MAX_PROVIDER_RESPONSE_BYTES,
) -> bytes:
    """Read one provider response without buffering beyond the configured limit."""

    content_length = response.headers.get("content-length")
    if content_length is not None:
        try:
            parsed_content_length = int(content_length)
        except ValueError as error:
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                f"{description} returned an invalid content length",
            ) from error
        if parsed_content_length < 0:
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                f"{description} returned an invalid content length",
            )
        if parsed_content_length > maximum_bytes:
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                f"{description} response exceeds the allowed size",
            )
    body = bytearray()
    async for chunk in response.aiter_bytes():
        if len(body) + len(chunk) > maximum_bytes:
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                f"{description} response exceeds the allowed size",
            )
        body.extend(chunk)
    return bytes(body)


@dataclass(frozen=True, slots=True)
class ProviderReadRequest:
    """The only common input for future authenticated provider reads."""

    account_id: AccountId
    timeout_seconds: float

    def __post_init__(self) -> None:
        if self.timeout_seconds < MIN_PROVIDER_TIMEOUT_SECONDS:
            raise ValueError("timeout_seconds must be positive")
        if self.timeout_seconds > MAX_PROVIDER_TIMEOUT_SECONDS:
            raise ValueError("timeout_seconds exceeds the provider read limit")


@dataclass(frozen=True, slots=True)
class ProviderReadiness:
    """A non-sensitive result for a future fixed-origin provider health check."""

    account_id: AccountId
    provider: Provider
    available: bool
    detail: str


@dataclass(frozen=True, slots=True)
class IndexNowSubmitRequest:
    """A bounded IndexNow submission against one configured immutable target."""

    target_id: IndexNowTargetId
    urls: tuple[str, ...]
    timeout_seconds: float

    def __post_init__(self) -> None:
        if not self.urls:
            raise ValueError("at least one IndexNow URL is required")
        if len(self.urls) > MAX_INDEXNOW_URLS:
            raise ValueError("IndexNow URL count exceeds the submission limit")
        if self.timeout_seconds < MIN_PROVIDER_TIMEOUT_SECONDS:
            raise ValueError("timeout_seconds must be positive")
        if self.timeout_seconds > MAX_PROVIDER_TIMEOUT_SECONDS:
            raise ValueError("timeout_seconds exceeds the provider request limit")


@dataclass(frozen=True, slots=True)
class IndexNowSubmission:
    """A secret-free acknowledgement of a submitted IndexNow batch."""

    target_id: IndexNowTargetId
    host: str
    submitted_count: int
    key_validation_pending: bool


class ProviderClient(Protocol):
    """Safe shape for future fixed-origin provider implementations.

    The deployment owns the provider base URL and credential path. Neither can
    enter this contract from MCP or REST input.
    """

    @property
    def provider(self) -> Provider:
        """Return the provider this client is permanently configured for."""
        ...

    async def readiness(self, request: ProviderReadRequest) -> ProviderReadiness:
        """Check configured-provider readiness without accepting a base URL."""
        ...
