from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from rankrat.constants import INDEXNOW_ENDPOINT_URL, MAX_PROVIDER_RESPONSE_BYTES
from rankrat.errors import BoundaryDeniedError
from rankrat.models.boundaries import BoundaryDocument
from rankrat.policy.boundaries import BoundaryPolicy
from rankrat.providers.base import (
    IndexNowSubmitRequest,
    IndexNowTargetId,
    ProviderFailureCode,
    ProviderOperationError,
)
from rankrat.providers.indexnow import IndexNowClient


def _policy(
    key_file: Path,
    key_location: str = "https://example.com/keys/indexnow-key.txt",
) -> BoundaryPolicy:
    return BoundaryPolicy(
        BoundaryDocument.model_validate(
            {
                "indexnow_targets": [
                    {
                        "id": "site-main",
                        "host": "example.com",
                        "key_location": key_location,
                        "key_file": str(key_file),
                    }
                ]
            }
        )
    )


def _request(*urls: str) -> IndexNowSubmitRequest:
    return IndexNowSubmitRequest(IndexNowTargetId("site-main"), tuple(urls), 1.0)


@pytest.mark.asyncio
async def test_submit_uses_fixed_endpoint_and_redacts_key_from_result(tmp_path: Path) -> None:
    key_file = tmp_path / "indexnow-key"
    key_file.write_text("test-indexnow-key", encoding="utf-8")

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == httpx.URL(INDEXNOW_ENDPOINT_URL)
        assert request.headers["content-type"] == "application/json"
        assert json.loads(request.content) == {
            "host": "example.com",
            "key": "test-indexnow-key",
            "keyLocation": "https://example.com/keys/indexnow-key.txt",
            "urlList": ["https://example.com/keys/article?a=b"],
        }
        return httpx.Response(202)

    client = IndexNowClient(_policy(key_file), lambda: httpx.MockTransport(handler))
    result = await client.submit(
        _request("https://Example.COM:443/keys/article?a=b", "https://example.com/keys/article?a=b")
    )

    assert result.target_id == "site-main"
    assert result.host == "example.com"
    assert result.submitted_count == 1
    assert result.key_validation_pending is True
    assert "test-indexnow-key" not in repr(result)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    (
        "http://example.com/keys/article",
        "https://attacker.example/keys/article",
        "https://example.com/other/article",
        "https://example.com/keys-evil/article",
        "https://example.com/keys/../article",
        "https://example.com/keys/%2farticle",
        "https://example.com/keys/%5Carticle",
        "https://user@example.com/keys/article",
        "https://example.com/keys/article#fragment",
        "https://example.com:444/keys/article",
    ),
)
async def test_submit_rejects_urls_outside_immutable_target_before_network(
    tmp_path: Path,
    url: str,
) -> None:
    key_file = tmp_path / "indexnow-key"
    key_file.write_text("test-indexnow-key", encoding="utf-8")
    client = IndexNowClient(
        _policy(key_file),
        lambda: pytest.fail("IndexNow network must not be reached"),
    )

    with pytest.raises(BoundaryDeniedError):
        await client.submit(_request(url))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "expected"),
    (
        (200, None),
        (403, ProviderFailureCode.FORBIDDEN),
        (429, ProviderFailureCode.RATE_LIMITED),
        (500, ProviderFailureCode.UNAVAILABLE),
        (400, ProviderFailureCode.INVALID_RESPONSE),
    ),
)
async def test_submit_maps_safe_statuses(
    tmp_path: Path,
    status_code: int,
    expected: ProviderFailureCode | None,
) -> None:
    key_file = tmp_path / "indexnow-key"
    key_file.write_text("test-indexnow-key", encoding="utf-8")
    client = IndexNowClient(
        _policy(key_file),
        lambda: httpx.MockTransport(lambda _: httpx.Response(status_code, text="private upstream")),
    )
    if expected is None:
        result = await client.submit(_request("https://example.com/keys/article"))
        assert result.key_validation_pending is False
        return
    with pytest.raises(ProviderOperationError) as error:
        await client.submit(_request("https://example.com/keys/article"))
    assert error.value.code is expected
    assert "private" not in str(error.value)


@pytest.mark.asyncio
async def test_submit_maps_transport_and_response_size_failures(tmp_path: Path) -> None:
    key_file = tmp_path / "indexnow-key"
    key_file.write_text("test-indexnow-key", encoding="utf-8")
    responses = iter(
        (
            httpx.Response(200, headers={"content-length": str(MAX_PROVIDER_RESPONSE_BYTES + 1)}),
            httpx.Response(200, content=b"x" * (MAX_PROVIDER_RESPONSE_BYTES + 1)),
        )
    )
    client = IndexNowClient(
        _policy(key_file),
        lambda: httpx.MockTransport(lambda _: next(responses)),
    )
    for _ in range(2):
        with pytest.raises(ProviderOperationError) as error:
            await client.submit(_request("https://example.com/keys/article"))
        assert error.value.code is ProviderFailureCode.INVALID_RESPONSE

    offline = IndexNowClient(
        _policy(key_file),
        lambda: httpx.MockTransport(lambda _: (_ for _ in ()).throw(httpx.ConnectError("private"))),
    )
    with pytest.raises(ProviderOperationError) as error:
        await offline.submit(_request("https://example.com/keys/article"))
    assert error.value.code is ProviderFailureCode.UNAVAILABLE
    assert "private" not in str(error.value)

    class _LargeResponseStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b"x" * (MAX_PROVIDER_RESPONSE_BYTES + 1)

        async def aclose(self) -> None:
            return None

    oversized_stream = IndexNowClient(
        _policy(key_file),
        lambda: httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                headers={"content-length": "unknown"},
                stream=_LargeResponseStream(),
            )
        ),
    )
    with pytest.raises(ProviderOperationError) as error:
        await oversized_stream.submit(_request("https://example.com/keys/article"))
    assert error.value.code is ProviderFailureCode.INVALID_RESPONSE

    timeout = IndexNowClient(
        _policy(key_file),
        lambda: httpx.MockTransport(lambda _: (_ for _ in ()).throw(httpx.ReadTimeout("private"))),
    )
    with pytest.raises(ProviderOperationError) as error:
        await timeout.submit(_request("https://example.com/keys/article"))
    assert error.value.code is ProviderFailureCode.TIMEOUT


@pytest.mark.asyncio
async def test_submit_rejects_missing_or_invalid_key_material(tmp_path: Path) -> None:
    missing = tmp_path / "missing"
    client = IndexNowClient(_policy(missing), lambda: pytest.fail("network must not be reached"))
    with pytest.raises(ProviderOperationError) as error:
        await client.submit(_request("https://example.com/keys/article"))
    assert error.value.code is ProviderFailureCode.AUTHENTICATION

    invalid = tmp_path / "invalid"
    invalid.write_text("not a key", encoding="utf-8")
    client = IndexNowClient(_policy(invalid), lambda: pytest.fail("network must not be reached"))
    with pytest.raises(ProviderOperationError) as error:
        await client.submit(_request("https://example.com/keys/article"))
    assert error.value.code is ProviderFailureCode.AUTHENTICATION


def test_url_normalization_rejects_empty_malformed_and_invalid_unicode_hosts() -> None:
    with pytest.raises(BoundaryDeniedError):
        IndexNowClient._normalize_urls((), "example.com", "https://example.com/keys/key.txt")
    for url in ("", "https://example.com:invalid/keys/article"):
        with pytest.raises(BoundaryDeniedError):
            IndexNowClient._normalize_url(url, "example.com", "/keys")
    with pytest.raises(BoundaryDeniedError):
        IndexNowClient._normalize_url(
            f"https://{chr(0xD800)}.example/keys/article",
            "example.com",
            "/keys",
        )
