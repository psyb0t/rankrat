"""Bounded, DNS-pinned HTTPS retrieval for public structured-data validation."""

from __future__ import annotations

import asyncio
import ipaddress
from collections.abc import AsyncIterable, AsyncIterator, Awaitable, Callable, Iterable
from dataclasses import dataclass
from typing import cast
from urllib.parse import urlparse

import httpcore
import httpx

from rankrat.constants import (
    MAX_SCHEMA_FETCH_RESPONSE_BYTES,
    MAX_SCHEMA_FETCH_URL_CHARS,
)
from rankrat.errors import InputLimitError, SchemaFetchError
from rankrat.models.boundaries import normalize_public_https_audit_url

_HTTPS_PORT = 443
_HTML_CONTENT_TYPES = frozenset({"application/xhtml+xml", "text/html"})
_USER_AGENT = "rankrat-schema-validator/0.1"

ResolvedAddress = ipaddress.IPv4Address | ipaddress.IPv6Address
Resolver = Callable[[str], Awaitable[tuple[ResolvedAddress, ...]]]
PinnedTransportFactory = Callable[[str, str], httpx.AsyncBaseTransport]


@dataclass(frozen=True, slots=True)
class SchemaFetchResult:
    """A bounded HTML document retained only inside schema-validation services."""

    url: str
    content_type: str
    body: bytes


async def resolve_public_host(hostname: str) -> tuple[ResolvedAddress, ...]:
    """Resolve a DNS hostname once and reject mixed or non-global answers."""

    try:
        records = await asyncio.get_running_loop().getaddrinfo(
            hostname,
            _HTTPS_PORT,
            type=0,
        )
    except OSError as error:
        raise SchemaFetchError("schema URL host cannot be resolved") from error

    addresses: set[ResolvedAddress] = set()
    for record in records:
        raw_address = record[4][0]
        try:
            address = ipaddress.ip_address(raw_address)
        except ValueError as error:
            raise SchemaFetchError("schema URL host returned an invalid address") from error
        addresses.add(address)

    return require_public_addresses(tuple(addresses))


def require_public_addresses(
    addresses: tuple[ResolvedAddress, ...],
) -> tuple[ResolvedAddress, ...]:
    """Reject an empty, private, link-local, or mixed DNS answer set."""

    if not addresses or any(not address.is_global for address in addresses):
        raise SchemaFetchError("schema URL host is not publicly routable")
    return tuple(sorted(addresses, key=str))


class _PinnedNetworkBackend(httpcore.AsyncNetworkBackend):
    """Connect only to the pre-resolved address while preserving TLS hostname checks."""

    def __init__(self, hostname: str, address: str) -> None:
        self._hostname = hostname
        self._address = address
        self._backend = cast(httpcore.AsyncNetworkBackend, httpcore.AnyIOBackend())

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[httpcore.SOCKET_OPTION] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        if host != self._hostname or port != _HTTPS_PORT:
            raise httpcore.ConnectError("pinned schema connection target changed")
        return await self._backend.connect_tcp(
            self._address,
            port,
            timeout,
            local_address,
            socket_options,
        )

    async def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,
        socket_options: Iterable[httpcore.SOCKET_OPTION] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        raise httpcore.ConnectError("schema fetch does not support Unix sockets")

    async def sleep(self, seconds: float) -> None:
        await self._backend.sleep(seconds)


class _HTTPXResponseStream(httpx.AsyncByteStream):
    """Adapt HTTPCore's stream without using HTTPX private modules."""

    def __init__(self, stream: AsyncIterable[bytes]) -> None:
        self._stream = stream

    async def __aiter__(self) -> AsyncIterator[bytes]:
        try:
            async for chunk in self._stream:
                yield chunk
        except httpcore.TimeoutException as error:
            raise httpx.ReadTimeout("schema response timed out") from error
        except httpcore.NetworkError as error:
            raise httpx.ReadError("schema response read failed") from error

    async def aclose(self) -> None:
        closer = getattr(self._stream, "aclose", None)
        if closer is not None:
            await closer()


class _PinnedAsyncTransport(httpx.AsyncBaseTransport):
    """A minimal public-API HTTPCore transport with one pinned TCP destination."""

    def __init__(self, hostname: str, address: str) -> None:
        self._pool = httpcore.AsyncConnectionPool(
            network_backend=_PinnedNetworkBackend(hostname, address),
            http1=True,
            http2=False,
            retries=0,
        )

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if not isinstance(request.stream, httpx.AsyncByteStream):
            raise httpx.RequestError("schema request stream is invalid", request=request)
        core_request = httpcore.Request(
            method=request.method,
            url=httpcore.URL(
                scheme=request.url.raw_scheme,
                host=request.url.raw_host,
                port=request.url.port,
                target=request.url.raw_path,
            ),
            headers=request.headers.raw,
            content=request.stream,
            extensions=request.extensions,
        )
        try:
            core_response = await self._pool.handle_async_request(core_request)
        except httpcore.TimeoutException as error:
            raise httpx.TimeoutException("schema request timed out", request=request) from error
        except httpcore.NetworkError as error:
            raise httpx.NetworkError("schema request failed", request=request) from error
        return httpx.Response(
            status_code=core_response.status,
            headers=core_response.headers,
            stream=_HTTPXResponseStream(cast(AsyncIterable[bytes], core_response.stream)),
            extensions={},
            request=request,
        )

    async def aclose(self) -> None:
        await self._pool.aclose()


def create_pinned_transport(hostname: str, address: str) -> httpx.AsyncBaseTransport:
    """Create the production transport after DNS policy has selected one address."""

    return _PinnedAsyncTransport(hostname, address)


class PublicSchemaFetcher:
    """Fetch HTML once, with SSRF defenses enforced before any network connection."""

    def __init__(
        self,
        resolver: Resolver = resolve_public_host,
        transport_factory: PinnedTransportFactory = create_pinned_transport,
    ) -> None:
        self._resolver = resolver
        self._transport_factory = transport_factory

    async def fetch(self, url: str, timeout_seconds: float) -> SchemaFetchResult:
        """Return one bounded HTML response without following redirects or re-resolving DNS."""

        if len(url.encode("utf-8")) > MAX_SCHEMA_FETCH_URL_CHARS:
            raise InputLimitError("schema URL exceeds the allowed length")
        normalized_url = normalize_public_https_audit_url(url, "schema_url")
        parsed = urlparse(normalized_url)
        hostname = parsed.hostname
        if hostname is None:
            raise SchemaFetchError("schema URL must include a DNS hostname")
        try:
            ipaddress.ip_address(hostname)
        except ValueError:
            pass
        else:
            raise SchemaFetchError("schema URL must use a DNS hostname")

        addresses = require_public_addresses(await self._resolver(hostname))
        address = str(addresses[0])
        transport = self._transport_factory(hostname, address)
        try:
            async with (
                httpx.AsyncClient(
                    transport=transport,
                    trust_env=False,
                    follow_redirects=False,
                    timeout=httpx.Timeout(timeout_seconds),
                ) as client,
                client.stream(
                    "GET", normalized_url, headers={"User-Agent": _USER_AGENT}
                ) as response,
            ):
                if response.status_code != 200 or response.is_redirect:
                    raise SchemaFetchError("schema URL returned an unexpected response")
                content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
                if content_type not in _HTML_CONTENT_TYPES:
                    raise SchemaFetchError("schema URL did not return HTML")
                body = await self._read_bounded_body(response)
        except SchemaFetchError:
            raise
        except httpx.TimeoutException as error:
            raise SchemaFetchError("schema URL request timed out") from error
        except httpx.HTTPError as error:
            raise SchemaFetchError("schema URL request failed") from error
        return SchemaFetchResult(normalized_url, content_type, body)

    @staticmethod
    async def _read_bounded_body(response: httpx.Response) -> bytes:
        content_length = response.headers.get("content-length")
        if (
            content_length is not None
            and content_length.isdigit()
            and int(content_length) > MAX_SCHEMA_FETCH_RESPONSE_BYTES
        ):
            raise SchemaFetchError("schema URL response exceeds the allowed size")
        body = bytearray()
        async for chunk in response.aiter_bytes():
            body.extend(chunk)
            if len(body) > MAX_SCHEMA_FETCH_RESPONSE_BYTES:
                raise SchemaFetchError("schema URL response exceeds the allowed size")
        return bytes(body)
