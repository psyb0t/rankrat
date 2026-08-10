from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from rankrat.models.boundaries import Provider, ResourceKind
from rankrat.operator.site_onboarding import (
    SiteOnboardingOperator,
    SiteOnboardingPartialError,
    SiteOnboardingRequest,
)
from rankrat.policy.boundaries import BoundaryPolicy
from rankrat.providers.bing import BingWebmasterClient
from rankrat.providers.google_analytics import GoogleAnalyticsDataClient
from rankrat.providers.google_analytics_admin import GoogleAnalyticsAdminClient
from rankrat.providers.google_search_console import GoogleSearchConsoleClient


async def _token(_: Path) -> str:
    return "test-token"


def _operator(
    tmp_path: Path,
    handler: httpx.MockTransport,
) -> tuple[Path, SiteOnboardingOperator]:
    secret_root = tmp_path / "secrets"
    secret_root.mkdir()
    bing_key = secret_root / "bing-key"
    bing_key.write_text("test-bing-key", encoding="utf-8")
    boundary_file = tmp_path / "boundaries.json"
    boundary_file.write_text(
        json.dumps(
            {
                "accounts": [
                    {
                        "id": "google-main",
                        "provider": "google",
                        "credential": str(secret_root / "google-client.json"),
                        "oauth_token_file": str(tmp_path / "oauth" / "google.json"),
                    },
                    {
                        "id": "bing-main",
                        "provider": "bing",
                        "credential": str(bing_key),
                        "sites": [],
                    },
                ],
                "indexnow_targets": [],
            }
        ),
        encoding="utf-8",
    )
    oauth_root = tmp_path / "oauth"
    oauth_root.mkdir(mode=0o700)
    policy = BoundaryPolicy.from_file(
        boundary_file,
        secret_root,
        oauth_root,
    )
    return boundary_file, SiteOnboardingOperator(
        boundary_file,
        policy,
        GoogleAnalyticsAdminClient(policy, _token, lambda: handler),
        GoogleAnalyticsDataClient(policy, _token, lambda: handler),
        GoogleSearchConsoleClient(policy, _token, lambda: handler),
        BingWebmasterClient(policy, lambda: handler),
    )


@pytest.mark.asyncio
async def test_site_onboarding_creates_all_provider_resources_then_updates_boundary(
    tmp_path: Path,
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/accountSummaries"):
            return httpx.Response(
                200,
                json={
                    "accountSummaries": [
                        {
                            "name": "accountSummaries/123",
                            "account": "accounts/123",
                            "displayName": "Example account",
                        }
                    ]
                },
            )
        if request.url.host == "analyticsadmin.googleapis.com" and request.url.path.endswith(
            "/properties"
        ):
            return httpx.Response(
                200,
                json={
                    "name": "properties/456",
                    "parent": "accounts/123",
                    "displayName": "Example",
                    "timeZone": "Etc/UTC",
                    "currencyCode": "USD",
                },
            )
        if request.url.host == "analyticsadmin.googleapis.com":
            return httpx.Response(
                200,
                json={
                    "name": "properties/456/dataStreams/789",
                    "displayName": "Example",
                    "type": "WEB_DATA_STREAM",
                    "webStreamData": {
                        "defaultUri": "https://example.com/",
                        "measurementId": "G-ABC123",
                    },
                },
            )
        if request.url.host == "www.googleapis.com" and request.method == "GET":
            return httpx.Response(200, json={})
        if request.url.host == "www.googleapis.com":
            return httpx.Response(204)
        if request.url.path.endswith("/GetUserSites"):
            return httpx.Response(200, json=[])
        return httpx.Response(200, json={"d": None})

    boundary_file, operator = _operator(tmp_path, httpx.MockTransport(handler))
    receipt = await operator.onboard(
        SiteOnboardingRequest(
            "google-main",
            "bing-main",
            "https://example.com/",
            google_analytics_parent_account_id="123",
            display_name="Example",
        )
    )

    boundary = json.loads(boundary_file.read_text(encoding="utf-8"))
    assert receipt.ga4_property_id == "456"
    assert receipt.ga4_measurement_id == "G-ABC123"
    assert boundary["accounts"][0]["search_console_sites"] == ["https://example.com/"]
    assert boundary["accounts"][0]["ga4_properties"] == ["456"]
    assert boundary["accounts"][1]["sites"] == ["https://example.com/"]
    assert [request.url.host for request in requests] == [
        "analyticsadmin.googleapis.com",
        "analyticsadmin.googleapis.com",
        "analyticsadmin.googleapis.com",
        "www.googleapis.com",
        "www.googleapis.com",
        "ssl.bing.com",
        "ssl.bing.com",
    ]
    assert "apikey=test-bing-key" not in boundary_file.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_site_onboarding_reuses_existing_provider_resources_idempotently(
    tmp_path: Path,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/accountSummaries"):
            return httpx.Response(
                200,
                json={
                    "accountSummaries": [
                        {
                            "name": "accountSummaries/456",
                            "account": "accounts/456",
                            "displayName": "Example account",
                            "propertySummaries": [
                                {"property": "properties/456", "displayName": "example.com"}
                            ],
                        }
                    ]
                },
            )
        if request.url.path.endswith("/dataStreams"):
            return httpx.Response(
                200,
                json={
                    "dataStreams": [
                        {
                            "name": "properties/456/dataStreams/789",
                            "displayName": "example.com",
                            "type": "WEB_DATA_STREAM",
                            "webStreamData": {
                                "defaultUri": "https://example.com/",
                                "measurementId": "G-ABC123",
                            },
                        }
                    ]
                },
            )
        if request.url.host == "www.googleapis.com":
            return httpx.Response(
                200,
                json={
                    "siteEntry": [
                        {"siteUrl": "https://example.com/", "permissionLevel": "siteOwner"}
                    ]
                },
            )
        return httpx.Response(200, json=[{"Url": "https://example.com/"}])

    boundary_file, operator = _operator(tmp_path, httpx.MockTransport(handler))
    receipt = await operator.onboard(
        SiteOnboardingRequest(
            "google-main",
            "bing-main",
            "https://example.com/",
            google_analytics_parent_account_id="456",
        )
    )

    persisted_policy = BoundaryPolicy.from_file(
        boundary_file,
        tmp_path / "secrets",
        tmp_path / "oauth",
    )
    assert receipt.boundary_updated is True
    assert receipt.ga4_created is False
    assert receipt.google_search_console_added is False
    assert receipt.bing_added is False
    assert (
        persisted_policy.require_resource(
            "google-main",
            Provider.GOOGLE,
            ResourceKind.GA4_PROPERTY,
            "456",
        ).id
        == "google-main"
    )
    assert (
        persisted_policy.require_resource(
            "bing-main",
            Provider.BING,
            ResourceKind.BING_SITE,
            "https://example.com/",
        ).id
        == "bing-main"
    )


@pytest.mark.asyncio
async def test_site_onboarding_reports_partial_success_without_boundary_write(
    tmp_path: Path,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/accountSummaries"):
            return httpx.Response(
                200,
                json={
                    "accountSummaries": [
                        {
                            "name": "accountSummaries/123",
                            "account": "accounts/123",
                            "displayName": "Example account",
                        }
                    ]
                },
            )
        if request.url.host == "analyticsadmin.googleapis.com" and request.url.path.endswith(
            "/properties"
        ):
            return httpx.Response(
                200,
                json={
                    "name": "properties/456",
                    "parent": "accounts/123",
                    "displayName": "example.com",
                    "timeZone": "Etc/UTC",
                    "currencyCode": "USD",
                },
            )
        if request.url.host == "analyticsadmin.googleapis.com":
            return httpx.Response(
                200,
                json={
                    "name": "properties/456/dataStreams/789",
                    "displayName": "example.com",
                    "type": "WEB_DATA_STREAM",
                    "webStreamData": {
                        "defaultUri": "https://example.com/",
                        "measurementId": "G-ABC123",
                    },
                },
            )
        return httpx.Response(403)

    boundary_file, operator = _operator(tmp_path, httpx.MockTransport(handler))
    original_boundary = boundary_file.read_bytes()

    with pytest.raises(SiteOnboardingPartialError) as error:
        await operator.onboard(
            SiteOnboardingRequest(
                "google-main",
                "bing-main",
                "https://example.com/",
                google_analytics_parent_account_id="123",
            )
        )

    assert error.value.completed_stages == ("google_analytics",)
    assert boundary_file.read_bytes() == original_boundary
