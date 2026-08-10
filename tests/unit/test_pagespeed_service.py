from __future__ import annotations

from datetime import UTC, datetime

import pytest

from rankrat.constants import DEFAULT_PAGESPEED_TIMEOUT_SECONDS
from rankrat.errors import InputLimitError
from rankrat.models.boundaries import BoundaryDocument
from rankrat.policy.boundaries import BoundaryPolicy
from rankrat.providers.pagespeed import (
    PageSpeedAnalysisResult,
    PageSpeedClient,
    PageSpeedLighthouseCategory,
    PageSpeedLoadingExperience,
    PageSpeedLoadingExperienceMetric,
    PageSpeedMetricDistribution,
)
from rankrat.services.pagespeed import (
    PageSpeedAnalysisReport,
    PageSpeedAnalysisRequest,
    PageSpeedCategory,
    PageSpeedCategoryScore,
    PageSpeedCoreWebVital,
    PageSpeedCoreWebVitalKind,
    PageSpeedCoreWebVitalsReport,
    PageSpeedService,
    PageSpeedStrategy,
)


def _service() -> PageSpeedService:
    policy = BoundaryPolicy(
        BoundaryDocument.model_validate(
            {
                "accounts": [
                    {
                        "id": "pagespeed-main",
                        "provider": "google",
                        "credential": "/run/secrets/google/oauth-client.json",
                        "pagespeed_api_key_file": "/run/secrets/google/pagespeed-api-key",
                        "pagespeed_sites": ["https://example.com/blog/"],
                    }
                ]
            }
        )
    )

    return PageSpeedService(policy, PageSpeedClient(policy))


def test_service_uses_pagespeed_specific_timeout_default() -> None:
    request = PageSpeedAnalysisRequest(
        "pagespeed-main",
        "https://example.com/blog/",
        "https://example.com/blog/post",
    )

    assert request.timeout_seconds == DEFAULT_PAGESPEED_TIMEOUT_SECONDS


@pytest.mark.asyncio
async def test_service_authorizes_and_converts_pagespeed_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service()
    calls: list[object] = []

    async def analyze(*arguments: object) -> PageSpeedAnalysisResult:
        calls.extend(arguments)
        return PageSpeedAnalysisResult(
            analyzed_url="https://example.com/blog/post",
            analysis_utc_timestamp=datetime(2026, 7, 30, 17, tzinfo=UTC),
            categories=(PageSpeedLighthouseCategory("performance", 0.95),),
            loading_experience_category="FAST",
            origin_loading_experience_category=None,
        )

    monkeypatch.setattr(service._client, "analyze", analyze)
    assert await service.analyze(
        PageSpeedAnalysisRequest(
            "pagespeed-main",
            "https://example.com/blog/",
            "https://example.com/blog/post",
            PageSpeedStrategy.MOBILE,
            (PageSpeedCategory.PERFORMANCE, PageSpeedCategory.SEO),
        )
    ) == PageSpeedAnalysisReport(
        analyzed_url="https://example.com/blog/post",
        analysis_utc_timestamp="2026-07-30T17:00:00+00:00",
        categories=(PageSpeedCategoryScore("performance", 0.95),),
        loading_experience_category="FAST",
        origin_loading_experience_category=None,
    )
    assert calls[1:] == [
        "https://example.com/blog/",
        "https://example.com/blog/post",
        "MOBILE",
        ("PERFORMANCE", "SEO"),
    ]


@pytest.mark.asyncio
async def test_service_extracts_only_selected_page_and_origin_core_web_vitals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service()

    async def analyze(*_: object) -> PageSpeedAnalysisResult:
        return PageSpeedAnalysisResult(
            analyzed_url="https://example.com/blog/post",
            analysis_utc_timestamp=datetime(2026, 7, 30, 17, tzinfo=UTC),
            categories=(PageSpeedLighthouseCategory("performance", 0.95),),
            loading_experience_category="FAST",
            origin_loading_experience_category="AVERAGE",
            loading_experience=PageSpeedLoadingExperience(
                "FAST",
                (
                    PageSpeedLoadingExperienceMetric(
                        "CUMULATIVE_LAYOUT_SHIFT_SCORE",
                        12,
                        "FAST",
                        (PageSpeedMetricDistribution(0, 10, 1.0),),
                    ),
                    PageSpeedLoadingExperienceMetric(
                        "FIRST_CONTENTFUL_PAINT_MS",
                        1_000,
                        "FAST",
                        (),
                    ),
                    PageSpeedLoadingExperienceMetric(
                        "LARGEST_CONTENTFUL_PAINT_MS",
                        2_500,
                        "AVERAGE",
                        (PageSpeedMetricDistribution(0, None, 1.0),),
                    ),
                ),
            ),
            origin_loading_experience=PageSpeedLoadingExperience(
                "AVERAGE",
                (
                    PageSpeedLoadingExperienceMetric(
                        "INTERACTION_TO_NEXT_PAINT",
                        200,
                        "FAST",
                        (PageSpeedMetricDistribution(0, 200, 1.0),),
                    ),
                ),
            ),
        )

    monkeypatch.setattr(service._client, "analyze", analyze)

    assert await service.core_web_vitals(
        PageSpeedAnalysisRequest(
            "pagespeed-main",
            "https://example.com/blog/",
            "https://example.com/blog/post",
        )
    ) == PageSpeedCoreWebVitalsReport(
        analyzed_url="https://example.com/blog/post",
        analysis_utc_timestamp="2026-07-30T17:00:00+00:00",
        page_metrics=(
            PageSpeedCoreWebVital(
                PageSpeedCoreWebVitalKind.CUMULATIVE_LAYOUT_SHIFT,
                "CUMULATIVE_LAYOUT_SHIFT_SCORE",
                12,
                "FAST",
                (PageSpeedMetricDistribution(0, 10, 1.0),),
            ),
            PageSpeedCoreWebVital(
                PageSpeedCoreWebVitalKind.LARGEST_CONTENTFUL_PAINT,
                "LARGEST_CONTENTFUL_PAINT_MS",
                2_500,
                "AVERAGE",
                (PageSpeedMetricDistribution(0, None, 1.0),),
            ),
        ),
        origin_metrics=(
            PageSpeedCoreWebVital(
                PageSpeedCoreWebVitalKind.INTERACTION_TO_NEXT_PAINT,
                "INTERACTION_TO_NEXT_PAINT",
                200,
                "FAST",
                (PageSpeedMetricDistribution(0, 200, 1.0),),
            ),
        ),
    )


def test_service_rejects_duplicate_or_excessive_categories() -> None:
    with pytest.raises(InputLimitError):
        PageSpeedAnalysisRequest(
            "pagespeed-main",
            "https://example.com/blog/",
            "https://example.com/blog/post",
            categories=(PageSpeedCategory.SEO, PageSpeedCategory.SEO),
        )
    with pytest.raises(InputLimitError):
        PageSpeedAnalysisRequest(
            "pagespeed-main",
            "https://example.com/blog/",
            "https://example.com/blog/post",
            categories=(
                PageSpeedCategory.ACCESSIBILITY,
                PageSpeedCategory.AGENTIC_BROWSING,
                PageSpeedCategory.BEST_PRACTICES,
                PageSpeedCategory.PERFORMANCE,
                PageSpeedCategory.SEO,
                PageSpeedCategory.SEO,
            ),
        )


@pytest.mark.asyncio
async def test_service_accepts_any_site_reachable_by_the_configured_account(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service()

    async def analyze(*_: object) -> PageSpeedAnalysisResult:
        return PageSpeedAnalysisResult(
            analyzed_url="https://example.com/blog/post",
            analysis_utc_timestamp=datetime(2026, 7, 30, 17, tzinfo=UTC),
            categories=(),
            loading_experience_category=None,
            origin_loading_experience_category=None,
        )

    monkeypatch.setattr(service._client, "analyze", analyze)
    report = await service.analyze(
        PageSpeedAnalysisRequest(
            "pagespeed-main",
            "https://example.com/",
            "https://example.com/blog/post",
        )
    )
    assert report.analyzed_url == "https://example.com/blog/post"


@pytest.mark.asyncio
async def test_core_web_vitals_accepts_any_site_reachable_by_the_configured_account(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service()

    async def analyze(*_: object) -> PageSpeedAnalysisResult:
        return PageSpeedAnalysisResult(
            analyzed_url="https://example.com/blog/post",
            analysis_utc_timestamp=datetime(2026, 7, 30, 17, tzinfo=UTC),
            categories=(),
            loading_experience_category=None,
            origin_loading_experience_category=None,
        )

    monkeypatch.setattr(service._client, "analyze", analyze)
    report = await service.core_web_vitals(
        PageSpeedAnalysisRequest(
            "pagespeed-main",
            "https://example.com/",
            "https://example.com/blog/post",
        )
    )
    assert report.analyzed_url == "https://example.com/blog/post"
