from __future__ import annotations

from datetime import date

import pytest

from rankrat.constants import MAX_BING_DERIVED_OPPORTUNITIES
from rankrat.errors import ApprovalDeniedError, BoundaryDeniedError, InputLimitError
from rankrat.models.boundaries import BoundaryDocument
from rankrat.policy.approvals import WriteApprovalStore
from rankrat.policy.boundaries import BoundaryPolicy
from rankrat.providers.base import ProviderFailureCode, ProviderOperationError
from rankrat.providers.bing import (
    BingCrawlIssueRow,
    BingCrawlStatsRow,
    BingFeedRow,
    BingKeywordStatsRow,
    BingLinkCountRow,
    BingLinkCounts,
    BingQueryStatsRow,
    BingRelatedKeywordRow,
    BingTrafficRow,
    BingUrlInformation,
    BingUrlSubmissionQuota,
    BingWebmasterClient,
)
from rankrat.services import bing as bing_service
from rankrat.services.bing import (
    BingBrandAnalysisRequest,
    BingCrawlIssuesRequest,
    BingCrawlStatsRequest,
    BingFeedsRequest,
    BingKeywordStatisticsRequest,
    BingLinkCountsRequest,
    BingOpportunityMatrixReport,
    BingPageQueryPerformanceRequest,
    BingPerformanceOpportunityKind,
    BingPerformanceRequest,
    BingPerformanceRow,
    BingQueryPagePerformanceRequest,
    BingRelatedKeywordsRequest,
    BingSiteApprovalRequest,
    BingSitemapApprovalRequest,
    BingSitemapOperation,
    BingSitemapSubmissionRequest,
    BingSiteOperation,
    BingSiteSubmissionRequest,
    BingTrafficComparisonRequest,
    BingTrafficMetrics,
    BingTrafficPeriodRequest,
    BingTrafficPoint,
    BingTrafficTrendReport,
    BingUrlInformationRequest,
    BingUrlSubmissionApprovalRequest,
    BingUrlSubmissionQuotaRequest,
    BingUrlSubmissionRequest,
    BingWebmasterService,
)


def _service(approvals: WriteApprovalStore | None = None) -> BingWebmasterService:
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
    return BingWebmasterService(policy, BingWebmasterClient(policy), approvals)


@pytest.mark.asyncio
async def test_service_maps_typed_keyword_inputs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service()
    captured: dict[str, tuple[object, ...]] = {}

    async def keyword_statistics_read(*args: object) -> tuple[BingKeywordStatsRow, ...]:
        captured["statistics"] = args
        return (
            BingKeywordStatsRow("rankrat", date(2026, 7, 2), 3, 4),
            BingKeywordStatsRow("rankrat", date(2026, 7, 1), 1, 2),
        )

    async def related_keywords_read(*args: object) -> tuple[BingRelatedKeywordRow, ...]:
        captured["related"] = args
        return (
            BingRelatedKeywordRow("second", 1, 2),
            BingRelatedKeywordRow("first", 2, 1),
        )

    monkeypatch.setattr(service._client, "read_keyword_stats", keyword_statistics_read)
    monkeypatch.setattr(service._client, "read_related_keywords", related_keywords_read)

    statistics = await service.keyword_statistics(
        BingKeywordStatisticsRequest(
            "bing-main",
            "rankrat",
            country="US",
            language="en",
        )
    )
    assert [point.day for point in statistics.points] == ["2026-07-01", "2026-07-02"]
    assert captured["statistics"][1:] == ("rankrat", "US", "en")

    related = await service.related_keywords(
        BingRelatedKeywordsRequest(
            "bing-main",
            "rankrat",
            date(2026, 7, 1),
            date(2026, 7, 2),
            country="US",
            language="en",
        )
    )
    assert [keyword.query for keyword in related.keywords] == ["first", "second"]
    assert captured["related"][1:] == (
        "rankrat",
        "US",
        "en",
        date(2026, 7, 1),
        date(2026, 7, 2),
    )


@pytest.mark.asyncio
async def test_bing_traffic_reports_are_fixed_bounded_and_typed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service()
    requests: list[tuple[object, ...]] = []

    async def traffic_read(*args: object) -> tuple[BingTrafficRow, ...]:
        requests.append(args)
        return (
            BingTrafficRow(date(2026, 6, 30), 8.0, 9.0),
            BingTrafficRow(date(2026, 7, 5), 100.0, 10.0),
            BingTrafficRow(date(2026, 7, 1), 0.0, 10.0),
            BingTrafficRow(date(2026, 7, 2), 0.0, 10.0),
            BingTrafficRow(date(2026, 7, 3), 0.0, 10.0),
            BingTrafficRow(date(2026, 7, 4), 0.0, 10.0),
        )

    monkeypatch.setattr(service._client, "read_rank_and_traffic_stats", traffic_read)
    request = BingTrafficPeriodRequest(
        "bing-main",
        "https://example.com/blog/",
        date(2026, 7, 1),
        date(2026, 7, 5),
    )
    trend = await service.traffic_trend(request)
    assert [point.day for point in trend.points] == [
        "2026-07-01",
        "2026-07-02",
        "2026-07-03",
        "2026-07-04",
        "2026-07-05",
    ]
    assert requests[0][1:] == ("https://example.com/blog/",)

    anomalies = await service.traffic_anomalies(request)
    assert len(anomalies.anomalies) == 1
    assert anomalies.anomalies[0].day == "2026-07-05"
    assert anomalies.anomalies[0].clicks_z_score == 2.0

    async def flat_traffic_read(*_: object) -> tuple[BingTrafficRow, ...]:
        return (
            BingTrafficRow(date(2026, 7, 1), 1.0, 1.0),
            BingTrafficRow(date(2026, 7, 2), 1.0, 1.0),
        )

    monkeypatch.setattr(service._client, "read_rank_and_traffic_stats", flat_traffic_read)
    assert (await service.traffic_anomalies(request)).anomalies == ()

    current = BingTrafficTrendReport(
        (BingTrafficPoint("2026-07-01", BingTrafficMetrics(3.0, 8.0)),)
    )
    previous = BingTrafficTrendReport(
        (BingTrafficPoint("2026-06-30", BingTrafficMetrics(1.0, 2.0)),)
    )
    trends = iter((current, previous))

    async def traffic_trend(_: BingTrafficPeriodRequest) -> BingTrafficTrendReport:
        return next(trends)

    monkeypatch.setattr(service, "traffic_trend", traffic_trend)
    comparison = await service.traffic_comparison(
        BingTrafficComparisonRequest(request, date(2026, 6, 30), date(2026, 6, 30))
    )
    assert comparison.clicks_delta == 2.0
    assert comparison.impressions_delta == 6.0


@pytest.mark.asyncio
async def test_bing_opportunity_matrix_preserves_query_and_page_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service()
    calls: list[str] = []

    async def query_read(*_: object) -> tuple[BingQueryStatsRow, ...]:
        calls.append("query")
        return (
            BingQueryStatsRow("quick-query", date(2026, 7, 1), 1.0, 20.0, 4.0, 4.0),
            BingQueryStatsRow("low-query", date(2026, 7, 1), 1.0, 25.0, 1.0, 1.0),
            BingQueryStatsRow("rank-query", date(2026, 7, 1), 10.0, 10.0, 5.0, 5.0),
            BingQueryStatsRow("high-query", date(2026, 7, 1), 8.0, 10.0, 1.0, 1.0),
        )

    async def page_read(*_: object) -> tuple[BingQueryStatsRow, ...]:
        calls.append("page")
        return (
            BingQueryStatsRow("quick-page", date(2026, 7, 1), 1.0, 20.0, 4.0, 4.0),
            BingQueryStatsRow("low-page", date(2026, 7, 1), 1.0, 25.0, 1.0, 1.0),
            BingQueryStatsRow("rank-page", date(2026, 7, 1), 10.0, 10.0, 5.0, 5.0),
            BingQueryStatsRow("high-page", date(2026, 7, 1), 8.0, 10.0, 1.0, 1.0),
        )

    monkeypatch.setattr(service._client, "read_query_stats", query_read)
    monkeypatch.setattr(service._client, "read_page_stats", page_read)
    report = await service.opportunity_matrix(
        BingPerformanceRequest("bing-main", "https://example.com/blog/")
    )

    assert isinstance(report, BingOpportunityMatrixReport)
    assert [item.row.label for item in report.query_opportunities.opportunities] == [
        "low-query",
        "quick-query",
        "rank-query",
    ]
    assert [item.row.label for item in report.page_opportunities.opportunities] == [
        "low-page",
        "quick-page",
        "rank-page",
    ]
    assert [item.row.label for item in report.query_quick_wins] == ["quick-query"]
    assert [item.row.label for item in report.page_quick_wins] == ["quick-page"]
    assert calls == ["query", "page"]


@pytest.mark.asyncio
async def test_bing_opportunity_matrix_denies_before_provider_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service()
    calls: list[str] = []

    async def query_read(*_: object) -> tuple[BingQueryStatsRow, ...]:
        calls.append("query")
        return ()

    async def page_read(*_: object) -> tuple[BingQueryStatsRow, ...]:
        calls.append("page")
        return ()

    monkeypatch.setattr(service._client, "read_query_stats", query_read)
    monkeypatch.setattr(service._client, "read_page_stats", page_read)

    with pytest.raises(BoundaryDeniedError):
        await service.opportunity_matrix(
            BingPerformanceRequest("bing-main", "https://outside.example/")
        )

    assert calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "rows",
    (
        (
            BingTrafficRow(date(2026, 7, 1), 1.0, 1.0),
            BingTrafficRow(date(2026, 7, 1), 2.0, 2.0),
        ),
    ),
)
async def test_bing_traffic_reports_reject_invalid_typed_provider_rows(
    monkeypatch: pytest.MonkeyPatch,
    rows: tuple[BingTrafficRow, ...],
) -> None:
    service = _service()

    async def traffic_read(*_: object) -> tuple[BingTrafficRow, ...]:
        return rows

    monkeypatch.setattr(service._client, "read_rank_and_traffic_stats", traffic_read)
    request = BingTrafficPeriodRequest(
        "bing-main",
        "https://example.com/blog/",
        date(2026, 7, 1),
        date(2026, 7, 3),
    )
    with pytest.raises(ProviderOperationError) as error:
        await service.traffic_trend(request)
    assert error.value.code is ProviderFailureCode.INVALID_RESPONSE


@pytest.mark.asyncio
async def test_bing_traffic_reports_reject_an_unconfigured_site_before_a_key_read() -> None:
    service = _service()
    request = BingTrafficPeriodRequest(
        "bing-main",
        "https://other.example/",
        date(2026, 7, 1),
        date(2026, 7, 3),
    )

    with pytest.raises(BoundaryDeniedError):
        await service.traffic_trend(request)


@pytest.mark.asyncio
async def test_bing_traffic_reports_return_an_empty_typed_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service()

    async def traffic_read(*_: object) -> tuple[BingTrafficRow, ...]:
        return ()

    monkeypatch.setattr(service._client, "read_rank_and_traffic_stats", traffic_read)
    request = BingTrafficPeriodRequest(
        "bing-main",
        "https://example.com/blog/",
        date(2026, 7, 1),
        date(2026, 7, 3),
    )

    assert (await service.traffic_trend(request)).points == ()


@pytest.mark.asyncio
async def test_bing_query_and_page_performance_are_typed_and_deterministic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service()
    requests: list[tuple[object, ...]] = []

    async def query_read(*args: object) -> tuple[BingQueryStatsRow, ...]:
        requests.append(args)
        return (
            BingQueryStatsRow("zebra", date(2026, 7, 2), 1.0, 9.0, 3.0, 5.0),
            BingQueryStatsRow("alpha", date(2026, 7, 1), 3.0, 8.0, 2.0, 4.0),
        )

    async def page_read(*args: object) -> tuple[BingQueryStatsRow, ...]:
        requests.append(args)
        return ()

    monkeypatch.setattr(service._client, "read_query_stats", query_read)
    monkeypatch.setattr(service._client, "read_page_stats", page_read)
    request = BingPerformanceRequest("bing-main", "https://example.com/blog/")

    query_report = await service.query_performance(request)
    page_report = await service.page_performance(request)

    assert [row.label for row in query_report.rows] == ["alpha", "zebra"]
    assert query_report.rows[0].day == "2026-07-01"
    assert page_report.rows == ()
    assert [call[1:] for call in requests] == [
        ("https://example.com/blog/",),
        ("https://example.com/blog/",),
    ]


@pytest.mark.asyncio
async def test_bing_opportunities_are_local_typed_bounded_and_deterministic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service()
    calls: list[tuple[object, ...]] = []

    async def query_read(*args: object) -> tuple[BingQueryStatsRow, ...]:
        calls.append(args)
        return (
            BingQueryStatsRow("not-a-candidate", date(2026, 7, 1), 9.0, 10.0, 2.0, 2.0),
            BingQueryStatsRow("low-ctr", date(2026, 7, 1), 1.0, 10.0, 2.0, 2.0),
            BingQueryStatsRow("striking", date(2026, 7, 1), 8.0, 10.0, 4.0, 4.0),
            BingQueryStatsRow("both", date(2026, 7, 1), 2.0, 10.0, 20.0, 20.0),
        )

    async def page_read(*args: object) -> tuple[BingQueryStatsRow, ...]:
        calls.append(args)
        return (BingQueryStatsRow("only", date(2026, 7, 1), 0.0, 10.0, 4.0, 4.0),)

    monkeypatch.setattr(service._client, "read_query_stats", query_read)
    monkeypatch.setattr(service._client, "read_page_stats", page_read)
    request = BingPerformanceRequest("bing-main", "https://example.com/blog/")

    query_report = await service.query_opportunities(request)
    page_report = await service.page_opportunities(request)

    assert [opportunity.row.label for opportunity in query_report.opportunities] == [
        "striking",
        "both",
        "low-ctr",
    ]
    assert query_report.opportunities[1].click_through_rate == 0.2
    assert query_report.opportunities[1].classifications == (
        BingPerformanceOpportunityKind.LOW_CTR,
        BingPerformanceOpportunityKind.STRIKING_DISTANCE,
    )
    assert query_report.opportunities[2].classifications == (
        BingPerformanceOpportunityKind.LOW_CTR,
    )
    assert query_report.opportunities[0].classifications == (
        BingPerformanceOpportunityKind.STRIKING_DISTANCE,
    )
    assert page_report.opportunities == ()
    assert [call[1:] for call in calls] == [
        ("https://example.com/blog/",),
        ("https://example.com/blog/",),
    ]

    async def empty_query_read(*_: object) -> tuple[BingQueryStatsRow, ...]:
        return ()

    monkeypatch.setattr(service._client, "read_query_stats", empty_query_read)
    assert (await service.query_opportunities(request)).opportunities == ()


@pytest.mark.asyncio
async def test_bing_rank_derivations_use_impression_position_when_click_position_is_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service()

    async def query_read(*_: object) -> tuple[BingQueryStatsRow, ...]:
        return (
            BingQueryStatsRow("low-ctr", date(2026, 7, 1), 0.0, 10.0, None, 4.0),
            BingQueryStatsRow("baseline", date(2026, 7, 1), 5.0, 10.0, 1.0, 1.0),
            BingQueryStatsRow("no-position", date(2026, 7, 1), 1.0, 10.0, None, None),
        )

    monkeypatch.setattr(service._client, "read_query_stats", query_read)
    request = BingPerformanceRequest("bing-main", "https://example.com/blog/")

    performance = await service.query_performance(request)
    preserved = next(row for row in performance.rows if row.label == "low-ctr")
    assert preserved.average_click_position is None
    assert preserved.average_impression_position == 4.0

    opportunities = await service.query_opportunities(request)
    low_ctr = next(
        opportunity
        for opportunity in opportunities.opportunities
        if opportunity.row.label == "low-ctr"
    )
    assert low_ctr.classifications == (
        BingPerformanceOpportunityKind.LOW_CTR,
        BingPerformanceOpportunityKind.STRIKING_DISTANCE,
    )

    buckets = await service.ranking_buckets(request)
    assert [row.label for row in buckets.buckets[1].rows] == ["low-ctr"]
    assert all(row.label != "no-position" for bucket in buckets.buckets for row in bucket.rows)


@pytest.mark.asyncio
async def test_bing_opportunities_reject_cross_site_before_a_key_read() -> None:
    service = _service()

    with pytest.raises(BoundaryDeniedError):
        await service.query_opportunities(
            BingPerformanceRequest("bing-main", "https://other.example/")
        )


@pytest.mark.asyncio
async def test_bing_opportunities_apply_the_fixed_output_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service()

    async def query_read(*_: object) -> tuple[BingQueryStatsRow, ...]:
        return tuple(
            BingQueryStatsRow(
                f"row-{index:03d}",
                date(2026, 7, 1),
                0.0,
                1.0,
                4.0,
                4.0,
            )
            for index in range(MAX_BING_DERIVED_OPPORTUNITIES + 1)
        )

    monkeypatch.setattr(service._client, "read_query_stats", query_read)
    report = await service.query_opportunities(
        BingPerformanceRequest("bing-main", "https://example.com/blog/")
    )

    assert len(report.opportunities) == MAX_BING_DERIVED_OPPORTUNITIES
    assert report.opportunities[0].row.label == "row-000"
    assert report.opportunities[-1].row.label == "row-499"


@pytest.mark.asyncio
async def test_bing_query_performance_rejects_cross_site_before_a_key_read() -> None:
    service = _service()

    with pytest.raises(BoundaryDeniedError):
        await service.query_performance(
            BingPerformanceRequest("bing-main", "https://other.example/")
        )


@pytest.mark.asyncio
async def test_bing_brand_analysis_uses_literal_casefolded_terms_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service()
    provider_calls: list[tuple[object, ...]] = []

    async def query_read(*args: object) -> tuple[BingQueryStatsRow, ...]:
        provider_calls.append(args)
        return (
            BingQueryStatsRow("Rankrat documentation", date(2026, 7, 1), 3.0, 8.0, 2.0, 4.0),
            BingQueryStatsRow("unrelated query", date(2026, 7, 1), 2.0, 4.0, 3.0, 5.0),
        )

    monkeypatch.setattr(service._client, "read_query_stats", query_read)
    report = await service.brand_analysis(
        BingBrandAnalysisRequest(
            "bing-main",
            "https://example.com/blog/",
            ("  RANKRAT ",),
        )
    )

    assert report.brand_terms == ("rankrat",)
    assert [row.label for row in report.brand_rows] == ["Rankrat documentation"]
    assert [row.label for row in report.non_brand_rows] == ["unrelated query"]
    assert len(provider_calls) == 1
    assert provider_calls[0][1:] == ("https://example.com/blog/",)
    with pytest.raises(InputLimitError):
        BingBrandAnalysisRequest("bing-main", "https://example.com/blog/", ())
    with pytest.raises(InputLimitError):
        BingBrandAnalysisRequest("bing-main", "https://example.com/blog/", (" ",))
    with pytest.raises(InputLimitError):
        BingBrandAnalysisRequest(
            "bing-main",
            "https://example.com/blog/",
            ("rankrat", "RANKRAT"),
        )


def test_bing_performance_opportunity_ignores_rows_without_impressions() -> None:
    row = BingPerformanceRow("empty", "2026-07-01", 0.0, 0.0, 1.0, 1.0)
    assert bing_service._bing_performance_opportunity(row, 0.1) is None


@pytest.mark.asyncio
async def test_bing_ranking_buckets_are_fixed_complete_and_use_one_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service()
    provider_calls: list[tuple[object, ...]] = []

    async def query_read(*args: object) -> tuple[BingQueryStatsRow, ...]:
        provider_calls.append(args)
        return (
            BingQueryStatsRow("top three", date(2026, 7, 1), 6.0, 6.0, 3.0, 3.0),
            BingQueryStatsRow("first page", date(2026, 7, 1), 5.0, 5.0, 3.1, 3.1),
            BingQueryStatsRow("first page end", date(2026, 7, 1), 4.0, 4.0, 10.0, 10.0),
            BingQueryStatsRow("second page", date(2026, 7, 1), 3.0, 3.0, 10.1, 10.1),
            BingQueryStatsRow("second page end", date(2026, 7, 1), 2.0, 2.0, 20.0, 20.0),
            BingQueryStatsRow("beyond", date(2026, 7, 1), 1.0, 1.0, 20.1, 20.1),
        )

    monkeypatch.setattr(service._client, "read_query_stats", query_read)
    report = await service.ranking_buckets(
        BingPerformanceRequest("bing-main", "https://example.com/blog/")
    )

    assert [
        (bucket.kind.value, [row.label for row in bucket.rows]) for bucket in report.buckets
    ] == [
        ("top_three", ["top three"]),
        ("first_page", ["first page", "first page end"]),
        ("second_page", ["second page", "second page end"]),
        ("beyond_second_page", ["beyond"]),
    ]
    assert len(provider_calls) == 1
    assert provider_calls[0][1:] == ("https://example.com/blog/",)

    async def empty_query_read(*_: object) -> tuple[BingQueryStatsRow, ...]:
        return ()

    monkeypatch.setattr(service._client, "read_query_stats", empty_query_read)
    empty_report = await service.ranking_buckets(
        BingPerformanceRequest("bing-main", "https://example.com/blog/")
    )
    assert [(bucket.kind.value, bucket.rows) for bucket in empty_report.buckets] == [
        ("top_three", ()),
        ("first_page", ()),
        ("second_page", ()),
        ("beyond_second_page", ()),
    ]


@pytest.mark.asyncio
async def test_bing_query_page_and_page_query_performance_are_typed_and_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service()
    calls: list[tuple[object, ...]] = []

    async def query_page_read(*args: object) -> tuple[BingQueryStatsRow, ...]:
        calls.append(args)
        return (
            BingQueryStatsRow("https://example.com/b", date(2026, 7, 1), 3.0, 2.0, 3.0, 4.0),
            BingQueryStatsRow("https://example.com/a", date(2026, 7, 1), 2.0, 2.0, 3.0, 4.0),
        )

    async def page_query_read(*args: object) -> tuple[BingQueryStatsRow, ...]:
        calls.append(args)
        return ()

    monkeypatch.setattr(service._client, "read_query_page_stats", query_page_read)
    monkeypatch.setattr(service._client, "read_page_query_stats", page_query_read)
    query_report = await service.query_page_performance(
        BingQueryPagePerformanceRequest("bing-main", "https://example.com/blog/", "rankrat")
    )
    provider_calls_before_cannibalization = len(calls)
    cannibalization = await service.query_cannibalization(
        BingQueryPagePerformanceRequest("bing-main", "https://example.com/blog/", "rankrat")
    )
    page_report = await service.page_query_performance(
        BingPageQueryPerformanceRequest(
            "bing-main",
            "https://example.com/blog/",
            "https://example.com/blog/page",
        )
    )
    assert query_report.rows[0].label == "https://example.com/b"
    assert cannibalization.query == "rankrat"
    assert [page.label for page in cannibalization.pages] == [
        "https://example.com/b",
        "https://example.com/a",
    ]
    assert page_report.rows == ()
    assert len(calls) == provider_calls_before_cannibalization + 2
    assert calls[0][1:] == ("https://example.com/blog/", "rankrat")
    assert calls[1][1:] == ("https://example.com/blog/", "rankrat")
    assert calls[2][1:] == ("https://example.com/blog/", "https://example.com/blog/page")
    with pytest.raises(InputLimitError):
        BingQueryPagePerformanceRequest("bing-main", "https://example.com/blog/", "x" * 257)
    with pytest.raises(BoundaryDeniedError):
        await service.page_query_performance(
            BingPageQueryPerformanceRequest(
                "bing-main",
                "https://example.com/blog/",
                "https://example.com/other",
            )
        )


@pytest.mark.asyncio
async def test_bing_query_cannibalization_requires_multiple_pages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service()

    async def query_page_read(*_: object) -> tuple[BingQueryStatsRow, ...]:
        return (BingQueryStatsRow("https://example.com/a", date(2026, 7, 1), 1.0, 2.0, 3.0, 4.0),)

    monkeypatch.setattr(service._client, "read_query_page_stats", query_page_read)

    report = await service.query_cannibalization(
        BingQueryPagePerformanceRequest("bing-main", "https://example.com/blog/", "rankrat")
    )

    assert report.query == "rankrat"
    assert report.pages == ()


@pytest.mark.asyncio
async def test_bing_url_submission_quota_is_typed_and_boundary_constrained(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service()
    captured: list[tuple[object, ...]] = []

    async def quota_read(*args: object) -> BingUrlSubmissionQuota:
        captured.append(args)
        return BingUrlSubmissionQuota(daily=5, monthly=24)

    monkeypatch.setattr(service._client, "read_url_submission_quota", quota_read)

    report = await service.url_submission_quota(
        BingUrlSubmissionQuotaRequest("bing-main", "https://example.com/blog/")
    )

    assert report.daily == 5
    assert report.monthly == 24
    assert captured[0][1:] == ("https://example.com/blog/",)

    with pytest.raises(BoundaryDeniedError):
        await service.url_submission_quota(
            BingUrlSubmissionQuotaRequest("bing-main", "https://other.example/")
        )


@pytest.mark.asyncio
async def test_bing_crawl_reports_are_typed_deterministic_and_boundary_constrained(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service()
    calls: list[tuple[object, ...]] = []

    async def crawl_issues(*args: object) -> tuple[BingCrawlIssueRow, ...]:
        calls.append(args)
        return (
            BingCrawlIssueRow("https://example.com/blog/z", 404, 1, 2),
            BingCrawlIssueRow("https://example.com/blog/a", 500, 3, 4),
        )

    async def crawl_stats(*args: object) -> tuple[BingCrawlStatsRow, ...]:
        calls.append(args)
        return (
            BingCrawlStatsRow(date(2026, 7, 2), 0, 0, 1, 0, 0, 0, 0, 0, None, 0, 1, None, 1, 1),
            BingCrawlStatsRow(date(2026, 7, 1), 0, 0, 1, 0, 0, 0, 0, 0, 2, 0, 1, 3, 1, 1),
        )

    monkeypatch.setattr(service._client, "read_crawl_issues", crawl_issues)
    monkeypatch.setattr(service._client, "read_crawl_stats", crawl_stats)
    request = BingCrawlIssuesRequest("bing-main", "https://example.com/blog/")
    issues = await service.crawl_issues(request)
    stats = await service.crawl_stats(
        BingCrawlStatsRequest("bing-main", "https://example.com/blog/")
    )

    assert [issue.url for issue in issues.issues] == [
        "https://example.com/blog/a",
        "https://example.com/blog/z",
    ]
    assert [point.day for point in stats.points] == ["2026-07-01", "2026-07-02"]
    assert stats.points[0].connection_timeout == 2
    assert stats.points[0].dns_failures == 3
    assert [call[1:] for call in calls] == [
        ("https://example.com/blog/",),
        ("https://example.com/blog/",),
    ]
    with pytest.raises(BoundaryDeniedError):
        await service.crawl_issues(BingCrawlIssuesRequest("bing-main", "https://other.example/"))
    with pytest.raises(BoundaryDeniedError):
        await service.crawl_stats(BingCrawlStatsRequest("bing-main", "https://other.example/"))


@pytest.mark.asyncio
async def test_bing_feeds_are_typed_deterministic_and_boundary_constrained(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service()
    calls: list[tuple[object, ...]] = []

    async def feeds(*args: object) -> tuple[BingFeedRow, ...]:
        calls.append(args)
        return (
            BingFeedRow(
                "https://example.com/blog/z.xml",
                "Sitemap",
                "Success",
                False,
                10,
                2,
                date(2026, 7, 2),
                date(2026, 7, 1),
            ),
            BingFeedRow(
                "https://example.com/blog/a.xml",
                "Sitemap",
                "Success",
                True,
                20,
                3,
                date(2026, 7, 3),
                date(2026, 7, 2),
            ),
        )

    monkeypatch.setattr(service._client, "read_feeds", feeds)
    report = await service.feeds(BingFeedsRequest("bing-main", "https://example.com/blog/"))

    assert [feed.url for feed in report.feeds] == [
        "https://example.com/blog/a.xml",
        "https://example.com/blog/z.xml",
    ]
    assert report.feeds[0].compressed is True
    assert report.feeds[0].last_crawled == "2026-07-03"
    assert calls[0][1:] == ("https://example.com/blog/",)
    with pytest.raises(BoundaryDeniedError):
        await service.feeds(BingFeedsRequest("bing-main", "https://other.example/"))


@pytest.mark.asyncio
async def test_bing_link_counts_are_typed_deterministic_and_boundary_constrained(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service()
    calls: list[tuple[object, ...]] = []

    async def link_counts(*args: object) -> BingLinkCounts:
        calls.append(args)
        return BingLinkCounts(
            links=(
                BingLinkCountRow("https://source.example/z", 1),
                BingLinkCountRow("https://source.example/a", 3),
            ),
            total_pages=2,
        )

    monkeypatch.setattr(service._client, "read_link_counts", link_counts)
    report = await service.link_counts(
        BingLinkCountsRequest("bing-main", "https://example.com/blog/", page=1)
    )

    assert [(link.url, link.count) for link in report.links] == [
        ("https://source.example/a", 3),
        ("https://source.example/z", 1),
    ]
    assert report.total_pages == 2
    assert calls[0][1:] == ("https://example.com/blog/", 1)
    with pytest.raises(BoundaryDeniedError):
        await service.link_counts(BingLinkCountsRequest("bing-main", "https://other.example/"))
    with pytest.raises(InputLimitError):
        BingLinkCountsRequest("bing-main", "https://example.com/blog/", page=-1)
    with pytest.raises(InputLimitError):
        BingLinkCountsRequest("bing-main", "https://example.com/blog/", page=1_001)


@pytest.mark.asyncio
async def test_bing_traffic_anomalies_rejects_an_overflowing_baseline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service()

    async def traffic_read(*_: object) -> tuple[BingTrafficRow, ...]:
        return (
            BingTrafficRow(date(2026, 7, 1), 1e308, 1.0),
            BingTrafficRow(date(2026, 7, 2), 1e308, 1.0),
            BingTrafficRow(date(2026, 7, 3), 1e308, 1.0),
        )

    monkeypatch.setattr(service._client, "read_rank_and_traffic_stats", traffic_read)
    request = BingTrafficPeriodRequest(
        "bing-main",
        "https://example.com/blog/",
        date(2026, 7, 1),
        date(2026, 7, 3),
    )
    with pytest.raises(ProviderOperationError) as error:
        await service.traffic_anomalies(request)
    assert error.value.code is ProviderFailureCode.INVALID_RESPONSE


def test_bing_traffic_requests_reject_invalid_windows() -> None:
    with pytest.raises(InputLimitError):
        BingTrafficPeriodRequest(
            "bing-main",
            "https://example.com/blog/",
            date(2026, 7, 2),
            date(2026, 7, 1),
        )
    with pytest.raises(InputLimitError):
        BingTrafficPeriodRequest(
            "bing-main",
            "https://example.com/blog/",
            date(2025, 1, 1),
            date(2026, 1, 2),
        )


def test_service_rejects_invalid_keyword_inputs_and_windows() -> None:
    with pytest.raises(InputLimitError):
        BingKeywordStatisticsRequest("bing-main", "x" * 257)
    with pytest.raises(InputLimitError):
        BingKeywordStatisticsRequest(
            "bing-main",
            "rankrat",
            country="x" * 17,
        )
    with pytest.raises(InputLimitError):
        BingKeywordStatisticsRequest(
            "bing-main",
            "rankrat",
            language="x" * 33,
        )
    with pytest.raises(InputLimitError):
        BingRelatedKeywordsRequest(
            "bing-main",
            "rankrat",
            date(2026, 7, 2),
            date(2026, 7, 1),
        )
    with pytest.raises(InputLimitError):
        BingRelatedKeywordsRequest(
            "bing-main",
            "rankrat",
            date(2025, 1, 1),
            date(2026, 1, 2),
        )


@pytest.mark.asyncio
async def test_bing_url_information_is_typed_and_boundary_constrained(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service()
    calls: list[tuple[object, ...]] = []

    async def url_information(*args: object) -> BingUrlInformation:
        calls.append(args)
        return BingUrlInformation(
            url="https://example.com/blog/article",
            anchor_count=3,
            discovery_date=date(2026, 7, 1),
            document_size=100,
            http_status=None,
            is_page=True,
            last_crawled_date=date(2026, 7, 2),
            total_child_url_count=2,
        )

    monkeypatch.setattr(service._client, "read_url_information", url_information)
    report = await service.url_information(
        BingUrlInformationRequest(
            "bing-main",
            "https://example.com/blog/",
            "https://example.com/blog/article",
        )
    )

    assert report.url == "https://example.com/blog/article"
    assert report.http_status is None
    assert report.last_crawled_date == "2026-07-02"
    assert calls[0][1:] == ("https://example.com/blog/", "https://example.com/blog/article")
    with pytest.raises(BoundaryDeniedError):
        await service.url_information(
            BingUrlInformationRequest(
                "bing-main",
                "https://example.com/blog/",
                "https://example.com/other",
            )
        )


@pytest.mark.asyncio
async def test_service_requires_exact_single_use_approval_for_bing_submission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service(WriteApprovalStore())
    submitted: list[tuple[object, ...]] = []

    async def submit_url_batch(*args: object) -> None:
        submitted.append(args)

    monkeypatch.setattr(service._client, "submit_url_batch", submit_url_batch)
    approval_request = BingUrlSubmissionApprovalRequest(
        "bing-main",
        "https://example.com/blog/",
        ("https://example.com/blog/post",),
    )
    approval = await service.approve_url_submission(approval_request)
    request = BingUrlSubmissionRequest(
        "bing-main",
        "https://example.com/blog/",
        ("https://example.com/blog/post",),
        approval.approval_id,
    )

    response = await service.submit_url_batch(request)
    assert response.submitted_count == 1
    assert submitted[0][1:] == (
        "https://example.com/blog/",
        ("https://example.com/blog/post",),
    )
    with pytest.raises(ApprovalDeniedError):
        await service.submit_url_batch(request)
    assert len(submitted) == 1


@pytest.mark.asyncio
async def test_service_rejects_disabled_duplicate_or_out_of_scope_bing_submissions() -> None:
    request = BingUrlSubmissionApprovalRequest(
        "bing-main",
        "https://example.com/blog/",
        ("https://example.com/blog/post",),
    )
    with pytest.raises(ApprovalDeniedError):
        await _service().approve_url_submission(request)
    with pytest.raises(ApprovalDeniedError):
        await _service().submit_url_batch(
            BingUrlSubmissionRequest(
                "bing-main",
                "https://example.com/blog/",
                ("https://example.com/blog/post",),
                "unused",
            )
        )

    service = _service(WriteApprovalStore())
    with pytest.raises(InputLimitError):
        await service.approve_url_submission(
            BingUrlSubmissionApprovalRequest(
                "bing-main",
                "https://example.com/blog/",
                ("https://example.com/blog/post", "https://example.com/blog/post"),
            )
        )
    with pytest.raises(BoundaryDeniedError):
        await service.approve_url_submission(
            BingUrlSubmissionApprovalRequest(
                "bing-main",
                "https://example.com/blog/",
                ("https://example.com/elsewhere",),
            )
        )
    with pytest.raises(InputLimitError):
        await service.approve_url_submission(
            BingUrlSubmissionApprovalRequest(
                "bing-main",
                "https://example.com/blog/",
                (),
            )
        )


@pytest.mark.asyncio
async def test_service_requires_exact_one_use_approval_for_bing_sitemap_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service(WriteApprovalStore())
    submitted: list[tuple[object, ...]] = []

    async def submit_feed(*args: object) -> None:
        submitted.append(args)

    monkeypatch.setattr(service._client, "submit_feed", submit_feed)
    approval_request = BingSitemapApprovalRequest(
        "bing-main",
        "https://example.com/blog/",
        "https://example.com/blog/sitemap.xml",
        BingSitemapOperation.SUBMIT,
    )
    approval = await service.approve_sitemap_submission(approval_request)
    request = BingSitemapSubmissionRequest(
        "bing-main",
        "https://example.com/blog/",
        "https://example.com/blog/sitemap.xml",
        BingSitemapOperation.SUBMIT,
        approval.approval_id,
    )

    response = await service.submit_sitemap(request)
    assert response.operation is BingSitemapOperation.SUBMIT
    assert submitted[0][1:] == (
        "https://example.com/blog/",
        "https://example.com/blog/sitemap.xml",
    )
    with pytest.raises(ApprovalDeniedError):
        await service.submit_sitemap(request)
    assert len(submitted) == 1


@pytest.mark.asyncio
async def test_service_rejects_changed_or_out_of_scope_bing_sitemap_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service(WriteApprovalStore())
    deleted = False

    async def remove_feed(*_: object) -> None:
        nonlocal deleted
        deleted = True

    monkeypatch.setattr(service._client, "remove_feed", remove_feed)
    approval = await service.approve_sitemap_submission(
        BingSitemapApprovalRequest(
            "bing-main",
            "https://example.com/blog/",
            "https://example.com/blog/sitemap.xml",
            BingSitemapOperation.DELETE,
        )
    )
    with pytest.raises(ApprovalDeniedError):
        await service.submit_sitemap(
            BingSitemapSubmissionRequest(
                "bing-main",
                "https://example.com/blog/",
                "https://example.com/blog/changed.xml",
                BingSitemapOperation.DELETE,
                approval.approval_id,
            )
        )
    with pytest.raises(BoundaryDeniedError):
        await service.approve_sitemap_submission(
            BingSitemapApprovalRequest(
                "bing-main",
                "https://example.com/blog/",
                "https://example.com/elsewhere.xml",
                BingSitemapOperation.DELETE,
            )
        )
    assert deleted is False

    delete_approval = await service.approve_sitemap_submission(
        BingSitemapApprovalRequest(
            "bing-main",
            "https://example.com/blog/",
            "https://example.com/blog/sitemap.xml",
            BingSitemapOperation.DELETE,
        )
    )
    await service.submit_sitemap(
        BingSitemapSubmissionRequest(
            "bing-main",
            "https://example.com/blog/",
            "https://example.com/blog/sitemap.xml",
            BingSitemapOperation.DELETE,
            delete_approval.approval_id,
        )
    )
    assert deleted is True


@pytest.mark.asyncio
async def test_bing_sitemap_mutation_requires_enablement_and_logs_provider_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    disabled = _service()
    request = BingSitemapApprovalRequest(
        "bing-main",
        "https://example.com/blog/",
        "https://example.com/blog/sitemap.xml",
        BingSitemapOperation.SUBMIT,
    )
    with pytest.raises(ApprovalDeniedError):
        await disabled.approve_sitemap_submission(request)
    with pytest.raises(ApprovalDeniedError):
        await disabled.submit_sitemap(
            BingSitemapSubmissionRequest(
                "bing-main",
                "https://example.com/blog/",
                "https://example.com/blog/sitemap.xml",
                BingSitemapOperation.SUBMIT,
                "unused",
            )
        )

    service = _service(WriteApprovalStore())

    async def submit_feed(*_: object) -> None:
        raise RuntimeError("upstream failure")

    monkeypatch.setattr(service._client, "submit_feed", submit_feed)
    approval = await service.approve_sitemap_submission(request)
    with pytest.raises(RuntimeError, match="upstream failure"):
        await service.submit_sitemap(
            BingSitemapSubmissionRequest(
                "bing-main",
                "https://example.com/blog/",
                "https://example.com/blog/sitemap.xml",
                BingSitemapOperation.SUBMIT,
                approval.approval_id,
            )
        )


@pytest.mark.asyncio
async def test_service_requires_exact_one_use_approval_for_bing_site_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service(WriteApprovalStore())
    added: list[str] = []

    async def add_site(_: object, site_url: str) -> None:
        added.append(site_url)

    monkeypatch.setattr(service._client, "add_site", add_site)
    approval_request = BingSiteApprovalRequest(
        "bing-main",
        "https://example.com/blog/",
        BingSiteOperation.ADD,
    )
    approval = await service.approve_site_submission(approval_request)
    request = BingSiteSubmissionRequest(
        "bing-main",
        "https://example.com/blog/",
        BingSiteOperation.ADD,
        approval.approval_id,
    )

    response = await service.submit_site(request)
    assert response.operation is BingSiteOperation.ADD
    assert added == ["https://example.com/blog/"]
    with pytest.raises(ApprovalDeniedError):
        await service.submit_site(request)
    assert added == ["https://example.com/blog/"]


@pytest.mark.asyncio
async def test_service_rejects_disabled_changed_and_out_of_scope_bing_site_mutations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    disabled_request = BingSiteApprovalRequest(
        "bing-main",
        "https://example.com/blog/",
        BingSiteOperation.ADD,
    )
    with pytest.raises(ApprovalDeniedError):
        await _service().approve_site_submission(disabled_request)
    with pytest.raises(ApprovalDeniedError):
        await _service().submit_site(
            BingSiteSubmissionRequest(
                "bing-main",
                "https://example.com/blog/",
                BingSiteOperation.ADD,
                "unused",
            )
        )

    service = _service(WriteApprovalStore())
    removed = False

    async def remove_site(*_: object) -> None:
        nonlocal removed
        removed = True

    monkeypatch.setattr(service._client, "remove_site", remove_site)
    approval = await service.approve_site_submission(disabled_request)
    with pytest.raises(ApprovalDeniedError):
        await service.submit_site(
            BingSiteSubmissionRequest(
                "bing-main",
                "https://example.com/blog/",
                BingSiteOperation.DELETE,
                approval.approval_id,
            )
        )
    with pytest.raises(BoundaryDeniedError):
        await service.approve_site_submission(
            BingSiteApprovalRequest(
                "bing-main",
                "https://other.example/",
                BingSiteOperation.DELETE,
            )
        )
    assert removed is False


@pytest.mark.asyncio
async def test_bing_site_mutation_logs_provider_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service(WriteApprovalStore())

    async def add_site(*_: object) -> None:
        raise RuntimeError("upstream failure")

    monkeypatch.setattr(service._client, "add_site", add_site)
    request = BingSiteApprovalRequest(
        "bing-main",
        "https://example.com/blog/",
        BingSiteOperation.ADD,
    )
    approval = await service.approve_site_submission(request)
    with pytest.raises(RuntimeError, match="upstream failure"):
        await service.submit_site(
            BingSiteSubmissionRequest(
                "bing-main",
                "https://example.com/blog/",
                BingSiteOperation.ADD,
                approval.approval_id,
            )
        )
