"""Strict transport inputs shared by REST and both MCP transports."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from rankrat.constants import (
    DEFAULT_MONITOR_INTERVAL_SECONDS,
    DEFAULT_PROVIDER_TIMEOUT_SECONDS,
    DEFAULT_SITE_AUDIT_DEPTH,
    DEFAULT_SITE_AUDIT_PAGES,
    DEFAULT_STATE_PAGE_SIZE,
    MAX_CLARITY_DATE_RANGE_DAYS,
    MAX_CLARITY_DIMENSIONS,
    MAX_CLOUDFLARE_ANALYTICS_GROUPS,
    MAX_CLOUDFLARE_PURGE_URLS,
    MAX_CONTENT_OPPORTUNITIES,
    MAX_CRUX_HISTORY_PERIODS,
    MAX_CRUX_METRICS,
    MAX_EDGE_REDIRECT_SOURCE_PATH_CHARS,
    MAX_GTM_NAME_CHARS,
    MAX_GTM_NOTES_CHARS,
    MAX_INTERNAL_LINK_OPPORTUNITIES,
    MAX_MONITOR_INTERVAL_SECONDS,
    MAX_MONITOR_NAME_CHARS,
    MAX_PROVIDER_TIMEOUT_SECONDS,
    MAX_SITE_AUDIT_DEPTH,
    MAX_SITE_AUDIT_PAGES,
    MAX_STATE_PAGE_SIZE,
    MIN_MONITOR_INTERVAL_SECONDS,
    MIN_PROVIDER_TIMEOUT_SECONDS,
)
from rankrat.models.boundaries import ACCOUNT_ID_PATTERN
from rankrat.providers.clarity import ClarityDimension
from rankrat.providers.cloudflare_performance import (
    CloudflareCacheTemplate,
    CloudflareRedirectStatus,
)
from rankrat.providers.crux import CruxFormFactor, CruxMetric
from rankrat.providers.google_tag_manager import (
    GtmEntityDefinition,
    GtmEntityKind,
    GtmUsageContext,
)
from rankrat.state.sqlite import IssueStatus

_URL_MAX_LENGTH = 2_048
_ZONE_ID_PATTERN = r"^[0-9a-f]{32}$"

AccountId = Annotated[str, Field(pattern=ACCOUNT_ID_PATTERN)]
WebUrl = Annotated[str, Field(min_length=1, max_length=_URL_MAX_LENGTH)]
Timeout = Annotated[
    float,
    Field(ge=MIN_PROVIDER_TIMEOUT_SECONDS, le=MAX_PROVIDER_TIMEOUT_SECONDS),
]
PageLimit = Annotated[int, Field(ge=1, le=MAX_STATE_PAGE_SIZE)]
PageOffset = Annotated[int, Field(ge=0)]


class StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class MonitorDeleteReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    deleted: Literal[True]
    monitor_id: UUID


class InternalLinkInput(StrictInput):
    account_id: AccountId
    site_url: WebUrl
    max_pages: int = Field(default=DEFAULT_SITE_AUDIT_PAGES, ge=1, le=MAX_SITE_AUDIT_PAGES)
    max_depth: int = Field(default=DEFAULT_SITE_AUDIT_DEPTH, ge=0, le=MAX_SITE_AUDIT_DEPTH)
    opportunity_limit: int = Field(default=100, ge=1, le=MAX_INTERNAL_LINK_OPPORTUNITIES)


class OrphanPageInput(StrictInput):
    crawl_account_id: AccountId
    crawl_site_url: WebUrl
    search_console_account_id: AccountId
    search_console_site_url: WebUrl
    ga4_account_id: AccountId
    ga4_property_id: str = Field(pattern=r"^[0-9]+$")
    start_date: date
    end_date: date
    max_pages: int = Field(default=DEFAULT_SITE_AUDIT_PAGES, ge=1, le=MAX_SITE_AUDIT_PAGES)
    max_depth: int = Field(default=DEFAULT_SITE_AUDIT_DEPTH, ge=0, le=MAX_SITE_AUDIT_DEPTH)


class CruxHistoryInput(StrictInput):
    account_id: AccountId
    site_url: WebUrl
    target: WebUrl
    target_kind: Literal["url", "origin"] = "url"
    form_factor: CruxFormFactor = CruxFormFactor.ALL
    metrics: tuple[CruxMetric, ...] = Field(
        default_factory=lambda: tuple(CruxMetric),
        min_length=1,
        max_length=MAX_CRUX_METRICS,
    )
    collection_period_count: int = Field(default=25, ge=1, le=MAX_CRUX_HISTORY_PERIODS)
    timeout_seconds: Timeout = DEFAULT_PROVIDER_TIMEOUT_SECONDS


class CloudflareAnalyticsInput(StrictInput):
    account_id: AccountId
    zone_id: str = Field(pattern=_ZONE_ID_PATTERN)
    start: datetime
    end: datetime
    limit: int = Field(default=100, ge=1, le=MAX_CLOUDFLARE_ANALYTICS_GROUPS)
    timeout_seconds: Timeout = DEFAULT_PROVIDER_TIMEOUT_SECONDS


class CloudflarePurgeInput(StrictInput):
    account_id: AccountId
    zone_id: str = Field(pattern=_ZONE_ID_PATTERN)
    site_url: WebUrl
    urls: tuple[WebUrl, ...] = Field(min_length=1, max_length=MAX_CLOUDFLARE_PURGE_URLS)
    timeout_seconds: Timeout = DEFAULT_PROVIDER_TIMEOUT_SECONDS


class CloudflareCacheTemplateInput(StrictInput):
    account_id: AccountId
    zone_id: str = Field(pattern=_ZONE_ID_PATTERN)
    template: CloudflareCacheTemplate
    timeout_seconds: Timeout = DEFAULT_PROVIDER_TIMEOUT_SECONDS


class ClarityInsightsInput(StrictInput):
    account_id: AccountId
    num_days: int = Field(default=1, ge=1, le=MAX_CLARITY_DATE_RANGE_DAYS)
    dimensions: tuple[ClarityDimension, ...] = Field(
        default=(),
        max_length=MAX_CLARITY_DIMENSIONS,
    )
    timeout_seconds: Timeout = DEFAULT_PROVIDER_TIMEOUT_SECONDS


class BingContentSubmissionInput(StrictInput):
    account_id: AccountId
    site_url: WebUrl
    page_url: WebUrl
    dynamic_serving: bool = False
    timeout_seconds: Timeout = DEFAULT_PROVIDER_TIMEOUT_SECONDS


class EdgeRedirectListInput(StrictInput):
    account_id: AccountId
    site_url: WebUrl
    timeout_seconds: Timeout = DEFAULT_PROVIDER_TIMEOUT_SECONDS


class EdgeRedirectUpsertInput(EdgeRedirectListInput):
    source_path: str = Field(min_length=1, max_length=MAX_EDGE_REDIRECT_SOURCE_PATH_CHARS)
    target_url: WebUrl
    status_code: CloudflareRedirectStatus = CloudflareRedirectStatus.MOVED_PERMANENTLY
    preserve_query_string: bool = True


class EdgeRedirectDeleteInput(EdgeRedirectListInput):
    rule_id: str = Field(pattern=_ZONE_ID_PATTERN)


class GtmAccountInput(StrictInput):
    account_id: AccountId
    timeout_seconds: Timeout = DEFAULT_PROVIDER_TIMEOUT_SECONDS


class GtmContainerInput(GtmAccountInput):
    gtm_account_id: str = Field(pattern=r"^[0-9]{1,64}$")


class GtmContainerCreateInput(GtmContainerInput):
    name: str = Field(min_length=1, max_length=MAX_GTM_NAME_CHARS)
    usage_contexts: tuple[GtmUsageContext, ...] = Field(min_length=1, max_length=5)


class GtmContainerDeleteInput(GtmContainerInput):
    container_id: str = Field(pattern=r"^[0-9]{1,64}$")


class GtmWorkspaceInput(GtmContainerInput):
    container_id: str = Field(pattern=r"^[0-9]{1,64}$")


class GtmWorkspaceCreateInput(GtmWorkspaceInput):
    name: str = Field(min_length=1, max_length=MAX_GTM_NAME_CHARS)
    description: str | None = Field(default=None, max_length=MAX_GTM_NOTES_CHARS)


class GtmWorkspaceDeleteInput(GtmWorkspaceInput):
    workspace_id: str = Field(pattern=r"^[0-9]{1,64}$")


class GtmEntityInput(GtmWorkspaceInput):
    workspace_id: str = Field(pattern=r"^[0-9]{1,64}$")
    kind: GtmEntityKind


class GtmEntityCreateInput(GtmEntityInput):
    definition: GtmEntityDefinition


class GtmEntityUpdateInput(GtmEntityCreateInput):
    entity_id: str = Field(pattern=r"^[0-9]{1,64}$")


class GtmEntityDeleteInput(GtmEntityInput):
    entity_id: str = Field(pattern=r"^[0-9]{1,64}$")


class GtmVersionCreateInput(GtmWorkspaceInput):
    workspace_id: str = Field(pattern=r"^[0-9]{1,64}$")
    name: str = Field(min_length=1, max_length=MAX_GTM_NAME_CHARS)
    notes: str | None = Field(default=None, max_length=MAX_GTM_NOTES_CHARS)


class GtmVersionPublishInput(GtmWorkspaceInput):
    version_id: str = Field(pattern=r"^[0-9]{1,64}$")


class ContentOpportunityInput(StrictInput):
    google_account_id: AccountId
    search_console_site_url: WebUrl
    bing_account_id: AccountId
    bing_site_url: WebUrl
    ga4_account_id: AccountId
    ga4_property_id: str = Field(pattern=r"^[0-9]+$")
    crawl_account_id: AccountId
    crawl_site_url: WebUrl
    start_date: date
    end_date: date
    limit: int = Field(default=100, ge=1, le=MAX_CONTENT_OPPORTUNITIES)


class MonitorScopeInput(StrictInput):
    account_id: AccountId
    site_url: WebUrl


class MonitorListInput(MonitorScopeInput):
    limit: PageLimit = DEFAULT_STATE_PAGE_SIZE
    offset: PageOffset = 0


class MonitorCreateInput(MonitorScopeInput):
    name: str = Field(min_length=1, max_length=MAX_MONITOR_NAME_CHARS)
    interval_seconds: int = Field(
        default=DEFAULT_MONITOR_INTERVAL_SECONDS,
        ge=MIN_MONITOR_INTERVAL_SECONDS,
        le=MAX_MONITOR_INTERVAL_SECONDS,
    )


class MonitorIdentityInput(MonitorScopeInput):
    monitor_id: UUID


class MonitorUpdateInput(MonitorIdentityInput):
    name: str = Field(min_length=1, max_length=MAX_MONITOR_NAME_CHARS)
    interval_seconds: int = Field(
        ge=MIN_MONITOR_INTERVAL_SECONDS,
        le=MAX_MONITOR_INTERVAL_SECONDS,
    )
    enabled: bool


class MonitorHistoryInput(MonitorIdentityInput):
    limit: PageLimit = DEFAULT_STATE_PAGE_SIZE
    offset: PageOffset = 0


class MonitorIssuesInput(MonitorHistoryInput):
    status: IssueStatus | None = None


class IssueStatusInput(MonitorIdentityInput):
    issue_id: UUID
    status: IssueStatus


class IssueEventsInput(MonitorIdentityInput):
    issue_id: UUID
    limit: PageLimit = DEFAULT_STATE_PAGE_SIZE
    offset: PageOffset = 0
