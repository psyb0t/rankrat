# rankrat

<!-- mcp-name: io.github.psyb0t/rankrat -->

[![CI](https://github.com/psyb0t/rankrat/actions/workflows/pipeline.yml/badge.svg?branch=main)](https://github.com/psyb0t/rankrat/actions/workflows/pipeline.yml)
[![coverage](https://raw.githubusercontent.com/psyb0t/rankrat/badges/coverage.svg)](https://github.com/psyb0t/rankrat/actions/workflows/pipeline.yml)
[![version](https://raw.githubusercontent.com/psyb0t/rankrat/badges/version.svg)](https://github.com/psyb0t/rankrat/tags)
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
list in a boundary file, and no tool widens that from inside a session.
Read-only unless you deliberately turn writes on, at which point the write tools
appear and stay inside the same boundaries. Nothing here crawls a site, tracks a
competitor, or touches a domain you haven't verified — it reads what the
providers already hold about you.

Speaks MCP over stdio and Streamable HTTP, plus a REST API for callers that
don't speak MCP.

**Status:** alpha. Everything documented here works against real accounts; the
tool surface is still free to move.

## Contents

- [Quick start](#quick-start)
- [Running it](#running-it)
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

Rankrat ships as a Docker image; Docker is the only requirement. Create the
working layout in a directory of your choosing — Rankrat reads all three paths
as mounts and never writes outside them:

```sh
mkdir -p config oauth secrets/google secrets/bing secrets/indexnow secrets/rankrat
chmod 700 config oauth secrets secrets/rankrat

curl -fsSL https://raw.githubusercontent.com/psyb0t/rankrat/main/config/boundaries.json.example \
  -o config/boundaries.json
chmod 600 config/boundaries.json

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

`setup` is a live, read-only verification gate. It checks configured provider
access; it does not create a provider resource or submit an IndexNow URL. It
reports the missing local file, OAuth grant, provider permission, or configured
resource that needs attention. It is the one mode that reads `.env`, where the
`RANKRAT_LIVE_*` selectors choose which providers it checks — leave the
selectors for unused providers empty and their checks skip.

## Running it

```sh
rankrat.sh          # MCP over stdio
rankrat.sh http     # REST + Streamable HTTP MCP on 127.0.0.1:8080
```

[`rankrat.sh`](rankrat.sh) is a wrapper around `docker run`: it resolves the
mounts, publishes the port, and applies the container hardening flags. Install
it once —

```sh
curl -fsSL https://raw.githubusercontent.com/psyb0t/rankrat/main/rankrat.sh \
  -o rankrat.sh
less rankrat.sh                       # it is ~250 lines; read before installing
chmod +x rankrat.sh
sudo mv rankrat.sh /usr/local/bin/rankrat.sh
```

— or skip it entirely and run the image yourself. `docker run` is the supported
contract and the wrapper is only convenience:

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

## Agent integrations

The [skill](.agents/skills/rankrat) works in any agent that reads
`.agents/skills/`, and installs natively in the clients below. An agent runs the
published image directly and does not need the wrapper.

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

The [bridge](.agents/plugins/rankrat) covers both transports. It defaults to
stdio, running the published image itself — set `RANKRAT_CONFIG_DIR` (plus
`RANKRAT_SECRETS_DIR` and `RANKRAT_OAUTH_DIR` when those are needed) and nothing
has to be running first. For a shared server, set `RANKRAT_TRANSPORT=http` and
`RANKRAT_URL`, plus `RANKRAT_AUTH_TOKEN` if a bearer secret is configured.

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
Indexing notifications, Search Console site/sitemap changes, and new-site
onboarding. They are marked destructive/non-idempotent in MCP.

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
for one URL, then records their IDs in the boundary file. Two things are worth
knowing before using it.

**It cannot verify the site, and does not pretend to.** Verification proves to a
provider that you own the domain; the token is issued by that provider's own
console and Rankrat holds no credential that can read it. So onboarding returns
success — meaning the three create calls were accepted — while the properties are
still unverified and returning no data. What you do next depends on the property
form:

| Property | Methods it accepts |
| --- | --- |
| `sc-domain:example.com` | DNS TXT record, and nothing else |
| `https://example.com/` | GA4 tag, HTML file, meta tag, DNS TXT |
| Bing | Import from a verified Search Console property, XML file, meta tag, CNAME |

Deploy the returned GA4 Measurement ID first. It is the one artifact Rankrat
hands you directly, and on a URL-prefix property it also satisfies Search Console
verification on its own — after which Bing can simply import that property. Least
work, no extra APIs.

The procedure is served rather than left implied, so an agent can walk you through
it instead of guessing: the `rankrat://onboarding` MCP resource, a
`rankrat://onboarding/{site_url}` template for one percent-encoded site, and an
`onboarding_guide` tool returning the same document for clients without resource
support. All three are read-only and present even on a read-only server — knowing
the procedure is not a privilege. `rankrat onboard-site` prints the same steps
when it finishes.

**Agents cannot reach it unless you say so.** It is the only operation that
rewrites the boundary file this server enforces, so `RANKRAT_READ_ONLY=false`
alone is deliberately not enough:

```dotenv
RANKRAT_READ_ONLY=false
RANKRAT_ALLOW_AGENT_ONBOARDING=true
```

Without the second switch `site_onboarding_submit` is absent from `tools/list`
and its REST route is never mounted, however writable the rest of the server is.
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
| IndexNow key | `secrets/indexnow/key` |
| HTTP bearer secret | `secrets/rankrat/http-bearer-token` |

### Google

1. Create/select a project in [Google Cloud Console](https://console.cloud.google.com/).
2. Configure [Google Auth platform](https://console.cloud.google.com/auth/overview).
   If External/Testing, add the signing-in user under
   [Audience](https://console.cloud.google.com/auth/audience).
3. Enable [Search Console](https://console.cloud.google.com/apis/library/searchconsole.googleapis.com),
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

The one consent flow requests Search Console management, Indexing, and GA4
read/edit scopes. It does not bypass provider-side ownership. Grant that Google
user the required Search Console and GA4 roles first.

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

IndexNow key generation and verification are the one part of setup that is not
in the image — they run from a checkout, since neither is something a running
server should be able to do:

```sh
make init-indexnow INDEXNOW_TARGET_ID=site INDEXNOW_HOST=example.com
make verify-indexnow-key INDEXNOW_TARGET_ID=site
```

Publish the generated `<key>.txt` on the public target host yourself. The
verifier requires exact key content over direct HTTPS, with no redirect. Skip
this section entirely if you are not submitting URLs to IndexNow.

## Configuration

Copy `config/boundaries.json.example` and list only resources Rankrat may touch.
Every account, site, GA4 property, child URL, and IndexNow host is validated at
the boundary; callers cannot choose provider origins or resources outside it.
`.env.example` leaves live-test selectors blank intentionally: set only the
account and resource selectors for providers you configured, so `rankrat.sh
setup` can verify those integrations without requiring credentials for the
others. HTTP mode requires the bearer-secret file even on loopback, and mounts
it only into the running container.

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
resource allow-lists for Google, Bing, and PageSpeed. It does not expose a
credential path, arbitrary provider origin, or IndexNow key target. Non-loopback
HTTP still requires the normal bearer secret.

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
```

Live read checks use the shipped image and configured accounts:

```sh
make test-live-google-search-console
make test-live-google-analytics
make test-live-pagespeed
make test-live-bing
make test-live-http
```

`make test-live-indexnow` is a real external submission only when both
`RANKRAT_READ_ONLY=false` and `RANKRAT_RUN_LIVE_INDEXNOW_SUBMISSION=true` are
set. Use an already-public harmless URL.

## Security

- Read-only is the safe default and removes write capability discovery.
- Writable mode trusts the process caller while retaining fixed boundaries,
  request limits, provider permissions, fixed origins, and normal HTTP auth.
- Provider responses are parsed into typed bounded results; credentials,
  OAuth records, raw provider bodies, and Bing key URLs are not returned/logged.
- The production image is non-root; the Compose example uses loopback ports,
  dropped capabilities, no-new-privileges, read-only root, tmpfs, and explicit
  secret mounts.

## Known gaps

**The published image carries a known high-severity advisory.**
[CVE-2026-69247](https://github.com/advisories/GHSA-g6cj-pr64-35w5) is a
Bleichenbacher oracle in `cryptography`'s PKCS#7 `EnvelopedData` decryption,
affecting `>= 44.0.0, < 50.0.0`. The image ships 49.0.0, reached transitively as
`cryptography` ← `pyjwt` ← `mcp`. Rankrat itself has no PKCS#7 code path — it
never calls `pkcs7_decrypt_der` / `pkcs7_decrypt_pem` / `pkcs7_decrypt_smime`,
handles no `EnvelopedData`, and does not import `jwt` — so the vulnerable
functions are present but unreached. The fix, `cryptography` 50.0.0, was
published on 2026-07-31 and is held out by the dependency age gate in
`pyproject.toml` (`exclude-newer`), which refuses releases younger than seven
days; it becomes installable on 2026-08-07. Waiting was chosen over overriding
that gate, because a fresh release window is the supply-chain hijack window and
a cryptography library is a poor candidate for rushing one.

**v0.3.0 is only partly published.** Its image and GitHub Release exist, but the
image scan gate failed on the advisory above, which skipped the ClawHub and MCP
registry publishes. The registry's newest entry is 0.2.0 until the follow-up
release.

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
