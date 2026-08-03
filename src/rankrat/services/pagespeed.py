"""Bounded PageSpeed analyses for explicit PageSpeed site boundaries."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from rankrat.constants import (
    DEFAULT_PAGESPEED_TIMEOUT_SECONDS,
    MAX_PAGESPEED_CATEGORIES,
    PAGESPEED_CUMULATIVE_LAYOUT_SHIFT_METRIC_IDS,
    PAGESPEED_INTERACTION_TO_NEXT_PAINT_METRIC_IDS,
    PAGESPEED_LARGEST_CONTENTFUL_PAINT_METRIC_IDS,
)
from rankrat.errors import InputLimitError
from rankrat.models.boundaries import ResourceKind
from rankrat.policy.boundaries import BoundaryPolicy
from rankrat.providers.base import AccountId, ProviderReadRequest
from rankrat.providers.pagespeed import (
    PageSpeedAnalysisResult,
    PageSpeedClient,
    PageSpeedLoadingExperience,
    PageSpeedLoadingExperienceMetric,
    PageSpeedMetricDistribution,
)


class PageSpeedStrategy(str, Enum):
    """Supported PageSpeed device strategies."""

    DESKTOP = "DESKTOP"
    MOBILE = "MOBILE"


class PageSpeedCategory(str, Enum):
    """Supported non-deprecated PageSpeed audit categories."""

    ACCESSIBILITY = "ACCESSIBILITY"
    AGENTIC_BROWSING = "AGENTIC_BROWSING"
    BEST_PRACTICES = "BEST_PRACTICES"
    PERFORMANCE = "PERFORMANCE"
    SEO = "SEO"


@dataclass(frozen=True, slots=True)
class PageSpeedAnalysisRequest:
    """One policy-authorized PageSpeed request for a child URL."""

    account_id: str
    site_url: str
    page_url: str
    strategy: PageSpeedStrategy = PageSpeedStrategy.DESKTOP
    categories: tuple[PageSpeedCategory, ...] = ()
    timeout_seconds: float = DEFAULT_PAGESPEED_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        if len(self.categories) > MAX_PAGESPEED_CATEGORIES:
            raise InputLimitError("PageSpeed category count exceeds the allowed range")
        if len(set(self.categories)) != len(self.categories):
            raise InputLimitError("PageSpeed categories must not repeat")


@dataclass(frozen=True, slots=True)
class PageSpeedCategoryScore:
    """One stable Lighthouse category score in a public PageSpeed report."""

    category: str
    score: float | None


@dataclass(frozen=True, slots=True)
class PageSpeedAnalysisReport:
    """Typed PageSpeed analysis summary suitable for REST and MCP output."""

    analyzed_url: str
    analysis_utc_timestamp: str
    categories: tuple[PageSpeedCategoryScore, ...]
    loading_experience_category: str | None
    origin_loading_experience_category: str | None


class PageSpeedCoreWebVitalKind(str, Enum):
    """Server-owned Core Web Vitals extracted from Chrome UX field data."""

    LARGEST_CONTENTFUL_PAINT = "largest_contentful_paint"
    CUMULATIVE_LAYOUT_SHIFT = "cumulative_layout_shift"
    INTERACTION_TO_NEXT_PAINT = "interaction_to_next_paint"


@dataclass(frozen=True, slots=True)
class PageSpeedCoreWebVital:
    """One selected PageSpeed Core Web Vital field-data observation."""

    kind: PageSpeedCoreWebVitalKind
    metric_id: str
    percentile: int | None
    category: str | None
    distributions: tuple[PageSpeedMetricDistribution, ...]


@dataclass(frozen=True, slots=True)
class PageSpeedCoreWebVitalsReport:
    """Page and origin Chrome UX Core Web Vitals without causal claims."""

    analyzed_url: str
    analysis_utc_timestamp: str
    page_metrics: tuple[PageSpeedCoreWebVital, ...]
    origin_metrics: tuple[PageSpeedCoreWebVital, ...]


class PageSpeedService:
    """Application layer for read-only PageSpeed analyses."""

    def __init__(self, policy: BoundaryPolicy, client: PageSpeedClient) -> None:
        self._policy = policy
        self._client = client

    async def analyze(self, request: PageSpeedAnalysisRequest) -> PageSpeedAnalysisReport:
        """Analyze one configured child URL using the fixed PageSpeed origin."""

        return _pagespeed_analysis_report(await self._analyze_result(request))

    async def core_web_vitals(
        self,
        request: PageSpeedAnalysisRequest,
    ) -> PageSpeedCoreWebVitalsReport:
        """Return selected Chrome UX Core Web Vitals for one bounded PageSpeed read."""

        return _pagespeed_core_web_vitals_report(await self._analyze_result(request))

    async def _analyze_result(self, request: PageSpeedAnalysisRequest) -> PageSpeedAnalysisResult:
        self._policy.require_resource(
            request.account_id,
            self._client.provider,
            ResourceKind.PAGESPEED_SITE,
            request.site_url,
        )
        self._policy.require_pagespeed_url(
            request.account_id,
            request.site_url,
            request.page_url,
        )
        result = await self._client.analyze(
            ProviderReadRequest(AccountId(request.account_id), request.timeout_seconds),
            request.site_url,
            request.page_url,
            request.strategy.value,
            tuple(category.value for category in request.categories),
        )
        return result


def _pagespeed_analysis_report(result: PageSpeedAnalysisResult) -> PageSpeedAnalysisReport:
    return PageSpeedAnalysisReport(
        analyzed_url=result.analyzed_url,
        analysis_utc_timestamp=result.analysis_utc_timestamp.isoformat(),
        categories=tuple(
            PageSpeedCategoryScore(category=category.category, score=category.score)
            for category in result.categories
        ),
        loading_experience_category=result.loading_experience_category,
        origin_loading_experience_category=result.origin_loading_experience_category,
    )


def _pagespeed_core_web_vitals_report(
    result: PageSpeedAnalysisResult,
) -> PageSpeedCoreWebVitalsReport:
    return PageSpeedCoreWebVitalsReport(
        analyzed_url=result.analyzed_url,
        analysis_utc_timestamp=result.analysis_utc_timestamp.isoformat(),
        page_metrics=_pagespeed_core_web_vitals(result.loading_experience),
        origin_metrics=_pagespeed_core_web_vitals(result.origin_loading_experience),
    )


def _pagespeed_core_web_vitals(
    loading_experience: PageSpeedLoadingExperience | None,
) -> tuple[PageSpeedCoreWebVital, ...]:
    if loading_experience is None:
        return ()
    metrics = tuple(
        core_web_vital
        for metric in loading_experience.metrics
        if (core_web_vital := _pagespeed_core_web_vital(metric)) is not None
    )
    return tuple(sorted(metrics, key=lambda metric: metric.kind.value))


def _pagespeed_core_web_vital(
    metric: PageSpeedLoadingExperienceMetric,
) -> PageSpeedCoreWebVital | None:
    kind = _PAGESPEED_CORE_WEB_VITAL_KIND_BY_METRIC_ID.get(metric.metric_id)
    if kind is None:
        return None
    return PageSpeedCoreWebVital(
        kind=kind,
        metric_id=metric.metric_id,
        percentile=metric.percentile,
        category=metric.category,
        distributions=metric.distributions,
    )


_PAGESPEED_CORE_WEB_VITAL_KIND_BY_METRIC_ID = (
    {
        metric_id: PageSpeedCoreWebVitalKind.LARGEST_CONTENTFUL_PAINT
        for metric_id in PAGESPEED_LARGEST_CONTENTFUL_PAINT_METRIC_IDS
    }
    | {
        metric_id: PageSpeedCoreWebVitalKind.CUMULATIVE_LAYOUT_SHIFT
        for metric_id in PAGESPEED_CUMULATIVE_LAYOUT_SHIFT_METRIC_IDS
    }
    | {
        metric_id: PageSpeedCoreWebVitalKind.INTERACTION_TO_NEXT_PAINT
        for metric_id in PAGESPEED_INTERACTION_TO_NEXT_PAINT_METRIC_IDS
    }
)
