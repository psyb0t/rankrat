# @psyb0t/rankrat

MCP bridge for [rankrat](https://github.com/psyb0t/rankrat): account-authorized
SEO and search-analytics operations over Google Search Console, Google Tag
Manager, Bing Webmaster Tools, GA4, Microsoft Clarity, PageSpeed, DNS ownership
automation (currently through Cloudflare), CrUX, and IndexNow, plus typed tag
management, provider-neutral managed edge redirects, safe Bing content
submission, bounded whole-site/internal-link/Bing-backlink/content-opportunity
reports, persistent monitoring, and optional isolated local Lighthouse audits.

The [operator manual](https://psyb0t.github.io/rankrat/) covers credentials,
boundaries, the HTTP deployment, feature workflows, security, and
troubleshooting. This README covers only OpenClaw-specific behavior.

Rankrat speaks MCP over Streamable HTTP at `/mcp`. The stdio transport was
removed in 0.21.0, so this package no longer starts the Rankrat image itself.
It is a thin stdio-to-HTTP bridge, built on
[`mcp-remote`](https://www.npmjs.com/package/mcp-remote), to a server you run.

## Start the server

Run the shared Rankrat + Lighthouse stack from the public launcher. The selected
profile owns the generated or preserved Compose deployment:

```bash
rankrat --data-dir /absolute/path/to/rankrat-profile http -d
```

Long-lived HTTP is also the only mode that runs the monitor scheduler and the
Lighthouse worker, so every tool works through it.

## Bridge plugin

```bash
openclaw plugins install clawhub:@psyb0t/rankrat
```

Set these in the plugin's environment:

| Variable | Required | Value |
| --- | --- | --- |
| `RANKRAT_URL` | yes | Base URL of the server, e.g. `http://127.0.0.1:8080`. The bridge appends `/mcp` |
| `RANKRAT_TOKEN` | when the server has a bearer | Contents of the profile's `secrets/rankrat/http-bearer-token` |

The bridge passes the bearer header to `mcp-remote` as the literal
`${RANKRAT_TOKEN}` placeholder, which `mcp-remote` fills in from its own
environment, so the token never shows up in a process argument list.

## Native Streamable HTTP

OpenClaw can also talk to the server directly, with no bridge process:

```bash
RANKRAT_TOKEN_FILE="$HOME/.config/rankrat/secrets/rankrat/http-bearer-token"
export RANKRAT_AUTH_TOKEN="$(<"$RANKRAT_TOKEN_FILE")"
openclaw mcp set rankrat '{
  "url": "http://127.0.0.1:8080/mcp",
  "transport": "streamable-http",
  "headers": {
    "Authorization": "Bearer ${RANKRAT_AUTH_TOKEN}"
  }
}'
openclaw mcp doctor rankrat --probe
```

The first two lines load the secret from its owner-readable file without
placing the value in shell history. The single quotes preserve `${RANKRAT_AUTH_TOKEN}`
for OpenClaw to resolve at runtime. If the server has no bearer secret, omit the
`headers` object. `openclaw mcp unset rankrat` removes the override and returns
to the bridge plugin.

The skill's setup reference has the
[complete MCP tool catalog](../../skills/rankrat/references/setup.md#complete-mcp-tool-catalog),
including the exact five MCP tool names and REST routes for Lighthouse and the
writable IndexNow change-notification tool. It also documents the Lighthouse
worker's trusted-site scope, Chromium sandbox limitation, and stronger-runtime
recommendation; read that security note before enabling browser audits.

## Writes

Rankrat is writable by default, so the server exposes every supported mutation
the configured provider accounts permit, including site onboarding. Start the
server with `RANKRAT_READ_ONLY=true` to make every write tool absent from
`tools/list`. The bridge only forwards; it cannot add or remove tools.

Within one running server, Cloudflare cache-template writes are serialized per
zone. Managed edge-redirect writes use provider-neutral tool names, and the
current Cloudflare adapter changes only Rankrat-managed rules.

## License

WTFPL. See [LICENSE](LICENSE).
