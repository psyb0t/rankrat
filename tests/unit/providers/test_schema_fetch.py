from __future__ import annotations

import ipaddress

import httpcore
import httpx
import pytest

from rankrat.constants import MAX_SCHEMA_FETCH_RESPONSE_BYTES
from rankrat.errors import InputLimitError, SchemaFetchError
from rankrat.providers import schema_fetch
from rankrat.providers.schema_fetch import (
    PublicSchemaFetcher,
    _HTTPXResponseStream,
    _PinnedAsyncTransport,
    _PinnedNetworkBackend,
    create_pinned_transport,
    require_public_addresses,
    resolve_public_host,
)


def _public_address() -> tuple[ipaddress.IPv4Address, ...]:
    return (ipaddress.IPv4Address("93.184.216.34"),)


@pytest.mark.asyncio
async def test_schema_fetch_uses_single_resolved_address_and_safe_http_request() -> None:
    calls: list[tuple[str, str]] = []

    async def resolver(hostname: str) -> tuple[ipaddress.IPv4Address, ...]:
        assert hostname == "example.com"
        return _public_address()

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert str(request.url) == "https://example.com/path"
        assert request.headers["user-agent"] == "rankrat-schema-validator/0.1"
        return httpx.Response(200, headers={"content-type": "text/html"}, content=b"<html />")

    def transport_factory(hostname: str, address: str) -> httpx.AsyncBaseTransport:
        calls.append((hostname, address))
        return httpx.MockTransport(handler)

    result = await PublicSchemaFetcher(resolver, transport_factory).fetch(
        "https://EXAMPLE.com:443/path",
        1.0,
    )
    assert result.url == "https://example.com/path"
    assert result.body == b"<html />"
    assert calls == [("example.com", "93.184.216.34")]


@pytest.mark.asyncio
async def test_schema_fetch_preserves_valid_tokenized_query_identity() -> None:
    tokenized_url = "https://example.com/video/?utfc=opaque%3D&variant=one"

    async def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == tokenized_url
        return httpx.Response(200, headers={"content-type": "text/html"}, content=b"<html />")

    result = await PublicSchemaFetcher(
        lambda _: _immediate(_public_address()),
        lambda _, __: httpx.MockTransport(handler),
    ).fetch(tokenized_url, 1.0)

    assert result.url == tokenized_url


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    (
        "http://example.com/",
        "https://example.com:444/",
        "https://user:pass@example.com/",
        "https://example.com/path#fragment",
        "https://example.com/?query=%",
        "https://example.com/?query=\x00",
        "https://127.0.0.1/",
    ),
)
async def test_schema_fetch_rejects_unsafe_urls_before_dns_or_network(url: str) -> None:
    fetcher = PublicSchemaFetcher(
        lambda _: pytest.fail("DNS must not be resolved"),
        lambda _, __: pytest.fail("network must not be contacted"),
    )
    with pytest.raises((SchemaFetchError, ValueError)):
        await fetcher.fetch(url, 1.0)


@pytest.mark.asyncio
async def test_schema_fetch_rejects_an_overlong_url_before_dns() -> None:
    fetcher = PublicSchemaFetcher(
        lambda _: pytest.fail("DNS must not be resolved"),
        lambda _, __: pytest.fail("network must not be contacted"),
    )
    with pytest.raises(InputLimitError):
        await fetcher.fetch(f"https://example.com/{'a' * 2_048}", 1.0)


@pytest.mark.asyncio
async def test_schema_fetch_rejects_a_normalized_url_without_a_hostname(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ParsedUrl:
        hostname = None

    fetcher = PublicSchemaFetcher(
        lambda _: pytest.fail("DNS must not be resolved"),
        lambda _, __: pytest.fail("network must not be contacted"),
    )

    def parse_url(_: str) -> ParsedUrl:
        return ParsedUrl()

    monkeypatch.setattr(schema_fetch, "urlparse", parse_url)
    with pytest.raises(SchemaFetchError, match="DNS hostname"):
        await fetcher.fetch("https://example.com/", 1.0)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "addresses",
    (
        (ipaddress.IPv4Address("127.0.0.1"),),
        (ipaddress.IPv4Address("10.0.0.1"),),
        (ipaddress.IPv6Address("::1"),),
        (ipaddress.IPv4Address("93.184.216.34"), ipaddress.IPv4Address("169.254.1.1")),
    ),
)
async def test_schema_fetch_rejects_non_public_dns_answers(
    addresses: tuple[ipaddress.IPv4Address | ipaddress.IPv6Address, ...],
) -> None:
    async def resolver(_: str) -> tuple[ipaddress.IPv4Address | ipaddress.IPv6Address, ...]:
        return addresses

    fetcher = PublicSchemaFetcher(resolver, lambda _, __: pytest.fail("network must not run"))
    with pytest.raises(SchemaFetchError):
        await fetcher.fetch("https://example.com/", 1.0)


def test_schema_fetch_address_validation_rejects_empty_and_mixed_answers() -> None:
    with pytest.raises(SchemaFetchError):
        require_public_addresses(())
    with pytest.raises(SchemaFetchError):
        require_public_addresses(
            (ipaddress.IPv4Address("93.184.216.34"), ipaddress.IPv4Address("10.0.0.1"))
        )


@pytest.mark.asyncio
async def test_schema_fetch_rejects_redirects_content_types_and_oversized_responses() -> None:
    responses = iter(
        (
            httpx.Response(302, headers={"location": "https://example.com/next"}),
            httpx.Response(200, headers={"content-type": "application/json"}, content=b"{}"),
            httpx.Response(
                200,
                headers={
                    "content-type": "text/html",
                    "content-length": str(MAX_SCHEMA_FETCH_RESPONSE_BYTES + 1),
                },
            ),
            httpx.Response(
                200,
                headers={"content-type": "text/html"},
                content=b"x" * (MAX_SCHEMA_FETCH_RESPONSE_BYTES + 1),
            ),
        )
    )

    async def handler(_: httpx.Request) -> httpx.Response:
        return next(responses)

    fetcher = PublicSchemaFetcher(
        lambda _: _immediate(_public_address()),
        lambda _, __: httpx.MockTransport(handler),
    )
    for _ in range(4):
        with pytest.raises(SchemaFetchError):
            await fetcher.fetch("https://example.com/", 1.0)


@pytest.mark.asyncio
async def test_schema_fetch_maps_transport_timeout_without_exposing_details() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("private upstream detail")

    fetcher = PublicSchemaFetcher(
        lambda _: _immediate(_public_address()),
        lambda _, __: httpx.MockTransport(handler),
    )
    with pytest.raises(SchemaFetchError) as error:
        await fetcher.fetch("https://example.com/", 1.0)
    assert "private" not in str(error.value)


@pytest.mark.asyncio
async def test_schema_fetch_maps_transport_failures_and_streamed_overflow() -> None:
    async def network_failure(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("private upstream detail")

    failed_fetcher = PublicSchemaFetcher(
        lambda _: _immediate(_public_address()),
        lambda _, __: httpx.MockTransport(network_failure),
    )
    with pytest.raises(SchemaFetchError) as failure:
        await failed_fetcher.fetch("https://example.com/", 1.0)
    assert "private" not in str(failure.value)

    class OversizedStream(httpx.AsyncByteStream):
        async def __aiter__(self):  # type: ignore[override]
            yield b"x" * (MAX_SCHEMA_FETCH_RESPONSE_BYTES + 1)

        async def aclose(self) -> None:
            return None

    async def oversized(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            stream=OversizedStream(),
        )

    oversized_fetcher = PublicSchemaFetcher(
        lambda _: _immediate(_public_address()),
        lambda _, __: httpx.MockTransport(oversized),
    )
    with pytest.raises(SchemaFetchError, match="allowed size"):
        await oversized_fetcher.fetch("https://example.com/", 1.0)


@pytest.mark.asyncio
async def test_pinned_backend_cannot_follow_dns_rebinding(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Backend:
        def __init__(self) -> None:
            self.calls: list[tuple[str, int]] = []

        async def connect_tcp(
            self,
            host: str,
            port: int,
            timeout: float | None = None,
            local_address: str | None = None,
            socket_options: object | None = None,
        ) -> httpcore.AsyncNetworkStream:
            del timeout, local_address, socket_options
            self.calls.append((host, port))
            return object()  # type: ignore[return-value]

        async def sleep(self, _: float) -> None:
            return None

    backend = _Backend()
    monkeypatch.setattr(
        "rankrat.providers.schema_fetch.httpcore.AnyIOBackend",
        lambda: backend,
    )
    pinned = _PinnedNetworkBackend("example.com", "93.184.216.34")
    await pinned.connect_tcp("example.com", 443)
    assert backend.calls == [("93.184.216.34", 443)]
    with pytest.raises(httpcore.ConnectError):
        await pinned.connect_tcp("metadata.internal", 443)
    assert backend.calls == [("93.184.216.34", 443)]


@pytest.mark.asyncio
async def test_resolve_public_host_rejects_private_dns_answers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Loop:
        async def getaddrinfo(self, *_: object, **__: object) -> list[tuple[object, ...]]:
            return [(0, 0, 0, "", ("127.0.0.1", 443))]

    monkeypatch.setattr("rankrat.providers.schema_fetch.asyncio.get_running_loop", lambda: _Loop())
    with pytest.raises(SchemaFetchError):
        await resolve_public_host("example.com")


@pytest.mark.asyncio
async def test_resolve_public_host_maps_dns_failures_and_invalid_records(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingLoop:
        async def getaddrinfo(self, *_: object, **__: object) -> list[tuple[object, ...]]:
            raise OSError("offline")

    monkeypatch.setattr(
        "rankrat.providers.schema_fetch.asyncio.get_running_loop",
        lambda: FailingLoop(),
    )
    with pytest.raises(SchemaFetchError, match="cannot be resolved"):
        await resolve_public_host("example.com")

    class InvalidLoop:
        async def getaddrinfo(self, *_: object, **__: object) -> list[tuple[object, ...]]:
            return [(0, 0, 0, "", ("not-an-address", 443))]

    monkeypatch.setattr(
        "rankrat.providers.schema_fetch.asyncio.get_running_loop",
        lambda: InvalidLoop(),
    )
    with pytest.raises(SchemaFetchError, match="invalid address"):
        await resolve_public_host("example.com")


@pytest.mark.asyncio
async def test_pinned_backend_rejects_unix_sockets_and_delegates_sleep(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Backend:
        slept = False

        async def connect_tcp(self, *_: object, **__: object) -> httpcore.AsyncNetworkStream:
            raise AssertionError("not used")

        async def sleep(self, _: float) -> None:
            self.slept = True

    backend = Backend()
    monkeypatch.setattr("rankrat.providers.schema_fetch.httpcore.AnyIOBackend", lambda: backend)
    pinned = _PinnedNetworkBackend("example.com", "93.184.216.34")
    with pytest.raises(httpcore.ConnectError, match="Unix"):
        await pinned.connect_unix_socket("socket")
    await pinned.sleep(0.01)
    assert backend.slept is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("upstream_error", "expected_error"),
    (
        (httpcore.ReadTimeout("timeout"), httpx.ReadTimeout),
        (httpcore.ReadError("offline"), httpx.ReadError),
    ),
)
async def test_httpx_response_stream_maps_core_errors_and_closes(
    upstream_error: httpcore.NetworkError,
    expected_error: type[httpx.HTTPError],
) -> None:
    class BrokenStream:
        closed = False

        def __aiter__(self) -> BrokenStream:
            return self

        async def __anext__(self) -> bytes:
            raise upstream_error

        async def aclose(self) -> None:
            self.closed = True

    stream = BrokenStream()
    response_stream = _HTTPXResponseStream(stream)
    with pytest.raises(expected_error):
        async for _ in response_stream:
            pass
    await response_stream.aclose()
    assert stream.closed is True


@pytest.mark.asyncio
async def test_httpx_response_stream_handles_success_and_streams_without_a_close_method() -> None:
    class CompleteStream:
        def __aiter__(self):
            return self

        async def __anext__(self) -> bytes:
            raise StopAsyncIteration

    assert [chunk async for chunk in _HTTPXResponseStream(CompleteStream())] == []


@pytest.mark.asyncio
async def test_pinned_transport_validates_request_stream_and_maps_core_errors() -> None:
    transport = _PinnedAsyncTransport("example.com", "93.184.216.34")
    request = httpx.Request("GET", "https://example.com/", content=_SyncStream())
    with pytest.raises(httpx.RequestError, match="stream"):
        await transport.handle_async_request(request)

    class FailingPool:
        async def handle_async_request(self, _: httpcore.Request) -> httpcore.Response:
            raise httpcore.ConnectError("offline")

        async def aclose(self) -> None:
            return None

    transport._pool = FailingPool()  # type: ignore[assignment]
    async_request = httpx.Request("GET", "https://example.com/", content=_AsyncStream())
    with pytest.raises(httpx.NetworkError, match="failed"):
        await transport.handle_async_request(async_request)
    await transport.aclose()

    class TimeoutPool:
        async def handle_async_request(self, _: httpcore.Request) -> httpcore.Response:
            raise httpcore.ReadTimeout("timeout")

        async def aclose(self) -> None:
            return None

    transport._pool = TimeoutPool()  # type: ignore[assignment]
    with pytest.raises(httpx.TimeoutException, match="timed out"):
        await transport.handle_async_request(async_request)


@pytest.mark.asyncio
async def test_pinned_transport_adapts_successful_core_response_and_factory() -> None:
    transport = _PinnedAsyncTransport("example.com", "93.184.216.34")

    class SuccessfulPool:
        async def handle_async_request(self, _: httpcore.Request) -> httpcore.Response:
            return httpcore.Response(200, headers=[(b"content-type", b"text/html")], content=b"ok")

        async def aclose(self) -> None:
            return None

    transport._pool = SuccessfulPool()  # type: ignore[assignment]
    response = await transport.handle_async_request(
        httpx.Request("GET", "https://example.com/", content=_AsyncStream())
    )
    assert response.status_code == 200
    assert await response.aread() == b"ok"
    await transport.aclose()
    assert isinstance(
        create_pinned_transport("example.com", "93.184.216.34"), httpx.AsyncBaseTransport
    )


class _AsyncStream(httpx.AsyncByteStream):
    async def __aiter__(self):  # type: ignore[override]
        if False:
            yield b""

    async def aclose(self) -> None:
        return None


class _SyncStream(httpx.SyncByteStream):
    def __iter__(self):  # type: ignore[override]
        if False:
            yield b""


async def _immediate(value: tuple[ipaddress.IPv4Address, ...]) -> tuple[ipaddress.IPv4Address, ...]:
    return value
