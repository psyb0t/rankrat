"""Rankrat process entrypoint for stdio MCP and local HTTP serving."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import webbrowser
from typing import cast

import uvicorn

from rankrat import __version__
from rankrat.config import RuntimeMode, Settings, load_settings
from rankrat.constants import (
    OAUTH_CONTAINER_LISTENER_HOST,
    OAUTH_DYNAMIC_CALLBACK_PORT,
    OAUTH_LOOPBACK_HOST,
)
from rankrat.errors import ConfigurationError, RankratError
from rankrat.logging import configure_logging, log_event
from rankrat.models.boundaries import Provider
from rankrat.operator.site_onboarding import (
    SiteOnboardingOperator,
    SiteOnboardingPartialError,
    SiteOnboardingRequest,
)
from rankrat.policy.boundaries import BoundaryPolicy
from rankrat.providers.base import ProviderFailureCode, ProviderOperationError
from rankrat.providers.bing import BingWebmasterClient
from rankrat.providers.google_analytics_admin import (
    GOOGLE_ANALYTICS_EDIT_SCOPE,
    GoogleAnalyticsAdminClient,
)
from rankrat.providers.google_oauth import (
    authorize_google_oauth_account,
    revoke_google_oauth_account,
)
from rankrat.providers.google_search_console import (
    SEARCH_CONSOLE_WRITE_SCOPE,
    GoogleConfiguredTokenProvider,
    GoogleSearchConsoleClient,
)
from rankrat.services.provider_readiness import ProviderReadinessRequest
from rankrat.transports.auth import load_bearer_secret
from rankrat.transports.http import create_http_app
from rankrat.transports.mcp import build_mcp_server
from rankrat.transports.runtime import build_services
from rankrat.transports.stdio import run_stdio

_LOGGER = logging.getLogger(__name__)
_SERVE_MODES = ("stdio", "http")
_OAUTH_MODES = ("auth-google", "revoke-google")
_OPERATOR_MODES = ("onboard-site", "setup")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rankrat")
    parser.add_argument(
        "mode",
        choices=(*_SERVE_MODES, *_OAUTH_MODES, *_OPERATOR_MODES),
        nargs="?",
        default="stdio",
    )
    parser.add_argument("--account-id")
    parser.add_argument("--callback-port", type=int)
    parser.add_argument("--docker-loopback-proxy", action="store_true")
    parser.add_argument("--print-authorization-url", action="store_true")
    parser.add_argument("--google-account-id")
    parser.add_argument("--bing-account-id")
    parser.add_argument("--site-url")
    parser.add_argument("--display-name")
    parser.add_argument("--time-zone", default="Etc/UTC")
    parser.add_argument("--currency-code", default="USD")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def main() -> int:
    """Load immutable configuration, then start exactly one selected transport."""
    arguments = _parser().parse_args()
    try:
        settings = load_settings()
        configure_logging(settings.log_level, settings.log_file)
        if arguments.mode in _OAUTH_MODES:
            return _run_google_oauth_operator(arguments, settings)
        if arguments.mode in _OPERATOR_MODES:
            if arguments.mode == "setup":
                return _run_setup_operator(settings)
            return _run_site_onboarding_operator(arguments, settings)
        settings = settings.model_copy(update={"mode": cast(RuntimeMode, arguments.mode)})
        services = build_services(settings)
    except ProviderOperationError as error:
        sys.stderr.write(f"rankrat provider startup failed: {error.code.value}\n")
        return 2
    except SiteOnboardingPartialError as error:
        stages = ",".join(error.completed_stages)
        sys.stderr.write(f"rankrat site onboarding partially completed: {stages}\n")
        return 2
    except (RankratError, ValueError, webbrowser.Error):
        sys.stderr.write("rankrat startup failed: invalid configuration\n")
        return 2
    log_event(_LOGGER, logging.INFO, "rankrat starting", mode=settings.mode)
    if settings.mode == "stdio":
        try:
            asyncio.run(run_stdio(build_mcp_server(services)))
        except KeyboardInterrupt:
            log_event(_LOGGER, logging.INFO, "rankrat stopped", mode=settings.mode)
        return 0
    uvicorn.run(
        create_http_app(settings, services),
        host=settings.http_host,
        port=settings.http_port,
        access_log=False,
        log_config=None,
    )
    return 0


def _run_google_oauth_operator(arguments: argparse.Namespace, settings: Settings) -> int:
    account_id = arguments.account_id
    if not isinstance(account_id, str) or not account_id:
        raise ConfigurationError("Google OAuth commands require --account-id")
    policy = BoundaryPolicy.from_file(
        settings.boundary_file,
        settings.secret_root,
        settings.oauth_token_root,
    )
    account = policy.resolve_account(account_id, Provider.GOOGLE)
    if account.oauth_token_file is None:
        raise ConfigurationError("configured Google account has no OAuth token path")
    if arguments.mode == "auth-google":
        if arguments.docker_loopback_proxy and arguments.callback_port is None:
            raise ConfigurationError("Docker OAuth authorization requires --callback-port")
        authorization_url_sink = (
            _stdout_authorization_url if arguments.print_authorization_url else None
        )
        asyncio.run(
            authorize_google_oauth_account(
                account,
                settings.enable_writes,
                None if arguments.print_authorization_url else webbrowser.open,
                authorization_url_sink,
                listener_host=(
                    OAUTH_CONTAINER_LISTENER_HOST
                    if arguments.docker_loopback_proxy
                    else OAUTH_LOOPBACK_HOST
                ),
                callback_port=arguments.callback_port or OAUTH_DYNAMIC_CALLBACK_PORT,
            )
        )
        log_event(_LOGGER, logging.INFO, "Google OAuth authorization stored", account_id=account.id)
        sys.stdout.write("Google OAuth authorization stored.\n")
        return 0
    asyncio.run(revoke_google_oauth_account(account, settings.enable_writes))
    log_event(_LOGGER, logging.INFO, "Google OAuth authorization revoked", account_id=account.id)
    sys.stdout.write("Google OAuth authorization revoked.\n")
    return 0


def _stdout_authorization_url(authorization_url: str) -> None:
    """Print an operator-requested, one-time authorization URL without logging it."""
    sys.stdout.write(f"{authorization_url}\n")


def _run_site_onboarding_operator(arguments: argparse.Namespace, settings: Settings) -> int:
    """Provision one site from the local terminal; this mode is never HTTP or MCP exposed."""

    if not settings.enable_writes:
        raise ConfigurationError("site onboarding requires RANKRAT_ENABLE_WRITES=true")
    load_bearer_secret(settings.admin_bearer_secret_file)
    google_account_id = _required_operator_argument(
        arguments.google_account_id, "--google-account-id"
    )
    bing_account_id = _required_operator_argument(arguments.bing_account_id, "--bing-account-id")
    site_url = _required_operator_argument(arguments.site_url, "--site-url")
    policy = BoundaryPolicy.from_file(
        settings.boundary_file,
        settings.secret_root,
        settings.oauth_token_root,
    )
    operator = SiteOnboardingOperator(
        settings.boundary_file,
        policy,
        GoogleAnalyticsAdminClient(
            policy,
            GoogleConfiguredTokenProvider(policy, (GOOGLE_ANALYTICS_EDIT_SCOPE,)),
        ),
        GoogleSearchConsoleClient(
            policy,
            GoogleConfiguredTokenProvider(policy, (SEARCH_CONSOLE_WRITE_SCOPE,)),
        ),
        BingWebmasterClient(policy),
    )
    receipt = asyncio.run(
        operator.onboard(
            SiteOnboardingRequest(
                google_account_id=google_account_id,
                bing_account_id=bing_account_id,
                site_url=site_url,
                display_name=arguments.display_name or None,
                time_zone=arguments.time_zone,
                currency_code=arguments.currency_code,
            )
        )
    )
    payload = {
        "site_url": receipt.site_url,
        "ga4_property_id": receipt.ga4_property_id,
        "ga4_measurement_id": receipt.ga4_measurement_id,
        "google_search_console_added": receipt.google_search_console_added,
        "bing_added": receipt.bing_added,
        "boundary_updated": receipt.boundary_updated,
    }
    sys.stdout.write(f"{json.dumps(payload, separators=(',', ':'))}\n")
    return 0


def _run_setup_operator(settings: Settings) -> int:
    """Check configured local files and live provider access without mutations."""
    policy = BoundaryPolicy.from_file(
        settings.boundary_file,
        settings.secret_root,
        settings.oauth_token_root,
    )
    missing_paths = tuple(
        path
        for account in policy.accounts()
        for path in (account.credential, account.pagespeed_api_key_file)
        if path is not None and not path.is_file()
    )
    if missing_paths:
        rendered = ", ".join(str(path) for path in missing_paths)
        sys.stdout.write(f"SETUP BLOCKED: place credential file(s) at: {rendered}\n")
        return 2
    missing_tokens = tuple(
        account.oauth_token_file
        for account in policy.accounts()
        if account.provider is Provider.GOOGLE
        and account.oauth_token_file is not None
        and not account.oauth_token_file.is_file()
    )
    if missing_tokens:
        account_ids = ", ".join(
            account.id
            for account in policy.accounts()
            if account.oauth_token_file in missing_tokens
        )
        sys.stdout.write(
            "SETUP BLOCKED: authorize Google with "
            f"make auth-google OAUTH_ACCOUNT_ID=<one of: {account_ids}>\n"
        )
        return 2
    services = build_services(settings)

    async def check() -> None:
        for account in policy.accounts():
            readiness = await services.provider_readiness.readiness(
                ProviderReadinessRequest(account.id)
            )
            if not readiness.available:
                raise ProviderOperationError(ProviderFailureCode.FORBIDDEN, readiness.detail)
            sys.stdout.write(f"READY: {account.id} — {readiness.detail}\n")

    asyncio.run(check())
    sys.stdout.write(
        "SETUP READY: Google Search Console and Bing passed live checks. "
        "Run make test-live for GA4, PageSpeed, IndexNow, and extended checks.\n"
    )
    return 0


def _required_operator_argument(value: object, flag: str) -> str:
    if not isinstance(value, str) or not value:
        raise ConfigurationError(f"site onboarding requires {flag}")
    return value
