from __future__ import annotations

import ipaddress

import httpx
import pytest

from rankrat.constants import MAX_SCHEMA_FETCH_RESPONSE_BYTES
from rankrat.errors import InputLimitError, SiteFetchError
from rankrat.providers.site_fetch import PublicSiteFetcher


def _public_address() -> tuple[ipaddress.IPv4Address, ...]:
    return (ipaddress.IPv4Address("93.184.216.34"),)


async def _public_resolver(_: str) -> tuple[ipaddress.IPv4Address, ...]:
    return _public_address()


@pytest.mark.asyncio
async def test_site_fetch_pins_public_dns_and_returns_bounded_text() -> None:
    calls: list[tuple[str, str]] = []

    def transport_factory(hostname: str, address: str) -> httpx.AsyncBaseTransport:
        calls.append((hostname, address))
        return httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                headers={"content-type": "text/html; charset=utf-8"},
                content=b"<html />",
                request=request,
            )
        )

    result = await PublicSiteFetcher(_public_resolver, transport_factory).fetch(
        "https://EXAMPLE.com:443/path?utfc=opaque%3D",
        1.0,
    )

    assert result.url == "https://example.com/path?utfc=opaque%3D"
    assert result.content_type == "text/html"
    assert result.body == b"<html />"
    assert calls == [("example.com", "93.184.216.34")]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    (
        "http://example.com/",
        "https://127.0.0.1/",
        "https://example.com:444/",
        "https://user:pass@example.com/",
        "https://example.com/#fragment",
        "https://example.com/?query=%ZZ",
        "https://example.com/?query=value\rx",
    ),
)
async def test_site_fetch_rejects_unsafe_urls_before_network(url: str) -> None:
    fetcher = PublicSiteFetcher(
        lambda _: pytest.fail("DNS must not run"),
        lambda _, __: pytest.fail("network must not run"),
    )
    with pytest.raises((SiteFetchError, ValueError)):
        await fetcher.fetch(url, 1.0)


@pytest.mark.asyncio
async def test_site_fetch_rejects_private_or_mixed_dns_answers() -> None:
    async def private_resolver(
        _: str,
    ) -> tuple[ipaddress.IPv4Address, ipaddress.IPv4Address]:
        return (
            ipaddress.IPv4Address("93.184.216.34"),
            ipaddress.IPv4Address("10.0.0.1"),
        )

    fetcher = PublicSiteFetcher(
        private_resolver,
        lambda _, __: pytest.fail("network must not run"),
    )
    with pytest.raises(SiteFetchError, match="not publicly routable"):
        await fetcher.fetch("https://example.com/", 1.0)


@pytest.mark.asyncio
async def test_site_fetch_does_not_follow_redirects_or_read_binary_bodies() -> None:
    responses = iter(
        (
            httpx.Response(302, headers={"location": "https://outside.example/"}),
            httpx.Response(
                200,
                headers={"content-type": "application/octet-stream"},
                content=b"secret binary",
            ),
        )
    )
    fetcher = PublicSiteFetcher(
        _public_resolver,
        lambda _, __: httpx.MockTransport(lambda _: next(responses)),
    )

    redirected = await fetcher.fetch("https://example.com/", 1.0)
    binary = await fetcher.fetch("https://example.com/file", 1.0)

    assert redirected.status_code == 302
    assert redirected.body == b""
    assert binary.body == b""


@pytest.mark.asyncio
async def test_site_fetch_rejects_oversized_urls_and_bodies() -> None:
    fetcher = PublicSiteFetcher(
        _public_resolver,
        lambda _, __: httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                headers={
                    "content-type": "text/html",
                    "content-length": str(MAX_SCHEMA_FETCH_RESPONSE_BYTES + 1),
                },
            )
        ),
    )
    with pytest.raises(InputLimitError):
        await fetcher.fetch(f"https://example.com/{'x' * 2_048}", 1.0)
    with pytest.raises(SiteFetchError, match="allowed size"):
        await fetcher.fetch("https://example.com/", 1.0)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure", "message"),
    (
        (httpx.ReadTimeout("private detail"), "timed out"),
        (httpx.ConnectError("private detail"), "request failed"),
    ),
)
async def test_site_fetch_maps_transport_failures_without_detail(
    failure: httpx.HTTPError,
    message: str,
) -> None:
    def fail(_: httpx.Request) -> httpx.Response:
        raise failure

    fetcher = PublicSiteFetcher(
        _public_resolver,
        lambda _, __: httpx.MockTransport(fail),
    )
    with pytest.raises(SiteFetchError, match=message) as error:
        await fetcher.fetch("https://example.com/", 1.0)
    assert "private detail" not in str(error.value)
