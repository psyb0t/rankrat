from __future__ import annotations

import json

import httpx
import mcp.types as types
import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from rankrat.config import Settings
from rankrat.operator.site_onboarding import SiteOnboardingReceipt
from rankrat.transports.http import create_http_app
from rankrat.transports.mcp import build_mcp_server
from rankrat.transports.runtime import ApplicationServices

_REQUEST = {
    "google_account_id": "google-main",
    "bing_account_id": "bing-main",
    "site_url": "https://new.example.com/",
    "google_analytics_parent_account_id": "123",
    "display_name": "New Example",
    "time_zone": "Etc/UTC",
    "currency_code": "USD",
}


def _receipt() -> SiteOnboardingReceipt:
    return SiteOnboardingReceipt(
        site_url="https://new.example.com/",
        ga4_property_id="456",
        ga4_measurement_id="G-ABC123",
        google_search_console_added=True,
        bing_added=True,
        boundary_updated=True,
    )


@pytest.mark.asyncio
async def test_read_only_runtime_does_not_publish_site_onboarding_to_http_or_mcp(
    deployment: tuple[Settings, ApplicationServices],
) -> None:
    settings, services = deployment
    assert services.writes_enabled is False
    app = create_http_app(settings.model_copy(update={"enable_openapi": True}), services)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://rankrat.test",
    ) as client:
        assert (
            await client.post("/v1/site-onboarding-submissions", json=_REQUEST)
        ).status_code == 404
        assert (
            "/v1/site-onboarding-submissions"
            not in (await client.get("/openapi.json")).json()["paths"]
        )
    server = build_mcp_server(services)
    async with create_connected_server_and_client_session(server) as client:
        tools = await client.list_tools()
        assert "site_onboarding_submit" not in {tool.name for tool in tools.tools}


@pytest.mark.asyncio
async def test_writable_runtime_submits_site_onboarding_directly_over_http_and_mcp(
    indexnow_deployment: tuple[Settings, ApplicationServices],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings, services = indexnow_deployment
    assert services.site_onboarding is not None
    assert services.writes_enabled is True
    calls: list[str] = []

    async def mock_onboard(*_: object) -> SiteOnboardingReceipt:
        calls.append("onboard")
        return _receipt()

    monkeypatch.setattr(services.site_onboarding._operator, "onboard", mock_onboard)
    app = create_http_app(settings.model_copy(update={"enable_openapi": True}), services)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://rankrat.test",
    ) as client:
        openapi = await client.get("/openapi.json")
        assert "/v1/site-onboarding-submissions" in openapi.json()["paths"]
        malformed = await client.post(
            "/v1/site-onboarding-submissions",
            json={**_REQUEST, "unexpected_legacy_field": "not-accepted"},
        )
        assert malformed.status_code == 422
        submission = await client.post("/v1/site-onboarding-submissions", json=_REQUEST)
        assert submission.status_code == 200
        assert submission.json()["ga4_property_id"] == "456"

    server = build_mcp_server(services)
    async with create_connected_server_and_client_session(server) as client:
        tools = await client.list_tools()
        onboarding = next(tool for tool in tools.tools if tool.name == "site_onboarding_submit")
        assert onboarding.annotations is not None
        assert onboarding.annotations.readOnlyHint is False
        assert onboarding.annotations.destructiveHint is True
        assert "google_analytics_parent_account_id" in onboarding.inputSchema["properties"]
        assert "unexpected_legacy_field" not in onboarding.inputSchema.get("properties", {})
        response = await client.call_tool("site_onboarding_submit", _REQUEST)
        assert response.isError is False
        content = response.content[0]
        assert isinstance(content, types.TextContent)
        assert json.loads(content.text)["ga4_property_id"] == "456"
    assert calls == ["onboard", "onboard"]
