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
      bins: [docker, curl]
permissions:
  network: "outbound HTTPS to the configured providers (Google Search Console, Google Analytics, Bing Webmaster Tools, PageSpeed Insights) and inbound only on the port you bind. Traffic goes to the provider APIs, never to a third party."
  shell: "docker and curl invocations shown in references/setup.md — no other host access."
  filesystem: "reads the boundary config and the provider credential files you point it at; writes only its own log file."
---

# rankrat

A self-hosted MCP server over the SEO and search-analytics APIs you already have
accounts on — Google Search Console, Bing Webmaster Tools, GA4, and PageSpeed
Insights — so an agent can read your own search data without you handing it a
browser session or a service-account key.

Install, credentials and the full environment reference:
[`references/setup.md`](references/setup.md).

## Security & safety

The account boundary is fixed by the operator, not by the agent. rankrat serves
only the sites and properties listed in its boundary config; an agent cannot
widen that scope, enumerate other properties, or reach an account you did not
configure.

It is **read-only by default** — `enable_writes` defaults to `false`, and the
write tools are not merely rejected but absent from the tool catalog entirely,
so an agent cannot see or call them. Turning writes on additionally requires an
admin bearer secret to be configured; rankrat refuses to start otherwise. Leave
writes off unless you specifically want submission tools, and only point the
server at properties you own.

Your provider credentials stay on the host running rankrat. Requests go to the
provider APIs over HTTPS; nothing is relayed to a third party. Bind it to
localhost or a private network and enable bearer auth if it is reachable by
anything else.

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
- **Changing anything.** Aside from the optional submission tools, there is no
  way to edit provider state — no settings, no property creation, no content.
- **Realtime dashboards.** Provider APIs lag (Search Console notably so), and
  rankrat reports what they return.
- **Crawling a site.** It reads provider APIs; it is not a crawler or an
  auditor.

## Usage

Start it and point an MCP client at it — the tool list adapts to which providers
are configured, so ask for `provider_readiness` first if a call comes back empty.

```bash
docker run --rm -p 8080:8080 \
  -v "$PWD/config:/config:ro" \
  psyb0t/rankrat http
```

MCP over Streamable HTTP is at `/mcp`. A FastAPI JSON API is available for
non-MCP callers on the same port.

`stdio` is the default mode and speaks MCP directly, so a client that spawns its
own server needs no bridge or proxy — point it at the image and let it own the
process:

```bash
docker run -i --rm -v "$PWD/config:/config:ro" psyb0t/rankrat stdio
```

Typical flow for "why did traffic drop":

1. `google_search_analytics_summary` — establish the baseline.
2. `google_search_analytics_comparison` — the affected period against the prior one.
3. `google_search_analytics_drop_attribution` — which queries and pages account for it.
4. `google_url_inspection` on the worst pages — whether it is an indexing problem.

Tool names are prefixed by provider (`google_*`, `bing_*`), with a handful of
server-level ones (`server_info`, `accounts_list`, `sites_list`, `diagnostics`,
`provider_readiness`). Full environment and credential setup lives in
[`references/setup.md`](references/setup.md).
