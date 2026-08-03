from __future__ import annotations

import json
from datetime import date

import httpx
import mcp.types as types
import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from rankrat.config import Settings
from rankrat.services.bing import BingTrafficMetrics
from rankrat.services.cross_provider import (
    SearchEngineComparisonReport,
    SearchEngineComparisonRequest,
)
from rankrat.services.google_search_console import SearchAnalyticsMetrics
from rankrat.transports.http import create_http_app
from rankrat.transports.mcp import build_mcp_server
from rankrat.transports.runtime import ApplicationServices


def _request_body() -> dict[str, object]:
    return {
        "google_search_console_account_id": "pagespeed-main",
        "google_search_console_site_url": "https://example.com/",
        "bing_account_id": "bing-main",
        "bing_site_url": "https://example.com/",
        "start_date": "2026-07-01",
        "end_date": "2026-07-02",
    }


def _report() -> SearchEngineComparisonReport:
    return SearchEngineComparisonReport(
        start_date="2026-07-01",
        end_date="2026-07-02",
        google_search_console=SearchAnalyticsMetrics(10.0, 100.0, 0.1, 3.0),
        bing=BingTrafficMetrics(5.0, 50.0),
    )


@pytest.mark.asyncio
async def test_search_engine_comparison_rest_contract_is_strict(
    deployment: tuple[Settings, ApplicationServices],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings, services = deployment
    received: list[SearchEngineComparisonRequest] = []

    async def search_engine_comparison(
        request: SearchEngineComparisonRequest,
    ) -> SearchEngineComparisonReport:
        received.append(request)
        return _report()

    monkeypatch.setattr(
        services.cross_provider,
        "search_engine_comparison",
        search_engine_comparison,
    )
    app = create_http_app(settings, services)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://rankrat.test",
    ) as client:
        response = await client.post(
            "/v1/cross-provider/search-engine-comparisons",
            json=_request_body(),
        )
        invalid = await client.post(
            "/v1/cross-provider/search-engine-comparisons",
            json={**_request_body(), "unexpected": True},
        )

    assert response.status_code == 200
    assert response.json() == {
        "start_date": "2026-07-01",
        "end_date": "2026-07-02",
        "google_search_console": {
            "clicks": 10.0,
            "impressions": 100.0,
            "ctr": 0.1,
            "position": 3.0,
        },
        "bing": {"clicks": 5.0, "impressions": 50.0},
    }
    assert invalid.status_code == 422
    assert invalid.json()["code"] == "VALIDATION_FAILED"
    assert received == [
        SearchEngineComparisonRequest(
            google_search_console_account_id="pagespeed-main",
            google_search_console_site_url="https://example.com/",
            bing_account_id="bing-main",
            bing_site_url="https://example.com/",
            start_date=date(2026, 7, 1),
            end_date=date(2026, 7, 2),
        )
    ]


@pytest.mark.asyncio
async def test_search_engine_comparison_mcp_contract_is_strict_and_read_only(
    deployment: tuple[Settings, ApplicationServices],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, services = deployment

    async def search_engine_comparison(
        _: SearchEngineComparisonRequest,
    ) -> SearchEngineComparisonReport:
        return _report()

    monkeypatch.setattr(
        services.cross_provider,
        "search_engine_comparison",
        search_engine_comparison,
    )
    server = build_mcp_server(services)
    async with create_connected_server_and_client_session(server) as client:
        tools = await client.list_tools()
        tool = next(tool for tool in tools.tools if tool.name == "search_engine_comparison")
        response = await client.call_tool("search_engine_comparison", _request_body())
        invalid = await client.call_tool(
            "search_engine_comparison",
            {**_request_body(), "unexpected": True},
        )

    assert tool.annotations is not None
    assert tool.annotations.readOnlyHint is True
    assert tool.annotations.destructiveHint is False
    assert tool.annotations.idempotentHint is True
    assert tool.annotations.openWorldHint is False
    assert tool.inputSchema["required"] == [
        "google_search_console_account_id",
        "google_search_console_site_url",
        "bing_account_id",
        "bing_site_url",
        "start_date",
        "end_date",
    ]
    response_content = response.content[0]
    assert isinstance(response_content, types.TextContent)
    assert json.loads(response_content.text)["bing"] == {"clicks": 5.0, "impressions": 50.0}
    assert invalid.isError is True
    invalid_content = invalid.content[0]
    assert isinstance(invalid_content, types.TextContent)
    assert json.loads(invalid_content.text)["code"] == "TOOL_INPUT_INVALID"
