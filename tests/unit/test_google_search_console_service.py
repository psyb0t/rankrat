from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

import rankrat.services.google_search_console as google_search_console
from rankrat.errors import BoundaryDeniedError, InputLimitError
from rankrat.models.boundaries import BoundaryDocument
from rankrat.policy.boundaries import BoundaryPolicy
from rankrat.providers.base import ProviderFailureCode, ProviderOperationError
from rankrat.providers.google_search_console import (
    GoogleSearchConsoleClient,
    SearchAnalyticsQuery,
    SearchAnalyticsReport,
    SearchAnalyticsRow,
    SearchConsolePermissionLevel,
    SearchConsoleSite,
    SearchConsoleSitemap,
    SearchConsoleSitemapList,
    SearchConsoleUrlInspection,
)
from rankrat.services.google_search_console import (
    GoogleSearchConsoleService,
    SearchAnalyticsComparisonRequest,
    SearchAnalyticsDimension,
    SearchAnalyticsDimensionReportKind,
    SearchAnalyticsDimensionReportRequest,
    SearchAnalyticsDropAttributionKind,
    SearchAnalyticsDropAttributionRequest,
    SearchAnalyticsFilter,
    SearchAnalyticsFilterOperator,
    SearchAnalyticsPagePerformanceRequest,
    SearchAnalyticsRequest,
    SearchAnalyticsSummaryRequest,
    SearchAnalyticsTrendRequest,
    SearchAnalyticsType,
    SiteGetRequest,
    SiteListRequest,
    SitemapGetRequest,
    SitemapListRequest,
    UrlInspectionBatchRequest,
    UrlInspectionRequest,
)


async def _token(credential_path: Path) -> str:
    del credential_path
    return "test-token"


def _analytics_report(*rows: SearchAnalyticsRow) -> SearchAnalyticsReport:
    return SearchAnalyticsReport(rows, None)


def _analytics_row(
    keys: tuple[str, ...] = (),
    clicks: float = 0.0,
    impressions: float = 0.0,
    position: float = 0.0,
) -> SearchAnalyticsRow:
    return SearchAnalyticsRow(keys, clicks, impressions, 0.0, position)


def _service() -> GoogleSearchConsoleService:
    policy = BoundaryPolicy(
        BoundaryDocument.model_validate(
            {
                "accounts": [
                    {
                        "id": "google-main",
                        "provider": "google",
                        "credential": "/run/secrets/google.json",
                        "search_console_sites": [
                            "sc-domain:example.com",
                            "https://example.net/blog/",
                        ],
                    }
                ]
            }
        )
    )
    return GoogleSearchConsoleService(policy, GoogleSearchConsoleClient(policy, _token))


@pytest.mark.asyncio
async def test_google_search_console_service_builds_bounded_provider_payloads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service()
    captured: dict[str, tuple[object, ...]] = {}

    async def search(*args: object) -> SearchAnalyticsReport:
        captured["search"] = args
        return _analytics_report()

    async def sitemaps(*args: object) -> SearchConsoleSitemapList:
        captured["sitemaps"] = args
        return SearchConsoleSitemapList(())

    async def list_sites(*args: object) -> tuple[str, ...]:
        captured["list_sites"] = args
        return ("sc-domain:example.com",)

    async def site(*args: object) -> SearchConsoleSite:
        captured["site"] = args
        return SearchConsoleSite("sc-domain:example.com", SearchConsolePermissionLevel.OWNER)

    async def sitemap(*args: object) -> SearchConsoleSitemap:
        captured["sitemap"] = args
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

    async def inspection(*args: object) -> SearchConsoleUrlInspection:
        captured["inspection"] = args
        return SearchConsoleUrlInspection(None, None)

    monkeypatch.setattr(service._client, "search_analytics", search)
    monkeypatch.setattr(service._client, "list_sites", list_sites)
    monkeypatch.setattr(service._client, "get_site", site)
    monkeypatch.setattr(service._client, "list_sitemaps", sitemaps)
    monkeypatch.setattr(service._client, "get_sitemap", sitemap)
    monkeypatch.setattr(service._client, "inspect_url", inspection)
    result = await service.search_analytics(
        SearchAnalyticsRequest(
            "google-main",
            "sc-domain:example.com",
            date(2026, 7, 1),
            date(2026, 7, 2),
            dimensions=(SearchAnalyticsDimension.QUERY,),
            filters=(
                SearchAnalyticsFilter(
                    SearchAnalyticsDimension.COUNTRY,
                    SearchAnalyticsFilterOperator.EQUALS,
                    "USA",
                ),
            ),
            search_type=SearchAnalyticsType.NEWS,
            row_limit=12,
            start_row=3,
        )
    )
    assert result == _analytics_report()
    assert await service.list_sites(SiteListRequest("google-main")) == ("sc-domain:example.com",)
    assert await service.get_site(SiteGetRequest("google-main", "sc-domain:example.com")) == (
        SearchConsoleSite("sc-domain:example.com", SearchConsolePermissionLevel.OWNER)
    )
    assert captured["site"][1] == "sc-domain:example.com"
    search_arguments = captured["search"]
    assert isinstance(search_arguments, tuple)
    assert search_arguments[1:] == (
        "sc-domain:example.com",
        SearchAnalyticsQuery(
            "2026-07-01",
            "2026-07-02",
            ("query",),
            "news",
            12,
            3,
            (("country", "equals", "USA"),),
        ),
    )
    assert await service.list_sitemaps(
        SitemapListRequest("google-main", "sc-domain:example.com")
    ) == SearchConsoleSitemapList(())
    assert await service.get_sitemap(
        SitemapGetRequest(
            "google-main",
            "sc-domain:example.com",
            "https://example.com/sitemap.xml",
        )
    ) == SearchConsoleSitemap(
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
    assert captured["sitemap"][2] == "https://example.com/sitemap.xml"
    assert await service.inspect_url(
        UrlInspectionRequest("google-main", "sc-domain:example.com", "https://www.example.com/page")
    ) == SearchConsoleUrlInspection(None, None)
    assert captured["inspection"][2] == "https://www.example.com/page"
    assert await service.inspect_urls(
        UrlInspectionBatchRequest(
            "google-main",
            "sc-domain:example.com",
            ("https://example.com/one", "https://www.example.com/two"),
        )
    ) == (SearchConsoleUrlInspection(None, None), SearchConsoleUrlInspection(None, None))
    assert (
        await service.search_analytics(
            SearchAnalyticsRequest(
                "google-main",
                "sc-domain:example.com",
                date(2026, 7, 1),
                date(2026, 7, 2),
            )
        )
        == _analytics_report()
    )


def test_google_search_console_service_rejects_unsafe_or_excessive_requests() -> None:
    with pytest.raises(InputLimitError):
        SearchAnalyticsFilter(
            SearchAnalyticsDimension.QUERY,
            SearchAnalyticsFilterOperator.CONTAINS,
            "x" * 4_097,
        )
    with pytest.raises(InputLimitError):
        SearchAnalyticsRequest(
            "google-main", "sc-domain:example.com", date(2026, 7, 2), date(2026, 7, 1)
        )
    with pytest.raises(InputLimitError):
        SearchAnalyticsRequest(
            "google-main", "sc-domain:example.com", date(2025, 1, 1), date(2026, 7, 1)
        )
    with pytest.raises(InputLimitError):
        SearchAnalyticsRequest(
            "google-main", "sc-domain:example.com", date(2026, 7, 1), date(2026, 7, 2), row_limit=0
        )
    with pytest.raises(InputLimitError):
        SearchAnalyticsRequest(
            "google-main", "sc-domain:example.com", date(2026, 7, 1), date(2026, 7, 2), start_row=-1
        )
    with pytest.raises(InputLimitError):
        SearchAnalyticsRequest(
            "google-main",
            "sc-domain:example.com",
            date(2026, 7, 1),
            date(2026, 7, 2),
            dimensions=(SearchAnalyticsDimension.QUERY,) * 6,
        )
    with pytest.raises(InputLimitError):
        SearchAnalyticsRequest(
            "google-main",
            "sc-domain:example.com",
            date(2026, 7, 1),
            date(2026, 7, 2),
            dimensions=(SearchAnalyticsDimension.QUERY, SearchAnalyticsDimension.QUERY),
        )
    filter_item = SearchAnalyticsFilter(
        SearchAnalyticsDimension.QUERY,
        SearchAnalyticsFilterOperator.CONTAINS,
        "query",
    )
    with pytest.raises(InputLimitError):
        SearchAnalyticsRequest(
            "google-main",
            "sc-domain:example.com",
            date(2026, 7, 1),
            date(2026, 7, 2),
            filters=(filter_item,) * 21,
        )
    with pytest.raises(InputLimitError):
        UrlInspectionBatchRequest(
            "google-main",
            "sc-domain:example.com",
            (),
        )
    with pytest.raises(InputLimitError):
        SearchAnalyticsComparisonRequest(
            SearchAnalyticsSummaryRequest(
                "google-main",
                "sc-domain:example.com",
                date(2026, 7, 1),
                date(2026, 7, 2),
            ),
            date(2026, 7, 2),
            date(2026, 7, 1),
        )
    with pytest.raises(InputLimitError):
        SearchAnalyticsDropAttributionRequest(
            "google-main",
            "sc-domain:example.com",
            SearchAnalyticsDropAttributionKind.QUERIES,
            date(2026, 7, 1),
            date(2026, 7, 2),
            date(2026, 6, 29),
            date(2026, 6, 30),
            row_limit=0,
        )
    with pytest.raises(InputLimitError):
        SearchAnalyticsDropAttributionRequest(
            "google-main",
            "sc-domain:example.com",
            SearchAnalyticsDropAttributionKind.QUERIES,
            date(2026, 7, 1),
            date(2026, 7, 2),
            date(2026, 6, 29),
            date(2026, 6, 30),
            row_limit=501,
        )
    with pytest.raises(InputLimitError):
        SearchAnalyticsPagePerformanceRequest(
            "google-main",
            "sc-domain:example.com",
            date(2026, 7, 1),
            date(2026, 7, 2),
            row_limit=501,
        )


@pytest.mark.asyncio
async def test_google_search_console_service_rejects_urls_outside_selected_property() -> None:
    service = _service()
    with pytest.raises(BoundaryDeniedError):
        await service.inspect_url(
            UrlInspectionRequest(
                "google-main", "https://example.net/blog/", "https://example.net/other"
            )
        )
    with pytest.raises(InputLimitError):
        await service.inspect_urls(
            UrlInspectionBatchRequest(
                "google-main",
                "sc-domain:example.com",
                ("https://example.com/duplicate", "https://example.com/duplicate"),
            )
        )
    with pytest.raises(BoundaryDeniedError):
        await service.inspect_url(
            UrlInspectionRequest(
                "google-main", "sc-domain:example.com", "https://example.invalid/page"
            )
        )


@pytest.mark.asyncio
async def test_search_analytics_reports_aggregate_and_compare_authorized_periods(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service()
    requests: list[SearchAnalyticsRequest] = []

    async def search(request: SearchAnalyticsRequest) -> SearchAnalyticsReport:
        requests.append(request)
        if request.start_date == date(2026, 7, 1):
            return _analytics_report(
                _analytics_row(clicks=10, impressions=100, position=4),
                _analytics_row(clicks=5, impressions=50, position=8),
            )
        return _analytics_report(_analytics_row(clicks=4, impressions=80, position=6))

    monkeypatch.setattr(service, "search_analytics", search)
    current = SearchAnalyticsSummaryRequest(
        "google-main",
        "sc-domain:example.com",
        date(2026, 7, 1),
        date(2026, 7, 2),
    )
    summary = await service.search_analytics_summary(current)
    comparison = await service.search_analytics_comparison(
        SearchAnalyticsComparisonRequest(current, date(2026, 6, 29), date(2026, 6, 30))
    )

    assert summary.clicks == 15.0
    assert summary.impressions == 150.0
    assert summary.ctr == 0.1
    assert summary.position == 16 / 3
    assert comparison.clicks_delta == 11.0
    assert comparison.impressions_delta == 70.0
    assert comparison.ctr_delta == 0.05
    assert comparison.position_delta == 16 / 3 - 6
    assert [request.dimensions for request in requests] == [
        (SearchAnalyticsDimension.DATE,),
        (SearchAnalyticsDimension.DATE,),
        (SearchAnalyticsDimension.DATE,),
    ]


@pytest.mark.asyncio
async def test_search_analytics_drop_attribution_merges_fixed_query_periods(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service()
    requests: list[SearchAnalyticsRequest] = []

    async def search(request: SearchAnalyticsRequest) -> SearchAnalyticsReport:
        requests.append(request)
        if request.start_date == date(2026, 7, 1):
            return _analytics_report(
                _analytics_row(("lost",), 2, 20, 6),
                _analytics_row(("new",), 4, 40, 5),
            )
        return _analytics_report(
            _analytics_row(("lost",), 10, 50, 3),
            _analytics_row(("gone",), 3, 30, 4),
        )

    monkeypatch.setattr(service, "search_analytics", search)
    report = await service.search_analytics_drop_attribution(
        SearchAnalyticsDropAttributionRequest(
            "google-main",
            "sc-domain:example.com",
            SearchAnalyticsDropAttributionKind.QUERIES,
            date(2026, 7, 1),
            date(2026, 7, 2),
            date(2026, 6, 29),
            date(2026, 6, 30),
        )
    )

    assert [row.key for row in report.rows] == ["lost", "gone", "new"]
    assert [row.clicks_delta for row in report.rows] == [-8.0, -3.0, 4.0]
    assert report.rows[1].current.clicks == 0.0
    assert report.rows[2].previous.clicks == 0.0
    assert report.has_more is False
    assert [request.dimensions for request in requests] == [
        (SearchAnalyticsDimension.QUERY,),
        (SearchAnalyticsDimension.QUERY,),
    ]


@pytest.mark.asyncio
async def test_search_analytics_drop_attribution_bounds_its_union_and_rejects_duplicate_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service()

    async def search(request: SearchAnalyticsRequest) -> SearchAnalyticsReport:
        if request.start_date == date(2026, 7, 1):
            return _analytics_report(
                _analytics_row(("lost",), 2, 20, 6),
                _analytics_row(("new",), 4, 40, 5),
            )
        return _analytics_report(
            _analytics_row(("lost",), 10, 50, 3),
            _analytics_row(("gone",), 3, 30, 4),
        )

    monkeypatch.setattr(service, "search_analytics", search)
    bounded = await service.search_analytics_drop_attribution(
        SearchAnalyticsDropAttributionRequest(
            "google-main",
            "sc-domain:example.com",
            SearchAnalyticsDropAttributionKind.PAGES,
            date(2026, 7, 1),
            date(2026, 7, 2),
            date(2026, 6, 29),
            date(2026, 6, 30),
            row_limit=2,
        )
    )

    assert [row.key for row in bounded.rows] == ["lost", "gone"]
    assert bounded.has_more is True

    async def duplicate(_: SearchAnalyticsRequest) -> SearchAnalyticsReport:
        return _analytics_report(
            _analytics_row(("duplicate",), 1, 1, 1),
            _analytics_row(("duplicate",), 2, 2, 2),
        )

    monkeypatch.setattr(service, "search_analytics", duplicate)
    with pytest.raises(ProviderOperationError) as error:
        await service.search_analytics_drop_attribution(
            SearchAnalyticsDropAttributionRequest(
                "google-main",
                "sc-domain:example.com",
                SearchAnalyticsDropAttributionKind.QUERIES,
                date(2026, 7, 1),
                date(2026, 7, 2),
                date(2026, 6, 29),
                date(2026, 6, 30),
                row_limit=2,
            )
        )
    assert error.value.code is ProviderFailureCode.INVALID_RESPONSE


@pytest.mark.asyncio
async def test_search_analytics_trend_anomalies_and_page_performance_are_fixed_and_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service()
    requests: list[SearchAnalyticsRequest] = []

    async def search(request: SearchAnalyticsRequest) -> SearchAnalyticsReport:
        requests.append(request)
        if request.dimensions == (SearchAnalyticsDimension.PAGE,):
            return _analytics_report(_analytics_row(("/article",), 3, 12, 4))
        return _analytics_report(
            _analytics_row(("2026-07-05",), 100, 10, 4),
            _analytics_row(("2026-07-03",), 0, 10, 4),
            _analytics_row(("2026-07-01",), 0, 10, 4),
            _analytics_row(("2026-07-04",), 0, 10, 4),
            _analytics_row(("2026-07-02",), 0, 10, 4),
        )

    monkeypatch.setattr(service, "search_analytics", search)
    trend_request = SearchAnalyticsTrendRequest(
        "google-main",
        "sc-domain:example.com",
        date(2026, 7, 1),
        date(2026, 7, 5),
    )
    trend = await service.search_analytics_trend(trend_request)
    anomalies = await service.search_analytics_anomalies(trend_request)
    page_performance = await service.search_analytics_page_performance(
        SearchAnalyticsPagePerformanceRequest(
            "google-main",
            "sc-domain:example.com",
            date(2026, 7, 1),
            date(2026, 7, 5),
            row_limit=1,
        )
    )

    assert [point.day for point in trend.points] == [
        "2026-07-01",
        "2026-07-02",
        "2026-07-03",
        "2026-07-04",
        "2026-07-05",
    ]
    assert anomalies.anomalies[0].day == "2026-07-05"
    assert anomalies.anomalies[0].clicks_z_score == 2.0
    assert anomalies.anomalies[0].impressions_z_score == 0.0
    assert page_performance.rows[0].key == "/article"
    assert page_performance.rows[0].metrics.ctr == 0.25
    assert page_performance.has_more is True
    assert [request.dimensions for request in requests] == [
        (SearchAnalyticsDimension.DATE,),
        (SearchAnalyticsDimension.DATE,),
        (SearchAnalyticsDimension.PAGE,),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "rows",
    (
        (_analytics_row(("not-a-day",), 1, 1, 1),),
        (_analytics_row(("2026-06-30",), 1, 1, 1),),
        (
            _analytics_row(("2026-07-01",), 1, 1, 1),
            _analytics_row(("2026-07-01",), 2, 2, 2),
        ),
    ),
)
async def test_search_analytics_trend_rejects_invalid_provider_days(
    monkeypatch: pytest.MonkeyPatch,
    rows: tuple[SearchAnalyticsRow, ...],
) -> None:
    service = _service()

    async def search(_: SearchAnalyticsRequest) -> SearchAnalyticsReport:
        return _analytics_report(*rows)

    monkeypatch.setattr(service, "search_analytics", search)
    with pytest.raises(ProviderOperationError) as error:
        await service.search_analytics_trend(
            SearchAnalyticsTrendRequest(
                "google-main",
                "sc-domain:example.com",
                date(2026, 7, 1),
                date(2026, 7, 3),
            )
        )
    assert error.value.code is ProviderFailureCode.INVALID_RESPONSE


@pytest.mark.asyncio
async def test_search_analytics_anomalies_ignore_short_and_flat_trends(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service()

    async def short(_: SearchAnalyticsRequest) -> SearchAnalyticsReport:
        return _analytics_report(
            _analytics_row(("2026-07-01",), 1, 1, 1),
            _analytics_row(("2026-07-02",), 2, 2, 2),
        )

    monkeypatch.setattr(service, "search_analytics", short)
    request = SearchAnalyticsTrendRequest(
        "google-main",
        "sc-domain:example.com",
        date(2026, 7, 1),
        date(2026, 7, 3),
    )
    assert (await service.search_analytics_anomalies(request)).anomalies == ()

    async def flat(_: SearchAnalyticsRequest) -> SearchAnalyticsReport:
        return _analytics_report(
            _analytics_row(("2026-07-01",), 1, 2, 1),
            _analytics_row(("2026-07-02",), 1, 2, 1),
            _analytics_row(("2026-07-03",), 1, 2, 1),
        )

    monkeypatch.setattr(service, "search_analytics", flat)
    assert (await service.search_analytics_anomalies(request)).anomalies == ()


def test_search_analytics_anomaly_scoring_rejects_nonfinite_calculations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(ProviderOperationError) as baseline_error:
        google_search_console._z_scores((1e308, 1e308, 1e308))
    assert baseline_error.value.code is ProviderFailureCode.INVALID_RESPONSE

    finite_calls = 0

    def finite_until_score(_: float) -> bool:
        nonlocal finite_calls
        finite_calls += 1
        return finite_calls <= 2

    monkeypatch.setattr(google_search_console, "isfinite", finite_until_score)
    with pytest.raises(ProviderOperationError) as score_error:
        google_search_console._z_scores((0.0, 0.0, 100.0))
    assert score_error.value.code is ProviderFailureCode.INVALID_RESPONSE


@pytest.mark.asyncio
async def test_search_analytics_reports_handle_empty_typed_provider_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service()
    request = SearchAnalyticsSummaryRequest(
        "google-main",
        "sc-domain:example.com",
        date(2026, 7, 1),
        date(2026, 7, 2),
    )

    async def empty(_: SearchAnalyticsRequest) -> SearchAnalyticsReport:
        return _analytics_report()

    monkeypatch.setattr(service, "search_analytics", empty)
    assert (await service.search_analytics_summary(request)).clicks == 0.0


@pytest.mark.asyncio
async def test_search_analytics_dimension_reports_fix_dimensions_and_validate_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service()
    calls: list[SearchAnalyticsRequest] = []

    async def search(request: SearchAnalyticsRequest) -> SearchAnalyticsReport:
        calls.append(request)
        return _analytics_report(_analytics_row(("/article",), 12, 100, 4))

    monkeypatch.setattr(service, "search_analytics", search)
    request = SearchAnalyticsDimensionReportRequest(
        "google-main",
        "sc-domain:example.com",
        SearchAnalyticsDimensionReportKind.TOP_PAGES,
        date(2026, 7, 1),
        date(2026, 7, 2),
        row_limit=1,
    )

    report = await service.search_analytics_dimension_report(request)

    assert calls[0].dimensions == (SearchAnalyticsDimension.PAGE,)
    assert report.rows[0].key == "/article"
    assert report.rows[0].metrics.ctr == 0.12
    assert report.has_more is True

    for kind, dimension in (
        (SearchAnalyticsDimensionReportKind.TOP_QUERIES, SearchAnalyticsDimension.QUERY),
        (SearchAnalyticsDimensionReportKind.COUNTRIES, SearchAnalyticsDimension.COUNTRY),
        (
            SearchAnalyticsDimensionReportKind.SEARCH_APPEARANCES,
            SearchAnalyticsDimension.SEARCH_APPEARANCE,
        ),
        (SearchAnalyticsDimensionReportKind.TIME_SERIES, SearchAnalyticsDimension.DATE),
    ):
        assert SearchAnalyticsDimensionReportRequest(
            "google-main",
            "sc-domain:example.com",
            kind,
            date(2026, 7, 1),
            date(2026, 7, 2),
        ).analytics_request().dimensions == (dimension,)


@pytest.mark.asyncio
async def test_search_analytics_dimension_reports_reject_wrong_typed_key_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service()

    async def search(_: SearchAnalyticsRequest) -> SearchAnalyticsReport:
        return _analytics_report(_analytics_row(("one", "two"), 1, 1, 1))

    monkeypatch.setattr(service, "search_analytics", search)
    request = SearchAnalyticsDimensionReportRequest(
        "google-main",
        "sc-domain:example.com",
        SearchAnalyticsDimensionReportKind.TOP_QUERIES,
        date(2026, 7, 1),
        date(2026, 7, 2),
        row_limit=1,
    )

    with pytest.raises(ProviderOperationError) as error:
        await service.search_analytics_dimension_report(request)

    assert error.value.code is ProviderFailureCode.INVALID_RESPONSE
