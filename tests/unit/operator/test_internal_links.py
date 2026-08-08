from __future__ import annotations

from datetime import date
from typing import cast

import pytest

from rankrat.operator.internal_links import (
    InternalLinkOperator,
    InternalLinkRequest,
    OrphanPageRequest,
)
from rankrat.providers.google_analytics import (
    Ga4MetricHeader,
    Ga4MetricType,
    Ga4ReportResult,
    Ga4ReportRow,
)
from rankrat.services.google_analytics import (
    Ga4FixedReport,
    Ga4FixedReportKind,
    GoogleAnalyticsDataService,
)
from rankrat.services.google_search_console import (
    GoogleSearchConsoleService,
    SearchAnalyticsDimensionReport,
    SearchAnalyticsDimensionReportRow,
    SearchAnalyticsMetrics,
)
from rankrat.services.site_audit import (
    SiteAuditPage,
    SiteAuditReport,
    SiteAuditService,
)


def _crawl() -> SiteAuditReport:
    return SiteAuditReport(
        "https://example.com/",
        90,
        (
            SiteAuditPage(
                "https://example.com/",
                200,
                "Home",
                "https://example.com/",
                1,
                0,
                0,
                ("https://example.com/authority",),
                0,
                False,
            ),
            SiteAuditPage(
                "https://example.com/authority",
                200,
                "Authority",
                "https://example.com/authority",
                0,
                0,
                0,
                (),
                1,
                False,
            ),
            SiteAuditPage(
                "https://example.com/orphan",
                200,
                "Authority orphan analysis",
                "https://example.com/orphan",
                0,
                0,
                1,
                (),
                1,
                True,
            ),
        ),
        (),
        ("https://example.com/sitemap.xml",),
        False,
    )


class _SiteAuditFake:
    async def audit(self, _: object) -> SiteAuditReport:
        return _crawl()


class _SearchConsoleFake:
    async def search_analytics_page_performance(
        self,
        _: object,
    ) -> SearchAnalyticsDimensionReport:
        return SearchAnalyticsDimensionReport(
            (
                SearchAnalyticsDimensionReportRow(
                    "https://example.com/orphan",
                    SearchAnalyticsMetrics(1, 10, 0.1, 5),
                ),
                SearchAnalyticsDimensionReportRow(
                    "https://example.com/search-only",
                    SearchAnalyticsMetrics(1, 10, 0.1, 5),
                ),
                SearchAnalyticsDimensionReportRow(
                    "https://other.example/foreign",
                    SearchAnalyticsMetrics(1, 10, 0.1, 5),
                ),
            ),
            False,
        )


class _AnalyticsFake:
    async def landing_page_performance(self, _: object) -> Ga4FixedReport:
        return Ga4FixedReport(
            Ga4FixedReportKind.LANDING_PAGE_PERFORMANCE,
            Ga4ReportResult(
                ("landingPage",),
                (Ga4MetricHeader("sessions", Ga4MetricType.INTEGER),),
                (
                    Ga4ReportRow(("/orphan",), ("3",)),
                    Ga4ReportRow(("/analytics-only",), ("2",)),
                    Ga4ReportRow(("https://other.example/foreign",), ("2",)),
                ),
                2,
            ),
        )


def _operator() -> InternalLinkOperator:
    return InternalLinkOperator(
        cast(SiteAuditService, _SiteAuditFake()),
        cast(GoogleSearchConsoleService, _SearchConsoleFake()),
        cast(GoogleAnalyticsDataService, _AnalyticsFake()),
    )


@pytest.mark.asyncio
async def test_internal_link_graph_and_opportunities_are_deterministic() -> None:
    request = InternalLinkRequest("pagespeed-main", "https://example.com/", 10, 2, 10)
    graph = await _operator().graph(request)
    assert [(node.url, node.inbound_links) for node in graph.nodes] == [
        ("https://example.com/", 0),
        ("https://example.com/authority", 1),
        ("https://example.com/orphan", 0),
    ]
    assert [(edge.source_url, edge.target_url) for edge in graph.edges] == [
        ("https://example.com/", "https://example.com/authority")
    ]

    opportunities = await _operator().opportunities(request)
    assert [(item.source_url, item.target_url) for item in opportunities.opportunities] == [
        ("https://example.com/orphan", "https://example.com/authority")
    ]
    assert opportunities.opportunities[0].suggested_anchor == "Authority"


@pytest.mark.asyncio
async def test_orphan_report_joins_crawl_search_and_analytics_evidence() -> None:
    report = await _operator().orphans(
        OrphanPageRequest(
            "pagespeed-main",
            "https://example.com/",
            "google-main",
            "sc-domain:example.com",
            "ga4-main",
            "123",
            date(2025, 1, 1),
            date(2025, 1, 31),
            10,
            2,
        )
    )
    by_url = {item.url: item for item in report.findings}
    assert by_url["https://example.com/orphan"].classification == ("sitemap_without_internal_links")
    assert by_url["https://example.com/search-only"].classification == (
        "search_without_internal_links"
    )
    assert by_url["https://example.com/analytics-only"].classification == (
        "analytics_without_internal_links"
    )
    assert "https://other.example/foreign" not in by_url
