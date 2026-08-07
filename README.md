# rankrat

<!-- mcp-name: io.github.psyb0t/rankrat -->

[![CI](https://github.com/psyb0t/rankrat/actions/workflows/pipeline.yml/badge.svg?branch=main)](https://github.com/psyb0t/rankrat/actions/workflows/pipeline.yml)
[![coverage](https://raw.githubusercontent.com/psyb0t/rankrat/badges/coverage.svg)](https://github.com/psyb0t/rankrat/actions/workflows/pipeline.yml)
[![version](https://raw.githubusercontent.com/psyb0t/rankrat/badges/version.svg)](https://github.com/psyb0t/rankrat/releases)
[![license](https://raw.githubusercontent.com/psyb0t/rankrat/badges/license.svg)](LICENSE)
[![Docker Pulls](https://img.shields.io/docker/pulls/psyb0t/rankrat?style=flat-square)](https://hub.docker.com/r/psyb0t/rankrat)

Search Console, Bing Webmaster Tools, GA4 and PageSpeed each ship a dashboard.
Dashboards answer the question you already knew to ask. The interesting ones —
*which queries actually caused last week's drop*, *is this page down because it
lost rankings or because it fell out of the index*, *do Google and Bing agree
something broke* — need you to pull four exports and do the join yourself, in a
spreadsheet, at 1am.

rankrat puts those APIs behind one MCP server so an agent does the joining. You
ask; it goes and rats out whichever provider knows.

It's a rat, not a burglar. It answers only for the accounts and properties you
list in a boundary file. Ordinary tools cannot widen that scope; the separately
gated onboarding tool can add only the exact resources it creates when you
explicitly enable agent onboarding and provide a validated writable config
mount. Read-only unless you deliberately turn writes on, at which point the
other write tools appear and stay inside the same boundaries. Provider tools
read what those providers already hold about you. The optional local Lighthouse
worker opens only an explicitly requested page beneath a configured PageSpeed
site. The separate whole-site auditor walks a strictly bounded same-site graph
with a DNS-pinned fetcher.

Speaks MCP over stdio and Streamable HTTP, plus a REST API for callers that
don't speak MCP.

**Status:** alpha. Everything documented here works against real accounts; the
tool surface is still free to move.

## Contents

- [Quick start](#quick-start)
- [Running it](#running-it)
- [Capabilities and discovery](#capabilities-and-discovery)
- [Local Lighthouse audits](#local-lighthouse-audits)
- [Ownership, whole-site audits, and backlinks](#ownership-whole-site-audits-and-backlinks)
- [Agent integrations](#agent-integrations)
- [Write capability](#write-capability)
- [Finding and naming GA4 containers](#finding-and-naming-ga4-containers)
- [Onboarding a new site](#onboarding-a-new-site)
- [Credentials](#credentials)
- [Configuration](#configuration)
- [Verification](#verification)
- [Security](#security)
- [Known gaps](#known-gaps)
- [Release information](#release-information)

## Quick start

Rankrat ships as a Docker image; Docker is the only runtime requirement. The
bootstrap commands below also use a POSIX shell, `curl`, `openssl`, and standard
core utilities. Create the working layout in a directory of your choosing —
Rankrat reads all three paths as mounts and never writes outside them:

```sh
curl -fsSL https://raw.githubusercontent.com/psyb0t/rankrat/main/rankrat.sh \
  -o rankrat.sh
less rankrat.sh
chmod +x rankrat.sh
sudo mv rankrat.sh /usr/local/bin/rankrat.sh

mkdir -p config oauth secrets/google secrets/bing secrets/cloudflare secrets/indexnow secrets/rankrat
chmod 700 config oauth secrets secrets/google secrets/bing secrets/cloudflare secrets/indexnow secrets/rankrat

curl -fsSL https://raw.githubusercontent.com/psyb0t/rankrat/main/config/boundaries.json.example \
  -o config/boundaries.json
chmod 600 config/boundaries.json

curl -fsSL https://raw.githubusercontent.com/psyb0t/rankrat/main/.env.example \
  -o .env
chmod 600 .env

install -m 600 /dev/null secrets/rankrat/http-bearer-token
openssl rand -base64 32 | tr -d '\n' > secrets/rankrat/http-bearer-token
```

The bearer secret authenticates `/v1/` and `/mcp` for non-loopback HTTP; stdio
never uses it, but the HTTP mode requires the file to exist.

Then edit `config/boundaries.json` to list only what Rankrat may read, put the
credentials for the providers you actually use at the paths in
[Credentials](#credentials), and authorize Google if you configured it:

```sh
rankrat.sh auth-google --account-id google --print-authorization-url
rankrat.sh setup
```

`rankrat.sh setup` is a live, read-only verification gate. It checks every
account represented in the boundary file and that account's configured provider
access; it does not create a provider resource or submit an IndexNow URL. It
reports the missing local file, OAuth grant, provider permission, or configured
resource that needs attention. It is the one wrapper mode that reads `.env`.

From a checkout, `make setup` first refuses symlinked local config, OAuth, or
secret paths and normalizes their permissions: directories become owner-only,
credential and OAuth files become mode `0600`, and `.env` plus
`config/boundaries.json` become mode `0600`. It runs `rankrat.sh setup`, then
uses the `RANKRAT_LIVE_*` selectors from `.env` for the deeper provider-specific
live suites and verifies the shipped HTTP and MCP transports. Leave selectors
for unused providers blank so those extra suites skip.

## Running it

```sh
rankrat.sh          # MCP over stdio
rankrat.sh http     # REST + Streamable HTTP MCP on 127.0.0.1:8080
```

[`rankrat.sh`](rankrat.sh) is a wrapper around `docker run`: it resolves the
mounts, publishes the port, and applies the container hardening flags. The
quick start installs it after giving you a chance to inspect the approximately
300-line script. You can instead run the image yourself: `docker run` is the
supported contract and the wrapper is only convenience.

```sh
docker run -i --rm --init --read-only \
  --user "$(id -u):$(id -g)" \
  --cap-drop=ALL --security-opt no-new-privileges:true \
  --pids-limit 128 --memory 512m --cpus 1 \
  --tmpfs /tmp:rw,noexec,nosuid,size=32m \
  -e RANKRAT_READ_ONLY=true \
  -e RANKRAT_BOUNDARY_FILE=/run/config/boundaries.json \
  -e RANKRAT_OAUTH_TOKEN_ROOT=/run/oauth \
  --mount type=bind,src="$PWD/config",dst=/run/config,readonly \
  --mount type=bind,src="$PWD/secrets",dst=/run/secrets,readonly \
  --mount type=bind,src="$PWD/oauth",dst=/run/oauth \
  psyb0t/rankrat:latest stdio
```

Mount `config/` as a directory, not `config/boundaries.json` as a single file.
The image bakes `/run/config` owned by its own `rankrat` user, so a single-file
mount leaves that directory in place and the boundary file then reads only when
the container uid happens to match the host file's owner. Mounting the directory
replaces it, and `readonly` still covers the file inside.

Swap `stdio` for `http` and add `-p 127.0.0.1:8080:8080`,
`-e RANKRAT_HTTP_HOST=0.0.0.0` and
`-e RANKRAT_HTTP_BEARER_SECRET_FILE=/run/secrets/rankrat/http-bearer-token`.
`RANKRAT_HTTP_HOST=0.0.0.0` binds inside the container; `-p` is what keeps it on
loopback. MCP is then at `http://127.0.0.1:8080/mcp`.

The wrapper reads `RANKRAT_IMAGE`, `RANKRAT_BOUNDARIES`, `RANKRAT_SECRETS`,
`RANKRAT_OAUTH`, `RANKRAT_ENV_FILE`, `RANKRAT_HTTP_PORT` and
`RANKRAT_OAUTH_CALLBACK_PORT` from the environment to point at non-default
paths. Those are host-side only — keep them out of `.env`, which goes straight
to the container, where an unrecognized `RANKRAT_*` variable fails startup.
`rankrat.sh --help` lists every mode.

On a checkout, the Make targets call the same wrapper against the locally built
image, so `make run` and `make run-http` exercise the path above rather than a
second copy of it. See [Verification](#verification) and `make help`.

## Capabilities and discovery

Rankrat does not hide a second API behind the examples in this README. MCP
clients get the exact enabled surface from `tools/list`: read-only mode omits
every write tool, writable mode adds the boundary-limited writes, and agent
onboarding adds its separately gated tool. HTTP callers get the matching
runtime contract from `/openapi.json` when `RANKRAT_ENABLE_OPENAPI=true`; the
source contract is [`src/rankrat/api/openapi.yaml`](src/rankrat/api/openapi.yaml).

The full, grouped MCP catalog is in the
[setup reference](.agents/skills/rankrat/references/setup.md#complete-mcp-tool-catalog).
It covers:

- Google Search Console reporting, inspection, sitemap status and writes;
- GA4 discovery, data streams, historical/realtime reports and renames;
- Bing performance, crawl, indexing, sitemap, backlink and opportunity data;
- PageSpeed Insights, Core Web Vitals and isolated local Lighthouse audits;
- local HTML/JSON-LD eligibility checks and bounded whole-site crawling;
- cross-provider comparisons and traffic-health reports;
- Google/Bing ownership checks and DNS-provider-backed verification;
- URL discovery remediation, site onboarding, and IndexNow submission.

IndexNow is not another dashboard or account that Rankrat reads. It is an open
push protocol for notifying participating search engines that a URL was added,
updated, or deleted. Rankrat's `indexnow_submit` write tool sends a bounded URL
batch with the configured key and public key-file location. One participating
endpoint shares accepted notifications with the other participating engines;
each engine still decides independently whether and when to crawl or index a
URL. See the [official IndexNow documentation](https://www.indexnow.org/documentation?hl=en).

## Local Lighthouse audits

Rankrat can run Chromium locally and return Lighthouse scores plus failed audit
findings without sending the page to PageSpeed Insights. Browser execution is
optional and lives in a separate `psyb0t/rankrat-lighthouse` image. The worker
gets no Google, Bing, IndexNow, OAuth, or HTTP bearer credentials and has no TCP
listener; Rankrat reaches it through `/run/lighthouse/lighthouse.sock`.

| Tool | Result |
| --- | --- |
| `lighthouse_audit` | Performance, accessibility, best-practices, and SEO scores and findings |
| `lighthouse_seo_findings` | Failed SEO audits only |
| `lighthouse_accessibility_findings` | Failed accessibility audits only |
| `lighthouse_performance_findings` | Failed performance audits only |
| `lighthouse_best_practices_findings` | Failed best-practices audits only |

The matching REST routes are under `/v1/lighthouse/`; both MCP transports expose
the same names and strict input schema. Every call requires `account_id`, the
configured `site_url`, and a child `page_url`. The account's `pagespeed_sites`
allow-list is the authority for both PageSpeed and Lighthouse, so enabling the
browser does not create a second URL boundary.

Run the browser worker only against sites whose content you control and trust.
Chromium uses `--no-sandbox` because its namespace and setuid sandboxes are not
available under the documented non-root, capability-free,
`no-new-privileges` container. The worker has no credentials, uses a read-only
root, and forces normal browser traffic through its public-address-only proxy,
but those controls are not a substitute for Chromium's renderer sandbox if a
hostile page exploits the browser. Use a stronger outer runtime such as gVisor
or Kata Containers before auditing untrusted content.

From a checkout, the Compose example is the supported local stack. It runs two
long-lived services plus a one-shot volume initializer:

```sh
make run-http-lighthouse
```

It builds both images, binds Rankrat HTTP to loopback, shares only the Unix
socket volume, drops all capabilities, uses read-only roots, applies process,
CPU, and memory limits, and gives Chromium its own tmpfs and shared-memory
budget. The example expects the same `config/`, `oauth/`, and `secrets/` layout
as [Quick start](#quick-start).

To disable browser execution, leave
`RANKRAT_LIGHTHOUSE_WORKER_SOCKET` empty or do not mount the socket. The five
tools remain discoverable and return a finite `UNAVAILABLE` provider error; no
fallback sends the URL to a third party. The worker permits only HTTP/HTTPS
subresources on ports 80 and 443, resolves targets itself, rejects private and
reserved addresses, and serializes audits one at a time. Redirected final URLs
use Lighthouse's actual final document URL and are rechecked against the
configured site by Rankrat before a report is returned. A public cross-origin
redirect may be fetched before that post-navigation check rejects the report,
just as an allowed page may fetch public third-party subresources; private and
special-address destinations remain blocked at the worker proxy.

## Ownership, whole-site audits, and backlinks

These operations turn Rankrat from a reporting bridge into a bounded SEO work
loop:

| MCP tool | REST route | What it does |
| --- | --- | --- |
| `site_ownership_check` | `POST /v1/site-ownership-checks` | Reads public DNS and Google/Bing ownership status without changing anything |
| `site_ownership_verify` | `POST /v1/site-ownership-verifications` | Creates only provider-issued Google TXT and Bing CNAME records through the configured DNS provider, then redeems propagated proofs |
| `site_audit` | `POST /v1/site-audits` | Crawls a bounded configured site and returns page evidence, findings, remediation text, and a normalized score |
| `site_remediation_apply` | `POST /v1/site-remediations` | Resubmits one bounded sitemap to Google and Bing and a bounded changed-URL batch to Bing |
| `bing_backlink_intelligence` | `POST /v1/bing/backlink-intelligence` | Walks bounded Bing backlink pages for explicit site URLs and aggregates referring domains and anchor text |

Ownership application is idempotent. Exact existing DNS records are reused,
conflicting CNAMEs are refused, arbitrary DNS CRUD is not exposed, and neither
tokens nor provider bodies appear in the receipt. DNS propagation is
asynchronous: call `site_ownership_verify`, then poll `site_ownership_check`
until `complete` is true. Keep verification records in place afterward;
providers can periodically recheck them.

The site audit checks public HTTPS status, robots and sitemap discovery,
titles, descriptions, canonicals, `noindex`, language, H1 count, image alt text,
Open Graph metadata, duplicate titles, non-HTML sitemap entries, broken fetches,
and restricted Google Indexing structured-data eligibility. It follows only
normalized same-site URLs, rejects redirects, IP literals and private/mixed DNS
answers, and reports when page or issue limits truncate the crawl. Its
remediation text tells an agent what needs changing; Rankrat does not edit an
arbitrary CMS or source repository.

Backlink intelligence reports only what Bing exposes for sites the configured
account owns. It does not scrape competitors, buy links, send outreach, or
manufacture backlinks. Its useful output is the evidence needed to find weak
anchor diversity, pages with few referring domains, and links worth reclaiming.

## Agent integrations

The [skill](.agents/skills/rankrat) works in any agent that reads
`.agents/skills/`, and installs natively in the clients below. An agent runs the
published image directly and does not need the wrapper. Installing the skill
adds operating instructions; it does not create credentials, authorize Google,
or start a server. Prepare `config/`, `secrets/`, and `oauth/` as described in
[Quick start](#quick-start) before asking an agent to use Rankrat.

### Claude Code

```sh
claude plugin marketplace add psyb0t/agents
claude plugin install rankrat@psyb0t
```

### Codex

```sh
codex plugin marketplace add psyb0t/agents
codex plugin add rankrat@psyb0t
```

Installed this way the skill invokes as `$rankrat:rankrat`. Codex also picks it
up on its own in any repo containing `.agents/skills/`, where it is `$rankrat`.

### OpenClaw

The skill and the MCP bridge are published to ClawHub on every release:

```sh
openclaw skills install @psyb0t/rankrat
openclaw plugins install clawhub:@psyb0t/rankrat
```

The [OpenClaw plugin](.agents/plugins/rankrat) contributes a static stdio MCP
server that runs the published image directly in read-only mode and needs
nothing else running. OpenClaw deliberately sanitizes a stdio child's ambient
environment, so the launcher uses `$HOME/.config/rankrat/config` and, when
present, sibling `secrets` and `oauth` directories. Run [Quick start](#quick-start)
from `$HOME/.config/rankrat` before enabling the plugin. The launcher uses the
current POSIX UID/GID, keeps provider secrets read-only, and permits Google to
persist a rotated OAuth refresh token. For custom paths, writes, onboarding, or
Lighthouse, replace that static definition with
OpenClaw's native Streamable HTTP configuration; the plugin README provides the
copy-paste command with an environment-backed bearer header. Use the shared
companion deployment for Lighthouse because a static one-container stdio
definition cannot also own the isolated browser worker.

## Write capability

There is no approval ID, admin API, or second bearer token.

```dotenv
# Default: no write services, REST write routes, or MCP write tools exist.
RANKRAT_READ_ONLY=true

# Direct, boundary-limited writes become visible to the trusted caller.
RANKRAT_READ_ONLY=false
```

In read-only mode, write routes are not mounted and write MCP tools are absent
from `tools/list`, so an LLM cannot discover or call them. In writable mode,
all writes remain restricted to the explicit boundaries and the provider's own
permissions. The regular HTTP bearer token protects `/v1/` for non-loopback
HTTP; stdio access is controlled by who can start the process.

Writes cover IndexNow submission, Bing URL/sitemap/property changes, Google
Indexing notifications, Search Console site/sitemap changes, DNS-provider-backed
ownership verification, discovery remediation, and new-site onboarding. They
are marked write/destructive in MCP; callers should still treat provider
acceptance and DNS propagation as asynchronous.

## Finding and naming GA4 containers

GA4 files every property under an *account*, chosen from a dropdown when the
property is created. Nobody picks it deliberately, so properties routinely end up
under an account named for something unrelated — an old merch store, or the
`Google Ads Account` that Ads auto-creates — and then cannot be found in the UI.

Three read-only tools answer "where does this live":

| Tool / route | Answers |
| --- | --- |
| `google_analytics_account_inventory` | Every account the credential can see, with its properties |
| `google_analytics_data_streams` | One configured property's streams and their `G-` measurement IDs |
| `accounts_list` / `sites_list` | The boundary as this server enforces it |

The data-stream read is the one that closes a specific trap: a site's tag carries
a `G-` measurement ID, and until now the only way to confirm it belonged to the
property Rankrat reads from was the Google Analytics UI. Deploying a tag whose
measurement ID points at a different property produces a property that stays
empty and a tag that looks correctly installed.

Renaming is available in writable mode — `google_analytics_account_rename` and
`google_analytics_property_rename`, or `POST /v1/google-analytics/account-renames`
and `/property-renames`. Account names are cosmetic: the numeric ID is what every
boundary, measurement ID and report binds to, so renaming an account breaks
nothing and is the cheapest fix for a misfiled property.

## Onboarding a new site

`onboard-site` creates a GA4 property, a Search Console property and a Bing site
for one URL, then records their IDs in the boundary file. Resource creation and
ownership verification are separate because DNS may take time to propagate.

With a configured DNS provider account, call `site_ownership_verify` after
onboarding. Rankrat selects the adapter from that account's `provider`, requests
the real Google TXT token and Bing CNAME proof, creates only those exact records,
checks public DNS, and redeems each provider when its proof is visible. Poll
`site_ownership_check`; do not interpret empty provider reports until its
`complete` field is true. Cloudflare is the currently shipped DNS adapter. If
the site's DNS provider has no Rankrat adapter, use one of the manual methods
below:

| Property | Methods it accepts |
| --- | --- |
| `sc-domain:example.com` | DNS TXT record, and nothing else |
| `https://example.com/` | GA4 tag, HTML file, meta tag, DNS TXT |
| Bing | Import from a verified Search Console property, XML file, meta tag, CNAME |

Deploy the returned GA4 Measurement ID as a separate operator step so Analytics
can collect data. On a URL-prefix Search Console property it can also be used as
a manual verification method; a Domain property still requires DNS TXT.

The procedure is served rather than left implied, so an agent can walk you through
it instead of guessing: the `rankrat://onboarding` MCP resource, a
`rankrat://onboarding/{site_url}` template for one percent-encoded site, an
`onboarding_guide` tool returning the same document for clients without resource
support, and `POST /v1/onboarding-guides` for callers that do not speak MCP at
all. All are read-only and present even on a read-only server — knowing the
procedure is not a privilege. `rankrat onboard-site` prints the same steps when
it finishes.

The guide also covers the one thing onboarding **cannot** do: create the GA4
account a property has to live inside. Its `manual_provisioning` block gives the
start URL and the ordered clicks — Admin, Create → Account, name it, accept the
Terms of Service — then tells the caller to read the numeric account ID back
with `google_analytics_account_inventory` and pass it to onboarding. It names
`accounts:provisionAccountTicket` too, and says plainly that it is not an
automation route, since the ticket it returns still ends at a Terms of Service
page a human has to accept.

**Agents cannot reach it unless you say so.** It is the only operation that
rewrites the boundary file this server enforces, so `RANKRAT_READ_ONLY=false`
alone is deliberately not enough:

```dotenv
RANKRAT_READ_ONLY=false
RANKRAT_ALLOW_AGENT_ONBOARDING=true
```

Without the second switch `site_onboarding_submit` is absent from `tools/list`
and its REST route is never mounted, however writable the rest of the server is.
The wrapper validates ownership and owner-only permissions before making the
config-directory mount writable for this operation, even in bounded mode, so
the final provider IDs can be atomically persisted.
`rankrat onboard-site` ignores the switch — that is you at a terminal, not an
agent in a session.

One caveat: if a later stage fails the earlier ones are not rolled back. A run
that creates the GA4 property then fails on Search Console leaves that property
real but absent from the boundary file, and re-running creates a second one.
Check Analytics before retrying.

## Credentials

`secrets/`, `oauth/`, `.env`, and `config/boundaries.json` are Git-ignored.
Keep credential files owner-readable only and their directories owner-only.
Never put a credential in source, YAML, Makefiles, or chat.

| Purpose | Local path |
| --- | --- |
| Google OAuth desktop-client JSON | `secrets/google/oauth-client.json` |
| Google OAuth token record | `oauth/google.json` |
| PageSpeed API key | `secrets/google/pagespeed-api-key` |
| Bing Webmaster API key | `secrets/bing/api-key` |
| Cloudflare scoped API token | `secrets/cloudflare/api-token` |
| IndexNow key | `secrets/indexnow/key` |
| HTTP bearer secret | `secrets/rankrat/http-bearer-token` |

### Google

1. Create/select a project in [Google Cloud Console](https://console.cloud.google.com/).
2. Configure [Google Auth platform](https://console.cloud.google.com/auth/overview).
   If External/Testing, add the signing-in user under
   [Audience](https://console.cloud.google.com/auth/audience).
3. Enable [Search Console](https://console.cloud.google.com/apis/library/searchconsole.googleapis.com),
   [Site Verification](https://console.cloud.google.com/apis/library/siteverification.googleapis.com),
   [Analytics Data](https://console.cloud.google.com/apis/library/analyticsdata.googleapis.com),
   [Analytics Admin](https://console.cloud.google.com/apis/library/analyticsadmin.googleapis.com),
   [Indexing](https://console.cloud.google.com/apis/library/indexing.googleapis.com), and
   [PageSpeed](https://console.cloud.google.com/apis/library/pagespeedonline.googleapis.com).
4. Create an **OAuth Desktop app** client at
   [OAuth Clients](https://console.cloud.google.com/auth/clients), download its
   JSON to `secrets/google/oauth-client.json`, configure boundaries, then run:

   ```sh
   rankrat.sh auth-google --account-id google --print-authorization-url
   ```

   The callback listens on `127.0.0.1:49152`; set `RANKRAT_OAUTH_CALLBACK_PORT`
   to move it. Revoke the grant later with
   `rankrat.sh revoke-google --account-id google`.

The one consent flow requests Search Console management, Site Verification,
Indexing, and GA4 read/edit scopes. Re-run `auth-google` after enabling the Site
Verification API so the stored grant contains the new scope. OAuth supplies the
proof and verification calls; the configured DNS provider adapter supplies the
DNS write.

### PageSpeed

PageSpeed is the one Google surface that does not use OAuth at all. It takes a
plain API key on the query string, so the consent flow above grants it nothing
and there is no PageSpeed scope to request.

The key is optional. Without one, PageSpeed calls go out unauthenticated and
Google applies a much tighter quota — fine for a handful of URLs, not for a
regular sweep. Get one:

1. Open [Credentials](https://console.cloud.google.com/apis/credentials) in the
   same project, then **Create credentials → API key**.
2. On the new key choose **Edit API key → Restrict key → API restrictions →
   Restrict key**, and select **PageSpeed Insights API** only. An unrestricted
   key works against every API enabled on the project, which is not what you
   want sitting in a file.
3. Save the key on its own line, no quotes:

   ```sh
   install -m 600 /dev/null secrets/google/pagespeed-api-key
   printf '%s' 'YOUR_KEY' > secrets/google/pagespeed-api-key
   ```

Then set the account's `pagespeed_api_key_file` in `config/boundaries.json` to
the path **inside the container** — `secrets/` is mounted read-only at
`/run/secrets`, so the host file above is:

```json
"pagespeed_api_key_file": "/run/secrets/google/pagespeed-api-key"
```

Leave that field unset to run keyless.

### Bing and IndexNow

Verify each site in [Bing Webmaster Tools](https://www.bing.com/webmasters/),
then create an API key under **Settings → API Access** and save it as
`secrets/bing/api-key`.

IndexNow is a push protocol, not a reporting service. `indexnow_submit` tells
participating search engines which bounded URLs changed; it does not return
rankings, crawl status, or an indexing guarantee. A submission to one
participating endpoint is shared with the other participating engines.

IndexNow key generation and verification are the one part of setup that is not
in the image — they run from a checkout, since neither is something a running
server should be able to do:

```sh
make init-indexnow INDEXNOW_TARGET_ID=site INDEXNOW_HOST=example.com
make verify-indexnow-key INDEXNOW_TARGET_ID=site
```

If the boundary or key lives somewhere else, pass its host path explicitly:

```sh
make verify-indexnow-key INDEXNOW_TARGET_ID=site \
  BOUNDARIES=/absolute/path/to/boundaries.json \
  INDEXNOW_KEY_FILE=/absolute/path/to/indexnow-key
```

The verifier mounts exactly those two files read-only into its sandboxed
container; it does not assume the standard key path after validating the host
file.

Publish the generated `<key>.txt` on the public target host yourself. The
verifier requires exact key content over direct HTTPS, with no redirect. Skip
this section entirely if you are not submitting URLs to IndexNow.

### DNS ownership automation (Cloudflare adapter)

1. Open [Cloudflare API Tokens](https://dash.cloudflare.com/profile/api-tokens)
   and choose **Create Token → Create Custom Token**.
2. Grant only **Zone → DNS → Edit** and **Zone → Zone → Read**. Under Zone
   Resources, include only the zones Rankrat should verify; do not use the
   account-wide Global API Key.
3. Save the token as one line in `secrets/cloudflare/api-token`, mode `0600`.
4. In each zone's Cloudflare **Overview**, copy the 32-character Zone ID into
   that account's `dns_zones` entry as `provider_zone_id` in
   `config/boundaries.json`. Replace both the all-zero ID and `example.com` from
   the example file.

The token can list only the allowed zones and create/read verification records.
Rankrat's API is narrower still: it exposes no generic DNS name, type, or value
chosen by the caller. In `RANKRAT_UNBOUNDED=true` bootstrap mode it may discover
the most-specific zone visible to that fixed Cloudflare account; bounded mode
requires the exact zone in `dns_zones`.

The public REST and MCP contracts are provider-neutral: verification accepts a
`dns_account_id`, and the boundary uses `dns_zones` plus `provider_zone_id`.
Cloudflare details remain inside its adapter. A future Namecheap, GoDaddy, or
other DNS adapter can therefore use the same `site_ownership_verify` operation
without changing callers or adding provider-specific payload fields.

## Configuration

Copy `config/boundaries.json.example` and list only resources Rankrat may touch.
Every account, site, GA4 property, child URL, and IndexNow host is validated at
the boundary; callers cannot choose provider origins or resources outside it.
`.env.example` leaves live-test selectors blank intentionally: set only the
account and resource selectors for providers you configured, so `make setup`
can run those deeper live suites without requiring credentials for the others.
`rankrat.sh setup` separately checks every account represented in the boundary
file. HTTP mode requires the bearer-secret file even on loopback, and mounts it
only into the running container.

`RANKRAT_LIGHTHOUSE_WORKER_SOCKET` is the only Lighthouse setting consumed by
Rankrat. It defaults to `/run/lighthouse/lighthouse.sock`; set it to an empty
value to disable the worker. Worker timeout and socket settings belong to the
companion container and are shown in `docker-compose.yml.example`.

### Unbounded bootstrap mode

For a trusted agent that needs to discover or onboard a resource not yet listed,
start Rankrat with both `RANKRAT_READ_ONLY=false` and `RANKRAT_UNBOUNDED=true`:

```sh
RANKRAT_READ_ONLY=false RANKRAT_UNBOUNDED=true rankrat.sh http
```

The same environment variables work with `rankrat.sh` for stdio MCP. Unbounded
mode is reusable: stop the process, start it with those variables whenever a
trusted agent needs another discovery/onboarding session, then restart without
them to return to normal bounded enforcement.

This keeps credential **accounts** fixed by the boundary file, but bypasses the
resource allow-lists for Google, Bing, PageSpeed, and DNS-provider zone discovery.
It does not expose a credential path, arbitrary provider origin, arbitrary DNS
operation, or IndexNow key target. Non-loopback HTTP still requires the normal
bearer secret.

The smallest bootstrap boundary still names the pre-mounted Google and Bing
credential accounts. In unbounded mode, use discovery, then
`site_onboarding_submit` with the discovered Google Analytics parent account ID.
The operation creates the GA4 property, Search Console property, and Bing site,
then atomically persists their exact IDs and URLs into `boundaries.json`. Restart
with `RANKRAT_UNBOUNDED=false` to enforce the now-expanded allow-list. You may
enable unbounded mode again later for another trusted onboarding session.

For this operation the parent directory holding `boundaries.json` must be owned
by the host user and owner-only (`chmod 700 config`); the file itself must not
be group- or world-writable. The `chmod 700` in [Quick start](#quick-start)
establishes that, and `rankrat.sh` refuses to start an unbounded process against
an unsafe writable mount. Normal bounded runs keep the boundary file read-only.
The Compose example intentionally stays bounded and mounts that file read-only;
use `rankrat.sh` for a reusable unbounded session.

Unbounded mode is also why that run mounts the boundary file's *directory* at
`/run/config` rather than the file itself — onboarding replaces the file
atomically, and a rename over a bind-mounted file is not possible. Running the
image by hand for an unbounded session needs the same substitution.

The authoritative REST contract is
[`src/rankrat/api/openapi.yaml`](src/rankrat/api/openapi.yaml). Run
`make generate-openapi` then `make check-openapi` after a spec change.
The source lists the full writable contract; a running read-only server removes
write routes from its served `/openapi.json` document.

## Verification

From a checkout. Everything below runs in containers — the host needs only
Docker and GNU Make:

```sh
make format
make lint
make test-unit
make test-contract
make test-integration
make test-security
make test-image
make test-lighthouse-image
make audit
make audit-secrets
make audit-compose
make audit-image
```

`make test` and `make lint` rebuild the versioned development image from their
pinned base images by default. If an already-built local image is available but
the registry is temporarily unreachable, `make test-local` reuses only that
exact versioned image after checking it exists. It never updates the image, so
use it only as an outage fallback; return to the normal commands before release.

Live read checks use the shipped image and configured accounts:

```sh
make test-live
make test-live-google-search-console
make test-live-google-analytics
make test-live-pagespeed
make test-live-bing
make test-live-http
```

`make test-live` runs every provider-specific check in sequence, then exercises
the shipped authenticated HTTP and Streamable HTTP MCP server. Individual
targets remain useful while configuring one provider.

`make test-live-indexnow` is a real external submission only when both
`RANKRAT_READ_ONLY=false` and `RANKRAT_RUN_LIVE_INDEXNOW_SUBMISSION=true` are
set. Use an already-public harmless URL.

`make test-lighthouse-image` builds both production images and runs real
public-page audits through production stdio MCP, authenticated REST, and
authenticated Streamable HTTP MCP. Mocked unit and contract suites cover
invalid URL boundaries, malformed worker responses, oversized bodies,
busy/timeout handling, SSRF address classes, and all three transports without
depending on the public network. `make sbom` and `make audit-image` inventory
and scan both production images.

## Security

- Read-only is the safe default and removes write capability discovery.
- Writable mode trusts the process caller while retaining fixed boundaries,
  request limits, provider permissions, fixed origins, and normal HTTP auth.
- Provider responses are parsed into typed bounded results; credentials,
  OAuth records, raw provider bodies, and Bing key URLs are not returned/logged.
  Provider failures expose only a finite category and the generic
  `provider operation failed` message over REST and either MCP transport.
- The production image is non-root; the Compose example uses loopback ports,
  dropped capabilities, no-new-privileges, read-only root, tmpfs, and explicit
  secret mounts.
- Chromium runs in a separate non-root image with no provider secrets or TCP
  API. A local forward proxy blocks loopback, link-local, private, multicast,
  documentation, and other reserved targets after DNS resolution. Rankrat then
  independently reauthorizes the requested and final URLs before returning the
  bounded report. Chromium uses `--no-sandbox` inside that locked-down companion
  because the container is the browser isolation boundary; do not run the
  worker directly on a host or add provider credential mounts to it.
- The Compose initializer is the only root process in the Lighthouse stack. It
  is networkless, receives only `CHOWN` and `FOWNER`, prepares the private Unix
  socket volume, exits, and is not part of the running service set.

## Known gaps

**TODO — monitoring and regression detection.** Persisting audit baselines,
scheduling rechecks, alerting on score/indexing/backlink regressions, and
tracking issue lifecycle over time are not implemented yet. Current reports are
point-in-time and the caller owns storage and scheduling.

**TODO — broader Cloudflare performance controls.** Rankrat currently uses
Cloudflare only for narrowly scoped ownership DNS proofs. Cache settings,
redirect rules, compression, image optimization, firewall controls, and other
zone performance/security mutations are intentionally not exposed yet.

**Discovery remediation is sequential, not transactional.** Google sitemap
submission, Bing sitemap submission, and Bing changed-URL submission are
separate provider writes. If a later provider fails, earlier accepted writes
remain accepted; inspect the returned error, check provider status, and retry
the idempotent operation after fixing the failing provider.

**Onboarding does not roll back a partial failure.** `onboard-site` creates the
GA4 property, then the Search Console property, then the Bing site, and writes
the boundary file only after all three succeed. A failure at stage two or three
leaves the earlier resources real but unrecorded, and because the boundary file
was never written, re-running creates a second copy of them. Check Google
Analytics before retrying.

**GA4 accounts cannot be created from here, and that one is Google's limit, not
Rankrat's.** The Admin API has no `accounts.create`; account provisioning goes
through `provisionAccountTicket`, which returns a ticket that must be completed
in the Google Analytics UI because it involves accepting terms. Property
creation is available and is what `onboard-site` uses.

**Nothing deletes.** `accounts.delete` soft-deletes an entire container and
everything beneath it, and no report this server serves justifies putting that
call behind an agent-reachable tool. Renaming is wrapped; deleting is not, and
that is deliberate rather than pending.

## License

WTFPL. See [LICENSE](LICENSE).

## Release information

See [CHANGELOG.md](CHANGELOG.md) for release history and
[THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md) for the production image's
third-party Python package attribution.
