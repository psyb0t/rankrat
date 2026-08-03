from __future__ import annotations

from datetime import date

import pytest

from rankrat.errors import BoundaryDeniedError, InputLimitError
from rankrat.models.boundaries import BoundaryDocument
from rankrat.policy.boundaries import BoundaryPolicy
from rankrat.providers.bing import (
    BingQueryStatsRow,
    BingWebmasterClient,
)
from rankrat.services.bing import (
    BingPerformanceRequest,
    BingSitemapOperation,
    BingSitemapSubmissionRequest,
    BingSiteOperation,
    BingSiteSubmissionRequest,
    BingUrlSubmissionRequest,
    BingWebmasterService,
)


def _service() -> BingWebmasterService:
    policy = BoundaryPolicy(
        BoundaryDocument.model_validate(
            {
                "accounts": [
                    {
                        "id": "bing-main",
                        "provider": "bing",
                        "credential": "/run/secrets/bing-key",
                        "sites": ["https://example.com/blog/"],
                    }
                ]
            }
        )
    )
    return BingWebmasterService(policy, BingWebmasterClient(policy))


@pytest.mark.asyncio
async def test_bing_query_report_is_typed_and_sorted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service()

    async def read_query_stats(*_: object) -> tuple[BingQueryStatsRow, ...]:
        return (
            BingQueryStatsRow("second", date(2026, 8, 1), 2, 20, 3.0, 4.0),
            BingQueryStatsRow("first", date(2026, 8, 1), 3, 30, 2.0, 3.0),
        )

    monkeypatch.setattr(service._client, "read_query_stats", read_query_stats)
    report = await service.query_performance(
        BingPerformanceRequest("bing-main", "https://example.com/blog/")
    )

    assert [row.label for row in report.rows] == ["first", "second"]
    assert report.rows[0].clicks == 3


@pytest.mark.asyncio
async def test_bing_url_write_calls_provider_only_for_configured_distinct_urls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service()
    submitted: list[tuple[object, ...]] = []

    async def submit_url_batch(*args: object) -> None:
        submitted.append(args)

    monkeypatch.setattr(service._client, "submit_url_batch", submit_url_batch)
    receipt = await service.submit_url_batch(
        BingUrlSubmissionRequest(
            "bing-main",
            "https://example.com/blog/",
            ("https://example.com/blog/post",),
        )
    )

    assert receipt.submitted_count == 1
    assert submitted[0][1:] == (
        "https://example.com/blog/",
        ("https://example.com/blog/post",),
    )
    with pytest.raises(InputLimitError, match="duplicate"):
        await service.submit_url_batch(
            BingUrlSubmissionRequest(
                "bing-main",
                "https://example.com/blog/",
                ("https://example.com/blog/post", "https://example.com/blog/post"),
            )
        )
    with pytest.raises(BoundaryDeniedError):
        await service.submit_url_batch(
            BingUrlSubmissionRequest(
                "bing-main",
                "https://example.com/blog/",
                ("https://example.com/elsewhere",),
            )
        )
    assert len(submitted) == 1


@pytest.mark.asyncio
async def test_bing_sitemap_write_is_direct_and_stays_within_configured_site(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service()
    submitted: list[tuple[object, ...]] = []

    async def submit_feed(*args: object) -> None:
        submitted.append(args)

    monkeypatch.setattr(service._client, "submit_feed", submit_feed)
    receipt = await service.submit_sitemap(
        BingSitemapSubmissionRequest(
            "bing-main",
            "https://example.com/blog/",
            "https://example.com/blog/sitemap.xml",
            BingSitemapOperation.SUBMIT,
        )
    )

    assert receipt.operation is BingSitemapOperation.SUBMIT
    assert submitted[0][1:] == (
        "https://example.com/blog/",
        "https://example.com/blog/sitemap.xml",
    )
    with pytest.raises(BoundaryDeniedError):
        await service.submit_sitemap(
            BingSitemapSubmissionRequest(
                "bing-main",
                "https://example.com/blog/",
                "https://example.com/elsewhere.xml",
                BingSitemapOperation.SUBMIT,
            )
        )


@pytest.mark.asyncio
async def test_bing_site_write_propagates_provider_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service()

    async def add_site(*_: object) -> None:
        raise RuntimeError("upstream failure")

    monkeypatch.setattr(service._client, "add_site", add_site)
    with pytest.raises(RuntimeError, match="upstream failure"):
        await service.submit_site(
            BingSiteSubmissionRequest(
                "bing-main",
                "https://example.com/blog/",
                BingSiteOperation.ADD,
            )
        )
    with pytest.raises(BoundaryDeniedError):
        await service.submit_site(
            BingSiteSubmissionRequest(
                "bing-main",
                "https://outside.example.net/",
                BingSiteOperation.ADD,
            )
        )
