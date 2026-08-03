from __future__ import annotations

import json
from datetime import date

import httpx
import mcp.types as types
import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from rankrat.config import Settings
from rankrat.providers.google_analytics import Ga4ReportRow
from rankrat.services.cross_provider import (
    Ga4PageSpeedCorrelationReport,
    Ga4PageSpeedCorrelationRequest,
)
from rankrat.services.pagespeed import PageSpeedAnalysisReport, PageSpeedCategoryScore
from rankrat.transports.http import create_http_app
from rankrat.transports.mcp import build_mcp_server
from rankrat.transports.runtime import ApplicationServices


def _report() -> Ga4PageSpeedCorrelationReport:
    return Ga4PageSpeedCorrelationReport(
        requested_page_path="/article",
        ga4_content_row=Ga4ReportRow(("/article",), ("7", "3", "2")),
        pagespeed=PageSpeedAnalysisReport(
            analyzed_url="https://example.com/article",
            analysis_utc_timestamp="2026-07-30T23:25:07+00:00",
            categories=(PageSpeedCategoryScore("performance", 0.95),),
            loading_experience_category="FAST",
            origin_loading_experience_category=None,
        ),
    )


def _request_body() -> dict[str, object]:
    return {
        "google_analytics_account_id": "google-main",
        "property_id": "123456789",
        "pagespeed_account_id": "pagespeed-main",
        "site_url": "https://example.com/",
        "page_url": "https://example.com/article",
        "start_date": "2026-07-01",
        "end_date": "2026-07-02",
    }


@pytest.mark.asyncio
async def test_cross_provider_rest_contract_is_strict_and_uses_two_account_boundaries(
    deployment: tuple[Settings, ApplicationServices],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings, services = deployment
    received_requests: list[Ga4PageSpeedCorrelationRequest] = []

    async def correlation(
        request: Ga4PageSpeedCorrelationRequest,
    ) -> Ga4PageSpeedCorrelationReport:
        received_requests.append(request)
        return _report()

    monkeypatch.setattr(services.cross_provider, "ga4_pagespeed_correlation", correlation)
    app = create_http_app(settings, services)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://rankrat.test",
    ) as client:
        response = await client.post(
            "/v1/cross-provider/ga4-pagespeed-correlations",
            json=_request_body(),
        )
        invalid = await client.post(
            "/v1/cross-provider/ga4-pagespeed-correlations",
            json={**_request_body(), "unexpected": True},
        )

    assert response.status_code == 200
    assert response.json() == {
        "requested_page_path": "/article",
        "ga4_content_row": {
            "dimension_values": ["/article"],
            "metric_values": ["7", "3", "2"],
        },
        "pagespeed": {
            "analyzed_url": "https://example.com/article",
            "analysis_utc_timestamp": "2026-07-30T23:25:07+00:00",
            "categories": [{"category": "performance", "score": 0.95}],
            "loading_experience_category": "FAST",
            "origin_loading_experience_category": None,
        },
    }
    assert invalid.status_code == 422
    assert invalid.json()["code"] == "VALIDATION_FAILED"
    assert received_requests == [
        Ga4PageSpeedCorrelationRequest(
            google_analytics_account_id="google-main",
            property_id="123456789",
            pagespeed_account_id="pagespeed-main",
            site_url="https://example.com/",
            page_url="https://example.com/article",
            start_date=date(2026, 7, 1),
            end_date=date(2026, 7, 2),
        )
    ]


@pytest.mark.asyncio
async def test_cross_provider_mcp_contract_is_strict_and_read_only(
    deployment: tuple[Settings, ApplicationServices],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, services = deployment

    async def correlation(
        _: Ga4PageSpeedCorrelationRequest,
    ) -> Ga4PageSpeedCorrelationReport:
        return _report()

    monkeypatch.setattr(services.cross_provider, "ga4_pagespeed_correlation", correlation)
    server = build_mcp_server(services)
    async with create_connected_server_and_client_session(server) as client:
        tools = await client.list_tools()
        tool = next(tool for tool in tools.tools if tool.name == "ga4_pagespeed_correlation")
        response = await client.call_tool("ga4_pagespeed_correlation", _request_body())
        invalid = await client.call_tool(
            "ga4_pagespeed_correlation",
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
        "pagespeed_account_id",
        "site_url",
        "page_url",
        "start_date",
        "end_date",
    ]
    response_content = response.content[0]
    assert isinstance(response_content, types.TextContent)
    assert json.loads(response_content.text)["requested_page_path"] == "/article"
    assert invalid.isError is True
    invalid_content = invalid.content[0]
    assert isinstance(invalid_content, types.TextContent)
    assert json.loads(invalid_content.text)["code"] == "TOOL_INPUT_INVALID"
