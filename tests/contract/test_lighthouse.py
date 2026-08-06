from __future__ import annotations

import json
from typing import Protocol, cast

import httpx
import mcp.types as types
import pytest
from fastapi import FastAPI
from mcp.shared.memory import create_connected_server_and_client_session

from rankrat.config import Settings
from rankrat.constants import DEFAULT_LIGHTHOUSE_TIMEOUT_SECONDS
from rankrat.providers.lighthouse import LighthouseCategoryScore, LighthouseFinding
from rankrat.services.lighthouse import (
    LighthouseAuditReport,
    LighthouseAuditRequest,
    LighthouseCategory,
)
from rankrat.transports.http import create_http_app
from rankrat.transports.mcp import build_mcp_server
from rankrat.transports.runtime import ApplicationServices

_OPERATIONS = {
    "lighthouse_audit": None,
    "lighthouse_seo_findings": LighthouseCategory.SEO,
    "lighthouse_accessibility_findings": LighthouseCategory.ACCESSIBILITY,
    "lighthouse_performance_findings": LighthouseCategory.PERFORMANCE,
    "lighthouse_best_practices_findings": LighthouseCategory.BEST_PRACTICES,
}
_PATHS = {
    "lighthouse_audit": "/v1/lighthouse/audits",
    "lighthouse_seo_findings": "/v1/lighthouse/seo-findings",
    "lighthouse_accessibility_findings": "/v1/lighthouse/accessibility-findings",
    "lighthouse_performance_findings": "/v1/lighthouse/performance-findings",
    "lighthouse_best_practices_findings": "/v1/lighthouse/best-practices-findings",
}


class _WrappedApp(Protocol):
    _app: object


def _unwrap_fastapi(app: object) -> FastAPI:
    current = app
    while not isinstance(current, FastAPI):
        current = cast(_WrappedApp, current)._app
    return current


def _request_body() -> dict[str, object]:
    return {
        "account_id": "pagespeed-main",
        "site_url": "https://example.com/",
        "page_url": "https://example.com/page",
    }


def _report(category: LighthouseCategory | None = None) -> LighthouseAuditReport:
    category_name = category.value if category is not None else LighthouseCategory.SEO.value
    return LighthouseAuditReport(
        requested_url="https://example.com/page",
        final_url="https://example.com/final",
        fetch_time="2026-08-05T18:30:32+00:00",
        lighthouse_version="13.4.1",
        categories=(LighthouseCategoryScore(category_name, 0.75),),
        findings=(
            LighthouseFinding(
                id="document-title",
                categories=(category_name,),
                score=0.5,
                score_display_mode="numeric",
                title="Document title",
                description="Add a descriptive title.",
                display_value=None,
                numeric_value=None,
                numeric_unit=None,
            ),
        ),
    )


def _mock_lighthouse(
    services: ApplicationServices,
    monkeypatch: pytest.MonkeyPatch,
    received: list[tuple[LighthouseAuditRequest, LighthouseCategory | None]],
) -> None:
    async def audit(request: LighthouseAuditRequest) -> LighthouseAuditReport:
        received.append((request, None))
        return _report()

    async def findings(
        request: LighthouseAuditRequest,
        category: LighthouseCategory,
    ) -> LighthouseAuditReport:
        received.append((request, category))
        return _report(category)

    monkeypatch.setattr(services.lighthouse, "audit", audit)
    monkeypatch.setattr(services.lighthouse, "findings", findings)


@pytest.mark.asyncio
async def test_all_lighthouse_rest_contracts_are_strict(
    deployment: tuple[Settings, ApplicationServices],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings, services = deployment
    received: list[tuple[LighthouseAuditRequest, LighthouseCategory | None]] = []
    _mock_lighthouse(services, monkeypatch, received)
    app = create_http_app(settings, services)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://rankrat.test",
    ) as client:
        responses = {
            operation: await client.post(path, json=_request_body())
            for operation, path in _PATHS.items()
        }
        invalid = await client.post(
            _PATHS["lighthouse_audit"],
            json={**_request_body(), "unexpected": True},
        )

    assert all(response.status_code == 200 for response in responses.values())
    assert responses["lighthouse_seo_findings"].json()["categories"] == [
        {"category": "seo", "score": 0.75}
    ]
    assert [category for _, category in received] == list(_OPERATIONS.values())
    assert all(
        request.timeout_seconds == DEFAULT_LIGHTHOUSE_TIMEOUT_SECONDS for request, _ in received
    )
    assert invalid.status_code == 422
    assert invalid.json()["code"] == "VALIDATION_FAILED"


@pytest.mark.asyncio
async def test_all_lighthouse_stdio_mcp_tools_have_parity_and_open_world_annotations(
    deployment: tuple[Settings, ApplicationServices],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, services = deployment
    received: list[tuple[LighthouseAuditRequest, LighthouseCategory | None]] = []
    _mock_lighthouse(services, monkeypatch, received)
    server = build_mcp_server(services)

    async with create_connected_server_and_client_session(server) as client:
        listed = await client.list_tools()
        tools = {tool.name: tool for tool in listed.tools if tool.name in _OPERATIONS}
        responses = {
            operation: await client.call_tool(operation, _request_body())
            for operation in _OPERATIONS
        }
        invalid = await client.call_tool(
            "lighthouse_audit",
            {**_request_body(), "unexpected": True},
        )

    assert set(tools) == set(_OPERATIONS)
    for tool in tools.values():
        assert tool.annotations is not None
        assert tool.annotations.readOnlyHint is True
        assert tool.annotations.destructiveHint is False
        assert tool.annotations.idempotentHint is True
        assert tool.annotations.openWorldHint is True
        assert tool.inputSchema["required"] == ["account_id", "site_url", "page_url"]
    for response in responses.values():
        content = response.content[0]
        assert isinstance(content, types.TextContent)
        assert json.loads(content.text)["lighthouse_version"] == "13.4.1"
    assert [category for _, category in received] == list(_OPERATIONS.values())
    assert invalid.isError is True
    invalid_content = invalid.content[0]
    assert isinstance(invalid_content, types.TextContent)
    assert json.loads(invalid_content.text)["code"] == "TOOL_INPUT_INVALID"


@pytest.mark.asyncio
async def test_lighthouse_streamable_http_mcp_uses_the_same_tool_contract(
    deployment: tuple[Settings, ApplicationServices],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings, services = deployment
    received: list[tuple[LighthouseAuditRequest, LighthouseCategory | None]] = []
    _mock_lighthouse(services, monkeypatch, received)
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
            "name": "lighthouse_performance_findings",
            "arguments": _request_body(),
        },
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

    assert initialized.status_code == 200
    assert called.status_code == 200
    content = called.json()["result"]["content"][0]
    assert json.loads(content["text"])["categories"] == [{"category": "performance", "score": 0.75}]
    assert received[0][1] is LighthouseCategory.PERFORMANCE
