from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest

from rankrat.models.boundaries import BoundaryDocument
from rankrat.policy.boundaries import BoundaryPolicy
from rankrat.providers.site_fetch import PublicSiteFetcher, SiteFetchResult
from rankrat.services.site_audit import SiteAuditRequest, SiteAuditService

_PAGE_WITH_DUPLICATE_HREFLANG = (
    b'<html lang="en"><head><title>Example</title>'
    b'<meta name="description" content="A sufficiently descriptive page summary '
    b'for search results and users.">'
    b'<meta property="og:title" content="Example">'
    b'<meta property="og:description" content="Summary">'
    b'<link rel="canonical" href="https://example.com/">'
    b'<link rel="alternate" hreflang="en" href="https://example.com/">'
    b'<link rel="alternate" hreflang="EN" href="https://example.com/">'
    b"</head><body><h1>Example</h1></body></html>"
)
_PAGE_WITH_RESPONSE_CONTROLS = (
    b'<html lang="en"><head><title>Example</title>'
    b'<meta name="description" content="A sufficiently descriptive page summary '
    b'for search results and users.">'
    b'<meta property="og:title" content="Example">'
    b'<meta property="og:description" content="Summary">'
    b'<link rel="canonical" href="https://example.com/">'
    b"</head><body><h1>Example</h1></body></html>"
)


def _policy(tmp_path: Path) -> BoundaryPolicy:
    return BoundaryPolicy(
        BoundaryDocument.model_validate(
            {
                "accounts": [
                    {
                        "id": "google-main",
                        "provider": "google",
                        "credential": str(tmp_path / "google-client.json"),
                        "pagespeed_sites": ["https://example.com/"],
                    }
                ]
            }
        )
    )


class _Fetcher:
    def __init__(self, result: SiteFetchResult) -> None:
        self._result = result

    async def fetch(self, _: str, __: float) -> SiteFetchResult:
        return self._result


def test_site_audit_reports_missing_headers_and_duplicate_hreflang_deterministically() -> None:
    result = SiteFetchResult(
        "https://example.com/",
        200,
        "text/html",
        _PAGE_WITH_DUPLICATE_HREFLANG,
    )

    _, issues = SiteAuditService._audit_fetched_page("https://example.com/", result)

    codes = {issue.code for issue in issues}
    assert {
        "missing_hsts",
        "missing_nosniff",
        "missing_referrer_policy",
        "missing_frame_protection",
        "duplicate_hreflang",
    } <= codes


def test_site_audit_does_not_report_header_issues_when_equivalent_controls_exist() -> None:
    result = SiteFetchResult(
        "https://example.com/",
        200,
        "text/html",
        _PAGE_WITH_RESPONSE_CONTROLS,
        (
            ("strict-transport-security", "max-age=31536000"),
            ("x-content-type-options", "nosniff"),
            ("referrer-policy", "strict-origin-when-cross-origin"),
            ("content-security-policy", "frame-ancestors 'none'"),
        ),
    )

    _, issues = SiteAuditService._audit_fetched_page("https://example.com/", result)

    assert {
        "missing_hsts",
        "missing_nosniff",
        "missing_referrer_policy",
        "missing_frame_protection",
    }.isdisjoint(issue.code for issue in issues)


@pytest.mark.asyncio
async def test_site_audit_rejects_dtd_sitemaps_without_resolving_external_entities(
    tmp_path: Path,
) -> None:
    service = SiteAuditService(
        _policy(tmp_path),
        cast(
            PublicSiteFetcher,
            _Fetcher(
                SiteFetchResult(
                    "https://example.com/sitemap.xml",
                    200,
                    "application/xml",
                    b'<!DOCTYPE urlset SYSTEM "https://evil.example/sitemap.dtd"><urlset/>',
                )
            ),
        ),
    )
    request = SiteAuditRequest("google-main", "https://example.com/")

    urls, issue = await service._sitemap_urls(request, "https://example.com/sitemap.xml")

    assert urls == ()
    assert issue is not None
    assert issue.code == "invalid_sitemap_xml"


@pytest.mark.asyncio
async def test_site_audit_extracts_namespaced_sitemap_locations_without_xml_parsing(
    tmp_path: Path,
) -> None:
    service = SiteAuditService(
        _policy(tmp_path),
        cast(
            PublicSiteFetcher,
            _Fetcher(
                SiteFetchResult(
                    "https://example.com/sitemap.xml",
                    200,
                    "application/xml",
                    b'<urlset xmlns:sm="https://www.sitemaps.org/schemas/sitemap/0.9">'
                    b"<url><loc>https://example.com/?first=one&amp;second=two</loc></url>"
                    b"<url><sm:loc>https://example.com/nested/</sm:loc></url>"
                    b"<url><loc>https://outside.example/</loc></url></urlset>",
                )
            ),
        ),
    )
    request = SiteAuditRequest("google-main", "https://example.com/")

    urls, issue = await service._sitemap_urls(request, "https://example.com/sitemap.xml")

    assert urls == (
        "https://example.com/?first=one&second=two",
        "https://example.com/nested/",
    )
    assert issue is None
