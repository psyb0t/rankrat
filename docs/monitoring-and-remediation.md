# Monitoring and remediation

Persistent monitors, issue history, and the provider-write operations that fix what they find — sitemap and URL resubmission, IndexNow, exact Cloudflare purges, finite cache templates, and managed edge redirects.

You decide at startup whether the process is trusted to write. Read-only mode
hides every write tool and REST route from discovery. Writable mode lets the
configured account credentials touch what they can reach — but the fixed provider
origins, request limits, URL containment, upstream permissions, and HTTP auth are
all still in force.

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
- [Tag, redirect, and content writes](#tag-redirect-and-content-writes)
- [Cloudflare cache writes](#cloudflare-cache-writes)
- [Write checklist](#write-checklist)

## Enable ordinary writes

```sh
RANKRAT_READ_ONLY=false rankrat          # writable stdio MCP
RANKRAT_READ_ONLY=false rankrat http     # writable REST + HTTP MCP
RANKRAT_READ_ONLY=false rankrat http -d  # persistent restartable scheduler
```

Writable mode carries site onboarding; read-only mode leaves it out.

## Persistent monitors

A monitor schedules the deterministic, bounded `site_audit` workflow — nothing
looser.

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

The scheduler only runs inside the long-lived HTTP process. At each configured
wake interval it:

1. claims due enabled monitors;
2. renews the claim while the bounded crawl runs;
3. persists an immutable snapshot;
4. opens or refreshes matching issues;
5. resolves system-managed issues that have disappeared;
6. applies snapshot/event retention.

Stdio still does explicit monitor management and `monitor_run`, but a stdio child
can't do future due work after its caller exits — nobody's home to fire it.

Use `rankrat http -d` for an unattended scheduler. Its Compose services run
`restart: unless-stopped`; an attached `rankrat http` dies with the foreground
Compose process.

Rankrat sends no email, no webhook, no pager — none of it. Agents poll the
issue/event tools and decide how to shout. And the scheduler watches site-audit
findings, not every backlink or provider-indexing metric.

## State and backup

State is SQLite at `RANKRAT_STATE_DATABASE`. The wrapper maps owner-only
`state/`; Compose uses a named volume. An empty database path disables
persistence, and monitor calls then return `UNAVAILABLE`.

Back up through SQLite's online-backup mechanism, or while Rankrat is stopped.
Copy the live main file alone and you can miss WAL state. Deleting a monitor
cascades only its local Rankrat history — it does not delete provider data.

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
took the API request — not that it fetched or processed the sitemap. Poll
`google_sitemap_get` / `google_sitemaps_list` and read the warnings and errors.

The Indexing API only covers Google's eligible structured-data content. It is
not a "force index" button. Rankrat checks supported eligibility before
publishing and hands back the notification metadata afterward, but Google still
decides what it crawls and indexes.

GA4 renames change the display name only. Numeric IDs and report boundaries stay
put. Analytics deletion isn't exposed.

## Bing writes

| Tool | Behavior |
| --- | --- |
| `bing_url_submit` | Submit a child-URL batch for one selected site |
| `bing_sitemap_submit` | Submit or delete one sitemap for one selected site |
| `bing_site_submit` | Add or delete one account-visible site |

Check `bing_url_submission_quota` before a big push. Site and sitemap deletion
is destructive and stays pinned to the exact configured resources. Acceptance
buys you nothing on crawl or ranking.

## IndexNow

`indexnow_submit` sends bounded changed URLs with the target's configured key
and public key location. It's a notification protocol: participating engines
share accepted notifications, then each decides crawl and index timing on its
own.

Live-test submission demands two independent opt-ins — one flag isn't enough:

```sh
RANKRAT_READ_ONLY=false \
RANKRAT_RUN_LIVE_INDEXNOW_SUBMISSION=true \
make test-live-indexnow
```

Point it at a harmless, already-public URL. Ordinary setup and readiness checks
never submit.

## Discovery remediation

`site_remediation_apply` runs one finite sequence for one configured site:

- resubmit one bounded sitemap to Google;
- resubmit it to Bing;
- submit bounded changed URLs to Bing.

It does not rewrite pages, robots, sitemap XML, CMS content, or source code — it
only re-pokes the providers. Each write is sequential and not transactional. A
later stage failing leaves the earlier accepted writes accepted. Read the
returned status, fix the provider that broke, retry — the workflow is
idempotent.

## Ownership and onboarding writes

- `site_ownership_verify` creates only provider-issued DNS proofs through a
  configured DNS adapter and redeems ownership once they propagate.
- `site_onboarding_submit` creates or reuses GA4/Search Console/Bing resources
  in writable mode and records the discovered inventory.

See [Ownership and onboarding](ownership-and-onboarding.md) for DNS propagation,
GA4 account limits, and partial-failure handling.

## Tag, redirect, and content writes

Google Tag Manager writes are typed and staged: discover an account, create or
update containers/workspaces/tags/triggers/variables, cut a workspace version,
then publish the version you chose. There is no arbitrary Google API proxy here.
Re-authorize with `rankrat auth-google` after upgrading to a release that adds a
Tag Manager scope.

`edge_redirect_upsert` and `edge_redirect_delete` use provider-neutral requests.
Cloudflare is the current adapter, and it only touches redirect rules that carry
Rankrat's ownership marker — your other redirects and rulesets are left alone.

`bing_content_submission_create` fetches the bounded public page inside Rankrat
and submits that freshly fetched HTML body to Bing. The caller can't hand it raw
content, arbitrary headers, or some other remote URL.

## Cloudflare cache writes

`cloudflare_cache_purge` purges exact URLs inside a configured site. No
whole-zone purge is exposed — that blast radius isn't yours to trigger.

`cloudflare_cache_template_apply` accepts exactly two templates:

- `cache_static_assets`;
- `bypass_html`.

It finds the one Rankrat-marked rule, refuses ambiguous duplicate markers, and
creates or patches only that rule through Cloudflare's per-rule API. It never
replaces a whole ruleset, and it preserves your unrelated rules. Applying a
template that already matches is a no-op.

Template mutations are serialized per zone within a single Rankrat process. That
stops two callers in that process from both racing to create the first rule — it
is not a distributed lock across separate Rankrat deployments.

## Write checklist

Before you enable writes:

1. Confirm every configured credential belongs to the intended provider account
   and carries the intended account-wide permissions.
2. Give provider tokens only the permissions in
   [Providers and credentials](providers.md).
3. Keep HTTP on loopback or private networking with bearer auth.
4. Call the read tools first, to confirm current state and quotas.
5. Know whether the operation is idempotent, asynchronous, or destructive.
6. Poll provider status after any accepted sitemap, ownership, indexing, or DNS
   write.
7. Back up monitoring state and the boundary before onboarding.

See [Security](security.md) for the full production checklist.
