# rankrat — setup reference

Everything the [skill](../SKILL.md) needs but does not need loaded up front:
configuration, credentials, and how to run it.

## Configuration

All settings are read from the environment with the `RANKRAT_` prefix, so a
field named `http_port` is set by `RANKRAT_HTTP_PORT`. The defaults below are
the ones in the settings model, not example values.

| Variable | Default | Purpose |
|---|---|---|
| `RANKRAT_MODE` | `stdio` | `stdio` for a client that spawns the process, `http` to listen. |
| `RANKRAT_HTTP_HOST` | `127.0.0.1` | Listen address in `http` mode. Loopback by default — bind wider only deliberately. |
| `RANKRAT_HTTP_PORT` | `8080` | Listen port in `http` mode. |
| `RANKRAT_BOUNDARY_FILE` | `/run/config/boundaries.json` | The accounts and sites this server is allowed to touch. |
| `RANKRAT_SECRET_ROOT` | `/run/secrets` | Directory holding provider credentials. |
| `RANKRAT_OAUTH_TOKEN_ROOT` | `/run/oauth` | Directory holding stored Google OAuth tokens. |
| `RANKRAT_LOG_FILE` | `/tmp/rankrat/rankrat.log` | Log destination. |
| `RANKRAT_LOG_LEVEL` | `INFO` | Standard Python log levels. |
| `RANKRAT_ENABLE_OPENAPI` | `false` | Serve the OpenAPI document. |
| `RANKRAT_ENABLE_WRITES` | `false` | See "Write access" below. |
| `RANKRAT_HTTP_BEARER_SECRET_FILE` | unset | File holding the bearer token required on HTTP requests. Unset means no auth, so only do that on loopback. |
| `RANKRAT_ADMIN_BEARER_SECRET_FILE` | unset | File holding the admin bearer token. Required when writes are enabled. |

## The boundary file

`boundaries.json` is what fixes the scope. It lists the accounts and the sites
or properties within them that this server may read. An agent cannot add to it,
and nothing in the tool surface enumerates properties outside it — a site that
is not listed is not reachable, whatever the underlying account can see.

Keep it to the properties you actually want an agent reading.

## Write access

`RANKRAT_ENABLE_WRITES` defaults to `false`, and the effect is stronger than a
refusal at call time: the tool catalog is built from that flag, so the
submission tools are not present in the tool list at all. An agent cannot see
them, let alone call them.

Setting it to `true` also requires `RANKRAT_ADMIN_BEARER_SECRET_FILE` to point
at a real file — the server refuses to start otherwise, so the capability cannot
be switched on without also switching on authentication for it.

## Provider credentials

Each provider is optional; rankrat exposes tools for whichever ones are
configured. Ask the `provider_readiness` tool which are live rather than
inferring it from an empty result.

- **Google Search Console / Google Analytics 4** — OAuth. The CLI has operator
  modes that run the OAuth flow and store the resulting token under
  `RANKRAT_OAUTH_TOKEN_ROOT`. Read scopes are requested by default
  (`webmasters.readonly`, `analytics.readonly`).
- **Bing Webmaster Tools** — an API key from the Bing Webmaster dashboard,
  placed under `RANKRAT_SECRET_ROOT`.
- **PageSpeed Insights** — an API key, same location.

Credentials stay on the host running rankrat. They are used to call the provider
APIs over HTTPS and are not sent anywhere else.

## Running it

HTTP mode, loopback, read-only:

```bash
docker run --rm -p 127.0.0.1:8080:8080 \
  -v "$PWD/config:/run/config:ro" \
  -v "$PWD/secrets:/run/secrets:ro" \
  -v "$PWD/oauth:/run/oauth:ro" \
  psyb0t/rankrat http
```

MCP over Streamable HTTP is then at `http://127.0.0.1:8080/mcp`.

For a client that spawns the process itself, run the same image with `stdio`
instead of `http` and no port mapping.

## Checking it works

- `server_info` — the server is up and which mode it is in.
- `provider_readiness` — which providers are actually configured.
- `accounts_list` / `sites_list` — the boundary as the server sees it.
- `diagnostics` — deeper detail when one of the above is not what you expected.

If a provider-specific tool returns nothing, check `provider_readiness` before
assuming the data is missing upstream.
