from __future__ import annotations

from datetime import UTC, date, datetime
from typing import cast

import pytest

from rankrat.errors import BoundaryDeniedError, InputLimitError
from rankrat.models.boundaries import BoundaryDocument
from rankrat.policy.boundaries import BoundaryPolicy
from rankrat.providers.google_analytics import (
    Ga4MetricHeader,
    Ga4MetricType,
    Ga4ReportResult,
    Ga4ReportRow,
)
from rankrat.services.bing import (
    BingTrafficAnomalyReport,
    BingTrafficMetrics,
    BingTrafficPoint,
    BingTrafficTrendReport,
    BingWebmasterService,
)
from rankrat.services.cross_provider import (
    CrossProviderService,
    Ga4PageSpeedCorrelationRequest,
    Ga4SearchConsoleComparisonReport,
    Ga4SearchConsoleComparisonRequest,
    SearchEngineComparisonReport,
    SearchEngineComparisonRequest,
    SearchEngineTrafficHealthReport,
    SearchEngineTrafficHealthRequest,
)
from rankrat.services.google_analytics import (
    Ga4FixedReport,
    Ga4FixedReportKind,
    GoogleAnalyticsDataService,
)
from rankrat.services.google_search_console import (
    GoogleSearchConsoleService,
    SearchAnalyticsAnomalyReport,
    SearchAnalyticsMetrics,
)
from rankrat.services.pagespeed import (
    PageSpeedAnalysisReport,
    PageSpeedCategoryScore,
    PageSpeedService,
)


class _GoogleAnalyticsFake:
    async def content_performance(self, _: object) -> Ga4FixedReport:
        raise AssertionError("test must replace the GA4 fake response")

    async def organic_search_landing_pages(self, _: object) -> Ga4FixedReport:
        raise AssertionError("test must replace the GA4 fake response")


class _PageSpeedFake:
    async def analyze(self, _: object) -> PageSpeedAnalysisReport:
        raise AssertionError("test must replace the PageSpeed fake response")


class _GoogleSearchConsoleFake:
    async def search_analytics_summary(self, _: object) -> SearchAnalyticsMetrics:
        raise AssertionError("test must replace the Search Console fake response")

    async def search_analytics_anomalies(self, _: object) -> SearchAnalyticsAnomalyReport:
        raise AssertionError("test must replace the Search Console fake response")


class _BingWebmasterFake:
    async def traffic_trend(self, _: object) -> BingTrafficTrendReport:
        raise AssertionError("test must replace the Bing fake response")

    async def traffic_anomalies(self, _: object) -> BingTrafficAnomalyReport:
        raise AssertionError("test must replace the Bing fake response")


def _service() -> CrossProviderService:
    policy = BoundaryPolicy(
        BoundaryDocument.model_validate(
            {
                "accounts": [
                    {
                        "id": "google-main",
                        "provider": "google",
                        "credential": "/run/secrets/google.json",
                        "ga4_properties": ["123456789"],
                    },
                    {
                        "id": "pagespeed-main",
                        "provider": "google",
                        "credential": "/run/secrets/pagespeed-key",
                        "search_console_sites": ["https://example.com/"],
                        "pagespeed_sites": ["https://example.com/"],
                    },
                    {
                        "id": "bing-main",
                        "provider": "bing",
                        "credential": "/run/secrets/bing-key",
                        "sites": ["https://example.com/"],
                    },
                ]
            }
        )
    )
    return CrossProviderService(
        policy,
        cast(GoogleAnalyticsDataService, _GoogleAnalyticsFake()),
        cast(PageSpeedService, _PageSpeedFake()),
        cast(GoogleSearchConsoleService, _GoogleSearchConsoleFake()),
        cast(BingWebmasterService, _BingWebmasterFake()),
    )


def _request(
    page_url: str = "https://example.com/article",
) -> Ga4PageSpeedCorrelationRequest:
    return Ga4PageSpeedCorrelationRequest(
        "google-main",
        "123456789",
        "pagespeed-main",
        "https://example.com/",
        page_url,
        date(2026, 7, 1),
        date(2026, 7, 2),
    )


def _ga4_report(rows: tuple[Ga4ReportRow, ...]) -> Ga4FixedReport:
    return Ga4FixedReport(
        Ga4FixedReportKind.CONTENT_PERFORMANCE,
        Ga4ReportResult(
            ("pagePathPlusQueryString",),
            (Ga4MetricHeader("screenPageViews", Ga4MetricType.INTEGER),),
            rows,
            len(rows),
        ),
    )


def _pagespeed_report() -> PageSpeedAnalysisReport:
    return PageSpeedAnalysisReport(
        "https://example.com/article",
        datetime(2026, 7, 30, 17, tzinfo=UTC).isoformat(),
        (PageSpeedCategoryScore("performance", 0.95),),
        "FAST",
        None,
    )


def _organic_search_report() -> Ga4FixedReport:
    return Ga4FixedReport(
        Ga4FixedReportKind.ORGANIC_SEARCH_LANDING_PAGES,
        Ga4ReportResult(
            ("landingPagePlusQueryString",),
            (Ga4MetricHeader("organicGoogleSearchClicks", Ga4MetricType.INTEGER),),
            (),
            0,
        ),
    )


@pytest.mark.asyncio
async def test_cross_provider_correlation_matches_one_exact_ga4_path_and_pagespeed_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service()
    ga4_calls: list[object] = []
    pagespeed_calls: list[object] = []

    async def content_performance(request: object) -> Ga4FixedReport:
        ga4_calls.append(request)
        return _ga4_report(
            (
                Ga4ReportRow(("/other",), ("1",)),
                Ga4ReportRow(("/article",), ("7",)),
            )
        )

    async def analyze(request: object) -> PageSpeedAnalysisReport:
        pagespeed_calls.append(request)
        return _pagespeed_report()

    monkeypatch.setattr(service._google_analytics, "content_performance", content_performance)
    monkeypatch.setattr(service._pagespeed, "analyze", analyze)

    report = await service.ga4_pagespeed_correlation(_request())

    assert report.requested_page_path == "/article"
    assert report.ga4_content_row == Ga4ReportRow(("/article",), ("7",))
    assert report.pagespeed == _pagespeed_report()
    assert len(ga4_calls) == 1
    assert len(pagespeed_calls) == 1


@pytest.mark.asyncio
async def test_cross_provider_correlation_returns_no_ga4_match_and_denies_before_service_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service()
    ga4_calls: list[object] = []
    pagespeed_calls: list[object] = []

    async def content_performance(request: object) -> Ga4FixedReport:
        ga4_calls.append(request)
        return _ga4_report(())

    async def analyze(request: object) -> PageSpeedAnalysisReport:
        pagespeed_calls.append(request)
        return _pagespeed_report()

    monkeypatch.setattr(service._google_analytics, "content_performance", content_performance)
    monkeypatch.setattr(service._pagespeed, "analyze", analyze)
    assert (await service.ga4_pagespeed_correlation(_request())).ga4_content_row is None
    assert len(ga4_calls) == 1
    assert len(pagespeed_calls) == 1

    ga4_calls.clear()
    pagespeed_calls.clear()

    await service.ga4_pagespeed_correlation(
        Ga4PageSpeedCorrelationRequest(
            "pagespeed-main",
            "123456789",
            "pagespeed-main",
            "https://example.com/",
            "https://example.com/article",
            date(2026, 7, 1),
            date(2026, 7, 2),
        )
    )
    assert len(ga4_calls) == 1
    assert len(pagespeed_calls) == 1

    ga4_calls.clear()
    pagespeed_calls.clear()

    with pytest.raises(BoundaryDeniedError):
        await service.ga4_pagespeed_correlation(_request("https://outside.example/article"))

    with pytest.raises(ValueError, match="must not contain credentials, query, or fragment"):
        await service.ga4_pagespeed_correlation(_request("https://example.com/article?source=bad"))


@pytest.mark.asyncio
async def test_cross_provider_correlation_rejects_duplicate_matching_ga4_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service()

    async def content_performance(_: object) -> Ga4FixedReport:
        row = Ga4ReportRow(("/article",), ("7",))
        return _ga4_report((row, row))

    async def analyze(_: object) -> PageSpeedAnalysisReport:
        return _pagespeed_report()

    monkeypatch.setattr(service._google_analytics, "content_performance", content_performance)
    monkeypatch.setattr(service._pagespeed, "analyze", analyze)
    with pytest.raises(InputLimitError, match="duplicate requested page rows"):
        await service.ga4_pagespeed_correlation(_request())


@pytest.mark.asyncio
async def test_search_engine_comparison_preserves_separate_engine_metrics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service()
    google_calls: list[object] = []
    bing_calls: list[object] = []

    async def search_analytics_summary(request: object) -> SearchAnalyticsMetrics:
        google_calls.append(request)
        return SearchAnalyticsMetrics(10.0, 100.0, 0.1, 3.0)

    async def traffic_trend(request: object) -> BingTrafficTrendReport:
        bing_calls.append(request)
        return BingTrafficTrendReport(
            (
                BingTrafficPoint("2026-07-01", BingTrafficMetrics(2.0, 20.0)),
                BingTrafficPoint("2026-07-02", BingTrafficMetrics(3.0, 30.0)),
            )
        )

    monkeypatch.setattr(
        service._google_search_console,
        "search_analytics_summary",
        search_analytics_summary,
    )
    monkeypatch.setattr(service._bing_webmaster, "traffic_trend", traffic_trend)
    request = SearchEngineComparisonRequest(
        google_search_console_account_id="pagespeed-main",
        google_search_console_site_url="https://example.com/",
        bing_account_id="bing-main",
        bing_site_url="https://example.com/",
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 2),
    )

    assert await service.search_engine_comparison(request) == SearchEngineComparisonReport(
        start_date="2026-07-01",
        end_date="2026-07-02",
        google_search_console=SearchAnalyticsMetrics(10.0, 100.0, 0.1, 3.0),
        bing=BingTrafficMetrics(5.0, 50.0),
    )
    assert google_calls == [request.google_request()]
    assert bing_calls == [request.bing_request()]


@pytest.mark.asyncio
async def test_search_engine_comparison_denies_before_either_service_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service()
    google_calls: list[object] = []
    bing_calls: list[object] = []

    async def search_analytics_summary(request: object) -> SearchAnalyticsMetrics:
        google_calls.append(request)
        return SearchAnalyticsMetrics(0.0, 0.0, 0.0, 0.0)

    async def traffic_trend(request: object) -> BingTrafficTrendReport:
        bing_calls.append(request)
        return BingTrafficTrendReport(())

    monkeypatch.setattr(
        service._google_search_console,
        "search_analytics_summary",
        search_analytics_summary,
    )
    monkeypatch.setattr(service._bing_webmaster, "traffic_trend", traffic_trend)

    with pytest.raises(BoundaryDeniedError):
        await service.search_engine_comparison(
            SearchEngineComparisonRequest(
                google_search_console_account_id="pagespeed-main",
                google_search_console_site_url="https://example.com/",
                bing_account_id="pagespeed-main",
                bing_site_url="https://example.com/",
                start_date=date(2026, 7, 1),
                end_date=date(2026, 7, 2),
            )
        )

    assert google_calls == []
    assert bing_calls == []


@pytest.mark.asyncio
async def test_search_engine_comparison_keeps_empty_bing_traffic_at_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service()

    async def search_analytics_summary(_: object) -> SearchAnalyticsMetrics:
        return SearchAnalyticsMetrics(10.0, 100.0, 0.1, 3.0)

    async def traffic_trend(_: object) -> BingTrafficTrendReport:
        return BingTrafficTrendReport(())

    monkeypatch.setattr(
        service._google_search_console,
        "search_analytics_summary",
        search_analytics_summary,
    )
    monkeypatch.setattr(service._bing_webmaster, "traffic_trend", traffic_trend)

    assert (
        await service.search_engine_comparison(
            SearchEngineComparisonRequest(
                google_search_console_account_id="pagespeed-main",
                google_search_console_site_url="https://example.com/",
                bing_account_id="bing-main",
                bing_site_url="https://example.com/",
                start_date=date(2026, 7, 1),
                end_date=date(2026, 7, 2),
            )
        )
    ).bing == BingTrafficMetrics(0.0, 0.0)


@pytest.mark.asyncio
async def test_search_engine_traffic_health_preserves_separate_engine_anomalies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service()
    google_calls: list[object] = []
    bing_calls: list[object] = []

    async def search_analytics_anomalies(request: object) -> SearchAnalyticsAnomalyReport:
        google_calls.append(request)
        return SearchAnalyticsAnomalyReport((), False)

    async def traffic_anomalies(request: object) -> BingTrafficAnomalyReport:
        bing_calls.append(request)
        return BingTrafficAnomalyReport(())

    monkeypatch.setattr(
        service._google_search_console,
        "search_analytics_anomalies",
        search_analytics_anomalies,
    )
    monkeypatch.setattr(service._bing_webmaster, "traffic_anomalies", traffic_anomalies)
    request = SearchEngineTrafficHealthRequest(
        google_search_console_account_id="pagespeed-main",
        google_search_console_site_url="https://example.com/",
        bing_account_id="bing-main",
        bing_site_url="https://example.com/",
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 2),
    )

    assert await service.search_engine_traffic_health(request) == SearchEngineTrafficHealthReport(
        google_search_console=SearchAnalyticsAnomalyReport((), False),
        bing=BingTrafficAnomalyReport(()),
    )
    assert google_calls == [request.google_request()]
    assert bing_calls == [request.bing_request()]


@pytest.mark.asyncio
async def test_search_engine_traffic_health_denies_before_either_service_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service()
    google_calls: list[object] = []
    bing_calls: list[object] = []

    async def search_analytics_anomalies(request: object) -> SearchAnalyticsAnomalyReport:
        google_calls.append(request)
        return SearchAnalyticsAnomalyReport((), False)

    async def traffic_anomalies(request: object) -> BingTrafficAnomalyReport:
        bing_calls.append(request)
        return BingTrafficAnomalyReport(())

    monkeypatch.setattr(
        service._google_search_console,
        "search_analytics_anomalies",
        search_analytics_anomalies,
    )
    monkeypatch.setattr(service._bing_webmaster, "traffic_anomalies", traffic_anomalies)

    with pytest.raises(BoundaryDeniedError):
        await service.search_engine_traffic_health(
            SearchEngineTrafficHealthRequest(
                google_search_console_account_id="pagespeed-main",
                google_search_console_site_url="https://example.com/",
                bing_account_id="pagespeed-main",
                bing_site_url="https://example.com/",
                start_date=date(2026, 7, 1),
                end_date=date(2026, 7, 2),
            )
        )

    assert google_calls == []
    assert bing_calls == []


@pytest.mark.asyncio
async def test_ga4_search_console_comparison_preserves_separate_observations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service()
    ga4_calls: list[object] = []
    google_calls: list[object] = []

    async def organic_search_landing_pages(request: object) -> Ga4FixedReport:
        ga4_calls.append(request)
        return _organic_search_report()

    async def search_analytics_summary(request: object) -> SearchAnalyticsMetrics:
        google_calls.append(request)
        return SearchAnalyticsMetrics(10.0, 100.0, 0.1, 3.0)

    monkeypatch.setattr(
        service._google_analytics,
        "organic_search_landing_pages",
        organic_search_landing_pages,
    )
    monkeypatch.setattr(
        service._google_search_console,
        "search_analytics_summary",
        search_analytics_summary,
    )
    request = Ga4SearchConsoleComparisonRequest(
        google_analytics_account_id="google-main",
        property_id="123456789",
        google_search_console_account_id="pagespeed-main",
        site_url="https://example.com/",
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 2),
    )

    assert await service.ga4_search_console_comparison(request) == Ga4SearchConsoleComparisonReport(
        ga4_organic_search=_organic_search_report(),
        google_search_console=SearchAnalyticsMetrics(10.0, 100.0, 0.1, 3.0),
    )
    assert ga4_calls == [request.ga4_request()]
    assert google_calls == [request.search_console_request()]


@pytest.mark.asyncio
async def test_ga4_search_console_comparison_denies_before_either_service_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service()
    ga4_calls: list[object] = []
    google_calls: list[object] = []

    async def organic_search_landing_pages(request: object) -> Ga4FixedReport:
        ga4_calls.append(request)
        return _organic_search_report()

    async def search_analytics_summary(request: object) -> SearchAnalyticsMetrics:
        google_calls.append(request)
        return SearchAnalyticsMetrics(0.0, 0.0, 0.0, 0.0)

    monkeypatch.setattr(
        service._google_analytics,
        "organic_search_landing_pages",
        organic_search_landing_pages,
    )
    monkeypatch.setattr(
        service._google_search_console,
        "search_analytics_summary",
        search_analytics_summary,
    )

    await service.ga4_search_console_comparison(
        Ga4SearchConsoleComparisonRequest(
            google_analytics_account_id="pagespeed-main",
            property_id="123456789",
            google_search_console_account_id="pagespeed-main",
            site_url="https://example.com/",
            start_date=date(2026, 7, 1),
            end_date=date(2026, 7, 2),
        )
    )

    assert len(ga4_calls) == 1
    assert len(google_calls) == 1
