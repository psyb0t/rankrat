from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from rankrat.models.boundaries import BoundaryDocument
from rankrat.policy.boundaries import BoundaryPolicy
from rankrat.providers.base import (
    AccountId,
    ProviderFailureCode,
    ProviderOperationError,
    ProviderReadRequest,
)
from rankrat.providers.google_analytics_admin import (
    Ga4SiteProperty,
    Ga4SitePropertyCreateRequest,
    GoogleAnalyticsAdminClient,
)


async def _token(_: Path) -> str:
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
                    }
                ]
            }
        )
    )


def _request() -> Ga4SitePropertyCreateRequest:
    return Ga4SitePropertyCreateRequest(
        account_id="google-main",
        parent_account_id="123",
        display_name="Example",
        site_url="https://example.com/",
        time_zone="Etc/UTC",
        currency_code="USD",
    )


@pytest.mark.asyncio
async def test_create_site_property_uses_fixed_origins_and_validates_each_response() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/properties"):
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

    client = GoogleAnalyticsAdminClient(
        _policy(),
        _token,
        transport_factory=lambda: httpx.MockTransport(handler),
    )

    result = await client.create_site_property(
        ProviderReadRequest(AccountId("google-main"), 1.0),
        _request(),
    )

    assert result == Ga4SiteProperty("456", "G-ABC123")
    assert [str(request.url) for request in requests] == [
        "https://analyticsadmin.googleapis.com/v1beta/properties",
        "https://analyticsadmin.googleapis.com/v1beta/properties/456/dataStreams",
    ]
    assert all(request.headers["Authorization"] == "Bearer test-token" for request in requests)
    assert json.loads(requests[0].content) == {
        "parent": "accounts/123",
        "displayName": "Example",
        "timeZone": "Etc/UTC",
        "currencyCode": "USD",
    }
    assert json.loads(requests[1].content) == {
        "displayName": "Example",
        "type": "WEB_DATA_STREAM",
        "webStreamData": {"defaultUri": "https://example.com/"},
    }


@pytest.mark.asyncio
async def test_create_site_property_rejects_mismatched_stream_response() -> None:
    responses = iter(
        (
            {
                "name": "properties/456",
                "parent": "accounts/123",
                "displayName": "Example",
                "timeZone": "Etc/UTC",
                "currencyCode": "USD",
            },
            {
                "name": "properties/456/dataStreams/789",
                "displayName": "Example",
                "type": "WEB_DATA_STREAM",
                "webStreamData": {
                    "defaultUri": "https://wrong.example/",
                    "measurementId": "G-ABC123",
                },
            },
        )
    )
    client = GoogleAnalyticsAdminClient(
        _policy(),
        _token,
        transport_factory=lambda: httpx.MockTransport(
            lambda _: httpx.Response(200, json=next(responses))
        ),
    )

    with pytest.raises(ProviderOperationError) as error:
        await client.create_site_property(
            ProviderReadRequest(AccountId("google-main"), 1.0), _request()
        )

    assert error.value.code is ProviderFailureCode.INVALID_RESPONSE
