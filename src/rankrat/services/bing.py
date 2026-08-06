"""Typed, bounded Bing Webmaster reads for configured accounts and sites."""

from __future__ import annotations

import asyncio
import logging
from collections import Counter
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from math import isfinite, sqrt
from statistics import median
from urllib.parse import urlparse

from rankrat.constants import (
    BING_FIRST_PAGE_MAX_AVERAGE_CLICK_POSITION,
    BING_SECOND_PAGE_MAX_AVERAGE_CLICK_POSITION,
    BING_STRIKING_DISTANCE_MAX_POSITION,
    BING_STRIKING_DISTANCE_MIN_POSITION,
    BING_TOP_THREE_MAX_AVERAGE_CLICK_POSITION,
    BING_TRAFFIC_ANOMALY_Z_SCORE,
    DEFAULT_PROVIDER_TIMEOUT_SECONDS,
    MAX_BING_BACKLINK_TARGETS,
    MAX_BING_BRAND_TERM_CHARS,
    MAX_BING_BRAND_TERMS,
    MAX_BING_COUNTRY_CHARS,
    MAX_BING_DERIVED_OPPORTUNITIES,
    MAX_BING_LANGUAGE_CHARS,
    MAX_BING_LINK_PAGE,
    MAX_BING_QUERY_CHARS,
    MAX_BING_SUBMISSION_URLS,
    MAX_BING_TRAFFIC_DATE_RANGE_DAYS,
    MIN_BING_TRAFFIC_ANOMALY_POINTS,
)
from rankrat.errors import InputLimitError
from rankrat.logging import log_event
from rankrat.models.boundaries import Provider, ResourceKind
from rankrat.policy.boundaries import BoundaryPolicy
from rankrat.providers.base import (
    AccountId,
    ProviderFailureCode,
    ProviderOperationError,
    ProviderReadRequest,
)
from rankrat.providers.bing import (
    BingCrawlIssueRow,
    BingCrawlStatsRow,
    BingFeedRow,
    BingKeywordStatsRow,
    BingLinkCounts,
    BingLinkDetail,
    BingQueryStatsRow,
    BingRelatedKeywordRow,
    BingTrafficRow,
    BingUrlInformation,
    BingUrlSubmissionQuota,
    BingWebmasterClient,
)

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class BingTrafficPeriodRequest:
    """One bounded daily Bing traffic interval for an exact configured site."""

    account_id: str
    site_url: str
    start_date: date
    end_date: date
    timeout_seconds: float = DEFAULT_PROVIDER_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        if self.end_date < self.start_date:
            raise InputLimitError("Bing traffic end date must not precede start date")
        if (self.end_date - self.start_date).days + 1 > MAX_BING_TRAFFIC_DATE_RANGE_DAYS:
            raise InputLimitError("Bing traffic date range exceeds the allowed size")


@dataclass(frozen=True, slots=True)
class BingTrafficMetrics:
    """Validated Bing daily or period-level click and impression metrics."""

    clicks: float
    impressions: float


@dataclass(frozen=True, slots=True)
class BingTrafficPoint:
    """One ascending daily Bing traffic point."""

    day: str
    metrics: BingTrafficMetrics


@dataclass(frozen=True, slots=True)
class BingTrafficTrendReport:
    """Typed daily traffic for one bounded Bing site interval."""

    points: tuple[BingTrafficPoint, ...]


@dataclass(frozen=True, slots=True)
class BingTrafficAnomaly:
    """One daily Bing point with an unusual click or impression value."""

    day: str
    metrics: BingTrafficMetrics
    clicks_baseline: float
    impressions_baseline: float
    clicks_z_score: float
    impressions_z_score: float


@dataclass(frozen=True, slots=True)
class BingTrafficAnomalyReport:
    """Deterministic bounded daily Bing traffic anomalies."""

    anomalies: tuple[BingTrafficAnomaly, ...]


@dataclass(frozen=True, slots=True)
class BingTrafficComparisonRequest:
    """Two valid Bing traffic intervals for one configured site."""

    current: BingTrafficPeriodRequest
    previous_start_date: date
    previous_end_date: date

    def __post_init__(self) -> None:
        self.previous_request()

    def previous_request(self) -> BingTrafficPeriodRequest:
        """Build the exact previous interval without changing account or site."""

        return BingTrafficPeriodRequest(
            account_id=self.current.account_id,
            site_url=self.current.site_url,
            start_date=self.previous_start_date,
            end_date=self.previous_end_date,
            timeout_seconds=self.current.timeout_seconds,
        )


@dataclass(frozen=True, slots=True)
class BingTrafficComparison:
    """Current/previous Bing traffic totals plus absolute deltas."""

    current: BingTrafficMetrics
    previous: BingTrafficMetrics
    clicks_delta: float
    impressions_delta: float


@dataclass(frozen=True, slots=True)
class BingPerformanceRequest:
    """One exact configured Bing site for a typed top-query or top-page report."""

    account_id: str
    site_url: str
    timeout_seconds: float = DEFAULT_PROVIDER_TIMEOUT_SECONDS


@dataclass(frozen=True, slots=True)
class BingBrandAnalysisRequest:
    """One configured Bing site and bounded literal terms for local classification."""

    account_id: str
    site_url: str
    brand_terms: tuple[str, ...]
    timeout_seconds: float = DEFAULT_PROVIDER_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        if not self.brand_terms or len(self.brand_terms) > MAX_BING_BRAND_TERMS:
            raise InputLimitError("Bing brand term count is outside the allowed range")
        normalized_terms = tuple(term.strip().casefold() for term in self.brand_terms)
        if any(
            not term or len(term) > MAX_BING_BRAND_TERM_CHARS for term in normalized_terms
        ) or len(set(normalized_terms)) != len(normalized_terms):
            raise InputLimitError("Bing brand terms must be unique bounded literals")
        object.__setattr__(self, "brand_terms", normalized_terms)


@dataclass(frozen=True, slots=True)
class BingQueryPagePerformanceRequest:
    """One exact configured Bing site and bounded query for page detail rows."""

    account_id: str
    site_url: str
    query: str
    timeout_seconds: float = DEFAULT_PROVIDER_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        if not self.query or len(self.query) > MAX_BING_QUERY_CHARS:
            raise InputLimitError("Bing query exceeds the allowed size")


@dataclass(frozen=True, slots=True)
class BingPageQueryPerformanceRequest:
    """One exact configured Bing site and child page for query detail rows."""

    account_id: str
    site_url: str
    page_url: str
    timeout_seconds: float = DEFAULT_PROVIDER_TIMEOUT_SECONDS


@dataclass(frozen=True, slots=True)
class BingPerformanceRow:
    """One typed Bing top-query or top-page result."""

    label: str
    day: str
    clicks: float
    impressions: float
    average_click_position: float | None
    average_impression_position: float | None


@dataclass(frozen=True, slots=True)
class BingPerformanceReport:
    """Deterministically ordered typed Bing query or page performance rows."""

    rows: tuple[BingPerformanceRow, ...]


@dataclass(frozen=True, slots=True)
class BingBrandAnalysisReport:
    """Literal brand/non-brand classification over one typed Bing query report."""

    brand_terms: tuple[str, ...]
    brand_rows: tuple[BingPerformanceRow, ...]
    non_brand_rows: tuple[BingPerformanceRow, ...]


@dataclass(frozen=True, slots=True)
class BingQueryCannibalizationReport:
    """Multiple Bing result pages competing for one exact query; a local signal."""

    query: str
    pages: tuple[BingPerformanceRow, ...]


class BingRankingBucketKind(StrEnum):
    """Fixed local groups for Bing average click positions."""

    TOP_THREE = "top_three"
    FIRST_PAGE = "first_page"
    SECOND_PAGE = "second_page"
    BEYOND_SECOND_PAGE = "beyond_second_page"


@dataclass(frozen=True, slots=True)
class BingRankingBucket:
    """One fixed local ranking bucket over typed Bing query rows."""

    kind: BingRankingBucketKind
    rows: tuple[BingPerformanceRow, ...]


@dataclass(frozen=True, slots=True)
class BingRankingBucketsReport:
    """All fixed local ranking buckets in stable rank order."""

    buckets: tuple[BingRankingBucket, ...]


class BingPerformanceOpportunityKind(StrEnum):
    """A deterministic local classification over validated Bing performance data."""

    LOW_CTR = "low_ctr"
    STRIKING_DISTANCE = "striking_distance"


@dataclass(frozen=True, slots=True)
class BingPerformanceOpportunity:
    """One bounded local opportunity; classifications are not Bing-provided facts."""

    row: BingPerformanceRow
    click_through_rate: float
    classifications: tuple[BingPerformanceOpportunityKind, ...]


@dataclass(frozen=True, slots=True)
class BingPerformanceOpportunityReport:
    """Stable candidates derived locally from one fixed Bing performance read."""

    opportunities: tuple[BingPerformanceOpportunity, ...]


@dataclass(frozen=True, slots=True)
class BingOpportunityMatrixReport:
    """Separate Bing query/page candidates and their two-rule quick-win subsets."""

    query_opportunities: BingPerformanceOpportunityReport
    page_opportunities: BingPerformanceOpportunityReport
    query_quick_wins: tuple[BingPerformanceOpportunity, ...]
    page_quick_wins: tuple[BingPerformanceOpportunity, ...]


@dataclass(frozen=True, slots=True)
class BingUrlSubmissionQuotaRequest:
    """One exact configured Bing site for a read-only URL-submission quota report."""

    account_id: str
    site_url: str
    timeout_seconds: float = DEFAULT_PROVIDER_TIMEOUT_SECONDS


@dataclass(frozen=True, slots=True)
class BingUrlSubmissionQuotaReport:
    """Remaining typed Bing URL-submission quotas for one configured site."""

    daily: int
    monthly: int


@dataclass(frozen=True, slots=True)
class BingCrawlIssuesRequest:
    """One exact configured Bing site for a typed crawl-issues report."""

    account_id: str
    site_url: str
    timeout_seconds: float = DEFAULT_PROVIDER_TIMEOUT_SECONDS


@dataclass(frozen=True, slots=True)
class BingCrawlIssue:
    """One stable crawl issue record suitable for REST and MCP output."""

    url: str
    http_code: int
    issues: int
    in_links: int


@dataclass(frozen=True, slots=True)
class BingCrawlIssuesReport:
    """Deterministically ordered crawl issues for one configured Bing site."""

    issues: tuple[BingCrawlIssue, ...]


@dataclass(frozen=True, slots=True)
class BingCrawlStatsRequest:
    """One exact configured Bing site for a typed crawl-statistics report."""

    account_id: str
    site_url: str
    timeout_seconds: float = DEFAULT_PROVIDER_TIMEOUT_SECONDS


@dataclass(frozen=True, slots=True)
class BingCrawlStatsPoint:
    """One stable daily Bing crawl-statistics record."""

    day: str
    all_other_codes: int
    blocked_by_robots_txt: int
    code_2xx: int
    code_301: int
    code_302: int
    code_4xx: int
    code_5xx: int
    contains_malware: int
    connection_timeout: int | None
    crawl_errors: int
    crawled_pages: int
    dns_failures: int | None
    in_index: int
    in_links: int


@dataclass(frozen=True, slots=True)
class BingCrawlStatsReport:
    """Ascending daily crawl statistics for one configured Bing site."""

    points: tuple[BingCrawlStatsPoint, ...]


@dataclass(frozen=True, slots=True)
class BingFeedsRequest:
    """One exact configured Bing site for a typed feed report."""

    account_id: str
    site_url: str
    timeout_seconds: float = DEFAULT_PROVIDER_TIMEOUT_SECONDS


@dataclass(frozen=True, slots=True)
class BingFeed:
    """One stable Bing sitemap or feed record."""

    url: str
    feed_type: str
    status: str
    compressed: bool
    file_size: int
    url_count: int
    last_crawled: str
    submitted: str


@dataclass(frozen=True, slots=True)
class BingFeedsReport:
    """Deterministically ordered feed records for one configured Bing site."""

    feeds: tuple[BingFeed, ...]


@dataclass(frozen=True, slots=True)
class BingLinkCountsRequest:
    """One exact configured Bing site and bounded provider page."""

    account_id: str
    site_url: str
    page: int = 0
    timeout_seconds: float = DEFAULT_PROVIDER_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        if self.page < 0 or self.page > MAX_BING_LINK_PAGE:
            raise InputLimitError("Bing link-count page exceeds the allowed range")


@dataclass(frozen=True, slots=True)
class BingLinkCount:
    """One stable inbound-link count record."""

    url: str
    count: int


@dataclass(frozen=True, slots=True)
class BingLinkCountsReport:
    """One deterministic fixed page of Bing inbound-link counts."""

    links: tuple[BingLinkCount, ...]
    total_pages: int


@dataclass(frozen=True, slots=True)
class BingBacklinkIntelligenceRequest:
    """Configured child URLs and bounded detail pages for backlink intelligence."""

    account_id: str
    site_url: str
    target_urls: tuple[str, ...]
    max_pages_per_target: int = 1
    timeout_seconds: float = DEFAULT_PROVIDER_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        if not self.target_urls or len(self.target_urls) > MAX_BING_BACKLINK_TARGETS:
            raise InputLimitError("Bing backlink target count is outside the allowed range")
        if len(set(self.target_urls)) != len(self.target_urls):
            raise InputLimitError("Bing backlink targets must not contain duplicates")
        if self.max_pages_per_target < 1 or self.max_pages_per_target > MAX_BING_LINK_PAGE + 1:
            raise InputLimitError("Bing backlink page count is outside the allowed range")


@dataclass(frozen=True, slots=True)
class BingBacklink:
    """One typed external backlink and its Bing-reported anchor text."""

    source_url: str
    source_domain: str
    anchor_text: str


@dataclass(frozen=True, slots=True)
class BingAnchorSummary:
    """One anchor text and its deterministic observed count."""

    anchor_text: str
    count: int


@dataclass(frozen=True, slots=True)
class BingBacklinkTargetReport:
    """Observed backlinks and aggregate diversity for one configured child URL."""

    target_url: str
    backlinks: tuple[BingBacklink, ...]
    referring_domains: tuple[str, ...]
    anchors: tuple[BingAnchorSummary, ...]
    provider_total_pages: int
    pages_read: int
    truncated: bool


@dataclass(frozen=True, slots=True)
class BingBacklinkIntelligenceReport:
    """Bounded backlink intelligence for explicit configured-site targets."""

    targets: tuple[BingBacklinkTargetReport, ...]


@dataclass(frozen=True, slots=True)
class BingUrlInformationRequest:
    """One exact configured Bing site and child URL for typed URL information."""

    account_id: str
    site_url: str
    page_url: str
    timeout_seconds: float = DEFAULT_PROVIDER_TIMEOUT_SECONDS


@dataclass(frozen=True, slots=True)
class BingUrlInformationReport:
    """Typed Bing indexing and crawl information for one configured child URL."""

    url: str
    anchor_count: int
    discovery_date: str
    document_size: int
    http_status: int | None
    is_page: bool
    last_crawled_date: str
    total_child_url_count: int


@dataclass(frozen=True, slots=True)
class BingKeywordStatisticsRequest:
    """One bounded global Bing keyword-statistics read."""

    account_id: str
    query: str
    country: str | None = None
    language: str | None = None
    timeout_seconds: float = DEFAULT_PROVIDER_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        if not self.query or len(self.query) > MAX_BING_QUERY_CHARS:
            raise InputLimitError("Bing keyword query exceeds the allowed size")
        if self.country is not None and len(self.country) > MAX_BING_COUNTRY_CHARS:
            raise InputLimitError("Bing country exceeds the allowed size")
        if self.language is not None and len(self.language) > MAX_BING_LANGUAGE_CHARS:
            raise InputLimitError("Bing language exceeds the allowed size")


@dataclass(frozen=True, slots=True)
class BingRelatedKeywordsRequest:
    """One bounded Bing related-keyword read over one explicit date interval."""

    account_id: str
    query: str
    start_date: date
    end_date: date
    country: str | None = None
    language: str | None = None
    timeout_seconds: float = DEFAULT_PROVIDER_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        BingKeywordStatisticsRequest(
            self.account_id,
            self.query,
            self.country,
            self.language,
            self.timeout_seconds,
        )
        if self.end_date < self.start_date:
            raise InputLimitError("Bing related-keyword end date must not precede start date")
        if (self.end_date - self.start_date).days + 1 > MAX_BING_TRAFFIC_DATE_RANGE_DAYS:
            raise InputLimitError("Bing related-keyword date range exceeds the allowed size")


@dataclass(frozen=True, slots=True)
class BingKeywordStatisticsPoint:
    """One stable daily Bing keyword-statistics point."""

    query: str
    day: str
    impressions: int
    broad_impressions: int


@dataclass(frozen=True, slots=True)
class BingKeywordStatisticsReport:
    """Deterministically ordered Bing keyword-statistics points."""

    points: tuple[BingKeywordStatisticsPoint, ...]


@dataclass(frozen=True, slots=True)
class BingRelatedKeyword:
    """One stable Bing related-keyword result."""

    query: str
    impressions: int
    broad_impressions: int


@dataclass(frozen=True, slots=True)
class BingRelatedKeywordsReport:
    """Deterministically ordered Bing related-keyword results."""

    keywords: tuple[BingRelatedKeyword, ...]


@dataclass(frozen=True, slots=True)
class BingUrlSubmissionRequest:
    """One boundary-limited Bing URL batch submission."""

    account_id: str
    site_url: str
    urls: tuple[str, ...]
    timeout_seconds: float = DEFAULT_PROVIDER_TIMEOUT_SECONDS


@dataclass(frozen=True, slots=True)
class BingUrlSubmissionResponse:
    """Safe summary of one accepted Bing URL batch submission."""

    account_id: str
    site_url: str
    submitted_count: int


class BingSitemapOperation(StrEnum):
    """The documented Bing Webmaster feed mutation operations."""

    SUBMIT = "submit"
    DELETE = "delete"


@dataclass(frozen=True, slots=True)
class BingSitemapSubmissionRequest:
    """One boundary-limited Bing sitemap mutation ready for the provider client."""

    account_id: str
    site_url: str
    sitemap_url: str
    operation: BingSitemapOperation

    timeout_seconds: float = DEFAULT_PROVIDER_TIMEOUT_SECONDS


@dataclass(frozen=True, slots=True)
class BingSitemapSubmissionResponse:
    """Safe Bing sitemap mutation receipt without the submitted sitemap URL."""

    account_id: str
    site_url: str
    operation: BingSitemapOperation


class BingSiteOperation(StrEnum):
    """The documented Bing Webmaster property mutation operations."""

    ADD = "add"
    DELETE = "delete"


@dataclass(frozen=True, slots=True)
class BingSiteSubmissionRequest:
    """One boundary-limited Bing property mutation ready for the provider client."""

    account_id: str
    site_url: str
    operation: BingSiteOperation

    timeout_seconds: float = DEFAULT_PROVIDER_TIMEOUT_SECONDS


@dataclass(frozen=True, slots=True)
class BingSiteSubmissionResponse:
    """Safe Bing property mutation receipt without an API key."""

    account_id: str
    site_url: str
    operation: BingSiteOperation


class BingWebmasterService:
    """Application service that permits only documented bounded Bing reads."""

    def __init__(
        self,
        policy: BoundaryPolicy,
        client: BingWebmasterClient,
    ) -> None:
        self._policy = policy
        self._client = client

    async def keyword_statistics(
        self,
        request: BingKeywordStatisticsRequest,
    ) -> BingKeywordStatisticsReport:
        """Return stable daily Bing keyword statistics for one configured account."""

        rows = await self._client.read_keyword_stats(
            ProviderReadRequest(AccountId(request.account_id), request.timeout_seconds),
            request.query,
            request.country,
            request.language,
        )
        return _bing_keyword_statistics_report(rows)

    async def related_keywords(
        self,
        request: BingRelatedKeywordsRequest,
    ) -> BingRelatedKeywordsReport:
        """Return stable related Bing keywords for one configured account and period."""

        rows = await self._client.read_related_keywords(
            ProviderReadRequest(AccountId(request.account_id), request.timeout_seconds),
            request.query,
            request.country,
            request.language,
            request.start_date,
            request.end_date,
        )
        return _bing_related_keywords_report(rows)

    async def traffic_trend(
        self,
        request: BingTrafficPeriodRequest,
    ) -> BingTrafficTrendReport:
        """Return validated ascending daily traffic from Bing's fixed site report."""

        rows = await self._client.read_rank_and_traffic_stats(
            ProviderReadRequest(AccountId(request.account_id), request.timeout_seconds),
            request.site_url,
        )
        points = _bing_traffic_points(rows, request.start_date, request.end_date)
        return BingTrafficTrendReport(tuple(sorted(points, key=lambda point: point.day)))

    async def traffic_anomalies(
        self,
        request: BingTrafficPeriodRequest,
    ) -> BingTrafficAnomalyReport:
        """Return deterministic finite daily Bing traffic outliers."""

        trend = await self.traffic_trend(request)
        if len(trend.points) < MIN_BING_TRAFFIC_ANOMALY_POINTS:
            return BingTrafficAnomalyReport(())
        clicks_baseline, clicks_z_scores = _bing_z_scores(
            tuple(point.metrics.clicks for point in trend.points)
        )
        impressions_baseline, impressions_z_scores = _bing_z_scores(
            tuple(point.metrics.impressions for point in trend.points)
        )
        anomalies = tuple(
            BingTrafficAnomaly(
                day=point.day,
                metrics=point.metrics,
                clicks_baseline=clicks_baseline,
                impressions_baseline=impressions_baseline,
                clicks_z_score=clicks_z_score,
                impressions_z_score=impressions_z_score,
            )
            for point, clicks_z_score, impressions_z_score in zip(
                trend.points,
                clicks_z_scores,
                impressions_z_scores,
                strict=True,
            )
            if abs(clicks_z_score) >= BING_TRAFFIC_ANOMALY_Z_SCORE
            or abs(impressions_z_score) >= BING_TRAFFIC_ANOMALY_Z_SCORE
        )
        return BingTrafficAnomalyReport(anomalies)

    async def traffic_comparison(
        self,
        request: BingTrafficComparisonRequest,
    ) -> BingTrafficComparison:
        """Compare exact bounded Bing traffic intervals without widening scope."""

        current = _bing_traffic_total(await self.traffic_trend(request.current))
        previous = _bing_traffic_total(await self.traffic_trend(request.previous_request()))
        return BingTrafficComparison(
            current=current,
            previous=previous,
            clicks_delta=current.clicks - previous.clicks,
            impressions_delta=current.impressions - previous.impressions,
        )

    async def query_performance(self, request: BingPerformanceRequest) -> BingPerformanceReport:
        """Return fixed typed Bing top-query statistics for one configured site."""

        rows = await self._client.read_query_stats(
            ProviderReadRequest(AccountId(request.account_id), request.timeout_seconds),
            request.site_url,
        )
        return _bing_performance_report(rows)

    async def page_performance(self, request: BingPerformanceRequest) -> BingPerformanceReport:
        """Return fixed typed Bing top-page statistics for one configured site."""

        rows = await self._client.read_page_stats(
            ProviderReadRequest(AccountId(request.account_id), request.timeout_seconds),
            request.site_url,
        )
        return _bing_performance_report(rows)

    async def query_opportunities(
        self,
        request: BingPerformanceRequest,
    ) -> BingPerformanceOpportunityReport:
        """Derive bounded local query candidates from one fixed Bing read."""

        return _bing_performance_opportunity_report(await self.query_performance(request))

    async def brand_analysis(self, request: BingBrandAnalysisRequest) -> BingBrandAnalysisReport:
        """Classify one fixed Bing top-query report with bounded literal terms."""

        report = await self.query_performance(
            BingPerformanceRequest(
                request.account_id,
                request.site_url,
                request.timeout_seconds,
            )
        )
        brand_rows = tuple(
            row
            for row in report.rows
            if any(term in row.label.casefold() for term in request.brand_terms)
        )
        brand_labels = {row.label for row in brand_rows}
        non_brand_rows = tuple(row for row in report.rows if row.label not in brand_labels)
        return BingBrandAnalysisReport(request.brand_terms, brand_rows, non_brand_rows)

    async def ranking_buckets(
        self,
        request: BingPerformanceRequest,
    ) -> BingRankingBucketsReport:
        """Group one fixed Bing top-query report into local position buckets."""

        return _bing_ranking_buckets_report(await self.query_performance(request))

    async def page_opportunities(
        self,
        request: BingPerformanceRequest,
    ) -> BingPerformanceOpportunityReport:
        """Derive bounded local page candidates from one fixed Bing read."""

        return _bing_performance_opportunity_report(await self.page_performance(request))

    async def opportunity_matrix(
        self,
        request: BingPerformanceRequest,
    ) -> BingOpportunityMatrixReport:
        """Return separate fixed Bing candidates and their explicit rule intersection."""

        self._require_site(request.account_id, request.site_url)
        query_opportunities, page_opportunities = await asyncio.gather(
            self.query_opportunities(request),
            self.page_opportunities(request),
        )
        return BingOpportunityMatrixReport(
            query_opportunities=query_opportunities,
            page_opportunities=page_opportunities,
            query_quick_wins=_bing_quick_wins(query_opportunities),
            page_quick_wins=_bing_quick_wins(page_opportunities),
        )

    async def query_page_performance(
        self,
        request: BingQueryPagePerformanceRequest,
    ) -> BingPerformanceReport:
        """Return fixed typed Bing page statistics for one exact query."""

        rows = await self._client.read_query_page_stats(
            ProviderReadRequest(AccountId(request.account_id), request.timeout_seconds),
            request.site_url,
            request.query,
        )
        return _bing_performance_report(rows)

    async def query_cannibalization(
        self,
        request: BingQueryPagePerformanceRequest,
    ) -> BingQueryCannibalizationReport:
        """Return competing pages only when Bing reports at least two for one query."""

        report = await self.query_page_performance(request)
        if len(report.rows) < 2:
            return BingQueryCannibalizationReport(request.query, ())
        return BingQueryCannibalizationReport(request.query, report.rows)

    async def page_query_performance(
        self,
        request: BingPageQueryPerformanceRequest,
    ) -> BingPerformanceReport:
        """Return fixed typed Bing query statistics for one configured child page."""

        page_url = self._policy.require_bing_site_url(
            request.account_id,
            request.site_url,
            request.page_url,
        )
        rows = await self._client.read_page_query_stats(
            ProviderReadRequest(AccountId(request.account_id), request.timeout_seconds),
            request.site_url,
            page_url,
        )
        return _bing_performance_report(rows)

    async def url_submission_quota(
        self,
        request: BingUrlSubmissionQuotaRequest,
    ) -> BingUrlSubmissionQuotaReport:
        """Return typed remaining URL-submission quotas for one configured Bing site."""

        self._policy.require_resource(
            request.account_id,
            Provider.BING,
            ResourceKind.BING_SITE,
            request.site_url,
        )
        quota = await self._client.read_url_submission_quota(
            ProviderReadRequest(AccountId(request.account_id), request.timeout_seconds),
            request.site_url,
        )
        return _bing_url_submission_quota_report(quota)

    async def crawl_issues(self, request: BingCrawlIssuesRequest) -> BingCrawlIssuesReport:
        """Return typed crawl issues after exact configured-site authorization."""

        self._require_site(request.account_id, request.site_url)
        rows = await self._client.read_crawl_issues(
            ProviderReadRequest(AccountId(request.account_id), request.timeout_seconds),
            request.site_url,
        )
        return _bing_crawl_issues_report(rows)

    async def crawl_stats(self, request: BingCrawlStatsRequest) -> BingCrawlStatsReport:
        """Return typed daily crawl statistics after configured-site authorization."""

        self._require_site(request.account_id, request.site_url)
        rows = await self._client.read_crawl_stats(
            ProviderReadRequest(AccountId(request.account_id), request.timeout_seconds),
            request.site_url,
        )
        return _bing_crawl_stats_report(rows)

    async def feeds(self, request: BingFeedsRequest) -> BingFeedsReport:
        """Return typed configured feeds after exact site authorization."""

        self._require_site(request.account_id, request.site_url)
        rows = await self._client.read_feeds(
            ProviderReadRequest(AccountId(request.account_id), request.timeout_seconds),
            request.site_url,
        )
        return _bing_feeds_report(rows)

    async def link_counts(self, request: BingLinkCountsRequest) -> BingLinkCountsReport:
        """Return a typed bounded Bing inbound-link-count page."""

        self._require_site(request.account_id, request.site_url)
        link_counts = await self._client.read_link_counts(
            ProviderReadRequest(AccountId(request.account_id), request.timeout_seconds),
            request.site_url,
            request.page,
        )
        return _bing_link_counts_report(link_counts)

    async def backlink_intelligence(
        self,
        request: BingBacklinkIntelligenceRequest,
    ) -> BingBacklinkIntelligenceReport:
        """Read bounded backlink details and derive local anchor/domain summaries."""

        self._require_site(request.account_id, request.site_url)
        targets: list[BingBacklinkTargetReport] = []
        provider_request = ProviderReadRequest(
            AccountId(request.account_id),
            request.timeout_seconds,
        )
        for target_url in request.target_urls:
            normalized_target = self._policy.require_bing_site_url(
                request.account_id,
                request.site_url,
                target_url,
            )
            details: list[BingLinkDetail] = []
            total_pages = 0
            pages_read = 0
            for page in range(request.max_pages_per_target):
                result = await self._client.read_url_links(
                    provider_request,
                    request.site_url,
                    normalized_target,
                    page,
                )
                total_pages = result.total_pages
                details.extend(result.links)
                pages_read += 1
                if page + 1 >= result.total_pages:
                    break
            targets.append(
                _bing_backlink_target_report(
                    normalized_target,
                    tuple(details),
                    total_pages,
                    pages_read,
                )
            )
        return BingBacklinkIntelligenceReport(tuple(targets))

    async def url_information(
        self,
        request: BingUrlInformationRequest,
    ) -> BingUrlInformationReport:
        """Return typed URL information after exact configured-child authorization."""

        page_url = self._policy.require_bing_site_url(
            request.account_id,
            request.site_url,
            request.page_url,
        )
        information = await self._client.read_url_information(
            ProviderReadRequest(AccountId(request.account_id), request.timeout_seconds),
            request.site_url,
            page_url,
        )
        return _bing_url_information_report(information)

    async def submit_url_batch(
        self,
        request: BingUrlSubmissionRequest,
    ) -> BingUrlSubmissionResponse:
        """Submit a boundary-limited Bing URL batch."""
        normalized_urls = self._normalized_submission_urls(
            request.account_id,
            request.site_url,
            request.urls,
        )
        await self._client.submit_url_batch(
            ProviderReadRequest(AccountId(request.account_id), request.timeout_seconds),
            request.site_url,
            normalized_urls,
        )
        return BingUrlSubmissionResponse(
            account_id=request.account_id,
            site_url=request.site_url,
            submitted_count=len(normalized_urls),
        )

    async def submit_site(
        self,
        request: BingSiteSubmissionRequest,
    ) -> BingSiteSubmissionResponse:
        """Run one boundary-limited fixed-origin Bing property mutation."""
        self._require_site(request.account_id, request.site_url)
        provider_request = ProviderReadRequest(
            AccountId(request.account_id),
            request.timeout_seconds,
        )
        try:
            if request.operation is BingSiteOperation.ADD:
                await self._client.add_site(provider_request, request.site_url)
            else:
                await self._client.remove_site(provider_request, request.site_url)
        except Exception:
            # Bing's key travels in its legacy query API, so never log its request URL.
            log_event(
                _LOGGER,
                logging.WARNING,
                "Bing property mutation failed",
                account_id=request.account_id,
                site_url=request.site_url,
                operation=request.operation.value,
            )
            raise
        log_event(
            _LOGGER,
            logging.INFO,
            "Bing property mutation accepted",
            account_id=request.account_id,
            site_url=request.site_url,
            operation=request.operation.value,
        )
        return BingSiteSubmissionResponse(
            request.account_id,
            request.site_url,
            request.operation,
        )

    async def submit_sitemap(
        self,
        request: BingSitemapSubmissionRequest,
    ) -> BingSitemapSubmissionResponse:
        """Run one boundary-limited fixed-origin Bing sitemap mutation."""
        sitemap_url = self._normalized_sitemap_url(request)
        provider_request = ProviderReadRequest(
            AccountId(request.account_id),
            request.timeout_seconds,
        )
        try:
            if request.operation is BingSitemapOperation.SUBMIT:
                await self._client.submit_feed(provider_request, request.site_url, sitemap_url)
            else:
                await self._client.remove_feed(provider_request, request.site_url, sitemap_url)
        except Exception:  # Preserve the provider's classified error after audit logging.
            log_event(
                _LOGGER,
                logging.WARNING,
                "Bing sitemap mutation failed",
                account_id=request.account_id,
                site_url=request.site_url,
                operation=request.operation.value,
            )
            raise
        log_event(
            _LOGGER,
            logging.INFO,
            "Bing sitemap mutation accepted",
            account_id=request.account_id,
            site_url=request.site_url,
            operation=request.operation.value,
        )
        return BingSitemapSubmissionResponse(
            request.account_id,
            request.site_url,
            request.operation,
        )

    def _normalized_submission_urls(
        self,
        account_id: str,
        site_url: str,
        urls: tuple[str, ...],
    ) -> tuple[str, ...]:
        if not urls or len(urls) > MAX_BING_SUBMISSION_URLS:
            raise InputLimitError("Bing URL submission has an invalid batch size")
        normalized_urls = tuple(
            self._policy.require_bing_site_url(account_id, site_url, url) for url in urls
        )
        if len(set(normalized_urls)) != len(normalized_urls):
            raise InputLimitError("Bing URL submission must not contain duplicate URLs")
        return normalized_urls

    def _require_site(self, account_id: str, site_url: str) -> None:
        self._policy.require_resource(
            account_id,
            self._client.provider,
            ResourceKind.BING_SITE,
            site_url,
        )

    def _normalized_sitemap_url(self, request: BingSitemapSubmissionRequest) -> str:
        return self._policy.require_bing_site_url(
            request.account_id,
            request.site_url,
            request.sitemap_url,
        )


def _bing_traffic_points(
    rows: tuple[BingTrafficRow, ...],
    start_date: date,
    end_date: date,
) -> tuple[BingTrafficPoint, ...]:
    points = tuple(_bing_traffic_point(row) for row in rows if start_date <= row.day <= end_date)
    if len({point.day for point in points}) != len(points):
        raise ProviderOperationError(
            ProviderFailureCode.INVALID_RESPONSE,
            "Bing Webmaster returned duplicate traffic days",
        )
    return points


def _bing_traffic_point(
    row: BingTrafficRow,
) -> BingTrafficPoint:
    return BingTrafficPoint(
        day=row.day.isoformat(),
        metrics=BingTrafficMetrics(
            clicks=row.clicks,
            impressions=row.impressions,
        ),
    )


def _bing_traffic_total(report: BingTrafficTrendReport) -> BingTrafficMetrics:
    return BingTrafficMetrics(
        clicks=sum(point.metrics.clicks for point in report.points),
        impressions=sum(point.metrics.impressions for point in report.points),
    )


def _bing_performance_report(rows: tuple[BingQueryStatsRow, ...]) -> BingPerformanceReport:
    performance_rows = tuple(
        BingPerformanceRow(
            label=row.label,
            day=row.day.isoformat(),
            clicks=row.clicks,
            impressions=row.impressions,
            average_click_position=row.average_click_position,
            average_impression_position=row.average_impression_position,
        )
        for row in rows
    )
    return BingPerformanceReport(
        tuple(
            sorted(
                performance_rows,
                key=lambda row: (-row.clicks, -row.impressions, row.label),
            )
        )
    )


def _bing_performance_opportunity_report(
    report: BingPerformanceReport,
) -> BingPerformanceOpportunityReport:
    click_through_rates = tuple(
        _bing_click_through_rate(row) for row in report.rows if row.impressions > 0
    )
    if len(click_through_rates) < 2:
        return BingPerformanceOpportunityReport(())
    median_click_through_rate = median(click_through_rates)
    opportunities = tuple(
        opportunity
        for row in report.rows
        if (opportunity := _bing_performance_opportunity(row, median_click_through_rate))
        is not None
    )
    ordered = tuple(
        sorted(
            opportunities,
            key=lambda opportunity: (
                -opportunity.row.impressions,
                -opportunity.row.clicks,
                _bing_position_sort_key(opportunity.row),
                opportunity.row.label,
                opportunity.row.day,
            ),
        )
    )
    return BingPerformanceOpportunityReport(ordered[:MAX_BING_DERIVED_OPPORTUNITIES])


def _bing_quick_wins(
    report: BingPerformanceOpportunityReport,
) -> tuple[BingPerformanceOpportunity, ...]:
    return tuple(
        opportunity
        for opportunity in report.opportunities
        if BingPerformanceOpportunityKind.LOW_CTR in opportunity.classifications
        and BingPerformanceOpportunityKind.STRIKING_DISTANCE in opportunity.classifications
    )


def _bing_ranking_buckets_report(
    report: BingPerformanceReport,
) -> BingRankingBucketsReport:
    rows_by_kind: dict[BingRankingBucketKind, list[BingPerformanceRow]] = {
        kind: [] for kind in BingRankingBucketKind
    }
    unavailable_position_rows = 0
    for row in report.rows:
        position = _bing_ranking_position(row)
        if position is None:
            unavailable_position_rows += 1
            continue
        rows_by_kind[_bing_ranking_bucket_kind(position)].append(row)
    if unavailable_position_rows:
        log_event(
            _LOGGER,
            logging.INFO,
            "Bing ranking buckets skipped rows without an available position",
            unavailable_position_rows=unavailable_position_rows,
        )
    return BingRankingBucketsReport(
        tuple(BingRankingBucket(kind, tuple(rows_by_kind[kind])) for kind in BingRankingBucketKind)
    )


def _bing_ranking_bucket_kind(position: float) -> BingRankingBucketKind:
    if position <= BING_TOP_THREE_MAX_AVERAGE_CLICK_POSITION:
        return BingRankingBucketKind.TOP_THREE
    if position <= BING_FIRST_PAGE_MAX_AVERAGE_CLICK_POSITION:
        return BingRankingBucketKind.FIRST_PAGE
    if position <= BING_SECOND_PAGE_MAX_AVERAGE_CLICK_POSITION:
        return BingRankingBucketKind.SECOND_PAGE
    return BingRankingBucketKind.BEYOND_SECOND_PAGE


def _bing_ranking_position(row: BingPerformanceRow) -> float | None:
    """Use visibility rank first; click rank is a documented fallback."""

    return row.average_impression_position or row.average_click_position


def _bing_position_sort_key(row: BingPerformanceRow) -> tuple[bool, float]:
    position = _bing_ranking_position(row)
    return (
        position is None,
        BING_STRIKING_DISTANCE_MAX_POSITION if position is None else position,
    )


def _bing_performance_opportunity(
    row: BingPerformanceRow,
    median_click_through_rate: float,
) -> BingPerformanceOpportunity | None:
    if row.impressions <= 0:
        return None
    click_through_rate = _bing_click_through_rate(row)
    classifications: list[BingPerformanceOpportunityKind] = []
    if click_through_rate < median_click_through_rate:
        classifications.append(BingPerformanceOpportunityKind.LOW_CTR)
    position = _bing_ranking_position(row)
    if position is not None and (
        BING_STRIKING_DISTANCE_MIN_POSITION <= position <= BING_STRIKING_DISTANCE_MAX_POSITION
    ):
        classifications.append(BingPerformanceOpportunityKind.STRIKING_DISTANCE)
    if not classifications:
        return None
    return BingPerformanceOpportunity(
        row=row,
        click_through_rate=click_through_rate,
        classifications=tuple(classifications),
    )


def _bing_click_through_rate(row: BingPerformanceRow) -> float:
    return row.clicks / row.impressions


def _bing_keyword_statistics_report(
    rows: tuple[BingKeywordStatsRow, ...],
) -> BingKeywordStatisticsReport:
    points = tuple(
        BingKeywordStatisticsPoint(
            query=row.query,
            day=row.day.isoformat(),
            impressions=row.impressions,
            broad_impressions=row.broad_impressions,
        )
        for row in rows
    )
    return BingKeywordStatisticsReport(
        tuple(sorted(points, key=lambda point: (point.day, point.query)))
    )


def _bing_related_keywords_report(
    rows: tuple[BingRelatedKeywordRow, ...],
) -> BingRelatedKeywordsReport:
    keywords = tuple(
        BingRelatedKeyword(
            query=row.query,
            impressions=row.impressions,
            broad_impressions=row.broad_impressions,
        )
        for row in rows
    )
    return BingRelatedKeywordsReport(
        tuple(
            sorted(
                keywords,
                key=lambda keyword: (
                    -keyword.impressions,
                    -keyword.broad_impressions,
                    keyword.query,
                ),
            )
        )
    )


def _bing_url_submission_quota_report(
    quota: BingUrlSubmissionQuota,
) -> BingUrlSubmissionQuotaReport:
    return BingUrlSubmissionQuotaReport(daily=quota.daily, monthly=quota.monthly)


def _bing_crawl_issues_report(rows: tuple[BingCrawlIssueRow, ...]) -> BingCrawlIssuesReport:
    issues = tuple(
        BingCrawlIssue(
            url=row.url,
            http_code=row.http_code,
            issues=row.issues,
            in_links=row.in_links,
        )
        for row in rows
    )
    return BingCrawlIssuesReport(
        tuple(sorted(issues, key=lambda issue: (issue.url, issue.http_code, issue.issues)))
    )


def _bing_crawl_stats_report(rows: tuple[BingCrawlStatsRow, ...]) -> BingCrawlStatsReport:
    points = tuple(
        BingCrawlStatsPoint(
            day=row.day.isoformat(),
            all_other_codes=row.all_other_codes,
            blocked_by_robots_txt=row.blocked_by_robots_txt,
            code_2xx=row.code_2xx,
            code_301=row.code_301,
            code_302=row.code_302,
            code_4xx=row.code_4xx,
            code_5xx=row.code_5xx,
            contains_malware=row.contains_malware,
            connection_timeout=row.connection_timeout,
            crawl_errors=row.crawl_errors,
            crawled_pages=row.crawled_pages,
            dns_failures=row.dns_failures,
            in_index=row.in_index,
            in_links=row.in_links,
        )
        for row in rows
    )
    return BingCrawlStatsReport(tuple(sorted(points, key=lambda point: point.day)))


def _bing_feeds_report(rows: tuple[BingFeedRow, ...]) -> BingFeedsReport:
    feeds = tuple(
        BingFeed(
            url=row.url,
            feed_type=row.feed_type,
            status=row.status,
            compressed=row.compressed,
            file_size=row.file_size,
            url_count=row.url_count,
            last_crawled=row.last_crawled.isoformat(),
            submitted=row.submitted.isoformat(),
        )
        for row in rows
    )
    return BingFeedsReport(tuple(sorted(feeds, key=lambda feed: (feed.url, feed.feed_type))))


def _bing_link_counts_report(link_counts: BingLinkCounts) -> BingLinkCountsReport:
    links = tuple(BingLinkCount(url=row.url, count=row.count) for row in link_counts.links)
    return BingLinkCountsReport(
        links=tuple(sorted(links, key=lambda link: (-link.count, link.url))),
        total_pages=link_counts.total_pages,
    )


def _bing_backlink_target_report(
    target_url: str,
    details: tuple[BingLinkDetail, ...],
    total_pages: int,
    pages_read: int,
) -> BingBacklinkTargetReport:
    backlinks = tuple(
        BingBacklink(
            source_url=detail.url,
            source_domain=urlparse(detail.url).hostname or "",
            anchor_text=detail.anchor_text,
        )
        for detail in details
    )
    deduplicated = {(backlink.source_url, backlink.anchor_text): backlink for backlink in backlinks}
    ordered_backlinks = tuple(
        sorted(
            deduplicated.values(),
            key=lambda backlink: (
                backlink.source_domain,
                backlink.source_url,
                backlink.anchor_text,
            ),
        )
    )
    anchor_counts = Counter(backlink.anchor_text for backlink in ordered_backlinks)
    anchors = tuple(
        BingAnchorSummary(anchor_text, count)
        for anchor_text, count in sorted(
            anchor_counts.items(),
            key=lambda item: (-item[1], item[0]),
        )
    )
    return BingBacklinkTargetReport(
        target_url=target_url,
        backlinks=ordered_backlinks,
        referring_domains=tuple(sorted({backlink.source_domain for backlink in ordered_backlinks})),
        anchors=anchors,
        provider_total_pages=total_pages,
        pages_read=pages_read,
        truncated=pages_read < total_pages,
    )


def _bing_url_information_report(
    information: BingUrlInformation,
) -> BingUrlInformationReport:
    return BingUrlInformationReport(
        url=information.url,
        anchor_count=information.anchor_count,
        discovery_date=information.discovery_date.isoformat(),
        document_size=information.document_size,
        http_status=information.http_status,
        is_page=information.is_page,
        last_crawled_date=information.last_crawled_date.isoformat(),
        total_child_url_count=information.total_child_url_count,
    )


def _bing_z_scores(values: tuple[float, ...]) -> tuple[float, tuple[float, ...]]:
    baseline = sum(values) / len(values)
    variance = sum((value - baseline) ** 2 for value in values) / len(values)
    deviation = sqrt(variance)
    if not isfinite(baseline) or not isfinite(deviation):
        raise ProviderOperationError(
            ProviderFailureCode.INVALID_RESPONSE,
            "Bing Webmaster returned metrics that cannot form a finite anomaly baseline",
        )
    if deviation == 0:
        return baseline, tuple(0.0 for _ in values)
    return baseline, tuple((value - baseline) / deviation for value in values)
