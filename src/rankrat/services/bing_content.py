"""Bing content submission from Rankrat's own bounded public-page fetch."""

from __future__ import annotations

import base64
from dataclasses import dataclass

from rankrat.constants import (
    DEFAULT_PROVIDER_TIMEOUT_SECONDS,
    MAX_BING_CONTENT_MESSAGE_BYTES,
)
from rankrat.errors import InputLimitError
from rankrat.policy.boundaries import BoundaryPolicy
from rankrat.providers.base import AccountId, ProviderReadRequest
from rankrat.providers.bing import BingWebmasterClient
from rankrat.providers.site_fetch import PublicSiteFetcher

_HTTP_OK_LINE = b"HTTP/1.1 200 OK\r\n"
_HTTP_CONTENT_TYPE = b"Content-Type: text/html; charset=utf-8\r\n"
_HTTP_CONTENT_LENGTH_PREFIX = b"Content-Length: "
_HTTP_HEADER_TERMINATOR = b"\r\n\r\n"
_HTML_CONTENT_TYPES = frozenset({"application/xhtml+xml", "text/html"})


@dataclass(frozen=True, slots=True)
class BingContentSubmissionRequest:
    """One explicit Bing site/page content submission derived by Rankrat itself."""

    account_id: str
    site_url: str
    page_url: str
    dynamic_serving: bool = False
    timeout_seconds: float = DEFAULT_PROVIDER_TIMEOUT_SECONDS


@dataclass(frozen=True, slots=True)
class BingContentSubmissionReceipt:
    """Secret-free acknowledgement of the exact page fetched and submitted."""

    site_url: str
    page_url: str
    content_bytes: int
    dynamic_serving: bool


class BingContentSubmissionService:
    """Fetch a configured public page and submit no caller-supplied HTTP body to Bing."""

    def __init__(
        self,
        policy: BoundaryPolicy,
        fetcher: PublicSiteFetcher,
        client: BingWebmasterClient,
    ) -> None:
        self._policy = policy
        self._fetcher = fetcher
        self._client = client

    async def submit(
        self,
        request: BingContentSubmissionRequest,
    ) -> BingContentSubmissionReceipt:
        """Fetch, construct, and submit one exact configured Bing page representation."""

        page_url = self._policy.require_bing_site_url(
            request.account_id,
            request.site_url,
            request.page_url,
        )
        fetched = await self._fetcher.fetch(page_url, request.timeout_seconds)
        if fetched.status_code != 200:
            raise InputLimitError("Bing content submission requires a public 200 response")
        if fetched.content_type not in _HTML_CONTENT_TYPES:
            raise InputLimitError("Bing content submission requires an HTML response")
        if not fetched.body:
            raise InputLimitError("Bing content submission requires a non-empty HTML response")
        http_message = _bing_http_message(fetched.body)
        if len(http_message) > MAX_BING_CONTENT_MESSAGE_BYTES:
            raise InputLimitError("Bing content submission exceeds the allowed size")
        await self._client.submit_content(
            ProviderReadRequest(
                AccountId(request.account_id),
                request.timeout_seconds,
            ),
            request.site_url,
            page_url,
            http_message.decode("ascii"),
            request.dynamic_serving,
        )
        return BingContentSubmissionReceipt(
            request.site_url,
            page_url,
            len(fetched.body),
            request.dynamic_serving,
        )


def _bing_http_message(body: bytes) -> bytes:
    payload = (
        _HTTP_OK_LINE
        + _HTTP_CONTENT_TYPE
        + _HTTP_CONTENT_LENGTH_PREFIX
        + str(len(body)).encode("ascii")
        + _HTTP_HEADER_TERMINATOR
        + body
    )
    return base64.b64encode(payload)
