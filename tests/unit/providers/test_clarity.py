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
from rankrat.providers.clarity import ClarityClient, ClarityDimension


def _policy(token_file: Path) -> BoundaryPolicy:
    return BoundaryPolicy(
        BoundaryDocument.model_validate(
            {
                "accounts": [
                    {
                        "id": "clarity-main",
                        "provider": "clarity",
                        "credential": str(token_file),
                    }
                ]
            }
        )
    )


def _client(tmp_path: Path, transport: httpx.AsyncBaseTransport) -> ClarityClient:
    token_file = tmp_path / "clarity-token"
    token_file.write_text("clarity-token-not-real", encoding="ascii")
    return ClarityClient(_policy(token_file), lambda: transport)


@pytest.mark.asyncio
async def test_clarity_uses_its_fixed_endpoint_and_bounded_dimensions(tmp_path: Path) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url == httpx.URL(
            "https://www.clarity.ms/export-data/api/v1/project-live-insights?numOfDays=3&dimension1=Browser&dimension2=URL"
        )
        assert request.headers["Authorization"] == "Bearer clarity-token-not-real"
        assert request.headers["Content-Type"] == "application/json"
        return httpx.Response(
            200,
            json=[
                {
                    "metricName": "Total Session Count",
                    "information": [{"browserName": "Chrome", "sessions": 3}],
                }
            ],
        )

    metrics = await _client(tmp_path, httpx.MockTransport(handler)).live_insights(
        ProviderReadRequest(AccountId("clarity-main"), 1.0),
        3,
        (ClarityDimension.BROWSER, ClarityDimension.URL),
    )
    assert metrics[0].metric_name == "Total Session Count"
    assert metrics[0].information == ({"browserName": "Chrome", "sessions": 3},)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("response", "expected_code"),
    (
        (httpx.Response(401), ProviderFailureCode.AUTHENTICATION),
        (httpx.Response(403), ProviderFailureCode.FORBIDDEN),
        (httpx.Response(429), ProviderFailureCode.RATE_LIMITED),
        (httpx.Response(503), ProviderFailureCode.UNAVAILABLE),
        (httpx.Response(200, content=b"invalid"), ProviderFailureCode.INVALID_RESPONSE),
    ),
)
async def test_clarity_maps_failures_without_upstream_body_leakage(
    tmp_path: Path,
    response: httpx.Response,
    expected_code: ProviderFailureCode,
) -> None:
    client = _client(tmp_path, httpx.MockTransport(lambda _: response))
    with pytest.raises(ProviderOperationError) as error:
        await client.live_insights(
            ProviderReadRequest(AccountId("clarity-main"), 1.0),
            1,
            (),
        )
    assert error.value.code is expected_code


@pytest.mark.asyncio
async def test_clarity_rejects_invalid_dimensions_and_response_rows(tmp_path: Path) -> None:
    client = _client(
        tmp_path,
        httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json=[{"metricName": "Sessions", "information": [{"nested": {"bad": True}}]}],
            )
        ),
    )
    with pytest.raises(ValueError, match="documented range"):
        await client.live_insights(
            ProviderReadRequest(AccountId("clarity-main"), 1.0),
            4,
            (),
        )
    with pytest.raises(ProviderOperationError) as error:
        await client.live_insights(
            ProviderReadRequest(AccountId("clarity-main"), 1.0),
            1,
            (),
        )
    assert error.value.code is ProviderFailureCode.INVALID_RESPONSE


@pytest.mark.asyncio
async def test_clarity_rejects_a_symlinked_or_invalid_token_file(tmp_path: Path) -> None:
    target = tmp_path / "token-target"
    target.write_text("clarity-token-not-real", encoding="ascii")
    token_file = tmp_path / "clarity-token"
    token_file.symlink_to(target)
    client = ClarityClient(
        _policy(token_file),
        lambda: httpx.MockTransport(lambda _: httpx.Response(200)),
    )
    with pytest.raises(ProviderOperationError) as error:
        await client.live_insights(ProviderReadRequest(AccountId("clarity-main"), 1.0), 1, ())
    assert error.value.code is ProviderFailureCode.AUTHENTICATION
