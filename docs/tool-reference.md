# MCP tool reference

MCP `tools/list` from the running process is authoritative. Read-only mode
exposes only read tools. Writable mode adds every supported mutation, including
site onboarding. Counts are deliberately not duplicated here because the
catalog evolves and runtime discovery is exact.

REST uses the same services and schemas, but route names are defined by the
generated [`openapi.json`](../openapi.json). Use that document rather than
deriving REST paths from MCP names.

## Contents

- [Discovery and guidance](#discovery-and-guidance)
- [Site audit, ownership, schema, and Bing backlinks](#site-audit-ownership-schema-and-bing-backlinks)
- [Google Search Console and Indexing reads](#google-search-console-and-indexing-reads)
- [Google Analytics reads](#google-analytics-reads)
- [PageSpeed and Lighthouse reads](#pagespeed-and-lighthouse-reads)
- [Cross-provider reads](#cross-provider-reads)
- [Bing reads](#bing-reads)
- [SEO intelligence reads](#seo-intelligence-reads)
- [Monitoring reads](#monitoring-reads)
- [Ordinary write tools](#ordinary-write-tools)
- [MCP resources](#mcp-resources)
- [Tool annotations](#tool-annotations)

## Discovery and guidance

| Tool | Purpose |
| --- | --- |
| `server_info` | Non-secret process capability/policy metadata |
| `accounts_list` | Configured account summaries |
| `sites_list` | Configured resource boundaries |
| `diagnostics` | Local checks without provider calls |
| `provider_readiness` | Live bounded access check for one account |
| `onboarding_guide` | Runtime-specific automated/manual onboarding procedure |

## Site audit, ownership, schema, and Bing backlinks

| Tool | Purpose |
| --- | --- |
| `site_audit` | Bounded same-site crawl, findings, score, and remediation text |
| `site_ownership_check` | Google/Bing/DNS ownership status without proof values |
| `bing_backlink_intelligence` | Bounded Bing backlink pages plus domain/anchor summaries |
| `schema_validate_url` | Fetch one public HTTPS page and validate supported indexing eligibility |
| `schema_validate_html` | Validate local HTML eligibility |
| `schema_validate_json_ld` | Validate local JSON-LD eligibility |

## Google Search Console and Indexing reads

| Tool | Purpose |
| --- | --- |
| `google_search_analytics_query` | Typed Search Analytics dimensions, filters, and rows |
| `google_search_analytics_summary` | Period aggregate |
| `google_search_analytics_comparison` | Two-period comparison |
| `google_search_analytics_dimension_report` | Fixed query/page/country/device/appearance/time report |
| `google_search_analytics_drop_attribution` | Query/page contribution to a period change |
| `google_search_analytics_trend` | Ascending daily trend |
| `google_search_analytics_anomalies` | Deterministic daily anomalies |
| `google_search_analytics_page_performance` | One bounded page report |
| `google_sites_list` | Upstream properties available to the account |
| `google_site_get` | One configured property |
| `google_sitemaps_list` | Property sitemap inventory |
| `google_sitemap_get` | One sitemap's submitted/discovered/error status |
| `google_url_inspection` | Inspect one child URL |
| `google_url_inspection_batch` | Inspect a bounded child-URL set |
| `google_indexing_metadata` | Last Indexing API notification metadata for one URL |

## Google Analytics reads

| Tool | Purpose |
| --- | --- |
| `google_analytics_account_inventory` | OAuth-visible accounts and properties |
| `google_analytics_data_streams` | One configured property's streams and measurement IDs |
| `google_analytics_report` | Typed historical report |
| `google_analytics_realtime_report` | Realtime report |
| `google_analytics_content_performance` | Fixed content metrics |
| `google_analytics_landing_page_performance` | Fixed landing-page metrics |
| `google_analytics_organic_search_landing_pages` | Search Console-linked organic landing metrics |
| `google_analytics_traffic_source_performance` | Fixed source/medium metrics |
| `google_analytics_ecommerce_performance` | Item-level ecommerce metrics |
| `google_analytics_audience_segments` | Audience segment metrics |
| `google_analytics_user_behavior` | New-versus-returning engagement |
| `google_analytics_conversion_funnel` | Closed ordered event funnel |

## PageSpeed and Lighthouse reads

| Tool | Purpose |
| --- | --- |
| `pagespeed_analyze` | PageSpeed Insights analysis |
| `pagespeed_core_web_vitals` | Selected Core Web Vitals |
| `lighthouse_audit` | Local performance/accessibility/best-practices/SEO audit |
| `lighthouse_seo_findings` | Failed local SEO audits |
| `lighthouse_accessibility_findings` | Failed local accessibility audits |
| `lighthouse_performance_findings` | Failed local performance audits |
| `lighthouse_best_practices_findings` | Failed local best-practices audits |

## Cross-provider reads

| Tool | Purpose |
| --- | --- |
| `ga4_pagespeed_correlation` | One GA4 content observation beside PageSpeed evidence |
| `ga4_search_console_comparison` | GA4 organic and Search Console observations |
| `search_engine_comparison` | Google and Bing traffic observations |
| `search_engine_traffic_health` | Google and Bing daily anomaly observations |

## Bing reads

| Tool | Purpose |
| --- | --- |
| `bing_keyword_statistics` | Daily keyword statistics |
| `bing_related_keywords` | Related keywords for a bounded interval |
| `bing_traffic_trend` | Ascending daily traffic trend |
| `bing_traffic_anomalies` | Deterministic daily anomalies |
| `bing_traffic_comparison` | Two-period comparison |
| `bing_query_performance` | Top-query performance |
| `bing_page_performance` | Top-page performance |
| `bing_brand_analysis` | Literal brand-term classification |
| `bing_ranking_buckets` | Average-click-position buckets |
| `bing_query_opportunities` | Local query opportunities |
| `bing_page_opportunities` | Local page opportunities |
| `bing_opportunity_matrix` | Query/page opportunities plus quick-win subsets |
| `bing_query_page_performance` | Page statistics for one query |
| `bing_query_cannibalization` | Competing pages for one query |
| `bing_page_query_performance` | Query statistics for one page |
| `bing_url_submission_quota` | Remaining submission quota |
| `bing_crawl_issues` | Crawl issues |
| `bing_crawl_stats` | Daily crawl statistics |
| `bing_feeds` | Sitemap/feed records |
| `bing_link_counts` | Paged inbound-link counts |
| `bing_url_information` | Crawl/index information for one child URL |

## SEO intelligence reads

| Tool | Purpose |
| --- | --- |
| `internal_link_graph` | Bounded incoming/outgoing site graph |
| `orphan_page_report` | Crawl/Search Console/GA4 orphan-page join |
| `internal_link_opportunities` | Deterministic lexical missing-link suggestions |
| `crux_history` | Bounded Chrome UX history for URL/origin |
| `cloudflare_analytics` | Hourly traffic/cache aggregates |
| `content_opportunities` | Joined Search Console/Bing/GA4/crawl opportunities |

## Monitoring reads

| Tool | Purpose |
| --- | --- |
| `monitors_list` | Paginated monitors for one site |
| `monitor_snapshots_list` | Immutable monitor snapshots |
| `monitor_issues_list` | Monitor issue history/filtering |
| `issue_events_list` | Immutable lifecycle events for one issue |

## Ordinary write tools

These appear only with `RANKRAT_READ_ONLY=false`.

### Search engine and analytics writes

| Tool | Purpose |
| --- | --- |
| `indexnow_submit` | Notify participating engines about bounded changed URLs |
| `bing_url_submit` | Submit bounded URLs |
| `bing_sitemap_submit` | Submit or delete one approved sitemap |
| `bing_site_submit` | Add or delete one approved site |
| `google_indexing_submit` | Publish one eligible URL notification |
| `google_indexing_batch_submit` | Publish a bounded eligible notification batch |
| `google_site_submit` | Add or delete one approved Search Console property |
| `google_sitemap_submit` | Submit or delete one approved sitemap |
| `google_analytics_account_rename` | Rename one reachable GA4 account |
| `google_analytics_property_rename` | Rename one configured GA4 property |

### Ownership and remediation writes

| Tool | Purpose |
| --- | --- |
| `site_ownership_verify` | Publish provider-issued DNS proofs and redeem ownership |
| `site_remediation_apply` | Resubmit a bounded sitemap and changed URLs to Google/Bing |
| `site_onboarding_submit` | Create/reuse GA4, Search Console, and Bing resources and persist discovered inventory |

### Monitoring writes

| Tool | Purpose |
| --- | --- |
| `monitor_create` | Create a persistent site-audit monitor |
| `monitor_update` | Update name, interval, and enabled state |
| `monitor_delete` | Delete monitor and local history |
| `monitor_run` | Run immediately and persist the result |
| `issue_status_update` | Set explicit issue lifecycle status |

### Cloudflare cache writes

| Tool | Purpose |
| --- | --- |
| `cloudflare_cache_purge` | Purge exact configured-site URLs |
| `cloudflare_cache_template_apply` | Apply `cache_static_assets` or `bypass_html` |

## MCP resources

In addition to tools, Rankrat serves:

| Resource | Purpose |
| --- | --- |
| `rankrat://onboarding` | General runtime onboarding guide |
| `rankrat://onboarding/{site_url}` | Guide narrowed to one percent-encoded site |

Clients without MCP resource support call `onboarding_guide` instead.

## Tool annotations

Read/write, destructive, idempotent, and open-world hints are emitted in MCP
tool annotations. They are guidance for clients, not a replacement for startup
policy or boundary enforcement. Provider acceptance and DNS/indexing progress
can remain asynchronous even when a request itself is idempotent.
