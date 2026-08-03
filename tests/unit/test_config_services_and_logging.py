from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from rankrat.config import Settings, load_settings
from rankrat.errors import BoundaryDeniedError, ConfigurationError
from rankrat.logging import (
    JsonFormatter,
    configure_logging,
    log_event,
    reset_log_scope,
    with_log_scope,
)
from rankrat.models.boundaries import Provider
from rankrat.policy.boundaries import BoundaryPolicy
from rankrat.providers.base import (
    AccountId,
    ProviderFailureCode,
    ProviderOperationError,
    ProviderReadiness,
    ProviderReadRequest,
)
from rankrat.services.capabilities import ServerInfoRequest
from rankrat.services.diagnostics import DiagnosticsRequest, DiagnosticStatus
from rankrat.services.provider_readiness import (
    ProviderReadinessRequest,
    ProviderReadinessService,
)
from rankrat.services.sites import AccountsListRequest, SitesListRequest
from rankrat.transports.auth import bearer_is_valid, load_bearer_secret
from rankrat.transports.runtime import ApplicationServices
from rankrat.transports.tool_contracts import ToolAnnotations


def test_settings_validate_exposure_paths_levels_and_write_mode(tmp_path: Path) -> None:
    secret = tmp_path / "bearer"
    secret.write_text("x" * 32, encoding="utf-8")
    settings = Settings(
        http_host="0.0.0.0",
        http_bearer_secret_file=secret,
        boundary_file=tmp_path / "boundaries.json",
        secret_root=tmp_path,
        log_file=tmp_path / "log",
        log_level="debug",
    )
    assert settings.log_level == "DEBUG"
    assert not settings.is_loopback_bind
    assert Settings(http_host="localhost").is_loopback_bind
    assert Settings(http_host="::1").is_loopback_bind

    invalid_settings = [
        {"http_host": "example.com"},
        {"http_host": "   "},
        {"http_host": "0.0.0.0"},
        {"log_level": "TRACE"},
        {"boundary_file": Path("relative")},
        {"oauth_token_root": Path("relative")},
        {"enable_writes": True},
    ]
    for values in invalid_settings:
        with pytest.raises(ValidationError):
            Settings.model_validate(values)
    write_settings = Settings(enable_writes=True, admin_bearer_secret_file=secret)
    assert write_settings.enable_writes is True


def test_load_settings_wraps_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RANKRAT_HTTP_PORT", "invalid")
    with pytest.raises(ConfigurationError):
        load_settings()


def test_services_filter_boundaries_and_report_capabilities(
    deployment: tuple[Settings, ApplicationServices],
) -> None:
    _, services = deployment
    server_info = services.capabilities.server_info(ServerInfoRequest())
    assert server_info.name == "rankrat"
    assert server_info.read_only is True
    assert [item.provider for item in server_info.providers] == [Provider.GOOGLE, Provider.BING]

    accounts = services.sites.accounts_list(AccountsListRequest(provider=Provider.GOOGLE))
    assert [item.account_id for item in accounts.accounts] == ["google-main", "pagespeed-main"]
    sites = services.sites.sites_list(SitesListRequest(account_id="bing-main"))
    assert [item.resource for item in sites.sites] == ["https://example.com/"]
    google_sites = services.sites.sites_list(SitesListRequest(provider=Provider.GOOGLE))
    assert all(item.provider is Provider.GOOGLE for item in google_sites.sites)
    assert not services.sites._matches_account_filter(
        "bing-main",
        Provider.BING,
        SitesListRequest(account_id="google-main"),
    )
    with pytest.raises(BoundaryDeniedError):
        services.sites.sites_list(SitesListRequest(account_id="missing"))
    with pytest.raises(BoundaryDeniedError):
        services.sites.sites_list(
            SitesListRequest(account_id="google-main", provider=Provider.BING)
        )

    diagnostics = services.diagnostics.diagnostics(DiagnosticsRequest())
    assert diagnostics.ready is True
    assert diagnostics.checks[0].status is DiagnosticStatus.PASS
    assert diagnostics.checks[1].status is DiagnosticStatus.NOT_CHECKED


class _ReadyClient:
    def __init__(self, provider: Provider) -> None:
        self.provider = provider

    async def readiness(self, request: ProviderReadRequest) -> ProviderReadiness:
        return ProviderReadiness(request.account_id, self.provider, True, "ready")


@pytest.mark.asyncio
async def test_provider_readiness_dispatches_to_each_configured_provider(
    deployment: tuple[Settings, ApplicationServices],
) -> None:
    settings, _ = deployment
    policy = BoundaryPolicy.from_file(
        settings.boundary_file,
        settings.secret_root,
        settings.oauth_token_root,
    )
    readiness = ProviderReadinessService(
        policy,
        {
            Provider.GOOGLE: _ReadyClient(Provider.GOOGLE),
            Provider.BING: _ReadyClient(Provider.BING),
        },
    )
    google = await readiness.readiness(ProviderReadinessRequest("google-main", 1.0))
    bing = await readiness.readiness(ProviderReadinessRequest("bing-main", 1.0))
    assert google.available is True
    assert bing.available is True

    unavailable = ProviderReadinessService(policy, {Provider.GOOGLE: _ReadyClient(Provider.GOOGLE)})
    missing_client = await unavailable.readiness(ProviderReadinessRequest("bing-main", 1.0))
    assert missing_client.available is False
    assert missing_client.detail == "configured provider client is unavailable"


def test_provider_request_and_error_validation() -> None:
    assert ProviderReadRequest(AccountId("main"), 1.0).timeout_seconds == 1.0
    for timeout in (0.01, 31.0):
        with pytest.raises(ValueError):
            ProviderReadRequest(AccountId("main"), timeout)
    error = ProviderOperationError(ProviderFailureCode.TIMEOUT, "safe")
    assert error.code is ProviderFailureCode.TIMEOUT
    assert str(error) == "safe"


def test_tool_annotations_use_the_documented_mcp_wire_names() -> None:
    assert ToolAnnotations(False, True, False, True).as_mcp() == {
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": False,
        "openWorldHint": True,
    }


def test_bearer_secret_loading_and_constant_time_validation(tmp_path: Path) -> None:
    secret_path = tmp_path / "bearer"
    secret_path.write_text("s" * 32, encoding="utf-8")
    secret_path.chmod(0o600)
    secret = load_bearer_secret(secret_path)
    assert secret == "s" * 32
    assert bearer_is_valid(None, None)
    assert bearer_is_valid(f"Bearer {secret}", secret)
    assert not bearer_is_valid(None, secret)
    assert not bearer_is_valid(f"Basic {secret}", secret)
    assert not bearer_is_valid("Bearer wrong", secret)

    secret_path.chmod(0o644)
    with pytest.raises(ConfigurationError, match="permissions are unsafe"):
        load_bearer_secret(secret_path)

    secret_path.chmod(0o600)
    secret_path.write_text("short", encoding="utf-8")
    with pytest.raises(ConfigurationError):
        load_bearer_secret(secret_path)
    with pytest.raises(ConfigurationError):
        load_bearer_secret(tmp_path / "missing")


def test_structured_logging_redacts_and_scopes(tmp_path: Path) -> None:
    log_file = tmp_path / "logs" / "rankrat.log"
    configure_logging("DEBUG", log_file)
    token = with_log_scope(request_id="request-scope")
    logger = logging.getLogger("rankrat.test")
    log_event(
        logger,
        logging.INFO,
        "safe event",
        authorization="Bearer private",
        nested={"api-key": "private"},
        count=2,
    )
    reset_log_scope(token)
    payload = json.loads(log_file.read_text(encoding="utf-8").splitlines()[-1])
    assert payload["msg"] == "safe event"
    assert payload["request_id"] == "request-scope"
    assert payload["authorization"] == "[REDACTED]"
    assert payload["nested"]["api-key"] == "[REDACTED]"
    assert payload["count"] == 2
    assert os.stat(log_file).st_mode & 0o777 == 0o600
    assert log_event is not None

    assert isinstance(redact_for_test([{"value": "safe"}]), list)
    assert redact_for_test("deep", depth=9) == "deep"

    record = logging.LogRecord("test", logging.INFO, __file__, 1, "hello", (), None)
    assert json.loads(JsonFormatter().format(record))["msg"] == "hello"


def redact_for_test(value: object, depth: int = 0) -> object:
    from rankrat.logging import redact

    return redact(value, depth=depth)
