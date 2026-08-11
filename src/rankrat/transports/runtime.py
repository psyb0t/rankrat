"""Shared application services for every Rankrat transport."""

from __future__ import annotations

from dataclasses import dataclass

from rankrat import __version__
from rankrat.config import Settings
from rankrat.constants import GOOGLE_SITE_VERIFICATION_SCOPE
from rankrat.operator.content_opportunities import ContentOpportunityOperator
from rankrat.operator.internal_links import InternalLinkOperator
from rankrat.operator.monitoring import MonitoringOperator
from rankrat.operator.site_onboarding import SiteOnboardingOperator
from rankrat.operator.site_ownership import SiteOwnershipOperator
from rankrat.policy.boundaries import BoundaryPolicy
from rankrat.providers.bing import BingWebmasterClient
from rankrat.providers.cloudflare import CloudflareDnsClient
from rankrat.providers.cloudflare_performance import CloudflarePerformanceClient
from rankrat.providers.crux import CruxHistoryClient
from rankrat.providers.dns import PublicDnsClient
from rankrat.providers.google_analytics import (
    GOOGLE_ANALYTICS_READ_SCOPE,
    GoogleAnalyticsDataClient,
)
from rankrat.providers.google_analytics_admin import (
    GOOGLE_ANALYTICS_EDIT_SCOPE,
    GoogleAnalyticsAdminClient,
)
from rankrat.providers.google_indexing import GOOGLE_INDEXING_SCOPE, GoogleIndexingClient
from rankrat.providers.google_search_console import (
    SEARCH_CONSOLE_WRITE_SCOPE,
    GoogleConfiguredTokenProvider,
    GoogleSearchConsoleClient,
)
from rankrat.providers.google_site_verification import GoogleSiteVerificationClient
from rankrat.providers.lighthouse import LighthouseWorkerClient
from rankrat.providers.pagespeed import PageSpeedClient
from rankrat.providers.schema_fetch import PublicSchemaFetcher
from rankrat.providers.site_fetch import PublicSiteFetcher
from rankrat.services.bing import BingWebmasterService
from rankrat.services.capabilities import CapabilityService
from rankrat.services.cloudflare_performance import CloudflarePerformanceService
from rankrat.services.cross_provider import CrossProviderService
from rankrat.services.crux import CruxHistoryService
from rankrat.services.diagnostics import DiagnosticsService
from rankrat.services.google_analytics import GoogleAnalyticsDataService
from rankrat.services.google_analytics_admin import GoogleAnalyticsAdminService
from rankrat.services.google_indexing import GoogleIndexingService
from rankrat.services.google_indexing_metadata import GoogleIndexingMetadataService
from rankrat.services.google_search_console import GoogleSearchConsoleService
from rankrat.services.google_sitemaps import GoogleSitemapService
from rankrat.services.google_sites import GoogleSiteService
from rankrat.services.indexnow import IndexNowService
from rankrat.services.lighthouse import LighthouseService
from rankrat.services.onboarding_guide import OnboardingGuideService
from rankrat.services.pagespeed import PageSpeedService
from rankrat.services.provider_readiness import ProviderReadinessService
from rankrat.services.schema import LocalSchemaValidationService
from rankrat.services.site_audit import SiteAuditService
from rankrat.services.site_onboarding import SiteOnboardingService
from rankrat.services.site_ownership import SiteOwnershipService
from rankrat.services.site_remediation import SiteRemediationService
from rankrat.services.sites import SitesService
from rankrat.state.sqlite import SQLiteStateRepository


@dataclass(frozen=True, slots=True)
class ApplicationServices:
    """The only application-service set exposed to transport adapters."""

    capabilities: CapabilityService
    cross_provider: CrossProviderService
    diagnostics: DiagnosticsService
    bing_webmaster: BingWebmasterService
    google_analytics: GoogleAnalyticsDataService
    google_indexing_metadata: GoogleIndexingMetadataService
    google_search_console: GoogleSearchConsoleService
    pagespeed: PageSpeedService
    lighthouse: LighthouseService
    local_schema: LocalSchemaValidationService
    provider_readiness: ProviderReadinessService
    sites: SitesService
    onboarding_guide: OnboardingGuideService
    google_analytics_admin: GoogleAnalyticsAdminService
    monitoring: MonitoringOperator
    internal_links: InternalLinkOperator
    crux: CruxHistoryService
    cloudflare_performance: CloudflarePerformanceService
    content_opportunities: ContentOpportunityOperator
    writes_enabled: bool = False
    indexnow: IndexNowService | None = None
    google_indexing: GoogleIndexingService | None = None
    google_sites: GoogleSiteService | None = None
    google_sitemaps: GoogleSitemapService | None = None
    site_onboarding: SiteOnboardingService | None = None
    site_ownership: SiteOwnershipService | None = None
    site_remediation: SiteRemediationService | None = None
    site_audit: SiteAuditService | None = None


def build_services(settings: Settings) -> ApplicationServices:
    """Build configured services from one immutable boundary policy."""
    policy = BoundaryPolicy.from_file(
        settings.boundary_file,
        settings.secret_root,
        settings.oauth_token_root,
    )
    google_client = GoogleSearchConsoleClient(
        policy,
        GoogleConfiguredTokenProvider(policy),
    )
    google_analytics_client = GoogleAnalyticsDataClient(
        policy,
        GoogleConfiguredTokenProvider(policy, (GOOGLE_ANALYTICS_READ_SCOPE,)),
    )
    google_indexing_read_client = GoogleSearchConsoleClient(
        policy,
        GoogleConfiguredTokenProvider(policy, (GOOGLE_INDEXING_SCOPE,)),
    )
    google_indexing_metadata = GoogleIndexingMetadataService(
        policy,
        GoogleIndexingClient(google_indexing_read_client),
    )
    bing_client = BingWebmasterClient(policy)
    cloudflare_client = CloudflareDnsClient(policy)
    pagespeed_client = PageSpeedClient(policy)
    crux_client = CruxHistoryClient(policy)
    cloudflare_performance_client = CloudflarePerformanceClient(policy)
    indexnow = None
    google_indexing = None
    google_sites = None
    google_sitemaps = None
    site_onboarding = None
    site_ownership = SiteOwnershipService(
        SiteOwnershipOperator(
            policy,
            GoogleSiteVerificationClient(
                policy,
                GoogleConfiguredTokenProvider(policy, (GOOGLE_SITE_VERIFICATION_SCOPE,)),
            ),
            bing_client,
            {cloudflare_client.provider: cloudflare_client},
            PublicDnsClient(),
        )
    )
    site_remediation = None
    if settings.writes_enabled:
        from rankrat.providers.indexnow import IndexNowClient

        indexnow = IndexNowService(
            policy,
            IndexNowClient(policy),
        )
        indexing_client = GoogleSearchConsoleClient(
            policy,
            GoogleConfiguredTokenProvider(policy, (GOOGLE_INDEXING_SCOPE,)),
        )
        google_indexing = GoogleIndexingService(
            policy,
            GoogleIndexingClient(indexing_client),
            PublicSchemaFetcher(),
        )
        site_client = GoogleSearchConsoleClient(
            policy,
            GoogleConfiguredTokenProvider(policy, (SEARCH_CONSOLE_WRITE_SCOPE,)),
        )
        google_sites = GoogleSiteService(
            policy,
            site_client,
        )
        sitemap_client = GoogleSearchConsoleClient(
            policy,
            GoogleConfiguredTokenProvider(policy, (SEARCH_CONSOLE_WRITE_SCOPE,)),
        )
        google_sitemaps = GoogleSitemapService(
            policy,
            sitemap_client,
        )
        site_remediation = SiteRemediationService(
            policy,
            sitemap_client,
            bing_client,
        )
    if settings.writes_enabled:
        site_onboarding = SiteOnboardingService(
            SiteOnboardingOperator(
                settings.boundary_file,
                policy,
                GoogleAnalyticsAdminClient(
                    policy,
                    GoogleConfiguredTokenProvider(policy, (GOOGLE_ANALYTICS_EDIT_SCOPE,)),
                ),
                google_analytics_client,
                GoogleSearchConsoleClient(
                    policy,
                    GoogleConfiguredTokenProvider(policy, (SEARCH_CONSOLE_WRITE_SCOPE,)),
                ),
                bing_client,
            ),
        )
    google_analytics = GoogleAnalyticsDataService(policy, google_analytics_client)
    google_search_console = GoogleSearchConsoleService(policy, google_client)
    bing_webmaster = BingWebmasterService(policy, bing_client)
    pagespeed = PageSpeedService(policy, pagespeed_client)
    lighthouse = LighthouseService(
        policy,
        LighthouseWorkerClient(settings.lighthouse_worker_socket),
    )
    site_audit = SiteAuditService(policy, PublicSiteFetcher())
    state_repository = (
        SQLiteStateRepository.open(settings.state_database, settings.state_retention_days)
        if settings.state_database is not None
        else None
    )
    monitoring = MonitoringOperator(state_repository, site_audit)
    internal_links = InternalLinkOperator(
        site_audit,
        google_search_console,
        google_analytics,
    )
    cloudflare_performance = CloudflarePerformanceService(cloudflare_performance_client)
    return ApplicationServices(
        capabilities=CapabilityService(settings, policy, __version__),
        cross_provider=CrossProviderService(
            policy,
            google_analytics,
            pagespeed,
            google_search_console,
            bing_webmaster,
        ),
        diagnostics=DiagnosticsService(policy),
        bing_webmaster=bing_webmaster,
        google_analytics=google_analytics,
        google_indexing_metadata=google_indexing_metadata,
        google_search_console=google_search_console,
        pagespeed=pagespeed,
        lighthouse=lighthouse,
        local_schema=LocalSchemaValidationService(PublicSchemaFetcher()),
        provider_readiness=ProviderReadinessService(
            policy,
            {
                google_client.provider: google_client,
                bing_client.provider: bing_client,
                cloudflare_client.provider: cloudflare_client,
            },
        ),
        sites=SitesService(policy),
        onboarding_guide=OnboardingGuideService(policy),
        # Reads are bounded per-property and renames need the edit scope, so the
        # one client serves both and the policy gates each call.
        google_analytics_admin=GoogleAnalyticsAdminService(
            policy,
            GoogleAnalyticsAdminClient(
                policy,
                GoogleConfiguredTokenProvider(policy, (GOOGLE_ANALYTICS_EDIT_SCOPE,)),
            ),
        ),
        monitoring=monitoring,
        internal_links=internal_links,
        crux=CruxHistoryService(crux_client),
        cloudflare_performance=cloudflare_performance,
        content_opportunities=ContentOpportunityOperator(
            google_search_console,
            bing_webmaster,
            google_analytics,
            site_audit,
        ),
        writes_enabled=settings.writes_enabled,
        indexnow=indexnow,
        google_indexing=google_indexing,
        google_sites=google_sites,
        google_sitemaps=google_sitemaps,
        site_onboarding=site_onboarding,
        site_ownership=site_ownership,
        site_remediation=site_remediation,
        site_audit=site_audit,
    )
