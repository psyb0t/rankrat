from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from rankrat.constants import MAX_GOOGLE_INDEXING_BATCH_PART_RESPONSE_BYTES
from rankrat.models.boundaries import BoundaryDocument
from rankrat.policy.boundaries import BoundaryPolicy
from rankrat.providers import google_indexing as google_indexing
from rankrat.providers.base import ProviderFailureCode, ProviderOperationError
from rankrat.providers.google_indexing import (
    URL_DELETED,
    URL_UPDATED,
    GoogleIndexingClient,
    GoogleIndexingMetadata,
    GoogleIndexingNotification,
    GoogleIndexingNotificationType,
    GoogleIndexingPublishReceipt,
)
from rankrat.providers.google_search_console import (
    GoogleIndexingBatchPartResponse,
    GoogleSearchConsoleClient,
    HttpTransportFactory,
)


async def _token(credential_path: Path) -> str:
    del credential_path
    return "test-token"


def _client(transport_factory: HttpTransportFactory) -> GoogleIndexingClient:
    policy = BoundaryPolicy(
        BoundaryDocument.model_validate(
            {
                "accounts": [
                    {
                        "id": "google-main",
                        "provider": "google",
                        "credential": "/run/secrets/google.json",
                        "search_console_sites": ["https://example.com/"],
                    }
                ]
            }
        )
    )
    return GoogleIndexingClient(GoogleSearchConsoleClient(policy, _token, transport_factory))


def _batch_response(
    boundary: str,
    parts: tuple[tuple[int, str], ...],
) -> bytes:
    output: list[bytes] = []
    for index, (status, body) in enumerate(parts):
        output.extend(
            (
                f"--{boundary}\r\n".encode(),
                b"Content-Type: application/http\r\n",
                f"Content-ID: <response-rankrat-{index}>\r\n\r\n".encode(),
                f"HTTP/1.1 {status} Result\r\nContent-Type: application/json\r\n\r\n".encode(),
                body.encode(),
                b"\r\n",
            )
        )
    output.append(f"--{boundary}--\r\n".encode())
    return b"".join(output)


def _one_response_part(
    boundary: str,
    content_id: str | None,
    payload: bytes,
    content_type: str = "application/http",
) -> bytes:
    content_id_header = b"" if content_id is None else f"Content-ID: {content_id}\r\n".encode()
    return (
        f"--{boundary}\r\nContent-Type: {content_type}\r\n".encode()
        + content_id_header
        + b"\r\n"
        + payload
        + f"\r\n--{boundary}--\r\n".encode()
    )


@pytest.mark.asyncio
async def test_google_indexing_publish_uses_fixed_origin_and_safe_payload() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert str(request.url) == "https://indexing.googleapis.com/v3/urlNotifications:publish"
        assert request.headers["Authorization"] == "Bearer test-token"
        assert json.loads(request.content) == {
            "url": "https://example.com/post",
            "type": URL_UPDATED,
        }
        return httpx.Response(
            200,
            json={
                "urlNotificationMetadata": {
                    "url": "https://example.com/post",
                    "latestUpdate": {
                        "url": "https://example.com/post",
                        "type": "URL_UPDATED",
                        "notifyTime": "2026-07-30T19:00:00Z",
                    },
                }
            },
        )

    result = await _client(lambda: httpx.MockTransport(handler)).publish(
        "google-main",
        "https://example.com/post",
        URL_UPDATED,
        1.0,
    )
    assert result == GoogleIndexingPublishReceipt(
        GoogleIndexingMetadata(
            url="https://example.com/post",
            latest_update=GoogleIndexingNotification(
                "https://example.com/post",
                GoogleIndexingNotificationType.UPDATED,
                "2026-07-30T19:00:00Z",
            ),
            latest_remove=None,
        )
    )


@pytest.mark.asyncio
async def test_google_indexing_rejects_unsupported_notification_without_network() -> None:
    with pytest.raises(ValueError):
        await _client(lambda: pytest.fail("network must not run")).publish(
            "google-main",
            "https://example.com/post",
            "ARBITRARY",
            1.0,
        )


@pytest.mark.asyncio
async def test_google_indexing_metadata_uses_fixed_encoded_get_origin() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert str(request.url) == (
            "https://indexing.googleapis.com/v3/urlNotifications/metadata?"
            "url=https%3A%2F%2Fexample.com%2Fpost%3Fa%3D1%26b%3D2"
        )
        assert request.headers["Authorization"] == "Bearer test-token"
        return httpx.Response(
            200,
            json={"url": "https://example.com/post?a=1&b=2"},
        )

    result = await _client(lambda: httpx.MockTransport(handler)).metadata(
        "google-main",
        "https://example.com/post?a=1&b=2",
        1.0,
    )

    assert result == GoogleIndexingMetadata(
        url="https://example.com/post?a=1&b=2",
        latest_update=None,
        latest_remove=None,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("publish", "response_body"),
    (
        (
            True,
            {
                "urlNotificationMetadata": {
                    "url": "https://example.com/post",
                    "latestUpdate": {
                        "url": "https://example.com/post",
                        "type": URL_DELETED,
                    },
                }
            },
        ),
        (
            False,
            {
                "url": "https://example.com/post",
                "latestRemove": {
                    "url": "https://example.com/post",
                    "type": URL_UPDATED,
                },
            },
        ),
        (
            False,
            {
                "url": "https://example.com/post",
                "latestUpdate": {
                    "url": "https://example.com/post",
                    "type": URL_UPDATED,
                    "notifyTime": "not-a-timestamp",
                },
            },
        ),
        (False, {"url": "https://example.com/other"}),
    ),
)
async def test_google_indexing_rejects_invalid_typed_receipts(
    publish: bool,
    response_body: dict[str, object],
) -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=response_body)

    client = _client(lambda: httpx.MockTransport(handler))
    with pytest.raises(ProviderOperationError) as error:
        if publish:
            await client.publish("google-main", "https://example.com/post", URL_UPDATED, 1.0)
        else:
            await client.metadata("google-main", "https://example.com/post", 1.0)
    assert error.value.code is ProviderFailureCode.INVALID_RESPONSE


@pytest.mark.parametrize(
    "payload",
    (
        {
            "url": "https://example.com/post",
            "latestUpdate": {"url": "https://example.com/post", "type": 1},
        },
        {
            "url": "https://example.com/post",
            "latestUpdate": {"url": "https://example.com/other", "type": URL_UPDATED},
        },
        {
            "url": "https://example.com/post",
            "latestRemove": {"url": "https://example.com/other", "type": URL_DELETED},
        },
        {
            "url": "https://example.com/post",
            "latestUpdate": {"url": "https://example.com/post", "type": URL_DELETED},
        },
        {
            "url": "https://example.com/post",
            "latestRemove": {"url": "https://example.com/post", "type": URL_UPDATED},
        },
        {
            "url": "https://example.com/post",
            "latestUpdate": {
                "url": "https://example.com/post",
                "type": URL_UPDATED,
                "notifyTime": "2026-07-30T19:00:00",
            },
        },
    ),
)
def test_google_indexing_internal_metadata_validation_rejects_untrusted_variants(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValueError, match="invalid notification metadata"):
        google_indexing._metadata(payload, "https://example.com/post")


def test_google_indexing_private_notification_validators_reject_unknown_types() -> None:
    with pytest.raises(ValueError, match="unsupported"):
        google_indexing._GoogleIndexingNotificationResponse.validate_notification_type(
            "UNKNOWN_NOTIFICATION"
        )
    assert google_indexing._GoogleIndexingNotificationResponse.validate_notify_time(None) is None


@pytest.mark.asyncio
async def test_google_indexing_batch_uses_fixed_multipart_origin_and_orders_partial_receipts() -> (
    None
):
    response_boundary = "google-response"

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert str(request.url) == "https://indexing.googleapis.com/batch"
        assert request.headers["Authorization"] == "Bearer test-token"
        content_type = request.headers["Content-Type"]
        assert content_type.startswith("multipart/mixed; boundary=rankrat-")
        assert request.content.count(b"POST /v3/urlNotifications:publish HTTP/1.1") == 2
        assert b'{"url":"https://example.com/one","type":"URL_UPDATED"}' in request.content
        assert b'{"url":"https://example.com/two","type":"URL_DELETED"}' in request.content
        return httpx.Response(
            200,
            headers={"Content-Type": f"multipart/mixed; boundary={response_boundary}"},
            content=_batch_response(
                response_boundary,
                ((200, "{}"), (429, '{"error":{"message":"never exposed"}}')),
            ),
        )

    receipts = await _client(lambda: httpx.MockTransport(handler)).publish_batch(
        "google-main",
        (("https://example.com/one", URL_UPDATED), ("https://example.com/two", URL_DELETED)),
        1.0,
    )

    assert [(receipt.url, receipt.accepted, receipt.failure_code) for receipt in receipts] == [
        ("https://example.com/one", True, None),
        ("https://example.com/two", False, ProviderFailureCode.RATE_LIMITED),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("response_boundary", "response_body", "expected_message"),
    (
        ("bad", b"not a multipart response", "invalid multipart"),
        (
            "bad-id",
            b"--bad-id\r\nContent-Type: application/http\r\n"
            b"Content-ID: <response-rankrat-1>\r\n\r\n"
            b"HTTP/1.1 200 Result\r\n\r\n{}\r\n--bad-id--\r\n",
            "unknown content ID",
        ),
        (
            "bad-status",
            b"--bad-status\r\nContent-Type: application/http\r\n"
            b"Content-ID: <response-rankrat-0>\r\n\r\n"
            b"not-http\r\n\r\n{}\r\n--bad-status--\r\n",
            "invalid response status",
        ),
        (
            "bad-json",
            b"--bad-json\r\nContent-Type: application/http\r\n"
            b"Content-ID: <response-rankrat-0>\r\n\r\n"
            b"HTTP/1.1 200 Result\r\n\r\nnot-json\r\n--bad-json--\r\n",
            "invalid JSON",
        ),
    ),
)
async def test_google_indexing_batch_rejects_malformed_provider_parts(
    response_boundary: str,
    response_body: bytes,
    expected_message: str,
) -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        content_type = (
            "text/plain"
            if response_boundary == "bad"
            else f"multipart/mixed; boundary={response_boundary}"
        )
        return httpx.Response(200, headers={"Content-Type": content_type}, content=response_body)

    with pytest.raises(ProviderOperationError, match=expected_message) as error:
        await _client(lambda: httpx.MockTransport(handler)).publish_batch(
            "google-main",
            (("https://example.com/one", URL_UPDATED),),
            1.0,
        )
    assert error.value.code is ProviderFailureCode.INVALID_RESPONSE


@pytest.mark.asyncio
async def test_google_indexing_batch_rejects_empty_or_unsupported_input_without_network() -> None:
    client = _client(lambda: pytest.fail("network must not run"))
    with pytest.raises(ValueError, match="must include"):
        await client.publish_batch("google-main", (), 1.0)
    with pytest.raises(ValueError, match="unsupported"):
        await client.publish_batch(
            "google-main",
            (("https://example.com/one", "ARBITRARY"),),
            1.0,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("exception", "expected_code", "unsafe_detail"),
    (
        (
            httpx.ReadTimeout("attacker-timeout-detail"),
            ProviderFailureCode.TIMEOUT,
            "attacker-timeout-detail",
        ),
        (
            httpx.ConnectError("attacker-network-detail"),
            ProviderFailureCode.UNAVAILABLE,
            "attacker-network-detail",
        ),
    ),
)
async def test_google_indexing_batch_redacts_transport_failures(
    exception: httpx.HTTPError,
    expected_code: ProviderFailureCode,
    unsafe_detail: str,
) -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        raise exception

    with pytest.raises(ProviderOperationError) as error:
        await _client(lambda: httpx.MockTransport(handler)).publish_batch(
            "google-main",
            (("https://example.com/one", URL_UPDATED),),
            1.0,
        )
    assert error.value.code is expected_code
    assert unsafe_detail not in str(error.value)


@pytest.mark.asyncio
async def test_google_indexing_batch_rejects_missing_outer_content_type() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"ignored")

    with pytest.raises(ProviderOperationError, match="invalid content type") as error:
        await _client(lambda: httpx.MockTransport(handler)).publish_batch(
            "google-main",
            (("https://example.com/one", URL_UPDATED),),
            1.0,
        )
    assert error.value.code is ProviderFailureCode.INVALID_RESPONSE


@pytest.mark.parametrize(
    ("body", "expected_parts", "expected_message"),
    (
        (
            _one_response_part(
                "wrong-part",
                "<response-rankrat-0>",
                b"HTTP/1.1 200 Result\r\n\r\n{}",
                "text/plain",
            ),
            1,
            "invalid response part",
        ),
        (
            _one_response_part(
                "missing-id",
                None,
                b"HTTP/1.1 200 Result\r\n\r\n{}",
            ),
            1,
            "omitted a content ID",
        ),
        (
            _one_response_part(
                "unbracketed-id",
                "response-rankrat-0",
                b"HTTP/1.1 200 Result\r\n\r\n{}",
            ),
            1,
            "invalid content ID",
        ),
        (
            _one_response_part(
                "bad-suffix",
                "<response-rankrat-nope>",
                b"HTTP/1.1 200 Result\r\n\r\n{}",
            ),
            1,
            "invalid content ID",
        ),
        (
            _one_response_part(
                "unknown-prefix",
                "<response-not-rankrat-0>",
                b"HTTP/1.1 200 Result\r\n\r\n{}",
            ),
            1,
            "unknown content ID",
        ),
        (
            _one_response_part(
                "bad-part-body",
                "<response-rankrat-0>",
                b"HTTP/1.1 200 Result\r\n\r\n"
                + b"x" * (MAX_GOOGLE_INDEXING_BATCH_PART_RESPONSE_BYTES + 1),
            ),
            1,
            "oversized response part",
        ),
        (
            _one_response_part(
                "no-separator",
                "<response-rankrat-0>",
                b"HTTP/1.1 200 Result",
            ),
            1,
            "invalid response part",
        ),
        (
            _one_response_part(
                "bad-range",
                "<response-rankrat-0>",
                b"HTTP/1.1 700 Result\r\n\r\n{}",
            ),
            1,
            "invalid response status",
        ),
        (
            _one_response_part(
                "json-list",
                "<response-rankrat-0>",
                b"HTTP/1.1 200 Result\r\n\r\n[]",
            ),
            1,
            "invalid response part",
        ),
        (
            _batch_response("duplicate", ((200, "{}"), (200, "{}"))).replace(
                b"response-rankrat-1",
                b"response-rankrat-0",
            ),
            2,
            "duplicate response parts",
        ),
        (
            _one_response_part(
                "incomplete",
                "<response-rankrat-0>",
                b"HTTP/1.1 200 Result\r\n\r\n{}",
            ),
            2,
            "incomplete response",
        ),
    ),
)
def test_google_indexing_batch_parser_rejects_each_untrusted_part_boundary(
    body: bytes,
    expected_parts: int,
    expected_message: str,
) -> None:
    boundary = body.split(b"\r\n", maxsplit=1)[0].removeprefix(b"--").decode()
    with pytest.raises(ProviderOperationError, match=expected_message) as error:
        GoogleSearchConsoleClient._parse_indexing_batch_response(
            f"multipart/mixed; boundary={boundary}",
            body,
            expected_parts,
        )
    assert error.value.code is ProviderFailureCode.INVALID_RESPONSE


def test_google_indexing_batch_maps_unavailable_part_without_exposing_provider_body() -> None:
    receipt = GoogleIndexingClient._batch_receipt(
        ("https://example.com/one", URL_UPDATED),
        GoogleIndexingBatchPartResponse(0, 503),
    )
    assert receipt.accepted is False
    assert receipt.failure_code is ProviderFailureCode.UNAVAILABLE
