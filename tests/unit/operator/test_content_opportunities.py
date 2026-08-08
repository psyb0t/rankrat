from __future__ import annotations

from datetime import date
from typing import cast

import pytest

from rankrat.operator.content_opportunities import (
    ContentOpportunityOperator,
    ContentOpportunityRequest,
    OpportunityConfidence,
)
from rankrat.providers.google_analytics import (
    Ga4MetricHeader,
    Ga4MetricType,
    Ga4ReportResult,
    Ga4ReportRow,
)
from rankrat.providers.google_search_console import SearchAnalyticsReport, SearchAnalyticsRow
from rankrat.services.bing import (
    BingPerformanceReport,
    BingPerformanceRow,
    BingWebmasterService,
)
from rankrat.services.google_analytics import (
    Ga4FixedReport,
    Ga4FixedReportKind,
    GoogleAnalyticsDataService,
)
from rankrat.services.google_search_console import GoogleSearchConsoleService
from rankrat.services.site_audit import SiteAuditPage, SiteAuditReport, SiteAuditService


class _SearchConsoleFake:
    async def search_analytics(self, _: object) -> SearchAnalyticsReport:
        return SearchAnalyticsReport(
            (
                SearchAnalyticsRow(
                    ("useful query", "https://example.com/page"),
                    2,
                    200,
                    0.01,
                    8,
                ),
                SearchAnalyticsRow(
                    ("too little evidence", "https://example.com/other"),
                    0,
                    1,
                    0,
                    30,
                ),
            ),
            None,
        )


class _BingFake:
    async def query_performance(self, _: object) -> BingPerformanceReport:
        return BingPerformanceReport(
            (
                BingPerformanceRow("bing query", "2025-01-01", 1, 100, 5, 9),
                BingPerformanceRow("bing query", "2025-01-02", 2, 50, 4, 12),
                BingPerformanceRow("outside period", "2024-12-31", 99, 999, 1, 1),
            )
        )


class _AnalyticsFake:
    async def landing_page_performance(self, _: object) -> Ga4FixedReport:
        return Ga4FixedReport(
            Ga4FixedReportKind.LANDING_PAGE_PERFORMANCE,
            Ga4ReportResult(
                ("landingPage",),
                (Ga4MetricHeader("sessions", Ga4MetricType.INTEGER),),
                (Ga4ReportRow(("/page",), ("0",)),),
                1,
            ),
        )


class _SiteAuditFake:
    async def audit(self, _: object) -> SiteAuditReport:
        return SiteAuditReport(
            "https://example.com/",
            80,
            (
                SiteAuditPage(
                    "https://example.com/page",
                    200,
                    "Page",
                    "https://example.com/page",
                    0,
                    0,
                    2,
                ),
            ),
            (),
            (),
            False,
        )


@pytest.mark.asyncio
async def test_content_opportunities_are_evidence_backed_and_ranked() -> None:
    operator = ContentOpportunityOperator(
        cast(GoogleSearchConsoleService, _SearchConsoleFake()),
        cast(BingWebmasterService, _BingFake()),
        cast(GoogleAnalyticsDataService, _AnalyticsFake()),
        cast(SiteAuditService, _SiteAuditFake()),
    )
    report = await operator.report(
        ContentOpportunityRequest(
            "google-main",
            "sc-domain:example.com",
            "bing-main",
            "https://example.com/",
            "ga4-main",
            "123",
            "pagespeed-main",
            "https://example.com/",
            date(2025, 1, 1),
            date(2025, 1, 31),
            10,
        )
    )

    google = next(item for item in report.opportunities if item.query == "useful query")
    assert google.confidence is OpportunityConfidence.HIGH
    assert google.evidence_sources == (
        "google_search_console",
        "google_analytics",
        "site_crawl",
    )
    assert set(google.reasons) == {
        "low_click_through_rate",
        "striking_distance",
        "search_visibility_without_sessions",
        "page_has_technical_issues",
    }
    assert all(item.query != "too little evidence" for item in report.opportunities)
    bing = next(item for item in report.opportunities if item.query == "bing query")
    assert bing.clicks == 3
    assert bing.impressions == 150
    assert bing.average_position == 10
    assert all(item.query != "outside period" for item in report.opportunities)
    assert report.insufficient_evidence is False
