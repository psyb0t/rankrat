from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import cast

import httpx
import pytest

from rankrat.constants import MAX_BACKLINK_PROVIDER_REQUESTS
from rankrat.errors import BoundaryDeniedError, InputLimitError
from rankrat.models.boundaries import BoundaryDocument, Provider
from rankrat.policy.boundaries import BoundaryPolicy
from rankrat.providers.backlinks import (
    AhrefsBacklinkClient,
    BingBacklinkClient,
    DataForSeoBacklinkClient,
    MajesticBacklinkClient,
    MozBacklinkClient,
    SemrushBacklinkClient,
    _BaseBacklinkClient,
    _record,
)
from rankrat.providers.base import (
    AccountId,
    ProviderFailureCode,
    ProviderOperationError,
    ProviderReadRequest,
)
from rankrat.providers.bing import BingLinkDetail, BingUrlLinks, BingWebmasterClient

_TARGET = "https://example.com/article"


def _policy(tmp_path: Path, provider: Provider, credential: str) -> BoundaryPolicy:
    credential_file = tmp_path / f"{provider.value}-credential"
    credential_file.write_text(credential, encoding="ascii")
    return BoundaryPolicy(
        BoundaryDocument.model_validate(
            {
                "accounts": [
                    {
                        "id": f"{provider.value}-main",
                        "provider": provider.value,
                        "credential": str(credential_file),
                        "backlink_targets": [_TARGET],
                    }
                ]
            }
        )
    )


def _request(provider: Provider) -> ProviderReadRequest:
    return ProviderReadRequest(AccountId(f"{provider.value}-main"), 1.0)


@pytest.mark.asyncio
async def test_ahrefs_adapter_uses_fixed_origin_and_normalizes_links(tmp_path: Path) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.ahrefs.com"
        assert request.headers["Authorization"] == "Bearer ahrefs-token"
        assert request.url.params["target"] == _TARGET
        assert "offset" not in request.url.params
        return httpx.Response(
            200,
            json={
                "backlinks": [
                    {
                        "url_from": "https://source.example/page",
                        "url_to": _TARGET,
                        "anchor": "reference",
                        "is_dofollow": True,
                        "domain_rating_source": 42.0,
                    }
                ]
            },
        )

    client = AhrefsBacklinkClient(
        _policy(tmp_path, Provider.AHREFS, "ahrefs-token"),
        lambda: httpx.MockTransport(handler),
    )
    result = await client.links(_request(Provider.AHREFS), _TARGET, 10, 0)
    assert result.provider is Provider.AHREFS
    assert result.links[0].source_domain == "source.example"
    readiness = await client.readiness(_request(Provider.AHREFS))
    assert readiness.available is True
    assert readiness.provider is Provider.AHREFS
    with pytest.raises(InputLimitError, match="pagination"):
        await client.links(_request(Provider.AHREFS), _TARGET, 10, 1)


@pytest.mark.asyncio
async def test_majestic_adapter_maps_trust_flow_and_pagination(tmp_path: Path) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.majestic.com"
        assert request.url.params["cmd"] == "GetBackLinkData"
        assert request.url.params["From"] == "5"
        return httpx.Response(
            200,
            json={
                "Code": "OK",
                "DataTables": {
                    "BackLinks": {
                        "Data": [
                            {
                                "SourceURL": "https://source.example/a",
                                "TargetURL": _TARGET,
                                "AnchorText": "a",
                                "SourceTrustFlow": 20.0,
                                "FlagNoFollow": True,
                            }
                        ]
                    }
                },
            },
        )

    client = MajesticBacklinkClient(
        _policy(tmp_path, Provider.MAJESTIC, "majestic-token"),
        lambda: httpx.MockTransport(handler),
    )
    result = await client.links(_request(Provider.MAJESTIC), _TARGET, 1, 5)
    assert result.links[0].authority == 20.0
    assert result.links[0].follow is False
    assert result.has_more is True


@pytest.mark.asyncio
async def test_moz_adapter_walks_cursor_to_implement_offset(tmp_path: Path) -> None:
    requests: list[dict[str, object]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        expected = "Basic " + base64.b64encode(b"access:secret").decode()
        assert request.headers["Authorization"] == expected
        body = cast(dict[str, object], json.loads(request.content))
        requests.append(body)
        start = 0 if "next_token" not in body else 2
        rows = [
            {
                "source": {
                    "page": f"https://source.example/{index}",
                    "domain_authority": 30,
                },
                "target": {"page": _TARGET},
                "anchor_text": str(index),
            }
            for index in range(start, start + 2)
        ]
        return httpx.Response(
            200,
            json={"results": rows, "next_token": "next" if start == 0 else None},
        )

    client = MozBacklinkClient(
        _policy(tmp_path, Provider.MOZ, "access:secret"),
        lambda: httpx.MockTransport(handler),
    )
    result = await client.links(_request(Provider.MOZ), _TARGET, 2, 1)
    assert [link.anchor for link in result.links] == ["1", "2"]
    assert len(requests) == 2


@pytest.mark.asyncio
async def test_semrush_adapter_uses_api_key_header_and_total(tmp_path: Path) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Apikey semrush-token"
        assert request.url.params["offset"] == "3"
        return httpx.Response(
            200,
            json={
                "meta": {"success": True, "total": 5},
                "data": [
                    {
                        "source_url": "https://source.example/a",
                        "target_url": _TARGET,
                        "anchor": "a",
                    }
                ],
            },
        )

    client = SemrushBacklinkClient(
        _policy(tmp_path, Provider.SEMRUSH, "semrush-token"),
        lambda: httpx.MockTransport(handler),
    )
    result = await client.links(_request(Provider.SEMRUSH), _TARGET, 1, 3)
    assert result.has_more is True


@pytest.mark.asyncio
async def test_dataforseo_adapter_uses_basic_auth_and_task_envelope(tmp_path: Path) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        expected = "Basic " + base64.b64encode(b"login:password").decode()
        assert request.headers["Authorization"] == expected
        return httpx.Response(
            200,
            json={
                "status_code": 20000,
                "tasks": [
                    {
                        "status_code": 20000,
                        "result": [
                            {
                                "total_count": 1,
                                "items": [
                                    {
                                        "url_from": "https://source.example/a",
                                        "url_to": _TARGET,
                                        "anchor": "a",
                                    }
                                ],
                            }
                        ],
                    }
                ],
            },
        )

    client = DataForSeoBacklinkClient(
        _policy(tmp_path, Provider.DATAFORSEO, "login:password"),
        lambda: httpx.MockTransport(handler),
    )
    result = await client.links(_request(Provider.DATAFORSEO), _TARGET, 1, 0)
    assert len(result.links) == 1


class _BingClientFake:
    def __init__(self, total_pages: int = 3) -> None:
        self.pages: list[int] = []
        self.total_pages = total_pages

    async def read_url_links(
        self,
        _: ProviderReadRequest,
        site_url: str,
        target_url: str,
        page: int,
    ) -> BingUrlLinks:
        self.pages.append(page)
        assert site_url == "https://example.com/"
        assert target_url == _TARGET
        return BingUrlLinks(
            (BingLinkDetail(f"https://source.example/{page}", str(page)),),
            self.total_pages,
        )


@pytest.mark.asyncio
async def test_bing_adapter_walks_provider_pages_for_shared_offset() -> None:
    bing = _BingClientFake()
    client = BingBacklinkClient(cast(BingWebmasterClient, bing))
    result = await client.links(
        ProviderReadRequest(AccountId("bing-main"), 1.0),
        _TARGET,
        1,
        1,
        "https://example.com/",
    )
    assert [link.anchor for link in result.links] == ["1"]
    assert result.has_more is True
    assert bing.pages == [0, 1]


@pytest.mark.asyncio
async def test_bing_adapter_enforces_provider_page_budget() -> None:
    bing = _BingClientFake(total_pages=1_000)
    client = BingBacklinkClient(cast(BingWebmasterClient, bing))
    with pytest.raises(InputLimitError, match="request budget"):
        await client.links(
            ProviderReadRequest(AccountId("bing-main"), 1.0),
            _TARGET,
            1,
            MAX_BACKLINK_PROVIDER_REQUESTS,
            "https://example.com/",
        )
    assert len(bing.pages) == MAX_BACKLINK_PROVIDER_REQUESTS


@pytest.mark.asyncio
async def test_moz_adapter_rejects_pagination_beyond_request_budget(
    tmp_path: Path,
) -> None:
    requests = 0

    async def handler(_: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(200, json={"results": [], "next_token": None})

    client = MozBacklinkClient(
        _policy(tmp_path, Provider.MOZ, "access:secret"),
        lambda: httpx.MockTransport(handler),
    )
    with pytest.raises(InputLimitError, match="request budget"):
        await client.links(
            _request(Provider.MOZ),
            _TARGET,
            1,
            MAX_BACKLINK_PROVIDER_REQUESTS * 50,
        )
    assert requests == 0


@pytest.mark.asyncio
async def test_adapters_reject_cross_boundary_and_malformed_provider_data(
    tmp_path: Path,
) -> None:
    client = AhrefsBacklinkClient(
        _policy(tmp_path, Provider.AHREFS, "ahrefs-token"),
        lambda: httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json={"backlinks": [{"url_from": "file:///etc/passwd", "url_to": _TARGET}]},
            )
        ),
    )
    with pytest.raises(BoundaryDeniedError):
        await client.links(
            _request(Provider.AHREFS),
            "https://other.example/article",
            1,
            0,
        )
    with pytest.raises(ProviderOperationError) as error:
        await client.links(_request(Provider.AHREFS), _TARGET, 1, 0)
    assert error.value.code is ProviderFailureCode.INVALID_RESPONSE


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (httpx.Response(401), ProviderFailureCode.AUTHENTICATION),
        (httpx.Response(403), ProviderFailureCode.FORBIDDEN),
        (httpx.Response(429), ProviderFailureCode.RATE_LIMITED),
        (httpx.Response(500), ProviderFailureCode.UNAVAILABLE),
        (httpx.Response(400), ProviderFailureCode.INVALID_RESPONSE),
        (
            httpx.Response(302, headers={"location": "https://example.invalid"}),
            ProviderFailureCode.INVALID_RESPONSE,
        ),
    ],
)
def test_backlink_status_mapping(
    response: httpx.Response,
    expected: ProviderFailureCode,
) -> None:
    with pytest.raises(ProviderOperationError) as raised:
        _BaseBacklinkClient._raise_for_status(response)
    assert raised.value.code is expected


@pytest.mark.parametrize("content", [b"bad token", b"\xff", b"x" * 10_000])
def test_backlink_credentials_are_strict(tmp_path: Path, content: bytes) -> None:
    credential = tmp_path / "credential"
    credential.write_bytes(content)
    with pytest.raises(ProviderOperationError) as raised:
        _BaseBacklinkClient._load_credential(credential)
    assert raised.value.code is ProviderFailureCode.AUTHENTICATION


def test_backlink_credentials_reject_symlinks(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.write_text("valid-token", encoding="ascii")
    credential = tmp_path / "credential"
    credential.symlink_to(target)
    with pytest.raises(ProviderOperationError):
        _BaseBacklinkClient._load_credential(credential)


@pytest.mark.parametrize(
    ("source", "anchor", "authority"),
    [
        ("file:///tmp/source", "ok", 1.0),
        ("https://source.example/", "x" * 2_049, 1.0),
        ("https://source.example/", "ok", float("nan")),
        ("https://source.example/", "ok", -1.0),
        ("https://source.example/" + "x" * 3_000, "ok", 1.0),
    ],
)
def test_backlink_records_reject_invalid_provider_fields(
    source: str,
    anchor: str,
    authority: float,
) -> None:
    with pytest.raises(ProviderOperationError) as raised:
        _record(source, _TARGET, anchor, True, authority, None, None)
    assert raised.value.code is ProviderFailureCode.INVALID_RESPONSE


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (httpx.ReadTimeout("slow"), ProviderFailureCode.TIMEOUT),
        (httpx.ConnectError("offline"), ProviderFailureCode.UNAVAILABLE),
    ],
)
async def test_backlink_transport_failures_are_bounded(
    tmp_path: Path,
    failure: httpx.HTTPError,
    expected: ProviderFailureCode,
) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        raise failure

    client = AhrefsBacklinkClient(
        _policy(tmp_path, Provider.AHREFS, "ahrefs-token"),
        lambda: httpx.MockTransport(handler),
    )
    with pytest.raises(ProviderOperationError) as raised:
        await client.links(_request(Provider.AHREFS), _TARGET, 1, 0)
    assert raised.value.code is expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("client_type", "provider"),
    [
        (MozBacklinkClient, Provider.MOZ),
        (DataForSeoBacklinkClient, Provider.DATAFORSEO),
    ],
)
async def test_colon_credentials_require_both_parts(
    tmp_path: Path,
    client_type: type[MozBacklinkClient] | type[DataForSeoBacklinkClient],
    provider: Provider,
) -> None:
    client = client_type(
        _policy(tmp_path, provider, "token-without-colon"),
        lambda: pytest.fail("network must not be reached"),
    )
    with pytest.raises(ProviderOperationError) as raised:
        await client.links(_request(provider), _TARGET, 1, 0)
    assert raised.value.code is ProviderFailureCode.AUTHENTICATION


@pytest.mark.asyncio
async def test_bing_backlinks_require_site_url() -> None:
    client = BingBacklinkClient(cast(BingWebmasterClient, _BingClientFake()))
    with pytest.raises(InputLimitError, match="site_url"):
        await client.links(
            ProviderReadRequest(AccountId("bing-main"), 1.0),
            _TARGET,
            1,
            0,
        )
