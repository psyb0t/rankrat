"""Boundary-aware Cloudflare analytics and controlled performance operations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from rankrat.constants import (
    DEFAULT_PROVIDER_TIMEOUT_SECONDS,
    MAX_CLOUDFLARE_ANALYTICS_GROUPS,
    MAX_CLOUDFLARE_ANALYTICS_RANGE_DAYS,
)
from rankrat.errors import InputLimitError
from rankrat.providers.base import AccountId, ProviderReadRequest
from rankrat.providers.cloudflare_performance import (
    CloudflareAnalyticsReport,
    CloudflareCacheRuleReceipt,
    CloudflareCacheTemplate,
    CloudflarePerformanceClient,
    CloudflarePurgeReceipt,
)


@dataclass(frozen=True, slots=True)
class CloudflareAnalyticsRequest:
    account_id: str
    zone_id: str
    start: datetime
    end: datetime
    limit: int = 100
    timeout_seconds: float = DEFAULT_PROVIDER_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        if self.start.tzinfo is None or self.end.tzinfo is None or self.end <= self.start:
            raise InputLimitError("Cloudflare analytics requires a valid timezone-aware range")
        if self.end - self.start > timedelta(days=MAX_CLOUDFLARE_ANALYTICS_RANGE_DAYS):
            raise InputLimitError("Cloudflare analytics date range exceeds the allowed limit")
        if not 1 <= self.limit <= MAX_CLOUDFLARE_ANALYTICS_GROUPS:
            raise InputLimitError("Cloudflare analytics limit is outside the allowed range")


@dataclass(frozen=True, slots=True)
class CloudflarePurgeRequest:
    account_id: str
    zone_id: str
    site_url: str
    urls: tuple[str, ...]
    timeout_seconds: float = DEFAULT_PROVIDER_TIMEOUT_SECONDS


@dataclass(frozen=True, slots=True)
class CloudflareCacheTemplateRequest:
    account_id: str
    zone_id: str
    template: CloudflareCacheTemplate
    timeout_seconds: float = DEFAULT_PROVIDER_TIMEOUT_SECONDS


class CloudflarePerformanceService:
    def __init__(self, client: CloudflarePerformanceClient) -> None:
        self._client = client

    async def analytics(self, request: CloudflareAnalyticsRequest) -> CloudflareAnalyticsReport:
        return await self._client.analytics(
            ProviderReadRequest(AccountId(request.account_id), request.timeout_seconds),
            request.zone_id,
            request.start,
            request.end,
            request.limit,
        )

    async def purge(self, request: CloudflarePurgeRequest) -> CloudflarePurgeReceipt:
        return await self._client.purge_urls(
            ProviderReadRequest(AccountId(request.account_id), request.timeout_seconds),
            request.zone_id,
            request.site_url,
            request.urls,
        )

    async def apply_cache_template(
        self,
        request: CloudflareCacheTemplateRequest,
    ) -> CloudflareCacheRuleReceipt:
        return await self._client.apply_cache_template(
            ProviderReadRequest(AccountId(request.account_id), request.timeout_seconds),
            request.zone_id,
            request.template,
        )
