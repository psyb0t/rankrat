# rankrat — setup reference

Everything the [skill](../SKILL.md) needs but does not need loaded up front:
configuration, credentials, and how to run it.

## Configuration

All settings are read from the environment with the `RANKRAT_` prefix, so a
field named `http_port` is set by `RANKRAT_HTTP_PORT`. The defaults below are
the ones in the settings model, not example values.

| Variable | Default | Purpose |
|---|---|---|
| `RANKRAT_HTTP_HOST` | `127.0.0.1` | Listen address in `http` mode. Loopback by default — bind wider only deliberately. |
| `RANKRAT_HTTP_PORT` | `8080` | Listen port in `http` mode. |
| `RANKRAT_BOUNDARY_FILE` | `/run/config/boundaries.json` | The accounts and sites this server is allowed to touch. |
| `RANKRAT_SECRET_ROOT` | `/run/secrets` | Directory holding provider credentials. |
| `RANKRAT_OAUTH_TOKEN_ROOT` | `/run/oauth` | Directory holding stored Google OAuth tokens. |
| `RANKRAT_LOG_FILE` | `/tmp/rankrat/rankrat.log` | Log destination. |
| `RANKRAT_LOG_LEVEL` | `INFO` | Standard Python log levels. |
| `RANKRAT_ENABLE_OPENAPI` | `false` | Serve the OpenAPI document. |
| `RANKRAT_READ_ONLY` | `true` | See "Write access" below. |
| `RANKRAT_UNBOUNDED` | `false` | Reusable trusted-onboarding mode; see "Unbounded mode". Requires `RANKRAT_READ_ONLY=false`. |
| `RANKRAT_HTTP_BEARER_SECRET_FILE` | unset | File holding the bearer token required on HTTP requests. Unset means no auth, so only do that on loopback. |

The supported names and safe defaults are in `.env.example`. Invalid values for
supported settings fail startup instead of being silently accepted.
`make run-http` always supplies a bearer-secret file, including for loopback
use; a custom loopback launch may deliberately omit it.

The `RANKRAT_LIVE_*` variables select exactly which configured provider
resources `make setup` verifies. They are blank in `.env.example`: set them
only for providers you configured and leave all unused-provider selectors blank
so their opt-in live checks skip.

## The boundary file

`boundaries.json` is what fixes the scope. It lists the accounts and the sites
or properties within them that this server may read. In bounded mode an agent
cannot add to it, and nothing in the tool surface enumerates properties outside
it — a site that is not listed is not reachable, whatever the underlying account
can see.

Keep it to the properties you actually want an agent reading.

## Write access

`RANKRAT_READ_ONLY` defaults to `true`, and the effect is stronger than a
refusal at call time: the tool catalog is built from that setting, so the write
tools are absent from `tools/list` and the REST write routes are not mounted. An
agent cannot discover them, let alone call them.

Set it to `false` and they appear. There is no approval ID, admin API, or second
bearer token — the trusted caller gets direct access, with writes still confined
to the configured boundaries and to what the provider account itself permits.
Writes cover IndexNow submission, Bing URL/sitemap/property changes, Google
Indexing notifications, Search Console site/sitemap changes, and new-site
onboarding, and are marked destructive and non-idempotent in MCP.

## Unbounded mode

`RANKRAT_UNBOUNDED=true` is a bootstrap escape hatch for onboarding a resource
that is not in the boundary file yet. It requires `RANKRAT_READ_ONLY=false`;
setting it alone is a startup error.

What it changes: authorization still resolves the credential **account** from
the boundary file, so accounts stay fixed, but resource allow-list checks are
skipped — including Google resource/account discovery and the GA4
parent-account pin.

What it does *not* change is worth knowing, because it is narrower than "the
boundary is off":

- **URL containment still applies.** A candidate page URL must still normalize
  as public HTTPS and sit beneath the property or site it was requested under,
  so naming an unlisted property does not let a caller reach a URL outside that
  property.
- **IndexNow targets stay resolved from the boundary file**, so no new key
  target appears.
- **The OAuth credential path stays resolved from the boundary file**, so no new
  credential becomes reachable.
- Non-loopback HTTP still requires the bearer secret.

Use it for a trusted discovery/onboarding session: start unbounded, discover
and onboard, let onboarding write the discovered IDs back into the boundary
file, then restart without it so the now-expanded allow-list is enforced again.
It is reusable: enable it again later when a trusted agent needs to expand the
boundary. A server left running unbounded is a trusted-caller deployment; treat
it that way.

## Provider credentials

Each provider is optional; rankrat exposes tools for whichever ones are
configured. Ask the `provider_readiness` tool which are live rather than
inferring it from an empty result.

- **Google Search Console / Google Analytics 4 / Google Indexing** — OAuth. The
  CLI runs one authorization flow and stores the resulting token under
  `RANKRAT_OAUTH_TOKEN_ROOT`. It requests Search Console management, Google
  Indexing, and GA4 read/edit scopes; provider-side ownership still controls
  what the account can do.
- **Bing Webmaster Tools** — an API key from the Bing Webmaster dashboard,
  placed under `RANKRAT_SECRET_ROOT`.
- **PageSpeed Insights** — an API key, same location, and the one Google surface
  that does not use OAuth: the key goes on the query string, so the Google
  consent flow grants it nothing. It is optional — with no key configured the
  call still goes out, unauthenticated, under a much tighter quota.

Credentials stay on the host running rankrat. They are used to call the provider
APIs over HTTPS and are not sent anywhere else.

## Running it

An agent runs the published image directly; the repo's Make targets exist for a
human working on a checkout, and are how the boundary file, credentials and
Google authorization get created in the first place.

Both transports take the same three read-only mounts. Container-side paths are
the server's defaults, so only the host side changes:

| Host | Container | Holds |
|---|---|---|
| `./config` | `/run/config` | `boundaries.json` |
| `./secrets` | `/run/secrets` | provider credentials, HTTP bearer secret |
| `./oauth` | `/run/oauth` | stored Google OAuth token |

**stdio** — the default mode, for a client that owns the process:

```bash
docker run -i --rm --init --read-only \
  --cap-drop=ALL --security-opt no-new-privileges:true \
  --tmpfs /tmp:rw,noexec,nosuid,size=32m \
  --mount type=bind,src="$PWD/config",dst=/run/config,readonly \
  --mount type=bind,src="$PWD/secrets",dst=/run/secrets,readonly \
  --mount type=bind,src="$PWD/oauth",dst=/run/oauth,readonly \
  psyb0t/rankrat stdio
```

**Streamable HTTP** — for a shared server. MCP lands at `/mcp` and the REST API
shares the port:

```bash
docker run --rm --init --read-only \
  --cap-drop=ALL --security-opt no-new-privileges:true \
  --tmpfs /tmp:rw,noexec,nosuid,size=32m \
  -p 127.0.0.1:8080:8080 \
  -e RANKRAT_HTTP_HOST=0.0.0.0 \
  -e RANKRAT_HTTP_BEARER_SECRET_FILE=/run/secrets/rankrat/http-bearer-token \
  --mount type=bind,src="$PWD/config",dst=/run/config,readonly \
  --mount type=bind,src="$PWD/secrets",dst=/run/secrets,readonly \
  --mount type=bind,src="$PWD/oauth",dst=/run/oauth,readonly \
  psyb0t/rankrat http
```

`RANKRAT_HTTP_HOST=0.0.0.0` binds inside the container while `-p` keeps it on
loopback. MCP is then at `http://127.0.0.1:8080/mcp`; send
`Authorization: Bearer <token>` whenever a bearer secret is configured.

## Checking it works

- `server_info` — the server is up and which mode it is in.
- `provider_readiness` — which providers are actually configured.
- `accounts_list` / `sites_list` — the boundary as the server sees it.
- `diagnostics` — deeper detail when one of the above is not what you expected.

If a provider-specific tool returns nothing, check `provider_readiness` before
assuming the data is missing upstream.
