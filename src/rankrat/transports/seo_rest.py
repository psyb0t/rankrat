"""Spec-owned REST adapters for persistent and cross-provider SEO intelligence."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import Field

from rankrat.constants import (
    CLOUDFLARE_ANALYTICS_OPERATION,
    CLOUDFLARE_ANALYTICS_PATH,
    CLOUDFLARE_CACHE_PURGE_OPERATION,
    CLOUDFLARE_CACHE_PURGE_PATH,
    CLOUDFLARE_CACHE_TEMPLATE_OPERATION,
    CLOUDFLARE_CACHE_TEMPLATE_PATH,
    CONTENT_OPPORTUNITIES_OPERATION,
    CONTENT_OPPORTUNITIES_PATH,
    CRUX_HISTORY_OPERATION,
    CRUX_HISTORY_PATH,
    DEFAULT_STATE_PAGE_SIZE,
    INTERNAL_LINK_GRAPH_OPERATION,
    INTERNAL_LINK_GRAPH_PATH,
    INTERNAL_LINK_OPPORTUNITIES_OPERATION,
    INTERNAL_LINK_OPPORTUNITIES_PATH,
    ISSUE_EVENTS_OPERATION,
    ISSUE_EVENTS_PATH,
    ISSUE_PATH,
    ISSUE_STATUS_OPERATION,
    MAX_MONITOR_INTERVAL_SECONDS,
    MAX_MONITOR_NAME_CHARS,
    MAX_STATE_PAGE_SIZE,
    MIN_MONITOR_INTERVAL_SECONDS,
    MONITOR_DELETE_OPERATION,
    MONITOR_ISSUES_OPERATION,
    MONITOR_ISSUES_PATH,
    MONITOR_PATH,
    MONITOR_RUN_OPERATION,
    MONITOR_RUN_PATH,
    MONITOR_SNAPSHOTS_OPERATION,
    MONITOR_SNAPSHOTS_PATH,
    MONITOR_UPDATE_OPERATION,
    MONITORS_CREATE_OPERATION,
    MONITORS_LIST_OPERATION,
    MONITORS_PATH,
    ORPHAN_PAGE_REPORT_OPERATION,
    ORPHAN_PAGE_REPORT_PATH,
)
from rankrat.models.boundaries import ACCOUNT_ID_PATTERN
from rankrat.models.common import JsonValue, to_json_value
from rankrat.operator.content_opportunities import (
    ContentOpportunityReport,
    ContentOpportunityRequest,
)
from rankrat.operator.internal_links import (
    InternalLinkGraph,
    InternalLinkOpportunityReport,
    InternalLinkRequest,
    OrphanPageReport,
    OrphanPageRequest,
)
from rankrat.operator.monitoring import (
    IssueHistoryRequest,
    IssueStatusRequest,
    MonitorCreateRequest,
    MonitorHistoryRequest,
    MonitorIssueListRequest,
    MonitorListRequest,
    MonitorRunResult,
    MonitorUpdateRequest,
)
from rankrat.providers.cloudflare_performance import (
    CloudflareAnalyticsReport,
    CloudflareCacheRuleReceipt,
    CloudflarePurgeReceipt,
)
from rankrat.providers.crux import CruxHistoryRecord
from rankrat.services.cloudflare_performance import (
    CloudflareAnalyticsRequest,
    CloudflareCacheTemplateRequest,
    CloudflarePurgeRequest,
)
from rankrat.services.crux import CruxHistoryRequest
from rankrat.state.sqlite import (
    IssueEvent,
    IssueStatus,
    MonitorDefinition,
    MonitorSnapshot,
    StatePage,
    TrackedIssue,
)
from rankrat.transports.runtime import ApplicationServices
from rankrat.transports.seo_contracts import (
    CloudflareAnalyticsInput,
    CloudflareCacheTemplateInput,
    CloudflarePurgeInput,
    ContentOpportunityInput,
    CruxHistoryInput,
    InternalLinkInput,
    MonitorCreateInput,
    MonitorDeleteReceipt,
    MonitorScopeInput,
    OrphanPageInput,
    StrictInput,
)

_URL_MAX_LENGTH = 2_048


class _MonitorUpdateBody(StrictInput):
    name: str = Field(min_length=1, max_length=MAX_MONITOR_NAME_CHARS)
    interval_seconds: int = Field(
        ge=MIN_MONITOR_INTERVAL_SECONDS,
        le=MAX_MONITOR_INTERVAL_SECONDS,
    )
    enabled: bool


class _IssueStatusBody(StrictInput):
    monitor_id: UUID
    account_id: str = Field(pattern=ACCOUNT_ID_PATTERN)
    site_url: str = Field(min_length=1, max_length=_URL_MAX_LENGTH)
    status: IssueStatus


def build_seo_router(services: ApplicationServices) -> APIRouter:
    """Build the additive routes shared by the public YAML contract."""
    router = APIRouter()

    @router.post(
        INTERNAL_LINK_GRAPH_PATH,
        response_model=InternalLinkGraph,
        operation_id=INTERNAL_LINK_GRAPH_OPERATION,
    )
    async def internal_link_graph(body: InternalLinkInput) -> JsonValue:
        return to_json_value(await services.internal_links.graph(_internal_link_request(body)))

    @router.post(
        ORPHAN_PAGE_REPORT_PATH,
        response_model=OrphanPageReport,
        operation_id=ORPHAN_PAGE_REPORT_OPERATION,
    )
    async def orphan_page_report(body: OrphanPageInput) -> JsonValue:
        return to_json_value(
            await services.internal_links.orphans(
                OrphanPageRequest(
                    crawl_account_id=body.crawl_account_id,
                    crawl_site_url=body.crawl_site_url,
                    search_console_account_id=body.search_console_account_id,
                    search_console_site_url=body.search_console_site_url,
                    ga4_account_id=body.ga4_account_id,
                    ga4_property_id=body.ga4_property_id,
                    start_date=body.start_date,
                    end_date=body.end_date,
                    max_pages=body.max_pages,
                    max_depth=body.max_depth,
                )
            )
        )

    @router.post(
        INTERNAL_LINK_OPPORTUNITIES_PATH,
        response_model=InternalLinkOpportunityReport,
        operation_id=INTERNAL_LINK_OPPORTUNITIES_OPERATION,
    )
    async def internal_link_opportunities(body: InternalLinkInput) -> JsonValue:
        return to_json_value(
            await services.internal_links.opportunities(_internal_link_request(body))
        )

    @router.post(
        CRUX_HISTORY_PATH,
        response_model=CruxHistoryRecord,
        operation_id=CRUX_HISTORY_OPERATION,
    )
    async def crux_history(body: CruxHistoryInput) -> JsonValue:
        return to_json_value(
            await services.crux.history(
                CruxHistoryRequest(
                    account_id=body.account_id,
                    site_url=body.site_url,
                    target=body.target,
                    target_kind=body.target_kind,
                    form_factor=body.form_factor,
                    metrics=body.metrics,
                    collection_period_count=body.collection_period_count,
                    timeout_seconds=body.timeout_seconds,
                )
            )
        )

    @router.post(
        CLOUDFLARE_ANALYTICS_PATH,
        response_model=CloudflareAnalyticsReport,
        operation_id=CLOUDFLARE_ANALYTICS_OPERATION,
    )
    async def cloudflare_analytics(body: CloudflareAnalyticsInput) -> JsonValue:
        return to_json_value(
            await services.cloudflare_performance.analytics(
                CloudflareAnalyticsRequest(
                    body.account_id,
                    body.zone_id,
                    body.start,
                    body.end,
                    body.limit,
                    body.timeout_seconds,
                )
            )
        )

    @router.post(
        CONTENT_OPPORTUNITIES_PATH,
        response_model=ContentOpportunityReport,
        operation_id=CONTENT_OPPORTUNITIES_OPERATION,
    )
    async def content_opportunities(body: ContentOpportunityInput) -> JsonValue:
        return to_json_value(
            await services.content_opportunities.report(
                ContentOpportunityRequest(
                    google_account_id=body.google_account_id,
                    search_console_site_url=body.search_console_site_url,
                    bing_account_id=body.bing_account_id,
                    bing_site_url=body.bing_site_url,
                    ga4_account_id=body.ga4_account_id,
                    ga4_property_id=body.ga4_property_id,
                    crawl_account_id=body.crawl_account_id,
                    crawl_site_url=body.crawl_site_url,
                    start_date=body.start_date,
                    end_date=body.end_date,
                    limit=body.limit,
                )
            )
        )

    @router.get(
        MONITORS_PATH,
        response_model=StatePage[MonitorDefinition],
        operation_id=MONITORS_LIST_OPERATION,
    )
    def monitors_list(
        account_id: Annotated[str, Query(pattern=ACCOUNT_ID_PATTERN)],
        site_url: Annotated[str, Query(min_length=1, max_length=_URL_MAX_LENGTH)],
        limit: Annotated[int, Query(ge=1, le=MAX_STATE_PAGE_SIZE)] = DEFAULT_STATE_PAGE_SIZE,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> JsonValue:
        return to_json_value(
            services.monitoring.list_monitors(
                MonitorListRequest(limit, offset, account_id, site_url)
            )
        )

    _register_monitor_read_routes(router, services)
    if services.writes_enabled:
        _register_write_routes(router, services)
    return router


def _register_monitor_read_routes(router: APIRouter, services: ApplicationServices) -> None:
    @router.get(
        MONITOR_SNAPSHOTS_PATH,
        response_model=StatePage[MonitorSnapshot],
        operation_id=MONITOR_SNAPSHOTS_OPERATION,
    )
    def monitor_snapshots(
        monitor_id: UUID,
        account_id: Annotated[str, Query(pattern=ACCOUNT_ID_PATTERN)],
        site_url: Annotated[str, Query(min_length=1, max_length=_URL_MAX_LENGTH)],
        limit: Annotated[int, Query(ge=1, le=MAX_STATE_PAGE_SIZE)] = DEFAULT_STATE_PAGE_SIZE,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> JsonValue:
        return to_json_value(
            services.monitoring.list_snapshots(
                MonitorHistoryRequest(limit, offset, str(monitor_id), account_id, site_url)
            )
        )

    @router.get(
        MONITOR_ISSUES_PATH,
        response_model=StatePage[TrackedIssue],
        operation_id=MONITOR_ISSUES_OPERATION,
    )
    def monitor_issues(
        monitor_id: UUID,
        account_id: Annotated[str, Query(pattern=ACCOUNT_ID_PATTERN)],
        site_url: Annotated[str, Query(min_length=1, max_length=_URL_MAX_LENGTH)],
        status: Annotated[str | None, Query(pattern=r"^(open|acknowledged|resolved)$")] = None,
        limit: Annotated[int, Query(ge=1, le=MAX_STATE_PAGE_SIZE)] = DEFAULT_STATE_PAGE_SIZE,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> JsonValue:
        return to_json_value(
            services.monitoring.list_issues(
                MonitorIssueListRequest(
                    limit,
                    offset,
                    str(monitor_id),
                    account_id,
                    site_url,
                    IssueStatus(status) if status is not None else None,
                )
            )
        )

    @router.get(
        ISSUE_EVENTS_PATH,
        response_model=StatePage[IssueEvent],
        operation_id=ISSUE_EVENTS_OPERATION,
    )
    def issue_events(
        issue_id: UUID,
        monitor_id: Annotated[UUID, Query()],
        account_id: Annotated[str, Query(pattern=ACCOUNT_ID_PATTERN)],
        site_url: Annotated[str, Query(min_length=1, max_length=_URL_MAX_LENGTH)],
        limit: Annotated[int, Query(ge=1, le=MAX_STATE_PAGE_SIZE)] = DEFAULT_STATE_PAGE_SIZE,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> JsonValue:
        return to_json_value(
            services.monitoring.list_issue_events(
                IssueHistoryRequest(
                    limit,
                    offset,
                    str(issue_id),
                    str(monitor_id),
                    account_id,
                    site_url,
                )
            )
        )


def _register_write_routes(router: APIRouter, services: ApplicationServices) -> None:
    @router.post(
        MONITORS_PATH,
        response_model=MonitorDefinition,
        operation_id=MONITORS_CREATE_OPERATION,
    )
    def monitor_create(body: MonitorCreateInput) -> JsonValue:
        return to_json_value(
            services.monitoring.create_monitor(
                MonitorCreateRequest(
                    body.name,
                    body.account_id,
                    body.site_url,
                    body.interval_seconds,
                )
            )
        )

    @router.patch(
        MONITOR_PATH,
        response_model=MonitorDefinition,
        operation_id=MONITOR_UPDATE_OPERATION,
    )
    def monitor_update(
        monitor_id: UUID,
        account_id: Annotated[str, Query(pattern=ACCOUNT_ID_PATTERN)],
        site_url: Annotated[str, Query(min_length=1, max_length=_URL_MAX_LENGTH)],
        body: _MonitorUpdateBody,
    ) -> JsonValue:
        return to_json_value(
            services.monitoring.update_monitor(
                MonitorUpdateRequest(
                    str(monitor_id),
                    account_id,
                    site_url,
                    body.name,
                    body.interval_seconds,
                    body.enabled,
                )
            )
        )

    @router.delete(
        MONITOR_PATH,
        response_model=MonitorDeleteReceipt,
        operation_id=MONITOR_DELETE_OPERATION,
    )
    def monitor_delete(
        monitor_id: UUID,
        account_id: Annotated[str, Query(pattern=ACCOUNT_ID_PATTERN)],
        site_url: Annotated[str, Query(min_length=1, max_length=_URL_MAX_LENGTH)],
    ) -> JsonValue:
        services.monitoring.delete_monitor(
            MonitorHistoryRequest(
                monitor_id=str(monitor_id),
                account_id=account_id,
                site_url=site_url,
            )
        )
        return {"deleted": True, "monitor_id": str(monitor_id)}

    @router.post(
        MONITOR_RUN_PATH,
        response_model=MonitorRunResult,
        operation_id=MONITOR_RUN_OPERATION,
    )
    async def monitor_run(
        monitor_id: UUID,
        body: MonitorScopeInput,
    ) -> JsonValue:
        return to_json_value(
            await services.monitoring.run_monitor(
                MonitorHistoryRequest(
                    monitor_id=str(monitor_id),
                    account_id=body.account_id,
                    site_url=body.site_url,
                )
            )
        )

    @router.patch(
        ISSUE_PATH,
        response_model=TrackedIssue,
        operation_id=ISSUE_STATUS_OPERATION,
    )
    def issue_status_update(issue_id: UUID, body: _IssueStatusBody) -> JsonValue:
        return to_json_value(
            services.monitoring.set_issue_status(
                IssueStatusRequest(
                    str(issue_id),
                    str(body.monitor_id),
                    body.account_id,
                    body.site_url,
                    body.status,
                )
            )
        )

    @router.post(
        CLOUDFLARE_CACHE_PURGE_PATH,
        response_model=CloudflarePurgeReceipt,
        operation_id=CLOUDFLARE_CACHE_PURGE_OPERATION,
    )
    async def cloudflare_cache_purge(body: CloudflarePurgeInput) -> JsonValue:
        return to_json_value(
            await services.cloudflare_performance.purge(
                CloudflarePurgeRequest(
                    body.account_id,
                    body.zone_id,
                    body.site_url,
                    body.urls,
                    body.timeout_seconds,
                )
            )
        )

    @router.post(
        CLOUDFLARE_CACHE_TEMPLATE_PATH,
        response_model=CloudflareCacheRuleReceipt,
        operation_id=CLOUDFLARE_CACHE_TEMPLATE_OPERATION,
    )
    async def cloudflare_cache_template(body: CloudflareCacheTemplateInput) -> JsonValue:
        return to_json_value(
            await services.cloudflare_performance.apply_cache_template(
                CloudflareCacheTemplateRequest(
                    body.account_id,
                    body.zone_id,
                    body.template,
                    body.timeout_seconds,
                )
            )
        )


def _internal_link_request(body: InternalLinkInput) -> InternalLinkRequest:
    return InternalLinkRequest(
        body.account_id,
        body.site_url,
        body.max_pages,
        body.max_depth,
        body.opportunity_limit,
    )
