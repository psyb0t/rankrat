from __future__ import annotations

import json
from typing import cast

import httpx
import mcp.types as types
import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from rankrat import __version__
from rankrat.config import Settings
from rankrat.models.boundaries import Provider
from rankrat.providers.base import (
    ProviderFailureCode,
    ProviderOperationError,
    ProviderReadiness,
    ProviderReadRequest,
)
from rankrat.providers.google_analytics import Ga4ReportResult
from rankrat.providers.google_indexing import GoogleIndexingMetadata
from rankrat.providers.google_search_console import (
    SearchAnalyticsReport,
    SearchConsolePermissionLevel,
    SearchConsoleSite,
    SearchConsoleSitemap,
    SearchConsoleSitemapList,
    SearchConsoleUrlInspection,
)
from rankrat.providers.schema_fetch import SchemaFetchResult
from rankrat.transports import mcp as mcp_transport
from rankrat.transports.mcp import build_mcp_server
from rankrat.transports.runtime import ApplicationServices


@pytest.mark.asyncio
async def test_bing_brand_report_rejects_generic_performance_arguments() -> None:
    arguments = mcp_transport._BingPerformanceArguments(
        account_id="bing-main",
        site_url="https://example.com/",
    )
    with pytest.raises(ValueError, match="literal brand terms"):
        await mcp_transport._bing_site_performance_report(
            cast(ApplicationServices, object()),
            arguments,
            mcp_transport._BingSitePerformanceReportKind.BRAND,
        )


@pytest.mark.asyncio
async def test_mcp_tool_catalog_annotations_and_calls(
    deployment: tuple[Settings, ApplicationServices],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, services = deployment

    async def mock_analytics(*_: object) -> SearchAnalyticsReport:
        return SearchAnalyticsReport((), None)

    async def mock_summary(*_: object) -> object:
        return {"clicks": 1.0, "impressions": 10.0, "ctr": 0.1, "position": 2.0}

    async def mock_comparison(*_: object) -> object:
        return {"clicks_delta": 1.0}

    async def mock_indexing_metadata(*_: object) -> GoogleIndexingMetadata:
        return GoogleIndexingMetadata("https://example.com/jobs/one", None, None)

    async def mock_sitemaps(*_: object) -> SearchConsoleSitemapList:
        return SearchConsoleSitemapList(())

    async def mock_sites(*_: object) -> tuple[str, ...]:
        return ("sc-domain:example.com",)

    async def mock_site(*_: object) -> SearchConsoleSite:
        return SearchConsoleSite("sc-domain:example.com", SearchConsolePermissionLevel.OWNER)

    async def mock_sitemap(*_: object) -> SearchConsoleSitemap:
        return SearchConsoleSitemap(
            path="https://example.com/sitemap.xml",
            last_submitted=None,
            is_pending=None,
            is_sitemaps_index=None,
            sitemap_type=None,
            last_downloaded=None,
            warnings=None,
            errors=None,
            contents=(),
        )

    async def mock_inspection(*_: object) -> SearchConsoleUrlInspection:
        return SearchConsoleUrlInspection(None, None)

    async def mock_inspections(*_: object) -> tuple[SearchConsoleUrlInspection, ...]:
        return (SearchConsoleUrlInspection(None, None),)

    async def mock_ga4_report(*_: object) -> Ga4ReportResult:
        return Ga4ReportResult((), (), (), 0)

    async def mock_ga4_fixed_report(*_: object) -> dict[str, object]:
        return {"kind": "content_performance", "report": {"rows": []}}

    async def mock_ga4_funnel(*_: object) -> dict[str, object]:
        return {"funnel_table": {"rows": []}, "funnel_visualization": {"rows": []}}

    async def mock_bing_keyword_statistics(*_: object) -> dict[str, object]:
        return {"points": []}

    async def mock_bing_related_keywords(*_: object) -> dict[str, object]:
        return {"keywords": []}

    async def mock_bing_traffic_trend(*_: object) -> dict[str, object]:
        return {"points": []}

    async def mock_bing_traffic_anomalies(*_: object) -> dict[str, object]:
        return {"anomalies": []}

    async def mock_bing_traffic_comparison(*_: object) -> dict[str, object]:
        return {
            "current": {"clicks": 3.0, "impressions": 8.0},
            "previous": {"clicks": 1.0, "impressions": 2.0},
            "clicks_delta": 2.0,
            "impressions_delta": 6.0,
        }

    async def mock_bing_performance(*_: object) -> dict[str, object]:
        return {
            "rows": [
                {
                    "label": "rankrat",
                    "day": "2026-07-01",
                    "clicks": 3.0,
                    "impressions": 8.0,
                    "average_click_position": None,
                    "average_impression_position": 4.0,
                }
            ]
        }

    async def mock_bing_brand_analysis(*_: object) -> dict[str, object]:
        return {
            "brand_terms": ["rankrat"],
            "brand_rows": [{"label": "rankrat documentation"}],
            "non_brand_rows": [{"label": "unrelated query"}],
        }

    async def mock_bing_ranking_buckets(*_: object) -> dict[str, object]:
        return {
            "buckets": [
                {"kind": "top_three", "rows": [{"label": "rankrat"}]},
                {"kind": "first_page", "rows": []},
                {"kind": "second_page", "rows": []},
                {"kind": "beyond_second_page", "rows": []},
            ]
        }

    async def mock_bing_cannibalization(*_: object) -> dict[str, object]:
        return {
            "query": "rankrat",
            "pages": [
                {
                    "label": "https://example.com/a",
                    "day": "2026-07-01",
                    "clicks": 3.0,
                    "impressions": 8.0,
                    "average_click_position": 2.0,
                    "average_impression_position": 4.0,
                },
                {
                    "label": "https://example.com/b",
                    "day": "2026-07-01",
                    "clicks": 2.0,
                    "impressions": 4.0,
                    "average_click_position": 3.0,
                    "average_impression_position": 5.0,
                },
            ],
        }

    async def mock_bing_opportunities(*_: object) -> dict[str, object]:
        return {
            "opportunities": [
                {
                    "row": {"label": "rankrat"},
                    "click_through_rate": 0.1,
                    "classifications": ["low_ctr"],
                }
            ]
        }

    async def mock_bing_url_submission_quota(*_: object) -> dict[str, int]:
        return {"daily": 5, "monthly": 24}

    async def mock_bing_crawl_issues(*_: object) -> dict[str, object]:
        return {"issues": [{"url": "https://example.com/missing", "http_code": 404}]}

    async def mock_bing_crawl_stats(*_: object) -> dict[str, object]:
        return {"points": [{"day": "2026-07-01", "code_2xx": 1}]}

    async def mock_bing_feeds(*_: object) -> dict[str, object]:
        return {"feeds": [{"url": "https://example.com/sitemap.xml", "url_count": 3}]}

    async def mock_bing_link_counts(*_: object) -> dict[str, object]:
        return {"links": [{"url": "https://source.example/a", "count": 3}], "total_pages": 2}

    async def mock_bing_url_information(*_: object) -> dict[str, object]:
        return {"url": "https://example.com/article", "http_status": None}

    async def mock_bing_readiness(request: ProviderReadRequest) -> ProviderReadiness:
        return ProviderReadiness(request.account_id, Provider.BING, True, "mocked")

    def mock_pagespeed_api_key(*_: object) -> str:
        return "test-pagespeed-api-key"

    async def mock_schema_fetch(*_: object) -> SchemaFetchResult:
        return SchemaFetchResult(
            url="https://example.com/jobs",
            content_type="text/html",
            body=b'<script type="application/ld+json">{"@type":"JobPosting"}</script>',
        )

    monkeypatch.setattr(services.google_search_console, "search_analytics", mock_analytics)
    monkeypatch.setattr(services.google_search_console, "search_analytics_summary", mock_summary)
    monkeypatch.setattr(
        services.google_search_console,
        "search_analytics_comparison",
        mock_comparison,
    )
    monkeypatch.setattr(services.google_indexing_metadata, "metadata", mock_indexing_metadata)
    monkeypatch.setattr(services.google_search_console, "list_sites", mock_sites)
    monkeypatch.setattr(services.google_search_console, "get_site", mock_site)
    monkeypatch.setattr(services.google_search_console, "list_sitemaps", mock_sitemaps)
    monkeypatch.setattr(services.google_search_console, "get_sitemap", mock_sitemap)
    monkeypatch.setattr(services.google_search_console, "inspect_url", mock_inspection)
    monkeypatch.setattr(services.google_search_console, "inspect_urls", mock_inspections)
    monkeypatch.setattr(services.google_analytics, "run_report", mock_ga4_report)
    monkeypatch.setattr(services.google_analytics, "run_realtime_report", mock_ga4_report)
    monkeypatch.setattr(services.google_analytics, "fixed_report", mock_ga4_fixed_report)
    monkeypatch.setattr(services.google_analytics, "conversion_funnel", mock_ga4_funnel)
    monkeypatch.setattr(
        services.pagespeed._client,
        "_api_key_loader",
        mock_pagespeed_api_key,
    )
    monkeypatch.setattr(
        services.pagespeed._client,
        "_transport_factory",
        lambda: httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json={
                    "analysisUTCTimestamp": "2026-07-30T17:00:00Z",
                    "id": "https://example.com/article",
                    "lighthouseResult": {
                        "categories": {"performance": {"id": "performance", "score": 0.95}}
                    },
                },
            )
        ),
    )
    monkeypatch.setattr(
        services.bing_webmaster,
        "keyword_statistics",
        mock_bing_keyword_statistics,
    )
    monkeypatch.setattr(
        services.bing_webmaster,
        "related_keywords",
        mock_bing_related_keywords,
    )
    monkeypatch.setattr(services.bing_webmaster, "traffic_trend", mock_bing_traffic_trend)
    monkeypatch.setattr(services.bing_webmaster, "traffic_anomalies", mock_bing_traffic_anomalies)
    monkeypatch.setattr(
        services.bing_webmaster,
        "traffic_comparison",
        mock_bing_traffic_comparison,
    )
    monkeypatch.setattr(services.bing_webmaster, "query_performance", mock_bing_performance)
    monkeypatch.setattr(services.bing_webmaster, "page_performance", mock_bing_performance)
    monkeypatch.setattr(services.bing_webmaster, "brand_analysis", mock_bing_brand_analysis)
    monkeypatch.setattr(services.bing_webmaster, "ranking_buckets", mock_bing_ranking_buckets)
    monkeypatch.setattr(services.bing_webmaster, "query_opportunities", mock_bing_opportunities)
    monkeypatch.setattr(services.bing_webmaster, "page_opportunities", mock_bing_opportunities)
    monkeypatch.setattr(services.bing_webmaster, "query_page_performance", mock_bing_performance)
    monkeypatch.setattr(
        services.bing_webmaster,
        "query_cannibalization",
        mock_bing_cannibalization,
    )
    monkeypatch.setattr(services.bing_webmaster, "page_query_performance", mock_bing_performance)
    monkeypatch.setattr(
        services.bing_webmaster,
        "url_submission_quota",
        mock_bing_url_submission_quota,
    )
    monkeypatch.setattr(services.bing_webmaster, "crawl_issues", mock_bing_crawl_issues)
    monkeypatch.setattr(services.bing_webmaster, "crawl_stats", mock_bing_crawl_stats)
    monkeypatch.setattr(services.bing_webmaster, "feeds", mock_bing_feeds)
    monkeypatch.setattr(services.bing_webmaster, "link_counts", mock_bing_link_counts)
    monkeypatch.setattr(services.bing_webmaster, "url_information", mock_bing_url_information)
    monkeypatch.setattr(
        services.provider_readiness._clients[Provider.BING],
        "readiness",
        mock_bing_readiness,
    )
    monkeypatch.setattr(services.local_schema._fetcher, "fetch", mock_schema_fetch)
    server = build_mcp_server(services)
    assert server.name == "rankrat"
    assert server.version == __version__
    async with create_connected_server_and_client_session(server) as client:
        tools = await client.list_tools()
        assert {tool.name for tool in tools.tools} == {
            "accounts_list",
            "diagnostics",
            "google_analytics_data_streams",
            "onboarding_guide",
            "provider_readiness",
            "server_info",
            "sites_list",
            "google_search_analytics_query",
            "google_search_analytics_summary",
            "google_search_analytics_comparison",
            "google_search_analytics_dimension_report",
            "google_search_analytics_drop_attribution",
            "google_search_analytics_trend",
            "google_search_analytics_anomalies",
            "google_search_analytics_page_performance",
            "google_indexing_metadata",
            "schema_validate_html",
            "schema_validate_json_ld",
            "schema_validate_url",
            "google_sites_list",
            "google_site_get",
            "google_sitemaps_list",
            "google_sitemap_get",
            "google_url_inspection",
            "google_url_inspection_batch",
            "google_analytics_account_inventory",
            "google_analytics_report",
            "google_analytics_realtime_report",
            "google_analytics_content_performance",
            "google_analytics_landing_page_performance",
            "google_analytics_organic_search_landing_pages",
            "google_analytics_traffic_source_performance",
            "google_analytics_ecommerce_performance",
            "google_analytics_audience_segments",
            "google_analytics_user_behavior",
            "google_analytics_conversion_funnel",
            "pagespeed_analyze",
            "pagespeed_core_web_vitals",
            "lighthouse_audit",
            "lighthouse_seo_findings",
            "lighthouse_accessibility_findings",
            "lighthouse_performance_findings",
            "lighthouse_best_practices_findings",
            "ga4_pagespeed_correlation",
            "ga4_search_console_comparison",
            "search_engine_comparison",
            "search_engine_traffic_health",
            "bing_keyword_statistics",
            "bing_related_keywords",
            "bing_traffic_trend",
            "bing_traffic_anomalies",
            "bing_traffic_comparison",
            "bing_query_performance",
            "bing_page_performance",
            "bing_brand_analysis",
            "bing_ranking_buckets",
            "bing_query_opportunities",
            "bing_page_opportunities",
            "bing_opportunity_matrix",
            "bing_query_page_performance",
            "bing_query_cannibalization",
            "bing_page_query_performance",
            "bing_url_submission_quota",
            "bing_crawl_issues",
            "bing_crawl_stats",
            "bing_feeds",
            "bing_link_counts",
            "bing_backlink_intelligence",
            "bing_url_information",
            "site_audit",
            "site_ownership_check",
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
        }
        new_open_world_tools = {
            "internal_link_graph",
            "orphan_page_report",
            "internal_link_opportunities",
            "crux_history",
            "cloudflare_analytics",
            "backlink_report",
            "backlink_aggregate",
            "content_opportunities",
        }
        for tool in tools.tools:
            assert tool.annotations is not None
            assert tool.annotations.readOnlyHint is True
            assert tool.annotations.destructiveHint is False
            assert tool.annotations.openWorldHint is (
                tool.name.startswith("lighthouse_") or tool.name in new_open_world_tools
            )

        accounts = await client.call_tool("accounts_list", {"provider": "google"})
        accounts_payload = json.loads(accounts.content[0].text)  # type: ignore[union-attr]
        assert accounts_payload["accounts"][0]["account_id"] == "google-main"
        server_info = await client.call_tool("server_info", {})
        assert json.loads(server_info.content[0].text)["name"] == "rankrat"  # type: ignore[union-attr]
        diagnostics = await client.call_tool("diagnostics", {})
        assert json.loads(diagnostics.content[0].text)["ready"] is True  # type: ignore[union-attr]

        readiness = await client.call_tool(
            "provider_readiness",
            {"account_id": "bing-main", "timeout_seconds": 1.0},
        )
        readiness_payload = json.loads(readiness.content[0].text)  # type: ignore[union-attr]
        assert readiness_payload["available"] is True

        for tool_name in (
            "google_analytics_content_performance",
            "google_analytics_landing_page_performance",
            "google_analytics_organic_search_landing_pages",
            "google_analytics_traffic_source_performance",
            "google_analytics_ecommerce_performance",
            "google_analytics_audience_segments",
            "google_analytics_user_behavior",
        ):
            fixed_report = await client.call_tool(
                tool_name,
                {
                    "account_id": "google-main",
                    "property_id": "123456789",
                    "start_date": "2026-07-01",
                    "end_date": "2026-07-02",
                },
            )
            assert json.loads(fixed_report.content[0].text)["report"] == {"rows": []}  # type: ignore[union-attr]
            malformed_fixed_report = await client.call_tool(
                tool_name,
                {
                    "account_id": "google-main",
                    "property_id": "123456789",
                    "start_date": "2026-07-01",
                    "end_date": "2026-07-02",
                    "metrics": ["sessions"],
                },
            )
            assert malformed_fixed_report.isError is True

        conversion_funnel = await client.call_tool(
            "google_analytics_conversion_funnel",
            {
                "account_id": "google-main",
                "property_id": "123456789",
                "start_date": "2026-07-01",
                "end_date": "2026-07-02",
                "event_names": ["view_item", "purchase"],
            },
        )
        assert json.loads(conversion_funnel.content[0].text) == {  # type: ignore[union-attr]
            "funnel_table": {"rows": []},
            "funnel_visualization": {"rows": []},
        }
        malformed_conversion_funnel = await client.call_tool(
            "google_analytics_conversion_funnel",
            {
                "account_id": "google-main",
                "property_id": "123456789",
                "start_date": "2026-07-01",
                "end_date": "2026-07-02",
                "event_names": ["view_item"],
            },
        )
        assert malformed_conversion_funnel.isError is True

        analytics = await client.call_tool(
            "google_search_analytics_query",
            {
                "account_id": "google-main",
                "site_url": "sc-domain:example.com",
                "start_date": "2026-07-01",
                "end_date": "2026-07-02",
                "dimensions": [],
                "filters": [],
            },
        )
        assert json.loads(analytics.content[0].text) == {  # type: ignore[union-attr]
            "rows": [],
            "aggregation_type": None,
        }
        summary = await client.call_tool(
            "google_search_analytics_summary",
            {
                "account_id": "google-main",
                "site_url": "sc-domain:example.com",
                "start_date": "2026-07-01",
                "end_date": "2026-07-02",
            },
        )
        comparison = await client.call_tool(
            "google_search_analytics_comparison",
            {
                "account_id": "google-main",
                "site_url": "sc-domain:example.com",
                "start_date": "2026-07-01",
                "end_date": "2026-07-02",
                "previous_start_date": "2026-06-29",
                "previous_end_date": "2026-06-30",
            },
        )
        dimension_report = await client.call_tool(
            "google_search_analytics_dimension_report",
            {
                "account_id": "google-main",
                "site_url": "sc-domain:example.com",
                "report": "top_queries",
                "start_date": "2026-07-01",
                "end_date": "2026-07-02",
            },
        )
        drop_attribution = await client.call_tool(
            "google_search_analytics_drop_attribution",
            {
                "account_id": "google-main",
                "site_url": "sc-domain:example.com",
                "attribution": "queries",
                "start_date": "2026-07-01",
                "end_date": "2026-07-02",
                "previous_start_date": "2026-06-29",
                "previous_end_date": "2026-06-30",
            },
        )
        trend = await client.call_tool(
            "google_search_analytics_trend",
            {
                "account_id": "google-main",
                "site_url": "sc-domain:example.com",
                "start_date": "2026-07-01",
                "end_date": "2026-07-02",
            },
        )
        anomalies = await client.call_tool(
            "google_search_analytics_anomalies",
            {
                "account_id": "google-main",
                "site_url": "sc-domain:example.com",
                "start_date": "2026-07-01",
                "end_date": "2026-07-02",
            },
        )
        page_performance = await client.call_tool(
            "google_search_analytics_page_performance",
            {
                "account_id": "google-main",
                "site_url": "sc-domain:example.com",
                "start_date": "2026-07-01",
                "end_date": "2026-07-02",
            },
        )
        assert json.loads(summary.content[0].text)["clicks"] == 1.0  # type: ignore[union-attr]
        assert json.loads(comparison.content[0].text)["clicks_delta"] == 1.0  # type: ignore[union-attr]
        assert json.loads(dimension_report.content[0].text) == {  # type: ignore[union-attr]
            "rows": [],
            "has_more": False,
        }
        assert json.loads(drop_attribution.content[0].text) == {  # type: ignore[union-attr]
            "rows": [],
            "has_more": False,
        }
        assert json.loads(trend.content[0].text) == {"points": [], "has_more": False}  # type: ignore[union-attr]
        assert json.loads(anomalies.content[0].text) == {"anomalies": [], "has_more": False}  # type: ignore[union-attr]
        assert json.loads(page_performance.content[0].text) == {  # type: ignore[union-attr]
            "rows": [],
            "has_more": False,
        }
        indexing_metadata = await client.call_tool(
            "google_indexing_metadata",
            {
                "account_id": "google-main",
                "site_url": "sc-domain:example.com",
                "url": "https://example.com/jobs/one",
            },
        )
        assert json.loads(indexing_metadata.content[0].text) == {  # type: ignore[union-attr]
            "url": "https://example.com/jobs/one",
            "latest_update": None,
            "latest_remove": None,
        }
        schema_html = await client.call_tool(
            "schema_validate_html",
            {"document": '<script type=\'application/ld+json\'>{"@type":"JobPosting"}</script>'},
        )
        schema_json = await client.call_tool(
            "schema_validate_json_ld",
            {"document": '{"@type":"JobPosting"}'},
        )
        schema_url = await client.call_tool(
            "schema_validate_url",
            {"url": "https://example.com/jobs"},
        )
        assert json.loads(schema_html.content[0].text)["eligible"] is True  # type: ignore[union-attr]
        assert json.loads(schema_json.content[0].text)["eligible"] is True  # type: ignore[union-attr]
        assert json.loads(schema_url.content[0].text)["eligibility"]["eligible"] is True  # type: ignore[union-attr]
        malformed_summary = await client.call_tool(
            "google_search_analytics_summary",
            {
                "account_id": "google-main",
                "site_url": "sc-domain:example.com",
                "start_date": "2026-07-01",
                "end_date": "2026-07-02",
                "unexpected": True,
            },
        )
        assert malformed_summary.isError is True
        malformed_schema = await client.call_tool(
            "schema_validate_html",
            {"document": "<html />", "unexpected": True},
        )
        assert malformed_schema.isError is True
        malformed_schema_url = await client.call_tool(
            "schema_validate_url",
            {"url": "https://example.com/jobs", "unexpected": True},
        )
        assert malformed_schema_url.isError is True
        invalid_schema_url_timeout = await client.call_tool(
            "schema_validate_url",
            {"url": "https://example.com/jobs", "timeout_seconds": 0},
        )
        assert invalid_schema_url_timeout.isError is True
        excessive_schema_url_timeout = await client.call_tool(
            "schema_validate_url",
            {"url": "https://example.com/jobs", "timeout_seconds": 30.1},
        )
        assert excessive_schema_url_timeout.isError is True
        malformed_dimension_report = await client.call_tool(
            "google_search_analytics_dimension_report",
            {
                "account_id": "google-main",
                "site_url": "sc-domain:example.com",
                "report": "top_queries",
                "start_date": "2026-07-01",
                "end_date": "2026-07-02",
                "dimensions": ["query"],
            },
        )
        assert malformed_dimension_report.isError is True
        malformed_drop_attribution = await client.call_tool(
            "google_search_analytics_drop_attribution",
            {
                "account_id": "google-main",
                "site_url": "sc-domain:example.com",
                "attribution": "queries",
                "start_date": "2026-07-01",
                "end_date": "2026-07-02",
                "previous_start_date": "2026-06-29",
                "previous_end_date": "2026-06-30",
                "unexpected": True,
            },
        )
        assert malformed_drop_attribution.isError is True
        assert json.loads(malformed_summary.content[0].text)["code"] == "TOOL_INPUT_INVALID"  # type: ignore[union-attr]
        malformed_drop_content = malformed_drop_attribution.content[0]
        assert isinstance(malformed_drop_content, types.TextContent)
        assert json.loads(malformed_drop_content.text)["code"] == "TOOL_INPUT_INVALID"
        for tool_name in (
            "google_search_analytics_trend",
            "google_search_analytics_anomalies",
            "google_search_analytics_page_performance",
        ):
            malformed_derived_report = await client.call_tool(
                tool_name,
                {
                    "account_id": "google-main",
                    "site_url": "sc-domain:example.com",
                    "start_date": "2026-07-01",
                    "end_date": "2026-07-02",
                    "unexpected": True,
                },
            )
            assert malformed_derived_report.isError is True
            derived_content = malformed_derived_report.content[0]
            assert isinstance(derived_content, types.TextContent)
            assert json.loads(derived_content.text)["code"] == "TOOL_INPUT_INVALID"
        invalid_comparison = await client.call_tool(
            "google_search_analytics_comparison",
            {
                "account_id": "google-main",
                "site_url": "sc-domain:example.com",
                "start_date": "2026-07-01",
                "end_date": "2026-07-02",
                "previous_start_date": "2026-06-30",
                "previous_end_date": "2026-06-29",
            },
        )
        assert invalid_comparison.isError is True
        assert json.loads(invalid_comparison.content[0].text)["code"] == "TOOL_REQUEST_REJECTED"  # type: ignore[union-attr]
        invalid_drop_attribution = await client.call_tool(
            "google_search_analytics_drop_attribution",
            {
                "account_id": "google-main",
                "site_url": "sc-domain:example.com",
                "attribution": "queries",
                "start_date": "2026-07-01",
                "end_date": "2026-07-02",
                "previous_start_date": "2026-06-30",
                "previous_end_date": "2026-06-29",
            },
        )
        assert invalid_drop_attribution.isError is True
        invalid_drop_content = invalid_drop_attribution.content[0]
        assert isinstance(invalid_drop_content, types.TextContent)
        assert json.loads(invalid_drop_content.text)["code"] == "TOOL_REQUEST_REJECTED"
        for tool_name in (
            "google_search_analytics_trend",
            "google_search_analytics_anomalies",
            "google_search_analytics_page_performance",
        ):
            invalid_derived_report = await client.call_tool(
                tool_name,
                {
                    "account_id": "google-main",
                    "site_url": "sc-domain:example.com",
                    "start_date": "2026-07-02",
                    "end_date": "2026-07-01",
                },
            )
            assert invalid_derived_report.isError is True
            derived_content = invalid_derived_report.content[0]
            assert isinstance(derived_content, types.TextContent)
            assert json.loads(derived_content.text)["code"] == "TOOL_REQUEST_REJECTED"
        google_sites = await client.call_tool(
            "google_sites_list",
            {"account_id": "google-main"},
        )
        assert json.loads(google_sites.content[0].text) == ["sc-domain:example.com"]  # type: ignore[union-attr]
        google_site = await client.call_tool(
            "google_site_get",
            {"account_id": "google-main", "site_url": "sc-domain:example.com"},
        )
        assert json.loads(google_site.content[0].text) == {  # type: ignore[union-attr]
            "site_url": "sc-domain:example.com",
            "permission_level": "siteOwner",
        }
        sitemaps = await client.call_tool(
            "google_sitemaps_list",
            {"account_id": "google-main", "site_url": "sc-domain:example.com"},
        )
        assert json.loads(sitemaps.content[0].text) == {"sitemaps": []}  # type: ignore[union-attr]
        sitemap = await client.call_tool(
            "google_sitemap_get",
            {
                "account_id": "google-main",
                "site_url": "sc-domain:example.com",
                "sitemap_url": "https://example.com/sitemap.xml",
            },
        )
        assert json.loads(sitemap.content[0].text) == {  # type: ignore[union-attr]
            "path": "https://example.com/sitemap.xml",
            "last_submitted": None,
            "is_pending": None,
            "is_sitemaps_index": None,
            "sitemap_type": None,
            "last_downloaded": None,
            "warnings": None,
            "errors": None,
            "contents": [],
        }
        inspection = await client.call_tool(
            "google_url_inspection",
            {
                "account_id": "google-main",
                "site_url": "sc-domain:example.com",
                "inspection_url": "https://example.com/article",
            },
        )
        assert json.loads(inspection.content[0].text) == {  # type: ignore[union-attr]
            "inspection_result_link": None,
            "index_status": None,
        }
        inspection_batch = await client.call_tool(
            "google_url_inspection_batch",
            {
                "account_id": "google-main",
                "site_url": "sc-domain:example.com",
                "inspection_urls": ["https://example.com/article"],
            },
        )
        assert json.loads(inspection_batch.content[0].text) == [  # type: ignore[union-attr]
            {"inspection_result_link": None, "index_status": None}
        ]
        ga4_report = await client.call_tool(
            "google_analytics_report",
            {
                "account_id": "google-main",
                "property_id": "123456789",
                "date_ranges": [{"start_date": "2026-07-01", "end_date": "2026-07-02"}],
                "dimensions": ["pagePath"],
                "metrics": ["screenPageViews"],
            },
        )
        assert json.loads(ga4_report.content[0].text) == {  # type: ignore[union-attr]
            "dimension_headers": [],
            "metric_headers": [],
            "rows": [],
            "row_count": 0,
        }
        ga4_realtime = await client.call_tool(
            "google_analytics_realtime_report",
            {
                "account_id": "google-main",
                "property_id": "123456789",
                "dimensions": ["country"],
                "metrics": ["activeUsers"],
            },
        )
        assert json.loads(ga4_realtime.content[0].text) == {  # type: ignore[union-attr]
            "dimension_headers": [],
            "metric_headers": [],
            "rows": [],
            "row_count": 0,
        }
        pagespeed = await client.call_tool(
            "pagespeed_analyze",
            {
                "account_id": "pagespeed-main",
                "site_url": "https://example.com/",
                "page_url": "https://example.com/article",
                "strategy": "MOBILE",
                "categories": ["PERFORMANCE", "SEO"],
            },
        )
        assert json.loads(pagespeed.content[0].text) == {  # type: ignore[union-attr]
            "analyzed_url": "https://example.com/article",
            "analysis_utc_timestamp": "2026-07-30T17:00:00+00:00",
            "categories": [{"category": "performance", "score": 0.95}],
            "loading_experience_category": None,
            "origin_loading_experience_category": None,
        }
        invalid_pagespeed = await client.call_tool(
            "pagespeed_analyze",
            {
                "account_id": "pagespeed-main",
                "site_url": "https://example.com/",
                "page_url": "https://example.com/article",
                "strategy": "INVALID",
            },
        )
        assert invalid_pagespeed.isError is True
        assert json.loads(invalid_pagespeed.content[0].text)["code"] == "TOOL_INPUT_INVALID"  # type: ignore[union-attr]
        extra_pagespeed = await client.call_tool(
            "pagespeed_analyze",
            {
                "account_id": "pagespeed-main",
                "site_url": "https://example.com/",
                "page_url": "https://example.com/article",
                "unexpected": True,
            },
        )
        assert extra_pagespeed.isError is True
        assert json.loads(extra_pagespeed.content[0].text)["code"] == "TOOL_INPUT_INVALID"  # type: ignore[union-attr]
        outside_pagespeed = await client.call_tool(
            "pagespeed_analyze",
            {
                "account_id": "pagespeed-main",
                "site_url": "https://example.com/",
                "page_url": "https://outside.example.com/article",
            },
        )
        assert outside_pagespeed.isError is True
        assert json.loads(outside_pagespeed.content[0].text)["code"] == "TOOL_REQUEST_REJECTED"  # type: ignore[union-attr]
        bing_keyword_statistics = await client.call_tool(
            "bing_keyword_statistics",
            {
                "account_id": "bing-main",
                "query": "rankrat",
            },
        )
        assert json.loads(bing_keyword_statistics.content[0].text) == {"points": []}  # type: ignore[union-attr]
        bing_related_keywords = await client.call_tool(
            "bing_related_keywords",
            {
                "account_id": "bing-main",
                "query": "rankrat",
                "start_date": "2026-07-01",
                "end_date": "2026-07-02",
            },
        )
        assert json.loads(bing_related_keywords.content[0].text) == {"keywords": []}  # type: ignore[union-attr]
        malformed_related_keywords = await client.call_tool(
            "bing_related_keywords",
            {
                "account_id": "bing-main",
                "query": "rankrat",
                "start_date": "2026-07-01",
                "end_date": "2026-07-02",
                "operation": "GetRelatedKeywords",
            },
        )
        assert malformed_related_keywords.isError is True
        malformed_related_keywords_content = malformed_related_keywords.content[0]
        assert isinstance(malformed_related_keywords_content, types.TextContent)
        assert json.loads(malformed_related_keywords_content.text)["code"] == "TOOL_INPUT_INVALID"
        bing_traffic_trend = await client.call_tool(
            "bing_traffic_trend",
            {
                "account_id": "bing-main",
                "site_url": "https://example.com/",
                "start_date": "2026-07-01",
                "end_date": "2026-07-02",
            },
        )
        assert json.loads(bing_traffic_trend.content[0].text) == {"points": []}  # type: ignore[union-attr]
        bing_traffic_anomalies = await client.call_tool(
            "bing_traffic_anomalies",
            {
                "account_id": "bing-main",
                "site_url": "https://example.com/",
                "start_date": "2026-07-01",
                "end_date": "2026-07-02",
            },
        )
        assert json.loads(bing_traffic_anomalies.content[0].text) == {"anomalies": []}  # type: ignore[union-attr]
        bing_traffic_comparison = await client.call_tool(
            "bing_traffic_comparison",
            {
                "account_id": "bing-main",
                "site_url": "https://example.com/",
                "start_date": "2026-07-01",
                "end_date": "2026-07-02",
                "previous_start_date": "2026-06-29",
                "previous_end_date": "2026-06-30",
            },
        )
        assert json.loads(bing_traffic_comparison.content[0].text)["clicks_delta"] == 2.0  # type: ignore[union-attr]
        for tool_name in ("bing_query_performance", "bing_page_performance"):
            bing_performance = await client.call_tool(
                tool_name,
                {
                    "account_id": "bing-main",
                    "site_url": "https://example.com/",
                },
            )
            performance_content = bing_performance.content[0]
            assert isinstance(performance_content, types.TextContent)
            performance_payload = json.loads(performance_content.text)
            assert performance_payload["rows"][0]["label"] == "rankrat"
            assert performance_payload["rows"][0]["average_click_position"] is None
            malformed_bing_performance = await client.call_tool(
                tool_name,
                {
                    "account_id": "bing-main",
                    "site_url": "https://example.com/",
                    "unexpected": True,
                },
            )
            assert malformed_bing_performance.isError is True
            malformed_performance_content = malformed_bing_performance.content[0]
            assert isinstance(malformed_performance_content, types.TextContent)
            assert json.loads(malformed_performance_content.text)["code"] == "TOOL_INPUT_INVALID"
        bing_brand_analysis = await client.call_tool(
            "bing_brand_analysis",
            {
                "account_id": "bing-main",
                "site_url": "https://example.com/",
                "brand_terms": ["rankrat"],
            },
        )
        assert json.loads(bing_brand_analysis.content[0].text)["brand_rows"][0]["label"] == (  # type: ignore[union-attr]
            "rankrat documentation"
        )
        malformed_bing_brand_analysis = await client.call_tool(
            "bing_brand_analysis",
            {
                "account_id": "bing-main",
                "site_url": "https://example.com/",
                "brand_terms": ["rankrat"],
                "unexpected": True,
            },
        )
        assert malformed_bing_brand_analysis.isError is True
        malformed_brand_analysis_content = malformed_bing_brand_analysis.content[0]
        assert isinstance(malformed_brand_analysis_content, types.TextContent)
        assert json.loads(malformed_brand_analysis_content.text)["code"] == "TOOL_INPUT_INVALID"
        bing_ranking_buckets = await client.call_tool(
            "bing_ranking_buckets",
            {
                "account_id": "bing-main",
                "site_url": "https://example.com/",
            },
        )
        assert json.loads(bing_ranking_buckets.content[0].text)["buckets"][0]["kind"] == (  # type: ignore[union-attr]
            "top_three"
        )
        malformed_bing_ranking_buckets = await client.call_tool(
            "bing_ranking_buckets",
            {
                "account_id": "bing-main",
                "site_url": "https://example.com/",
                "threshold": 3,
            },
        )
        assert malformed_bing_ranking_buckets.isError is True
        malformed_ranking_buckets_content = malformed_bing_ranking_buckets.content[0]
        assert isinstance(malformed_ranking_buckets_content, types.TextContent)
        assert json.loads(malformed_ranking_buckets_content.text)["code"] == "TOOL_INPUT_INVALID"
        for tool_name in ("bing_query_opportunities", "bing_page_opportunities"):
            bing_opportunities = await client.call_tool(
                tool_name,
                {
                    "account_id": "bing-main",
                    "site_url": "https://example.com/",
                },
            )
            assert (
                json.loads(bing_opportunities.content[0].text)["opportunities"][0]["row"][  # type: ignore[union-attr]
                    "label"
                ]
                == "rankrat"
            )
            malformed_bing_opportunities = await client.call_tool(
                tool_name,
                {
                    "account_id": "bing-main",
                    "site_url": "https://example.com/",
                    "unexpected": True,
                },
            )
            assert malformed_bing_opportunities.isError is True
            malformed_opportunities_content = malformed_bing_opportunities.content[0]
            assert isinstance(malformed_opportunities_content, types.TextContent)
            assert json.loads(malformed_opportunities_content.text)["code"] == "TOOL_INPUT_INVALID"
        for tool_name, detail_arguments in (
            ("bing_query_page_performance", {"query": "rankrat"}),
            ("bing_page_query_performance", {"page_url": "https://example.com/page"}),
        ):
            bing_performance = await client.call_tool(
                tool_name,
                {
                    "account_id": "bing-main",
                    "site_url": "https://example.com/",
                    **detail_arguments,
                },
            )
            assert json.loads(bing_performance.content[0].text)["rows"][0]["label"] == "rankrat"  # type: ignore[union-attr]
            malformed_bing_performance = await client.call_tool(
                tool_name,
                {
                    "account_id": "bing-main",
                    "site_url": "https://example.com/",
                    "unexpected": True,
                    **detail_arguments,
                },
            )
            assert malformed_bing_performance.isError is True
            malformed_performance_content = malformed_bing_performance.content[0]
            assert isinstance(malformed_performance_content, types.TextContent)
            assert json.loads(malformed_performance_content.text)["code"] == "TOOL_INPUT_INVALID"
        bing_cannibalization = await client.call_tool(
            "bing_query_cannibalization",
            {
                "account_id": "bing-main",
                "site_url": "https://example.com/",
                "query": "rankrat",
            },
        )
        assert json.loads(bing_cannibalization.content[0].text)["pages"][0]["label"] == (  # type: ignore[union-attr]
            "https://example.com/a"
        )
        malformed_bing_cannibalization = await client.call_tool(
            "bing_query_cannibalization",
            {
                "account_id": "bing-main",
                "site_url": "https://example.com/",
                "query": "rankrat",
                "unexpected": True,
            },
        )
        assert malformed_bing_cannibalization.isError is True
        malformed_cannibalization_content = malformed_bing_cannibalization.content[0]
        assert isinstance(malformed_cannibalization_content, types.TextContent)
        assert json.loads(malformed_cannibalization_content.text)["code"] == "TOOL_INPUT_INVALID"
        bing_url_submission_quota = await client.call_tool(
            "bing_url_submission_quota",
            {
                "account_id": "bing-main",
                "site_url": "https://example.com/",
            },
        )
        assert json.loads(bing_url_submission_quota.content[0].text) == {"daily": 5, "monthly": 24}  # type: ignore[union-attr]
        malformed_bing_url_submission_quota = await client.call_tool(
            "bing_url_submission_quota",
            {
                "account_id": "bing-main",
                "site_url": "https://example.com/",
                "unexpected": True,
            },
        )
        assert malformed_bing_url_submission_quota.isError is True
        malformed_quota_content = malformed_bing_url_submission_quota.content[0]
        assert isinstance(malformed_quota_content, types.TextContent)
        assert json.loads(malformed_quota_content.text)["code"] == "TOOL_INPUT_INVALID"
        bing_crawl_issues = await client.call_tool(
            "bing_crawl_issues",
            {"account_id": "bing-main", "site_url": "https://example.com/"},
        )
        assert json.loads(bing_crawl_issues.content[0].text)["issues"][0]["http_code"] == 404  # type: ignore[union-attr]
        bing_crawl_stats = await client.call_tool(
            "bing_crawl_stats",
            {"account_id": "bing-main", "site_url": "https://example.com/"},
        )
        assert json.loads(bing_crawl_stats.content[0].text)["points"][0]["code_2xx"] == 1  # type: ignore[union-attr]
        malformed_bing_crawl_stats = await client.call_tool(
            "bing_crawl_stats",
            {"account_id": "bing-main", "site_url": "https://example.com/", "unexpected": True},
        )
        assert malformed_bing_crawl_stats.isError is True
        malformed_crawl_stats_content = malformed_bing_crawl_stats.content[0]
        assert isinstance(malformed_crawl_stats_content, types.TextContent)
        assert json.loads(malformed_crawl_stats_content.text)["code"] == "TOOL_INPUT_INVALID"
        bing_feeds = await client.call_tool(
            "bing_feeds",
            {"account_id": "bing-main", "site_url": "https://example.com/"},
        )
        assert json.loads(bing_feeds.content[0].text)["feeds"][0]["url_count"] == 3  # type: ignore[union-attr]
        bing_link_counts = await client.call_tool(
            "bing_link_counts",
            {"account_id": "bing-main", "site_url": "https://example.com/", "page": 1},
        )
        assert json.loads(bing_link_counts.content[0].text)["links"][0]["count"] == 3  # type: ignore[union-attr]
        malformed_bing_link_counts = await client.call_tool(
            "bing_link_counts",
            {"account_id": "bing-main", "site_url": "https://example.com/", "page": -1},
        )
        assert malformed_bing_link_counts.isError is True
        bing_url_information = await client.call_tool(
            "bing_url_information",
            {
                "account_id": "bing-main",
                "site_url": "https://example.com/",
                "page_url": "https://example.com/article",
            },
        )
        assert json.loads(bing_url_information.content[0].text)["http_status"] is None  # type: ignore[union-attr]
        malformed_bing_url_information = await client.call_tool(
            "bing_url_information",
            {
                "account_id": "bing-main",
                "site_url": "https://example.com/",
                "page_url": "https://example.com/article",
                "unexpected": True,
            },
        )
        assert malformed_bing_url_information.isError is True
        malformed_bing_traffic = await client.call_tool(
            "bing_traffic_trend",
            {
                "account_id": "bing-main",
                "site_url": "https://example.com/",
                "start_date": "2026-07-01",
                "end_date": "2026-07-02",
                "unexpected": True,
            },
        )
        assert malformed_bing_traffic.isError is True
        assert json.loads(malformed_bing_traffic.content[0].text)["code"] == "TOOL_INPUT_INVALID"  # type: ignore[union-attr]
        invalid_bing_comparison = await client.call_tool(
            "bing_traffic_comparison",
            {
                "account_id": "bing-main",
                "site_url": "https://example.com/",
                "start_date": "2026-07-01",
                "end_date": "2026-07-02",
                "previous_start_date": "2026-06-30",
                "previous_end_date": "2026-06-29",
            },
        )
        assert invalid_bing_comparison.isError is True
        comparison_content = invalid_bing_comparison.content[0]
        assert isinstance(comparison_content, types.TextContent)
        assert json.loads(comparison_content.text)["code"] == "TOOL_REQUEST_REJECTED"
        invalid = await client.call_tool("accounts_list", {"unexpected": True})
        assert invalid.isError is True
        assert json.loads(invalid.content[0].text)["code"] == "TOOL_INPUT_INVALID"  # type: ignore[union-attr]
        missing = await client.call_tool("sites_list", {"account_id": "missing"})
        assert missing.isError is True
        assert json.loads(missing.content[0].text)["code"] == "TOOL_REQUEST_REJECTED"  # type: ignore[union-attr]
        unknown = await client.call_tool("does_not_exist", {})
        assert unknown.isError is True
        assert json.loads(unknown.content[0].text)["code"] == "TOOL_NOT_FOUND"  # type: ignore[union-attr]


@pytest.mark.parametrize("failure_code", list(ProviderFailureCode))
@pytest.mark.asyncio
async def test_mcp_provider_errors_preserve_only_the_safe_failure_category(
    deployment: tuple[Settings, ApplicationServices],
    monkeypatch: pytest.MonkeyPatch,
    failure_code: ProviderFailureCode,
) -> None:
    _, services = deployment
    upstream_detail = "upstream credential and response must not cross the MCP boundary"

    async def fail(*_: object) -> ProviderReadiness:
        raise ProviderOperationError(failure_code, upstream_detail)

    monkeypatch.setattr(services.provider_readiness, "readiness", fail)
    server = build_mcp_server(services)
    async with create_connected_server_and_client_session(server) as client:
        result = await client.call_tool(
            "provider_readiness",
            {"account_id": "google-main"},
        )

    assert result.isError is True
    content = result.content[0]
    assert isinstance(content, types.TextContent)
    assert json.loads(content.text) == {
        "code": failure_code.value,
        "message": "provider operation failed",
    }
    assert upstream_detail not in content.text


@pytest.mark.asyncio
async def test_mcp_write_contract_when_read_only_is_disabled(
    indexnow_deployment: tuple[Settings, ApplicationServices],
) -> None:
    _, services = indexnow_deployment
    assert services.indexnow is not None
    server = build_mcp_server(services)
    async with create_connected_server_and_client_session(server) as client:
        tools = await client.list_tools()
        indexnow = next(tool for tool in tools.tools if tool.name == "indexnow_submit")
        bing_submission = next(tool for tool in tools.tools if tool.name == "bing_url_submit")
        bing_sitemap_submission = next(
            tool for tool in tools.tools if tool.name == "bing_sitemap_submit"
        )
        assert indexnow.annotations is not None
        assert indexnow.annotations.readOnlyHint is False
        assert indexnow.annotations.destructiveHint is True
        assert indexnow.annotations.idempotentHint is False
        assert indexnow.annotations.openWorldHint is False
        assert indexnow.inputSchema["required"] == ["target_id", "urls"]
        assert bing_submission.annotations is not None
        assert bing_submission.annotations.readOnlyHint is False
        assert bing_sitemap_submission.annotations is not None
        assert bing_sitemap_submission.annotations.readOnlyHint is False
        assert bing_sitemap_submission.annotations.destructiveHint is True

        async def mock_bing_submission(*_: object) -> None:
            return None

        services.bing_webmaster._client.submit_url_batch = mock_bing_submission  # type: ignore[method-assign, assignment]

        async def mock_bing_sitemap_submission(*_: object) -> None:
            return None

        services.bing_webmaster._client.submit_feed = mock_bing_sitemap_submission  # type: ignore[method-assign, assignment]

        accepted = await client.call_tool(
            "indexnow_submit",
            {
                "target_id": "site-main",
                "urls": ["https://example.com/article"],
            },
        )
        payload = json.loads(accepted.content[0].text)  # type: ignore[union-attr]
        assert payload["submitted_count"] == 1

        bing_accepted = await client.call_tool(
            "bing_url_submit",
            {
                "account_id": "bing-main",
                "site_url": "https://example.com/",
                "urls": ["https://example.com/article"],
            },
        )
        assert json.loads(bing_accepted.content[0].text)["submitted_count"] == 1  # type: ignore[union-attr]

        bing_sitemap_accepted = await client.call_tool(
            "bing_sitemap_submit",
            {
                "account_id": "bing-main",
                "site_url": "https://example.com/",
                "sitemap_url": "https://example.com/sitemap.xml",
                "operation": "submit",
            },
        )
        assert json.loads(bing_sitemap_accepted.content[0].text) == {  # type: ignore[union-attr]
            "account_id": "bing-main",
            "site_url": "https://example.com/",
            "operation": "submit",
        }

        invalid = await client.call_tool(
            "indexnow_submit",
            {
                "target_id": "site-main",
                "urls": ["http://example.com/article"],
            },
        )
        assert invalid.isError is True
        assert json.loads(invalid.content[0].text)["code"] == "TOOL_REQUEST_REJECTED"  # type: ignore[union-attr]
