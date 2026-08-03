from __future__ import annotations

import json

import httpx
import mcp.types as types
import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from rankrat.config import Settings
from rankrat.constants import DEFAULT_PAGESPEED_TIMEOUT_SECONDS
from rankrat.providers.pagespeed import PageSpeedMetricDistribution
from rankrat.services.pagespeed import (
    PageSpeedAnalysisRequest,
    PageSpeedCoreWebVital,
    PageSpeedCoreWebVitalKind,
    PageSpeedCoreWebVitalsReport,
)
from rankrat.transports.http import create_http_app
from rankrat.transports.mcp import build_mcp_server
from rankrat.transports.runtime import ApplicationServices

_LOWER_TIMEOUT_SECONDS = 0.5


def _request_body() -> dict[str, object]:
    return {
        "account_id": "pagespeed-main",
        "site_url": "https://example.com/",
        "page_url": "https://example.com/article",
    }


def _report() -> PageSpeedCoreWebVitalsReport:
    return PageSpeedCoreWebVitalsReport(
        analyzed_url="https://example.com/article",
        analysis_utc_timestamp="2026-07-30T23:41:11+00:00",
        page_metrics=(
            PageSpeedCoreWebVital(
                PageSpeedCoreWebVitalKind.LARGEST_CONTENTFUL_PAINT,
                "LARGEST_CONTENTFUL_PAINT_MS",
                2_500,
                "AVERAGE",
                (
                    PageSpeedMetricDistribution(0, 2_500, 0.75),
                    PageSpeedMetricDistribution(2_500, None, 0.25),
                ),
            ),
        ),
        origin_metrics=(),
    )


@pytest.mark.asyncio
async def test_pagespeed_core_web_vitals_rest_contract_is_strict(
    deployment: tuple[Settings, ApplicationServices],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings, services = deployment
    received: list[PageSpeedAnalysisRequest] = []

    async def core_web_vitals(request: PageSpeedAnalysisRequest) -> PageSpeedCoreWebVitalsReport:
        received.append(request)
        return _report()

    monkeypatch.setattr(services.pagespeed, "core_web_vitals", core_web_vitals)
    app = create_http_app(settings, services)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://rankrat.test",
    ) as client:
        response = await client.post("/v1/pagespeed/core-web-vitals", json=_request_body())
        faster_response = await client.post(
            "/v1/pagespeed/core-web-vitals",
            json={**_request_body(), "timeout_seconds": _LOWER_TIMEOUT_SECONDS},
        )
        invalid = await client.post(
            "/v1/pagespeed/core-web-vitals",
            json={**_request_body(), "unexpected": True},
        )

    assert response.status_code == 200
    assert faster_response.status_code == 200
    assert response.json() == {
        "analyzed_url": "https://example.com/article",
        "analysis_utc_timestamp": "2026-07-30T23:41:11+00:00",
        "page_metrics": [
            {
                "kind": "largest_contentful_paint",
                "metric_id": "LARGEST_CONTENTFUL_PAINT_MS",
                "percentile": 2_500,
                "category": "AVERAGE",
                "distributions": [
                    {"minimum": 0, "maximum": 2_500, "proportion": 0.75},
                    {"minimum": 2_500, "maximum": None, "proportion": 0.25},
                ],
            }
        ],
        "origin_metrics": [],
    }
    assert [request.timeout_seconds for request in received] == [
        DEFAULT_PAGESPEED_TIMEOUT_SECONDS,
        _LOWER_TIMEOUT_SECONDS,
    ]
    assert invalid.status_code == 422
    assert invalid.json()["code"] == "VALIDATION_FAILED"


@pytest.mark.asyncio
async def test_pagespeed_core_web_vitals_mcp_contract_is_strict_and_read_only(
    deployment: tuple[Settings, ApplicationServices],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, services = deployment

    received: list[PageSpeedAnalysisRequest] = []

    async def core_web_vitals(request: PageSpeedAnalysisRequest) -> PageSpeedCoreWebVitalsReport:
        received.append(request)
        return _report()

    monkeypatch.setattr(services.pagespeed, "core_web_vitals", core_web_vitals)
    server = build_mcp_server(services)
    async with create_connected_server_and_client_session(server) as client:
        tools = await client.list_tools()
        tool = next(tool for tool in tools.tools if tool.name == "pagespeed_core_web_vitals")
        response = await client.call_tool("pagespeed_core_web_vitals", _request_body())
        faster_response = await client.call_tool(
            "pagespeed_core_web_vitals",
            {**_request_body(), "timeout_seconds": _LOWER_TIMEOUT_SECONDS},
        )
        invalid = await client.call_tool(
            "pagespeed_core_web_vitals",
            {**_request_body(), "unexpected": True},
        )

    assert tool.annotations is not None
    assert tool.annotations.readOnlyHint is True
    assert tool.annotations.destructiveHint is False
    assert tool.annotations.idempotentHint is True
    assert tool.annotations.openWorldHint is False
    assert tool.inputSchema["required"] == ["account_id", "site_url", "page_url"]
    assert [request.timeout_seconds for request in received] == [
        DEFAULT_PAGESPEED_TIMEOUT_SECONDS,
        _LOWER_TIMEOUT_SECONDS,
    ]
    response_content = response.content[0]
    assert isinstance(response_content, types.TextContent)
    assert (
        json.loads(response_content.text)["page_metrics"][0]["kind"] == "largest_contentful_paint"
    )
    faster_response_content = faster_response.content[0]
    assert isinstance(faster_response_content, types.TextContent)
    assert json.loads(faster_response_content.text)["page_metrics"] == [
        {
            "kind": "largest_contentful_paint",
            "metric_id": "LARGEST_CONTENTFUL_PAINT_MS",
            "percentile": 2_500,
            "category": "AVERAGE",
            "distributions": [
                {"minimum": 0, "maximum": 2_500, "proportion": 0.75},
                {"minimum": 2_500, "maximum": None, "proportion": 0.25},
            ],
        }
    ]
    assert invalid.isError is True
    invalid_content = invalid.content[0]
    assert isinstance(invalid_content, types.TextContent)
    assert json.loads(invalid_content.text)["code"] == "TOOL_INPUT_INVALID"
