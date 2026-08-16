from __future__ import annotations

import httpx
import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from rankrat.config import Settings
from rankrat.providers.google_analytics_admin import Ga4DataStream, Ga4RenamedResource
from rankrat.transports.http import create_http_app
from rankrat.transports.mcp import build_mcp_server
from rankrat.transports.runtime import ApplicationServices

_RENAME_TOOLS = ("google_analytics_account_rename", "google_analytics_property_rename")
_RENAME_ROUTES = (
    "/v1/google-analytics/account-renames",
    "/v1/google-analytics/property-renames",
)


@pytest.mark.asyncio
async def test_read_only_runtime_publishes_data_streams_but_no_renames(
    deployment: tuple[Settings, ApplicationServices],
) -> None:
    """Reading which measurement ID belongs to a property is not a write."""

    settings, services = deployment
    assert services.writes_enabled is False
    server = build_mcp_server(services)

    async with create_connected_server_and_client_session(server) as client:
        tools = {tool.name for tool in (await client.list_tools()).tools}

    assert "google_analytics_data_streams" in tools
    assert not tools.intersection(_RENAME_TOOLS)

    app = create_http_app(settings.model_copy(update={"enable_openapi": True}), services)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://rankrat.test",
    ) as http_client:
        document = (await http_client.get("/openapi.json")).json()

    assert "/v1/google-analytics/data-streams" in document["paths"]
    for route in _RENAME_ROUTES:
        assert route not in document["paths"]


@pytest.mark.asyncio
async def test_read_only_runtime_refuses_a_rename_call_not_just_its_discovery(
    deployment: tuple[Settings, ApplicationServices],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Absence from tools/list is not enforcement — an unlisted tool is still dispatchable."""

    import json

    _, services = deployment

    async def must_not_run(*_: object, **__: object) -> Ga4RenamedResource:
        raise AssertionError("a read-only server reached the rename client")

    monkeypatch.setattr(
        services.google_analytics_admin._client,
        "update_account_display_name",
        must_not_run,
    )
    monkeypatch.setattr(
        services.google_analytics_admin._client,
        "update_property_display_name",
        must_not_run,
    )

    server = build_mcp_server(services)
    async with create_connected_server_and_client_session(server) as client:
        for name, arguments in (
            (
                "google_analytics_account_rename",
                {
                    "account_id": "google-main",
                    "analytics_account_id": "247964066",
                    "display_name": "psyb0t",
                },
            ),
            (
                "google_analytics_property_rename",
                {
                    "account_id": "google-main",
                    "property_id": "123456789",
                    "display_name": "psyb0t",
                },
            ),
        ):
            result = await client.call_tool(name, arguments)
            payload = json.loads(result.content[0].text)  # type: ignore[union-attr]
            assert payload["code"] == "TOOL_NOT_FOUND", name


@pytest.mark.asyncio
async def test_writable_runtime_publishes_the_renames(
    indexnow_deployment: tuple[Settings, ApplicationServices],
) -> None:
    settings, services = indexnow_deployment
    assert services.writes_enabled is True
    server = build_mcp_server(services)

    async with create_connected_server_and_client_session(server) as client:
        tools = {tool.name for tool in (await client.list_tools()).tools}
        annotations = {
            tool.name: tool.annotations
            for tool in (await client.list_tools()).tools
            if tool.name in _RENAME_TOOLS
        }

    assert set(_RENAME_TOOLS).issubset(tools)
    for name in _RENAME_TOOLS:
        annotation = annotations[name]
        assert annotation is not None
        assert annotation.readOnlyHint is False

    app = create_http_app(settings.model_copy(update={"enable_openapi": True}), services)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://rankrat.test",
    ) as http_client:
        document = (await http_client.get("/openapi.json")).json()

    for route in _RENAME_ROUTES:
        assert route in document["paths"]


@pytest.mark.asyncio
async def test_data_streams_reaches_the_service_over_both_transports(
    deployment: tuple[Settings, ApplicationServices],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import json

    settings, services = deployment
    calls: list[str] = []

    async def mock_list(*_: object, **__: object) -> tuple[Ga4DataStream, ...]:
        calls.append("called")
        return (
            Ga4DataStream(
                stream_id="11",
                display_name="Web",
                stream_type="WEB_DATA_STREAM",
                default_uri="https://example.com",
                measurement_id="G-ABC123",
            ),
        )

    monkeypatch.setattr(services.google_analytics_admin._client, "list_data_streams", mock_list)

    server = build_mcp_server(services)
    async with create_connected_server_and_client_session(server) as client:
        result = await client.call_tool(
            "google_analytics_data_streams",
            {"account_id": "google-main", "property_id": "123456789"},
        )
    payload = json.loads(result.content[0].text)  # type: ignore[union-attr]
    assert payload["streams"][0]["measurement_id"] == "G-ABC123"

    app = create_http_app(settings.model_copy(update={"enable_openapi": True}), services)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://rankrat.test",
    ) as http_client:
        response = await http_client.post(
            "/v1/google-analytics/data-streams",
            json={"account_id": "google-main", "property_id": "123456789"},
        )

    assert response.status_code == 200
    assert response.json()["streams"][0]["measurement_id"] == "G-ABC123"
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_rename_reaches_the_service_when_writes_are_enabled(
    indexnow_deployment: tuple[Settings, ApplicationServices],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import json

    settings, services = indexnow_deployment

    async def mock_rename(*_: object, **__: object) -> Ga4RenamedResource:
        return Ga4RenamedResource("247964066", "psyb0t")

    monkeypatch.setattr(
        services.google_analytics_admin._client,
        "update_account_display_name",
        mock_rename,
    )

    server = build_mcp_server(services)
    async with create_connected_server_and_client_session(server) as client:
        result = await client.call_tool(
            "google_analytics_account_rename",
            {
                "account_id": "google-main",
                "analytics_account_id": "247964066",
                "display_name": "psyb0t",
            },
        )
    payload = json.loads(result.content[0].text)  # type: ignore[union-attr]
    assert payload == {"resource_id": "247964066", "display_name": "psyb0t"}

    app = create_http_app(settings.model_copy(update={"enable_openapi": True}), services)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://rankrat.test",
    ) as http_client:
        response = await http_client.post(
            "/v1/google-analytics/account-renames",
            json={
                "account_id": "google-main",
                "analytics_account_id": "247964066",
                "display_name": "psyb0t",
            },
        )

    assert response.status_code == 200
    assert response.json()["display_name"] == "psyb0t"


@pytest.mark.asyncio
async def test_rename_rejects_a_blank_or_padded_display_name(
    indexnow_deployment: tuple[Settings, ApplicationServices],
) -> None:
    """A padded name silently renames the account to something the operator did not type."""

    settings, services = indexnow_deployment
    app = create_http_app(settings.model_copy(update={"enable_openapi": True}), services)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://rankrat.test",
    ) as http_client:
        for display_name in ("", "   ", " psyb0t "):
            response = await http_client.post(
                "/v1/google-analytics/account-renames",
                json={
                    "account_id": "google-main",
                    "analytics_account_id": "247964066",
                    "display_name": display_name,
                },
            )
            assert response.status_code in (400, 422), display_name
