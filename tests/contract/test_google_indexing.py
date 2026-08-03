from __future__ import annotations

import json

import httpx
import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from rankrat.config import Settings
from rankrat.providers.google_indexing import GoogleIndexingMetadata, GoogleIndexingPublishReceipt
from rankrat.providers.schema_fetch import SchemaFetchResult
from rankrat.transports.http import create_http_app
from rankrat.transports.mcp import build_mcp_server
from rankrat.transports.runtime import ApplicationServices

_REQUEST = {
    "account_id": "google-main",
    "site_url": "sc-domain:example.com",
    "url": "https://example.com/jobs/one",
    "notification_type": "URL_UPDATED",
}


def _eligible_document(url: str) -> SchemaFetchResult:
    return SchemaFetchResult(
        url,
        "text/html",
        b'<script type="application/ld+json">{"@type":"JobPosting"}</script>',
    )


@pytest.mark.asyncio
async def test_google_indexing_write_is_absent_from_read_only_http_and_mcp(
    deployment: tuple[Settings, ApplicationServices],
) -> None:
    settings, services = deployment
    app = create_http_app(settings, services)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://rankrat.test",
    ) as client:
        assert (
            await client.post("/v1/google-indexing-submissions", json=_REQUEST)
        ).status_code == 404
    server = build_mcp_server(services)
    async with create_connected_server_and_client_session(server) as client:
        tools = await client.list_tools()
        assert "google_indexing_submit" not in {tool.name for tool in tools.tools}


@pytest.mark.asyncio
async def test_google_indexing_write_is_direct_and_rejects_the_removed_field(
    indexnow_deployment: tuple[Settings, ApplicationServices],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings, services = indexnow_deployment
    assert services.google_indexing is not None
    published: list[tuple[str, str, str]] = []

    async def fetch(url: str, _: float) -> SchemaFetchResult:
        return _eligible_document(url)

    async def publish(
        account_id: str,
        url: str,
        notification_type: str,
        _: float,
    ) -> GoogleIndexingPublishReceipt:
        published.append((account_id, url, notification_type))
        return GoogleIndexingPublishReceipt(GoogleIndexingMetadata(url, None, None))

    monkeypatch.setattr(services.google_indexing._schema_fetcher, "fetch", fetch)
    monkeypatch.setattr(services.google_indexing._client, "publish", publish)
    app = create_http_app(settings, services)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://rankrat.test",
    ) as client:
        rejected = await client.post(
            "/v1/google-indexing-submissions",
            json={**_REQUEST, "unexpected_legacy_field": "rejected"},
        )
        submitted = await client.post("/v1/google-indexing-submissions", json=_REQUEST)
    assert rejected.status_code == 422
    assert submitted.status_code == 200
    assert published == [("google-main", "https://example.com/jobs/one", "URL_UPDATED")]

    server = build_mcp_server(services)
    async with create_connected_server_and_client_session(server) as client:
        tools = await client.list_tools()
        tool = next(item for item in tools.tools if item.name == "google_indexing_submit")
        assert "unexpected_legacy_field" not in tool.inputSchema.get("properties", {})
        result = await client.call_tool("google_indexing_submit", _REQUEST)
    assert json.loads(result.content[0].text)["metadata"]["url"] == _REQUEST["url"]  # type: ignore[union-attr]
