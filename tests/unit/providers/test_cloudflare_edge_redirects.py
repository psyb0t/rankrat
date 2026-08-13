from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from rankrat.errors import BoundaryDeniedError
from rankrat.models.boundaries import BoundaryDocument
from rankrat.policy.boundaries import BoundaryPolicy
from rankrat.providers.base import AccountId, ProviderReadRequest
from rankrat.providers.cloudflare_performance import (
    CloudflarePerformanceClient,
    CloudflareRedirectStatus,
)

_ZONE_ID = "a" * 32
_RULE_ID = "b" * 32
_RULESET_ID = "ruleset-1"


def _policy(token_file: Path) -> BoundaryPolicy:
    return BoundaryPolicy(
        BoundaryDocument.model_validate(
            {
                "accounts": [
                    {
                        "id": "cloudflare-main",
                        "provider": "cloudflare",
                        "credential": str(token_file),
                        "dns_zones": [{"provider_zone_id": _ZONE_ID, "name": "example.com"}],
                    }
                ]
            }
        )
    )


def _client(tmp_path: Path, transport: httpx.AsyncBaseTransport) -> CloudflarePerformanceClient:
    token_file = tmp_path / "cloudflare-token"
    token_file.write_text("valid_cloudflare_token_123", encoding="ascii")
    return CloudflarePerformanceClient(_policy(token_file), lambda: transport)


def _managed_rule(
    *,
    target_url: str = "https://target.example/new",
    status_code: int = 301,
) -> dict[str, object]:
    return {
        "id": _RULE_ID,
        "ref": "rankrat_redirect_6d69407ea481e45e",
        "action": "redirect",
        "expression": 'http.request.uri.path eq "/old"',
        "description": "Managed by Rankrat [edge-redirect] rankrat_redirect_6d69407ea481e45e",
        "enabled": True,
        "action_parameters": {
            "from_value": {
                "target_url": {"value": target_url},
                "status_code": status_code,
                "preserve_query_string": True,
            }
        },
    }


def _ruleset(rules: list[dict[str, object]]) -> dict[str, object]:
    return {
        "success": True,
        "result": {
            "id": _RULESET_ID,
            "name": "Dynamic Redirects",
            "kind": "zone",
            "phase": "http_request_dynamic_redirect",
            "rules": rules,
        },
    }


def _request() -> ProviderReadRequest:
    return ProviderReadRequest(AccountId("cloudflare-main"), 1.0)


@pytest.mark.asyncio
async def test_cloudflare_redirect_list_filters_unmanaged_rules_and_validates_the_wire_shape(
    tmp_path: Path,
) -> None:
    unmanaged: dict[str, object] = {
        "id": "c" * 32,
        "action": "redirect",
        "expression": "true",
        "description": "Operator redirect",
        "enabled": True,
        "action_parameters": {},
    }

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path.endswith(
            "/rulesets/phases/http_request_dynamic_redirect/entrypoint"
        )
        assert request.headers["Authorization"] == "Bearer valid_cloudflare_token_123"
        return httpx.Response(200, json=_ruleset([unmanaged, _managed_rule()]))

    redirects = await _client(tmp_path, httpx.MockTransport(handler)).list_edge_redirects(
        _request(),
        _ZONE_ID,
    )
    assert len(redirects) == 1
    assert redirects[0].source_path == "/old"
    assert redirects[0].target_url == "https://target.example/new"
    assert redirects[0].status_code is CloudflareRedirectStatus.MOVED_PERMANENTLY


@pytest.mark.asyncio
async def test_cloudflare_redirect_upsert_preserves_other_rules_and_is_idempotent(
    tmp_path: Path,
) -> None:
    requests: list[httpx.Request] = []
    existing = _managed_rule()

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.method == "GET"
        return httpx.Response(200, json=_ruleset([existing]))

    receipt = await _client(tmp_path, httpx.MockTransport(handler)).upsert_edge_redirect(
        _request(),
        _ZONE_ID,
        "/old",
        "https://target.example/new",
        CloudflareRedirectStatus.MOVED_PERMANENTLY,
        True,
    )
    assert receipt.created is False
    assert receipt.changed is False
    assert [request.method for request in requests] == ["GET"]


@pytest.mark.asyncio
async def test_cloudflare_redirect_upsert_writes_only_the_matching_managed_rule(
    tmp_path: Path,
) -> None:
    requests: list[httpx.Request] = []
    existing = _managed_rule()
    changed = _managed_rule(target_url="https://target.example/replacement", status_code=302)

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(200, json=_ruleset([existing]))
        assert request.method == "PATCH"
        assert request.url.path.endswith(f"/rulesets/{_RULESET_ID}/rules/{_RULE_ID}")
        payload = json.loads(request.content)
        assert payload["action"] == "redirect"
        assert payload["description"].startswith("Managed by Rankrat [edge-redirect]")
        assert payload["action_parameters"]["from_value"]["target_url"] == {
            "value": "https://target.example/replacement"
        }
        return httpx.Response(200, json=_ruleset([changed]))

    receipt = await _client(tmp_path, httpx.MockTransport(handler)).upsert_edge_redirect(
        _request(),
        _ZONE_ID,
        "/old",
        "https://target.example/replacement",
        CloudflareRedirectStatus.FOUND,
        True,
    )
    assert receipt.created is False
    assert receipt.changed is True
    assert receipt.redirect.status_code is CloudflareRedirectStatus.FOUND
    assert [request.method for request in requests] == ["GET", "PATCH"]


@pytest.mark.asyncio
async def test_cloudflare_redirect_delete_refuses_unmanaged_rules(tmp_path: Path) -> None:
    foreign_rule: dict[str, object] = {
        "id": _RULE_ID,
        "action": "redirect",
        "expression": "true",
        "description": "Operator redirect",
        "enabled": True,
        "action_parameters": {},
    }
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=_ruleset([foreign_rule]))

    client = _client(tmp_path, httpx.MockTransport(handler))
    with pytest.raises(BoundaryDeniedError, match="not managed"):
        await client.delete_edge_redirect(_request(), _ZONE_ID, _RULE_ID)
    assert [request.method for request in requests] == ["GET"]
