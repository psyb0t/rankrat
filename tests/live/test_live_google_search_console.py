from __future__ import annotations

import os
from datetime import date, timedelta
from typing import Final

import pytest

from rankrat.config import Settings
from rankrat.policy.approvals import WriteApprovalStore
from rankrat.policy.boundaries import BoundaryPolicy
from rankrat.providers.base import AccountId, ProviderReadRequest
from rankrat.providers.bing import BingWebmasterClient
from rankrat.providers.google_analytics import (
    GOOGLE_ANALYTICS_READ_SCOPE,
    GoogleAnalyticsDataClient,
)
from rankrat.providers.google_indexing import GOOGLE_INDEXING_SCOPE, GoogleIndexingClient
from rankrat.providers.google_search_console import (
    GoogleConfiguredTokenProvider,
    GoogleSearchConsoleClient,
)
from rankrat.providers.indexnow import IndexNowClient
from rankrat.providers.pagespeed import PageSpeedClient
from rankrat.services.bing import (
    BingCrawlIssuesRequest,
    BingCrawlStatsRequest,
    BingFeedsRequest,
    BingKeywordStatisticsRequest,
    BingLinkCountsRequest,
    BingPageQueryPerformanceRequest,
    BingPerformanceRequest,
    BingQueryPagePerformanceRequest,
    BingRelatedKeywordsRequest,
    BingTrafficPeriodRequest,
    BingUrlInformationRequest,
    BingUrlSubmissionQuotaRequest,
    BingWebmasterService,
)
from rankrat.services.google_analytics import (
    Ga4AccountDiscoveryRequest,
    Ga4ConversionFunnelRequest,
    Ga4DateRange,
    Ga4RealtimeReportRequest,
    Ga4ReportRequest,
    GoogleAnalyticsDataService,
)
from rankrat.services.google_indexing_metadata import (
    GoogleIndexingMetadataRequest,
    GoogleIndexingMetadataService,
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
from rankrat.services.indexnow import (
    IndexNowApprovalRequest,
    IndexNowService,
    IndexNowSubmissionRequest,
)
from rankrat.services.pagespeed import (
    PageSpeedAnalysisRequest,
    PageSpeedCategory,
    PageSpeedService,
)

pytestmark = pytest.mark.live

_LIVE_GA4_FUNNEL_EVENTS_ENV: Final = "RANKRAT_LIVE_GA4_FUNNEL_EVENTS"
_LIVE_GA4_REALTIME_DIMENSIONS: Final = ("country",)
_LIVE_GA4_REALTIME_METRICS: Final = ("activeUsers",)
_LIVE_GOOGLE_SITEMAP_URL_ENV: Final = "RANKRAT_LIVE_GOOGLE_SITEMAP_URL"
_LIVE_BING_COUNTRY_ENV: Final = "RANKRAT_LIVE_BING_COUNTRY"
_LIVE_BING_KEYWORD_QUERY_ENV: Final = "RANKRAT_LIVE_BING_KEYWORD_QUERY"
_LIVE_BING_LANGUAGE_ENV: Final = "RANKRAT_LIVE_BING_LANGUAGE"
_LIVE_BING_PAGE_URL_ENV: Final = "RANKRAT_LIVE_BING_PAGE_URL"
_LIVE_BING_QUERY_ENV: Final = "RANKRAT_LIVE_BING_QUERY"
_LIVE_BING_SITE_URL_ENV: Final = "RANKRAT_LIVE_BING_SITE_URL"


@pytest.mark.asyncio
async def test_live_google_search_console_matches_mocked_contract() -> None:
    if os.environ.get("RANKRAT_RUN_LIVE_TESTS") != "true":
        pytest.skip("live provider checks are not explicitly enabled")
    account_id = os.environ.get("RANKRAT_LIVE_GOOGLE_ACCOUNT_ID")
    if not account_id:
        pytest.skip("an explicit live Google account ID is required")

    settings = Settings()
    policy = BoundaryPolicy.from_file(
        settings.boundary_file,
        settings.secret_root,
        settings.oauth_token_root,
    )
    account = policy.resolve_account(account_id)
    client = GoogleSearchConsoleClient(policy, GoogleConfiguredTokenProvider(policy))
    sites = await client.list_sites(
        ProviderReadRequest(AccountId(account_id), timeout_seconds=10.0)
    )

    if account.google_account_discovery:
        assert all(site.startswith(("https://", "sc-domain:")) for site in sites)
        return

    assert set(sites).issubset(account.search_console_sites)
    assert all(site.startswith(("https://", "sc-domain:")) for site in sites)


@pytest.mark.asyncio
async def test_live_google_analytics_account_discovery_matches_mocked_contract() -> None:
    if os.environ.get("RANKRAT_RUN_LIVE_TESTS") != "true":
        pytest.skip("live provider checks are not explicitly enabled")
    account_id = os.environ.get("RANKRAT_LIVE_GOOGLE_ACCOUNT_ID")
    if not account_id:
        pytest.skip("an explicit live Google account ID is required")

    settings = Settings()
    policy = BoundaryPolicy.from_file(
        settings.boundary_file,
        settings.secret_root,
        settings.oauth_token_root,
    )
    account = policy.resolve_account(account_id)
    if not account.google_account_discovery:
        pytest.skip("the live Google account has not enabled account discovery")

    service = GoogleAnalyticsDataService(
        policy,
        GoogleAnalyticsDataClient(
            policy,
            GoogleConfiguredTokenProvider(policy, (GOOGLE_ANALYTICS_READ_SCOPE,)),
        ),
    )
    inventory = await service.list_account_summaries(Ga4AccountDiscoveryRequest(account_id))

    assert all(summary.account_id.isdecimal() for summary in inventory)
    assert all(
        property_summary.property_id.isdecimal()
        for summary in inventory
        for property_summary in summary.properties
    )


@pytest.mark.asyncio
async def test_live_google_search_console_unique_read_operations() -> None:
    if os.environ.get("RANKRAT_RUN_LIVE_TESTS") != "true":
        pytest.skip("live provider checks are not explicitly enabled")
    account_id = os.environ.get("RANKRAT_LIVE_GOOGLE_ACCOUNT_ID")
    site_url = os.environ.get("RANKRAT_LIVE_GOOGLE_SITE_URL")
    if not account_id or not site_url:
        pytest.skip("an explicit live Google account ID and site URL are required")

    settings = Settings()
    policy = BoundaryPolicy.from_file(
        settings.boundary_file,
        settings.secret_root,
        settings.oauth_token_root,
    )
    client = GoogleSearchConsoleClient(policy, GoogleConfiguredTokenProvider(policy))
    service = GoogleSearchConsoleService(policy, client)
    end_date = date.today() - timedelta(days=2)
    start_date = end_date - timedelta(days=6)
    analytics = await service.search_analytics(
        SearchAnalyticsRequest(
            account_id,
            site_url,
            start_date,
            end_date,
            dimensions=(SearchAnalyticsDimension.DATE,),
            row_limit=10,
        )
    )
    summary = await service.search_analytics_summary(
        SearchAnalyticsSummaryRequest(
            account_id,
            site_url,
            start_date,
            end_date,
        )
    )
    sitemaps = await service.list_sitemaps(SitemapListRequest(account_id, site_url))

    assert isinstance(analytics.rows, tuple)
    assert isinstance(summary.clicks, float)
    assert isinstance(sitemaps.sitemaps, tuple)

    sitemap_url = os.environ.get(_LIVE_GOOGLE_SITEMAP_URL_ENV)
    if sitemap_url:
        sitemap = await service.get_sitemap(SitemapGetRequest(account_id, site_url, sitemap_url))
        assert sitemap.path == sitemap_url

    inspection_url = os.environ.get("RANKRAT_LIVE_GOOGLE_INSPECTION_URL")
    if inspection_url:
        inspection = await service.inspect_url(
            UrlInspectionRequest(account_id, site_url, inspection_url)
        )
        if inspection.index_status is not None:
            assert isinstance(inspection.index_status.referring_urls, tuple)

    indexing_url = os.environ.get("RANKRAT_LIVE_GOOGLE_INDEXING_URL")
    if indexing_url:
        metadata = await GoogleIndexingMetadataService(
            policy,
            GoogleIndexingClient(
                GoogleSearchConsoleClient(
                    policy,
                    GoogleConfiguredTokenProvider(policy, (GOOGLE_INDEXING_SCOPE,)),
                )
            ),
        ).metadata(GoogleIndexingMetadataRequest(account_id, site_url, indexing_url))
        assert metadata.url == indexing_url


@pytest.mark.asyncio
async def test_live_ga4_report_matches_mocked_contract() -> None:
    if os.environ.get("RANKRAT_RUN_LIVE_TESTS") != "true":
        pytest.skip("live provider checks are not explicitly enabled")
    account_id = os.environ.get("RANKRAT_LIVE_GOOGLE_ACCOUNT_ID")
    property_id = os.environ.get("RANKRAT_LIVE_GA4_PROPERTY_ID")
    if not account_id or not property_id:
        pytest.skip("an explicit live Google account ID and GA4 property ID are required")

    settings = Settings()
    policy = BoundaryPolicy.from_file(
        settings.boundary_file,
        settings.secret_root,
        settings.oauth_token_root,
    )
    service = GoogleAnalyticsDataService(
        policy,
        GoogleAnalyticsDataClient(
            policy,
            GoogleConfiguredTokenProvider(policy, (GOOGLE_ANALYTICS_READ_SCOPE,)),
        ),
    )
    previous_day = date.today() - timedelta(days=1)
    result = await service.run_report(
        Ga4ReportRequest(
            account_id,
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
    if os.environ.get("RANKRAT_RUN_LIVE_TESTS") != "true":
        pytest.skip("live provider checks are not explicitly enabled")
    account_id = os.environ.get("RANKRAT_LIVE_GOOGLE_ACCOUNT_ID")
    property_id = os.environ.get("RANKRAT_LIVE_GA4_PROPERTY_ID")
    if not account_id or not property_id:
        pytest.skip("an explicit live Google account ID and GA4 property ID are required")

    settings = Settings()
    policy = BoundaryPolicy.from_file(
        settings.boundary_file,
        settings.secret_root,
        settings.oauth_token_root,
    )
    service = GoogleAnalyticsDataService(
        policy,
        GoogleAnalyticsDataClient(
            policy,
            GoogleConfiguredTokenProvider(policy, (GOOGLE_ANALYTICS_READ_SCOPE,)),
        ),
    )
    realtime = await service.run_realtime_report(
        Ga4RealtimeReportRequest(
            account_id,
            property_id,
            _LIVE_GA4_REALTIME_DIMENSIONS,
            _LIVE_GA4_REALTIME_METRICS,
            limit=10,
        )
    )

    assert isinstance(realtime.rows, tuple)

    funnel_event_names = tuple(
        event_name.strip()
        for event_name in os.environ.get(_LIVE_GA4_FUNNEL_EVENTS_ENV, "").split(",")
        if event_name.strip()
    )
    if funnel_event_names:
        end_date = date.today() - timedelta(days=2)
        funnel = await service.conversion_funnel(
            Ga4ConversionFunnelRequest(
                account_id,
                property_id,
                end_date - timedelta(days=6),
                end_date,
                funnel_event_names,
                limit=10,
            )
        )
        assert isinstance(funnel.funnel_table.rows, tuple)
        assert isinstance(funnel.funnel_visualization.rows, tuple)


@pytest.mark.asyncio
async def test_live_pagespeed_analysis_matches_mocked_contract() -> None:
    if os.environ.get("RANKRAT_RUN_LIVE_TESTS") != "true":
        pytest.skip("live provider checks are not explicitly enabled")
    account_id = os.environ.get("RANKRAT_LIVE_PAGESPEED_ACCOUNT_ID")
    site_url = os.environ.get("RANKRAT_LIVE_PAGESPEED_SITE_URL")
    page_url = os.environ.get("RANKRAT_LIVE_PAGESPEED_URL")
    if not account_id or not site_url or not page_url:
        pytest.skip("explicit live PageSpeed account, site, and URL settings are required")

    settings = Settings()
    policy = BoundaryPolicy.from_file(
        settings.boundary_file,
        settings.secret_root,
        settings.oauth_token_root,
    )
    service = PageSpeedService(policy, PageSpeedClient(policy))
    result = await service.analyze(
        PageSpeedAnalysisRequest(
            account_id,
            site_url,
            page_url,
            categories=tuple(PageSpeedCategory),
        )
    )

    assert isinstance(result.categories, tuple)


@pytest.mark.asyncio
async def test_live_bing_readiness_matches_mocked_contract() -> None:
    if os.environ.get("RANKRAT_RUN_LIVE_TESTS") != "true":
        pytest.skip("live provider checks are not explicitly enabled")
    account_id = os.environ.get("RANKRAT_LIVE_BING_ACCOUNT_ID")
    if not account_id:
        pytest.skip("an explicit live Bing account ID is required")

    settings = Settings()
    policy = BoundaryPolicy.from_file(
        settings.boundary_file,
        settings.secret_root,
        settings.oauth_token_root,
    )
    account = policy.resolve_account(account_id)
    client = BingWebmasterClient(policy)
    sites = await client.list_sites(
        ProviderReadRequest(AccountId(account_id), timeout_seconds=10.0)
    )

    assert set(sites).issubset(account.bing_sites)
    assert all(site.startswith("https://") for site in sites)


@pytest.mark.asyncio
async def test_live_bing_unique_read_operations() -> None:
    if os.environ.get("RANKRAT_RUN_LIVE_TESTS") != "true":
        pytest.skip("live provider checks are not explicitly enabled")
    account_id = os.environ.get("RANKRAT_LIVE_BING_ACCOUNT_ID")
    site_url = os.environ.get(_LIVE_BING_SITE_URL_ENV)
    if not account_id or not site_url:
        pytest.skip("an explicit live Bing account ID and site URL are required")

    settings = Settings()
    policy = BoundaryPolicy.from_file(
        settings.boundary_file,
        settings.secret_root,
        settings.oauth_token_root,
    )
    service = BingWebmasterService(policy, BingWebmasterClient(policy))
    end_date = date.today() - timedelta(days=2)
    start_date = end_date - timedelta(days=6)
    traffic = await service.traffic_trend(
        BingTrafficPeriodRequest(account_id, site_url, start_date, end_date)
    )
    query_performance = await service.query_performance(
        BingPerformanceRequest(account_id, site_url)
    )
    page_performance = await service.page_performance(BingPerformanceRequest(account_id, site_url))
    crawl_issues = await service.crawl_issues(BingCrawlIssuesRequest(account_id, site_url))
    crawl_stats = await service.crawl_stats(BingCrawlStatsRequest(account_id, site_url))
    feeds = await service.feeds(BingFeedsRequest(account_id, site_url))
    quota = await service.url_submission_quota(BingUrlSubmissionQuotaRequest(account_id, site_url))
    links = await service.link_counts(BingLinkCountsRequest(account_id, site_url))

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

    query = os.environ.get(_LIVE_BING_QUERY_ENV)
    page_url = os.environ.get(_LIVE_BING_PAGE_URL_ENV)
    if query:
        query_pages = await service.query_page_performance(
            BingQueryPagePerformanceRequest(account_id, site_url, query)
        )
        assert isinstance(query_pages.rows, tuple)
    if page_url:
        page_queries = await service.page_query_performance(
            BingPageQueryPerformanceRequest(account_id, site_url, page_url)
        )
        url_information = await service.url_information(
            BingUrlInformationRequest(account_id, site_url, page_url)
        )
        assert isinstance(page_queries.rows, tuple)
        assert url_information.url == page_url

    keyword_query = os.environ.get(_LIVE_BING_KEYWORD_QUERY_ENV)
    if keyword_query:
        country = os.environ.get(_LIVE_BING_COUNTRY_ENV)
        language = os.environ.get(_LIVE_BING_LANGUAGE_ENV)
        keyword_statistics = await service.keyword_statistics(
            BingKeywordStatisticsRequest(account_id, keyword_query, country, language)
        )
        related_keywords = await service.related_keywords(
            BingRelatedKeywordsRequest(
                account_id,
                keyword_query,
                start_date,
                end_date,
                country,
                language,
            )
        )
        assert isinstance(keyword_statistics.points, tuple)
        assert isinstance(related_keywords.keywords, tuple)


@pytest.mark.asyncio
async def test_live_indexnow_submission_matches_mocked_contract() -> None:
    if os.environ.get("RANKRAT_RUN_LIVE_TESTS") != "true":
        pytest.skip("live provider checks are not explicitly enabled")
    if os.environ.get("RANKRAT_RUN_LIVE_INDEXNOW_SUBMISSION") != "true":
        pytest.skip("live IndexNow submission is not explicitly enabled")
    target_id = os.environ.get("RANKRAT_LIVE_INDEXNOW_TARGET_ID")
    url = os.environ.get("RANKRAT_LIVE_INDEXNOW_URL")
    if not target_id or not url:
        pytest.skip("an explicit live IndexNow target ID and URL are required")

    settings = Settings()
    if not settings.enable_writes:
        pytest.skip("RANKRAT_ENABLE_WRITES=true is required for a live IndexNow submission")
    policy = BoundaryPolicy.from_file(
        settings.boundary_file,
        settings.secret_root,
        settings.oauth_token_root,
    )
    service = IndexNowService(policy, IndexNowClient(policy), WriteApprovalStore())
    approval = await service.approve(IndexNowApprovalRequest(target_id, (url,)))
    result = await service.submit(
        IndexNowSubmissionRequest(target_id, (url,), approval.approval_id)
    )

    assert result.target_id == target_id
    assert result.submitted_count == 1
