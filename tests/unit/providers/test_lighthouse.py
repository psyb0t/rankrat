from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from rankrat.constants import MAX_LIGHTHOUSE_RESPONSE_BYTES
from rankrat.providers.base import ProviderFailureCode, ProviderOperationError
from rankrat.providers.lighthouse import LighthouseWorkerClient


def _payload(**updates: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "requestedUrl": "https://example.com/page",
        "finalUrl": "https://example.com/final",
        "fetchTime": "2026-08-05T18:30:32+00:00",
        "lighthouseVersion": "13.4.1",
        "categories": {"seo": {"score": 0.75}},
        "findings": [
            {
                "id": "document-title",
                "categories": ["seo"],
                "score": 0.5,
                "scoreDisplayMode": "numeric",
                "title": "Document title",
                "description": "Add a descriptive title.",
            }
        ],
    }
    payload.update(updates)
    return payload


def _client(handler: httpx.MockTransport) -> LighthouseWorkerClient:
    return LighthouseWorkerClient(Path("/run/lighthouse/test.sock"), lambda _: handler)


@pytest.mark.asyncio
async def test_lighthouse_client_uses_fixed_uds_origin_and_validates_result() -> None:
    captured: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json=_payload())

    result = await _client(httpx.MockTransport(handle)).audit(
        "https://example.com/page",
        ("seo",),
        10,
    )

    assert captured[0].url == httpx.URL("http://lighthouse/v1/audits")
    assert json.loads(captured[0].content) == {
        "url": "https://example.com/page",
        "categories": ["seo"],
    }
    assert result.categories[0].category == "seo"
    assert result.findings[0].id == "document-title"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "expected_code"),
    [
        (409, ProviderFailureCode.RATE_LIMITED),
        (400, ProviderFailureCode.UNAVAILABLE),
        (502, ProviderFailureCode.UNAVAILABLE),
    ],
)
async def test_lighthouse_client_maps_finite_worker_statuses(
    status: int,
    expected_code: ProviderFailureCode,
) -> None:
    client = _client(httpx.MockTransport(lambda _: httpx.Response(status, text="secret body")))

    with pytest.raises(ProviderOperationError) as caught:
        await client.audit("https://example.com/", ("seo",), 10)

    assert caught.value.code is expected_code
    assert "secret body" not in str(caught.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        _payload(finalUrl="http://example.com/final"),
        _payload(fetchTime="not-a-time"),
        _payload(categories={"unknown": {"score": 1}}),
        _payload(
            findings=[
                {
                    "id": "duplicate",
                    "categories": ["seo"],
                    "score": 0,
                    "scoreDisplayMode": "binary",
                    "title": "One",
                    "description": "",
                },
                {
                    "id": "duplicate",
                    "categories": ["seo"],
                    "score": 0,
                    "scoreDisplayMode": "binary",
                    "title": "Two",
                    "description": "",
                },
            ]
        ),
    ],
)
async def test_lighthouse_client_rejects_malformed_worker_reports(
    payload: dict[str, object],
) -> None:
    client = _client(httpx.MockTransport(lambda _: httpx.Response(200, json=payload)))

    with pytest.raises(ProviderOperationError) as caught:
        await client.audit("https://example.com/", ("seo",), 10)

    assert caught.value.code is ProviderFailureCode.INVALID_RESPONSE


@pytest.mark.asyncio
async def test_lighthouse_client_rejects_oversized_worker_response() -> None:
    client = _client(
        httpx.MockTransport(
            lambda _: httpx.Response(200, content=b"x" * (MAX_LIGHTHOUSE_RESPONSE_BYTES + 1))
        )
    )

    with pytest.raises(ProviderOperationError) as caught:
        await client.audit("https://example.com/", ("seo",), 10)

    assert caught.value.code is ProviderFailureCode.INVALID_RESPONSE


@pytest.mark.asyncio
async def test_lighthouse_client_fails_safely_when_worker_is_not_configured() -> None:
    with pytest.raises(ProviderOperationError) as caught:
        await LighthouseWorkerClient(None).audit("https://example.com/", ("seo",), 10)

    assert caught.value.code is ProviderFailureCode.UNAVAILABLE
