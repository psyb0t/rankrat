from __future__ import annotations

import json

import httpx
import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from rankrat.config import Settings
from rankrat.providers.google_indexing import GoogleIndexingMetadata, GoogleIndexingPublishReceipt
from rankrat.providers.schema_fetch import SchemaFetchResult
from rankrat.services.bing import BingSiteApprovalRequest, BingSiteOperation
from rankrat.services.google_indexing import (
    GoogleIndexingApprovalRequest,
    GoogleIndexingBatchApprovalRequest,
    GoogleIndexingBatchNotification,
    GoogleIndexingNotificationType,
)
from rankrat.services.google_sitemaps import (
    GoogleSitemapApprovalRequest,
    GoogleSitemapOperation,
)
from rankrat.services.google_sites import GoogleSiteApprovalRequest, GoogleSiteOperation
from rankrat.transports.http import create_http_app
from rankrat.transports.mcp import build_mcp_server
from rankrat.transports.runtime import ApplicationServices


def _eligible_document(url: str) -> SchemaFetchResult:
    return SchemaFetchResult(
        url,
        "text/html",
        b'<script type="application/ld+json">{"@type":"JobPosting"}</script>',
    )


def _publish_receipt(url: str) -> GoogleIndexingPublishReceipt:
    return GoogleIndexingPublishReceipt(GoogleIndexingMetadata(url, None, None))


@pytest.mark.asyncio
async def test_http_google_indexing_requires_admin_approval_and_consumes_it_once(
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
        return _publish_receipt(url)

    monkeypatch.setattr(services.google_indexing._schema_fetcher, "fetch", fetch)
    monkeypatch.setattr(services.google_indexing._client, "publish", publish)
    app = create_http_app(settings, services)
    request = {
        "account_id": "google-main",
        "site_url": "sc-domain:example.com",
        "url": "https://example.com/jobs/one",
        "notification_type": "URL_UPDATED",
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://rankrat.test",
    ) as client:
        unauthorized = await client.post("/v1/admin/google-indexing-approvals", json=request)
        assert unauthorized.status_code == 401
        approval = await client.post(
            "/v1/admin/google-indexing-approvals",
            json=request,
            headers={"authorization": f"Bearer {'a' * 32}"},
        )
        assert approval.status_code == 200
        submission = await client.post(
            "/v1/google-indexing-submissions",
            json={**request, "approval_id": approval.json()["approval_id"]},
        )
        replay = await client.post(
            "/v1/google-indexing-submissions",
            json={**request, "approval_id": approval.json()["approval_id"]},
        )
        malformed = await client.post(
            "/v1/google-indexing-submissions",
            json={**request, "approval_id": "unused", "extra": True},
        )

    assert submission.status_code == 200
    assert submission.json() == {
        "metadata": {
            "url": "https://example.com/jobs/one",
            "latest_update": None,
            "latest_remove": None,
        }
    }
    assert replay.status_code == 400
    assert replay.json()["code"] == "REQUEST_REJECTED"
    assert malformed.status_code == 422
    assert published == [("google-main", "https://example.com/jobs/one", "URL_UPDATED")]


@pytest.mark.asyncio
async def test_mcp_google_indexing_exposes_only_consumer_tool(
    indexnow_deployment: tuple[Settings, ApplicationServices],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, services = indexnow_deployment
    assert services.google_indexing is not None
    published = False

    async def fetch(url: str, _: float) -> SchemaFetchResult:
        return _eligible_document(url)

    async def publish(*_: object) -> GoogleIndexingPublishReceipt:
        nonlocal published
        published = True
        return _publish_receipt("https://example.com/jobs/one")

    monkeypatch.setattr(services.google_indexing._schema_fetcher, "fetch", fetch)
    monkeypatch.setattr(services.google_indexing._client, "publish", publish)
    approval = await services.google_indexing.approve(
        GoogleIndexingApprovalRequest(
            "google-main",
            "sc-domain:example.com",
            "https://example.com/jobs/one",
            GoogleIndexingNotificationType.UPDATED,
        )
    )
    server = build_mcp_server(services)
    async with create_connected_server_and_client_session(server) as client:
        tools = await client.list_tools()
        tool = next(item for item in tools.tools if item.name == "google_indexing_submit")
        assert tool.annotations is not None
        assert tool.annotations.readOnlyHint is False
        assert tool.annotations.destructiveHint is True
        assert tool.inputSchema["required"] == [
            "account_id",
            "site_url",
            "url",
            "notification_type",
            "approval_id",
        ]
        result = await client.call_tool(
            "google_indexing_submit",
            {
                "account_id": "google-main",
                "site_url": "sc-domain:example.com",
                "url": "https://example.com/jobs/one",
                "notification_type": "URL_UPDATED",
                "approval_id": approval.approval_id,
            },
        )
        unknown = await client.call_tool("google_indexing_approve", {})

    assert json.loads(result.content[0].text) == {  # type: ignore[union-attr]
        "metadata": {
            "url": "https://example.com/jobs/one",
            "latest_update": None,
            "latest_remove": None,
        }
    }
    assert unknown.isError is True
    assert published is True


@pytest.mark.asyncio
async def test_http_and_mcp_google_indexing_batch_require_admin_approval(
    indexnow_deployment: tuple[Settings, ApplicationServices],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings, services = indexnow_deployment
    assert services.google_indexing is not None
    published: list[tuple[tuple[str, str], ...]] = []

    async def fetch(url: str, _: float) -> SchemaFetchResult:
        return _eligible_document(url)

    async def publish_batch(
        _: str,
        notifications: tuple[tuple[str, str], ...],
        __: float,
    ) -> tuple[object, ...]:
        published.append(notifications)
        return ()

    monkeypatch.setattr(services.google_indexing._schema_fetcher, "fetch", fetch)
    monkeypatch.setattr(services.google_indexing._client, "publish_batch", publish_batch)
    request = {
        "account_id": "google-main",
        "site_url": "sc-domain:example.com",
        "notifications": [
            {"url": "https://example.com/jobs/one", "notification_type": "URL_UPDATED"},
            {"url": "https://example.com/jobs/two", "notification_type": "URL_DELETED"},
        ],
    }
    app = create_http_app(settings, services)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://rankrat.test",
    ) as client:
        unauthorized = await client.post("/v1/admin/google-indexing-batch-approvals", json=request)
        approval = await client.post(
            "/v1/admin/google-indexing-batch-approvals",
            json=request,
            headers={"authorization": f"Bearer {'a' * 32}"},
        )
        rejected = await client.post(
            "/v1/google-indexing-batch-submissions",
            json={**request, "approval_id": approval.json()["approval_id"], "extra": True},
        )
        submission = await client.post(
            "/v1/google-indexing-batch-submissions",
            json={**request, "approval_id": approval.json()["approval_id"]},
        )

    assert unauthorized.status_code == 401
    assert approval.status_code == 200
    assert rejected.status_code == 422
    assert submission.status_code == 200
    assert submission.json() == {"receipts": [], "accepted_count": 0, "rejected_count": 0}

    approval = await services.google_indexing.approve_batch(
        GoogleIndexingBatchApprovalRequest(
            "google-main",
            "sc-domain:example.com",
            (
                GoogleIndexingBatchNotification(
                    "https://example.com/jobs/one", GoogleIndexingNotificationType.UPDATED
                ),
                GoogleIndexingBatchNotification(
                    "https://example.com/jobs/two", GoogleIndexingNotificationType.DELETED
                ),
            ),
        )
    )
    server = build_mcp_server(services)
    async with create_connected_server_and_client_session(server) as client:
        tools = await client.list_tools()
        tool = next(item for item in tools.tools if item.name == "google_indexing_batch_submit")
        assert tool.annotations is not None
        assert tool.annotations.readOnlyHint is False
        assert tool.annotations.destructiveHint is True
        result = await client.call_tool(
            "google_indexing_batch_submit",
            {**request, "approval_id": approval.approval_id},
        )

    assert json.loads(result.content[0].text) == {  # type: ignore[union-attr]
        "receipts": [],
        "accepted_count": 0,
        "rejected_count": 0,
    }
    assert published == [
        (
            ("https://example.com/jobs/one", "URL_UPDATED"),
            ("https://example.com/jobs/two", "URL_DELETED"),
        ),
        (
            ("https://example.com/jobs/one", "URL_UPDATED"),
            ("https://example.com/jobs/two", "URL_DELETED"),
        ),
    ]


@pytest.mark.asyncio
async def test_rest_and_mcp_google_sitemap_mutations_require_admin_approval(
    indexnow_deployment: tuple[Settings, ApplicationServices],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings, services = indexnow_deployment
    assert services.google_sitemaps is not None
    submitted: list[tuple[str, str]] = []
    deleted: list[tuple[str, str]] = []

    async def submit_sitemap(_: object, site_url: str, sitemap_url: str) -> None:
        submitted.append((site_url, sitemap_url))

    async def delete_sitemap(_: object, site_url: str, sitemap_url: str) -> None:
        deleted.append((site_url, sitemap_url))

    monkeypatch.setattr(services.google_sitemaps._client, "submit_sitemap", submit_sitemap)
    monkeypatch.setattr(services.google_sitemaps._client, "delete_sitemap", delete_sitemap)
    request = {
        "account_id": "google-main",
        "site_url": "sc-domain:example.com",
        "sitemap_url": "https://example.com/sitemap.xml",
        "operation": "submit",
    }
    app = create_http_app(settings, services)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://rankrat.test",
    ) as client:
        approval = await client.post(
            "/v1/admin/google-sitemap-approvals",
            json=request,
            headers={"authorization": f"Bearer {'a' * 32}"},
        )
        assert approval.status_code == 200
        response = await client.post(
            "/v1/google-sitemap-submissions",
            json={**request, "approval_id": approval.json()["approval_id"]},
        )
    assert response.status_code == 200
    assert response.json() == {
        "account_id": "google-main",
        "site_url": "sc-domain:example.com",
        "operation": "submit",
    }
    assert submitted == [("sc-domain:example.com", "https://example.com/sitemap.xml")]

    delete_approval = await services.google_sitemaps.approve(
        GoogleSitemapApprovalRequest(
            "google-main",
            "sc-domain:example.com",
            "https://example.com/sitemap.xml",
            GoogleSitemapOperation.DELETE,
        )
    )
    server = build_mcp_server(services)
    async with create_connected_server_and_client_session(server) as client:
        tools = await client.list_tools()
        tool = next(item for item in tools.tools if item.name == "google_sitemap_submit")
        assert tool.annotations is not None
        assert tool.annotations.readOnlyHint is False
        assert tool.annotations.destructiveHint is True
        result = await client.call_tool(
            "google_sitemap_submit",
            {
                "account_id": "google-main",
                "site_url": "sc-domain:example.com",
                "sitemap_url": "https://example.com/sitemap.xml",
                "operation": "delete",
                "approval_id": delete_approval.approval_id,
            },
        )
    assert json.loads(result.content[0].text)["operation"] == "delete"  # type: ignore[union-attr]
    assert deleted == [("sc-domain:example.com", "https://example.com/sitemap.xml")]


@pytest.mark.asyncio
async def test_rest_and_mcp_google_site_mutations_require_admin_approval(
    indexnow_deployment: tuple[Settings, ApplicationServices],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings, services = indexnow_deployment
    assert services.google_sites is not None
    added: list[str] = []
    deleted: list[str] = []

    async def add_site(_: object, site_url: str) -> None:
        added.append(site_url)

    async def delete_site(_: object, site_url: str) -> None:
        deleted.append(site_url)

    monkeypatch.setattr(services.google_sites._client, "add_site", add_site)
    monkeypatch.setattr(services.google_sites._client, "delete_site", delete_site)
    request = {
        "account_id": "google-main",
        "site_url": "sc-domain:example.com",
        "operation": "add",
    }
    app = create_http_app(settings, services)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://rankrat.test",
    ) as client:
        unauthorized = await client.post("/v1/admin/google-site-approvals", json=request)
        assert unauthorized.status_code == 401
        approval = await client.post(
            "/v1/admin/google-site-approvals",
            json=request,
            headers={"authorization": f"Bearer {'a' * 32}"},
        )
        assert approval.status_code == 200
        response = await client.post(
            "/v1/google-site-submissions",
            json={**request, "approval_id": approval.json()["approval_id"]},
        )
        replay = await client.post(
            "/v1/google-site-submissions",
            json={**request, "approval_id": approval.json()["approval_id"]},
        )

    assert response.status_code == 200
    assert response.json() == {
        "account_id": "google-main",
        "site_url": "sc-domain:example.com",
        "operation": "add",
    }
    assert replay.status_code == 400
    assert replay.json()["code"] == "REQUEST_REJECTED"
    assert added == ["sc-domain:example.com"]

    delete_approval = await services.google_sites.approve(
        GoogleSiteApprovalRequest(
            "google-main",
            "sc-domain:example.com",
            GoogleSiteOperation.DELETE,
        )
    )
    server = build_mcp_server(services)
    async with create_connected_server_and_client_session(server) as client:
        tools = await client.list_tools()
        tool = next(item for item in tools.tools if item.name == "google_site_submit")
        assert tool.annotations is not None
        assert tool.annotations.readOnlyHint is False
        assert tool.annotations.destructiveHint is True
        result = await client.call_tool(
            "google_site_submit",
            {
                "account_id": "google-main",
                "site_url": "sc-domain:example.com",
                "operation": "delete",
                "approval_id": delete_approval.approval_id,
            },
        )
        unknown = await client.call_tool("google_site_approve", {})
    assert json.loads(result.content[0].text)["operation"] == "delete"  # type: ignore[union-attr]
    assert unknown.isError is True
    assert deleted == ["sc-domain:example.com"]


@pytest.mark.asyncio
async def test_rest_and_mcp_bing_site_mutations_require_admin_approval(
    indexnow_deployment: tuple[Settings, ApplicationServices],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings, services = indexnow_deployment
    added: list[str] = []
    removed: list[str] = []

    async def add_site(_: object, site_url: str) -> None:
        added.append(site_url)

    async def remove_site(_: object, site_url: str) -> None:
        removed.append(site_url)

    monkeypatch.setattr(services.bing_webmaster._client, "add_site", add_site)
    monkeypatch.setattr(services.bing_webmaster._client, "remove_site", remove_site)
    request = {
        "account_id": "bing-main",
        "site_url": "https://example.com/",
        "operation": "add",
    }
    app = create_http_app(settings, services)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://rankrat.test",
    ) as client:
        unauthorized = await client.post("/v1/admin/bing-site-approvals", json=request)
        assert unauthorized.status_code == 401
        approval = await client.post(
            "/v1/admin/bing-site-approvals",
            json=request,
            headers={"authorization": f"Bearer {'a' * 32}"},
        )
        assert approval.status_code == 200
        response = await client.post(
            "/v1/bing-site-submissions",
            json={**request, "approval_id": approval.json()["approval_id"]},
        )
        replay = await client.post(
            "/v1/bing-site-submissions",
            json={**request, "approval_id": approval.json()["approval_id"]},
        )

    assert response.status_code == 200
    assert response.json() == {
        "account_id": "bing-main",
        "site_url": "https://example.com/",
        "operation": "add",
    }
    assert replay.status_code == 400
    assert replay.json()["code"] == "REQUEST_REJECTED"
    assert added == ["https://example.com/"]

    delete_approval = await services.bing_webmaster.approve_site_submission(
        BingSiteApprovalRequest(
            "bing-main",
            "https://example.com/",
            BingSiteOperation.DELETE,
        )
    )
    server = build_mcp_server(services)
    async with create_connected_server_and_client_session(server) as client:
        tools = await client.list_tools()
        tool = next(item for item in tools.tools if item.name == "bing_site_submit")
        assert tool.annotations is not None
        assert tool.annotations.readOnlyHint is False
        assert tool.annotations.destructiveHint is True
        result = await client.call_tool(
            "bing_site_submit",
            {
                "account_id": "bing-main",
                "site_url": "https://example.com/",
                "operation": "delete",
                "approval_id": delete_approval.approval_id,
            },
        )
        unknown = await client.call_tool("bing_site_approve", {})
    assert json.loads(result.content[0].text)["operation"] == "delete"  # type: ignore[union-attr]
    assert unknown.isError is True
    assert removed == ["https://example.com/"]
