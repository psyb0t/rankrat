"""Transport-neutral catalog for the foundation's read-only MCP operations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from rankrat.constants import (
    BING_OPPORTUNITY_MATRIX_OPERATION,
    GA4_PAGESPEED_CORRELATION_OPERATION,
    GA4_SEARCH_CONSOLE_COMPARISON_OPERATION,
    GOOGLE_ANALYTICS_ACCOUNT_INVENTORY_OPERATION,
    LIGHTHOUSE_ACCESSIBILITY_FINDINGS_OPERATION,
    LIGHTHOUSE_AUDIT_OPERATION,
    LIGHTHOUSE_BEST_PRACTICES_FINDINGS_OPERATION,
    LIGHTHOUSE_PERFORMANCE_FINDINGS_OPERATION,
    LIGHTHOUSE_SEO_FINDINGS_OPERATION,
    PAGESPEED_CORE_WEB_VITALS_OPERATION,
    SEARCH_ENGINE_COMPARISON_OPERATION,
    SEARCH_ENGINE_TRAFFIC_HEALTH_OPERATION,
)
from rankrat.operator.site_onboarding import SiteOnboardingReceipt
from rankrat.operator.site_ownership import SiteOwnershipReceipt
from rankrat.providers.base import ProviderReadiness
from rankrat.providers.google_analytics import Ga4AccountSummary, Ga4FunnelReport, Ga4ReportResult
from rankrat.providers.google_analytics_admin import Ga4RenamedResource
from rankrat.providers.google_indexing import GoogleIndexingMetadata, GoogleIndexingPublishReceipt
from rankrat.services.bing import (
    BingBacklinkIntelligenceReport,
    BingBacklinkIntelligenceRequest,
    BingBrandAnalysisReport,
    BingBrandAnalysisRequest,
    BingCrawlIssuesReport,
    BingCrawlIssuesRequest,
    BingCrawlStatsReport,
    BingCrawlStatsRequest,
    BingFeedsReport,
    BingFeedsRequest,
    BingKeywordStatisticsReport,
    BingKeywordStatisticsRequest,
    BingLinkCountsReport,
    BingLinkCountsRequest,
    BingOpportunityMatrixReport,
    BingPageQueryPerformanceRequest,
    BingPerformanceOpportunityReport,
    BingPerformanceReport,
    BingPerformanceRequest,
    BingQueryCannibalizationReport,
    BingQueryPagePerformanceRequest,
    BingRankingBucketsReport,
    BingRelatedKeywordsReport,
    BingRelatedKeywordsRequest,
    BingSitemapSubmissionRequest,
    BingSitemapSubmissionResponse,
    BingSiteSubmissionRequest,
    BingSiteSubmissionResponse,
    BingTrafficAnomalyReport,
    BingTrafficComparison,
    BingTrafficComparisonRequest,
    BingTrafficPeriodRequest,
    BingTrafficTrendReport,
    BingUrlInformationReport,
    BingUrlInformationRequest,
    BingUrlSubmissionQuotaReport,
    BingUrlSubmissionQuotaRequest,
    BingUrlSubmissionRequest,
    BingUrlSubmissionResponse,
)
from rankrat.services.capabilities import ServerInfoRequest, ServerInfoResponse
from rankrat.services.cross_provider import (
    Ga4PageSpeedCorrelationReport,
    Ga4PageSpeedCorrelationRequest,
    Ga4SearchConsoleComparisonReport,
    Ga4SearchConsoleComparisonRequest,
    SearchEngineComparisonReport,
    SearchEngineComparisonRequest,
    SearchEngineTrafficHealthReport,
    SearchEngineTrafficHealthRequest,
)
from rankrat.services.diagnostics import DiagnosticsRequest, DiagnosticsResponse
from rankrat.services.google_analytics import (
    Ga4AccountDiscoveryRequest,
    Ga4ConversionFunnelRequest,
    Ga4FixedReport,
    Ga4FixedReportRequest,
    Ga4RealtimeReportRequest,
    Ga4ReportRequest,
)
from rankrat.services.google_analytics_admin import (
    Ga4AccountRenameRequest,
    Ga4DataStreamsReport,
    Ga4DataStreamsRequest,
    Ga4PropertyRenameRequest,
)
from rankrat.services.google_indexing import (
    GoogleIndexingBatchSubmission,
    GoogleIndexingBatchSubmissionRequest,
    GoogleIndexingSubmissionRequest,
)
from rankrat.services.google_indexing_metadata import GoogleIndexingMetadataRequest
from rankrat.services.google_search_console import (
    SearchAnalyticsAnomalyReport,
    SearchAnalyticsComparison,
    SearchAnalyticsComparisonRequest,
    SearchAnalyticsDimensionReport,
    SearchAnalyticsDimensionReportRequest,
    SearchAnalyticsDropAttributionReport,
    SearchAnalyticsDropAttributionRequest,
    SearchAnalyticsMetrics,
    SearchAnalyticsPagePerformanceRequest,
    SearchAnalyticsRequest,
    SearchAnalyticsSummaryRequest,
    SearchAnalyticsTrendReport,
    SearchAnalyticsTrendRequest,
    SiteGetRequest,
    SiteListRequest,
    SitemapGetRequest,
    SitemapListRequest,
    UrlInspectionBatchRequest,
    UrlInspectionRequest,
)
from rankrat.services.google_sitemaps import (
    GoogleSitemapSubmissionRequest,
    GoogleSitemapSubmissionResponse,
)
from rankrat.services.google_sites import GoogleSiteSubmissionRequest, GoogleSiteSubmissionResponse
from rankrat.services.indexnow import IndexNowSubmissionRequest, IndexNowSubmissionResponse
from rankrat.services.lighthouse import LighthouseAuditReport, LighthouseAuditRequest
from rankrat.services.onboarding_guide import OnboardingGuide, OnboardingGuideRequest
from rankrat.services.pagespeed import (
    PageSpeedAnalysisReport,
    PageSpeedAnalysisRequest,
    PageSpeedCoreWebVitalsReport,
)
from rankrat.services.provider_readiness import ProviderReadinessRequest
from rankrat.services.schema import (
    IndexingEligibility,
    LocalSchemaValidationRequest,
    PublicSchemaValidationReport,
    PublicSchemaValidationRequest,
)
from rankrat.services.site_audit import SiteAuditReport, SiteAuditRequest
from rankrat.services.site_onboarding import (
    SiteOnboardingSubmissionRequest,
)
from rankrat.services.site_ownership import (
    SiteOwnershipCheckRequest,
    SiteOwnershipVerificationRequest,
)
from rankrat.services.site_remediation import SiteRemediationReceipt, SiteRemediationRequest
from rankrat.services.sites import (
    AccountsListRequest,
    AccountsListResponse,
    SitesListRequest,
    SitesListResponse,
)

_SERVER_INFO_TOOL_NAME = "server_info"
_ACCOUNTS_LIST_TOOL_NAME = "accounts_list"
_SITES_LIST_TOOL_NAME = "sites_list"
_DIAGNOSTICS_TOOL_NAME = "diagnostics"
_PROVIDER_READINESS_TOOL_NAME = "provider_readiness"
_INDEXNOW_SUBMIT_TOOL_NAME = "indexnow_submit"
_GOOGLE_SEARCH_ANALYTICS_QUERY_TOOL_NAME = "google_search_analytics_query"
_GOOGLE_SEARCH_ANALYTICS_SUMMARY_TOOL_NAME = "google_search_analytics_summary"
_GOOGLE_SEARCH_ANALYTICS_COMPARISON_TOOL_NAME = "google_search_analytics_comparison"
_GOOGLE_SEARCH_ANALYTICS_DIMENSION_REPORT_TOOL_NAME = "google_search_analytics_dimension_report"
_GOOGLE_SEARCH_ANALYTICS_DROP_ATTRIBUTION_TOOL_NAME = "google_search_analytics_drop_attribution"
_GOOGLE_SEARCH_ANALYTICS_TREND_TOOL_NAME = "google_search_analytics_trend"
_GOOGLE_SEARCH_ANALYTICS_ANOMALIES_TOOL_NAME = "google_search_analytics_anomalies"
_GOOGLE_SEARCH_ANALYTICS_PAGE_PERFORMANCE_TOOL_NAME = "google_search_analytics_page_performance"
_GOOGLE_SITES_LIST_TOOL_NAME = "google_sites_list"
_GOOGLE_SITE_GET_TOOL_NAME = "google_site_get"
_GOOGLE_SITEMAPS_LIST_TOOL_NAME = "google_sitemaps_list"
_GOOGLE_SITEMAP_GET_TOOL_NAME = "google_sitemap_get"
_GOOGLE_URL_INSPECTION_TOOL_NAME = "google_url_inspection"
_GOOGLE_URL_INSPECTION_BATCH_TOOL_NAME = "google_url_inspection_batch"
_GOOGLE_ANALYTICS_REPORT_TOOL_NAME = "google_analytics_report"
_GOOGLE_ANALYTICS_REALTIME_REPORT_TOOL_NAME = "google_analytics_realtime_report"
_GOOGLE_ANALYTICS_CONTENT_PERFORMANCE_TOOL_NAME = "google_analytics_content_performance"
_GOOGLE_ANALYTICS_LANDING_PAGE_PERFORMANCE_TOOL_NAME = "google_analytics_landing_page_performance"
_GOOGLE_ANALYTICS_ORGANIC_SEARCH_LANDING_PAGES_TOOL_NAME = (
    "google_analytics_organic_search_landing_pages"
)
_GOOGLE_ANALYTICS_TRAFFIC_SOURCE_PERFORMANCE_TOOL_NAME = (
    "google_analytics_traffic_source_performance"
)
_GOOGLE_ANALYTICS_ECOMMERCE_PERFORMANCE_TOOL_NAME = "google_analytics_ecommerce_performance"
_GOOGLE_ANALYTICS_AUDIENCE_SEGMENTS_TOOL_NAME = "google_analytics_audience_segments"
_GOOGLE_ANALYTICS_USER_BEHAVIOR_TOOL_NAME = "google_analytics_user_behavior"
_GOOGLE_ANALYTICS_CONVERSION_FUNNEL_TOOL_NAME = "google_analytics_conversion_funnel"
_BING_KEYWORD_STATISTICS_TOOL_NAME = "bing_keyword_statistics"
_BING_RELATED_KEYWORDS_TOOL_NAME = "bing_related_keywords"
_BING_TRAFFIC_TREND_TOOL_NAME = "bing_traffic_trend"
_BING_TRAFFIC_ANOMALIES_TOOL_NAME = "bing_traffic_anomalies"
_BING_TRAFFIC_COMPARISON_TOOL_NAME = "bing_traffic_comparison"
_BING_QUERY_PERFORMANCE_TOOL_NAME = "bing_query_performance"
_BING_PAGE_PERFORMANCE_TOOL_NAME = "bing_page_performance"
_BING_BRAND_ANALYSIS_TOOL_NAME = "bing_brand_analysis"
_BING_RANKING_BUCKETS_TOOL_NAME = "bing_ranking_buckets"
_BING_QUERY_OPPORTUNITIES_TOOL_NAME = "bing_query_opportunities"
_BING_PAGE_OPPORTUNITIES_TOOL_NAME = "bing_page_opportunities"
_BING_OPPORTUNITY_MATRIX_DESCRIPTION = (
    "Return separate bounded Bing query/page opportunities and two-rule quick-win subsets."
)
_BING_QUERY_PAGE_PERFORMANCE_TOOL_NAME = "bing_query_page_performance"
_BING_QUERY_CANNIBALIZATION_TOOL_NAME = "bing_query_cannibalization"
_BING_PAGE_QUERY_PERFORMANCE_TOOL_NAME = "bing_page_query_performance"
_BING_URL_SUBMISSION_QUOTA_TOOL_NAME = "bing_url_submission_quota"
_BING_CRAWL_ISSUES_TOOL_NAME = "bing_crawl_issues"
_BING_CRAWL_STATS_TOOL_NAME = "bing_crawl_stats"
_BING_FEEDS_TOOL_NAME = "bing_feeds"
_BING_LINK_COUNTS_TOOL_NAME = "bing_link_counts"
_BING_URL_INFORMATION_TOOL_NAME = "bing_url_information"
_BING_URL_SUBMIT_TOOL_NAME = "bing_url_submit"
_BING_SITEMAP_SUBMIT_TOOL_NAME = "bing_sitemap_submit"
_BING_SITE_SUBMIT_TOOL_NAME = "bing_site_submit"
_GOOGLE_INDEXING_SUBMIT_TOOL_NAME = "google_indexing_submit"
_GOOGLE_INDEXING_BATCH_SUBMIT_TOOL_NAME = "google_indexing_batch_submit"
_GOOGLE_INDEXING_METADATA_TOOL_NAME = "google_indexing_metadata"
_GOOGLE_SITE_SUBMIT_TOOL_NAME = "google_site_submit"
_GOOGLE_SITEMAP_SUBMIT_TOOL_NAME = "google_sitemap_submit"
_SITE_ONBOARDING_SUBMIT_TOOL_NAME = "site_onboarding_submit"
_SITE_AUDIT_TOOL_NAME = "site_audit"
_SITE_OWNERSHIP_CHECK_TOOL_NAME = "site_ownership_check"
_SITE_OWNERSHIP_VERIFY_TOOL_NAME = "site_ownership_verify"
_SITE_REMEDIATION_APPLY_TOOL_NAME = "site_remediation_apply"
_BING_BACKLINK_INTELLIGENCE_TOOL_NAME = "bing_backlink_intelligence"
_ONBOARDING_GUIDE_TOOL_NAME = "onboarding_guide"
_GOOGLE_ANALYTICS_DATA_STREAMS_TOOL_NAME = "google_analytics_data_streams"
_GOOGLE_ANALYTICS_ACCOUNT_RENAME_TOOL_NAME = "google_analytics_account_rename"
_GOOGLE_ANALYTICS_PROPERTY_RENAME_TOOL_NAME = "google_analytics_property_rename"
_PAGESPEED_ANALYZE_TOOL_NAME = "pagespeed_analyze"
_SCHEMA_VALIDATE_HTML_TOOL_NAME = "schema_validate_html"
_SCHEMA_VALIDATE_JSON_LD_TOOL_NAME = "schema_validate_json_ld"
_SCHEMA_VALIDATE_URL_TOOL_NAME = "schema_validate_url"

_ONBOARDING_GUIDE_DESCRIPTION = (
    "Explain the onboarding steps only the operator can perform, and what to tell them."
)
_GOOGLE_ANALYTICS_DATA_STREAMS_DESCRIPTION = (
    "List one configured GA4 property's data streams and their measurement IDs."
)
_GOOGLE_ANALYTICS_ACCOUNT_RENAME_DESCRIPTION = "Rename one reachable Google Analytics account."
_GOOGLE_ANALYTICS_PROPERTY_RENAME_DESCRIPTION = "Rename one configured Google Analytics property."
_SERVER_INFO_DESCRIPTION = "Show non-sensitive Rankrat capability metadata."
_ACCOUNTS_LIST_DESCRIPTION = "List configured account summaries only."
_SITES_LIST_DESCRIPTION = "List configured site and property boundaries only."
_DIAGNOSTICS_DESCRIPTION = "Run local read-only diagnostics without provider calls."
_PROVIDER_READINESS_DESCRIPTION = "Check read-only access for one configured provider account."
_INDEXNOW_SUBMIT_DESCRIPTION = "Submit changed URLs to one configured IndexNow target."
_GOOGLE_SEARCH_ANALYTICS_QUERY_DESCRIPTION = "Query one configured Google Search Console property."
_GOOGLE_SEARCH_ANALYTICS_SUMMARY_DESCRIPTION = (
    "Summarize one configured Google Search Console period."
)
_GOOGLE_SEARCH_ANALYTICS_COMPARISON_DESCRIPTION = (
    "Compare two configured Google Search Console periods."
)
_GOOGLE_SEARCH_ANALYTICS_DIMENSION_REPORT_DESCRIPTION = (
    "Return one bounded fixed-dimension Google Search Console report."
)
_GOOGLE_SEARCH_ANALYTICS_DROP_ATTRIBUTION_DESCRIPTION = (
    "Attribute one bounded Google Search Console period change to fixed query or page keys."
)
_GOOGLE_SEARCH_ANALYTICS_TREND_DESCRIPTION = (
    "Return an ascending bounded daily Google Search Console trend."
)
_GOOGLE_SEARCH_ANALYTICS_ANOMALIES_DESCRIPTION = (
    "Return deterministic bounded daily Google Search Console anomalies."
)
_GOOGLE_SEARCH_ANALYTICS_PAGE_PERFORMANCE_DESCRIPTION = (
    "Return a bounded fixed-page Google Search Console performance report."
)
_GOOGLE_SITES_LIST_DESCRIPTION = (
    "List configured Google Search Console properties available upstream."
)
_GOOGLE_SITE_GET_DESCRIPTION = "Get one configured Google Search Console property."
_GOOGLE_SITEMAPS_LIST_DESCRIPTION = (
    "List sitemaps for one configured Google Search Console property."
)
_GOOGLE_SITEMAP_GET_DESCRIPTION = "Get one configured Google Search Console sitemap."
_GOOGLE_URL_INSPECTION_DESCRIPTION = (
    "Inspect one URL beneath a configured Google Search Console property."
)
_GOOGLE_URL_INSPECTION_BATCH_DESCRIPTION = (
    "Inspect a bounded set of URLs beneath one configured Google Search Console property."
)
_GOOGLE_ANALYTICS_REPORT_DESCRIPTION = "Run one configured GA4 historical report."
_GOOGLE_ANALYTICS_ACCOUNT_INVENTORY_DESCRIPTION = (
    "List GA4 accounts and properties visible to one discovery-enabled Google OAuth account."
)
_GOOGLE_ANALYTICS_REALTIME_REPORT_DESCRIPTION = "Run one configured GA4 realtime report."
_GOOGLE_ANALYTICS_CONTENT_PERFORMANCE_DESCRIPTION = (
    "Return fixed GA4 content performance for one configured property."
)
_GOOGLE_ANALYTICS_LANDING_PAGE_PERFORMANCE_DESCRIPTION = (
    "Return fixed GA4 landing-page performance for one configured property."
)
_GOOGLE_ANALYTICS_ORGANIC_SEARCH_LANDING_PAGES_DESCRIPTION = (
    "Return fixed GA4 Search Console-linked organic-search landing-page metrics."
)
_GOOGLE_ANALYTICS_TRAFFIC_SOURCE_PERFORMANCE_DESCRIPTION = (
    "Return fixed GA4 traffic-source performance for one configured property."
)
_GOOGLE_ANALYTICS_ECOMMERCE_PERFORMANCE_DESCRIPTION = (
    "Return fixed GA4 item-level ecommerce performance for one configured property."
)
_GOOGLE_ANALYTICS_AUDIENCE_SEGMENTS_DESCRIPTION = (
    "Return fixed GA4 audience-segment metrics for one configured property."
)
_GOOGLE_ANALYTICS_USER_BEHAVIOR_DESCRIPTION = (
    "Return fixed GA4 new-versus-returning engagement metrics for one configured property."
)
_GOOGLE_ANALYTICS_CONVERSION_FUNNEL_DESCRIPTION = (
    "Return a bounded closed GA4 event-step conversion funnel for one configured property."
)
_BING_KEYWORD_STATISTICS_DESCRIPTION = (
    "Return typed daily Bing keyword statistics for one configured account."
)
_BING_RELATED_KEYWORDS_DESCRIPTION = (
    "Return typed Bing related keywords for one configured account and date interval."
)
_BING_TRAFFIC_TREND_DESCRIPTION = "Return an ascending bounded daily Bing traffic trend."
_BING_TRAFFIC_ANOMALIES_DESCRIPTION = "Return deterministic bounded daily Bing traffic anomalies."
_BING_TRAFFIC_COMPARISON_DESCRIPTION = "Compare two bounded Bing traffic periods."
_BING_QUERY_PERFORMANCE_DESCRIPTION = (
    "Return typed top-query performance for one configured Bing site."
)
_BING_PAGE_PERFORMANCE_DESCRIPTION = (
    "Return typed top-page performance for one configured Bing site."
)
_BING_BRAND_ANALYSIS_DESCRIPTION = (
    "Classify one fixed Bing query report with bounded literal brand terms."
)
_BING_RANKING_BUCKETS_DESCRIPTION = (
    "Group one fixed Bing query report into local average-click-position buckets."
)
_BING_QUERY_OPPORTUNITIES_DESCRIPTION = (
    "Derive bounded local query opportunities from one configured Bing site."
)
_BING_PAGE_OPPORTUNITIES_DESCRIPTION = (
    "Derive bounded local page opportunities from one configured Bing site."
)
_BING_QUERY_PAGE_PERFORMANCE_DESCRIPTION = (
    "Return typed Bing page statistics for one bounded query."
)
_BING_QUERY_CANNIBALIZATION_DESCRIPTION = (
    "Return locally derived competing Bing pages for one configured query."
)
_BING_PAGE_QUERY_PERFORMANCE_DESCRIPTION = (
    "Return typed Bing query statistics for one configured child page."
)
_BING_URL_SUBMISSION_QUOTA_DESCRIPTION = (
    "Return typed remaining Bing URL-submission quotas for one configured site."
)
_BING_CRAWL_ISSUES_DESCRIPTION = "Return typed crawl issues for one configured Bing site."
_BING_CRAWL_STATS_DESCRIPTION = "Return typed daily crawl statistics for one configured Bing site."
_BING_FEEDS_DESCRIPTION = "Return typed sitemap and feed records for one configured Bing site."
_BING_LINK_COUNTS_DESCRIPTION = "Return one typed bounded Bing inbound-link-count page."
_BING_URL_INFORMATION_DESCRIPTION = (
    "Return typed indexing and crawl information for one configured Bing child URL."
)
_BING_URL_SUBMIT_DESCRIPTION = "Submit approved URLs to one configured Bing site."
_BING_SITEMAP_SUBMIT_DESCRIPTION = "Submit or delete one approved Bing sitemap."
_BING_SITE_SUBMIT_DESCRIPTION = "Add or delete one approved Bing property."
_GOOGLE_INDEXING_SUBMIT_DESCRIPTION = (
    "Publish one approved, eligible URL notification to Google Indexing."
)
_GOOGLE_INDEXING_BATCH_SUBMIT_DESCRIPTION = (
    "Publish one approved, eligible Google Indexing multipart notification batch."
)
_GOOGLE_INDEXING_METADATA_DESCRIPTION = (
    "Read Google Indexing notification receipt metadata for one configured URL."
)
_GOOGLE_SITE_SUBMIT_DESCRIPTION = "Add or delete one approved Google Search Console property."
_SITE_ONBOARDING_SUBMIT_DESCRIPTION = (
    "Create one approved GA4 property, Search Console property, and Bing site."
)
_SITE_AUDIT_DESCRIPTION = "Crawl and score one configured site under strict public-fetch bounds."
_SITE_OWNERSHIP_CHECK_DESCRIPTION = (
    "Check Google and Bing DNS ownership without returning verification tokens."
)
_SITE_OWNERSHIP_VERIFY_DESCRIPTION = (
    "Create provider-issued DNS records through the configured DNS adapter and redeem proofs."
)
_SITE_REMEDIATION_APPLY_DESCRIPTION = (
    "Resubmit a configured sitemap and changed URLs to Google and Bing."
)
_BING_BACKLINK_INTELLIGENCE_DESCRIPTION = (
    "Read bounded Bing backlinks with referring-domain and anchor summaries."
)
_GOOGLE_SITEMAP_SUBMIT_DESCRIPTION = "Submit or delete one approved Google Search Console sitemap."
_PAGESPEED_ANALYZE_DESCRIPTION = "Analyze one configured child URL with PageSpeed Insights."
_PAGESPEED_CORE_WEB_VITALS_DESCRIPTION = (
    "Return selected Chrome UX Core Web Vitals for one configured child URL."
)
_LIGHTHOUSE_AUDIT_DESCRIPTION = (
    "Run local Lighthouse performance, accessibility, best-practices, and SEO audits."
)
_LIGHTHOUSE_SEO_FINDINGS_DESCRIPTION = "Return failed SEO audits for one configured page."
_LIGHTHOUSE_ACCESSIBILITY_FINDINGS_DESCRIPTION = (
    "Return failed accessibility audits for one configured page."
)
_LIGHTHOUSE_PERFORMANCE_FINDINGS_DESCRIPTION = (
    "Return failed performance audits for one configured page."
)
_LIGHTHOUSE_BEST_PRACTICES_FINDINGS_DESCRIPTION = (
    "Return failed best-practices audits for one configured page."
)
_GA4_PAGESPEED_CORRELATION_DESCRIPTION = (
    "Pair one configured GA4 content row with one configured PageSpeed analysis."
)
_GA4_SEARCH_CONSOLE_COMPARISON_DESCRIPTION = (
    "Return separate configured GA4 organic-search and Search Console observations."
)
_SEARCH_ENGINE_COMPARISON_DESCRIPTION = (
    "Return separate configured Google Search Console and Bing traffic observations."
)
_SEARCH_ENGINE_TRAFFIC_HEALTH_DESCRIPTION = (
    "Return separate configured Google Search Console and Bing daily anomaly observations."
)
_SCHEMA_VALIDATE_HTML_DESCRIPTION = "Validate local HTML for Google Indexing eligibility."
_SCHEMA_VALIDATE_JSON_LD_DESCRIPTION = "Validate local JSON-LD for Google Indexing eligibility."
_SCHEMA_VALIDATE_URL_DESCRIPTION = (
    "Fetch one public HTTPS page under SSRF policy and validate Google Indexing eligibility."
)


@dataclass(frozen=True, slots=True)
class ToolAnnotations:
    """Explicit MCP semantics for a safe, read-only operation."""

    read_only_hint: bool = True
    destructive_hint: bool = False
    idempotent_hint: bool = True
    open_world_hint: bool = False

    def as_mcp(self) -> dict[str, bool]:
        """Return the official MCP annotation key names."""
        return {
            "readOnlyHint": self.read_only_hint,
            "destructiveHint": self.destructive_hint,
            "idempotentHint": self.idempotent_hint,
            "openWorldHint": self.open_world_hint,
        }


@dataclass(frozen=True, slots=True)
class ToolContract[InputT, OutputT]:
    """A typed operation descriptor that adapters can expose consistently."""

    name: str
    description: str
    input_type: type[InputT]
    output_type: type[OutputT]
    annotations: ToolAnnotations


_READ_ONLY_ANNOTATIONS = ToolAnnotations(True, False, True, False)
_LIGHTHOUSE_ANNOTATIONS = ToolAnnotations(True, False, True, True)
_INDEXNOW_WRITE_ANNOTATIONS = ToolAnnotations(False, True, False, False)

READ_ONLY_TOOL_CATALOG: tuple[ToolContract[object, object], ...] = (
    ToolContract(
        name=_SITE_AUDIT_TOOL_NAME,
        description=_SITE_AUDIT_DESCRIPTION,
        input_type=SiteAuditRequest,
        output_type=SiteAuditReport,
        annotations=_READ_ONLY_ANNOTATIONS,
    ),
    ToolContract(
        name=_SITE_OWNERSHIP_CHECK_TOOL_NAME,
        description=_SITE_OWNERSHIP_CHECK_DESCRIPTION,
        input_type=SiteOwnershipCheckRequest,
        output_type=SiteOwnershipReceipt,
        annotations=_READ_ONLY_ANNOTATIONS,
    ),
    ToolContract(
        name=_BING_BACKLINK_INTELLIGENCE_TOOL_NAME,
        description=_BING_BACKLINK_INTELLIGENCE_DESCRIPTION,
        input_type=BingBacklinkIntelligenceRequest,
        output_type=BingBacklinkIntelligenceReport,
        annotations=_READ_ONLY_ANNOTATIONS,
    ),
    ToolContract(
        name=_ONBOARDING_GUIDE_TOOL_NAME,
        description=_ONBOARDING_GUIDE_DESCRIPTION,
        input_type=OnboardingGuideRequest,
        output_type=OnboardingGuide,
        annotations=_READ_ONLY_ANNOTATIONS,
    ),
    ToolContract(
        name=_GOOGLE_ANALYTICS_DATA_STREAMS_TOOL_NAME,
        description=_GOOGLE_ANALYTICS_DATA_STREAMS_DESCRIPTION,
        input_type=Ga4DataStreamsRequest,
        output_type=Ga4DataStreamsReport,
        annotations=_READ_ONLY_ANNOTATIONS,
    ),
    ToolContract(
        name=_SCHEMA_VALIDATE_URL_TOOL_NAME,
        description=_SCHEMA_VALIDATE_URL_DESCRIPTION,
        input_type=PublicSchemaValidationRequest,
        output_type=PublicSchemaValidationReport,
        annotations=_READ_ONLY_ANNOTATIONS,
    ),
    ToolContract(
        name=_SCHEMA_VALIDATE_HTML_TOOL_NAME,
        description=_SCHEMA_VALIDATE_HTML_DESCRIPTION,
        input_type=LocalSchemaValidationRequest,
        output_type=IndexingEligibility,
        annotations=_READ_ONLY_ANNOTATIONS,
    ),
    ToolContract(
        name=_SCHEMA_VALIDATE_JSON_LD_TOOL_NAME,
        description=_SCHEMA_VALIDATE_JSON_LD_DESCRIPTION,
        input_type=LocalSchemaValidationRequest,
        output_type=IndexingEligibility,
        annotations=_READ_ONLY_ANNOTATIONS,
    ),
    ToolContract(
        name=_SERVER_INFO_TOOL_NAME,
        description=_SERVER_INFO_DESCRIPTION,
        input_type=ServerInfoRequest,
        output_type=ServerInfoResponse,
        annotations=_READ_ONLY_ANNOTATIONS,
    ),
    ToolContract(
        name=_GOOGLE_SEARCH_ANALYTICS_SUMMARY_TOOL_NAME,
        description=_GOOGLE_SEARCH_ANALYTICS_SUMMARY_DESCRIPTION,
        input_type=SearchAnalyticsSummaryRequest,
        output_type=SearchAnalyticsMetrics,
        annotations=_READ_ONLY_ANNOTATIONS,
    ),
    ToolContract(
        name=_GOOGLE_INDEXING_METADATA_TOOL_NAME,
        description=_GOOGLE_INDEXING_METADATA_DESCRIPTION,
        input_type=GoogleIndexingMetadataRequest,
        output_type=GoogleIndexingMetadata,
        annotations=_READ_ONLY_ANNOTATIONS,
    ),
    ToolContract(
        name=_GOOGLE_SEARCH_ANALYTICS_COMPARISON_TOOL_NAME,
        description=_GOOGLE_SEARCH_ANALYTICS_COMPARISON_DESCRIPTION,
        input_type=SearchAnalyticsComparisonRequest,
        output_type=SearchAnalyticsComparison,
        annotations=_READ_ONLY_ANNOTATIONS,
    ),
    ToolContract(
        name=_GOOGLE_SEARCH_ANALYTICS_DIMENSION_REPORT_TOOL_NAME,
        description=_GOOGLE_SEARCH_ANALYTICS_DIMENSION_REPORT_DESCRIPTION,
        input_type=SearchAnalyticsDimensionReportRequest,
        output_type=SearchAnalyticsDimensionReport,
        annotations=_READ_ONLY_ANNOTATIONS,
    ),
    ToolContract(
        name=_GOOGLE_SEARCH_ANALYTICS_DROP_ATTRIBUTION_TOOL_NAME,
        description=_GOOGLE_SEARCH_ANALYTICS_DROP_ATTRIBUTION_DESCRIPTION,
        input_type=SearchAnalyticsDropAttributionRequest,
        output_type=SearchAnalyticsDropAttributionReport,
        annotations=_READ_ONLY_ANNOTATIONS,
    ),
    ToolContract(
        name=_GOOGLE_SEARCH_ANALYTICS_TREND_TOOL_NAME,
        description=_GOOGLE_SEARCH_ANALYTICS_TREND_DESCRIPTION,
        input_type=SearchAnalyticsTrendRequest,
        output_type=SearchAnalyticsTrendReport,
        annotations=_READ_ONLY_ANNOTATIONS,
    ),
    ToolContract(
        name=_GOOGLE_SEARCH_ANALYTICS_ANOMALIES_TOOL_NAME,
        description=_GOOGLE_SEARCH_ANALYTICS_ANOMALIES_DESCRIPTION,
        input_type=SearchAnalyticsTrendRequest,
        output_type=SearchAnalyticsAnomalyReport,
        annotations=_READ_ONLY_ANNOTATIONS,
    ),
    ToolContract(
        name=_GOOGLE_SEARCH_ANALYTICS_PAGE_PERFORMANCE_TOOL_NAME,
        description=_GOOGLE_SEARCH_ANALYTICS_PAGE_PERFORMANCE_DESCRIPTION,
        input_type=SearchAnalyticsPagePerformanceRequest,
        output_type=SearchAnalyticsDimensionReport,
        annotations=_READ_ONLY_ANNOTATIONS,
    ),
    ToolContract(
        name=_GOOGLE_SITEMAP_GET_TOOL_NAME,
        description=_GOOGLE_SITEMAP_GET_DESCRIPTION,
        input_type=SitemapGetRequest,
        output_type=dict,
        annotations=_READ_ONLY_ANNOTATIONS,
    ),
    ToolContract(
        name=_ACCOUNTS_LIST_TOOL_NAME,
        description=_ACCOUNTS_LIST_DESCRIPTION,
        input_type=AccountsListRequest,
        output_type=AccountsListResponse,
        annotations=_READ_ONLY_ANNOTATIONS,
    ),
    ToolContract(
        name=_SITES_LIST_TOOL_NAME,
        description=_SITES_LIST_DESCRIPTION,
        input_type=SitesListRequest,
        output_type=SitesListResponse,
        annotations=_READ_ONLY_ANNOTATIONS,
    ),
    ToolContract(
        name=_DIAGNOSTICS_TOOL_NAME,
        description=_DIAGNOSTICS_DESCRIPTION,
        input_type=DiagnosticsRequest,
        output_type=DiagnosticsResponse,
        annotations=_READ_ONLY_ANNOTATIONS,
    ),
    ToolContract(
        name=_PROVIDER_READINESS_TOOL_NAME,
        description=_PROVIDER_READINESS_DESCRIPTION,
        input_type=ProviderReadinessRequest,
        output_type=ProviderReadiness,
        annotations=_READ_ONLY_ANNOTATIONS,
    ),
    ToolContract(
        name=_GOOGLE_SEARCH_ANALYTICS_QUERY_TOOL_NAME,
        description=_GOOGLE_SEARCH_ANALYTICS_QUERY_DESCRIPTION,
        input_type=SearchAnalyticsRequest,
        output_type=dict,
        annotations=_READ_ONLY_ANNOTATIONS,
    ),
    ToolContract(
        name=_GOOGLE_SITES_LIST_TOOL_NAME,
        description=_GOOGLE_SITES_LIST_DESCRIPTION,
        input_type=SiteListRequest,
        output_type=tuple,
        annotations=_READ_ONLY_ANNOTATIONS,
    ),
    ToolContract(
        name=_GOOGLE_SITE_GET_TOOL_NAME,
        description=_GOOGLE_SITE_GET_DESCRIPTION,
        input_type=SiteGetRequest,
        output_type=dict,
        annotations=_READ_ONLY_ANNOTATIONS,
    ),
    ToolContract(
        name=_GOOGLE_SITEMAPS_LIST_TOOL_NAME,
        description=_GOOGLE_SITEMAPS_LIST_DESCRIPTION,
        input_type=SitemapListRequest,
        output_type=dict,
        annotations=_READ_ONLY_ANNOTATIONS,
    ),
    ToolContract(
        name=_GOOGLE_URL_INSPECTION_TOOL_NAME,
        description=_GOOGLE_URL_INSPECTION_DESCRIPTION,
        input_type=UrlInspectionRequest,
        output_type=dict,
        annotations=_READ_ONLY_ANNOTATIONS,
    ),
    ToolContract(
        name=_GOOGLE_URL_INSPECTION_BATCH_TOOL_NAME,
        description=_GOOGLE_URL_INSPECTION_BATCH_DESCRIPTION,
        input_type=UrlInspectionBatchRequest,
        output_type=tuple,
        annotations=_READ_ONLY_ANNOTATIONS,
    ),
    ToolContract(
        name=GOOGLE_ANALYTICS_ACCOUNT_INVENTORY_OPERATION,
        description=_GOOGLE_ANALYTICS_ACCOUNT_INVENTORY_DESCRIPTION,
        input_type=Ga4AccountDiscoveryRequest,
        output_type=tuple[Ga4AccountSummary, ...],
        annotations=_READ_ONLY_ANNOTATIONS,
    ),
    ToolContract(
        name=_GOOGLE_ANALYTICS_REPORT_TOOL_NAME,
        description=_GOOGLE_ANALYTICS_REPORT_DESCRIPTION,
        input_type=Ga4ReportRequest,
        output_type=Ga4ReportResult,
        annotations=_READ_ONLY_ANNOTATIONS,
    ),
    ToolContract(
        name=_GOOGLE_ANALYTICS_REALTIME_REPORT_TOOL_NAME,
        description=_GOOGLE_ANALYTICS_REALTIME_REPORT_DESCRIPTION,
        input_type=Ga4RealtimeReportRequest,
        output_type=Ga4ReportResult,
        annotations=_READ_ONLY_ANNOTATIONS,
    ),
    ToolContract(
        name=_GOOGLE_ANALYTICS_CONTENT_PERFORMANCE_TOOL_NAME,
        description=_GOOGLE_ANALYTICS_CONTENT_PERFORMANCE_DESCRIPTION,
        input_type=Ga4FixedReportRequest,
        output_type=Ga4FixedReport,
        annotations=_READ_ONLY_ANNOTATIONS,
    ),
    ToolContract(
        name=_GOOGLE_ANALYTICS_LANDING_PAGE_PERFORMANCE_TOOL_NAME,
        description=_GOOGLE_ANALYTICS_LANDING_PAGE_PERFORMANCE_DESCRIPTION,
        input_type=Ga4FixedReportRequest,
        output_type=Ga4FixedReport,
        annotations=_READ_ONLY_ANNOTATIONS,
    ),
    ToolContract(
        name=_GOOGLE_ANALYTICS_ORGANIC_SEARCH_LANDING_PAGES_TOOL_NAME,
        description=_GOOGLE_ANALYTICS_ORGANIC_SEARCH_LANDING_PAGES_DESCRIPTION,
        input_type=Ga4FixedReportRequest,
        output_type=Ga4FixedReport,
        annotations=_READ_ONLY_ANNOTATIONS,
    ),
    ToolContract(
        name=_GOOGLE_ANALYTICS_TRAFFIC_SOURCE_PERFORMANCE_TOOL_NAME,
        description=_GOOGLE_ANALYTICS_TRAFFIC_SOURCE_PERFORMANCE_DESCRIPTION,
        input_type=Ga4FixedReportRequest,
        output_type=Ga4FixedReport,
        annotations=_READ_ONLY_ANNOTATIONS,
    ),
    ToolContract(
        name=_GOOGLE_ANALYTICS_ECOMMERCE_PERFORMANCE_TOOL_NAME,
        description=_GOOGLE_ANALYTICS_ECOMMERCE_PERFORMANCE_DESCRIPTION,
        input_type=Ga4FixedReportRequest,
        output_type=Ga4FixedReport,
        annotations=_READ_ONLY_ANNOTATIONS,
    ),
    ToolContract(
        name=_GOOGLE_ANALYTICS_AUDIENCE_SEGMENTS_TOOL_NAME,
        description=_GOOGLE_ANALYTICS_AUDIENCE_SEGMENTS_DESCRIPTION,
        input_type=Ga4FixedReportRequest,
        output_type=Ga4FixedReport,
        annotations=_READ_ONLY_ANNOTATIONS,
    ),
    ToolContract(
        name=_GOOGLE_ANALYTICS_USER_BEHAVIOR_TOOL_NAME,
        description=_GOOGLE_ANALYTICS_USER_BEHAVIOR_DESCRIPTION,
        input_type=Ga4FixedReportRequest,
        output_type=Ga4FixedReport,
        annotations=_READ_ONLY_ANNOTATIONS,
    ),
    ToolContract(
        name=_GOOGLE_ANALYTICS_CONVERSION_FUNNEL_TOOL_NAME,
        description=_GOOGLE_ANALYTICS_CONVERSION_FUNNEL_DESCRIPTION,
        input_type=Ga4ConversionFunnelRequest,
        output_type=Ga4FunnelReport,
        annotations=_READ_ONLY_ANNOTATIONS,
    ),
    ToolContract(
        name=_PAGESPEED_ANALYZE_TOOL_NAME,
        description=_PAGESPEED_ANALYZE_DESCRIPTION,
        input_type=PageSpeedAnalysisRequest,
        output_type=PageSpeedAnalysisReport,
        annotations=_READ_ONLY_ANNOTATIONS,
    ),
    ToolContract(
        name=PAGESPEED_CORE_WEB_VITALS_OPERATION,
        description=_PAGESPEED_CORE_WEB_VITALS_DESCRIPTION,
        input_type=PageSpeedAnalysisRequest,
        output_type=PageSpeedCoreWebVitalsReport,
        annotations=_READ_ONLY_ANNOTATIONS,
    ),
    ToolContract(
        name=LIGHTHOUSE_AUDIT_OPERATION,
        description=_LIGHTHOUSE_AUDIT_DESCRIPTION,
        input_type=LighthouseAuditRequest,
        output_type=LighthouseAuditReport,
        annotations=_LIGHTHOUSE_ANNOTATIONS,
    ),
    ToolContract(
        name=LIGHTHOUSE_SEO_FINDINGS_OPERATION,
        description=_LIGHTHOUSE_SEO_FINDINGS_DESCRIPTION,
        input_type=LighthouseAuditRequest,
        output_type=LighthouseAuditReport,
        annotations=_LIGHTHOUSE_ANNOTATIONS,
    ),
    ToolContract(
        name=LIGHTHOUSE_ACCESSIBILITY_FINDINGS_OPERATION,
        description=_LIGHTHOUSE_ACCESSIBILITY_FINDINGS_DESCRIPTION,
        input_type=LighthouseAuditRequest,
        output_type=LighthouseAuditReport,
        annotations=_LIGHTHOUSE_ANNOTATIONS,
    ),
    ToolContract(
        name=LIGHTHOUSE_PERFORMANCE_FINDINGS_OPERATION,
        description=_LIGHTHOUSE_PERFORMANCE_FINDINGS_DESCRIPTION,
        input_type=LighthouseAuditRequest,
        output_type=LighthouseAuditReport,
        annotations=_LIGHTHOUSE_ANNOTATIONS,
    ),
    ToolContract(
        name=LIGHTHOUSE_BEST_PRACTICES_FINDINGS_OPERATION,
        description=_LIGHTHOUSE_BEST_PRACTICES_FINDINGS_DESCRIPTION,
        input_type=LighthouseAuditRequest,
        output_type=LighthouseAuditReport,
        annotations=_LIGHTHOUSE_ANNOTATIONS,
    ),
    ToolContract(
        name=GA4_PAGESPEED_CORRELATION_OPERATION,
        description=_GA4_PAGESPEED_CORRELATION_DESCRIPTION,
        input_type=Ga4PageSpeedCorrelationRequest,
        output_type=Ga4PageSpeedCorrelationReport,
        annotations=_READ_ONLY_ANNOTATIONS,
    ),
    ToolContract(
        name=GA4_SEARCH_CONSOLE_COMPARISON_OPERATION,
        description=_GA4_SEARCH_CONSOLE_COMPARISON_DESCRIPTION,
        input_type=Ga4SearchConsoleComparisonRequest,
        output_type=Ga4SearchConsoleComparisonReport,
        annotations=_READ_ONLY_ANNOTATIONS,
    ),
    ToolContract(
        name=SEARCH_ENGINE_COMPARISON_OPERATION,
        description=_SEARCH_ENGINE_COMPARISON_DESCRIPTION,
        input_type=SearchEngineComparisonRequest,
        output_type=SearchEngineComparisonReport,
        annotations=_READ_ONLY_ANNOTATIONS,
    ),
    ToolContract(
        name=SEARCH_ENGINE_TRAFFIC_HEALTH_OPERATION,
        description=_SEARCH_ENGINE_TRAFFIC_HEALTH_DESCRIPTION,
        input_type=SearchEngineTrafficHealthRequest,
        output_type=SearchEngineTrafficHealthReport,
        annotations=_READ_ONLY_ANNOTATIONS,
    ),
    ToolContract(
        name=_BING_KEYWORD_STATISTICS_TOOL_NAME,
        description=_BING_KEYWORD_STATISTICS_DESCRIPTION,
        input_type=BingKeywordStatisticsRequest,
        output_type=BingKeywordStatisticsReport,
        annotations=_READ_ONLY_ANNOTATIONS,
    ),
    ToolContract(
        name=_BING_RELATED_KEYWORDS_TOOL_NAME,
        description=_BING_RELATED_KEYWORDS_DESCRIPTION,
        input_type=BingRelatedKeywordsRequest,
        output_type=BingRelatedKeywordsReport,
        annotations=_READ_ONLY_ANNOTATIONS,
    ),
    ToolContract(
        name=_BING_TRAFFIC_TREND_TOOL_NAME,
        description=_BING_TRAFFIC_TREND_DESCRIPTION,
        input_type=BingTrafficPeriodRequest,
        output_type=BingTrafficTrendReport,
        annotations=_READ_ONLY_ANNOTATIONS,
    ),
    ToolContract(
        name=_BING_TRAFFIC_ANOMALIES_TOOL_NAME,
        description=_BING_TRAFFIC_ANOMALIES_DESCRIPTION,
        input_type=BingTrafficPeriodRequest,
        output_type=BingTrafficAnomalyReport,
        annotations=_READ_ONLY_ANNOTATIONS,
    ),
    ToolContract(
        name=_BING_TRAFFIC_COMPARISON_TOOL_NAME,
        description=_BING_TRAFFIC_COMPARISON_DESCRIPTION,
        input_type=BingTrafficComparisonRequest,
        output_type=BingTrafficComparison,
        annotations=_READ_ONLY_ANNOTATIONS,
    ),
    ToolContract(
        name=_BING_QUERY_PERFORMANCE_TOOL_NAME,
        description=_BING_QUERY_PERFORMANCE_DESCRIPTION,
        input_type=BingPerformanceRequest,
        output_type=BingPerformanceReport,
        annotations=_READ_ONLY_ANNOTATIONS,
    ),
    ToolContract(
        name=_BING_PAGE_PERFORMANCE_TOOL_NAME,
        description=_BING_PAGE_PERFORMANCE_DESCRIPTION,
        input_type=BingPerformanceRequest,
        output_type=BingPerformanceReport,
        annotations=_READ_ONLY_ANNOTATIONS,
    ),
    ToolContract(
        name=_BING_BRAND_ANALYSIS_TOOL_NAME,
        description=_BING_BRAND_ANALYSIS_DESCRIPTION,
        input_type=BingBrandAnalysisRequest,
        output_type=BingBrandAnalysisReport,
        annotations=_READ_ONLY_ANNOTATIONS,
    ),
    ToolContract(
        name=_BING_RANKING_BUCKETS_TOOL_NAME,
        description=_BING_RANKING_BUCKETS_DESCRIPTION,
        input_type=BingPerformanceRequest,
        output_type=BingRankingBucketsReport,
        annotations=_READ_ONLY_ANNOTATIONS,
    ),
    ToolContract(
        name=_BING_QUERY_OPPORTUNITIES_TOOL_NAME,
        description=_BING_QUERY_OPPORTUNITIES_DESCRIPTION,
        input_type=BingPerformanceRequest,
        output_type=BingPerformanceOpportunityReport,
        annotations=_READ_ONLY_ANNOTATIONS,
    ),
    ToolContract(
        name=_BING_PAGE_OPPORTUNITIES_TOOL_NAME,
        description=_BING_PAGE_OPPORTUNITIES_DESCRIPTION,
        input_type=BingPerformanceRequest,
        output_type=BingPerformanceOpportunityReport,
        annotations=_READ_ONLY_ANNOTATIONS,
    ),
    ToolContract(
        name=BING_OPPORTUNITY_MATRIX_OPERATION,
        description=_BING_OPPORTUNITY_MATRIX_DESCRIPTION,
        input_type=BingPerformanceRequest,
        output_type=BingOpportunityMatrixReport,
        annotations=_READ_ONLY_ANNOTATIONS,
    ),
    ToolContract(
        name=_BING_QUERY_PAGE_PERFORMANCE_TOOL_NAME,
        description=_BING_QUERY_PAGE_PERFORMANCE_DESCRIPTION,
        input_type=BingQueryPagePerformanceRequest,
        output_type=BingPerformanceReport,
        annotations=_READ_ONLY_ANNOTATIONS,
    ),
    ToolContract(
        name=_BING_QUERY_CANNIBALIZATION_TOOL_NAME,
        description=_BING_QUERY_CANNIBALIZATION_DESCRIPTION,
        input_type=BingQueryPagePerformanceRequest,
        output_type=BingQueryCannibalizationReport,
        annotations=_READ_ONLY_ANNOTATIONS,
    ),
    ToolContract(
        name=_BING_PAGE_QUERY_PERFORMANCE_TOOL_NAME,
        description=_BING_PAGE_QUERY_PERFORMANCE_DESCRIPTION,
        input_type=BingPageQueryPerformanceRequest,
        output_type=BingPerformanceReport,
        annotations=_READ_ONLY_ANNOTATIONS,
    ),
    ToolContract(
        name=_BING_URL_SUBMISSION_QUOTA_TOOL_NAME,
        description=_BING_URL_SUBMISSION_QUOTA_DESCRIPTION,
        input_type=BingUrlSubmissionQuotaRequest,
        output_type=BingUrlSubmissionQuotaReport,
        annotations=_READ_ONLY_ANNOTATIONS,
    ),
    ToolContract(
        name=_BING_CRAWL_ISSUES_TOOL_NAME,
        description=_BING_CRAWL_ISSUES_DESCRIPTION,
        input_type=BingCrawlIssuesRequest,
        output_type=BingCrawlIssuesReport,
        annotations=_READ_ONLY_ANNOTATIONS,
    ),
    ToolContract(
        name=_BING_CRAWL_STATS_TOOL_NAME,
        description=_BING_CRAWL_STATS_DESCRIPTION,
        input_type=BingCrawlStatsRequest,
        output_type=BingCrawlStatsReport,
        annotations=_READ_ONLY_ANNOTATIONS,
    ),
    ToolContract(
        name=_BING_FEEDS_TOOL_NAME,
        description=_BING_FEEDS_DESCRIPTION,
        input_type=BingFeedsRequest,
        output_type=BingFeedsReport,
        annotations=_READ_ONLY_ANNOTATIONS,
    ),
    ToolContract(
        name=_BING_LINK_COUNTS_TOOL_NAME,
        description=_BING_LINK_COUNTS_DESCRIPTION,
        input_type=BingLinkCountsRequest,
        output_type=BingLinkCountsReport,
        annotations=_READ_ONLY_ANNOTATIONS,
    ),
    ToolContract(
        name=_BING_URL_INFORMATION_TOOL_NAME,
        description=_BING_URL_INFORMATION_DESCRIPTION,
        input_type=BingUrlInformationRequest,
        output_type=BingUrlInformationReport,
        annotations=_READ_ONLY_ANNOTATIONS,
    ),
)

INDEXNOW_TOOL_CONTRACT = cast(
    ToolContract[object, object],
    ToolContract(
        name=_INDEXNOW_SUBMIT_TOOL_NAME,
        description=_INDEXNOW_SUBMIT_DESCRIPTION,
        input_type=IndexNowSubmissionRequest,
        output_type=IndexNowSubmissionResponse,
        annotations=_INDEXNOW_WRITE_ANNOTATIONS,
    ),
)

BING_URL_SUBMIT_TOOL_CONTRACT = cast(
    ToolContract[object, object],
    ToolContract(
        name=_BING_URL_SUBMIT_TOOL_NAME,
        description=_BING_URL_SUBMIT_DESCRIPTION,
        input_type=BingUrlSubmissionRequest,
        output_type=BingUrlSubmissionResponse,
        annotations=_INDEXNOW_WRITE_ANNOTATIONS,
    ),
)

BING_SITEMAP_SUBMIT_TOOL_CONTRACT = cast(
    ToolContract[object, object],
    ToolContract(
        name=_BING_SITEMAP_SUBMIT_TOOL_NAME,
        description=_BING_SITEMAP_SUBMIT_DESCRIPTION,
        input_type=BingSitemapSubmissionRequest,
        output_type=BingSitemapSubmissionResponse,
        annotations=_INDEXNOW_WRITE_ANNOTATIONS,
    ),
)

BING_SITE_SUBMIT_TOOL_CONTRACT = cast(
    ToolContract[object, object],
    ToolContract(
        name=_BING_SITE_SUBMIT_TOOL_NAME,
        description=_BING_SITE_SUBMIT_DESCRIPTION,
        input_type=BingSiteSubmissionRequest,
        output_type=BingSiteSubmissionResponse,
        annotations=_INDEXNOW_WRITE_ANNOTATIONS,
    ),
)

GOOGLE_INDEXING_SUBMIT_TOOL_CONTRACT = cast(
    ToolContract[object, object],
    ToolContract(
        name=_GOOGLE_INDEXING_SUBMIT_TOOL_NAME,
        description=_GOOGLE_INDEXING_SUBMIT_DESCRIPTION,
        input_type=GoogleIndexingSubmissionRequest,
        output_type=GoogleIndexingPublishReceipt,
        annotations=_INDEXNOW_WRITE_ANNOTATIONS,
    ),
)

GOOGLE_INDEXING_BATCH_SUBMIT_TOOL_CONTRACT = cast(
    ToolContract[object, object],
    ToolContract(
        name=_GOOGLE_INDEXING_BATCH_SUBMIT_TOOL_NAME,
        description=_GOOGLE_INDEXING_BATCH_SUBMIT_DESCRIPTION,
        input_type=GoogleIndexingBatchSubmissionRequest,
        output_type=GoogleIndexingBatchSubmission,
        annotations=_INDEXNOW_WRITE_ANNOTATIONS,
    ),
)

GOOGLE_SITE_SUBMIT_TOOL_CONTRACT = cast(
    ToolContract[object, object],
    ToolContract(
        name=_GOOGLE_SITE_SUBMIT_TOOL_NAME,
        description=_GOOGLE_SITE_SUBMIT_DESCRIPTION,
        input_type=GoogleSiteSubmissionRequest,
        output_type=GoogleSiteSubmissionResponse,
        annotations=_INDEXNOW_WRITE_ANNOTATIONS,
    ),
)

GOOGLE_SITEMAP_SUBMIT_TOOL_CONTRACT = cast(
    ToolContract[object, object],
    ToolContract(
        name=_GOOGLE_SITEMAP_SUBMIT_TOOL_NAME,
        description=_GOOGLE_SITEMAP_SUBMIT_DESCRIPTION,
        input_type=GoogleSitemapSubmissionRequest,
        output_type=GoogleSitemapSubmissionResponse,
        annotations=_INDEXNOW_WRITE_ANNOTATIONS,
    ),
)

GOOGLE_ANALYTICS_ACCOUNT_RENAME_TOOL_CONTRACT = cast(
    ToolContract[object, object],
    ToolContract(
        name=_GOOGLE_ANALYTICS_ACCOUNT_RENAME_TOOL_NAME,
        description=_GOOGLE_ANALYTICS_ACCOUNT_RENAME_DESCRIPTION,
        input_type=Ga4AccountRenameRequest,
        output_type=Ga4RenamedResource,
        annotations=_INDEXNOW_WRITE_ANNOTATIONS,
    ),
)

GOOGLE_ANALYTICS_PROPERTY_RENAME_TOOL_CONTRACT = cast(
    ToolContract[object, object],
    ToolContract(
        name=_GOOGLE_ANALYTICS_PROPERTY_RENAME_TOOL_NAME,
        description=_GOOGLE_ANALYTICS_PROPERTY_RENAME_DESCRIPTION,
        input_type=Ga4PropertyRenameRequest,
        output_type=Ga4RenamedResource,
        annotations=_INDEXNOW_WRITE_ANNOTATIONS,
    ),
)

SITE_ONBOARDING_SUBMIT_TOOL_CONTRACT = cast(
    ToolContract[object, object],
    ToolContract(
        name=_SITE_ONBOARDING_SUBMIT_TOOL_NAME,
        description=_SITE_ONBOARDING_SUBMIT_DESCRIPTION,
        input_type=SiteOnboardingSubmissionRequest,
        output_type=SiteOnboardingReceipt,
        annotations=_INDEXNOW_WRITE_ANNOTATIONS,
    ),
)

SITE_OWNERSHIP_VERIFY_TOOL_CONTRACT = cast(
    ToolContract[object, object],
    ToolContract(
        name=_SITE_OWNERSHIP_VERIFY_TOOL_NAME,
        description=_SITE_OWNERSHIP_VERIFY_DESCRIPTION,
        input_type=SiteOwnershipVerificationRequest,
        output_type=SiteOwnershipReceipt,
        annotations=_INDEXNOW_WRITE_ANNOTATIONS,
    ),
)

SITE_REMEDIATION_APPLY_TOOL_CONTRACT = cast(
    ToolContract[object, object],
    ToolContract(
        name=_SITE_REMEDIATION_APPLY_TOOL_NAME,
        description=_SITE_REMEDIATION_APPLY_DESCRIPTION,
        input_type=SiteRemediationRequest,
        output_type=SiteRemediationReceipt,
        annotations=_INDEXNOW_WRITE_ANNOTATIONS,
    ),
)


def tool_catalog(
    writes_enabled: bool,
) -> tuple[ToolContract[object, object], ...]:
    """Expose write tools only when the immutable startup settings permit them."""
    if writes_enabled:
        write_catalog = (
            *READ_ONLY_TOOL_CATALOG,
            INDEXNOW_TOOL_CONTRACT,
            BING_URL_SUBMIT_TOOL_CONTRACT,
            BING_SITEMAP_SUBMIT_TOOL_CONTRACT,
            BING_SITE_SUBMIT_TOOL_CONTRACT,
            GOOGLE_INDEXING_SUBMIT_TOOL_CONTRACT,
            GOOGLE_INDEXING_BATCH_SUBMIT_TOOL_CONTRACT,
            GOOGLE_SITE_SUBMIT_TOOL_CONTRACT,
            GOOGLE_SITEMAP_SUBMIT_TOOL_CONTRACT,
            GOOGLE_ANALYTICS_ACCOUNT_RENAME_TOOL_CONTRACT,
            GOOGLE_ANALYTICS_PROPERTY_RENAME_TOOL_CONTRACT,
            SITE_OWNERSHIP_VERIFY_TOOL_CONTRACT,
            SITE_REMEDIATION_APPLY_TOOL_CONTRACT,
            SITE_ONBOARDING_SUBMIT_TOOL_CONTRACT,
        )
        return write_catalog
    return READ_ONLY_TOOL_CATALOG
