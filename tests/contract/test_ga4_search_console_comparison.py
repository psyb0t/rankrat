from __future__ import annotations

import json
from datetime import date

import httpx
import mcp.types as types
import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from rankrat.config import Settings
from rankrat.providers.google_analytics import Ga4MetricHeader, Ga4MetricType, Ga4ReportResult
from rankrat.services.cross_provider import (
    Ga4SearchConsoleComparisonReport,
    Ga4SearchConsoleComparisonRequest,
)
from rankrat.services.google_analytics import Ga4FixedReport, Ga4FixedReportKind
from rankrat.services.google_search_console import SearchAnalyticsMetrics
from rankrat.transports.http import create_http_app
from rankrat.transports.mcp import build_mcp_server
from rankrat.transports.runtime import ApplicationServices


def _request_body() -> dict[str, object]:
    return {
        "google_analytics_account_id": "google-main",
        "property_id": "123456789",
        "google_search_console_account_id": "pagespeed-main",
        "site_url": "https://example.com/",
        "start_date": "2026-07-01",
        "end_date": "2026-07-02",
    }


def _report() -> Ga4SearchConsoleComparisonReport:
    return Ga4SearchConsoleComparisonReport(
        ga4_organic_search=Ga4FixedReport(
            Ga4FixedReportKind.ORGANIC_SEARCH_LANDING_PAGES,
            Ga4ReportResult(
                ("landingPagePlusQueryString",),
                (Ga4MetricHeader("organicGoogleSearchClicks", Ga4MetricType.INTEGER),),
                (),
                0,
            ),
        ),
        google_search_console=SearchAnalyticsMetrics(10.0, 100.0, 0.1, 3.0),
    )


@pytest.mark.asyncio
async def test_ga4_search_console_comparison_rest_contract_is_strict(
    deployment: tuple[Settings, ApplicationServices],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings, services = deployment
    received: list[Ga4SearchConsoleComparisonRequest] = []

    async def ga4_search_console_comparison(
        request: Ga4SearchConsoleComparisonRequest,
    ) -> Ga4SearchConsoleComparisonReport:
        received.append(request)
        return _report()

    monkeypatch.setattr(
        services.cross_provider,
        "ga4_search_console_comparison",
        ga4_search_console_comparison,
    )
    app = create_http_app(settings, services)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://rankrat.test",
    ) as client:
        response = await client.post(
            "/v1/cross-provider/ga4-search-console-comparisons",
            json=_request_body(),
        )
        invalid = await client.post(
            "/v1/cross-provider/ga4-search-console-comparisons",
            json={**_request_body(), "unexpected": True},
        )

    assert response.status_code == 200
    assert response.json()["ga4_organic_search"]["kind"] == "organic_search_landing_pages"
    assert response.json()["google_search_console"]["clicks"] == 10.0
    assert invalid.status_code == 422
    assert invalid.json()["code"] == "VALIDATION_FAILED"
    assert received == [
        Ga4SearchConsoleComparisonRequest(
            google_analytics_account_id="google-main",
            property_id="123456789",
            google_search_console_account_id="pagespeed-main",
            site_url="https://example.com/",
            start_date=date(2026, 7, 1),
            end_date=date(2026, 7, 2),
        )
    ]


@pytest.mark.asyncio
async def test_ga4_search_console_comparison_mcp_contract_is_strict_and_read_only(
    deployment: tuple[Settings, ApplicationServices],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, services = deployment

    async def ga4_search_console_comparison(
        _: Ga4SearchConsoleComparisonRequest,
    ) -> Ga4SearchConsoleComparisonReport:
        return _report()

    monkeypatch.setattr(
        services.cross_provider,
        "ga4_search_console_comparison",
        ga4_search_console_comparison,
    )
    server = build_mcp_server(services)
    async with create_connected_server_and_client_session(server) as client:
        tools = await client.list_tools()
        tool = next(tool for tool in tools.tools if tool.name == "ga4_search_console_comparison")
        response = await client.call_tool("ga4_search_console_comparison", _request_body())
        invalid = await client.call_tool(
            "ga4_search_console_comparison",
            {**_request_body(), "unexpected": True},
        )

    assert tool.annotations is not None
    assert tool.annotations.readOnlyHint is True
    assert tool.annotations.destructiveHint is False
    assert tool.annotations.idempotentHint is True
    assert tool.annotations.openWorldHint is False
    assert tool.inputSchema["required"] == [
        "google_analytics_account_id",
        "property_id",
        "google_search_console_account_id",
        "site_url",
        "start_date",
        "end_date",
    ]
    response_content = response.content[0]
    assert isinstance(response_content, types.TextContent)
    assert json.loads(response_content.text)["google_search_console"]["clicks"] == 10.0
    assert invalid.isError is True
    invalid_content = invalid.content[0]
    assert isinstance(invalid_content, types.TextContent)
    assert json.loads(invalid_content.text)["code"] == "TOOL_INPUT_INVALID"
