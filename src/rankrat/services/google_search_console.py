"""Bounded Google Search Console reads through exact configured properties."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from math import isfinite, sqrt

from rankrat.constants import (
    DEFAULT_PROVIDER_TIMEOUT_SECONDS,
    MAX_ANALYTICS_DATE_RANGE_DAYS,
    MAX_ANALYTICS_DIMENSIONS,
    MAX_ANALYTICS_FILTER_EXPRESSION_CHARS,
    MAX_ANALYTICS_FILTERS,
    MAX_ANALYTICS_OFFSET,
    MAX_ANALYTICS_ROWS,
    MAX_SEARCH_ANALYTICS_DERIVED_ROWS,
    MAX_URL_INSPECTION_BATCH,
    MIN_SEARCH_ANALYTICS_ANOMALY_POINTS,
    SEARCH_ANALYTICS_ANOMALY_Z_SCORE,
)
from rankrat.errors import InputLimitError
from rankrat.models.boundaries import ResourceKind
from rankrat.policy.boundaries import BoundaryPolicy
from rankrat.providers.base import (
    AccountId,
    ProviderFailureCode,
    ProviderOperationError,
    ProviderReadRequest,
)
from rankrat.providers.google_search_console import (
    GoogleSearchConsoleClient,
    SearchAnalyticsQuery,
    SearchAnalyticsReport,
    SearchAnalyticsRow,
    SearchConsoleSite,
    SearchConsoleSitemap,
    SearchConsoleSitemapList,
    SearchConsoleUrlInspection,
)


class SearchAnalyticsDimension(StrEnum):
    """Google Search Console dimensions safe for bounded raw queries."""

    DATE = "date"
    QUERY = "query"
    PAGE = "page"
    COUNTRY = "country"
    DEVICE = "device"
    SEARCH_APPEARANCE = "searchAppearance"


class SearchAnalyticsFilterOperator(StrEnum):
    """Documented Search Console dimension-filter operators."""

    EQUALS = "equals"
    CONTAINS = "contains"
    NOT_CONTAINS = "notContains"
    INCLUDING_REGEX = "includingRegex"
    EXCLUDING_REGEX = "excludingRegex"


class SearchAnalyticsType(StrEnum):
    """Documented Search Console report types."""

    WEB = "web"
    IMAGE = "image"
    VIDEO = "video"
    NEWS = "news"
    DISCOVER = "discover"
    GOOGLE_NEWS = "googleNews"


class SearchAnalyticsDimensionReportKind(StrEnum):
    """Fixed, useful Search Analytics groupings with no caller-selected dimension."""

    TOP_QUERIES = "top_queries"
    TOP_PAGES = "top_pages"
    COUNTRIES = "countries"
    SEARCH_APPEARANCES = "search_appearances"
    TIME_SERIES = "time_series"


class SearchAnalyticsDropAttributionKind(StrEnum):
    """The only fixed dimensions used to attribute a Search Console drop."""

    QUERIES = "queries"
    PAGES = "pages"


@dataclass(frozen=True, slots=True)
class SearchAnalyticsFilter:
    """One bounded literal-or-provider-regex Search Console filter."""

    dimension: SearchAnalyticsDimension
    operator: SearchAnalyticsFilterOperator
    expression: str

    def __post_init__(self) -> None:
        if not self.expression or len(self.expression) > MAX_ANALYTICS_FILTER_EXPRESSION_CHARS:
            raise InputLimitError("Search Analytics filter expression exceeds the allowed size")


@dataclass(frozen=True, slots=True)
class SearchAnalyticsRequest:
    """A typed, bounded Search Console Search Analytics request."""

    account_id: str
    site_url: str
    start_date: date
    end_date: date
    dimensions: tuple[SearchAnalyticsDimension, ...] = ()
    filters: tuple[SearchAnalyticsFilter, ...] = ()
    search_type: SearchAnalyticsType = SearchAnalyticsType.WEB
    row_limit: int = MAX_ANALYTICS_ROWS
    start_row: int = 0
    timeout_seconds: float = DEFAULT_PROVIDER_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        if self.end_date < self.start_date:
            raise InputLimitError("Search Analytics end date precedes start date")
        if (self.end_date - self.start_date).days + 1 > MAX_ANALYTICS_DATE_RANGE_DAYS:
            raise InputLimitError("Search Analytics date range exceeds the allowed size")
        if len(self.dimensions) > MAX_ANALYTICS_DIMENSIONS:
            raise InputLimitError("Search Analytics dimension count exceeds the allowed size")
        if len(set(self.dimensions)) != len(self.dimensions):
            raise InputLimitError("Search Analytics dimensions must not repeat")
        if len(self.filters) > MAX_ANALYTICS_FILTERS:
            raise InputLimitError("Search Analytics filter count exceeds the allowed size")
        if not 1 <= self.row_limit <= MAX_ANALYTICS_ROWS:
            raise InputLimitError("Search Analytics row limit is outside the allowed range")
        if not 0 <= self.start_row <= MAX_ANALYTICS_OFFSET:
            raise InputLimitError("Search Analytics start row is outside the allowed range")


@dataclass(frozen=True, slots=True)
class SearchAnalyticsSummaryRequest:
    """One aggregate report for an exact configured Search Console property."""

    account_id: str
    site_url: str
    start_date: date
    end_date: date
    filters: tuple[SearchAnalyticsFilter, ...] = ()
    search_type: SearchAnalyticsType = SearchAnalyticsType.WEB
    timeout_seconds: float = DEFAULT_PROVIDER_TIMEOUT_SECONDS

    def analytics_request(self) -> SearchAnalyticsRequest:
        """Build a bounded daily request whose rows can be safely aggregated."""

        return SearchAnalyticsRequest(
            account_id=self.account_id,
            site_url=self.site_url,
            start_date=self.start_date,
            end_date=self.end_date,
            dimensions=(SearchAnalyticsDimension.DATE,),
            filters=self.filters,
            search_type=self.search_type,
            row_limit=MAX_ANALYTICS_ROWS,
            timeout_seconds=self.timeout_seconds,
        )


@dataclass(frozen=True, slots=True)
class SearchAnalyticsMetrics:
    """Validated public aggregate metrics derived from untrusted provider rows."""

    clicks: float
    impressions: float
    ctr: float
    position: float


@dataclass(frozen=True, slots=True)
class SearchAnalyticsDimensionReportRequest:
    """One fixed-dimension report for an exact configured Search Console property."""

    account_id: str
    site_url: str
    report: SearchAnalyticsDimensionReportKind
    start_date: date
    end_date: date
    filters: tuple[SearchAnalyticsFilter, ...] = ()
    search_type: SearchAnalyticsType = SearchAnalyticsType.WEB
    row_limit: int = MAX_ANALYTICS_ROWS
    start_row: int = 0
    timeout_seconds: float = DEFAULT_PROVIDER_TIMEOUT_SECONDS

    def analytics_request(self) -> SearchAnalyticsRequest:
        """Build the sole provider request with the report's fixed dimension."""

        return SearchAnalyticsRequest(
            account_id=self.account_id,
            site_url=self.site_url,
            start_date=self.start_date,
            end_date=self.end_date,
            dimensions=(_report_dimension(self.report),),
            filters=self.filters,
            search_type=self.search_type,
            row_limit=self.row_limit,
            start_row=self.start_row,
            timeout_seconds=self.timeout_seconds,
        )


@dataclass(frozen=True, slots=True)
class SearchAnalyticsDimensionReportRow:
    """One validated key and metric set returned by a fixed-dimension report."""

    key: str
    metrics: SearchAnalyticsMetrics


@dataclass(frozen=True, slots=True)
class SearchAnalyticsDimensionReport:
    """A bounded typed page of Search Analytics dimension rows."""

    rows: tuple[SearchAnalyticsDimensionReportRow, ...]
    has_more: bool


@dataclass(frozen=True, slots=True)
class SearchAnalyticsDropAttributionRequest:
    """Compare two periods by one fixed query or page dimension."""

    account_id: str
    site_url: str
    attribution: SearchAnalyticsDropAttributionKind
    current_start_date: date
    current_end_date: date
    previous_start_date: date
    previous_end_date: date
    filters: tuple[SearchAnalyticsFilter, ...] = ()
    search_type: SearchAnalyticsType = SearchAnalyticsType.WEB
    row_limit: int = MAX_SEARCH_ANALYTICS_DERIVED_ROWS
    timeout_seconds: float = DEFAULT_PROVIDER_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        self.current_request().analytics_request()
        self.previous_request().analytics_request()
        if not 1 <= self.row_limit <= MAX_SEARCH_ANALYTICS_DERIVED_ROWS:
            raise InputLimitError("Search Analytics derived row limit is outside the allowed range")

    def current_request(self) -> SearchAnalyticsDimensionReportRequest:
        """Build the fixed-dimension current-period request."""

        return SearchAnalyticsDimensionReportRequest(
            account_id=self.account_id,
            site_url=self.site_url,
            report=_drop_attribution_report(self.attribution),
            start_date=self.current_start_date,
            end_date=self.current_end_date,
            filters=self.filters,
            search_type=self.search_type,
            row_limit=self.row_limit,
            timeout_seconds=self.timeout_seconds,
        )

    def previous_request(self) -> SearchAnalyticsDimensionReportRequest:
        """Build the fixed-dimension comparison-period request."""

        return SearchAnalyticsDimensionReportRequest(
            account_id=self.account_id,
            site_url=self.site_url,
            report=_drop_attribution_report(self.attribution),
            start_date=self.previous_start_date,
            end_date=self.previous_end_date,
            filters=self.filters,
            search_type=self.search_type,
            row_limit=self.row_limit,
            timeout_seconds=self.timeout_seconds,
        )


@dataclass(frozen=True, slots=True)
class SearchAnalyticsDropAttributionRow:
    """One key's typed current/previous metrics and signed loss deltas."""

    key: str
    current: SearchAnalyticsMetrics
    previous: SearchAnalyticsMetrics
    clicks_delta: float
    impressions_delta: float


@dataclass(frozen=True, slots=True)
class SearchAnalyticsDropAttributionReport:
    """A bounded union of the fixed current and comparison report pages."""

    rows: tuple[SearchAnalyticsDropAttributionRow, ...]
    has_more: bool


@dataclass(frozen=True, slots=True)
class SearchAnalyticsTrendRequest:
    """A bounded fixed-date report for one configured Search Console property."""

    account_id: str
    site_url: str
    start_date: date
    end_date: date
    filters: tuple[SearchAnalyticsFilter, ...] = ()
    search_type: SearchAnalyticsType = SearchAnalyticsType.WEB
    timeout_seconds: float = DEFAULT_PROVIDER_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        self.dimension_request().analytics_request()

    def dimension_request(self) -> SearchAnalyticsDimensionReportRequest:
        """Build the fixed date-dimension request."""

        return SearchAnalyticsDimensionReportRequest(
            account_id=self.account_id,
            site_url=self.site_url,
            report=SearchAnalyticsDimensionReportKind.TIME_SERIES,
            start_date=self.start_date,
            end_date=self.end_date,
            filters=self.filters,
            search_type=self.search_type,
            row_limit=MAX_SEARCH_ANALYTICS_DERIVED_ROWS,
            timeout_seconds=self.timeout_seconds,
        )


@dataclass(frozen=True, slots=True)
class SearchAnalyticsTrendPoint:
    """One validated daily Search Analytics metric set."""

    day: str
    metrics: SearchAnalyticsMetrics


@dataclass(frozen=True, slots=True)
class SearchAnalyticsTrendReport:
    """An ascending bounded daily Search Analytics report."""

    points: tuple[SearchAnalyticsTrendPoint, ...]
    has_more: bool


@dataclass(frozen=True, slots=True)
class SearchAnalyticsAnomaly:
    """One daily metric set whose clicks or impressions cross the fixed threshold."""

    day: str
    metrics: SearchAnalyticsMetrics
    clicks_baseline: float
    impressions_baseline: float
    clicks_z_score: float
    impressions_z_score: float


@dataclass(frozen=True, slots=True)
class SearchAnalyticsAnomalyReport:
    """Deterministic daily Search Analytics anomalies for one bounded period."""

    anomalies: tuple[SearchAnalyticsAnomaly, ...]
    has_more: bool


@dataclass(frozen=True, slots=True)
class SearchAnalyticsPagePerformanceRequest:
    """A bounded fixed-page report for one configured Search Console property."""

    account_id: str
    site_url: str
    start_date: date
    end_date: date
    filters: tuple[SearchAnalyticsFilter, ...] = ()
    search_type: SearchAnalyticsType = SearchAnalyticsType.WEB
    row_limit: int = MAX_SEARCH_ANALYTICS_DERIVED_ROWS
    timeout_seconds: float = DEFAULT_PROVIDER_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        self.dimension_request().analytics_request()
        if not 1 <= self.row_limit <= MAX_SEARCH_ANALYTICS_DERIVED_ROWS:
            raise InputLimitError("Search Analytics page row limit is outside the allowed range")

    def dimension_request(self) -> SearchAnalyticsDimensionReportRequest:
        """Build the fixed page-dimension request."""

        return SearchAnalyticsDimensionReportRequest(
            account_id=self.account_id,
            site_url=self.site_url,
            report=SearchAnalyticsDimensionReportKind.TOP_PAGES,
            start_date=self.start_date,
            end_date=self.end_date,
            filters=self.filters,
            search_type=self.search_type,
            row_limit=self.row_limit,
            timeout_seconds=self.timeout_seconds,
        )


@dataclass(frozen=True, slots=True)
class SearchAnalyticsComparisonRequest:
    """Two aggregate periods for one exact configured Search Console property."""

    current: SearchAnalyticsSummaryRequest
    previous_start_date: date
    previous_end_date: date

    def __post_init__(self) -> None:
        """Validate both periods before making either provider request."""

        self.current.analytics_request()
        self.previous_request().analytics_request()

    def previous_request(self) -> SearchAnalyticsSummaryRequest:
        """Build the previous-period request without widening resource scope."""

        return SearchAnalyticsSummaryRequest(
            account_id=self.current.account_id,
            site_url=self.current.site_url,
            start_date=self.previous_start_date,
            end_date=self.previous_end_date,
            filters=self.current.filters,
            search_type=self.current.search_type,
            timeout_seconds=self.current.timeout_seconds,
        )


@dataclass(frozen=True, slots=True)
class SearchAnalyticsComparison:
    """Current/previous metrics plus simple absolute deltas."""

    current: SearchAnalyticsMetrics
    previous: SearchAnalyticsMetrics
    clicks_delta: float
    impressions_delta: float
    ctr_delta: float
    position_delta: float


@dataclass(frozen=True, slots=True)
class SiteListRequest:
    """List Google Search Console properties visible within one configured account."""

    account_id: str
    timeout_seconds: float = DEFAULT_PROVIDER_TIMEOUT_SECONDS


@dataclass(frozen=True, slots=True)
class SiteGetRequest:
    """Get one exact configured Google Search Console property."""

    account_id: str
    site_url: str
    timeout_seconds: float = DEFAULT_PROVIDER_TIMEOUT_SECONDS


@dataclass(frozen=True, slots=True)
class SitemapListRequest:
    """List sitemaps for one exact configured Search Console property."""

    account_id: str
    site_url: str
    timeout_seconds: float = DEFAULT_PROVIDER_TIMEOUT_SECONDS


@dataclass(frozen=True, slots=True)
class SitemapGetRequest:
    """Get one normalized sitemap beneath an exact configured property."""

    account_id: str
    site_url: str
    sitemap_url: str
    timeout_seconds: float = DEFAULT_PROVIDER_TIMEOUT_SECONDS


@dataclass(frozen=True, slots=True)
class UrlInspectionRequest:
    """Inspect a normalized page URL beneath one exact configured property."""

    account_id: str
    site_url: str
    inspection_url: str
    timeout_seconds: float = DEFAULT_PROVIDER_TIMEOUT_SECONDS


@dataclass(frozen=True, slots=True)
class UrlInspectionBatchRequest:
    """Inspect a small, fully authorized set of URLs under one property."""

    account_id: str
    site_url: str
    inspection_urls: tuple[str, ...]
    timeout_seconds: float = DEFAULT_PROVIDER_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        if not self.inspection_urls or len(self.inspection_urls) > MAX_URL_INSPECTION_BATCH:
            raise InputLimitError("URL inspection batch size is outside the allowed range")


class GoogleSearchConsoleService:
    """Application layer for explicit or account-discovered Search Console reads."""

    def __init__(self, policy: BoundaryPolicy, client: GoogleSearchConsoleClient) -> None:
        self._policy = policy
        self._client = client

    async def list_sites(self, request: SiteListRequest) -> tuple[str, ...]:
        """List configured properties or the selected account's OAuth-visible inventory."""

        return await self._client.list_sites(
            ProviderReadRequest(AccountId(request.account_id), request.timeout_seconds)
        )

    async def get_site(self, request: SiteGetRequest) -> SearchConsoleSite:
        """Get one explicit or OAuth-discovered property's permission metadata."""

        return await self._client.get_site(
            ProviderReadRequest(AccountId(request.account_id), request.timeout_seconds),
            request.site_url,
        )

    async def search_analytics(self, request: SearchAnalyticsRequest) -> SearchAnalyticsReport:
        """Run a policy-checked Search Analytics request."""
        self._policy.require_google_read_resource(
            request.account_id,
            ResourceKind.SEARCH_CONSOLE_SITE,
            request.site_url,
        )
        return await self._client.search_analytics(
            ProviderReadRequest(AccountId(request.account_id), request.timeout_seconds),
            request.site_url,
            SearchAnalyticsQuery(
                start_date=request.start_date.isoformat(),
                end_date=request.end_date.isoformat(),
                dimensions=tuple(dimension.value for dimension in request.dimensions),
                search_type=request.search_type.value,
                row_limit=request.row_limit,
                start_row=request.start_row,
                filters=tuple(
                    (item.dimension.value, item.operator.value, item.expression)
                    for item in request.filters
                ),
            ),
        )

    async def search_analytics_summary(
        self,
        request: SearchAnalyticsSummaryRequest,
    ) -> SearchAnalyticsMetrics:
        """Return safe aggregate Search Analytics metrics for one configured property."""

        return self._aggregate_metrics(await self.search_analytics(request.analytics_request()))

    async def search_analytics_comparison(
        self,
        request: SearchAnalyticsComparisonRequest,
    ) -> SearchAnalyticsComparison:
        """Compare two bounded authorized periods without a caller-controlled provider path."""

        current = await self.search_analytics_summary(request.current)
        previous = await self.search_analytics_summary(request.previous_request())
        return SearchAnalyticsComparison(
            current=current,
            previous=previous,
            clicks_delta=current.clicks - previous.clicks,
            impressions_delta=current.impressions - previous.impressions,
            ctr_delta=current.ctr - previous.ctr,
            position_delta=current.position - previous.position,
        )

    async def search_analytics_dimension_report(
        self,
        request: SearchAnalyticsDimensionReportRequest,
    ) -> SearchAnalyticsDimensionReport:
        """Return one validated fixed-dimension Search Analytics result page."""

        analytics_request = request.analytics_request()
        report = await self.search_analytics(analytics_request)
        result_rows = tuple(self._dimension_row(row) for row in report.rows)
        return SearchAnalyticsDimensionReport(
            rows=result_rows,
            has_more=len(result_rows) == request.row_limit,
        )

    async def search_analytics_drop_attribution(
        self,
        request: SearchAnalyticsDropAttributionRequest,
    ) -> SearchAnalyticsDropAttributionReport:
        """Attribute a period loss to a fixed, bounded query or page key union."""

        current = await self.search_analytics_dimension_report(request.current_request())
        previous = await self.search_analytics_dimension_report(request.previous_request())
        current_by_key = {row.key: row.metrics for row in current.rows}
        previous_by_key = {row.key: row.metrics for row in previous.rows}
        if len(current_by_key) != len(current.rows) or len(previous_by_key) != len(previous.rows):
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "Google Search Console returned duplicate report keys",
            )
        empty = SearchAnalyticsMetrics(0.0, 0.0, 0.0, 0.0)
        rows = sorted(
            (
                _drop_attribution_row(
                    key,
                    current_by_key.get(key, empty),
                    previous_by_key.get(key, empty),
                )
                for key in current_by_key.keys() | previous_by_key.keys()
            ),
            key=lambda row: (row.clicks_delta, row.key),
        )
        return SearchAnalyticsDropAttributionReport(
            rows=tuple(rows[: request.row_limit]),
            has_more=current.has_more or previous.has_more or len(rows) > request.row_limit,
        )

    async def search_analytics_trend(
        self,
        request: SearchAnalyticsTrendRequest,
    ) -> SearchAnalyticsTrendReport:
        """Return ordered daily metrics from the sole fixed date dimension."""

        report = await self.search_analytics_dimension_report(request.dimension_request())
        points = tuple(
            _trend_point(row, request.start_date, request.end_date) for row in report.rows
        )
        if len({point.day for point in points}) != len(points):
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "Google Search Console returned duplicate trend days",
            )
        return SearchAnalyticsTrendReport(
            points=tuple(sorted(points, key=lambda point: point.day)),
            has_more=report.has_more,
        )

    async def search_analytics_anomalies(
        self,
        request: SearchAnalyticsTrendRequest,
    ) -> SearchAnalyticsAnomalyReport:
        """Return deterministic click or impression outliers from a daily trend."""

        trend = await self.search_analytics_trend(request)
        if len(trend.points) < MIN_SEARCH_ANALYTICS_ANOMALY_POINTS:
            return SearchAnalyticsAnomalyReport((), trend.has_more)
        clicks = tuple(point.metrics.clicks for point in trend.points)
        impressions = tuple(point.metrics.impressions for point in trend.points)
        clicks_baseline, clicks_z_scores = _z_scores(clicks)
        impressions_baseline, impressions_z_scores = _z_scores(impressions)
        anomalies = tuple(
            SearchAnalyticsAnomaly(
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
            if abs(clicks_z_score) >= SEARCH_ANALYTICS_ANOMALY_Z_SCORE
            or abs(impressions_z_score) >= SEARCH_ANALYTICS_ANOMALY_Z_SCORE
        )
        return SearchAnalyticsAnomalyReport(anomalies, trend.has_more)

    async def search_analytics_page_performance(
        self,
        request: SearchAnalyticsPagePerformanceRequest,
    ) -> SearchAnalyticsDimensionReport:
        """Return a bounded fixed-page report with validated CTR and position."""

        return await self.search_analytics_dimension_report(request.dimension_request())

    async def list_sitemaps(self, request: SitemapListRequest) -> SearchConsoleSitemapList:
        """List policy-authorized sitemaps."""
        return await self._client.list_sitemaps(
            ProviderReadRequest(AccountId(request.account_id), request.timeout_seconds),
            request.site_url,
        )

    async def get_sitemap(self, request: SitemapGetRequest) -> SearchConsoleSitemap:
        """Get one normalized sitemap that belongs to the selected property."""

        sitemap_url = self._policy.require_google_search_console_read_url(
            request.account_id,
            request.site_url,
            request.sitemap_url,
        )
        return await self._client.get_sitemap(
            ProviderReadRequest(AccountId(request.account_id), request.timeout_seconds),
            request.site_url,
            sitemap_url,
        )

    async def inspect_url(self, request: UrlInspectionRequest) -> SearchConsoleUrlInspection:
        """Inspect one normalized URL that belongs to the selected property."""
        inspection_url = self._policy.require_google_search_console_read_url(
            request.account_id,
            request.site_url,
            request.inspection_url,
        )
        return await self._client.inspect_url(
            ProviderReadRequest(AccountId(request.account_id), request.timeout_seconds),
            request.site_url,
            inspection_url,
        )

    async def inspect_urls(
        self,
        request: UrlInspectionBatchRequest,
    ) -> tuple[SearchConsoleUrlInspection, ...]:
        """Inspect each unique, pre-authorized URL without widening provider scope."""

        normalized_urls = tuple(
            self._policy.require_google_search_console_read_url(
                request.account_id,
                request.site_url,
                inspection_url,
            )
            for inspection_url in request.inspection_urls
        )
        if len(set(normalized_urls)) != len(normalized_urls):
            raise InputLimitError("URL inspection batch must not contain duplicate URLs")
        provider_request = ProviderReadRequest(
            AccountId(request.account_id),
            request.timeout_seconds,
        )
        results: list[SearchConsoleUrlInspection] = []
        for inspection_url in normalized_urls:
            result = await self._client.inspect_url(
                provider_request,
                request.site_url,
                inspection_url,
            )
            results.append(result)
        return tuple(results)

    @staticmethod
    def _aggregate_metrics(report: SearchAnalyticsReport) -> SearchAnalyticsMetrics:
        if not report.rows:
            return SearchAnalyticsMetrics(0.0, 0.0, 0.0, 0.0)

        clicks = 0.0
        impressions = 0.0
        weighted_position = 0.0
        for row in report.rows:
            clicks += row.clicks
            impressions += row.impressions
            weighted_position += row.position * row.impressions
        return SearchAnalyticsMetrics(
            clicks=clicks,
            impressions=impressions,
            ctr=clicks / impressions if impressions else 0.0,
            position=weighted_position / impressions if impressions else 0.0,
        )

    @staticmethod
    def _dimension_row(row: SearchAnalyticsRow) -> SearchAnalyticsDimensionReportRow:
        if len(row.keys) != 1:
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "Google Search Console returned an invalid report key",
            )
        return SearchAnalyticsDimensionReportRow(
            key=row.keys[0],
            metrics=SearchAnalyticsMetrics(
                clicks=row.clicks,
                impressions=row.impressions,
                ctr=row.clicks / row.impressions if row.impressions else 0.0,
                position=row.position,
            ),
        )


def _report_dimension(report: SearchAnalyticsDimensionReportKind) -> SearchAnalyticsDimension:
    report_dimensions = {
        SearchAnalyticsDimensionReportKind.TOP_QUERIES: SearchAnalyticsDimension.QUERY,
        SearchAnalyticsDimensionReportKind.TOP_PAGES: SearchAnalyticsDimension.PAGE,
        SearchAnalyticsDimensionReportKind.COUNTRIES: SearchAnalyticsDimension.COUNTRY,
        SearchAnalyticsDimensionReportKind.SEARCH_APPEARANCES: (
            SearchAnalyticsDimension.SEARCH_APPEARANCE
        ),
        SearchAnalyticsDimensionReportKind.TIME_SERIES: SearchAnalyticsDimension.DATE,
    }
    return report_dimensions[report]


def _drop_attribution_report(
    attribution: SearchAnalyticsDropAttributionKind,
) -> SearchAnalyticsDimensionReportKind:
    reports = {
        SearchAnalyticsDropAttributionKind.QUERIES: SearchAnalyticsDimensionReportKind.TOP_QUERIES,
        SearchAnalyticsDropAttributionKind.PAGES: SearchAnalyticsDimensionReportKind.TOP_PAGES,
    }
    return reports[attribution]


def _drop_attribution_row(
    key: str,
    current: SearchAnalyticsMetrics,
    previous: SearchAnalyticsMetrics,
) -> SearchAnalyticsDropAttributionRow:
    return SearchAnalyticsDropAttributionRow(
        key=key,
        current=current,
        previous=previous,
        clicks_delta=current.clicks - previous.clicks,
        impressions_delta=current.impressions - previous.impressions,
    )


def _trend_point(
    row: SearchAnalyticsDimensionReportRow,
    start_date: date,
    end_date: date,
) -> SearchAnalyticsTrendPoint:
    try:
        day = date.fromisoformat(row.key)
    except ValueError as error:
        raise ProviderOperationError(
            ProviderFailureCode.INVALID_RESPONSE,
            "Google Search Console returned an invalid trend day",
        ) from error
    if day < start_date or day > end_date:
        raise ProviderOperationError(
            ProviderFailureCode.INVALID_RESPONSE,
            "Google Search Console returned a trend day outside the requested period",
        )
    return SearchAnalyticsTrendPoint(day.isoformat(), row.metrics)


def _z_scores(values: tuple[float, ...]) -> tuple[float, tuple[float, ...]]:
    baseline = sum(values) / len(values)
    variance = sum((value - baseline) ** 2 for value in values) / len(values)
    deviation = sqrt(variance)
    if not isfinite(baseline) or not isfinite(deviation):
        raise ProviderOperationError(
            ProviderFailureCode.INVALID_RESPONSE,
            "Google Search Console returned metrics that cannot form a finite anomaly baseline",
        )
    if deviation == 0:
        return baseline, tuple(0.0 for _ in values)
    z_scores = tuple((value - baseline) / deviation for value in values)
    if not all(isfinite(z_score) for z_score in z_scores):
        raise ProviderOperationError(
            ProviderFailureCode.INVALID_RESPONSE,
            "Google Search Console returned metrics that cannot form finite anomaly scores",
        )
    return baseline, z_scores
