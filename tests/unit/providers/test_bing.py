from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import httpx
import pytest

from rankrat.constants import MAX_PROVIDER_ITEMS, MAX_PROVIDER_RESPONSE_BYTES
from rankrat.errors import BoundaryDeniedError
from rankrat.models.boundaries import BoundaryDocument, Provider
from rankrat.policy.boundaries import BoundaryPolicy
from rankrat.providers.base import (
    AccountId,
    ProviderFailureCode,
    ProviderOperationError,
    ProviderReadRequest,
)
from rankrat.providers.bing import (
    BingCrawlIssueRow,
    BingCrawlStatsRow,
    BingFeedRow,
    BingLinkCountRow,
    BingLinkCounts,
    BingQueryStatsRow,
    BingReadOperation,
    BingTrafficRow,
    BingUrlInformation,
    BingUrlSubmissionQuota,
    BingWebmasterClient,
)


def _policy(credential: Path) -> BoundaryPolicy:
    return BoundaryPolicy(
        BoundaryDocument.model_validate(
            {
                "accounts": [
                    {
                        "id": "bing-main",
                        "provider": Provider.BING,
                        "credential": str(credential),
                        "sites": ["https://example.com/"],
                    }
                ]
            }
        )
    )


def _request() -> ProviderReadRequest:
    return ProviderReadRequest(AccountId("bing-main"), timeout_seconds=1.0)


def _key_file(tmp_path: Path) -> Path:
    key_file = tmp_path / "bing-api-key"
    key_file.write_text("example-bing-key-not-real\n", encoding="utf-8")
    return key_file


def _feed_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "Compressed": False,
        "FileSize": 100,
        "LastCrawled": "/Date(0+0000)/",
        "Status": "Success",
        "Submitted": "2026-07-01",
        "Type": "Sitemap",
        "Url": "https://example.com/sitemap.xml",
        "UrlCount": 3,
    }
    payload.update(overrides)
    return payload


@pytest.mark.asyncio
async def test_list_sites_uses_fixed_origin_and_returns_account_inventory(tmp_path: Path) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url == httpx.URL(
            "https://ssl.bing.com/webmaster/api.svc/json/GetUserSites?apikey=example-bing-key-not-real"
        )
        return httpx.Response(
            200,
            json=[{"Url": "https://example.com/"}, {"Url": "https://other.example/"}],
        )

    client = BingWebmasterClient(
        _policy(_key_file(tmp_path)),
        transport_factory=lambda: httpx.MockTransport(handler),
    )

    assert await client.list_sites(_request()) == (
        "https://example.com/",
        "https://other.example/",
    )


@pytest.mark.asyncio
async def test_read_site_data_uses_enumerated_method_exact_site_and_unwraps_payload(
    tmp_path: Path,
) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == httpx.URL(
            "https://ssl.bing.com/webmaster/api.svc/json/GetQueryStats?apikey=example-bing-key-not-real&siteUrl=https%3A%2F%2Fexample.com%2F"
        )
        return httpx.Response(200, json={"d": {"queries": []}})

    client = BingWebmasterClient(
        _policy(_key_file(tmp_path)),
        transport_factory=lambda: httpx.MockTransport(handler),
    )

    result = await client.read_site_data(
        _request(),
        "https://example.com/",
        BingReadOperation.QUERY_STATS,
    )

    assert result == {"queries": []}


@pytest.mark.asyncio
async def test_rank_and_traffic_stats_returns_only_typed_validated_rows(tmp_path: Path) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == httpx.URL(
            "https://ssl.bing.com/webmaster/api.svc/json/GetRankAndTrafficStats?"
            "apikey=example-bing-key-not-real&siteUrl=https%3A%2F%2Fexample.com%2F"
        )
        return httpx.Response(
            200,
            json={
                "d": [
                    {
                        "Date": "/Date(0+0000)/",
                        "Clicks": 3,
                        "Impressions": 8,
                        "Unused": "ignored by the constrained boundary model",
                    }
                ]
            },
        )

    client = BingWebmasterClient(
        _policy(_key_file(tmp_path)),
        transport_factory=lambda: httpx.MockTransport(handler),
    )

    assert await client.read_rank_and_traffic_stats(
        _request(),
        "https://example.com/",
    ) == (BingTrafficRow(date(1970, 1, 1), 3.0, 8.0),)


@pytest.mark.asyncio
async def test_rank_and_traffic_stats_accepts_a_legacy_utc_timestamp(tmp_path: Path) -> None:
    client = BingWebmasterClient(
        _policy(_key_file(tmp_path)),
        transport_factory=lambda: httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json=[{"Date": "/Date(0)/", "Clicks": 3, "Impressions": 8}],
            )
        ),
    )

    assert await client.read_rank_and_traffic_stats(
        _request(),
        "https://example.com/",
    ) == (BingTrafficRow(date(1970, 1, 1), 3.0, 8.0),)


@pytest.mark.asyncio
async def test_query_and_page_stats_use_fixed_operations_and_return_typed_rows(
    tmp_path: Path,
) -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        label = (
            "rankrat" if request.url.path.endswith("GetQueryStats") else "https://example.com/page"
        )
        return httpx.Response(
            200,
            json={
                "d": [
                    {
                        "Query": label,
                        "Date": "/Date(0+0000)/",
                        "Clicks": 3,
                        "Impressions": 8,
                        "AvgClickPosition": 2,
                        "AvgImpressionPosition": 4,
                        "Unused": "ignored by the constrained boundary model",
                    }
                ]
            },
        )

    client = BingWebmasterClient(
        _policy(_key_file(tmp_path)),
        transport_factory=lambda: httpx.MockTransport(handler),
    )

    assert await client.read_query_stats(_request(), "https://example.com/") == (
        BingQueryStatsRow("rankrat", date(1970, 1, 1), 3.0, 8.0, 2.0, 4.0),
    )
    assert await client.read_page_stats(_request(), "https://example.com/") == (
        BingQueryStatsRow("https://example.com/page", date(1970, 1, 1), 3.0, 8.0, 2.0, 4.0),
    )
    assert [request.method for request in requests] == ["GET", "GET"]
    assert [request.url.path.rsplit("/", maxsplit=1)[-1] for request in requests] == [
        "GetQueryStats",
        "GetPageStats",
    ]
    assert all(request.url.params["siteUrl"] == "https://example.com/" for request in requests)


@pytest.mark.asyncio
async def test_query_stats_preserves_rows_with_unavailable_average_positions(
    tmp_path: Path,
) -> None:
    client = BingWebmasterClient(
        _policy(_key_file(tmp_path)),
        transport_factory=lambda: httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json=[
                    {
                        "Query": "unavailable rank",
                        "Date": "2026-07-01",
                        "Clicks": 0,
                        "Impressions": 1,
                        "AvgClickPosition": -1,
                        "AvgImpressionPosition": -1,
                    },
                    {
                        "Query": "usable rank",
                        "Date": "2026-07-01",
                        "Clicks": 1,
                        "Impressions": 2,
                        "AvgClickPosition": 2,
                        "AvgImpressionPosition": 3,
                    },
                ],
            )
        ),
    )

    assert await client.read_query_stats(_request(), "https://example.com/") == (
        BingQueryStatsRow("unavailable rank", date(2026, 7, 1), 0.0, 1.0, None, None),
        BingQueryStatsRow("usable rank", date(2026, 7, 1), 1.0, 2.0, 2.0, 3.0),
    )


@pytest.mark.asyncio
async def test_query_stats_preserves_a_valid_impression_position_without_a_click_position(
    tmp_path: Path,
) -> None:
    client = BingWebmasterClient(
        _policy(_key_file(tmp_path)),
        transport_factory=lambda: httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json=[
                    {
                        "Query": "impression-ranked",
                        "Date": "2026-07-01",
                        "Clicks": 0,
                        "Impressions": 2,
                        "AvgClickPosition": -1,
                        "AvgImpressionPosition": 8,
                    }
                ],
            )
        ),
    )

    assert await client.read_query_stats(_request(), "https://example.com/") == (
        BingQueryStatsRow("impression-ranked", date(2026, 7, 1), 0.0, 2.0, None, 8.0),
    )


@pytest.mark.asyncio
async def test_query_stats_preserves_one_label_with_distinct_daily_records(tmp_path: Path) -> None:
    client = BingWebmasterClient(
        _policy(_key_file(tmp_path)),
        transport_factory=lambda: httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json=[
                    {
                        "Query": "daily query",
                        "Date": "2026-07-01",
                        "Clicks": 1,
                        "Impressions": 2,
                        "AvgClickPosition": -1,
                        "AvgImpressionPosition": 4,
                    },
                    {
                        "Query": "daily query",
                        "Date": "2026-07-02",
                        "Clicks": 2,
                        "Impressions": 3,
                        "AvgClickPosition": -1,
                        "AvgImpressionPosition": 5,
                    },
                ],
            )
        ),
    )

    assert await client.read_query_stats(_request(), "https://example.com/") == (
        BingQueryStatsRow("daily query", date(2026, 7, 1), 1.0, 2.0, None, 4.0),
        BingQueryStatsRow("daily query", date(2026, 7, 2), 2.0, 3.0, None, 5.0),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    (
        {},
        ["invalid"],
        [
            {
                "Query": "rankrat",
                "Date": "not-a-date",
                "Clicks": 1,
                "Impressions": 1,
                "AvgClickPosition": 1,
                "AvgImpressionPosition": 1,
            }
        ],
        [
            {
                "Query": "",
                "Date": "2026-07-01",
                "Clicks": 1,
                "Impressions": 1,
                "AvgClickPosition": 1,
                "AvgImpressionPosition": 1,
            }
        ],
        [
            {
                "Query": "rankrat",
                "Date": "2026-07-01",
                "Clicks": True,
                "Impressions": 1,
                "AvgClickPosition": 1,
                "AvgImpressionPosition": 1,
            }
        ],
        [
            {
                "Query": "rankrat",
                "Date": "2026-07-01",
                "Clicks": -1,
                "Impressions": 1,
                "AvgClickPosition": 1,
                "AvgImpressionPosition": 1,
            }
        ],
        [
            {
                "Query": "rankrat",
                "Date": "2026-07-01",
                "Clicks": 1,
                "Impressions": 1,
                "AvgClickPosition": 0,
                "AvgImpressionPosition": 1,
            }
        ],
        [
            {
                "Query": "rankrat",
                "Date": "2026-07-01",
                "Clicks": 1,
                "Impressions": 1,
                "AvgClickPosition": -2,
                "AvgImpressionPosition": 1,
            }
        ],
        [
            {
                "Query": "rankrat",
                "Date": "2026-07-01",
                "Clicks": 1,
                "Impressions": 1,
                "AvgClickPosition": 1,
                "AvgImpressionPosition": 1,
            },
            {
                "Query": "rankrat",
                "Date": "2026-07-01",
                "Clicks": 2,
                "Impressions": 2,
                "AvgClickPosition": 2,
                "AvgImpressionPosition": 2,
            },
        ],
        [
            {
                "Query": "rankrat",
                "Date": "2026-07-01",
                "Clicks": 1,
                "Impressions": 1,
                "AvgClickPosition": 1,
                "AvgImpressionPosition": 1,
            }
        ]
        * (MAX_PROVIDER_ITEMS + 1),
    ),
)
async def test_query_and_page_stats_reject_malformed_upstream_rows(
    tmp_path: Path,
    payload: object,
) -> None:
    client = BingWebmasterClient(
        _policy(_key_file(tmp_path)),
        transport_factory=lambda: httpx.MockTransport(lambda _: httpx.Response(200, json=payload)),
    )

    with pytest.raises(ProviderOperationError) as error:
        await client.read_query_stats(_request(), "https://example.com/")

    assert error.value.code is ProviderFailureCode.INVALID_RESPONSE


@pytest.mark.asyncio
async def test_query_and_page_stats_reject_non_finite_metrics_and_boundary_escape(
    tmp_path: Path,
) -> None:
    client = BingWebmasterClient(
        _policy(_key_file(tmp_path)),
        transport_factory=lambda: httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                content=(
                    b'[{"Query":"rankrat","Date":"2026-07-01","Clicks":1,'
                    b'"Impressions":Infinity,"AvgClickPosition":1,'
                    b'"AvgImpressionPosition":1}]'
                ),
            )
        ),
    )

    with pytest.raises(ProviderOperationError) as invalid_response:
        await client.read_page_stats(_request(), "https://example.com/")
    assert invalid_response.value.code is ProviderFailureCode.INVALID_RESPONSE

    no_network = BingWebmasterClient(
        _policy(tmp_path / "missing-key"),
        transport_factory=lambda: pytest.fail("network must not be reached"),
    )
    with pytest.raises(ProviderOperationError):
        await no_network.read_query_stats(_request(), "https://other.example/")


@pytest.mark.asyncio
async def test_query_page_and_page_query_stats_use_fixed_parameters_and_boundaries(
    tmp_path: Path,
) -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json=[
                {
                    "Query": "opaque-label",
                    "Date": "2026-07-01",
                    "Clicks": 1,
                    "Impressions": 2,
                    "AvgClickPosition": 3,
                    "AvgImpressionPosition": 4,
                }
            ],
        )

    client = BingWebmasterClient(
        _policy(_key_file(tmp_path)),
        transport_factory=lambda: httpx.MockTransport(handler),
    )
    assert await client.read_query_page_stats(_request(), "https://example.com/", "rankrat") == (
        BingQueryStatsRow("opaque-label", date(2026, 7, 1), 1.0, 2.0, 3.0, 4.0),
    )
    assert await client.read_page_query_stats(
        _request(), "https://example.com/", "https://example.com/page"
    ) == (BingQueryStatsRow("opaque-label", date(2026, 7, 1), 1.0, 2.0, 3.0, 4.0),)
    assert [request.url.path.rsplit("/", maxsplit=1)[-1] for request in requests] == [
        "GetQueryPageStats",
        "GetPageQueryStats",
    ]
    assert requests[0].url.params["query"] == "rankrat"
    assert requests[1].url.params["page"] == "https://example.com/page"

    no_network = BingWebmasterClient(
        _policy(tmp_path / "missing-key"),
        transport_factory=lambda: pytest.fail("network must not be reached"),
    )
    with pytest.raises(BoundaryDeniedError):
        await no_network.read_page_query_stats(
            _request(),
            "https://example.com/",
            "https://other.example/page",
        )


@pytest.mark.asyncio
async def test_url_submission_quota_uses_fixed_operation_and_returns_typed_values(
    tmp_path: Path,
) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url == httpx.URL(
            "https://ssl.bing.com/webmaster/api.svc/json/GetUrlSubmissionQuota?"
            "apikey=example-bing-key-not-real&siteUrl=https%3A%2F%2Fexample.com%2F"
        )
        return httpx.Response(
            200,
            json={"d": {"DailyQuota": 5, "MonthlyQuota": 24, "FutureField": "ignored"}},
        )

    client = BingWebmasterClient(
        _policy(_key_file(tmp_path)),
        transport_factory=lambda: httpx.MockTransport(handler),
    )

    assert await client.read_url_submission_quota(
        _request(),
        "https://example.com/",
    ) == BingUrlSubmissionQuota(daily=5, monthly=24)

    no_network = BingWebmasterClient(
        _policy(tmp_path / "missing-key"),
        transport_factory=lambda: pytest.fail("network must not be reached"),
    )
    with pytest.raises(ProviderOperationError):
        await no_network.read_url_submission_quota(_request(), "https://other.example/")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    (
        {},
        [],
        {"DailyQuota": 5},
        {"DailyQuota": True, "MonthlyQuota": 24},
        {"DailyQuota": -1, "MonthlyQuota": 24},
        {"DailyQuota": 5.5, "MonthlyQuota": 24},
    ),
)
async def test_url_submission_quota_rejects_malformed_upstream_values(
    tmp_path: Path,
    payload: object,
) -> None:
    client = BingWebmasterClient(
        _policy(_key_file(tmp_path)),
        transport_factory=lambda: httpx.MockTransport(lambda _: httpx.Response(200, json=payload)),
    )

    with pytest.raises(ProviderOperationError) as error:
        await client.read_url_submission_quota(_request(), "https://example.com/")

    assert error.value.code is ProviderFailureCode.INVALID_RESPONSE


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    (
        {},
        ["invalid"],
        [{"Date": "not-a-date", "Clicks": 1, "Impressions": 1}],
        [{"Date": "2026-07-01", "Clicks": True, "Impressions": 1}],
        [{"Date": "2026-07-01", "Clicks": -1, "Impressions": 1}],
        [
            {"Date": "2026-07-01", "Clicks": 1, "Impressions": 1},
            {"Date": "2026-07-01", "Clicks": 2, "Impressions": 2},
        ],
        [{"Date": "/Date(0+9999)/", "Clicks": 1, "Impressions": 1}],
        [{"Date": "2026-07-01", "Clicks": 1, "Impressions": 1}] * (MAX_PROVIDER_ITEMS + 1),
    ),
)
async def test_rank_and_traffic_stats_rejects_malformed_upstream_rows(
    tmp_path: Path,
    payload: object,
) -> None:
    client = BingWebmasterClient(
        _policy(_key_file(tmp_path)),
        transport_factory=lambda: httpx.MockTransport(lambda _: httpx.Response(200, json=payload)),
    )

    with pytest.raises(ProviderOperationError) as error:
        await client.read_rank_and_traffic_stats(_request(), "https://example.com/")

    assert error.value.code is ProviderFailureCode.INVALID_RESPONSE


@pytest.mark.asyncio
async def test_rank_and_traffic_stats_rejects_non_finite_json_metric(tmp_path: Path) -> None:
    client = BingWebmasterClient(
        _policy(_key_file(tmp_path)),
        transport_factory=lambda: httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                content=b'[{"Date":"2026-07-01","Clicks":1,"Impressions":Infinity}]',
            )
        ),
    )

    with pytest.raises(ProviderOperationError) as error:
        await client.read_rank_and_traffic_stats(_request(), "https://example.com/")

    assert error.value.code is ProviderFailureCode.INVALID_RESPONSE


@pytest.mark.asyncio
async def test_readiness_site_parameters_and_keyword_reads_are_fixed_and_bounded(
    tmp_path: Path,
) -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("GetUserSites"):
            return httpx.Response(200, json=[])
        return httpx.Response(200, json={"d": []})

    client = BingWebmasterClient(
        _policy(_key_file(tmp_path)),
        transport_factory=lambda: httpx.MockTransport(handler),
    )

    readiness = await client.readiness(_request())
    site_result = await client.read_site_data(
        _request(),
        "https://example.com/",
        BingReadOperation.URL_INFO,
        {"page": "https://example.com/post"},
    )
    keyword_statistics = await client.read_keyword_stats(
        _request(),
        "rankrat",
        "US",
        "en",
    )
    related_keywords = await client.read_related_keywords(
        _request(),
        "rankrat",
        "US",
        "en",
        date(2026, 7, 1),
        date(2026, 7, 2),
    )

    assert readiness.available is True
    assert site_result == []
    assert keyword_statistics == ()
    assert related_keywords == ()
    assert [request.url.path.rsplit("/", maxsplit=1)[-1] for request in requests] == [
        "GetUserSites",
        "GetUrlInfo",
        "GetKeywordStats",
        "GetRelatedKeywords",
    ]
    assert requests[1].url.params["siteUrl"] == "https://example.com/"
    assert requests[1].url.params["page"] == "https://example.com/post"
    assert "siteUrl" not in requests[2].url.params
    assert dict(requests[2].url.params) == {
        "apikey": "example-bing-key-not-real",
        "q": "rankrat",
        "country": "US",
        "language": "en",
    }
    assert dict(requests[3].url.params) == {
        "apikey": "example-bing-key-not-real",
        "q": "rankrat",
        "country": "US",
        "language": "en",
        "startDate": "2026-07-01",
        "endDate": "2026-07-02",
    }


@pytest.mark.asyncio
async def test_keyword_reads_reject_unknown_account_before_key_or_network(
    tmp_path: Path,
) -> None:
    client = BingWebmasterClient(
        _policy(tmp_path / "missing-key"),
        transport_factory=lambda: pytest.fail("network must not be reached"),
    )

    with pytest.raises(BoundaryDeniedError):
        await client.read_keyword_stats(
            ProviderReadRequest(AccountId("missing"), timeout_seconds=1.0),
            "rankrat",
            None,
            None,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    (
        {},
        [{"Query": "", "Date": "2026-07-01", "Impressions": 1, "BroadImpressions": 1}],
        [{"Query": "rankrat", "Date": "invalid", "Impressions": 1, "BroadImpressions": 1}],
        [{"Query": "rankrat", "Date": "2026-07-01", "Impressions": True, "BroadImpressions": 1}],
        [{"Query": "rankrat", "Date": "2026-07-01", "Impressions": -1, "BroadImpressions": 1}],
        [
            {"Query": "rankrat", "Date": "2026-07-01", "Impressions": 1, "BroadImpressions": 1},
            {"Query": "rankrat", "Date": "2026-07-01", "Impressions": 2, "BroadImpressions": 2},
        ],
    ),
)
async def test_keyword_statistics_rejects_malformed_upstream_rows(
    tmp_path: Path,
    payload: object,
) -> None:
    client = BingWebmasterClient(
        _policy(_key_file(tmp_path)),
        transport_factory=lambda: httpx.MockTransport(lambda _: httpx.Response(200, json=payload)),
    )

    with pytest.raises(ProviderOperationError) as error:
        await client.read_keyword_stats(_request(), "rankrat", None, None)

    assert error.value.code is ProviderFailureCode.INVALID_RESPONSE


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    (
        {},
        [{"Query": "", "Impressions": 1, "BroadImpressions": 1}],
        [{"Query": "related", "Impressions": True, "BroadImpressions": 1}],
        [{"Query": "related", "Impressions": -1, "BroadImpressions": 1}],
        [
            {"Query": "related", "Impressions": 1, "BroadImpressions": 1},
            {"Query": "related", "Impressions": 2, "BroadImpressions": 2},
        ],
    ),
)
async def test_related_keywords_reject_malformed_upstream_rows(
    tmp_path: Path,
    payload: object,
) -> None:
    client = BingWebmasterClient(
        _policy(_key_file(tmp_path)),
        transport_factory=lambda: httpx.MockTransport(lambda _: httpx.Response(200, json=payload)),
    )

    with pytest.raises(ProviderOperationError) as error:
        await client.read_related_keywords(
            _request(),
            "rankrat",
            None,
            None,
            date(2026, 7, 1),
            date(2026, 7, 2),
        )

    assert error.value.code is ProviderFailureCode.INVALID_RESPONSE


@pytest.mark.asyncio
async def test_account_scoped_reads_still_require_a_valid_api_key(tmp_path: Path) -> None:
    client = BingWebmasterClient(
        _policy(tmp_path / "missing-key"),
        transport_factory=lambda: pytest.fail("network must not be reached"),
    )

    with pytest.raises(ProviderOperationError):
        await client.read_site_data(
            _request(),
            "https://other.example/",
            BingReadOperation.QUERY_STATS,
        )


@pytest.mark.asyncio
async def test_submit_url_batch_uses_fixed_post_origin_and_exact_configured_site(
    tmp_path: Path,
) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url == httpx.URL(
            "https://ssl.bing.com/webmaster/api.svc/json/SubmitUrlBatch?apikey=example-bing-key-not-real"
        )
        assert json.loads(request.content) == {
            "siteUrl": "https://example.com/",
            "urlList": ["https://example.com/article"],
        }
        return httpx.Response(200, json={"d": None})

    client = BingWebmasterClient(
        _policy(_key_file(tmp_path)),
        transport_factory=lambda: httpx.MockTransport(handler),
    )

    await client.submit_url_batch(
        _request(),
        "https://example.com/",
        ("https://example.com/article",),
    )


@pytest.mark.asyncio
async def test_submit_url_batch_on_account_scope_still_requires_a_valid_api_key(
    tmp_path: Path,
) -> None:
    client = BingWebmasterClient(
        _policy(tmp_path / "missing-key"),
        transport_factory=lambda: pytest.fail("network must not be reached"),
    )

    with pytest.raises(ProviderOperationError):
        await client.submit_url_batch(
            _request(),
            "https://other.example/",
            ("https://other.example/article",),
        )


@pytest.mark.asyncio
async def test_feed_mutations_use_only_fixed_post_operations_and_configured_site(
    tmp_path: Path,
) -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"d": None})

    client = BingWebmasterClient(
        _policy(_key_file(tmp_path)),
        transport_factory=lambda: httpx.MockTransport(handler),
    )
    await client.submit_feed(
        _request(),
        "https://example.com/",
        "https://example.com/sitemap.xml",
    )
    await client.remove_feed(
        _request(),
        "https://example.com/",
        "https://example.com/sitemap.xml",
    )

    assert [request.method for request in requests] == ["POST", "POST"]
    assert [request.url.path.rsplit("/", maxsplit=1)[-1] for request in requests] == [
        "SubmitFeed",
        "RemoveFeed",
    ]
    assert all(request.url.params["apikey"] == "example-bing-key-not-real" for request in requests)
    assert [json.loads(request.content) for request in requests] == [
        {
            "siteUrl": "https://example.com/",
            "feedUrl": "https://example.com/sitemap.xml",
        },
        {
            "siteUrl": "https://example.com/",
            "feedUrl": "https://example.com/sitemap.xml",
        },
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ("submit_feed", "remove_feed"))
async def test_feed_mutations_classify_legacy_unverified_site_errors_without_leaking_body(
    tmp_path: Path,
    operation: str,
) -> None:
    provider_message = "provider-error-containing-a-fake-secret-value"
    client = BingWebmasterClient(
        _policy(_key_file(tmp_path)),
        transport_factory=lambda: httpx.MockTransport(
            lambda _: httpx.Response(
                400,
                json={"ErrorCode": 14, "Message": provider_message},
            )
        ),
    )

    with pytest.raises(ProviderOperationError) as error:
        await getattr(client, operation)(
            _request(),
            "https://example.com/",
            "https://example.com/sitemap.xml",
        )

    assert error.value.code is ProviderFailureCode.FORBIDDEN
    assert provider_message not in str(error.value)
    assert "example-bing-key-not-real" not in str(error.value)


@pytest.mark.asyncio
async def test_feed_mutations_reject_non_null_success_response(tmp_path: Path) -> None:
    client = BingWebmasterClient(
        _policy(_key_file(tmp_path)),
        transport_factory=lambda: httpx.MockTransport(
            lambda _: httpx.Response(200, json={"d": {"unexpected": True}})
        ),
    )

    with pytest.raises(ProviderOperationError) as error:
        await client.submit_feed(
            _request(),
            "https://example.com/",
            "https://example.com/sitemap.xml",
        )

    assert error.value.code is ProviderFailureCode.INVALID_RESPONSE


@pytest.mark.asyncio
async def test_feed_mutations_on_account_scope_still_require_a_valid_api_key(
    tmp_path: Path,
) -> None:
    client = BingWebmasterClient(
        _policy(tmp_path / "missing-key"),
        transport_factory=lambda: pytest.fail("network must not be reached"),
    )

    with pytest.raises(ProviderOperationError):
        await client.submit_feed(
            _request(),
            "https://other.example/",
            "https://other.example/sitemap.xml",
        )


@pytest.mark.asyncio
async def test_site_mutations_use_only_fixed_post_operations_and_configured_site(
    tmp_path: Path,
) -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"d": None})

    client = BingWebmasterClient(
        _policy(_key_file(tmp_path)),
        transport_factory=lambda: httpx.MockTransport(handler),
    )
    await client.add_site(_request(), "https://example.com/")
    await client.remove_site(_request(), "https://example.com/")

    assert [request.method for request in requests] == ["POST", "POST"]
    assert [request.url.path.rsplit("/", maxsplit=1)[-1] for request in requests] == [
        "AddSite",
        "RemoveSite",
    ]
    assert all(request.url.params["apikey"] == "example-bing-key-not-real" for request in requests)
    assert [json.loads(request.content) for request in requests] == [
        {"siteUrl": "https://example.com/"},
        {"siteUrl": "https://example.com/"},
    ]


@pytest.mark.asyncio
async def test_site_mutations_reject_bad_response_and_missing_api_key(
    tmp_path: Path,
) -> None:
    invalid_response = BingWebmasterClient(
        _policy(_key_file(tmp_path)),
        transport_factory=lambda: httpx.MockTransport(
            lambda _: httpx.Response(200, json={"d": {"unexpected": True}})
        ),
    )
    with pytest.raises(ProviderOperationError) as response_error:
        await invalid_response.add_site(_request(), "https://example.com/")
    assert response_error.value.code is ProviderFailureCode.INVALID_RESPONSE

    no_network = BingWebmasterClient(
        _policy(tmp_path / "missing-key"),
        transport_factory=lambda: pytest.fail("network must not be reached"),
    )
    with pytest.raises(ProviderOperationError):
        await no_network.remove_site(_request(), "https://other.example/")


@pytest.mark.asyncio
async def test_site_mutations_map_transport_failures_without_exposing_the_api_key(
    tmp_path: Path,
) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline")

    client = BingWebmasterClient(
        _policy(_key_file(tmp_path)),
        transport_factory=lambda: httpx.MockTransport(handler),
    )
    with pytest.raises(ProviderOperationError) as error:
        await client.add_site(_request(), "https://example.com/")

    assert error.value.code is ProviderFailureCode.UNAVAILABLE
    assert "example-bing-key-not-real" not in str(error.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    (
        {"Url": "https://example.com/"},
        ["not-an-object"],
        [{}],
        [{"Url": 1}],
        [{"Url": "https://example.com/"}] * (MAX_PROVIDER_ITEMS + 1),
    ),
)
async def test_list_sites_rejects_malformed_payloads(tmp_path: Path, payload: object) -> None:
    client = BingWebmasterClient(
        _policy(_key_file(tmp_path)),
        transport_factory=lambda: httpx.MockTransport(lambda _: httpx.Response(200, json=payload)),
    )

    with pytest.raises(ProviderOperationError) as error:
        await client.list_sites(_request())

    assert error.value.code is ProviderFailureCode.INVALID_RESPONSE


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "expected_code"),
    (
        (401, ProviderFailureCode.AUTHENTICATION),
        (403, ProviderFailureCode.AUTHENTICATION),
        (429, ProviderFailureCode.RATE_LIMITED),
        (500, ProviderFailureCode.UNAVAILABLE),
        (301, ProviderFailureCode.INVALID_RESPONSE),
        (400, ProviderFailureCode.INVALID_RESPONSE),
    ),
)
async def test_list_sites_maps_safe_upstream_failures(
    tmp_path: Path,
    status_code: int,
    expected_code: ProviderFailureCode,
) -> None:
    client = BingWebmasterClient(
        _policy(_key_file(tmp_path)),
        transport_factory=lambda: httpx.MockTransport(
            lambda _: httpx.Response(status_code, text="untrusted provider body")
        ),
    )

    with pytest.raises(ProviderOperationError) as error:
        await client.list_sites(_request())

    assert error.value.code is expected_code
    assert "untrusted" not in str(error.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("upstream_error", "expected_code"),
    (
        (httpx.ReadTimeout("timeout"), ProviderFailureCode.TIMEOUT),
        (httpx.ConnectError("offline"), ProviderFailureCode.UNAVAILABLE),
    ),
)
async def test_list_sites_maps_transport_errors(
    tmp_path: Path,
    upstream_error: httpx.HTTPError,
    expected_code: ProviderFailureCode,
) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        raise upstream_error

    client = BingWebmasterClient(
        _policy(_key_file(tmp_path)),
        transport_factory=lambda: httpx.MockTransport(handler),
    )

    with pytest.raises(ProviderOperationError) as error:
        await client.list_sites(_request())

    assert error.value.code is expected_code
    assert "offline" not in str(error.value)


@pytest.mark.asyncio
async def test_list_sites_rejects_invalid_json_and_oversized_response(tmp_path: Path) -> None:
    key_file = _key_file(tmp_path)
    invalid_json = BingWebmasterClient(
        _policy(key_file),
        transport_factory=lambda: httpx.MockTransport(lambda _: httpx.Response(200, content=b"{")),
    )
    oversized = BingWebmasterClient(
        _policy(key_file),
        transport_factory=lambda: httpx.MockTransport(
            lambda _: httpx.Response(200, content=b"x" * (MAX_PROVIDER_RESPONSE_BYTES + 1))
        ),
    )

    for client in (invalid_json, oversized):
        with pytest.raises(ProviderOperationError) as error:
            await client.list_sites(_request())
        assert error.value.code is ProviderFailureCode.INVALID_RESPONSE

    class OversizedStream(httpx.AsyncByteStream):
        async def __aiter__(self):  # type: ignore[override]
            yield b"x" * (MAX_PROVIDER_RESPONSE_BYTES + 1)

        async def aclose(self) -> None:
            return None

    streamed = BingWebmasterClient(
        _policy(key_file),
        transport_factory=lambda: httpx.MockTransport(
            lambda _: httpx.Response(200, stream=OversizedStream())
        ),
    )
    with pytest.raises(ProviderOperationError) as streamed_error:
        await streamed.list_sites(_request())
    assert streamed_error.value.code is ProviderFailureCode.INVALID_RESPONSE


@pytest.mark.parametrize("key_content", (b"", b"bad\x00key", b"x" * 513))
def test_load_api_key_rejects_invalid_or_oversized_key(tmp_path: Path, key_content: bytes) -> None:
    key_file = tmp_path / "bing-api-key"
    key_file.write_bytes(key_content)

    with pytest.raises(ProviderOperationError) as error:
        BingWebmasterClient._load_api_key(key_file)

    assert error.value.code is ProviderFailureCode.AUTHENTICATION


def test_load_api_key_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ProviderOperationError) as error:
        BingWebmasterClient._load_api_key(tmp_path / "missing-key")

    assert error.value.code is ProviderFailureCode.AUTHENTICATION


@pytest.mark.asyncio
async def test_crawl_reports_use_fixed_operations_and_return_typed_rows(tmp_path: Path) -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("GetCrawlIssues"):
            return httpx.Response(
                200,
                json={
                    "d": [
                        {
                            "HttpCode": 404,
                            "Issues": 2,
                            "Url": "https://example.com/missing",
                            "InLinks": 3,
                            "Ignored": "not exposed",
                        }
                    ]
                },
            )
        return httpx.Response(
            200,
            json={
                "d": [
                    {
                        "AllOtherCodes": 1,
                        "BlockedByRobotsTxt": 2,
                        "Code2xx": 3,
                        "Code301": 4,
                        "Code302": 5,
                        "Code4xx": 6,
                        "Code5xx": 7,
                        "ContainsMalware": 8,
                        "ConnectionTimeout": None,
                        "CrawlErrors": 9,
                        "CrawledPages": 10,
                        "Date": "/Date(0+0000)/",
                        "DnsFailures": None,
                        "InIndex": 11,
                        "InLinks": 12,
                        "Ignored": "not exposed",
                    }
                ]
            },
        )

    client = BingWebmasterClient(
        _policy(_key_file(tmp_path)),
        transport_factory=lambda: httpx.MockTransport(handler),
    )

    assert await client.read_crawl_issues(_request(), "https://example.com/") == (
        BingCrawlIssueRow("https://example.com/missing", 404, 2, 3),
    )
    assert await client.read_crawl_stats(_request(), "https://example.com/") == (
        BingCrawlStatsRow(
            day=date(1970, 1, 1),
            all_other_codes=1,
            blocked_by_robots_txt=2,
            code_2xx=3,
            code_301=4,
            code_302=5,
            code_4xx=6,
            code_5xx=7,
            contains_malware=8,
            connection_timeout=None,
            crawl_errors=9,
            crawled_pages=10,
            dns_failures=None,
            in_index=11,
            in_links=12,
        ),
    )
    assert [request.url.path.rsplit("/", maxsplit=1)[-1] for request in requests] == [
        "GetCrawlIssues",
        "GetCrawlStats",
    ]
    assert all(request.url.params["siteUrl"] == "https://example.com/" for request in requests)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("operation", "payload"),
    (
        ("issues", {}),
        ("issues", [{"HttpCode": -1, "Issues": 1, "Url": "https://example.com/a", "InLinks": 1}]),
        ("issues", [{"HttpCode": 1, "Issues": 1, "Url": "", "InLinks": 1}]),
        ("issues", [{"HttpCode": 1, "Issues": 1, "Url": "x" * 2_049, "InLinks": 1}]),
        (
            "issues",
            [{"HttpCode": 1, "Issues": 1, "Url": "https://example.com/a", "InLinks": 1}] * 2,
        ),
        (
            "issues",
            [{"HttpCode": 1, "Issues": 1, "Url": "https://example.com/a", "InLinks": 1}]
            * (MAX_PROVIDER_ITEMS + 1),
        ),
        ("stats", [{"Date": "not-a-date"}]),
        (
            "stats",
            [
                {
                    "AllOtherCodes": 0,
                    "BlockedByRobotsTxt": 0,
                    "Code2xx": 0,
                    "Code301": 0,
                    "Code302": 0,
                    "Code4xx": 0,
                    "Code5xx": 0,
                    "ContainsMalware": 0,
                    "CrawlErrors": 0,
                    "CrawledPages": 0,
                    "Date": "2026-07-01",
                    "InIndex": 0,
                    "InLinks": -1,
                }
            ],
        ),
        (
            "stats",
            [
                {
                    "AllOtherCodes": 0,
                    "BlockedByRobotsTxt": 0,
                    "Code2xx": 0,
                    "Code301": 0,
                    "Code302": 0,
                    "Code4xx": 0,
                    "Code5xx": 0,
                    "ContainsMalware": 0,
                    "CrawlErrors": 0,
                    "CrawledPages": 0,
                    "Date": "2026-07-01",
                    "InIndex": 0,
                    "InLinks": 0,
                    "ConnectionTimeout": -1,
                }
            ],
        ),
        (
            "stats",
            [
                {
                    "AllOtherCodes": 0,
                    "BlockedByRobotsTxt": 0,
                    "Code2xx": 0,
                    "Code301": 0,
                    "Code302": 0,
                    "Code4xx": 0,
                    "Code5xx": 0,
                    "ContainsMalware": 0,
                    "CrawlErrors": 0,
                    "CrawledPages": 0,
                    "Date": "2026-07-01",
                    "InIndex": 0,
                    "InLinks": 0,
                },
                {
                    "AllOtherCodes": 0,
                    "BlockedByRobotsTxt": 0,
                    "Code2xx": 0,
                    "Code301": 0,
                    "Code302": 0,
                    "Code4xx": 0,
                    "Code5xx": 0,
                    "ContainsMalware": 0,
                    "CrawlErrors": 0,
                    "CrawledPages": 0,
                    "Date": "2026-07-01",
                    "InIndex": 0,
                    "InLinks": 0,
                },
            ],
        ),
    ),
)
async def test_crawl_reports_reject_malformed_or_duplicate_upstream_payloads(
    tmp_path: Path,
    operation: str,
    payload: object,
) -> None:
    client = BingWebmasterClient(
        _policy(_key_file(tmp_path)),
        transport_factory=lambda: httpx.MockTransport(lambda _: httpx.Response(200, json=payload)),
    )

    with pytest.raises(ProviderOperationError) as error:
        if operation == "issues":
            await client.read_crawl_issues(_request(), "https://example.com/")
        else:
            await client.read_crawl_stats(_request(), "https://example.com/")

    assert error.value.code is ProviderFailureCode.INVALID_RESPONSE


@pytest.mark.asyncio
async def test_crawl_reports_on_account_scope_still_require_a_valid_api_key(
    tmp_path: Path,
) -> None:
    client = BingWebmasterClient(
        _policy(tmp_path / "missing-key"),
        transport_factory=lambda: pytest.fail("network must not be reached"),
    )

    with pytest.raises(ProviderOperationError):
        await client.read_crawl_issues(_request(), "https://other.example/")
    with pytest.raises(ProviderOperationError):
        await client.read_crawl_stats(_request(), "https://other.example/")


@pytest.mark.asyncio
async def test_feeds_use_the_fixed_operation_and_return_typed_rows(tmp_path: Path) -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"d": [_feed_payload(Ignored="not exposed")]})

    client = BingWebmasterClient(
        _policy(_key_file(tmp_path)),
        transport_factory=lambda: httpx.MockTransport(handler),
    )

    assert await client.read_feeds(_request(), "https://example.com/") == (
        BingFeedRow(
            url="https://example.com/sitemap.xml",
            feed_type="Sitemap",
            status="Success",
            compressed=False,
            file_size=100,
            url_count=3,
            last_crawled=date(1970, 1, 1),
            submitted=date(2026, 7, 1),
        ),
    )
    assert requests[0].url.path.endswith("GetFeeds")
    assert requests[0].url.params["siteUrl"] == "https://example.com/"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    (
        {},
        [_feed_payload(FileSize=-1)],
        [_feed_payload(UrlCount=-1)],
        [_feed_payload(Compressed=1)],
        [_feed_payload(Status="")],
        [_feed_payload(Type="x" * 2_049)],
        [_feed_payload(LastCrawled="not-a-date")],
        [_feed_payload(), _feed_payload()],
        [_feed_payload()] * (MAX_PROVIDER_ITEMS + 1),
    ),
)
async def test_feeds_reject_malformed_duplicate_or_oversized_payloads(
    tmp_path: Path,
    payload: object,
) -> None:
    client = BingWebmasterClient(
        _policy(_key_file(tmp_path)),
        transport_factory=lambda: httpx.MockTransport(lambda _: httpx.Response(200, json=payload)),
    )

    with pytest.raises(ProviderOperationError) as error:
        await client.read_feeds(_request(), "https://example.com/")

    assert error.value.code is ProviderFailureCode.INVALID_RESPONSE


@pytest.mark.asyncio
async def test_feeds_on_account_scope_still_require_a_valid_api_key(tmp_path: Path) -> None:
    client = BingWebmasterClient(
        _policy(tmp_path / "missing-key"),
        transport_factory=lambda: pytest.fail("network must not be reached"),
    )

    with pytest.raises(ProviderOperationError):
        await client.read_feeds(_request(), "https://other.example/")


@pytest.mark.asyncio
async def test_link_counts_use_fixed_page_and_return_typed_values(tmp_path: Path) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("GetLinkCounts")
        assert request.url.params["siteUrl"] == "https://example.com/"
        assert request.url.params["page"] == "2"
        return httpx.Response(
            200,
            json={
                "d": {
                    "Links": [
                        {"Count": 3, "Url": "https://source.example/a"},
                        {"Count": 1, "Url": "https://source.example/b"},
                    ],
                    "TotalPages": 4,
                }
            },
        )

    client = BingWebmasterClient(
        _policy(_key_file(tmp_path)),
        transport_factory=lambda: httpx.MockTransport(handler),
    )

    assert await client.read_link_counts(_request(), "https://example.com/", 2) == BingLinkCounts(
        links=(
            BingLinkCountRow(url="https://source.example/a", count=3),
            BingLinkCountRow(url="https://source.example/b", count=1),
        ),
        total_pages=4,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    (
        {},
        {"Links": [], "TotalPages": -1},
        {"Links": [{"Count": -1, "Url": "https://source.example/a"}], "TotalPages": 1},
        {"Links": [{"Count": 1, "Url": ""}], "TotalPages": 1},
        {
            "Links": [
                {"Count": 1, "Url": "https://source.example/a"},
                {"Count": 2, "Url": "https://source.example/a"},
            ],
            "TotalPages": 1,
        },
        {
            "Links": [{"Count": 1, "Url": "https://source.example/a"}] * (MAX_PROVIDER_ITEMS + 1),
            "TotalPages": 1,
        },
    ),
)
async def test_link_counts_reject_malformed_duplicate_or_oversized_payloads(
    tmp_path: Path,
    payload: object,
) -> None:
    client = BingWebmasterClient(
        _policy(_key_file(tmp_path)),
        transport_factory=lambda: httpx.MockTransport(lambda _: httpx.Response(200, json=payload)),
    )

    with pytest.raises(ProviderOperationError) as error:
        await client.read_link_counts(_request(), "https://example.com/", 0)

    assert error.value.code is ProviderFailureCode.INVALID_RESPONSE


@pytest.mark.asyncio
async def test_link_counts_on_account_scope_still_require_a_valid_api_key(
    tmp_path: Path,
) -> None:
    client = BingWebmasterClient(
        _policy(tmp_path / "missing-key"),
        transport_factory=lambda: pytest.fail("network must not be reached"),
    )

    with pytest.raises(ProviderOperationError):
        await client.read_link_counts(_request(), "https://other.example/", 0)


@pytest.mark.asyncio
async def test_url_information_uses_fixed_operation_and_returns_typed_values(
    tmp_path: Path,
) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("GetUrlInfo")
        assert request.url.params["siteUrl"] == "https://example.com/"
        assert request.url.params["url"] == "https://example.com/article"
        return httpx.Response(
            200,
            json={
                "d": {
                    "AnchorCount": 3,
                    "DiscoveryDate": "2026-07-01",
                    "DocumentSize": 100,
                    "HttpStatus": 200,
                    "IsPage": True,
                    "LastCrawledDate": "/Date(0+0000)/",
                    "TotalChildUrlCount": 2,
                    "Url": "https://example.com/article",
                }
            },
        )

    client = BingWebmasterClient(
        _policy(_key_file(tmp_path)),
        transport_factory=lambda: httpx.MockTransport(handler),
    )

    assert await client.read_url_information(
        _request(),
        "https://example.com/",
        "https://example.com/article",
    ) == BingUrlInformation(
        url="https://example.com/article",
        anchor_count=3,
        discovery_date=date(2026, 7, 1),
        document_size=100,
        http_status=200,
        is_page=True,
        last_crawled_date=date(1970, 1, 1),
        total_child_url_count=2,
    )


@pytest.mark.asyncio
async def test_url_information_maps_bings_documented_zero_status_to_none(
    tmp_path: Path,
) -> None:
    payload = {
        "d": {
            "AnchorCount": 3,
            "DiscoveryDate": "2026-07-01",
            "DocumentSize": 100,
            "HttpStatus": 0,
            "IsPage": False,
            "LastCrawledDate": "/Date(0+0000)/",
            "TotalChildUrlCount": 2,
            "Url": "https://example.com/article",
        }
    }
    client = BingWebmasterClient(
        _policy(_key_file(tmp_path)),
        transport_factory=lambda: httpx.MockTransport(lambda _: httpx.Response(200, json=payload)),
    )

    information = await client.read_url_information(
        _request(),
        "https://example.com/",
        "https://example.com/article",
    )

    assert information.http_status is None
    assert information.is_page is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    (
        {},
        {
            "AnchorCount": -1,
            "DiscoveryDate": "2026-07-01",
            "DocumentSize": 100,
            "HttpStatus": 200,
            "IsPage": True,
            "LastCrawledDate": "2026-07-02",
            "TotalChildUrlCount": 2,
            "Url": "https://example.com/article",
        },
        {
            "AnchorCount": 1,
            "DiscoveryDate": "not-a-date",
            "DocumentSize": 100,
            "HttpStatus": 200,
            "IsPage": 1,
            "LastCrawledDate": "2026-07-02",
            "TotalChildUrlCount": 2,
            "Url": "https://example.com/article",
        },
        {
            "AnchorCount": 1,
            "DiscoveryDate": "2026-07-01",
            "DocumentSize": 100,
            "HttpStatus": 99,
            "IsPage": True,
            "LastCrawledDate": "2026-07-02",
            "TotalChildUrlCount": 2,
            "Url": "https://example.com/article",
        },
        {
            "AnchorCount": 1,
            "DiscoveryDate": "2026-07-01",
            "DocumentSize": 100,
            "HttpStatus": 600,
            "IsPage": True,
            "LastCrawledDate": "2026-07-02",
            "TotalChildUrlCount": 2,
            "Url": "https://example.com/article",
        },
        {
            "AnchorCount": 1,
            "DiscoveryDate": "2026-07-01",
            "DocumentSize": 100,
            "HttpStatus": 200,
            "IsPage": True,
            "LastCrawledDate": "2026-07-02",
            "TotalChildUrlCount": 2,
            "Url": "",
        },
        {
            "AnchorCount": 1,
            "DiscoveryDate": "2026-07-01",
            "DocumentSize": 100,
            "HttpStatus": 200,
            "IsPage": True,
            "LastCrawledDate": "2026-07-02",
            "TotalChildUrlCount": 2,
            "Url": "https://example.com/other",
        },
        {
            "AnchorCount": 1,
            "DiscoveryDate": "2026-07-01",
            "DocumentSize": 100,
            "HttpStatus": 200,
            "IsPage": True,
            "LastCrawledDate": "2026-07-02",
            "TotalChildUrlCount": 2,
            "Url": "https://other.example/article",
        },
    ),
)
async def test_url_information_rejects_malformed_or_mismatched_payloads(
    tmp_path: Path,
    payload: object,
) -> None:
    client = BingWebmasterClient(
        _policy(_key_file(tmp_path)),
        transport_factory=lambda: httpx.MockTransport(lambda _: httpx.Response(200, json=payload)),
    )

    with pytest.raises(ProviderOperationError) as error:
        await client.read_url_information(
            _request(),
            "https://example.com/",
            "https://example.com/article",
        )

    assert error.value.code is ProviderFailureCode.INVALID_RESPONSE


@pytest.mark.asyncio
async def test_url_information_rejects_unconfigured_url_before_key_or_network(
    tmp_path: Path,
) -> None:
    client = BingWebmasterClient(
        _policy(tmp_path / "missing-key"),
        transport_factory=lambda: pytest.fail("network must not be reached"),
    )

    with pytest.raises(BoundaryDeniedError):
        await client.read_url_information(
            _request(),
            "https://example.com/",
            "https://other.example/article",
        )
