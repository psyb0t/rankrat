from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import httpx
import pytest
from pydantic import BaseModel, ValidationError

from rankrat.constants import MAX_PROVIDER_ITEMS
from rankrat.errors import BoundaryDeniedError
from rankrat.models.boundaries import BoundaryDocument, Provider
from rankrat.policy.boundaries import BoundaryPolicy
from rankrat.providers import google_search_console as google_search_console
from rankrat.providers.base import (
    AccountId,
    ProviderFailureCode,
    ProviderOperationError,
    ProviderReadRequest,
)
from rankrat.providers.google_oauth import GoogleOAuthTokenRecord
from rankrat.providers.google_search_console import (
    GoogleSearchConsoleClient,
    SearchAnalyticsAggregationType,
    SearchAnalyticsQuery,
    SearchAnalyticsReport,
    SearchAnalyticsRow,
    SearchConsoleIndexStatus,
    SearchConsolePermissionLevel,
    SearchConsoleSite,
    SearchConsoleSitemap,
    SearchConsoleSitemapContent,
    SearchConsoleSitemapContentType,
    SearchConsoleSitemapList,
    SearchConsoleSitemapType,
    SearchConsoleUrlInspection,
)


async def _token(credential_path: Path) -> str:
    del credential_path
    return "test-token"


def _policy(provider: Provider = Provider.GOOGLE) -> BoundaryPolicy:
    account: dict[str, object] = {
        "id": "google-main" if provider is Provider.GOOGLE else "bing-main",
        "provider": provider,
        "credential": "/run/secrets/test.json",
    }
    if provider is Provider.GOOGLE:
        account["search_console_sites"] = ["https://example.com/"]
    else:
        account["sites"] = ["https://example.com/"]
    return BoundaryPolicy(BoundaryDocument.model_validate({"accounts": [account]}))


def _search_analytics_query() -> SearchAnalyticsQuery:
    return SearchAnalyticsQuery("2026-07-01", "2026-07-02", (), "web", 1, 0, ())


_MALFORMED_SEARCH_ANALYTICS_PAYLOADS = cast(
    tuple[object, ...],
    (
        {"rows": [{}]},
        {
            "rows": [
                {"keys": ["example"], "clicks": True, "impressions": 1, "ctr": 0.1, "position": 1}
            ]
        },
        {"rows": [{"keys": ["example"], "clicks": 1, "impressions": 1, "ctr": 1.1, "position": 1}]},
        {
            "rows": [
                {"keys": ["example"], "clicks": 1, "impressions": 1, "ctr": 0.1, "position": -1}
            ]
        },
        {"rows": [{"keys": [], "clicks": 1, "impressions": 1, "ctr": 0.1, "position": 1}]},
        {
            "rows": [
                {"keys": ["one", "two"], "clicks": 1, "impressions": 1, "ctr": 0.1, "position": 1}
            ]
        },
        {
            "rows": [
                {"keys": ["example"], "clicks": 1, "impressions": 1, "ctr": 0.1, "position": 1}
            ]
            * 2
        },
        {"rows": [], "responseAggregationType": "unexpected"},
    ),
)


@pytest.mark.asyncio
async def test_list_sites_uses_fixed_origin_and_returns_account_inventory() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == httpx.URL("https://www.googleapis.com/webmasters/v3/sites")
        assert request.headers["Authorization"] == "Bearer test-token"
        return httpx.Response(
            200,
            json={
                "siteEntry": [
                    {
                        "siteUrl": "https://example.com/",
                        "permissionLevel": "siteOwner",
                    },
                    {
                        "siteUrl": "https://unconfigured.example/",
                        "permissionLevel": "siteFullUser",
                    },
                ]
            },
        )

    client = GoogleSearchConsoleClient(
        _policy(),
        _token,
        transport_factory=lambda: httpx.MockTransport(handler),
    )

    sites = await client.list_sites(
        ProviderReadRequest(AccountId("google-main"), timeout_seconds=1.0)
    )

    assert sites == ("https://example.com/", "https://unconfigured.example/")


@pytest.mark.asyncio
async def test_account_scoped_google_credential_allows_reachable_reads_and_writes() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path.endswith("/sites"):
            return httpx.Response(
                200,
                json={
                    "siteEntry": [
                        {
                            "siteUrl": "https://example.com/",
                            "permissionLevel": "siteOwner",
                        },
                        {
                            "siteUrl": "https://other.example/",
                            "permissionLevel": "siteFullUser",
                        },
                    ]
                },
            )
        if request.method == "POST":
            return httpx.Response(200, json={"rows": []})
        if request.method == "PUT":
            return httpx.Response(204)
        pytest.fail(f"unexpected Google request: {request.method} {request.url}")

    client = GoogleSearchConsoleClient(
        _policy(),
        _token,
        transport_factory=lambda: httpx.MockTransport(handler),
    )
    request = ProviderReadRequest(AccountId("google-main"), timeout_seconds=1.0)

    assert await client.list_sites(request) == (
        "https://example.com/",
        "https://other.example/",
    )
    assert await client.search_analytics(
        request,
        "https://other.example/",
        _search_analytics_query(),
    ) == SearchAnalyticsReport((), None)
    await client.add_site(request, "https://other.example/")


@pytest.mark.asyncio
async def test_other_google_reads_use_fixed_origins_exact_property_and_safe_payloads() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/searchAnalytics/query"):
            return httpx.Response(200, json={"rows": []})
        if request.url.path.endswith("/sitemaps"):
            return httpx.Response(
                200,
                json={
                    "sitemap": [
                        {
                            "path": "https://example.com/sitemap.xml",
                            "type": "sitemap",
                            "warnings": "0",
                            "errors": "0",
                            "contents": [{"type": "web", "submitted": "3", "indexed": "2"}],
                        }
                    ]
                },
            )
        if "/sitemaps/" in request.url.path:
            return httpx.Response(
                200,
                json={
                    "path": "https://example.com/sitemap.xml",
                    "isPending": False,
                    "isSitemapsIndex": False,
                    "type": "sitemap",
                },
            )
        if request.url == httpx.URL(
            "https://searchconsole.googleapis.com/v1/urlInspection/index:inspect"
        ):
            return httpx.Response(
                200,
                json={
                    "inspectionResult": {
                        "inspectionResultLink": "https://search.google.com/search-console/inspect",
                        "indexStatusResult": {
                            "verdict": "PASS",
                            "coverageState": "Submitted and indexed",
                            "referringUrls": ["https://example.com/"],
                            "sitemap": ["https://example.com/sitemap.xml"],
                        },
                    }
                },
            )
        return httpx.Response(
            200,
            json={"siteUrl": "https://example.com/", "permissionLevel": "siteOwner"},
        )

    client = GoogleSearchConsoleClient(
        _policy(),
        _token,
        transport_factory=lambda: httpx.MockTransport(handler),
    )
    provider_request = ProviderReadRequest(AccountId("google-main"), timeout_seconds=1.0)
    analytics = await client.search_analytics(
        provider_request,
        "https://example.com/",
        SearchAnalyticsQuery(
            "2026-07-01",
            "2026-07-02",
            (),
            "web",
            1,
            0,
            (),
        ),
    )
    site = await client.get_site(provider_request, "https://example.com/")
    sitemaps = await client.list_sitemaps(provider_request, "https://example.com/")
    sitemap = await client.get_sitemap(
        provider_request,
        "https://example.com/",
        "https://example.com/sitemap.xml",
    )
    inspection = await client.inspect_url(
        provider_request,
        "https://example.com/",
        "https://example.com/post",
    )

    assert analytics == SearchAnalyticsReport((), None)
    assert site == SearchConsoleSite("https://example.com/", SearchConsolePermissionLevel.OWNER)
    assert sitemaps == SearchConsoleSitemapList(
        (
            SearchConsoleSitemap(
                path="https://example.com/sitemap.xml",
                last_submitted=None,
                is_pending=None,
                is_sitemaps_index=None,
                sitemap_type=SearchConsoleSitemapType.SITEMAP,
                last_downloaded=None,
                warnings=0,
                errors=0,
                contents=(
                    SearchConsoleSitemapContent(
                        SearchConsoleSitemapContentType.WEB,
                        3,
                        2,
                    ),
                ),
            ),
        )
    )
    assert sitemap == SearchConsoleSitemap(
        path="https://example.com/sitemap.xml",
        last_submitted=None,
        is_pending=False,
        is_sitemaps_index=False,
        sitemap_type=SearchConsoleSitemapType.SITEMAP,
        last_downloaded=None,
        warnings=None,
        errors=None,
        contents=(),
    )
    assert inspection == SearchConsoleUrlInspection(
        inspection_result_link="https://search.google.com/search-console/inspect",
        index_status=SearchConsoleIndexStatus(
            verdict="PASS",
            coverage_state="Submitted and indexed",
            robots_txt_state=None,
            indexing_state=None,
            last_crawl_time=None,
            page_fetch_state=None,
            google_canonical=None,
            user_canonical=None,
            crawled_as=None,
            referring_urls=("https://example.com/",),
            sitemaps=("https://example.com/sitemap.xml",),
        ),
    )
    assert [request.method for request in requests] == ["POST", "GET", "GET", "GET", "POST"]
    assert [str(request.url) for request in requests] == [
        "https://www.googleapis.com/webmasters/v3/sites/https%3A%2F%2Fexample.com%2F/searchAnalytics/query",
        "https://www.googleapis.com/webmasters/v3/sites/https%3A%2F%2Fexample.com%2F",
        "https://www.googleapis.com/webmasters/v3/sites/https%3A%2F%2Fexample.com%2F/sitemaps",
        "https://www.googleapis.com/webmasters/v3/sites/https%3A%2F%2Fexample.com%2F/"
        "sitemaps/https%3A%2F%2Fexample.com%2Fsitemap.xml",
        "https://searchconsole.googleapis.com/v1/urlInspection/index:inspect",
    ]
    assert all(request.headers["Authorization"] == "Bearer test-token" for request in requests)
    assert json.loads(requests[0].content) == {
        "startDate": "2026-07-01",
        "endDate": "2026-07-02",
        "dimensions": [],
        "type": "web",
        "rowLimit": 1,
        "startRow": 0,
    }
    assert json.loads(requests[4].content) == {
        "inspectionUrl": "https://example.com/post",
        "siteUrl": "https://example.com/",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("operation", "payload"),
    (
        (
            "site",
            {"siteUrl": "https://example.com/", "permissionLevel": "unexpected"},
        ),
        (
            "sitemaps",
            {"sitemap": [{"path": "https://example.invalid/sitemap.xml"}]},
        ),
        (
            "inspection",
            {"inspectionResult": {"indexStatusResult": {"referringUrls": [""]}}},
        ),
    ),
)
async def test_typed_google_reads_reject_malformed_upstream_payloads(
    operation: str,
    payload: object,
) -> None:
    client = GoogleSearchConsoleClient(
        _policy(),
        _token,
        transport_factory=lambda: httpx.MockTransport(lambda _: httpx.Response(200, json=payload)),
    )
    request = ProviderReadRequest(AccountId("google-main"), timeout_seconds=1.0)

    with pytest.raises(ProviderOperationError) as error:
        if operation == "sitemaps":
            await client.list_sitemaps(request, "https://example.com/")
        elif operation == "inspection":
            await client.inspect_url(request, "https://example.com/", "https://example.com/post")
        else:
            await client.get_site(request, "https://example.com/")

    assert error.value.code is ProviderFailureCode.INVALID_RESPONSE


@pytest.mark.asyncio
async def test_search_analytics_parses_strict_typed_header_aligned_rows() -> None:
    client = GoogleSearchConsoleClient(
        _policy(),
        _token,
        transport_factory=lambda: httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json={
                    "rows": [
                        {
                            "keys": ["example"],
                            "clicks": 3,
                            "impressions": 12,
                            "ctr": 0.25,
                            "position": 4.5,
                        }
                    ],
                    "responseAggregationType": "byProperty",
                    "metadata": {"ignored": True},
                },
            )
        ),
    )

    assert await client.search_analytics(
        ProviderReadRequest(AccountId("google-main"), timeout_seconds=1.0),
        "https://example.com/",
        SearchAnalyticsQuery("2026-07-01", "2026-07-02", ("query",), "web", 1, 0, ()),
    ) == SearchAnalyticsReport(
        (SearchAnalyticsRow(("example",), 3.0, 12.0, 0.25, 4.5),),
        SearchAnalyticsAggregationType.BY_PROPERTY,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", _MALFORMED_SEARCH_ANALYTICS_PAYLOADS)
async def test_search_analytics_rejects_malformed_upstream_reports(payload: object) -> None:
    client = GoogleSearchConsoleClient(
        _policy(),
        _token,
        transport_factory=lambda: httpx.MockTransport(lambda _: httpx.Response(200, json=payload)),
    )

    with pytest.raises(ProviderOperationError) as error:
        await client.search_analytics(
            ProviderReadRequest(AccountId("google-main"), timeout_seconds=1.0),
            "https://example.com/",
            SearchAnalyticsQuery("2026-07-01", "2026-07-02", ("query",), "web", 1, 0, ()),
        )

    assert error.value.code is ProviderFailureCode.INVALID_RESPONSE


def test_search_console_private_models_reject_invalid_provider_types_and_duplicates() -> None:
    query = SearchAnalyticsQuery(
        "2026-07-01",
        "2026-07-02",
        ("query",),
        "web",
        1,
        0,
        (("query", "contains", "rankrat"),),
    )
    assert query.as_payload()["dimensionFilterGroups"] == [
        {
            "groupType": "and",
            "filters": [{"dimension": "query", "operator": "contains", "expression": "rankrat"}],
        }
    ]
    invalid_models: tuple[tuple[type[BaseModel], object], ...] = (
        (
            google_search_console._SearchAnalyticsRowResponse,
            {"keys": [""], "clicks": 1, "impressions": 1, "ctr": 0.1, "position": 1},
        ),
        (google_search_console._SearchAnalyticsResponse, {"responseAggregationType": 1}),
        (
            google_search_console._SearchConsoleSiteResponse,
            {"siteUrl": "https://example.com/", "permissionLevel": 1},
        ),
        (google_search_console._SearchConsoleSitemapContentResponse, {"type": 1}),
        (google_search_console._SearchConsoleSitemapContentResponse, {"type": "unexpected"}),
        (
            google_search_console._SearchConsoleSitemapResponse,
            {"path": "https://example.com/sitemap.xml", "type": 1},
        ),
        (
            google_search_console._SearchConsoleSitemapResponse,
            {"path": "https://example.com/sitemap.xml", "type": "unexpected"},
        ),
    )
    for model, payload in invalid_models:
        with pytest.raises(ValidationError):
            model.model_validate(payload)
    assert google_search_console._SearchAnalyticsResponse.validate_aggregation_type(None) is None
    assert google_search_console._SearchConsoleSitemapResponse.validate_sitemap_type(None) is None

    with pytest.raises(ProviderOperationError, match="invalid Search Analytics report"):
        google_search_console._search_analytics_report(
            {
                "rows": [
                    {"keys": ["one"], "clicks": 1, "impressions": 1, "ctr": 0.1, "position": 1},
                    {"keys": ["one"], "clicks": 2, "impressions": 2, "ctr": 0.2, "position": 2},
                ]
            },
            SearchAnalyticsQuery("2026-07-01", "2026-07-02", ("query",), "web", 2, 0, ()),
        )
    with pytest.raises(ProviderOperationError, match="invalid site list"):
        google_search_console._search_console_site_list(
            {
                "siteEntry": [
                    {"siteUrl": "https://example.com/", "permissionLevel": "siteOwner"},
                    {"siteUrl": "https://example.com/", "permissionLevel": "siteFullUser"},
                ]
            }
        )


def test_sitemap_long_counters_accept_google_wire_format_and_reject_invalid_values() -> None:
    maximum = str(google_search_console._GOOGLE_API_INT64_MAX)
    sitemap = google_search_console._SearchConsoleSitemapResponse.model_validate(
        {
            "path": "https://example.com/sitemap.xml",
            "warnings": maximum,
            "errors": "0",
        }
    )
    content = google_search_console._SearchConsoleSitemapContentResponse.model_validate(
        {"type": "web", "submitted": maximum, "indexed": "0"}
    )

    assert sitemap.warnings == google_search_console._GOOGLE_API_INT64_MAX
    assert sitemap.errors == 0
    assert content.submitted == google_search_console._GOOGLE_API_INT64_MAX
    assert content.indexed == 0
    assert google_search_console._parse_google_sitemap_counter(None) is None

    invalid_counters: tuple[object, ...] = (
        True,
        1.0,
        -1,
        "",
        " 1",
        "+1",
        "-1",
        "01",
        "1.0",
        "١",
        google_search_console._GOOGLE_API_INT64_MAX + 1,
        str(google_search_console._GOOGLE_API_INT64_MAX + 1),
    )
    for counter in invalid_counters:
        with pytest.raises(ValidationError):
            google_search_console._SearchConsoleSitemapResponse.model_validate(
                {"path": "https://example.com/sitemap.xml", "warnings": counter, "errors": counter}
            )
        with pytest.raises(ValidationError):
            google_search_console._SearchConsoleSitemapContentResponse.model_validate(
                {"type": "web", "submitted": counter, "indexed": counter}
            )
    assert google_search_console._search_console_url_inspection(
        {"inspectionResult": {"inspectionResultLink": "https://example.com/inspection"}}
    ) == SearchConsoleUrlInspection("https://example.com/inspection", None)


def test_configured_google_token_provider_requires_nonempty_scopes() -> None:
    with pytest.raises(ValueError, match="at least one"):
        google_search_console.GoogleConfiguredTokenProvider(_policy(), ())


@pytest.mark.asyncio
async def test_configured_google_token_provider_rejects_missing_token_path_and_persists_rotation(
    tmp_path: Path,
) -> None:
    client_file = tmp_path / "client.json"
    client_file.write_text(
        '{"installed":{"client_id":"client-id.example.apps.googleusercontent.com"}}',
        encoding="utf-8",
    )
    token_root = tmp_path / "oauth"
    token_root.mkdir(mode=0o700)
    account = BoundaryDocument.model_validate(
        {
            "accounts": [
                {
                    "id": "google-main",
                    "provider": "google",
                    "credential": str(client_file),
                    "oauth_token_file": str(token_root / "token.json"),
                }
            ]
        }
    ).accounts[0]

    class Policy:
        def __init__(self, resolved_account: object) -> None:
            self.account = resolved_account

        def resolve_google_oauth_account(self, _: Path) -> object:
            return self.account

    no_token_provider = google_search_console.GoogleConfiguredTokenProvider(
        cast(BoundaryPolicy, Policy(account.model_copy(update={"oauth_token_file": None}))),
        ("https://www.googleapis.com/auth/webmasters.readonly",),
    )
    with pytest.raises(ProviderOperationError, match="missing a refresh token"):
        await no_token_provider(client_file)

    record = GoogleOAuthTokenRecord(
        "google-main",
        "client-id.example.apps.googleusercontent.com",
        "old-refresh-token",
        ("https://www.googleapis.com/auth/webmasters.readonly",),
    )
    store = google_search_console.GoogleOAuthTokenStore(
        token_root / "token.json",
        record.account_id,
        record.client_id,
        record.scopes,
    )
    store.write(record)

    class OAuthClient:
        async def refresh(
            self,
            _: object,
            current_record: object,
        ) -> tuple[str, object]:
            assert current_record == record
            return (
                "access-token",
                GoogleOAuthTokenRecord(
                    "google-main",
                    "client-id.example.apps.googleusercontent.com",
                    "rotated-refresh-token",
                    ("https://www.googleapis.com/auth/webmasters.readonly",),
                ),
            )

    rotating_provider = google_search_console.GoogleConfiguredTokenProvider(
        cast(BoundaryPolicy, Policy(account)),
        record.scopes,
        oauth_token_client=cast(google_search_console.GoogleOAuthTokenClient, OAuthClient()),
    )
    assert await rotating_provider(client_file) == "access-token"
    assert store.load().refresh_token == "rotated-refresh-token"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("operation", "payload", "expected_message"),
    (
        (
            "site",
            {"siteUrl": "https://example.com/other", "permissionLevel": "siteOwner"},
            "mismatched site",
        ),
        (
            "sitemap",
            {"path": "https://example.com/other.xml"},
            "mismatched sitemap",
        ),
        (
            "sitemaps",
            {"sitemap": [{"path": "https://example.com/other.xml", "type": "unexpected"}]},
            "invalid sitemap list",
        ),
    ),
)
async def test_search_console_rejects_mismatched_or_invalid_typed_resources(
    operation: str,
    payload: object,
    expected_message: str,
) -> None:
    client = GoogleSearchConsoleClient(
        _policy(),
        _token,
        transport_factory=lambda: httpx.MockTransport(lambda _: httpx.Response(200, json=payload)),
    )
    request = ProviderReadRequest(AccountId("google-main"), timeout_seconds=1.0)
    with pytest.raises(ProviderOperationError, match=expected_message):
        if operation == "site":
            await client.get_site(request, "https://example.com/")
        elif operation == "sitemap":
            await client.get_sitemap(
                request,
                "https://example.com/",
                "https://example.com/sitemap.xml",
            )
        else:
            await client.list_sitemaps(request, "https://example.com/")


@pytest.mark.asyncio
async def test_account_scoped_google_reads_accept_unlisted_property() -> None:
    called = False

    async def token(credential_path: Path) -> str:
        del credential_path
        nonlocal called
        called = True
        return "test-token"

    client = GoogleSearchConsoleClient(
        _policy(),
        token,
        transport_factory=lambda: httpx.MockTransport(
            lambda _: httpx.Response(200, json={"rows": []})
        ),
    )
    request = ProviderReadRequest(AccountId("google-main"), timeout_seconds=1.0)
    assert await client.search_analytics(
        request,
        "https://other.example/",
        _search_analytics_query(),
    ) == SearchAnalyticsReport((), None)
    assert called is True


@pytest.mark.asyncio
async def test_other_google_reads_safely_wrap_unexpected_token_provider_errors() -> None:
    async def token(credential_path: Path) -> str:
        del credential_path
        raise RuntimeError("private token failure")

    client = GoogleSearchConsoleClient(_policy(), token)
    with pytest.raises(ProviderOperationError) as error:
        await client.search_analytics(
            ProviderReadRequest(AccountId("google-main"), timeout_seconds=1.0),
            "https://example.com/",
            _search_analytics_query(),
        )
    assert error.value.code is ProviderFailureCode.AUTHENTICATION
    assert "private" not in str(error.value)

    async def expected_error(credential_path: Path) -> str:
        del credential_path
        raise ProviderOperationError(ProviderFailureCode.FORBIDDEN, "safe failure")

    with pytest.raises(ProviderOperationError) as expected:
        await GoogleSearchConsoleClient(_policy(), expected_error).search_analytics(
            ProviderReadRequest(AccountId("google-main"), timeout_seconds=1.0),
            "https://example.com/",
            _search_analytics_query(),
        )
    assert expected.value.code is ProviderFailureCode.FORBIDDEN


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "expected_code"),
    [
        (401, ProviderFailureCode.AUTHENTICATION),
        (403, ProviderFailureCode.FORBIDDEN),
        (429, ProviderFailureCode.RATE_LIMITED),
        (500, ProviderFailureCode.UNAVAILABLE),
    ],
)
async def test_list_sites_maps_safe_upstream_failures(
    status_code: int,
    expected_code: ProviderFailureCode,
) -> None:
    client = GoogleSearchConsoleClient(
        _policy(),
        _token,
        transport_factory=lambda: httpx.MockTransport(
            lambda _: httpx.Response(status_code, text="untrusted upstream body")
        ),
    )

    with pytest.raises(ProviderOperationError) as error:
        await client.list_sites(ProviderReadRequest(AccountId("google-main"), timeout_seconds=1.0))

    assert error.value.code is expected_code
    assert "untrusted" not in str(error.value)


@pytest.mark.asyncio
async def test_list_sites_rejects_cross_provider_before_token_or_network() -> None:
    called = False

    async def token(credential_path: Path) -> str:
        del credential_path
        nonlocal called
        called = True
        return "test-token"

    client = GoogleSearchConsoleClient(
        _policy(Provider.BING),
        token,
        transport_factory=lambda: pytest.fail("network must not be reached"),
    )

    with pytest.raises(BoundaryDeniedError):
        await client.list_sites(ProviderReadRequest(AccountId("bing-main"), timeout_seconds=1.0))

    assert called is False


@pytest.mark.asyncio
async def test_readiness_and_empty_site_list() -> None:
    client = GoogleSearchConsoleClient(
        _policy(),
        _token,
        transport_factory=lambda: httpx.MockTransport(lambda _: httpx.Response(200, json={})),
    )
    readiness = await client.readiness(
        ProviderReadRequest(AccountId("google-main"), timeout_seconds=1.0)
    )
    assert readiness.available is True
    assert (
        await client.list_sites(ProviderReadRequest(AccountId("google-main"), timeout_seconds=1.0))
        == ()
    )


_MALFORMED_PAYLOADS: tuple[object, ...] = (
    list[object](),
    dict[str, object](siteEntry="not-a-list"),
    dict[str, object](siteEntry=["not-an-object"]),
    dict[str, object](siteEntry=[dict[str, object]()]),
    dict[str, object](siteEntry=[dict[str, object](siteUrl=1)]),
    dict[str, object](
        siteEntry=[dict[str, object](siteUrl="https://example.com/")] * (MAX_PROVIDER_ITEMS + 1)
    ),
)


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", _MALFORMED_PAYLOADS)
async def test_list_sites_rejects_malformed_payloads(payload: object) -> None:
    client = GoogleSearchConsoleClient(
        _policy(),
        _token,
        transport_factory=lambda: httpx.MockTransport(lambda _: httpx.Response(200, json=payload)),
    )
    with pytest.raises(ProviderOperationError) as error:
        await client.list_sites(ProviderReadRequest(AccountId("google-main"), timeout_seconds=1.0))
    assert error.value.code is ProviderFailureCode.INVALID_RESPONSE


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [301, 400])
async def test_list_sites_rejects_unexpected_status(status_code: int) -> None:
    client = GoogleSearchConsoleClient(
        _policy(),
        _token,
        transport_factory=lambda: httpx.MockTransport(lambda _: httpx.Response(status_code)),
    )
    with pytest.raises(ProviderOperationError) as error:
        await client.list_sites(ProviderReadRequest(AccountId("google-main"), timeout_seconds=1.0))
    assert error.value.code is ProviderFailureCode.INVALID_RESPONSE


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("upstream_error", "expected_code"),
    [
        (httpx.ReadTimeout("timeout"), ProviderFailureCode.TIMEOUT),
        (httpx.ConnectError("offline"), ProviderFailureCode.UNAVAILABLE),
    ],
)
async def test_list_sites_maps_transport_errors(
    upstream_error: httpx.HTTPError,
    expected_code: ProviderFailureCode,
) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        raise upstream_error

    client = GoogleSearchConsoleClient(
        _policy(),
        _token,
        transport_factory=lambda: httpx.MockTransport(handler),
    )
    with pytest.raises(ProviderOperationError) as error:
        await client.list_sites(ProviderReadRequest(AccountId("google-main"), timeout_seconds=1.0))
    assert error.value.code is expected_code
    assert "offline" not in str(error.value)


@pytest.mark.asyncio
async def test_list_sites_rejects_invalid_json_and_response_size() -> None:
    responses = iter(
        (
            httpx.Response(200, content=b"not-json"),
            httpx.Response(200, headers={"content-length": "2097153"}),
            httpx.Response(
                200,
                headers={"content-length": "unknown"},
                content=b"x" * 2_097_153,
            ),
        )
    )
    client = GoogleSearchConsoleClient(
        _policy(),
        _token,
        transport_factory=lambda: httpx.MockTransport(lambda _: next(responses)),
    )
    for _ in range(3):
        with pytest.raises(ProviderOperationError) as error:
            await client.list_sites(
                ProviderReadRequest(AccountId("google-main"), timeout_seconds=1.0)
            )
        assert error.value.code is ProviderFailureCode.INVALID_RESPONSE


@pytest.mark.asyncio
async def test_token_provider_errors_are_safely_wrapped() -> None:
    async def unexpected(credential_path: Path) -> str:
        del credential_path
        raise RuntimeError("private provider detail")

    async def expected(credential_path: Path) -> str:
        del credential_path
        raise ProviderOperationError(ProviderFailureCode.AUTHENTICATION, "safe")

    for provider, expected_message in ((unexpected, "authentication failed"), (expected, "safe")):
        client = GoogleSearchConsoleClient(_policy(), provider)
        with pytest.raises(ProviderOperationError) as error:
            await client.list_sites(
                ProviderReadRequest(AccountId("google-main"), timeout_seconds=1.0)
            )
        assert expected_message in str(error.value)
