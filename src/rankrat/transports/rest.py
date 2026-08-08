"""Versioned REST routes backed by the same read-only application services."""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict, Field

from rankrat.constants import (
    API_PREFIX,
    BING_OPPORTUNITY_MATRIX_OPERATION,
    BING_OPPORTUNITY_MATRIX_PATH,
    DEFAULT_LIGHTHOUSE_TIMEOUT_SECONDS,
    DEFAULT_PAGESPEED_TIMEOUT_SECONDS,
    DEFAULT_PROVIDER_TIMEOUT_SECONDS,
    DEFAULT_SITE_AUDIT_DEPTH,
    DEFAULT_SITE_AUDIT_PAGES,
    GA4_PAGESPEED_CORRELATION_OPERATION,
    GA4_PAGESPEED_CORRELATION_PATH,
    GA4_SEARCH_CONSOLE_COMPARISON_OPERATION,
    GA4_SEARCH_CONSOLE_COMPARISON_PATH,
    GOOGLE_ANALYTICS_ACCOUNT_INVENTORY_OPERATION,
    GOOGLE_ANALYTICS_ACCOUNT_INVENTORY_PATH,
    GOOGLE_ANALYTICS_ACCOUNT_RENAME_OPERATION,
    GOOGLE_ANALYTICS_ACCOUNT_RENAME_PATH,
    GOOGLE_ANALYTICS_DATA_STREAMS_OPERATION,
    GOOGLE_ANALYTICS_DATA_STREAMS_PATH,
    GOOGLE_ANALYTICS_PROPERTY_RENAME_OPERATION,
    GOOGLE_ANALYTICS_PROPERTY_RENAME_PATH,
    ISO_CURRENCY_CODE_CHARS,
    LIGHTHOUSE_ACCESSIBILITY_FINDINGS_OPERATION,
    LIGHTHOUSE_ACCESSIBILITY_FINDINGS_PATH,
    LIGHTHOUSE_AUDIT_OPERATION,
    LIGHTHOUSE_AUDIT_PATH,
    LIGHTHOUSE_BEST_PRACTICES_FINDINGS_OPERATION,
    LIGHTHOUSE_BEST_PRACTICES_FINDINGS_PATH,
    LIGHTHOUSE_PERFORMANCE_FINDINGS_OPERATION,
    LIGHTHOUSE_PERFORMANCE_FINDINGS_PATH,
    LIGHTHOUSE_SEO_FINDINGS_OPERATION,
    LIGHTHOUSE_SEO_FINDINGS_PATH,
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
    MAX_LIGHTHOUSE_CATEGORIES,
    MAX_LIGHTHOUSE_DISPLAY_VALUE_CHARS,
    MAX_LIGHTHOUSE_FINDINGS,
    MAX_LIGHTHOUSE_ID_CHARS,
    MAX_LIGHTHOUSE_TEXT_CHARS,
    MAX_LIGHTHOUSE_TIMEOUT_SECONDS,
    MAX_LIGHTHOUSE_TITLE_CHARS,
    MAX_LIGHTHOUSE_URL_CHARS,
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
    ONBOARDING_GUIDE_OPERATION,
    ONBOARDING_GUIDE_PATH,
    PAGESPEED_CORE_WEB_VITALS_OPERATION,
    PAGESPEED_CORE_WEB_VITALS_PATH,
    SEARCH_ENGINE_COMPARISON_OPERATION,
    SEARCH_ENGINE_COMPARISON_PATH,
    SEARCH_ENGINE_TRAFFIC_HEALTH_OPERATION,
    SEARCH_ENGINE_TRAFFIC_HEALTH_PATH,
)
from rankrat.models.boundaries import ACCOUNT_ID_PATTERN, Provider
from rankrat.models.common import JsonValue, to_json_value
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
from rankrat.services.google_analytics import (
    Ga4AccountDiscoveryRequest,
    Ga4ConversionFunnelRequest,
    Ga4DateRange,
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
from rankrat.services.google_sites import (
    GoogleSiteOperation,
    GoogleSiteSubmissionRequest,
)
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
from rankrat.transports.seo_rest import build_seo_router


class _IndexNowSubmissionBody(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    target_id: str = Field(pattern=ACCOUNT_ID_PATTERN)
    urls: tuple[str, ...] = Field(min_length=1, max_length=MAX_INDEXNOW_URLS)


class _GoogleIndexingSubmissionBody(BaseModel):
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


class _GoogleIndexingBatchNotificationBody(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    url: str = Field(min_length=1, max_length=2_048)
    notification_type: GoogleIndexingNotificationType


class _GoogleIndexingBatchSubmissionBody(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    account_id: str = Field(pattern=ACCOUNT_ID_PATTERN)
    site_url: str = Field(min_length=1, max_length=2_048)
    notifications: tuple[_GoogleIndexingBatchNotificationBody, ...] = Field(
        min_length=1,
        max_length=MAX_GOOGLE_INDEXING_BATCH,
    )

    timeout_seconds: float = Field(
        default=DEFAULT_PROVIDER_TIMEOUT_SECONDS,
        ge=MIN_PROVIDER_TIMEOUT_SECONDS,
        le=MAX_PROVIDER_TIMEOUT_SECONDS,
    )


class _GoogleIndexingMetadataBody(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    account_id: str = Field(pattern=ACCOUNT_ID_PATTERN)
    site_url: str = Field(min_length=1, max_length=2_048)
    url: str = Field(min_length=1, max_length=2_048)
    timeout_seconds: float = Field(
        default=DEFAULT_PROVIDER_TIMEOUT_SECONDS,
        ge=MIN_PROVIDER_TIMEOUT_SECONDS,
        le=MAX_PROVIDER_TIMEOUT_SECONDS,
    )


class _GoogleSitemapSubmissionBody(BaseModel):
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


class _GoogleSiteSubmissionBody(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    account_id: str = Field(pattern=ACCOUNT_ID_PATTERN)
    site_url: str = Field(min_length=1, max_length=2_048)
    operation: GoogleSiteOperation

    timeout_seconds: float = Field(
        default=DEFAULT_PROVIDER_TIMEOUT_SECONDS,
        ge=MIN_PROVIDER_TIMEOUT_SECONDS,
        le=MAX_PROVIDER_TIMEOUT_SECONDS,
    )


class _SiteOnboardingSubmissionBody(BaseModel):
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


class _SearchAnalyticsFilterBody(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    dimension: SearchAnalyticsDimension
    operator: SearchAnalyticsFilterOperator
    expression: str = Field(min_length=1, max_length=4_096)


class _SearchAnalyticsBody(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    account_id: str = Field(pattern=ACCOUNT_ID_PATTERN)
    site_url: str = Field(min_length=1, max_length=2_048)
    start_date: date
    end_date: date
    dimensions: tuple[SearchAnalyticsDimension, ...] = Field(max_length=MAX_ANALYTICS_DIMENSIONS)
    filters: tuple[_SearchAnalyticsFilterBody, ...] = Field(
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


class _SearchAnalyticsSummaryBody(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    account_id: str = Field(pattern=ACCOUNT_ID_PATTERN)
    site_url: str = Field(min_length=1, max_length=2_048)
    start_date: date
    end_date: date
    filters: tuple[_SearchAnalyticsFilterBody, ...] = Field(
        default=(),
        max_length=MAX_ANALYTICS_FILTERS,
    )
    search_type: SearchAnalyticsType = SearchAnalyticsType.WEB
    timeout_seconds: float = Field(
        default=DEFAULT_PROVIDER_TIMEOUT_SECONDS,
        ge=MIN_PROVIDER_TIMEOUT_SECONDS,
        le=MAX_PROVIDER_TIMEOUT_SECONDS,
    )


class _SearchAnalyticsComparisonBody(_SearchAnalyticsSummaryBody):
    previous_start_date: date
    previous_end_date: date


class _SearchAnalyticsDimensionReportBody(_SearchAnalyticsSummaryBody):
    report: SearchAnalyticsDimensionReportKind
    row_limit: int = Field(default=1_000, ge=1, le=1_000)
    start_row: int = Field(default=0, ge=0, le=100_000)


class _SearchAnalyticsDropAttributionBody(_SearchAnalyticsSummaryBody):
    attribution: SearchAnalyticsDropAttributionKind
    previous_start_date: date
    previous_end_date: date
    row_limit: int = Field(default=MAX_SEARCH_ANALYTICS_DERIVED_ROWS, ge=1, le=500)


class _SearchAnalyticsPagePerformanceBody(_SearchAnalyticsSummaryBody):
    row_limit: int = Field(default=MAX_SEARCH_ANALYTICS_DERIVED_ROWS, ge=1, le=500)


class _UrlInspectionBody(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    account_id: str = Field(pattern=ACCOUNT_ID_PATTERN)
    site_url: str = Field(min_length=1, max_length=2_048)
    inspection_url: str = Field(min_length=1, max_length=2_048)
    timeout_seconds: float = Field(
        default=DEFAULT_PROVIDER_TIMEOUT_SECONDS,
        ge=MIN_PROVIDER_TIMEOUT_SECONDS,
        le=MAX_PROVIDER_TIMEOUT_SECONDS,
    )


class _UrlInspectionBatchBody(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    account_id: str = Field(pattern=ACCOUNT_ID_PATTERN)
    site_url: str = Field(min_length=1, max_length=2_048)
    inspection_urls: tuple[str, ...] = Field(
        min_length=1,
        max_length=MAX_URL_INSPECTION_BATCH,
    )
    timeout_seconds: float = Field(
        default=DEFAULT_PROVIDER_TIMEOUT_SECONDS,
        ge=MIN_PROVIDER_TIMEOUT_SECONDS,
        le=MAX_PROVIDER_TIMEOUT_SECONDS,
    )


class _Ga4DateRangeBody(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    start_date: date
    end_date: date


class _OnboardingGuideBody(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    site_url: str | None = Field(default=None, min_length=1, max_length=2048)


class _Ga4DataStreamsBody(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    account_id: str = Field(pattern=ACCOUNT_ID_PATTERN)
    property_id: str = Field(pattern=r"^[0-9]+$")
    timeout_seconds: float = Field(
        default=DEFAULT_PROVIDER_TIMEOUT_SECONDS,
        ge=MIN_PROVIDER_TIMEOUT_SECONDS,
        le=MAX_PROVIDER_TIMEOUT_SECONDS,
    )


class _Ga4AccountRenameBody(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    account_id: str = Field(pattern=ACCOUNT_ID_PATTERN)
    analytics_account_id: str = Field(pattern=r"^[0-9]+$")
    display_name: str = Field(min_length=1, max_length=255)
    timeout_seconds: float = Field(
        default=DEFAULT_PROVIDER_TIMEOUT_SECONDS,
        ge=MIN_PROVIDER_TIMEOUT_SECONDS,
        le=MAX_PROVIDER_TIMEOUT_SECONDS,
    )


class _Ga4PropertyRenameBody(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    account_id: str = Field(pattern=ACCOUNT_ID_PATTERN)
    property_id: str = Field(pattern=r"^[0-9]+$")
    display_name: str = Field(min_length=1, max_length=255)
    timeout_seconds: float = Field(
        default=DEFAULT_PROVIDER_TIMEOUT_SECONDS,
        ge=MIN_PROVIDER_TIMEOUT_SECONDS,
        le=MAX_PROVIDER_TIMEOUT_SECONDS,
    )


class _Ga4AccountDiscoveryBody(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    account_id: str = Field(pattern=ACCOUNT_ID_PATTERN)
    timeout_seconds: float = Field(
        default=DEFAULT_PROVIDER_TIMEOUT_SECONDS,
        ge=MIN_PROVIDER_TIMEOUT_SECONDS,
        le=MAX_PROVIDER_TIMEOUT_SECONDS,
    )


class _Ga4ReportBody(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    account_id: str = Field(pattern=ACCOUNT_ID_PATTERN)
    property_id: str = Field(pattern=r"^[0-9]+$")
    date_ranges: tuple[_Ga4DateRangeBody, ...] = Field(min_length=1, max_length=MAX_GA4_DATE_RANGES)
    dimensions: tuple[str, ...] = Field(
        min_length=1,
        max_length=MAX_GA4_DIMENSIONS,
    )
    metrics: tuple[str, ...] = Field(
        min_length=1,
        max_length=MAX_GA4_METRICS,
    )
    limit: int = Field(default=MAX_GA4_ROWS, ge=1, le=MAX_GA4_ROWS)
    offset: int = Field(default=0, ge=0, le=MAX_GA4_OFFSET)
    timeout_seconds: float = Field(
        default=DEFAULT_PROVIDER_TIMEOUT_SECONDS,
        ge=MIN_PROVIDER_TIMEOUT_SECONDS,
        le=MAX_PROVIDER_TIMEOUT_SECONDS,
    )


class _Ga4RealtimeReportBody(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    account_id: str = Field(pattern=ACCOUNT_ID_PATTERN)
    property_id: str = Field(pattern=r"^[0-9]+$")
    dimensions: tuple[str, ...] = Field(
        min_length=1,
        max_length=MAX_GA4_DIMENSIONS,
    )
    metrics: tuple[str, ...] = Field(
        min_length=1,
        max_length=MAX_GA4_METRICS,
    )
    limit: int = Field(default=MAX_GA4_ROWS, ge=1, le=MAX_GA4_ROWS)
    timeout_seconds: float = Field(
        default=DEFAULT_PROVIDER_TIMEOUT_SECONDS,
        ge=MIN_PROVIDER_TIMEOUT_SECONDS,
        le=MAX_PROVIDER_TIMEOUT_SECONDS,
    )


class _Ga4FixedReportBody(BaseModel):
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


class _Ga4ConversionFunnelBody(BaseModel):
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


class _BingKeywordStatisticsBody(BaseModel):
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


class _BingRelatedKeywordsBody(_BingKeywordStatisticsBody):
    start_date: date
    end_date: date


class _BingTrafficBody(BaseModel):
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


class _BingTrafficComparisonBody(_BingTrafficBody):
    previous_start_date: date
    previous_end_date: date


class _BingPerformanceBody(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    account_id: str = Field(pattern=ACCOUNT_ID_PATTERN)
    site_url: str = Field(min_length=1, max_length=2_048)
    timeout_seconds: float = Field(
        default=DEFAULT_PROVIDER_TIMEOUT_SECONDS,
        ge=MIN_PROVIDER_TIMEOUT_SECONDS,
        le=MAX_PROVIDER_TIMEOUT_SECONDS,
    )


class _BingBrandAnalysisBody(_BingPerformanceBody):
    brand_terms: tuple[str, ...] = Field(min_length=1, max_length=MAX_BING_BRAND_TERMS)


class _BingQueryPagePerformanceBody(_BingPerformanceBody):
    query: str = Field(min_length=1, max_length=MAX_BING_QUERY_CHARS)


class _BingPageQueryPerformanceBody(_BingPerformanceBody):
    page_url: str = Field(min_length=1, max_length=2_048)


class _BingUrlInformationBody(_BingPerformanceBody):
    page_url: str = Field(min_length=1, max_length=2_048)


class _BingLinkCountsBody(_BingPerformanceBody):
    page: int = Field(default=0, ge=0, le=MAX_BING_LINK_PAGE)


class _BingUrlSubmissionBody(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    account_id: str = Field(pattern=ACCOUNT_ID_PATTERN)
    site_url: str = Field(min_length=1, max_length=2_048)
    urls: tuple[str, ...] = Field(min_length=1, max_length=MAX_BING_SUBMISSION_URLS)

    timeout_seconds: float = Field(
        default=DEFAULT_PROVIDER_TIMEOUT_SECONDS,
        ge=MIN_PROVIDER_TIMEOUT_SECONDS,
        le=MAX_PROVIDER_TIMEOUT_SECONDS,
    )


class _BingSitemapSubmissionBody(BaseModel):
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


class _BingSiteSubmissionBody(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    account_id: str = Field(pattern=ACCOUNT_ID_PATTERN)
    site_url: str = Field(min_length=1, max_length=2_048)
    operation: BingSiteOperation

    timeout_seconds: float = Field(
        default=DEFAULT_PROVIDER_TIMEOUT_SECONDS,
        ge=MIN_PROVIDER_TIMEOUT_SECONDS,
        le=MAX_PROVIDER_TIMEOUT_SECONDS,
    )


class _PageSpeedAnalysisBody(BaseModel):
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


class _LighthouseAuditBody(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    account_id: str = Field(pattern=ACCOUNT_ID_PATTERN)
    site_url: str = Field(min_length=1, max_length=2_048)
    page_url: str = Field(min_length=1, max_length=2_048)
    timeout_seconds: float = Field(
        default=DEFAULT_LIGHTHOUSE_TIMEOUT_SECONDS,
        ge=MIN_LIGHTHOUSE_TIMEOUT_SECONDS,
        le=MAX_LIGHTHOUSE_TIMEOUT_SECONDS,
    )


class LighthouseCategoryScore(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    category: LighthouseCategory
    score: float | None = Field(ge=0, le=1)


class LighthouseFinding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1, max_length=MAX_LIGHTHOUSE_ID_CHARS)
    categories: tuple[LighthouseCategory, ...] = Field(
        min_length=1,
        max_length=MAX_LIGHTHOUSE_CATEGORIES,
        json_schema_extra={"uniqueItems": True},
    )
    score: float | None = Field(ge=0, le=1)
    score_display_mode: str = Field(min_length=1, max_length=MAX_LIGHTHOUSE_ID_CHARS)
    title: str = Field(min_length=1, max_length=MAX_LIGHTHOUSE_TITLE_CHARS)
    description: str = Field(max_length=MAX_LIGHTHOUSE_TEXT_CHARS)
    display_value: str | None = Field(
        max_length=MAX_LIGHTHOUSE_DISPLAY_VALUE_CHARS,
    )
    numeric_value: float | None
    numeric_unit: str | None = Field(max_length=MAX_LIGHTHOUSE_ID_CHARS)


class LighthouseAuditReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    requested_url: str = Field(
        max_length=MAX_LIGHTHOUSE_URL_CHARS,
        json_schema_extra={"format": "uri"},
    )
    final_url: str = Field(
        max_length=MAX_LIGHTHOUSE_URL_CHARS,
        json_schema_extra={"format": "uri"},
    )
    fetch_time: str = Field(
        max_length=MAX_LIGHTHOUSE_ID_CHARS,
        json_schema_extra={"format": "date-time"},
    )
    lighthouse_version: str = Field(min_length=1, max_length=MAX_LIGHTHOUSE_ID_CHARS)
    categories: tuple[LighthouseCategoryScore, ...] = Field(
        min_length=1,
        max_length=MAX_LIGHTHOUSE_CATEGORIES,
        json_schema_extra={"uniqueItems": True},
    )
    findings: tuple[LighthouseFinding, ...] = Field(max_length=MAX_LIGHTHOUSE_FINDINGS)


class _Ga4PageSpeedCorrelationBody(BaseModel):
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


class _Ga4SearchConsoleComparisonBody(BaseModel):
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


class _SearchEngineComparisonBody(BaseModel):
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


class _SearchEngineTrafficHealthBody(_SearchEngineComparisonBody):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _LocalSchemaValidationBody(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    document: str = Field(min_length=1, max_length=MAX_SCHEMA_LOCAL_DOCUMENT_CHARS)


class _PublicSchemaValidationBody(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    url: str = Field(min_length=1, max_length=MAX_SCHEMA_FETCH_URL_CHARS)
    timeout_seconds: float = Field(
        default=DEFAULT_PROVIDER_TIMEOUT_SECONDS,
        ge=MIN_PROVIDER_TIMEOUT_SECONDS,
        le=MAX_PROVIDER_TIMEOUT_SECONDS,
    )


class _SiteAuditBody(BaseModel):
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


class _SiteOwnershipCheckBody(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    google_account_id: str = Field(pattern=ACCOUNT_ID_PATTERN)
    bing_account_id: str = Field(pattern=ACCOUNT_ID_PATTERN)
    site_url: str = Field(min_length=1, max_length=2_048)
    timeout_seconds: float = Field(
        default=DEFAULT_PROVIDER_TIMEOUT_SECONDS,
        ge=MIN_PROVIDER_TIMEOUT_SECONDS,
        le=MAX_PROVIDER_TIMEOUT_SECONDS,
    )


class _SiteOwnershipVerificationBody(_SiteOwnershipCheckBody):
    dns_account_id: str = Field(pattern=ACCOUNT_ID_PATTERN)


class _SiteRemediationBody(BaseModel):
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


class _BingBacklinkIntelligenceBody(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    account_id: str = Field(pattern=ACCOUNT_ID_PATTERN)
    site_url: str = Field(min_length=1, max_length=2_048)
    target_urls: tuple[str, ...] = Field(min_length=1, max_length=MAX_BING_BACKLINK_TARGETS)
    max_pages_per_target: int = Field(default=1, ge=1, le=MAX_BING_LINK_PAGE + 1)
    timeout_seconds: float = Field(
        default=DEFAULT_PROVIDER_TIMEOUT_SECONDS,
        ge=MIN_PROVIDER_TIMEOUT_SECONDS,
        le=MAX_PROVIDER_TIMEOUT_SECONDS,
    )


def build_api_router(services: ApplicationServices) -> APIRouter:
    """Create all versioned read-only REST endpoints."""
    router = APIRouter(prefix=API_PREFIX)

    @router.get("/server-info", response_model=None, operation_id="server_info")
    def server_info() -> JsonValue:
        return to_json_value(services.capabilities.server_info(ServerInfoRequest()))

    @router.get("/accounts", response_model=None, operation_id="accounts_list")
    def accounts_list(
        provider: Annotated[Provider | None, Query()] = None,
    ) -> JsonValue:
        return to_json_value(services.sites.accounts_list(AccountsListRequest(provider=provider)))

    @router.get("/sites", response_model=None, operation_id="sites_list")
    def sites_list(
        account_id: Annotated[str | None, Query(min_length=1, max_length=63)] = None,
        provider: Annotated[Provider | None, Query()] = None,
    ) -> JsonValue:
        return to_json_value(
            services.sites.sites_list(SitesListRequest(account_id=account_id, provider=provider))
        )

    @router.get(
        "/provider-readiness",
        response_model=None,
        operation_id="provider_readiness",
    )
    async def provider_readiness(
        account_id: Annotated[str, Query(pattern=ACCOUNT_ID_PATTERN)],
        timeout_seconds: Annotated[
            float,
            Query(ge=MIN_PROVIDER_TIMEOUT_SECONDS, le=MAX_PROVIDER_TIMEOUT_SECONDS),
        ] = DEFAULT_PROVIDER_TIMEOUT_SECONDS,
    ) -> JsonValue:
        return to_json_value(
            await services.provider_readiness.readiness(
                ProviderReadinessRequest(
                    account_id=account_id,
                    timeout_seconds=timeout_seconds,
                )
            )
        )

    @router.post(
        "/site-audits",
        response_model=None,
        operation_id="site_audit_create",
    )
    async def site_audit(body: _SiteAuditBody) -> JsonValue:
        if services.site_audit is None:
            raise RuntimeError("site audit service is unavailable")
        return to_json_value(
            await services.site_audit.audit(
                SiteAuditRequest(
                    account_id=body.account_id,
                    site_url=body.site_url,
                    max_pages=body.max_pages,
                    max_depth=body.max_depth,
                    timeout_seconds=body.timeout_seconds,
                )
            )
        )

    @router.post(
        "/site-ownership-checks",
        response_model=None,
        operation_id="site_ownership_check",
    )
    async def site_ownership_check(body: _SiteOwnershipCheckBody) -> JsonValue:
        if services.site_ownership is None:
            raise RuntimeError("site ownership service is unavailable")
        return to_json_value(
            await services.site_ownership.check(
                SiteOwnershipCheckRequest(
                    google_account_id=body.google_account_id,
                    bing_account_id=body.bing_account_id,
                    site_url=body.site_url,
                    timeout_seconds=body.timeout_seconds,
                )
            )
        )

    @router.post(
        "/bing/backlink-intelligence",
        response_model=None,
        operation_id="bing_backlink_intelligence",
    )
    async def bing_backlink_intelligence(body: _BingBacklinkIntelligenceBody) -> JsonValue:
        return to_json_value(
            await services.bing_webmaster.backlink_intelligence(
                BingBacklinkIntelligenceRequest(
                    account_id=body.account_id,
                    site_url=body.site_url,
                    target_urls=body.target_urls,
                    max_pages_per_target=body.max_pages_per_target,
                    timeout_seconds=body.timeout_seconds,
                )
            )
        )

    @router.post(
        "/google/search-analytics-queries",
        response_model=None,
        operation_id="google_search_analytics_query",
    )
    async def google_search_analytics_query(body: _SearchAnalyticsBody) -> JsonValue:
        return to_json_value(
            await services.google_search_console.search_analytics(
                SearchAnalyticsRequest(
                    account_id=body.account_id,
                    site_url=body.site_url,
                    start_date=body.start_date,
                    end_date=body.end_date,
                    dimensions=body.dimensions,
                    filters=tuple(
                        SearchAnalyticsFilter(
                            dimension=item.dimension,
                            operator=item.operator,
                            expression=item.expression,
                        )
                        for item in body.filters
                    ),
                    search_type=body.search_type,
                    row_limit=body.row_limit,
                    start_row=body.start_row,
                    timeout_seconds=body.timeout_seconds,
                )
            )
        )

    @router.post(
        "/google/search-analytics-summary",
        response_model=None,
        operation_id="google_search_analytics_summary",
    )
    async def google_search_analytics_summary(body: _SearchAnalyticsSummaryBody) -> JsonValue:
        return to_json_value(
            await services.google_search_console.search_analytics_summary(
                SearchAnalyticsSummaryRequest(
                    account_id=body.account_id,
                    site_url=body.site_url,
                    start_date=body.start_date,
                    end_date=body.end_date,
                    filters=tuple(
                        SearchAnalyticsFilter(
                            dimension=item.dimension,
                            operator=item.operator,
                            expression=item.expression,
                        )
                        for item in body.filters
                    ),
                    search_type=body.search_type,
                    timeout_seconds=body.timeout_seconds,
                )
            )
        )

    @router.post(
        "/google/search-analytics-comparison",
        response_model=None,
        operation_id="google_search_analytics_comparison",
    )
    async def google_search_analytics_comparison(
        body: _SearchAnalyticsComparisonBody,
    ) -> JsonValue:
        current = SearchAnalyticsSummaryRequest(
            account_id=body.account_id,
            site_url=body.site_url,
            start_date=body.start_date,
            end_date=body.end_date,
            filters=tuple(
                SearchAnalyticsFilter(
                    dimension=item.dimension,
                    operator=item.operator,
                    expression=item.expression,
                )
                for item in body.filters
            ),
            search_type=body.search_type,
            timeout_seconds=body.timeout_seconds,
        )
        return to_json_value(
            await services.google_search_console.search_analytics_comparison(
                SearchAnalyticsComparisonRequest(
                    current=current,
                    previous_start_date=body.previous_start_date,
                    previous_end_date=body.previous_end_date,
                )
            )
        )

    @router.post(
        "/google/search-analytics-dimension-report",
        response_model=None,
        operation_id="google_search_analytics_dimension_report",
    )
    async def google_search_analytics_dimension_report(
        body: _SearchAnalyticsDimensionReportBody,
    ) -> JsonValue:
        return to_json_value(
            await services.google_search_console.search_analytics_dimension_report(
                SearchAnalyticsDimensionReportRequest(
                    account_id=body.account_id,
                    site_url=body.site_url,
                    report=body.report,
                    start_date=body.start_date,
                    end_date=body.end_date,
                    filters=tuple(
                        SearchAnalyticsFilter(
                            dimension=item.dimension,
                            operator=item.operator,
                            expression=item.expression,
                        )
                        for item in body.filters
                    ),
                    search_type=body.search_type,
                    row_limit=body.row_limit,
                    start_row=body.start_row,
                    timeout_seconds=body.timeout_seconds,
                )
            )
        )

    @router.post(
        "/google/search-analytics-drop-attribution",
        response_model=None,
        operation_id="google_search_analytics_drop_attribution",
    )
    async def google_search_analytics_drop_attribution(
        body: _SearchAnalyticsDropAttributionBody,
    ) -> JsonValue:
        return to_json_value(
            await services.google_search_console.search_analytics_drop_attribution(
                SearchAnalyticsDropAttributionRequest(
                    account_id=body.account_id,
                    site_url=body.site_url,
                    attribution=body.attribution,
                    current_start_date=body.start_date,
                    current_end_date=body.end_date,
                    previous_start_date=body.previous_start_date,
                    previous_end_date=body.previous_end_date,
                    filters=tuple(
                        SearchAnalyticsFilter(
                            dimension=item.dimension,
                            operator=item.operator,
                            expression=item.expression,
                        )
                        for item in body.filters
                    ),
                    search_type=body.search_type,
                    row_limit=body.row_limit,
                    timeout_seconds=body.timeout_seconds,
                )
            )
        )

    @router.post(
        "/google/search-analytics-trend",
        response_model=None,
        operation_id="google_search_analytics_trend",
    )
    async def google_search_analytics_trend(body: _SearchAnalyticsSummaryBody) -> JsonValue:
        return to_json_value(
            await services.google_search_console.search_analytics_trend(
                SearchAnalyticsTrendRequest(
                    account_id=body.account_id,
                    site_url=body.site_url,
                    start_date=body.start_date,
                    end_date=body.end_date,
                    filters=tuple(
                        SearchAnalyticsFilter(
                            dimension=item.dimension,
                            operator=item.operator,
                            expression=item.expression,
                        )
                        for item in body.filters
                    ),
                    search_type=body.search_type,
                    timeout_seconds=body.timeout_seconds,
                )
            )
        )

    @router.post(
        "/google/search-analytics-anomalies",
        response_model=None,
        operation_id="google_search_analytics_anomalies",
    )
    async def google_search_analytics_anomalies(body: _SearchAnalyticsSummaryBody) -> JsonValue:
        return to_json_value(
            await services.google_search_console.search_analytics_anomalies(
                SearchAnalyticsTrendRequest(
                    account_id=body.account_id,
                    site_url=body.site_url,
                    start_date=body.start_date,
                    end_date=body.end_date,
                    filters=tuple(
                        SearchAnalyticsFilter(
                            dimension=item.dimension,
                            operator=item.operator,
                            expression=item.expression,
                        )
                        for item in body.filters
                    ),
                    search_type=body.search_type,
                    timeout_seconds=body.timeout_seconds,
                )
            )
        )

    @router.post(
        "/google/search-analytics-page-performance",
        response_model=None,
        operation_id="google_search_analytics_page_performance",
    )
    async def google_search_analytics_page_performance(
        body: _SearchAnalyticsPagePerformanceBody,
    ) -> JsonValue:
        return to_json_value(
            await services.google_search_console.search_analytics_page_performance(
                SearchAnalyticsPagePerformanceRequest(
                    account_id=body.account_id,
                    site_url=body.site_url,
                    start_date=body.start_date,
                    end_date=body.end_date,
                    filters=tuple(
                        SearchAnalyticsFilter(
                            dimension=item.dimension,
                            operator=item.operator,
                            expression=item.expression,
                        )
                        for item in body.filters
                    ),
                    search_type=body.search_type,
                    row_limit=body.row_limit,
                    timeout_seconds=body.timeout_seconds,
                )
            )
        )

    @router.get(
        "/google/sites",
        response_model=None,
        operation_id="google_sites_list",
    )
    async def google_sites_list(
        account_id: Annotated[str, Query(pattern=ACCOUNT_ID_PATTERN)],
        timeout_seconds: Annotated[
            float,
            Query(ge=MIN_PROVIDER_TIMEOUT_SECONDS, le=MAX_PROVIDER_TIMEOUT_SECONDS),
        ] = DEFAULT_PROVIDER_TIMEOUT_SECONDS,
    ) -> JsonValue:
        return to_json_value(
            await services.google_search_console.list_sites(
                SiteListRequest(account_id, timeout_seconds)
            )
        )

    @router.get(
        "/google/site",
        response_model=None,
        operation_id="google_site_get",
    )
    async def google_site_get(
        account_id: Annotated[str, Query(pattern=ACCOUNT_ID_PATTERN)],
        site_url: Annotated[str, Query(min_length=1, max_length=2_048)],
        timeout_seconds: Annotated[
            float,
            Query(ge=MIN_PROVIDER_TIMEOUT_SECONDS, le=MAX_PROVIDER_TIMEOUT_SECONDS),
        ] = DEFAULT_PROVIDER_TIMEOUT_SECONDS,
    ) -> JsonValue:
        return to_json_value(
            await services.google_search_console.get_site(
                SiteGetRequest(account_id, site_url, timeout_seconds)
            )
        )

    @router.get(
        "/google/sitemaps",
        response_model=None,
        operation_id="google_sitemaps_list",
    )
    async def google_sitemaps_list(
        account_id: Annotated[str, Query(pattern=ACCOUNT_ID_PATTERN)],
        site_url: Annotated[str, Query(min_length=1, max_length=2_048)],
        timeout_seconds: Annotated[
            float,
            Query(ge=MIN_PROVIDER_TIMEOUT_SECONDS, le=MAX_PROVIDER_TIMEOUT_SECONDS),
        ] = DEFAULT_PROVIDER_TIMEOUT_SECONDS,
    ) -> JsonValue:
        return to_json_value(
            await services.google_search_console.list_sitemaps(
                SitemapListRequest(account_id, site_url, timeout_seconds)
            )
        )

    @router.get(
        "/google/sitemap",
        response_model=None,
        operation_id="google_sitemap_get",
    )
    async def google_sitemap_get(
        account_id: Annotated[str, Query(pattern=ACCOUNT_ID_PATTERN)],
        site_url: Annotated[str, Query(min_length=1, max_length=2_048)],
        sitemap_url: Annotated[str, Query(min_length=1, max_length=2_048)],
        timeout_seconds: Annotated[
            float,
            Query(ge=MIN_PROVIDER_TIMEOUT_SECONDS, le=MAX_PROVIDER_TIMEOUT_SECONDS),
        ] = DEFAULT_PROVIDER_TIMEOUT_SECONDS,
    ) -> JsonValue:
        return to_json_value(
            await services.google_search_console.get_sitemap(
                SitemapGetRequest(account_id, site_url, sitemap_url, timeout_seconds)
            )
        )

    @router.post(
        "/google/url-inspections",
        response_model=None,
        operation_id="google_url_inspection",
    )
    async def google_url_inspection(body: _UrlInspectionBody) -> JsonValue:
        return to_json_value(
            await services.google_search_console.inspect_url(
                UrlInspectionRequest(
                    body.account_id,
                    body.site_url,
                    body.inspection_url,
                    body.timeout_seconds,
                )
            )
        )

    @router.post(
        "/google/url-inspection-batches",
        response_model=None,
        operation_id="google_url_inspection_batch",
    )
    async def google_url_inspection_batch(body: _UrlInspectionBatchBody) -> JsonValue:
        return to_json_value(
            await services.google_search_console.inspect_urls(
                UrlInspectionBatchRequest(
                    account_id=body.account_id,
                    site_url=body.site_url,
                    inspection_urls=body.inspection_urls,
                    timeout_seconds=body.timeout_seconds,
                )
            )
        )

    @router.post(
        ONBOARDING_GUIDE_PATH,
        response_model=None,
        operation_id=ONBOARDING_GUIDE_OPERATION,
    )
    async def onboarding_guide(body: _OnboardingGuideBody) -> JsonValue:
        return to_json_value(
            services.onboarding_guide.render(
                OnboardingGuideRequest(site_url=body.site_url),
                writes_enabled=services.writes_enabled,
                agent_onboarding_enabled=services.agent_onboarding_enabled,
            )
        )

    @router.post(
        GOOGLE_ANALYTICS_DATA_STREAMS_PATH,
        response_model=None,
        operation_id=GOOGLE_ANALYTICS_DATA_STREAMS_OPERATION,
    )
    async def google_analytics_data_streams(
        body: _Ga4DataStreamsBody,
    ) -> JsonValue:
        return to_json_value(
            await services.google_analytics_admin.list_data_streams(
                Ga4DataStreamsRequest(
                    account_id=body.account_id,
                    property_id=body.property_id,
                    timeout_seconds=body.timeout_seconds,
                )
            )
        )

    @router.post(
        GOOGLE_ANALYTICS_ACCOUNT_INVENTORY_PATH,
        response_model=None,
        operation_id=GOOGLE_ANALYTICS_ACCOUNT_INVENTORY_OPERATION,
    )
    async def google_analytics_account_inventory(
        body: _Ga4AccountDiscoveryBody,
    ) -> JsonValue:
        return to_json_value(
            await services.google_analytics.list_account_summaries(
                Ga4AccountDiscoveryRequest(
                    account_id=body.account_id,
                    timeout_seconds=body.timeout_seconds,
                )
            )
        )

    @router.post(
        "/google-analytics/reports",
        response_model=None,
        operation_id="google_analytics_report",
    )
    async def google_analytics_report(body: _Ga4ReportBody) -> JsonValue:
        return to_json_value(
            await services.google_analytics.run_report(
                Ga4ReportRequest(
                    account_id=body.account_id,
                    property_id=body.property_id,
                    date_ranges=tuple(
                        Ga4DateRange(item.start_date, item.end_date) for item in body.date_ranges
                    ),
                    dimensions=body.dimensions,
                    metrics=body.metrics,
                    limit=body.limit,
                    offset=body.offset,
                    timeout_seconds=body.timeout_seconds,
                )
            )
        )

    @router.post(
        "/google-analytics/content-performance",
        response_model=None,
        operation_id="google_analytics_content_performance",
    )
    async def google_analytics_content_performance(body: _Ga4FixedReportBody) -> JsonValue:
        return to_json_value(
            await services.google_analytics.content_performance(
                Ga4FixedReportRequest(
                    body.account_id,
                    body.property_id,
                    body.start_date,
                    body.end_date,
                    body.limit,
                    body.timeout_seconds,
                )
            )
        )

    @router.post(
        "/google-analytics/landing-page-performance",
        response_model=None,
        operation_id="google_analytics_landing_page_performance",
    )
    async def google_analytics_landing_page_performance(
        body: _Ga4FixedReportBody,
    ) -> JsonValue:
        return to_json_value(
            await services.google_analytics.landing_page_performance(
                Ga4FixedReportRequest(
                    body.account_id,
                    body.property_id,
                    body.start_date,
                    body.end_date,
                    body.limit,
                    body.timeout_seconds,
                )
            )
        )

    @router.post(
        "/google-analytics/organic-search-landing-pages",
        response_model=None,
        operation_id="google_analytics_organic_search_landing_pages",
    )
    async def google_analytics_organic_search_landing_pages(
        body: _Ga4FixedReportBody,
    ) -> JsonValue:
        return to_json_value(
            await services.google_analytics.organic_search_landing_pages(
                Ga4FixedReportRequest(
                    body.account_id,
                    body.property_id,
                    body.start_date,
                    body.end_date,
                    body.limit,
                    body.timeout_seconds,
                )
            )
        )

    @router.post(
        "/google-analytics/traffic-source-performance",
        response_model=None,
        operation_id="google_analytics_traffic_source_performance",
    )
    async def google_analytics_traffic_source_performance(
        body: _Ga4FixedReportBody,
    ) -> JsonValue:
        return to_json_value(
            await services.google_analytics.traffic_source_performance(
                Ga4FixedReportRequest(
                    body.account_id,
                    body.property_id,
                    body.start_date,
                    body.end_date,
                    body.limit,
                    body.timeout_seconds,
                )
            )
        )

    @router.post(
        "/google-analytics/ecommerce-performance",
        response_model=None,
        operation_id="google_analytics_ecommerce_performance",
    )
    async def google_analytics_ecommerce_performance(
        body: _Ga4FixedReportBody,
    ) -> JsonValue:
        return to_json_value(
            await services.google_analytics.ecommerce_performance(
                Ga4FixedReportRequest(
                    body.account_id,
                    body.property_id,
                    body.start_date,
                    body.end_date,
                    body.limit,
                    body.timeout_seconds,
                )
            )
        )

    @router.post(
        "/google-analytics/audience-segments",
        response_model=None,
        operation_id="google_analytics_audience_segments",
    )
    async def google_analytics_audience_segments(body: _Ga4FixedReportBody) -> JsonValue:
        return to_json_value(
            await services.google_analytics.audience_segments(
                Ga4FixedReportRequest(
                    body.account_id,
                    body.property_id,
                    body.start_date,
                    body.end_date,
                    body.limit,
                    body.timeout_seconds,
                )
            )
        )

    @router.post(
        "/google-analytics/user-behavior",
        response_model=None,
        operation_id="google_analytics_user_behavior",
    )
    async def google_analytics_user_behavior(body: _Ga4FixedReportBody) -> JsonValue:
        return to_json_value(
            await services.google_analytics.user_behavior(
                Ga4FixedReportRequest(
                    body.account_id,
                    body.property_id,
                    body.start_date,
                    body.end_date,
                    body.limit,
                    body.timeout_seconds,
                )
            )
        )

    @router.post(
        "/google-analytics/conversion-funnels",
        response_model=None,
        operation_id="google_analytics_conversion_funnel",
    )
    async def google_analytics_conversion_funnel(body: _Ga4ConversionFunnelBody) -> JsonValue:
        return to_json_value(
            await services.google_analytics.conversion_funnel(
                Ga4ConversionFunnelRequest(
                    account_id=body.account_id,
                    property_id=body.property_id,
                    start_date=body.start_date,
                    end_date=body.end_date,
                    event_names=body.event_names,
                    limit=body.limit,
                    timeout_seconds=body.timeout_seconds,
                )
            )
        )

    @router.post(
        "/google-analytics/realtime-reports",
        response_model=None,
        operation_id="google_analytics_realtime_report",
    )
    async def google_analytics_realtime_report(body: _Ga4RealtimeReportBody) -> JsonValue:
        return to_json_value(
            await services.google_analytics.run_realtime_report(
                Ga4RealtimeReportRequest(
                    account_id=body.account_id,
                    property_id=body.property_id,
                    dimensions=body.dimensions,
                    metrics=body.metrics,
                    limit=body.limit,
                    timeout_seconds=body.timeout_seconds,
                )
            )
        )

    @router.post(
        "/pagespeed/analyses",
        response_model=None,
        operation_id="pagespeed_analyze",
    )
    async def pagespeed_analyze(body: _PageSpeedAnalysisBody) -> JsonValue:
        return to_json_value(
            await services.pagespeed.analyze(
                PageSpeedAnalysisRequest(
                    account_id=body.account_id,
                    site_url=body.site_url,
                    page_url=body.page_url,
                    strategy=body.strategy,
                    categories=body.categories,
                    timeout_seconds=body.timeout_seconds,
                )
            )
        )

    @router.post(
        PAGESPEED_CORE_WEB_VITALS_PATH,
        response_model=None,
        operation_id=PAGESPEED_CORE_WEB_VITALS_OPERATION,
    )
    async def pagespeed_core_web_vitals(body: _PageSpeedAnalysisBody) -> JsonValue:
        return to_json_value(
            await services.pagespeed.core_web_vitals(
                PageSpeedAnalysisRequest(
                    account_id=body.account_id,
                    site_url=body.site_url,
                    page_url=body.page_url,
                    strategy=body.strategy,
                    categories=body.categories,
                    timeout_seconds=body.timeout_seconds,
                )
            )
        )

    @router.post(
        LIGHTHOUSE_AUDIT_PATH,
        response_model=LighthouseAuditReport,
        operation_id=LIGHTHOUSE_AUDIT_OPERATION,
    )
    async def lighthouse_audit(body: _LighthouseAuditBody) -> JsonValue:
        return to_json_value(await services.lighthouse.audit(_lighthouse_request(body)))

    @router.post(
        LIGHTHOUSE_SEO_FINDINGS_PATH,
        response_model=LighthouseAuditReport,
        operation_id=LIGHTHOUSE_SEO_FINDINGS_OPERATION,
    )
    async def lighthouse_seo_findings(body: _LighthouseAuditBody) -> JsonValue:
        return to_json_value(
            await services.lighthouse.findings(
                _lighthouse_request(body),
                LighthouseCategory.SEO,
            )
        )

    @router.post(
        LIGHTHOUSE_ACCESSIBILITY_FINDINGS_PATH,
        response_model=LighthouseAuditReport,
        operation_id=LIGHTHOUSE_ACCESSIBILITY_FINDINGS_OPERATION,
    )
    async def lighthouse_accessibility_findings(body: _LighthouseAuditBody) -> JsonValue:
        return to_json_value(
            await services.lighthouse.findings(
                _lighthouse_request(body),
                LighthouseCategory.ACCESSIBILITY,
            )
        )

    @router.post(
        LIGHTHOUSE_PERFORMANCE_FINDINGS_PATH,
        response_model=LighthouseAuditReport,
        operation_id=LIGHTHOUSE_PERFORMANCE_FINDINGS_OPERATION,
    )
    async def lighthouse_performance_findings(body: _LighthouseAuditBody) -> JsonValue:
        return to_json_value(
            await services.lighthouse.findings(
                _lighthouse_request(body),
                LighthouseCategory.PERFORMANCE,
            )
        )

    @router.post(
        LIGHTHOUSE_BEST_PRACTICES_FINDINGS_PATH,
        response_model=LighthouseAuditReport,
        operation_id=LIGHTHOUSE_BEST_PRACTICES_FINDINGS_OPERATION,
    )
    async def lighthouse_best_practices_findings(body: _LighthouseAuditBody) -> JsonValue:
        return to_json_value(
            await services.lighthouse.findings(
                _lighthouse_request(body),
                LighthouseCategory.BEST_PRACTICES,
            )
        )

    @router.post(
        GA4_PAGESPEED_CORRELATION_PATH,
        response_model=None,
        operation_id=GA4_PAGESPEED_CORRELATION_OPERATION,
    )
    async def ga4_pagespeed_correlation(body: _Ga4PageSpeedCorrelationBody) -> JsonValue:
        return to_json_value(
            await services.cross_provider.ga4_pagespeed_correlation(
                Ga4PageSpeedCorrelationRequest(
                    google_analytics_account_id=body.google_analytics_account_id,
                    property_id=body.property_id,
                    pagespeed_account_id=body.pagespeed_account_id,
                    site_url=body.site_url,
                    page_url=body.page_url,
                    start_date=body.start_date,
                    end_date=body.end_date,
                    strategy=body.strategy,
                    timeout_seconds=body.timeout_seconds,
                )
            )
        )

    @router.post(
        GA4_SEARCH_CONSOLE_COMPARISON_PATH,
        response_model=None,
        operation_id=GA4_SEARCH_CONSOLE_COMPARISON_OPERATION,
    )
    async def ga4_search_console_comparison(body: _Ga4SearchConsoleComparisonBody) -> JsonValue:
        return to_json_value(
            await services.cross_provider.ga4_search_console_comparison(
                Ga4SearchConsoleComparisonRequest(
                    google_analytics_account_id=body.google_analytics_account_id,
                    property_id=body.property_id,
                    google_search_console_account_id=body.google_search_console_account_id,
                    site_url=body.site_url,
                    start_date=body.start_date,
                    end_date=body.end_date,
                    timeout_seconds=body.timeout_seconds,
                )
            )
        )

    @router.post(
        SEARCH_ENGINE_COMPARISON_PATH,
        response_model=None,
        operation_id=SEARCH_ENGINE_COMPARISON_OPERATION,
    )
    async def search_engine_comparison(body: _SearchEngineComparisonBody) -> JsonValue:
        return to_json_value(
            await services.cross_provider.search_engine_comparison(
                SearchEngineComparisonRequest(
                    google_search_console_account_id=body.google_search_console_account_id,
                    google_search_console_site_url=body.google_search_console_site_url,
                    bing_account_id=body.bing_account_id,
                    bing_site_url=body.bing_site_url,
                    start_date=body.start_date,
                    end_date=body.end_date,
                    timeout_seconds=body.timeout_seconds,
                )
            )
        )

    @router.post(
        SEARCH_ENGINE_TRAFFIC_HEALTH_PATH,
        response_model=None,
        operation_id=SEARCH_ENGINE_TRAFFIC_HEALTH_OPERATION,
    )
    async def search_engine_traffic_health(body: _SearchEngineTrafficHealthBody) -> JsonValue:
        return to_json_value(
            await services.cross_provider.search_engine_traffic_health(
                SearchEngineTrafficHealthRequest(
                    google_search_console_account_id=body.google_search_console_account_id,
                    google_search_console_site_url=body.google_search_console_site_url,
                    bing_account_id=body.bing_account_id,
                    bing_site_url=body.bing_site_url,
                    start_date=body.start_date,
                    end_date=body.end_date,
                    timeout_seconds=body.timeout_seconds,
                )
            )
        )

    @router.post(
        "/schema/validate-html",
        response_model=None,
        operation_id="schema_validate_html",
    )
    def schema_validate_html(body: _LocalSchemaValidationBody) -> JsonValue:
        return to_json_value(
            services.local_schema.validate_html(LocalSchemaValidationRequest(body.document))
        )

    @router.post(
        "/schema/validate-json-ld",
        response_model=None,
        operation_id="schema_validate_json_ld",
    )
    def schema_validate_json_ld(body: _LocalSchemaValidationBody) -> JsonValue:
        return to_json_value(
            services.local_schema.validate_json_ld(LocalSchemaValidationRequest(body.document))
        )

    @router.post(
        "/schema/validate-url",
        response_model=None,
        operation_id="schema_validate_url",
    )
    async def schema_validate_url(body: _PublicSchemaValidationBody) -> JsonValue:
        return to_json_value(
            await services.local_schema.validate_url(
                PublicSchemaValidationRequest(
                    url=body.url,
                    timeout_seconds=body.timeout_seconds,
                )
            )
        )

    @router.post(
        "/bing/keyword-statistics",
        response_model=None,
        operation_id="bing_keyword_statistics",
    )
    async def bing_keyword_statistics(body: _BingKeywordStatisticsBody) -> JsonValue:
        return to_json_value(
            await services.bing_webmaster.keyword_statistics(
                BingKeywordStatisticsRequest(
                    body.account_id,
                    body.query,
                    body.country,
                    body.language,
                    body.timeout_seconds,
                )
            )
        )

    @router.post(
        "/bing/related-keywords",
        response_model=None,
        operation_id="bing_related_keywords",
    )
    async def bing_related_keywords(body: _BingRelatedKeywordsBody) -> JsonValue:
        return to_json_value(
            await services.bing_webmaster.related_keywords(
                BingRelatedKeywordsRequest(
                    body.account_id,
                    body.query,
                    body.start_date,
                    body.end_date,
                    body.country,
                    body.language,
                    body.timeout_seconds,
                )
            )
        )

    @router.post(
        "/bing/traffic-trend",
        response_model=None,
        operation_id="bing_traffic_trend",
    )
    async def bing_traffic_trend(body: _BingTrafficBody) -> JsonValue:
        return to_json_value(
            await services.bing_webmaster.traffic_trend(
                BingTrafficPeriodRequest(
                    body.account_id,
                    body.site_url,
                    body.start_date,
                    body.end_date,
                    body.timeout_seconds,
                )
            )
        )

    @router.post(
        "/bing/traffic-anomalies",
        response_model=None,
        operation_id="bing_traffic_anomalies",
    )
    async def bing_traffic_anomalies(body: _BingTrafficBody) -> JsonValue:
        return to_json_value(
            await services.bing_webmaster.traffic_anomalies(
                BingTrafficPeriodRequest(
                    body.account_id,
                    body.site_url,
                    body.start_date,
                    body.end_date,
                    body.timeout_seconds,
                )
            )
        )

    @router.post(
        "/bing/traffic-comparison",
        response_model=None,
        operation_id="bing_traffic_comparison",
    )
    async def bing_traffic_comparison(body: _BingTrafficComparisonBody) -> JsonValue:
        current = BingTrafficPeriodRequest(
            body.account_id,
            body.site_url,
            body.start_date,
            body.end_date,
            body.timeout_seconds,
        )
        return to_json_value(
            await services.bing_webmaster.traffic_comparison(
                BingTrafficComparisonRequest(
                    current,
                    body.previous_start_date,
                    body.previous_end_date,
                )
            )
        )

    @router.post(
        "/bing/query-performance",
        response_model=None,
        operation_id="bing_query_performance",
    )
    async def bing_query_performance(body: _BingPerformanceBody) -> JsonValue:
        return to_json_value(
            await services.bing_webmaster.query_performance(
                BingPerformanceRequest(
                    body.account_id,
                    body.site_url,
                    body.timeout_seconds,
                )
            )
        )

    @router.post(
        "/bing/page-performance",
        response_model=None,
        operation_id="bing_page_performance",
    )
    async def bing_page_performance(body: _BingPerformanceBody) -> JsonValue:
        return to_json_value(
            await services.bing_webmaster.page_performance(
                BingPerformanceRequest(
                    body.account_id,
                    body.site_url,
                    body.timeout_seconds,
                )
            )
        )

    @router.post(
        "/bing/brand-analysis",
        response_model=None,
        operation_id="bing_brand_analysis",
    )
    async def bing_brand_analysis(body: _BingBrandAnalysisBody) -> JsonValue:
        return to_json_value(
            await services.bing_webmaster.brand_analysis(
                BingBrandAnalysisRequest(
                    body.account_id,
                    body.site_url,
                    body.brand_terms,
                    body.timeout_seconds,
                )
            )
        )

    @router.post(
        "/bing/ranking-buckets",
        response_model=None,
        operation_id="bing_ranking_buckets",
    )
    async def bing_ranking_buckets(body: _BingPerformanceBody) -> JsonValue:
        return to_json_value(
            await services.bing_webmaster.ranking_buckets(
                BingPerformanceRequest(
                    body.account_id,
                    body.site_url,
                    body.timeout_seconds,
                )
            )
        )

    @router.post(
        "/bing/query-opportunities",
        response_model=None,
        operation_id="bing_query_opportunities",
    )
    async def bing_query_opportunities(body: _BingPerformanceBody) -> JsonValue:
        return to_json_value(
            await services.bing_webmaster.query_opportunities(
                BingPerformanceRequest(
                    body.account_id,
                    body.site_url,
                    body.timeout_seconds,
                )
            )
        )

    @router.post(
        "/bing/page-opportunities",
        response_model=None,
        operation_id="bing_page_opportunities",
    )
    async def bing_page_opportunities(body: _BingPerformanceBody) -> JsonValue:
        return to_json_value(
            await services.bing_webmaster.page_opportunities(
                BingPerformanceRequest(
                    body.account_id,
                    body.site_url,
                    body.timeout_seconds,
                )
            )
        )

    @router.post(
        BING_OPPORTUNITY_MATRIX_PATH,
        response_model=None,
        operation_id=BING_OPPORTUNITY_MATRIX_OPERATION,
    )
    async def bing_opportunity_matrix(body: _BingPerformanceBody) -> JsonValue:
        return to_json_value(
            await services.bing_webmaster.opportunity_matrix(
                BingPerformanceRequest(
                    body.account_id,
                    body.site_url,
                    body.timeout_seconds,
                )
            )
        )

    @router.post(
        "/bing/query-page-performance",
        response_model=None,
        operation_id="bing_query_page_performance",
    )
    async def bing_query_page_performance(body: _BingQueryPagePerformanceBody) -> JsonValue:
        return to_json_value(
            await services.bing_webmaster.query_page_performance(
                BingQueryPagePerformanceRequest(
                    body.account_id,
                    body.site_url,
                    body.query,
                    body.timeout_seconds,
                )
            )
        )

    @router.post(
        "/bing/query-cannibalization",
        response_model=None,
        operation_id="bing_query_cannibalization",
    )
    async def bing_query_cannibalization(body: _BingQueryPagePerformanceBody) -> JsonValue:
        return to_json_value(
            await services.bing_webmaster.query_cannibalization(
                BingQueryPagePerformanceRequest(
                    body.account_id,
                    body.site_url,
                    body.query,
                    body.timeout_seconds,
                )
            )
        )

    @router.post(
        "/bing/page-query-performance",
        response_model=None,
        operation_id="bing_page_query_performance",
    )
    async def bing_page_query_performance(body: _BingPageQueryPerformanceBody) -> JsonValue:
        return to_json_value(
            await services.bing_webmaster.page_query_performance(
                BingPageQueryPerformanceRequest(
                    body.account_id,
                    body.site_url,
                    body.page_url,
                    body.timeout_seconds,
                )
            )
        )

    @router.post(
        "/bing/url-submission-quota",
        response_model=None,
        operation_id="bing_url_submission_quota",
    )
    async def bing_url_submission_quota(body: _BingPerformanceBody) -> JsonValue:
        return to_json_value(
            await services.bing_webmaster.url_submission_quota(
                BingUrlSubmissionQuotaRequest(
                    body.account_id,
                    body.site_url,
                    body.timeout_seconds,
                )
            )
        )

    @router.post(
        "/bing/crawl-issues",
        response_model=None,
        operation_id="bing_crawl_issues",
    )
    async def bing_crawl_issues(body: _BingPerformanceBody) -> JsonValue:
        return to_json_value(
            await services.bing_webmaster.crawl_issues(
                BingCrawlIssuesRequest(
                    body.account_id,
                    body.site_url,
                    body.timeout_seconds,
                )
            )
        )

    @router.post(
        "/bing/crawl-stats",
        response_model=None,
        operation_id="bing_crawl_stats",
    )
    async def bing_crawl_stats(body: _BingPerformanceBody) -> JsonValue:
        return to_json_value(
            await services.bing_webmaster.crawl_stats(
                BingCrawlStatsRequest(
                    body.account_id,
                    body.site_url,
                    body.timeout_seconds,
                )
            )
        )

    @router.post(
        "/bing/feeds",
        response_model=None,
        operation_id="bing_feeds",
    )
    async def bing_feeds(body: _BingPerformanceBody) -> JsonValue:
        return to_json_value(
            await services.bing_webmaster.feeds(
                BingFeedsRequest(
                    body.account_id,
                    body.site_url,
                    body.timeout_seconds,
                )
            )
        )

    @router.post(
        "/bing/link-counts",
        response_model=None,
        operation_id="bing_link_counts",
    )
    async def bing_link_counts(body: _BingLinkCountsBody) -> JsonValue:
        return to_json_value(
            await services.bing_webmaster.link_counts(
                BingLinkCountsRequest(
                    account_id=body.account_id,
                    site_url=body.site_url,
                    page=body.page,
                    timeout_seconds=body.timeout_seconds,
                )
            )
        )

    @router.post(
        "/bing/url-information",
        response_model=None,
        operation_id="bing_url_information",
    )
    async def bing_url_information(body: _BingUrlInformationBody) -> JsonValue:
        return to_json_value(
            await services.bing_webmaster.url_information(
                BingUrlInformationRequest(
                    account_id=body.account_id,
                    site_url=body.site_url,
                    page_url=body.page_url,
                    timeout_seconds=body.timeout_seconds,
                )
            )
        )

    if services.writes_enabled:

        @router.post(
            "/bing-url-submissions",
            response_model=None,
            operation_id="bing_url_submission_create",
        )
        async def bing_url_submission(body: _BingUrlSubmissionBody) -> JsonValue:
            return to_json_value(
                await services.bing_webmaster.submit_url_batch(
                    BingUrlSubmissionRequest(
                        account_id=body.account_id,
                        site_url=body.site_url,
                        urls=body.urls,
                        timeout_seconds=body.timeout_seconds,
                    )
                )
            )

        @router.post(
            "/bing-sitemap-submissions",
            response_model=None,
            operation_id="bing_sitemap_submission_create",
        )
        async def bing_sitemap_submission(body: _BingSitemapSubmissionBody) -> JsonValue:
            return to_json_value(
                await services.bing_webmaster.submit_sitemap(
                    BingSitemapSubmissionRequest(
                        account_id=body.account_id,
                        site_url=body.site_url,
                        sitemap_url=body.sitemap_url,
                        operation=body.operation,
                        timeout_seconds=body.timeout_seconds,
                    )
                )
            )

        @router.post(
            "/bing-site-submissions",
            response_model=None,
            operation_id="bing_site_submission_create",
        )
        async def bing_site_submission(body: _BingSiteSubmissionBody) -> JsonValue:
            return to_json_value(
                await services.bing_webmaster.submit_site(
                    BingSiteSubmissionRequest(
                        account_id=body.account_id,
                        site_url=body.site_url,
                        operation=body.operation,
                        timeout_seconds=body.timeout_seconds,
                    )
                )
            )

    @router.post(
        "/google-indexing-metadata",
        response_model=None,
        operation_id="google_indexing_metadata_get",
    )
    async def google_indexing_metadata(body: _GoogleIndexingMetadataBody) -> JsonValue:
        return to_json_value(
            await services.google_indexing_metadata.metadata(
                GoogleIndexingMetadataRequest(
                    account_id=body.account_id,
                    site_url=body.site_url,
                    url=body.url,
                    timeout_seconds=body.timeout_seconds,
                )
            )
        )

    google_indexing = services.google_indexing
    if services.writes_enabled and google_indexing is not None:

        @router.post(
            "/google-indexing-submissions",
            response_model=None,
            operation_id="google_indexing_submission_create",
        )
        async def google_indexing_submission(
            body: _GoogleIndexingSubmissionBody,
        ) -> JsonValue:
            return to_json_value(
                await google_indexing.submit(
                    GoogleIndexingSubmissionRequest(
                        account_id=body.account_id,
                        site_url=body.site_url,
                        url=body.url,
                        notification_type=body.notification_type,
                        timeout_seconds=body.timeout_seconds,
                    )
                )
            )

        @router.post(
            "/google-indexing-batch-submissions",
            response_model=None,
            operation_id="google_indexing_batch_submission_create",
        )
        async def google_indexing_batch_submission(
            body: _GoogleIndexingBatchSubmissionBody,
        ) -> JsonValue:
            return to_json_value(
                await google_indexing.submit_batch(
                    GoogleIndexingBatchSubmissionRequest(
                        account_id=body.account_id,
                        site_url=body.site_url,
                        notifications=tuple(
                            GoogleIndexingBatchNotification(
                                url=notification.url,
                                notification_type=notification.notification_type,
                            )
                            for notification in body.notifications
                        ),
                        timeout_seconds=body.timeout_seconds,
                    )
                )
            )

    google_sitemaps = services.google_sitemaps
    if services.writes_enabled and google_sitemaps is not None:

        @router.post(
            "/google-sitemap-submissions",
            response_model=None,
            operation_id="google_sitemap_submission_create",
        )
        async def google_sitemap_submission(
            body: _GoogleSitemapSubmissionBody,
        ) -> JsonValue:
            return to_json_value(
                await google_sitemaps.submit(
                    GoogleSitemapSubmissionRequest(
                        account_id=body.account_id,
                        site_url=body.site_url,
                        sitemap_url=body.sitemap_url,
                        operation=body.operation,
                        timeout_seconds=body.timeout_seconds,
                    )
                )
            )

    if services.writes_enabled:

        @router.post(
            GOOGLE_ANALYTICS_ACCOUNT_RENAME_PATH,
            response_model=None,
            operation_id=GOOGLE_ANALYTICS_ACCOUNT_RENAME_OPERATION,
        )
        async def google_analytics_account_rename(body: _Ga4AccountRenameBody) -> JsonValue:
            return to_json_value(
                await services.google_analytics_admin.rename_account(
                    Ga4AccountRenameRequest(
                        account_id=body.account_id,
                        analytics_account_id=body.analytics_account_id,
                        display_name=body.display_name,
                        timeout_seconds=body.timeout_seconds,
                    )
                )
            )

        @router.post(
            GOOGLE_ANALYTICS_PROPERTY_RENAME_PATH,
            response_model=None,
            operation_id=GOOGLE_ANALYTICS_PROPERTY_RENAME_OPERATION,
        )
        async def google_analytics_property_rename(body: _Ga4PropertyRenameBody) -> JsonValue:
            return to_json_value(
                await services.google_analytics_admin.rename_property(
                    Ga4PropertyRenameRequest(
                        account_id=body.account_id,
                        property_id=body.property_id,
                        display_name=body.display_name,
                        timeout_seconds=body.timeout_seconds,
                    )
                )
            )

    google_sites = services.google_sites
    if services.writes_enabled and google_sites is not None:

        @router.post(
            "/google-site-submissions",
            response_model=None,
            operation_id="google_site_submission_create",
        )
        async def google_site_submission(body: _GoogleSiteSubmissionBody) -> JsonValue:
            return to_json_value(
                await google_sites.submit(
                    GoogleSiteSubmissionRequest(
                        account_id=body.account_id,
                        site_url=body.site_url,
                        operation=body.operation,
                        timeout_seconds=body.timeout_seconds,
                    )
                )
            )

    site_onboarding = services.site_onboarding
    if services.writes_enabled and site_onboarding is not None:

        @router.post(
            "/site-onboarding-submissions",
            response_model=None,
            operation_id="site_onboarding_submission_create",
        )
        async def site_onboarding_submission(
            body: _SiteOnboardingSubmissionBody,
        ) -> JsonValue:
            return to_json_value(
                await site_onboarding.submit(
                    SiteOnboardingSubmissionRequest(
                        google_account_id=body.google_account_id,
                        bing_account_id=body.bing_account_id,
                        site_url=body.site_url,
                        google_analytics_parent_account_id=(
                            body.google_analytics_parent_account_id
                        ),
                        display_name=body.display_name,
                        time_zone=body.time_zone,
                        currency_code=body.currency_code,
                        timeout_seconds=body.timeout_seconds,
                    )
                )
            )

    site_ownership = services.site_ownership
    if services.writes_enabled and site_ownership is not None:

        @router.post(
            "/site-ownership-verifications",
            response_model=None,
            operation_id="site_ownership_verification_create",
        )
        async def site_ownership_verification(
            body: _SiteOwnershipVerificationBody,
        ) -> JsonValue:
            return to_json_value(
                await site_ownership.verify(
                    SiteOwnershipVerificationRequest(
                        google_account_id=body.google_account_id,
                        bing_account_id=body.bing_account_id,
                        dns_account_id=body.dns_account_id,
                        site_url=body.site_url,
                        timeout_seconds=body.timeout_seconds,
                    )
                )
            )

    site_remediation = services.site_remediation
    if services.writes_enabled and site_remediation is not None:

        @router.post(
            "/site-remediations",
            response_model=None,
            operation_id="site_remediation_create",
        )
        async def site_remediation_apply(body: _SiteRemediationBody) -> JsonValue:
            return to_json_value(
                await site_remediation.apply(
                    SiteRemediationRequest(
                        google_account_id=body.google_account_id,
                        google_site_url=body.google_site_url,
                        bing_account_id=body.bing_account_id,
                        bing_site_url=body.bing_site_url,
                        sitemap_url=body.sitemap_url,
                        changed_urls=body.changed_urls,
                        timeout_seconds=body.timeout_seconds,
                    )
                )
            )

    indexnow = services.indexnow
    if services.writes_enabled and indexnow is not None:

        @router.post(
            "/indexnow-submissions",
            response_model=None,
            operation_id="indexnow_submit",
        )
        async def indexnow_submit(body: _IndexNowSubmissionBody) -> JsonValue:
            return to_json_value(
                await indexnow.submit(
                    IndexNowSubmissionRequest(
                        target_id=body.target_id,
                        urls=body.urls,
                    )
                )
            )

    router.include_router(build_seo_router(services))
    return router


def _lighthouse_request(body: _LighthouseAuditBody) -> LighthouseAuditRequest:
    return LighthouseAuditRequest(
        account_id=body.account_id,
        site_url=body.site_url,
        page_url=body.page_url,
        timeout_seconds=body.timeout_seconds,
    )
