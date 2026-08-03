"""Stdio MCP runner; protocol output stays exclusively on stdout."""

from __future__ import annotations

import mcp.server.stdio
from mcp.server.lowlevel import NotificationOptions, Server


async def run_stdio(server: Server[object, object]) -> None:
    """Serve the low-level MCP application over standard input and output."""
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(
                notification_options=NotificationOptions(),
                experimental_capabilities={},
            ),
        )
