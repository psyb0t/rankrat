# rankrat

<!-- mcp-name: io.github.psyb0t/rankrat -->

[![CI](https://github.com/psyb0t/rankrat/actions/workflows/pipeline.yml/badge.svg?branch=main)](https://github.com/psyb0t/rankrat/actions/workflows/pipeline.yml)
[![coverage](https://raw.githubusercontent.com/psyb0t/rankrat/badges/coverage.svg)](https://github.com/psyb0t/rankrat/actions/workflows/pipeline.yml)
[![version](https://raw.githubusercontent.com/psyb0t/rankrat/badges/version.svg)](https://github.com/psyb0t/rankrat/tags)
[![license](https://raw.githubusercontent.com/psyb0t/rankrat/badges/license.svg)](LICENSE)

Your SEO data has been sitting in four different dashboards that don't talk to
each other. rankrat rats all of it out to an agent through one MCP server —
Google Search Console, Bing Webmaster Tools, GA4, and PageSpeed Insights — so
you can ask "why did this page fall off a cliff" instead of opening four tabs
and eyeballing charts.

Read-only unless you say otherwise, and scoped to the properties you list. The
agent can't wander into an account you didn't hand it, and it can't change
anything on a provider. Speaks MCP over stdio and Streamable HTTP, plus a plain
JSON API for things that don't speak MCP.

> [!WARNING]
> This reads real analytics for real properties you own. It is not a rank
> tracker and it cannot query domains you haven't verified — if that's what you
> came for, this is the wrong tool.

## Contents

- [Status](#status)
- [Quick start](#quick-start)
- [Agent integrations](#agent-integrations)
- [Provider credentials](#provider-credentials)
- [Run modes](#run-modes)
- [What the live targets prove](#what-the-live-targets-prove)
- [Boundary configuration](#boundary-configuration)
- [Security model](#security-model)
- [Development](#development)
- [Live provider verification](#live-provider-verification)
- [Layout](#layout)
- [License](#license)

## Status

Current implementation: validated immutable boundaries; fixed-origin Google
Search Console property listing/get, Search Analytics, sitemap listing, URL
inspection, and Indexing notification metadata; configured Bing site, keyword,
crawl, rank/traffic, feed, link,
quota, and URL-information reads; matching REST/MCP transports; and guarded
IndexNow, Bing URL/sitemap/property submissions, Google Indexing notifications,
Google property mutations, and Google sitemap mutations for explicitly
configured targets. GA4 historical and realtime reports plus fixed content,
landing-page, session-source, item-level ecommerce, audience-segment, and
new-versus-returning user-behavior reports are available for configured
properties. PageSpeed analyses are available only for configured child URLs.
Search Console aggregate and period-comparison reports are
available for configured properties, along with typed fixed-dimension reports
for queries, pages, countries, search appearances, time series, period-drop
attribution by query or page, ascending daily trends, deterministic daily
anomalies, and page performance. Local raw HTML and JSON-LD eligibility checks,
plus bounded public-HTTPS page validation, are available without credentials.
Bing has typed daily traffic
trends, deterministic anomalies, and exact period comparisons from its fixed
rank-and-traffic report, typed top-query and top-page performance reports, and
local query/page opportunity reports. It also exposes a local query
cannibalization signal, literal brand/non-brand query analysis, and fixed
ranking buckets over Bing's fixed query reports. It also exposes one bounded
GA4/PageSpeed correlation for exact configured GA4 and PageSpeed accounts, a
site, and child URL; a bounded Search Console/Bing comparison that keeps each
engine's traffic observations separate; a bounded Search Console/Bing daily
traffic-health report that preserves each engine's anomaly observations; and a bounded GA4/Search Console
comparison that keeps linked GA4 organic-search and Search Console observations
separate. Broader cross-provider derived reports, including claims that need a
persisted historical Bing snapshot, are intentionally outside this no-database
release rather than presented as falsely precise live data.

Every provider read that Rankrat exposes is mapped at its HTTP boundary into a
bounded immutable result type. In particular, Search Console site metadata,
Search Analytics rows, sitemap records, and URL Inspection index-status fields
are not relayed as generic Google JSON objects.

## Quick start

Every supported workflow is a Makefile target.

```sh
make setup
```

`make setup` creates the ignored local layout without overwriting anything,
then stops at the first missing credential or authorization and prints the
exact host path or next Make command. It runs the direct provider checks for
Google Search Console, GA4, PageSpeed, and Bing, then starts the **shipped
production image** on Docker's default egress bridge and verifies its authenticated
REST and Streamable HTTP MCP paths against those same configured accounts.
Provider checks are independently runnable:

```sh
make test-live-google-search-console
make test-live-google-analytics
make test-live-pagespeed
make test-live-bing
make test-live-indexnow
make test-live-http
```

`make test-live-indexnow` performs a real submission only when its existing
double opt-in environment setting is true; otherwise it is safely skipped.
`make setup` deliberately does **not** run that target. It never submits an
IndexNow URL. `make test-live-http` is non-mutating: it checks `/ready`, MCP
`initialize`, configured account routing, Search Console readiness/Search
Analytics, GA4 inventory/reports, PageSpeed, and Bing readiness/traffic for
the resources actually present in `config/boundaries.json`.

The examples contain only fake resources and secret-file paths. Keep real
credential files under `secrets/`; it is gitignored and excluded from images.
The Compose example mounts only the individually named files it needs, never the
whole directory.

## Agent integrations

The [skill](.agents/skills/rankrat) works in any agent that reads
`.agents/skills/`, and installs natively in the clients below.

There is no MCP bridge plugin here and there doesn't need to be — rankrat's
default mode already speaks MCP over stdio, so any MCP client can just spawn it:

```sh
docker run -i --rm -v "$PWD/config:/run/config:ro" psyb0t/rankrat stdio
```

### Claude Code

```sh
claude plugin marketplace add psyb0t/agents
claude plugin install rankrat@psyb0t
```

Claude Code prompts for the rankrat URL and, if the server was started with
bearer auth, the token — which it stores in your OS keychain rather than a
settings file.

### Codex

```sh
codex plugin marketplace add psyb0t/agents
codex plugin add rankrat@psyb0t
```

Installed this way the skill invokes as `$rankrat:rankrat`. Codex also picks the
skill up on its own in any repo containing `.agents/skills/` — no install
needed — and there it invokes as plain `$rankrat`.

### OpenClaw

The skill is published to ClawHub on every release:

```sh
openclaw skills install @psyb0t/rankrat
```

## Provider credentials

Rankrat uses four separate credential arrangements. Do not create a Google
service-account JSON for Rankrat: its Google integration is deliberately
user-delegated OAuth, so it acts only as the Google user who completed
`make auth-google`.

| What it enables | What to create | Where it belongs |
| --- | --- | --- |
| Search Console, GA4, and eligible Google Indexing operations | One **Desktop app** OAuth client JSON | `secrets/google/oauth-client.json` |
| PageSpeed Insights automation | One restricted Google API key | `secrets/google/pagespeed-api-key` |
| Bing Webmaster reads and explicitly approved writes | One Bing Webmaster API key | `secrets/bing/api-key` |
| IndexNow ownership and explicitly approved submissions | A locally generated opaque key | `secrets/indexnow/key` |

All credential paths are local-only: `secrets/`, `oauth/`, `.env`, and
`config/boundaries.json` are ignored by Git. Create every secret file with owner-only
permissions (`chmod 600 path/to/file`). Never paste a credential into a shell
history, a Makefile, a boundary JSON file, an issue, or a chat transcript.

`make init-config` creates the ignored directories and copies the two public
templates without overwriting existing local files. These are the standard host
paths and their matching container paths:

| Purpose | Host path | Container path |
| --- | --- | --- |
| Google OAuth client | `secrets/google/oauth-client.json` | `/run/secrets/google/oauth-client.json` |
| Google PageSpeed key | `secrets/google/pagespeed-api-key` | `/run/secrets/google/pagespeed-api-key` |
| Bing Webmaster key | `secrets/bing/api-key` | `/run/secrets/bing/api-key` |
| IndexNow key | `secrets/indexnow/key` | `/run/secrets/indexnow/key` |
| HTTP bearer secret | `secrets/rankrat/http-bearer-token` | `/run/secrets/rankrat/http-bearer-token` |
| Write-approval bearer secret | `secrets/rankrat/admin-bearer-token` | `/run/secrets/rankrat/admin-bearer-token` |
| Google refresh-token record | `oauth/google.json` | `/run/oauth/google.json` |

### Read/write prerequisite checklist

An OAuth client JSON or API key identifies Rankrat to a provider; it does
**not** make the signed-in user an owner of a site or grant them an Analytics
role. Configure the credential, grant the human account the relevant
provider-side access, and restrict Rankrat to the intended resources in
`config/boundaries.json`.

| Capability | Provider-side prerequisite | Rankrat credential and configuration |
| --- | --- | --- |
| Search Console and GA4 reports | The Google user can access the selected Search Console property and GA4 property. | Desktop OAuth client JSON, required Google APIs enabled, then `make auth-google`; add the exact site/property to the boundary, or enable read-only account discovery. |
| Search Console site and sitemap writes | The Google user is permitted to manage the selected Search Console property. | The same OAuth flow requests the full `webmasters` scope. Enable Rankrat writes and use a one-time approval for the exact configured property. |
| GA4 new-site onboarding | The Google user can create a property under the selected Google Analytics **account**. | Enable Analytics Admin API; set that account's numeric `google_analytics_parent_account_id`; re-authorize with `make auth-google`; enable Rankrat writes and use a one-time onboarding approval. |
| Google Indexing notifications | The Google user has the required Search Console ownership. The URL is an eligible `JobPosting` or livestream `VideoObject` page. | Enable Indexing API; the OAuth flow requests its `indexing` scope. Enable writes and approve the exact configured URL or batch. |
| PageSpeed automation | None beyond a Google Cloud project; the key should be restricted to PageSpeed Insights API. | Put the restricted API key in `secrets/google/pagespeed-api-key`, configure `pagespeed_api_key_file`, and allow the exact HTTPS `pagespeed_sites` boundary. |
| Bing reads and writes | The Bing user has added and verified each site. | Generate that user's Bing Webmaster API key, store it at `secrets/bing/api-key`, and allow each exact HTTPS site. Writes additionally need Rankrat's write gate and a one-time approval. |
| IndexNow submissions | The site serves the generated `<key>.txt` at its public key-file URL. | Run `make init-indexnow`, deploy the key file, run `make verify-indexnow-key`, then enable writes and approve the exact URLs. |

For the single Google consent flow, `make auth-google` requests fixed,
purpose-limited scopes: Search Console management (`webmasters`), Indexing,
GA4 read-only, and GA4 edit. It does not grant access to unrelated Google
products, bypass provider-side ownership checks, enable Cloud APIs, or turn on
Rankrat writes by itself.

### Enable Rankrat write operations

Provider permission alone is deliberately insufficient. Before any write route
or destructive MCP tool is available, complete **all** of the following:

1. Put the intended site, GA4 property, Bing property, or IndexNow target in
   `config/boundaries.json`. Rankrat will not accept a caller-supplied account
   or arbitrary target outside that file.
2. Set `RANKRAT_ENABLE_WRITES=true` in the ignored `.env` used by the running
   process.
3. Create an owner-only, at-least-32-character admin bearer secret at
   `secrets/rankrat/admin-bearer-token`, run `chmod 600` on it, and set
   `RANKRAT_ADMIN_BEARER_SECRET_FILE=/run/secrets/rankrat/admin-bearer-token`.
   This authenticates only approval-minting endpoints; it is separate from
   provider credentials and from the normal HTTP bearer secret.
4. For an HTTP deployment, also create
   `secrets/rankrat/http-bearer-token` with owner-only permissions and set
   `RANKRAT_HTTP_BEARER_SECRET_FILE=/run/secrets/rankrat/http-bearer-token`.
   This is required for a non-loopback HTTP host and protects normal REST/MCP
access; `GET /healthz` remains public.

### What the live targets prove

The two live layers are intentional and answer different questions:

| Target | What it uses | What it proves |
| --- | --- | --- |
| `make test-live-google-search-console` (and the GA4, PageSpeed, Bing variants) | The real provider client in the pinned development image | Provider credential, scope, and provider-response handling in isolation. |
| `make test-live-http` | The real production image, authenticated `/v1/` REST routes, and Streamable HTTP MCP on Docker's default egress bridge | The image entrypoint, mounted configuration, bearer auth, HTTP/MCP transport, route wiring, service wiring, and real provider access together. |
| `make verify-indexnow-key INDEXNOW_TARGET_ID=...` | The public deployed ownership file | IndexNow ownership-file deployment without submitting a URL. |
| `make test-live-indexnow` | The real IndexNow endpoint | A real URL notification only after the separate existing double opt-in is set. |

The production transport verifier never publishes a host port, never prints
bearer tokens, OAuth records, API keys, or provider response bodies, and removes
only the exact temporary container it started. It is deliberately
read-only. Provider writes remain behind the normal write switch and one-time
approval protocol, and should be verified as a separately authorized operation.
5. Use the admin bearer to mint a short-lived, single-use approval whose
   account, operation, and resource exactly match the intended write. Submit
   that approval once through the corresponding REST route or MCP tool.

The write switch and bearer secrets do not enlarge provider permissions. They
only allow Rankrat to use the least privilege already granted by the configured
OAuth login, API key, or IndexNow key.

### Google: one OAuth login for Search Console, GA4, and Indexing

1. Open the [Google Cloud console](https://console.cloud.google.com/) and
   select or create one project for Rankrat.
2. Open [Google Auth platform](https://console.cloud.google.com/auth/overview).
   Complete the branding/contact fields. For a personal project, choose
   **External** and keep it in **Testing**; then open
   [Audience](https://console.cloud.google.com/auth/audience) and add every
   Google account that will run `make auth-google` as a test user. This avoids
   Google's `Error 403: access_denied` test-user block.
3. Enable these APIs in that same Cloud project. Use the links directly, select
   the project if prompted, then click **Enable**:

   - [Google Search Console API](https://console.cloud.google.com/apis/library/searchconsole.googleapis.com)
   - [Google Analytics Data API](https://console.cloud.google.com/apis/library/analyticsdata.googleapis.com)
   - [Google Analytics Admin API](https://console.cloud.google.com/apis/library/analyticsadmin.googleapis.com)
   - [Google Indexing API](https://console.cloud.google.com/apis/library/indexing.googleapis.com)
   - [PageSpeed Insights API](https://console.cloud.google.com/apis/library/pagespeedonline.googleapis.com)

4. Open [Google Auth platform → Clients](https://console.cloud.google.com/auth/clients),
   click **Create client**, choose **Desktop app**, give it a recognisable name
   such as `rankrat-local`, create it, and download the JSON. Put that download
   at `secrets/google/oauth-client.json`. This is an OAuth **client** JSON,
   not a service-account JSON; its top-level object is normally named
   `installed`.
5. In [Google Search Console](https://search.google.com/search-console), make
   sure the same Google user is an owner or has the required permission on the
   site property. Prefer a Domain property for the whole hostname family; use
   a URL-prefix property only when its narrower boundary is intentional.
6. In [Google Analytics](https://analytics.google.com/), make sure that same
   Google user has access to every GA4 property that Rankrat should read. The
   property ID Rankrat needs is the numeric GA4 property ID, not a Measurement
   ID such as `G-...`.
7. Configure the Google account in the local boundary file, then run:

   ```sh
   make auth-google
   ```

   Open the printed URL in a browser on the same host, sign in as the user from
   steps 5–6, grant the requested consent, and wait for the browser to say
   `Authorization complete`. The callback is loopback-only and the resulting
   refresh token stays under the ignored `oauth/` directory. One consent flow
   requests Search Console management, Google Indexing, and GA4 read/edit
   scopes; it does not give Rankrat unrestricted Google-account access or
   bypass the provider-side permissions from steps 5–6.

Google's Indexing API is *not* a general site-submission shortcut. Rankrat will
only enable an `URL_UPDATED` notification after its local eligibility check
finds a `JobPosting` or a `BroadcastEvent` inside a `VideoObject`; ordinary
pages, posts, category pages, and sitemaps should use normal crawling,
Search Console sitemaps, and IndexNow instead.

### PageSpeed: a separate restricted API key

PageSpeed does not use the OAuth refresh token. In the same Google Cloud
project, open [APIs & Services → Credentials](https://console.cloud.google.com/apis/credentials),
click **Create credentials → API key**, then immediately restrict the key:

1. Under **API restrictions**, select **Restrict key** and choose only
   **PageSpeed Insights API**.
2. Keep the key server-side in `secrets/google/pagespeed-api-key`; do not add a
   browser referrer restriction because Rankrat uses it from a local container,
   not a browser.
3. Add `"pagespeed_api_key_file": "/run/secrets/google/pagespeed-api-key"` and
   explicit HTTPS `pagespeed_sites` entries to the corresponding Google account
   boundary. OAuth account discovery and Search Console property access do not
   authorize PageSpeed URLs.

The PageSpeed API can be called anonymously, but Google documents an API key as
the reliable choice for automated use. Rankrat never returns the key or writes
it into its logs, provider URLs, errors, or result objects.

### Bing Webmaster: one API key for your verified sites

1. Open [Bing Webmaster Tools](https://www.bing.com/webmasters/) and sign in.
2. Add and verify each site Rankrat will be allowed to see. The same account
   must own or have access to the site.
3. In the portal, click the top-right **Settings** control, open **API Access**,
   accept the terms if this is the first use, then click **Generate API Key**.
   Bing issues one key per user, not per site, so that one key can cover all
   sites that user has verified.
4. Save it as `secrets/bing/api-key` and configure only the exact allowed
   HTTPS sites under the Bing account in the local boundary file.

The Bing key is enough for its configured sites; it is not a Microsoft-account
password and it does not grant access to arbitrary Bing properties. Rotate it
in the same **API Access** screen if it is ever exposed.

### IndexNow: no dashboard key to buy or copy

Choose a stable target ID and public DNS hostname, then run:

```sh
make init-indexnow INDEXNOW_TARGET_ID=my-site INDEXNOW_HOST=www.example.com
```

This generates `secrets/indexnow/key`, adds exactly that target to the ignored
boundary file, fills its two IndexNow live-check settings in `.env`, and leaves
writes disabled. Deploy the generated root `<key>.txt` file with your own site
build or hosting workflow, then verify it without submitting anything:

```sh
make verify-indexnow-key INDEXNOW_TARGET_ID=my-site
```

The verifier accepts only a direct HTTPS `200` response with exact key content;
it rejects redirects, oversized responses, unsafe DNS answers, and mismatches.

IndexNow is a notification protocol, not proof that a page is indexed. Its
write path remains separately disabled until an operator explicitly enables it
and consumes a short-lived approval for exact URLs.

## Run modes

The production image defaults to stdio MCP and reserves stdout for protocol
frames. Logs go to stderr.

```sh
make run
```

For local HTTP development:

```sh
make run-http
```

Before running it, create an owner-only opaque bearer secret at
`secrets/rankrat/http-bearer-token`; `make run-http` refuses to start without
that file. The target binds Rankrat to the container network interface, mounts
the secret read-only, and publishes only `127.0.0.1:8080` on the host. The HTTP
service provides unauthenticated `GET /healthz`, protected `GET /ready`, REST
under `/v1/`, and Streamable HTTP MCP at `/mcp/`.

`docker-compose.yml.example` is the hardened HTTP deployment shape. Copy it to
the gitignored `docker-compose.yml`, create the individually referenced files under
`secrets/`, and edit the local boundary file before starting it. Add one
explicit Compose secret and service attachment for each configured credential;
remove unused boundary accounts and secret attachments together. It builds
locally; replace `build:` with an immutable image digest after a published
release exists. It uses Docker's default bridge because some host firewalls
block the GA4 Admin endpoint from user-defined bridges; it still publishes only
the loopback HTTP port and retains the container's network namespace.

## Boundary configuration

`config/boundaries.json` is the sole source of account and resource
authorization. MCP and REST callers cannot add accounts, select credentials,
or override resource identifiers. A Google OAuth account may explicitly opt
into account-wide **read** discovery; it can then enumerate the Search Console
sites and GA4 accounts/properties visible to that one Google login. This never
widens any write operation.

```json
{
  "accounts": [
    {
      "id": "google",
      "provider": "google",
      "credential": "/run/secrets/google/oauth-client.json",
      "oauth_token_file": "/run/oauth/google.json",
      "google_account_discovery": true,
      "search_console_sites": ["https://example.com/"]
    }
  ],
  "indexnow_targets": []
}
```

`credential` is a file path, never a secret value. Rankrat never returns
credential paths, values, access tokens, or upstream error bodies. Google
Search Console, GA4, and Indexing load only the exact configured OAuth client
and owner-only refresh-token record. PageSpeed uses a separate optional API-key
file under the configured secret root; without one it uses PageSpeed's
anonymous request shape. The one-time authorization flow requests Rankrat's
fixed Google account-data scope set; each runtime operation still enforces its
configured resource boundary and calls fixed Google origins with redirects and
proxy inheritance disabled.

### Google OAuth setup

For user-delegated Google access, create an installed-app OAuth client in Google
Cloud and mount its downloaded JSON as a named secret file. Configure the
account with a unique `oauth_token_file` below
`RANKRAT_OAUTH_TOKEN_ROOT`; the example uses `/run/oauth/google.json`.
That mount is separate from `secrets/`, is gitignored, and must be writable only
by the same non-root UID that runs Rankrat.

Authorize the exact preconfigured account with the containerized operator flow:

```sh
make init-config
make auth-google
```

The command prints a one-time Google URL, opens no embedded browser, and waits
for the browser redirect. Its container listens on a fixed port that Docker
publishes only to host `127.0.0.1`; it has no host-network mode, no added Linux
capabilities, and no writable path other than `oauth/`. The code/state exchange
uses PKCE S256, explicit Google consent, and an external browser so each
authorization obtains fresh offline refresh material. Only refresh material is atomically
stored; access tokens, authorization codes, state, and verifier values are
never persisted, logged, or exposed as MCP/REST tools.

Set `"google_account_discovery": true` on that OAuth account to let its
read-only tools discover every Search Console site and every GA4
account/property the authorized Google user can access. The normal
`make auth-google` flow already obtains the required Google permissions, so no
second consent is needed after enabling discovery. Discovery is deliberately
not a write grant: Google site,
sitemap, and Indexing mutations still require an explicit configured Search
Console property, the write startup flag, and a single-use admin approval.

If authorization fails, Rankrat appends one redacted JSON line to
`oauth/google-auth.log` beside the configured token file. It records only the
time, fixed authorization stage, and stable failure category. It never stores
or prints the Google response body, authorization code, client secret, access
token, or refresh token.

Use the same host UID/GID for the runtime so it can read and rotate the
owner-only record. The Make targets do this automatically. For Compose, export
`RANKRAT_UID=$(id -u)` and `RANKRAT_GID=$(id -g)` before `docker compose up`.
To remove the stored authorization both remotely and locally:

```sh
make oauth-revoke
```

### Google Analytics 4 setup

For a least-privilege fixed scope, add numeric GA4 property IDs to a configured
Google account's `ga4_properties` allowlist. Alternatively,
`google_account_discovery: true` permits reads of every GA4 property visible to
that account's OAuth grant. `google_analytics_account_inventory` (MCP) and
`POST /v1/google-analytics/account-inventory` (REST) return the available
account/property inventory. Rankrat's one OAuth consent includes Google
Analytics read-only and edit scopes so a separately approval-gated onboarding
operation can create a property; report and inventory routes themselves make
read-only calls to fixed Google API origins with redirects and proxy
inheritance disabled.

REST exposes `POST /v1/google-analytics/reports` and
`POST /v1/google-analytics/realtime-reports`; MCP exposes
`google_analytics_report` and `google_analytics_realtime_report`. Both accept
bounded date ranges, dimensions, metrics, result limits, and offsets. They do
not accept a GA4 property outside the immutable allowlist, a credential, or a
provider URL. Their responses are immutable typed report tables: ordered
dimension headers, metric headers with the documented GA4 metric type, and
header-aligned rows. The provider boundary rejects malformed, duplicate,
unexpected, oversized, mismatched, or negative-count upstream fields instead
of relaying a raw GA4 payload.

For common read-only analysis, REST also exposes
`POST /v1/google-analytics/content-performance`,
`POST /v1/google-analytics/landing-page-performance`, and
`POST /v1/google-analytics/traffic-source-performance`; MCP exposes matching
`google_analytics_*_performance` tools. Each accepts only the configured
account/property, an absolute bounded date range, result limit, and timeout.
They fix the GA4 fields respectively to `pagePathPlusQueryString` with
`screenPageViews`, `activeUsers`, and `engagedSessions`;
`landingPagePlusQueryString` with `sessions`, `activeUsers`, and
`engagedSessions`; and `sessionSourceMedium` with `sessions`, `activeUsers`,
and `engagedSessions`. Callers cannot replace those dimensions or metrics.

REST `POST /v1/google-analytics/ecommerce-performance` and MCP
`google_analytics_ecommerce_performance` return one fixed item-level table.
They request only `itemName` with `itemsPurchased`, `itemsViewed`, and
`itemRevenue`; callers cannot replace those fields, add filters, or select a
different operation.

REST `POST /v1/google-analytics/audience-segments` and MCP
`google_analytics_audience_segments` return one fixed historical audience table
using only `audienceName`, `activeUsers`, `newUsers`, and `engagedSessions`.
They do not accept caller-selected GA4 fields or filters.

REST `POST /v1/google-analytics/user-behavior` and MCP
`google_analytics_user_behavior` return one fixed historical new-versus-returning
table using only `newVsReturning`, `activeUsers`, `newUsers`, and
`engagedSessions`. They do not accept caller-selected GA4 fields or filters.

REST `POST /v1/google-analytics/conversion-funnels` and MCP
`google_analytics_conversion_funnel` return a closed GA4 event-step funnel for
one configured property. The caller supplies 2–10 unique literal event names,
one bounded date range, and a row limit; Rankrat builds the documented nested
event filters itself and rejects arbitrary filters, segments, breakdowns,
origins, and credentials. Google currently exposes `runFunnelReport` only on
the alpha Data API surface, so this endpoint is intentionally narrow and must
be verified against a configured property before relying on it operationally.

REST `POST /v1/google-analytics/organic-search-landing-pages` and MCP
`google_analytics_organic_search_landing_pages` return a separate fixed
landing-page table for properties linked to Search Console. It requests only
`organicGoogleSearchClicks`, `organicGoogleSearchImpressions`,
`organicGoogleSearchClickThroughRate`, and
`organicGoogleSearchAveragePosition`; GA4 returns data for these metrics only
when the property has the required active Search Console link.

### New-site onboarding from REST or MCP

Rankrat can onboard a new site while the service is running. The write creates
a GA4 property and web stream, adds the HTTPS URL-prefix property to Search
Console, adds the site to Bing Webmaster, then atomically records the resulting
local boundaries. `make onboard-site` remains a convenience wrapper for a
human operator; it uses the same guarded flow.

This is deliberately a two-step write protocol:

1. An administrator mints a 60-second, single-use approval through
   `POST /v1/admin/site-onboarding-approvals`, authenticated with the separate
   admin bearer token.
2. A running client submits that exact approval through
   `POST /v1/site-onboarding-submissions` or the destructive MCP tool
   `site_onboarding_submit`.

The MCP server intentionally does **not** expose an approval-minting tool. An
MCP client can execute the one intended onboarding but cannot grant itself
unbounded authority to create provider resources. A trusted controller may use
the admin REST endpoint to mint an approval immediately before its MCP call.

The approval and submission bodies use the same fields:

```json
{
  "google_account_id": "google",
  "bing_account_id": "bing",
  "site_url": "https://www.example.com/",
  "display_name": "Example",
  "time_zone": "Etc/UTC",
  "currency_code": "USD"
}
```

The submission additionally requires the returned `approval_id`; it may set a
bounded `timeout_seconds`. The approval is bound to every field above, is spent
on the first matching execution, and is rejected if replayed or altered.

With one explicit invocation it:

1. Creates a GA4 property and web data stream under the exact Google Analytics
   parent account configured in `google_analytics_parent_account_id`.
2. Adds the HTTPS URL-prefix property to Search Console.
3. Adds the site to Bing Webmaster.
4. Atomically records the normalized site URL and GA4 property ID in the
   ignored local boundary document, so normal Rankrat reads work immediately.

Set `google_analytics_parent_account_id` once on the Google boundary account;
it is the numeric Analytics **account** ID returned by
`google_analytics_account_inventory`, not a GA4 property ID or `G-...`
Measurement ID. The OAuth client project must have the Google Analytics Admin
API enabled. Re-run `make auth-google` once after upgrading to a version that
supports onboarding so the stored grant includes `analytics.edit`; the normal
consent flow remains a single browser approval.

Before the command, create the owner-only admin bearer-secret file used for all
write-capability startup gates. The command verifies that the file exists and
contains a non-trivial secret; keep its permissions at `0600`. Then run:

```sh
make onboard-site \
  ONBOARD_GOOGLE_ACCOUNT_ID=google \
  ONBOARD_BING_ACCOUNT_ID=bing \
  ONBOARD_SITE_URL=https://www.example.com/ \
  ONBOARD_DISPLAY_NAME='Example' \
  ONBOARD_TIME_ZONE=Etc/UTC \
  ONBOARD_CURRENCY_CODE=USD
```

The command accepts only a canonical public HTTPS site root: no HTTP, custom
port, credentials, query, fragment, or path. It returns the numeric GA4
property ID and non-secret `G-...` measurement ID so the site owner can add the
resulting Google tag to the site build. It never prints OAuth material, Bing
keys, provider error bodies, or request URLs.

Provider ownership rules still apply. Search Console and Bing can accept the
registration request, but if the authorized account is not already an owner,
their own verification workflow remains necessary. Rankrat does not attempt to
bypass a provider's ownership proof. If a later provider fails after an earlier
one succeeds, Rankrat reports the completed provider stages and intentionally
does not perform destructive automatic rollback of remote resources.

### Search Console sitemap and inspection reads

In addition to listing configured-property sitemaps, REST
`GET /v1/google/sitemap` and MCP `google_sitemap_get` retrieve one exact
configured child sitemap. REST `POST /v1/google/url-inspection-batches` and
MCP `google_url_inspection_batch` inspect 1–20 distinct HTTPS URLs beneath one
configured property. Every URL is normalized and authorized before the first
provider request; duplicate or out-of-property URLs are rejected. Site results
contain a documented permission enum; sitemap results contain the documented
type, counters, timestamps, and content records; URL Inspection results expose
the stable index-status fields (verdict, coverage, indexing, crawl, canonical,
referring URL, and sitemap data). Unexpected Google fields are ignored, but
malformed fields in those exposed typed results are rejected at the provider
boundary.

### Search Console aggregate reports

REST `POST /v1/google/search-analytics-summary` and MCP
`google_search_analytics_summary` return validated aggregate clicks,
impressions, CTR, and average position for one bounded period. REST
`POST /v1/google/search-analytics-comparison` and MCP
`google_search_analytics_comparison` return those metrics for two bounded
periods plus absolute deltas. Both operations use only an exact configured
property, optional bounded Search Analytics filters, and Google's fixed Search
Console origin; malformed upstream metrics are rejected rather than returned.

REST `POST /v1/google/search-analytics-dimension-report` and MCP
`google_search_analytics_dimension_report` provide typed, paged top-query,
top-page, country, search-appearance, and daily time-series reports. The fixed
`report` enum selects one Google dimension; callers cannot inject arbitrary
dimensions or receive a raw provider payload. Every result key and metric is
validated before it is returned.

REST `POST /v1/google/search-analytics-drop-attribution` and MCP
`google_search_analytics_drop_attribution` compare two bounded periods by only
the fixed `queries` or `pages` grouping. They return typed current and previous
metrics plus signed click and impression deltas, ordered by click loss. The
merged result cannot exceed the requested limit, marks `has_more` when data was
truncated, and rejects malformed or duplicate upstream keys.

REST `POST /v1/google/search-analytics-trend` and MCP
`google_search_analytics_trend` return ascending, validated daily metrics from
the fixed `date` dimension. REST `POST /v1/google/search-analytics-anomalies`
and MCP `google_search_analytics_anomalies` return only finite click or
impression z-score outliers against that bounded trend; a flat or fewer-than-
three-day series has no anomaly. REST
`POST /v1/google/search-analytics-page-performance` and MCP
`google_search_analytics_page_performance` return a bounded fixed `page`
dimension report with validated CTR and position. None of these operations
accept caller-selected dimensions, provider origins, properties, or credentials.

### Schema eligibility

REST `POST /v1/schema/validate-html` and
`POST /v1/schema/validate-json-ld`, plus MCP `schema_validate_html` and
`schema_validate_json_ld`, evaluate caller-supplied content locally for the
restricted Google Indexing API eligibility rule: a `JobPosting`, or a
`BroadcastEvent` nested in a `VideoObject`. They make no provider request, read
no credentials, and cannot submit or modify anything. Inputs are strict and
bounded by document size, embedded JSON-LD script count and size, parsed depth,
and parsed item count; malformed or excessive input returns an ineligible
result or a bounded validation error.

REST `POST /v1/schema/validate-url` and MCP `schema_validate_url` perform the
same conservative assessment for one caller-supplied public HTTPS page. They
need no provider credential or configured account, but do make one bounded
public read: IP-literal, private or mixed DNS, credential-bearing, nonstandard-
port, redirect, non-HTML, oversized, and timed-out responses fail closed. The
fetcher pins the validated DNS address for the connection, keeps TLS hostname
verification, and ignores proxy environment variables.

### Google Search Console properties

REST `GET /v1/google/sites` and MCP `google_sites_list` return only upstream
properties that exactly match the configured account boundary. REST
`GET /v1/google/site` and MCP `google_site_get` retrieve permission metadata
for one configured property. Neither route accepts a credential or arbitrary
provider origin.

When writes are enabled, `POST /v1/admin/google-site-approvals` mints one exact
approval to add or delete an already configured property. REST
`POST /v1/google-site-submissions` and MCP `google_site_submit` consume it
once. This deliberate boundary means Rankrat cannot introduce a new property
outside deployment configuration; add/delete use only Google's fixed empty-body
`PUT`/`DELETE` path with the separate `webmasters` write scope.

### PageSpeed Insights setup

Add every PageSpeed site as an exact HTTPS `pagespeed_sites` boundary on the
Google account; account discovery and `search_console_sites` are deliberately
not enough for PageSpeed. PageSpeed does not use the Google OAuth grant or send an OAuth
bearing header. For reliable automation, create a PageSpeed Insights API key in
the same Google Cloud project, restrict it to the PageSpeed Insights API, save
it in the gitignored `secrets/google/pagespeed-api-key` file, and set
`"pagespeed_api_key_file": "/run/secrets/google/pagespeed-api-key"` on that
account. Restrict the local file to its owner (`chmod 600
secrets/google/pagespeed-api-key`). The supplied boundary and Compose examples
mount that exact filename.
If the field is absent, Rankrat makes the documented anonymous request; Google
can rate-limit that mode. In both modes, the service resolves the configured
account, site, and child URL before a request and uses only the fixed PageSpeed
Insights endpoint with redirects and proxy inheritance disabled. API-key bytes
never appear in logs, errors, response data, or headers.

REST exposes `POST /v1/pagespeed/analyses`; MCP exposes `pagespeed_analyze`.
Both accept only `DESKTOP` or `MOBILE` plus bounded, non-repeated audit
categories. They cannot select an arbitrary origin, credential, or URL outside
the configured site path. Responses are parsed into an immutable report with
the canonical analyzed URL, UTC analysis time, bounded Lighthouse category
scores, and page/origin loading-experience categories. A canonical URL that
leaves the configured site is rejected; no raw PageSpeed payload is relayed to
callers.

PageSpeed defaults to a bounded 30-second provider timeout; callers may lower
it within the existing request bounds when they need a faster failure.

REST `POST /v1/pagespeed/core-web-vitals` and MCP
`pagespeed_core_web_vitals` reuse that same bounded request and return only
server-selected Chrome UX Core Web Vitals: LCP, CLS, and INP. Page and origin
field data remain separate, metrics are typed with bounded percentile,
category, and distribution fields, and callers cannot request arbitrary
upstream metric maps.

REST `POST /v1/cross-provider/ga4-pagespeed-correlations` and MCP
`ga4_pagespeed_correlation` combine exactly one configured GA4 content row with
one configured PageSpeed analysis. The caller supplies independently configured
GA4 and PageSpeed account IDs, the configured GA4 property, PageSpeed Search
Console site, child URL, bounded date range, and `DESKTOP` or `MOBILE` strategy.
Rankrat authorizes each account boundary before launching the two fixed reads
concurrently. GA4 uses its persisted OAuth grant while PageSpeed uses its
optional API key. Separate Google accounts remain explicit, independent
boundaries, selected by their configured IDs.
Child URLs cannot include credentials, query strings, or
fragments, so the local join key is the normalized pathname only; it returns an
absent GA4 row when none matches and rejects duplicate matching rows. This is a
correlation report, not a causal claim or SEO recommendation.

REST `POST /v1/cross-provider/search-engine-comparisons` and MCP
`search_engine_comparison` compare one configured Search Console aggregate with
one independently configured Bing site over the same bounded date range. The
result preserves each engine's native observations separately; it does not
calculate market share, normalize unlike metrics, or return a recommendation.

REST `POST /v1/cross-provider/search-engine-traffic-health` and MCP
`search_engine_traffic_health` return separate deterministic daily anomaly
observations for one configured Search Console property and one independently
configured Bing site. Both resources are authorized before the concurrent
fixed-origin reads. The result does not normalize engine metrics, infer a cause,
or make a recommendation.

REST `POST /v1/cross-provider/ga4-search-console-comparisons` and MCP
`ga4_search_console_comparison` combine one configured GA4 property's fixed
Google-linked organic-landing-page report with one independently configured
Search Console aggregate over the same bounded date range. Rankrat authorizes
the GA4 property and Search Console site independently before concurrent reads.
It returns their typed results separately: their collection and attribution
models differ, so it neither normalizes the values nor derives a recommendation.

### Bing Webmaster setup

Add a Bing account with an API-key file and exact HTTPS sites to the boundary
document. Rankrat loads the key only after resolving the configured account and
site, uses the fixed Bing Webmaster JSON origin, disables redirects and proxy
inheritance, and never returns or logs the key. REST exposes
`POST /v1/bing/keyword-statistics` and MCP exposes `bing_keyword_statistics`.
REST `POST /v1/bing/related-keywords` and MCP `bing_related_keywords` require
an explicit bounded date interval. Both return immutable typed reports and
accept only bounded account, query, locale, and date inputs—never a provider
URL, API key, method name, or arbitrary query-parameter map. Site reports have
dedicated typed endpoints; there is no generic Bing read escape hatch.

Keyword-statistics rows contain a query, report day, impressions, and broad
impressions. Related-keyword rows contain a query, impressions, and broad
impressions. The provider boundary rejects malformed dates, booleans in integer
fields, negative values, duplicate rows, and oversized reports before service
code sees a result.

REST `POST /v1/bing/traffic-trend` and MCP `bing_traffic_trend` return
ascending typed daily click/impression points for one bounded configured site
and period. REST `POST /v1/bing/traffic-anomalies` and MCP
`bing_traffic_anomalies` return only finite click or impression z-score outliers
from that trend; a flat or fewer-than-three-day series has no anomaly. REST
`POST /v1/bing/traffic-comparison` and MCP `bing_traffic_comparison` return
two exact period totals and signed deltas. These reports use only Bing's fixed
`GetRankAndTrafficStats` operation. Its untrusted JSON is strictly parsed into
immutable typed rows before service code sees it; malformed, duplicate,
out-of-window, non-finite, or negative values are rejected rather than returned.

REST `POST /v1/bing/query-performance` and MCP `bing_query_performance`, plus
REST `POST /v1/bing/page-performance` and MCP `bing_page_performance`, return
typed top-query and top-page rows from only Bing's fixed `GetQueryStats` and
`GetPageStats` operations. A row has its query/page label, report date, clicks,
impressions, and nullable average click and impression positions. Bing's `-1`
unavailable-position sentinel becomes JSON `null`; a label may repeat on
different report days, but duplicate `(label, day)` records are rejected. The
provider boundary also rejects invalid dates, booleans, non-finite or negative
metrics, and non-positive positions other than that exact sentinel before
service code sees a row.

REST `POST /v1/bing/query-opportunities` and MCP
`bing_query_opportunities`, plus REST `POST /v1/bing/page-opportunities` and
MCP `bing_page_opportunities`, derive bounded local candidates from exactly one
of those fixed reports. They make no extra provider call and accept no caller
threshold. A candidate is flagged for below-median CTR among rows with
impressions and/or a local striking-distance position from 4 through 20.
Rankrat uses average impression position when available and average click
position only as a fallback; a row with neither position cannot receive the
rank-based classification. Those labels are Rankrat policy, not Bing
assertions; each response includes the typed source row, computed CTR, and
applicable classifications.

REST `POST /v1/bing/opportunity-matrix` and MCP `bing_opportunity_matrix`
concurrently compose those existing fixed query and page reports for one
configured site. Query and page candidates remain separate. Its quick-win lists
contain only candidates with both local `low_ctr` and `striking_distance`
classifications; they are a transparent rule intersection, not a Bing-supplied
recommendation or predicted result.

REST `POST /v1/bing/brand-analysis` and MCP `bing_brand_analysis` classify a
single fixed `GetQueryStats` response into brand and non-brand rows using 1–20
bounded, case-insensitive literal terms. Terms are local-only—they are never
compiled as patterns or sent to Bing—and the report makes exactly one
configured-site provider read.

REST `POST /v1/bing/ranking-buckets` and MCP `bing_ranking_buckets` group one
fixed `GetQueryStats` response by average impression position, falling back to
average click position when needed, into the fixed local
bands top three (at most 3), first page (over 3 through 10), second page (over
10 through 20), and beyond the second page (over 20). A row with neither
position remains in performance output but is absent from rank buckets;
otherwise rows are in exactly one bucket, including empty buckets in that
order. Those bands are Rankrat policy, never caller input or provider
parameters.

REST `POST /v1/bing/query-page-performance` and MCP
`bing_query_page_performance` expose only `GetQueryPageStats` for one bounded
query. REST `POST /v1/bing/query-cannibalization` and MCP
`bing_query_cannibalization` make that same one fixed query-page read and return
pages only when Bing reports at least two distinct validated labels; they never
make a second provider call or accept a caller-selected threshold. REST
`POST /v1/bing/page-query-performance` and MCP `bing_page_query_performance`
expose only `GetPageQueryStats` for one configured child page URL. These
reports reuse the typed row boundary and never infer a URL from Bing's opaque
response label.

REST `POST /v1/bing/url-submission-quota` and MCP
`bing_url_submission_quota` expose only `GetUrlSubmissionQuota` for one exact
configured site. The provider boundary returns immutable non-negative integer
`daily` and `monthly` quotas and rejects malformed values before service code
sees them.

REST `POST /v1/bing/crawl-issues` and MCP `bing_crawl_issues` expose only
`GetCrawlIssues`. They return typed URL, HTTP-code, issue-count, and in-link
records after rejecting malformed, negative, duplicate, or oversized upstream
data. REST `POST /v1/bing/crawl-stats` and MCP `bing_crawl_stats` expose only
`GetCrawlStats`; they return ascending, typed daily crawl counters. Neither
operation accepts a provider method, origin, credential, or query map.

REST `POST /v1/bing/feeds` and MCP `bing_feeds` expose only `GetFeeds`.
They return typed feed URL, type, status, compression, file-size, URL-count,
and crawl/submission date fields after rejecting malformed, negative, duplicate,
or oversized upstream data. The operation accepts no provider method, origin,
credential, or arbitrary query parameters.

REST `POST /v1/bing/link-counts` and MCP `bing_link_counts` expose only
`GetLinkCounts` for a bounded non-negative provider page. They return typed
inbound-link URLs and counts plus the total page count, rejecting malformed,
negative, duplicate, or oversized upstream data before service code sees it.

REST `POST /v1/bing/url-information` and MCP `bing_url_information` expose
only `GetUrlInfo` for one exact configured child URL. They return typed URL,
indexing, crawl-date, document-size, HTTP-status, and child-count fields.
Malformed records, URLs outside the configured site, and responses for a URL
other than the requested URL are rejected before service code sees them.
Bing's documented `HttpStatus: 0` sentinel means no HTTP status was reported;
Rankrat exposes that as JSON `null`, never as a fabricated HTTP status.

When writes are enabled, an administrator can mint one exact Bing batch
approval at `POST /v1/admin/bing-url-submission-approvals`. The request must
identify one configured Bing account and site plus 1–500 unique child URLs.
`POST /v1/bing-url-submissions` and MCP `bing_url_submit` consume the resulting
single-use approval ID; neither can mint it. The provider client uses only the
documented fixed Bing JSON `SubmitUrlBatch` endpoint and the configured API-key
file. IndexNow remains the preferred cross-engine notification path; this Bing
operation is for direct Bing-only submissions.

`POST /v1/admin/bing-sitemap-approvals` similarly mints one exact approval to
submit or delete one HTTPS sitemap inside the selected Bing site. REST
`POST /v1/bing-sitemap-submissions` and MCP `bing_sitemap_submit` consume it
once. The provider client can only call Bing's fixed JSON `SubmitFeed` or
`RemoveFeed` operations; response receipts omit the sitemap URL and all
credentials.

`POST /v1/admin/bing-site-approvals` mints one exact approval to add or delete
an already configured Bing property. REST `POST /v1/bing-site-submissions` and
MCP `bing_site_submit` consume it once. The provider client can only call
Bing's fixed JSON `AddSite` or `RemoveSite` operation with `{"siteUrl": ...}`;
the legacy API-key query parameter is never logged or returned. Because each
property must already be in the immutable boundary file, this cannot introduce
an arbitrary site.

### Google Indexing setup

Google's Indexing API is limited to pages with `JobPosting` structured data or
a `BroadcastEvent` embedded in a `VideoObject`. When writes are enabled,
Rankrat uses the configured Google OAuth refresh-token record with the Indexing
API scope. An administrator first mints one exact approval through
`POST /v1/admin/google-indexing-approvals`, authenticated by the separate admin
bearer secret. For `URL_UPDATED`, Rankrat checks the configured Search Console
property owns the URL, fetches that public HTTPS page through its DNS-pinned
schema validator, and requires the eligible JSON-LD evidence. `URL_DELETED`
does not fetch a page that may no longer exist, but still requires exact
configured-property ownership and the same approval gate.

REST `POST /v1/google-indexing-metadata` and MCP
`google_indexing_metadata` are read-only and available even when writes are
disabled. They return only Google’s receipt metadata for one configured URL;
that metadata has a canonical URL plus optional typed `latest_update` and
`latest_remove` receipts. Each receipt has only its URL, fixed event type, and
timestamp. It confirms the last notification Google received, not whether the
page has been indexed or removed.

REST `POST /v1/google-indexing-submissions` and MCP
`google_indexing_submit` consume that single-use approval; MCP cannot mint one.
For 1–100 notifications on one configured property, an administrator can mint
one ordered approval at `POST /v1/admin/google-indexing-batch-approvals`; REST
`POST /v1/google-indexing-batch-submissions` and MCP
`google_indexing_batch_submit` consume it once. Rankrat sends that batch as one
documented `multipart/mixed` request to Google's fixed batch origin, validates
every response part and returns ordered, secret-free accepted/rejected receipts.
It never automatically retries a batch because Google may process parts
independently. The provider client refuses redirects and proxy inheritance and
never returns credentials, access tokens, or upstream error bodies.

### Google sitemap mutations

When writes are enabled, `POST /v1/admin/google-sitemap-approvals` mints one
exact approval to submit or delete a sitemap within a configured Search Console
property. REST `POST /v1/google-sitemap-submissions` and MCP
`google_sitemap_submit` consume it once. Rankrat requests the separate
`webmasters` write scope only for this path, permits only an HTTPS sitemap
within the selected configured property, and sends the documented fixed
`PUT`/`DELETE` request with no body. A success must be the expected empty
response; upstream bodies, credentials, and sitemap URLs are never returned in
the mutation receipt.

### IndexNow setup

IndexNow is absent unless `RANKRAT_ENABLE_WRITES=true` at process startup and
the boundary file includes the exact target. Initialize each target with
`make init-indexnow INDEXNOW_TARGET_ID=<id> INDEXNOW_HOST=<hostname>`; it
creates an ignored mode-600 key, records that one target, and keeps both write
switches disabled. It neither deploys the key file nor calls IndexNow. Serve
the generated root `<key>.txt` from the selected hostname using your own site
deployment; `scripts/indexnow_export.sh` is a sourceable reference
implementation of that publish-and-verify step for a static exporter. Then run
`make verify-indexnow-key INDEXNOW_TARGET_ID=<id>`. The
verifier requires direct HTTPS `200` with exact key content and rejects
redirects, unsafe DNS, and mismatches. The submission client accepts only HTTPS
URLs on that target host, within the key file's directory,
submits to the fixed `api.indexnow.org`
endpoint, limits batches to 1,000 URLs and process-local attempts to 10 per
target per minute, and keeps bounded process-local deduplication state.

When writes are enabled, `RANKRAT_ADMIN_BEARER_SECRET_FILE` is mandatory and
must point to a separately mounted secret. An operator first calls
`POST /v1/admin/write-approvals` with that admin bearer token and the exact
`target_id` and bounded `urls` request. The returned opaque `approval_id` is
single-use, expires after 60 seconds, and is bound to the normalized target and
URL list. REST `POST /v1/indexnow-submissions` and MCP `indexnow_submit` both
require that `approval_id`; MCP cannot mint approvals. Neither surface accepts
a provider URL, host override, credential, or key.

## Security model

- Boundaries are checked before every later provider operation.
- There is no global credential fallback or caller-selected provider URL.
- IndexNow, Bing URL/sitemap/property submission, Google Indexing, and Google
  property/sitemap mutations are disabled until the explicit startup flag and
  separately authenticated exact-request approval; every write tool is marked
  destructive and non-idempotent in MCP.
- The production image is multi-stage, non-root, has no shell entrypoint, and
  defaults to stdio.
- The compose example uses a read-only filesystem, dropped capabilities,
  `no-new-privileges`, loopback-only port publication, resource limits, capped
  logs, a healthcheck, and individually mounted secret files.
- Versions are exact and locked in `uv.lock`. The frozen
  release-age gate advances only during a `make pkg-*` dependency mutation.
  Use `PKG_GROUP=dev` with `make pkg-add` or `make pkg-remove` for development
  tooling so it is not added to the production dependency set.

## Development

```sh
make dev-image
make generate
make lint
make test
make test-image
make audit
make audit-secrets
make sbom
make audit-image
```

Development commands run in the development container. Builds, lint, tests,
and audits use `uv.lock` frozen. The mocked suite performs no provider network
access; `make test-coverage` is the statement-and-branch coverage gate and
fails below 95%.
`make test-image` builds the production image, verifies MCP stdio initialization
without network access, verifies HTTP on a random host-loopback port, and checks
that protected HTTP endpoints reject a request without its synthetic test-only
bearer value. It also verifies the authenticated `/openapi.json` response comes
from the OAS 3.1 YAML contract. It mounts only the public boundary example and
creates no provider credentials. `make sbom` exports the local production image
and generates Syft JSON plus a CycloneDX SBOM under gitignored `.sbom/`. The
scanner has no network or Docker socket access. `make audit-image` refreshes
Grype's public vulnerability database in a separate constrained container, then
scans that SBOM offline and fails for fixable high or critical findings. It
applies only the exact,
checked-in OpenVEX assertions in `security/rankrat-cpython.openvex.json` for
installed CPython stdlib code that Rankrat cannot execute; the regression suite
rejects any broadened VEX assertion or reintroduced application import. Ignored
matches remain in its JSON report for release triage. Its local database cache
lives under the gitignored `.grype-db/`; neither target reads provider
credentials. The editable API source is
[`src/rankrat/api/openapi.yaml`](src/rankrat/api/openapi.yaml), an OAS 3.1
document. `make generate-openapi` deterministically renders its checked-in
`openapi.json` distribution artifact; `make check-openapi` rejects a stale
artifact. When enabled, FastAPI publishes that same YAML-derived document at
`/openapi.json` to a caller with the regular bearer token when that token is
configured. The contract suite independently derives FastAPI's route schema and
fails if it differs from the YAML contract. The source declares the normal
bearer boundary, the separate admin bearer boundary, and `/healthz` as the only
public route. The document lists Rankrat's full supported surface; write routes
remain unavailable until their separate runtime write and approval gates are
satisfied.

## Live provider verification

Live checks use the same provider clients as production. They are opt-in and
never run as part of `make test`.

1. Run `make init-config`, then configure only the provider accounts and site
   boundaries you intend to use in the ignored `config/boundaries.json`.
2. For every Google Search Console, GA4, Indexing, or account-discovery
   boundary, put the installed-client JSON at
   `secrets/google/oauth-client.json`, set `oauth_token_file` beneath
   `/run/oauth`, and run `make auth-google` before
   the live check. It requests Search Console full scope, Indexing API, and GA4
   read/edit access in one consent flow. It does not enable Google Cloud APIs, grant product
   roles, or enable Rankrat write operations. The live harness mounts `oauth/`
   separately because a token refresh may rotate refresh material. Re-run
   `make auth-google` whenever the stored Google authorization must gain a new
   scope or otherwise be replaced. For reliable PageSpeed automation, create a
   PageSpeed Insights API key, restrict it to that API, save it as
   `secrets/google/pagespeed-api-key`, and configure
   `pagespeed_api_key_file` as `/run/secrets/google/pagespeed-api-key`. PageSpeed
   works without that field but anonymous quota can be rate-limited.
3. Fill the ignored `.env` with the provider-specific account ID
requested by the relevant live test. The GA4 report check also requires
`RANKRAT_LIVE_GA4_PROPERTY_ID` for a property in that account's immutable
allowlist. `RANKRAT_LIVE_GA4_FUNNEL_EVENTS` is optional: give a comma-separated
configured event sequence with at least two distinct names to execute the
separate GA4 Funnel endpoint. Set `RANKRAT_LIVE_PAGESPEED_ACCOUNT_ID` to the
configured Google account ID, plus
`RANKRAT_LIVE_PAGESPEED_SITE_URL` and `RANKRAT_LIVE_PAGESPEED_URL`. Both URLs
must match that account's exact immutable HTTPS `pagespeed_sites`
boundary; discovery alone does not authorize PageSpeed. It submits every
non-deprecated category supported by the v5 API in one desktop analysis. The
Bing readiness check requires
`RANKRAT_LIVE_BING_ACCOUNT_ID` and `RANKRAT_LIVE_BING_SITE_URL` for an exact
configured Bing property. That extended read-only group covers traffic,
query/page performance, crawl reports, feeds, URL-submission quota, and link
counts. `RANKRAT_LIVE_BING_QUERY`, `RANKRAT_LIVE_BING_PAGE_URL`, and
`RANKRAT_LIVE_BING_KEYWORD_QUERY` are optional inputs for Bing's query/page,
URL-information, keyword-statistics, and related-keyword endpoints;
`RANKRAT_LIVE_BING_COUNTRY` and `RANKRAT_LIVE_BING_LANGUAGE` optionally scope
the latter two reads.
For the extended Google read smoke, also set
`RANKRAT_LIVE_GOOGLE_SITE_URL` to one configured Search Console property.
`RANKRAT_LIVE_GOOGLE_SITEMAP_URL`, `RANKRAT_LIVE_GOOGLE_INSPECTION_URL`, and
`RANKRAT_LIVE_GOOGLE_INDEXING_URL` are optional exact child URLs; they enable
the corresponding read only when that URL is suitable for the provider API.
4. Run `make test-live`. Google Search Console and GA4 use the same configured
   OAuth dispatcher as production, so the exact configured OAuth boundary is
   exercised. With `google_account_discovery: true`, the live suite also lists
   every OAuth-visible Search Console site and GA4 account/property summary.

Rankrat returns only provider resources that exactly match the allowlist in
`config/boundaries.json`. Use least-privilege credentials; no provider
credential belongs in `.env`. URL-prefix resources reject dot segments and ambiguous
percent-encoded path separators before a provider request is created.

The live IndexNow test performs a real submission only when all three settings
are present in `.env`: `RANKRAT_ENABLE_WRITES=true`,
`RANKRAT_RUN_LIVE_INDEXNOW_SUBMISSION=true`, and a configured
`RANKRAT_LIVE_INDEXNOW_TARGET_ID` plus one
`RANKRAT_LIVE_INDEXNOW_URL`. Use a harmless, already-public URL under the
target's configured key-directory scope. Set
`RANKRAT_ADMIN_BEARER_SECRET_FILE=/run/secrets/rankrat/admin-bearer-token`
in `.env` and create that gitignored file at
`secrets/rankrat/admin-bearer-token`; it is required
to enable the write path even though the live test mints its short-lived
approval in-process. It is deliberately separate from the default live checks.

## Layout

```text
src/rankrat/api/openapi.yaml  Authoritative OAS 3.1 contract
src/rankrat/    Application, policy, providers, services, and transports
tests/          Unit, contract, integration, and security tests
config/         Boundary-file example; operator configuration is local
```

## License

WTFPL. See [LICENSE](LICENSE). Do what the fuck you want to.

The published Docker image also carries rankrat's Python dependencies, which
keep their own licenses — two of them ask for something in return for
redistribution. [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md) records which
and why.
