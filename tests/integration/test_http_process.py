from __future__ import annotations

import asyncio
import json
import os
import socket
import sys
from pathlib import Path

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.types import TextContent

_STARTUP_ATTEMPTS = 100
_STARTUP_DELAY_SECONDS = 0.1


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


async def _wait_until_healthy(base_url: str, process: asyncio.subprocess.Process) -> None:
    for _ in range(_STARTUP_ATTEMPTS):
        if process.returncode is not None:
            pytest.fail(f"rankrat http exited early with {process.returncode}")
        try:
            async with httpx.AsyncClient(timeout=1) as client:
                if (await client.get(f"{base_url}/healthz")).status_code == 200:
                    return
        except httpx.HTTPError:
            pass
        await asyncio.sleep(_STARTUP_DELAY_SECONDS)
    pytest.fail("rankrat http did not become healthy")


@pytest.mark.asyncio
async def test_http_process_persists_and_reads_monitor_state(tmp_path: Path) -> None:
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
    port = _free_port()
    environment = {
        **os.environ,
        "RANKRAT_BOUNDARY_FILE": str(boundary_file),
        "RANKRAT_SECRET_ROOT": str(secret_root),
        "RANKRAT_OAUTH_TOKEN_ROOT": str(oauth_root),
        "RANKRAT_LOG_FILE": str(tmp_path / "rankrat.log"),
        "RANKRAT_LIGHTHOUSE_WORKER_SOCKET": "",
        "RANKRAT_STATE_DATABASE": str(state_root / "rankrat.sqlite3"),
        "RANKRAT_READ_ONLY": "false",
        "RANKRAT_HTTP_HOST": "127.0.0.1",
        "RANKRAT_HTTP_PORT": str(port),
    }
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "rankrat",
        "http",
        env=environment,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    base_url = f"http://127.0.0.1:{port}"
    try:
        await _wait_until_healthy(base_url, process)
        async with (
            streamable_http_client(f"{base_url}/mcp") as (read_stream, write_stream, _),
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
    finally:
        process.terminate()
        await process.wait()

    assert created.isError is not True
    assert listed.isError is not True
    content = listed.content[0]
    assert isinstance(content, TextContent)
    listed_payload = json.loads(content.text)
    assert len(listed_payload["items"]) == 1
    assert listed_payload["items"][0]["name"] == "Daily audit"
    assert (state_root / "rankrat.sqlite3").is_file()
