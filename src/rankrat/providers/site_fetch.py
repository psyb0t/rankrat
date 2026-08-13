"""Bounded, DNS-pinned retrieval for whole-site technical SEO audits."""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

from rankrat.constants import MAX_SCHEMA_FETCH_RESPONSE_BYTES, MAX_SCHEMA_FETCH_URL_CHARS
from rankrat.errors import InputLimitError, SchemaFetchError, SiteFetchError
from rankrat.models.boundaries import normalize_public_https_url
from rankrat.providers.schema_fetch import (
    PinnedTransportFactory,
    Resolver,
    create_pinned_transport,
    require_public_addresses,
    resolve_public_host,
)

_AUDIT_USER_AGENT = "rankrat-site-audit/0.1"
_BODY_CONTENT_TYPES = frozenset(
    {
        "application/atom+xml",
        "application/rss+xml",
        "application/xhtml+xml",
        "application/xml",
        "text/html",
        "text/plain",
        "text/xml",
    }
)
_AUDIT_RESPONSE_HEADERS = (
    "content-security-policy",
    "referrer-policy",
    "strict-transport-security",
    "x-content-type-options",
    "x-frame-options",
)


@dataclass(frozen=True, slots=True)
class SiteFetchResult:
    """Bounded response metadata and optional supported text body."""

    url: str
    status_code: int
    content_type: str
    body: bytes
    headers: tuple[tuple[str, str], ...] = ()


class PublicSiteFetcher:
    """Fetch one public HTTPS URL without redirects, proxies, or DNS rebinding."""

    def __init__(
        self,
        resolver: Resolver = resolve_public_host,
        transport_factory: PinnedTransportFactory = create_pinned_transport,
    ) -> None:
        self._resolver = resolver
        self._transport_factory = transport_factory

    async def fetch(self, url: str, timeout_seconds: float) -> SiteFetchResult:
        """Return one bounded response after pinning a validated public address."""

        if len(url.encode("utf-8")) > MAX_SCHEMA_FETCH_URL_CHARS:
            raise InputLimitError("site audit URL exceeds the allowed length")
        normalized_url = normalize_public_https_url(url, "site_audit_url")
        parsed = urlparse(normalized_url)
        hostname = parsed.hostname
        if hostname is None:
            raise SiteFetchError("site audit URL must include a DNS hostname")
        try:
            ipaddress.ip_address(hostname)
        except ValueError:
            pass
        else:
            raise SiteFetchError("site audit URL must use a DNS hostname")

        try:
            addresses = require_public_addresses(await self._resolver(hostname))
        except SchemaFetchError as error:
            raise SiteFetchError("site audit URL host is not publicly routable") from error
        transport = self._transport_factory(hostname, str(addresses[0]))
        try:
            async with (
                httpx.AsyncClient(
                    transport=transport,
                    trust_env=False,
                    follow_redirects=False,
                    timeout=httpx.Timeout(timeout_seconds),
                ) as client,
                client.stream(
                    "GET",
                    normalized_url,
                    headers={"User-Agent": _AUDIT_USER_AGENT},
                ) as response,
            ):
                content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
                body = b""
                if response.status_code == 200 and content_type in _BODY_CONTENT_TYPES:
                    body = await self._read_bounded_body(response)
                return SiteFetchResult(
                    normalized_url,
                    response.status_code,
                    content_type,
                    body,
                    tuple(
                        (header, value)
                        for header in _AUDIT_RESPONSE_HEADERS
                        if (value := response.headers.get(header)) is not None
                    ),
                )
        except httpx.TimeoutException as error:
            raise SiteFetchError("site audit request timed out") from error
        except httpx.HTTPError as error:
            raise SiteFetchError("site audit request failed") from error

    @staticmethod
    async def _read_bounded_body(response: httpx.Response) -> bytes:
        content_length = response.headers.get("content-length")
        if (
            content_length is not None
            and content_length.isdigit()
            and int(content_length) > MAX_SCHEMA_FETCH_RESPONSE_BYTES
        ):
            raise SiteFetchError("site audit response exceeds the allowed size")
        body = bytearray()
        async for chunk in response.aiter_bytes():
            body.extend(chunk)
            if len(body) > MAX_SCHEMA_FETCH_RESPONSE_BYTES:
                raise SiteFetchError("site audit response exceeds the allowed size")
        return bytes(body)
