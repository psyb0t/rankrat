"""MCP catalog and dispatch for SEO intelligence operations."""

from __future__ import annotations

from typing import Any

import mcp.types as types
from pydantic import BaseModel

from rankrat.constants import (
    BING_CONTENT_SUBMISSION_OPERATION,
    CLARITY_INSIGHTS_OPERATION,
    CLOUDFLARE_ANALYTICS_OPERATION,
    CLOUDFLARE_CACHE_PURGE_OPERATION,
    CLOUDFLARE_CACHE_TEMPLATE_OPERATION,
    CONTENT_OPPORTUNITIES_OPERATION,
    CRUX_HISTORY_OPERATION,
    EDGE_REDIRECT_DELETE_OPERATION,
    EDGE_REDIRECT_UPSERT_OPERATION,
    EDGE_REDIRECTS_LIST_OPERATION,
    GTM_ACCOUNTS_LIST_OPERATION,
    GTM_CONTAINERS_CREATE_OPERATION,
    GTM_CONTAINERS_DELETE_OPERATION,
    GTM_CONTAINERS_LIST_OPERATION,
    GTM_ENTITIES_CREATE_OPERATION,
    GTM_ENTITIES_DELETE_OPERATION,
    GTM_ENTITIES_LIST_OPERATION,
    GTM_ENTITIES_UPDATE_OPERATION,
    GTM_VERSION_PUBLISH_OPERATION,
    GTM_WORKSPACE_VERSION_CREATE_OPERATION,
    GTM_WORKSPACES_CREATE_OPERATION,
    GTM_WORKSPACES_DELETE_OPERATION,
    GTM_WORKSPACES_LIST_OPERATION,
    INTERNAL_LINK_GRAPH_OPERATION,
    INTERNAL_LINK_OPPORTUNITIES_OPERATION,
    ISSUE_EVENTS_OPERATION,
    ISSUE_STATUS_OPERATION,
    MONITOR_DELETE_OPERATION,
    MONITOR_ISSUES_OPERATION,
    MONITOR_RUN_OPERATION,
    MONITOR_SNAPSHOTS_OPERATION,
    MONITOR_UPDATE_OPERATION,
    MONITORS_CREATE_OPERATION,
    MONITORS_LIST_OPERATION,
    ORPHAN_PAGE_REPORT_OPERATION,
)
from rankrat.operator.content_opportunities import ContentOpportunityRequest
from rankrat.operator.internal_links import InternalLinkRequest, OrphanPageRequest
from rankrat.operator.monitoring import (
    IssueHistoryRequest,
    IssueStatusRequest,
    MonitorCreateRequest,
    MonitorHistoryRequest,
    MonitorIssueListRequest,
    MonitorListRequest,
    MonitorUpdateRequest,
)
from rankrat.services.bing_content import BingContentSubmissionRequest
from rankrat.services.clarity import ClarityInsightsRequest
from rankrat.services.cloudflare_performance import (
    CloudflareAnalyticsRequest,
    CloudflareCacheTemplateRequest,
    CloudflarePurgeRequest,
)
from rankrat.services.crux import CruxHistoryRequest
from rankrat.services.edge_redirects import (
    EdgeRedirectDeleteRequest,
    EdgeRedirectListRequest,
    EdgeRedirectUpsertRequest,
)
from rankrat.services.google_tag_manager import (
    GtmContainerCreateRequest,
    GtmContainerRequest,
    GtmEntityCreateRequest,
    GtmEntityRequest,
    GtmEntityUpdateRequest,
    GtmVersionCreateRequest,
    GtmVersionPublishRequest,
    GtmWorkspaceCreateRequest,
    GtmWorkspaceRequest,
)
from rankrat.transports.runtime import ApplicationServices
from rankrat.transports.seo_contracts import (
    BingContentSubmissionInput,
    ClarityInsightsInput,
    CloudflareAnalyticsInput,
    CloudflareCacheTemplateInput,
    CloudflarePurgeInput,
    ContentOpportunityInput,
    CruxHistoryInput,
    EdgeRedirectDeleteInput,
    EdgeRedirectListInput,
    EdgeRedirectUpsertInput,
    GtmAccountInput,
    GtmContainerCreateInput,
    GtmContainerDeleteInput,
    GtmContainerInput,
    GtmEntityCreateInput,
    GtmEntityDeleteInput,
    GtmEntityInput,
    GtmEntityUpdateInput,
    GtmVersionCreateInput,
    GtmVersionPublishInput,
    GtmWorkspaceCreateInput,
    GtmWorkspaceDeleteInput,
    GtmWorkspaceInput,
    InternalLinkInput,
    IssueEventsInput,
    IssueStatusInput,
    MonitorCreateInput,
    MonitorHistoryInput,
    MonitorIdentityInput,
    MonitorIssuesInput,
    MonitorListInput,
    MonitorUpdateInput,
    OrphanPageInput,
    StrictInput,
)

SEO_TOOL_NOT_HANDLED = object()

_READ_TOOL_MODELS: dict[str, type[StrictInput]] = {
    CLARITY_INSIGHTS_OPERATION: ClarityInsightsInput,
    EDGE_REDIRECTS_LIST_OPERATION: EdgeRedirectListInput,
    GTM_ACCOUNTS_LIST_OPERATION: GtmAccountInput,
    GTM_CONTAINERS_LIST_OPERATION: GtmContainerInput,
    GTM_WORKSPACES_LIST_OPERATION: GtmWorkspaceInput,
    GTM_ENTITIES_LIST_OPERATION: GtmEntityInput,
    INTERNAL_LINK_GRAPH_OPERATION: InternalLinkInput,
    ORPHAN_PAGE_REPORT_OPERATION: OrphanPageInput,
    INTERNAL_LINK_OPPORTUNITIES_OPERATION: InternalLinkInput,
    CRUX_HISTORY_OPERATION: CruxHistoryInput,
    CLOUDFLARE_ANALYTICS_OPERATION: CloudflareAnalyticsInput,
    CONTENT_OPPORTUNITIES_OPERATION: ContentOpportunityInput,
    MONITORS_LIST_OPERATION: MonitorListInput,
    MONITOR_SNAPSHOTS_OPERATION: MonitorHistoryInput,
    MONITOR_ISSUES_OPERATION: MonitorIssuesInput,
    ISSUE_EVENTS_OPERATION: IssueEventsInput,
}
_WRITE_TOOL_MODELS: dict[str, type[StrictInput]] = {
    BING_CONTENT_SUBMISSION_OPERATION: BingContentSubmissionInput,
    EDGE_REDIRECT_UPSERT_OPERATION: EdgeRedirectUpsertInput,
    EDGE_REDIRECT_DELETE_OPERATION: EdgeRedirectDeleteInput,
    GTM_CONTAINERS_CREATE_OPERATION: GtmContainerCreateInput,
    GTM_CONTAINERS_DELETE_OPERATION: GtmContainerDeleteInput,
    GTM_WORKSPACES_CREATE_OPERATION: GtmWorkspaceCreateInput,
    GTM_WORKSPACES_DELETE_OPERATION: GtmWorkspaceDeleteInput,
    GTM_ENTITIES_CREATE_OPERATION: GtmEntityCreateInput,
    GTM_ENTITIES_UPDATE_OPERATION: GtmEntityUpdateInput,
    GTM_ENTITIES_DELETE_OPERATION: GtmEntityDeleteInput,
    GTM_WORKSPACE_VERSION_CREATE_OPERATION: GtmVersionCreateInput,
    GTM_VERSION_PUBLISH_OPERATION: GtmVersionPublishInput,
    MONITORS_CREATE_OPERATION: MonitorCreateInput,
    MONITOR_UPDATE_OPERATION: MonitorUpdateInput,
    MONITOR_DELETE_OPERATION: MonitorIdentityInput,
    MONITOR_RUN_OPERATION: MonitorIdentityInput,
    ISSUE_STATUS_OPERATION: IssueStatusInput,
    CLOUDFLARE_CACHE_PURGE_OPERATION: CloudflarePurgeInput,
    CLOUDFLARE_CACHE_TEMPLATE_OPERATION: CloudflareCacheTemplateInput,
}
_TOOL_DESCRIPTIONS = {
    CLARITY_INSIGHTS_OPERATION: (
        "Read the documented 1-3 day Microsoft Clarity live-insights report."
    ),
    EDGE_REDIRECTS_LIST_OPERATION: "List only Rankrat-managed provider-neutral edge redirects.",
    GTM_ACCOUNTS_LIST_OPERATION: (
        "List Google Tag Manager accounts available to the configured OAuth account."
    ),
    GTM_CONTAINERS_LIST_OPERATION: "List containers in one Google Tag Manager account.",
    GTM_WORKSPACES_LIST_OPERATION: "List workspaces in one Google Tag Manager container.",
    GTM_ENTITIES_LIST_OPERATION: "List tags, triggers, or variables in one GTM workspace.",
    BING_CONTENT_SUBMISSION_OPERATION: (
        "Fetch and submit one configured HTML page to Bing Webmaster."
    ),
    EDGE_REDIRECT_UPSERT_OPERATION: "Create or update one provider-neutral edge redirect.",
    EDGE_REDIRECT_DELETE_OPERATION: "Delete one previously listed Rankrat-managed edge redirect.",
    GTM_CONTAINERS_CREATE_OPERATION: "Create one Google Tag Manager container.",
    GTM_CONTAINERS_DELETE_OPERATION: "Delete one Google Tag Manager container.",
    GTM_WORKSPACES_CREATE_OPERATION: "Create one Google Tag Manager workspace.",
    GTM_WORKSPACES_DELETE_OPERATION: "Delete one Google Tag Manager workspace.",
    GTM_ENTITIES_CREATE_OPERATION: "Create one typed GTM tag, trigger, or variable.",
    GTM_ENTITIES_UPDATE_OPERATION: "Update one typed GTM tag, trigger, or variable.",
    GTM_ENTITIES_DELETE_OPERATION: "Delete one typed GTM tag, trigger, or variable.",
    GTM_WORKSPACE_VERSION_CREATE_OPERATION: "Create one GTM container version from a workspace.",
    GTM_VERSION_PUBLISH_OPERATION: "Publish one GTM container version.",
    INTERNAL_LINK_GRAPH_OPERATION: "Build a bounded internal-link graph from one configured site.",
    ORPHAN_PAGE_REPORT_OPERATION: "Join crawl, Search Console, and GA4 evidence for orphan pages.",
    INTERNAL_LINK_OPPORTUNITIES_OPERATION: (
        "Find deterministic missing internal-link opportunities."
    ),
    CRUX_HISTORY_OPERATION: "Read bounded Chrome UX Report history for one configured target.",
    CLOUDFLARE_ANALYTICS_OPERATION: "Read bounded Cloudflare traffic and cache aggregates.",
    CONTENT_OPPORTUNITIES_OPERATION: (
        "Join search, analytics, and crawl evidence into opportunities."
    ),
    MONITORS_LIST_OPERATION: "List persistent monitors for one configured site.",
    MONITOR_SNAPSHOTS_OPERATION: "List immutable snapshots for one scoped monitor.",
    MONITOR_ISSUES_OPERATION: "List lifecycle issues for one scoped monitor.",
    ISSUE_EVENTS_OPERATION: "List immutable lifecycle events for one scoped issue.",
    MONITORS_CREATE_OPERATION: "Create one persistent site-audit monitor.",
    MONITOR_UPDATE_OPERATION: "Update one scoped monitor schedule and enabled state.",
    MONITOR_DELETE_OPERATION: "Delete one scoped monitor and its local history.",
    MONITOR_RUN_OPERATION: "Run one scoped monitor immediately and persist its result.",
    ISSUE_STATUS_OPERATION: "Set the explicit lifecycle status of one scoped issue.",
    CLOUDFLARE_CACHE_PURGE_OPERATION: "Purge exact configured-site URLs from Cloudflare cache.",
    CLOUDFLARE_CACHE_TEMPLATE_OPERATION: "Apply one named, bounded Cloudflare cache template.",
}
_DESTRUCTIVE_TOOLS = frozenset(
    {
        MONITOR_DELETE_OPERATION,
        CLOUDFLARE_CACHE_PURGE_OPERATION,
        CLOUDFLARE_CACHE_TEMPLATE_OPERATION,
        EDGE_REDIRECT_DELETE_OPERATION,
        GTM_CONTAINERS_DELETE_OPERATION,
        GTM_WORKSPACES_DELETE_OPERATION,
        GTM_ENTITIES_DELETE_OPERATION,
    }
)
_IDEMPOTENT_WRITE_TOOLS = frozenset(
    {
        MONITOR_UPDATE_OPERATION,
        ISSUE_STATUS_OPERATION,
        CLOUDFLARE_CACHE_TEMPLATE_OPERATION,
        EDGE_REDIRECT_UPSERT_OPERATION,
        GTM_ENTITIES_UPDATE_OPERATION,
    }
)


def seo_mcp_tools(writes_enabled: bool) -> list[types.Tool]:
    """Return tools visible under the current process-level write policy."""
    tools = [_tool(name, model, True) for name, model in _READ_TOOL_MODELS.items()]
    if writes_enabled:
        tools.extend(_tool(name, model, False) for name, model in _WRITE_TOOL_MODELS.items())
    return tools


async def dispatch_seo_tool(
    services: ApplicationServices,
    name: str,
    raw_arguments: dict[str, Any],
) -> object:
    """Dispatch one known tool or return the identity sentinel for legacy dispatch."""
    if name not in _READ_TOOL_MODELS and name not in _WRITE_TOOL_MODELS:
        return SEO_TOOL_NOT_HANDLED
    if name in _WRITE_TOOL_MODELS and not services.writes_enabled:
        return SEO_TOOL_NOT_HANDLED
    if name == INTERNAL_LINK_GRAPH_OPERATION:
        graph_arguments = InternalLinkInput.model_validate(raw_arguments)
        return await services.internal_links.graph(_internal_link_request(graph_arguments))
    if name == ORPHAN_PAGE_REPORT_OPERATION:
        orphan_arguments = OrphanPageInput.model_validate(raw_arguments)
        return await services.internal_links.orphans(
            OrphanPageRequest(
                crawl_account_id=orphan_arguments.crawl_account_id,
                crawl_site_url=orphan_arguments.crawl_site_url,
                search_console_account_id=orphan_arguments.search_console_account_id,
                search_console_site_url=orphan_arguments.search_console_site_url,
                ga4_account_id=orphan_arguments.ga4_account_id,
                ga4_property_id=orphan_arguments.ga4_property_id,
                start_date=orphan_arguments.start_date,
                end_date=orphan_arguments.end_date,
                max_pages=orphan_arguments.max_pages,
                max_depth=orphan_arguments.max_depth,
            )
        )
    if name == INTERNAL_LINK_OPPORTUNITIES_OPERATION:
        opportunity_arguments = InternalLinkInput.model_validate(raw_arguments)
        return await services.internal_links.opportunities(
            _internal_link_request(opportunity_arguments)
        )
    if name == CRUX_HISTORY_OPERATION:
        crux_arguments = CruxHistoryInput.model_validate(raw_arguments)
        return await services.crux.history(
            CruxHistoryRequest(
                crux_arguments.account_id,
                crux_arguments.site_url,
                crux_arguments.target,
                crux_arguments.target_kind,
                crux_arguments.form_factor,
                crux_arguments.metrics,
                crux_arguments.collection_period_count,
                crux_arguments.timeout_seconds,
            )
        )
    if name == CLOUDFLARE_ANALYTICS_OPERATION:
        cloudflare_arguments = CloudflareAnalyticsInput.model_validate(raw_arguments)
        return await services.cloudflare_performance.analytics(
            CloudflareAnalyticsRequest(
                cloudflare_arguments.account_id,
                cloudflare_arguments.zone_id,
                cloudflare_arguments.start,
                cloudflare_arguments.end,
                cloudflare_arguments.limit,
                cloudflare_arguments.timeout_seconds,
            )
        )
    if name == CONTENT_OPPORTUNITIES_OPERATION:
        content_arguments = ContentOpportunityInput.model_validate(raw_arguments)
        return await services.content_opportunities.report(
            ContentOpportunityRequest(
                google_account_id=content_arguments.google_account_id,
                search_console_site_url=content_arguments.search_console_site_url,
                bing_account_id=content_arguments.bing_account_id,
                bing_site_url=content_arguments.bing_site_url,
                ga4_account_id=content_arguments.ga4_account_id,
                ga4_property_id=content_arguments.ga4_property_id,
                crawl_account_id=content_arguments.crawl_account_id,
                crawl_site_url=content_arguments.crawl_site_url,
                start_date=content_arguments.start_date,
                end_date=content_arguments.end_date,
                limit=content_arguments.limit,
            )
        )
    if name == CLARITY_INSIGHTS_OPERATION:
        clarity_arguments = ClarityInsightsInput.model_validate(raw_arguments)
        return await services.clarity.live_insights(
            ClarityInsightsRequest(
                clarity_arguments.account_id,
                clarity_arguments.num_days,
                clarity_arguments.dimensions,
                clarity_arguments.timeout_seconds,
            )
        )
    if name == EDGE_REDIRECTS_LIST_OPERATION:
        redirect_arguments = EdgeRedirectListInput.model_validate(raw_arguments)
        if services.edge_redirects is None:
            return SEO_TOOL_NOT_HANDLED
        return await services.edge_redirects.list(
            EdgeRedirectListRequest(
                redirect_arguments.account_id,
                redirect_arguments.site_url,
                redirect_arguments.timeout_seconds,
            )
        )
    if name == GTM_ACCOUNTS_LIST_OPERATION:
        gtm_arguments = GtmAccountInput.model_validate(raw_arguments)
        return await services.google_tag_manager.list_accounts(
            gtm_arguments.account_id,
            gtm_arguments.timeout_seconds,
        )
    if name == GTM_CONTAINERS_LIST_OPERATION:
        gtm_arguments = GtmContainerInput.model_validate(raw_arguments)
        return await services.google_tag_manager.list_containers(
            GtmContainerRequest(
                gtm_arguments.account_id,
                gtm_arguments.gtm_account_id,
                gtm_arguments.timeout_seconds,
            )
        )
    if name == GTM_WORKSPACES_LIST_OPERATION:
        gtm_arguments = GtmWorkspaceInput.model_validate(raw_arguments)
        return await services.google_tag_manager.list_workspaces(
            GtmWorkspaceRequest(
                gtm_arguments.account_id,
                gtm_arguments.gtm_account_id,
                gtm_arguments.container_id,
                gtm_arguments.timeout_seconds,
            )
        )
    if name == GTM_ENTITIES_LIST_OPERATION:
        gtm_arguments = GtmEntityInput.model_validate(raw_arguments)
        return await services.google_tag_manager.list_entities(
            GtmEntityRequest(
                gtm_arguments.account_id,
                gtm_arguments.gtm_account_id,
                gtm_arguments.container_id,
                gtm_arguments.timeout_seconds,
                gtm_arguments.workspace_id,
                gtm_arguments.kind,
            )
        )
    return await _dispatch_state_or_write(services, name, raw_arguments)


async def _dispatch_state_or_write(
    services: ApplicationServices,
    name: str,
    raw_arguments: dict[str, Any],
) -> object:
    if name == BING_CONTENT_SUBMISSION_OPERATION:
        bing_content_arguments = BingContentSubmissionInput.model_validate(raw_arguments)
        if services.bing_content is None:
            return SEO_TOOL_NOT_HANDLED
        return await services.bing_content.submit(
            BingContentSubmissionRequest(
                bing_content_arguments.account_id,
                bing_content_arguments.site_url,
                bing_content_arguments.page_url,
                bing_content_arguments.dynamic_serving,
                bing_content_arguments.timeout_seconds,
            )
        )
    if name == EDGE_REDIRECT_UPSERT_OPERATION:
        redirect_upsert_arguments = EdgeRedirectUpsertInput.model_validate(raw_arguments)
        if services.edge_redirects is None:
            return SEO_TOOL_NOT_HANDLED
        return await services.edge_redirects.upsert(
            EdgeRedirectUpsertRequest(
                redirect_upsert_arguments.account_id,
                redirect_upsert_arguments.site_url,
                redirect_upsert_arguments.timeout_seconds,
                redirect_upsert_arguments.source_path,
                redirect_upsert_arguments.target_url,
                redirect_upsert_arguments.status_code,
                redirect_upsert_arguments.preserve_query_string,
            )
        )
    if name == EDGE_REDIRECT_DELETE_OPERATION:
        redirect_delete_arguments = EdgeRedirectDeleteInput.model_validate(raw_arguments)
        if services.edge_redirects is None:
            return SEO_TOOL_NOT_HANDLED
        await services.edge_redirects.delete(
            EdgeRedirectDeleteRequest(
                redirect_delete_arguments.account_id,
                redirect_delete_arguments.site_url,
                redirect_delete_arguments.timeout_seconds,
                redirect_delete_arguments.rule_id,
            )
        )
        return {"deleted": True, "rule_id": redirect_delete_arguments.rule_id}
    if name == GTM_CONTAINERS_CREATE_OPERATION:
        container_create_arguments = GtmContainerCreateInput.model_validate(raw_arguments)
        return await services.google_tag_manager.create_container(
            GtmContainerCreateRequest(
                container_create_arguments.account_id,
                container_create_arguments.gtm_account_id,
                container_create_arguments.timeout_seconds,
                container_create_arguments.name,
                container_create_arguments.usage_contexts,
            )
        )
    if name == GTM_CONTAINERS_DELETE_OPERATION:
        container_delete_arguments = GtmContainerDeleteInput.model_validate(raw_arguments)
        await services.google_tag_manager.delete_container(
            GtmContainerRequest(
                container_delete_arguments.account_id,
                container_delete_arguments.gtm_account_id,
                container_delete_arguments.timeout_seconds,
            ),
            container_delete_arguments.container_id,
        )
        return {"deleted": True, "container_id": container_delete_arguments.container_id}
    if name == GTM_WORKSPACES_CREATE_OPERATION:
        workspace_create_arguments = GtmWorkspaceCreateInput.model_validate(raw_arguments)
        return await services.google_tag_manager.create_workspace(
            GtmWorkspaceCreateRequest(
                workspace_create_arguments.account_id,
                workspace_create_arguments.gtm_account_id,
                workspace_create_arguments.container_id,
                workspace_create_arguments.timeout_seconds,
                workspace_create_arguments.name,
                workspace_create_arguments.description,
            )
        )
    if name == GTM_WORKSPACES_DELETE_OPERATION:
        workspace_delete_arguments = GtmWorkspaceDeleteInput.model_validate(raw_arguments)
        await services.google_tag_manager.delete_workspace(
            GtmWorkspaceRequest(
                workspace_delete_arguments.account_id,
                workspace_delete_arguments.gtm_account_id,
                workspace_delete_arguments.container_id,
                workspace_delete_arguments.timeout_seconds,
            ),
            workspace_delete_arguments.workspace_id,
        )
        return {"deleted": True, "workspace_id": workspace_delete_arguments.workspace_id}
    if name == GTM_ENTITIES_CREATE_OPERATION:
        entity_create_arguments = GtmEntityCreateInput.model_validate(raw_arguments)
        return await services.google_tag_manager.create_entity(
            GtmEntityCreateRequest(
                entity_create_arguments.account_id,
                entity_create_arguments.gtm_account_id,
                entity_create_arguments.container_id,
                entity_create_arguments.timeout_seconds,
                entity_create_arguments.workspace_id,
                entity_create_arguments.kind,
                entity_create_arguments.definition,
            )
        )
    if name == GTM_ENTITIES_UPDATE_OPERATION:
        entity_update_arguments = GtmEntityUpdateInput.model_validate(raw_arguments)
        return await services.google_tag_manager.update_entity(
            GtmEntityUpdateRequest(
                entity_update_arguments.account_id,
                entity_update_arguments.gtm_account_id,
                entity_update_arguments.container_id,
                entity_update_arguments.timeout_seconds,
                entity_update_arguments.workspace_id,
                entity_update_arguments.kind,
                entity_update_arguments.definition,
                entity_update_arguments.entity_id,
            )
        )
    if name == GTM_ENTITIES_DELETE_OPERATION:
        entity_delete_arguments = GtmEntityDeleteInput.model_validate(raw_arguments)
        await services.google_tag_manager.delete_entity(
            GtmEntityRequest(
                entity_delete_arguments.account_id,
                entity_delete_arguments.gtm_account_id,
                entity_delete_arguments.container_id,
                entity_delete_arguments.timeout_seconds,
                entity_delete_arguments.workspace_id,
                entity_delete_arguments.kind,
            ),
            entity_delete_arguments.entity_id,
        )
        return {"deleted": True, "entity_id": entity_delete_arguments.entity_id}
    if name == GTM_WORKSPACE_VERSION_CREATE_OPERATION:
        version_create_arguments = GtmVersionCreateInput.model_validate(raw_arguments)
        return await services.google_tag_manager.create_version(
            GtmVersionCreateRequest(
                version_create_arguments.account_id,
                version_create_arguments.gtm_account_id,
                version_create_arguments.container_id,
                version_create_arguments.timeout_seconds,
                version_create_arguments.workspace_id,
                version_create_arguments.name,
                version_create_arguments.notes,
            )
        )
    if name == GTM_VERSION_PUBLISH_OPERATION:
        version_publish_arguments = GtmVersionPublishInput.model_validate(raw_arguments)
        return await services.google_tag_manager.publish_version(
            GtmVersionPublishRequest(
                version_publish_arguments.account_id,
                version_publish_arguments.gtm_account_id,
                version_publish_arguments.container_id,
                version_publish_arguments.timeout_seconds,
                version_publish_arguments.version_id,
            )
        )
    if name == MONITORS_LIST_OPERATION:
        list_arguments = MonitorListInput.model_validate(raw_arguments)
        return services.monitoring.list_monitors(
            MonitorListRequest(
                list_arguments.limit,
                list_arguments.offset,
                list_arguments.account_id,
                list_arguments.site_url,
            )
        )
    if name == MONITOR_SNAPSHOTS_OPERATION:
        snapshot_arguments = MonitorHistoryInput.model_validate(raw_arguments)
        return services.monitoring.list_snapshots(
            MonitorHistoryRequest(
                snapshot_arguments.limit,
                snapshot_arguments.offset,
                str(snapshot_arguments.monitor_id),
                snapshot_arguments.account_id,
                snapshot_arguments.site_url,
            )
        )
    if name == MONITOR_ISSUES_OPERATION:
        issue_list_arguments = MonitorIssuesInput.model_validate(raw_arguments)
        return services.monitoring.list_issues(
            MonitorIssueListRequest(
                issue_list_arguments.limit,
                issue_list_arguments.offset,
                str(issue_list_arguments.monitor_id),
                issue_list_arguments.account_id,
                issue_list_arguments.site_url,
                issue_list_arguments.status,
            )
        )
    if name == ISSUE_EVENTS_OPERATION:
        event_arguments = IssueEventsInput.model_validate(raw_arguments)
        return services.monitoring.list_issue_events(
            IssueHistoryRequest(
                event_arguments.limit,
                event_arguments.offset,
                str(event_arguments.issue_id),
                str(event_arguments.monitor_id),
                event_arguments.account_id,
                event_arguments.site_url,
            )
        )
    if name == MONITORS_CREATE_OPERATION:
        create_arguments = MonitorCreateInput.model_validate(raw_arguments)
        return services.monitoring.create_monitor(
            MonitorCreateRequest(
                create_arguments.name,
                create_arguments.account_id,
                create_arguments.site_url,
                create_arguments.interval_seconds,
            )
        )
    if name == MONITOR_UPDATE_OPERATION:
        update_arguments = MonitorUpdateInput.model_validate(raw_arguments)
        return services.monitoring.update_monitor(
            MonitorUpdateRequest(
                str(update_arguments.monitor_id),
                update_arguments.account_id,
                update_arguments.site_url,
                update_arguments.name,
                update_arguments.interval_seconds,
                update_arguments.enabled,
            )
        )
    if name == MONITOR_DELETE_OPERATION:
        delete_arguments = MonitorIdentityInput.model_validate(raw_arguments)
        services.monitoring.delete_monitor(_monitor_history(delete_arguments))
        return {"deleted": True, "monitor_id": str(delete_arguments.monitor_id)}
    if name == MONITOR_RUN_OPERATION:
        run_arguments = MonitorIdentityInput.model_validate(raw_arguments)
        return await services.monitoring.run_monitor(_monitor_history(run_arguments))
    if name == ISSUE_STATUS_OPERATION:
        status_arguments = IssueStatusInput.model_validate(raw_arguments)
        return services.monitoring.set_issue_status(
            IssueStatusRequest(
                str(status_arguments.issue_id),
                str(status_arguments.monitor_id),
                status_arguments.account_id,
                status_arguments.site_url,
                status_arguments.status,
            )
        )
    if name == CLOUDFLARE_CACHE_PURGE_OPERATION:
        purge_arguments = CloudflarePurgeInput.model_validate(raw_arguments)
        return await services.cloudflare_performance.purge(
            CloudflarePurgeRequest(
                purge_arguments.account_id,
                purge_arguments.zone_id,
                purge_arguments.site_url,
                purge_arguments.urls,
                purge_arguments.timeout_seconds,
            )
        )
    if name == CLOUDFLARE_CACHE_TEMPLATE_OPERATION:
        template_arguments = CloudflareCacheTemplateInput.model_validate(raw_arguments)
        return await services.cloudflare_performance.apply_cache_template(
            CloudflareCacheTemplateRequest(
                template_arguments.account_id,
                template_arguments.zone_id,
                template_arguments.template,
                template_arguments.timeout_seconds,
            )
        )
    return SEO_TOOL_NOT_HANDLED


def _tool(name: str, model: type[BaseModel], read_only: bool) -> types.Tool:
    return types.Tool(
        name=name,
        description=_TOOL_DESCRIPTIONS[name],
        inputSchema=model.model_json_schema(),
        annotations=types.ToolAnnotations(
            readOnlyHint=read_only,
            destructiveHint=name in _DESTRUCTIVE_TOOLS,
            idempotentHint=read_only or name in _IDEMPOTENT_WRITE_TOOLS,
            openWorldHint=name
            not in {
                MONITORS_LIST_OPERATION,
                MONITOR_SNAPSHOTS_OPERATION,
                MONITOR_ISSUES_OPERATION,
                ISSUE_EVENTS_OPERATION,
            },
        ),
    )


def _internal_link_request(arguments: InternalLinkInput) -> InternalLinkRequest:
    return InternalLinkRequest(
        arguments.account_id,
        arguments.site_url,
        arguments.max_pages,
        arguments.max_depth,
        arguments.opportunity_limit,
    )


def _monitor_history(arguments: MonitorIdentityInput) -> MonitorHistoryRequest:
    return MonitorHistoryRequest(
        monitor_id=str(arguments.monitor_id),
        account_id=arguments.account_id,
        site_url=arguments.site_url,
    )
