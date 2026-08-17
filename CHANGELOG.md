# Changelog

Notable changes to Rankrat, newest first.

## v0.18.0 — 2026-08-17

Lighthouse audits now work over stdio. `rankrat` stdio brings up an ephemeral
Lighthouse sidecar for the session — the same browser-audit capability the HTTP
Compose stack has — and tears it down on exit.

- The wrapper launches the sidecar host-side over a per-session private socket
  volume, so the main app never touches the Docker socket and reaches Lighthouse
  only over the shared Unix socket, mounted read-only. The sidecar mirrors the
  Compose worker's hardening: dropped capabilities, read-only root, and a
  networkless one-shot volume initializer.
- No change to the REST/HTTP path, provider contracts, or the container images.

## v0.17.1 — 2026-08-17

Adds release-version pinning and an `upgrade` command to the host wrapper.
`rankrat setup` now pins both images to the latest release instead of tracking
the moving `:latest`, and records the pin — along with the HTTP port and
read-only flag — in a `.env` at the profile root.

- `rankrat upgrade` re-pins both `psyb0t/rankrat` and `psyb0t/rankrat-lighthouse`
  to the newest release, pulls them, restarts a running HTTP stack (reusing the
  recorded port and read-only flag), and drops the superseded images.
- `--rolling` (or `RANKRAT_ROLLING=1`) runs the moving `:latest` images for a
  single invocation without changing the recorded pin.
- `RANKRAT_IMAGE`, `RANKRAT_LIGHTHOUSE_IMAGE`, `RANKRAT_HTTP_PORT`, and
  `RANKRAT_READ_ONLY` still override the recorded values per run.
- No change to Rankrat's REST, MCP, provider contracts, or the container images
  themselves — this is host-wrapper behavior. Existing profiles keep working and
  fall back to `:latest` until the next `setup` or `upgrade`.

## v0.16.0 — 2026-08-16

Removes the `--google-oauth-client-file` setup flag. Google's Desktop OAuth
client JSON is now pasted at the same hidden prompt as every other credential —
one setup path for all providers, nothing to bind-mount.

- `rankrat setup` no longer takes `--google-oauth-client-file`, and the wrapper
  no longer reads `RANKRAT_GOOGLE_OAUTH_CLIENT_FILE` or bind-mounts a host file
  into the setup container. Paste the client JSON's single line when setup asks;
  it is validated before storage, so a bad paste is caught rather than saved.
- Migration: drop the flag and the env var from any setup scripts. Open the
  downloaded `client_secret_*.json` and paste its one line at the prompt — the
  Desktop-app JSON Google hands you is already single-line, so paste it as-is.
- No change to Rankrat's REST, MCP, provider contracts, or the OAuth flow
  itself; only how the client JSON reaches setup.

## v0.15.0 — 2026-08-16

Adds a one-command installer for the `rankrat` wrapper without changing
Rankrat's REST, MCP, or provider contracts.

- Ships `install.sh`, which places the `rankrat` wrapper on your PATH — per-user
  (no root) at `~/.local/bin/rankrat`, or system-wide (with sudo) at
  `/usr/local/bin/rankrat`. The mode auto-detects from the invoking user, with
  `--user` / `--system` to force it and `--uninstall` to remove the command; a
  per-user install that finds `~/.local/bin` off PATH prints the exact bash/zsh
  line to add it. The installer verifies the downloaded wrapper before placing
  it and warns when Docker is missing.
- A system-wide install shares only the command: Rankrat data stays in each
  user's owner-only `~/.config/rankrat` profile (override per launch with
  `rankrat --data-dir` or `RANKRAT_DATA_DIR`), which the wrapper refuses to
  share — so the security model is unchanged.
- Documents the installer as the primary "Install the wrapper" path in
  [Getting started](docs/getting-started.md), keeping the manual
  download-and-move method as a fallback.

## v0.14.2 — 2026-08-16

Completes the repaired release path without changing Rankrat's REST, MCP, or
provider contracts.

- Declares the bundled OpenClaw stdio launcher as the package extension that
  ClawHub requires, in both the package metadata and plugin manifest.
- Moves the Lighthouse worker to patched Chrome for Testing `152.0.7977.42`.
- Pins the Lighthouse worker's transitive `nanoid` dependency to `3.3.18`, the
  advisory-fixed release.
- Lets CI consume the current shared release workflows, including the corrected
  ClawHub handling for deterministic package metadata errors.

## v0.14.1 — 2026-08-15

Repairs release publication validation without changing Rankrat's HTTP, MCP, or
provider contracts.

- Updates the isolated Chrome for Testing binary used by the Lighthouse image
  to its patched release and refreshes the final base-image packages, so the
  image vulnerability gate no longer reports fixable high or critical findings.
- Makes the MCP registry descriptor comply with its description-length limit
  and locks that limit into a regression test.
- Declares the OpenClaw plugin compatibility and build metadata ClawHub
  requires, while keeping the plugin a dependency-free stdio launcher.

## v0.14.0 — 2026-08-14

Completes provider-scoped ownership verification and makes the guided setup
flow usable with the Google OAuth client file downloaded from Google Cloud.

- Accepts a regular, owner-selected Google OAuth client JSON file through the
  `rankrat setup` wrapper and imports only the client metadata needed for the
  local OAuth flow.
- Lets ownership checks and verification target Google, Bing, or both without
  contacting an unselected provider. Google uses the Site Verification API and
  Bing uses the provider-issued CNAME proof through the selected DNS adapter.
- Preserves valid tokenized query URLs during safe public fetching and site
  audits, so self-contained public video URLs remain distinct crawl targets.
- Treats Bing Webmaster authorization failures as a typed forbidden result and
  rejects unexpected successful-looking sitemap response bodies rather than
  falsely reporting a completed mutation.

## v0.13.1 — 2026-08-13

Restores a passing coverage gate and makes the release-version workflow atomic.

- Sets the repository-wide coverage floor to 90%, preserving an enforced gate
  that matches the current tested surface.
- Adds `make version V=X.Y.Z`, which updates the Python package metadata, its
  `uv.lock` self-entry, the Codex plugin manifest, the YAML-first OpenAPI
  source, and generated `openapi.json` together without creating a commit or
  tag.
- Documents all YAML OpenAPI fragments that compose the generated REST
  contract.

## v0.13.0 — 2026-08-12

Adds free, account-authorized SEO controls and diagnostics for the provider
accounts the operator already owns.

- Adds Microsoft Clarity Data Export insights, including guided setup and a
  bounded live check for its project-scoped free API.
- Adds typed Google Tag Manager account discovery and container, workspace,
  tag, trigger, variable, version, and publication operations. `rankrat
  auth-google` requests the necessary Tag Manager scopes; existing Google
  grants must be renewed after upgrading.
- Adds provider-neutral managed edge redirects. The initial Cloudflare adapter
  lists and changes only redirects marked as Rankrat-managed, leaving unrelated
  rulesets intact.
- Adds safe Bing content submission: Rankrat fetches the bounded public HTML
  page itself and does not accept caller-provided bodies, headers, or arbitrary
  destinations.
- Expands deterministic site-audit diagnostics for missing response security
  controls, duplicate `hreflang` entries, and malformed sitemaps without XML
  entity resolution.
- Adds GitHub Sponsors and the project Monero funding link through
  `.github/FUNDING.yml`.

## v0.12.0 — 2026-08-12

Simplifies operator setup around one safe, reusable Rankrat profile and one
public launcher.

- **Breaking.** Replaces `rankrat.sh` with the executable `rankrat`. Replace
  `bash rankrat.sh <mode>` with `rankrat <mode>`; a non-default profile is now
  selected explicitly with `rankrat --data-dir /absolute/path <mode>`.
- **Breaking.** Removes repository-local configuration initialization and the
  profile `.env` file. `rankrat setup` now creates the owner-only default
  profile at `$HOME/.config/rankrat`; checkout users can use
  `RANKRAT_PROFILE=/absolute/path make <target>`.
- Makes `make run`, `make auth-google`, and setup build only the Rankrat image;
  the Lighthouse image is built only for the HTTP stack and explicit browser
  audits.
- Simplifies Google OAuth commands for the ordinary one-account case and keeps
  IndexNow initialization inside the selected profile.

## v0.11.0 — 2026-08-10

Keeps Rankrat's provider surface free to use and makes its public metadata and
operator documentation precise about the remaining integrations.

- **Breaking.** Removes the paid Ahrefs, Majestic, Moz, Semrush, and
  DataForSEO adapters, their credentials, and the generic
  `backlink_report`/`backlink_aggregate` REST and MCP operations. Use
  `bing_backlink_intelligence` and `POST /v1/bing/backlink-intelligence` for
  the remaining free backlink evidence.
- Limits Cloudflare traffic/cache analytics queries to the Free-plan 24-hour
  window.
- Corrects the README, provider/security guides, OpenClaw metadata, MCP
  registry metadata, and generated OpenAPI version for the free-only surface.

## v0.10.0 — 2026-08-10

Makes each configured provider credential the authority for its full account,
adds one guided credential setup, and gives HTTP deployments a persistent
Compose-backed profile.

- **Breaking.** Changes `RANKRAT_READ_ONLY` from `true` by default to `false`.
  Set `RANKRAT_READ_ONLY=true` to omit every mutating REST route and MCP tool;
  writable mode now includes `site_onboarding_submit` without a second switch.
- **Breaking.** Removes `RANKRAT_UNBOUNDED`,
  `RANKRAT_ALLOW_AGENT_ONBOARDING`, `google_account_discovery`, and the legacy
  per-path wrapper variables. A configured provider credential now authorizes
  all supported resources that its provider account can reach; resource arrays
  in `boundaries.json` are discovered inventory and URL-containment roots.
- Adds `make setup` and `rankrat.sh setup` as an interactive provider setup:
  they print the required account-wide console permissions, accept secrets
  through hidden terminal prompts, complete Google OAuth, preserve unrelated
  accounts on reruns, and validate live provider access before succeeding.
- Makes Google and Bing account IDs optional for site onboarding when exactly
  one matching account is configured, reuses existing GA4, Search Console, and
  Bing resources, and persists the resolved account/resource inventory.
- Replaces `docker-compose.yml.example` with a runnable
  `docker-compose.yml`. `rankrat.sh http` uses the selected
  `RANKRAT_DATA_DIR` as its Compose project, generates the reviewed deployment
  when absent, preserves an existing operator file, and supports `-d` or
  `--detach` with automatic service restarts.
- Uses one shared profile layout for stdio, HTTP, setup, Claude Code, Codex,
  and OpenClaw while mounting only its fixed config, secret, OAuth, and state
  children. The repository wrapper and packaged agent reference remain
  byte-identical.
- Synchronizes the YAML-first OpenAPI contract, generated JSON, REST and MCP
  catalogs, environment template, Make targets, live checks, README manual,
  and all committed agent integrations with the new behavior.

## v0.9.1 — 2026-08-10

Reorganizes Rankrat's public documentation into a concise entry point and a
complete task-oriented manual without changing its runtime API.

- Replaces the oversized root README with a 150-line overview and adds a
  documentation index plus focused guides for setup, configuration, providers,
  transports, features, Lighthouse, ownership and onboarding, monitoring and
  remediation, security, tools, troubleshooting, and development.
- Documents the complete REST and MCP surfaces, credential and provider setup,
  boundary behavior, write gates, deployment paths, and operator workflows with
  source-verified commands and cross-links.
- Synchronizes the Codex skill, OpenClaw plugin guide, embedded setup reference,
  and launcher documentation across stdio and Streamable HTTP MCP.
- Corrects the documented Google discovery, GA4 mutation, HTTP bearer, OAuth
  failure-log, and unknown-environment-variable behavior.

## v0.9.0 — 2026-08-08

Adds a persistent SEO intelligence layer while preserving the same strict
boundary, transport, and read-only discovery semantics.

- Adds persistent site-audit monitors, immutable snapshots, issue lifecycle
  history, manual runs, and a bounded HTTP scheduler backed by an owner-only
  SQLite database. Monitor and Cloudflare mutation tools remain absent from
  read-only servers.
- Adds internal-link graphs, orphan-page joins, deterministic missing-link
  opportunities, and content opportunities that combine Search Console, Bing,
  GA4, and bounded crawl evidence.
- Adds Chrome UX Report history and bounded Cloudflare hourly analytics, exact
  URL purges, and two named cache templates that preserve unmanaged rules.
- Adds normalized backlink adapters for Ahrefs, Majestic, Moz, Semrush, and
  DataForSEO alongside Bing, plus cross-provider deduplication. Provider
  readiness validates commercial credentials through a one-result query
  against the account's first allowed target. Each call has one deadline and a
  shared 20-request provider budget; duplicate aggregate sources are rejected.
- Serializes Cloudflare cache-template mutations per zone so concurrent callers
  cannot both create the first Rankrat-managed rule.
- Exposes the complete surface through YAML-first OpenAPI, REST, MCP stdio, and
  Streamable HTTP MCP, with strict typed inputs, mocked external-provider
  contracts, transport-parity tests, persistent state mounts, and synchronized
  setup and agent documentation.
- Pins the Lighthouse test toolchain's transitive Nano ID dependency to the
  first patched 3.x release for CVE-2026-67213, and gives cold image stdio
  probes a bounded 60-second budget so loaded Docker hosts do not produce
  false-negative release smokes.

## v0.8.0 — 2026-08-07

Makes site-ownership automation DNS-provider-neutral before additional DNS
adapters are introduced.

- Replaces the Cloudflare-shaped `cloudflare_zones[].id` boundary with
  `dns_zones[].provider_zone_id`. The configured DNS account selects the
  internal provider adapter.
- Renames `site_ownership_status` to `site_ownership_check` and moves the REST
  operation from `POST /v1/site-ownership-status-checks` to
  `POST /v1/site-ownership-checks`.
- Renames `site_ownership_apply` to `site_ownership_verify`, and replaces the
  request field `cloudflare_account_id` with `dns_account_id`. Read-only
  ownership checks no longer require a DNS account.
- Keeps provider-specific credentials and record translation behind the DNS
  provider protocol, while preserving the same strict authorization,
  verification-value redaction, and bounded-write controls.
- Synchronizes the YAML-first OpenAPI source, generated JSON, REST and MCP
  contracts, setup guidance, README, and agent integrations. No compatibility
  aliases are retained during the pre-1.0 API phase.

## v0.7.0 — 2026-08-06

Adds a bounded SEO improvement loop: ownership automation, deterministic
whole-site audits, discovery remediation, and backlink intelligence.

- Adds Cloudflare-backed Google and Bing ownership automation. Rankrat requests
  provider-issued proof material, creates only the exact Google TXT and Bing
  CNAME records in an authorized zone, checks public DNS propagation, and
  redeems ownership without exposing verification values or generic DNS CRUD.
- Adds `site_ownership_status` at
  `POST /v1/site-ownership-status-checks` and `site_ownership_apply` at
  `POST /v1/site-ownership-verifications`. Ownership completion remains
  asynchronous and explicitly pollable.
- Adds `site_audit` at `POST /v1/site-audits`, with a DNS-pinned,
  proxy-disabled, redirect-disabled crawler that stays beneath a configured
  public HTTPS site and returns bounded evidence, scores, findings, and
  deterministic remediation guidance.
- Adds `site_remediation_apply` at `POST /v1/site-remediations` for bounded
  Google and Bing sitemap resubmission plus Bing changed-URL submission.
  Multi-provider writes are sequential and report failures without claiming
  transactional rollback.
- Adds `bing_backlink_intelligence` at
  `POST /v1/bing/backlink-intelligence`, walking bounded Bing backlink pages
  and aggregating referring domains and anchor text for owned sites.
- Keeps read-only discovery free of mutation tools and exposes the same strict
  contracts through REST, stdio MCP, and Streamable HTTP MCP. The YAML-first
  OpenAPI source, generated JSON, setup configuration, README, and agent
  integrations describe the complete surface.
- Hardens provider responses, DNS parsing, crawl limits, SSRF defenses, secret
  handling, and the production Cloudflare secret mount. The production images
  pass stdio, authenticated REST, Streamable HTTP, and real Chromium
  Lighthouse smokes.

## v0.6.0 — 2026-08-06

Makes the published OpenClaw integration a self-contained, hardened Docker
stdio launcher while keeping shared deployments on native Streamable HTTP.

- The static OpenClaw MCP definition now starts Rankrat from the standard
  `$HOME/.config/rankrat` layout even under OpenClaw's restricted child
  environment. Direct `rankrat-mcp` invocations retain explicit environment
  overrides for custom config, credential, OAuth, and image paths.
- The launcher passes every Docker option as an argument without a shell,
  rejects symlinked path ancestry, and validates file type, owner, and mode
  before making `/run/config` writable for unbounded operation or agent
  onboarding. Provider secrets stay read-only and OAuth storage remains
  writable for refresh-token rotation.
- The static server deliberately stays bounded and read-only. The plugin and
  skill now direct custom paths, writes, onboarding, and the optional isolated
  Lighthouse worker through Rankrat's native Streamable HTTP transport.
- The repository wrapper and the copy bundled with the agent skill remain
  byte-identical, and the agent integration documents both MCP transports and
  their credential, boundary, and browser-worker security constraints.

## v0.5.0 — 2026-08-06

Adds boundary-limited local Lighthouse audits through an isolated Chromium
companion and keeps the complete feature available over every Rankrat transport.

- Adds `lighthouse_audit`, `lighthouse_seo_findings`,
  `lighthouse_accessibility_findings`, `lighthouse_performance_findings`, and
  `lighthouse_best_practices_findings` over stdio MCP and Streamable HTTP MCP.
  Matching REST operations are available at `POST /v1/lighthouse/audits`,
  `/seo-findings`, `/accessibility-findings`, `/performance-findings`, and
  `/best-practices-findings`.
- Adds the separate `psyb0t/rankrat-lighthouse` image. It receives no provider
  credentials, exposes only a private Unix socket, serializes expensive audits,
  bounds subprocess time and output, and permits browser traffic only through a
  public-address policy proxy. Requested and final document URLs must remain
  inside an account's configured `pagespeed_sites` boundary.
- Adds a hardened two-image Compose example, a real production-image smoke that
  exercises all five operations over all three transports, and independent
  worker tests for request validation, Chrome failure handling, HTTP and CONNECT
  proxy policy, report projection, concurrency, cancellation, and cleanup.
- Adds exact, age-gated pnpm locks for the TypeScript worker; digest-pinned
  browser and scanner images; checksum-verified Chrome for Testing; separate
  SBOM and fixable-high image gates; and a second tag-published Docker image.
- Resolves Docker Official Node and Python bases through Amazon ECR Public,
  shell tooling through Google's registry mirror, and the Anchore scanners
  through GHCR while preserving their reviewed immutable digests, so stale
  Docker Hub credentials cannot block Rankrat release gates.
- Documents the local browser's trusted-site scope. Chromium runs without its
  renderer sandbox inside the capability-free worker container, so untrusted
  pages require a stronger outer runtime such as gVisor or Kata Containers.
- Keeps the README, OpenAPI source and generated document, agent skill, embedded
  `rankrat.sh`, Claude/Codex manifests, and OpenClaw bridge synchronized with the
  new tools and both MCP transports.
- Forwards `RANKRAT_ALLOW_AGENT_ONBOARDING` through the wrapper and OpenClaw
  launcher, while keeping read-tool discovery stable and write tools hidden
  unless their explicit runtime switches enable them.

## v0.4.1 — 2026-08-05

Remediates the published image's transitive cryptography advisory and restores
Dependabot compatibility.

- Upgrades every build stage from uv 0.8.8 to the immutable uv 0.11.31 image
  and upgrades the locked `cryptography` package from 49.0.0 to 50.0.0, which
  contains the PKCS#7 decryption fix for CVE-2026-69247.
- Keeps the seven-day dependency cooldown for the rest of the graph while using
  a package-specific cutoff that admits the first fixed cryptography release.
- Removes the obsolete pip-audit suppression and OpenVEX statement for
  cryptography 49.0.0. The generated production SBOM now contains
  cryptography 50.0.0 and produces no cryptography match in the image scan.
- Gives cold-started stdio MCP image checks a 30-second timeout budget. The
  prior 10-second process timeout could kill a correct response on a loaded
  Docker host; the container memory and CPU limits are unchanged.

## v0.4.0 — 2026-08-05

Answers "where is this site filed, and does its tag point at the property I am
reading" without the Google Analytics UI.

- **`google_analytics_data_streams`** — a read-only tool and
  `POST /v1/google-analytics/data-streams`, returning a configured property's
  data streams with their `G-` measurement IDs. This closes a real trap: a tag
  whose measurement ID belongs to a different property looks correctly installed
  and reports into a property nobody reads, and confirming the match previously
  required the web UI. Bounded by the same per-property allow-list as every other
  GA4 read, and present on read-only servers. App streams carry no
  `webStreamData`, so the measurement ID and URI come back null rather than
  failing the read.
- **`google_analytics_account_rename` and `google_analytics_property_rename`** —
  writable mode only, over MCP and `POST /v1/google-analytics/account-renames`
  and `/property-renames`. GA4 account names are cosmetic; the numeric ID is what
  boundaries, measurement IDs and reports bind to, so renaming an account is the
  cheapest fix for a property filed under an unrelated one. Property renames are
  gated per-property; account renames ride the existing
  `google_account_discovery` switch, since a rename reaches an account-wide
  resource rather than a listed one.
- **Nothing creates or deletes a GA4 container.** `accounts.delete` soft-deletes
  an entire container and everything beneath it and is deliberately not wrapped.
  Account *creation* is not implementable at all — the Admin API has no
  `accounts.create`, only `provisionAccountTicket`, which must be completed in
  the UI.
- **The onboarding guide now hands over the click path for what it cannot do.**
  A caller with no GA4 account previously hit a dead end: onboarding creates a
  property *inside* an account, the Admin API has no `accounts.create`, and
  nothing said where to go instead. The guide's new `manual_provisioning` block
  names the resource, why no tool can create it, the start URL
  (`https://analytics.google.com`) and the ordered steps — Admin, Create →
  Account, name it, accept the Terms of Service, then read the numeric ID back
  with `google_analytics_account_inventory`. It also describes
  `accounts:provisionAccountTicket` explicitly as *not* an automation escape
  hatch, because it returns a ticket that still has to be carried into a Terms
  of Service page a human accepts.
- **The guide is now on the REST API too** — `POST /v1/onboarding-guides`,
  returning the identical document the MCP resource and tool serve. It was
  MCP-only before, which left every non-MCP caller without the procedure.
- Renames send a `PATCH` with an explicit `updateMask` and verify that the
  response names the resource that was requested, so a response describing a
  different account or property is rejected rather than reported as success.
- **OpenClaw now receives Rankrat through its native static MCP-server
  declaration.** The plugin no longer registers a process launcher as runtime
  extension code or proxies Streamable HTTP through `mcp-remote`. Stdio still
  runs the published image directly; shared HTTP deployments use OpenClaw's
  direct Streamable HTTP client with an environment-backed bearer header, so the
  bearer does not appear in child-process arguments or proxy logs.
- **`make test-local` is a deliberate registry-outage fallback.** It validates
  that the exact versioned development image is already local, then runs the
  same ephemeral test containers without resolving image metadata remotely.
  Normal `make test` and `make lint` still rebuild from pinned bases.
- **Provider failures no longer carry upstream detail across a public
  transport.** REST, stdio MCP and Streamable HTTP MCP preserve the bounded
  `AUTHENTICATION`, `AUTHORIZATION`, `RATE_LIMITED`, `NOT_FOUND`,
  `INVALID_RESPONSE` or `UPSTREAM` category, but replace the provider message
  with `provider operation failed`. OAuth details, key-bearing URLs and raw
  provider responses therefore cannot escape through an error envelope.
- **The production-image smoke test now exercises complete MCP exchanges on
  both transports.** It initializes, lists tools and calls `server_info` over
  stdio and Streamable HTTP, and proves the HTTP MCP endpoint rejects an
  unauthenticated request. This catches an image that starts but cannot serve a
  real MCP client.
- **`make test-live` is the complete configured-system gate.** It runs every
  provider-specific live target in sequence, then reads configured data through
  the shipped authenticated REST and Streamable HTTP MCP server. The production
  service receives only the explicit runtime settings it needs rather than the
  development `.env`, and its boundary file is copied into an owner-only
  temporary config directory before the read-only mount.
- **Local setup and IndexNow verification reject path substitution.**
  `make setup` refuses symlinked config, OAuth and secret trees and normalizes
  directories to mode `0700` and sensitive files to mode `0600`.
  `make verify-indexnow-key` mounts the exact operator-selected boundary and key
  files read-only, so `BOUNDARIES` and `INDEXNOW_KEY_FILE` overrides are honored
  instead of silently checking the default paths.
- **The image scan now carries a reviewable exception for the transitive
  `cryptography` PKCS#7 advisory.** The OpenVEX statement names the locked
  package version and unreachable decryption path; a security regression test
  ties that statement, the `pip-audit` exception, the lockfile and the absence
  of affected entry-point usage together. Fixable high or critical findings
  outside an applicable VEX statement still fail the release.

## v0.3.0 — 2026-08-04

Drops the GA4 parent-account pin from the boundary file.

- **Breaking. `google_analytics_parent_account_id` is gone from the boundary
  file.** It constrained exactly one thing — which GA4 account a newly created
  property was filed under — and constrained nothing else: GA4 reads are gated
  per-property by `ga4_properties`, and account discovery already returned every
  account the credential could see. For an operator whose GA4 accounts all sit
  under one Google identity it bought nothing, while quietly guaranteeing that
  every property onboarding created landed under whichever account happened to
  be named there, forever.
- The parent account is now supplied by the caller on each onboarding request,
  where it already could be, and nothing validates it against the boundary file.
  The credential account is still pinned; which of that identity's own GA4
  accounts the property lands under is now the caller's decision per call.
- **Migration:** delete the `google_analytics_parent_account_id` line from every
  account in `boundaries.json`. The document is parsed with unknown fields
  forbidden, so leaving it in place fails startup with
  `invalid Rankrat boundary configuration` and no further detail.

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
