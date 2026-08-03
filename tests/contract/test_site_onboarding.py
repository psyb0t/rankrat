from __future__ import annotations

import json

import httpx
import mcp.types as types
import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from rankrat.config import Settings
from rankrat.operator.site_onboarding import SiteOnboardingReceipt
from rankrat.services.site_onboarding import SiteOnboardingApprovalRequest
from rankrat.transports.http import create_http_app
from rankrat.transports.mcp import build_mcp_server
from rankrat.transports.runtime import ApplicationServices

_ADMIN_BEARER = "a" * 32
_REQUEST = {
    "google_account_id": "google-main",
    "bing_account_id": "bing-main",
    "site_url": "https://new.example.com/",
    "display_name": "New Example",
    "time_zone": "Etc/UTC",
    "currency_code": "USD",
}


@pytest.mark.asyncio
async def test_http_site_onboarding_requires_admin_approval_then_consumes_it_once(
    indexnow_deployment: tuple[Settings, ApplicationServices],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings, services = indexnow_deployment
    assert services.site_onboarding is not None
    calls: list[str] = []

    async def mock_onboard(*_: object) -> SiteOnboardingReceipt:
        calls.append("onboard")
        return SiteOnboardingReceipt(
            site_url="https://new.example.com/",
            ga4_property_id="456",
            ga4_measurement_id="G-ABC123",
            google_search_console_added=True,
            bing_added=True,
            boundary_updated=True,
        )

    monkeypatch.setattr(services.site_onboarding._operator, "onboard", mock_onboard)
    app = create_http_app(settings.model_copy(update={"enable_openapi": True}), services)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://rankrat.test",
    ) as client:
        openapi = await client.get("/openapi.json")
        assert openapi.status_code == 200
        assert "/v1/admin/site-onboarding-approvals" in openapi.json()["paths"]
        assert "/v1/site-onboarding-submissions" in openapi.json()["paths"]
        unauthorized = await client.post(
            "/v1/admin/site-onboarding-approvals",
            json=_REQUEST,
        )
        assert unauthorized.status_code == 401
        approval = await client.post(
            "/v1/admin/site-onboarding-approvals",
            json=_REQUEST,
            headers={"authorization": f"Bearer {_ADMIN_BEARER}"},
        )
        assert approval.status_code == 200
        approval_id = approval.json()["approval_id"]
        malformed = await client.post(
            "/v1/site-onboarding-submissions",
            json={**_REQUEST, "approval_id": approval_id, "unexpected": True},
        )
        assert malformed.status_code == 422
        submission = await client.post(
            "/v1/site-onboarding-submissions",
            json={**_REQUEST, "approval_id": approval_id},
        )
        assert submission.status_code == 200
        assert submission.json() == {
            "site_url": "https://new.example.com/",
            "ga4_property_id": "456",
            "ga4_measurement_id": "G-ABC123",
            "google_search_console_added": True,
            "bing_added": True,
            "boundary_updated": True,
        }
        replay = await client.post(
            "/v1/site-onboarding-submissions",
            json={**_REQUEST, "approval_id": approval_id},
        )
        assert replay.status_code == 400
        assert replay.json()["code"] == "REQUEST_REJECTED"
    assert calls == ["onboard"]


@pytest.mark.asyncio
async def test_mcp_site_onboarding_consumes_admin_minted_exact_approval(
    indexnow_deployment: tuple[Settings, ApplicationServices],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, services = indexnow_deployment
    assert services.site_onboarding is not None

    async def mock_onboard(*_: object) -> SiteOnboardingReceipt:
        return SiteOnboardingReceipt(
            site_url="https://new.example.com/",
            ga4_property_id="456",
            ga4_measurement_id="G-ABC123",
            google_search_console_added=True,
            bing_added=True,
            boundary_updated=True,
        )

    monkeypatch.setattr(services.site_onboarding._operator, "onboard", mock_onboard)
    approval = await services.site_onboarding.approve(SiteOnboardingApprovalRequest(**_REQUEST))
    server = build_mcp_server(services)
    async with create_connected_server_and_client_session(server) as client:
        tools = await client.list_tools()
        onboarding = next(tool for tool in tools.tools if tool.name == "site_onboarding_submit")
        assert onboarding.annotations is not None
        assert onboarding.annotations.readOnlyHint is False
        assert onboarding.annotations.destructiveHint is True
        assert onboarding.inputSchema["required"] == [
            "google_account_id",
            "bing_account_id",
            "site_url",
            "approval_id",
        ]
        response = await client.call_tool(
            "site_onboarding_submit",
            {**_REQUEST, "approval_id": approval.approval_id},
        )
        assert response.isError is False
        content = response.content[0]
        assert isinstance(content, types.TextContent)
        assert json.loads(content.text)["ga4_property_id"] == "456"
        missing = await client.call_tool("site_onboarding_approve", _REQUEST)
        assert missing.isError is True
        missing_content = missing.content[0]
        assert isinstance(missing_content, types.TextContent)
        assert json.loads(missing_content.text)["code"] == "TOOL_NOT_FOUND"
