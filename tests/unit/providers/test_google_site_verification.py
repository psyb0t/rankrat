from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from rankrat.constants import MAX_PROVIDER_RESPONSE_BYTES
from rankrat.models.boundaries import BoundaryDocument
from rankrat.policy.boundaries import BoundaryPolicy
from rankrat.providers.base import (
    AccountId,
    ProviderFailureCode,
    ProviderOperationError,
    ProviderReadRequest,
)
from rankrat.providers.google_site_verification import (
    GoogleSiteVerificationClient,
    GoogleVerificationMethod,
)


def _client(
    tmp_path: Path,
    handler: httpx.AsyncBaseTransport,
) -> GoogleSiteVerificationClient:
    credential = tmp_path / "oauth-client.json"
    policy = BoundaryPolicy(
        BoundaryDocument.model_validate(
            {
                "accounts": [
                    {
                        "id": "google-main",
                        "provider": "google",
                        "credential": str(credential),
                    }
                ]
            }
        )
    )

    async def token_provider(_: Path) -> str:
        return "safe-access-token"

    return GoogleSiteVerificationClient(
        policy,
        token_provider,
        transport_factory=lambda: handler,
    )


@pytest.mark.asyncio
async def test_google_site_verification_token_status_and_insert(tmp_path: Path) -> None:
    responses = iter(
        (
            httpx.Response(
                200,
                json={"method": "DNS_TXT", "token": "google-site-verification=value"},
            ),
            httpx.Response(200, json={"items": []}),
            httpx.Response(
                200,
                json={
                    "id": "inet-domain:example.com",
                    "site": {"identifier": "example.com", "type": "INET_DOMAIN"},
                },
            ),
        )
    )

    client = _client(tmp_path, httpx.MockTransport(lambda _: next(responses)))
    request = ProviderReadRequest(AccountId("google-main"), 1.0)
    token = await client.get_token(request, "example.com")
    assert token.token == "google-site-verification=value"
    assert await client.is_verified(request, "example.com") is False
    verified = await client.verify(request, "example.com")
    assert verified.domain == "example.com"


@pytest.mark.asyncio
async def test_google_site_verification_finds_only_exact_domain_resources(tmp_path: Path) -> None:
    client = _client(
        tmp_path,
        httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": "url-prefix",
                            "site": {"identifier": "example.com", "type": "SITE"},
                        },
                        {
                            "id": "other",
                            "site": {"identifier": "other.example", "type": "INET_DOMAIN"},
                        },
                        {
                            "id": "wanted",
                            "site": {"identifier": "EXAMPLE.com", "type": "INET_DOMAIN"},
                        },
                    ]
                },
            )
        ),
    )

    verified = await client.is_verified(
        ProviderReadRequest(AccountId("google-main"), 1.0),
        "example.com",
    )

    assert verified is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("operation", "payload", "message"),
    (
        (
            "token",
            {"method": "DNS_CNAME", "token": "value"},
            "different verification method",
        ),
        (
            "verify",
            {
                "id": "resource",
                "site": {"identifier": "example.com", "type": "SITE"},
            },
            "different resource type",
        ),
        (
            "verify",
            {
                "id": "resource",
                "site": {"identifier": "other.example", "type": "INET_DOMAIN"},
            },
            "different domain",
        ),
        ("status", {"items": "invalid"}, "invalid resource list"),
    ),
)
async def test_google_site_verification_rejects_mismatched_provider_data(
    tmp_path: Path,
    operation: str,
    payload: object,
    message: str,
) -> None:
    client = _client(
        tmp_path,
        httpx.MockTransport(lambda _: httpx.Response(200, json=payload)),
    )
    request = ProviderReadRequest(AccountId("google-main"), 1.0)

    with pytest.raises(ProviderOperationError, match=message):
        if operation == "token":
            await client.get_token(request, "example.com", GoogleVerificationMethod.DNS_TXT)
        elif operation == "verify":
            await client.verify(request, "example.com")
        else:
            await client.is_verified(request, "example.com")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "failure_code"),
    (
        (401, ProviderFailureCode.AUTHENTICATION),
        (403, ProviderFailureCode.FORBIDDEN),
        (404, ProviderFailureCode.FORBIDDEN),
        (429, ProviderFailureCode.RATE_LIMITED),
        (500, ProviderFailureCode.UNAVAILABLE),
        (302, ProviderFailureCode.INVALID_RESPONSE),
        (400, ProviderFailureCode.INVALID_RESPONSE),
    ),
)
async def test_google_site_verification_maps_http_failures_safely(
    tmp_path: Path,
    status_code: int,
    failure_code: ProviderFailureCode,
) -> None:
    client = _client(
        tmp_path,
        httpx.MockTransport(lambda _: httpx.Response(status_code, text="private provider detail")),
    )

    with pytest.raises(ProviderOperationError) as error:
        await client.get_token(
            ProviderReadRequest(AccountId("google-main"), 1.0),
            "example.com",
        )

    assert error.value.code is failure_code
    assert "private provider detail" not in str(error.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    (
        httpx.Response(200, content=b"not-json"),
        httpx.Response(200, content=b"x" * (MAX_PROVIDER_RESPONSE_BYTES + 1)),
    ),
)
async def test_google_site_verification_rejects_invalid_or_oversized_json(
    tmp_path: Path,
    response: httpx.Response,
) -> None:
    client = _client(tmp_path, httpx.MockTransport(lambda _: response))

    with pytest.raises(ProviderOperationError) as error:
        await client.get_token(
            ProviderReadRequest(AccountId("google-main"), 1.0),
            "example.com",
        )

    assert error.value.code is ProviderFailureCode.INVALID_RESPONSE


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure", "failure_code"),
    (
        (httpx.ReadTimeout("private detail"), ProviderFailureCode.TIMEOUT),
        (httpx.ConnectError("private detail"), ProviderFailureCode.UNAVAILABLE),
    ),
)
async def test_google_site_verification_maps_transport_failures_safely(
    tmp_path: Path,
    failure: httpx.HTTPError,
    failure_code: ProviderFailureCode,
) -> None:
    def fail(_: httpx.Request) -> httpx.Response:
        raise failure

    client = _client(tmp_path, httpx.MockTransport(fail))

    with pytest.raises(ProviderOperationError) as error:
        await client.get_token(
            ProviderReadRequest(AccountId("google-main"), 1.0),
            "example.com",
        )

    assert error.value.code is failure_code
    assert "private detail" not in str(error.value)
