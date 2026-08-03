# Changelog

Notable changes to Rankrat, newest first.

## v0.2.0 — 2026-08-03

Onboarding now explains the half it cannot do, and agents no longer reach it just
because the server is writable.

- **Rankrat cannot verify site ownership, and now says so instead of implying
  otherwise.** Onboarding creates the GA4 property, the Search Console property
  and the Bing site, then returns `google_search_console_added: true`. That flag
  only ever meant the create call was accepted — the property is unverified,
  answers reads with a `siteUnverifiedUser` permission level rather than data,
  and stays that way until a human deploys a token issued by the provider's own
  console. Nothing reported that, so a run that "worked" left the user with
  unexplained empty reads.
- **The procedure is now served.** New read-only surfaces: a
  `rankrat://onboarding` MCP resource, a `rankrat://onboarding/{site_url}`
  resource template narrowing it to one percent-encoded site, and an
  `onboarding_guide` tool returning the identical document for clients without
  resource support. All three render from one function and exist on every server,
  including a read-only one — knowing the procedure is not a privilege, and a
  read-only Rankrat can now coach an operator through work it will not do itself.
  `rankrat onboard-site` prints the same steps when it finishes. The server
  advertises the `resources` capability for the first time; it previously
  advertised only `tools`.
- **The guidance is narrowed by the property form,** because the options are not
  the same: a `sc-domain:` property accepts a DNS TXT record and nothing else,
  while a `https://` URL-prefix property also accepts the GA4 tag, an HTML file
  or a meta tag. It never invents a token value — Rankrat holds no credential
  that can read one — so each method names its artifact and says which console
  issues it.
- **Breaking. `RANKRAT_READ_ONLY=false` no longer exposes `site_onboarding_submit`
  on its own.** Onboarding is the one operation that rewrites the boundary file
  this server enforces, so an agent calling it widens its own future scope; that
  should not ride along with the switch that permits an IndexNow submission. It
  now also requires `RANKRAT_ALLOW_AGENT_ONBOARDING=true`, without which the tool
  is absent from `tools/list` and its REST route is never mounted. Deployments
  that relied on the old behaviour set the new variable. The `rankrat
  onboard-site` command is unaffected.

Known gap, unchanged in this release: a partially-failed onboarding is not rolled
back, and because the boundary file is only written after all three stages
succeed, retrying creates a second GA4 property.

## v0.1.2 — 2026-08-03

Adds `rankrat.sh`, makes the README lead with the image rather than the
Makefile, and fixes the run command that had never worked.

- **Mounting the boundary file on its own never worked, and that is what every
  Make target did.** The image creates `/run/config` as mode 750 owned by its
  own `rankrat` user. A single-file bind mount leaves that directory in place,
  so a container started with `--user "$(id -u)"` cannot traverse into it and
  the read fails with `PermissionError`, surfacing only as `rankrat startup
  failed: invalid configuration`. Running as the image's own user instead just
  moves the problem: the host file is owner-only, and its owner is not uid
  10001. `run`, `run-http`, `setup`, `auth-google`, `oauth-revoke` and
  `onboard-site` all did this and all failed. Everything now mounts the boundary
  file's **directory**, which is what the agent skill, the smoke test and (as of
  this release) the Compose example already did — and what unbounded onboarding
  needs anyway, since it replaces the file by rename. A test asserts the
  single-file form never comes back.
- **`rankrat.sh` — a wrapper around `docker run`.** Install it on `PATH` and
  `rankrat.sh` / `rankrat.sh http` start the published image with the mounts,
  the published port and the container hardening flags already resolved. Its
  first argument is the image's own mode, so `setup`, `auth-google`,
  `revoke-google` and `onboard-site` work the same way and every remaining
  argument is forwarded untouched. `docker run` remains the supported contract
  and the README still documents it in full; the wrapper is convenience.
- **The Makefile now calls that wrapper** for every production-image target, so
  `make run` exercises the same path a user takes instead of a second copy of
  it — which is how the mount bug above finally surfaced. That invocation
  existed in five drifting copies. `make verify-runtime-boundary` is gone with
  it: the wrapper performs those ownership and permission checks itself, for
  `docker run` users as well.
- **README is Docker-first.** The quick start creates the working layout and
  runs the image; Make is presented as what it is, the checkout workflow. The
  two things genuinely unavailable from the image alone — IndexNow key creation
  and verification — are called out rather than left implied.
- **`server.json` was rejected by the registry again**, this time with a `400`:
  an OCI package may not carry `registryBaseUrl`, and `identifier` has to be a
  canonical reference including the registry host. It now reads
  `docker.io/psyb0t/rankrat:latest` with no `registryBaseUrl`, matching the
  shape the other servers in this namespace publish with, and the release
  workflow refuses both mistakes up front.
- **`__version__` reported `0.1.0` from the v0.1.1 image.** The version in
  `pyproject.toml` had not moved with the tag. `server.json` now carries the
  `0.0.0` placeholder the publish workflow overwrites from the tag, which is one
  fewer file that can drift.

## v0.1.1 — 2026-08-03

Fixes the MCP registry publish, which was the one job the v0.1.0 tag did not
complete, and documents how to get a PageSpeed key.

- **`server.json` description was 126 characters; the registry caps it at 100.**
  It rejects the publish with a `422`, and that request is the last step of a tag
  run — the image push, the GitHub Release and the ClawHub publish had all
  already succeeded, so v0.1.0 exists everywhere except the MCP registry. The
  description is now 95 characters and matches the repository's own About text.
- **The About text now names what it reads.** It led with "security-first" and
  "boundary-limited", which say nothing to someone who has not read the code,
  and never mentioned Search Console, Bing Webmaster, GA4 or PageSpeed.
- **README documents the PageSpeed API key**: where to create it, restricting it
  to the PageSpeed Insights API, and that `pagespeed_api_key_file` takes the
  path *inside* the container (`/run/secrets/...`), not the host path the key
  was written to. PageSpeed is also called out as the one Google surface that
  does not use OAuth — the key rides on the query string, so the consent flow
  grants it nothing — and as optional, since an unset key means unauthenticated
  calls under a tighter quota rather than an error.

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
