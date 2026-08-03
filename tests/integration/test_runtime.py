from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from rankrat.config import Settings
from rankrat.providers.schema_fetch import PublicSchemaFetcher
from rankrat.transports.http import create_http_app
from rankrat.transports.runtime import ApplicationServices


@pytest.mark.asyncio
async def test_runtime_serves_consistent_boundary_data_without_provider_traffic(
    deployment: tuple[Settings, ApplicationServices],
) -> None:
    settings, services = deployment
    app = create_http_app(settings, services)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://rankrat.test",
    ) as client:
        accounts = (await client.get("/v1/accounts")).json()["accounts"]
        sites = (await client.get("/v1/sites")).json()["sites"]
    assert {account["account_id"] for account in accounts} == {
        "google-main",
        "bing-main",
        "pagespeed-main",
    }
    assert {site["account_id"] for site in sites} == {
        "google-main",
        "bing-main",
        "pagespeed-main",
    }
    assert isinstance(services.local_schema._fetcher, PublicSchemaFetcher)


@pytest.mark.asyncio
async def test_runtime_routes_fixed_ga4_reports_through_provider_boundary(
    deployment: tuple[Settings, ApplicationServices],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings, services = deployment
    provider_requests: list[httpx.Request] = []

    async def access_token(_: Path) -> str:
        return "test-token"

    async def provider_response(request: httpx.Request) -> httpx.Response:
        provider_requests.append(request)
        requested_payload = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "dimensionHeaders": requested_payload["dimensions"],
                "metricHeaders": [
                    {"name": metric["name"], "type": "TYPE_INTEGER"}
                    for metric in requested_payload["metrics"]
                ],
                "rows": [],
                "rowCount": 0,
            },
        )

    client = services.google_analytics._client
    monkeypatch.setattr(client, "_access_token_provider", access_token)
    monkeypatch.setattr(
        client,
        "_transport_factory",
        lambda: httpx.MockTransport(provider_response),
    )

    app = create_http_app(settings, services)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://rankrat.test",
    ) as http_client:
        responses = [
            await http_client.post(
                route,
                json={
                    "account_id": "google-main",
                    "property_id": "123456789",
                    "start_date": "2026-07-01",
                    "end_date": "2026-07-02",
                    "limit": 10,
                },
            )
            for route in (
                "/v1/google-analytics/content-performance",
                "/v1/google-analytics/landing-page-performance",
                "/v1/google-analytics/organic-search-landing-pages",
                "/v1/google-analytics/traffic-source-performance",
                "/v1/google-analytics/ecommerce-performance",
                "/v1/google-analytics/audience-segments",
                "/v1/google-analytics/user-behavior",
            )
        ]

    assert all(response.status_code == 200 for response in responses)
    assert [response.json()["kind"] for response in responses] == [
        "content_performance",
        "landing_page_performance",
        "organic_search_landing_pages",
        "traffic_source_performance",
        "ecommerce_performance",
        "audience_segments",
        "user_behavior",
    ]
    assert [json.loads(request.content) for request in provider_requests] == [
        {
            "dateRanges": [{"startDate": "2026-07-01", "endDate": "2026-07-02"}],
            "dimensions": [{"name": "pagePathPlusQueryString"}],
            "metrics": [
                {"name": "screenPageViews"},
                {"name": "activeUsers"},
                {"name": "engagedSessions"},
            ],
            "limit": "10",
            "offset": "0",
        },
        {
            "dateRanges": [{"startDate": "2026-07-01", "endDate": "2026-07-02"}],
            "dimensions": [{"name": "landingPagePlusQueryString"}],
            "metrics": [
                {"name": "sessions"},
                {"name": "activeUsers"},
                {"name": "engagedSessions"},
            ],
            "limit": "10",
            "offset": "0",
        },
        {
            "dateRanges": [{"startDate": "2026-07-01", "endDate": "2026-07-02"}],
            "dimensions": [{"name": "landingPagePlusQueryString"}],
            "metrics": [
                {"name": "organicGoogleSearchClicks"},
                {"name": "organicGoogleSearchImpressions"},
                {"name": "organicGoogleSearchClickThroughRate"},
                {"name": "organicGoogleSearchAveragePosition"},
            ],
            "limit": "10",
            "offset": "0",
        },
        {
            "dateRanges": [{"startDate": "2026-07-01", "endDate": "2026-07-02"}],
            "dimensions": [{"name": "sessionSourceMedium"}],
            "metrics": [
                {"name": "sessions"},
                {"name": "activeUsers"},
                {"name": "engagedSessions"},
            ],
            "limit": "10",
            "offset": "0",
        },
        {
            "dateRanges": [{"startDate": "2026-07-01", "endDate": "2026-07-02"}],
            "dimensions": [{"name": "itemName"}],
            "metrics": [
                {"name": "itemsPurchased"},
                {"name": "itemsViewed"},
                {"name": "itemRevenue"},
            ],
            "limit": "10",
            "offset": "0",
        },
        {
            "dateRanges": [{"startDate": "2026-07-01", "endDate": "2026-07-02"}],
            "dimensions": [{"name": "audienceName"}],
            "metrics": [
                {"name": "activeUsers"},
                {"name": "newUsers"},
                {"name": "engagedSessions"},
            ],
            "limit": "10",
            "offset": "0",
        },
        {
            "dateRanges": [{"startDate": "2026-07-01", "endDate": "2026-07-02"}],
            "dimensions": [{"name": "newVsReturning"}],
            "metrics": [
                {"name": "activeUsers"},
                {"name": "newUsers"},
                {"name": "engagedSessions"},
            ],
            "limit": "10",
            "offset": "0",
        },
    ]


@pytest.mark.asyncio
async def test_runtime_routes_ga4_conversion_funnel_through_alpha_provider_boundary(
    deployment: tuple[Settings, ApplicationServices],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings, services = deployment
    provider_requests: list[httpx.Request] = []

    async def access_token(_: Path) -> str:
        return "test-token"

    async def provider_response(request: httpx.Request) -> httpx.Response:
        provider_requests.append(request)
        subreport = {
            "dimensionHeaders": [{"name": "funnelStepName"}],
            "metricHeaders": [{"name": "activeUsers", "type": "TYPE_INTEGER"}],
            "rows": [
                {
                    "dimensionValues": [{"value": "1. view_item"}],
                    "metricValues": [{"value": "5"}],
                }
            ],
        }
        return httpx.Response(
            200,
            json={"funnelTable": subreport, "funnelVisualization": subreport},
        )

    client = services.google_analytics._client
    monkeypatch.setattr(client, "_access_token_provider", access_token)
    monkeypatch.setattr(
        client,
        "_transport_factory",
        lambda: httpx.MockTransport(provider_response),
    )

    app = create_http_app(settings, services)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://rankrat.test",
    ) as http_client:
        response = await http_client.post(
            "/v1/google-analytics/conversion-funnels",
            json={
                "account_id": "google-main",
                "property_id": "123456789",
                "start_date": "2026-07-01",
                "end_date": "2026-07-02",
                "event_names": ["view_item", "purchase"],
                "limit": 10,
            },
        )

    assert response.status_code == 200
    assert response.json()["funnel_table"]["rows"][0]["metric_values"] == ["5"]
    assert len(provider_requests) == 1
    assert str(provider_requests[0].url) == (
        "https://analyticsdata.googleapis.com/v1alpha/properties/123456789:runFunnelReport"
    )
    assert json.loads(provider_requests[0].content) == {
        "dateRanges": [{"startDate": "2026-07-01", "endDate": "2026-07-02"}],
        "funnel": {
            "isOpenFunnel": False,
            "steps": [
                {
                    "name": "view_item",
                    "filterExpression": {"funnelEventFilter": {"eventName": "view_item"}},
                },
                {
                    "name": "purchase",
                    "filterExpression": {"funnelEventFilter": {"eventName": "purchase"}},
                },
            ],
        },
        "limit": "10",
    }


@pytest.mark.asyncio
async def test_runtime_routes_query_cannibalization_through_bing_provider_boundary(
    indexnow_deployment: tuple[Settings, ApplicationServices],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings, services = indexnow_deployment
    provider_requests: list[httpx.Request] = []

    async def provider_response(request: httpx.Request) -> httpx.Response:
        provider_requests.append(request)
        return httpx.Response(
            200,
            json=[
                {
                    "Query": "https://example.com/page-b",
                    "Date": "2026-07-01",
                    "Clicks": 3,
                    "Impressions": 8,
                    "AvgClickPosition": 2,
                    "AvgImpressionPosition": 4,
                },
                {
                    "Query": "https://example.com/page-a",
                    "Date": "2026-07-01",
                    "Clicks": 2,
                    "Impressions": 4,
                    "AvgClickPosition": 3,
                    "AvgImpressionPosition": 5,
                },
            ],
        )

    monkeypatch.setattr(
        services.bing_webmaster._client,
        "_transport_factory",
        lambda: httpx.MockTransport(provider_response),
    )
    app = create_http_app(settings, services)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://rankrat.test",
    ) as http_client:
        response = await http_client.post(
            "/v1/bing/query-cannibalization",
            json={
                "account_id": "bing-main",
                "site_url": "https://example.com/",
                "query": "rankrat",
            },
        )

    assert response.status_code == 200
    assert response.json()["query"] == "rankrat"
    assert [page["label"] for page in response.json()["pages"]] == [
        "https://example.com/page-b",
        "https://example.com/page-a",
    ]
    assert len(provider_requests) == 1
    assert provider_requests[0].method == "GET"
    assert provider_requests[0].url.path.endswith("/GetQueryPageStats")
    assert provider_requests[0].url.params["siteUrl"] == "https://example.com/"
    assert provider_requests[0].url.params["query"] == "rankrat"


@pytest.mark.asyncio
async def test_runtime_routes_brand_analysis_through_bing_provider_boundary(
    indexnow_deployment: tuple[Settings, ApplicationServices],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings, services = indexnow_deployment
    provider_requests: list[httpx.Request] = []

    async def provider_response(request: httpx.Request) -> httpx.Response:
        provider_requests.append(request)
        return httpx.Response(
            200,
            json=[
                {
                    "Query": "Rankrat documentation",
                    "Date": "2026-07-01",
                    "Clicks": 3,
                    "Impressions": 8,
                    "AvgClickPosition": 2,
                    "AvgImpressionPosition": 4,
                },
                {
                    "Query": "unrelated query",
                    "Date": "2026-07-01",
                    "Clicks": 2,
                    "Impressions": 4,
                    "AvgClickPosition": 3,
                    "AvgImpressionPosition": 5,
                },
            ],
        )

    monkeypatch.setattr(
        services.bing_webmaster._client,
        "_transport_factory",
        lambda: httpx.MockTransport(provider_response),
    )
    app = create_http_app(settings, services)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://rankrat.test",
    ) as http_client:
        response = await http_client.post(
            "/v1/bing/brand-analysis",
            json={
                "account_id": "bing-main",
                "site_url": "https://example.com/",
                "brand_terms": ["RANKRAT"],
            },
        )

    assert response.status_code == 200
    assert response.json()["brand_terms"] == ["rankrat"]
    assert [row["label"] for row in response.json()["brand_rows"]] == ["Rankrat documentation"]
    assert [row["label"] for row in response.json()["non_brand_rows"]] == ["unrelated query"]
    assert len(provider_requests) == 1
    assert provider_requests[0].method == "GET"
    assert provider_requests[0].url.path.endswith("/GetQueryStats")
    assert provider_requests[0].url.params["siteUrl"] == "https://example.com/"
    assert "brand_terms" not in provider_requests[0].url.params


@pytest.mark.asyncio
async def test_runtime_routes_ranking_buckets_through_bing_provider_boundary(
    indexnow_deployment: tuple[Settings, ApplicationServices],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings, services = indexnow_deployment
    provider_requests: list[httpx.Request] = []

    async def provider_response(request: httpx.Request) -> httpx.Response:
        provider_requests.append(request)
        return httpx.Response(
            200,
            json=[
                {
                    "Query": "top result",
                    "Date": "2026-07-01",
                    "Clicks": 3,
                    "Impressions": 8,
                    "AvgClickPosition": -1,
                    "AvgImpressionPosition": 3,
                },
                {
                    "Query": "later result",
                    "Date": "2026-07-01",
                    "Clicks": 2,
                    "Impressions": 4,
                    "AvgClickPosition": 20.1,
                    "AvgImpressionPosition": 5,
                },
            ],
        )

    monkeypatch.setattr(
        services.bing_webmaster._client,
        "_transport_factory",
        lambda: httpx.MockTransport(provider_response),
    )
    app = create_http_app(settings, services)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://rankrat.test",
    ) as http_client:
        response = await http_client.post(
            "/v1/bing/ranking-buckets",
            json={
                "account_id": "bing-main",
                "site_url": "https://example.com/",
            },
        )

    assert response.status_code == 200
    assert [
        (bucket["kind"], [row["label"] for row in bucket["rows"]])
        for bucket in response.json()["buckets"]
    ] == [
        ("top_three", ["top result"]),
        ("first_page", ["later result"]),
        ("second_page", []),
        ("beyond_second_page", []),
    ]
    top_result = response.json()["buckets"][0]["rows"][0]
    assert top_result["average_click_position"] is None
    assert top_result["average_impression_position"] == 3.0
    assert len(provider_requests) == 1
    assert provider_requests[0].method == "GET"
    assert provider_requests[0].url.path.endswith("/GetQueryStats")
    assert provider_requests[0].url.params["siteUrl"] == "https://example.com/"
    assert "threshold" not in provider_requests[0].url.params


@pytest.mark.asyncio
async def test_runtime_routes_cross_provider_correlation_through_separate_boundaries(
    deployment: tuple[Settings, ApplicationServices],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings, services = deployment
    ga4_requests: list[httpx.Request] = []
    pagespeed_requests: list[httpx.Request] = []

    async def access_token(_: Path) -> str:
        return "test-token"

    async def ga4_response(request: httpx.Request) -> httpx.Response:
        ga4_requests.append(request)
        return httpx.Response(
            200,
            json={
                "dimensionHeaders": [{"name": "pagePathPlusQueryString"}],
                "metricHeaders": [
                    {"name": "screenPageViews", "type": "TYPE_INTEGER"},
                    {"name": "activeUsers", "type": "TYPE_INTEGER"},
                    {"name": "engagedSessions", "type": "TYPE_INTEGER"},
                ],
                "rows": [
                    {
                        "dimensionValues": [{"value": "/article"}],
                        "metricValues": [{"value": "7"}, {"value": "3"}, {"value": "2"}],
                    }
                ],
                "rowCount": 1,
            },
        )

    async def pagespeed_response(request: httpx.Request) -> httpx.Response:
        pagespeed_requests.append(request)
        return httpx.Response(
            200,
            json={
                "analysisUTCTimestamp": "2026-07-30T23:25:07Z",
                "id": "https://example.com/article",
                "lighthouseResult": {
                    "categories": {"performance": {"id": "performance", "score": 0.95}}
                },
            },
        )

    monkeypatch.setattr(services.google_analytics._client, "_access_token_provider", access_token)
    monkeypatch.setattr(
        services.google_analytics._client,
        "_transport_factory",
        lambda: httpx.MockTransport(ga4_response),
    )
    monkeypatch.setattr(
        services.pagespeed._client,
        "_transport_factory",
        lambda: httpx.MockTransport(pagespeed_response),
    )
    app = create_http_app(settings, services)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://rankrat.test",
    ) as http_client:
        response = await http_client.post(
            "/v1/cross-provider/ga4-pagespeed-correlations",
            json={
                "google_analytics_account_id": "google-main",
                "property_id": "123456789",
                "pagespeed_account_id": "pagespeed-main",
                "site_url": "https://example.com/",
                "page_url": "https://example.com/article",
                "start_date": "2026-07-01",
                "end_date": "2026-07-02",
            },
        )

    assert response.status_code == 200
    assert response.json()["ga4_content_row"]["dimension_values"] == ["/article"]
    assert response.json()["pagespeed"]["analyzed_url"] == "https://example.com/article"
    assert len(ga4_requests) == 1
    assert len(pagespeed_requests) == 1
    assert ga4_requests[0].url.host == "analyticsdata.googleapis.com"
    assert pagespeed_requests[0].url.host == "pagespeedonline.googleapis.com"
    assert pagespeed_requests[0].url.params["key"] == "test-pagespeed-api-key"
    assert "Authorization" not in pagespeed_requests[0].headers


@pytest.mark.asyncio
async def test_runtime_routes_pagespeed_core_web_vitals_through_the_fixed_provider_origin(
    deployment: tuple[Settings, ApplicationServices],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings, services = deployment
    provider_requests: list[httpx.Request] = []

    async def pagespeed_response(request: httpx.Request) -> httpx.Response:
        provider_requests.append(request)
        return httpx.Response(
            200,
            json={
                "analysisUTCTimestamp": "2026-07-30T23:41:11Z",
                "id": "https://example.com/article",
                "lighthouseResult": {
                    "categories": {"performance": {"id": "performance", "score": 0.95}}
                },
                "loadingExperience": {
                    "metrics": {
                        "LARGEST_CONTENTFUL_PAINT_MS": {
                            "percentile": 2_500,
                            "category": "AVERAGE",
                            "distributions": [{"min": 0, "proportion": 1.0}],
                        }
                    }
                },
            },
        )

    monkeypatch.setattr(
        services.pagespeed._client,
        "_transport_factory",
        lambda: httpx.MockTransport(pagespeed_response),
    )
    app = create_http_app(settings, services)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://rankrat.test",
    ) as http_client:
        response = await http_client.post(
            "/v1/pagespeed/core-web-vitals",
            json={
                "account_id": "pagespeed-main",
                "site_url": "https://example.com/",
                "page_url": "https://example.com/article",
            },
        )

    assert response.status_code == 200
    assert response.json()["page_metrics"][0]["kind"] == "largest_contentful_paint"
    assert len(provider_requests) == 1
    assert provider_requests[0].url.host == "pagespeedonline.googleapis.com"
    assert provider_requests[0].url.params["key"] == "test-pagespeed-api-key"
    assert "Authorization" not in provider_requests[0].headers


@pytest.mark.asyncio
async def test_runtime_routes_search_engine_comparison_through_fixed_provider_origins(
    indexnow_deployment: tuple[Settings, ApplicationServices],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings, services = indexnow_deployment
    google_requests: list[httpx.Request] = []
    bing_requests: list[httpx.Request] = []

    async def access_token(_: Path) -> str:
        return "test-token"

    async def google_response(request: httpx.Request) -> httpx.Response:
        google_requests.append(request)
        return httpx.Response(
            200,
            json={
                "rows": [
                    {
                        "keys": ["2026-07-01"],
                        "clicks": 10,
                        "impressions": 100,
                        "ctr": 0.1,
                        "position": 3,
                    }
                ]
            },
        )

    async def bing_response(request: httpx.Request) -> httpx.Response:
        bing_requests.append(request)
        return httpx.Response(
            200,
            json=[
                {"Date": "2026-07-01", "Clicks": 2, "Impressions": 20},
                {"Date": "2026-07-02", "Clicks": 3, "Impressions": 30},
            ],
        )

    monkeypatch.setattr(
        services.google_search_console._client,
        "_access_token_provider",
        access_token,
    )
    monkeypatch.setattr(
        services.google_search_console._client,
        "_transport_factory",
        lambda: httpx.MockTransport(google_response),
    )
    monkeypatch.setattr(
        services.bing_webmaster._client,
        "_transport_factory",
        lambda: httpx.MockTransport(bing_response),
    )
    app = create_http_app(settings, services)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://rankrat.test",
    ) as http_client:
        response = await http_client.post(
            "/v1/cross-provider/search-engine-comparisons",
            json={
                "google_search_console_account_id": "google-main",
                "google_search_console_site_url": "sc-domain:example.com",
                "bing_account_id": "bing-main",
                "bing_site_url": "https://example.com/",
                "start_date": "2026-07-01",
                "end_date": "2026-07-02",
            },
        )

    assert response.status_code == 200
    assert response.json()["google_search_console"]["clicks"] == 10.0
    assert response.json()["bing"] == {"clicks": 5.0, "impressions": 50.0}
    assert len(google_requests) == 1
    assert google_requests[0].url.host == "www.googleapis.com"
    assert google_requests[0].url.path.endswith("/searchAnalytics/query")
    assert json.loads(google_requests[0].content)["dimensions"] == ["date"]
    assert len(bing_requests) == 1
    assert bing_requests[0].url.host == "ssl.bing.com"
    assert bing_requests[0].url.path.endswith("/GetRankAndTrafficStats")


@pytest.mark.asyncio
async def test_runtime_routes_bing_opportunity_matrix_through_fixed_provider_origin(
    indexnow_deployment: tuple[Settings, ApplicationServices],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings, services = indexnow_deployment
    bing_requests: list[httpx.Request] = []

    async def bing_response(request: httpx.Request) -> httpx.Response:
        bing_requests.append(request)
        if request.url.path.endswith("/GetQueryStats"):
            prefix = "query"
        elif request.url.path.endswith("/GetPageStats"):
            prefix = "page"
        else:
            raise AssertionError(f"unexpected Bing operation path: {request.url.path}")
        return httpx.Response(
            200,
            json=[
                {
                    "Query": f"low-{prefix}",
                    "Date": "2026-07-01",
                    "Clicks": 1,
                    "Impressions": 25,
                    "AvgClickPosition": 1,
                    "AvgImpressionPosition": 1,
                },
                {
                    "Query": f"quick-{prefix}",
                    "Date": "2026-07-01",
                    "Clicks": 1,
                    "Impressions": 20,
                    "AvgClickPosition": 4,
                    "AvgImpressionPosition": 4,
                },
                {
                    "Query": f"rank-{prefix}",
                    "Date": "2026-07-01",
                    "Clicks": 10,
                    "Impressions": 10,
                    "AvgClickPosition": 5,
                    "AvgImpressionPosition": 5,
                },
                {
                    "Query": f"high-{prefix}",
                    "Date": "2026-07-01",
                    "Clicks": 8,
                    "Impressions": 10,
                    "AvgClickPosition": 1,
                    "AvgImpressionPosition": 1,
                },
            ],
        )

    monkeypatch.setattr(
        services.bing_webmaster._client,
        "_transport_factory",
        lambda: httpx.MockTransport(bing_response),
    )
    app = create_http_app(settings, services)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://rankrat.test",
    ) as http_client:
        response = await http_client.post(
            "/v1/bing/opportunity-matrix",
            json={
                "account_id": "bing-main",
                "site_url": "https://example.com/",
            },
        )

    assert response.status_code == 200
    assert response.json()["query_quick_wins"][0]["row"]["label"] == "quick-query"
    assert response.json()["page_quick_wins"][0]["row"]["label"] == "quick-page"
    assert len(bing_requests) == 2
    assert {request.url.host for request in bing_requests} == {"ssl.bing.com"}
    assert {request.url.path.rsplit("/", 1)[-1] for request in bing_requests} == {
        "GetQueryStats",
        "GetPageStats",
    }


@pytest.mark.asyncio
async def test_runtime_routes_search_engine_traffic_health_through_fixed_provider_origins(
    indexnow_deployment: tuple[Settings, ApplicationServices],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings, services = indexnow_deployment
    google_requests: list[httpx.Request] = []
    bing_requests: list[httpx.Request] = []

    async def access_token(_: Path) -> str:
        return "test-token"

    async def google_response(request: httpx.Request) -> httpx.Response:
        google_requests.append(request)
        return httpx.Response(
            200,
            json={
                "rows": [
                    {
                        "keys": ["2026-07-01"],
                        "clicks": 2,
                        "impressions": 20,
                        "ctr": 0.1,
                        "position": 3,
                    },
                    {
                        "keys": ["2026-07-02"],
                        "clicks": 3,
                        "impressions": 30,
                        "ctr": 0.1,
                        "position": 3,
                    },
                    {
                        "keys": ["2026-07-03"],
                        "clicks": 4,
                        "impressions": 40,
                        "ctr": 0.1,
                        "position": 3,
                    },
                ]
            },
        )

    async def bing_response(request: httpx.Request) -> httpx.Response:
        bing_requests.append(request)
        return httpx.Response(
            200,
            json=[
                {"Date": "2026-07-01", "Clicks": 2, "Impressions": 20},
                {"Date": "2026-07-02", "Clicks": 3, "Impressions": 30},
                {"Date": "2026-07-03", "Clicks": 4, "Impressions": 40},
            ],
        )

    monkeypatch.setattr(
        services.google_search_console._client,
        "_access_token_provider",
        access_token,
    )
    monkeypatch.setattr(
        services.google_search_console._client,
        "_transport_factory",
        lambda: httpx.MockTransport(google_response),
    )
    monkeypatch.setattr(
        services.bing_webmaster._client,
        "_transport_factory",
        lambda: httpx.MockTransport(bing_response),
    )
    app = create_http_app(settings, services)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://rankrat.test",
    ) as http_client:
        response = await http_client.post(
            "/v1/cross-provider/search-engine-traffic-health",
            json={
                "google_search_console_account_id": "google-main",
                "google_search_console_site_url": "sc-domain:example.com",
                "bing_account_id": "bing-main",
                "bing_site_url": "https://example.com/",
                "start_date": "2026-07-01",
                "end_date": "2026-07-03",
            },
        )

    assert response.status_code == 200
    assert response.json() == {
        "google_search_console": {"anomalies": [], "has_more": False},
        "bing": {"anomalies": []},
    }
    assert len(google_requests) == 1
    assert google_requests[0].url.host == "www.googleapis.com"
    assert google_requests[0].url.path.endswith("/searchAnalytics/query")
    assert len(bing_requests) == 1
    assert bing_requests[0].url.host == "ssl.bing.com"
    assert bing_requests[0].url.path.endswith("/GetRankAndTrafficStats")


@pytest.mark.asyncio
async def test_runtime_routes_ga4_search_console_comparison_through_fixed_origins(
    deployment: tuple[Settings, ApplicationServices],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings, services = deployment
    ga4_requests: list[httpx.Request] = []
    google_requests: list[httpx.Request] = []

    async def access_token(_: Path) -> str:
        return "test-token"

    async def ga4_response(request: httpx.Request) -> httpx.Response:
        ga4_requests.append(request)
        payload = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "dimensionHeaders": payload["dimensions"],
                "metricHeaders": [
                    {"name": metric["name"], "type": "TYPE_INTEGER"}
                    for metric in payload["metrics"]
                ],
                "rows": [],
                "rowCount": 0,
            },
        )

    async def google_response(request: httpx.Request) -> httpx.Response:
        google_requests.append(request)
        return httpx.Response(
            200,
            json={
                "rows": [
                    {
                        "keys": ["2026-07-01"],
                        "clicks": 10,
                        "impressions": 100,
                        "ctr": 0.1,
                        "position": 3,
                    }
                ]
            },
        )

    monkeypatch.setattr(services.google_analytics._client, "_access_token_provider", access_token)
    monkeypatch.setattr(
        services.google_analytics._client,
        "_transport_factory",
        lambda: httpx.MockTransport(ga4_response),
    )
    monkeypatch.setattr(
        services.google_search_console._client,
        "_access_token_provider",
        access_token,
    )
    monkeypatch.setattr(
        services.google_search_console._client,
        "_transport_factory",
        lambda: httpx.MockTransport(google_response),
    )
    app = create_http_app(settings, services)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://rankrat.test",
    ) as http_client:
        response = await http_client.post(
            "/v1/cross-provider/ga4-search-console-comparisons",
            json={
                "google_analytics_account_id": "google-main",
                "property_id": "123456789",
                "google_search_console_account_id": "google-main",
                "site_url": "sc-domain:example.com",
                "start_date": "2026-07-01",
                "end_date": "2026-07-02",
            },
        )

    assert response.status_code == 200
    assert response.json()["ga4_organic_search"]["kind"] == "organic_search_landing_pages"
    assert response.json()["google_search_console"]["clicks"] == 10.0
    assert len(ga4_requests) == 1
    assert ga4_requests[0].url.host == "analyticsdata.googleapis.com"
    assert ga4_requests[0].url.path.endswith("/properties/123456789:runReport")
    assert len(google_requests) == 1
    assert google_requests[0].url.host == "www.googleapis.com"
    assert google_requests[0].url.path.endswith("/searchAnalytics/query")
    assert json.loads(google_requests[0].content)["dimensions"] == ["date"]
