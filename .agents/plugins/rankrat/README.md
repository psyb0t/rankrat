# @psyb0t/rankrat

MCP bridge for [rankrat](https://github.com/psyb0t/rankrat) — boundary-limited
SEO and search-analytics operations over Google Search Console, Bing Webmaster
Tools, GA4, PageSpeed, DNS ownership automation (currently through Cloudflare),
and IndexNow, plus bounded
whole-site/backlink intelligence and optional isolated local Lighthouse audits.

rankrat speaks MCP itself, over both stdio and Streamable HTTP. This plugin has
no OpenClaw runtime extension; its static MCP definition executes the bundled
stdio launcher, which starts the published Rankrat image. Local
Lighthouse audits use an optional second image and therefore require the shared
Streamable HTTP deployment described below.

## stdio (default)

Runs the published image and talks to it directly. Nothing needs to be running
first. OpenClaw intentionally starts stdio MCP children with a restricted
environment, so the static plugin does not depend on exported `RANKRAT_*`
variables. It uses this standard layout:

```bash
$HOME/.config/rankrat/config/boundaries.json
$HOME/.config/rankrat/secrets/
$HOME/.config/rankrat/oauth/
```

Run the repository's [Quick start](https://github.com/psyb0t/rankrat#quick-start)
from `$HOME/.config/rankrat`, then install/enable the plugin. Only `config` is
required — the other two directories can be omitted for a boundary that uses
just credential-free tools. Config and provider secrets are read-only. OAuth
storage is writable because Google may rotate the refresh token during refresh.
The launcher runs as the current POSIX UID/GID with no capabilities, a read-only
root, and CPU, memory, and process limits.

The direct `rankrat-mcp` executable still accepts `RANKRAT_CONFIG_DIR`,
`RANKRAT_SECRETS_DIR`, `RANKRAT_OAUTH_DIR`, and `RANKRAT_IMAGE`; those ambient
overrides are for a direct shell launch, not OpenClaw's sanitized static server.

## Streamable HTTP

For a Rankrat server you are already running, replace the plugin's static stdio
definition with OpenClaw's native Streamable HTTP client. There is no proxy
process and the bearer token never appears in a child-process argument.

```bash
export RANKRAT_AUTH_TOKEN=REPLACE_ME
openclaw mcp set rankrat '{"url":"http://127.0.0.1:8080/mcp","transport":"streamable-http","headers":{"Authorization":"Bearer ${RANKRAT_AUTH_TOKEN}"}}'
openclaw mcp doctor rankrat --probe
```

The single quotes preserve `${RANKRAT_AUTH_TOKEN}` for OpenClaw to resolve at
runtime. If the Rankrat server has no bearer secret, omit the `headers` object.
`openclaw mcp unset rankrat` removes the override and returns to the plugin's
default stdio server.

The skill's setup reference has direct published-image commands for the
credential-free `psyb0t/rankrat-lighthouse` worker and both Rankrat transports,
plus the
[complete MCP tool catalog](../../skills/rankrat/references/setup.md#complete-mcp-tool-catalog),
including the exact five MCP tool names and REST routes for Lighthouse and the
writable IndexNow change-notification tool. IndexNow is a push protocol rather
than a reporting dashboard. The setup reference also documents the worker's
trusted-site scope, Chromium sandbox limitation, and stronger-runtime
recommendation; read that security note before enabling browser audits.
The static stdio plugin does not start that second image, so its five Lighthouse
tools return `UNAVAILABLE` rather than silently falling back to PageSpeed
Insights.

## Writes

rankrat is read-only by default and its write tools are absent from `tools/list`
entirely, so an agent cannot discover them. The static OpenClaw stdio server
intentionally stays at that default. Use the Streamable HTTP form for writes:
the already-running Rankrat server fixes read-only, unbounded, and onboarding
settings at startup, while OpenClaw receives only the MCP URL and bearer header.

When the launcher is invoked directly with unbounded mode or agent onboarding
enabled, it verifies owner-only config-directory permissions, ownership,
regular-file and ancestor-symlink constraints before making only `/run/config`
writable. This lets onboarding persist exact provider IDs instead of mutating a
provider and then failing the local boundary update. Provider secrets remain
read-only.

## License

WTFPL. See [LICENSE](LICENSE).
