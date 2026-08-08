from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from rankrat.errors import BoundaryDeniedError, InputLimitError
from rankrat.models.boundaries import BoundaryDocument
from rankrat.policy.boundaries import BoundaryPolicy
from rankrat.providers.base import (
    AccountId,
    ProviderFailureCode,
    ProviderOperationError,
    ProviderReadRequest,
)
from rankrat.providers.cloudflare_performance import (
    CloudflareCacheTemplate,
    CloudflarePerformanceClient,
)

_ZONE_ID = "a" * 32


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


def _request() -> ProviderReadRequest:
    return ProviderReadRequest(AccountId("cloudflare-main"), 1.0)


def _client(
    tmp_path: Path,
    transport: httpx.AsyncBaseTransport,
) -> CloudflarePerformanceClient:
    token_file = tmp_path / "cloudflare-token"
    token_file.write_text("valid_cloudflare_token_123", encoding="ascii")
    return CloudflarePerformanceClient(_policy(token_file), lambda: transport)


@pytest.mark.asyncio
async def test_cloudflare_analytics_is_fixed_origin_and_bounded(tmp_path: Path) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://api.cloudflare.com/client/v4/graphql"
        assert request.headers["Authorization"] == "Bearer valid_cloudflare_token_123"
        body = json.loads(request.content)
        assert body["variables"]["zoneTag"] == _ZONE_ID
        assert body["variables"]["limit"] == 10
        assert "trustedClientCategory: verifiedBotCategory" in body["query"]
        assert "orderBy: [datetimeHour_ASC]" in body["query"]
        assert "dimensions_datetimeHour_ASC" not in body["query"]
        return httpx.Response(
            200,
            json={
                "data": {
                    "viewer": {
                        "zones": [
                            {
                                "traffic": [
                                    {
                                        "count": 12,
                                        "sum": {"edgeResponseBytes": 42, "visits": 3},
                                        "avg": {"sampleInterval": 2.0},
                                        "dimensions": {
                                            "datetimeHour": "2025-01-01T00:00:00Z",
                                            "cacheStatus": "hit",
                                            "edgeResponseStatus": 200,
                                            "trustedClientCategory": "HONEST_BOT",
                                        },
                                    }
                                ]
                            }
                        ]
                    }
                }
            },
        )

    client = _client(tmp_path, httpx.MockTransport(handler))
    report = await client.analytics(
        _request(),
        _ZONE_ID,
        datetime(2025, 1, 1, tzinfo=UTC),
        datetime(2025, 1, 2, tzinfo=UTC),
        10,
    )
    assert report.sampled is True
    assert report.points[0].requests == 12
    assert report.points[0].trusted_client_category == "HONEST_BOT"


@pytest.mark.asyncio
async def test_cloudflare_purges_only_exact_site_urls(tmp_path: Path) -> None:
    observed: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        observed.update(json.loads(request.content))
        return httpx.Response(200, json={"success": True, "result": {"id": "purge-1"}})

    client = _client(tmp_path, httpx.MockTransport(handler))
    receipt = await client.purge_urls(
        _request(),
        _ZONE_ID,
        "https://example.com/",
        ("https://example.com/a", "https://example.com/b"),
    )
    assert receipt.provider_request_id == "purge-1"
    assert observed == {"files": ["https://example.com/a", "https://example.com/b"]}

    with pytest.raises(BoundaryDeniedError):
        await client.purge_urls(
            _request(),
            _ZONE_ID,
            "https://example.com/",
            ("https://attacker.invalid/a",),
        )
    with pytest.raises(InputLimitError, match="repeat"):
        await client.purge_urls(
            _request(),
            _ZONE_ID,
            "https://example.com/",
            ("https://example.com/a", "https://example.com/a"),
        )


@pytest.mark.asyncio
async def test_cloudflare_cache_template_preserves_unmanaged_rules(tmp_path: Path) -> None:
    requests: list[httpx.Request] = []
    unmanaged = {
        "id": "rule-existing",
        "action": "set_cache_settings",
        "expression": "true",
        "description": "Operator-managed rule",
        "enabled": True,
        "action_parameters": {"cache": False},
    }

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "result": {
                        "id": "ruleset-1",
                        "name": "default",
                        "kind": "zone",
                        "phase": "http_request_cache_settings",
                        "rules": [unmanaged],
                    },
                },
            )
        assert request.url.path.endswith("/rulesets/ruleset-1/rules")
        body = json.loads(request.content)
        assert body["description"] == "Managed by Rankrat [cache_static_assets]"
        return httpx.Response(
            200,
            json={
                "success": True,
                "result": {
                    "id": "ruleset-1",
                    "name": "default",
                    "kind": "zone",
                    "phase": "http_request_cache_settings",
                    "rules": [
                        unmanaged,
                        {
                            **body,
                            "id": "rule-rankrat",
                        },
                    ],
                },
            },
        )

    client = _client(tmp_path, httpx.MockTransport(handler))
    receipt = await client.apply_cache_template(
        _request(),
        _ZONE_ID,
        CloudflareCacheTemplate.CACHE_STATIC_ASSETS,
    )
    assert receipt.changed is True
    assert receipt.rule_id == "rule-rankrat"
    assert [request.method for request in requests] == ["GET", "POST"]


@pytest.mark.asyncio
async def test_cloudflare_cache_template_is_idempotent(tmp_path: Path) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        return httpx.Response(
            200,
            json={
                "success": True,
                "result": {
                    "id": "ruleset-1",
                    "name": "default",
                    "kind": "zone",
                    "phase": "http_request_cache_settings",
                    "rules": [
                        {
                            "id": "rule-rankrat",
                            "action": "set_cache_settings",
                            "expression": (
                                '(http.request.uri.path.extension in {"" "html" "htm"})'
                            ),
                            "description": "Managed by Rankrat [bypass_html]",
                            "enabled": True,
                            "action_parameters": {"cache": False},
                        }
                    ],
                },
            },
        )

    client = _client(tmp_path, httpx.MockTransport(handler))
    receipt = await client.apply_cache_template(
        _request(),
        _ZONE_ID,
        CloudflareCacheTemplate.BYPASS_HTML,
    )
    assert receipt.changed is False
    assert receipt.rule_id == "rule-rankrat"


@pytest.mark.asyncio
async def test_cloudflare_cache_template_serializes_concurrent_creation(
    tmp_path: Path,
) -> None:
    requests: list[str] = []
    managed_rule: dict[str, object] | None = None

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal managed_rule
        requests.append(request.method)
        if request.method == "GET":
            if managed_rule is None:
                await asyncio.sleep(0.01)
            rules = [] if managed_rule is None else [managed_rule]
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "result": {
                        "id": "ruleset-1",
                        "name": "default",
                        "kind": "zone",
                        "phase": "http_request_cache_settings",
                        "rules": rules,
                    },
                },
            )
        body = json.loads(request.content)
        managed_rule = {**body, "id": "rule-rankrat"}
        return httpx.Response(
            200,
            json={
                "success": True,
                "result": {
                    "id": "ruleset-1",
                    "name": "default",
                    "kind": "zone",
                    "phase": "http_request_cache_settings",
                    "rules": [managed_rule],
                },
            },
        )

    client = _client(tmp_path, httpx.MockTransport(handler))
    receipts = await asyncio.gather(
        client.apply_cache_template(
            _request(),
            _ZONE_ID,
            CloudflareCacheTemplate.BYPASS_HTML,
        ),
        client.apply_cache_template(
            _request(),
            _ZONE_ID,
            CloudflareCacheTemplate.BYPASS_HTML,
        ),
    )

    assert requests == ["GET", "POST", "GET"]
    assert [receipt.changed for receipt in receipts] == [True, False]


@pytest.mark.asyncio
async def test_cloudflare_cache_template_updates_only_the_managed_rule(tmp_path: Path) -> None:
    methods: list[str] = []
    prior_rule = {
        "id": "rule-rankrat",
        "action": "set_cache_settings",
        "expression": "true",
        "description": "Managed by Rankrat [bypass_html]",
        "enabled": True,
        "action_parameters": {"cache": True},
    }

    async def handler(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        rules = [prior_rule]
        if request.method == "PATCH":
            assert request.url.path.endswith("/rules/rule-rankrat")
            updated = json.loads(request.content)
            rules = [{**updated, "id": "rule-rankrat"}]
        return httpx.Response(
            200,
            json={
                "success": True,
                "result": {
                    "id": "ruleset-1",
                    "name": "default",
                    "kind": "zone",
                    "phase": "http_request_cache_settings",
                    "rules": rules,
                },
            },
        )

    client = _client(tmp_path, httpx.MockTransport(handler))
    receipt = await client.apply_cache_template(
        _request(),
        _ZONE_ID,
        CloudflareCacheTemplate.BYPASS_HTML,
    )

    assert methods == ["GET", "PATCH"]
    assert receipt.changed is True
    assert receipt.previous_managed_rule == {
        key: value for key, value in prior_rule.items() if key != "id"
    }


@pytest.mark.asyncio
async def test_cloudflare_cache_template_rejects_duplicate_managed_markers(
    tmp_path: Path,
) -> None:
    marker = "Managed by Rankrat [bypass_html]"

    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "success": True,
                "result": {
                    "id": "ruleset-1",
                    "name": "default",
                    "kind": "zone",
                    "phase": "http_request_cache_settings",
                    "rules": [
                        {
                            "id": "one",
                            "action": "set_cache_settings",
                            "expression": "true",
                            "description": marker,
                        },
                        {
                            "id": "two",
                            "action": "set_cache_settings",
                            "expression": "true",
                            "description": marker,
                        },
                    ],
                },
            },
        )

    client = _client(tmp_path, httpx.MockTransport(handler))
    with pytest.raises(ProviderOperationError) as raised:
        await client.apply_cache_template(
            _request(),
            _ZONE_ID,
            CloudflareCacheTemplate.BYPASS_HTML,
        )
    assert raised.value.code is ProviderFailureCode.INVALID_RESPONSE


@pytest.mark.asyncio
async def test_cloudflare_creates_a_missing_cache_ruleset(tmp_path: Path) -> None:
    methods: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        if request.method == "GET":
            return httpx.Response(404, json={})
        body = json.loads(request.content)
        rule = body["rules"][0]
        return httpx.Response(
            200,
            json={
                "success": True,
                "result": {
                    "id": "created-ruleset",
                    "name": body["name"],
                    "kind": body["kind"],
                    "phase": body["phase"],
                    "rules": [{**rule, "id": "created-rule"}],
                },
            },
        )

    receipt = await _client(tmp_path, httpx.MockTransport(handler)).apply_cache_template(
        _request(),
        _ZONE_ID,
        CloudflareCacheTemplate.CACHE_STATIC_ASSETS,
    )

    assert methods == ["GET", "PUT"]
    assert receipt.ruleset_id == "created-ruleset"
    assert receipt.rule_id == "created-rule"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("operation", "payload"),
    [
        ("analytics", {"errors": [{"message": "nope"}]}),
        ("purge", {"success": False, "result": {"id": "request"}}),
        (
            "ruleset",
            {
                "success": False,
                "result": {
                    "id": "ruleset",
                    "name": "default",
                    "kind": "zone",
                    "phase": "http_request_cache_settings",
                    "rules": [],
                },
            },
        ),
    ],
)
async def test_cloudflare_rejects_unsuccessful_provider_payloads(
    tmp_path: Path,
    operation: str,
    payload: dict[str, object],
) -> None:
    client = _client(
        tmp_path,
        httpx.MockTransport(lambda _: httpx.Response(200, content=json.dumps(payload).encode())),
    )

    with pytest.raises(ProviderOperationError) as raised:
        if operation == "analytics":
            await client.analytics(
                _request(),
                _ZONE_ID,
                datetime(2025, 1, 1, tzinfo=UTC),
                datetime(2025, 1, 2, tzinfo=UTC),
                1,
            )
        elif operation == "purge":
            await client.purge_urls(
                _request(),
                _ZONE_ID,
                "https://example.com/",
                ("https://example.com/page",),
            )
        else:
            await client.apply_cache_template(
                _request(),
                _ZONE_ID,
                CloudflareCacheTemplate.BYPASS_HTML,
            )

    assert raised.value.code in {
        ProviderFailureCode.UNAVAILABLE,
        ProviderFailureCode.INVALID_RESPONSE,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (httpx.Response(401), ProviderFailureCode.AUTHENTICATION),
        (httpx.Response(403), ProviderFailureCode.FORBIDDEN),
        (httpx.Response(429), ProviderFailureCode.RATE_LIMITED),
        (httpx.Response(500), ProviderFailureCode.UNAVAILABLE),
        (
            httpx.Response(302, headers={"location": "https://example.invalid"}),
            ProviderFailureCode.INVALID_RESPONSE,
        ),
        (httpx.Response(400), ProviderFailureCode.INVALID_RESPONSE),
    ],
)
async def test_cloudflare_maps_provider_statuses(
    tmp_path: Path,
    response: httpx.Response,
    expected: ProviderFailureCode,
) -> None:
    client = _client(tmp_path, httpx.MockTransport(lambda _: response))

    with pytest.raises(ProviderOperationError) as raised:
        await client.analytics(
            _request(),
            _ZONE_ID,
            datetime(2025, 1, 1, tzinfo=UTC),
            datetime(2025, 1, 2, tzinfo=UTC),
            1,
        )

    assert raised.value.code is expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (httpx.ReadTimeout("slow"), ProviderFailureCode.TIMEOUT),
        (httpx.ConnectError("offline"), ProviderFailureCode.UNAVAILABLE),
    ],
)
async def test_cloudflare_maps_transport_failures(
    tmp_path: Path,
    failure: httpx.HTTPError,
    expected: ProviderFailureCode,
) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        raise failure

    client = _client(tmp_path, httpx.MockTransport(handler))
    with pytest.raises(ProviderOperationError) as raised:
        await client.analytics(
            _request(),
            _ZONE_ID,
            datetime(2025, 1, 1, tzinfo=UTC),
            datetime(2025, 1, 2, tzinfo=UTC),
            1,
        )
    assert raised.value.code is expected


@pytest.mark.asyncio
async def test_cloudflare_rejects_invalid_json(tmp_path: Path) -> None:
    client = _client(
        tmp_path,
        httpx.MockTransport(lambda _: httpx.Response(200, content=b"not-json")),
    )
    with pytest.raises(ProviderOperationError) as raised:
        await client.analytics(
            _request(),
            _ZONE_ID,
            datetime(2025, 1, 1, tzinfo=UTC),
            datetime(2025, 1, 2, tzinfo=UTC),
            1,
        )
    assert raised.value.code is ProviderFailureCode.INVALID_RESPONSE


@pytest.mark.parametrize("content", [b"bad token", b"\xff", b"x" * 10_000])
def test_cloudflare_rejects_invalid_token_files(tmp_path: Path, content: bytes) -> None:
    token_file = tmp_path / "token"
    token_file.write_bytes(content)

    with pytest.raises(ProviderOperationError) as raised:
        CloudflarePerformanceClient._load_token(token_file)

    assert raised.value.code is ProviderFailureCode.AUTHENTICATION


def test_cloudflare_rejects_symlinked_token_file(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.write_text("valid_cloudflare_token_123", encoding="ascii")
    link = tmp_path / "token"
    link.symlink_to(target)

    with pytest.raises(ProviderOperationError) as raised:
        CloudflarePerformanceClient._load_token(link)

    assert raised.value.code is ProviderFailureCode.AUTHENTICATION


@pytest.mark.asyncio
async def test_cloudflare_rejects_nan_analytics_and_invalid_zone(tmp_path: Path) -> None:
    payload = {
        "data": {
            "viewer": {
                "zones": [
                    {
                        "traffic": [
                            {
                                "count": 1,
                                "sum": {},
                                "avg": {"sampleInterval": float("nan")},
                                "dimensions": {"datetimeHour": "2025-01-01T00:00:00Z"},
                            }
                        ]
                    }
                ]
            }
        }
    }
    client = _client(
        tmp_path,
        httpx.MockTransport(lambda _: httpx.Response(200, content=json.dumps(payload).encode())),
    )
    with pytest.raises(ProviderOperationError) as raised:
        await client.analytics(
            _request(),
            _ZONE_ID,
            datetime(2025, 1, 1, tzinfo=UTC),
            datetime(2025, 1, 2, tzinfo=UTC),
            1,
        )
    assert raised.value.code is ProviderFailureCode.UNAVAILABLE
    with pytest.raises(BoundaryDeniedError, match="zone ID"):
        await client.analytics(
            _request(),
            "not-a-zone",
            datetime(2025, 1, 1, tzinfo=UTC),
            datetime(2025, 1, 2, tzinfo=UTC),
            1,
        )


@pytest.mark.asyncio
async def test_cloudflare_purge_rejects_empty_and_mismatched_zone(tmp_path: Path) -> None:
    client = _client(tmp_path, httpx.MockTransport(lambda _: pytest.fail("no network")))
    with pytest.raises(InputLimitError, match="count"):
        await client.purge_urls(_request(), _ZONE_ID, "https://example.com/", ())
    with pytest.raises(BoundaryDeniedError, match="configured zone"):
        await client.purge_urls(
            _request(),
            "b" * 32,
            "https://example.com/",
            ("https://example.com/page",),
        )


@pytest.mark.asyncio
async def test_cloudflare_cache_template_requires_stable_managed_rule_id(
    tmp_path: Path,
) -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "success": True,
                "result": {
                    "id": "ruleset",
                    "name": "default",
                    "kind": "zone",
                    "phase": "http_request_cache_settings",
                    "rules": [
                        {
                            "action": "set_cache_settings",
                            "expression": "true",
                            "description": "Managed by Rankrat [bypass_html]",
                        }
                    ],
                },
            },
        )

    client = _client(tmp_path, httpx.MockTransport(handler))
    with pytest.raises(ProviderOperationError, match="stable identifier"):
        await client.apply_cache_template(
            _request(),
            _ZONE_ID,
            CloudflareCacheTemplate.BYPASS_HTML,
        )


@pytest.mark.asyncio
async def test_cloudflare_cache_template_rejects_ambiguous_update_response(
    tmp_path: Path,
) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        rules = [
            {
                "id": "rule",
                "action": "set_cache_settings",
                "expression": "true",
                "description": "Managed by Rankrat [bypass_html]",
            }
        ]
        if request.method == "PATCH":
            rules = []
        return httpx.Response(
            200,
            json={
                "success": True,
                "result": {
                    "id": "ruleset",
                    "name": "default",
                    "kind": "zone",
                    "phase": "http_request_cache_settings",
                    "rules": rules,
                },
            },
        )

    client = _client(tmp_path, httpx.MockTransport(handler))
    with pytest.raises(ProviderOperationError) as raised:
        await client.apply_cache_template(
            _request(),
            _ZONE_ID,
            CloudflareCacheTemplate.BYPASS_HTML,
        )
    assert raised.value.code is ProviderFailureCode.INVALID_RESPONSE
