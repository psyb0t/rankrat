from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from rankrat.constants import MAX_PAGESPEED_LOADING_EXPERIENCE_METRICS
from rankrat.errors import BoundaryDeniedError
from rankrat.models.boundaries import BoundaryDocument
from rankrat.policy.boundaries import BoundaryPolicy
from rankrat.providers.base import (
    AccountId,
    ProviderFailureCode,
    ProviderOperationError,
    ProviderReadRequest,
)
from rankrat.providers.pagespeed import (
    PageSpeedAnalysisResult,
    PageSpeedClient,
    PageSpeedLighthouseCategory,
    PageSpeedLoadingExperience,
    PageSpeedLoadingExperienceMetric,
    PageSpeedMetricDistribution,
    _PageSpeedQueryParameters,
)

_API_KEY = "test-pagespeed-api-key"
_API_KEY_PATH = Path("/run/secrets/pagespeed-main-api-key")


def _analysis_payload(url: str) -> dict[str, object]:
    return {
        "analysisUTCTimestamp": "2026-07-30T17:00:00Z",
        "id": url,
        "lighthouseResult": {
            "categories": {
                "performance": {"id": "performance", "score": 0.95},
                "seo": {"id": "seo", "score": None},
            }
        },
        "loadingExperience": {"overall_category": "FAST"},
        "originLoadingExperience": {"overall_category": "AVERAGE"},
    }


def _policy(api_key_file: Path | None = _API_KEY_PATH) -> BoundaryPolicy:
    account: dict[str, object] = {
        "id": "pagespeed-main",
        "provider": "google",
        "credential": "/run/secrets/google/oauth-client.json",
        "pagespeed_sites": ["https://example.com/blog/"],
    }
    if api_key_file is not None:
        account["pagespeed_api_key_file"] = str(api_key_file)
    return BoundaryPolicy(BoundaryDocument.model_validate({"accounts": [account]}))


def _request() -> ProviderReadRequest:
    return ProviderReadRequest(AccountId("pagespeed-main"), 1.0)


def _api_key(_: Path) -> str:
    return _API_KEY


def _payload_with_excessive_field_metrics() -> dict[str, object]:
    payload = _analysis_payload("https://example.com/blog/post")
    payload["loadingExperience"] = {
        "metrics": {
            f"METRIC_{index}": {"distributions": []}
            for index in range(MAX_PAGESPEED_LOADING_EXPERIENCE_METRICS + 1)
        }
    }
    return payload


@pytest.mark.asyncio
async def test_pagespeed_uses_fixed_origin_and_api_key_parameter() -> None:
    api_key_paths: list[Path] = []

    def api_key(path: Path) -> str:
        api_key_paths.append(path)
        return _API_KEY

    async def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url).startswith(
            "https://pagespeedonline.googleapis.com/pagespeedonline/v5/runPagespeed?"
        )
        assert request.url.params.get("url") == "https://example.com/blog/post"
        assert request.url.params.get("strategy") == "MOBILE"
        assert request.url.params.get_list("category") == ["PERFORMANCE", "SEO"]
        assert request.url.params.get("key") == _API_KEY
        assert request.url.params.get("access_token") is None
        assert request.url.params.get("oauth_token") is None
        assert "Authorization" not in request.headers
        return httpx.Response(200, json=_analysis_payload("https://example.com/blog/post/"))

    client = PageSpeedClient(_policy(), api_key, lambda: httpx.MockTransport(handler))
    assert await client.analyze(
        _request(),
        "https://example.com/blog/",
        "https://example.com/blog/post",
        "MOBILE",
        ("PERFORMANCE", "SEO"),
    ) == PageSpeedAnalysisResult(
        analyzed_url="https://example.com/blog/post/",
        analysis_utc_timestamp=datetime(2026, 7, 30, 17, tzinfo=UTC),
        categories=(
            PageSpeedLighthouseCategory("performance", 0.95),
            PageSpeedLighthouseCategory("seo", None),
        ),
        loading_experience_category="FAST",
        origin_loading_experience_category="AVERAGE",
    )
    assert api_key_paths == [_API_KEY_PATH]


@pytest.mark.asyncio
async def test_pagespeed_without_a_key_uses_the_anonymous_request_shape() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params.get("key") is None
        assert request.url.params.get("access_token") is None
        assert request.url.params.get("oauth_token") is None
        assert "Authorization" not in request.headers
        return httpx.Response(200, json=_analysis_payload("https://example.com/blog/post"))

    client = PageSpeedClient(
        _policy(None),
        lambda _: pytest.fail("anonymous requests must not load an API key"),
        lambda: httpx.MockTransport(handler),
    )

    result = await client.analyze(
        _request(),
        "https://example.com/blog/",
        "https://example.com/blog/post",
        "MOBILE",
        (),
    )

    assert result.analyzed_url == "https://example.com/blog/post"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("contents", "expected"),
    (
        (b"valid-api-key\n", "valid-api-key"),
        (b"valid-api-key\r\n", "valid-api-key"),
        (b"valid-api-key\r", "valid-api-key"),
    ),
)
async def test_pagespeed_loads_one_optional_trailing_line_ending(
    tmp_path: Path,
    contents: bytes,
    expected: str,
) -> None:
    key_file = tmp_path / "pagespeed-api-key"
    key_file.write_bytes(contents)
    observed_keys: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        observed_keys.append(request.url.params["key"])
        return httpx.Response(200, json=_analysis_payload("https://example.com/blog/post"))

    client = PageSpeedClient(
        _policy(key_file),
        transport_factory=lambda: httpx.MockTransport(handler),
    )
    await client.analyze(
        _request(),
        "https://example.com/blog/",
        "https://example.com/blog/post",
        "MOBILE",
        (),
    )
    assert observed_keys == [expected]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "contents",
    (
        b"",
        b"has whitespace",
        b"valid-api-key\n\n",
        b"invalid\x00api-key",
        b"x" * 513,
    ),
)
async def test_pagespeed_rejects_malformed_key_files_before_network(
    tmp_path: Path,
    contents: bytes,
) -> None:
    key_file = tmp_path / "pagespeed-api-key"
    key_file.write_bytes(contents)
    client = PageSpeedClient(
        _policy(key_file),
        transport_factory=lambda: pytest.fail("network must not be reached"),
    )

    with pytest.raises(ProviderOperationError) as error:
        await client.analyze(
            _request(),
            "https://example.com/blog/",
            "https://example.com/blog/post",
            "MOBILE",
            (),
        )

    assert error.value.code is ProviderFailureCode.AUTHENTICATION


@pytest.mark.asyncio
async def test_pagespeed_rejects_missing_or_non_utf8_key_file_before_network(
    tmp_path: Path,
) -> None:
    missing_key_file = tmp_path / "missing-api-key"
    missing_client = PageSpeedClient(
        _policy(missing_key_file),
        transport_factory=lambda: pytest.fail("network must not be reached"),
    )
    with pytest.raises(ProviderOperationError) as missing_error:
        await missing_client.analyze(
            _request(),
            "https://example.com/blog/",
            "https://example.com/blog/post",
            "MOBILE",
            (),
        )
    assert missing_error.value.code is ProviderFailureCode.AUTHENTICATION

    malformed_key_file = tmp_path / "malformed-api-key"
    malformed_key_file.write_bytes(b"\xff")
    malformed_client = PageSpeedClient(
        _policy(malformed_key_file),
        transport_factory=lambda: pytest.fail("network must not be reached"),
    )
    with pytest.raises(ProviderOperationError) as malformed_error:
        await malformed_client.analyze(
            _request(),
            "https://example.com/blog/",
            "https://example.com/blog/post",
            "MOBILE",
            (),
        )
    assert malformed_error.value.code is ProviderFailureCode.AUTHENTICATION


@pytest.mark.asyncio
async def test_pagespeed_parses_bounded_page_and_origin_field_metric_maps() -> None:
    payload = _analysis_payload("https://example.com/blog/post")
    payload["loadingExperience"] = {
        "overall_category": "FAST",
        "metrics": {
            "LARGEST_CONTENTFUL_PAINT_MS": {
                "percentile": 2_500,
                "category": "AVERAGE",
                "distributions": [
                    {"min": 0, "max": 2_500, "proportion": 0.75},
                    {"min": 2_500, "proportion": 0.25},
                ],
            }
        },
    }
    payload["originLoadingExperience"] = {
        "overall_category": "AVERAGE",
        "metrics": {
            "INTERACTION_TO_NEXT_PAINT": {
                "metricId": "INTERACTION_TO_NEXT_PAINT",
                "percentile": 200,
                "category": "FAST",
                "distributions": [{"min": 0, "max": 200, "proportion": 1.0}],
            }
        },
    }
    client = PageSpeedClient(
        _policy(),
        _api_key,
        lambda: httpx.MockTransport(lambda _: httpx.Response(200, json=payload)),
    )

    result = await client.analyze(
        _request(),
        "https://example.com/blog/",
        "https://example.com/blog/post",
        "MOBILE",
        (),
    )

    assert result.loading_experience == PageSpeedLoadingExperience(
        "FAST",
        (
            PageSpeedLoadingExperienceMetric(
                "LARGEST_CONTENTFUL_PAINT_MS",
                2_500,
                "AVERAGE",
                (
                    PageSpeedMetricDistribution(0, 2_500, 0.75),
                    PageSpeedMetricDistribution(2_500, None, 0.25),
                ),
            ),
        ),
    )
    assert result.origin_loading_experience == PageSpeedLoadingExperience(
        "AVERAGE",
        (
            PageSpeedLoadingExperienceMetric(
                "INTERACTION_TO_NEXT_PAINT",
                200,
                "FAST",
                (PageSpeedMetricDistribution(0, 200, 1.0),),
            ),
        ),
    )


@pytest.mark.asyncio
async def test_pagespeed_preserves_optional_field_metric_defaults() -> None:
    payload = _analysis_payload("https://example.com/blog/post")
    payload["loadingExperience"] = {
        "metrics": {
            "FIRST_CONTENTFUL_PAINT_MS": {
                "metricId": None,
                "category": None,
            }
        }
    }
    client = PageSpeedClient(
        _policy(),
        _api_key,
        lambda: httpx.MockTransport(lambda _: httpx.Response(200, json=payload)),
    )

    result = await client.analyze(
        _request(),
        "https://example.com/blog/",
        "https://example.com/blog/post",
        "MOBILE",
        (),
    )

    assert result.loading_experience == PageSpeedLoadingExperience(
        None,
        (PageSpeedLoadingExperienceMetric("FIRST_CONTENTFUL_PAINT_MS", None, None, ()),),
    )


@pytest.mark.asyncio
async def test_pagespeed_rejects_outside_url_before_api_key_or_network() -> None:
    client = PageSpeedClient(
        _policy(),
        lambda _: pytest.fail("API key loader must not be reached"),
        lambda: pytest.fail("network must not be reached"),
    )
    with pytest.raises(BoundaryDeniedError):
        await client.analyze(
            _request(), "https://example.com/blog/", "https://example.com/elsewhere", "MOBILE", ()
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,code",
    [
        (400, ProviderFailureCode.INVALID_RESPONSE),
        (401, ProviderFailureCode.AUTHENTICATION),
        (403, ProviderFailureCode.FORBIDDEN),
        (429, ProviderFailureCode.RATE_LIMITED),
        (500, ProviderFailureCode.UNAVAILABLE),
        (301, ProviderFailureCode.INVALID_RESPONSE),
    ],
)
async def test_pagespeed_maps_safe_failures(status: int, code: ProviderFailureCode) -> None:
    client = PageSpeedClient(
        _policy(),
        _api_key,
        lambda: httpx.MockTransport(lambda _: httpx.Response(status, text="private")),
    )
    with pytest.raises(ProviderOperationError) as error:
        await client.analyze(
            _request(), "https://example.com/blog/", "https://example.com/blog/post", "MOBILE", ()
        )
    assert error.value.code is code
    assert "private" not in str(error.value)


@pytest.mark.asyncio
async def test_pagespeed_rejects_transport_and_response_failures() -> None:
    responses = iter(
        (
            httpx.Response(200, content=b"nope"),
            httpx.Response(200, content=b"[]"),
            httpx.Response(200, headers={"content-length": "2097153"}),
            httpx.Response(200, headers={"content-length": "bad"}, content=b"x" * 2_097_153),
        )
    )
    client = PageSpeedClient(
        _policy(), _api_key, lambda: httpx.MockTransport(lambda _: next(responses))
    )
    for _ in range(4):
        with pytest.raises(ProviderOperationError) as error:
            await client.analyze(
                _request(),
                "https://example.com/blog/",
                "https://example.com/blog/post",
                "MOBILE",
                (),
            )
        assert error.value.code is ProviderFailureCode.INVALID_RESPONSE
    failing_client = PageSpeedClient(
        _policy(),
        _api_key,
        lambda: httpx.MockTransport(lambda _: (_ for _ in ()).throw(httpx.ReadTimeout("timeout"))),
    )
    with pytest.raises(ProviderOperationError) as error:
        await failing_client.analyze(
            _request(), "https://example.com/blog/", "https://example.com/blog/post", "MOBILE", ()
        )
    assert error.value.code is ProviderFailureCode.TIMEOUT
    timeout_traceback = str(error.getrepr(showlocals=True))
    assert _API_KEY not in timeout_traceback
    assert _REDACTED_API_KEY_VALUE in timeout_traceback
    unavailable_client = PageSpeedClient(
        _policy(),
        _api_key,
        lambda: httpx.MockTransport(
            lambda _: (_ for _ in ()).throw(httpx.ConnectError("unavailable"))
        ),
    )
    with pytest.raises(ProviderOperationError) as error:
        await unavailable_client.analyze(
            _request(), "https://example.com/blog/", "https://example.com/blog/post", "MOBILE", ()
        )
    assert error.value.code is ProviderFailureCode.UNAVAILABLE


_REDACTED_API_KEY_VALUE = "[REDACTED]"


def test_pagespeed_query_parameter_repr_redacts_only_api_key() -> None:
    parameters = _PageSpeedQueryParameters(
        {
            "url": "https://example.com/blog/post",
            "key": _API_KEY,
        }
    )

    assert repr(parameters) == "{'url': 'https://example.com/blog/post', 'key': '[REDACTED]'}"


@pytest.mark.asyncio
async def test_pagespeed_rejects_nonfinite_field_metric_proportion() -> None:
    payload = b"""{
      "analysisUTCTimestamp": "2026-07-30T17:00:00Z",
      "id": "https://example.com/blog/post",
      "lighthouseResult": {"categories": {"performance": {"id": "performance"}}},
      "loadingExperience": {
        "metrics": {
          "LARGEST_CONTENTFUL_PAINT_MS": {
            "distributions": [{"min": 0, "proportion": 1e999}]
          }
        }
      }
    }"""
    client = PageSpeedClient(
        _policy(),
        _api_key,
        lambda: httpx.MockTransport(lambda _: httpx.Response(200, content=payload)),
    )

    with pytest.raises(ProviderOperationError) as error:
        await client.analyze(
            _request(),
            "https://example.com/blog/",
            "https://example.com/blog/post",
            "MOBILE",
            (),
        )

    assert error.value.code is ProviderFailureCode.INVALID_RESPONSE


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    (
        {},
        {
            "analysisUTCTimestamp": "2026-07-30T17:00:00Z",
            "id": "",
            "lighthouseResult": {"categories": {"performance": {"id": "performance"}}},
        },
        {
            "analysisUTCTimestamp": "2026-07-30T17:00:00Z",
            "id": "https://example.com/blog/post",
            "lighthouseResult": {"categories": {}},
        },
        {
            "analysisUTCTimestamp": "2026-07-30T17:00:00Z",
            "id": "https://example.com/blog/post",
            "lighthouseResult": {"categories": {"": {"id": "performance"}}},
        },
        {
            "analysisUTCTimestamp": "not-a-time",
            "id": "https://example.com/blog/post",
            "lighthouseResult": {"categories": {"performance": {"id": "performance"}}},
        },
        {
            "analysisUTCTimestamp": "2026-07-30T17:00:00",
            "id": "https://example.com/blog/post",
            "lighthouseResult": {"categories": {"performance": {"id": "performance"}}},
        },
        {
            "analysisUTCTimestamp": "2026-07-30T17:00:00Z",
            "id": "https://example.com/blog/post",
            "lighthouseResult": {"categories": {"performance": {"id": ""}}},
        },
        {
            "analysisUTCTimestamp": "2026-07-30T17:00:00Z",
            "id": "https://example.com/blog/post",
            "lighthouseResult": {"categories": {"performance": {"id": "performance"}}},
            "loadingExperience": {"overall_category": ""},
        },
        {
            "analysisUTCTimestamp": "2026-07-30T17:00:00Z",
            "id": "https://example.com/blog/post",
            "lighthouseResult": {
                "categories": {"performance": {"id": "performance", "score": True}}
            },
        },
        {
            "analysisUTCTimestamp": "2026-07-30T17:00:00Z",
            "id": "https://example.com/blog/post",
            "lighthouseResult": {
                "categories": {"performance": {"id": "performance", "score": 1.1}}
            },
        },
        {
            "analysisUTCTimestamp": "2026-07-30T17:00:00Z",
            "id": "https://outside.example.com/post",
            "lighthouseResult": {
                "categories": {"performance": {"id": "performance", "score": 0.9}}
            },
        },
        {
            "analysisUTCTimestamp": "2026-07-30T17:00:00Z",
            "id": "https://example.com/blog/post",
            "lighthouseResult": {
                "categories": {
                    "performance": {"id": "performance", "score": 0.9},
                    "duplicate": {"id": "performance", "score": 0.8},
                }
            },
        },
        {
            "analysisUTCTimestamp": "2026-07-30T17:00:00Z",
            "id": "https://example.com/blog/post",
            "lighthouseResult": {"categories": {"performance": {"id": "performance"}}},
            "loadingExperience": {
                "metrics": {
                    "LARGEST_CONTENTFUL_PAINT_MS": {
                        "category": "X" * 33,
                        "distributions": [{"min": 0, "proportion": 1.0}],
                    }
                }
            },
        },
        {
            "analysisUTCTimestamp": "2026-07-30T17:00:00Z",
            "id": "https://example.com/blog/post",
            "lighthouseResult": {"categories": {"performance": {"id": "performance"}}},
            "loadingExperience": {
                "metrics": {
                    "LARGEST_CONTENTFUL_PAINT_MS": {
                        "distributions": [{"min": 2, "max": 1, "proportion": 1.0}],
                    }
                }
            },
        },
        {
            "analysisUTCTimestamp": "2026-07-30T17:00:00Z",
            "id": "https://example.com/blog/post",
            "lighthouseResult": {"categories": {"performance": {"id": "performance"}}},
            "loadingExperience": {
                "metrics": {
                    "LARGEST_CONTENTFUL_PAINT_MS": {
                        "metricId": "INTERACTION_TO_NEXT_PAINT",
                        "distributions": [{"min": 0, "proportion": 1.0}],
                    }
                }
            },
        },
        {
            "analysisUTCTimestamp": "2026-07-30T17:00:00Z",
            "id": "https://example.com/blog/post",
            "lighthouseResult": {"categories": {"performance": {"id": "performance"}}},
            "loadingExperience": {
                "metrics": {
                    "LARGEST_CONTENTFUL_PAINT_MS": {
                        "distributions": [
                            {"min": 0, "max": 1, "proportion": 0.25},
                            {"min": 1, "proportion": 0.25},
                        ]
                    }
                }
            },
        },
        {
            "analysisUTCTimestamp": "2026-07-30T17:00:00Z",
            "id": "https://example.com/blog/post",
            "lighthouseResult": {"categories": {"performance": {"id": "performance"}}},
            "loadingExperience": {
                "metrics": {
                    "LARGEST_CONTENTFUL_PAINT_MS": {
                        "metricId": "",
                        "distributions": [],
                    }
                }
            },
        },
        {
            "analysisUTCTimestamp": "2026-07-30T17:00:00Z",
            "id": "https://example.com/blog/post",
            "lighthouseResult": {"categories": {"performance": {"id": "performance"}}},
            "loadingExperience": {"metrics": {"": {"distributions": []}}},
        },
        _payload_with_excessive_field_metrics(),
    ),
)
async def test_pagespeed_rejects_invalid_typed_results(
    payload: object,
) -> None:
    client = PageSpeedClient(
        _policy(),
        _api_key,
        lambda: httpx.MockTransport(lambda _: httpx.Response(200, json=payload)),
    )

    with pytest.raises(ProviderOperationError) as error:
        await client.analyze(
            _request(),
            "https://example.com/blog/",
            "https://example.com/blog/post",
            "MOBILE",
            (),
        )

    assert error.value.code is ProviderFailureCode.INVALID_RESPONSE


@pytest.mark.asyncio
async def test_pagespeed_rejects_api_key_loader_failure_before_network() -> None:
    def failing_api_key_loader(_: Path) -> str:
        raise RuntimeError("private API key backend detail")

    client = PageSpeedClient(
        _policy(),
        failing_api_key_loader,
        lambda: pytest.fail("network must not be reached"),
    )
    with pytest.raises(ProviderOperationError) as error:
        await client.analyze(
            _request(),
            "https://example.com/blog/",
            "https://example.com/blog/post",
            "MOBILE",
            (),
        )
    assert error.value.code is ProviderFailureCode.AUTHENTICATION
    assert "private" not in str(error.value)


@pytest.mark.asyncio
async def test_pagespeed_preserves_safe_api_key_loader_failure_before_network() -> None:
    expected_error = ProviderOperationError(
        ProviderFailureCode.FORBIDDEN,
        "configured API key is forbidden",
    )

    def failing_api_key_loader(_: Path) -> str:
        raise expected_error

    client = PageSpeedClient(
        _policy(),
        failing_api_key_loader,
        lambda: pytest.fail("network must not be reached"),
    )
    with pytest.raises(ProviderOperationError) as error:
        await client.analyze(
            _request(),
            "https://example.com/blog/",
            "https://example.com/blog/post",
            "MOBILE",
            (),
        )
    assert error.value is expected_error
