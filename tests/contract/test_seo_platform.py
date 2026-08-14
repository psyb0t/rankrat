from __future__ import annotations

import json
from typing import Protocol, cast

import httpx
import pytest
from fastapi import FastAPI
from mcp.shared.memory import create_connected_server_and_client_session

from rankrat.config import Settings
from rankrat.operator.site_ownership import (
    SiteOwnershipProviderStatus,
    SiteOwnershipReceipt,
)
from rankrat.services.bing import (
    BingBacklink,
    BingBacklinkIntelligenceReport,
    BingBacklinkTargetReport,
)
from rankrat.services.site_audit import SiteAuditReport
from rankrat.services.site_ownership import (
    SiteOwnershipCheckRequest,
    SiteOwnershipVerificationRequest,
)
from rankrat.services.site_remediation import SiteRemediationReceipt
from rankrat.transports.http import create_http_app
from rankrat.transports.mcp import build_mcp_server
from rankrat.transports.runtime import ApplicationServices


class _WrappedApp(Protocol):
    _app: object


def _unwrap_fastapi(app: object) -> FastAPI:
    current = app
    while not isinstance(current, FastAPI):
        current = cast(_WrappedApp, current)._app
    return current


def _audit_report() -> SiteAuditReport:
    return SiteAuditReport("https://example.com/", 100, (), (), (), False)


def _ownership_receipt() -> SiteOwnershipReceipt:
    complete = SiteOwnershipProviderStatus(False, True, True)
    return SiteOwnershipReceipt(
        site_url="https://example.com/",
        domain="example.com",
        google=complete,
        bing=complete,
        complete=True,
    )


def _backlink_report() -> BingBacklinkIntelligenceReport:
    backlink = BingBacklink(
        source_url="https://source.example/article",
        source_domain="source.example",
        anchor_text="Example",
    )
    target = BingBacklinkTargetReport(
        target_url="https://example.com/article",
        backlinks=(backlink,),
        referring_domains=("source.example",),
        anchors=(),
        provider_total_pages=1,
        pages_read=1,
        truncated=False,
    )
    return BingBacklinkIntelligenceReport((target,))


def _patch_read_services(
    services: ApplicationServices,
    monkeypatch: pytest.MonkeyPatch,
) -> list[SiteOwnershipCheckRequest]:
    ownership_requests: list[SiteOwnershipCheckRequest] = []

    async def audit(*_: object) -> SiteAuditReport:
        return _audit_report()

    async def ownership(request: SiteOwnershipCheckRequest) -> SiteOwnershipReceipt:
        ownership_requests.append(request)
        return _ownership_receipt()

    async def backlinks(*_: object) -> BingBacklinkIntelligenceReport:
        return _backlink_report()

    assert services.site_audit is not None
    assert services.site_ownership is not None
    monkeypatch.setattr(services.site_audit, "audit", audit)
    monkeypatch.setattr(services.site_ownership, "check", ownership)
    monkeypatch.setattr(services.bing_webmaster, "backlink_intelligence", backlinks)
    return ownership_requests


@pytest.mark.asyncio
async def test_seo_read_operations_have_rest_and_stdio_mcp_parity(
    deployment: tuple[Settings, ApplicationServices],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings, services = deployment
    ownership_requests = _patch_read_services(services, monkeypatch)
    app = create_http_app(settings, services)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://rankrat.test",
    ) as client:
        audit = await client.post(
            "/v1/site-audits",
            json={"account_id": "google-main", "site_url": "https://example.com/"},
        )
        ownership = await client.post(
            "/v1/site-ownership-checks",
            json={
                "google_account_id": "google-main",
                "bing_account_id": "bing-main",
                "site_url": "https://example.com/",
            },
        )
        bing_only_ownership = await client.post(
            "/v1/site-ownership-checks",
            json={
                "bing_account_id": "bing-main",
                "site_url": "https://example.com/",
            },
        )
        backlinks = await client.post(
            "/v1/bing/backlink-intelligence",
            json={
                "account_id": "bing-main",
                "site_url": "https://example.com/",
                "target_urls": ["https://example.com/article"],
            },
        )
        assert audit.json()["score"] == 100
        assert ownership.json()["complete"] is True
        assert bing_only_ownership.json()["complete"] is True
        assert backlinks.json()["targets"][0]["referring_domains"] == ["source.example"]
        legacy_ownership = await client.post(
            "/v1/site-ownership-checks",
            json={
                "google_account_id": "google-main",
                "bing_account_id": "bing-main",
                "cloudflare_account_id": "cloudflare-main",
                "site_url": "https://example.com/",
            },
        )
        assert legacy_ownership.status_code == 422
        assert (
            await client.post(
                "/v1/site-ownership-checks",
                json={"site_url": "https://example.com/"},
            )
        ).status_code == 422
        assert (await client.post("/v1/site-ownership-verifications", json={})).status_code == 404
        assert (await client.post("/v1/site-remediations", json={})).status_code == 404

    server = build_mcp_server(services)
    async with create_connected_server_and_client_session(server) as client:
        catalog = {tool.name for tool in (await client.list_tools()).tools}
        assert {"site_audit", "site_ownership_check", "bing_backlink_intelligence"} <= catalog
        assert "site_ownership_verify" not in catalog
        assert {"site_ownership_status", "site_ownership_apply"}.isdisjoint(catalog)
        assert "site_remediation_apply" not in catalog
        audit = await client.call_tool(
            "site_audit",
            {"account_id": "google-main", "site_url": "https://example.com/"},
        )
        ownership = await client.call_tool(
            "site_ownership_check",
            {
                "google_account_id": "google-main",
                "bing_account_id": "bing-main",
                "site_url": "https://example.com/",
            },
        )
        bing_only_ownership = await client.call_tool(
            "site_ownership_check",
            {
                "bing_account_id": "bing-main",
                "site_url": "https://example.com/",
            },
        )
        missing_provider = await client.call_tool(
            "site_ownership_check",
            {"site_url": "https://example.com/"},
        )
        assert json.loads(audit.content[0].text)["score"] == 100  # type: ignore[union-attr]
        assert json.loads(ownership.content[0].text)["complete"] is True  # type: ignore[union-attr]
        assert json.loads(bing_only_ownership.content[0].text)["complete"] is True  # type: ignore[union-attr]
        assert missing_provider.isError is True

    assert ownership_requests[1].google_account_id is None
    assert ownership_requests[1].bing_account_id == "bing-main"
    assert ownership_requests[3].google_account_id is None
    assert ownership_requests[3].bing_account_id == "bing-main"


@pytest.mark.asyncio
async def test_seo_write_operations_have_rest_and_stdio_mcp_parity(
    indexnow_deployment: tuple[Settings, ApplicationServices],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings, services = indexnow_deployment
    assert services.site_ownership is not None
    assert services.site_remediation is not None

    ownership_requests: list[SiteOwnershipVerificationRequest] = []

    async def ownership(request: SiteOwnershipVerificationRequest) -> SiteOwnershipReceipt:
        ownership_requests.append(request)
        return _ownership_receipt()

    async def remediation(*_: object) -> SiteRemediationReceipt:
        return SiteRemediationReceipt(True, True, 1)

    monkeypatch.setattr(services.site_ownership, "verify", ownership)
    monkeypatch.setattr(services.site_remediation, "apply", remediation)
    ownership_arguments = {
        "google_account_id": "google-main",
        "bing_account_id": "bing-main",
        "dns_account_id": "cloudflare-main",
        "site_url": "https://example.com/",
    }
    remediation_arguments = {
        "google_account_id": "google-main",
        "google_site_url": "sc-domain:example.com",
        "bing_account_id": "bing-main",
        "bing_site_url": "https://example.com/",
        "sitemap_url": "https://example.com/sitemap.xml",
        "changed_urls": ["https://example.com/article"],
    }
    app = create_http_app(settings, services)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://rankrat.test",
    ) as client:
        ownership_response = await client.post(
            "/v1/site-ownership-verifications",
            json=ownership_arguments,
        )
        bing_only_ownership_response = await client.post(
            "/v1/site-ownership-verifications",
            json={
                "bing_account_id": "bing-main",
                "dns_account_id": "cloudflare-main",
                "site_url": "https://example.com/",
            },
        )
        remediation_response = await client.post(
            "/v1/site-remediations",
            json=remediation_arguments,
        )
        assert ownership_response.json()["complete"] is True
        assert bing_only_ownership_response.json()["complete"] is True
        assert remediation_response.json()["bing_urls_submitted"] == 1
        legacy_ownership = await client.post(
            "/v1/site-ownership-verifications",
            json={
                "google_account_id": "google-main",
                "bing_account_id": "bing-main",
                "cloudflare_account_id": "cloudflare-main",
                "site_url": "https://example.com/",
            },
        )
        assert legacy_ownership.status_code == 422
        assert (
            await client.post(
                "/v1/site-ownership-verifications",
                json={
                    "dns_account_id": "cloudflare-main",
                    "site_url": "https://example.com/",
                },
            )
        ).status_code == 422

    server = build_mcp_server(services)
    async with create_connected_server_and_client_session(server) as client:
        catalog = {tool.name for tool in (await client.list_tools()).tools}
        assert {"site_ownership_verify", "site_remediation_apply"} <= catalog
        assert {"site_ownership_status", "site_ownership_apply"}.isdisjoint(catalog)
        ownership_result = await client.call_tool("site_ownership_verify", ownership_arguments)
        bing_only_ownership_result = await client.call_tool(
            "site_ownership_verify",
            {
                "bing_account_id": "bing-main",
                "dns_account_id": "cloudflare-main",
                "site_url": "https://example.com/",
            },
        )
        missing_provider = await client.call_tool(
            "site_ownership_verify",
            {
                "dns_account_id": "cloudflare-main",
                "site_url": "https://example.com/",
            },
        )
        remediation_result = await client.call_tool(
            "site_remediation_apply",
            remediation_arguments,
        )
        assert json.loads(ownership_result.content[0].text)["complete"] is True  # type: ignore[union-attr]
        assert json.loads(bing_only_ownership_result.content[0].text)["complete"] is True  # type: ignore[union-attr]
        assert missing_provider.isError is True
        assert json.loads(remediation_result.content[0].text)["bing_urls_submitted"] == 1  # type: ignore[union-attr]

    assert ownership_requests[1].google_account_id is None
    assert ownership_requests[1].bing_account_id == "bing-main"
    assert ownership_requests[3].google_account_id is None
    assert ownership_requests[3].bing_account_id == "bing-main"


@pytest.mark.asyncio
async def test_site_audit_is_callable_over_streamable_http_mcp(
    deployment: tuple[Settings, ApplicationServices],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings, services = deployment
    _patch_read_services(services, monkeypatch)
    app = create_http_app(settings, services)
    fastapi_app = _unwrap_fastapi(app)
    headers = {
        "accept": "application/json, text/event-stream",
        "content-type": "application/json",
    }
    initialize_request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "rankrat-contract", "version": "0"},
        },
    }
    tool_request = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {
            "name": "site_audit",
            "arguments": {
                "account_id": "google-main",
                "site_url": "https://example.com/",
            },
        },
    }
    catalog_request: dict[str, object] = {
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/list",
        "params": {},
    }
    async with (
        fastapi_app.router.lifespan_context(fastapi_app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://rankrat.test",
        ) as client,
    ):
        initialized = await client.post("/mcp/", headers=headers, json=initialize_request)
        called = await client.post("/mcp/", headers=headers, json=tool_request)
        catalog_response = await client.post("/mcp/", headers=headers, json=catalog_request)

    assert initialized.status_code == 200
    assert called.status_code == 200
    assert catalog_response.status_code == 200
    content = called.json()["result"]["content"][0]
    assert json.loads(content["text"])["score"] == 100
    catalog = {tool["name"] for tool in catalog_response.json()["result"]["tools"]}
    assert "site_ownership_check" in catalog
    assert "site_ownership_verify" not in catalog
    assert {"site_ownership_status", "site_ownership_apply"}.isdisjoint(catalog)


@pytest.mark.asyncio
async def test_seo_transports_reject_unknown_fields(
    deployment: tuple[Settings, ApplicationServices],
) -> None:
    settings, services = deployment
    app = create_http_app(settings, services)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://rankrat.test",
    ) as client:
        response = await client.post(
            "/v1/site-audits",
            json={
                "account_id": "google-main",
                "site_url": "https://example.com/",
                "unexpected": True,
            },
        )
    assert response.status_code == 422

    server = build_mcp_server(services)
    async with create_connected_server_and_client_session(server) as client:
        result = await client.call_tool(
            "site_audit",
            {
                "account_id": "google-main",
                "site_url": "https://example.com/",
                "unexpected": True,
            },
        )

    assert result.isError is True
