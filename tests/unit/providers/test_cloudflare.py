from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from rankrat.constants import MAX_PROVIDER_RESPONSE_BYTES
from rankrat.errors import BoundaryDeniedError, InputLimitError
from rankrat.models.boundaries import BoundaryDocument
from rankrat.policy.boundaries import BoundaryPolicy
from rankrat.providers.base import (
    AccountId,
    ProviderFailureCode,
    ProviderOperationError,
    ProviderReadRequest,
)
from rankrat.providers.cloudflare import CloudflareDnsClient
from rankrat.providers.dns import DnsRecordType


def _policy(token_file: Path) -> BoundaryPolicy:
    return BoundaryPolicy(
        BoundaryDocument.model_validate(
            {
                "accounts": [
                    {
                        "id": "cloudflare-main",
                        "provider": "cloudflare",
                        "credential": str(token_file),
                        "dns_zones": [
                            {"provider_zone_id": "a" * 32, "name": "example.com"},
                        ],
                    }
                ]
            }
        )
    )


@pytest.mark.asyncio
async def test_cloudflare_creates_only_exact_verification_record(tmp_path: Path) -> None:
    token_file = tmp_path / "token"
    token_file.write_text("safe_test_token_123456789", encoding="ascii")
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(200, json={"success": True, "result": []})
        return httpx.Response(
            200,
            json={
                "success": True,
                "result": {
                    "id": "b" * 32,
                    "type": "TXT",
                    "name": "example.com",
                    "content": "provider-issued-value",
                },
            },
        )

    client = CloudflareDnsClient(
        _policy(token_file),
        transport_factory=lambda: httpx.MockTransport(handler),
    )
    receipt = await client.ensure_verification_record(
        ProviderReadRequest(AccountId("cloudflare-main"), 1.0),
        "example.com",
        DnsRecordType.TXT,
        "example.com",
        "provider-issued-value",
    )

    assert receipt.created is True
    assert [request.method for request in requests] == ["GET", "POST"]
    payload = json.loads(requests[1].content)
    assert payload["proxied"] is False
    assert payload["type"] == "TXT"
    assert requests[1].headers["authorization"].startswith("Bearer ")


@pytest.mark.asyncio
async def test_cloudflare_reuses_exact_record_and_rejects_zone_escape(tmp_path: Path) -> None:
    token_file = tmp_path / "token"
    token_file.write_text("safe_test_token_123456789", encoding="ascii")

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "success": True,
                "result": [
                    {
                        "id": "b" * 32,
                        "type": "CNAME",
                        "name": "proof.example.com",
                        "content": "verify.bing.com",
                    }
                ],
            },
        )

    client = CloudflareDnsClient(
        _policy(token_file),
        transport_factory=lambda: httpx.MockTransport(handler),
    )
    receipt = await client.ensure_verification_record(
        ProviderReadRequest(AccountId("cloudflare-main"), 1.0),
        "example.com",
        DnsRecordType.CNAME,
        "proof.example.com",
        "verify.bing.com",
    )
    assert receipt.created is False

    with pytest.raises(BoundaryDeniedError):
        await client.ensure_verification_record(
            ProviderReadRequest(AccountId("cloudflare-main"), 1.0),
            "example.com",
            DnsRecordType.TXT,
            "attacker.invalid",
            "value",
        )


@pytest.mark.asyncio
async def test_cloudflare_refuses_to_overwrite_a_conflicting_cname(tmp_path: Path) -> None:
    token_file = tmp_path / "token"
    token_file.write_text("safe_test_token_123456789", encoding="ascii")

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "success": True,
                "result": [
                    {
                        "id": "b" * 32,
                        "type": "CNAME",
                        "name": "proof.example.com",
                        "content": "occupied.example.com",
                    }
                ],
            },
        )

    client = CloudflareDnsClient(
        _policy(token_file),
        transport_factory=lambda: httpx.MockTransport(handler),
    )
    with pytest.raises(BoundaryDeniedError, match="already occupied"):
        await client.ensure_verification_record(
            ProviderReadRequest(AccountId("cloudflare-main"), 1.0),
            "example.com",
            DnsRecordType.CNAME,
            "proof.example.com",
            "verify.bing.com",
        )


@pytest.mark.asyncio
async def test_cloudflare_unbounded_mode_discovers_the_most_specific_zone(
    tmp_path: Path,
) -> None:
    token_file = tmp_path / "token"
    token_file.write_text("safe_test_token_123456789", encoding="ascii")
    policy = BoundaryPolicy(
        BoundaryDocument.model_validate(
            {
                "accounts": [
                    {
                        "id": "cloudflare-main",
                        "provider": "cloudflare",
                        "credential": str(token_file),
                    }
                ]
            }
        ),
        unbounded=True,
    )
    requested_names: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_names.append(request.url.params["name"])
        if request.url.params["name"] == "example.com":
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "result": [{"id": "a" * 32, "name": "example.com"}],
                },
            )
        return httpx.Response(200, json={"success": True, "result": []})

    client = CloudflareDnsClient(
        policy,
        transport_factory=lambda: httpx.MockTransport(handler),
    )
    zone = await client.resolve_zone(
        ProviderReadRequest(AccountId("cloudflare-main"), 1.0),
        "www.example.com",
    )

    assert zone.name == "example.com"
    assert requested_names == ["www.example.com", "example.com"]


@pytest.mark.asyncio
async def test_cloudflare_readiness_and_bounded_zone_denial(tmp_path: Path) -> None:
    token_file = tmp_path / "token"
    token_file.write_text("safe_test_token_123456789", encoding="ascii")
    client = CloudflareDnsClient(
        _policy(token_file),
        transport_factory=lambda: httpx.MockTransport(
            lambda _: httpx.Response(200, json={"success": True, "result": []})
        ),
    )
    request = ProviderReadRequest(AccountId("cloudflare-main"), 1.0)

    readiness = await client.readiness(request)

    assert readiness.available is True
    with pytest.raises(BoundaryDeniedError):
        await client.resolve_zone(request, "outside.example.net")


@pytest.mark.asyncio
async def test_cloudflare_rejects_duplicate_discovered_zones(tmp_path: Path) -> None:
    token_file = tmp_path / "token"
    token_file.write_text("safe_test_token_123456789", encoding="ascii")
    policy = BoundaryPolicy(
        BoundaryDocument.model_validate(
            {
                "accounts": [
                    {
                        "id": "cloudflare-main",
                        "provider": "cloudflare",
                        "credential": str(token_file),
                    }
                ]
            }
        ),
        unbounded=True,
    )
    duplicate = {"id": "a" * 32, "name": "example.com"}
    client = CloudflareDnsClient(
        policy,
        transport_factory=lambda: httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json={"success": True, "result": [duplicate, duplicate]},
            )
        ),
    )

    with pytest.raises(ProviderOperationError, match="duplicate zones"):
        await client.resolve_zone(
            ProviderReadRequest(AccountId("cloudflare-main"), 1.0),
            "example.com",
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "failure_code"),
    (
        (401, ProviderFailureCode.AUTHENTICATION),
        (403, ProviderFailureCode.AUTHENTICATION),
        (429, ProviderFailureCode.RATE_LIMITED),
        (500, ProviderFailureCode.UNAVAILABLE),
        (302, ProviderFailureCode.INVALID_RESPONSE),
        (400, ProviderFailureCode.INVALID_RESPONSE),
    ),
)
async def test_cloudflare_maps_http_failures_without_response_details(
    tmp_path: Path,
    status_code: int,
    failure_code: ProviderFailureCode,
) -> None:
    token_file = tmp_path / "token"
    token_file.write_text("safe_test_token_123456789", encoding="ascii")
    client = CloudflareDnsClient(
        _policy(token_file),
        transport_factory=lambda: httpx.MockTransport(
            lambda _: httpx.Response(status_code, text="private provider detail")
        ),
    )

    with pytest.raises(ProviderOperationError) as error:
        await client.readiness(ProviderReadRequest(AccountId("cloudflare-main"), 1.0))

    assert error.value.code is failure_code
    assert "private provider detail" not in str(error.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    (
        httpx.Response(200, content=b"not-json"),
        httpx.Response(200, json={"success": False, "result": []}),
        httpx.Response(200, json={"success": True, "result": [object().__class__.__name__]}),
        httpx.Response(200, content=b"x" * (MAX_PROVIDER_RESPONSE_BYTES + 1)),
    ),
)
async def test_cloudflare_rejects_invalid_or_oversized_responses(
    tmp_path: Path,
    response: httpx.Response,
) -> None:
    token_file = tmp_path / "token"
    token_file.write_text("safe_test_token_123456789", encoding="ascii")
    client = CloudflareDnsClient(
        _policy(token_file),
        transport_factory=lambda: httpx.MockTransport(lambda _: response),
    )

    with pytest.raises(ProviderOperationError) as error:
        await client.readiness(ProviderReadRequest(AccountId("cloudflare-main"), 1.0))

    assert error.value.code is ProviderFailureCode.INVALID_RESPONSE


@pytest.mark.asyncio
async def test_cloudflare_rejects_invalid_token_and_record_material(tmp_path: Path) -> None:
    token_file = tmp_path / "token"
    token_file.write_text("bad token", encoding="ascii")
    client = CloudflareDnsClient(
        _policy(token_file),
        transport_factory=lambda: pytest.fail("network must not run"),
    )
    request = ProviderReadRequest(AccountId("cloudflare-main"), 1.0)

    with pytest.raises(ProviderOperationError) as error:
        await client.readiness(request)
    assert error.value.code is ProviderFailureCode.AUTHENTICATION

    token_file.write_text("safe_test_token_123456789", encoding="ascii")
    with pytest.raises(InputLimitError):
        await client.ensure_verification_record(
            request,
            "example.com",
            DnsRecordType.TXT,
            "example.com",
            "line one\nline two",
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure", "failure_code"),
    (
        (httpx.ReadTimeout("private detail"), ProviderFailureCode.TIMEOUT),
        (httpx.ConnectError("private detail"), ProviderFailureCode.UNAVAILABLE),
    ),
)
async def test_cloudflare_maps_transport_failures_safely(
    tmp_path: Path,
    failure: httpx.HTTPError,
    failure_code: ProviderFailureCode,
) -> None:
    token_file = tmp_path / "token"
    token_file.write_text("safe_test_token_123456789", encoding="ascii")

    def fail(_: httpx.Request) -> httpx.Response:
        raise failure

    client = CloudflareDnsClient(
        _policy(token_file),
        transport_factory=lambda: httpx.MockTransport(fail),
    )

    with pytest.raises(ProviderOperationError) as error:
        await client.readiness(ProviderReadRequest(AccountId("cloudflare-main"), 1.0))

    assert error.value.code is failure_code
    assert "private detail" not in str(error.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "invalid_response",
    (
        {"success": True, "result": "invalid"},
        {"success": False, "result": {}},
    ),
)
async def test_cloudflare_rejects_invalid_record_creation_response(
    tmp_path: Path,
    invalid_response: object,
) -> None:
    token_file = tmp_path / "token"
    token_file.write_text("safe_test_token_123456789", encoding="ascii")
    responses = iter(
        (
            httpx.Response(200, json={"success": True, "result": []}),
            httpx.Response(200, json=invalid_response),
        )
    )
    client = CloudflareDnsClient(
        _policy(token_file),
        transport_factory=lambda: httpx.MockTransport(lambda _: next(responses)),
    )

    with pytest.raises(ProviderOperationError) as error:
        await client.ensure_verification_record(
            ProviderReadRequest(AccountId("cloudflare-main"), 1.0),
            "example.com",
            DnsRecordType.TXT,
            "example.com",
            "provider-issued-value",
        )

    assert error.value.code is ProviderFailureCode.INVALID_RESPONSE
