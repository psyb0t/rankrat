"""Deterministic internal-link graph, orphan, and opportunity analysis."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from urllib.parse import unquote, urljoin, urlsplit

from rankrat.constants import (
    DEFAULT_SITE_AUDIT_DEPTH,
    DEFAULT_SITE_AUDIT_PAGES,
    MAX_INTERNAL_LINK_OPPORTUNITIES,
)
from rankrat.errors import InputLimitError
from rankrat.models.boundaries import configured_site_contains_url
from rankrat.services.google_analytics import Ga4FixedReportRequest, GoogleAnalyticsDataService
from rankrat.services.google_search_console import (
    GoogleSearchConsoleService,
    SearchAnalyticsPagePerformanceRequest,
)
from rankrat.services.site_audit import SiteAuditReport, SiteAuditRequest, SiteAuditService


@dataclass(frozen=True, slots=True)
class InternalLinkRequest:
    account_id: str
    site_url: str
    max_pages: int = DEFAULT_SITE_AUDIT_PAGES
    max_depth: int = DEFAULT_SITE_AUDIT_DEPTH
    opportunity_limit: int = 100

    def __post_init__(self) -> None:
        if not 1 <= self.opportunity_limit <= MAX_INTERNAL_LINK_OPPORTUNITIES:
            raise InputLimitError("internal-link opportunity limit is outside the allowed range")


@dataclass(frozen=True, slots=True)
class OrphanPageRequest:
    crawl_account_id: str
    crawl_site_url: str
    search_console_account_id: str
    search_console_site_url: str
    ga4_account_id: str
    ga4_property_id: str
    start_date: date
    end_date: date
    max_pages: int = DEFAULT_SITE_AUDIT_PAGES
    max_depth: int = DEFAULT_SITE_AUDIT_DEPTH

    def __post_init__(self) -> None:
        if self.end_date < self.start_date:
            raise InputLimitError("orphan evidence date range is invalid")


@dataclass(frozen=True, slots=True)
class InternalLinkNode:
    url: str
    title: str | None
    inbound_links: int
    outbound_links: int
    crawl_depth: int
    discovered_in_sitemap: bool
    issue_count: int


@dataclass(frozen=True, slots=True)
class InternalLinkEdge:
    source_url: str
    target_url: str


@dataclass(frozen=True, slots=True)
class InternalLinkGraph:
    site_url: str
    nodes: tuple[InternalLinkNode, ...]
    edges: tuple[InternalLinkEdge, ...]
    truncated: bool


@dataclass(frozen=True, slots=True)
class OrphanPageFinding:
    url: str
    classification: str
    evidence: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class OrphanPageReport:
    site_url: str
    findings: tuple[OrphanPageFinding, ...]
    crawl_truncated: bool


@dataclass(frozen=True, slots=True)
class InternalLinkOpportunity:
    source_url: str
    target_url: str
    suggested_anchor: str
    score: int
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class InternalLinkOpportunityReport:
    site_url: str
    opportunities: tuple[InternalLinkOpportunity, ...]
    crawl_truncated: bool


class InternalLinkOperator:
    """Build link intelligence from the exact same bounded crawl as site audits."""

    def __init__(
        self,
        site_audit: SiteAuditService,
        google_search_console: GoogleSearchConsoleService,
        google_analytics: GoogleAnalyticsDataService,
    ) -> None:
        self._site_audit = site_audit
        self._google_search_console = google_search_console
        self._google_analytics = google_analytics

    async def graph(self, request: InternalLinkRequest) -> InternalLinkGraph:
        report = await self._crawl(request)
        page_urls = frozenset(page.url for page in report.pages)
        edges = tuple(
            InternalLinkEdge(page.url, target)
            for page in report.pages
            for target in page.internal_link_urls
            if target in page_urls and target != page.url
        )
        inbound_counts = {url: 0 for url in page_urls}
        for edge in edges:
            inbound_counts[edge.target_url] += 1
        nodes = tuple(
            InternalLinkNode(
                url=page.url,
                title=page.title,
                inbound_links=inbound_counts[page.url],
                outbound_links=sum(1 for edge in edges if edge.source_url == page.url),
                crawl_depth=page.crawl_depth,
                discovered_in_sitemap=page.discovered_in_sitemap,
                issue_count=page.issue_count,
            )
            for page in sorted(report.pages, key=lambda item: item.url)
        )
        return InternalLinkGraph(request.site_url, nodes, edges, report.truncated)

    async def orphans(self, request: OrphanPageRequest) -> OrphanPageReport:
        graph = await self.graph(
            InternalLinkRequest(
                account_id=request.crawl_account_id,
                site_url=request.crawl_site_url,
                max_pages=request.max_pages,
                max_depth=request.max_depth,
            )
        )
        search_report = await self._google_search_console.search_analytics_page_performance(
            SearchAnalyticsPagePerformanceRequest(
                account_id=request.search_console_account_id,
                site_url=request.search_console_site_url,
                start_date=request.start_date,
                end_date=request.end_date,
            )
        )
        analytics_report = await self._google_analytics.landing_page_performance(
            Ga4FixedReportRequest(
                account_id=request.ga4_account_id,
                property_id=request.ga4_property_id,
                start_date=request.start_date,
                end_date=request.end_date,
            )
        )
        search_pages = frozenset(
            row.key
            for row in search_report.rows
            if configured_site_contains_url(request.crawl_site_url, row.key)
        )
        analytics_pages = frozenset(
            page_url
            for page_url in _analytics_pages(
                request.crawl_site_url,
                analytics_report.report.dimension_headers,
                tuple(row.dimension_values for row in analytics_report.report.rows),
            )
            if configured_site_contains_url(request.crawl_site_url, page_url)
        )
        nodes = {node.url: node for node in graph.nodes}
        evidence_urls = frozenset(nodes) | search_pages | analytics_pages
        findings: list[OrphanPageFinding] = []
        for url in sorted(evidence_urls):
            if url == request.crawl_site_url:
                continue
            node = nodes.get(url)
            if node is not None and node.inbound_links > 0:
                continue
            evidence = tuple(
                reason
                for condition, reason in (
                    (node is not None, "discovered_by_crawl"),
                    (node is not None and node.discovered_in_sitemap, "present_in_sitemap"),
                    (url in search_pages, "has_search_console_visibility"),
                    (url in analytics_pages, "has_ga4_sessions"),
                    (node is None, "not_reached_by_internal_crawl"),
                    (node is not None, "no_inbound_internal_links"),
                )
                if condition
            )
            findings.append(
                OrphanPageFinding(
                    url,
                    _orphan_classification(node, url in search_pages, url in analytics_pages),
                    evidence,
                )
            )
        return OrphanPageReport(request.crawl_site_url, tuple(findings), graph.truncated)

    async def opportunities(
        self,
        request: InternalLinkRequest,
    ) -> InternalLinkOpportunityReport:
        graph = await self.graph(request)
        linked_pairs = frozenset((edge.source_url, edge.target_url) for edge in graph.edges)
        candidates: list[InternalLinkOpportunity] = []
        for source in graph.nodes:
            for target in graph.nodes:
                if source.url == target.url or (source.url, target.url) in linked_pairs:
                    continue
                if target.title is None or target.inbound_links < 1:
                    continue
                shared_terms = _page_terms(source) & _page_terms(target)
                if not shared_terms:
                    continue
                score = min(
                    100,
                    40 + len(shared_terms) * 15 + max(0, 3 - target.inbound_links) * 10,
                )
                candidates.append(
                    InternalLinkOpportunity(
                        source.url,
                        target.url,
                        target.title,
                        score,
                        (
                            "shared_topic_terms",
                            "target_is_underlinked",
                            "source_does_not_link_to_target",
                        ),
                    )
                )
        candidates.sort(key=lambda item: (-item.score, item.source_url, item.target_url))
        return InternalLinkOpportunityReport(
            request.site_url,
            tuple(candidates[: request.opportunity_limit]),
            graph.truncated,
        )

    async def _crawl(self, request: InternalLinkRequest) -> SiteAuditReport:
        return await self._site_audit.audit(
            SiteAuditRequest(
                account_id=request.account_id,
                site_url=request.site_url,
                max_pages=request.max_pages,
                max_depth=request.max_depth,
            )
        )


def _analytics_pages(
    site_url: str,
    dimensions: tuple[str, ...],
    rows: tuple[tuple[str, ...], ...],
) -> frozenset[str]:
    if not dimensions:
        return frozenset()
    return frozenset(
        urljoin(site_url, values[0])
        for values in rows
        if values and values[0] not in {"", "(not set)"}
    )


def _orphan_classification(
    node: InternalLinkNode | None,
    has_search_evidence: bool,
    has_analytics_evidence: bool,
) -> str:
    if node is not None and node.discovered_in_sitemap:
        return "sitemap_without_internal_links"
    if has_search_evidence and has_analytics_evidence:
        return "search_and_analytics_without_internal_links"
    if has_search_evidence:
        return "search_without_internal_links"
    if has_analytics_evidence:
        return "analytics_without_internal_links"
    return "crawl_orphan"


_TOPIC_TOKEN_PATTERN = re.compile(r"[a-z0-9]{3,}")
_TOPIC_STOP_WORDS = frozenset(
    {
        "about",
        "and",
        "blog",
        "category",
        "contact",
        "from",
        "home",
        "page",
        "the",
        "this",
        "with",
    }
)


def _page_terms(node: InternalLinkNode) -> frozenset[str]:
    parsed = urlsplit(node.url)
    source = f"{node.title or ''} {unquote(parsed.path)}"
    return frozenset(
        token
        for token in _TOPIC_TOKEN_PATTERN.findall(source.casefold())
        if token not in _TOPIC_STOP_WORDS
    )
