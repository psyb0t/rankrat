from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest

from rankrat.errors import BoundaryDeniedError, InputLimitError, SiteFetchError
from rankrat.models.boundaries import BoundaryDocument, Provider
from rankrat.operator.site_ownership import (
    SiteOwnershipOperator,
    SiteOwnershipReceipt,
    SiteOwnershipRequest,
    SiteOwnershipWriteRequest,
)
from rankrat.policy.boundaries import BoundaryPolicy
from rankrat.providers.base import ProviderFailureCode, ProviderOperationError
from rankrat.providers.bing import (
    BingLinkDetail,
    BingSiteVerification,
    BingUrlLinks,
    BingWebmasterClient,
)
from rankrat.providers.dns import (
    DnsOwnershipClient,
    DnsPropagationResult,
    DnsRecordReceipt,
    DnsRecordType,
    PublicDnsClient,
)
from rankrat.providers.google_search_console import GoogleSearchConsoleClient
from rankrat.providers.google_site_verification import (
    GoogleSiteVerificationClient,
    GoogleVerificationMethod,
    GoogleVerificationToken,
    GoogleVerifiedWebResource,
)
from rankrat.providers.site_fetch import PublicSiteFetcher, SiteFetchResult
from rankrat.services.bing import BingBacklinkIntelligenceRequest, BingWebmasterService
from rankrat.services.site_audit import SiteAuditRequest, SiteAuditService
from rankrat.services.site_ownership import (
    SiteOwnershipCheckRequest,
    SiteOwnershipService,
    SiteOwnershipVerificationRequest,
)
from rankrat.services.site_remediation import SiteRemediationRequest, SiteRemediationService


def _policy(tmp_path: Path) -> BoundaryPolicy:
    return BoundaryPolicy(
        BoundaryDocument.model_validate(
            {
                "accounts": [
                    {
                        "id": "google-main",
                        "provider": "google",
                        "credential": str(tmp_path / "google.json"),
                        "search_console_sites": ["sc-domain:example.com"],
                        "pagespeed_sites": ["https://example.com/"],
                    },
                    {
                        "id": "bing-main",
                        "provider": "bing",
                        "credential": str(tmp_path / "bing-key"),
                        "sites": ["https://example.com/"],
                    },
                    {
                        "id": "cloudflare-main",
                        "provider": "cloudflare",
                        "credential": str(tmp_path / "cloudflare-token"),
                        "dns_zones": [
                            {"provider_zone_id": "a" * 32, "name": "example.com"},
                        ],
                    },
                ]
            }
        )
    )


class _SiteFetcher:
    def __init__(self) -> None:
        page = b"""<html lang="en"><head><title>Home</title>
        <meta name="description"
        content="A sufficiently descriptive page summary for search results and users.">
        <meta property="og:title" content="Home"><meta property="og:description" content="Summary">
        <link rel="canonical" href="https://example.com/"></head>
        <body><h1>Home</h1><a href="/post/?utfc=opaque%3D">Post</a></body></html>"""
        post = page.replace(b"Home", b"Post").replace(
            b'https://example.com/"',
            b'https://example.com/post/?utfc=opaque%3D"',
        )
        self.responses = {
            "https://example.com/robots.txt": SiteFetchResult(
                "https://example.com/robots.txt",
                200,
                "text/plain",
                b"User-agent: *\nSitemap: https://example.com/sitemap.xml\n",
            ),
            "https://example.com/sitemap.xml": SiteFetchResult(
                "https://example.com/sitemap.xml",
                200,
                "application/xml",
                b"<urlset><url><loc>https://example.com/</loc></url>"
                b"<url><loc>https://example.com/post/?utfc=opaque%3D</loc></url></urlset>",
            ),
            "https://example.com/": SiteFetchResult("https://example.com/", 200, "text/html", page),
            "https://example.com/post/?utfc=opaque%3D": SiteFetchResult(
                "https://example.com/post/?utfc=opaque%3D", 200, "text/html", post
            ),
        }

    async def fetch(self, url: str, _: float) -> SiteFetchResult:
        return self.responses[url]


@pytest.mark.asyncio
async def test_site_audit_crawls_sitemap_and_same_site_links(tmp_path: Path) -> None:
    service = SiteAuditService(
        _policy(tmp_path),
        cast(PublicSiteFetcher, _SiteFetcher()),
    )
    report = await service.audit(
        SiteAuditRequest(
            account_id="google-main",
            site_url="https://example.com/",
            max_pages=10,
            max_depth=2,
        )
    )

    assert tuple(page.url for page in report.pages) == (
        "https://example.com/",
        "https://example.com/post/?utfc=opaque%3D",
    )
    assert report.discovered_sitemaps == ("https://example.com/sitemap.xml",)
    assert report.truncated is False
    assert report.score > 0


class _BacklinkClient:
    provider = BingWebmasterClient.provider

    def __init__(self) -> None:
        self.pages: list[int] = []

    async def read_url_links(
        self,
        *arguments: object,
    ) -> BingUrlLinks:
        page = cast(int, arguments[-1])
        self.pages.append(page)
        source = "https://source.example/a" if page < 2 else "https://third.example/c"
        return BingUrlLinks(
            links=(
                BingLinkDetail(source, "Example anchor"),
                BingLinkDetail("https://other.example/b", "Example anchor"),
            ),
            total_pages=3,
        )


@pytest.mark.asyncio
async def test_backlink_intelligence_aggregates_domains_and_anchors(tmp_path: Path) -> None:
    client = _BacklinkClient()
    service = BingWebmasterService(
        _policy(tmp_path),
        cast(BingWebmasterClient, client),
    )
    report = await service.backlink_intelligence(
        BingBacklinkIntelligenceRequest(
            account_id="bing-main",
            site_url="https://example.com/",
            target_urls=("https://example.com/post/",),
            max_pages_per_target=3,
        )
    )

    target = report.targets[0]
    assert target.referring_domains == (
        "other.example",
        "source.example",
        "third.example",
    )
    assert target.anchors[0].count == 3
    assert client.pages == [0, 1, 2]
    assert target.pages_read == 3
    assert target.truncated is False


class _GoogleRemediationClient:
    def __init__(self) -> None:
        self.sitemaps: list[str] = []

    async def submit_sitemap(self, _: object, __: str, sitemap_url: str) -> None:
        self.sitemaps.append(sitemap_url)


class _BingRemediationClient:
    provider = BingWebmasterClient.provider

    def __init__(self) -> None:
        self.sitemaps: list[str] = []
        self.urls: tuple[str, ...] = ()

    async def submit_feed(self, _: object, __: str, sitemap_url: str) -> None:
        self.sitemaps.append(sitemap_url)

    async def submit_url_batch(self, _: object, __: str, urls: tuple[str, ...]) -> None:
        self.urls = urls


@pytest.mark.asyncio
async def test_site_remediation_submits_bounded_discovery_changes(tmp_path: Path) -> None:
    google = _GoogleRemediationClient()
    bing = _BingRemediationClient()
    service = SiteRemediationService(
        _policy(tmp_path),
        cast(GoogleSearchConsoleClient, google),
        cast(BingWebmasterClient, bing),
    )
    receipt = await service.apply(
        SiteRemediationRequest(
            google_account_id="google-main",
            google_site_url="sc-domain:example.com",
            bing_account_id="bing-main",
            bing_site_url="https://example.com/",
            sitemap_url="https://example.com/sitemap.xml",
            changed_urls=("https://example.com/post/",),
        )
    )

    assert receipt.google_sitemap_submitted is True
    assert google.sitemaps == ["https://example.com/sitemap.xml"]
    assert bing.urls == ("https://example.com/post/",)


class _GoogleOwnershipClient:
    async def get_token(self, *_: object) -> GoogleVerificationToken:
        return GoogleVerificationToken(
            GoogleVerificationMethod.DNS_TXT,
            "google-site-verification=value",
        )

    async def is_verified(self, *_: object) -> bool:
        return False

    async def verify(self, _: object, domain: str, __: object) -> GoogleVerifiedWebResource:
        return GoogleVerifiedWebResource("resource", domain)


class _BingOwnershipClient:
    provider = BingWebmasterClient.provider

    async def site_verification_for_onboarding(
        self,
        *_: object,
    ) -> BingSiteVerification:
        return BingSiteVerification(
            "https://example.com/",
            "proof.example.com",
            False,
        )

    async def verify_site_for_onboarding(self, *_: object) -> bool:
        return True


class _DnsOwnershipClient:
    provider = Provider.CLOUDFLARE

    def __init__(self) -> None:
        self.record_types: list[DnsRecordType] = []

    async def ensure_verification_record(
        self,
        _: object,
        __: str,
        record_type: DnsRecordType,
        name: str,
        ___: str,
    ) -> DnsRecordReceipt:
        self.record_types.append(record_type)
        return DnsRecordReceipt("a" * 32, "b" * 32, record_type, name, True)


class _DnsClient:
    async def has_record(self, *_: object) -> DnsPropagationResult:
        return DnsPropagationResult(True, 1)


@pytest.mark.asyncio
async def test_site_ownership_verifies_and_redeems_without_tokens(tmp_path: Path) -> None:
    operator = SiteOwnershipOperator(
        _policy(tmp_path),
        cast(GoogleSiteVerificationClient, _GoogleOwnershipClient()),
        cast(BingWebmasterClient, _BingOwnershipClient()),
        {Provider.CLOUDFLARE: cast(DnsOwnershipClient, _DnsOwnershipClient())},
        cast(PublicDnsClient, _DnsClient()),
    )
    receipt = await operator.verify(
        SiteOwnershipWriteRequest(
            google_account_id="google-main",
            bing_account_id="bing-main",
            dns_account_id="cloudflare-main",
            site_url="https://example.com/",
            timeout_seconds=1.0,
        )
    )

    assert receipt.complete is True
    assert "verification" not in repr(receipt)


class _UnexpectedGoogleOwnershipClient:
    async def get_token(self, *_: object) -> GoogleVerificationToken:
        raise AssertionError("Bing-only ownership must not request a Google token")

    async def is_verified(self, *_: object) -> bool:
        raise AssertionError("Bing-only ownership must not check Google verification")

    async def verify(self, *_: object) -> GoogleVerifiedWebResource:
        raise AssertionError("Bing-only ownership must not redeem Google verification")


class _UnexpectedBingOwnershipClient:
    provider = BingWebmasterClient.provider

    async def site_verification_for_onboarding(self, *_: object) -> BingSiteVerification:
        raise AssertionError("Google-only ownership must not request a Bing CNAME")

    async def add_site_for_onboarding(self, *_: object) -> None:
        raise AssertionError("Google-only ownership must not add a Bing site")

    async def verify_site_for_onboarding(self, *_: object) -> bool:
        raise AssertionError("Google-only ownership must not redeem Bing verification")


@pytest.mark.asyncio
async def test_site_ownership_verifies_bing_without_contacting_google(tmp_path: Path) -> None:
    dns = _DnsOwnershipClient()
    operator = SiteOwnershipOperator(
        _policy(tmp_path),
        cast(GoogleSiteVerificationClient, _UnexpectedGoogleOwnershipClient()),
        cast(BingWebmasterClient, _BingOwnershipClient()),
        {Provider.CLOUDFLARE: cast(DnsOwnershipClient, dns)},
        cast(PublicDnsClient, _DnsClient()),
    )

    receipt = await operator.verify(
        SiteOwnershipWriteRequest(
            google_account_id=None,
            bing_account_id="bing-main",
            dns_account_id="cloudflare-main",
            site_url="https://example.com/",
            timeout_seconds=1.0,
        )
    )

    assert receipt.google is None
    assert receipt.bing is not None
    assert receipt.bing.verified is True
    assert receipt.complete is True
    assert dns.record_types == [DnsRecordType.CNAME]


@pytest.mark.asyncio
async def test_site_ownership_verifies_google_without_contacting_bing(tmp_path: Path) -> None:
    dns = _DnsOwnershipClient()
    operator = SiteOwnershipOperator(
        _policy(tmp_path),
        cast(GoogleSiteVerificationClient, _GoogleOwnershipClient()),
        cast(BingWebmasterClient, _UnexpectedBingOwnershipClient()),
        {Provider.CLOUDFLARE: cast(DnsOwnershipClient, dns)},
        cast(PublicDnsClient, _DnsClient()),
    )

    receipt = await operator.verify(
        SiteOwnershipWriteRequest(
            google_account_id="google-main",
            bing_account_id=None,
            dns_account_id="cloudflare-main",
            site_url="https://example.com/",
            timeout_seconds=1.0,
        )
    )

    assert receipt.google is not None
    assert receipt.google.verified is True
    assert receipt.bing is None
    assert receipt.complete is True
    assert dns.record_types == [DnsRecordType.TXT]


@pytest.mark.asyncio
async def test_site_ownership_rejects_empty_provider_selection(tmp_path: Path) -> None:
    operator = SiteOwnershipOperator(
        _policy(tmp_path),
        cast(GoogleSiteVerificationClient, _UnexpectedGoogleOwnershipClient()),
        cast(BingWebmasterClient, _UnexpectedBingOwnershipClient()),
        {Provider.CLOUDFLARE: cast(DnsOwnershipClient, _DnsOwnershipClient())},
        cast(PublicDnsClient, _DnsClient()),
    )

    with pytest.raises(InputLimitError, match="Google or Bing"):
        await operator.check(
            SiteOwnershipRequest(
                google_account_id=None,
                bing_account_id=None,
                site_url="https://example.com/",
                timeout_seconds=1.0,
            )
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("dns_account_id", ("google-main", "missing"))
async def test_site_ownership_rejects_invalid_dns_adapter_selection(
    tmp_path: Path,
    dns_account_id: str,
) -> None:
    operator = SiteOwnershipOperator(
        _policy(tmp_path),
        cast(GoogleSiteVerificationClient, _GoogleOwnershipClient()),
        cast(BingWebmasterClient, _BingOwnershipClient()),
        {},
        cast(PublicDnsClient, _DnsClient()),
    )

    with pytest.raises(BoundaryDeniedError):
        await operator.verify(
            SiteOwnershipWriteRequest(
                google_account_id="google-main",
                bing_account_id="bing-main",
                dns_account_id=dns_account_id,
                site_url="https://example.com/",
                timeout_seconds=1.0,
            )
        )


@pytest.mark.asyncio
async def test_site_audit_reports_page_failures_duplicates_and_truncation(tmp_path: Path) -> None:
    document = b"""<html><head><title>Repeated title that is deliberately much longer than sixty
    characters for the audit</title><meta name="robots" content="noindex"></head>
    <body><h1>One</h1><h1>Two</h1><img src="/image.png"><a href="/second/">Next</a>
    <a href="https://external.example/path">External</a></body></html>"""

    class Fetcher:
        async def fetch(self, url: str, _: float) -> SiteFetchResult:
            if url.endswith("robots.txt"):
                raise SiteFetchError("unavailable")
            if url.endswith("sitemap.xml"):
                return SiteFetchResult(url, 404, "text/plain", b"")
            if url.endswith("second/"):
                return SiteFetchResult(url, 200, "text/html", document)
            return SiteFetchResult(url, 200, "text/html", document)

    service = SiteAuditService(_policy(tmp_path), cast(PublicSiteFetcher, Fetcher()))
    report = await service.audit(
        SiteAuditRequest(
            account_id="google-main",
            site_url="https://example.com/",
            max_pages=2,
            max_depth=1,
        )
    )

    codes = {issue.code for issue in report.issues}
    assert {
        "long_title",
        "missing_description",
        "missing_canonical",
        "noindex",
        "missing_language",
        "h1_count",
        "missing_image_alt",
        "incomplete_open_graph",
        "structured_data",
        "duplicate_title",
    } <= codes
    assert report.pages[0].internal_links == 1
    assert report.pages[0].external_links == 1
    assert report.truncated is False
    assert report.score < 100


@pytest.mark.asyncio
async def test_site_audit_turns_fetch_and_non_html_failures_into_findings(tmp_path: Path) -> None:
    class Fetcher:
        async def fetch(self, url: str, _: float) -> SiteFetchResult:
            if url.endswith("robots.txt"):
                return SiteFetchResult(
                    url,
                    200,
                    "text/plain",
                    b"Sitemap: https://outside.example/sitemap.xml\n"
                    b"Sitemap: https://example.com/feed.xml\n",
                )
            if url.endswith("sitemap.xml"):
                return SiteFetchResult(url, 500, "text/plain", b"")
            if url.endswith("feed.xml"):
                return SiteFetchResult(
                    url,
                    200,
                    "application/xml",
                    b"<urlset><loc>https://example.com/file.pdf</loc>"
                    b"<loc>https://example.com/missing/</loc>"
                    b"<loc>https://outside.example/</loc></urlset>",
                )
            if url.endswith("file.pdf"):
                return SiteFetchResult(url, 200, "application/pdf", b"")
            if url == "https://example.com/":
                return SiteFetchResult(url, 503, "text/html", b"")
            raise SiteFetchError("private fetch detail")

    service = SiteAuditService(_policy(tmp_path), cast(PublicSiteFetcher, Fetcher()))
    report = await service.audit(
        SiteAuditRequest(
            account_id="google-main",
            site_url="https://example.com/",
            max_pages=3,
            max_depth=0,
        )
    )

    assert report.discovered_sitemaps == (
        "https://example.com/sitemap.xml",
        "https://example.com/feed.xml",
    )
    assert {issue.code for issue in report.issues} == {
        "fetch_failed",
        "http_status",
        "invalid_sitemap_xml",
        "non_html_page",
    }
    assert tuple(page.status_code for page in report.pages) == (503, 200, 0)


@pytest.mark.asyncio
async def test_site_audit_marks_pending_pages_as_truncated(tmp_path: Path) -> None:
    class Fetcher:
        async def fetch(self, url: str, _: float) -> SiteFetchResult:
            if url.endswith(("robots.txt", "sitemap.xml")):
                return SiteFetchResult(url, 404, "text/plain", b"")
            return SiteFetchResult(
                url,
                200,
                "text/html",
                b'<html lang="en"><head><title>Home</title></head>'
                b'<body><h1>Home</h1><a href="/one/">One</a>'
                b'<a href="/two/">Two</a></body></html>',
            )

    report = await SiteAuditService(
        _policy(tmp_path),
        cast(PublicSiteFetcher, Fetcher()),
    ).audit(
        SiteAuditRequest(
            account_id="google-main",
            site_url="https://example.com/",
            max_pages=1,
            max_depth=1,
        )
    )

    assert report.truncated is True
    assert len(report.pages) == 1


@pytest.mark.parametrize(
    ("max_pages", "max_depth"),
    ((0, 1), (201, 1), (1, -1), (1, 5)),
)
def test_site_audit_request_enforces_crawl_limits(max_pages: int, max_depth: int) -> None:
    with pytest.raises(InputLimitError):
        SiteAuditRequest(
            account_id="google-main",
            site_url="https://example.com/",
            max_pages=max_pages,
            max_depth=max_depth,
        )


class _MissingBingOwnershipClient:
    provider = BingWebmasterClient.provider

    def __init__(self) -> None:
        self.added = 0

    async def site_verification_for_onboarding(self, *_: object) -> None:
        return None

    async def add_site_for_onboarding(self, *_: object) -> None:
        self.added += 1


@pytest.mark.asyncio
async def test_site_ownership_check_handles_absent_bing_site_without_writes(
    tmp_path: Path,
) -> None:
    bing = _MissingBingOwnershipClient()
    operator = SiteOwnershipOperator(
        _policy(tmp_path),
        cast(GoogleSiteVerificationClient, _GoogleOwnershipClient()),
        cast(BingWebmasterClient, bing),
        {Provider.CLOUDFLARE: cast(DnsOwnershipClient, _DnsOwnershipClient())},
        cast(PublicDnsClient, _DnsClient()),
    )
    request = SiteOwnershipRequest(
        google_account_id="google-main",
        bing_account_id="bing-main",
        site_url="https://example.com/",
        timeout_seconds=1.0,
    )

    receipt = await operator.check(request)

    assert receipt.complete is False
    assert receipt.google is not None
    assert receipt.google.verified is False
    assert bing.added == 0


@pytest.mark.asyncio
async def test_site_ownership_verify_refuses_missing_bing_material_after_add(
    tmp_path: Path,
) -> None:
    bing = _MissingBingOwnershipClient()
    operator = SiteOwnershipOperator(
        _policy(tmp_path),
        cast(GoogleSiteVerificationClient, _GoogleOwnershipClient()),
        cast(BingWebmasterClient, bing),
        {Provider.CLOUDFLARE: cast(DnsOwnershipClient, _DnsOwnershipClient())},
        cast(PublicDnsClient, _DnsClient()),
    )

    with pytest.raises(InputLimitError, match="verification material"):
        await operator.verify(
            SiteOwnershipWriteRequest(
                google_account_id="google-main",
                bing_account_id="bing-main",
                dns_account_id="cloudflare-main",
                site_url="https://example.com/",
                timeout_seconds=1.0,
            )
        )

    assert bing.added == 1


@pytest.mark.asyncio
async def test_site_ownership_service_exposes_status_and_successful_apply(tmp_path: Path) -> None:
    operator = SiteOwnershipOperator(
        _policy(tmp_path),
        cast(GoogleSiteVerificationClient, _GoogleOwnershipClient()),
        cast(BingWebmasterClient, _BingOwnershipClient()),
        {Provider.CLOUDFLARE: cast(DnsOwnershipClient, _DnsOwnershipClient())},
        cast(PublicDnsClient, _DnsClient()),
    )
    service = SiteOwnershipService(operator)
    check_request = SiteOwnershipCheckRequest(
        google_account_id="google-main",
        bing_account_id="bing-main",
        site_url="https://example.com/",
        timeout_seconds=1.0,
    )
    verification_request = SiteOwnershipVerificationRequest(
        google_account_id="google-main",
        bing_account_id="bing-main",
        dns_account_id="cloudflare-main",
        site_url="https://example.com/",
        timeout_seconds=1.0,
    )

    checked = await service.check(check_request)
    applied = await service.verify(verification_request)

    assert checked.complete is False
    assert applied.complete is True


@pytest.mark.asyncio
async def test_site_ownership_service_preserves_safe_provider_failures() -> None:
    class FailingOperator:
        async def verify(self, _: SiteOwnershipWriteRequest) -> SiteOwnershipReceipt:
            raise ProviderOperationError(
                ProviderFailureCode.UNAVAILABLE,
                "safe provider failure",
            )

    service = SiteOwnershipService(cast(SiteOwnershipOperator, FailingOperator()))

    with pytest.raises(ProviderOperationError, match="safe provider failure"):
        await service.verify(
            SiteOwnershipVerificationRequest(
                google_account_id="google-main",
                bing_account_id="bing-main",
                dns_account_id="cloudflare-main",
                site_url="https://example.com/",
                timeout_seconds=1.0,
            )
        )
