from __future__ import annotations

import json

import httpx
import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from rankrat.config import Settings
from rankrat.constants import (
    BING_CONTENT_SUBMISSION_OPERATION,
    CLARITY_INSIGHTS_OPERATION,
    EDGE_REDIRECT_DELETE_OPERATION,
    EDGE_REDIRECT_UPSERT_OPERATION,
    EDGE_REDIRECTS_LIST_OPERATION,
    GTM_ACCOUNTS_LIST_OPERATION,
    GTM_CONTAINERS_CREATE_OPERATION,
    GTM_CONTAINERS_DELETE_OPERATION,
    GTM_CONTAINERS_LIST_OPERATION,
    GTM_ENTITIES_CREATE_OPERATION,
    GTM_ENTITIES_DELETE_OPERATION,
    GTM_ENTITIES_LIST_OPERATION,
    GTM_ENTITIES_UPDATE_OPERATION,
    GTM_VERSION_PUBLISH_OPERATION,
    GTM_WORKSPACE_VERSION_CREATE_OPERATION,
    GTM_WORKSPACES_CREATE_OPERATION,
    GTM_WORKSPACES_DELETE_OPERATION,
    GTM_WORKSPACES_LIST_OPERATION,
)
from rankrat.providers.clarity import ClarityDimension, ClarityMetric
from rankrat.providers.cloudflare_performance import (
    CloudflareEdgeRedirect,
    CloudflareEdgeRedirectReceipt,
    CloudflareRedirectStatus,
)
from rankrat.providers.google_tag_manager import (
    GtmAccount,
    GtmContainer,
    GtmEntity,
    GtmEntityKind,
    GtmVersion,
    GtmWorkspace,
)
from rankrat.services.bing_content import BingContentSubmissionReceipt
from rankrat.services.clarity import ClarityInsightsReport
from rankrat.transports.http import create_http_app
from rankrat.transports.mcp import build_mcp_server
from rankrat.transports.runtime import ApplicationServices

_RULE_ID = "b" * 32
_GTM_ACCOUNT_ID = "101"
_CONTAINER_ID = "202"
_WORKSPACE_ID = "303"
_ENTITY_ID = "404"
_VERSION_ID = "505"
_SITE_URL = "https://example.com/"
_PAGE_URL = "https://example.com/article"
_GTM_ENTITY_DEFINITION = {
    "name": "Rankrat HTML",
    "type": "html",
    "parameters": [{"key": "html", "type": "template", "value": "<script></script>"}],
}

_READ_TOOLS = {
    CLARITY_INSIGHTS_OPERATION,
    EDGE_REDIRECTS_LIST_OPERATION,
    GTM_ACCOUNTS_LIST_OPERATION,
    GTM_CONTAINERS_LIST_OPERATION,
    GTM_WORKSPACES_LIST_OPERATION,
    GTM_ENTITIES_LIST_OPERATION,
}
_WRITE_TOOLS = {
    BING_CONTENT_SUBMISSION_OPERATION,
    EDGE_REDIRECT_UPSERT_OPERATION,
    EDGE_REDIRECT_DELETE_OPERATION,
    GTM_CONTAINERS_CREATE_OPERATION,
    GTM_CONTAINERS_DELETE_OPERATION,
    GTM_WORKSPACES_CREATE_OPERATION,
    GTM_WORKSPACES_DELETE_OPERATION,
    GTM_ENTITIES_CREATE_OPERATION,
    GTM_ENTITIES_UPDATE_OPERATION,
    GTM_ENTITIES_DELETE_OPERATION,
    GTM_WORKSPACE_VERSION_CREATE_OPERATION,
    GTM_VERSION_PUBLISH_OPERATION,
}


def _gtm_container() -> GtmContainer:
    return GtmContainer(
        _GTM_ACCOUNT_ID,
        _CONTAINER_ID,
        "Rankrat web",
        f"accounts/{_GTM_ACCOUNT_ID}/containers/{_CONTAINER_ID}",
        "GTM-TEST",
    )


def _gtm_workspace() -> GtmWorkspace:
    return GtmWorkspace(
        _GTM_ACCOUNT_ID,
        _CONTAINER_ID,
        _WORKSPACE_ID,
        "Default Workspace",
        f"accounts/{_GTM_ACCOUNT_ID}/containers/{_CONTAINER_ID}/workspaces/{_WORKSPACE_ID}",
    )


def _gtm_entity() -> GtmEntity:
    return GtmEntity(
        GtmEntityKind.TAG,
        _GTM_ACCOUNT_ID,
        _CONTAINER_ID,
        _WORKSPACE_ID,
        _ENTITY_ID,
        "Rankrat HTML",
        "html",
        f"accounts/{_GTM_ACCOUNT_ID}/containers/{_CONTAINER_ID}/workspaces/{_WORKSPACE_ID}/tags/{_ENTITY_ID}",
    )


def _gtm_version() -> GtmVersion:
    return GtmVersion(
        _GTM_ACCOUNT_ID,
        _CONTAINER_ID,
        _VERSION_ID,
        "Rankrat version",
        f"accounts/{_GTM_ACCOUNT_ID}/containers/{_CONTAINER_ID}/versions/{_VERSION_ID}",
    )


def _redirect() -> CloudflareEdgeRedirect:
    return CloudflareEdgeRedirect(
        "a" * 32,
        _RULE_ID,
        "/old",
        "https://target.example/new",
        CloudflareRedirectStatus.MOVED_PERMANENTLY,
        True,
    )


def _patch_reads(services: ApplicationServices, monkeypatch: pytest.MonkeyPatch) -> None:
    async def clarity(*_: object) -> ClarityInsightsReport:
        return ClarityInsightsReport(
            1,
            (ClarityDimension.URL,),
            (ClarityMetric("Sessions", ({"url": _SITE_URL, "sessions": 3},)),),
        )

    async def accounts(*_: object) -> tuple[GtmAccount, ...]:
        return (GtmAccount(_GTM_ACCOUNT_ID, "Main", f"accounts/{_GTM_ACCOUNT_ID}"),)

    async def containers(*_: object) -> tuple[GtmContainer, ...]:
        return (_gtm_container(),)

    async def workspaces(*_: object) -> tuple[GtmWorkspace, ...]:
        return (_gtm_workspace(),)

    async def entities(*_: object) -> tuple[GtmEntity, ...]:
        return (_gtm_entity(),)

    async def redirects(*_: object) -> tuple[CloudflareEdgeRedirect, ...]:
        return (_redirect(),)

    assert services.edge_redirects is not None
    monkeypatch.setattr(services.clarity, "live_insights", clarity)
    monkeypatch.setattr(services.google_tag_manager, "list_accounts", accounts)
    monkeypatch.setattr(services.google_tag_manager, "list_containers", containers)
    monkeypatch.setattr(services.google_tag_manager, "list_workspaces", workspaces)
    monkeypatch.setattr(services.google_tag_manager, "list_entities", entities)
    monkeypatch.setattr(services.edge_redirects, "list", redirects)


def _patch_writes(services: ApplicationServices, monkeypatch: pytest.MonkeyPatch) -> None:
    async def content(*_: object) -> BingContentSubmissionReceipt:
        return BingContentSubmissionReceipt(_SITE_URL, _PAGE_URL, 42, False)

    async def redirect_upsert(*_: object) -> CloudflareEdgeRedirectReceipt:
        return CloudflareEdgeRedirectReceipt(_redirect(), True, True)

    async def delete(*_: object) -> None:
        return None

    async def container(*_: object) -> GtmContainer:
        return _gtm_container()

    async def workspace(*_: object) -> GtmWorkspace:
        return _gtm_workspace()

    async def entity(*_: object) -> GtmEntity:
        return _gtm_entity()

    async def version(*_: object) -> GtmVersion:
        return _gtm_version()

    assert services.bing_content is not None
    assert services.edge_redirects is not None
    monkeypatch.setattr(services.bing_content, "submit", content)
    monkeypatch.setattr(services.edge_redirects, "upsert", redirect_upsert)
    monkeypatch.setattr(services.edge_redirects, "delete", delete)
    monkeypatch.setattr(services.google_tag_manager, "create_container", container)
    monkeypatch.setattr(services.google_tag_manager, "delete_container", delete)
    monkeypatch.setattr(services.google_tag_manager, "create_workspace", workspace)
    monkeypatch.setattr(services.google_tag_manager, "delete_workspace", delete)
    monkeypatch.setattr(services.google_tag_manager, "create_entity", entity)
    monkeypatch.setattr(services.google_tag_manager, "update_entity", entity)
    monkeypatch.setattr(services.google_tag_manager, "delete_entity", delete)
    monkeypatch.setattr(services.google_tag_manager, "create_version", version)
    monkeypatch.setattr(services.google_tag_manager, "publish_version", version)


@pytest.mark.asyncio
async def test_free_seo_read_routes_have_stdio_mcp_parity_and_hide_writes(
    deployment: tuple[Settings, ApplicationServices],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings, services = deployment
    _patch_reads(services, monkeypatch)
    app = create_http_app(settings, services)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://rankrat.test",
    ) as client:
        clarity = await client.post(
            "/v1/clarity/insights",
            json={"account_id": "clarity-main", "dimensions": ["URL"]},
        )
        accounts = await client.get("/v1/google-tag-manager/accounts?account_id=google-main")
        containers = await client.get(
            "/v1/google-tag-manager/containers?account_id=google-main&gtm_account_id=101"
        )
        workspaces = await client.get(
            "/v1/google-tag-manager/workspaces?account_id=google-main&gtm_account_id=101&container_id=202"
        )
        entities = await client.get(
            "/v1/google-tag-manager/entities?account_id=google-main&gtm_account_id=101&container_id=202&workspace_id=303&kind=tag"
        )
        redirects = await client.get(
            "/v1/edge-redirects?account_id=cloudflare-main&site_url=https%3A%2F%2Fexample.com%2F"
        )
        hidden_write = await client.post("/v1/bing/content-submissions", json={})
        invalid_clarity = await client.post(
            "/v1/clarity/insights",
            json={"account_id": "clarity-main", "unexpected": True},
        )

    assert clarity.json()["metrics"][0]["information"][0]["sessions"] == 3
    assert accounts.json()[0]["account_id"] == _GTM_ACCOUNT_ID
    assert containers.json()[0]["container_id"] == _CONTAINER_ID
    assert workspaces.json()[0]["workspace_id"] == _WORKSPACE_ID
    assert entities.json()[0]["entity_id"] == _ENTITY_ID
    assert redirects.json()[0]["rule_id"] == _RULE_ID
    assert hidden_write.status_code == 404
    assert invalid_clarity.status_code == 422

    server = build_mcp_server(services)
    async with create_connected_server_and_client_session(server) as client:
        catalog = {tool.name for tool in (await client.list_tools()).tools}
        assert catalog >= _READ_TOOLS
        assert _WRITE_TOOLS.isdisjoint(catalog)
        result = await client.call_tool(
            CLARITY_INSIGHTS_OPERATION,
            {"account_id": "clarity-main", "dimensions": ["URL"]},
        )
        assert json.loads(result.content[0].text)["metrics"][0]["metric_name"] == "Sessions"  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_free_seo_write_routes_have_stdio_mcp_parity(
    indexnow_deployment: tuple[Settings, ApplicationServices],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings, services = indexnow_deployment
    _patch_writes(services, monkeypatch)
    app = create_http_app(settings, services)
    gtm_scope = {
        "account_id": "google-main",
        "gtm_account_id": _GTM_ACCOUNT_ID,
        "container_id": _CONTAINER_ID,
    }
    entity_scope = {**gtm_scope, "workspace_id": _WORKSPACE_ID, "kind": "tag"}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://rankrat.test",
    ) as client:
        content = await client.post(
            "/v1/bing/content-submissions",
            json={"account_id": "bing-main", "site_url": _SITE_URL, "page_url": _PAGE_URL},
        )
        redirect = await client.post(
            "/v1/edge-redirects",
            json={
                "account_id": "cloudflare-main",
                "site_url": _SITE_URL,
                "source_path": "/old",
                "target_url": "https://target.example/new",
            },
        )
        redirect_delete = await client.request(
            "DELETE",
            f"/v1/edge-redirects/{_RULE_ID}",
            json={"account_id": "cloudflare-main", "site_url": _SITE_URL, "rule_id": _RULE_ID},
        )
        container = await client.post(
            "/v1/google-tag-manager/containers",
            json={
                "account_id": "google-main",
                "gtm_account_id": _GTM_ACCOUNT_ID,
                "name": "Rankrat",
                "usage_contexts": ["web"],
            },
        )
        container_delete = await client.request(
            "DELETE",
            f"/v1/google-tag-manager/containers/{_CONTAINER_ID}",
            json={
                "account_id": "google-main",
                "gtm_account_id": _GTM_ACCOUNT_ID,
                "container_id": _CONTAINER_ID,
            },
        )
        workspace = await client.post(
            "/v1/google-tag-manager/workspaces",
            json={**gtm_scope, "name": "Rankrat"},
        )
        workspace_delete = await client.request(
            "DELETE",
            f"/v1/google-tag-manager/workspaces/{_WORKSPACE_ID}",
            json={**gtm_scope, "workspace_id": _WORKSPACE_ID},
        )
        entity = await client.post(
            "/v1/google-tag-manager/entities",
            json={**entity_scope, "definition": _GTM_ENTITY_DEFINITION},
        )
        entity_update = await client.put(
            f"/v1/google-tag-manager/entities/{_ENTITY_ID}",
            json={**entity_scope, "entity_id": _ENTITY_ID, "definition": _GTM_ENTITY_DEFINITION},
        )
        entity_delete = await client.request(
            "DELETE",
            f"/v1/google-tag-manager/entities/{_ENTITY_ID}",
            json={**entity_scope, "entity_id": _ENTITY_ID},
        )
        version = await client.post(
            "/v1/google-tag-manager/workspace-versions",
            json={**gtm_scope, "workspace_id": _WORKSPACE_ID, "name": "Rankrat version"},
        )
        publish = await client.post(
            "/v1/google-tag-manager/version-publications",
            json={**gtm_scope, "version_id": _VERSION_ID},
        )

    assert content.json()["content_bytes"] == 42
    assert redirect.json()["created"] is True
    assert container.json()["container_id"] == _CONTAINER_ID
    assert workspace.json()["workspace_id"] == _WORKSPACE_ID
    assert entity.json()["entity_id"] == _ENTITY_ID
    assert entity_update.json()["entity_id"] == _ENTITY_ID
    assert version.json()["version_id"] == _VERSION_ID
    assert publish.json()["version_id"] == _VERSION_ID
    assert all(
        response.status_code == 204
        for response in (redirect_delete, container_delete, workspace_delete, entity_delete)
    )

    server = build_mcp_server(services)
    async with create_connected_server_and_client_session(server) as client:
        catalog = {tool.name for tool in (await client.list_tools()).tools}
        assert catalog >= _WRITE_TOOLS
        result = await client.call_tool(
            GTM_ENTITIES_CREATE_OPERATION,
            {**entity_scope, "definition": _GTM_ENTITY_DEFINITION},
        )
        assert json.loads(result.content[0].text)["entity_id"] == _ENTITY_ID  # type: ignore[union-attr]
