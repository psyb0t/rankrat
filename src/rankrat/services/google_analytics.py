"""Bounded Google Analytics Data API reports for configured GA4 properties."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from rankrat.constants import (
    DEFAULT_PROVIDER_TIMEOUT_SECONDS,
    GA4_AUDIENCE_SEGMENT_DIMENSIONS,
    GA4_AUDIENCE_SEGMENT_METRICS,
    GA4_CONTENT_PERFORMANCE_DIMENSIONS,
    GA4_CONTENT_PERFORMANCE_METRICS,
    GA4_ECOMMERCE_PERFORMANCE_DIMENSIONS,
    GA4_ECOMMERCE_PERFORMANCE_METRICS,
    GA4_LANDING_PAGE_PERFORMANCE_DIMENSIONS,
    GA4_LANDING_PAGE_PERFORMANCE_METRICS,
    GA4_ORGANIC_SEARCH_LANDING_PAGE_DIMENSIONS,
    GA4_ORGANIC_SEARCH_LANDING_PAGE_METRICS,
    GA4_TRAFFIC_SOURCE_PERFORMANCE_DIMENSIONS,
    GA4_TRAFFIC_SOURCE_PERFORMANCE_METRICS,
    GA4_USER_BEHAVIOR_DIMENSIONS,
    GA4_USER_BEHAVIOR_METRICS,
    MAX_ANALYTICS_DATE_RANGE_DAYS,
    MAX_GA4_DATE_RANGES,
    MAX_GA4_DIMENSIONS,
    MAX_GA4_FIELD_NAME_CHARS,
    MAX_GA4_FUNNEL_STEPS,
    MAX_GA4_METRICS,
    MAX_GA4_OFFSET,
    MAX_GA4_ROWS,
    MIN_GA4_FUNNEL_STEPS,
)
from rankrat.errors import InputLimitError
from rankrat.models.boundaries import ResourceKind
from rankrat.policy.boundaries import BoundaryPolicy
from rankrat.providers.base import AccountId, ProviderReadRequest
from rankrat.providers.google_analytics import (
    Ga4AccountSummary,
    Ga4DateRangeInput,
    Ga4FunnelQuery,
    Ga4FunnelReport,
    Ga4ReportQuery,
    Ga4ReportResult,
    GoogleAnalyticsDataClient,
)

_GA4_FIELD_NAME_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_:]*$")


def _require_field_names(field_names: tuple[str, ...], subject: str, maximum: int) -> None:
    if not field_names or len(field_names) > maximum:
        raise InputLimitError(f"GA4 {subject} count is outside the allowed range")
    if len(set(field_names)) != len(field_names):
        raise InputLimitError(f"GA4 {subject} must not repeat")
    if any(
        len(field_name) > MAX_GA4_FIELD_NAME_CHARS
        or _GA4_FIELD_NAME_PATTERN.fullmatch(field_name) is None
        for field_name in field_names
    ):
        raise InputLimitError(f"GA4 {subject} contains an invalid name")


@dataclass(frozen=True, slots=True)
class Ga4DateRange:
    """One bounded absolute GA4 historical reporting period."""

    start_date: date
    end_date: date

    def __post_init__(self) -> None:
        if self.end_date < self.start_date:
            raise InputLimitError("GA4 end date precedes start date")
        if (self.end_date - self.start_date).days + 1 > MAX_ANALYTICS_DATE_RANGE_DAYS:
            raise InputLimitError("GA4 date range exceeds the allowed size")


@dataclass(frozen=True, slots=True)
class Ga4AccountDiscoveryRequest:
    """One account-wide GA4 inventory request for an OAuth discovery boundary."""

    account_id: str
    timeout_seconds: float = DEFAULT_PROVIDER_TIMEOUT_SECONDS


@dataclass(frozen=True, slots=True)
class Ga4ReportRequest:
    """One bounded historical GA4 report for an exact configured property."""

    account_id: str
    property_id: str
    date_ranges: tuple[Ga4DateRange, ...]
    dimensions: tuple[str, ...]
    metrics: tuple[str, ...]
    limit: int = MAX_GA4_ROWS
    offset: int = 0
    timeout_seconds: float = DEFAULT_PROVIDER_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        if not 1 <= len(self.date_ranges) <= MAX_GA4_DATE_RANGES:
            raise InputLimitError("GA4 date range count is outside the allowed range")
        _require_field_names(self.dimensions, "dimension", MAX_GA4_DIMENSIONS)
        _require_field_names(self.metrics, "metric", MAX_GA4_METRICS)
        if not 1 <= self.limit <= MAX_GA4_ROWS:
            raise InputLimitError("GA4 report limit is outside the allowed range")
        if not 0 <= self.offset <= MAX_GA4_OFFSET:
            raise InputLimitError("GA4 report offset is outside the allowed range")


@dataclass(frozen=True, slots=True)
class Ga4RealtimeReportRequest:
    """One bounded realtime GA4 report for an exact configured property."""

    account_id: str
    property_id: str
    dimensions: tuple[str, ...]
    metrics: tuple[str, ...]
    limit: int = MAX_GA4_ROWS
    timeout_seconds: float = DEFAULT_PROVIDER_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        _require_field_names(self.dimensions, "dimension", MAX_GA4_DIMENSIONS)
        _require_field_names(self.metrics, "metric", MAX_GA4_METRICS)
        if not 1 <= self.limit <= MAX_GA4_ROWS:
            raise InputLimitError("GA4 report limit is outside the allowed range")


@dataclass(frozen=True, slots=True)
class Ga4FixedReportRequest:
    """One fixed-field historical GA4 report for an exact configured property."""

    account_id: str
    property_id: str
    start_date: date
    end_date: date
    limit: int = MAX_GA4_ROWS
    timeout_seconds: float = DEFAULT_PROVIDER_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        Ga4DateRange(self.start_date, self.end_date)
        if not 1 <= self.limit <= MAX_GA4_ROWS:
            raise InputLimitError("GA4 report limit is outside the allowed range")


@dataclass(frozen=True, slots=True)
class Ga4ConversionFunnelRequest:
    """A bounded closed event-step funnel for one configured GA4 property."""

    account_id: str
    property_id: str
    start_date: date
    end_date: date
    event_names: tuple[str, ...]
    limit: int = MAX_GA4_ROWS
    timeout_seconds: float = DEFAULT_PROVIDER_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        Ga4DateRange(self.start_date, self.end_date)
        if not MIN_GA4_FUNNEL_STEPS <= len(self.event_names) <= MAX_GA4_FUNNEL_STEPS:
            raise InputLimitError("GA4 funnel step count is outside the allowed range")
        _require_field_names(self.event_names, "funnel event", MAX_GA4_FUNNEL_STEPS)
        if not 1 <= self.limit <= MAX_GA4_ROWS:
            raise InputLimitError("GA4 funnel report limit is outside the allowed range")


class Ga4FixedReportKind(StrEnum):
    """The local fixed GA4 reports whose fields callers cannot override."""

    CONTENT_PERFORMANCE = "content_performance"
    LANDING_PAGE_PERFORMANCE = "landing_page_performance"
    ORGANIC_SEARCH_LANDING_PAGES = "organic_search_landing_pages"
    TRAFFIC_SOURCE_PERFORMANCE = "traffic_source_performance"
    ECOMMERCE_PERFORMANCE = "ecommerce_performance"
    AUDIENCE_SEGMENTS = "audience_segments"
    USER_BEHAVIOR = "user_behavior"


@dataclass(frozen=True, slots=True)
class Ga4FixedReport:
    """One immutable fixed-field GA4 report with its explicit local kind."""

    kind: Ga4FixedReportKind
    report: Ga4ReportResult


class GoogleAnalyticsDataService:
    """Application layer for useful GA4 historical and realtime reports."""

    def __init__(self, policy: BoundaryPolicy, client: GoogleAnalyticsDataClient) -> None:
        self._policy = policy
        self._client = client

    async def list_account_summaries(
        self,
        request: Ga4AccountDiscoveryRequest,
    ) -> tuple[Ga4AccountSummary, ...]:
        """Return the GA4 accounts and properties reachable by this OAuth account."""

        self._policy.require_google_account(request.account_id)
        return await self._client.list_account_summaries(
            ProviderReadRequest(AccountId(request.account_id), request.timeout_seconds)
        )

    async def run_report(self, request: Ga4ReportRequest) -> Ga4ReportResult:
        """Run one policy-authorized historical GA4 report."""

        self._require_property(request.account_id, request.property_id)
        return await self._client.run_report(
            ProviderReadRequest(AccountId(request.account_id), request.timeout_seconds),
            request.property_id,
            Ga4ReportQuery(
                date_ranges=tuple(
                    Ga4DateRangeInput(
                        start_date=date_range.start_date.isoformat(),
                        end_date=date_range.end_date.isoformat(),
                    )
                    for date_range in request.date_ranges
                ),
                dimensions=request.dimensions,
                metrics=request.metrics,
                limit=request.limit,
                offset=request.offset,
            ),
        )

    async def run_realtime_report(self, request: Ga4RealtimeReportRequest) -> Ga4ReportResult:
        """Run one policy-authorized realtime GA4 report."""

        self._require_property(request.account_id, request.property_id)
        return await self._client.run_realtime_report(
            ProviderReadRequest(AccountId(request.account_id), request.timeout_seconds),
            request.property_id,
            Ga4ReportQuery(
                date_ranges=None,
                dimensions=request.dimensions,
                metrics=request.metrics,
                limit=request.limit,
                offset=None,
            ),
        )

    async def conversion_funnel(
        self,
        request: Ga4ConversionFunnelRequest,
    ) -> Ga4FunnelReport:
        """Return one configured property's bounded closed event-step funnel."""

        self._require_property(request.account_id, request.property_id)
        return await self._client.run_funnel_report(
            ProviderReadRequest(AccountId(request.account_id), request.timeout_seconds),
            request.property_id,
            Ga4FunnelQuery(
                date_range=Ga4DateRangeInput(
                    start_date=request.start_date.isoformat(),
                    end_date=request.end_date.isoformat(),
                ),
                event_names=request.event_names,
                limit=request.limit,
            ),
        )

    async def content_performance(self, request: Ga4FixedReportRequest) -> Ga4FixedReport:
        """Return fixed page-path content performance for one configured GA4 property."""

        return await self._fixed_report(
            request,
            Ga4FixedReportKind.CONTENT_PERFORMANCE,
            GA4_CONTENT_PERFORMANCE_DIMENSIONS,
            GA4_CONTENT_PERFORMANCE_METRICS,
        )

    async def landing_page_performance(self, request: Ga4FixedReportRequest) -> Ga4FixedReport:
        """Return fixed landing-page performance for one configured GA4 property."""

        return await self._fixed_report(
            request,
            Ga4FixedReportKind.LANDING_PAGE_PERFORMANCE,
            GA4_LANDING_PAGE_PERFORMANCE_DIMENSIONS,
            GA4_LANDING_PAGE_PERFORMANCE_METRICS,
        )

    async def traffic_source_performance(self, request: Ga4FixedReportRequest) -> Ga4FixedReport:
        """Return fixed session-source performance for one configured GA4 property."""

        return await self._fixed_report(
            request,
            Ga4FixedReportKind.TRAFFIC_SOURCE_PERFORMANCE,
            GA4_TRAFFIC_SOURCE_PERFORMANCE_DIMENSIONS,
            GA4_TRAFFIC_SOURCE_PERFORMANCE_METRICS,
        )

    async def organic_search_landing_pages(self, request: Ga4FixedReportRequest) -> Ga4FixedReport:
        """Return Search Console-linked organic-search metrics by GA4 landing page."""

        return await self._fixed_report(
            request,
            Ga4FixedReportKind.ORGANIC_SEARCH_LANDING_PAGES,
            GA4_ORGANIC_SEARCH_LANDING_PAGE_DIMENSIONS,
            GA4_ORGANIC_SEARCH_LANDING_PAGE_METRICS,
        )

    async def ecommerce_performance(self, request: Ga4FixedReportRequest) -> Ga4FixedReport:
        """Return fixed item-level ecommerce metrics for one configured GA4 property."""

        return await self._fixed_report(
            request,
            Ga4FixedReportKind.ECOMMERCE_PERFORMANCE,
            GA4_ECOMMERCE_PERFORMANCE_DIMENSIONS,
            GA4_ECOMMERCE_PERFORMANCE_METRICS,
        )

    async def audience_segments(self, request: Ga4FixedReportRequest) -> Ga4FixedReport:
        """Return fixed audience-segment metrics for one configured GA4 property."""

        return await self._fixed_report(
            request,
            Ga4FixedReportKind.AUDIENCE_SEGMENTS,
            GA4_AUDIENCE_SEGMENT_DIMENSIONS,
            GA4_AUDIENCE_SEGMENT_METRICS,
        )

    async def user_behavior(self, request: Ga4FixedReportRequest) -> Ga4FixedReport:
        """Return fixed new-versus-returning engagement metrics for one property."""

        return await self._fixed_report(
            request,
            Ga4FixedReportKind.USER_BEHAVIOR,
            GA4_USER_BEHAVIOR_DIMENSIONS,
            GA4_USER_BEHAVIOR_METRICS,
        )

    async def fixed_report(
        self,
        request: Ga4FixedReportRequest,
        kind: Ga4FixedReportKind,
    ) -> Ga4FixedReport:
        """Run one named local GA4 report without caller-selected fields."""

        if kind is Ga4FixedReportKind.CONTENT_PERFORMANCE:
            return await self.content_performance(request)
        if kind is Ga4FixedReportKind.LANDING_PAGE_PERFORMANCE:
            return await self.landing_page_performance(request)
        if kind is Ga4FixedReportKind.ORGANIC_SEARCH_LANDING_PAGES:
            return await self.organic_search_landing_pages(request)
        if kind is Ga4FixedReportKind.TRAFFIC_SOURCE_PERFORMANCE:
            return await self.traffic_source_performance(request)
        if kind is Ga4FixedReportKind.ECOMMERCE_PERFORMANCE:
            return await self.ecommerce_performance(request)
        if kind is Ga4FixedReportKind.AUDIENCE_SEGMENTS:
            return await self.audience_segments(request)
        if kind is Ga4FixedReportKind.USER_BEHAVIOR:
            return await self.user_behavior(request)
        raise InputLimitError("GA4 fixed report kind is unsupported")

    async def _fixed_report(
        self,
        request: Ga4FixedReportRequest,
        kind: Ga4FixedReportKind,
        dimensions: tuple[str, ...],
        metrics: tuple[str, ...],
    ) -> Ga4FixedReport:
        report = await self.run_report(
            Ga4ReportRequest(
                account_id=request.account_id,
                property_id=request.property_id,
                date_ranges=(Ga4DateRange(request.start_date, request.end_date),),
                dimensions=dimensions,
                metrics=metrics,
                limit=request.limit,
                timeout_seconds=request.timeout_seconds,
            )
        )
        return Ga4FixedReport(kind, report)

    def _require_property(self, account_id: str, property_id: str) -> None:
        self._policy.require_google_read_resource(
            account_id,
            ResourceKind.GA4_PROPERTY,
            property_id,
        )
