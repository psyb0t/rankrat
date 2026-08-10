from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType

import httpx
import pytest

from rankrat.policy.boundaries import BoundaryPolicy

_SCRIPT_PATH = Path("scripts/run_live_http_image.py")
_SHELL_SCRIPT_PATH = Path("scripts/test_live_http_image.sh")
_FINAL_IMAGE_SCRIPT_PATH = Path("scripts/test_final_image.sh")
_MAKEFILE_PATH = Path("Makefile")
_MODULE_NAME = "rankrat_live_http_image"
_TEST_BEARER_SECRET = "test-only-not-a-real-secret-value-000000000000"
_TEST_UPSTREAM_MESSAGE = "upstream response must never appear in verifier output"
_HTTP_OK_STATUS = 200
_HTTP_BAD_GATEWAY_STATUS = 502
_MCP_PROTOCOL_VERSION = "2025-03-26"
_MINIMUM_COLD_START_MCP_TIMEOUT_SECONDS = 30
_PROVIDER_AUTHENTICATION_CODE = "AUTHENTICATION"


def _load_verifier_module() -> ModuleType:
    specification = importlib.util.spec_from_file_location(_MODULE_NAME, _SCRIPT_PATH)
    assert specification is not None
    assert specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    sys.modules[_MODULE_NAME] = module
    specification.loader.exec_module(module)
    return module


def _policy(tmp_path: Path) -> BoundaryPolicy:
    secret_root = tmp_path / "secrets"
    oauth_root = tmp_path / "oauth"
    secret_root.mkdir()
    oauth_root.mkdir()
    boundary_file = tmp_path / "boundaries.json"
    boundary_file.write_text(
        json.dumps(
            {
                "accounts": [
                    {
                        "id": "google-main",
                        "provider": "google",
                        "credential": str(secret_root / "google" / "oauth-client.json"),
                        "oauth_token_file": str(oauth_root / "google.json"),
                        "pagespeed_api_key_file": str(secret_root / "google" / "pagespeed-api-key"),
                        "search_console_sites": ["sc-domain:example.com"],
                        "pagespeed_sites": ["https://example.com/"],
                        "ga4_properties": ["123456789"],
                    },
                    {
                        "id": "bing-main",
                        "provider": "bing",
                        "credential": str(secret_root / "bing" / "api-key"),
                        "sites": ["https://example.com/"],
                    },
                    {
                        "id": "cloudflare-main",
                        "provider": "cloudflare",
                        "credential": str(secret_root / "cloudflare" / "api-token"),
                        "dns_zones": [
                            {
                                "provider_zone_id": "a" * 32,
                                "name": "example.com",
                            }
                        ],
                    },
                ],
                "indexnow_targets": [],
            }
        ),
        encoding="utf-8",
    )
    return BoundaryPolicy.from_file(boundary_file, secret_root, oauth_root)


@pytest.mark.asyncio
async def test_live_http_verifier_exercises_real_transport_route_shapes(tmp_path: Path) -> None:
    module = _load_verifier_module()
    requests: list[httpx.Request] = []

    def response(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path != "/healthz":
            assert request.headers["authorization"] == f"Bearer {_TEST_BEARER_SECRET}"
        if request.url.path == "/mcp/":
            return httpx.Response(
                _HTTP_OK_STATUS,
                json={"result": {"protocolVersion": _MCP_PROTOCOL_VERSION}},
            )
        return httpx.Response(_HTTP_OK_STATUS, json={})

    verifier = module.LiveHttpVerifier(
        _policy(tmp_path),
        "http://rankrat.test",
        _TEST_BEARER_SECRET,
    )
    completed = await verifier.verify(httpx.MockTransport(response))

    assert {(request.method, request.url.path) for request in requests} == {
        ("GET", "/healthz"),
        ("GET", "/ready"),
        ("POST", "/mcp/"),
        ("GET", "/v1/accounts"),
        ("GET", "/v1/provider-readiness"),
        ("POST", "/v1/google/search-analytics-summary"),
        ("POST", "/v1/google-analytics/account-inventory"),
        ("POST", "/v1/google-analytics/reports"),
        ("POST", "/v1/pagespeed/analyses"),
        ("POST", "/v1/bing/traffic-trend"),
        ("POST", "/v1/cloudflare/analytics-reports"),
    }
    assert "mcp" in completed
    assert "pagespeed" in completed
    assert "bing-traffic" in completed
    assert "cloudflare-analytics" in completed


@pytest.mark.asyncio
async def test_live_http_verifier_reports_only_a_bounded_provider_error_code(
    tmp_path: Path,
) -> None:
    module = _load_verifier_module()

    def response(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            _HTTP_BAD_GATEWAY_STATUS,
            json={
                "code": _PROVIDER_AUTHENTICATION_CODE,
                "message": _TEST_UPSTREAM_MESSAGE,
            },
        )

    verifier = module.LiveHttpVerifier(
        _policy(tmp_path),
        "http://rankrat.test",
        _TEST_BEARER_SECRET,
    )
    async with httpx.AsyncClient(
        base_url="http://rankrat.test",
        transport=httpx.MockTransport(response),
    ) as client:
        with pytest.raises(module.LiveHttpVerificationError) as error:
            await verifier._request(client, "GET", "/v1/provider-readiness")

    assert str(error.value) == "GET /v1/provider-readiness returned HTTP 502 (AUTHENTICATION)"
    assert _TEST_UPSTREAM_MESSAGE not in str(error.value)


@pytest.mark.asyncio
async def test_live_http_verifier_accepts_a_valid_list_response_for_inventory(
    tmp_path: Path,
) -> None:
    module = _load_verifier_module()

    def response(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/mcp/":
            return httpx.Response(
                _HTTP_OK_STATUS,
                json={"result": {"protocolVersion": _MCP_PROTOCOL_VERSION}},
            )
        if request.url.path == "/v1/google-analytics/account-inventory":
            return httpx.Response(_HTTP_OK_STATUS, json=[])
        return httpx.Response(_HTTP_OK_STATUS, json={})

    verifier = module.LiveHttpVerifier(
        _policy(tmp_path),
        "http://rankrat.test",
        _TEST_BEARER_SECRET,
    )

    completed = await verifier.verify(httpx.MockTransport(response))

    assert "google-analytics-inventory" in completed


def test_live_http_make_target_uses_production_and_dev_images() -> None:
    makefile = _MAKEFILE_PATH.read_text(encoding="utf-8")
    target = makefile.split("test-live-http:", maxsplit=1)[1].split("\n\n", maxsplit=1)[0]

    assert "build dev-image" in target
    assert "scripts/test_live_http_image.sh" in target
    assert "$(IMAGE_NAME):$(IMAGE_TAG)" in target
    assert "$(DEV_IMAGE)" in target
    assert "$(ENV_FILE)" not in target


def test_live_http_shell_runner_uses_default_egress_and_never_submits_indexnow() -> None:
    script = _SHELL_SCRIPT_PATH.read_text(encoding="utf-8")

    assert 'docker run -d --name "$container_name" --network bridge' in script
    assert "docker inspect --format" in script
    assert '--add-host "$SERVICE_HOSTNAME:$service_ip"' in script
    assert "--read-only" in script
    assert "--cap-drop=ALL" in script
    assert "no-new-privileges:true" in script
    assert 'install -m 600 "$boundary_file" "$runtime_config_directory/boundaries.json"' in script
    assert "src=$runtime_config_directory,dst=/run/config,readonly" in script
    assert "dst=/run/config/boundaries.json" not in script
    assert '--mount "type=bind,src=$secret_directory,dst=/run/secrets,readonly"' in script
    assert '--mount "type=bind,src=$oauth_directory,dst=/run/oauth"' in script
    assert '--mount "type=bind,src=$oauth_directory,dst=/run/oauth,readonly"' in script
    assert "run_live_http_image.py" in script
    assert "indexnow" not in script.lower()
    assert "environment_file" not in script
    assert "--env-file" not in script


def test_final_image_exercises_writable_stdio_with_mounted_state() -> None:
    script = _FINAL_IMAGE_SCRIPT_PATH.read_text(encoding="utf-8")

    security_arguments = script.split("container_security_args=(", maxsplit=1)[1].split(
        ")\nreadonly -a container_security_args",
        maxsplit=1,
    )[0]
    assert "RANKRAT_READ_ONLY=true" in security_arguments
    assert "checking writable stdio MCP persists monitor state" in script
    assert "type=bind,src=$state_directory,dst=/run/state" in script
    assert "RANKRAT_STATE_DATABASE=/run/state/rankrat.sqlite3" in script
    assert "RANKRAT_READ_ONLY=false" in script
    assert '[[ -f "$state_directory/rankrat.sqlite3" ]]' in script
    assert "Audit '\\'' OR 1=1--" in script


def test_final_image_runs_changed_surface_bad_input_smoke() -> None:
    script = _FINAL_IMAGE_SCRIPT_PATH.read_text(encoding="utf-8")

    assert "INVALID_INTERNAL_LINK_REQUEST" in script
    assert "CROSS_BOUNDARY_CRUX_REQUEST" in script
    assert '[[ "$oversized_status" == "413" ]]' in script
    assert '"code":"VALIDATION_FAILED"' in script


def test_final_image_streamable_mcp_uses_the_mcp_timeout_budget() -> None:
    script = _FINAL_IMAGE_SCRIPT_PATH.read_text(encoding="utf-8")
    streamable_mcp_block = script.split('streamable_mcp_output=""', maxsplit=1)[1].split(
        "unauthorized_openapi_status=", maxsplit=1
    )[0]

    assert '--connect-timeout "$HTTP_CONNECT_TIMEOUT_SECONDS"' in streamable_mcp_block
    assert '--max-time "$MCP_TIMEOUT_SECONDS"' in streamable_mcp_block
    assert '--max-time "$HTTP_CONNECT_TIMEOUT_SECONDS"' not in streamable_mcp_block

    timeout_assignment = next(
        line for line in script.splitlines() if line.startswith("readonly MCP_TIMEOUT_SECONDS=")
    )
    timeout_seconds = int(timeout_assignment.partition("=")[2])
    assert timeout_seconds >= _MINIMUM_COLD_START_MCP_TIMEOUT_SECONDS


@pytest.mark.parametrize("argument_count", [0, 5, 7])
def test_live_http_shell_runner_rejects_wrong_argument_shapes_before_docker(
    argument_count: int,
) -> None:
    result = subprocess.run(  # noqa: S603 -- fixed checked-in script with inert test arguments.
        ["/bin/bash", str(_SHELL_SCRIPT_PATH), *(["unused"] * argument_count)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert "usage:" in result.stderr
    assert "docker" not in result.stderr.lower()


def test_live_http_report_period_uses_two_finalized_days(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_verifier_module()

    class FixedDatetime:
        @classmethod
        def now(cls, tz: object) -> datetime:
            assert tz is UTC
            return datetime(2026, 8, 2, tzinfo=UTC)

    monkeypatch.setattr(module, "datetime", FixedDatetime)

    assert module._report_period() == ("2026-07-25", "2026-07-31")
