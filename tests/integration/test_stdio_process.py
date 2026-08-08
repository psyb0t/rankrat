from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import TextContent


@pytest.mark.asyncio
async def test_stdio_process_persists_and_reads_monitor_state(tmp_path: Path) -> None:
    secret_root = tmp_path / "secrets"
    oauth_root = tmp_path / "oauth"
    state_root = tmp_path / "state"
    secret_root.mkdir(mode=0o700)
    oauth_root.mkdir(mode=0o700)
    state_root.mkdir(mode=0o700)
    boundary_file = tmp_path / "boundaries.json"
    boundary_file.write_text(
        json.dumps(
            {
                "accounts": [
                    {
                        "id": "pagespeed-main",
                        "provider": "google",
                        "credential": str(secret_root / "google-client.json"),
                        "pagespeed_sites": ["https://example.com/"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    environment = {
        **os.environ,
        "RANKRAT_BOUNDARY_FILE": str(boundary_file),
        "RANKRAT_SECRET_ROOT": str(secret_root),
        "RANKRAT_OAUTH_TOKEN_ROOT": str(oauth_root),
        "RANKRAT_LOG_FILE": str(tmp_path / "rankrat.log"),
        "RANKRAT_LIGHTHOUSE_WORKER_SOCKET": "",
        "RANKRAT_STATE_DATABASE": str(state_root / "rankrat.sqlite3"),
        "RANKRAT_READ_ONLY": "false",
    }
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "rankrat", "stdio"],
        env=environment,
    )

    async with (
        stdio_client(parameters) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream) as session,
    ):
        await session.initialize()
        catalog = {tool.name for tool in (await session.list_tools()).tools}
        assert "monitor_create" in catalog
        created = await session.call_tool(
            "monitor_create",
            {
                "name": "Daily audit",
                "account_id": "pagespeed-main",
                "site_url": "https://example.com/",
            },
        )
        listed = await session.call_tool(
            "monitors_list",
            {
                "account_id": "pagespeed-main",
                "site_url": "https://example.com/",
            },
        )

    assert created.isError is not True
    assert listed.isError is not True
    content = listed.content[0]
    assert isinstance(content, TextContent)
    listed_payload = json.loads(content.text)
    assert len(listed_payload["items"]) == 1
    assert listed_payload["items"][0]["name"] == "Daily audit"
    assert (state_root / "rankrat.sqlite3").is_file()
