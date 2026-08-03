from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from rankrat.config import Settings
from rankrat.errors import BoundaryDeniedError
from rankrat.models.boundaries import BoundaryDocument
from rankrat.policy.boundaries import BoundaryPolicy
from rankrat.transports.http import create_http_app
from rankrat.transports.runtime import ApplicationServices
from rankrat.transports.tool_contracts import READ_ONLY_TOOL_CATALOG, tool_catalog

_OWNER_ONLY_SECRET_FILE_MODE = 0o600
_DOCKERFILE_PATHS = (Path("Dockerfile"), Path("Dockerfile.dev"), Path("Dockerfile.lock"))
_DOCKER_HUB_FRONTEND_DIRECTIVE = "# syntax=docker/dockerfile"


def test_dockerfiles_do_not_require_a_docker_hub_frontend_image() -> None:
    for dockerfile_path in _DOCKERFILE_PATHS:
        contents = dockerfile_path.read_text(encoding="utf-8")
        assert _DOCKER_HUB_FRONTEND_DIRECTIVE not in contents


def test_normalized_duplicate_resources_and_cross_provider_resources_are_rejected(
    tmp_path: Path,
) -> None:
    credential = str(tmp_path / "credential")
    with pytest.raises(ValidationError):
        BoundaryDocument.model_validate(
            {
                "accounts": [
                    {
                        "id": "google-main",
                        "provider": "google",
                        "credential": credential,
                        "search_console_sites": [
                            "https://example.com",
                            "https://EXAMPLE.com:443/",
                        ],
                    }
                ]
            }
        )
    with pytest.raises(ValidationError):
        BoundaryDocument.model_validate(
            {
                "accounts": [
                    {
                        "id": "bing-main",
                        "provider": "bing",
                        "credential": credential,
                        "ga4_properties": ["123"],
                    }
                ]
            }
        )


def test_url_prefix_boundaries_reject_sibling_path_escalation(tmp_path: Path) -> None:
    configured_url = "https://example.com/blog"
    sibling_url = "https://example.com/blogger/article"
    traversal_url = "https://example.com/blog/%2e%2e/private"
    google_policy = BoundaryPolicy(
        BoundaryDocument.model_validate(
            {
                "accounts": [
                    {
                        "id": "google-main",
                        "provider": "google",
                        "credential": str(tmp_path / "google-credential"),
                        "search_console_sites": [configured_url],
                    }
                ]
            }
        )
    )
    bing_policy = BoundaryPolicy(
        BoundaryDocument.model_validate(
            {
                "accounts": [
                    {
                        "id": "bing-main",
                        "provider": "bing",
                        "credential": str(tmp_path / "bing-credential"),
                        "sites": [configured_url],
                    }
                ]
            }
        )
    )

    with pytest.raises(BoundaryDeniedError):
        google_policy.require_search_console_url("google-main", configured_url, sibling_url)
    with pytest.raises(BoundaryDeniedError):
        bing_policy.require_bing_site_url("bing-main", configured_url, sibling_url)
    with pytest.raises(ValueError):
        google_policy.require_search_console_url("google-main", configured_url, traversal_url)
    with pytest.raises(ValueError):
        bing_policy.require_bing_site_url("bing-main", configured_url, traversal_url)


def test_write_tools_are_absent_by_default_and_explicitly_annotated_when_enabled(
    tmp_path: Path,
) -> None:
    assert all(contract.annotations.read_only_hint for contract in READ_ONLY_TOOL_CATALOG)
    assert not any(
        "submit" in contract.name or "delete" in contract.name
        for contract in READ_ONLY_TOOL_CATALOG
    )
    enabled_catalog = tool_catalog(Settings(read_only=False).writes_enabled)
    indexnow = next(contract for contract in enabled_catalog if contract.name == "indexnow_submit")
    assert indexnow.annotations.read_only_hint is False
    assert indexnow.annotations.destructive_hint is True
    assert indexnow.annotations.idempotent_hint is False
    assert indexnow.annotations.open_world_hint is False


@pytest.mark.asyncio
async def test_duplicate_authorization_headers_fail_closed(
    deployment: tuple[Settings, ApplicationServices],
    tmp_path: Path,
) -> None:
    settings, services = deployment
    bearer_file = tmp_path / "bearer"
    bearer_file.write_text("z" * 32, encoding="utf-8")
    bearer_file.chmod(_OWNER_ONLY_SECRET_FILE_MODE)
    app = create_http_app(
        settings.model_copy(update={"http_bearer_secret_file": bearer_file}),
        services,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://rankrat.test",
    ) as client:
        response = await client.get(
            "/v1/server-info",
            headers=[
                ("authorization", f"Bearer {'z' * 32}"),
                ("authorization", f"Bearer {'z' * 32}"),
            ],
        )
    assert response.status_code == 401
    assert response.json() == {
        "code": "UNAUTHORIZED",
        "message": "missing or invalid bearer token",
    }
    assert "z" * 32 not in json.dumps(response.json())
