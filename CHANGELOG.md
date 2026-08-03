# Changelog

Notable changes to Rankrat, newest first.

## v0.1.0 — 2026-08-03

Initial release.

- Read-only SEO and search analytics over three transports from one service:
  MCP over stdio, MCP over Streamable HTTP, and a FastAPI JSON API.
- Ships as a Docker image (`psyb0t/rankrat`), registered with the MCP registry
  as `io.github.psyb0t/rankrat`. Not published to PyPI.
- Validated boundaries: in bounded operation an agent cannot expand account
  scope, alter provider state, or discover arbitrary properties. Every provider
  read is mapped at its HTTP boundary into a bounded immutable result type
  rather than relayed as generic provider JSON.
- One switch for write capability. `RANKRAT_READ_ONLY` defaults to `true`, and
  the effect is stronger than refusing a call: the tool catalog is built from
  that setting, so write tools are absent from `tools/list` and the REST write
  routes are never mounted. There is no approval ID, admin API, or second bearer
  token — setting it to `false` gives the trusted caller direct access, still
  confined to the configured boundaries and to what the provider account itself
  permits.
- `RANKRAT_UNBOUNDED=true` adds a reusable trusted-onboarding session for a
  resource not yet in the boundary file. It requires read-only off, keeps the
  credential accounts fixed, and relaxes only the per-resource allow-lists —
  URL containment, IndexNow target resolution and the OAuth credential path stay
  bound. Onboarding persists the exact created resource IDs back to the boundary
  file, so restarting without the switch enforces the expanded list.
- Unknown `RANKRAT_*` variables fail startup rather than being silently ignored.
- Agent surface under `.agents/`: a skill, Claude Code and Codex plugin
  manifests, and an MCP bridge that defaults to running the published image over
  stdio — rankrat already speaks MCP there, so no proxy is involved — and can
  instead proxy to a running server's Streamable HTTP endpoint.
- `src/rankrat/api/openapi.yaml` is the source of truth for REST operation IDs,
  and the served OpenAPI document reflects the routes enabled in the current
  runtime.
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
- Writes are off by default: IndexNow submissions, Bing URL/sitemap/property
  submissions, Google Indexing notifications, and Google property and sitemap
  mutations run only when writable mode is explicitly selected and only against
  the configured provider account and target boundary.
- Hardened image: multi-stage build on a digest-pinned CPython base, non-root
  `rankrat` user, no build tools in the runtime stage, secrets read from mounted
  files rather than environment values.
- Supply chain: frozen `uv.lock` under a dependency age gate, Syft and CycloneDX
  SBOMs, Gitleaks secret scanning, and a Grype image gate that fails on fixable
  high or critical findings, with assessed CPython stdlib CVEs recorded as
  OpenVEX statements in `security/rankrat-cpython.openvex.json`.
