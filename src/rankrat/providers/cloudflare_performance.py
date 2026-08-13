"""Bounded Cloudflare analytics, exact purge, and named cache-rule operations."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import IntEnum, StrEnum
from math import isfinite
from pathlib import Path
from typing import cast
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from rankrat.constants import (
    MAX_CLOUDFLARE_ANALYTICS_GROUPS,
    MAX_CLOUDFLARE_PURGE_URLS,
    MAX_CLOUDFLARE_TOKEN_BYTES,
    MAX_EDGE_REDIRECT_SOURCE_PATH_CHARS,
    MAX_EDGE_REDIRECTS,
)
from rankrat.errors import BoundaryDeniedError, InputLimitError
from rankrat.models.boundaries import (
    Provider,
    ResourceKind,
    configured_site_contains_url,
    normalize_indexnow_host,
    normalize_public_https_url,
)
from rankrat.policy.boundaries import BoundaryPolicy
from rankrat.providers.base import (
    ProviderFailureCode,
    ProviderOperationError,
    ProviderReadRequest,
    read_limited_response,
)

_API_ROOT = "https://api.cloudflare.com/client/v4"
_GRAPHQL_URL = f"{_API_ROOT}/graphql"
_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{16,512}$")
_ZONE_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
_RULESET_PHASE = "http_request_cache_settings"
_REDIRECT_RULESET_PHASE = "http_request_dynamic_redirect"
_REDIRECT_MARKER = "Managed by Rankrat [edge-redirect]"
_REDIRECT_EXPRESSION_PREFIX = "http.request.uri.path eq "
_REDIRECT_STATUS_CODES = frozenset((301, 302, 307, 308))
_WRITABLE_RULE_FIELDS = frozenset(
    {
        "action",
        "action_parameters",
        "description",
        "enabled",
        "expression",
        "logging",
        "ratelimit",
        "ref",
    }
)
_ANALYTICS_QUERY = """
query RankratZoneAnalytics(
  $zoneTag: string,
  $filter: ZoneHttpRequestsAdaptiveGroupsFilter_InputObject!,
  $limit: Int!
) {
  viewer {
    zones(filter: {zoneTag: $zoneTag}) {
      traffic: httpRequestsAdaptiveGroups(
        limit: $limit,
        filter: $filter,
        orderBy: [datetimeHour_ASC]
      ) {
        count
        sum { edgeResponseBytes visits }
        avg { sampleInterval }
        dimensions {
          datetimeHour
          cacheStatus
          edgeResponseStatus
          trustedClientCategory: verifiedBotCategory
        }
      }
    }
  }
}
"""

HttpTransportFactory = Callable[[], httpx.AsyncBaseTransport | None]


class CloudflareCacheTemplate(StrEnum):
    CACHE_STATIC_ASSETS = "cache_static_assets"
    BYPASS_HTML = "bypass_html"


class CloudflareRedirectStatus(IntEnum):
    """Documented Cloudflare redirect status codes Rankrat can create."""

    MOVED_PERMANENTLY = 301
    FOUND = 302
    TEMPORARY_REDIRECT = 307
    PERMANENT_REDIRECT = 308


@dataclass(frozen=True, slots=True)
class CloudflareAnalyticsPoint:
    hour: str
    requests: int
    edge_response_bytes: int
    visits: int
    sample_interval: float
    cache_status: str | None
    edge_response_status: int | None
    trusted_client_category: str | None


@dataclass(frozen=True, slots=True)
class CloudflareAnalyticsReport:
    zone_id: str
    points: tuple[CloudflareAnalyticsPoint, ...]
    sampled: bool


@dataclass(frozen=True, slots=True)
class CloudflarePurgeReceipt:
    zone_id: str
    purged_urls: tuple[str, ...]
    provider_request_id: str


@dataclass(frozen=True, slots=True)
class CloudflareCacheRuleReceipt:
    zone_id: str
    template: CloudflareCacheTemplate
    changed: bool
    ruleset_id: str
    rule_id: str | None
    previous_managed_rule: dict[str, object] | None


@dataclass(frozen=True, slots=True)
class CloudflareEdgeRedirect:
    """One Rankrat-managed Cloudflare dynamic redirect rule."""

    zone_id: str
    rule_id: str
    source_path: str
    target_url: str
    status_code: CloudflareRedirectStatus
    preserve_query_string: bool


@dataclass(frozen=True, slots=True)
class CloudflareEdgeRedirectReceipt:
    """One managed redirect upsert result without unrelated ruleset details."""

    redirect: CloudflareEdgeRedirect
    created: bool
    changed: bool


class _AnalyticsDimensions(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)

    datetimeHour: str
    cacheStatus: str | None = None
    edgeResponseStatus: int | None = None
    trustedClientCategory: str | None = None


class _AnalyticsSum(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)

    edgeResponseBytes: int = Field(default=0, ge=0)
    visits: int = Field(default=0, ge=0)


class _AnalyticsAverage(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)

    sampleInterval: float = Field(default=1, gt=0)

    @field_validator("sampleInterval")
    @classmethod
    def validate_finite(cls, value: float) -> float:
        if not isfinite(value):
            raise ValueError("Cloudflare sample interval must be finite")
        return value


class _AnalyticsGroup(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)

    count: int = Field(ge=0)
    sum: _AnalyticsSum
    avg: _AnalyticsAverage
    dimensions: _AnalyticsDimensions


class _AnalyticsZone(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)

    traffic: list[_AnalyticsGroup] = Field(max_length=MAX_CLOUDFLARE_ANALYTICS_GROUPS)


class _AnalyticsViewer(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)

    zones: list[_AnalyticsZone] = Field(max_length=1)


class _AnalyticsData(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)

    viewer: _AnalyticsViewer


class _AnalyticsResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)

    data: _AnalyticsData | None = None
    errors: list[object] | None = None


class _ApiResult(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)

    id: str = Field(min_length=1, max_length=64)


class _ApiResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)

    success: bool
    result: _ApiResult


class _RulesetRule(BaseModel):
    model_config = ConfigDict(extra="allow", frozen=True)

    id: str | None = None
    version: str | None = None
    last_updated: str | None = None
    ref: str | None = None
    action: str
    expression: str
    description: str = ""
    enabled: bool = True
    action_parameters: dict[str, object] = Field(default_factory=dict)


class _Ruleset(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    id: str
    name: str
    description: str = ""
    kind: str
    phase: str
    rules: list[_RulesetRule] = Field(
        default_factory=list[_RulesetRule],
        max_length=MAX_EDGE_REDIRECTS,
    )


class _RulesetResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    success: bool
    result: _Ruleset


class CloudflarePerformanceClient:
    provider = Provider.CLOUDFLARE

    def __init__(
        self,
        policy: BoundaryPolicy,
        transport_factory: HttpTransportFactory = lambda: None,
    ) -> None:
        self._policy = policy
        self._transport_factory = transport_factory
        self._cache_template_locks: dict[str, asyncio.Lock] = {}
        self._edge_redirect_locks: dict[str, asyncio.Lock] = {}

    async def analytics(
        self,
        request: ProviderReadRequest,
        zone_id: str,
        start: datetime,
        end: datetime,
        limit: int,
    ) -> CloudflareAnalyticsReport:
        credential = self._credential(request, zone_id)
        body = await self._request_json(
            request,
            credential,
            "POST",
            _GRAPHQL_URL,
            json_body={
                "query": _ANALYTICS_QUERY,
                "variables": {
                    "zoneTag": zone_id,
                    "filter": {
                        "datetime_geq": start.isoformat(),
                        "datetime_lt": end.isoformat(),
                        "requestSource": "eyeball",
                    },
                    "limit": limit,
                },
            },
        )
        try:
            response = _AnalyticsResponse.model_validate(body)
            if response.errors or response.data is None or len(response.data.viewer.zones) != 1:
                raise ValueError("Cloudflare GraphQL response contains errors")
            groups = response.data.viewer.zones[0].traffic
        except (ValidationError, ValueError) as error:
            raise ProviderOperationError(
                ProviderFailureCode.UNAVAILABLE,
                "Cloudflare analytics dataset is unavailable or invalid",
            ) from error
        points = tuple(
            CloudflareAnalyticsPoint(
                group.dimensions.datetimeHour,
                group.count,
                group.sum.edgeResponseBytes,
                group.sum.visits,
                group.avg.sampleInterval,
                group.dimensions.cacheStatus,
                group.dimensions.edgeResponseStatus,
                group.dimensions.trustedClientCategory,
            )
            for group in groups
        )
        return CloudflareAnalyticsReport(
            zone_id,
            points,
            any(point.sample_interval > 1 for point in points),
        )

    async def purge_urls(
        self,
        request: ProviderReadRequest,
        zone_id: str,
        site_url: str,
        urls: tuple[str, ...],
    ) -> CloudflarePurgeReceipt:
        if not urls or len(urls) > MAX_CLOUDFLARE_PURGE_URLS:
            raise InputLimitError("Cloudflare purge URL count is outside the allowed range")
        normalized = tuple(normalize_public_https_url(url, "purge_url") for url in urls)
        if len(set(normalized)) != len(normalized):
            raise InputLimitError("Cloudflare purge URLs must not repeat")
        if any(not configured_site_contains_url(site_url, url) for url in normalized):
            raise BoundaryDeniedError("Cloudflare purge URL is outside the configured site")
        site_host = urlsplit(normalize_public_https_url(site_url, "site_url")).hostname
        if site_host is None:
            raise BoundaryDeniedError("Cloudflare purge site is invalid")
        configured_zone = self._policy.resolve_dns_zone(
            str(request.account_id),
            normalize_indexnow_host(site_host),
        )
        if configured_zone.provider_zone_id != zone_id:
            raise BoundaryDeniedError("Cloudflare purge site is outside the configured zone")
        credential = self._credential(request, zone_id)
        payload = await self._request_json(
            request,
            credential,
            "POST",
            f"{_API_ROOT}/zones/{zone_id}/purge_cache",
            json_body={"files": list(normalized)},
        )
        try:
            response = _ApiResponse.model_validate(payload)
            if not response.success:
                raise ValueError("Cloudflare purge was unsuccessful")
        except (ValidationError, ValueError) as error:
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "Cloudflare returned an invalid purge response",
            ) from error
        return CloudflarePurgeReceipt(zone_id, normalized, response.result.id)

    async def apply_cache_template(
        self,
        request: ProviderReadRequest,
        zone_id: str,
        template: CloudflareCacheTemplate,
    ) -> CloudflareCacheRuleReceipt:
        credential = self._credential(request, zone_id)
        lock = self._cache_template_locks.setdefault(zone_id, asyncio.Lock())
        async with lock:
            return await self._apply_cache_template_locked(
                request,
                credential,
                zone_id,
                template,
            )

    async def _apply_cache_template_locked(
        self,
        request: ProviderReadRequest,
        credential: Path,
        zone_id: str,
        template: CloudflareCacheTemplate,
    ) -> CloudflareCacheRuleReceipt:
        ruleset_payload = await self._request_json(
            request,
            credential,
            "GET",
            f"{_API_ROOT}/zones/{zone_id}/rulesets/phases/{_RULESET_PHASE}/entrypoint",
            allow_not_found=True,
        )
        if ruleset_payload is None:
            return await self._create_cache_ruleset(
                request,
                credential,
                zone_id,
                template,
            )
        try:
            response = _RulesetResponse.model_validate(ruleset_payload)
            if not response.success or response.result.phase != _RULESET_PHASE:
                raise ValueError("Cloudflare ruleset was unsuccessful")
        except (ValidationError, ValueError) as error:
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "Cloudflare returned an invalid cache ruleset",
            ) from error
        expected = _template_rule(template)
        marker = _template_marker(template)
        matches = tuple(rule for rule in response.result.rules if rule.description == marker)
        if len(matches) > 1:
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "Cloudflare cache ruleset contains ambiguous Rankrat-managed rules",
            )
        matched = matches[0] if matches else None
        previous = (
            _strip_read_only_rule_fields(matched.model_dump()) if matched is not None else None
        )
        if previous is not None and _same_managed_rule(previous, expected):
            return CloudflareCacheRuleReceipt(
                zone_id,
                template,
                False,
                response.result.id,
                matched.id if matched is not None else None,
                previous,
            )
        if matched is not None and matched.id is None:
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "Cloudflare managed cache rule has no stable identifier",
            )
        method = "POST" if matched is None else "PATCH"
        rule_path = "rules" if matched is None else f"rules/{matched.id}"
        updated_payload = await self._request_json(
            request,
            credential,
            method,
            f"{_API_ROOT}/zones/{zone_id}/rulesets/{response.result.id}/{rule_path}",
            json_body=expected,
        )
        try:
            updated = _RulesetResponse.model_validate(updated_payload)
            if not updated.success:
                raise ValueError("Cloudflare ruleset update was unsuccessful")
            managed_rules = tuple(
                rule for rule in updated.result.rules if rule.description == marker
            )
            if len(managed_rules) != 1:
                raise ValueError("Cloudflare managed cache rule update is ambiguous")
            managed = managed_rules[0]
        except (ValidationError, ValueError) as error:
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "Cloudflare returned an invalid cache ruleset update",
            ) from error
        return CloudflareCacheRuleReceipt(
            zone_id,
            template,
            True,
            updated.result.id,
            managed.id,
            previous,
        )

    async def list_edge_redirects(
        self,
        request: ProviderReadRequest,
        zone_id: str,
    ) -> tuple[CloudflareEdgeRedirect, ...]:
        """List only redirect rules that carry Rankrat's stable ownership marker."""

        credential = self._credential(request, zone_id)
        payload = await self._request_json(
            request,
            credential,
            "GET",
            f"{_API_ROOT}/zones/{zone_id}/rulesets/phases/{_REDIRECT_RULESET_PHASE}/entrypoint",
            allow_not_found=True,
        )
        if payload is None:
            return ()
        ruleset = _validated_ruleset(payload, _REDIRECT_RULESET_PHASE, "redirect")
        redirects = tuple(
            _edge_redirect_from_rule(zone_id, rule)
            for rule in ruleset.rules
            if rule.description.startswith(_REDIRECT_MARKER)
        )
        return tuple(sorted(redirects, key=lambda redirect: redirect.source_path))

    async def upsert_edge_redirect(
        self,
        request: ProviderReadRequest,
        zone_id: str,
        source_path: str,
        target_url: str,
        status_code: CloudflareRedirectStatus,
        preserve_query_string: bool,
    ) -> CloudflareEdgeRedirectReceipt:
        """Create or replace one identified Rankrat redirect while preserving other rules."""

        credential = self._credential(request, zone_id)
        lock = self._edge_redirect_locks.setdefault(zone_id, asyncio.Lock())
        async with lock:
            return await self._upsert_edge_redirect_locked(
                request,
                credential,
                zone_id,
                source_path,
                target_url,
                status_code,
                preserve_query_string,
            )

    async def delete_edge_redirect(
        self,
        request: ProviderReadRequest,
        zone_id: str,
        rule_id: str,
    ) -> None:
        """Delete exactly one already-listed Rankrat-managed dynamic redirect rule."""

        credential = self._credential(request, zone_id)
        _require_rule_id(rule_id)
        lock = self._edge_redirect_locks.setdefault(zone_id, asyncio.Lock())
        async with lock:
            payload = await self._request_json(
                request,
                credential,
                "GET",
                f"{_API_ROOT}/zones/{zone_id}/rulesets/phases/{_REDIRECT_RULESET_PHASE}/entrypoint",
                allow_not_found=True,
            )
            if payload is None:
                raise BoundaryDeniedError("Rankrat-managed edge redirect was not found")
            ruleset = _validated_ruleset(payload, _REDIRECT_RULESET_PHASE, "redirect")
            rule = next((item for item in ruleset.rules if item.id == rule_id), None)
            if rule is None or not rule.description.startswith(_REDIRECT_MARKER):
                raise BoundaryDeniedError("edge redirect is not managed by Rankrat")
            await self._request_json(
                request,
                credential,
                "DELETE",
                f"{_API_ROOT}/zones/{zone_id}/rulesets/{ruleset.id}/rules/{rule_id}",
            )

    async def _upsert_edge_redirect_locked(
        self,
        request: ProviderReadRequest,
        credential: Path,
        zone_id: str,
        source_path: str,
        target_url: str,
        status_code: CloudflareRedirectStatus,
        preserve_query_string: bool,
    ) -> CloudflareEdgeRedirectReceipt:
        expected = _edge_redirect_rule(
            source_path,
            target_url,
            status_code,
            preserve_query_string,
        )
        payload = await self._request_json(
            request,
            credential,
            "GET",
            f"{_API_ROOT}/zones/{zone_id}/rulesets/phases/{_REDIRECT_RULESET_PHASE}/entrypoint",
            allow_not_found=True,
        )
        if payload is None:
            created = await self._request_json(
                request,
                credential,
                "PUT",
                f"{_API_ROOT}/zones/{zone_id}/rulesets/phases/{_REDIRECT_RULESET_PHASE}/entrypoint",
                json_body={
                    "name": "Rankrat managed redirect rules",
                    "description": "Provider-neutral redirects managed by Rankrat",
                    "kind": "zone",
                    "phase": _REDIRECT_RULESET_PHASE,
                    "rules": [expected],
                },
            )
            ruleset = _validated_ruleset(created, _REDIRECT_RULESET_PHASE, "redirect")
            rule = _single_managed_redirect(ruleset.rules, expected["ref"])
            return CloudflareEdgeRedirectReceipt(
                _edge_redirect_from_rule(zone_id, rule),
                True,
                True,
            )
        ruleset = _validated_ruleset(payload, _REDIRECT_RULESET_PHASE, "redirect")
        matched = next((rule for rule in ruleset.rules if rule.ref == expected["ref"]), None)
        if matched is not None and _same_managed_rule(
            _strip_read_only_rule_fields(matched.model_dump()),
            expected,
        ):
            return CloudflareEdgeRedirectReceipt(
                _edge_redirect_from_rule(zone_id, matched),
                False,
                False,
            )
        if matched is not None and matched.id is None:
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "Cloudflare managed edge redirect has no stable identifier",
            )
        method = "POST" if matched is None else "PATCH"
        rule_path = "rules" if matched is None else f"rules/{matched.id}"
        updated = await self._request_json(
            request,
            credential,
            method,
            f"{_API_ROOT}/zones/{zone_id}/rulesets/{ruleset.id}/{rule_path}",
            json_body=expected,
        )
        updated_ruleset = _validated_ruleset(updated, _REDIRECT_RULESET_PHASE, "redirect")
        rule = _single_managed_redirect(updated_ruleset.rules, expected["ref"])
        return CloudflareEdgeRedirectReceipt(
            _edge_redirect_from_rule(zone_id, rule),
            matched is None,
            True,
        )

    def _credential(self, request: ProviderReadRequest, zone_id: str) -> Path:
        if _ZONE_ID_PATTERN.fullmatch(zone_id) is None:
            raise BoundaryDeniedError("Cloudflare zone ID is invalid")
        account = self._policy.require_resource(
            str(request.account_id),
            Provider.CLOUDFLARE,
            ResourceKind.DNS_ZONE,
            zone_id,
        )
        return account.credential

    async def _create_cache_ruleset(
        self,
        request: ProviderReadRequest,
        credential: Path,
        zone_id: str,
        template: CloudflareCacheTemplate,
    ) -> CloudflareCacheRuleReceipt:
        payload = await self._request_json(
            request,
            credential,
            "PUT",
            f"{_API_ROOT}/zones/{zone_id}/rulesets/phases/{_RULESET_PHASE}/entrypoint",
            json_body={
                "name": "Rankrat managed cache rules",
                "description": "Finite cache templates managed by Rankrat",
                "kind": "zone",
                "phase": _RULESET_PHASE,
                "rules": [_template_rule(template)],
            },
        )
        try:
            response = _RulesetResponse.model_validate(payload)
            marker = _template_marker(template)
            managed = next(
                (rule for rule in response.result.rules if rule.description == marker),
                None,
            )
            if not response.success or managed is None:
                raise ValueError("Cloudflare ruleset creation was unsuccessful")
        except (ValidationError, ValueError) as error:
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "Cloudflare returned an invalid cache ruleset creation response",
            ) from error
        return CloudflareCacheRuleReceipt(
            zone_id,
            template,
            True,
            response.result.id,
            managed.id,
            None,
        )

    async def _request_json(
        self,
        request: ProviderReadRequest,
        credential: Path,
        method: str,
        url: str,
        *,
        json_body: object | None = None,
        allow_not_found: bool = False,
    ) -> object | None:
        token = self._load_token(credential)
        try:
            async with (
                httpx.AsyncClient(
                    transport=self._transport_factory(),
                    trust_env=False,
                    follow_redirects=False,
                    timeout=httpx.Timeout(request.timeout_seconds),
                ) as client,
                client.stream(
                    method,
                    url,
                    headers={"Authorization": f"Bearer {token}"},
                    json=json_body,
                ) as response,
            ):
                if allow_not_found and response.status_code == 404:
                    return None
                self._raise_for_status(response)
                body = await read_limited_response(
                    response,
                    description="Cloudflare",
                )
        except httpx.TimeoutException as error:
            raise ProviderOperationError(
                ProviderFailureCode.TIMEOUT,
                "Cloudflare request timed out",
            ) from error
        except httpx.HTTPError as error:
            raise ProviderOperationError(
                ProviderFailureCode.UNAVAILABLE,
                "Cloudflare is unavailable",
            ) from error
        try:
            return cast(object, json.loads(body))
        except json.JSONDecodeError as error:
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "Cloudflare returned invalid JSON",
            ) from error

    @staticmethod
    def _load_token(path: Path) -> str:
        try:
            if path.is_symlink() or not path.is_file():
                raise ProviderOperationError(
                    ProviderFailureCode.AUTHENTICATION,
                    "Cloudflare token file is invalid",
                )
            raw = path.read_bytes()
        except OSError as error:
            raise ProviderOperationError(
                ProviderFailureCode.AUTHENTICATION,
                "Cloudflare token file is unavailable",
            ) from error
        if len(raw) > MAX_CLOUDFLARE_TOKEN_BYTES + 2:
            raise ProviderOperationError(
                ProviderFailureCode.AUTHENTICATION,
                "Cloudflare token file is invalid",
            )
        try:
            token = raw.decode("ascii").strip()
        except UnicodeDecodeError as error:
            raise ProviderOperationError(
                ProviderFailureCode.AUTHENTICATION,
                "Cloudflare token file is invalid",
            ) from error
        if _TOKEN_PATTERN.fullmatch(token) is None:
            raise ProviderOperationError(
                ProviderFailureCode.AUTHENTICATION,
                "Cloudflare token file is invalid",
            )
        return token

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        if response.status_code == 401:
            code = ProviderFailureCode.AUTHENTICATION
        elif response.status_code == 403:
            code = ProviderFailureCode.FORBIDDEN
        elif response.status_code == 429:
            code = ProviderFailureCode.RATE_LIMITED
        elif response.status_code >= 500:
            code = ProviderFailureCode.UNAVAILABLE
        elif response.is_redirect or response.status_code >= 400:
            code = ProviderFailureCode.INVALID_RESPONSE
        else:
            return
        raise ProviderOperationError(code, "Cloudflare request failed")


def _template_marker(template: CloudflareCacheTemplate) -> str:
    return f"Managed by Rankrat [{template.value}]"


def _template_rule(template: CloudflareCacheTemplate) -> dict[str, object]:
    if template is CloudflareCacheTemplate.CACHE_STATIC_ASSETS:
        return {
            "action": "set_cache_settings",
            "expression": (
                '(http.request.uri.path.extension in {"css" "js" "jpg" "jpeg" '
                '"png" "gif" "webp" "svg" "ico" "woff" "woff2"})'
            ),
            "description": _template_marker(template),
            "enabled": True,
            "action_parameters": {
                "cache": True,
                "edge_ttl": {"mode": "override_origin", "default": 86400},
            },
        }
    return {
        "action": "set_cache_settings",
        "expression": '(http.request.uri.path.extension in {"" "html" "htm"})',
        "description": _template_marker(template),
        "enabled": True,
        "action_parameters": {"cache": False},
    }


def _strip_read_only_rule_fields(rule: dict[str, object]) -> dict[str, object]:
    return {
        key: value
        for key, value in rule.items()
        if key in _WRITABLE_RULE_FIELDS and value is not None
    }


def _same_managed_rule(actual: dict[str, object], expected: dict[str, object]) -> bool:
    return all(actual.get(key) == value for key, value in expected.items())


def _validated_ruleset(
    payload: object,
    phase: str,
    subject: str,
) -> _Ruleset:
    try:
        response = _RulesetResponse.model_validate(payload)
        if not response.success or response.result.phase != phase:
            raise ValueError("Cloudflare ruleset was unsuccessful")
        return response.result
    except (ValidationError, ValueError) as error:
        raise ProviderOperationError(
            ProviderFailureCode.INVALID_RESPONSE,
            f"Cloudflare returned an invalid {subject} ruleset",
        ) from error


def _edge_redirect_rule(
    source_path: str,
    target_url: str,
    status_code: CloudflareRedirectStatus,
    preserve_query_string: bool,
) -> dict[str, object]:
    _require_edge_redirect_path(source_path)
    normalized_target = normalize_public_https_url(target_url, "edge redirect target")
    reference = _edge_redirect_reference(source_path)
    return {
        "ref": reference,
        "action": "redirect",
        "expression": f'{_REDIRECT_EXPRESSION_PREFIX}"{source_path}"',
        "description": f"{_REDIRECT_MARKER} {reference}",
        "enabled": True,
        "action_parameters": {
            "from_value": {
                "target_url": {"value": normalized_target},
                "status_code": int(status_code),
                "preserve_query_string": preserve_query_string,
            }
        },
    }


def _edge_redirect_reference(source_path: str) -> str:
    digest = hashlib.sha256(source_path.encode("utf-8")).hexdigest()
    return f"rankrat_redirect_{digest[:16]}"


def _edge_redirect_from_rule(
    zone_id: str,
    rule: _RulesetRule,
) -> CloudflareEdgeRedirect:
    if rule.id is None:
        raise ProviderOperationError(
            ProviderFailureCode.INVALID_RESPONSE,
            "Cloudflare managed edge redirect has no stable identifier",
        )
    source_path = _edge_redirect_source_path(rule.expression)
    parameters = rule.action_parameters.get("from_value")
    if not isinstance(parameters, dict):
        raise ProviderOperationError(
            ProviderFailureCode.INVALID_RESPONSE,
            "Cloudflare managed edge redirect is invalid",
        )
    redirect_parameters = cast(dict[str, object], parameters)
    target_url = redirect_parameters.get("target_url")
    status_code = redirect_parameters.get("status_code")
    preserve_query_string = redirect_parameters.get("preserve_query_string", False)
    target_value: object | None = None
    if isinstance(target_url, dict):
        target_value = cast(dict[str, object], target_url).get("value")
    if (
        not isinstance(target_url, dict)
        or not isinstance(target_value, str)
        or not isinstance(status_code, int)
        or status_code not in _REDIRECT_STATUS_CODES
        or not isinstance(preserve_query_string, bool)
    ):
        raise ProviderOperationError(
            ProviderFailureCode.INVALID_RESPONSE,
            "Cloudflare managed edge redirect is invalid",
        )
    try:
        return CloudflareEdgeRedirect(
            zone_id,
            rule.id,
            source_path,
            normalize_public_https_url(target_value, "edge redirect target"),
            CloudflareRedirectStatus(status_code),
            preserve_query_string,
        )
    except ValueError as error:
        raise ProviderOperationError(
            ProviderFailureCode.INVALID_RESPONSE,
            "Cloudflare managed edge redirect is invalid",
        ) from error


def _single_managed_redirect(
    rules: list[_RulesetRule],
    reference: object,
) -> _RulesetRule:
    if not isinstance(reference, str):
        raise ProviderOperationError(
            ProviderFailureCode.INVALID_RESPONSE,
            "Cloudflare managed edge redirect has an invalid reference",
        )
    matches = tuple(rule for rule in rules if rule.ref == reference)
    if len(matches) != 1:
        raise ProviderOperationError(
            ProviderFailureCode.INVALID_RESPONSE,
            "Cloudflare managed edge redirect update is ambiguous",
        )
    return matches[0]


def _edge_redirect_source_path(expression: str) -> str:
    if not expression.startswith(_REDIRECT_EXPRESSION_PREFIX):
        raise ProviderOperationError(
            ProviderFailureCode.INVALID_RESPONSE,
            "Cloudflare managed edge redirect has an invalid expression",
        )
    quoted_path = expression.removeprefix(_REDIRECT_EXPRESSION_PREFIX)
    if len(quoted_path) < 2 or not quoted_path.startswith('"') or not quoted_path.endswith('"'):
        raise ProviderOperationError(
            ProviderFailureCode.INVALID_RESPONSE,
            "Cloudflare managed edge redirect has an invalid expression",
        )
    path = quoted_path[1:-1]
    _require_edge_redirect_path(path)
    return path


def _require_edge_redirect_path(value: str) -> None:
    if (
        not value.startswith("/")
        or len(value) > MAX_EDGE_REDIRECT_SOURCE_PATH_CHARS
        or any(character in value for character in ('"', "\\", "\r", "\n"))
    ):
        raise ValueError("edge redirect source path is invalid")


def _require_rule_id(value: str) -> None:
    if _ZONE_ID_PATTERN.fullmatch(value) is None:
        raise ValueError("Cloudflare rule ID is invalid")
