from __future__ import annotations

from typing import cast

import pytest

from rankrat.errors import InputLimitError
from rankrat.models.boundaries import DnsZone
from rankrat.providers.cloudflare import CloudflareDnsClient
from rankrat.providers.cloudflare_performance import (
    CloudflareEdgeRedirect,
    CloudflareEdgeRedirectReceipt,
    CloudflarePerformanceClient,
    CloudflareRedirectStatus,
)
from rankrat.services.edge_redirects import (
    EdgeRedirectDeleteRequest,
    EdgeRedirectListRequest,
    EdgeRedirectService,
    EdgeRedirectUpsertRequest,
)

_ZONE_ID = "a" * 32
_RULE_ID = "b" * 32


class _DnsClient:
    async def resolve_zone(self, _: object, hostname: str) -> DnsZone:
        assert hostname == "www.example.com"
        return DnsZone(provider_zone_id=_ZONE_ID, name="example.com")


class _PerformanceClient:
    def __init__(self) -> None:
        self.upserts: list[tuple[object, ...]] = []
        self.deletions: list[tuple[object, ...]] = []

    async def list_edge_redirects(
        self, _: object, zone_id: str
    ) -> tuple[CloudflareEdgeRedirect, ...]:
        assert zone_id == _ZONE_ID
        return (
            CloudflareEdgeRedirect(
                _ZONE_ID,
                _RULE_ID,
                "/old",
                "https://target.example/new",
                CloudflareRedirectStatus.MOVED_PERMANENTLY,
                True,
            ),
        )

    async def upsert_edge_redirect(self, *arguments: object) -> CloudflareEdgeRedirectReceipt:
        self.upserts.append(arguments)
        return CloudflareEdgeRedirectReceipt(
            CloudflareEdgeRedirect(
                _ZONE_ID,
                _RULE_ID,
                "/old",
                "https://target.example/new",
                CloudflareRedirectStatus.FOUND,
                False,
            ),
            True,
            True,
        )

    async def delete_edge_redirect(self, *arguments: object) -> None:
        self.deletions.append(arguments)


@pytest.mark.asyncio
async def test_edge_redirect_service_resolves_source_zone_and_allows_cross_site_https_target() -> (
    None
):
    performance = _PerformanceClient()
    service = EdgeRedirectService(
        cast(CloudflareDnsClient, _DnsClient()),
        cast(CloudflarePerformanceClient, performance),
    )
    request = EdgeRedirectUpsertRequest(
        account_id="cloudflare-main",
        site_url="https://www.example.com/",
        source_path="/old",
        target_url="https://target.example/new",
        status_code=CloudflareRedirectStatus.FOUND,
        preserve_query_string=False,
    )

    receipt = await service.upsert(request)
    assert receipt.redirect.target_url == "https://target.example/new"
    assert performance.upserts[0][1:] == (
        _ZONE_ID,
        "/old",
        "https://target.example/new",
        CloudflareRedirectStatus.FOUND,
        False,
    )
    assert (
        await service.list(EdgeRedirectListRequest("cloudflare-main", "https://www.example.com/"))
    )[0].rule_id == _RULE_ID
    await service.delete(
        EdgeRedirectDeleteRequest("cloudflare-main", "https://www.example.com/", rule_id=_RULE_ID)
    )
    assert performance.deletions[0][1:] == (_ZONE_ID, _RULE_ID)


@pytest.mark.parametrize(
    ("source_path", "target_url"),
    (
        ("old", "https://target.example/new"),
        ('/old"', "https://target.example/new"),
        ("/old", "http://target.example/new"),
        ("/old", "https://target.example/new?query=value"),
    ),
)
def test_edge_redirect_request_rejects_unsafe_path_or_target(
    source_path: str,
    target_url: str,
) -> None:
    with pytest.raises((InputLimitError, ValueError)):
        EdgeRedirectUpsertRequest(
            account_id="cloudflare-main",
            site_url="https://www.example.com/",
            source_path=source_path,
            target_url=target_url,
        )
