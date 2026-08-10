from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import httpx
import pytest

import rankrat.providers.google_analytics as google_analytics
from rankrat.constants import MAX_GA4_ROWS, MAX_GA4_VALUE_CHARS
from rankrat.errors import BoundaryDeniedError
from rankrat.models.boundaries import BoundaryDocument
from rankrat.policy.boundaries import BoundaryPolicy
from rankrat.providers.base import (
    AccountId,
    ProviderFailureCode,
    ProviderOperationError,
    ProviderReadRequest,
)
from rankrat.providers.google_analytics import (
    Ga4AccountSummary,
    Ga4DateRangeInput,
    Ga4FunnelQuery,
    Ga4FunnelReport,
    Ga4MetricHeader,
    Ga4MetricType,
    Ga4PropertySummary,
    Ga4ReportQuery,
    Ga4ReportResult,
    Ga4ReportRow,
    GoogleAnalyticsDataClient,
)


async def _token(credential_path: Path) -> str:
    del credential_path
    return "test-token"


def _policy() -> BoundaryPolicy:
    return BoundaryPolicy(
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


def _discovery_policy() -> BoundaryPolicy:
    return BoundaryPolicy(
        BoundaryDocument.model_validate(
            {
                "accounts": [
                    {
                        "id": "google-main",
                        "provider": "google",
                        "credential": "/run/secrets/google.json",
                        "oauth_token_file": "/run/oauth/google-main.json",
                    }
                ]
            }
        )
    )


def _request() -> ProviderReadRequest:
    return ProviderReadRequest(AccountId("google-main"), timeout_seconds=1.0)


def _query() -> Ga4ReportQuery:
    return Ga4ReportQuery(None, (), (), 1, None)


def _typed_report_payload() -> dict[str, object]:
    return {
        "dimensionHeaders": [{"name": "pagePath"}],
        "metricHeaders": [{"name": "activeUsers", "type": "TYPE_INTEGER"}],
        "rows": [
            {
                "dimensionValues": [{"value": "/article"}],
                "metricValues": [{"value": "3"}],
            }
        ],
        "rowCount": 1,
    }


@pytest.mark.asyncio
async def test_ga4_reports_use_fixed_origin_exact_property_and_safe_payloads() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith(":runReport"):
            payload = {
                "dimensionHeaders": [{"name": "pagePath"}],
                "metricHeaders": [],
                "rows": [],
                "rowCount": 0,
            }
        else:
            payload = {
                "dimensionHeaders": [],
                "metricHeaders": [{"name": "activeUsers", "type": "TYPE_INTEGER"}],
                "rows": [],
                "rowCount": 0,
            }
        return httpx.Response(
            200,
            json=payload,
        )

    client = GoogleAnalyticsDataClient(
        _policy(),
        _token,
        transport_factory=lambda: httpx.MockTransport(handler),
    )
    report = await client.run_report(
        _request(),
        "123456789",
        Ga4ReportQuery(None, ("pagePath",), (), 1, None),
    )
    realtime = await client.run_realtime_report(
        _request(),
        "123456789",
        Ga4ReportQuery(None, (), ("activeUsers",), 1, None),
    )

    assert report == Ga4ReportResult(("pagePath",), (), (), 0)
    assert realtime == Ga4ReportResult(
        (),
        (Ga4MetricHeader("activeUsers", Ga4MetricType.INTEGER),),
        (),
        0,
    )
    assert [str(request.url) for request in requests] == [
        "https://analyticsdata.googleapis.com/v1beta/properties/123456789:runReport",
        "https://analyticsdata.googleapis.com/v1beta/properties/123456789:runRealtimeReport",
    ]
    assert all(request.method == "POST" for request in requests)
    assert all(request.headers["Authorization"] == "Bearer test-token" for request in requests)
    assert json.loads(requests[0].content) == {
        "dimensions": [{"name": "pagePath"}],
        "metrics": [],
        "limit": "1",
    }
    assert json.loads(requests[1].content) == {
        "dimensions": [],
        "metrics": [{"name": "activeUsers"}],
        "limit": "1",
    }


@pytest.mark.asyncio
async def test_ga4_account_discovery_reads_fixed_origin_pages_and_validates_resources() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.params.get("pageToken") == "second-page":
            return httpx.Response(
                200,
                json={
                    "accountSummaries": [
                        {
                            "name": "accountSummaries/2",
                            "account": "accounts/2",
                            "displayName": "Second account",
                            "propertySummaries": [],
                        }
                    ]
                },
            )
        return httpx.Response(
            200,
            json={
                "accountSummaries": [
                    {
                        "name": "accountSummaries/1",
                        "account": "accounts/1",
                        "displayName": "First account",
                        "propertySummaries": [
                            {
                                "property": "properties/123",
                                "displayName": "First property",
                            }
                        ],
                    }
                ],
                "nextPageToken": "second-page",
            },
        )

    client = GoogleAnalyticsDataClient(
        _discovery_policy(),
        _token,
        transport_factory=lambda: httpx.MockTransport(handler),
    )

    assert await client.list_account_summaries(_request()) == (
        Ga4AccountSummary("1", "First account", (Ga4PropertySummary("123", "First property"),)),
        Ga4AccountSummary("2", "Second account", ()),
    )
    assert [str(request.url) for request in requests] == [
        "https://analyticsadmin.googleapis.com/v1beta/accountSummaries?pageSize=200",
        "https://analyticsadmin.googleapis.com/v1beta/accountSummaries?pageSize=200&pageToken=second-page",
    ]
    assert all(request.method == "GET" for request in requests)
    assert all(request.content == b"" for request in requests)


@pytest.mark.asyncio
async def test_ga4_account_discovery_rejects_unknown_account_before_token_or_network() -> None:
    token_called = False

    async def token(credential_path: Path) -> str:
        del credential_path
        nonlocal token_called
        token_called = True
        return "test-token"

    client = GoogleAnalyticsDataClient(
        _policy(),
        token,
        transport_factory=lambda: pytest.fail("network must not be reached"),
    )

    with pytest.raises(BoundaryDeniedError):
        await client.list_account_summaries(
            ProviderReadRequest(AccountId("missing"), timeout_seconds=1.0)
        )
    assert token_called is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    (
        {"accountSummaries": [{"name": "bad", "account": "accounts/1", "displayName": "x"}]},
        {
            "accountSummaries": [
                {
                    "name": "accountSummaries/1",
                    "account": "accounts/2",
                    "displayName": "x",
                }
            ]
        },
        {
            "accountSummaries": [
                {
                    "name": "accountSummaries/1",
                    "account": "accounts/1",
                    "displayName": "x",
                    "propertySummaries": [
                        {"property": "properties/123", "displayName": "one"},
                        {"property": "properties/123", "displayName": "two"},
                    ],
                }
            ]
        },
        {
            "accountSummaries": [
                {
                    "name": "accountSummaries/1",
                    "account": "accounts/1",
                    "displayName": "one",
                },
                {
                    "name": "accountSummaries/1",
                    "account": "accounts/1",
                    "displayName": "two",
                },
            ]
        },
        {"nextPageToken": 1},
    ),
)
async def test_ga4_account_discovery_rejects_invalid_provider_pages(payload: object) -> None:
    client = GoogleAnalyticsDataClient(
        _discovery_policy(),
        _token,
        transport_factory=lambda: httpx.MockTransport(lambda _: httpx.Response(200, json=payload)),
    )

    with pytest.raises(ProviderOperationError) as error:
        await client.list_account_summaries(_request())

    assert error.value.code is ProviderFailureCode.INVALID_RESPONSE


@pytest.mark.asyncio
async def test_ga4_account_discovery_rejects_repeated_tokens_and_page_limits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses: tuple[dict[str, object], ...] = (
        {"accountSummaries": [], "nextPageToken": "again"},
        {"accountSummaries": [], "nextPageToken": "again"},
    )
    response_index = 0

    def repeated_token_handler(_: httpx.Request) -> httpx.Response:
        nonlocal response_index
        response = responses[response_index]
        response_index += 1
        return httpx.Response(200, json=response)

    client = GoogleAnalyticsDataClient(
        _discovery_policy(),
        _token,
        transport_factory=lambda: httpx.MockTransport(repeated_token_handler),
    )
    with pytest.raises(ProviderOperationError, match="repeated") as repeated_error:
        await client.list_account_summaries(_request())
    assert repeated_error.value.code is ProviderFailureCode.INVALID_RESPONSE

    monkeypatch.setattr(google_analytics, "MAX_GOOGLE_ANALYTICS_DISCOVERY_PAGES", 1)
    limited_client = GoogleAnalyticsDataClient(
        _discovery_policy(),
        _token,
        transport_factory=lambda: httpx.MockTransport(
            lambda _: httpx.Response(200, json={"accountSummaries": [], "nextPageToken": "next"})
        ),
    )
    with pytest.raises(ProviderOperationError, match="pagination exceeds") as limited_error:
        await limited_client.list_account_summaries(_request())
    assert limited_error.value.code is ProviderFailureCode.INVALID_RESPONSE


@pytest.mark.asyncio
async def test_ga4_parses_a_typed_header_aligned_table() -> None:
    client = GoogleAnalyticsDataClient(
        _policy(),
        _token,
        transport_factory=lambda: httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json={
                    **_typed_report_payload(),
                    "propertyQuota": {"tokensPerDay": {"consumed": 1}},
                },
            )
        ),
    )

    assert await client.run_report(
        _request(),
        "123456789",
        Ga4ReportQuery(None, ("pagePath",), ("activeUsers",), 1, None),
    ) == Ga4ReportResult(
        dimension_headers=("pagePath",),
        metric_headers=(Ga4MetricHeader("activeUsers", Ga4MetricType.INTEGER),),
        rows=(Ga4ReportRow(("/article",), ("3",)),),
        row_count=1,
    )


def test_ga4_query_serializes_only_its_fixed_shape() -> None:
    assert Ga4ReportQuery(
        (Ga4DateRangeInput("2026-07-01", "2026-07-02"),),
        ("pagePath",),
        ("activeUsers",),
        10,
        5,
    ).as_payload() == {
        "dateRanges": [{"startDate": "2026-07-01", "endDate": "2026-07-02"}],
        "dimensions": [{"name": "pagePath"}],
        "metrics": [{"name": "activeUsers"}],
        "limit": "10",
        "offset": "5",
    }


@pytest.mark.asyncio
async def test_ga4_funnel_uses_alpha_fixed_origin_and_validates_both_subreports() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "funnelTable": _typed_report_payload(),
                "funnelVisualization": _typed_report_payload(),
            },
        )

    client = GoogleAnalyticsDataClient(
        _policy(),
        _token,
        transport_factory=lambda: httpx.MockTransport(handler),
    )
    query = Ga4FunnelQuery(
        date_range=Ga4DateRangeInput("2026-07-01", "2026-07-02"),
        event_names=("view_item", "purchase"),
        limit=10,
    )

    report = await client.run_funnel_report(_request(), "123456789", query)

    expected_subreport = Ga4ReportResult(
        dimension_headers=("pagePath",),
        metric_headers=(Ga4MetricHeader("activeUsers", Ga4MetricType.INTEGER),),
        rows=(Ga4ReportRow(("/article",), ("3",)),),
        row_count=None,
    )
    assert report == Ga4FunnelReport(expected_subreport, expected_subreport)
    assert str(requests[0].url) == (
        "https://analyticsdata.googleapis.com/v1alpha/properties/123456789:runFunnelReport"
    )
    assert json.loads(requests[0].content) == {
        "dateRanges": [{"startDate": "2026-07-01", "endDate": "2026-07-02"}],
        "funnel": {
            "isOpenFunnel": False,
            "steps": [
                {
                    "name": "view_item",
                    "filterExpression": {"funnelEventFilter": {"eventName": "view_item"}},
                },
                {
                    "name": "purchase",
                    "filterExpression": {"funnelEventFilter": {"eventName": "purchase"}},
                },
            ],
        },
        "limit": "10",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    cast(
        tuple[object, ...],
        (
            {},
            {
                "funnelTable": {
                    "dimensionHeaders": [
                        {"name": "funnelStepName"},
                        {"name": "funnelStepName"},
                    ],
                    "metricHeaders": [],
                    "rows": [],
                },
                "funnelVisualization": {"dimensionHeaders": [], "metricHeaders": [], "rows": []},
            },
            {
                "funnelTable": {
                    "dimensionHeaders": [],
                    "metricHeaders": [
                        {"name": "activeUsers", "type": "TYPE_INTEGER"},
                        {"name": "activeUsers", "type": "TYPE_INTEGER"},
                    ],
                    "rows": [],
                },
                "funnelVisualization": {"dimensionHeaders": [], "metricHeaders": [], "rows": []},
            },
            {
                "funnelTable": {
                    "dimensionHeaders": [],
                    "metricHeaders": [],
                    "rows": [{} for _ in range(MAX_GA4_ROWS + 1)],
                },
                "funnelVisualization": {"dimensionHeaders": [], "metricHeaders": [], "rows": []},
            },
        ),
    ),
)
async def test_ga4_rejects_malformed_funnel_reports(payload: object) -> None:
    client = GoogleAnalyticsDataClient(
        _policy(),
        _token,
        transport_factory=lambda: httpx.MockTransport(lambda _: httpx.Response(200, json=payload)),
    )

    with pytest.raises(ProviderOperationError) as error:
        await client.run_funnel_report(
            _request(),
            "123456789",
            Ga4FunnelQuery(
                Ga4DateRangeInput("2026-07-01", "2026-07-02"), ("view_item", "purchase"), 1
            ),
        )

    assert error.value.code is ProviderFailureCode.INVALID_RESPONSE


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    cast(
        tuple[object, ...],
        (
            {"dimensionHeaders": [{"name": ""}], "metricHeaders": [], "rows": []},
            {
                "dimensionHeaders": [],
                "metricHeaders": [{"name": "activeUsers", "type": 1}],
                "rows": [],
            },
            {
                "dimensionHeaders": [],
                "metricHeaders": [{"name": "activeUsers", "type": "TYPE_UNKNOWN"}],
                "rows": [],
            },
            {
                "dimensionHeaders": [],
                "metricHeaders": [{"name": "activeUsers", "type": "TYPE_INTEGER"}],
                "rows": [{"metricValues": [{"value": "x" * (MAX_GA4_VALUE_CHARS + 1)}]}],
            },
            {
                "dimensionHeaders": [{"name": "pagePath"}, {"name": "pagePath"}],
                "metricHeaders": [],
                "rows": [],
            },
            {"dimensionHeaders": [{"name": "pagePath"}], "metricHeaders": [], "rows": []},
            {
                "dimensionHeaders": [],
                "metricHeaders": [
                    {"name": "activeUsers", "type": "TYPE_INTEGER"},
                    {"name": "activeUsers", "type": "TYPE_INTEGER"},
                ],
                "rows": [],
            },
            {
                "dimensionHeaders": [],
                "metricHeaders": [{"name": "activeUsers", "type": "TYPE_INTEGER"}],
                "rows": [],
            },
            {
                "dimensionHeaders": [{"name": "pagePath"}],
                "metricHeaders": [],
                "rows": [{}],
            },
            {
                "dimensionHeaders": [],
                "metricHeaders": [{"name": "activeUsers", "type": "TYPE_INTEGER"}],
                "rows": [{}],
            },
            {**_typed_report_payload(), "rowCount": 0},
            {**_typed_report_payload(), "rowCount": -1},
            {
                "dimensionHeaders": [],
                "metricHeaders": [],
                "rows": [{} for _ in range(MAX_GA4_ROWS + 1)],
            },
        ),
    ),
)
async def test_ga4_rejects_malformed_typed_reports(payload: object) -> None:
    client = GoogleAnalyticsDataClient(
        _policy(),
        _token,
        transport_factory=lambda: httpx.MockTransport(lambda _: httpx.Response(200, json=payload)),
    )

    with pytest.raises(ProviderOperationError) as error:
        await client.run_report(_request(), "123456789", _query())

    assert error.value.code is ProviderFailureCode.INVALID_RESPONSE


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("payload", "query"),
    cast(
        tuple[tuple[object, Ga4ReportQuery], ...],
        (
            (
                {**_typed_report_payload(), "rowCount": 0},
                Ga4ReportQuery(None, ("pagePath",), ("activeUsers",), 1, None),
            ),
            (
                {
                    "dimensionHeaders": [{"name": "pagePath"}],
                    "metricHeaders": [],
                    "rows": [{}],
                },
                Ga4ReportQuery(None, ("pagePath",), (), 1, None),
            ),
            (
                {
                    "dimensionHeaders": [],
                    "metricHeaders": [{"name": "activeUsers", "type": "TYPE_INTEGER"}],
                    "rows": [{}],
                },
                Ga4ReportQuery(None, (), ("activeUsers",), 1, None),
            ),
        ),
    ),
)
async def test_ga4_rejects_header_aligned_row_integrity_failures(
    payload: object,
    query: Ga4ReportQuery,
) -> None:
    client = GoogleAnalyticsDataClient(
        _policy(),
        _token,
        transport_factory=lambda: httpx.MockTransport(lambda _: httpx.Response(200, json=payload)),
    )

    with pytest.raises(ProviderOperationError) as error:
        await client.run_report(_request(), "123456789", query)

    assert error.value.code is ProviderFailureCode.INVALID_RESPONSE


@pytest.mark.asyncio
async def test_ga4_account_scope_accepts_an_unlisted_property() -> None:
    token_called = False

    async def token(credential_path: Path) -> str:
        del credential_path
        nonlocal token_called
        token_called = True
        return "test-token"

    client = GoogleAnalyticsDataClient(
        _policy(),
        token,
        transport_factory=lambda: httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json={"dimensionHeaders": [], "metricHeaders": [], "rows": []},
            )
        ),
    )

    result = await client.run_report(_request(), "999999999", _query())
    assert result.rows == ()
    assert token_called is True


@pytest.mark.asyncio
async def test_ga4_safely_wraps_unexpected_token_provider_errors() -> None:
    async def token(credential_path: Path) -> str:
        del credential_path
        raise RuntimeError("private provider detail")

    client = GoogleAnalyticsDataClient(_policy(), token)
    with pytest.raises(ProviderOperationError) as error:
        await client.run_report(_request(), "123456789", _query())
    assert error.value.code is ProviderFailureCode.AUTHENTICATION
    assert "private" not in str(error.value)

    async def expected_token_error(credential_path: Path) -> str:
        del credential_path
        raise ProviderOperationError(ProviderFailureCode.FORBIDDEN, "safe failure")

    with pytest.raises(ProviderOperationError) as expected_error:
        await GoogleAnalyticsDataClient(_policy(), expected_token_error).run_report(
            _request(),
            "123456789",
            _query(),
        )
    assert expected_error.value.code is ProviderFailureCode.FORBIDDEN


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "expected_code"),
    [
        (301, ProviderFailureCode.INVALID_RESPONSE),
        (400, ProviderFailureCode.INVALID_RESPONSE),
        (401, ProviderFailureCode.AUTHENTICATION),
        (403, ProviderFailureCode.FORBIDDEN),
        (429, ProviderFailureCode.RATE_LIMITED),
        (500, ProviderFailureCode.UNAVAILABLE),
    ],
)
async def test_ga4_maps_safe_upstream_failures(
    status_code: int,
    expected_code: ProviderFailureCode,
) -> None:
    client = GoogleAnalyticsDataClient(
        _policy(),
        _token,
        transport_factory=lambda: httpx.MockTransport(
            lambda _: httpx.Response(status_code, text="untrusted upstream body")
        ),
    )

    with pytest.raises(ProviderOperationError) as error:
        await client.run_report(_request(), "123456789", _query())
    assert error.value.code is expected_code
    assert "untrusted" not in str(error.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("upstream_error", "expected_code"),
    [
        (httpx.ReadTimeout("timeout"), ProviderFailureCode.TIMEOUT),
        (httpx.ConnectError("offline"), ProviderFailureCode.UNAVAILABLE),
    ],
)
async def test_ga4_maps_transport_errors(
    upstream_error: httpx.HTTPError,
    expected_code: ProviderFailureCode,
) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        raise upstream_error

    client = GoogleAnalyticsDataClient(
        _policy(),
        _token,
        transport_factory=lambda: httpx.MockTransport(handler),
    )
    with pytest.raises(ProviderOperationError) as error:
        await client.run_report(_request(), "123456789", _query())
    assert error.value.code is expected_code
    assert "offline" not in str(error.value)


@pytest.mark.asyncio
async def test_ga4_rejects_invalid_json_non_object_and_oversized_responses() -> None:
    responses = iter(
        (
            httpx.Response(200, content=b"not-json"),
            httpx.Response(200, content=b"[]"),
            httpx.Response(200, headers={"content-length": "2097153"}),
            httpx.Response(
                200,
                headers={"content-length": "unknown"},
                content=b"x" * 2_097_153,
            ),
        )
    )
    client = GoogleAnalyticsDataClient(
        _policy(),
        _token,
        transport_factory=lambda: httpx.MockTransport(lambda _: next(responses)),
    )

    for _ in range(4):
        with pytest.raises(ProviderOperationError) as error:
            await client.run_report(_request(), "123456789", _query())
        assert error.value.code is ProviderFailureCode.INVALID_RESPONSE
