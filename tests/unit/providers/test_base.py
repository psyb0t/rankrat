from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest

from rankrat.providers.base import (
    ProviderFailureCode,
    ProviderOperationError,
    read_limited_response,
)


class _CountingStream(httpx.AsyncByteStream):
    def __init__(self, chunks: tuple[bytes, ...]) -> None:
        self._chunks = chunks
        self.yielded = 0

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for chunk in self._chunks:
            self.yielded += 1
            yield chunk


@pytest.mark.asyncio
async def test_limited_response_stops_streaming_before_unbounded_buffering() -> None:
    stream = _CountingStream((b"123456", b"abcdef", b"must-not-be-read"))
    response = httpx.Response(200, stream=stream)

    with pytest.raises(ProviderOperationError) as raised:
        await read_limited_response(response, description="provider", maximum_bytes=10)

    assert raised.value.code is ProviderFailureCode.INVALID_RESPONSE
    assert stream.yielded == 2


@pytest.mark.asyncio
async def test_limited_response_rejects_oversized_header_without_reading_body() -> None:
    stream = _CountingStream((b"must-not-be-read",))
    response = httpx.Response(
        200,
        headers={"content-length": "11"},
        stream=stream,
    )

    with pytest.raises(ProviderOperationError) as raised:
        await read_limited_response(response, description="provider", maximum_bytes=10)

    assert raised.value.code is ProviderFailureCode.INVALID_RESPONSE
    assert stream.yielded == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("content_length", ("invalid", "-1"))
async def test_limited_response_rejects_invalid_content_length(content_length: str) -> None:
    response = httpx.Response(
        200,
        headers={"content-length": content_length},
        stream=_CountingStream((b"body",)),
    )

    with pytest.raises(ProviderOperationError) as raised:
        await read_limited_response(response, description="provider", maximum_bytes=10)

    assert raised.value.code is ProviderFailureCode.INVALID_RESPONSE


@pytest.mark.asyncio
async def test_limited_response_accepts_an_exactly_bounded_stream() -> None:
    response = httpx.Response(
        200,
        stream=_CountingStream((b"12345", b"67890")),
    )

    assert (
        await read_limited_response(
            response,
            description="provider",
            maximum_bytes=10,
        )
        == b"1234567890"
    )
