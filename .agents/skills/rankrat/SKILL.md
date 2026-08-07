---
name: rankrat
description: Query Google Search Console, Bing Webmaster Tools, Google Analytics 4 (GA4), and PageSpeed Insights, run local Lighthouse and bounded whole-site audits, automate Google/Bing DNS ownership through a configured DNS provider adapter, apply sitemap and URL discovery remediation, and aggregate Bing backlink evidence through one self-hosted MCP server. Includes search analytics, indexing, crawl, ranking, schema, performance, audience, conversion, referring-domain, and anchor-text reports. Speaks MCP over stdio and Streamable HTTP, plus a FastAPI JSON API. Use when the user wants to inspect or improve SEO, indexing, ownership, backlinks, browser scores, or search traffic for sites they control.
homepage: https://github.com/psyb0t/rankrat
user-invocable: true
metadata:
  openclaw:
    emoji: "🐀"
    requires:
      bins: [docker]
permissions:
  network: "outbound HTTPS to configured Google Search Console, Google Analytics, Bing Webmaster Tools, PageSpeed Insights, Cloudflare, public DNS, public pages beneath configured sites, and IndexNow provider endpoints; optional Lighthouse browser traffic to explicitly requested bounded pages; inbound only on the port you bind."
  shell: "docker run invocations for the published image, or bash execution of the bundled references/rankrat.sh wrapper; no other host access is required."
  filesystem: "reads the boundary config and provider credentials. Local initialization creates an HTTP bearer secret; Google authorization writes its token record; IndexNow initialization creates or retains its local key and updates .env plus the boundary file; agent onboarding and unbounded onboarding update the one configured boundary file with exact created-resource IDs."
---

# rankrat

A self-hosted MCP server over the SEO and search-analytics APIs you already have
accounts on — Google Search Console, Bing Webmaster Tools, GA4, and PageSpeed
Insights — so an agent can read your own search data without you handing it a
browser session or a service-account key.

Install, credentials and the full environment reference:
[`references/setup.md`](references/setup.md).

## Security & safety

In normal bounded mode, the operator fixes the boundary at startup and rankrat
serves only the accounts, sites and properties listed in it. Ordinary provider
tools cannot widen that scope. The only exception is the separately gated
`site_onboarding_submit` tool: it can add the exact resources it creates when
`RANKRAT_ALLOW_AGENT_ONBOARDING=true` and the config mount passes the ownership
and mode checks described below.

It is **read-only by default** — `RANKRAT_READ_ONLY` defaults to `true`, and the
write tools are not merely rejected but absent from `tools/list` entirely, so an
agent cannot discover or call them. Setting it to `false` makes them visible;
writes still stay inside the configured boundaries and whatever the provider
account is actually permitted to do.

There is a second, wider switch. `RANKRAT_UNBOUNDED=true` (which also requires
read-only off) is a reusable trusted-caller mode for discovering or onboarding a
resource that is not in the boundary file yet. It keeps credential **accounts**
fixed but skips per-resource allow-lists. Onboarding records exact resulting
resources in the boundary file; restart without the switch to enforce them
again. The operator may enable unbounded mode again for a later onboarding
session. Treat any unbounded server as a trusted-caller setup, not a public
service.

Your provider credentials stay on the host running rankrat. Requests go to the
provider APIs over HTTPS. The optional Lighthouse companion opens only an
explicitly requested page beneath a configured PageSpeed site and receives no
provider credentials. Credentials, OAuth records and raw provider bodies are
never returned or logged. Bind Rankrat to loopback or a private network, and use
the bearer token if anything else can reach it.

## When to use

- Reading Search Console performance: queries, pages, countries, devices, dates
  — as raw rows, summaries, trends, period comparisons, or anomaly and
  traffic-drop attribution.
- Diagnosing indexing: URL inspection (single or batch), sitemap listings,
  crawl issues, crawl stats.
- Bing Webmaster Tools equivalents, plus keyword statistics, related keywords,
  ranking buckets, query/page opportunity reports and cannibalization analysis.
- GA4 reporting: realtime, content and landing-page performance, organic search
  landing pages, traffic sources, ecommerce, audience segments, user behavior,
  conversion funnels.
- PageSpeed Insights, and fetching a page's structured-data schema.
- Whole-site crawling for deterministic metadata, canonical, robots, sitemap,
  duplicate-title, link, and structured-data findings with remediation text.
- Google/Bing ownership checks and narrowly scoped verification through the
  configured DNS adapter; Cloudflare is currently supported.
- IndexNow change notifications for bounded URLs. This is a writable push
  protocol, not a reporting dashboard or an indexing guarantee.
- Bing backlink detail aggregated into referring domains and anchor summaries.
- Local Lighthouse performance, accessibility, best-practices, and SEO scores
  or category-specific failed findings when the companion worker is configured.
- Checking which providers are actually wired up (`provider_readiness`,
  `diagnostics`) before trusting a report.

## When NOT to use

- **Sites you don't control.** Everything is scoped to configured provider
  accounts and site boundaries. It is not a competitor crawler or arbitrary
  backlink scraper.
- **Changing anything in the default configuration.** Read-only mode exposes no
  write tools. A trusted writable deployment can submit URLs/sitemaps and,
  during an unbounded session, create supported provider resources for a newly
  onboarded site.
- **Realtime dashboards.** Provider APIs lag (Search Console notably so), and
  rankrat reports what they return.
- **Editing an arbitrary CMS or repository.** Audits return deterministic fixes;
  provider remediation resubmits sitemaps and URLs but does not rewrite pages.

## Usage

Both MCP transports run from the published image. Read tools have a stable
discovery surface even when their provider is not configured; ask
`provider_readiness` before interpreting an empty or unavailable result. Only
write-tool discovery changes with `RANKRAT_READ_ONLY` and
`RANKRAT_ALLOW_AGENT_ONBOARDING`.

**stdio** is the default mode, so a client that spawns its own server just runs
the image and talks to it — no port, no bridge:

```bash
docker run -i --rm --init --read-only \
  --user "$(id -u):$(id -g)" \
  --cap-drop=ALL --security-opt no-new-privileges:true \
  --pids-limit 128 --memory 512m --cpus 1 \
  --tmpfs /tmp:rw,noexec,nosuid,size=32m \
  --mount type=bind,src="$PWD/config",dst=/run/config,readonly \
  --mount type=bind,src="$PWD/secrets",dst=/run/secrets,readonly \
  --mount type=bind,src="$PWD/oauth",dst=/run/oauth \
  psyb0t/rankrat stdio
```

**Streamable HTTP** for a shared or already-running server. MCP is at `/mcp`,
and the REST API is on the same port:

```bash
docker run --rm --init --read-only \
  --user "$(id -u):$(id -g)" \
  --cap-drop=ALL --security-opt no-new-privileges:true \
  --pids-limit 128 --memory 512m --cpus 1 \
  --tmpfs /tmp:rw,noexec,nosuid,size=32m \
  -p 127.0.0.1:8080:8080 \
  -e RANKRAT_HTTP_HOST=0.0.0.0 \
  -e RANKRAT_HTTP_BEARER_SECRET_FILE=/run/secrets/rankrat/http-bearer-token \
  --mount type=bind,src="$PWD/config",dst=/run/config,readonly \
  --mount type=bind,src="$PWD/secrets",dst=/run/secrets,readonly \
  --mount type=bind,src="$PWD/oauth",dst=/run/oauth \
  psyb0t/rankrat http
```

`RANKRAT_HTTP_HOST=0.0.0.0` binds inside the container; the `-p` publishes it on
loopback only. Send `Authorization: Bearer <token>` when a bearer secret is
configured.

These examples are bounded, so config stays read-only. Google OAuth storage is
writable because token refresh may rotate and persist a refresh token; provider
secrets stay read-only. For unbounded onboarding, use the bundled wrapper or the
validated writable-config procedure in the setup reference.

The repo ships a `rankrat.sh` wrapper around exactly these invocations for
humans. The published skill bundles the same script at
[`references/rankrat.sh`](references/rankrat.sh), so it remains available when
the skill is installed without a repository checkout; agents can still invoke
the image directly.

The one-container stdio examples return `UNAVAILABLE` for Lighthouse because
Chromium is deliberately isolated in `psyb0t/rankrat-lighthouse`. Use the
published two-image commands in `references/setup.md` when local browser audits
are required. They support both stdio and Streamable HTTP while sharing only a
Unix socket; the worker receives no provider credential mounts.

Use the browser worker only for operator-controlled sites. Its documented
non-root, capability-free container needs Chromium's `--no-sandbox`; a hostile
page therefore requires a stronger outer sandbox such as gVisor or Kata. The
worker blocks private/special-address egress, while public cross-origin
subresources—and a public redirect before Rankrat rejects its final URL—remain
possible.

The browser surface is exactly `lighthouse_audit`,
`lighthouse_seo_findings`, `lighthouse_accessibility_findings`,
`lighthouse_performance_findings`, and
`lighthouse_best_practices_findings`. Every call takes `account_id`, a
configured `site_url`, a child `page_url`, and an optional timeout from 5 to 300
seconds. The REST equivalents live under `/v1/lighthouse/`.

### Finding where a site lives, and matching its tag

GA4 nests every property under an *account*, and properties routinely sit under
an unrelated one because that is whatever the dropdown defaulted to when they
were created. `google_analytics_account_inventory` lists every account the
credential can see with its properties — that is the tool for "which account is
this site under", and the answer is often surprising.

`google_analytics_data_streams` returns a configured property's streams and their
`G-` measurement IDs. Use it before telling anyone their tag is installed
correctly: a tag whose measurement ID belongs to a different property looks
perfectly installed and reports into a property nobody is reading.

`google_analytics_account_rename` and `google_analytics_property_rename` exist in
writable mode. Account names are cosmetic — the numeric ID is what boundaries,
measurement IDs and reports bind to — so renaming is safe and is the usual fix
for a misfiled property. There is no create and no delete: GA4 has no account
create API at all, and deletion is deliberately not wrapped.

### Onboarding a site

Read the `rankrat://onboarding` resource before saying anything about onboarding,
or call the `onboarding_guide` tool if the client does not support resources —
pass `site_url` to get the methods that site's property form actually accepts.
Both are read-only and present on every server, including read-only ones, and
`POST /v1/onboarding-guides` serves the same document over REST.

If the user has no GA4 account yet, do not attempt to create one and do not
guess the steps. No tool can create a GA4 account — the Admin API has no
`accounts.create`, and the flow ends at a Terms of Service page. The guide's
`manual_provisioning` block carries the start URL and the exact ordered clicks;
relay those, then ask the user for the numeric account ID, which
`google_analytics_account_inventory` can also read back once it exists.

Creating provider resources and proving ownership are separate. When a DNS
provider account is configured, call `site_ownership_verify` after onboarding,
then poll `site_ownership_check` until `complete` is true. Cloudflare is the
currently shipped DNS adapter; without a supported adapter, the guide lists the
manual methods accepted by the property form. Rankrat still cannot deploy the
GA4 tag or create a GA4 account. `site_onboarding_submit`
exists only when the operator has set `RANKRAT_ALLOW_AGENT_ONBOARDING=true`;
when it is absent, guide the user through `rankrat onboard-site`.

Typical flow for "why did traffic drop":

1. `google_search_analytics_summary` — establish the baseline.
2. `google_search_analytics_comparison` — the affected period against the prior one.
3. `google_search_analytics_drop_attribution` — which queries and pages account for it.
4. `google_url_inspection` on the worst pages — whether it is an indexing problem.

Tool names are prefixed by provider (`google_*`, `bing_*`), with a handful of
server-level ones (`server_info`, `accounts_list`, `sites_list`, `diagnostics`,
`provider_readiness`). The complete grouped tool catalog, environment, and
credential setup live in [`references/setup.md`](references/setup.md).
