"""Cross-provider keyword and content opportunity scoring with explicit evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from math import isfinite, log1p
from urllib.parse import urljoin

from rankrat.constants import (
    MAX_CONTENT_OPPORTUNITIES,
    MIN_CONTENT_OPPORTUNITY_IMPRESSIONS,
)
from rankrat.errors import InputLimitError
from rankrat.services.bing import (
    BingPerformanceRequest,
    BingPerformanceRow,
    BingWebmasterService,
)
from rankrat.services.google_analytics import Ga4FixedReportRequest, GoogleAnalyticsDataService
from rankrat.services.google_search_console import (
    GoogleSearchConsoleService,
    SearchAnalyticsDimension,
    SearchAnalyticsRequest,
)
from rankrat.services.site_audit import SiteAuditRequest, SiteAuditService


class OpportunityConfidence(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True, slots=True)
class ContentOpportunityRequest:
    google_account_id: str
    search_console_site_url: str
    bing_account_id: str
    bing_site_url: str
    ga4_account_id: str
    ga4_property_id: str
    crawl_account_id: str
    crawl_site_url: str
    start_date: date
    end_date: date
    limit: int = 100

    def __post_init__(self) -> None:
        if self.end_date < self.start_date:
            raise InputLimitError("content opportunity date range is invalid")
        if not 1 <= self.limit <= MAX_CONTENT_OPPORTUNITIES:
            raise InputLimitError("content opportunity limit is outside the allowed range")


@dataclass(frozen=True, slots=True)
class ContentOpportunity:
    query: str | None
    page_url: str | None
    score: float
    confidence: OpportunityConfidence
    reasons: tuple[str, ...]
    evidence_sources: tuple[str, ...]
    clicks: float
    impressions: float
    ctr: float
    average_position: float | None
    sessions: float | None


@dataclass(frozen=True, slots=True)
class ContentOpportunityReport:
    opportunities: tuple[ContentOpportunity, ...]
    insufficient_evidence: bool
    truncated: bool


@dataclass(frozen=True, slots=True)
class _BingPeriodRow:
    label: str
    clicks: float
    impressions: float
    average_impression_position: float | None


class ContentOpportunityOperator:
    """Join bounded search, analytics, and crawl evidence without model inference."""

    def __init__(
        self,
        google_search_console: GoogleSearchConsoleService,
        bing: BingWebmasterService,
        google_analytics: GoogleAnalyticsDataService,
        site_audit: SiteAuditService,
    ) -> None:
        self._google_search_console = google_search_console
        self._bing = bing
        self._google_analytics = google_analytics
        self._site_audit = site_audit

    async def report(self, request: ContentOpportunityRequest) -> ContentOpportunityReport:
        google = await self._google_search_console.search_analytics(
            SearchAnalyticsRequest(
                account_id=request.google_account_id,
                site_url=request.search_console_site_url,
                start_date=request.start_date,
                end_date=request.end_date,
                dimensions=(SearchAnalyticsDimension.QUERY, SearchAnalyticsDimension.PAGE),
                row_limit=MAX_CONTENT_OPPORTUNITIES,
            )
        )
        bing = await self._bing.query_performance(
            BingPerformanceRequest(
                account_id=request.bing_account_id,
                site_url=request.bing_site_url,
            )
        )
        analytics = await self._google_analytics.landing_page_performance(
            Ga4FixedReportRequest(
                account_id=request.ga4_account_id,
                property_id=request.ga4_property_id,
                start_date=request.start_date,
                end_date=request.end_date,
                limit=MAX_CONTENT_OPPORTUNITIES,
            )
        )
        crawl = await self._site_audit.audit(
            SiteAuditRequest(
                account_id=request.crawl_account_id,
                site_url=request.crawl_site_url,
            )
        )
        sessions_by_page = _ga4_sessions_by_page(
            request.crawl_site_url,
            analytics.report.dimension_headers,
            tuple(header.name for header in analytics.report.metric_headers),
            tuple((row.dimension_values, row.metric_values) for row in analytics.report.rows),
        )
        crawl_issues = {page.url: page.issue_count for page in crawl.pages}
        candidates: list[ContentOpportunity] = []
        for google_row in google.rows:
            if (
                len(google_row.keys) != 2
                or google_row.impressions < MIN_CONTENT_OPPORTUNITY_IMPRESSIONS
            ):
                continue
            query, page_url = google_row.keys
            sessions = sessions_by_page.get(page_url)
            reasons = _reasons(
                google_row.ctr,
                google_row.position,
                sessions,
                crawl_issues.get(page_url),
            )
            sources = ["google_search_console"]
            if sessions is not None:
                sources.append("google_analytics")
            if page_url in crawl_issues:
                sources.append("site_crawl")
            candidates.append(
                ContentOpportunity(
                    query=query,
                    page_url=page_url,
                    score=_score(
                        google_row.impressions,
                        google_row.ctr,
                        google_row.position,
                        len(sources),
                    ),
                    confidence=_confidence(len(sources)),
                    reasons=reasons,
                    evidence_sources=tuple(sources),
                    clicks=google_row.clicks,
                    impressions=google_row.impressions,
                    ctr=google_row.ctr,
                    average_position=google_row.position,
                    sessions=sessions,
                )
            )
        for bing_row in _bing_period_rows(bing.rows, request.start_date, request.end_date):
            if bing_row.impressions < MIN_CONTENT_OPPORTUNITY_IMPRESSIONS:
                continue
            ctr = bing_row.clicks / bing_row.impressions if bing_row.impressions else 0.0
            position = bing_row.average_impression_position
            candidates.append(
                ContentOpportunity(
                    query=bing_row.label,
                    page_url=None,
                    score=_score(bing_row.impressions, ctr, position or 100.0, 1),
                    confidence=OpportunityConfidence.LOW,
                    reasons=_reasons(ctr, position, None, None),
                    evidence_sources=("bing_webmaster",),
                    clicks=bing_row.clicks,
                    impressions=bing_row.impressions,
                    ctr=ctr,
                    average_position=position,
                    sessions=None,
                )
            )
        candidates.sort(
            key=lambda item: (
                -item.score,
                item.query or "",
                item.page_url or "",
            )
        )
        total_evidence = sum(item.impressions for item in candidates)
        return ContentOpportunityReport(
            tuple(candidates[: request.limit]),
            total_evidence < MIN_CONTENT_OPPORTUNITY_IMPRESSIONS,
            len(candidates) > request.limit or crawl.truncated,
        )


def _score(impressions: float, ctr: float, position: float, source_count: int) -> float:
    position_weight = max(0.1, min(1.0, position / 20.0))
    ctr_gap = max(0.0, 0.1 - ctr) * 10
    confidence_weight = 0.5 + min(source_count, 3) / 6
    return round(log1p(impressions) * position_weight * (1 + ctr_gap) * confidence_weight, 4)


def _reasons(
    ctr: float,
    position: float | None,
    sessions: float | None,
    crawl_issue_count: int | None,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if ctr < 0.03:
        reasons.append("low_click_through_rate")
    if position is not None and 4 <= position <= 20:
        reasons.append("striking_distance")
    if sessions is not None and sessions == 0:
        reasons.append("search_visibility_without_sessions")
    if crawl_issue_count:
        reasons.append("page_has_technical_issues")
    return tuple(reasons or ("measurable_search_demand",))


def _confidence(source_count: int) -> OpportunityConfidence:
    if source_count >= 3:
        return OpportunityConfidence.HIGH
    if source_count == 2:
        return OpportunityConfidence.MEDIUM
    return OpportunityConfidence.LOW


def _ga4_sessions_by_page(
    site_url: str,
    dimensions: tuple[str, ...],
    metrics: tuple[str, ...],
    rows: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...],
) -> dict[str, float]:
    if not dimensions or "sessions" not in metrics:
        return {}
    metric_index = metrics.index("sessions")
    result: dict[str, float] = {}
    for dimension_values, metric_values in rows:
        if not dimension_values or metric_index >= len(metric_values):
            continue
        try:
            sessions = float(metric_values[metric_index])
        except (OverflowError, ValueError):
            continue
        if not isfinite(sessions) or sessions < 0:
            continue
        result[urljoin(site_url, dimension_values[0])] = sessions
    return result


def _bing_period_rows(
    rows: tuple[BingPerformanceRow, ...],
    start_date: date,
    end_date: date,
) -> tuple[_BingPeriodRow, ...]:
    grouped: dict[str, list[BingPerformanceRow]] = {}
    for row in rows:
        day = date.fromisoformat(row.day)
        if start_date <= day <= end_date:
            grouped.setdefault(row.label, []).append(row)
    return tuple(
        _BingPeriodRow(
            label=label,
            clicks=sum(row.clicks for row in group),
            impressions=sum(row.impressions for row in group),
            average_impression_position=_weighted_average(
                tuple((row.average_impression_position, row.impressions) for row in group)
            ),
        )
        for label, group in sorted(grouped.items())
    )


def _weighted_average(values: tuple[tuple[float | None, float], ...]) -> float | None:
    usable = tuple((value, weight) for value, weight in values if value is not None and weight > 0)
    total_weight = sum(weight for _, weight in usable)
    if total_weight == 0:
        return None
    return sum(value * weight for value, weight in usable) / total_weight
