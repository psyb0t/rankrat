# @psyb0t/rankrat

MCP bridge for [rankrat](https://github.com/psyb0t/rankrat) — account-authorized
SEO and search-analytics operations over Google Search Console, Google Tag
Manager, Bing Webmaster Tools, GA4, Microsoft Clarity, PageSpeed, DNS ownership
automation (currently through Cloudflare), CrUX, and IndexNow, plus typed tag
management, provider-neutral managed edge redirects, safe Bing content
submission, bounded whole-site/internal-link/Bing-backlink/content-opportunity
reports, persistent monitoring, and optional isolated local Lighthouse audits.

The topic-based [operator manual](https://github.com/psyb0t/rankrat/tree/main/docs)
covers credentials, boundaries, all three transports, feature workflows,
security, and troubleshooting. This README covers only OpenClaw-specific
behavior.

rankrat speaks MCP itself, over both stdio and Streamable HTTP. This plugin has
no OpenClaw runtime extension; its static MCP definition executes the bundled
stdio launcher, which starts the published Rankrat image. Local
Lighthouse audits use an optional second image and therefore require the shared
Streamable HTTP deployment described below.

## stdio (default)

Runs the published image and talks to it directly. Nothing needs to be running
first. OpenClaw intentionally starts stdio MCP children with a restricted
environment. The plugin declares the settings it consumes and uses this
standard layout when `RANKRAT_DATA_DIR` is unset:

```bash
$HOME/.config/rankrat/config/boundaries.json
$HOME/.config/rankrat/secrets/
$HOME/.config/rankrat/oauth/
$HOME/.config/rankrat/state/
```

Run the repository's [Quick start](https://github.com/psyb0t/rankrat#quick-start),
then set `RANKRAT_DATA_DIR` to that checkout's absolute path or move its fixed
layout under `$HOME/.config/rankrat`. The profile must contain `config/`,
`secrets/`, `oauth/`, and `state/`; `config/boundaries.json` is required.
Provider secrets are read-only. OAuth storage is writable because Google may
rotate the refresh token during refresh; state is writable for the SQLite
monitor database. The launcher runs as the current POSIX UID/GID with no
capabilities, a read-only root, and CPU, memory, and process limits.

The static stdio child uses Rankrat's writable default, so it can create
monitors and run one explicitly as well as read persistent history. Set
`RANKRAT_READ_ONLY=true` for a direct launcher when only reads should exist.
Automatic due-monitor scheduling runs only in Rankrat's long-lived HTTP mode,
so use the shared Streamable HTTP deployment when monitors must execute without
an agent keeping a stdio process alive.

`RANKRAT_DATA_DIR=/absolute/path/to/rankrat-profile` is the only host-path
override. It selects config, credentials, OAuth authorization, and state as one
unit, so multiple site projects can reuse the same logged-in provider accounts.
The launcher also accepts `RANKRAT_IMAGE`, `RANKRAT_READ_ONLY`, and
`RANKRAT_LOG_LEVEL` through its declared plugin environment.

## Streamable HTTP

For a Rankrat server you are already running, replace the plugin's static stdio
definition with OpenClaw's native Streamable HTTP client. There is no proxy
process and the bearer token never appears in a child-process argument.

Start the shared Rankrat + Lighthouse server from the installed public launcher.
The selected profile owns the generated/preserved Compose deployment:

```bash
rankrat --data-dir /absolute/path/to/rankrat-profile http -d
```

```bash
export RANKRAT_AUTH_TOKEN="$(<"$HOME/.config/rankrat/secrets/rankrat/http-bearer-token")"
openclaw mcp set rankrat '{"url":"http://127.0.0.1:8080/mcp","transport":"streamable-http","headers":{"Authorization":"Bearer ${RANKRAT_AUTH_TOKEN}"}}'
openclaw mcp doctor rankrat --probe
```

The first command loads the secret from its owner-readable file without placing
the value in shell history. The single quotes preserve
`${RANKRAT_AUTH_TOKEN}` for OpenClaw to resolve at runtime. If the Rankrat
server has no bearer secret, omit the `headers` object.
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

Rankrat is writable by default. The static OpenClaw stdio server therefore
exposes every supported mutation permitted by the configured provider accounts,
including site onboarding. Set `RANKRAT_READ_ONLY=true` to make all write tools
absent from `tools/list`. Use the Streamable HTTP form for a shared service with
centralized bearer authentication; OpenClaw receives only the MCP URL and
bearer header.
Within one running server, Cloudflare cache-template writes are serialized per
zone. Managed edge-redirect writes use provider-neutral tool names and the
current Cloudflare adapter changes only Rankrat-managed rules.

In writable mode the launcher verifies owner-only config-directory permissions,
ownership, regular-file and ancestor-symlink constraints before making only
`/run/config` writable. This lets discovery and onboarding persist provider
inventory instead of mutating a provider and then failing the local update.
Provider secrets remain read-only.

## License

WTFPL. See [LICENSE](LICENSE).
