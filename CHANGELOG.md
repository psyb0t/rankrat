# Changelog

Notable changes to Rankrat, newest first.

## v0.1.0 — 2026-08-01

Initial release.

- Read-only SEO and search analytics over three transports from one service:
  MCP over stdio, MCP over Streamable HTTP, and a FastAPI JSON API.
- Ships as a Docker image (`psyb0t/rankrat`), registered with the MCP registry
  as `io.github.psyb0t/rankrat`. Not published to PyPI.
- Validated immutable boundaries: an agent cannot expand account scope, alter
  provider state, or discover arbitrary properties. Every provider read is
  mapped at its HTTP boundary into a bounded immutable result type rather than
  relayed as generic provider JSON.
- Google Search Console: fixed-origin property listing and get, Search
  Analytics, sitemap listing, URL inspection, Indexing notification metadata,
  aggregate and period-comparison reports, and typed fixed-dimension reports for
  queries, pages, countries, search appearances, time series, period-drop
  attribution, ascending daily trends, deterministic daily anomalies, and page
  performance.
- Bing Webmaster Tools: site, keyword, crawl, rank/traffic, feed, link, quota,
  and URL-information reads, plus typed daily traffic trends, deterministic
  anomalies, exact period comparisons, top-query and top-page performance,
  local opportunity reports, a query cannibalization signal, literal
  brand/non-brand query analysis, and fixed ranking buckets.
- GA4: historical and realtime reports plus fixed content, landing-page,
  session-source, item-level ecommerce, audience-segment, and
  new-versus-returning user-behavior reports for configured properties.
- PageSpeed Insights analyses for configured child URLs only.
- Bounded cross-provider reports: GA4/PageSpeed correlation, Search
  Console/Bing comparison, Search Console/Bing daily traffic health, and
  GA4/Search Console comparison — each keeping every engine's observations
  separate rather than merging them into falsely precise numbers.
- Credential-free local checks: raw HTML and JSON-LD eligibility, plus bounded
  public-HTTPS page validation.
- Writes are off by default and individually guarded: IndexNow submissions, Bing
  URL/sitemap/property submissions, Google Indexing notifications, and Google
  property and sitemap mutations run only against explicitly configured targets,
  behind a separate admin bearer secret and a short-lived per-write approval.
- Hardened image: multi-stage build on a digest-pinned CPython base, non-root
  `rankrat` user, no build tools in the runtime stage, secrets read from mounted
  files rather than environment values.
- Supply chain: frozen `uv.lock` under a dependency age gate, Syft and CycloneDX
  SBOMs, Gitleaks secret scanning, and a Grype image gate that fails on fixable
  high or critical findings, with assessed CPython stdlib CVEs recorded as
  OpenVEX statements in `security/rankrat-cpython.openvex.json`.
