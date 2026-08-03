from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest

from rankrat.transports import stdio


class _Server:
    def __init__(self) -> None:
        self.received: tuple[object, object, object] | None = None

    def create_initialization_options(self, **kwargs: object) -> object:
        return kwargs

    async def run(self, read_stream: object, write_stream: object, options: object) -> None:
        self.received = (read_stream, write_stream, options)


@pytest.mark.asyncio
async def test_stdio_runner_connects_mcp_streams_and_initialization_options(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    read_stream = object()
    write_stream = object()

    @asynccontextmanager
    async def local_stdio_server() -> AsyncIterator[tuple[object, object]]:
        yield read_stream, write_stream

    monkeypatch.setattr(stdio.mcp.server.stdio, "stdio_server", local_stdio_server)
    server = _Server()
    await stdio.run_stdio(server)  # type: ignore[arg-type]
    assert server.received is not None
    assert server.received[:2] == (read_stream, write_stream)
