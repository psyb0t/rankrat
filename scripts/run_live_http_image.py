"""Verify configured providers through a running Rankrat HTTP production image."""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final, cast

import httpx

from rankrat.config import Settings
from rankrat.models.boundaries import ConfiguredAccount, Provider
from rankrat.models.common import JsonValue
from rankrat.policy.boundaries import BoundaryPolicy
from rankrat.providers.base import ProviderFailureCode
from rankrat.transports.auth import load_bearer_secret

_DEFAULT_TIMEOUT_SECONDS: Final = 30.0
_HTTP_OK_STATUS: Final = 200
_HTTP_AUTHORIZATION_HEADER: Final = "Authorization"
_HTTP_BEARER_PREFIX: Final = "Bearer "
_HTTP_ACCEPT_HEADER: Final = "Accept"
_JSON_CONTENT_TYPE: Final = "application/json"
_MCP_ACCEPT: Final = "application/json, text/event-stream"
_MCP_INITIALIZE_REQUEST: Final = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-03-26",
        "capabilities": {},
        "clientInfo": {"name": "rankrat-live-http-verifier", "version": "0"},
    },
}
_HEALTH_PATH: Final = "/healthz"
_READY_PATH: Final = "/ready"
_MCP_PATH: Final = "/mcp/"
_ACCOUNTS_PATH: Final = "/v1/accounts"
_PROVIDER_READINESS_PATH: Final = "/v1/provider-readiness"
_SEARCH_ANALYTICS_SUMMARY_PATH: Final = "/v1/google/search-analytics-summary"
_GA4_ACCOUNT_INVENTORY_PATH: Final = "/v1/google-analytics/account-inventory"
_GA4_REPORT_PATH: Final = "/v1/google-analytics/reports"
_PAGESPEED_ANALYSIS_PATH: Final = "/v1/pagespeed/analyses"
_BING_TRAFFIC_TREND_PATH: Final = "/v1/bing/traffic-trend"
_CLOUDFLARE_ANALYTICS_PATH: Final = "/v1/cloudflare/analytics-reports"
_PAGESPEED_BOUNDARY_ERROR: Final = (
    "PageSpeed API key is configured but no explicit HTTPS PageSpeed site is available"
)
_MAX_REPORT_ROWS: Final = 1
_REPORT_END_DAY_OFFSET: Final = 2
_REPORT_DURATION_DAYS: Final = 7
_CLOUDFLARE_REPORT_DURATION_HOURS: Final = 24
_CLOUDFLARE_REPORT_LIMIT: Final = 24
_HEALTH_RETRY_COUNT: Final = 10
_HEALTH_RETRY_DELAY_SECONDS: Final = 1
_SAFE_PROVIDER_FAILURE_CODES: Final = frozenset(
    provider_failure_code.value for provider_failure_code in ProviderFailureCode
)


class LiveHttpVerificationError(RuntimeError):
    """The shipped HTTP/MCP transport could not prove a configured read path."""


@dataclass(frozen=True, slots=True)
class LiveHttpVerifier:
    """Exercise fixed, non-mutating HTTP/MCP routes for immutable configured accounts."""

    policy: BoundaryPolicy
    base_url: str
    bearer_secret: str
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS

    async def verify(
        self,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> tuple[str, ...]:
        """Return safe operation labels after every configured read path succeeds."""
        headers = {
            _HTTP_AUTHORIZATION_HEADER: f"{_HTTP_BEARER_PREFIX}{self.bearer_secret}",
            _HTTP_ACCEPT_HEADER: _JSON_CONTENT_TYPE,
        }
        completed: list[str] = []
        async with httpx.AsyncClient(
            base_url=self.base_url,
            headers=headers,
            timeout=httpx.Timeout(self.timeout_seconds),
            transport=transport,
        ) as client:
            await self._wait_for_health(client)
            completed.append("health")
            await self._request(client, "GET", _READY_PATH)
            completed.append("ready")
            mcp_body = await self._request(
                client,
                "POST",
                _MCP_PATH,
                json_body=_MCP_INITIALIZE_REQUEST,
                extra_headers={_HTTP_ACCEPT_HEADER: _MCP_ACCEPT},
            )
            if not isinstance(mcp_body, dict):
                raise LiveHttpVerificationError(
                    "Streamable HTTP MCP initialize returned an unexpected JSON shape"
                )
            mcp_result = mcp_body.get("result")
            if not isinstance(mcp_result, dict):
                raise LiveHttpVerificationError(
                    "Streamable HTTP MCP initialize returned no protocol"
                )
            if not isinstance(mcp_result.get("protocolVersion"), str):
                raise LiveHttpVerificationError(
                    "Streamable HTTP MCP initialize returned no protocol"
                )
            completed.append("mcp")
            await self._request(client, "GET", _ACCOUNTS_PATH)
            completed.append("accounts")
            for account in self.policy.accounts():
                await self._verify_account(client, account, completed)
        return tuple(completed)

    async def _wait_for_health(self, client: httpx.AsyncClient) -> None:
        last_error: LiveHttpVerificationError | None = None
        for attempt in range(_HEALTH_RETRY_COUNT):
            try:
                await self._request(client, "GET", _HEALTH_PATH, authenticated=False)
                return
            except LiveHttpVerificationError as error:
                last_error = error
                if attempt + 1 < _HEALTH_RETRY_COUNT:
                    await asyncio.sleep(_HEALTH_RETRY_DELAY_SECONDS)
        raise LiveHttpVerificationError(
            "Rankrat production HTTP endpoint did not become ready"
        ) from last_error

    async def _verify_account(
        self,
        client: httpx.AsyncClient,
        account: ConfiguredAccount,
        completed: list[str],
    ) -> None:
        await self._request(
            client,
            "GET",
            _PROVIDER_READINESS_PATH,
            params={"account_id": account.id},
        )
        completed.append(f"{account.provider}-readiness")
        if account.provider == Provider.GOOGLE:
            await self._verify_google_account(client, account, completed)
            return
        if account.provider == Provider.BING:
            await self._verify_bing_account(client, account, completed)
            return
        if account.provider == Provider.CLOUDFLARE:
            await self._verify_cloudflare_account(client, account, completed)

    async def _verify_google_account(
        self,
        client: httpx.AsyncClient,
        account: ConfiguredAccount,
        completed: list[str],
    ) -> None:
        start_date, end_date = _report_period()
        for site_url in account.search_console_sites:
            await self._request(
                client,
                "POST",
                _SEARCH_ANALYTICS_SUMMARY_PATH,
                json_body={
                    "account_id": account.id,
                    "site_url": site_url,
                    "start_date": start_date,
                    "end_date": end_date,
                },
            )
            completed.append("google-search-analytics")
        await self._request(
            client,
            "POST",
            _GA4_ACCOUNT_INVENTORY_PATH,
            json_body={"account_id": account.id},
        )
        completed.append("google-analytics-inventory")
        for property_id in account.ga4_properties:
            await self._request(
                client,
                "POST",
                _GA4_REPORT_PATH,
                json_body={
                    "account_id": account.id,
                    "property_id": property_id,
                    "date_ranges": [{"start_date": start_date, "end_date": end_date}],
                    "dimensions": ["date"],
                    "metrics": ["activeUsers"],
                    "limit": _MAX_REPORT_ROWS,
                },
            )
            completed.append("google-analytics-report")
        if account.pagespeed_api_key_file is None:
            return
        site_url = next(
            (
                configured_site
                for configured_site in account.pagespeed_sites
                if configured_site.startswith("https://")
            ),
            None,
        )
        if site_url is None:
            raise LiveHttpVerificationError(_PAGESPEED_BOUNDARY_ERROR)
        await self._request(
            client,
            "POST",
            _PAGESPEED_ANALYSIS_PATH,
            json_body={
                "account_id": account.id,
                "site_url": site_url,
                "page_url": site_url,
                "strategy": "MOBILE",
                "categories": ["PERFORMANCE"],
            },
        )
        completed.append("pagespeed")

    async def _verify_bing_account(
        self,
        client: httpx.AsyncClient,
        account: ConfiguredAccount,
        completed: list[str],
    ) -> None:
        start_date, end_date = _report_period()
        for site_url in account.bing_sites:
            await self._request(
                client,
                "POST",
                _BING_TRAFFIC_TREND_PATH,
                json_body={
                    "account_id": account.id,
                    "site_url": site_url,
                    "start_date": start_date,
                    "end_date": end_date,
                },
            )
            completed.append("bing-traffic")

    async def _verify_cloudflare_account(
        self,
        client: httpx.AsyncClient,
        account: ConfiguredAccount,
        completed: list[str],
    ) -> None:
        start, end = _cloudflare_report_period()
        for zone in account.dns_zones:
            await self._request(
                client,
                "POST",
                _CLOUDFLARE_ANALYTICS_PATH,
                json_body={
                    "account_id": account.id,
                    "zone_id": zone.provider_zone_id,
                    "start": start,
                    "end": end,
                    "limit": _CLOUDFLARE_REPORT_LIMIT,
                },
            )
            completed.append("cloudflare-analytics")

    async def _request(
        self,
        client: httpx.AsyncClient,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        json_body: object | None = None,
        extra_headers: dict[str, str] | None = None,
        authenticated: bool = True,
    ) -> JsonValue:
        headers = extra_headers or {}
        if not authenticated:
            headers = {_HTTP_AUTHORIZATION_HEADER: ""}
        try:
            response = await client.request(
                method,
                path,
                params=params,
                json=json_body,
                headers=headers,
            )
        except httpx.HTTPError as error:
            raise LiveHttpVerificationError(f"{method} {path} could not reach Rankrat") from error
        if response.status_code != _HTTP_OK_STATUS:
            error_code = _safe_provider_failure_code(response)
            error_suffix = f" ({error_code})" if error_code is not None else ""
            raise LiveHttpVerificationError(
                f"{method} {path} returned HTTP {response.status_code}{error_suffix}"
            )
        try:
            body = response.json()
        except ValueError as error:
            raise LiveHttpVerificationError(f"{method} {path} did not return JSON") from error
        return body


def _safe_provider_failure_code(response: httpx.Response) -> str | None:
    """Extract only Rankrat's finite provider code; never relay a response body."""
    try:
        body = cast(object, response.json())
    except ValueError:
        return None
    if not isinstance(body, dict):
        return None
    code = cast(dict[object, object], body).get("code")
    if not isinstance(code, str) or code not in _SAFE_PROVIDER_FAILURE_CODES:
        return None
    return code


def _report_period() -> tuple[str, str]:
    end_date = datetime.now(UTC).date() - timedelta(days=_REPORT_END_DAY_OFFSET)
    start_date = end_date - timedelta(days=_REPORT_DURATION_DAYS - 1)
    return start_date.isoformat(), end_date.isoformat()


def _cloudflare_report_period() -> tuple[str, str]:
    end = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    start = end - timedelta(hours=_CLOUDFLARE_REPORT_DURATION_HOURS)
    return start.isoformat(), end.isoformat()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="run_live_http_image")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--http-bearer-secret-file", type=Path, required=True)
    return parser


def main() -> int:
    """Run the production-image HTTP/MCP verifier using mounted local-only state."""
    arguments = _parser().parse_args()
    settings = Settings()
    policy = BoundaryPolicy.from_file(
        settings.boundary_file,
        settings.secret_root,
        settings.oauth_token_root,
    )
    bearer_secret = load_bearer_secret(arguments.http_bearer_secret_file)
    if bearer_secret is None:
        raise LiveHttpVerificationError("an HTTP bearer secret is required")
    completed = asyncio.run(LiveHttpVerifier(policy, arguments.base_url, bearer_secret).verify())
    print(f"PASS: production HTTP/MCP live verification completed ({len(completed)} checks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
