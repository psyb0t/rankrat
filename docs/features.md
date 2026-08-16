# Feature workflows

Questions mapped to the tools that answer them. For exact request/response
schemas, hit runtime MCP `tools/list` or read [`openapi.json`](../openapi.json);
the [tool reference](tool-reference.md) has every MCP name.

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
- [Manage tags, redirects, and Bing content](#manage-tags-redirects-and-bing-content)
- [Ownership and onboarding](#ownership-and-onboarding)
- [Monitoring and writes](#monitoring-and-writes)

## Start with discovery

Look before you interpret. Five reads tell you what's actually wired up:

1. `server_info` — process policy, enabled surfaces, version metadata.
2. `accounts_list` — the configured accounts, no secrets.
3. `sites_list` — the resource boundaries you're allowed to touch.
4. `diagnostics` — local config/credential presence, zero provider calls.
5. `provider_readiness` — live access for one account.

Read tools stay discoverable even when a provider isn't configured, so your
client always gets a stable schema. "Unavailable" is not "empty" — a missing
credential is a different answer than a clean report.

## Diagnose a Google traffic drop

Work outward from the aggregate to the individual pages:

1. `google_search_analytics_summary` for the affected period.
2. `google_search_analytics_comparison` against the period before it.
3. `google_search_analytics_drop_attribution` to see which queries or pages ate the loss.
4. `google_search_analytics_trend` and `google_search_analytics_anomalies` to pin the timing.
5. `google_url_inspection` or `google_url_inspection_batch` on the pages that dropped.
6. `google_sitemap_get` for submitted/discovered counts and current errors.

Search Console lags upstream. Rankrat reports what the provider says — it does
not turn a not-yet-arrived recent row into proof you lost traffic. Don't confuse
the two.

More Search Console reads:

- `google_search_analytics_query` — typed dimensions/filters/rows;
- `google_search_analytics_dimension_report` — fixed query/page/country/device/appearance/time dimensions;
- `google_search_analytics_page_performance` — one page's report;
- `google_sites_list` and `google_site_get` — upstream property state;
- `google_sitemaps_list` — the property's sitemap inventory;
- `google_indexing_metadata` — last Indexing API notification metadata.

That last one is a trap: Indexing notification metadata is not general crawl or
index status. For ordinary pages, use URL Inspection and sitemap state.

## Understand a GA4 property

`google_analytics_account_inventory` lists every account and property a
discovery-enabled credential can see. Expect properties to sit under an account
you didn't expect — the Analytics UI picks a default at creation time and
nobody ever moves them.

`google_analytics_data_streams` maps a property to its web stream and `G-`
measurement ID. A tag can be installed perfectly and still feed a different
property; match the measurement ID before you declare it broken.

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

Writable mode adds account and property renames. Names are cosmetic — the
numeric IDs stay the boundary and the reporting identity. There is deliberately
no GA4 delete. Google gives no API to create a GA4 account, so onboarding can
only create a property inside an account that already exists.

## Diagnose Bing search and crawl state

Traffic and reporting:

- `bing_traffic_trend`, `bing_traffic_anomalies`, `bing_traffic_comparison`;
- `bing_query_performance` and `bing_page_performance`;
- `bing_query_page_performance` and `bing_page_query_performance`;
- `bing_brand_analysis`, `bing_ranking_buckets`, `bing_query_opportunities`,
  `bing_page_opportunities`, `bing_opportunity_matrix`;
- `bing_query_cannibalization` when several pages fight over one query.

Crawl and indexing:

- `bing_crawl_issues` and `bing_crawl_stats`;
- `bing_feeds` for sitemaps/feeds;
- `bing_url_information` for one bounded child URL;
- `bing_url_submission_quota` — check it before you spend writes.

Keywords and backlinks:

- `bing_keyword_statistics` and `bing_related_keywords`;
- `bing_link_counts` for paged inbound counts;
- `bing_backlink_intelligence` for bounded page walking plus referring-domain
  and anchor summaries.

The opportunity, brand, bucket, and cannibalization reports are deterministic
local math over Bing's own data. The labels are evidence — not buying advice,
not a promise anything gets indexed.

## Compare providers

Rankrat keeps each provider's numbers separate instead of pretending a Search
Console click and a GA4 session measure the same thing. They don't:

- `ga4_search_console_comparison` — organic landing observations next to Search Console observations;
- `search_engine_comparison` — Google and Bing traffic evidence side by side;
- `search_engine_traffic_health` — separate anomaly evidence per engine;
- `ga4_pagespeed_correlation` — one GA4 content row next to one PageSpeed analysis.

Use these to find where the sources disagree — a Search Console click, a Bing
click, a GA4 session, and a PageSpeed lab result each measure a different system.

## Audit a site

`site_audit` crawls one configured HTTPS site through a DNS-pinned public
fetcher and hands back page evidence, findings, remediation text, and a
normalized score. It checks:

- HTTP status and fetch failures;
- robots and sitemap discovery;
- titles, descriptions, canonicals, `noindex`, language, and H1 count;
- image alt text and Open Graph metadata;
- duplicate titles and non-HTML sitemap entries;
- restricted Google Indexing structured-data eligibility;
- truncation when page/issue/depth limits are hit.

The crawler follows normalized same-site links only. It rejects redirects, IP
literals, private/special/mixed DNS answers, and out-of-bound paths — it doesn't
wander off your site. Findings tell the caller what to change; Rankrat does not
edit your CMS or repo for you.

Structured-data checks stand alone too:

- `schema_validate_json_ld` — a local JSON-LD string;
- `schema_validate_html` — a local HTML string;
- `schema_validate_url` — a bounded public HTTPS fetch.

These validate Rankrat's supported Google Indexing eligibility rules — not every
schema.org vocabulary, and not Google's full Rich Results suite.

## Improve internal links and content

- `internal_link_graph` crawls the bounded site and returns incoming/outgoing relationships.
- `orphan_page_report` joins crawl, Search Console, and GA4 to surface URLs that have provider evidence but no crawled internal path.
- `internal_link_opportunities` suggests missing same-site links, and only when normalized title/path tokens overlap.
- `content_opportunities` joins Search Console, Bing, GA4, and crawl evidence into deterministic ranked opportunities.

No LLM in that loop. The suggestions are lexical — they don't invent semantic
relationships out of thin air. Crawl truncation is reported, so you know when a
graph or orphan result is partial instead of trusting a half-finished picture.

## Inspect backlinks

`bing_backlink_intelligence` is the backlink evidence, from one configured Bing
Webmaster site. It reports only what Bing exposes for that account. It does not
scrape competitors, manufacture links, buy links, or send outreach — it's a
reader, not a link farm.

## Inspect performance

- `pagespeed_analyze` — PageSpeed Insights lab analysis;
- `pagespeed_core_web_vitals` — selected field metrics;
- `crux_history` — up to the configured bounded history periods for an allowed URL or origin;
- `cloudflare_analytics` — bounded hourly traffic/cache groups;
- five local Lighthouse tools — an isolated Chromium audit plus per-category findings.

PageSpeed and CrUX are external Google services. Lighthouse is local and
optional — read [Lighthouse](lighthouse.md) before you turn on its browser worker.

## Manage tags, redirects, and Bing content

Start with `google_tag_manager_accounts_list` to find the signed-in user's Tag
Manager accounts. From there the Tag Manager tools cover typed list, create,
update, delete, workspace-version, and publication operations for containers,
workspaces, tags, triggers, and variables. Bump to a release that adds a Tag
Manager scope? Re-run `rankrat auth-google` first — the grant has to carry the
current edit, delete, version-edit, and publish scopes or those writes just fail.

`clarity_insights` reads one bounded Microsoft Clarity project export. It's a
read-only project token with a small daily upstream quota — use it to inspect
evidence, not as a polling monitor you hammer every minute.

`edge_redirects_list`, `edge_redirect_upsert`, and `edge_redirect_delete` are
provider-neutral names; Cloudflare is the adapter that ships today. Rankrat only
lists and changes redirects marked as Rankrat-managed — it will not clobber your
hand-written provider rules.

`bing_content_submission_create` fetches an allowed public HTML page itself and
sends that freshly fetched body to Bing. It does not take caller-supplied HTML,
headers, or a free-form destination URL — you don't get to inject content
through it.

## Ownership and onboarding

`site_ownership_check` reads Google/Bing and public DNS status without ever
handing back provider verification tokens. `site_ownership_verify` creates only
the exact provider-issued DNS proofs through a supported adapter, then redeems
them after propagation. Site onboarding creates GA4/Search Console/Bing
resources under the configured accounts, in normal writable mode. Read
[Ownership and onboarding](ownership-and-onboarding.md) before you run either
write flow.

## Monitoring and writes

Monitors persist bounded site-audit snapshots and issue lifecycle state.
Everything else that writes: submits sitemaps/URLs, publishes eligible Indexing
notifications, notifies IndexNow, renames GA4 resources, verifies ownership,
remediates discovery, and runs typed Tag Manager, managed edge-redirect, Bing
content-submission, and finite Cloudflare cache actions. Provider acceptance and
indexing progress can lag after the call returns — read
[Monitoring and remediation](monitoring-and-remediation.md) for the async and
partial-failure semantics before you enable writes.
