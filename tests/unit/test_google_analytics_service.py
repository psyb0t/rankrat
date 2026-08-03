from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import cast

import pytest

from rankrat.errors import BoundaryDeniedError, InputLimitError
from rankrat.models.boundaries import BoundaryDocument
from rankrat.policy.boundaries import BoundaryPolicy
from rankrat.providers.google_analytics import (
    Ga4AccountSummary,
    Ga4DateRangeInput,
    Ga4FunnelQuery,
    Ga4FunnelReport,
    Ga4ReportQuery,
    Ga4ReportResult,
    GoogleAnalyticsDataClient,
)
from rankrat.services.google_analytics import (
    Ga4AccountDiscoveryRequest,
    Ga4ConversionFunnelRequest,
    Ga4DateRange,
    Ga4FixedReportKind,
    Ga4FixedReportRequest,
    Ga4RealtimeReportRequest,
    Ga4ReportRequest,
    GoogleAnalyticsDataService,
)


def _service() -> GoogleAnalyticsDataService:
    policy = BoundaryPolicy(
        BoundaryDocument.model_validate(
            {
                "accounts": [
                    {
                        "id": "google-main",
                        "provider": "google",
                        "credential": "/run/secrets/google.json",
                        "ga4_properties": ["123456789"],
                    }
                ]
            }
        )
    )

    async def token(credential_path: Path) -> str:
        del credential_path
        return "test-token"

    return GoogleAnalyticsDataService(policy, GoogleAnalyticsDataClient(policy, token))


@pytest.mark.asyncio
async def test_service_builds_bounded_ga4_historical_and_realtime_payloads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service()
    historical: list[object] = []
    realtime: list[object] = []

    async def run_report(*args: object) -> Ga4ReportResult:
        historical.extend(args)
        return Ga4ReportResult((), (), (), 0)

    async def run_realtime_report(*args: object) -> Ga4ReportResult:
        realtime.extend(args)
        return Ga4ReportResult((), (), (), 0)

    monkeypatch.setattr(service._client, "run_report", run_report)
    monkeypatch.setattr(service._client, "run_realtime_report", run_realtime_report)
    assert await service.run_report(
        Ga4ReportRequest(
            "google-main",
            "123456789",
            (Ga4DateRange(date(2026, 7, 1), date(2026, 7, 2)),),
            ("pagePath",),
            ("screenPageViews",),
            limit=10,
            offset=5,
        )
    ) == Ga4ReportResult((), (), (), 0)
    assert historical[1:] == [
        "123456789",
        Ga4ReportQuery(
            (Ga4DateRangeInput("2026-07-01", "2026-07-02"),),
            ("pagePath",),
            ("screenPageViews",),
            10,
            5,
        ),
    ]
    assert await service.run_realtime_report(
        Ga4RealtimeReportRequest(
            "google-main",
            "123456789",
            ("country",),
            ("activeUsers",),
            limit=10,
        )
    ) == Ga4ReportResult((), (), (), 0)
    assert realtime[1:] == [
        "123456789",
        Ga4ReportQuery(None, ("country",), ("activeUsers",), 10, None),
    ]


@pytest.mark.asyncio
async def test_service_lists_ga4_inventory_only_for_a_discovery_enabled_account(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy = BoundaryPolicy(
        BoundaryDocument.model_validate(
            {
                "accounts": [
                    {
                        "id": "google-main",
                        "provider": "google",
                        "credential": "/run/secrets/google.json",
                        "oauth_token_file": "/run/oauth/google-main.json",
                        "google_account_discovery": True,
                    }
                ]
            }
        )
    )

    async def token(credential_path: Path) -> str:
        del credential_path
        return "test-token"

    service = GoogleAnalyticsDataService(policy, GoogleAnalyticsDataClient(policy, token))
    captured: list[object] = []

    async def list_account_summaries(*args: object) -> tuple[Ga4AccountSummary, ...]:
        captured.extend(args)
        return ()

    monkeypatch.setattr(service._client, "list_account_summaries", list_account_summaries)

    assert await service.list_account_summaries(Ga4AccountDiscoveryRequest("google-main")) == ()
    assert len(captured) == 1

    with pytest.raises(BoundaryDeniedError):
        await _service().list_account_summaries(Ga4AccountDiscoveryRequest("google-main"))


@pytest.mark.asyncio
async def test_service_builds_fixed_ga4_reports_without_caller_selected_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service()
    calls: list[tuple[object, ...]] = []

    async def run_report(*args: object) -> Ga4ReportResult:
        calls.append(args)
        return Ga4ReportResult((), (), (), 0)

    monkeypatch.setattr(service._client, "run_report", run_report)
    request = Ga4FixedReportRequest(
        "google-main",
        "123456789",
        date(2026, 7, 1),
        date(2026, 7, 2),
        limit=10,
    )

    content = await service.fixed_report(request, Ga4FixedReportKind.CONTENT_PERFORMANCE)
    organic_search = await service.fixed_report(
        request, Ga4FixedReportKind.ORGANIC_SEARCH_LANDING_PAGES
    )
    landing = await service.fixed_report(request, Ga4FixedReportKind.LANDING_PAGE_PERFORMANCE)
    traffic_source = await service.fixed_report(
        request, Ga4FixedReportKind.TRAFFIC_SOURCE_PERFORMANCE
    )
    ecommerce = await service.fixed_report(request, Ga4FixedReportKind.ECOMMERCE_PERFORMANCE)
    audiences = await service.fixed_report(request, Ga4FixedReportKind.AUDIENCE_SEGMENTS)
    user_behavior = await service.fixed_report(request, Ga4FixedReportKind.USER_BEHAVIOR)

    assert content.kind is Ga4FixedReportKind.CONTENT_PERFORMANCE
    assert landing.kind is Ga4FixedReportKind.LANDING_PAGE_PERFORMANCE
    assert organic_search.kind is Ga4FixedReportKind.ORGANIC_SEARCH_LANDING_PAGES
    assert traffic_source.kind is Ga4FixedReportKind.TRAFFIC_SOURCE_PERFORMANCE
    assert ecommerce.kind is Ga4FixedReportKind.ECOMMERCE_PERFORMANCE
    assert audiences.kind is Ga4FixedReportKind.AUDIENCE_SEGMENTS
    assert user_behavior.kind is Ga4FixedReportKind.USER_BEHAVIOR
    assert [call[2] for call in calls] == [
        Ga4ReportQuery(
            (Ga4DateRangeInput("2026-07-01", "2026-07-02"),),
            ("pagePathPlusQueryString",),
            ("screenPageViews", "activeUsers", "engagedSessions"),
            10,
            0,
        ),
        Ga4ReportQuery(
            (Ga4DateRangeInput("2026-07-01", "2026-07-02"),),
            ("landingPagePlusQueryString",),
            (
                "organicGoogleSearchClicks",
                "organicGoogleSearchImpressions",
                "organicGoogleSearchClickThroughRate",
                "organicGoogleSearchAveragePosition",
            ),
            10,
            0,
        ),
        Ga4ReportQuery(
            (Ga4DateRangeInput("2026-07-01", "2026-07-02"),),
            ("landingPagePlusQueryString",),
            ("sessions", "activeUsers", "engagedSessions"),
            10,
            0,
        ),
        Ga4ReportQuery(
            (Ga4DateRangeInput("2026-07-01", "2026-07-02"),),
            ("sessionSourceMedium",),
            ("sessions", "activeUsers", "engagedSessions"),
            10,
            0,
        ),
        Ga4ReportQuery(
            (Ga4DateRangeInput("2026-07-01", "2026-07-02"),),
            ("itemName",),
            ("itemsPurchased", "itemsViewed", "itemRevenue"),
            10,
            0,
        ),
        Ga4ReportQuery(
            (Ga4DateRangeInput("2026-07-01", "2026-07-02"),),
            ("audienceName",),
            ("activeUsers", "newUsers", "engagedSessions"),
            10,
            0,
        ),
        Ga4ReportQuery(
            (Ga4DateRangeInput("2026-07-01", "2026-07-02"),),
            ("newVsReturning",),
            ("activeUsers", "newUsers", "engagedSessions"),
            10,
            0,
        ),
    ]


@pytest.mark.asyncio
async def test_service_builds_a_bounded_closed_event_step_funnel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service()
    calls: list[tuple[object, ...]] = []

    async def run_funnel_report(*args: object) -> Ga4FunnelReport:
        calls.append(args)
        return Ga4FunnelReport(Ga4ReportResult((), (), (), None), Ga4ReportResult((), (), (), None))

    monkeypatch.setattr(service._client, "run_funnel_report", run_funnel_report)
    request = Ga4ConversionFunnelRequest(
        "google-main",
        "123456789",
        date(2026, 7, 1),
        date(2026, 7, 2),
        ("view_item", "purchase"),
        limit=10,
    )

    assert await service.conversion_funnel(request) == Ga4FunnelReport(
        Ga4ReportResult((), (), (), None),
        Ga4ReportResult((), (), (), None),
    )
    assert calls[0][1:] == (
        "123456789",
        Ga4FunnelQuery(
            Ga4DateRangeInput("2026-07-01", "2026-07-02"),
            ("view_item", "purchase"),
            10,
        ),
    )


def test_service_rejects_invalid_ga4_requests() -> None:
    with pytest.raises(InputLimitError):
        Ga4FixedReportRequest(
            "google-main",
            "123456789",
            date(2026, 7, 1),
            date(2026, 7, 2),
            limit=0,
        )
    with pytest.raises(InputLimitError):
        Ga4DateRange(date(2026, 7, 2), date(2026, 7, 1))
    with pytest.raises(InputLimitError):
        Ga4DateRange(date(2025, 1, 1), date(2026, 1, 2))
    with pytest.raises(InputLimitError):
        Ga4ReportRequest("google-main", "123456789", (), ("country",), ("activeUsers",))
    with pytest.raises(InputLimitError):
        Ga4ReportRequest(
            "google-main",
            "123456789",
            (Ga4DateRange(date(2026, 7, 1), date(2026, 7, 1)),),
            (),
            ("activeUsers",),
        )

    with pytest.raises(InputLimitError):
        Ga4ReportRequest(
            "google-main",
            "123456789",
            (Ga4DateRange(date(2026, 7, 1), date(2026, 7, 1)),),
            ("country", "country"),
            ("activeUsers",),
        )
    with pytest.raises(InputLimitError):
        Ga4RealtimeReportRequest("google-main", "123456789", ("country",), ("bad name",))
    with pytest.raises(InputLimitError):
        Ga4ReportRequest(
            "google-main",
            "123456789",
            (Ga4DateRange(date(2026, 7, 1), date(2026, 7, 1)),),
            ("country",),
            ("activeUsers",),
            limit=0,
        )
    with pytest.raises(InputLimitError):
        Ga4ReportRequest(
            "google-main",
            "123456789",
            (Ga4DateRange(date(2026, 7, 1), date(2026, 7, 1)),),
            ("country",),
            ("activeUsers",),
            offset=-1,
        )
    with pytest.raises(InputLimitError):
        Ga4RealtimeReportRequest(
            "google-main",
            "123456789",
            ("country",),
            ("activeUsers",),
            limit=0,
        )
    with pytest.raises(InputLimitError):
        Ga4ConversionFunnelRequest(
            "google-main",
            "123456789",
            date(2026, 7, 1),
            date(2026, 7, 2),
            ("purchase",),
        )
    with pytest.raises(InputLimitError):
        Ga4ConversionFunnelRequest(
            "google-main",
            "123456789",
            date(2026, 7, 1),
            date(2026, 7, 2),
            ("view_item", "view_item"),
        )
    with pytest.raises(InputLimitError):
        Ga4ConversionFunnelRequest(
            "google-main",
            "123456789",
            date(2026, 7, 1),
            date(2026, 7, 2),
            ("view_item", "purchase"),
            limit=0,
        )


@pytest.mark.asyncio
async def test_fixed_report_rejects_an_unknown_internal_kind() -> None:
    request = Ga4FixedReportRequest(
        "google-main",
        "123456789",
        date(2026, 7, 1),
        date(2026, 7, 2),
    )
    with pytest.raises(InputLimitError, match="kind is unsupported"):
        await _service().fixed_report(request, cast(Ga4FixedReportKind, "unrecognized"))


@pytest.mark.asyncio
async def test_service_rejects_unconfigured_property_before_provider_call() -> None:
    with pytest.raises(BoundaryDeniedError):
        await _service().run_realtime_report(
            Ga4RealtimeReportRequest(
                "google-main",
                "999999999",
                ("country",),
                ("activeUsers",),
            )
        )
    with pytest.raises(BoundaryDeniedError):
        await _service().content_performance(
            Ga4FixedReportRequest(
                "google-main",
                "999999999",
                date(2026, 7, 1),
                date(2026, 7, 2),
            )
        )
    with pytest.raises(BoundaryDeniedError):
        await _service().conversion_funnel(
            Ga4ConversionFunnelRequest(
                "google-main",
                "999999999",
                date(2026, 7, 1),
                date(2026, 7, 2),
                ("view_item", "purchase"),
            )
        )
