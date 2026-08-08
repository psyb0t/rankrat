from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import replace
from typing import Protocol, cast

import httpx
import pytest
from fastapi import FastAPI
from mcp.shared.memory import create_connected_server_and_client_session

from rankrat.config import Settings
from rankrat.operator.content_opportunities import ContentOpportunityOperator
from rankrat.operator.internal_links import InternalLinkOperator
from rankrat.operator.monitoring import MonitoringOperator
from rankrat.services.backlinks import BacklinkService
from rankrat.services.cloudflare_performance import CloudflarePerformanceService
from rankrat.services.crux import CruxHistoryService
from rankrat.transports.http import create_http_app
from rankrat.transports.mcp import build_mcp_server
from rankrat.transports.runtime import ApplicationServices

_MONITOR_ID = "00000000-0000-4000-8000-000000000001"
_ISSUE_ID = "00000000-0000-4000-8000-000000000002"
_ZONE_ID = "a" * 32
_TIMESTAMP = "2025-01-01T00:00:00+00:00"


def _monitor() -> dict[str, object]:
    return {
        "id": _MONITOR_ID,
        "name": "Daily audit",
        "kind": "site_audit",
        "account_id": "pagespeed-main",
        "site_url": "https://example.com/",
        "interval_seconds": 300,
        "enabled": True,
        "next_run_at": _TIMESTAMP,
        "created_at": _TIMESTAMP,
        "updated_at": _TIMESTAMP,
    }


def _snapshot() -> dict[str, object]:
    return {
        "id": "00000000-0000-4000-8000-000000000003",
        "monitor_id": _MONITOR_ID,
        "observed_at": _TIMESTAMP,
        "score": 100,
        "issue_count": 0,
        "payload": {},
    }


def _issue() -> dict[str, object]:
    return {
        "id": _ISSUE_ID,
        "monitor_id": _MONITOR_ID,
        "identity": "missing-title:https://example.com/",
        "code": "missing_title",
        "resource": "https://example.com/",
        "severity": "error",
        "message": "Page has no title.",
        "remediation": "Add a descriptive title.",
        "status": "open",
        "observations": 1,
        "first_seen_at": _TIMESTAMP,
        "last_seen_at": _TIMESTAMP,
        "resolved_at": None,
    }


class _WrappedApp(Protocol):
    _app: object


def _unwrap_fastapi(app: object) -> FastAPI:
    current = app
    while not isinstance(current, FastAPI):
        current = cast(_WrappedApp, current)._app
    return current


class _InternalLinksFake:
    async def graph(self, _: object) -> dict[str, object]:
        return {
            "site_url": "https://example.com/",
            "nodes": [],
            "edges": [],
            "truncated": False,
        }

    async def orphans(self, _: object) -> dict[str, object]:
        return {
            "site_url": "https://example.com/",
            "findings": [],
            "crawl_truncated": False,
        }

    async def opportunities(self, _: object) -> dict[str, object]:
        return {
            "site_url": "https://example.com/",
            "opportunities": [],
            "crawl_truncated": False,
        }


class _CruxFake:
    async def history(self, _: object) -> dict[str, object]:
        return {
            "target": "https://example.com/",
            "target_kind": "url",
            "form_factor": "ALL_FORM_FACTORS",
            "metrics": [],
            "no_data": True,
        }


class _CloudflareFake:
    async def analytics(self, _: object) -> dict[str, object]:
        return {"zone_id": _ZONE_ID, "points": [], "sampled": False}

    async def purge(self, _: object) -> dict[str, object]:
        return {
            "zone_id": _ZONE_ID,
            "purged_urls": ["https://example.com/page"],
            "provider_request_id": "request-id",
        }

    async def apply_cache_template(self, _: object) -> dict[str, object]:
        return {
            "zone_id": _ZONE_ID,
            "template": "bypass_html",
            "changed": True,
            "ruleset_id": "ruleset-id",
            "rule_id": "rule-id",
            "previous_managed_rule": None,
        }


class _BacklinksFake:
    async def read(self, _: object) -> dict[str, object]:
        return {
            "provider": "ahrefs",
            "target": "https://example.com/",
            "links": [],
            "has_more": False,
        }

    async def aggregate(self, _: object) -> dict[str, object]:
        return {
            "links": [],
            "referring_domains": [],
            "successful_sources": ["ahrefs"],
            "failures": [],
        }


class _ContentFake:
    async def report(self, _: object) -> dict[str, object]:
        return {
            "opportunities": [],
            "insufficient_evidence": True,
            "truncated": False,
        }


class _MonitoringFake:
    available = False

    def list_monitors(self, _: object) -> dict[str, object]:
        return {"items": [_monitor()], "has_more": False}

    def list_snapshots(self, _: object) -> dict[str, object]:
        return {"items": [_snapshot()], "has_more": False}

    def list_issues(self, _: object) -> dict[str, object]:
        return {"items": [_issue()], "has_more": False}

    def list_issue_events(self, _: object) -> dict[str, object]:
        return {
            "items": [
                {
                    "id": 1,
                    "issue_id": _ISSUE_ID,
                    "event": "opened",
                    "occurred_at": _TIMESTAMP,
                }
            ],
            "has_more": False,
        }

    def create_monitor(self, _: object) -> dict[str, object]:
        return _monitor()

    def update_monitor(self, _: object) -> dict[str, object]:
        return _monitor()

    def delete_monitor(self, _: object) -> None:
        return None

    async def run_monitor(self, _: object) -> dict[str, object]:
        return {"monitor": _monitor(), "snapshot": _snapshot()}

    def set_issue_status(self, _: object) -> dict[str, object]:
        return _issue()


def _services(
    services: ApplicationServices,
    *,
    writes_enabled: bool,
) -> ApplicationServices:
    return replace(
        services,
        monitoring=cast(MonitoringOperator, _MonitoringFake()),
        internal_links=cast(InternalLinkOperator, _InternalLinksFake()),
        crux=cast(CruxHistoryService, _CruxFake()),
        cloudflare_performance=cast(CloudflarePerformanceService, _CloudflareFake()),
        backlinks=cast(BacklinkService, _BacklinksFake()),
        content_opportunities=cast(ContentOpportunityOperator, _ContentFake()),
        writes_enabled=writes_enabled,
    )


def _read_calls() -> tuple[tuple[str, str, Mapping[str, object] | None], ...]:
    internal = {
        "account_id": "pagespeed-main",
        "site_url": "https://example.com/",
    }
    return (
        ("POST", "/v1/internal-link-graphs", internal),
        (
            "POST",
            "/v1/orphan-page-reports",
            {
                "crawl_account_id": "pagespeed-main",
                "crawl_site_url": "https://example.com/",
                "search_console_account_id": "google-main",
                "search_console_site_url": "sc-domain:example.com",
                "ga4_account_id": "google-main",
                "ga4_property_id": "123",
                "start_date": "2025-01-01",
                "end_date": "2025-01-31",
            },
        ),
        ("POST", "/v1/internal-link-opportunity-reports", internal),
        (
            "POST",
            "/v1/crux/history-reports",
            {
                "account_id": "pagespeed-main",
                "site_url": "https://example.com/",
                "target": "https://example.com/",
            },
        ),
        (
            "POST",
            "/v1/cloudflare/analytics-reports",
            {
                "account_id": "cloudflare-main",
                "zone_id": _ZONE_ID,
                "start": "2025-01-01T00:00:00Z",
                "end": "2025-01-02T00:00:00Z",
            },
        ),
        (
            "POST",
            "/v1/backlink-reports",
            {
                "account_id": "ahrefs-main",
                "provider": "ahrefs",
                "target": "https://example.com/",
            },
        ),
        (
            "POST",
            "/v1/backlink-aggregate-reports",
            {
                "sources": [
                    {
                        "account_id": "ahrefs-main",
                        "provider": "ahrefs",
                        "target": "https://example.com/",
                    }
                ]
            },
        ),
        (
            "POST",
            "/v1/content-opportunity-reports",
            {
                "google_account_id": "google-main",
                "search_console_site_url": "sc-domain:example.com",
                "bing_account_id": "bing-main",
                "bing_site_url": "https://example.com/",
                "ga4_account_id": "google-main",
                "ga4_property_id": "123",
                "crawl_account_id": "pagespeed-main",
                "crawl_site_url": "https://example.com/",
                "start_date": "2025-01-01",
                "end_date": "2025-01-31",
            },
        ),
        (
            "GET",
            "/v1/monitors?account_id=pagespeed-main&site_url=https%3A%2F%2Fexample.com%2F",
            None,
        ),
        (
            "GET",
            f"/v1/monitors/{_MONITOR_ID}/snapshots?account_id=pagespeed-main&site_url=https%3A%2F%2Fexample.com%2F",
            None,
        ),
        (
            "GET",
            f"/v1/monitors/{_MONITOR_ID}/issues?account_id=pagespeed-main&site_url=https%3A%2F%2Fexample.com%2F",
            None,
        ),
        (
            "GET",
            f"/v1/issues/{_ISSUE_ID}/events?monitor_id={_MONITOR_ID}&account_id=pagespeed-main&site_url=https%3A%2F%2Fexample.com%2F",
            None,
        ),
    )


def _write_calls() -> tuple[tuple[str, str, Mapping[str, object] | None], ...]:
    scope = {"account_id": "pagespeed-main", "site_url": "https://example.com/"}
    return (
        ("POST", "/v1/monitors", {**scope, "name": "Daily"}),
        (
            "PATCH",
            f"/v1/monitors/{_MONITOR_ID}?account_id=pagespeed-main&site_url=https%3A%2F%2Fexample.com%2F",
            {"name": "Weekly", "interval_seconds": 600, "enabled": True},
        ),
        (
            "POST",
            f"/v1/monitors/{_MONITOR_ID}/runs",
            scope,
        ),
        (
            "PATCH",
            f"/v1/issues/{_ISSUE_ID}",
            {
                **scope,
                "monitor_id": _MONITOR_ID,
                "status": "acknowledged",
            },
        ),
        (
            "POST",
            "/v1/cloudflare/cache-purges",
            {
                "account_id": "cloudflare-main",
                "zone_id": _ZONE_ID,
                "site_url": "https://example.com/",
                "urls": ["https://example.com/page"],
            },
        ),
        (
            "POST",
            "/v1/cloudflare/cache-template-applications",
            {
                "account_id": "cloudflare-main",
                "zone_id": _ZONE_ID,
                "template": "bypass_html",
            },
        ),
        (
            "DELETE",
            f"/v1/monitors/{_MONITOR_ID}?account_id=pagespeed-main&site_url=https%3A%2F%2Fexample.com%2F",
            None,
        ),
    )


def _mcp_calls() -> tuple[tuple[str, Mapping[str, object]], ...]:
    scope = {"account_id": "pagespeed-main", "site_url": "https://example.com/"}
    return (
        ("internal_link_graph", scope),
        (
            "orphan_page_report",
            {
                "crawl_account_id": "pagespeed-main",
                "crawl_site_url": "https://example.com/",
                "search_console_account_id": "google-main",
                "search_console_site_url": "sc-domain:example.com",
                "ga4_account_id": "google-main",
                "ga4_property_id": "123",
                "start_date": "2025-01-01",
                "end_date": "2025-01-31",
            },
        ),
        ("internal_link_opportunities", scope),
        (
            "crux_history",
            {
                **scope,
                "target": "https://example.com/",
            },
        ),
        (
            "cloudflare_analytics",
            {
                "account_id": "cloudflare-main",
                "zone_id": _ZONE_ID,
                "start": "2025-01-01T00:00:00Z",
                "end": "2025-01-02T00:00:00Z",
            },
        ),
        (
            "backlink_report",
            {
                "account_id": "ahrefs-main",
                "provider": "ahrefs",
                "target": "https://example.com/",
            },
        ),
        (
            "backlink_aggregate",
            {
                "sources": [
                    {
                        "account_id": "ahrefs-main",
                        "provider": "ahrefs",
                        "target": "https://example.com/",
                    }
                ]
            },
        ),
        (
            "content_opportunities",
            {
                "google_account_id": "google-main",
                "search_console_site_url": "sc-domain:example.com",
                "bing_account_id": "bing-main",
                "bing_site_url": "https://example.com/",
                "ga4_account_id": "google-main",
                "ga4_property_id": "123",
                "crawl_account_id": "pagespeed-main",
                "crawl_site_url": "https://example.com/",
                "start_date": "2025-01-01",
                "end_date": "2025-01-31",
            },
        ),
        ("monitors_list", scope),
        ("monitor_snapshots_list", {**scope, "monitor_id": _MONITOR_ID}),
        ("monitor_issues_list", {**scope, "monitor_id": _MONITOR_ID}),
        (
            "issue_events_list",
            {**scope, "monitor_id": _MONITOR_ID, "issue_id": _ISSUE_ID},
        ),
        ("monitor_create", {**scope, "name": "Daily"}),
        (
            "monitor_update",
            {
                **scope,
                "monitor_id": _MONITOR_ID,
                "name": "Weekly",
                "interval_seconds": 600,
                "enabled": True,
            },
        ),
        ("monitor_run", {**scope, "monitor_id": _MONITOR_ID}),
        (
            "issue_status_update",
            {
                **scope,
                "monitor_id": _MONITOR_ID,
                "issue_id": _ISSUE_ID,
                "status": "acknowledged",
            },
        ),
        (
            "cloudflare_cache_purge",
            {
                "account_id": "cloudflare-main",
                "zone_id": _ZONE_ID,
                "site_url": "https://example.com/",
                "urls": ["https://example.com/page"],
            },
        ),
        (
            "cloudflare_cache_template_apply",
            {
                "account_id": "cloudflare-main",
                "zone_id": _ZONE_ID,
                "template": "bypass_html",
            },
        ),
        ("monitor_delete", {**scope, "monitor_id": _MONITOR_ID}),
    )


@pytest.mark.asyncio
async def test_all_seo_intelligence_rest_routes_and_read_only_hiding(
    deployment: tuple[Settings, ApplicationServices],
) -> None:
    settings, base_services = deployment
    services = _services(base_services, writes_enabled=False)
    app = create_http_app(settings, services)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://rankrat.test",
    ) as client:
        for method, path, body in _read_calls():
            response = await client.request(method, path, json=body)
            assert response.status_code == 200, (path, response.text)
        for method, path, body in _write_calls():
            response = await client.request(method, path, json=body)
            assert response.status_code in {404, 405}, (path, response.text)
        invalid = await client.post(
            "/v1/internal-link-graphs",
            json={
                "account_id": "pagespeed-main",
                "site_url": "https://example.com/",
                "unexpected": True,
            },
        )
        assert invalid.status_code == 422
        assert invalid.json() == {
            "code": "VALIDATION_FAILED",
            "message": "request validation failed",
        }
        oversized_offset = await client.post(
            "/v1/backlink-reports",
            json={
                "account_id": "ahrefs-main",
                "provider": "ahrefs",
                "target": "https://example.com/",
                "offset": 20_001,
            },
        )
        assert oversized_offset.status_code == 422


@pytest.mark.asyncio
async def test_all_seo_intelligence_write_routes_and_mcp_tool_visibility(
    deployment: tuple[Settings, ApplicationServices],
) -> None:
    settings, base_services = deployment
    services = _services(base_services, writes_enabled=True)
    app = create_http_app(settings, services)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://rankrat.test",
    ) as client:
        for method, path, body in _write_calls():
            response = await client.request(method, path, json=body)
            assert response.status_code == 200, (path, response.text)

    server = build_mcp_server(services)
    async with create_connected_server_and_client_session(server) as client:
        catalog = {tool.name: tool for tool in (await client.list_tools()).tools}
        expected = {
            "internal_link_graph",
            "orphan_page_report",
            "internal_link_opportunities",
            "crux_history",
            "cloudflare_analytics",
            "backlink_report",
            "backlink_aggregate",
            "content_opportunities",
            "monitors_list",
            "monitor_snapshots_list",
            "monitor_issues_list",
            "issue_events_list",
            "monitor_create",
            "monitor_update",
            "monitor_delete",
            "monitor_run",
            "issue_status_update",
            "cloudflare_cache_purge",
            "cloudflare_cache_template_apply",
        }
        assert expected <= set(catalog)
        delete_annotations = catalog["monitor_delete"].annotations
        list_annotations = catalog["monitors_list"].annotations
        assert delete_annotations is not None
        assert list_annotations is not None
        assert delete_annotations.destructiveHint is True
        assert list_annotations.openWorldHint is False
        for tool_name, arguments in _mcp_calls():
            result = await client.call_tool(tool_name, dict(arguments))
            assert result.isError is not True, tool_name
            assert result.content, tool_name


@pytest.mark.asyncio
async def test_new_seo_tools_are_callable_over_streamable_http_mcp(
    deployment: tuple[Settings, ApplicationServices],
) -> None:
    settings, base_services = deployment
    services = _services(base_services, writes_enabled=True)
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
    async with (
        fastapi_app.router.lifespan_context(fastapi_app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://rankrat.test",
        ) as client,
    ):
        initialized = await client.post("/mcp/", headers=headers, json=initialize_request)
        calls: list[tuple[str, httpx.Response]] = []
        for request_id, (tool_name, arguments) in enumerate(_mcp_calls(), start=2):
            calls.append(
                (
                    tool_name,
                    await client.post(
                        "/mcp/",
                        headers=headers,
                        json={
                            "jsonrpc": "2.0",
                            "id": request_id,
                            "method": "tools/call",
                            "params": {
                                "name": tool_name,
                                "arguments": dict(arguments),
                            },
                        },
                    ),
                )
            )
        invalid = await client.post(
            "/mcp/",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 100,
                "method": "tools/call",
                "params": {
                    "name": "backlink_report",
                    "arguments": {
                        "account_id": "ahrefs-main",
                        "provider": "ahrefs",
                        "target": "https://example.com/",
                        "offset": 20_001,
                    },
                },
            },
        )

    assert initialized.status_code == 200
    assert all(response.status_code == 200 for _, response in calls)
    assert all(response.json()["result"]["isError"] is not True for _, response in calls)
    graph_response = next(response for name, response in calls if name == "internal_link_graph")
    content = graph_response.json()["result"]["content"][0]
    assert json.loads(content["text"]) == {
        "site_url": "https://example.com/",
        "nodes": [],
        "edges": [],
        "truncated": False,
    }
    assert invalid.status_code == 200
    assert invalid.json()["result"]["isError"] is True


@pytest.mark.asyncio
async def test_streamable_http_mcp_hides_write_tools_in_read_only_mode(
    deployment: tuple[Settings, ApplicationServices],
) -> None:
    settings, base_services = deployment
    services = _services(base_services, writes_enabled=False)
    app = create_http_app(settings, services)
    fastapi_app = _unwrap_fastapi(app)
    headers = {
        "accept": "application/json, text/event-stream",
        "content-type": "application/json",
    }
    async with (
        fastapi_app.router.lifespan_context(fastapi_app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://rankrat.test",
        ) as client,
    ):
        response = await client.post(
            "/mcp/",
            headers=headers,
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        )

    assert response.status_code == 200
    names = {tool["name"] for tool in response.json()["result"]["tools"]}
    assert "monitors_list" in names
    assert "monitor_create" not in names
    assert "cloudflare_cache_purge" not in names


@pytest.mark.asyncio
async def test_read_only_mcp_catalog_hides_every_new_write_tool(
    deployment: tuple[Settings, ApplicationServices],
) -> None:
    _, base_services = deployment
    services = _services(base_services, writes_enabled=False)
    server = build_mcp_server(services)
    async with create_connected_server_and_client_session(server) as client:
        catalog = {tool.name for tool in (await client.list_tools()).tools}
    assert {
        "monitor_create",
        "monitor_update",
        "monitor_delete",
        "monitor_run",
        "issue_status_update",
        "cloudflare_cache_purge",
        "cloudflare_cache_template_apply",
    }.isdisjoint(catalog)


@pytest.mark.asyncio
async def test_monitor_reads_report_disabled_state_as_service_unavailable(
    deployment: tuple[Settings, ApplicationServices],
) -> None:
    settings, services = deployment
    app = create_http_app(settings, services)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://rankrat.test",
    ) as client:
        response = await client.get(
            "/v1/monitors",
            params={
                "account_id": "pagespeed-main",
                "site_url": "https://example.com/",
            },
        )
    assert response.status_code == 503
    assert response.json() == {
        "code": "REQUEST_REJECTED",
        "message": "persistent state is disabled",
    }
