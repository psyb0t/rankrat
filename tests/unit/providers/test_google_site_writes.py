from __future__ import annotations

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
from rankrat.providers.google_search_console import GoogleSearchConsoleClient


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
                        "search_console_sites": ["sc-domain:example.com"],
                    }
                ]
            }
        )
    )


def _client(transport_factory: object) -> GoogleSearchConsoleClient:
    return GoogleSearchConsoleClient(_policy(), _token, transport_factory)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_site_writes_use_only_documented_fixed_empty_response_paths() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(204)

    client = _client(lambda: httpx.MockTransport(handler))
    request = ProviderReadRequest(AccountId("google-main"), 1.0)
    await client.add_site(request, "sc-domain:example.com")
    await client.delete_site(request, "sc-domain:example.com")

    assert [item.method for item in requests] == ["PUT", "DELETE"]
    assert [str(item.url) for item in requests] == [
        "https://www.googleapis.com/webmasters/v3/sites/sc-domain%3Aexample.com",
        "https://www.googleapis.com/webmasters/v3/sites/sc-domain%3Aexample.com",
    ]
    assert all(item.headers["Authorization"] == "Bearer test-token" for item in requests)
    assert all(item.content == b"" for item in requests)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    (httpx.Response(200), httpx.Response(204, content=b"body")),
)
async def test_site_writes_reject_non_empty_or_unexpected_success_responses(
    response: httpx.Response,
) -> None:
    client = _client(lambda: httpx.MockTransport(lambda _: response))
    with pytest.raises(ProviderOperationError) as error:
        await client.add_site(
            ProviderReadRequest(AccountId("google-main"), 1.0),
            "sc-domain:example.com",
        )
    assert error.value.code is ProviderFailureCode.INVALID_RESPONSE


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("upstream_error", "expected_code"),
    (
        (httpx.ReadTimeout("timeout"), ProviderFailureCode.TIMEOUT),
        (httpx.ConnectError("offline"), ProviderFailureCode.UNAVAILABLE),
    ),
)
async def test_site_writes_map_transport_errors(
    upstream_error: httpx.HTTPError,
    expected_code: ProviderFailureCode,
) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        raise upstream_error

    client = _client(lambda: httpx.MockTransport(handler))
    with pytest.raises(ProviderOperationError) as error:
        await client.delete_site(
            ProviderReadRequest(AccountId("google-main"), 1.0),
            "sc-domain:example.com",
        )
    assert error.value.code is expected_code


@pytest.mark.asyncio
async def test_site_writes_accept_any_property_reachable_by_the_configured_account() -> None:
    called = False
    requests: list[httpx.Request] = []

    async def token(credential_path: Path) -> str:
        del credential_path
        nonlocal called
        called = True
        return "test-token"

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(204)

    client = GoogleSearchConsoleClient(
        _policy(),
        token,
        transport_factory=lambda: httpx.MockTransport(handler),
    )
    await client.add_site(
        ProviderReadRequest(AccountId("google-main"), 1.0),
        "sc-domain:outside.example.com",
    )
    assert called is True
    assert str(requests[0].url).endswith("sc-domain%3Aoutside.example.com")
