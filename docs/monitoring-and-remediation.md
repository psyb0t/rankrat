# Monitoring and remediation

You choose whether the process is trusted for writes at startup. In read-only
mode, write tools and REST routes are absent from discovery. In writable mode,
configured account credentials authorize their reachable resources; fixed
provider origins, request limits, URL containment, upstream permissions, and
HTTP auth still apply.

## Contents

- [Enable ordinary writes](#enable-ordinary-writes)
- [Persistent monitors](#persistent-monitors)
- [Scheduler behavior](#scheduler-behavior)
- [State and backup](#state-and-backup)
- [Google writes](#google-writes)
- [Bing writes](#bing-writes)
- [IndexNow](#indexnow)
- [Discovery remediation](#discovery-remediation)
- [Ownership and onboarding writes](#ownership-and-onboarding-writes)
- [Cloudflare cache writes](#cloudflare-cache-writes)
- [Write checklist](#write-checklist)

## Enable ordinary writes

```sh
RANKRAT_READ_ONLY=false rankrat          # writable stdio MCP
RANKRAT_READ_ONLY=false rankrat http     # writable REST + HTTP MCP
RANKRAT_READ_ONLY=false rankrat http -d  # persistent restartable scheduler
```

Writable mode includes site onboarding; read-only mode omits it.

## Persistent monitors

Monitors schedule the deterministic bounded `site_audit` workflow.

Read operations:

| MCP tool | Purpose |
| --- | --- |
| `monitors_list` | Paginated monitors for one configured site |
| `monitor_snapshots_list` | Immutable audit snapshots |
| `monitor_issues_list` | Current/historical lifecycle issues |
| `issue_events_list` | Immutable events for one issue |

Writable operations:

| MCP tool | Purpose |
| --- | --- |
| `monitor_create` | Create one named interval schedule |
| `monitor_update` | Change name, interval, or enabled state |
| `monitor_run` | Run immediately and persist results |
| `monitor_delete` | Delete one monitor and its local history |
| `issue_status_update` | Explicitly acknowledge, reopen, or resolve an issue |

The REST equivalents live under `/v1/monitors` and `/v1/issues`.

## Scheduler behavior

The scheduler runs only in the long-lived HTTP process. At each configured wake
interval it:

1. claims due enabled monitors;
2. renews the claim while the bounded crawl runs;
3. persists an immutable snapshot;
4. opens or refreshes matching issues;
5. resolves system-managed issues that disappear;
6. applies snapshot/event retention.

Stdio supports explicit monitor management and `monitor_run`, but a stdio child
cannot perform future due work after its caller exits.

Use `rankrat http -d` for an unattended scheduler. Its Compose services use
`restart: unless-stopped`, while an attached `rankrat http` exits with the
foreground Compose process.

Rankrat sends no email, webhook, or pager notification. Agents poll issue/event
tools and decide how to notify. The built-in scheduler monitors site-audit
findings, not every backlink or provider-indexing metric.

## State and backup

State uses SQLite at `RANKRAT_STATE_DATABASE`. The wrapper maps owner-only
`state/`; Compose uses a named volume. Empty database path disables persistence
and monitor calls return `UNAVAILABLE`.

Back up with SQLite's online-backup mechanism or while Rankrat is stopped.
Copying only the live main file can omit WAL state. Deleting a monitor cascades
only its local Rankrat history; it does not delete provider data.

## Google writes

| Tool | Behavior |
| --- | --- |
| `google_site_submit` | Add or delete one Search Console property reachable through the account |
| `google_sitemap_submit` | Submit or delete one sitemap beneath a selected property |
| `google_indexing_submit` | Publish one eligible URL notification |
| `google_indexing_batch_submit` | Publish a bounded eligible multipart batch |
| `google_analytics_account_rename` | Rename one discovery-authorized account |
| `google_analytics_property_rename` | Rename one account-visible property |

Provider acceptance is asynchronous. A successful sitemap submit means Google
accepted the API request, not that it fetched or processed the sitemap. Poll
`google_sitemap_get`/`google_sitemaps_list` and inspect warnings/errors.

The Indexing API applies only to Google's eligible structured-data content. It
is not a general "force index" API. Rankrat validates supported eligibility
before publishing and exposes notification metadata afterward, but Google still
decides crawl/index behavior.

GA4 renames change display names only. Numeric IDs and report boundaries stay
the same. Rankrat does not expose Analytics deletion.

## Bing writes

| Tool | Behavior |
| --- | --- |
| `bing_url_submit` | Submit a child-URL batch for one selected site |
| `bing_sitemap_submit` | Submit or delete one sitemap for one selected site |
| `bing_site_submit` | Add or delete one account-visible site |

Check `bing_url_submission_quota` before large submissions. Site/sitemap
deletion is destructive and remains constrained to exact configured resources.
Acceptance does not guarantee crawl or ranking.

## IndexNow

`indexnow_submit` sends bounded changed URLs with the target's configured key
and public key location. It is a notification protocol: participating engines
share accepted notifications but independently decide crawl/index timing.

Live-test submission requires two independent opt-ins:

```sh
RANKRAT_READ_ONLY=false \
RANKRAT_RUN_LIVE_INDEXNOW_SUBMISSION=true \
make test-live-indexnow
```

Use a harmless, already-public URL. General setup/readiness never submits.

## Discovery remediation

`site_remediation_apply` performs a finite sequence for one configured site:

- resubmit one bounded sitemap to Google;
- resubmit it to Bing;
- submit bounded changed URLs to Bing.

It does not rewrite pages, robots, sitemap XML, CMS content, or source code.
Each provider write is sequential and not transactional. If a later stage
fails, earlier accepted writes remain accepted. Check returned status, fix the
failing provider, then retry the idempotent workflow.

## Ownership and onboarding writes

- `site_ownership_verify` creates only provider-issued DNS proofs through a
  configured DNS adapter and redeems propagated ownership.
- `site_onboarding_submit` creates or reuses GA4/Search Console/Bing resources
  in writable mode and records the discovered inventory.

Read [Ownership and onboarding](ownership-and-onboarding.md) for DNS propagation,
GA4 account limits, and partial-failure handling.

## Cloudflare cache writes

`cloudflare_cache_purge` purges exact URLs within a configured site. Rankrat
does not expose a whole-zone purge.

`cloudflare_cache_template_apply` accepts only:

- `cache_static_assets`;
- `bypass_html`.

It finds one Rankrat-marked rule, rejects ambiguous duplicate markers, and
creates or patches only that rule through Cloudflare's per-rule API. It does not
replace an entire ruleset and preserves unrelated operator rules. Applying an
already matching template is idempotent.

Template mutations are serialized per zone inside one Rankrat process. That
prevents concurrent callers in that process from both creating the first rule;
it is not a distributed lock across multiple Rankrat deployments.

## Write checklist

Before enabling writes:

1. Confirm every configured credential belongs to the intended provider
   account and has the intended account-wide permissions.
2. Give provider tokens only the permissions in
   [Providers and credentials](providers.md).
3. Keep HTTP on loopback/private networking with bearer auth.
4. Call read tools first to confirm current state and quotas.
5. Understand whether the operation is idempotent, asynchronous, or destructive.
6. Poll provider status after accepted sitemap, ownership, indexing, or DNS
   operations.
7. Back up monitoring state and the boundary before onboarding.

See [Security](security.md) for the complete production checklist.
