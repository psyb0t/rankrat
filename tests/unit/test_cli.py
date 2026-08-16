from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from rankrat import cli
from rankrat.config import Settings
from rankrat.constants import OAUTH_DYNAMIC_CALLBACK_PORT, OAUTH_LOOPBACK_HOST
from rankrat.models.boundaries import BoundaryDocument, Provider
from rankrat.policy.boundaries import BoundaryPolicy
from rankrat.providers.base import (
    AccountId,
    ProviderFailureCode,
    ProviderOperationError,
    ProviderReadiness,
)
from rankrat.services.provider_readiness import ProviderReadinessRequest


def _oauth_policy(tmp_path: Path) -> BoundaryPolicy:
    return BoundaryPolicy(
        BoundaryDocument.model_validate(
            {
                "accounts": [
                    {
                        "id": "google-main",
                        "provider": "google",
                        "credential": str(tmp_path / "secrets" / "oauth-client.json"),
                        "oauth_token_file": str(tmp_path / "oauth" / "google-main.json"),
                    }
                ]
            }
        )
    )


def _configure_logging(_: str, __: Path) -> None:
    return None


def _open_browser(_: str) -> bool:
    return True


def test_parser_supports_local_oauth_operator_commands() -> None:
    arguments = cli._parser().parse_args(
        [
            "auth-google",
            "--account-id",
            "google-main",
            "--callback-port",
            "49152",
            "--docker-loopback-proxy",
            "--print-authorization-url",
        ]
    )
    assert arguments.mode == "auth-google"
    assert arguments.account_id == "google-main"
    assert arguments.callback_port == 49152
    assert arguments.docker_loopback_proxy is True
    assert arguments.print_authorization_url is True
    assert not hasattr(arguments, "full_scope_grant")


def test_parser_supports_local_site_onboarding_without_a_transport_surface() -> None:
    arguments = cli._parser().parse_args(
        [
            "onboard-site",
            "--google-account-id",
            "google-main",
            "--bing-account-id",
            "bing-main",
            "--site-url",
            "https://example.com/",
        ]
    )
    assert arguments.mode == "onboard-site"
    assert arguments.google_account_id == "google-main"
    assert arguments.bing_account_id == "bing-main"
    assert arguments.site_url == "https://example.com/"


def test_site_onboarding_requires_explicit_write_enablement(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    settings = Settings(
        boundary_file=tmp_path / "boundaries.json",
        secret_root=tmp_path / "secrets",
        oauth_token_root=tmp_path / "oauth",
        log_file=tmp_path / "rankrat.log",
        read_only=True,
    )
    monkeypatch.setattr(cli, "load_settings", lambda: settings)
    monkeypatch.setattr(cli, "configure_logging", _configure_logging)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "rankrat",
            "onboard-site",
            "--google-account-id",
            "google-main",
            "--bing-account-id",
            "bing-main",
            "--site-url",
            "https://example.com/",
        ],
    )

    assert cli.main() == 2
    assert capsys.readouterr().err == "rankrat startup failed: invalid configuration\n"


def test_oauth_commands_fail_without_a_configured_google_account(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(sys, "argv", ["rankrat", "auth-google"])
    assert cli.main() == 2
    assert capsys.readouterr().err == "rankrat startup failed: invalid configuration\n"


def test_revoke_google_rejects_the_removed_full_scope_flag(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    settings = Settings(
        boundary_file=tmp_path / "boundaries.json",
        secret_root=tmp_path / "secrets",
        oauth_token_root=tmp_path / "oauth",
        log_file=tmp_path / "rankrat.log",
    )
    monkeypatch.setattr(cli, "load_settings", lambda: settings)
    monkeypatch.setattr(cli, "configure_logging", _configure_logging)

    monkeypatch.setattr(
        sys,
        "argv",
        ["rankrat", "revoke-google", "--account-id", "google-main", "--full-scope-grant"],
    )

    with pytest.raises(SystemExit) as error:
        cli.main()
    assert error.value.code == 2
    assert "unrecognized arguments: --full-scope-grant" in capsys.readouterr().err


def test_auth_google_prints_an_authorization_url_only_when_requested(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    settings = Settings(
        boundary_file=tmp_path / "boundaries.json",
        secret_root=tmp_path / "secrets",
        oauth_token_root=tmp_path / "oauth",
        log_file=tmp_path / "rankrat.log",
    )
    monkeypatch.setattr(cli, "load_settings", lambda: settings)
    monkeypatch.setattr(cli, "configure_logging", _configure_logging)

    def boundary_policy_from_file(*_: object) -> BoundaryPolicy:
        return _oauth_policy(tmp_path)

    monkeypatch.setattr(
        cli.BoundaryPolicy,
        "from_file",
        boundary_policy_from_file,
    )
    observed: dict[str, object] = {}

    async def authorize(
        account: object,
        enable_writes: bool,
        browser_opener: object,
        authorization_url_sink: object,
        listener_host: object,
        callback_port: object,
    ) -> None:
        observed["account"] = account
        observed["enable_writes"] = enable_writes
        observed["browser_opener"] = browser_opener
        observed["listener_host"] = listener_host
        observed["callback_port"] = callback_port
        if callable(authorization_url_sink):
            authorization_url_sink("https://accounts.google.com/?state=one-time-state")

    monkeypatch.setattr(cli, "authorize_google_oauth_account", authorize)
    monkeypatch.setattr(cli.webbrowser, "open", _open_browser)
    monkeypatch.setattr(
        sys,
        "argv",
        ["rankrat", "auth-google", "--print-authorization-url"],
    )
    assert cli.main() == 0
    assert observed["enable_writes"] is True
    assert observed["browser_opener"] is None
    assert observed["listener_host"] == OAUTH_LOOPBACK_HOST
    assert observed["callback_port"] == OAUTH_DYNAMIC_CALLBACK_PORT
    assert capsys.readouterr().out == (
        "https://accounts.google.com/?state=one-time-state\nGoogle OAuth authorization stored.\n"
    )


def test_revoke_google_never_registers_a_transport_surface(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    settings = Settings(
        boundary_file=tmp_path / "boundaries.json",
        secret_root=tmp_path / "secrets",
        oauth_token_root=tmp_path / "oauth",
        log_file=tmp_path / "rankrat.log",
    )
    monkeypatch.setattr(cli, "load_settings", lambda: settings)
    monkeypatch.setattr(cli, "configure_logging", _configure_logging)

    def boundary_policy_from_file(*_: object) -> BoundaryPolicy:
        return _oauth_policy(tmp_path)

    monkeypatch.setattr(cli.BoundaryPolicy, "from_file", boundary_policy_from_file)
    revoked: list[object] = []

    async def revoke(account: object, enable_writes: bool) -> None:
        revoked.extend((account, enable_writes))

    monkeypatch.setattr(cli, "revoke_google_oauth_account", revoke)
    monkeypatch.setattr(sys, "argv", ["rankrat", "revoke-google"])
    assert cli.main() == 0
    assert len(revoked) == 2
    assert revoked[1] is True
    assert capsys.readouterr().out == "Google OAuth authorization revoked.\n"


def test_docker_oauth_authorization_requires_a_fixed_callback_port(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    settings = Settings(
        boundary_file=tmp_path / "boundaries.json",
        secret_root=tmp_path / "secrets",
        oauth_token_root=tmp_path / "oauth",
        log_file=tmp_path / "rankrat.log",
    )
    monkeypatch.setattr(cli, "load_settings", lambda: settings)
    monkeypatch.setattr(cli, "configure_logging", _configure_logging)

    def boundary_policy_from_file(
        _: Path,
        __: Path,
        ___: Path | None = None,
    ) -> BoundaryPolicy:
        return _oauth_policy(tmp_path)

    monkeypatch.setattr(cli.BoundaryPolicy, "from_file", boundary_policy_from_file)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "rankrat",
            "auth-google",
            "--account-id",
            "google-main",
            "--docker-loopback-proxy",
        ],
    )
    assert cli.main() == 2


def test_main_runs_the_stdio_transport_and_handles_operator_interrupt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    settings = Settings(
        boundary_file=tmp_path / "boundaries.json",
        secret_root=tmp_path / "secrets",
        oauth_token_root=tmp_path / "oauth",
        log_file=tmp_path / "rankrat.log",
    )
    monkeypatch.setattr(cli, "load_settings", lambda: settings)
    monkeypatch.setattr(cli, "configure_logging", _configure_logging)
    services = object()
    server = object()
    observed: list[object] = []

    def build_services(received: Settings) -> object:
        observed.append(received)
        return services

    def build_mcp_server(received: object) -> object:
        observed.append(received)
        return server

    monkeypatch.setattr(cli, "build_services", build_services)
    monkeypatch.setattr(cli, "build_mcp_server", build_mcp_server)

    async def run_stdio(received: object) -> None:
        observed.append(received)

    monkeypatch.setattr(cli, "run_stdio", run_stdio)
    monkeypatch.setattr(sys, "argv", ["rankrat", "stdio"])
    assert cli.main() == 0
    assert observed == [settings, services, server]

    async def interrupt_stdio(_: object) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "run_stdio", interrupt_stdio)
    assert cli.main() == 0


def test_main_runs_the_local_http_transport(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    settings = Settings(
        boundary_file=tmp_path / "boundaries.json",
        secret_root=tmp_path / "secrets",
        oauth_token_root=tmp_path / "oauth",
        log_file=tmp_path / "rankrat.log",
    )
    monkeypatch.setattr(cli, "load_settings", lambda: settings)
    monkeypatch.setattr(cli, "configure_logging", _configure_logging)
    services = object()
    application = object()

    def build_services(_: Settings) -> object:
        return services

    monkeypatch.setattr(cli, "build_services", build_services)

    def create_application(received_settings: Settings, received_services: object) -> object:
        if received_settings.mode == "http" and received_services is services:
            return application
        pytest.fail("HTTP application received unexpected dependencies")

    monkeypatch.setattr(cli, "create_http_app", create_application)
    observed: dict[str, object] = {}

    def run(application_argument: object, **kwargs: object) -> None:
        observed["application"] = application_argument
        observed.update(kwargs)

    monkeypatch.setattr(cli.uvicorn, "run", run)
    monkeypatch.setattr(sys, "argv", ["rankrat", "http"])
    assert cli.main() == 0
    assert observed == {
        "application": application,
        "host": settings.http_host,
        "port": settings.http_port,
        "access_log": False,
        "log_config": None,
    }


def test_main_returns_a_safe_startup_failure_for_runtime_dependency_errors(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    settings = Settings(
        boundary_file=tmp_path / "boundaries.json",
        secret_root=tmp_path / "secrets",
        oauth_token_root=tmp_path / "oauth",
        log_file=tmp_path / "rankrat.log",
    )
    monkeypatch.setattr(cli, "load_settings", lambda: settings)
    monkeypatch.setattr(cli, "configure_logging", _configure_logging)

    def fail(_: Settings) -> object:
        raise ValueError("untrusted detail")

    monkeypatch.setattr(cli, "build_services", fail)
    monkeypatch.setattr(sys, "argv", ["rankrat", "stdio"])
    assert cli.main() == 2
    assert capsys.readouterr().err == "rankrat startup failed: invalid configuration\n"


def test_auth_google_reports_only_a_safe_provider_failure_category(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    settings = Settings(
        boundary_file=tmp_path / "boundaries.json",
        secret_root=tmp_path / "secrets",
        oauth_token_root=tmp_path / "oauth",
        log_file=tmp_path / "rankrat.log",
    )
    monkeypatch.setattr(cli, "load_settings", lambda: settings)
    monkeypatch.setattr(cli, "configure_logging", _configure_logging)

    def boundary_policy_from_file(
        _: Path,
        __: Path,
        ___: Path | None = None,
    ) -> BoundaryPolicy:
        return _oauth_policy(tmp_path)

    monkeypatch.setattr(cli.BoundaryPolicy, "from_file", boundary_policy_from_file)

    async def authorize(*_: object, **__: object) -> None:
        raise ProviderOperationError(ProviderFailureCode.INVALID_RESPONSE, "untrusted detail")

    monkeypatch.setattr(cli, "authorize_google_oauth_account", authorize)
    monkeypatch.setattr(
        sys,
        "argv",
        ["rankrat", "auth-google", "--account-id", "google-main", "--print-authorization-url"],
    )
    assert cli.main() == 2
    assert capsys.readouterr().err == "rankrat provider startup failed: INVALID_RESPONSE\n"


def test_google_oauth_operator_rejects_a_google_account_without_an_oauth_token_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    settings = Settings(
        boundary_file=tmp_path / "boundaries.json",
        secret_root=tmp_path / "secrets",
        oauth_token_root=tmp_path / "oauth",
        log_file=tmp_path / "rankrat.log",
    )
    missing_token_path = BoundaryPolicy(
        BoundaryDocument.model_validate(
            {
                "accounts": [
                    {
                        "id": "google-main",
                        "provider": "google",
                        "credential": str(tmp_path / "secrets" / "google-oauth-client.json"),
                    }
                ]
            }
        )
    )
    monkeypatch.setattr(cli, "load_settings", lambda: settings)
    monkeypatch.setattr(cli, "configure_logging", _configure_logging)

    def boundary_policy_from_file(
        _: Path,
        __: Path,
        ___: Path | None = None,
    ) -> BoundaryPolicy:
        return missing_token_path

    monkeypatch.setattr(cli.BoundaryPolicy, "from_file", boundary_policy_from_file)
    monkeypatch.setattr(sys, "argv", ["rankrat", "revoke-google", "--account-id", "google-main"])
    assert cli.main() == 2
    assert capsys.readouterr().err == "rankrat startup failed: invalid configuration\n"


def test_setup_reports_missing_credentials_without_calling_a_provider(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    secret_root = tmp_path / "secrets"
    secret_root.mkdir()
    oauth_root = tmp_path / "oauth"
    oauth_root.mkdir()
    boundary_file = tmp_path / "boundaries.json"
    boundary_file.write_text(
        json.dumps(
            {
                "accounts": [
                    {
                        "id": "bing-main",
                        "provider": "bing",
                        "credential": str(secret_root / "bing-api-key"),
                        "sites": ["https://example.com/"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    settings = Settings(
        boundary_file=boundary_file,
        secret_root=secret_root,
        oauth_token_root=oauth_root,
        log_file=tmp_path / "rankrat.log",
    )
    monkeypatch.setattr(cli, "load_settings", lambda: settings)
    monkeypatch.setattr(cli, "configure_logging", _configure_logging)
    monkeypatch.setattr(sys, "argv", ["rankrat", "setup"])

    assert cli.main() == 2
    assert "SETUP BLOCKED: place credential file(s) at:" in capsys.readouterr().out


def test_setup_runs_live_readiness_after_local_preflight(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    secret_root = tmp_path / "secrets"
    secret_root.mkdir()
    (secret_root / "bing-api-key").write_text("not-a-real-key", encoding="utf-8")
    oauth_root = tmp_path / "oauth"
    oauth_root.mkdir()
    boundary_file = tmp_path / "boundaries.json"
    boundary_file.write_text(
        json.dumps(
            {
                "accounts": [
                    {
                        "id": "bing-main",
                        "provider": "bing",
                        "credential": str(secret_root / "bing-api-key"),
                        "sites": ["https://example.com/"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    settings = Settings(
        boundary_file=boundary_file,
        secret_root=secret_root,
        oauth_token_root=oauth_root,
        log_file=tmp_path / "rankrat.log",
    )

    async def readiness(request: ProviderReadinessRequest) -> ProviderReadiness:
        assert request.account_id == "bing-main"
        return ProviderReadiness(
            AccountId("bing-main"), Provider.BING, True, "Bing access is available"
        )

    monkeypatch.setattr(cli, "load_settings", lambda: settings)
    monkeypatch.setattr(cli, "configure_logging", _configure_logging)

    def build_services(_: Settings) -> SimpleNamespace:
        return SimpleNamespace(provider_readiness=SimpleNamespace(readiness=readiness))

    monkeypatch.setattr(cli, "build_services", build_services)
    monkeypatch.setattr(sys, "argv", ["rankrat", "setup"])

    assert cli.main() == 0
    assert "READY: bing-main" in capsys.readouterr().out


def test_setup_explains_ga4_property_and_tag_prerequisites(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    secret_root = tmp_path / "secrets"
    secret_root.mkdir()
    credential = secret_root / "oauth-client.json"
    credential.write_text("not-a-real-client", encoding="utf-8")
    oauth_root = tmp_path / "oauth"
    oauth_root.mkdir()
    boundary_file = tmp_path / "boundaries.json"
    boundary_file.write_text(
        json.dumps(
            {
                "accounts": [
                    {
                        "id": "google-main",
                        "provider": "google",
                        "credential": str(credential),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    settings = Settings(
        boundary_file=boundary_file,
        secret_root=secret_root,
        oauth_token_root=oauth_root,
        log_file=tmp_path / "rankrat.log",
    )

    async def readiness(request: ProviderReadinessRequest) -> ProviderReadiness:
        assert request.account_id == "google-main"
        return ProviderReadiness(
            AccountId("google-main"),
            Provider.GOOGLE,
            True,
            "Google access is available",
        )

    monkeypatch.setattr(cli, "load_settings", lambda: settings)
    monkeypatch.setattr(cli, "configure_logging", _configure_logging)

    def build_services(_: Settings) -> SimpleNamespace:
        return SimpleNamespace(provider_readiness=SimpleNamespace(readiness=readiness))

    monkeypatch.setattr(
        cli,
        "build_services",
        build_services,
    )
    monkeypatch.setattr(sys, "argv", ["rankrat", "setup"])

    assert cli.main() == 0
    output = capsys.readouterr().out
    assert "SETUP ACTION: google-main has no configured GA4 property." in output
    assert "G- Measurement ID" in output
