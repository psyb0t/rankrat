"""Official low-level MCP server shared by stdio and Streamable HTTP."""
# pyright: reportGeneralTypeIssues=false, reportUnusedClass=false, reportUnusedImport=false, reportUnusedVariable=false

from __future__ import annotations

import json
from datetime import date
from enum import StrEnum
from typing import Any, Final
from urllib.parse import unquote

import mcp.types as types
from mcp.server.lowlevel import Server
from pydantic import AnyUrl, BaseModel, ConfigDict, Field, ValidationError

from rankrat import __version__
from rankrat.constants import (
    APP_NAME,
    BING_OPPORTUNITY_MATRIX_OPERATION,
    DEFAULT_LIGHTHOUSE_TIMEOUT_SECONDS,
    DEFAULT_PAGESPEED_TIMEOUT_SECONDS,
    DEFAULT_PROVIDER_TIMEOUT_SECONDS,
    DEFAULT_SITE_AUDIT_DEPTH,
    DEFAULT_SITE_AUDIT_PAGES,
    GA4_PAGESPEED_CORRELATION_OPERATION,
    GA4_SEARCH_CONSOLE_COMPARISON_OPERATION,
    GOOGLE_ANALYTICS_ACCOUNT_INVENTORY_OPERATION,
    ISO_CURRENCY_CODE_CHARS,
    LIGHTHOUSE_ACCESSIBILITY_FINDINGS_OPERATION,
    LIGHTHOUSE_AUDIT_OPERATION,
    LIGHTHOUSE_BEST_PRACTICES_FINDINGS_OPERATION,
    LIGHTHOUSE_PERFORMANCE_FINDINGS_OPERATION,
    LIGHTHOUSE_SEO_FINDINGS_OPERATION,
    MAX_ANALYTICS_DIMENSIONS,
    MAX_ANALYTICS_FILTERS,
    MAX_BING_BACKLINK_TARGETS,
    MAX_BING_BRAND_TERMS,
    MAX_BING_COUNTRY_CHARS,
    MAX_BING_LANGUAGE_CHARS,
    MAX_BING_LINK_PAGE,
    MAX_BING_QUERY_CHARS,
    MAX_BING_SUBMISSION_URLS,
    MAX_GA4_DATE_RANGES,
    MAX_GA4_DIMENSIONS,
    MAX_GA4_FUNNEL_STEPS,
    MAX_GA4_METRICS,
    MAX_GA4_OFFSET,
    MAX_GA4_ROWS,
    MAX_GOOGLE_INDEXING_BATCH,
    MAX_INDEXNOW_URLS,
    MAX_LIGHTHOUSE_TIMEOUT_SECONDS,
    MAX_PAGESPEED_CATEGORIES,
    MAX_PROVIDER_TIMEOUT_SECONDS,
    MAX_SCHEMA_FETCH_URL_CHARS,
    MAX_SCHEMA_LOCAL_DOCUMENT_CHARS,
    MAX_SEARCH_ANALYTICS_DERIVED_ROWS,
    MAX_SITE_AUDIT_DEPTH,
    MAX_SITE_AUDIT_PAGES,
    MAX_SITE_ONBOARDING_DISPLAY_NAME_CHARS,
    MAX_SITE_ONBOARDING_TIME_ZONE_CHARS,
    MAX_URL_INSPECTION_BATCH,
    MIN_GA4_FUNNEL_STEPS,
    MIN_LIGHTHOUSE_TIMEOUT_SECONDS,
    MIN_PROVIDER_TIMEOUT_SECONDS,
    PAGESPEED_CORE_WEB_VITALS_OPERATION,
    PROVIDER_OPERATION_FAILED_MESSAGE,
    SEARCH_ENGINE_COMPARISON_OPERATION,
    SEARCH_ENGINE_TRAFFIC_HEALTH_OPERATION,
)
from rankrat.errors import RankratError
from rankrat.models.boundaries import ACCOUNT_ID_PATTERN, Provider
from rankrat.models.common import JsonValue, to_json_value
from rankrat.providers.base import ProviderOperationError
from rankrat.services.bing import (
    BingBacklinkIntelligenceRequest,
    BingBrandAnalysisRequest,
    BingCrawlIssuesRequest,
    BingCrawlStatsRequest,
    BingFeedsRequest,
    BingKeywordStatisticsRequest,
    BingLinkCountsRequest,
    BingPageQueryPerformanceRequest,
    BingPerformanceRequest,
    BingQueryPagePerformanceRequest,
    BingRelatedKeywordsRequest,
    BingSitemapOperation,
    BingSitemapSubmissionRequest,
    BingSiteOperation,
    BingSiteSubmissionRequest,
    BingTrafficComparisonRequest,
    BingTrafficPeriodRequest,
    BingUrlInformationRequest,
    BingUrlSubmissionQuotaRequest,
    BingUrlSubmissionRequest,
)
from rankrat.services.capabilities import ServerInfoRequest
from rankrat.services.cross_provider import (
    Ga4PageSpeedCorrelationRequest,
    Ga4SearchConsoleComparisonRequest,
    SearchEngineComparisonRequest,
    SearchEngineTrafficHealthRequest,
)
from rankrat.services.diagnostics import DiagnosticsRequest
from rankrat.services.google_analytics import (
    Ga4AccountDiscoveryRequest,
    Ga4ConversionFunnelRequest,
    Ga4DateRange,
    Ga4FixedReportKind,
    Ga4FixedReportRequest,
    Ga4RealtimeReportRequest,
    Ga4ReportRequest,
)
from rankrat.services.google_analytics_admin import (
    Ga4AccountRenameRequest,
    Ga4DataStreamsRequest,
    Ga4PropertyRenameRequest,
)
from rankrat.services.google_indexing import (
    GoogleIndexingBatchNotification,
    GoogleIndexingBatchSubmissionRequest,
    GoogleIndexingNotificationType,
    GoogleIndexingSubmissionRequest,
)
from rankrat.services.google_indexing_metadata import GoogleIndexingMetadataRequest
from rankrat.services.google_search_console import (
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
from rankrat.services.google_sitemaps import (
    GoogleSitemapOperation,
    GoogleSitemapSubmissionRequest,
)
from rankrat.services.google_sites import GoogleSiteOperation, GoogleSiteSubmissionRequest
from rankrat.services.indexnow import IndexNowSubmissionRequest
from rankrat.services.lighthouse import LighthouseAuditRequest, LighthouseCategory
from rankrat.services.onboarding_guide import OnboardingGuideRequest
from rankrat.services.pagespeed import (
    PageSpeedAnalysisRequest,
    PageSpeedCategory,
    PageSpeedStrategy,
)
from rankrat.services.provider_readiness import ProviderReadinessRequest
from rankrat.services.schema import (
    LocalSchemaValidationRequest,
    PublicSchemaValidationRequest,
)
from rankrat.services.site_audit import SiteAuditRequest
from rankrat.services.site_onboarding import SiteOnboardingSubmissionRequest
from rankrat.services.site_ownership import (
    SiteOwnershipCheckRequest,
    SiteOwnershipVerificationRequest,
)
from rankrat.services.site_remediation import SiteRemediationRequest
from rankrat.services.sites import AccountsListRequest, SitesListRequest
from rankrat.transports.runtime import ApplicationServices
from rankrat.transports.seo_mcp import (
    SEO_TOOL_NOT_HANDLED,
    dispatch_seo_tool,
    seo_mcp_tools,
)
from rankrat.transports.tool_contracts import ToolAnnotations, tool_catalog

_OBJECT_SCHEMA = "object"
# GA4 account, property and stream IDs are all bare numerics. The same literal is
# still inlined on the older report arguments below; new arguments use the name.
_GA4_RESOURCE_ID_PATTERN = r"^[0-9]+$"
_GA4_DISPLAY_NAME_MAX_CHARS = 255
_JSON_MIME_TYPE = "application/json"
_ONBOARDING_RESOURCE_URI = "rankrat://onboarding"
_ONBOARDING_RESOURCE_NAME = "onboarding"
_ONBOARDING_RESOURCE_DESCRIPTION = (
    "The onboarding steps only the operator can perform, and what to tell them."
)
_ONBOARDING_SITE_RESOURCE_TEMPLATE = "rankrat://onboarding/{site_url}"
_ONBOARDING_SITE_RESOURCE_NAME = "onboarding-site"
_ONBOARDING_SITE_RESOURCE_DESCRIPTION = (
    "The same guidance narrowed to one percent-encoded site URL, which decides "
    "which verification methods its Search Console property form accepts."
)
_ONBOARDING_SITE_RESOURCE_PREFIX = f"{_ONBOARDING_RESOURCE_URI}/"
_UNKNOWN_RESOURCE_CODE = "RESOURCE_NOT_FOUND"
_TOOL_ERROR_CODE = "TOOL_INPUT_INVALID"
_UNKNOWN_TOOL_CODE = "TOOL_NOT_FOUND"
_TOOL_REQUEST_REJECTED_CODE = "TOOL_REQUEST_REJECTED"
_LIGHTHOUSE_CATEGORY_BY_OPERATION = {
    LIGHTHOUSE_SEO_FINDINGS_OPERATION: LighthouseCategory.SEO,
    LIGHTHOUSE_ACCESSIBILITY_FINDINGS_OPERATION: LighthouseCategory.ACCESSIBILITY,
    LIGHTHOUSE_PERFORMANCE_FINDINGS_OPERATION: LighthouseCategory.PERFORMANCE,
    LIGHTHOUSE_BEST_PRACTICES_FINDINGS_OPERATION: LighthouseCategory.BEST_PRACTICES,
}
_GA4_FIXED_REPORT_TOOL_KINDS: Final[dict[str, Ga4FixedReportKind]] = {
    "google_analytics_content_performance": Ga4FixedReportKind.CONTENT_PERFORMANCE,
    "google_analytics_landing_page_performance": Ga4FixedReportKind.LANDING_PAGE_PERFORMANCE,
    "google_analytics_organic_search_landing_pages": (
        Ga4FixedReportKind.ORGANIC_SEARCH_LANDING_PAGES
    ),
    "google_analytics_traffic_source_performance": Ga4FixedReportKind.TRAFFIC_SOURCE_PERFORMANCE,
    "google_analytics_ecommerce_performance": Ga4FixedReportKind.ECOMMERCE_PERFORMANCE,
    "google_analytics_audience_segments": Ga4FixedReportKind.AUDIENCE_SEGMENTS,
    "google_analytics_user_behavior": Ga4FixedReportKind.USER_BEHAVIOR,
}


class _BingQueryPageReportKind(StrEnum):
    PERFORMANCE = "performance"
    CANNIBALIZATION = "cannibalization"


_BING_QUERY_PAGE_REPORT_TOOL_KINDS: Final[dict[str, _BingQueryPageReportKind]] = {
    "bing_query_page_performance": _BingQueryPageReportKind.PERFORMANCE,
    "bing_query_cannibalization": _BingQueryPageReportKind.CANNIBALIZATION,
}


class _BingSitePerformanceReportKind(StrEnum):
    QUERY = "query"
    PAGE = "page"
    BRAND = "brand"
    RANKING_BUCKETS = "ranking_buckets"


_BING_SITE_PERFORMANCE_REPORT_TOOL_KINDS: Final[dict[str, _BingSitePerformanceReportKind]] = {
    "bing_query_performance": _BingSitePerformanceReportKind.QUERY,
    "bing_page_performance": _BingSitePerformanceReportKind.PAGE,
    "bing_brand_analysis": _BingSitePerformanceReportKind.BRAND,
    "bing_ranking_buckets": _BingSitePerformanceReportKind.RANKING_BUCKETS,
}


class _NoArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _AccountsListArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: Provider | None = None


class _SitesListArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    account_id: str | None = None
    provider: Provider | None = None


class _ProviderReadinessArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    account_id: str = Field(pattern=ACCOUNT_ID_PATTERN)
    timeout_seconds: float = Field(
        default=DEFAULT_PROVIDER_TIMEOUT_SECONDS,
        ge=MIN_PROVIDER_TIMEOUT_SECONDS,
        le=MAX_PROVIDER_TIMEOUT_SECONDS,
    )


class _IndexNowSubmissionArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    target_id: str = Field(pattern=ACCOUNT_ID_PATTERN)
    urls: tuple[str, ...] = Field(min_length=1, max_length=MAX_INDEXNOW_URLS)


class _GoogleIndexingSubmissionArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    account_id: str = Field(pattern=ACCOUNT_ID_PATTERN)
    site_url: str = Field(min_length=1, max_length=2_048)
    url: str = Field(min_length=1, max_length=2_048)
    notification_type: GoogleIndexingNotificationType
    timeout_seconds: float = Field(
        default=DEFAULT_PROVIDER_TIMEOUT_SECONDS,
        ge=MIN_PROVIDER_TIMEOUT_SECONDS,
        le=MAX_PROVIDER_TIMEOUT_SECONDS,
    )


class _GoogleIndexingBatchNotificationArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    url: str = Field(min_length=1, max_length=2_048)
    notification_type: GoogleIndexingNotificationType


class _GoogleIndexingBatchSubmissionArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    account_id: str = Field(pattern=ACCOUNT_ID_PATTERN)
    site_url: str = Field(min_length=1, max_length=2_048)
    notifications: tuple[_GoogleIndexingBatchNotificationArguments, ...] = Field(
        min_length=1,
        max_length=MAX_GOOGLE_INDEXING_BATCH,
    )
    timeout_seconds: float = Field(
        default=DEFAULT_PROVIDER_TIMEOUT_SECONDS,
        ge=MIN_PROVIDER_TIMEOUT_SECONDS,
        le=MAX_PROVIDER_TIMEOUT_SECONDS,
    )


class _GoogleIndexingMetadataArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    account_id: str = Field(pattern=ACCOUNT_ID_PATTERN)
    site_url: str = Field(min_length=1, max_length=2_048)
    url: str = Field(min_length=1, max_length=2_048)
    timeout_seconds: float = Field(
        default=DEFAULT_PROVIDER_TIMEOUT_SECONDS,
        ge=MIN_PROVIDER_TIMEOUT_SECONDS,
        le=MAX_PROVIDER_TIMEOUT_SECONDS,
    )


class _GoogleSitemapSubmissionArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    account_id: str = Field(pattern=ACCOUNT_ID_PATTERN)
    site_url: str = Field(min_length=1, max_length=2_048)
    sitemap_url: str = Field(min_length=1, max_length=2_048)
    operation: GoogleSitemapOperation
    timeout_seconds: float = Field(
        default=DEFAULT_PROVIDER_TIMEOUT_SECONDS,
        ge=MIN_PROVIDER_TIMEOUT_SECONDS,
        le=MAX_PROVIDER_TIMEOUT_SECONDS,
    )


class _GoogleSiteSubmissionArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    account_id: str = Field(pattern=ACCOUNT_ID_PATTERN)
    site_url: str = Field(min_length=1, max_length=2_048)
    operation: GoogleSiteOperation
    timeout_seconds: float = Field(
        default=DEFAULT_PROVIDER_TIMEOUT_SECONDS,
        ge=MIN_PROVIDER_TIMEOUT_SECONDS,
        le=MAX_PROVIDER_TIMEOUT_SECONDS,
    )


class _Ga4DataStreamsArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    account_id: str = Field(pattern=ACCOUNT_ID_PATTERN)
    property_id: str = Field(pattern=_GA4_RESOURCE_ID_PATTERN)
    timeout_seconds: float = Field(default=10.0, gt=0, le=30.0)


class _Ga4AccountRenameArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    account_id: str = Field(pattern=ACCOUNT_ID_PATTERN)
    analytics_account_id: str = Field(pattern=_GA4_RESOURCE_ID_PATTERN)
    display_name: str = Field(min_length=1, max_length=_GA4_DISPLAY_NAME_MAX_CHARS)
    timeout_seconds: float = Field(default=10.0, gt=0, le=30.0)


class _Ga4PropertyRenameArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    account_id: str = Field(pattern=ACCOUNT_ID_PATTERN)
    property_id: str = Field(pattern=_GA4_RESOURCE_ID_PATTERN)
    display_name: str = Field(min_length=1, max_length=_GA4_DISPLAY_NAME_MAX_CHARS)
    timeout_seconds: float = Field(default=10.0, gt=0, le=30.0)


class _OnboardingGuideArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    site_url: str | None = Field(default=None, min_length=1, max_length=2_048)


class _SiteOnboardingSubmissionArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    google_account_id: str = Field(pattern=ACCOUNT_ID_PATTERN)
    bing_account_id: str = Field(pattern=ACCOUNT_ID_PATTERN)
    site_url: str = Field(min_length=1, max_length=2_048)
    google_analytics_parent_account_id: str | None = Field(default=None, max_length=64)
    display_name: str | None = Field(
        default=None, max_length=MAX_SITE_ONBOARDING_DISPLAY_NAME_CHARS
    )
    time_zone: str = Field(
        default="Etc/UTC", min_length=1, max_length=MAX_SITE_ONBOARDING_TIME_ZONE_CHARS
    )
    currency_code: str = Field(
        default="USD", min_length=ISO_CURRENCY_CODE_CHARS, max_length=ISO_CURRENCY_CODE_CHARS
    )
    timeout_seconds: float = Field(
        default=DEFAULT_PROVIDER_TIMEOUT_SECONDS,
        ge=MIN_PROVIDER_TIMEOUT_SECONDS,
        le=MAX_PROVIDER_TIMEOUT_SECONDS,
    )


class _SiteOwnershipCheckArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    google_account_id: str = Field(pattern=ACCOUNT_ID_PATTERN)
    bing_account_id: str = Field(pattern=ACCOUNT_ID_PATTERN)
    site_url: str = Field(min_length=1, max_length=2_048)
    timeout_seconds: float = Field(
        default=DEFAULT_PROVIDER_TIMEOUT_SECONDS,
        ge=MIN_PROVIDER_TIMEOUT_SECONDS,
        le=MAX_PROVIDER_TIMEOUT_SECONDS,
    )


class _SiteOwnershipVerificationArguments(_SiteOwnershipCheckArguments):
    dns_account_id: str = Field(pattern=ACCOUNT_ID_PATTERN)


class _SiteAuditArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    account_id: str = Field(pattern=ACCOUNT_ID_PATTERN)
    site_url: str = Field(min_length=1, max_length=2_048)
    max_pages: int = Field(default=DEFAULT_SITE_AUDIT_PAGES, ge=1, le=MAX_SITE_AUDIT_PAGES)
    max_depth: int = Field(default=DEFAULT_SITE_AUDIT_DEPTH, ge=0, le=MAX_SITE_AUDIT_DEPTH)
    timeout_seconds: float = Field(
        default=DEFAULT_PROVIDER_TIMEOUT_SECONDS,
        ge=MIN_PROVIDER_TIMEOUT_SECONDS,
        le=MAX_PROVIDER_TIMEOUT_SECONDS,
    )


class _SiteRemediationArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    google_account_id: str = Field(pattern=ACCOUNT_ID_PATTERN)
    google_site_url: str = Field(min_length=1, max_length=2_048)
    bing_account_id: str = Field(pattern=ACCOUNT_ID_PATTERN)
    bing_site_url: str = Field(min_length=1, max_length=2_048)
    sitemap_url: str = Field(min_length=1, max_length=2_048)
    changed_urls: tuple[str, ...] = Field(min_length=1, max_length=MAX_BING_SUBMISSION_URLS)
    timeout_seconds: float = Field(
        default=DEFAULT_PROVIDER_TIMEOUT_SECONDS,
        ge=MIN_PROVIDER_TIMEOUT_SECONDS,
        le=MAX_PROVIDER_TIMEOUT_SECONDS,
    )


class _SearchAnalyticsFilterArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    dimension: SearchAnalyticsDimension
    operator: SearchAnalyticsFilterOperator
    expression: str = Field(min_length=1, max_length=4_096)


class _SearchAnalyticsArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    account_id: str = Field(pattern=ACCOUNT_ID_PATTERN)
    site_url: str = Field(min_length=1, max_length=2_048)
    start_date: date
    end_date: date
    dimensions: tuple[SearchAnalyticsDimension, ...] = Field(max_length=MAX_ANALYTICS_DIMENSIONS)
    filters: tuple[_SearchAnalyticsFilterArguments, ...] = Field(
        default=(),
        max_length=MAX_ANALYTICS_FILTERS,
    )
    search_type: SearchAnalyticsType = SearchAnalyticsType.WEB
    row_limit: int = Field(default=1_000, ge=1, le=1_000)
    start_row: int = Field(default=0, ge=0, le=100_000)
    timeout_seconds: float = Field(
        default=DEFAULT_PROVIDER_TIMEOUT_SECONDS,
        ge=MIN_PROVIDER_TIMEOUT_SECONDS,
        le=MAX_PROVIDER_TIMEOUT_SECONDS,
    )


class _SearchAnalyticsSummaryArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    account_id: str = Field(pattern=ACCOUNT_ID_PATTERN)
    site_url: str = Field(min_length=1, max_length=2_048)
    start_date: date
    end_date: date
    filters: tuple[_SearchAnalyticsFilterArguments, ...] = Field(
        default=(),
        max_length=MAX_ANALYTICS_FILTERS,
    )
    search_type: SearchAnalyticsType = SearchAnalyticsType.WEB
    timeout_seconds: float = Field(
        default=DEFAULT_PROVIDER_TIMEOUT_SECONDS,
        ge=MIN_PROVIDER_TIMEOUT_SECONDS,
        le=MAX_PROVIDER_TIMEOUT_SECONDS,
    )


class _SearchAnalyticsComparisonArguments(_SearchAnalyticsSummaryArguments):
    previous_start_date: date
    previous_end_date: date


class _SearchAnalyticsDimensionReportArguments(_SearchAnalyticsSummaryArguments):
    report: SearchAnalyticsDimensionReportKind
    row_limit: int = Field(default=1_000, ge=1, le=1_000)
    start_row: int = Field(default=0, ge=0, le=100_000)


class _SearchAnalyticsDropAttributionArguments(_SearchAnalyticsSummaryArguments):
    attribution: SearchAnalyticsDropAttributionKind
    previous_start_date: date
    previous_end_date: date
    row_limit: int = Field(default=MAX_SEARCH_ANALYTICS_DERIVED_ROWS, ge=1, le=500)


class _SearchAnalyticsPagePerformanceArguments(_SearchAnalyticsSummaryArguments):
    row_limit: int = Field(default=MAX_SEARCH_ANALYTICS_DERIVED_ROWS, ge=1, le=500)


def _summary_request(
    arguments: _SearchAnalyticsSummaryArguments,
) -> SearchAnalyticsSummaryRequest:
    return SearchAnalyticsSummaryRequest(
        account_id=arguments.account_id,
        site_url=arguments.site_url,
        start_date=arguments.start_date,
        end_date=arguments.end_date,
        filters=tuple(
            SearchAnalyticsFilter(
                dimension=item.dimension,
                operator=item.operator,
                expression=item.expression,
            )
            for item in arguments.filters
        ),
        search_type=arguments.search_type,
        timeout_seconds=arguments.timeout_seconds,
    )


def _trend_request(
    arguments: _SearchAnalyticsSummaryArguments,
) -> SearchAnalyticsTrendRequest:
    return SearchAnalyticsTrendRequest(
        account_id=arguments.account_id,
        site_url=arguments.site_url,
        start_date=arguments.start_date,
        end_date=arguments.end_date,
        filters=tuple(
            SearchAnalyticsFilter(
                dimension=item.dimension,
                operator=item.operator,
                expression=item.expression,
            )
            for item in arguments.filters
        ),
        search_type=arguments.search_type,
        timeout_seconds=arguments.timeout_seconds,
    )


class _SitemapListArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    account_id: str = Field(pattern=ACCOUNT_ID_PATTERN)
    site_url: str = Field(min_length=1, max_length=2_048)
    timeout_seconds: float = Field(
        default=DEFAULT_PROVIDER_TIMEOUT_SECONDS,
        ge=MIN_PROVIDER_TIMEOUT_SECONDS,
        le=MAX_PROVIDER_TIMEOUT_SECONDS,
    )


class _GoogleSitesListArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    account_id: str = Field(pattern=ACCOUNT_ID_PATTERN)
    timeout_seconds: float = Field(
        default=DEFAULT_PROVIDER_TIMEOUT_SECONDS,
        ge=MIN_PROVIDER_TIMEOUT_SECONDS,
        le=MAX_PROVIDER_TIMEOUT_SECONDS,
    )


class _GoogleSiteGetArguments(_GoogleSitesListArguments):
    site_url: str = Field(min_length=1, max_length=2_048)


class _SitemapGetArguments(_SitemapListArguments):
    sitemap_url: str = Field(min_length=1, max_length=2_048)


class _UrlInspectionArguments(_SitemapListArguments):
    inspection_url: str = Field(min_length=1, max_length=2_048)


class _UrlInspectionBatchArguments(_SitemapListArguments):
    inspection_urls: tuple[str, ...] = Field(
        min_length=1,
        max_length=MAX_URL_INSPECTION_BATCH,
    )


class _Ga4DateRangeArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    start_date: date
    end_date: date


class _Ga4ReportArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    account_id: str = Field(pattern=ACCOUNT_ID_PATTERN)
    property_id: str = Field(pattern=r"^[0-9]+$")
    date_ranges: tuple[_Ga4DateRangeArguments, ...] = Field(
        min_length=1,
        max_length=MAX_GA4_DATE_RANGES,
    )
    dimensions: tuple[str, ...] = Field(min_length=1, max_length=MAX_GA4_DIMENSIONS)
    metrics: tuple[str, ...] = Field(min_length=1, max_length=MAX_GA4_METRICS)
    limit: int = Field(default=MAX_GA4_ROWS, ge=1, le=MAX_GA4_ROWS)
    offset: int = Field(default=0, ge=0, le=MAX_GA4_OFFSET)
    timeout_seconds: float = Field(
        default=DEFAULT_PROVIDER_TIMEOUT_SECONDS,
        ge=MIN_PROVIDER_TIMEOUT_SECONDS,
        le=MAX_PROVIDER_TIMEOUT_SECONDS,
    )


class _Ga4RealtimeReportArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    account_id: str = Field(pattern=ACCOUNT_ID_PATTERN)
    property_id: str = Field(pattern=r"^[0-9]+$")
    dimensions: tuple[str, ...] = Field(min_length=1, max_length=MAX_GA4_DIMENSIONS)
    metrics: tuple[str, ...] = Field(min_length=1, max_length=MAX_GA4_METRICS)
    limit: int = Field(default=MAX_GA4_ROWS, ge=1, le=MAX_GA4_ROWS)
    timeout_seconds: float = Field(
        default=DEFAULT_PROVIDER_TIMEOUT_SECONDS,
        ge=MIN_PROVIDER_TIMEOUT_SECONDS,
        le=MAX_PROVIDER_TIMEOUT_SECONDS,
    )


class _Ga4FixedReportArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    account_id: str = Field(pattern=ACCOUNT_ID_PATTERN)
    property_id: str = Field(pattern=r"^[0-9]+$")
    start_date: date
    end_date: date
    limit: int = Field(default=MAX_GA4_ROWS, ge=1, le=MAX_GA4_ROWS)
    timeout_seconds: float = Field(
        default=DEFAULT_PROVIDER_TIMEOUT_SECONDS,
        ge=MIN_PROVIDER_TIMEOUT_SECONDS,
        le=MAX_PROVIDER_TIMEOUT_SECONDS,
    )


class _Ga4ConversionFunnelArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    account_id: str = Field(pattern=ACCOUNT_ID_PATTERN)
    property_id: str = Field(pattern=r"^[0-9]+$")
    start_date: date
    end_date: date
    event_names: tuple[str, ...] = Field(
        min_length=MIN_GA4_FUNNEL_STEPS,
        max_length=MAX_GA4_FUNNEL_STEPS,
    )
    limit: int = Field(default=MAX_GA4_ROWS, ge=1, le=MAX_GA4_ROWS)
    timeout_seconds: float = Field(
        default=DEFAULT_PROVIDER_TIMEOUT_SECONDS,
        ge=MIN_PROVIDER_TIMEOUT_SECONDS,
        le=MAX_PROVIDER_TIMEOUT_SECONDS,
    )


def _fixed_report_request(arguments: _Ga4FixedReportArguments) -> Ga4FixedReportRequest:
    return Ga4FixedReportRequest(
        account_id=arguments.account_id,
        property_id=arguments.property_id,
        start_date=arguments.start_date,
        end_date=arguments.end_date,
        limit=arguments.limit,
        timeout_seconds=arguments.timeout_seconds,
    )


class _BingKeywordStatisticsArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    account_id: str = Field(pattern=ACCOUNT_ID_PATTERN)
    query: str = Field(min_length=1, max_length=MAX_BING_QUERY_CHARS)
    country: str | None = Field(default=None, min_length=1, max_length=MAX_BING_COUNTRY_CHARS)
    language: str | None = Field(default=None, min_length=1, max_length=MAX_BING_LANGUAGE_CHARS)
    timeout_seconds: float = Field(
        default=DEFAULT_PROVIDER_TIMEOUT_SECONDS,
        ge=MIN_PROVIDER_TIMEOUT_SECONDS,
        le=MAX_PROVIDER_TIMEOUT_SECONDS,
    )


class _BingRelatedKeywordsArguments(_BingKeywordStatisticsArguments):
    start_date: date
    end_date: date


class _BingTrafficArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    account_id: str = Field(pattern=ACCOUNT_ID_PATTERN)
    site_url: str = Field(min_length=1, max_length=2_048)
    start_date: date
    end_date: date
    timeout_seconds: float = Field(
        default=DEFAULT_PROVIDER_TIMEOUT_SECONDS,
        ge=MIN_PROVIDER_TIMEOUT_SECONDS,
        le=MAX_PROVIDER_TIMEOUT_SECONDS,
    )


class _BingTrafficComparisonArguments(_BingTrafficArguments):
    previous_start_date: date
    previous_end_date: date


class _BingPerformanceArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    account_id: str = Field(pattern=ACCOUNT_ID_PATTERN)
    site_url: str = Field(min_length=1, max_length=2_048)
    timeout_seconds: float = Field(
        default=DEFAULT_PROVIDER_TIMEOUT_SECONDS,
        ge=MIN_PROVIDER_TIMEOUT_SECONDS,
        le=MAX_PROVIDER_TIMEOUT_SECONDS,
    )


class _BingBrandAnalysisArguments(_BingPerformanceArguments):
    brand_terms: tuple[str, ...] = Field(min_length=1, max_length=MAX_BING_BRAND_TERMS)


class _BingQueryPagePerformanceArguments(_BingPerformanceArguments):
    query: str = Field(min_length=1, max_length=MAX_BING_QUERY_CHARS)


class _BingPageQueryPerformanceArguments(_BingPerformanceArguments):
    page_url: str = Field(min_length=1, max_length=2_048)


class _BingUrlInformationArguments(_BingPerformanceArguments):
    page_url: str = Field(min_length=1, max_length=2_048)


class _BingLinkCountsArguments(_BingPerformanceArguments):
    page: int = Field(default=0, ge=0, le=MAX_BING_LINK_PAGE)


class _BingBacklinkIntelligenceArguments(_BingPerformanceArguments):
    target_urls: tuple[str, ...] = Field(min_length=1, max_length=MAX_BING_BACKLINK_TARGETS)
    max_pages_per_target: int = Field(default=1, ge=1, le=MAX_BING_LINK_PAGE + 1)


class _BingUrlSubmissionArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    account_id: str = Field(pattern=ACCOUNT_ID_PATTERN)
    site_url: str = Field(min_length=1, max_length=2_048)
    urls: tuple[str, ...] = Field(min_length=1, max_length=MAX_BING_SUBMISSION_URLS)
    timeout_seconds: float = Field(
        default=DEFAULT_PROVIDER_TIMEOUT_SECONDS,
        ge=MIN_PROVIDER_TIMEOUT_SECONDS,
        le=MAX_PROVIDER_TIMEOUT_SECONDS,
    )


class _BingSitemapSubmissionArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    account_id: str = Field(pattern=ACCOUNT_ID_PATTERN)
    site_url: str = Field(min_length=1, max_length=2_048)
    sitemap_url: str = Field(min_length=1, max_length=2_048)
    operation: BingSitemapOperation
    timeout_seconds: float = Field(
        default=DEFAULT_PROVIDER_TIMEOUT_SECONDS,
        ge=MIN_PROVIDER_TIMEOUT_SECONDS,
        le=MAX_PROVIDER_TIMEOUT_SECONDS,
    )


class _BingSiteSubmissionArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    account_id: str = Field(pattern=ACCOUNT_ID_PATTERN)
    site_url: str = Field(min_length=1, max_length=2_048)
    operation: BingSiteOperation
    timeout_seconds: float = Field(
        default=DEFAULT_PROVIDER_TIMEOUT_SECONDS,
        ge=MIN_PROVIDER_TIMEOUT_SECONDS,
        le=MAX_PROVIDER_TIMEOUT_SECONDS,
    )


class _PageSpeedAnalysisArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    account_id: str = Field(pattern=ACCOUNT_ID_PATTERN)
    site_url: str = Field(min_length=1, max_length=2_048)
    page_url: str = Field(min_length=1, max_length=2_048)
    strategy: PageSpeedStrategy = PageSpeedStrategy.DESKTOP
    categories: tuple[PageSpeedCategory, ...] = Field(
        default=(),
        max_length=MAX_PAGESPEED_CATEGORIES,
    )
    timeout_seconds: float = Field(
        default=DEFAULT_PAGESPEED_TIMEOUT_SECONDS,
        ge=MIN_PROVIDER_TIMEOUT_SECONDS,
        le=MAX_PROVIDER_TIMEOUT_SECONDS,
    )


class _LighthouseAuditArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    account_id: str = Field(pattern=ACCOUNT_ID_PATTERN)
    site_url: str = Field(min_length=1, max_length=2_048)
    page_url: str = Field(min_length=1, max_length=2_048)
    timeout_seconds: float = Field(
        default=DEFAULT_LIGHTHOUSE_TIMEOUT_SECONDS,
        ge=MIN_LIGHTHOUSE_TIMEOUT_SECONDS,
        le=MAX_LIGHTHOUSE_TIMEOUT_SECONDS,
    )


class _Ga4PageSpeedCorrelationArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    google_analytics_account_id: str = Field(pattern=ACCOUNT_ID_PATTERN)
    property_id: str = Field(pattern=r"^[0-9]+$")
    pagespeed_account_id: str = Field(pattern=ACCOUNT_ID_PATTERN)
    site_url: str = Field(min_length=1, max_length=2_048)
    page_url: str = Field(min_length=1, max_length=2_048)
    start_date: date
    end_date: date
    strategy: PageSpeedStrategy = PageSpeedStrategy.DESKTOP
    timeout_seconds: float = Field(
        default=DEFAULT_PROVIDER_TIMEOUT_SECONDS,
        ge=MIN_PROVIDER_TIMEOUT_SECONDS,
        le=MAX_PROVIDER_TIMEOUT_SECONDS,
    )


class _Ga4AccountDiscoveryArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    account_id: str = Field(pattern=ACCOUNT_ID_PATTERN)
    timeout_seconds: float = Field(
        default=DEFAULT_PROVIDER_TIMEOUT_SECONDS,
        ge=MIN_PROVIDER_TIMEOUT_SECONDS,
        le=MAX_PROVIDER_TIMEOUT_SECONDS,
    )


class _Ga4SearchConsoleComparisonArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    google_analytics_account_id: str = Field(pattern=ACCOUNT_ID_PATTERN)
    property_id: str = Field(pattern=r"^[0-9]+$")
    google_search_console_account_id: str = Field(pattern=ACCOUNT_ID_PATTERN)
    site_url: str = Field(min_length=1, max_length=2_048)
    start_date: date
    end_date: date
    timeout_seconds: float = Field(
        default=DEFAULT_PROVIDER_TIMEOUT_SECONDS,
        ge=MIN_PROVIDER_TIMEOUT_SECONDS,
        le=MAX_PROVIDER_TIMEOUT_SECONDS,
    )


class _SearchEngineComparisonArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    google_search_console_account_id: str = Field(pattern=ACCOUNT_ID_PATTERN)
    google_search_console_site_url: str = Field(min_length=1, max_length=2_048)
    bing_account_id: str = Field(pattern=ACCOUNT_ID_PATTERN)
    bing_site_url: str = Field(min_length=1, max_length=2_048)
    start_date: date
    end_date: date
    timeout_seconds: float = Field(
        default=DEFAULT_PROVIDER_TIMEOUT_SECONDS,
        ge=MIN_PROVIDER_TIMEOUT_SECONDS,
        le=MAX_PROVIDER_TIMEOUT_SECONDS,
    )


class _SearchEngineTrafficHealthArguments(_SearchEngineComparisonArguments):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _LocalSchemaValidationArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    document: str = Field(min_length=1, max_length=MAX_SCHEMA_LOCAL_DOCUMENT_CHARS)


class _PublicSchemaValidationArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    url: str = Field(min_length=1, max_length=MAX_SCHEMA_FETCH_URL_CHARS)
    timeout_seconds: float = Field(
        default=DEFAULT_PROVIDER_TIMEOUT_SECONDS,
        ge=MIN_PROVIDER_TIMEOUT_SECONDS,
        le=MAX_PROVIDER_TIMEOUT_SECONDS,
    )


def _tool_annotations(annotations: ToolAnnotations) -> types.ToolAnnotations:
    return types.ToolAnnotations(
        readOnlyHint=annotations.read_only_hint,
        destructiveHint=annotations.destructive_hint,
        idempotentHint=annotations.idempotent_hint,
        openWorldHint=annotations.open_world_hint,
    )


def _onboarding_resource_site_url(uri: str) -> str | None:
    """Resolve a supported onboarding URI to its optional site, rejecting anything else."""

    if uri == _ONBOARDING_RESOURCE_URI:
        return None
    if not uri.startswith(_ONBOARDING_SITE_RESOURCE_PREFIX):
        raise RankratError(f"{_UNKNOWN_RESOURCE_CODE}: {uri}")
    encoded_site_url = uri[len(_ONBOARDING_SITE_RESOURCE_PREFIX) :]
    site_url = unquote(encoded_site_url)
    if not site_url:
        raise RankratError(f"{_UNKNOWN_RESOURCE_CODE}: {uri}")
    return site_url


def _tool_input_schema(name: str) -> dict[str, object]:
    schemas: dict[str, dict[str, object]] = {
        "onboarding_guide": _OnboardingGuideArguments.model_json_schema(),
        "google_analytics_data_streams": _Ga4DataStreamsArguments.model_json_schema(),
        "google_analytics_account_rename": _Ga4AccountRenameArguments.model_json_schema(),
        "google_analytics_property_rename": _Ga4PropertyRenameArguments.model_json_schema(),
        "server_info": {"type": _OBJECT_SCHEMA, "properties": {}, "additionalProperties": False},
        "diagnostics": {"type": _OBJECT_SCHEMA, "properties": {}, "additionalProperties": False},
        "accounts_list": {
            "type": _OBJECT_SCHEMA,
            "properties": {
                "provider": {
                    "type": "string",
                    "enum": [item.value for item in Provider],
                }
            },
            "additionalProperties": False,
        },
        "sites_list": {
            "type": _OBJECT_SCHEMA,
            "properties": {
                "account_id": {"type": "string", "minLength": 1, "maxLength": 63},
                "provider": {"type": "string", "enum": [item.value for item in Provider]},
            },
            "additionalProperties": False,
        },
        "provider_readiness": {
            "type": _OBJECT_SCHEMA,
            "properties": {
                "account_id": {
                    "type": "string",
                    "pattern": ACCOUNT_ID_PATTERN,
                },
                "timeout_seconds": {
                    "type": "number",
                    "minimum": MIN_PROVIDER_TIMEOUT_SECONDS,
                    "maximum": MAX_PROVIDER_TIMEOUT_SECONDS,
                    "default": DEFAULT_PROVIDER_TIMEOUT_SECONDS,
                },
            },
            "required": ["account_id"],
            "additionalProperties": False,
        },
        "indexnow_submit": {
            "type": _OBJECT_SCHEMA,
            "properties": {
                "target_id": {"type": "string", "pattern": ACCOUNT_ID_PATTERN},
                "urls": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1},
                    "minItems": 1,
                    "maxItems": MAX_INDEXNOW_URLS,
                },
            },
            "required": ["target_id", "urls"],
            "additionalProperties": False,
        },
        "google_indexing_submit": _GoogleIndexingSubmissionArguments.model_json_schema(),
        "google_indexing_batch_submit": _GoogleIndexingBatchSubmissionArguments.model_json_schema(),
        "google_indexing_metadata": _GoogleIndexingMetadataArguments.model_json_schema(),
        "google_site_submit": _GoogleSiteSubmissionArguments.model_json_schema(),
        "google_sitemap_submit": _GoogleSitemapSubmissionArguments.model_json_schema(),
        "site_onboarding_submit": _SiteOnboardingSubmissionArguments.model_json_schema(),
        "site_ownership_check": _SiteOwnershipCheckArguments.model_json_schema(),
        "site_ownership_verify": _SiteOwnershipVerificationArguments.model_json_schema(),
        "site_audit": _SiteAuditArguments.model_json_schema(),
        "site_remediation_apply": _SiteRemediationArguments.model_json_schema(),
        "google_search_analytics_query": _SearchAnalyticsArguments.model_json_schema(),
        "google_search_analytics_summary": _SearchAnalyticsSummaryArguments.model_json_schema(),
        "google_search_analytics_comparison": (
            _SearchAnalyticsComparisonArguments.model_json_schema()
        ),
        "google_search_analytics_dimension_report": (
            _SearchAnalyticsDimensionReportArguments.model_json_schema()
        ),
        "google_search_analytics_drop_attribution": (
            _SearchAnalyticsDropAttributionArguments.model_json_schema()
        ),
        "google_search_analytics_trend": _SearchAnalyticsSummaryArguments.model_json_schema(),
        "google_search_analytics_anomalies": _SearchAnalyticsSummaryArguments.model_json_schema(),
        "google_search_analytics_page_performance": (
            _SearchAnalyticsPagePerformanceArguments.model_json_schema()
        ),
        "google_sites_list": _GoogleSitesListArguments.model_json_schema(),
        "google_site_get": _GoogleSiteGetArguments.model_json_schema(),
        "google_sitemaps_list": _SitemapListArguments.model_json_schema(),
        "google_sitemap_get": _SitemapGetArguments.model_json_schema(),
        "google_url_inspection": _UrlInspectionArguments.model_json_schema(),
        "google_url_inspection_batch": _UrlInspectionBatchArguments.model_json_schema(),
        GOOGLE_ANALYTICS_ACCOUNT_INVENTORY_OPERATION: (
            _Ga4AccountDiscoveryArguments.model_json_schema()
        ),
        "google_analytics_report": _Ga4ReportArguments.model_json_schema(),
        "google_analytics_realtime_report": _Ga4RealtimeReportArguments.model_json_schema(),
        "google_analytics_content_performance": _Ga4FixedReportArguments.model_json_schema(),
        "google_analytics_landing_page_performance": _Ga4FixedReportArguments.model_json_schema(),
        "google_analytics_organic_search_landing_pages": (
            _Ga4FixedReportArguments.model_json_schema()
        ),
        "google_analytics_traffic_source_performance": _Ga4FixedReportArguments.model_json_schema(),
        "google_analytics_ecommerce_performance": _Ga4FixedReportArguments.model_json_schema(),
        "google_analytics_audience_segments": _Ga4FixedReportArguments.model_json_schema(),
        "google_analytics_user_behavior": _Ga4FixedReportArguments.model_json_schema(),
        "google_analytics_conversion_funnel": _Ga4ConversionFunnelArguments.model_json_schema(),
        "pagespeed_analyze": _PageSpeedAnalysisArguments.model_json_schema(),
        PAGESPEED_CORE_WEB_VITALS_OPERATION: _PageSpeedAnalysisArguments.model_json_schema(),
        LIGHTHOUSE_AUDIT_OPERATION: _LighthouseAuditArguments.model_json_schema(),
        LIGHTHOUSE_SEO_FINDINGS_OPERATION: _LighthouseAuditArguments.model_json_schema(),
        LIGHTHOUSE_ACCESSIBILITY_FINDINGS_OPERATION: (
            _LighthouseAuditArguments.model_json_schema()
        ),
        LIGHTHOUSE_PERFORMANCE_FINDINGS_OPERATION: (_LighthouseAuditArguments.model_json_schema()),
        LIGHTHOUSE_BEST_PRACTICES_FINDINGS_OPERATION: (
            _LighthouseAuditArguments.model_json_schema()
        ),
        GA4_PAGESPEED_CORRELATION_OPERATION: (
            _Ga4PageSpeedCorrelationArguments.model_json_schema()
        ),
        GA4_SEARCH_CONSOLE_COMPARISON_OPERATION: (
            _Ga4SearchConsoleComparisonArguments.model_json_schema()
        ),
        SEARCH_ENGINE_COMPARISON_OPERATION: _SearchEngineComparisonArguments.model_json_schema(),
        SEARCH_ENGINE_TRAFFIC_HEALTH_OPERATION: (
            _SearchEngineTrafficHealthArguments.model_json_schema()
        ),
        "schema_validate_html": _LocalSchemaValidationArguments.model_json_schema(),
        "schema_validate_json_ld": _LocalSchemaValidationArguments.model_json_schema(),
        "schema_validate_url": _PublicSchemaValidationArguments.model_json_schema(),
        "bing_keyword_statistics": _BingKeywordStatisticsArguments.model_json_schema(),
        "bing_related_keywords": _BingRelatedKeywordsArguments.model_json_schema(),
        "bing_traffic_trend": _BingTrafficArguments.model_json_schema(),
        "bing_traffic_anomalies": _BingTrafficArguments.model_json_schema(),
        "bing_traffic_comparison": _BingTrafficComparisonArguments.model_json_schema(),
        "bing_query_performance": _BingPerformanceArguments.model_json_schema(),
        "bing_page_performance": _BingPerformanceArguments.model_json_schema(),
        "bing_brand_analysis": _BingBrandAnalysisArguments.model_json_schema(),
        "bing_ranking_buckets": _BingPerformanceArguments.model_json_schema(),
        "bing_query_opportunities": _BingPerformanceArguments.model_json_schema(),
        "bing_page_opportunities": _BingPerformanceArguments.model_json_schema(),
        BING_OPPORTUNITY_MATRIX_OPERATION: _BingPerformanceArguments.model_json_schema(),
        "bing_query_page_performance": _BingQueryPagePerformanceArguments.model_json_schema(),
        "bing_query_cannibalization": _BingQueryPagePerformanceArguments.model_json_schema(),
        "bing_page_query_performance": _BingPageQueryPerformanceArguments.model_json_schema(),
        "bing_url_submission_quota": _BingPerformanceArguments.model_json_schema(),
        "bing_crawl_issues": _BingPerformanceArguments.model_json_schema(),
        "bing_crawl_stats": _BingPerformanceArguments.model_json_schema(),
        "bing_feeds": _BingPerformanceArguments.model_json_schema(),
        "bing_link_counts": _BingLinkCountsArguments.model_json_schema(),
        "bing_backlink_intelligence": (_BingBacklinkIntelligenceArguments.model_json_schema()),
        "bing_url_information": _BingUrlInformationArguments.model_json_schema(),
        "bing_url_submit": _BingUrlSubmissionArguments.model_json_schema(),
        "bing_sitemap_submit": _BingSitemapSubmissionArguments.model_json_schema(),
        "bing_site_submit": _BingSiteSubmissionArguments.model_json_schema(),
    }
    return schemas[name]


def _tool_error(
    code: str,
    message: str = "MCP tool input was rejected",
) -> types.CallToolResult:
    payload: JsonValue = {"code": code, "message": message}
    return types.CallToolResult(
        content=[
            types.TextContent(
                type="text",
                text=json.dumps(payload, separators=(",", ":")),
            )
        ],
        isError=True,
    )


def _tool_success(result: object) -> list[types.TextContent]:
    payload = to_json_value(result)
    return [types.TextContent(type="text", text=json.dumps(payload, separators=(",", ":")))]


async def _bing_query_page_report(
    services: ApplicationServices,
    arguments: _BingQueryPagePerformanceArguments,
    kind: _BingQueryPageReportKind,
) -> object:
    request = BingQueryPagePerformanceRequest(
        arguments.account_id,
        arguments.site_url,
        arguments.query,
        arguments.timeout_seconds,
    )
    if kind is _BingQueryPageReportKind.PERFORMANCE:
        return await services.bing_webmaster.query_page_performance(request)
    return await services.bing_webmaster.query_cannibalization(request)


async def _bing_site_performance_report(
    services: ApplicationServices,
    arguments: _BingPerformanceArguments | _BingBrandAnalysisArguments,
    kind: _BingSitePerformanceReportKind,
) -> object:
    if kind is _BingSitePerformanceReportKind.BRAND:
        if not isinstance(arguments, _BingBrandAnalysisArguments):
            raise ValueError("Bing brand analysis requires literal brand terms")
        return await services.bing_webmaster.brand_analysis(
            BingBrandAnalysisRequest(
                arguments.account_id,
                arguments.site_url,
                arguments.brand_terms,
                arguments.timeout_seconds,
            )
        )
    request = BingPerformanceRequest(
        arguments.account_id,
        arguments.site_url,
        arguments.timeout_seconds,
    )
    if kind is _BingSitePerformanceReportKind.QUERY:
        return await services.bing_webmaster.query_performance(request)
    if kind is _BingSitePerformanceReportKind.PAGE:
        return await services.bing_webmaster.page_performance(request)
    return await services.bing_webmaster.ranking_buckets(request)


async def _google_analytics_or_pagespeed_tool(
    services: ApplicationServices,
    name: str,
    raw_arguments: dict[str, Any],
) -> list[types.TextContent] | None:
    if name == LIGHTHOUSE_AUDIT_OPERATION:
        lighthouse_arguments = _LighthouseAuditArguments.model_validate(raw_arguments)
        return _tool_success(
            await services.lighthouse.audit(_lighthouse_request(lighthouse_arguments))
        )
    lighthouse_category = _LIGHTHOUSE_CATEGORY_BY_OPERATION.get(name)
    if lighthouse_category is not None:
        lighthouse_arguments = _LighthouseAuditArguments.model_validate(raw_arguments)
        return _tool_success(
            await services.lighthouse.findings(
                _lighthouse_request(lighthouse_arguments),
                lighthouse_category,
            )
        )
    if name == GOOGLE_ANALYTICS_ACCOUNT_INVENTORY_OPERATION:
        account_discovery_arguments = _Ga4AccountDiscoveryArguments.model_validate(raw_arguments)
        return _tool_success(
            await services.google_analytics.list_account_summaries(
                Ga4AccountDiscoveryRequest(
                    account_id=account_discovery_arguments.account_id,
                    timeout_seconds=account_discovery_arguments.timeout_seconds,
                )
            )
        )
    if name == "google_analytics_report":
        ga4_arguments = _Ga4ReportArguments.model_validate(raw_arguments)
        return _tool_success(
            await services.google_analytics.run_report(
                Ga4ReportRequest(
                    account_id=ga4_arguments.account_id,
                    property_id=ga4_arguments.property_id,
                    date_ranges=tuple(
                        Ga4DateRange(item.start_date, item.end_date)
                        for item in ga4_arguments.date_ranges
                    ),
                    dimensions=ga4_arguments.dimensions,
                    metrics=ga4_arguments.metrics,
                    limit=ga4_arguments.limit,
                    offset=ga4_arguments.offset,
                    timeout_seconds=ga4_arguments.timeout_seconds,
                )
            )
        )
    if name == "google_analytics_realtime_report":
        realtime_arguments = _Ga4RealtimeReportArguments.model_validate(raw_arguments)
        return _tool_success(
            await services.google_analytics.run_realtime_report(
                Ga4RealtimeReportRequest(
                    account_id=realtime_arguments.account_id,
                    property_id=realtime_arguments.property_id,
                    dimensions=realtime_arguments.dimensions,
                    metrics=realtime_arguments.metrics,
                    limit=realtime_arguments.limit,
                    timeout_seconds=realtime_arguments.timeout_seconds,
                )
            )
        )
    if name == "google_analytics_conversion_funnel":
        funnel_arguments = _Ga4ConversionFunnelArguments.model_validate(raw_arguments)
        return _tool_success(
            await services.google_analytics.conversion_funnel(
                Ga4ConversionFunnelRequest(
                    account_id=funnel_arguments.account_id,
                    property_id=funnel_arguments.property_id,
                    start_date=funnel_arguments.start_date,
                    end_date=funnel_arguments.end_date,
                    event_names=funnel_arguments.event_names,
                    limit=funnel_arguments.limit,
                    timeout_seconds=funnel_arguments.timeout_seconds,
                )
            )
        )
    fixed_report_kind = _GA4_FIXED_REPORT_TOOL_KINDS.get(name)
    if fixed_report_kind is not None:
        fixed_report_arguments = _Ga4FixedReportArguments.model_validate(raw_arguments)
        return _tool_success(
            await services.google_analytics.fixed_report(
                _fixed_report_request(fixed_report_arguments),
                fixed_report_kind,
            )
        )
    if name == "pagespeed_analyze":
        pagespeed_arguments = _PageSpeedAnalysisArguments.model_validate(raw_arguments)
        return _tool_success(
            await services.pagespeed.analyze(
                PageSpeedAnalysisRequest(
                    account_id=pagespeed_arguments.account_id,
                    site_url=pagespeed_arguments.site_url,
                    page_url=pagespeed_arguments.page_url,
                    strategy=pagespeed_arguments.strategy,
                    categories=pagespeed_arguments.categories,
                    timeout_seconds=pagespeed_arguments.timeout_seconds,
                )
            )
        )
    if name == PAGESPEED_CORE_WEB_VITALS_OPERATION:
        pagespeed_arguments = _PageSpeedAnalysisArguments.model_validate(raw_arguments)
        return _tool_success(
            await services.pagespeed.core_web_vitals(
                PageSpeedAnalysisRequest(
                    account_id=pagespeed_arguments.account_id,
                    site_url=pagespeed_arguments.site_url,
                    page_url=pagespeed_arguments.page_url,
                    strategy=pagespeed_arguments.strategy,
                    categories=pagespeed_arguments.categories,
                    timeout_seconds=pagespeed_arguments.timeout_seconds,
                )
            )
        )
    if name == GA4_PAGESPEED_CORRELATION_OPERATION:
        correlation_arguments = _Ga4PageSpeedCorrelationArguments.model_validate(raw_arguments)
        return _tool_success(
            await services.cross_provider.ga4_pagespeed_correlation(
                Ga4PageSpeedCorrelationRequest(
                    google_analytics_account_id=(correlation_arguments.google_analytics_account_id),
                    property_id=correlation_arguments.property_id,
                    pagespeed_account_id=correlation_arguments.pagespeed_account_id,
                    site_url=correlation_arguments.site_url,
                    page_url=correlation_arguments.page_url,
                    start_date=correlation_arguments.start_date,
                    end_date=correlation_arguments.end_date,
                    strategy=correlation_arguments.strategy,
                    timeout_seconds=correlation_arguments.timeout_seconds,
                )
            )
        )
    if name == GA4_SEARCH_CONSOLE_COMPARISON_OPERATION:
        ga4_search_console_arguments = _Ga4SearchConsoleComparisonArguments.model_validate(
            raw_arguments
        )
        return _tool_success(
            await services.cross_provider.ga4_search_console_comparison(
                Ga4SearchConsoleComparisonRequest(
                    google_analytics_account_id=(
                        ga4_search_console_arguments.google_analytics_account_id
                    ),
                    property_id=ga4_search_console_arguments.property_id,
                    google_search_console_account_id=(
                        ga4_search_console_arguments.google_search_console_account_id
                    ),
                    site_url=ga4_search_console_arguments.site_url,
                    start_date=ga4_search_console_arguments.start_date,
                    end_date=ga4_search_console_arguments.end_date,
                    timeout_seconds=ga4_search_console_arguments.timeout_seconds,
                )
            )
        )
    if name == SEARCH_ENGINE_COMPARISON_OPERATION:
        search_engine_arguments = _SearchEngineComparisonArguments.model_validate(raw_arguments)
        return _tool_success(
            await services.cross_provider.search_engine_comparison(
                SearchEngineComparisonRequest(
                    google_search_console_account_id=(
                        search_engine_arguments.google_search_console_account_id
                    ),
                    google_search_console_site_url=(
                        search_engine_arguments.google_search_console_site_url
                    ),
                    bing_account_id=search_engine_arguments.bing_account_id,
                    bing_site_url=search_engine_arguments.bing_site_url,
                    start_date=search_engine_arguments.start_date,
                    end_date=search_engine_arguments.end_date,
                    timeout_seconds=search_engine_arguments.timeout_seconds,
                )
            )
        )
    if name == SEARCH_ENGINE_TRAFFIC_HEALTH_OPERATION:
        traffic_health_arguments = _SearchEngineTrafficHealthArguments.model_validate(raw_arguments)
        return _tool_success(
            await services.cross_provider.search_engine_traffic_health(
                SearchEngineTrafficHealthRequest(
                    google_search_console_account_id=(
                        traffic_health_arguments.google_search_console_account_id
                    ),
                    google_search_console_site_url=(
                        traffic_health_arguments.google_search_console_site_url
                    ),
                    bing_account_id=traffic_health_arguments.bing_account_id,
                    bing_site_url=traffic_health_arguments.bing_site_url,
                    start_date=traffic_health_arguments.start_date,
                    end_date=traffic_health_arguments.end_date,
                    timeout_seconds=traffic_health_arguments.timeout_seconds,
                )
            )
        )
    return None


def _lighthouse_request(arguments: _LighthouseAuditArguments) -> LighthouseAuditRequest:
    return LighthouseAuditRequest(
        account_id=arguments.account_id,
        site_url=arguments.site_url,
        page_url=arguments.page_url,
        timeout_seconds=arguments.timeout_seconds,
    )


def build_mcp_server(services: ApplicationServices) -> Server[object, object]:
    """Build a server with immutable read operations and enabled write tools."""
    server: Server[object, object] = Server(APP_NAME, version=__version__)

    @server.list_tools()  # type: ignore[misc,no-untyped-call]
    async def list_tools() -> list[types.Tool]:
        established_tools = [
            types.Tool(
                name=contract.name,
                description=contract.description,
                inputSchema=_tool_input_schema(contract.name),
                annotations=_tool_annotations(contract.annotations),
            )
            for contract in tool_catalog(
                services.writes_enabled,
                services.agent_onboarding_enabled,
            )
        ]
        return established_tools + seo_mcp_tools(services.writes_enabled)

    @server.list_resources()  # type: ignore[misc,no-untyped-call]
    async def list_resources() -> list[types.Resource]:
        return [
            types.Resource(
                uri=AnyUrl(_ONBOARDING_RESOURCE_URI),
                name=_ONBOARDING_RESOURCE_NAME,
                description=_ONBOARDING_RESOURCE_DESCRIPTION,
                mimeType=_JSON_MIME_TYPE,
            ),
        ]

    @server.list_resource_templates()  # type: ignore[misc,no-untyped-call]
    async def list_resource_templates() -> list[types.ResourceTemplate]:
        return [
            types.ResourceTemplate(
                uriTemplate=_ONBOARDING_SITE_RESOURCE_TEMPLATE,
                name=_ONBOARDING_SITE_RESOURCE_NAME,
                description=_ONBOARDING_SITE_RESOURCE_DESCRIPTION,
                mimeType=_JSON_MIME_TYPE,
            ),
        ]

    @server.read_resource()  # type: ignore[misc,no-untyped-call]
    async def read_resource(uri: AnyUrl) -> str:
        site_url = _onboarding_resource_site_url(str(uri))
        guide = services.onboarding_guide.render(
            OnboardingGuideRequest(site_url=site_url),
            writes_enabled=services.writes_enabled,
            agent_onboarding_enabled=services.agent_onboarding_enabled,
        )
        return json.dumps(to_json_value(guide), separators=(",", ":"))

    @server.call_tool(validate_input=False)  # type: ignore[misc]
    async def call_tool(
        name: str,
        arguments: dict[str, Any] | None,
    ) -> list[types.TextContent] | types.CallToolResult:
        raw_arguments = arguments or {}
        try:
            seo_result = await dispatch_seo_tool(services, name, raw_arguments)
            if seo_result is not SEO_TOOL_NOT_HANDLED:
                return _tool_success(seo_result)
            analytics_or_pagespeed_result = await _google_analytics_or_pagespeed_tool(
                services,
                name,
                raw_arguments,
            )
            if analytics_or_pagespeed_result is not None:
                return analytics_or_pagespeed_result
            if name == "google_analytics_data_streams":
                streams_arguments = _Ga4DataStreamsArguments.model_validate(raw_arguments)
                return _tool_success(
                    await services.google_analytics_admin.list_data_streams(
                        Ga4DataStreamsRequest(
                            account_id=streams_arguments.account_id,
                            property_id=streams_arguments.property_id,
                            timeout_seconds=streams_arguments.timeout_seconds,
                        ),
                    ),
                )
            if name == "google_analytics_account_rename" and services.writes_enabled:
                account_rename_arguments = _Ga4AccountRenameArguments.model_validate(raw_arguments)
                return _tool_success(
                    await services.google_analytics_admin.rename_account(
                        Ga4AccountRenameRequest(
                            account_id=account_rename_arguments.account_id,
                            analytics_account_id=account_rename_arguments.analytics_account_id,
                            display_name=account_rename_arguments.display_name,
                            timeout_seconds=account_rename_arguments.timeout_seconds,
                        ),
                    ),
                )
            if name == "google_analytics_property_rename" and services.writes_enabled:
                property_rename_arguments = _Ga4PropertyRenameArguments.model_validate(
                    raw_arguments,
                )
                return _tool_success(
                    await services.google_analytics_admin.rename_property(
                        Ga4PropertyRenameRequest(
                            account_id=property_rename_arguments.account_id,
                            property_id=property_rename_arguments.property_id,
                            display_name=property_rename_arguments.display_name,
                            timeout_seconds=property_rename_arguments.timeout_seconds,
                        ),
                    ),
                )
            if name == "onboarding_guide":
                guide_arguments = _OnboardingGuideArguments.model_validate(raw_arguments)
                return _tool_success(
                    services.onboarding_guide.render(
                        OnboardingGuideRequest(site_url=guide_arguments.site_url),
                        writes_enabled=services.writes_enabled,
                        agent_onboarding_enabled=services.agent_onboarding_enabled,
                    ),
                )
            if name == "server_info":
                _NoArguments.model_validate(raw_arguments)
                return _tool_success(services.capabilities.server_info(ServerInfoRequest()))
            if name == "accounts_list":
                accounts_arguments = _AccountsListArguments.model_validate(raw_arguments)
                return _tool_success(
                    services.sites.accounts_list(
                        AccountsListRequest(provider=accounts_arguments.provider)
                    )
                )
            if name == "sites_list":
                sites_arguments = _SitesListArguments.model_validate(raw_arguments)
                return _tool_success(
                    services.sites.sites_list(
                        SitesListRequest(
                            account_id=sites_arguments.account_id,
                            provider=sites_arguments.provider,
                        )
                    )
                )
            if name == "diagnostics":
                _NoArguments.model_validate(raw_arguments)
                return _tool_success(services.diagnostics.diagnostics(DiagnosticsRequest()))
            if name == "provider_readiness":
                readiness_arguments = _ProviderReadinessArguments.model_validate(raw_arguments)
                return _tool_success(
                    await services.provider_readiness.readiness(
                        ProviderReadinessRequest(
                            account_id=readiness_arguments.account_id,
                            timeout_seconds=readiness_arguments.timeout_seconds,
                        )
                    )
                )
            if name == "site_audit" and services.site_audit is not None:
                site_audit_arguments = _SiteAuditArguments.model_validate(raw_arguments)
                return _tool_success(
                    await services.site_audit.audit(
                        SiteAuditRequest(
                            account_id=site_audit_arguments.account_id,
                            site_url=site_audit_arguments.site_url,
                            max_pages=site_audit_arguments.max_pages,
                            max_depth=site_audit_arguments.max_depth,
                            timeout_seconds=site_audit_arguments.timeout_seconds,
                        )
                    )
                )
            if name == "site_ownership_check" and services.site_ownership is not None:
                ownership_arguments = _SiteOwnershipCheckArguments.model_validate(raw_arguments)
                return _tool_success(
                    await services.site_ownership.check(
                        SiteOwnershipCheckRequest(
                            google_account_id=ownership_arguments.google_account_id,
                            bing_account_id=ownership_arguments.bing_account_id,
                            site_url=ownership_arguments.site_url,
                            timeout_seconds=ownership_arguments.timeout_seconds,
                        )
                    )
                )
            if name == "google_search_analytics_query":
                analytics_arguments = _SearchAnalyticsArguments.model_validate(raw_arguments)
                return _tool_success(
                    await services.google_search_console.search_analytics(
                        SearchAnalyticsRequest(
                            account_id=analytics_arguments.account_id,
                            site_url=analytics_arguments.site_url,
                            start_date=analytics_arguments.start_date,
                            end_date=analytics_arguments.end_date,
                            dimensions=analytics_arguments.dimensions,
                            filters=tuple(
                                SearchAnalyticsFilter(
                                    dimension=item.dimension,
                                    operator=item.operator,
                                    expression=item.expression,
                                )
                                for item in analytics_arguments.filters
                            ),
                            search_type=analytics_arguments.search_type,
                            row_limit=analytics_arguments.row_limit,
                            start_row=analytics_arguments.start_row,
                            timeout_seconds=analytics_arguments.timeout_seconds,
                        )
                    )
                )
            if name == "google_search_analytics_summary":
                summary_arguments = _SearchAnalyticsSummaryArguments.model_validate(raw_arguments)
                return _tool_success(
                    await services.google_search_console.search_analytics_summary(
                        _summary_request(summary_arguments)
                    )
                )
            if name == "google_search_analytics_comparison":
                comparison_arguments = _SearchAnalyticsComparisonArguments.model_validate(
                    raw_arguments
                )
                return _tool_success(
                    await services.google_search_console.search_analytics_comparison(
                        SearchAnalyticsComparisonRequest(
                            current=_summary_request(comparison_arguments),
                            previous_start_date=comparison_arguments.previous_start_date,
                            previous_end_date=comparison_arguments.previous_end_date,
                        )
                    )
                )
            if name == "google_search_analytics_dimension_report":
                report_arguments = _SearchAnalyticsDimensionReportArguments.model_validate(
                    raw_arguments
                )
                return _tool_success(
                    await services.google_search_console.search_analytics_dimension_report(
                        SearchAnalyticsDimensionReportRequest(
                            account_id=report_arguments.account_id,
                            site_url=report_arguments.site_url,
                            report=report_arguments.report,
                            start_date=report_arguments.start_date,
                            end_date=report_arguments.end_date,
                            filters=tuple(
                                SearchAnalyticsFilter(
                                    dimension=item.dimension,
                                    operator=item.operator,
                                    expression=item.expression,
                                )
                                for item in report_arguments.filters
                            ),
                            search_type=report_arguments.search_type,
                            row_limit=report_arguments.row_limit,
                            start_row=report_arguments.start_row,
                            timeout_seconds=report_arguments.timeout_seconds,
                        )
                    )
                )
            if name == "google_search_analytics_drop_attribution":
                drop_arguments = _SearchAnalyticsDropAttributionArguments.model_validate(
                    raw_arguments
                )
                return _tool_success(
                    await services.google_search_console.search_analytics_drop_attribution(
                        SearchAnalyticsDropAttributionRequest(
                            account_id=drop_arguments.account_id,
                            site_url=drop_arguments.site_url,
                            attribution=drop_arguments.attribution,
                            current_start_date=drop_arguments.start_date,
                            current_end_date=drop_arguments.end_date,
                            previous_start_date=drop_arguments.previous_start_date,
                            previous_end_date=drop_arguments.previous_end_date,
                            filters=tuple(
                                SearchAnalyticsFilter(
                                    dimension=item.dimension,
                                    operator=item.operator,
                                    expression=item.expression,
                                )
                                for item in drop_arguments.filters
                            ),
                            search_type=drop_arguments.search_type,
                            row_limit=drop_arguments.row_limit,
                            timeout_seconds=drop_arguments.timeout_seconds,
                        )
                    )
                )
            if name == "google_search_analytics_trend":
                trend_arguments = _SearchAnalyticsSummaryArguments.model_validate(raw_arguments)
                return _tool_success(
                    await services.google_search_console.search_analytics_trend(
                        _trend_request(trend_arguments)
                    )
                )
            if name == "google_search_analytics_anomalies":
                anomaly_arguments = _SearchAnalyticsSummaryArguments.model_validate(raw_arguments)
                return _tool_success(
                    await services.google_search_console.search_analytics_anomalies(
                        _trend_request(anomaly_arguments)
                    )
                )
            if name == "google_search_analytics_page_performance":
                page_performance_arguments = (
                    _SearchAnalyticsPagePerformanceArguments.model_validate(raw_arguments)
                )
                return _tool_success(
                    await services.google_search_console.search_analytics_page_performance(
                        SearchAnalyticsPagePerformanceRequest(
                            account_id=page_performance_arguments.account_id,
                            site_url=page_performance_arguments.site_url,
                            start_date=page_performance_arguments.start_date,
                            end_date=page_performance_arguments.end_date,
                            filters=tuple(
                                SearchAnalyticsFilter(
                                    dimension=item.dimension,
                                    operator=item.operator,
                                    expression=item.expression,
                                )
                                for item in page_performance_arguments.filters
                            ),
                            search_type=page_performance_arguments.search_type,
                            row_limit=page_performance_arguments.row_limit,
                            timeout_seconds=page_performance_arguments.timeout_seconds,
                        )
                    )
                )
            if name == "google_sites_list":
                google_sites_list_arguments = _GoogleSitesListArguments.model_validate(
                    raw_arguments
                )
                return _tool_success(
                    await services.google_search_console.list_sites(
                        SiteListRequest(
                            google_sites_list_arguments.account_id,
                            google_sites_list_arguments.timeout_seconds,
                        )
                    )
                )
            if name == "google_site_get":
                google_site_get_arguments = _GoogleSiteGetArguments.model_validate(raw_arguments)
                return _tool_success(
                    await services.google_search_console.get_site(
                        SiteGetRequest(
                            google_site_get_arguments.account_id,
                            google_site_get_arguments.site_url,
                            google_site_get_arguments.timeout_seconds,
                        )
                    )
                )
            if name == "google_sitemaps_list":
                sitemap_arguments = _SitemapListArguments.model_validate(raw_arguments)
                return _tool_success(
                    await services.google_search_console.list_sitemaps(
                        SitemapListRequest(
                            sitemap_arguments.account_id,
                            sitemap_arguments.site_url,
                            sitemap_arguments.timeout_seconds,
                        )
                    )
                )
            if name == "google_sitemap_get":
                sitemap_get_arguments = _SitemapGetArguments.model_validate(raw_arguments)
                return _tool_success(
                    await services.google_search_console.get_sitemap(
                        SitemapGetRequest(
                            sitemap_get_arguments.account_id,
                            sitemap_get_arguments.site_url,
                            sitemap_get_arguments.sitemap_url,
                            sitemap_get_arguments.timeout_seconds,
                        )
                    )
                )
            if name == "google_url_inspection":
                inspection_arguments = _UrlInspectionArguments.model_validate(raw_arguments)
                return _tool_success(
                    await services.google_search_console.inspect_url(
                        UrlInspectionRequest(
                            inspection_arguments.account_id,
                            inspection_arguments.site_url,
                            inspection_arguments.inspection_url,
                            inspection_arguments.timeout_seconds,
                        )
                    )
                )
            if name == "google_url_inspection_batch":
                batch_arguments = _UrlInspectionBatchArguments.model_validate(raw_arguments)
                return _tool_success(
                    await services.google_search_console.inspect_urls(
                        UrlInspectionBatchRequest(
                            account_id=batch_arguments.account_id,
                            site_url=batch_arguments.site_url,
                            inspection_urls=batch_arguments.inspection_urls,
                            timeout_seconds=batch_arguments.timeout_seconds,
                        )
                    )
                )
            if name == "schema_validate_html":
                schema_arguments = _LocalSchemaValidationArguments.model_validate(raw_arguments)
                return _tool_success(
                    services.local_schema.validate_html(
                        LocalSchemaValidationRequest(schema_arguments.document)
                    )
                )
            if name == "schema_validate_json_ld":
                schema_arguments = _LocalSchemaValidationArguments.model_validate(raw_arguments)
                return _tool_success(
                    services.local_schema.validate_json_ld(
                        LocalSchemaValidationRequest(schema_arguments.document)
                    )
                )
            if name == "schema_validate_url":
                public_schema_arguments = _PublicSchemaValidationArguments.model_validate(
                    raw_arguments
                )
                return _tool_success(
                    await services.local_schema.validate_url(
                        PublicSchemaValidationRequest(
                            url=public_schema_arguments.url,
                            timeout_seconds=public_schema_arguments.timeout_seconds,
                        )
                    )
                )
            if name == "bing_keyword_statistics":
                keyword_arguments = _BingKeywordStatisticsArguments.model_validate(raw_arguments)
                return _tool_success(
                    await services.bing_webmaster.keyword_statistics(
                        BingKeywordStatisticsRequest(
                            keyword_arguments.account_id,
                            keyword_arguments.query,
                            keyword_arguments.country,
                            keyword_arguments.language,
                            keyword_arguments.timeout_seconds,
                        )
                    )
                )
            if name == "bing_related_keywords":
                keyword_arguments = _BingRelatedKeywordsArguments.model_validate(raw_arguments)
                return _tool_success(
                    await services.bing_webmaster.related_keywords(
                        BingRelatedKeywordsRequest(
                            keyword_arguments.account_id,
                            keyword_arguments.query,
                            keyword_arguments.start_date,
                            keyword_arguments.end_date,
                            keyword_arguments.country,
                            keyword_arguments.language,
                            keyword_arguments.timeout_seconds,
                        )
                    )
                )
            if name == "bing_traffic_trend":
                traffic_arguments = _BingTrafficArguments.model_validate(raw_arguments)
                return _tool_success(
                    await services.bing_webmaster.traffic_trend(
                        BingTrafficPeriodRequest(
                            traffic_arguments.account_id,
                            traffic_arguments.site_url,
                            traffic_arguments.start_date,
                            traffic_arguments.end_date,
                            traffic_arguments.timeout_seconds,
                        )
                    )
                )
            if name == "bing_traffic_anomalies":
                traffic_arguments = _BingTrafficArguments.model_validate(raw_arguments)
                return _tool_success(
                    await services.bing_webmaster.traffic_anomalies(
                        BingTrafficPeriodRequest(
                            traffic_arguments.account_id,
                            traffic_arguments.site_url,
                            traffic_arguments.start_date,
                            traffic_arguments.end_date,
                            traffic_arguments.timeout_seconds,
                        )
                    )
                )
            if name == "bing_traffic_comparison":
                bing_comparison_arguments = _BingTrafficComparisonArguments.model_validate(
                    raw_arguments
                )
                current = BingTrafficPeriodRequest(
                    bing_comparison_arguments.account_id,
                    bing_comparison_arguments.site_url,
                    bing_comparison_arguments.start_date,
                    bing_comparison_arguments.end_date,
                    bing_comparison_arguments.timeout_seconds,
                )
                return _tool_success(
                    await services.bing_webmaster.traffic_comparison(
                        BingTrafficComparisonRequest(
                            current,
                            bing_comparison_arguments.previous_start_date,
                            bing_comparison_arguments.previous_end_date,
                        )
                    )
                )
            site_performance_report_kind = _BING_SITE_PERFORMANCE_REPORT_TOOL_KINDS.get(name)
            if site_performance_report_kind is not None:
                site_performance_arguments: _BingPerformanceArguments | _BingBrandAnalysisArguments
                if site_performance_report_kind is _BingSitePerformanceReportKind.BRAND:
                    site_performance_arguments = _BingBrandAnalysisArguments.model_validate(
                        raw_arguments
                    )
                else:
                    site_performance_arguments = _BingPerformanceArguments.model_validate(
                        raw_arguments
                    )
                return _tool_success(
                    await _bing_site_performance_report(
                        services,
                        site_performance_arguments,
                        site_performance_report_kind,
                    )
                )
            if name == "bing_query_opportunities":
                performance_arguments = _BingPerformanceArguments.model_validate(raw_arguments)
                return _tool_success(
                    await services.bing_webmaster.query_opportunities(
                        BingPerformanceRequest(
                            performance_arguments.account_id,
                            performance_arguments.site_url,
                            performance_arguments.timeout_seconds,
                        )
                    )
                )
            if name == "bing_page_opportunities":
                performance_arguments = _BingPerformanceArguments.model_validate(raw_arguments)
                return _tool_success(
                    await services.bing_webmaster.page_opportunities(
                        BingPerformanceRequest(
                            performance_arguments.account_id,
                            performance_arguments.site_url,
                            performance_arguments.timeout_seconds,
                        )
                    )
                )
            if name == BING_OPPORTUNITY_MATRIX_OPERATION:
                performance_arguments = _BingPerformanceArguments.model_validate(raw_arguments)
                return _tool_success(
                    await services.bing_webmaster.opportunity_matrix(
                        BingPerformanceRequest(
                            performance_arguments.account_id,
                            performance_arguments.site_url,
                            performance_arguments.timeout_seconds,
                        )
                    )
                )
            query_page_report_kind = _BING_QUERY_PAGE_REPORT_TOOL_KINDS.get(name)
            if query_page_report_kind is not None:
                query_page_arguments = _BingQueryPagePerformanceArguments.model_validate(
                    raw_arguments
                )
                return _tool_success(
                    await _bing_query_page_report(
                        services,
                        query_page_arguments,
                        query_page_report_kind,
                    )
                )
            if name == "bing_page_query_performance":
                page_query_arguments = _BingPageQueryPerformanceArguments.model_validate(
                    raw_arguments
                )
                return _tool_success(
                    await services.bing_webmaster.page_query_performance(
                        BingPageQueryPerformanceRequest(
                            page_query_arguments.account_id,
                            page_query_arguments.site_url,
                            page_query_arguments.page_url,
                            page_query_arguments.timeout_seconds,
                        )
                    )
                )
            if name == "bing_url_submission_quota":
                quota_arguments = _BingPerformanceArguments.model_validate(raw_arguments)
                return _tool_success(
                    await services.bing_webmaster.url_submission_quota(
                        BingUrlSubmissionQuotaRequest(
                            quota_arguments.account_id,
                            quota_arguments.site_url,
                            quota_arguments.timeout_seconds,
                        )
                    )
                )
            if name == "bing_crawl_issues":
                crawl_arguments = _BingPerformanceArguments.model_validate(raw_arguments)
                return _tool_success(
                    await services.bing_webmaster.crawl_issues(
                        BingCrawlIssuesRequest(
                            crawl_arguments.account_id,
                            crawl_arguments.site_url,
                            crawl_arguments.timeout_seconds,
                        )
                    )
                )
            if name == "bing_crawl_stats":
                crawl_arguments = _BingPerformanceArguments.model_validate(raw_arguments)
                return _tool_success(
                    await services.bing_webmaster.crawl_stats(
                        BingCrawlStatsRequest(
                            crawl_arguments.account_id,
                            crawl_arguments.site_url,
                            crawl_arguments.timeout_seconds,
                        )
                    )
                )
            if name == "bing_feeds":
                feed_arguments = _BingPerformanceArguments.model_validate(raw_arguments)
                return _tool_success(
                    await services.bing_webmaster.feeds(
                        BingFeedsRequest(
                            feed_arguments.account_id,
                            feed_arguments.site_url,
                            feed_arguments.timeout_seconds,
                        )
                    )
                )
            if name == "bing_link_counts":
                link_arguments = _BingLinkCountsArguments.model_validate(raw_arguments)
                return _tool_success(
                    await services.bing_webmaster.link_counts(
                        BingLinkCountsRequest(
                            account_id=link_arguments.account_id,
                            site_url=link_arguments.site_url,
                            page=link_arguments.page,
                            timeout_seconds=link_arguments.timeout_seconds,
                        )
                    )
                )
            if name == "bing_backlink_intelligence":
                backlink_arguments = _BingBacklinkIntelligenceArguments.model_validate(
                    raw_arguments
                )
                return _tool_success(
                    await services.bing_webmaster.backlink_intelligence(
                        BingBacklinkIntelligenceRequest(
                            account_id=backlink_arguments.account_id,
                            site_url=backlink_arguments.site_url,
                            target_urls=backlink_arguments.target_urls,
                            max_pages_per_target=backlink_arguments.max_pages_per_target,
                            timeout_seconds=backlink_arguments.timeout_seconds,
                        )
                    )
                )
            if name == "bing_url_information":
                information_arguments = _BingUrlInformationArguments.model_validate(raw_arguments)
                return _tool_success(
                    await services.bing_webmaster.url_information(
                        BingUrlInformationRequest(
                            account_id=information_arguments.account_id,
                            site_url=information_arguments.site_url,
                            page_url=information_arguments.page_url,
                            timeout_seconds=information_arguments.timeout_seconds,
                        )
                    )
                )
            if name == "bing_url_submit" and services.writes_enabled:
                submission_arguments = _BingUrlSubmissionArguments.model_validate(raw_arguments)
                return _tool_success(
                    await services.bing_webmaster.submit_url_batch(
                        BingUrlSubmissionRequest(
                            account_id=submission_arguments.account_id,
                            site_url=submission_arguments.site_url,
                            urls=submission_arguments.urls,
                            timeout_seconds=submission_arguments.timeout_seconds,
                        )
                    )
                )
            if name == "bing_sitemap_submit" and services.writes_enabled:
                sitemap_submission_arguments = _BingSitemapSubmissionArguments.model_validate(
                    raw_arguments
                )
                return _tool_success(
                    await services.bing_webmaster.submit_sitemap(
                        BingSitemapSubmissionRequest(
                            account_id=sitemap_submission_arguments.account_id,
                            site_url=sitemap_submission_arguments.site_url,
                            sitemap_url=sitemap_submission_arguments.sitemap_url,
                            operation=sitemap_submission_arguments.operation,
                            timeout_seconds=sitemap_submission_arguments.timeout_seconds,
                        )
                    )
                )
            if name == "bing_site_submit" and services.writes_enabled:
                bing_site_submission_arguments = _BingSiteSubmissionArguments.model_validate(
                    raw_arguments
                )
                return _tool_success(
                    await services.bing_webmaster.submit_site(
                        BingSiteSubmissionRequest(
                            account_id=bing_site_submission_arguments.account_id,
                            site_url=bing_site_submission_arguments.site_url,
                            operation=bing_site_submission_arguments.operation,
                            timeout_seconds=bing_site_submission_arguments.timeout_seconds,
                        )
                    )
                )
            if (
                name == "indexnow_submit"
                and services.writes_enabled
                and services.indexnow is not None
            ):
                indexnow_arguments = _IndexNowSubmissionArguments.model_validate(raw_arguments)
                return _tool_success(
                    await services.indexnow.submit(
                        IndexNowSubmissionRequest(
                            target_id=indexnow_arguments.target_id,
                            urls=indexnow_arguments.urls,
                        )
                    )
                )
            if (
                name == "google_indexing_submit"
                and services.writes_enabled
                and services.google_indexing is not None
            ):
                indexing_arguments = _GoogleIndexingSubmissionArguments.model_validate(
                    raw_arguments
                )
                return _tool_success(
                    await services.google_indexing.submit(
                        GoogleIndexingSubmissionRequest(
                            account_id=indexing_arguments.account_id,
                            site_url=indexing_arguments.site_url,
                            url=indexing_arguments.url,
                            notification_type=indexing_arguments.notification_type,
                            timeout_seconds=indexing_arguments.timeout_seconds,
                        )
                    )
                )
            if (
                name == "google_indexing_batch_submit"
                and services.writes_enabled
                and services.google_indexing is not None
            ):
                google_indexing_batch_arguments = (
                    _GoogleIndexingBatchSubmissionArguments.model_validate(raw_arguments)
                )
                return _tool_success(
                    await services.google_indexing.submit_batch(
                        GoogleIndexingBatchSubmissionRequest(
                            account_id=google_indexing_batch_arguments.account_id,
                            site_url=google_indexing_batch_arguments.site_url,
                            notifications=tuple(
                                GoogleIndexingBatchNotification(
                                    url=notification.url,
                                    notification_type=notification.notification_type,
                                )
                                for notification in google_indexing_batch_arguments.notifications
                            ),
                            timeout_seconds=google_indexing_batch_arguments.timeout_seconds,
                        )
                    )
                )
            if name == "google_indexing_metadata":
                metadata_arguments = _GoogleIndexingMetadataArguments.model_validate(raw_arguments)
                return _tool_success(
                    await services.google_indexing_metadata.metadata(
                        GoogleIndexingMetadataRequest(
                            account_id=metadata_arguments.account_id,
                            site_url=metadata_arguments.site_url,
                            url=metadata_arguments.url,
                            timeout_seconds=metadata_arguments.timeout_seconds,
                        )
                    )
                )
            if (
                name == "google_site_submit"
                and services.writes_enabled
                and services.google_sites is not None
            ):
                google_site_submission_arguments = _GoogleSiteSubmissionArguments.model_validate(
                    raw_arguments
                )
                return _tool_success(
                    await services.google_sites.submit(
                        GoogleSiteSubmissionRequest(
                            account_id=google_site_submission_arguments.account_id,
                            site_url=google_site_submission_arguments.site_url,
                            operation=google_site_submission_arguments.operation,
                            timeout_seconds=google_site_submission_arguments.timeout_seconds,
                        )
                    )
                )
            if (
                name == "google_sitemap_submit"
                and services.writes_enabled
                and services.google_sitemaps is not None
            ):
                google_sitemap_submission_arguments = (
                    _GoogleSitemapSubmissionArguments.model_validate(raw_arguments)
                )
                return _tool_success(
                    await services.google_sitemaps.submit(
                        GoogleSitemapSubmissionRequest(
                            account_id=google_sitemap_submission_arguments.account_id,
                            site_url=google_sitemap_submission_arguments.site_url,
                            sitemap_url=google_sitemap_submission_arguments.sitemap_url,
                            operation=google_sitemap_submission_arguments.operation,
                            timeout_seconds=google_sitemap_submission_arguments.timeout_seconds,
                        )
                    )
                )
            if (
                name == "site_onboarding_submit"
                and services.writes_enabled
                and services.site_onboarding is not None
            ):
                site_onboarding_arguments = _SiteOnboardingSubmissionArguments.model_validate(
                    raw_arguments
                )
                return _tool_success(
                    await services.site_onboarding.submit(
                        SiteOnboardingSubmissionRequest(
                            google_account_id=site_onboarding_arguments.google_account_id,
                            bing_account_id=site_onboarding_arguments.bing_account_id,
                            site_url=site_onboarding_arguments.site_url,
                            google_analytics_parent_account_id=(
                                site_onboarding_arguments.google_analytics_parent_account_id
                            ),
                            display_name=site_onboarding_arguments.display_name,
                            time_zone=site_onboarding_arguments.time_zone,
                            currency_code=site_onboarding_arguments.currency_code,
                            timeout_seconds=site_onboarding_arguments.timeout_seconds,
                        )
                    )
                )
            if (
                name == "site_ownership_verify"
                and services.writes_enabled
                and services.site_ownership is not None
            ):
                ownership_arguments = _SiteOwnershipVerificationArguments.model_validate(
                    raw_arguments
                )
                return _tool_success(
                    await services.site_ownership.verify(
                        SiteOwnershipVerificationRequest(
                            google_account_id=ownership_arguments.google_account_id,
                            bing_account_id=ownership_arguments.bing_account_id,
                            dns_account_id=ownership_arguments.dns_account_id,
                            site_url=ownership_arguments.site_url,
                            timeout_seconds=ownership_arguments.timeout_seconds,
                        )
                    )
                )
            if (
                name == "site_remediation_apply"
                and services.writes_enabled
                and services.site_remediation is not None
            ):
                remediation_arguments = _SiteRemediationArguments.model_validate(raw_arguments)
                return _tool_success(
                    await services.site_remediation.apply(
                        SiteRemediationRequest(
                            google_account_id=remediation_arguments.google_account_id,
                            google_site_url=remediation_arguments.google_site_url,
                            bing_account_id=remediation_arguments.bing_account_id,
                            bing_site_url=remediation_arguments.bing_site_url,
                            sitemap_url=remediation_arguments.sitemap_url,
                            changed_urls=remediation_arguments.changed_urls,
                            timeout_seconds=remediation_arguments.timeout_seconds,
                        )
                    )
                )
        except ValidationError:
            return _tool_error(_TOOL_ERROR_CODE)
        except ProviderOperationError as error:
            return _tool_error(
                error.code.value,
                PROVIDER_OPERATION_FAILED_MESSAGE,
            )
        except RankratError:
            return _tool_error(
                _TOOL_REQUEST_REJECTED_CODE,
                "MCP tool request was rejected",
            )
        return _tool_error(_UNKNOWN_TOOL_CODE)

    return server
