"""Bounded cross-provider reports composed from existing authorized services."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date
from urllib.parse import urlsplit

from rankrat.constants import DEFAULT_PROVIDER_TIMEOUT_SECONDS
from rankrat.errors import InputLimitError
from rankrat.models.boundaries import Provider, ResourceKind
from rankrat.policy.boundaries import BoundaryPolicy
from rankrat.providers.google_analytics import Ga4ReportRow
from rankrat.services.bing import (
    BingTrafficAnomalyReport,
    BingTrafficMetrics,
    BingTrafficPeriodRequest,
    BingTrafficTrendReport,
    BingWebmasterService,
)
from rankrat.services.google_analytics import (
    Ga4FixedReport,
    Ga4FixedReportRequest,
    GoogleAnalyticsDataService,
)
from rankrat.services.google_search_console import (
    GoogleSearchConsoleService,
    SearchAnalyticsAnomalyReport,
    SearchAnalyticsMetrics,
    SearchAnalyticsSummaryRequest,
    SearchAnalyticsTrendRequest,
)
from rankrat.services.pagespeed import (
    PageSpeedAnalysisReport,
    PageSpeedAnalysisRequest,
    PageSpeedService,
    PageSpeedStrategy,
)


@dataclass(frozen=True, slots=True)
class Ga4PageSpeedCorrelationRequest:
    """One configured property's GA4 content row paired with one PageSpeed URL."""

    google_analytics_account_id: str
    property_id: str
    pagespeed_account_id: str
    site_url: str
    page_url: str
    start_date: date
    end_date: date
    strategy: PageSpeedStrategy = PageSpeedStrategy.DESKTOP
    timeout_seconds: float = DEFAULT_PROVIDER_TIMEOUT_SECONDS


@dataclass(frozen=True, slots=True)
class Ga4PageSpeedCorrelationReport:
    """One explicit correlation, without a causal recommendation or inference."""

    requested_page_path: str
    ga4_content_row: Ga4ReportRow | None
    pagespeed: PageSpeedAnalysisReport


@dataclass(frozen=True, slots=True)
class SearchEngineComparisonRequest:
    """One bounded Google Search Console and Bing site comparison."""

    google_search_console_account_id: str
    google_search_console_site_url: str
    bing_account_id: str
    bing_site_url: str
    start_date: date
    end_date: date
    timeout_seconds: float = DEFAULT_PROVIDER_TIMEOUT_SECONDS

    def google_request(self) -> SearchAnalyticsSummaryRequest:
        """Build the fixed Google aggregate request without caller filters."""

        return SearchAnalyticsSummaryRequest(
            account_id=self.google_search_console_account_id,
            site_url=self.google_search_console_site_url,
            start_date=self.start_date,
            end_date=self.end_date,
            timeout_seconds=self.timeout_seconds,
        )

    def bing_request(self) -> BingTrafficPeriodRequest:
        """Build the exact Bing traffic interval without widening scope."""

        return BingTrafficPeriodRequest(
            account_id=self.bing_account_id,
            site_url=self.bing_site_url,
            start_date=self.start_date,
            end_date=self.end_date,
            timeout_seconds=self.timeout_seconds,
        )


@dataclass(frozen=True, slots=True)
class SearchEngineComparisonReport:
    """Separate Google and Bing observations, not a combined market claim."""

    start_date: str
    end_date: str
    google_search_console: SearchAnalyticsMetrics
    bing: BingTrafficMetrics


@dataclass(frozen=True, slots=True)
class Ga4SearchConsoleComparisonRequest:
    """One configured GA4 property and Search Console site comparison."""

    google_analytics_account_id: str
    property_id: str
    google_search_console_account_id: str
    site_url: str
    start_date: date
    end_date: date
    timeout_seconds: float = DEFAULT_PROVIDER_TIMEOUT_SECONDS

    def ga4_request(self) -> Ga4FixedReportRequest:
        """Build the fixed GA4 organic-search report request."""

        return Ga4FixedReportRequest(
            account_id=self.google_analytics_account_id,
            property_id=self.property_id,
            start_date=self.start_date,
            end_date=self.end_date,
            timeout_seconds=self.timeout_seconds,
        )

    def search_console_request(self) -> SearchAnalyticsSummaryRequest:
        """Build the fixed Search Console aggregate request without filters."""

        return SearchAnalyticsSummaryRequest(
            account_id=self.google_search_console_account_id,
            site_url=self.site_url,
            start_date=self.start_date,
            end_date=self.end_date,
            timeout_seconds=self.timeout_seconds,
        )


@dataclass(frozen=True, slots=True)
class Ga4SearchConsoleComparisonReport:
    """Separate GA4 linked-organic and Search Console observations."""

    ga4_organic_search: Ga4FixedReport
    google_search_console: SearchAnalyticsMetrics


@dataclass(frozen=True, slots=True)
class SearchEngineTrafficHealthRequest:
    """One bounded Google Search Console and Bing traffic-health comparison."""

    google_search_console_account_id: str
    google_search_console_site_url: str
    bing_account_id: str
    bing_site_url: str
    start_date: date
    end_date: date
    timeout_seconds: float = DEFAULT_PROVIDER_TIMEOUT_SECONDS

    def google_request(self) -> SearchAnalyticsTrendRequest:
        """Build the fixed Google daily-trend request without caller filters."""

        return SearchAnalyticsTrendRequest(
            account_id=self.google_search_console_account_id,
            site_url=self.google_search_console_site_url,
            start_date=self.start_date,
            end_date=self.end_date,
            timeout_seconds=self.timeout_seconds,
        )

    def bing_request(self) -> BingTrafficPeriodRequest:
        """Build the exact Bing traffic interval without widening scope."""

        return BingTrafficPeriodRequest(
            account_id=self.bing_account_id,
            site_url=self.bing_site_url,
            start_date=self.start_date,
            end_date=self.end_date,
            timeout_seconds=self.timeout_seconds,
        )


@dataclass(frozen=True, slots=True)
class SearchEngineTrafficHealthReport:
    """Separate engine-specific trend anomalies without a combined diagnosis."""

    google_search_console: SearchAnalyticsAnomalyReport
    bing: BingTrafficAnomalyReport


class CrossProviderService:
    """Compose two already-bounded provider services without expanding authority."""

    def __init__(
        self,
        policy: BoundaryPolicy,
        google_analytics: GoogleAnalyticsDataService,
        pagespeed: PageSpeedService,
        google_search_console: GoogleSearchConsoleService,
        bing_webmaster: BingWebmasterService,
    ) -> None:
        self._policy = policy
        self._google_analytics = google_analytics
        self._pagespeed = pagespeed
        self._google_search_console = google_search_console
        self._bing_webmaster = bing_webmaster

    async def ga4_pagespeed_correlation(
        self,
        request: Ga4PageSpeedCorrelationRequest,
    ) -> Ga4PageSpeedCorrelationReport:
        """Return a matched GA4 content row and one PageSpeed analysis concurrently."""

        self._policy.require_google_read_resource(
            request.google_analytics_account_id,
            ResourceKind.GA4_PROPERTY,
            request.property_id,
        )
        self._policy.require_resource(
            request.pagespeed_account_id,
            Provider.GOOGLE,
            ResourceKind.PAGESPEED_SITE,
            request.site_url,
        )
        authorized_page_url = self._policy.require_pagespeed_url(
            request.pagespeed_account_id,
            request.site_url,
            request.page_url,
        )
        requested_page_path = _page_path(authorized_page_url)
        ga4_report, pagespeed_report = await asyncio.gather(
            self._google_analytics.content_performance(
                Ga4FixedReportRequest(
                    request.google_analytics_account_id,
                    request.property_id,
                    request.start_date,
                    request.end_date,
                    timeout_seconds=request.timeout_seconds,
                )
            ),
            self._pagespeed.analyze(
                PageSpeedAnalysisRequest(
                    request.pagespeed_account_id,
                    request.site_url,
                    authorized_page_url,
                    strategy=request.strategy,
                    timeout_seconds=request.timeout_seconds,
                )
            ),
        )
        return Ga4PageSpeedCorrelationReport(
            requested_page_path,
            _matched_ga4_content_row(ga4_report.report.rows, requested_page_path),
            pagespeed_report,
        )

    async def search_engine_comparison(
        self,
        request: SearchEngineComparisonRequest,
    ) -> SearchEngineComparisonReport:
        """Compare separately authorized Google and Bing aggregate observations."""

        google_request = request.google_request()
        bing_request = request.bing_request()
        self._policy.require_google_read_resource(
            request.google_search_console_account_id,
            ResourceKind.SEARCH_CONSOLE_SITE,
            request.google_search_console_site_url,
        )
        self._policy.require_resource(
            request.bing_account_id,
            Provider.BING,
            ResourceKind.BING_SITE,
            request.bing_site_url,
        )
        google_metrics, bing_trend = await asyncio.gather(
            self._google_search_console.search_analytics_summary(google_request),
            self._bing_webmaster.traffic_trend(bing_request),
        )
        return SearchEngineComparisonReport(
            start_date=request.start_date.isoformat(),
            end_date=request.end_date.isoformat(),
            google_search_console=google_metrics,
            bing=_bing_traffic_total(bing_trend),
        )

    async def ga4_search_console_comparison(
        self,
        request: Ga4SearchConsoleComparisonRequest,
    ) -> Ga4SearchConsoleComparisonReport:
        """Return separate configured GA4 organic and Search Console observations."""

        ga4_request = request.ga4_request()
        search_console_request = request.search_console_request()
        self._policy.require_google_read_resource(
            request.google_analytics_account_id,
            ResourceKind.GA4_PROPERTY,
            request.property_id,
        )
        self._policy.require_google_read_resource(
            request.google_search_console_account_id,
            ResourceKind.SEARCH_CONSOLE_SITE,
            request.site_url,
        )
        ga4_organic_search, google_search_console = await asyncio.gather(
            self._google_analytics.organic_search_landing_pages(ga4_request),
            self._google_search_console.search_analytics_summary(search_console_request),
        )
        return Ga4SearchConsoleComparisonReport(
            ga4_organic_search=ga4_organic_search,
            google_search_console=google_search_console,
        )

    async def search_engine_traffic_health(
        self,
        request: SearchEngineTrafficHealthRequest,
    ) -> SearchEngineTrafficHealthReport:
        """Return separate daily traffic anomaly observations for two authorized engines."""

        google_request = request.google_request()
        bing_request = request.bing_request()
        self._policy.require_google_read_resource(
            request.google_search_console_account_id,
            ResourceKind.SEARCH_CONSOLE_SITE,
            request.google_search_console_site_url,
        )
        self._policy.require_resource(
            request.bing_account_id,
            Provider.BING,
            ResourceKind.BING_SITE,
            request.bing_site_url,
        )
        google_search_console, bing = await asyncio.gather(
            self._google_search_console.search_analytics_anomalies(google_request),
            self._bing_webmaster.traffic_anomalies(bing_request),
        )
        return SearchEngineTrafficHealthReport(
            google_search_console=google_search_console,
            bing=bing,
        )


def _page_path(page_url: str) -> str:
    parsed = urlsplit(page_url)
    return parsed.path or "/"


def _matched_ga4_content_row(
    rows: tuple[Ga4ReportRow, ...],
    requested_page_path: str,
) -> Ga4ReportRow | None:
    matching_rows = tuple(
        row
        for row in rows
        if len(row.dimension_values) == 1 and row.dimension_values[0] == requested_page_path
    )
    if len(matching_rows) > 1:
        raise InputLimitError("GA4 content report contains duplicate requested page rows")
    if not matching_rows:
        return None
    return matching_rows[0]


def _bing_traffic_total(report: BingTrafficTrendReport) -> BingTrafficMetrics:
    return BingTrafficMetrics(
        clicks=sum(point.metrics.clicks for point in report.points),
        impressions=sum(point.metrics.impressions for point in report.points),
    )
