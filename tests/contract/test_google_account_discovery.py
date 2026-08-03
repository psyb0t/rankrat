from __future__ import annotations

import json

import httpx
import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from rankrat.config import Settings
from rankrat.constants import (
    GOOGLE_ANALYTICS_ACCOUNT_INVENTORY_OPERATION,
    GOOGLE_ANALYTICS_ACCOUNT_INVENTORY_PATH,
)
from rankrat.providers.google_analytics import Ga4AccountSummary, Ga4PropertySummary
from rankrat.transports.http import create_http_app
from rankrat.transports.mcp import build_mcp_server
from rankrat.transports.runtime import ApplicationServices

_INVENTORY = (
    Ga4AccountSummary(
        account_id="123",
        display_name="Example account",
        properties=(Ga4PropertySummary("456", "Example property"),),
    ),
)


@pytest.mark.asyncio
async def test_rest_google_account_inventory_contract(
    deployment: tuple[Settings, ApplicationServices],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings, services = deployment
    captured: list[object] = []

    async def list_account_summaries(*arguments: object) -> tuple[Ga4AccountSummary, ...]:
        captured.extend(arguments)
        return _INVENTORY

    monkeypatch.setattr(services.google_analytics, "list_account_summaries", list_account_summaries)
    app = create_http_app(settings, services)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://rankrat.test",
    ) as client:
        response = await client.post(
            f"/v1{GOOGLE_ANALYTICS_ACCOUNT_INVENTORY_PATH}",
            json={"account_id": "google-main", "timeout_seconds": 1.0},
        )
        malformed_response = await client.post(
            f"/v1{GOOGLE_ANALYTICS_ACCOUNT_INVENTORY_PATH}",
            json={"account_id": "google-main", "property_id": "456"},
        )

    assert response.status_code == 200
    assert response.json() == [
        {
            "account_id": "123",
            "display_name": "Example account",
            "properties": [{"property_id": "456", "display_name": "Example property"}],
        }
    ]
    assert len(captured) == 1
    assert malformed_response.status_code == 422


@pytest.mark.asyncio
async def test_mcp_google_account_inventory_contract(
    deployment: tuple[Settings, ApplicationServices],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, services = deployment

    async def list_account_summaries(*_: object) -> tuple[Ga4AccountSummary, ...]:
        return _INVENTORY

    monkeypatch.setattr(services.google_analytics, "list_account_summaries", list_account_summaries)
    server = build_mcp_server(services)
    async with create_connected_server_and_client_session(server) as client:
        tools = await client.list_tools()
        inventory_tool = next(
            tool
            for tool in tools.tools
            if tool.name == GOOGLE_ANALYTICS_ACCOUNT_INVENTORY_OPERATION
        )
        result = await client.call_tool(
            GOOGLE_ANALYTICS_ACCOUNT_INVENTORY_OPERATION,
            {"account_id": "google-main", "timeout_seconds": 1.0},
        )
        malformed_result = await client.call_tool(
            GOOGLE_ANALYTICS_ACCOUNT_INVENTORY_OPERATION,
            {"account_id": "google-main", "property_id": "456"},
        )

    assert inventory_tool.annotations is not None
    assert inventory_tool.annotations.readOnlyHint is True
    assert inventory_tool.annotations.destructiveHint is False
    assert json.loads(result.content[0].text) == [  # type: ignore[union-attr]
        {
            "account_id": "123",
            "display_name": "Example account",
            "properties": [{"property_id": "456", "display_name": "Example property"}],
        }
    ]
    assert malformed_result.isError is True
