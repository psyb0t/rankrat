"""Fixed-origin IndexNow submissions constrained to immutable targets."""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import Final
from urllib.parse import unquote, urlparse, urlunparse

import httpx

from rankrat.constants import INDEXNOW_ENDPOINT_URL, MAX_PROVIDER_RESPONSE_BYTES
from rankrat.errors import BoundaryDeniedError
from rankrat.policy.boundaries import BoundaryPolicy
from rankrat.providers.base import (
    IndexNowSubmission,
    IndexNowSubmitRequest,
    ProviderFailureCode,
    ProviderOperationError,
)

_CONTENT_TYPE_HEADER: Final = "Content-Type"
_JSON_CONTENT_TYPE: Final = "application/json"
_KEY_PATTERN: Final = re.compile(r"[A-Za-z0-9-]{8,128}(?:\r\n|\n)?\Z")
_MAX_KEY_FILE_BYTES: Final = 130
_ENCODED_PATH_SEPARATOR_PATTERN: Final = re.compile(r"%(?:2f|5c)", re.IGNORECASE)

HttpTransportFactory = Callable[[], httpx.AsyncBaseTransport | None]


class IndexNowClient:
    """Submit configured URLs to the one IndexNow endpoint without SSRF input."""

    def __init__(
        self,
        boundary_policy: BoundaryPolicy,
        transport_factory: HttpTransportFactory = lambda: None,
    ) -> None:
        self._boundary_policy = boundary_policy
        self._transport_factory = transport_factory

    async def submit(self, request: IndexNowSubmitRequest) -> IndexNowSubmission:
        """Submit a validated, first-seen URL batch for one configured target."""
        target = self._boundary_policy.resolve_indexnow_target(str(request.target_id))
        urls = self._normalize_urls(request.urls, target.host, target.key_location)
        key = self._load_key(target.key_file)
        key_validation_pending = await self._submit_request(
            host=target.host,
            key=key,
            key_location=target.key_location,
            urls=urls,
            timeout_seconds=request.timeout_seconds,
        )
        return IndexNowSubmission(
            target_id=request.target_id,
            host=target.host,
            submitted_count=len(urls),
            key_validation_pending=key_validation_pending,
        )

    async def _submit_request(
        self,
        host: str,
        key: str,
        key_location: str,
        urls: tuple[str, ...],
        timeout_seconds: float,
    ) -> bool:
        payload = {
            "host": host,
            "key": key,
            "keyLocation": key_location,
            "urlList": urls,
        }
        try:
            async with (
                httpx.AsyncClient(
                    transport=self._transport_factory(),
                    trust_env=False,
                    follow_redirects=False,
                    timeout=httpx.Timeout(timeout_seconds),
                ) as client,
                client.stream(
                    "POST",
                    INDEXNOW_ENDPOINT_URL,
                    headers={_CONTENT_TYPE_HEADER: _JSON_CONTENT_TYPE},
                    json=payload,
                ) as response,
            ):
                key_validation_pending = self._raise_for_status(response)
                await self._read_bounded_body(response)
                return key_validation_pending
        except httpx.TimeoutException as error:
            raise ProviderOperationError(
                ProviderFailureCode.TIMEOUT,
                "IndexNow request timed out",
            ) from error
        except httpx.HTTPError as error:
            raise ProviderOperationError(
                ProviderFailureCode.UNAVAILABLE,
                "IndexNow is unavailable",
            ) from error

    @staticmethod
    def _load_key(path: Path) -> str:
        try:
            with path.open("rb") as key_file:
                raw_key = key_file.read(_MAX_KEY_FILE_BYTES + 1)
            key = raw_key.decode("utf-8")
        except (OSError, UnicodeDecodeError) as error:
            raise ProviderOperationError(
                ProviderFailureCode.AUTHENTICATION,
                "IndexNow key is unavailable",
            ) from error
        if len(raw_key) > _MAX_KEY_FILE_BYTES or not _KEY_PATTERN.fullmatch(key):
            raise ProviderOperationError(
                ProviderFailureCode.AUTHENTICATION,
                "IndexNow key is unavailable",
            )
        return key.rstrip("\r\n")

    @classmethod
    def _normalize_urls(
        cls,
        urls: tuple[str, ...],
        host: str,
        key_location: str,
    ) -> tuple[str, ...]:
        key_path = urlparse(key_location).path
        directory, _, _ = key_path.rpartition("/")
        key_directory = f"{directory}/" if directory else "/"
        normalized_urls: list[str] = []
        seen: set[str] = set()
        for url in urls:
            normalized = cls._normalize_url(url, host, key_directory)
            if normalized in seen:
                continue
            seen.add(normalized)
            normalized_urls.append(normalized)
        if not normalized_urls:
            raise BoundaryDeniedError("IndexNow URL submission contains no eligible URLs")
        return tuple(normalized_urls)

    @staticmethod
    def _normalize_url(value: str, host: str, key_directory: str) -> str:
        if not value or any(ord(character) < 32 or ord(character) == 127 for character in value):
            raise BoundaryDeniedError("IndexNow URL is outside the configured boundary")
        try:
            parsed = urlparse(value)
            port = parsed.port
        except ValueError as error:
            raise BoundaryDeniedError("IndexNow URL is outside the configured boundary") from error
        if (
            parsed.scheme.lower() != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.fragment
            or port not in (None, 443)
        ):
            raise BoundaryDeniedError("IndexNow URL is outside the configured boundary")
        try:
            hostname = parsed.hostname.encode("idna").decode("ascii").lower()
        except UnicodeError as error:
            raise BoundaryDeniedError("IndexNow URL is outside the configured boundary") from error
        path = parsed.path or "/"
        decoded_path = unquote(path)
        if _ENCODED_PATH_SEPARATOR_PATTERN.search(path) or "\\" in decoded_path:
            raise BoundaryDeniedError("IndexNow URL is outside the configured boundary")
        if any(segment in {".", ".."} for segment in decoded_path.split("/")):
            raise BoundaryDeniedError("IndexNow URL is outside the configured boundary")
        if hostname != host or not IndexNowClient._is_in_key_scope(path, key_directory):
            raise BoundaryDeniedError("IndexNow URL is outside the configured boundary")
        return urlunparse(("https", hostname, path, "", parsed.query, ""))

    @staticmethod
    def _is_in_key_scope(path: str, key_directory: str) -> bool:
        if key_directory == "/":
            return True
        return path.startswith(key_directory)

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> bool:
        if response.status_code == 200:
            return False
        if response.status_code == 202:
            return True
        if response.status_code == 403:
            raise ProviderOperationError(
                ProviderFailureCode.FORBIDDEN,
                "IndexNow request was rejected",
            )
        if response.status_code == 429:
            raise ProviderOperationError(
                ProviderFailureCode.RATE_LIMITED,
                "IndexNow request was rate limited",
            )
        if response.status_code >= 500:
            raise ProviderOperationError(
                ProviderFailureCode.UNAVAILABLE,
                "IndexNow is unavailable",
            )
        raise ProviderOperationError(
            ProviderFailureCode.INVALID_RESPONSE,
            "IndexNow returned an unexpected response",
        )

    @staticmethod
    async def _read_bounded_body(response: httpx.Response) -> bytes:
        content_length = response.headers.get("content-length")
        if (
            content_length is not None
            and content_length.isdigit()
            and int(content_length) > MAX_PROVIDER_RESPONSE_BYTES
        ):
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "IndexNow response exceeds the allowed size",
            )
        body = bytearray()
        async for chunk in response.aiter_bytes():
            body.extend(chunk)
            if len(body) > MAX_PROVIDER_RESPONSE_BYTES:
                raise ProviderOperationError(
                    ProviderFailureCode.INVALID_RESPONSE,
                    "IndexNow response exceeds the allowed size",
                )
        return bytes(body)
