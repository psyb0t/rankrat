"""Shared application services for every Rankrat transport."""

from __future__ import annotations

from dataclasses import dataclass

from rankrat import __version__
from rankrat.config import Settings
from rankrat.operator.site_onboarding import SiteOnboardingOperator
from rankrat.policy.boundaries import BoundaryPolicy
from rankrat.providers.bing import BingWebmasterClient
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
from rankrat.providers.lighthouse import LighthouseWorkerClient
from rankrat.providers.pagespeed import PageSpeedClient
from rankrat.providers.schema_fetch import PublicSchemaFetcher
from rankrat.services.bing import BingWebmasterService
from rankrat.services.capabilities import CapabilityService
from rankrat.services.cross_provider import CrossProviderService
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
from rankrat.services.site_onboarding import SiteOnboardingService
from rankrat.services.sites import SitesService


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
    writes_enabled: bool = False
    agent_onboarding_enabled: bool = False
    indexnow: IndexNowService | None = None
    google_indexing: GoogleIndexingService | None = None
    google_sites: GoogleSiteService | None = None
    google_sitemaps: GoogleSitemapService | None = None
    site_onboarding: SiteOnboardingService | None = None


def build_services(settings: Settings) -> ApplicationServices:
    """Build configured services from one immutable boundary policy."""
    policy = BoundaryPolicy.from_file(
        settings.boundary_file,
        settings.secret_root,
        settings.oauth_token_root,
        unbounded=settings.unbounded,
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
    pagespeed_client = PageSpeedClient(policy)
    indexnow = None
    google_indexing = None
    google_sites = None
    google_sitemaps = None
    site_onboarding = None
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
    # Its own switch rather than the writes_enabled block above: onboarding is
    # the only operation that rewrites the boundary file this server enforces, so
    # writable mode by itself must not expose it. agent_onboarding_enabled
    # already requires writes_enabled, so this stays a subset.
    if settings.agent_onboarding_enabled:
        site_onboarding = SiteOnboardingService(
            SiteOnboardingOperator(
                settings.boundary_file,
                policy,
                GoogleAnalyticsAdminClient(
                    policy,
                    GoogleConfiguredTokenProvider(policy, (GOOGLE_ANALYTICS_EDIT_SCOPE,)),
                ),
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
            {google_client.provider: google_client, bing_client.provider: bing_client},
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
        writes_enabled=settings.writes_enabled,
        agent_onboarding_enabled=settings.agent_onboarding_enabled,
        indexnow=indexnow,
        google_indexing=google_indexing,
        google_sites=google_sites,
        google_sitemaps=google_sitemaps,
        site_onboarding=site_onboarding,
    )
