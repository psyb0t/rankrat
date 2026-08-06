from __future__ import annotations

import httpx
import pytest

from rankrat.constants import MAX_PROVIDER_RESPONSE_BYTES
from rankrat.providers.base import ProviderFailureCode, ProviderOperationError
from rankrat.providers.cloudflare import CloudflareDnsRecordType
from rankrat.providers.dns import PublicDnsClient


@pytest.mark.asyncio
async def test_public_dns_matches_txt_and_cname_wire_formats() -> None:
    responses = iter(
        (
            httpx.Response(200, json={"Status": 0, "Answer": [{"data": '"txt-value"'}]}),
            httpx.Response(
                200,
                json={"Status": 0, "Answer": [{"data": "verify.bing.com."}]},
            ),
        )
    )
    client = PublicDnsClient(
        transport_factory=lambda: httpx.MockTransport(lambda _: next(responses))
    )
    txt = await client.has_record(
        "example.com",
        CloudflareDnsRecordType.TXT,
        "txt-value",
        1.0,
    )
    cname = await client.has_record(
        "proof.example.com",
        CloudflareDnsRecordType.CNAME,
        "verify.bing.com",
        1.0,
    )
    assert txt.propagated is True
    assert cname.propagated is True


@pytest.mark.asyncio
async def test_public_dns_reports_absent_records_and_normalizes_split_txt() -> None:
    responses = iter(
        (
            httpx.Response(200, json={"Status": 3}),
            httpx.Response(
                200,
                json={"Status": 0, "Answer": [{"data": '"split" "value"'}]},
            ),
        )
    )
    client = PublicDnsClient(
        transport_factory=lambda: httpx.MockTransport(lambda _: next(responses))
    )

    absent = await client.has_record(
        "example.com",
        CloudflareDnsRecordType.TXT,
        "value",
        1.0,
    )
    split = await client.has_record(
        "example.com",
        CloudflareDnsRecordType.TXT,
        "splitvalue",
        1.0,
    )

    assert absent.propagated is False
    assert absent.answer_count == 0
    assert split.propagated is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    (
        httpx.Response(500),
        httpx.Response(302, headers={"location": "https://attacker.invalid/"}),
        httpx.Response(200, content=b"not-json"),
        httpx.Response(200, json={"Status": 0, "Answer": [{"data": "x"}] * 101}),
        httpx.Response(200, content=b"x" * (MAX_PROVIDER_RESPONSE_BYTES + 1)),
    ),
)
async def test_public_dns_rejects_unavailable_or_invalid_responses(
    response: httpx.Response,
) -> None:
    client = PublicDnsClient(transport_factory=lambda: httpx.MockTransport(lambda _: response))

    with pytest.raises(ProviderOperationError):
        await client.has_record(
            "example.com",
            CloudflareDnsRecordType.TXT,
            "value",
            1.0,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure", "failure_code"),
    (
        (httpx.ReadTimeout("private detail"), ProviderFailureCode.TIMEOUT),
        (httpx.ConnectError("private detail"), ProviderFailureCode.UNAVAILABLE),
    ),
)
async def test_public_dns_maps_transport_errors_safely(
    failure: httpx.HTTPError,
    failure_code: ProviderFailureCode,
) -> None:
    def fail(_: httpx.Request) -> httpx.Response:
        raise failure

    client = PublicDnsClient(transport_factory=lambda: httpx.MockTransport(fail))

    with pytest.raises(ProviderOperationError) as error:
        await client.has_record(
            "example.com",
            CloudflareDnsRecordType.TXT,
            "value",
            1.0,
        )

    assert error.value.code is failure_code
    assert "private detail" not in str(error.value)
