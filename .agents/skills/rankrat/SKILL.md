---
name: rankrat
description: Query Google Search Console, Bing Webmaster Tools, Google Analytics 4 (GA4), and PageSpeed Insights through one self-hosted MCP server. Search analytics queries, summaries, trends, anomalies, comparisons and drop attribution; query and page performance, ranking buckets, cannibalization and opportunity reports; URL inspection, sitemaps, crawl issues, crawl stats, link counts and feeds; GA4 reports covering realtime, content, landing pages, organic search, traffic sources, ecommerce, audience segments, user behavior and conversion funnels; PageSpeed Insights and schema fetching. Speaks MCP over stdio and Streamable HTTP, plus a FastAPI JSON API. Use when the user wants to inspect SEO, indexing, ranking or search-traffic data for sites they already own.
homepage: https://github.com/psyb0t/rankrat
user-invocable: true
metadata:
  openclaw:
    emoji: "🐀"
    primaryEnv: RANKRAT_URL
    requires:
      bins: [docker]
permissions:
  network: "outbound HTTPS to the configured providers (Google Search Console, Google Analytics, Bing Webmaster Tools, PageSpeed Insights) and inbound only on the port you bind. Traffic goes to the provider APIs, never to a third party."
  shell: "docker run invocations for the published image, as shown below; no other host access is required."
  filesystem: "reads the boundary config and provider credentials. Local initialization creates an HTTP bearer secret; Google authorization writes its token record; IndexNow initialization creates or retains its local key and updates .env plus the boundary file; writable unbounded onboarding updates the one configured boundary file with exact created-resource IDs."
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
serves only the accounts, sites and properties listed in it. A tool cannot widen
that scope from inside a bounded session.

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
provider APIs over HTTPS; nothing is relayed to a third party, and credentials,
OAuth records and raw provider bodies are never returned or logged. Bind it to
loopback or a private network, and use the bearer token if anything else can
reach it.

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
- Checking which providers are actually wired up (`provider_readiness`,
  `diagnostics`) before trusting a report.

## When NOT to use

- **Sites you don't control.** Everything is scoped to properties already
  verified in your own Search Console / Bing / GA4 accounts. It is not a rank
  tracker or a competitor-research tool and cannot query arbitrary domains.
- **Changing anything in the default configuration.** Read-only mode exposes no
  write tools. A trusted writable deployment can submit URLs/sitemaps and,
  during an unbounded session, create supported provider resources for a newly
  onboarded site.
- **Realtime dashboards.** Provider APIs lag (Search Console notably so), and
  rankrat reports what they return.
- **Crawling a site.** It reads provider APIs; it is not a crawler or an
  auditor.

## Usage

Both MCP transports run from the published image. The tool list adapts to which
providers are configured, so ask `provider_readiness` first if a call comes back
empty.

**stdio** is the default mode, so a client that spawns its own server just runs
the image and talks to it — no port, no bridge:

```bash
docker run -i --rm --init --read-only \
  --cap-drop=ALL --security-opt no-new-privileges:true \
  --tmpfs /tmp:rw,noexec,nosuid,size=32m \
  --mount type=bind,src="$PWD/config",dst=/run/config,readonly \
  --mount type=bind,src="$PWD/secrets",dst=/run/secrets,readonly \
  --mount type=bind,src="$PWD/oauth",dst=/run/oauth,readonly \
  psyb0t/rankrat stdio
```

**Streamable HTTP** for a shared or already-running server. MCP is at `/mcp`,
and the REST API is on the same port:

```bash
docker run --rm --init --read-only \
  --cap-drop=ALL --security-opt no-new-privileges:true \
  --tmpfs /tmp:rw,noexec,nosuid,size=32m \
  -p 127.0.0.1:8080:8080 \
  -e RANKRAT_HTTP_HOST=0.0.0.0 \
  -e RANKRAT_HTTP_BEARER_SECRET_FILE=/run/secrets/rankrat/http-bearer-token \
  --mount type=bind,src="$PWD/config",dst=/run/config,readonly \
  --mount type=bind,src="$PWD/secrets",dst=/run/secrets,readonly \
  --mount type=bind,src="$PWD/oauth",dst=/run/oauth,readonly \
  psyb0t/rankrat http
```

`RANKRAT_HTTP_HOST=0.0.0.0` binds inside the container; the `-p` publishes it on
loopback only. Send `Authorization: Bearer <token>` when a bearer secret is
configured.

The repo ships a `rankrat.sh` wrapper around exactly these invocations for
humans; an agent does not need it.

Typical flow for "why did traffic drop":

1. `google_search_analytics_summary` — establish the baseline.
2. `google_search_analytics_comparison` — the affected period against the prior one.
3. `google_search_analytics_drop_attribution` — which queries and pages account for it.
4. `google_url_inspection` on the worst pages — whether it is an indexing problem.

Tool names are prefixed by provider (`google_*`, `bing_*`), with a handful of
server-level ones (`server_info`, `accounts_list`, `sites_list`, `diagnostics`,
`provider_readiness`). Full environment and credential setup lives in
[`references/setup.md`](references/setup.md).
