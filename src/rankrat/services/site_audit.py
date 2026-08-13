"""Bounded whole-site technical SEO auditing with deterministic local checks."""

from __future__ import annotations

import html
import re
from collections import Counter, deque
from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import urljoin, urlparse

from rankrat.constants import (
    DEFAULT_PROVIDER_TIMEOUT_SECONDS,
    DEFAULT_SITE_AUDIT_DEPTH,
    DEFAULT_SITE_AUDIT_PAGES,
    MAX_SITE_AUDIT_DEPTH,
    MAX_SITE_AUDIT_ISSUES,
    MAX_SITE_AUDIT_LINKS_PER_PAGE,
    MAX_SITE_AUDIT_PAGES,
    MAX_SITE_AUDIT_SITEMAPS,
)
from rankrat.errors import InputLimitError, SiteFetchError
from rankrat.models.boundaries import (
    configured_site_contains_url,
    normalize_public_https_root_url,
    normalize_public_https_url,
)
from rankrat.policy.boundaries import BoundaryPolicy
from rankrat.providers.site_fetch import PublicSiteFetcher, SiteFetchResult
from rankrat.services.schema import assess_google_indexing_eligibility

_HTML_CONTENT_TYPES = frozenset({"application/xhtml+xml", "text/html"})
_TITLE_PATTERN = re.compile(r"<title(?:\s[^<>]{0,8192})?>(.*?)</title\s*>", re.I | re.S)
_TAG_PATTERN = re.compile(
    r"<(?P<closing>/)?(?P<name>[A-Za-z][A-Za-z0-9:-]*)(?P<attrs>[^<>]{0,8192})>",
    re.I,
)
_ATTRIBUTE_PATTERN = re.compile(
    r"(?P<name>[A-Za-z_:][A-Za-z0-9_.:-]*)\s*(?:=\s*(?P<value>\"[^\"]*\"|'[^']*'|[^\s\"'=<>`]+))?",
    re.S,
)
_XML_DANGEROUS_DECLARATION_PATTERN = re.compile(r"<!\s*(?:DOCTYPE|ENTITY)\b", re.I)
_SITEMAP_LOCATION_PATTERN = re.compile(
    r"<(?:[A-Za-z_][A-Za-z0-9_.-]*:)?loc\b[^>]{0,8192}>\s*"
    r"(?P<value>[^<]{0,2048})\s*"
    r"</(?:[A-Za-z_][A-Za-z0-9_.-]*:)?loc\s*>",
    re.I | re.S,
)
_MAX_TITLE_CHARS = 60
_MAX_DESCRIPTION_CHARS = 160
_MIN_DESCRIPTION_CHARS = 50


class SiteAuditSeverity(StrEnum):
    """Stable severity classes used by score deduction and remediation."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass(frozen=True, slots=True)
class SiteAuditRequest:
    """One configured site root and bounded crawl controls."""

    account_id: str
    site_url: str
    max_pages: int = DEFAULT_SITE_AUDIT_PAGES
    max_depth: int = DEFAULT_SITE_AUDIT_DEPTH
    timeout_seconds: float = DEFAULT_PROVIDER_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        normalized_url = normalize_public_https_root_url(self.site_url, "site_url")
        if self.max_pages < 1 or self.max_pages > MAX_SITE_AUDIT_PAGES:
            raise InputLimitError("site audit page count is outside the allowed range")
        if self.max_depth < 0 or self.max_depth > MAX_SITE_AUDIT_DEPTH:
            raise InputLimitError("site audit depth is outside the allowed range")
        object.__setattr__(self, "site_url", normalized_url)


@dataclass(frozen=True, slots=True)
class SiteAuditIssue:
    """One actionable deterministic issue backed by fetched page evidence."""

    code: str
    severity: SiteAuditSeverity
    url: str
    message: str
    remediation: str


@dataclass(frozen=True, slots=True)
class SiteAuditPage:
    """One fetched page's stable audit summary."""

    url: str
    status_code: int
    title: str | None
    canonical_url: str | None
    internal_links: int
    external_links: int
    issue_count: int
    internal_link_urls: tuple[str, ...] = ()
    crawl_depth: int = 0
    discovered_in_sitemap: bool = False


@dataclass(frozen=True, slots=True)
class SiteAuditReport:
    """A bounded site score, pages, issues, and crawl completeness metadata."""

    site_url: str
    score: int
    pages: tuple[SiteAuditPage, ...]
    issues: tuple[SiteAuditIssue, ...]
    discovered_sitemaps: tuple[str, ...]
    truncated: bool


@dataclass(frozen=True, slots=True)
class _ParsedPage:
    title: str | None
    description: str | None
    canonical_url: str | None
    language: str | None
    robots: str | None
    h1_count: int
    image_count: int
    image_without_alt_count: int
    links: tuple[str, ...]
    has_open_graph_title: bool
    has_open_graph_description: bool
    hreflang_languages: tuple[str, ...]


class SiteAuditService:
    """Crawl configured pages only and derive reproducible technical SEO findings."""

    def __init__(self, policy: BoundaryPolicy, fetcher: PublicSiteFetcher) -> None:
        self._policy = policy
        self._fetcher = fetcher

    def authorize(self, account_id: str, site_url: str) -> str:
        """Authorize an exact configured site without making an outbound request."""

        return self._policy.require_pagespeed_url(account_id, site_url, site_url)

    async def audit(self, request: SiteAuditRequest) -> SiteAuditReport:
        """Audit robots, sitemaps, and a bounded same-site page graph."""

        self.authorize(request.account_id, request.site_url)
        discovered_sitemaps = await self._discover_sitemaps(request)
        issues: list[SiteAuditIssue] = []
        seeds = [request.site_url]
        for sitemap_url in discovered_sitemaps:
            sitemap_urls, sitemap_issue = await self._sitemap_urls(request, sitemap_url)
            seeds.extend(sitemap_urls)
            if sitemap_issue is not None:
                issues.append(sitemap_issue)
        sitemap_seeds = frozenset(seeds[1:])
        queue = deque((url, 0) for url in dict.fromkeys(seeds))
        queued = set(url for url, _ in queue)
        pages: list[SiteAuditPage] = []
        titles: dict[str, list[str]] = {}
        truncated = False
        while queue and len(pages) < request.max_pages:
            url, depth = queue.popleft()
            try:
                fetched = await self._fetcher.fetch(url, request.timeout_seconds)
            except SiteFetchError:
                issues.append(self._fetch_issue(url))
                pages.append(
                    SiteAuditPage(
                        url,
                        0,
                        None,
                        None,
                        0,
                        0,
                        1,
                        crawl_depth=depth,
                        discovered_in_sitemap=url in sitemap_seeds,
                    )
                )
                continue
            parsed, page_issues = self._audit_fetched_page(request.site_url, fetched)
            issues.extend(page_issues)
            if parsed.title:
                titles.setdefault(parsed.title.casefold(), []).append(url)
            internal_links = tuple(
                link
                for link in parsed.links
                if configured_site_contains_url(request.site_url, link)
            )
            internal_link_set = frozenset(internal_links)
            external_links = tuple(link for link in parsed.links if link not in internal_link_set)
            pages.append(
                SiteAuditPage(
                    url=fetched.url,
                    status_code=fetched.status_code,
                    title=parsed.title,
                    canonical_url=parsed.canonical_url,
                    internal_links=len(internal_links),
                    external_links=len(external_links),
                    issue_count=len(page_issues),
                    internal_link_urls=internal_links,
                    crawl_depth=depth,
                    discovered_in_sitemap=url in sitemap_seeds,
                )
            )
            if depth >= request.max_depth:
                continue
            for link in internal_links[:MAX_SITE_AUDIT_LINKS_PER_PAGE]:
                if link in queued:
                    continue
                queued.add(link)
                queue.append((link, depth + 1))
        if queue:
            truncated = True
        issues.extend(self._duplicate_title_issues(titles))
        bounded_issues = tuple(issues[:MAX_SITE_AUDIT_ISSUES])
        if len(issues) > len(bounded_issues):
            truncated = True
        return SiteAuditReport(
            site_url=request.site_url,
            score=self._score(bounded_issues, len(pages)),
            pages=tuple(pages),
            issues=bounded_issues,
            discovered_sitemaps=discovered_sitemaps,
            truncated=truncated,
        )

    async def _discover_sitemaps(self, request: SiteAuditRequest) -> tuple[str, ...]:
        candidates = [urljoin(request.site_url, "sitemap.xml")]
        robots_url = urljoin(request.site_url, "robots.txt")
        try:
            robots = await self._fetcher.fetch(robots_url, request.timeout_seconds)
        except SiteFetchError:
            return tuple(candidates)
        if robots.status_code == 200:
            for line in robots.body.decode("utf-8", errors="replace").splitlines():
                field, separator, value = line.partition(":")
                if not separator or field.strip().casefold() != "sitemap":
                    continue
                candidate = value.strip()
                try:
                    if configured_site_contains_url(request.site_url, candidate):
                        candidates.append(candidate)
                except ValueError:
                    continue
        return tuple(dict.fromkeys(candidates[:MAX_SITE_AUDIT_SITEMAPS]))

    async def _sitemap_urls(
        self,
        request: SiteAuditRequest,
        sitemap_url: str,
    ) -> tuple[tuple[str, ...], SiteAuditIssue | None]:
        try:
            fetched = await self._fetcher.fetch(sitemap_url, request.timeout_seconds)
        except SiteFetchError:
            return (), self._invalid_sitemap_issue(sitemap_url)
        if fetched.status_code != 200:
            return (), self._invalid_sitemap_issue(sitemap_url)
        if _XML_DANGEROUS_DECLARATION_PATTERN.search(
            fetched.body.decode("utf-8", errors="replace")
        ):
            return (), self._invalid_sitemap_issue(sitemap_url)
        urls: list[str] = []
        sitemap = fetched.body.decode("utf-8", errors="replace")
        for match in _SITEMAP_LOCATION_PATTERN.finditer(sitemap):
            candidate = html.unescape(match.group("value")).strip()
            try:
                if configured_site_contains_url(request.site_url, candidate):
                    urls.append(candidate)
            except ValueError:
                continue
            if len(urls) >= request.max_pages:
                break
        return tuple(dict.fromkeys(urls)), None

    @classmethod
    def _audit_fetched_page(
        cls,
        site_url: str,
        fetched: SiteFetchResult,
    ) -> tuple[_ParsedPage, tuple[SiteAuditIssue, ...]]:
        if fetched.status_code != 200:
            empty = _ParsedPage(None, None, None, None, None, 0, 0, 0, (), False, False, ())
            issue = SiteAuditIssue(
                "http_status",
                SiteAuditSeverity.ERROR,
                fetched.url,
                f"Page returned HTTP {fetched.status_code}.",
                "Restore a crawlable 200 response or remove the URL from navigation and sitemaps.",
            )
            return empty, (issue,)
        if fetched.content_type not in _HTML_CONTENT_TYPES:
            empty = _ParsedPage(None, None, None, None, None, 0, 0, 0, (), False, False, ())
            issue = SiteAuditIssue(
                "non_html_page",
                SiteAuditSeverity.WARNING,
                fetched.url,
                "Crawl target did not return HTML.",
                "Keep non-HTML resources out of page sitemaps and crawl navigation.",
            )
            return empty, (issue,)
        document = fetched.body.decode("utf-8", errors="replace")
        parsed = cls._parse_page(fetched.url, document)
        return parsed, cls._page_issues(
            site_url,
            fetched.url,
            fetched.body,
            dict(fetched.headers),
            parsed,
        )

    @staticmethod
    def _parse_page(page_url: str, document: str) -> _ParsedPage:
        title_match = _TITLE_PATTERN.search(document)
        title = html.unescape(title_match.group(1)).strip() if title_match else None
        description: str | None = None
        canonical_url: str | None = None
        language: str | None = None
        robots: str | None = None
        links: list[str] = []
        h1_count = 0
        image_count = 0
        image_without_alt_count = 0
        has_open_graph_title = False
        has_open_graph_description = False
        hreflang_languages: list[str] = []
        for tag in _TAG_PATTERN.finditer(document):
            if tag.group("closing"):
                continue
            name = tag.group("name").casefold()
            attributes = _attributes(tag.group("attrs"))
            if name == "html":
                language = attributes.get("lang")
            elif name == "h1":
                h1_count += 1
            elif name == "img":
                image_count += 1
                if not attributes.get("alt", "").strip():
                    image_without_alt_count += 1
            elif name == "a" and "href" in attributes:
                normalized = _audit_link(page_url, attributes["href"])
                if normalized is not None:
                    links.append(normalized)
            elif name == "link":
                relations = frozenset(attributes.get("rel", "").casefold().split())
                if "canonical" in relations:
                    canonical_url = _audit_link(page_url, attributes.get("href", ""))
                if "alternate" in relations and attributes.get("hreflang"):
                    hreflang_languages.append(attributes["hreflang"].casefold())
            elif name == "meta":
                key = attributes.get("name", attributes.get("property", "")).casefold()
                value = attributes.get("content", "").strip()
                if key == "description":
                    description = value
                elif key == "robots":
                    robots = value.casefold()
                elif key == "og:title":
                    has_open_graph_title = bool(value)
                elif key == "og:description":
                    has_open_graph_description = bool(value)
        return _ParsedPage(
            title,
            description,
            canonical_url,
            language,
            robots,
            h1_count,
            image_count,
            image_without_alt_count,
            tuple(dict.fromkeys(links)),
            has_open_graph_title,
            has_open_graph_description,
            tuple(hreflang_languages),
        )

    @staticmethod
    def _page_issues(
        site_url: str,
        page_url: str,
        body: bytes,
        headers: dict[str, str],
        page: _ParsedPage,
    ) -> tuple[SiteAuditIssue, ...]:
        issues: list[SiteAuditIssue] = []

        def add(
            code: str,
            severity: SiteAuditSeverity,
            message: str,
            remediation: str,
        ) -> None:
            issues.append(SiteAuditIssue(code, severity, page_url, message, remediation))

        if not page.title:
            add(
                "missing_title",
                SiteAuditSeverity.ERROR,
                "Page has no title.",
                "Add a unique title element.",
            )
        elif len(page.title) > _MAX_TITLE_CHARS:
            add(
                "long_title",
                SiteAuditSeverity.WARNING,
                "Page title is long.",
                "Shorten the title to about 60 characters.",
            )
        if not page.description:
            add(
                "missing_description",
                SiteAuditSeverity.WARNING,
                "Page has no meta description.",
                "Add a specific meta description.",
            )
        elif not _MIN_DESCRIPTION_CHARS <= len(page.description) <= _MAX_DESCRIPTION_CHARS:
            add(
                "description_length",
                SiteAuditSeverity.INFO,
                "Meta description length is weak.",
                "Keep the description between 50 and 160 characters.",
            )
        if page.canonical_url is None:
            add(
                "missing_canonical",
                SiteAuditSeverity.WARNING,
                "Page has no canonical URL.",
                "Add a self-referencing canonical URL.",
            )
        elif not configured_site_contains_url(site_url, page.canonical_url):
            add(
                "external_canonical",
                SiteAuditSeverity.ERROR,
                "Canonical URL leaves the site boundary.",
                "Point canonical to the intended same-site URL.",
            )
        if page.robots and "noindex" in page.robots:
            add(
                "noindex",
                SiteAuditSeverity.WARNING,
                "Page asks search engines not to index it.",
                "Remove noindex when the page should rank.",
            )
        if not page.language:
            add(
                "missing_language",
                SiteAuditSeverity.INFO,
                "Document language is missing.",
                "Set the HTML lang attribute.",
            )
        if page.h1_count != 1:
            add(
                "h1_count",
                SiteAuditSeverity.WARNING,
                f"Page has {page.h1_count} H1 elements.",
                "Use one descriptive H1.",
            )
        if page.image_without_alt_count:
            add(
                "missing_image_alt",
                SiteAuditSeverity.WARNING,
                f"{page.image_without_alt_count} images lack alt text.",
                "Add meaningful alt text or an explicit empty alt for decorative images.",
            )
        if not page.has_open_graph_title or not page.has_open_graph_description:
            add(
                "incomplete_open_graph",
                SiteAuditSeverity.INFO,
                "Open Graph title or description is missing.",
                "Add complete Open Graph metadata.",
            )
        if not headers.get("strict-transport-security"):
            add(
                "missing_hsts",
                SiteAuditSeverity.INFO,
                "HTTPS response has no Strict-Transport-Security header.",
                "Set a suitable Strict-Transport-Security header after confirming HTTPS coverage.",
            )
        if headers.get("x-content-type-options", "").casefold() != "nosniff":
            add(
                "missing_nosniff",
                SiteAuditSeverity.INFO,
                "Response does not set X-Content-Type-Options: nosniff.",
                "Set X-Content-Type-Options to nosniff.",
            )
        if not headers.get("referrer-policy"):
            add(
                "missing_referrer_policy",
                SiteAuditSeverity.INFO,
                "Response has no Referrer-Policy header.",
                "Set an appropriate Referrer-Policy header.",
            )
        content_security_policy = headers.get("content-security-policy", "").casefold()
        if not headers.get("x-frame-options") and "frame-ancestors" not in content_security_policy:
            add(
                "missing_frame_protection",
                SiteAuditSeverity.INFO,
                "Response has no framing protection header.",
                "Set X-Frame-Options or CSP frame-ancestors.",
            )
        if len(set(page.hreflang_languages)) != len(page.hreflang_languages):
            add(
                "duplicate_hreflang",
                SiteAuditSeverity.WARNING,
                "Page repeats a hreflang language value.",
                "Keep one alternate link per hreflang language value.",
            )
        eligibility = assess_google_indexing_eligibility(body)
        if not eligibility.eligible:
            add(
                "structured_data",
                SiteAuditSeverity.INFO,
                "No restricted-indexing structured data was found.",
                "Add valid structured data only when the page type supports it.",
            )
        return tuple(issues)

    @staticmethod
    def _duplicate_title_issues(titles: dict[str, list[str]]) -> tuple[SiteAuditIssue, ...]:
        issues: list[SiteAuditIssue] = []
        for urls in titles.values():
            if len(urls) < 2:
                continue
            for url in urls:
                issues.append(
                    SiteAuditIssue(
                        "duplicate_title",
                        SiteAuditSeverity.WARNING,
                        url,
                        "Page title is duplicated elsewhere in the crawl.",
                        "Give each indexable page a unique intent-specific title.",
                    )
                )
        return tuple(issues)

    @staticmethod
    def _fetch_issue(url: str) -> SiteAuditIssue:
        return SiteAuditIssue(
            "fetch_failed",
            SiteAuditSeverity.ERROR,
            url,
            "Page could not be fetched safely.",
            "Fix DNS, TLS, reachability, or the URL and rerun the audit.",
        )

    @staticmethod
    def _invalid_sitemap_issue(url: str) -> SiteAuditIssue:
        return SiteAuditIssue(
            "invalid_sitemap_xml",
            SiteAuditSeverity.WARNING,
            url,
            "Sitemap is unavailable, invalid XML, or uses prohibited XML declarations.",
            "Serve a parseable XML sitemap without DTD or entity declarations.",
        )

    @staticmethod
    def _score(issues: tuple[SiteAuditIssue, ...], page_count: int) -> int:
        deductions = Counter(issue.severity for issue in issues)
        penalty = (
            deductions[SiteAuditSeverity.ERROR] * 8
            + deductions[SiteAuditSeverity.WARNING] * 3
            + deductions[SiteAuditSeverity.INFO]
        )
        normalized_penalty = round(penalty / max(1, page_count))
        return max(0, 100 - normalized_penalty)


def _attributes(raw_attributes: str) -> dict[str, str]:
    attributes: dict[str, str] = {}
    for match in _ATTRIBUTE_PATTERN.finditer(raw_attributes):
        name = match.group("name").casefold()
        raw_value = match.group("value") or ""
        if raw_value[:1] in {'"', "'"} and raw_value[-1:] == raw_value[:1]:
            raw_value = raw_value[1:-1]
        attributes.setdefault(name, html.unescape(raw_value))
    return attributes


def _audit_link(page_url: str, raw_link: str) -> str | None:
    candidate = html.unescape(raw_link).strip()
    if not candidate or candidate.startswith(("#", "mailto:", "tel:", "javascript:")):
        return None
    absolute = urljoin(page_url, candidate)
    parsed = urlparse(absolute)
    if parsed.scheme != "https" or parsed.query or parsed.fragment:
        return None
    try:
        return normalize_public_https_url(absolute, "audit_link")
    except ValueError:
        return None
