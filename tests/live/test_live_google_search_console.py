from __future__ import annotations

import os
from datetime import UTC, date, datetime, timedelta
from typing import Final

import pytest

from rankrat.config import Settings
from rankrat.constants import (
    GOOGLE_TAG_MANAGER_DELETE_SCOPE,
    GOOGLE_TAG_MANAGER_EDIT_SCOPE,
    GOOGLE_TAG_MANAGER_PUBLISH_SCOPE,
    GOOGLE_TAG_MANAGER_VERSION_EDIT_SCOPE,
)
from rankrat.errors import ConfigurationError
from rankrat.models.boundaries import ConfiguredAccount, Provider
from rankrat.policy.boundaries import BoundaryPolicy
from rankrat.providers.base import AccountId, ProviderReadRequest
from rankrat.providers.bing import BingWebmasterClient
from rankrat.providers.clarity import ClarityClient
from rankrat.providers.cloudflare_performance import CloudflarePerformanceClient
from rankrat.providers.google_analytics import (
    GOOGLE_ANALYTICS_READ_SCOPE,
    GoogleAnalyticsDataClient,
)
from rankrat.providers.google_search_console import (
    GoogleConfiguredTokenProvider,
    GoogleSearchConsoleClient,
)
from rankrat.providers.google_tag_manager import GoogleTagManagerClient
from rankrat.providers.indexnow import IndexNowClient
from rankrat.providers.pagespeed import PageSpeedClient
from rankrat.services.bing import (
    BingCrawlIssuesRequest,
    BingCrawlStatsRequest,
    BingFeedsRequest,
    BingLinkCountsRequest,
    BingPerformanceRequest,
    BingTrafficPeriodRequest,
    BingUrlSubmissionQuotaRequest,
    BingWebmasterService,
)
from rankrat.services.clarity import ClarityInsightsRequest, ClarityService
from rankrat.services.cloudflare_performance import (
    CloudflareAnalyticsRequest,
    CloudflarePerformanceService,
)
from rankrat.services.google_analytics import (
    Ga4AccountDiscoveryRequest,
    Ga4DateRange,
    Ga4RealtimeReportRequest,
    Ga4ReportRequest,
    GoogleAnalyticsDataService,
)
from rankrat.services.google_search_console import (
    GoogleSearchConsoleService,
    SearchAnalyticsDimension,
    SearchAnalyticsRequest,
    SearchAnalyticsSummaryRequest,
    SitemapGetRequest,
    SitemapListRequest,
    UrlInspectionRequest,
)
from rankrat.services.google_tag_manager import GoogleTagManagerService
from rankrat.services.indexnow import IndexNowService, IndexNowSubmissionRequest
from rankrat.services.pagespeed import (
    PageSpeedAnalysisRequest,
    PageSpeedCategory,
    PageSpeedService,
)

pytestmark = pytest.mark.live

_LIVE_GA4_REALTIME_DIMENSIONS: Final = ("country",)
_LIVE_GA4_REALTIME_METRICS: Final = ("activeUsers",)
_LIVE_CLOUDFLARE_REPORT_HOURS: Final = 24
_LIVE_CLOUDFLARE_REPORT_LIMIT: Final = 24
_LIVE_ENABLED_ENV: Final = "RANKRAT_RUN_LIVE_TESTS"
_LIVE_INDEXNOW_SUBMISSION_ENV: Final = "RANKRAT_RUN_LIVE_INDEXNOW_SUBMISSION"


def _live_policy() -> BoundaryPolicy:
    if os.environ.get(_LIVE_ENABLED_ENV) != "true":
        pytest.skip("live provider checks are not explicitly enabled")
    settings = Settings()
    return BoundaryPolicy.from_file(
        settings.boundary_file,
        settings.secret_root,
        settings.oauth_token_root,
    )


def _sole_account(policy: BoundaryPolicy, provider: Provider) -> ConfiguredAccount:
    try:
        return policy.select_account(provider)
    except ConfigurationError as error:
        pytest.skip(str(error))


def _first_or_skip(items: tuple[str, ...], subject: str) -> str:
    if not items:
        pytest.skip(f"no {subject} is available in the configured account")
    return items[0]


def _inspection_root(site_url: str) -> str:
    if site_url.startswith("sc-domain:"):
        return f"https://{site_url.removeprefix('sc-domain:')}/"
    return site_url


@pytest.mark.asyncio
async def test_live_google_search_console_matches_mocked_contract() -> None:
    policy = _live_policy()
    account = _sole_account(policy, Provider.GOOGLE)
    client = GoogleSearchConsoleClient(policy, GoogleConfiguredTokenProvider(policy))
    sites = await client.list_sites(
        ProviderReadRequest(AccountId(account.id), timeout_seconds=10.0)
    )

    assert all(site.startswith(("https://", "sc-domain:")) for site in sites)


@pytest.mark.asyncio
async def test_live_google_analytics_account_discovery_matches_mocked_contract() -> None:
    policy = _live_policy()
    account = _sole_account(policy, Provider.GOOGLE)

    service = GoogleAnalyticsDataService(
        policy,
        GoogleAnalyticsDataClient(
            policy,
            GoogleConfiguredTokenProvider(policy, (GOOGLE_ANALYTICS_READ_SCOPE,)),
        ),
    )
    inventory = await service.list_account_summaries(Ga4AccountDiscoveryRequest(account.id))

    assert all(summary.account_id.isdecimal() for summary in inventory)
    assert all(
        property_summary.property_id.isdecimal()
        for summary in inventory
        for property_summary in summary.properties
    )


@pytest.mark.asyncio
async def test_live_google_search_console_unique_read_operations() -> None:
    policy = _live_policy()
    account = _sole_account(policy, Provider.GOOGLE)
    client = GoogleSearchConsoleClient(policy, GoogleConfiguredTokenProvider(policy))
    service = GoogleSearchConsoleService(policy, client)
    site_url = _first_or_skip(
        await client.list_sites(ProviderReadRequest(AccountId(account.id), timeout_seconds=10.0)),
        "Google Search Console site",
    )
    end_date = date.today() - timedelta(days=2)
    start_date = end_date - timedelta(days=6)
    analytics = await service.search_analytics(
        SearchAnalyticsRequest(
            account.id,
            site_url,
            start_date,
            end_date,
            dimensions=(SearchAnalyticsDimension.DATE,),
            row_limit=10,
        )
    )
    summary = await service.search_analytics_summary(
        SearchAnalyticsSummaryRequest(
            account.id,
            site_url,
            start_date,
            end_date,
        )
    )
    sitemaps = await service.list_sitemaps(SitemapListRequest(account.id, site_url))

    assert isinstance(analytics.rows, tuple)
    assert isinstance(summary.clicks, float)
    assert isinstance(sitemaps.sitemaps, tuple)

    if sitemaps.sitemaps:
        sitemap_url = sitemaps.sitemaps[0].path
        sitemap = await service.get_sitemap(SitemapGetRequest(account.id, site_url, sitemap_url))
        assert sitemap.path == sitemap_url

    inspection = await service.inspect_url(
        UrlInspectionRequest(account.id, site_url, _inspection_root(site_url))
    )
    if inspection.index_status is not None:
        assert isinstance(inspection.index_status.referring_urls, tuple)


@pytest.mark.asyncio
async def test_live_ga4_report_matches_mocked_contract() -> None:
    policy = _live_policy()
    account = _sole_account(policy, Provider.GOOGLE)
    service = GoogleAnalyticsDataService(
        policy,
        GoogleAnalyticsDataClient(
            policy,
            GoogleConfiguredTokenProvider(policy, (GOOGLE_ANALYTICS_READ_SCOPE,)),
        ),
    )
    inventory = await service.list_account_summaries(Ga4AccountDiscoveryRequest(account.id))
    property_id = _first_or_skip(
        tuple(
            property_summary.property_id
            for summary in inventory
            for property_summary in summary.properties
        ),
        "GA4 property",
    )
    previous_day = date.today() - timedelta(days=1)
    result = await service.run_report(
        Ga4ReportRequest(
            account.id,
            property_id,
            (Ga4DateRange(previous_day, previous_day),),
            ("date",),
            ("activeUsers",),
            limit=1,
        )
    )

    assert isinstance(result.rows, tuple)


@pytest.mark.asyncio
async def test_live_ga4_unique_read_operations() -> None:
    policy = _live_policy()
    account = _sole_account(policy, Provider.GOOGLE)
    service = GoogleAnalyticsDataService(
        policy,
        GoogleAnalyticsDataClient(
            policy,
            GoogleConfiguredTokenProvider(policy, (GOOGLE_ANALYTICS_READ_SCOPE,)),
        ),
    )
    inventory = await service.list_account_summaries(Ga4AccountDiscoveryRequest(account.id))
    property_id = _first_or_skip(
        tuple(
            property_summary.property_id
            for summary in inventory
            for property_summary in summary.properties
        ),
        "GA4 property",
    )
    realtime = await service.run_realtime_report(
        Ga4RealtimeReportRequest(
            account.id,
            property_id,
            _LIVE_GA4_REALTIME_DIMENSIONS,
            _LIVE_GA4_REALTIME_METRICS,
            limit=10,
        )
    )

    assert isinstance(realtime.rows, tuple)


@pytest.mark.asyncio
async def test_live_google_tag_manager_accounts_match_mocked_contract() -> None:
    policy = _live_policy()
    account = _sole_account(policy, Provider.GOOGLE)
    service = GoogleTagManagerService(
        GoogleTagManagerClient(
            policy,
            GoogleConfiguredTokenProvider(
                policy,
                (
                    GOOGLE_TAG_MANAGER_EDIT_SCOPE,
                    GOOGLE_TAG_MANAGER_DELETE_SCOPE,
                    GOOGLE_TAG_MANAGER_VERSION_EDIT_SCOPE,
                    GOOGLE_TAG_MANAGER_PUBLISH_SCOPE,
                ),
            ),
        )
    )

    accounts = await service.list_accounts(account.id, timeout_seconds=10.0)

    assert all(item.account_id.isdecimal() for item in accounts)


@pytest.mark.asyncio
async def test_live_clarity_insights_match_mocked_contract() -> None:
    policy = _live_policy()
    account = _sole_account(policy, Provider.CLARITY)
    service = ClarityService(ClarityClient(policy))

    report = await service.live_insights(ClarityInsightsRequest(account.id))

    assert report.num_days == 1
    assert report.dimensions == ()
    assert isinstance(report.metrics, tuple)


@pytest.mark.asyncio
async def test_live_pagespeed_analysis_matches_mocked_contract() -> None:
    policy = _live_policy()
    account = _sole_account(policy, Provider.GOOGLE)
    site_url = _first_or_skip(account.pagespeed_sites, "PageSpeed site")
    service = PageSpeedService(policy, PageSpeedClient(policy))
    result = await service.analyze(
        PageSpeedAnalysisRequest(
            account.id,
            site_url,
            site_url,
            categories=tuple(PageSpeedCategory),
        )
    )

    assert isinstance(result.categories, tuple)


@pytest.mark.asyncio
async def test_live_cloudflare_analytics_matches_mocked_contract() -> None:
    policy = _live_policy()
    account = _sole_account(policy, Provider.CLOUDFLARE)
    zone_id = _first_or_skip(
        tuple(zone.provider_zone_id for zone in account.dns_zones),
        "Cloudflare DNS zone",
    )
    service = CloudflarePerformanceService(CloudflarePerformanceClient(policy))
    end = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    report = await service.analytics(
        CloudflareAnalyticsRequest(
            account.id,
            zone_id,
            end - timedelta(hours=_LIVE_CLOUDFLARE_REPORT_HOURS),
            end,
            limit=_LIVE_CLOUDFLARE_REPORT_LIMIT,
        )
    )

    assert report.zone_id == zone_id
    assert isinstance(report.points, tuple)


@pytest.mark.asyncio
async def test_live_bing_readiness_matches_mocked_contract() -> None:
    policy = _live_policy()
    account = _sole_account(policy, Provider.BING)
    client = BingWebmasterClient(policy)
    sites = await client.list_sites(
        ProviderReadRequest(AccountId(account.id), timeout_seconds=10.0)
    )

    assert all(site.startswith("https://") for site in sites)


@pytest.mark.asyncio
async def test_live_bing_unique_read_operations() -> None:
    policy = _live_policy()
    account = _sole_account(policy, Provider.BING)
    service = BingWebmasterService(policy, BingWebmasterClient(policy))
    site_url = _first_or_skip(
        await BingWebmasterClient(policy).list_sites(
            ProviderReadRequest(AccountId(account.id), timeout_seconds=10.0)
        ),
        "Bing Webmaster site",
    )
    end_date = date.today() - timedelta(days=2)
    start_date = end_date - timedelta(days=6)
    traffic = await service.traffic_trend(
        BingTrafficPeriodRequest(account.id, site_url, start_date, end_date)
    )
    query_performance = await service.query_performance(
        BingPerformanceRequest(account.id, site_url)
    )
    page_performance = await service.page_performance(BingPerformanceRequest(account.id, site_url))
    crawl_issues = await service.crawl_issues(BingCrawlIssuesRequest(account.id, site_url))
    crawl_stats = await service.crawl_stats(BingCrawlStatsRequest(account.id, site_url))
    feeds = await service.feeds(BingFeedsRequest(account.id, site_url))
    quota = await service.url_submission_quota(BingUrlSubmissionQuotaRequest(account.id, site_url))
    links = await service.link_counts(BingLinkCountsRequest(account.id, site_url))

    assert isinstance(traffic.points, tuple)
    assert isinstance(query_performance.rows, tuple)
    assert isinstance(page_performance.rows, tuple)
    assert isinstance(crawl_issues.issues, tuple)
    assert isinstance(crawl_stats.points, tuple)
    assert isinstance(feeds.feeds, tuple)
    assert quota.daily >= 0
    assert quota.monthly >= 0
    assert isinstance(links.links, tuple)
    assert links.total_pages >= 0


@pytest.mark.asyncio
async def test_live_indexnow_submission_matches_mocked_contract() -> None:
    policy = _live_policy()
    if os.environ.get(_LIVE_INDEXNOW_SUBMISSION_ENV) != "true":
        pytest.skip("live IndexNow submission is not explicitly enabled")
    settings = Settings()
    if settings.read_only:
        pytest.skip("RANKRAT_READ_ONLY=false is required for a live IndexNow submission")
    targets = policy.indexnow_targets()
    if not targets:
        pytest.skip("no IndexNow target is configured")
    target = targets[0]
    url = f"https://{target.host}/"
    service = IndexNowService(policy, IndexNowClient(policy))
    result = await service.submit(IndexNowSubmissionRequest(target.id, (url,)))

    assert result.target_id == target.id
    assert result.submitted_count == 1
