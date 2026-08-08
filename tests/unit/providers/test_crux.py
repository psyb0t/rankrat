from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import httpx
import pytest

from rankrat.errors import BoundaryDeniedError, InputLimitError
from rankrat.models.boundaries import BoundaryDocument
from rankrat.policy.boundaries import BoundaryPolicy
from rankrat.providers.base import (
    AccountId,
    ProviderFailureCode,
    ProviderOperationError,
    ProviderReadRequest,
)
from rankrat.providers.crux import CruxFormFactor, CruxHistoryClient, CruxMetric


def _policy(key_file: Path) -> BoundaryPolicy:
    return BoundaryPolicy(
        BoundaryDocument.model_validate(
            {
                "accounts": [
                    {
                        "id": "pagespeed-main",
                        "provider": "google",
                        "credential": "/run/secrets/google-client.json",
                        "pagespeed_api_key_file": str(key_file),
                        "pagespeed_sites": ["https://example.com/blog/"],
                    }
                ]
            }
        )
    )


def _request() -> ProviderReadRequest:
    return ProviderReadRequest(AccountId("pagespeed-main"), 1.0)


def _payload() -> dict[str, object]:
    return {
        "record": {
            "collectionPeriods": [
                {
                    "firstDate": {"year": 2025, "month": 1, "day": 1},
                    "lastDate": {"year": 2025, "month": 1, "day": 28},
                },
                {
                    "firstDate": {"year": 2025, "month": 1, "day": 8},
                    "lastDate": {"year": 2025, "month": 2, "day": 4},
                },
            ],
            "metrics": {
                "largest_contentful_paint": {
                    "histogramTimeseries": [
                        {"densities": [0.6, 0.7]},
                        {"densities": [0.3, 0.2]},
                        {"densities": [0.1, 0.1]},
                    ],
                    "percentilesTimeseries": {"p75s": [2400, 2200]},
                }
            },
        }
    }


@pytest.mark.asyncio
async def test_crux_uses_fixed_origin_key_and_parses_history(tmp_path: Path) -> None:
    key_file = tmp_path / "pagespeed-key"
    key_file.write_text("valid-pagespeed-key", encoding="ascii")

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "chromeuxreport.googleapis.com"
        assert request.url.params["key"] == "valid-pagespeed-key"
        assert "Authorization" not in request.headers
        body = json.loads(request.content)
        assert body == {
            "url": "https://example.com/blog/post",
            "formFactor": "PHONE",
            "metrics": ["largest_contentful_paint"],
            "collectionPeriodCount": 2,
        }
        return httpx.Response(200, json=_payload())

    client = CruxHistoryClient(
        _policy(key_file),
        lambda: httpx.MockTransport(handler),
    )
    report = await client.query(
        _request(),
        "https://example.com/blog/",
        "https://example.com/blog/post",
        "url",
        CruxFormFactor.PHONE,
        (CruxMetric.LARGEST_CONTENTFUL_PAINT,),
        2,
    )

    assert report.no_data is False
    assert report.metrics[0].points[0].p75 == 2400.0
    assert report.metrics[0].points[1].densities == (0.7, 0.2, 0.1)


@pytest.mark.asyncio
async def test_crux_normalizes_origin_and_returns_explicit_no_data(tmp_path: Path) -> None:
    key_file = tmp_path / "pagespeed-key"
    key_file.write_text("valid-pagespeed-key", encoding="ascii")

    async def handler(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content)["origin"] == "https://example.com"
        return httpx.Response(404, json={"error": {"code": 404}})

    client = CruxHistoryClient(
        _policy(key_file),
        lambda: httpx.MockTransport(handler),
    )
    report = await client.query(
        _request(),
        "https://example.com/blog/",
        "https://example.com/",
        "origin",
        CruxFormFactor.ALL,
        (CruxMetric.CUMULATIVE_LAYOUT_SHIFT,),
        1,
    )
    assert report.no_data is True
    assert report.metrics == ()


@pytest.mark.asyncio
async def test_crux_rejects_scope_escape_and_origin_path(tmp_path: Path) -> None:
    key_file = tmp_path / "pagespeed-key"
    key_file.write_text("valid-pagespeed-key", encoding="ascii")
    client = CruxHistoryClient(
        _policy(key_file),
        lambda: pytest.fail("network must not be reached"),
    )

    with pytest.raises(BoundaryDeniedError):
        await client.query(
            _request(),
            "https://example.com/blog/",
            "https://attacker.invalid/",
            "url",
            CruxFormFactor.ALL,
            (CruxMetric.LARGEST_CONTENTFUL_PAINT,),
            1,
        )
    with pytest.raises(InputLimitError, match="origin"):
        await client.query(
            _request(),
            "https://example.com/blog/",
            "https://example.com/blog/",
            "origin",
            CruxFormFactor.ALL,
            (CruxMetric.LARGEST_CONTENTFUL_PAINT,),
            1,
        )


@pytest.mark.asyncio
async def test_crux_rejects_bad_key_and_mismatched_series(tmp_path: Path) -> None:
    key_file = tmp_path / "pagespeed-key"
    key_file.write_bytes(b"bad key")
    client = CruxHistoryClient(
        _policy(key_file),
        lambda: pytest.fail("network must not be reached"),
    )
    with pytest.raises(ProviderOperationError) as key_error:
        await client.query(
            _request(),
            "https://example.com/blog/",
            "https://example.com/blog/post",
            "url",
            CruxFormFactor.ALL,
            (CruxMetric.LARGEST_CONTENTFUL_PAINT,),
            1,
        )
    assert key_error.value.code is ProviderFailureCode.AUTHENTICATION

    key_file.write_text("valid-pagespeed-key", encoding="ascii")
    payload = _payload()
    record = cast(dict[str, object], payload["record"])
    metrics = cast(dict[str, object], record["metrics"])
    metric = cast(dict[str, object], metrics["largest_contentful_paint"])
    percentiles = cast(dict[str, object], metric["percentilesTimeseries"])
    percentiles["p75s"] = [1]
    invalid_client = CruxHistoryClient(
        _policy(key_file),
        lambda: httpx.MockTransport(lambda _: httpx.Response(200, json=payload)),
    )
    with pytest.raises(ProviderOperationError) as response_error:
        await invalid_client.query(
            _request(),
            "https://example.com/blog/",
            "https://example.com/blog/post",
            "url",
            CruxFormFactor.ALL,
            (CruxMetric.LARGEST_CONTENTFUL_PAINT,),
            2,
        )
    assert response_error.value.code is ProviderFailureCode.INVALID_RESPONSE


@pytest.mark.asyncio
async def test_crux_normalizes_documented_nan_density_markers(tmp_path: Path) -> None:
    key_file = tmp_path / "pagespeed-key"
    key_file.write_text("valid-pagespeed-key", encoding="ascii")
    payload = _payload()
    record = cast(dict[str, object], payload["record"])
    metrics = cast(dict[str, object], record["metrics"])
    metric = cast(dict[str, object], metrics["largest_contentful_paint"])
    histograms = cast(list[dict[str, object]], metric["histogramTimeseries"])
    histograms[0]["densities"] = ["NaN", 0.7]

    client = CruxHistoryClient(
        _policy(key_file),
        lambda: httpx.MockTransport(lambda _: httpx.Response(200, json=payload)),
    )
    report = await client.query(
        _request(),
        "https://example.com/blog/",
        "https://example.com/blog/post",
        "url",
        CruxFormFactor.ALL,
        (CruxMetric.LARGEST_CONTENTFUL_PAINT,),
        2,
    )

    assert report.metrics[0].points[0].densities == (None, 0.3, 0.1)


@pytest.mark.asyncio
async def test_crux_rejects_unrecognized_density_strings(tmp_path: Path) -> None:
    key_file = tmp_path / "pagespeed-key"
    key_file.write_text("valid-pagespeed-key", encoding="ascii")
    payload = _payload()
    record = cast(dict[str, object], payload["record"])
    metrics = cast(dict[str, object], record["metrics"])
    metric = cast(dict[str, object], metrics["largest_contentful_paint"])
    histograms = cast(list[dict[str, object]], metric["histogramTimeseries"])
    histograms[0]["densities"] = ["unknown", 0.7]
    client = CruxHistoryClient(
        _policy(key_file),
        lambda: httpx.MockTransport(lambda _: httpx.Response(200, json=payload)),
    )

    with pytest.raises(ProviderOperationError) as response_error:
        await client.query(
            _request(),
            "https://example.com/blog/",
            "https://example.com/blog/post",
            "url",
            CruxFormFactor.ALL,
            (CruxMetric.LARGEST_CONTENTFUL_PAINT,),
            2,
        )
    assert response_error.value.code is ProviderFailureCode.INVALID_RESPONSE


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (httpx.Response(401), ProviderFailureCode.AUTHENTICATION),
        (httpx.Response(403), ProviderFailureCode.FORBIDDEN),
        (httpx.Response(429), ProviderFailureCode.RATE_LIMITED),
        (httpx.Response(500), ProviderFailureCode.UNAVAILABLE),
        (httpx.Response(400), ProviderFailureCode.INVALID_RESPONSE),
        (
            httpx.Response(302, headers={"location": "https://example.invalid"}),
            ProviderFailureCode.INVALID_RESPONSE,
        ),
    ],
)
def test_crux_maps_provider_statuses(
    response: httpx.Response,
    expected: ProviderFailureCode,
) -> None:
    with pytest.raises(ProviderOperationError) as raised:
        CruxHistoryClient._raise_for_status(response)
    assert raised.value.code is expected


@pytest.mark.parametrize("content", [b"bad key", b"\xff", b"x" * 10_000])
def test_crux_rejects_invalid_key_files(tmp_path: Path, content: bytes) -> None:
    key_file = tmp_path / "key"
    key_file.write_bytes(content)
    with pytest.raises(ProviderOperationError) as raised:
        CruxHistoryClient._load_key(key_file)
    assert raised.value.code is ProviderFailureCode.AUTHENTICATION


def test_crux_rejects_symlinked_key_file(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.write_text("valid-pagespeed-key", encoding="ascii")
    key_file = tmp_path / "key"
    key_file.symlink_to(target)
    with pytest.raises(ProviderOperationError):
        CruxHistoryClient._load_key(key_file)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (httpx.ReadTimeout("slow"), ProviderFailureCode.TIMEOUT),
        (httpx.ConnectError("offline"), ProviderFailureCode.UNAVAILABLE),
    ],
)
async def test_crux_maps_transport_failures(
    tmp_path: Path,
    failure: httpx.HTTPError,
    expected: ProviderFailureCode,
) -> None:
    key_file = tmp_path / "key"
    key_file.write_text("valid-pagespeed-key", encoding="ascii")

    def handler(_: httpx.Request) -> httpx.Response:
        raise failure

    client = CruxHistoryClient(_policy(key_file), lambda: httpx.MockTransport(handler))
    with pytest.raises(ProviderOperationError) as raised:
        await client.query(
            _request(),
            "https://example.com/blog/",
            "https://example.com/blog/post",
            "url",
            CruxFormFactor.ALL,
            (CruxMetric.LARGEST_CONTENTFUL_PAINT,),
            1,
        )
    assert raised.value.code is expected


@pytest.mark.asyncio
async def test_crux_rejects_unsupported_target_kind_and_cross_origin(tmp_path: Path) -> None:
    key_file = tmp_path / "key"
    key_file.write_text("valid-pagespeed-key", encoding="ascii")
    client = CruxHistoryClient(
        _policy(key_file),
        lambda: pytest.fail("network must not be reached"),
    )

    with pytest.raises(ValueError, match="target kind"):
        await client.query(
            _request(),
            "https://example.com/blog/",
            "https://example.com/blog/post",
            "unsupported",
            CruxFormFactor.ALL,
            (CruxMetric.LARGEST_CONTENTFUL_PAINT,),
            1,
        )
    with pytest.raises(BoundaryDeniedError, match="origin"):
        await client.query(
            _request(),
            "https://example.com/blog/",
            "https://other.example/",
            "origin",
            CruxFormFactor.ALL,
            (CruxMetric.LARGEST_CONTENTFUL_PAINT,),
            1,
        )


@pytest.mark.asyncio
async def test_crux_rejects_mismatched_histogram_series(tmp_path: Path) -> None:
    key_file = tmp_path / "key"
    key_file.write_text("valid-pagespeed-key", encoding="ascii")
    payload = _payload()
    record = cast(dict[str, object], payload["record"])
    metrics = cast(dict[str, object], record["metrics"])
    metric = cast(dict[str, object], metrics["largest_contentful_paint"])
    histograms = cast(list[dict[str, object]], metric["histogramTimeseries"])
    histograms[0]["densities"] = [0.5]
    client = CruxHistoryClient(
        _policy(key_file),
        lambda: httpx.MockTransport(lambda _: httpx.Response(200, json=payload)),
    )

    with pytest.raises(ProviderOperationError) as raised:
        await client.query(
            _request(),
            "https://example.com/blog/",
            "https://example.com/blog/post",
            "url",
            CruxFormFactor.ALL,
            (CruxMetric.LARGEST_CONTENTFUL_PAINT,),
            2,
        )
    assert raised.value.code is ProviderFailureCode.INVALID_RESPONSE


@pytest.mark.asyncio
async def test_crux_omits_requested_metric_when_provider_has_no_series(tmp_path: Path) -> None:
    key_file = tmp_path / "key"
    key_file.write_text("valid-pagespeed-key", encoding="ascii")
    client = CruxHistoryClient(
        _policy(key_file),
        lambda: httpx.MockTransport(lambda _: httpx.Response(200, json=_payload())),
    )

    report = await client.query(
        _request(),
        "https://example.com/blog/",
        "https://example.com/blog/post",
        "url",
        CruxFormFactor.ALL,
        (CruxMetric.CUMULATIVE_LAYOUT_SHIFT,),
        2,
    )
    assert report.metrics == ()
