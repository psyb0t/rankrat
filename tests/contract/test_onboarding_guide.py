from __future__ import annotations

import json

import pytest
from mcp.shared.memory import create_connected_server_and_client_session
from pydantic import AnyUrl

from rankrat.config import Settings
from rankrat.transports.http import create_http_app
from rankrat.transports.mcp import build_mcp_server
from rankrat.transports.runtime import ApplicationServices

_ONBOARDING_URI = "rankrat://onboarding"
_DOMAIN_PROPERTY_URI = "rankrat://onboarding/sc-domain%3Aexample.com"
_URL_PREFIX_PROPERTY_URI = "rankrat://onboarding/https%3A%2F%2Fexample.com%2F"


@pytest.mark.asyncio
async def test_read_only_runtime_still_serves_the_onboarding_resource(
    deployment: tuple[Settings, ApplicationServices],
) -> None:
    """Knowing the procedure is not a privilege — a read-only server still explains it."""

    _, services = deployment
    assert services.agent_onboarding_enabled is False
    server = build_mcp_server(services)

    async with create_connected_server_and_client_session(server) as client:
        resources = await client.list_resources()
        assert _ONBOARDING_URI in {str(resource.uri) for resource in resources.resources}

        templates = await client.list_resource_templates()
        assert "rankrat://onboarding/{site_url}" in {
            template.uriTemplate for template in templates.resourceTemplates
        }

        contents = await client.read_resource(AnyUrl(_ONBOARDING_URI))
        guide = json.loads(contents.contents[0].text)  # type: ignore[union-attr]

    assert guide["agent_onboarding_enabled"] is False
    assert any(
        "no tool performs this step" in step["detail"] for step in guide["recommended_order"]
    )
    assert any(
        "cannot" in claim or "Prove site ownership" in claim
        for claim in guide["tell_the_user"] + guide["rankrat_cannot_perform"]
    )


@pytest.mark.asyncio
async def test_guide_tells_the_caller_how_to_create_a_ga4_account_by_hand(
    deployment: tuple[Settings, ApplicationServices],
) -> None:
    """No tool can create a GA4 account, so the guide has to hand over the click path."""

    _, services = deployment
    server = build_mcp_server(services)

    async with create_connected_server_and_client_session(server) as client:
        contents = await client.read_resource(AnyUrl(_ONBOARDING_URI))
        guide = json.loads(contents.contents[0].text)  # type: ignore[union-attr]

    provisioning = {item["resource"]: item for item in guide["manual_provisioning"]}
    account = provisioning["google_analytics_account"]

    assert account["start_url"] == "https://analytics.google.com"
    assert "accounts.create" in account["why_no_tool"]
    assert "Terms of Service" in account["why_no_tool"]

    steps = account["steps"]
    assert [step["order"] for step in steps] == list(range(1, len(steps) + 1))
    assert any(step["url"] == "https://analytics.google.com" for step in steps)
    joined = " ".join(step["action"] for step in steps)
    assert "Admin" in joined
    assert "Create" in joined and "Account" in joined
    assert "google_analytics_account_inventory" in joined

    # The adjacent API must be described as not removing the browser step, so a
    # model does not go looking for it as an automation escape hatch.
    assert "provisionAccountTicket" in account["api_note"]
    assert "redirectUri" in account["api_note"]
    assert "analytics.edit" in account["api_note"]


@pytest.mark.asyncio
async def test_guide_is_reachable_over_rest_with_the_same_document(
    deployment: tuple[Settings, ApplicationServices],
) -> None:
    """Callers that do not speak MCP still need the procedure."""

    import httpx

    settings, services = deployment
    server = build_mcp_server(services)

    async with create_connected_server_and_client_session(server) as client:
        contents = await client.read_resource(AnyUrl(_ONBOARDING_URI))
        from_resource = json.loads(contents.contents[0].text)  # type: ignore[union-attr]

    app = create_http_app(settings.model_copy(update={"enable_openapi": True}), services)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://rankrat.test",
    ) as http_client:
        response = await http_client.post("/v1/onboarding-guides", json={})

    assert response.status_code == 200
    assert response.json() == from_resource


@pytest.mark.asyncio
async def test_domain_property_offers_dns_txt_only(
    deployment: tuple[Settings, ApplicationServices],
) -> None:
    """A sc-domain: property cannot be verified by file, meta tag or the Analytics tag."""

    _, services = deployment
    server = build_mcp_server(services)

    async with create_connected_server_and_client_session(server) as client:
        contents = await client.read_resource(AnyUrl(_DOMAIN_PROPERTY_URI))
        guide = json.loads(contents.contents[0].text)  # type: ignore[union-attr]

    site = guide["sites"][0]
    assert site["site_url"] == "sc-domain:example.com"
    assert site["search_console_property_type"] == "domain"
    assert [method["method"] for method in site["search_console_verification"]] == ["dns_txt"]
    assert any("DNS TXT is the only method" in note for note in site["notes"])


@pytest.mark.asyncio
async def test_url_prefix_property_offers_the_analytics_shortcut(
    deployment: tuple[Settings, ApplicationServices],
) -> None:
    _, services = deployment
    server = build_mcp_server(services)

    async with create_connected_server_and_client_session(server) as client:
        contents = await client.read_resource(AnyUrl(_URL_PREFIX_PROPERTY_URI))
        guide = json.loads(contents.contents[0].text)  # type: ignore[union-attr]

    site = guide["sites"][0]
    assert site["site_url"] == "https://example.com/"
    assert site["search_console_property_type"] == "url_prefix"
    methods = [method["method"] for method in site["search_console_verification"]]
    assert methods[0] == "google_analytics"
    assert {"html_file", "meta_tag", "dns_txt"}.issubset(set(methods))


@pytest.mark.asyncio
async def test_the_tool_mirror_returns_the_same_document_as_the_resource(
    deployment: tuple[Settings, ApplicationServices],
) -> None:
    """One renderer, two surfaces — clients without resource support must not lose content."""

    _, services = deployment
    server = build_mcp_server(services)

    async with create_connected_server_and_client_session(server) as client:
        contents = await client.read_resource(AnyUrl(_URL_PREFIX_PROPERTY_URI))
        from_resource = json.loads(contents.contents[0].text)  # type: ignore[union-attr]
        called = await client.call_tool("onboarding_guide", {"site_url": "https://example.com/"})
        from_tool = json.loads(called.content[0].text)  # type: ignore[union-attr]

    assert from_tool == from_resource


@pytest.mark.asyncio
async def test_unknown_resource_uri_is_refused(
    deployment: tuple[Settings, ApplicationServices],
) -> None:
    _, services = deployment
    server = build_mcp_server(services)

    async with create_connected_server_and_client_session(server) as client:
        with pytest.raises(Exception, match="RESOURCE_NOT_FOUND"):
            await client.read_resource(AnyUrl("rankrat://not-a-resource"))


@pytest.mark.asyncio
async def test_onboarding_tool_needs_its_own_switch_not_just_writable_mode(
    indexnow_deployment: tuple[Settings, ApplicationServices],
) -> None:
    """Writable mode alone must not hand an agent the boundary-rewriting tool."""

    from dataclasses import replace

    _, services = indexnow_deployment
    assert services.writes_enabled is True
    assert services.agent_onboarding_enabled is True

    withheld = replace(services, agent_onboarding_enabled=False, site_onboarding=None)
    server = build_mcp_server(withheld)

    async with create_connected_server_and_client_session(server) as client:
        tools = {tool.name for tool in (await client.list_tools()).tools}
        contents = await client.read_resource(AnyUrl(_ONBOARDING_URI))
        guide = json.loads(contents.contents[0].text)  # type: ignore[union-attr]

    assert "site_onboarding_submit" not in tools
    assert "indexnow_submit" in tools
    assert "onboarding_guide" in tools
    assert guide["writes_enabled"] is True
    assert guide["agent_onboarding_enabled"] is False
