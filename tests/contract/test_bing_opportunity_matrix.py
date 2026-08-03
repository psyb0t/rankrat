from __future__ import annotations

import json

import httpx
import mcp.types as types
import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from rankrat.config import Settings
from rankrat.services.bing import (
    BingOpportunityMatrixReport,
    BingPerformanceOpportunityReport,
    BingPerformanceRequest,
)
from rankrat.transports.http import create_http_app
from rankrat.transports.mcp import build_mcp_server
from rankrat.transports.runtime import ApplicationServices


def _request_body() -> dict[str, object]:
    return {"account_id": "bing-main", "site_url": "https://example.com/"}


def _report() -> BingOpportunityMatrixReport:
    return BingOpportunityMatrixReport(
        query_opportunities=BingPerformanceOpportunityReport(()),
        page_opportunities=BingPerformanceOpportunityReport(()),
        query_quick_wins=(),
        page_quick_wins=(),
    )


@pytest.mark.asyncio
async def test_bing_opportunity_matrix_rest_contract_is_strict(
    deployment: tuple[Settings, ApplicationServices],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings, services = deployment
    received: list[BingPerformanceRequest] = []

    async def opportunity_matrix(request: BingPerformanceRequest) -> BingOpportunityMatrixReport:
        received.append(request)
        return _report()

    monkeypatch.setattr(services.bing_webmaster, "opportunity_matrix", opportunity_matrix)
    app = create_http_app(settings, services)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://rankrat.test",
    ) as client:
        response = await client.post("/v1/bing/opportunity-matrix", json=_request_body())
        invalid = await client.post(
            "/v1/bing/opportunity-matrix",
            json={**_request_body(), "unexpected": True},
        )

    assert response.status_code == 200
    assert response.json() == {
        "query_opportunities": {"opportunities": []},
        "page_opportunities": {"opportunities": []},
        "query_quick_wins": [],
        "page_quick_wins": [],
    }
    assert invalid.status_code == 422
    assert invalid.json()["code"] == "VALIDATION_FAILED"
    assert received == [BingPerformanceRequest("bing-main", "https://example.com/")]


@pytest.mark.asyncio
async def test_bing_opportunity_matrix_mcp_contract_is_strict_and_read_only(
    deployment: tuple[Settings, ApplicationServices],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, services = deployment

    async def opportunity_matrix(_: BingPerformanceRequest) -> BingOpportunityMatrixReport:
        return _report()

    monkeypatch.setattr(services.bing_webmaster, "opportunity_matrix", opportunity_matrix)
    server = build_mcp_server(services)
    async with create_connected_server_and_client_session(server) as client:
        tools = await client.list_tools()
        tool = next(tool for tool in tools.tools if tool.name == "bing_opportunity_matrix")
        response = await client.call_tool("bing_opportunity_matrix", _request_body())
        invalid = await client.call_tool(
            "bing_opportunity_matrix",
            {**_request_body(), "unexpected": True},
        )

    assert tool.annotations is not None
    assert tool.annotations.readOnlyHint is True
    assert tool.annotations.destructiveHint is False
    assert tool.annotations.idempotentHint is True
    assert tool.annotations.openWorldHint is False
    response_content = response.content[0]
    assert isinstance(response_content, types.TextContent)
    assert json.loads(response_content.text)["query_quick_wins"] == []
    assert invalid.isError is True
    invalid_content = invalid.content[0]
    assert isinstance(invalid_content, types.TextContent)
    assert json.loads(invalid_content.text)["code"] == "TOOL_INPUT_INVALID"
