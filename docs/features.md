# Feature workflows

This guide maps questions to Rankrat operations. Use runtime MCP `tools/list`
or [`openapi.json`](../openapi.json) for exact request/response schemas. The
[tool reference](tool-reference.md) lists every MCP name.

## Contents

- [Start with discovery](#start-with-discovery)
- [Diagnose a Google traffic drop](#diagnose-a-google-traffic-drop)
- [Understand a GA4 property](#understand-a-ga4-property)
- [Diagnose Bing search and crawl state](#diagnose-bing-search-and-crawl-state)
- [Compare providers](#compare-providers)
- [Audit a site](#audit-a-site)
- [Improve internal links and content](#improve-internal-links-and-content)
- [Inspect backlinks](#inspect-backlinks)
- [Inspect performance](#inspect-performance)
- [Ownership and onboarding](#ownership-and-onboarding)
- [Monitoring and writes](#monitoring-and-writes)

## Start with discovery

Before interpreting provider data:

1. `server_info` — process policy, enabled surfaces, and version metadata.
2. `accounts_list` — non-secret configured accounts.
3. `sites_list` — configured resource boundaries.
4. `diagnostics` — local config/credential presence without provider calls.
5. `provider_readiness` — live access for a selected account.

Read tools remain discoverable when a provider is unconfigured so clients can
have a stable schema. An unavailable result is not the same as an empty report.

## Diagnose a Google traffic drop

Suggested sequence:

1. `google_search_analytics_summary` for the affected period.
2. `google_search_analytics_comparison` against the prior period.
3. `google_search_analytics_drop_attribution` by query or page.
4. `google_search_analytics_trend` and
   `google_search_analytics_anomalies` for timing.
5. `google_url_inspection` or `google_url_inspection_batch` on affected pages.
6. `google_sitemap_get` for submitted/discovered counts and current errors.

Search Console data is delayed upstream. Rankrat reports provider evidence; it
does not convert a missing recent row into proof of lost traffic.

Other Search Console reads:

- `google_search_analytics_query` — typed dimensions/filters/rows;
- `google_search_analytics_dimension_report` — fixed query/page/country/device/
  appearance/time dimensions;
- `google_search_analytics_page_performance` — one page's report;
- `google_sites_list` and `google_site_get` — upstream property state;
- `google_sitemaps_list` — property sitemap inventory;
- `google_indexing_metadata` — last Indexing API notification metadata.

Google Indexing notification metadata is not general Google crawl/index status.
Use URL Inspection and sitemap state for ordinary pages.

## Understand a GA4 property

Use `google_analytics_account_inventory` to find every account/property visible
to a discovery-enabled credential. Properties often sit under an unexpected
account because the Analytics UI chose a default during creation.

Use `google_analytics_data_streams` to map a property to its web stream and
`G-` measurement ID. A tag can be installed correctly while sending data to a
different property; matching the measurement ID avoids that false conclusion.

Reports:

| Tool | Purpose |
| --- | --- |
| `google_analytics_report` | Typed custom historical dimensions/metrics |
| `google_analytics_realtime_report` | Current activity |
| `google_analytics_content_performance` | Page/content engagement |
| `google_analytics_landing_page_performance` | Landing page performance |
| `google_analytics_organic_search_landing_pages` | Search Console-linked organic landing metrics |
| `google_analytics_traffic_source_performance` | Source/medium evidence |
| `google_analytics_ecommerce_performance` | Item-level ecommerce evidence |
| `google_analytics_audience_segments` | Audience segment metrics |
| `google_analytics_user_behavior` | New versus returning engagement |
| `google_analytics_conversion_funnel` | Closed ordered event-step funnel |

Writable mode includes account/property renames. Names are cosmetic; numeric
IDs remain the boundary and reporting identity. Rankrat deliberately exposes no
GA4 account/property delete. Google provides no API to create a GA4 account;
Rankrat can create a property inside an existing account during onboarding.

## Diagnose Bing search and crawl state

Traffic/reporting:

- `bing_traffic_trend`, `bing_traffic_anomalies`, and
  `bing_traffic_comparison`;
- `bing_query_performance` and `bing_page_performance`;
- `bing_query_page_performance` and `bing_page_query_performance`;
- `bing_brand_analysis`, `bing_ranking_buckets`,
  `bing_query_opportunities`, `bing_page_opportunities`, and
  `bing_opportunity_matrix`;
- `bing_query_cannibalization` for multiple competing pages.

Crawl/indexing:

- `bing_crawl_issues` and `bing_crawl_stats`;
- `bing_feeds` for sitemaps/feeds;
- `bing_url_information` for one bounded child URL;
- `bing_url_submission_quota` before writes.

Keywords/backlinks:

- `bing_keyword_statistics` and `bing_related_keywords`;
- `bing_link_counts` for paged inbound counts;
- `bing_backlink_intelligence` for bounded page walking plus referring-domain
  and anchor summaries.

The opportunity, brand, bucket, and cannibalization reports are deterministic
local derivations from Bing data. Their labels are evidence, not buying advice
or an indexing promise.

## Compare providers

Rankrat keeps separate observations rather than pretending metrics from
different products are directly interchangeable:

- `ga4_search_console_comparison` — organic landing observations alongside
  Search Console observations;
- `search_engine_comparison` — Google and Bing traffic evidence;
- `search_engine_traffic_health` — separate anomaly evidence for each engine;
- `ga4_pagespeed_correlation` — one GA4 content row alongside one PageSpeed
  analysis.

Use these to locate disagreement. A Search Console click, Bing click, GA4
session, and PageSpeed lab result measure different systems.

## Audit a site

`site_audit` crawls one configured HTTPS site through a DNS-pinned public
fetcher and reports page evidence, findings, remediation text, and a normalized
score. It checks:

- HTTP status and fetch failures;
- robots and sitemap discovery;
- titles, descriptions, canonicals, `noindex`, language, and H1 count;
- image alt text and Open Graph metadata;
- duplicate titles and non-HTML sitemap entries;
- restricted Google Indexing structured-data eligibility;
- truncation when page/issue/depth limits are reached.

The crawler follows normalized same-site links only and rejects redirects, IP
literals, private/special/mixed DNS answers, and out-of-bound paths. Findings
tell a caller what to change; Rankrat does not edit an arbitrary CMS/repository.

Structured-data checks are also available directly:

- `schema_validate_json_ld` — local JSON-LD string;
- `schema_validate_html` — local HTML string;
- `schema_validate_url` — bounded public HTTPS fetch.

These validate Rankrat's supported Google Indexing eligibility rules, not every
schema.org vocabulary or Google's full Rich Results product.

## Improve internal links and content

- `internal_link_graph` crawls the bounded site and returns incoming/outgoing
  relationships.
- `orphan_page_report` joins crawl, Search Console, and GA4 pages to identify
  URLs with provider evidence but no crawled internal path.
- `internal_link_opportunities` suggests missing same-site links only when
  normalized title/path tokens overlap.
- `content_opportunities` joins Search Console, Bing, GA4, and crawl evidence
  into deterministic ranked opportunities.

The lexical suggestions do not use an LLM and do not invent arbitrary semantic
relationships. Crawl truncation is reported so the caller knows when a graph or
orphan result is incomplete.

## Inspect backlinks

Use `bing_backlink_intelligence` for backlink evidence from one configured Bing
Webmaster site. It reports only the data Bing exposes for that account; Rankrat
does not scrape competitors, manufacture links, buy links, or send outreach.

## Inspect performance

- `pagespeed_analyze` — PageSpeed Insights lab analysis;
- `pagespeed_core_web_vitals` — selected user-experience metrics;
- `crux_history` — up to the configured bounded history periods for an allowed
  URL or origin;
- `cloudflare_analytics` — bounded hourly traffic/cache groups;
- five local Lighthouse tools — isolated Chromium audit and category findings.

PageSpeed/CrUX are external Google services. Lighthouse is local and optional.
Read [Lighthouse](lighthouse.md) before enabling its browser worker.

## Ownership and onboarding

`site_ownership_check` reads Google/Bing and public DNS status without returning
provider verification tokens. `site_ownership_verify` creates only the exact
provider-issued DNS proofs through a supported adapter and redeems them after
propagation. Site onboarding creates GA4/Search Console/Bing resources under
the configured provider accounts in normal writable mode. Read
[Ownership and onboarding](ownership-and-onboarding.md) before using either
write flow.

## Monitoring and writes

Monitors persist bounded site-audit snapshots and issue lifecycle state. Other
writes submit sitemaps/URLs, publish eligible Indexing notifications, notify
IndexNow, rename GA4 resources, verify ownership, remediate discovery, and
perform finite Cloudflare cache actions. Read
[Monitoring and remediation](monitoring-and-remediation.md) for asynchronous and
partial-failure semantics before enabling writes.
