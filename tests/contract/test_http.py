from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Protocol, cast

import httpx
import pytest
from fastapi import FastAPI
from starlette.types import Message, Receive, Scope, Send

from rankrat.config import Settings
from rankrat.errors import InputLimitError
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
from rankrat.transports.http import _BodyLimitASGI, create_http_app
from rankrat.transports.runtime import ApplicationServices


class _WrappedApp(Protocol):
    _app: object


def _unwrap_fastapi(app: object) -> FastAPI:
    current = app
    while not isinstance(current, FastAPI):
        current = cast(_WrappedApp, current)._app
    return current


@pytest.mark.asyncio
async def test_http_rest_contract_and_security_headers(
    deployment: tuple[Settings, ApplicationServices],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings, services = deployment

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
        return {
            "issues": [
                {
                    "url": "https://example.com/missing",
                    "http_code": 404,
                    "issues": 1,
                    "in_links": 2,
                }
            ]
        }

    async def mock_bing_crawl_stats(*_: object) -> dict[str, object]:
        return {
            "points": [
                {
                    "day": "2026-07-01",
                    "all_other_codes": 0,
                    "blocked_by_robots_txt": 0,
                    "code_2xx": 1,
                    "code_301": 0,
                    "code_302": 0,
                    "code_4xx": 0,
                    "code_5xx": 0,
                    "contains_malware": 0,
                    "connection_timeout": None,
                    "crawl_errors": 0,
                    "crawled_pages": 1,
                    "dns_failures": None,
                    "in_index": 1,
                    "in_links": 1,
                }
            ]
        }

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
    monkeypatch.setattr(services.google_analytics, "content_performance", mock_ga4_fixed_report)
    monkeypatch.setattr(
        services.google_analytics,
        "landing_page_performance",
        mock_ga4_fixed_report,
    )
    monkeypatch.setattr(
        services.google_analytics,
        "organic_search_landing_pages",
        mock_ga4_fixed_report,
    )
    monkeypatch.setattr(
        services.google_analytics,
        "traffic_source_performance",
        mock_ga4_fixed_report,
    )
    monkeypatch.setattr(
        services.google_analytics,
        "ecommerce_performance",
        mock_ga4_fixed_report,
    )
    monkeypatch.setattr(
        services.google_analytics,
        "audience_segments",
        mock_ga4_fixed_report,
    )
    monkeypatch.setattr(
        services.google_analytics,
        "user_behavior",
        mock_ga4_fixed_report,
    )
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
    app = create_http_app(settings, services)
    request_id = str(uuid.uuid4())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://rankrat.test",
    ) as client:
        health = await client.get("/healthz", headers={"x-request-id": request_id})
        assert health.status_code == 200
        assert health.headers["x-request-id"] == request_id
        assert health.headers["x-content-type-options"] == "nosniff"
        assert health.headers["x-frame-options"] == "DENY"

        generated = await client.get("/v1/server-info", headers={"x-request-id": "bad"})
        assert generated.status_code == 200
        uuid.UUID(generated.headers["x-request-id"])
        assert generated.json()["read_only"] is True

        accounts = await client.get("/v1/accounts", params={"provider": "google"})
        assert accounts.json()["accounts"][0]["account_id"] == "google-main"
        sites = await client.get("/v1/sites", params={"account_id": "bing-main"})
        assert sites.json()["sites"][0]["resource"] == "https://example.com/"
        readiness = await client.get(
            "/v1/provider-readiness",
            params={"account_id": "bing-main"},
        )
        assert readiness.json()["available"] is True
        assert (await client.get("/ready")).json()["ready"] is True
        provider_error = await client.get(
            "/v1/provider-readiness",
            params={"account_id": "google-main"},
        )
        assert provider_error.status_code == 502
        assert provider_error.json() == {
            "code": "AUTHENTICATION",
            "message": "provider operation failed",
        }

        analytics_response = await client.post(
            "/v1/google/search-analytics-queries",
            json={
                "account_id": "google-main",
                "site_url": "sc-domain:example.com",
                "start_date": "2026-07-01",
                "end_date": "2026-07-02",
                "dimensions": [],
                "filters": [],
            },
        )
        assert analytics_response.json() == {"rows": [], "aggregation_type": None}
        summary_response = await client.post(
            "/v1/google/search-analytics-summary",
            json={
                "account_id": "google-main",
                "site_url": "sc-domain:example.com",
                "start_date": "2026-07-01",
                "end_date": "2026-07-02",
            },
        )
        comparison_response = await client.post(
            "/v1/google/search-analytics-comparison",
            json={
                "account_id": "google-main",
                "site_url": "sc-domain:example.com",
                "start_date": "2026-07-01",
                "end_date": "2026-07-02",
                "previous_start_date": "2026-06-29",
                "previous_end_date": "2026-06-30",
            },
        )
        dimension_report_response = await client.post(
            "/v1/google/search-analytics-dimension-report",
            json={
                "account_id": "google-main",
                "site_url": "sc-domain:example.com",
                "report": "top_queries",
                "start_date": "2026-07-01",
                "end_date": "2026-07-02",
            },
        )
        drop_attribution_response = await client.post(
            "/v1/google/search-analytics-drop-attribution",
            json={
                "account_id": "google-main",
                "site_url": "sc-domain:example.com",
                "attribution": "queries",
                "start_date": "2026-07-01",
                "end_date": "2026-07-02",
                "previous_start_date": "2026-06-29",
                "previous_end_date": "2026-06-30",
            },
        )
        trend_response = await client.post(
            "/v1/google/search-analytics-trend",
            json={
                "account_id": "google-main",
                "site_url": "sc-domain:example.com",
                "start_date": "2026-07-01",
                "end_date": "2026-07-02",
            },
        )
        anomalies_response = await client.post(
            "/v1/google/search-analytics-anomalies",
            json={
                "account_id": "google-main",
                "site_url": "sc-domain:example.com",
                "start_date": "2026-07-01",
                "end_date": "2026-07-02",
            },
        )
        page_performance_response = await client.post(
            "/v1/google/search-analytics-page-performance",
            json={
                "account_id": "google-main",
                "site_url": "sc-domain:example.com",
                "start_date": "2026-07-01",
                "end_date": "2026-07-02",
            },
        )
        assert summary_response.json()["clicks"] == 1.0
        assert comparison_response.json()["clicks_delta"] == 1.0
        assert dimension_report_response.json() == {"rows": [], "has_more": False}
        assert drop_attribution_response.json() == {"rows": [], "has_more": False}
        assert trend_response.json() == {"points": [], "has_more": False}
        assert anomalies_response.json() == {"anomalies": [], "has_more": False}
        assert page_performance_response.json() == {"rows": [], "has_more": False}
        for path in (
            "/v1/google-analytics/content-performance",
            "/v1/google-analytics/landing-page-performance",
            "/v1/google-analytics/organic-search-landing-pages",
            "/v1/google-analytics/traffic-source-performance",
        ):
            fixed_report_response = await client.post(
                path,
                json={
                    "account_id": "google-main",
                    "property_id": "123456789",
                    "start_date": "2026-07-01",
                    "end_date": "2026-07-02",
                },
            )
            assert fixed_report_response.json()["report"] == {"rows": []}
            malformed_fixed_report = await client.post(
                path,
                json={
                    "account_id": "google-main",
                    "property_id": "123456789",
                    "start_date": "2026-07-01",
                    "end_date": "2026-07-02",
                    "dimensions": ["country"],
                },
            )
            assert malformed_fixed_report.status_code == 422
            assert malformed_fixed_report.json()["code"] == "VALIDATION_FAILED"
        indexing_metadata_response = await client.post(
            "/v1/google-indexing-metadata",
            json={
                "account_id": "google-main",
                "site_url": "sc-domain:example.com",
                "url": "https://example.com/jobs/one",
            },
        )
        assert indexing_metadata_response.json() == {
            "url": "https://example.com/jobs/one",
            "latest_update": None,
            "latest_remove": None,
        }
        schema_html = await client.post(
            "/v1/schema/validate-html",
            json={
                "document": '<script type=\'application/ld+json\'>{"@type":"JobPosting"}</script>'
            },
        )
        schema_json = await client.post(
            "/v1/schema/validate-json-ld",
            json={"document": '{"@type":"JobPosting"}'},
        )
        schema_url = await client.post(
            "/v1/schema/validate-url",
            json={"url": "https://example.com/jobs"},
        )
        assert schema_html.json()["eligible"] is True
        assert schema_json.json()["eligible"] is True
        assert schema_url.json() == {
            "url": "https://example.com/jobs",
            "eligibility": {
                "eligible": True,
                "reason": "page contains JobPosting structured data",
            },
        }
        malformed_summary = await client.post(
            "/v1/google/search-analytics-summary",
            json={
                "account_id": "google-main",
                "site_url": "sc-domain:example.com",
                "start_date": "2026-07-01",
                "end_date": "2026-07-02",
                "unexpected": True,
            },
        )
        assert malformed_summary.status_code == 422
        assert malformed_summary.json()["code"] == "VALIDATION_FAILED"
        malformed_schema = await client.post(
            "/v1/schema/validate-html",
            json={"document": "<html />", "unexpected": True},
        )
        assert malformed_schema.status_code == 422
        malformed_schema_url = await client.post(
            "/v1/schema/validate-url",
            json={"url": "https://example.com/jobs", "unexpected": True},
        )
        assert malformed_schema_url.status_code == 422
        invalid_schema_url_timeout = await client.post(
            "/v1/schema/validate-url",
            json={"url": "https://example.com/jobs", "timeout_seconds": 0},
        )
        assert invalid_schema_url_timeout.status_code == 422
        excessive_schema_url_timeout = await client.post(
            "/v1/schema/validate-url",
            json={"url": "https://example.com/jobs", "timeout_seconds": 30.1},
        )
        assert excessive_schema_url_timeout.status_code == 422
        malformed_dimension_report = await client.post(
            "/v1/google/search-analytics-dimension-report",
            json={
                "account_id": "google-main",
                "site_url": "sc-domain:example.com",
                "report": "top_queries",
                "start_date": "2026-07-01",
                "end_date": "2026-07-02",
                "dimensions": ["query"],
            },
        )
        assert malformed_dimension_report.status_code == 422
        malformed_drop_attribution = await client.post(
            "/v1/google/search-analytics-drop-attribution",
            json={
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
        assert malformed_drop_attribution.status_code == 422
        for path in (
            "/v1/google/search-analytics-trend",
            "/v1/google/search-analytics-anomalies",
            "/v1/google/search-analytics-page-performance",
        ):
            malformed_derived_report = await client.post(
                path,
                json={
                    "account_id": "google-main",
                    "site_url": "sc-domain:example.com",
                    "start_date": "2026-07-01",
                    "end_date": "2026-07-02",
                    "unexpected": True,
                },
            )
            assert malformed_derived_report.status_code == 422
            assert malformed_derived_report.json()["code"] == "VALIDATION_FAILED"
        invalid_comparison = await client.post(
            "/v1/google/search-analytics-comparison",
            json={
                "account_id": "google-main",
                "site_url": "sc-domain:example.com",
                "start_date": "2026-07-01",
                "end_date": "2026-07-02",
                "previous_start_date": "2026-06-30",
                "previous_end_date": "2026-06-29",
            },
        )
        assert invalid_comparison.status_code == 400
        assert invalid_comparison.json()["code"] == "REQUEST_REJECTED"
        invalid_drop_attribution = await client.post(
            "/v1/google/search-analytics-drop-attribution",
            json={
                "account_id": "google-main",
                "site_url": "sc-domain:example.com",
                "attribution": "queries",
                "start_date": "2026-07-01",
                "end_date": "2026-07-02",
                "previous_start_date": "2026-06-30",
                "previous_end_date": "2026-06-29",
            },
        )
        assert invalid_drop_attribution.status_code == 400
        assert invalid_drop_attribution.json()["code"] == "REQUEST_REJECTED"
        for path in (
            "/v1/google/search-analytics-trend",
            "/v1/google/search-analytics-anomalies",
            "/v1/google/search-analytics-page-performance",
        ):
            invalid_derived_report = await client.post(
                path,
                json={
                    "account_id": "google-main",
                    "site_url": "sc-domain:example.com",
                    "start_date": "2026-07-02",
                    "end_date": "2026-07-01",
                },
            )
            assert invalid_derived_report.status_code == 400
            assert invalid_derived_report.json()["code"] == "REQUEST_REJECTED"
        google_sites_response = await client.get(
            "/v1/google/sites",
            params={"account_id": "google-main"},
        )
        assert google_sites_response.json() == ["sc-domain:example.com"]
        google_site_response = await client.get(
            "/v1/google/site",
            params={"account_id": "google-main", "site_url": "sc-domain:example.com"},
        )
        assert google_site_response.json() == {
            "site_url": "sc-domain:example.com",
            "permission_level": "siteOwner",
        }
        sitemaps_response = await client.get(
            "/v1/google/sitemaps",
            params={"account_id": "google-main", "site_url": "sc-domain:example.com"},
        )
        assert sitemaps_response.json() == {"sitemaps": []}
        sitemap_response = await client.get(
            "/v1/google/sitemap",
            params={
                "account_id": "google-main",
                "site_url": "sc-domain:example.com",
                "sitemap_url": "https://example.com/sitemap.xml",
            },
        )
        assert sitemap_response.json() == {
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
        inspection_response = await client.post(
            "/v1/google/url-inspections",
            json={
                "account_id": "google-main",
                "site_url": "sc-domain:example.com",
                "inspection_url": "https://example.com/article",
            },
        )
        assert inspection_response.json() == {
            "inspection_result_link": None,
            "index_status": None,
        }
        inspection_batch_response = await client.post(
            "/v1/google/url-inspection-batches",
            json={
                "account_id": "google-main",
                "site_url": "sc-domain:example.com",
                "inspection_urls": ["https://example.com/article"],
            },
        )
        assert inspection_batch_response.json() == [
            {"inspection_result_link": None, "index_status": None}
        ]
        ga4_report = await client.post(
            "/v1/google-analytics/reports",
            json={
                "account_id": "google-main",
                "property_id": "123456789",
                "date_ranges": [{"start_date": "2026-07-01", "end_date": "2026-07-02"}],
                "dimensions": ["pagePath"],
                "metrics": ["screenPageViews"],
            },
        )
        assert ga4_report.json() == {
            "dimension_headers": [],
            "metric_headers": [],
            "rows": [],
            "row_count": 0,
        }
        ga4_realtime = await client.post(
            "/v1/google-analytics/realtime-reports",
            json={
                "account_id": "google-main",
                "property_id": "123456789",
                "dimensions": ["country"],
                "metrics": ["activeUsers"],
            },
        )
        assert ga4_realtime.json() == {
            "dimension_headers": [],
            "metric_headers": [],
            "rows": [],
            "row_count": 0,
        }
        ga4_ecommerce = await client.post(
            "/v1/google-analytics/ecommerce-performance",
            json={
                "account_id": "google-main",
                "property_id": "123456789",
                "start_date": "2026-07-01",
                "end_date": "2026-07-02",
            },
        )
        assert ga4_ecommerce.json() == {"kind": "content_performance", "report": {"rows": []}}
        malformed_ga4_ecommerce = await client.post(
            "/v1/google-analytics/ecommerce-performance",
            json={
                "account_id": "google-main",
                "property_id": "123456789",
                "start_date": "2026-07-01",
                "end_date": "2026-07-02",
                "metrics": ["itemsPurchased"],
            },
        )
        assert malformed_ga4_ecommerce.status_code == 422
        assert malformed_ga4_ecommerce.json()["code"] == "VALIDATION_FAILED"
        ga4_audience_segments = await client.post(
            "/v1/google-analytics/audience-segments",
            json={
                "account_id": "google-main",
                "property_id": "123456789",
                "start_date": "2026-07-01",
                "end_date": "2026-07-02",
            },
        )
        assert ga4_audience_segments.json() == {
            "kind": "content_performance",
            "report": {"rows": []},
        }
        malformed_ga4_audience_segments = await client.post(
            "/v1/google-analytics/audience-segments",
            json={
                "account_id": "google-main",
                "property_id": "123456789",
                "start_date": "2026-07-01",
                "end_date": "2026-07-02",
                "filter": "arbitrary",
            },
        )
        assert malformed_ga4_audience_segments.status_code == 422
        assert malformed_ga4_audience_segments.json()["code"] == "VALIDATION_FAILED"
        ga4_user_behavior = await client.post(
            "/v1/google-analytics/user-behavior",
            json={
                "account_id": "google-main",
                "property_id": "123456789",
                "start_date": "2026-07-01",
                "end_date": "2026-07-02",
            },
        )
        assert ga4_user_behavior.json() == {
            "kind": "content_performance",
            "report": {"rows": []},
        }
        malformed_ga4_user_behavior = await client.post(
            "/v1/google-analytics/user-behavior",
            json={
                "account_id": "google-main",
                "property_id": "123456789",
                "start_date": "2026-07-01",
                "end_date": "2026-07-02",
                "dimension": "newVsReturning",
            },
        )
        assert malformed_ga4_user_behavior.status_code == 422
        assert malformed_ga4_user_behavior.json()["code"] == "VALIDATION_FAILED"
        ga4_conversion_funnel = await client.post(
            "/v1/google-analytics/conversion-funnels",
            json={
                "account_id": "google-main",
                "property_id": "123456789",
                "start_date": "2026-07-01",
                "end_date": "2026-07-02",
                "event_names": ["view_item", "purchase"],
            },
        )
        assert ga4_conversion_funnel.json() == {
            "funnel_table": {"rows": []},
            "funnel_visualization": {"rows": []},
        }
        malformed_ga4_conversion_funnel = await client.post(
            "/v1/google-analytics/conversion-funnels",
            json={
                "account_id": "google-main",
                "property_id": "123456789",
                "start_date": "2026-07-01",
                "end_date": "2026-07-02",
                "event_names": ["view_item"],
            },
        )
        assert malformed_ga4_conversion_funnel.status_code == 422
        assert malformed_ga4_conversion_funnel.json()["code"] == "VALIDATION_FAILED"
        pagespeed = await client.post(
            "/v1/pagespeed/analyses",
            json={
                "account_id": "pagespeed-main",
                "site_url": "https://example.com/",
                "page_url": "https://example.com/article",
                "strategy": "MOBILE",
                "categories": ["PERFORMANCE", "SEO"],
            },
        )
        assert pagespeed.json() == {
            "analyzed_url": "https://example.com/article",
            "analysis_utc_timestamp": "2026-07-30T17:00:00+00:00",
            "categories": [{"category": "performance", "score": 0.95}],
            "loading_experience_category": None,
            "origin_loading_experience_category": None,
        }
        invalid_pagespeed = await client.post(
            "/v1/pagespeed/analyses",
            json={
                "account_id": "pagespeed-main",
                "site_url": "https://example.com/",
                "page_url": "https://example.com/article",
                "strategy": "INVALID",
            },
        )
        assert invalid_pagespeed.status_code == 422
        assert invalid_pagespeed.json()["code"] == "VALIDATION_FAILED"
        extra_pagespeed = await client.post(
            "/v1/pagespeed/analyses",
            json={
                "account_id": "pagespeed-main",
                "site_url": "https://example.com/",
                "page_url": "https://example.com/article",
                "unexpected": True,
            },
        )
        assert extra_pagespeed.status_code == 422
        assert extra_pagespeed.json()["code"] == "VALIDATION_FAILED"
        outside_pagespeed = await client.post(
            "/v1/pagespeed/analyses",
            json={
                "account_id": "pagespeed-main",
                "site_url": "https://example.com/",
                "page_url": "https://outside.example.com/article",
            },
        )
        assert outside_pagespeed.status_code == 400
        assert outside_pagespeed.json()["code"] == "REQUEST_REJECTED"
        bing_keyword_statistics = await client.post(
            "/v1/bing/keyword-statistics",
            json={
                "account_id": "bing-main",
                "query": "rankrat",
            },
        )
        assert bing_keyword_statistics.json() == {"points": []}
        bing_related_keywords = await client.post(
            "/v1/bing/related-keywords",
            json={
                "account_id": "bing-main",
                "query": "rankrat",
                "start_date": "2026-07-01",
                "end_date": "2026-07-02",
            },
        )
        assert bing_related_keywords.json() == {"keywords": []}
        generic_keyword_read = await client.post(
            "/v1/bing/keyword-reads",
            json={"account_id": "bing-main", "query": "rankrat"},
        )
        assert generic_keyword_read.status_code == 404
        malformed_related_keywords = await client.post(
            "/v1/bing/related-keywords",
            json={
                "account_id": "bing-main",
                "query": "rankrat",
                "start_date": "2026-07-01",
                "end_date": "2026-07-02",
                "operation": "GetRelatedKeywords",
            },
        )
        assert malformed_related_keywords.status_code == 422
        assert malformed_related_keywords.json()["code"] == "VALIDATION_FAILED"
        bing_traffic_trend = await client.post(
            "/v1/bing/traffic-trend",
            json={
                "account_id": "bing-main",
                "site_url": "https://example.com/",
                "start_date": "2026-07-01",
                "end_date": "2026-07-02",
            },
        )
        assert bing_traffic_trend.json() == {"points": []}
        bing_traffic_anomalies = await client.post(
            "/v1/bing/traffic-anomalies",
            json={
                "account_id": "bing-main",
                "site_url": "https://example.com/",
                "start_date": "2026-07-01",
                "end_date": "2026-07-02",
            },
        )
        assert bing_traffic_anomalies.json() == {"anomalies": []}
        bing_traffic_comparison = await client.post(
            "/v1/bing/traffic-comparison",
            json={
                "account_id": "bing-main",
                "site_url": "https://example.com/",
                "start_date": "2026-07-01",
                "end_date": "2026-07-02",
                "previous_start_date": "2026-06-29",
                "previous_end_date": "2026-06-30",
            },
        )
        assert bing_traffic_comparison.json()["clicks_delta"] == 2.0
        for path in ("/v1/bing/query-performance", "/v1/bing/page-performance"):
            performance_response = await client.post(
                path,
                json={
                    "account_id": "bing-main",
                    "site_url": "https://example.com/",
                },
            )
            assert performance_response.json()["rows"][0]["label"] == "rankrat"
            assert performance_response.json()["rows"][0]["average_click_position"] is None
            malformed_performance = await client.post(
                path,
                json={
                    "account_id": "bing-main",
                    "site_url": "https://example.com/",
                    "unexpected": True,
                },
            )
            assert malformed_performance.status_code == 422
            assert malformed_performance.json()["code"] == "VALIDATION_FAILED"
        bing_brand_analysis = await client.post(
            "/v1/bing/brand-analysis",
            json={
                "account_id": "bing-main",
                "site_url": "https://example.com/",
                "brand_terms": ["rankrat"],
            },
        )
        assert bing_brand_analysis.json()["brand_rows"][0]["label"] == "rankrat documentation"
        malformed_bing_brand_analysis = await client.post(
            "/v1/bing/brand-analysis",
            json={
                "account_id": "bing-main",
                "site_url": "https://example.com/",
                "brand_terms": ["rankrat"],
                "unexpected": True,
            },
        )
        assert malformed_bing_brand_analysis.status_code == 422
        assert malformed_bing_brand_analysis.json()["code"] == "VALIDATION_FAILED"
        bing_ranking_buckets = await client.post(
            "/v1/bing/ranking-buckets",
            json={
                "account_id": "bing-main",
                "site_url": "https://example.com/",
            },
        )
        assert bing_ranking_buckets.json()["buckets"][0]["kind"] == "top_three"
        malformed_bing_ranking_buckets = await client.post(
            "/v1/bing/ranking-buckets",
            json={
                "account_id": "bing-main",
                "site_url": "https://example.com/",
                "threshold": 3,
            },
        )
        assert malformed_bing_ranking_buckets.status_code == 422
        assert malformed_bing_ranking_buckets.json()["code"] == "VALIDATION_FAILED"
        for path in ("/v1/bing/query-opportunities", "/v1/bing/page-opportunities"):
            opportunities_response = await client.post(
                path,
                json={
                    "account_id": "bing-main",
                    "site_url": "https://example.com/",
                },
            )
            assert opportunities_response.json()["opportunities"][0]["row"]["label"] == "rankrat"
            malformed_opportunities = await client.post(
                path,
                json={
                    "account_id": "bing-main",
                    "site_url": "https://example.com/",
                    "unexpected": True,
                },
            )
            assert malformed_opportunities.status_code == 422
            assert malformed_opportunities.json()["code"] == "VALIDATION_FAILED"
        detail_bodies = (
            ("/v1/bing/query-page-performance", {"query": "rankrat"}),
            ("/v1/bing/page-query-performance", {"page_url": "https://example.com/page"}),
        )
        for path, detail_body in detail_bodies:
            performance_response = await client.post(
                path,
                json={
                    "account_id": "bing-main",
                    "site_url": "https://example.com/",
                    **detail_body,
                },
            )
            assert performance_response.json()["rows"][0]["label"] == "rankrat"
            malformed_performance = await client.post(
                path,
                json={
                    "account_id": "bing-main",
                    "site_url": "https://example.com/",
                    "unexpected": True,
                    **detail_body,
                },
            )
            assert malformed_performance.status_code == 422
            assert malformed_performance.json()["code"] == "VALIDATION_FAILED"
        bing_cannibalization = await client.post(
            "/v1/bing/query-cannibalization",
            json={
                "account_id": "bing-main",
                "site_url": "https://example.com/",
                "query": "rankrat",
            },
        )
        assert bing_cannibalization.json()["pages"][0]["label"] == "https://example.com/a"
        malformed_bing_cannibalization = await client.post(
            "/v1/bing/query-cannibalization",
            json={
                "account_id": "bing-main",
                "site_url": "https://example.com/",
                "query": "rankrat",
                "unexpected": True,
            },
        )
        assert malformed_bing_cannibalization.status_code == 422
        assert malformed_bing_cannibalization.json()["code"] == "VALIDATION_FAILED"
        bing_url_submission_quota = await client.post(
            "/v1/bing/url-submission-quota",
            json={
                "account_id": "bing-main",
                "site_url": "https://example.com/",
            },
        )
        assert bing_url_submission_quota.json() == {"daily": 5, "monthly": 24}
        malformed_bing_url_submission_quota = await client.post(
            "/v1/bing/url-submission-quota",
            json={
                "account_id": "bing-main",
                "site_url": "https://example.com/",
                "unexpected": True,
            },
        )
        assert malformed_bing_url_submission_quota.status_code == 422
        assert malformed_bing_url_submission_quota.json()["code"] == "VALIDATION_FAILED"
        bing_crawl_issues = await client.post(
            "/v1/bing/crawl-issues",
            json={"account_id": "bing-main", "site_url": "https://example.com/"},
        )
        assert bing_crawl_issues.json()["issues"][0]["http_code"] == 404
        bing_crawl_stats = await client.post(
            "/v1/bing/crawl-stats",
            json={"account_id": "bing-main", "site_url": "https://example.com/"},
        )
        assert bing_crawl_stats.json()["points"][0]["code_2xx"] == 1
        malformed_bing_crawl_stats = await client.post(
            "/v1/bing/crawl-stats",
            json={
                "account_id": "bing-main",
                "site_url": "https://example.com/",
                "unexpected": True,
            },
        )
        assert malformed_bing_crawl_stats.status_code == 422
        assert malformed_bing_crawl_stats.json()["code"] == "VALIDATION_FAILED"
        bing_feeds = await client.post(
            "/v1/bing/feeds",
            json={"account_id": "bing-main", "site_url": "https://example.com/"},
        )
        assert bing_feeds.json()["feeds"][0]["url_count"] == 3
        bing_link_counts = await client.post(
            "/v1/bing/link-counts",
            json={"account_id": "bing-main", "site_url": "https://example.com/", "page": 1},
        )
        assert bing_link_counts.json()["links"][0]["count"] == 3
        malformed_bing_link_counts = await client.post(
            "/v1/bing/link-counts",
            json={"account_id": "bing-main", "site_url": "https://example.com/", "page": -1},
        )
        assert malformed_bing_link_counts.status_code == 422
        assert malformed_bing_link_counts.json()["code"] == "VALIDATION_FAILED"
        bing_url_information = await client.post(
            "/v1/bing/url-information",
            json={
                "account_id": "bing-main",
                "site_url": "https://example.com/",
                "page_url": "https://example.com/article",
            },
        )
        assert bing_url_information.json()["http_status"] is None
        malformed_bing_url_information = await client.post(
            "/v1/bing/url-information",
            json={
                "account_id": "bing-main",
                "site_url": "https://example.com/",
                "page_url": "https://example.com/article",
                "unexpected": True,
            },
        )
        assert malformed_bing_url_information.status_code == 422
        assert malformed_bing_url_information.json()["code"] == "VALIDATION_FAILED"
        for path in (
            "/v1/bing/traffic-trend",
            "/v1/bing/traffic-anomalies",
        ):
            malformed_bing_traffic = await client.post(
                path,
                json={
                    "account_id": "bing-main",
                    "site_url": "https://example.com/",
                    "start_date": "2026-07-01",
                    "end_date": "2026-07-02",
                    "unexpected": True,
                },
            )
            assert malformed_bing_traffic.status_code == 422
            assert malformed_bing_traffic.json()["code"] == "VALIDATION_FAILED"
        invalid_bing_traffic = await client.post(
            "/v1/bing/traffic-comparison",
            json={
                "account_id": "bing-main",
                "site_url": "https://example.com/",
                "start_date": "2026-07-01",
                "end_date": "2026-07-02",
                "previous_start_date": "2026-06-30",
                "previous_end_date": "2026-06-29",
            },
        )
        assert invalid_bing_traffic.status_code == 400
        assert invalid_bing_traffic.json()["code"] == "REQUEST_REJECTED"
        invalid_bing_timeout = await client.post(
            "/v1/bing/traffic-trend",
            json={
                "account_id": "bing-main",
                "site_url": "https://example.com/",
                "start_date": "2026-07-01",
                "end_date": "2026-07-02",
                "timeout_seconds": 0,
            },
        )
        assert invalid_bing_timeout.status_code == 422
        assert invalid_bing_timeout.json()["code"] == "VALIDATION_FAILED"
        rejected = await client.get("/v1/sites", params={"account_id": "missing"})
        assert rejected.status_code == 400
        assert rejected.json()["code"] == "REQUEST_REJECTED"
        invalid = await client.get("/v1/accounts", params={"provider": "invalid"})
        assert invalid.status_code == 422
        assert invalid.json() == {
            "code": "VALIDATION_FAILED",
            "message": "request validation failed",
        }
        assert (await client.post("/v1/indexnow-submissions", json={})).status_code == 404
        assert (await client.get("/openapi.json")).status_code == 404

    openapi_app = create_http_app(
        settings.model_copy(update={"enable_openapi": True}),
        services,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=openapi_app),
        base_url="http://rankrat.test",
    ) as client:
        assert (await client.get("/openapi.json")).status_code == 200

    current: object = app
    while not isinstance(current, FastAPI):
        current = cast(_WrappedApp, current)._app
    async with current.router.lifespan_context(current):
        pass


@pytest.mark.asyncio
async def test_http_bearer_auth_covers_errors_and_health_is_public(
    deployment: tuple[Settings, ApplicationServices],
    tmp_path: Path,
) -> None:
    settings, services = deployment
    bearer_file = tmp_path / "bearer"
    bearer_file.write_text("a" * 32, encoding="utf-8")
    bearer_file.chmod(0o600)
    protected_settings = settings.model_copy(update={"http_bearer_secret_file": bearer_file})
    app = create_http_app(protected_settings, services)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://rankrat.test",
    ) as client:
        assert (await client.get("/healthz")).status_code == 200
        unauthorized = await client.get("/v1/server-info")
        assert unauthorized.status_code == 401
        assert "x-request-id" in unauthorized.headers
        assert unauthorized.headers["x-content-type-options"] == "nosniff"
        unauthorized_summary = await client.post(
            "/v1/google/search-analytics-summary",
            json={
                "account_id": "google-main",
                "site_url": "sc-domain:example.com",
                "start_date": "2026-07-01",
                "end_date": "2026-07-02",
            },
        )
        assert unauthorized_summary.status_code == 401
        assert unauthorized_summary.json()["code"] == "UNAUTHORIZED"
        unauthorized_schema_url = await client.post(
            "/v1/schema/validate-url",
            json={"url": "https://example.com/jobs"},
        )
        assert unauthorized_schema_url.status_code == 401
        assert unauthorized_schema_url.json()["code"] == "UNAUTHORIZED"
        unauthorized_drop_attribution = await client.post(
            "/v1/google/search-analytics-drop-attribution",
            json={
                "account_id": "google-main",
                "site_url": "sc-domain:example.com",
                "attribution": "queries",
                "start_date": "2026-07-01",
                "end_date": "2026-07-02",
                "previous_start_date": "2026-06-29",
                "previous_end_date": "2026-06-30",
            },
        )
        assert unauthorized_drop_attribution.status_code == 401
        assert unauthorized_drop_attribution.json()["code"] == "UNAUTHORIZED"
        for path in (
            "/v1/bing/query-performance",
            "/v1/bing/page-performance",
            "/v1/bing/query-opportunities",
            "/v1/bing/page-opportunities",
        ):
            unauthorized_performance = await client.post(
                path,
                json={
                    "account_id": "bing-main",
                    "site_url": "https://example.com/",
                },
            )
            assert unauthorized_performance.status_code == 401
            assert unauthorized_performance.json()["code"] == "UNAUTHORIZED"
        for path, detail_body in (
            ("/v1/bing/query-page-performance", {"query": "rankrat"}),
            ("/v1/bing/page-query-performance", {"page_url": "https://example.com/page"}),
        ):
            unauthorized_performance = await client.post(
                path,
                json={
                    "account_id": "bing-main",
                    "site_url": "https://example.com/",
                    **detail_body,
                },
            )
            assert unauthorized_performance.status_code == 401
            assert unauthorized_performance.json()["code"] == "UNAUTHORIZED"
        for path in (
            "/v1/google/search-analytics-trend",
            "/v1/google/search-analytics-anomalies",
            "/v1/google/search-analytics-page-performance",
            "/v1/bing/traffic-trend",
            "/v1/bing/traffic-anomalies",
            "/v1/bing/traffic-comparison",
        ):
            unauthorized_derived_report = await client.post(
                path,
                json={
                    "account_id": "google-main",
                    "site_url": "sc-domain:example.com",
                    "start_date": "2026-07-01",
                    "end_date": "2026-07-02",
                },
            )
            assert unauthorized_derived_report.status_code == 401
            assert unauthorized_derived_report.json()["code"] == "UNAUTHORIZED"
        authorized = await client.get(
            "/v1/server-info",
            headers={"authorization": f"Bearer {'a' * 32}"},
        )
        assert authorized.status_code == 200


@pytest.mark.asyncio
async def test_http_write_contract_when_read_only_is_disabled(
    indexnow_deployment: tuple[Settings, ApplicationServices],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings, services = indexnow_deployment

    async def mock_bing_submission(*_: object) -> None:
        return None

    monkeypatch.setattr(services.bing_webmaster._client, "submit_url_batch", mock_bing_submission)
    app = create_http_app(settings, services)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://rankrat.test",
    ) as client:
        bing_submission = await client.post(
            "/v1/bing-url-submissions",
            json={
                "account_id": "bing-main",
                "site_url": "https://example.com/",
                "urls": ["https://example.com/article"],
            },
        )
        assert bing_submission.json() == {
            "account_id": "bing-main",
            "site_url": "https://example.com/",
            "submitted_count": 1,
        }

        async def mock_bing_sitemap_submission(*_: object) -> None:
            return None

        monkeypatch.setattr(
            services.bing_webmaster._client,
            "submit_feed",
            mock_bing_sitemap_submission,
        )
        bing_sitemap_submission = await client.post(
            "/v1/bing-sitemap-submissions",
            json={
                "account_id": "bing-main",
                "site_url": "https://example.com/",
                "sitemap_url": "https://example.com/sitemap.xml",
                "operation": "submit",
            },
        )
        assert bing_sitemap_submission.json() == {
            "account_id": "bing-main",
            "site_url": "https://example.com/",
            "operation": "submit",
        }
        response = await client.post(
            "/v1/indexnow-submissions",
            json={
                "target_id": "site-main",
                "urls": ["https://example.com/article"],
            },
        )
        invalid = await client.post(
            "/v1/indexnow-submissions",
            json={
                "target_id": "site-main",
                "urls": ["http://example.com/article"],
            },
        )

    assert response.status_code == 200
    assert response.json() == {
        "target_id": "site-main",
        "host": "example.com",
        "submitted_count": 1,
        "deduplicated_count": 0,
        "suppressed_count": 0,
        "key_validation_pending": False,
    }
    assert invalid.status_code == 400
    assert invalid.json()["code"] == "REQUEST_REJECTED"


@pytest.mark.parametrize("failure_code", list(ProviderFailureCode))
@pytest.mark.asyncio
async def test_rest_provider_errors_preserve_only_the_safe_failure_category(
    deployment: tuple[Settings, ApplicationServices],
    monkeypatch: pytest.MonkeyPatch,
    failure_code: ProviderFailureCode,
) -> None:
    settings, services = deployment
    upstream_detail = "upstream credential and response must not cross the HTTP boundary"

    async def fail(*_: object) -> ProviderReadiness:
        raise ProviderOperationError(failure_code, upstream_detail)

    monkeypatch.setattr(services.provider_readiness, "readiness", fail)
    app = create_http_app(settings, services)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://rankrat.test",
    ) as client:
        response = await client.get(
            "/v1/provider-readiness",
            params={"account_id": "google-main"},
        )

    expected_status = 429 if failure_code is ProviderFailureCode.RATE_LIMITED else 502
    assert response.status_code == expected_status
    assert response.json() == {
        "code": failure_code.value,
        "message": "provider operation failed",
    }
    assert upstream_detail not in response.text


@pytest.mark.asyncio
async def test_streamable_http_mcp_calls_tools_and_sanitizes_provider_errors(
    deployment: tuple[Settings, ApplicationServices],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings, services = deployment
    upstream_detail = "upstream OAuth token must not cross Streamable HTTP MCP"

    async def fail(*_: object) -> ProviderReadiness:
        raise ProviderOperationError(ProviderFailureCode.AUTHENTICATION, upstream_detail)

    monkeypatch.setattr(services.provider_readiness, "readiness", fail)
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
            "name": "provider_readiness",
            "arguments": {"account_id": "google-main"},
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
    assert initialized.json()["result"]["protocolVersion"]
    assert called.status_code == 200
    content = called.json()["result"]["content"][0]
    assert json.loads(content["text"]) == {
        "code": "AUTHENTICATION",
        "message": "provider operation failed",
    }
    assert called.json()["result"]["isError"] is True
    assert upstream_detail not in called.text


@pytest.mark.asyncio
async def test_body_limit_rejects_duplicate_and_streamed_oversize() -> None:
    async def consuming_app(scope: Scope, receive: Receive, send: Send) -> None:
        del scope, send
        await receive()

    app = _BodyLimitASGI(consuming_app, 4)

    async def run(headers: list[tuple[bytes, bytes]], body: bytes) -> list[Message]:
        messages = iter(({"type": "http.request", "body": body, "more_body": False},))
        sent: list[Message] = []

        async def receive() -> Message:
            return next(messages)

        async def send(message: Message) -> None:
            sent.append(message)

        scope: Scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/",
            "raw_path": b"/",
            "query_string": b"",
            "headers": headers,
            "client": ("127.0.0.1", 1),
            "server": ("127.0.0.1", 80),
            "root_path": "",
        }
        await app(scope, receive, send)
        return sent

    duplicate = await run(
        [(b"content-length", b"1"), (b"content-length", b"1")],
        b"x",
    )
    assert duplicate[0]["status"] == 400
    oversized = await run([], b"12345")
    assert oversized[0]["status"] == 413
    declared = await run([(b"content-length", b"5")], b"")
    assert declared[0]["status"] == 413
    invalid = await run([(b"content-length", b"invalid")], b"")
    assert invalid[0]["status"] == 400
    negative = await run([(b"content-length", b"-1")], b"")
    assert negative[0]["status"] == 400
    assert await run([(b"content-length", b"4")], b"1234") == []

    called = False

    async def websocket_app(scope: Scope, receive: Receive, send: Send) -> None:
        del scope, receive, send
        nonlocal called
        called = True

    websocket_scope = cast(Scope, {"type": "websocket"})

    async def unused_receive() -> Message:
        return {"type": "websocket.disconnect", "code": 1000}

    async def unused_send(_: Message) -> None:
        return None

    await _BodyLimitASGI(websocket_app, 4)(websocket_scope, unused_receive, unused_send)
    assert called is True

    async def response_then_read(scope: Scope, receive: Receive, send: Send) -> None:
        del scope
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await receive()

    response_app = _BodyLimitASGI(response_then_read, 4)
    messages = iter(({"type": "http.request", "body": b"12345", "more_body": False},))

    async def oversized_receive() -> Message:
        return next(messages)

    scope = cast(Scope, {"type": "http", "headers": [], "path": "/"})
    with pytest.raises(InputLimitError):
        await response_app(scope, oversized_receive, unused_send)

    async def disconnecting_receive() -> Message:
        return {"type": "http.disconnect"}

    await _BodyLimitASGI(consuming_app, 4)(scope, disconnecting_receive, unused_send)
