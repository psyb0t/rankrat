# rankrat

<!-- mcp-name: io.github.psyb0t/rankrat -->

[![CI](https://github.com/psyb0t/rankrat/actions/workflows/pipeline.yml/badge.svg?branch=main)](https://github.com/psyb0t/rankrat/actions/workflows/pipeline.yml)
[![coverage](https://raw.githubusercontent.com/psyb0t/rankrat/badges/coverage.svg)](https://github.com/psyb0t/rankrat/actions/workflows/pipeline.yml)
[![version](https://raw.githubusercontent.com/psyb0t/rankrat/badges/version.svg)](https://github.com/psyb0t/rankrat/tags)
[![license](https://raw.githubusercontent.com/psyb0t/rankrat/badges/license.svg)](LICENSE)

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
- [Agent integrations](#agent-integrations)
- [Write capability](#write-capability)
- [Credentials](#credentials)
- [Configuration](#configuration)
- [Verification](#verification)
- [Security](#security)
- [Release information](#release-information)

## Quick start

Rankrat requires Docker and GNU Make on the host. Start by creating the ignored
local layout:

```sh
make init-config
```

`make init-config` also creates an owner-only random HTTP bearer secret at
`secrets/rankrat/http-bearer-token`; it retains an existing regular file rather
than replacing it.

Then configure `config/boundaries.json`, place only the credentials for the
providers you intend to use at the paths in [Credentials](#credentials), and
authorize Google if configured:

```sh
make auth-google
make setup
```

`make setup` is a live, read-only verification gate. It checks configured
provider access and exercises the shipped HTTP/MCP image; it does not create a
provider resource or submit an IndexNow URL. It reports the missing local file,
OAuth grant, provider permission, or configured resource that needs attention.
Set the matching `RANKRAT_LIVE_*` selectors in `.env` for each provider you
configure; leave selectors for unused providers empty so their live checks skip.

For stdio MCP, use `make run`. For Streamable HTTP/REST on loopback port 8080,
use `make run-http`. Both targets build the production image and use the
configured ignored `config/`, `secrets/`, and `oauth/` paths.

## Agent integrations

The [skill](.agents/skills/rankrat) works in any agent that reads
`.agents/skills/`, and installs natively in the clients below. The Make targets
above are for humans on a checkout; an agent runs the published image.

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
   make auth-google
   ```

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

```sh
make init-indexnow INDEXNOW_TARGET_ID=site INDEXNOW_HOST=example.com
make verify-indexnow-key INDEXNOW_TARGET_ID=site
```

Publish the generated `<key>.txt` on the public target host yourself. The
verifier requires exact key content over direct HTTPS, with no redirect.

## Configuration

Copy `config/boundaries.json.example` and list only resources Rankrat may touch.
Every account, site, GA4 property, child URL, and IndexNow host is validated at
the boundary; callers cannot choose provider origins or resources outside it.
`.env.example` leaves live-test selectors blank intentionally: set only the
account and resource selectors for providers you configured, so `make setup`
can verify those integrations without requiring credentials for the others.
For HTTP use, `make init-config` creates the owner-only bearer-secret file at
the configured path (`secrets/rankrat/http-bearer-token` by default).
`make run-http` requires it even on loopback and mounts it only into the
running container.

### Unbounded bootstrap mode

For a trusted agent that needs to discover or onboard a resource not yet listed,
start Rankrat with both `RANKRAT_READ_ONLY=false` and `RANKRAT_UNBOUNDED=true`:

```sh
RANKRAT_READ_ONLY=false RANKRAT_UNBOUNDED=true make run-http
```

The same environment variables work with `make run` for stdio MCP. Unbounded
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
be group- or world-writable. `make init-config` establishes those permissions,
and `make run` / `make run-http` reject an unsafe writable mount before starting
an unbounded process. Normal bounded runs keep the boundary file read-only.
The Compose example intentionally stays bounded and mounts that file read-only;
use the Make targets for a reusable unbounded session.

The authoritative REST contract is
[`src/rankrat/api/openapi.yaml`](src/rankrat/api/openapi.yaml). Run
`make generate-openapi` then `make check-openapi` after a spec change.
The source lists the full writable contract; a running read-only server removes
write routes from its served `/openapi.json` document.

## Verification

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

## License

WTFPL. See [LICENSE](LICENSE).

## Release information

See [CHANGELOG.md](CHANGELOG.md) for release history and
[THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md) for the production image's
third-party Python package attribution.
