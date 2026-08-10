from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from rankrat.errors import InputLimitError
from rankrat.models.boundaries import BoundaryDocument
from rankrat.policy.boundaries import BoundaryPolicy
from rankrat.providers.base import (
    AccountId,
    ProviderFailureCode,
    ProviderOperationError,
    ProviderReadRequest,
)
from rankrat.providers.google_analytics_admin import GoogleAnalyticsAdminClient

_ADMIN_ROOT = "https://analyticsadmin.googleapis.com/v1beta"
_PROPERTY_ID = "548269885"
_ANALYTICS_ACCOUNT_ID = "247964066"


def _policy(tmp_path: Path) -> BoundaryPolicy:
    secret_root = tmp_path / "secrets"
    secret_root.mkdir()
    credential = secret_root / "google.json"
    credential.write_text("{}", encoding="utf-8")
    document = BoundaryDocument.model_validate(
        {
            "accounts": [
                {
                    "id": "google-main",
                    "provider": "google",
                    "credential": str(credential),
                    "oauth_token_file": str(tmp_path / "token.json"),
                    "ga4_properties": [_PROPERTY_ID],
                },
                {
                    "id": "google-closed",
                    "provider": "google",
                    "credential": str(credential),
                    "ga4_properties": [],
                },
            ],
            "indexnow_targets": [],
        }
    )
    return BoundaryPolicy(document)


def _client(tmp_path: Path, handler: object) -> GoogleAnalyticsAdminClient:
    return GoogleAnalyticsAdminClient(
        _policy(tmp_path),
        lambda _: _token(),
        transport_factory=lambda: httpx.MockTransport(handler),  # type: ignore[arg-type]
    )


async def _token() -> str:
    return "test-token"


def _request(account_id: str = "google-main") -> ProviderReadRequest:
    return ProviderReadRequest(AccountId(account_id), 5.0)


@pytest.mark.asyncio
async def test_data_streams_returns_web_measurement_ids_and_tolerates_app_streams(
    tmp_path: Path,
) -> None:
    """App streams carry no webStreamData; the read must not choke on them."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert str(request.url).startswith(f"{_ADMIN_ROOT}/properties/{_PROPERTY_ID}/dataStreams")
        return httpx.Response(
            200,
            json={
                "dataStreams": [
                    {
                        "name": f"properties/{_PROPERTY_ID}/dataStreams/11",
                        "displayName": "Web",
                        "type": "WEB_DATA_STREAM",
                        "webStreamData": {
                            "defaultUri": "https://example.com",
                            "measurementId": "G-ABC123",
                        },
                    },
                    {
                        "name": f"properties/{_PROPERTY_ID}/dataStreams/22",
                        "displayName": "Android",
                        "type": "ANDROID_APP_DATA_STREAM",
                    },
                ]
            },
        )

    streams = await _client(tmp_path, handler).list_data_streams(_request(), _PROPERTY_ID)

    assert [stream.stream_id for stream in streams] == ["11", "22"]
    assert streams[0].measurement_id == "G-ABC123"
    assert streams[0].default_uri == "https://example.com"
    assert streams[1].measurement_id is None
    assert streams[1].default_uri is None


@pytest.mark.asyncio
async def test_data_streams_rejects_a_stream_belonging_to_another_property(
    tmp_path: Path,
) -> None:
    """A response naming a different property is not the resource that was authorized."""

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "dataStreams": [
                    {
                        "name": "properties/999/dataStreams/11",
                        "displayName": "Web",
                        "type": "WEB_DATA_STREAM",
                        "webStreamData": {
                            "defaultUri": "https://evil.example",
                            "measurementId": "G-ABC123",
                        },
                    }
                ]
            },
        )

    with pytest.raises(ProviderOperationError) as error:
        await _client(tmp_path, handler).list_data_streams(_request(), _PROPERTY_ID)
    assert error.value.code is ProviderFailureCode.INVALID_RESPONSE


@pytest.mark.asyncio
async def test_data_streams_accepts_an_unlisted_property_in_the_account(tmp_path: Path) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"dataStreams": []})

    assert await _client(tmp_path, handler).list_data_streams(_request(), "999") == ()


@pytest.mark.asyncio
async def test_account_rename_sends_a_patch_with_the_display_name_update_mask(
    tmp_path: Path,
) -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"name": f"accounts/{_ANALYTICS_ACCOUNT_ID}", "displayName": "psyb0t"},
        )

    renamed = await _client(tmp_path, handler).update_account_display_name(
        _request(),
        _ANALYTICS_ACCOUNT_ID,
        "psyb0t",
    )

    assert renamed.resource_id == _ANALYTICS_ACCOUNT_ID
    assert renamed.display_name == "psyb0t"
    assert seen["method"] == "PATCH"
    assert "updateMask=display_name" in str(seen["url"])
    assert seen["body"] == {"displayName": "psyb0t"}


@pytest.mark.asyncio
async def test_account_rename_rejects_a_response_naming_another_account(tmp_path: Path) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"name": "accounts/999", "displayName": "psyb0t"})

    with pytest.raises(ProviderOperationError) as error:
        await _client(tmp_path, handler).update_account_display_name(
            _request(),
            _ANALYTICS_ACCOUNT_ID,
            "psyb0t",
        )
    assert error.value.code is ProviderFailureCode.INVALID_RESPONSE


@pytest.mark.asyncio
async def test_account_rename_uses_any_configured_google_account(tmp_path: Path) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"name": f"accounts/{_ANALYTICS_ACCOUNT_ID}", "displayName": "psyb0t"},
        )

    renamed = await _client(tmp_path, handler).update_account_display_name(
        _request("google-closed"),
        _ANALYTICS_ACCOUNT_ID,
        "psyb0t",
    )
    assert renamed.resource_id == _ANALYTICS_ACCOUNT_ID


@pytest.mark.asyncio
async def test_account_rename_refuses_a_non_numeric_id_before_building_a_url(
    tmp_path: Path,
) -> None:
    """The ID is interpolated into an Admin API path, so it must be a bare numeric."""

    def handler(_: httpx.Request) -> httpx.Response:  # pragma: no cover - must not be reached
        raise AssertionError("the ID check must run before any request")

    with pytest.raises(InputLimitError):
        await _client(tmp_path, handler).update_account_display_name(
            _request(),
            "../../properties/999",
            "psyb0t",
        )


@pytest.mark.asyncio
async def test_property_rename_patches_the_configured_property(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "PATCH"
        assert f"{_ADMIN_ROOT}/properties/{_PROPERTY_ID}" in str(request.url)
        return httpx.Response(
            200,
            json={"name": f"properties/{_PROPERTY_ID}", "displayName": "example.com"},
        )

    renamed = await _client(tmp_path, handler).update_property_display_name(
        _request(),
        _PROPERTY_ID,
        "example.com",
    )

    assert renamed.resource_id == _PROPERTY_ID
    assert renamed.display_name == "example.com"


@pytest.mark.asyncio
async def test_property_rename_accepts_an_unlisted_property_in_the_account(
    tmp_path: Path,
) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"name": "properties/999", "displayName": "whatever"},
        )

    renamed = await _client(tmp_path, handler).update_property_display_name(
        _request(),
        "999",
        "whatever",
    )
    assert renamed.resource_id == "999"
