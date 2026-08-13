from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from rankrat.models.boundaries import BoundaryDocument
from rankrat.policy.boundaries import BoundaryPolicy
from rankrat.providers.base import (
    AccountId,
    ProviderFailureCode,
    ProviderOperationError,
    ProviderReadRequest,
)
from rankrat.providers.google_tag_manager import (
    GoogleTagManagerClient,
    GtmEntityDefinition,
    GtmEntityKind,
    GtmParameter,
    GtmUsageContext,
)


async def _token(credential_path: Path) -> str:
    del credential_path
    return "test-google-access-token"


def _policy(tmp_path: Path) -> BoundaryPolicy:
    return BoundaryPolicy(
        BoundaryDocument.model_validate(
            {
                "accounts": [
                    {
                        "id": "google-main",
                        "provider": "google",
                        "credential": str(tmp_path / "google-client.json"),
                    }
                ]
            }
        )
    )


def _request() -> ProviderReadRequest:
    return ProviderReadRequest(AccountId("google-main"), 1.0)


def _client(
    tmp_path: Path,
    transport: httpx.AsyncBaseTransport,
) -> GoogleTagManagerClient:
    return GoogleTagManagerClient(_policy(tmp_path), _token, lambda: transport)


def _entity_payload(kind: GtmEntityKind, entity_id: str = "3") -> dict[str, str]:
    return {
        "accountId": "1",
        "containerId": "2",
        "workspaceId": "4",
        f"{kind.value}Id": entity_id,
        "name": "Rankrat managed tag",
        "type": "html",
        "path": f"accounts/1/containers/2/workspaces/4/{kind.value}s/{entity_id}",
    }


@pytest.mark.asyncio
async def test_gtm_lists_documented_singular_collections_at_fixed_origin(tmp_path: Path) -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.headers["Authorization"] == "Bearer test-google-access-token"
        if request.url.path.endswith("/accounts"):
            return httpx.Response(
                200,
                json={"account": [{"accountId": "1", "name": "Main", "path": "accounts/1"}]},
            )
        if request.url.path.endswith("/containers"):
            return httpx.Response(
                200,
                json={
                    "container": [
                        {
                            "accountId": "1",
                            "containerId": "2",
                            "name": "Web",
                            "path": "accounts/1/containers/2",
                            "publicId": "GTM-TEST",
                        }
                    ]
                },
            )
        if request.url.path.endswith("/workspaces"):
            return httpx.Response(
                200,
                json={
                    "workspace": [
                        {
                            "accountId": "1",
                            "containerId": "2",
                            "workspaceId": "4",
                            "name": "Default Workspace",
                            "path": "accounts/1/containers/2/workspaces/4",
                        }
                    ]
                },
            )
        return httpx.Response(200, json={"tag": [_entity_payload(GtmEntityKind.TAG)]})

    client = _client(tmp_path, httpx.MockTransport(handler))
    assert (await client.list_accounts(_request()))[0].account_id == "1"
    assert (await client.list_containers(_request(), "1"))[0].public_id == "GTM-TEST"
    assert (await client.list_workspaces(_request(), "1", "2"))[0].workspace_id == "4"
    assert (await client.list_entities(_request(), "1", "2", "4", GtmEntityKind.TAG))[
        0
    ].entity_id == "3"
    assert [request.url.host for request in requests] == ["tagmanager.googleapis.com"] * 4
    assert [request.url.path.rsplit("/", 1)[-1] for request in requests] == [
        "accounts",
        "containers",
        "workspaces",
        "tags",
    ]


@pytest.mark.asyncio
async def test_gtm_serializes_rankrat_fields_to_the_documented_wire_payload(tmp_path: Path) -> None:
    requests: list[httpx.Request] = []
    definition = GtmEntityDefinition(
        name="Rankrat GA4",
        type="html",
        parameters=(
            GtmParameter(
                key="html",
                type="template",
                value="<script>window.dataLayer = window.dataLayer || [];</script>",
            ),
        ),
        filters=(
            GtmParameter(
                key="condition",
                type="list",
                list_items=(GtmParameter(key="equals", type="template", value="true"),),
            ),
        ),
        firing_trigger_ids=("7",),
        notes="Created by Rankrat",
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "POST":
            payload = json.loads(request.content)
            assert payload == {
                "name": "Rankrat GA4",
                "type": "html",
                "parameter": [
                    {
                        "key": "html",
                        "type": "template",
                        "value": "<script>window.dataLayer = window.dataLayer || [];</script>",
                    }
                ],
                "filter": [
                    {
                        "key": "condition",
                        "type": "list",
                        "list": [{"key": "equals", "type": "template", "value": "true"}],
                    }
                ],
                "firingTriggerId": ["7"],
                "notes": "Created by Rankrat",
            }
            return httpx.Response(200, json=_entity_payload(GtmEntityKind.TAG))
        assert request.method == "PUT"
        return httpx.Response(200, json=_entity_payload(GtmEntityKind.TAG))

    client = _client(tmp_path, httpx.MockTransport(handler))
    created = await client.create_entity(
        _request(),
        "1",
        "2",
        "4",
        GtmEntityKind.TAG,
        definition,
    )
    updated = await client.update_entity(
        _request(),
        "1",
        "2",
        "4",
        GtmEntityKind.TAG,
        created.entity_id,
        definition,
    )
    assert updated.entity_id == "3"
    assert [request.method for request in requests] == ["POST", "PUT"]
    assert requests[1].url.path.endswith("/tags/3")


@pytest.mark.asyncio
async def test_gtm_container_workspace_version_and_delete_routes_are_typed(tmp_path: Path) -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "DELETE":
            return httpx.Response(204)
        if request.url.path.endswith(":create_version"):
            return httpx.Response(
                200,
                json={
                    "containerVersion": {
                        "accountId": "1",
                        "containerId": "2",
                        "containerVersionId": "9",
                        "name": "Release",
                        "path": "accounts/1/containers/2/versions/9",
                    }
                },
            )
        if request.url.path.endswith(":publish"):
            return httpx.Response(
                200,
                json={
                    "containerVersion": {
                        "accountId": "1",
                        "containerId": "2",
                        "containerVersionId": "9",
                        "name": "Release",
                        "path": "accounts/1/containers/2/versions/9",
                    }
                },
            )
        if request.url.path.endswith("/containers"):
            assert json.loads(request.content) == {"name": "Web", "usageContext": ["web"]}
            return httpx.Response(
                200,
                json={
                    "accountId": "1",
                    "containerId": "2",
                    "name": "Web",
                    "path": "accounts/1/containers/2",
                },
            )
        assert request.url.path.endswith("/workspaces")
        return httpx.Response(
            200,
            json={
                "accountId": "1",
                "containerId": "2",
                "workspaceId": "4",
                "name": "Deploy",
                "path": "accounts/1/containers/2/workspaces/4",
            },
        )

    client = _client(tmp_path, httpx.MockTransport(handler))
    await client.create_container(_request(), "1", "Web", (GtmUsageContext.WEB,))
    await client.create_workspace(_request(), "1", "2", "Deploy", "Release workspace")
    version = await client.create_workspace_version(_request(), "1", "2", "4", "Release", None)
    assert (
        await client.publish_version(_request(), "1", "2", version.version_id)
    ).version_id == "9"
    await client.delete_entity(_request(), "1", "2", "4", GtmEntityKind.TAG, "3")
    await client.delete_workspace(_request(), "1", "2", "4")
    await client.delete_container(_request(), "1", "2")
    assert [request.method for request in requests] == [
        "POST",
        "POST",
        "POST",
        "POST",
        "DELETE",
        "DELETE",
        "DELETE",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("response", "expected_code"),
    (
        (httpx.Response(403, json={"error": "forbidden"}), ProviderFailureCode.FORBIDDEN),
        (httpx.Response(429, json={"error": "limited"}), ProviderFailureCode.RATE_LIMITED),
        (httpx.Response(500, json={"error": "offline"}), ProviderFailureCode.UNAVAILABLE),
        (httpx.Response(200, content=b"not-json"), ProviderFailureCode.INVALID_RESPONSE),
    ),
)
async def test_gtm_maps_upstream_failures_without_exposing_response_body(
    tmp_path: Path,
    response: httpx.Response,
    expected_code: ProviderFailureCode,
) -> None:
    client = _client(tmp_path, httpx.MockTransport(lambda _: response))
    with pytest.raises(ProviderOperationError) as error:
        await client.list_accounts(_request())
    assert error.value.code is expected_code
    assert "forbidden" not in str(error.value).casefold()


def test_gtm_definition_rejects_ambiguous_and_overdeep_parameter_shapes() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        GtmParameter(
            key="value",
            type="template",
            value="x",
            list_items=(GtmParameter(key="list", type="template", value="x"),),
        )

    nested = GtmParameter(key="leaf", type="template", value="x")
    for index in range(8):
        nested = GtmParameter(key=f"nested-{index}", type="list", list_items=(nested,))
    with pytest.raises(ValueError, match="nesting"):
        GtmEntityDefinition(name="Deep", type="html", parameters=(nested,))
