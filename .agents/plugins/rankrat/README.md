# @psyb0t/rankrat

MCP bridge for [rankrat](https://github.com/psyb0t/rankrat) — boundary-limited
SEO and search-analytics reads over Google Search Console, Bing Webmaster Tools,
GA4, PageSpeed and IndexNow.

rankrat speaks MCP itself, over both stdio and Streamable HTTP. This plugin
contributes a static OpenClaw MCP server; it does not execute plugin code.

## stdio (default)

Runs the published image and talks to it directly. Nothing needs to be running
first.

```bash
export RANKRAT_CONFIG_DIR=/path/to/config     # holds boundaries.json
export RANKRAT_SECRETS_DIR=/path/to/secrets   # provider credentials
export RANKRAT_OAUTH_DIR=/path/to/oauth       # stored Google OAuth token
```

Only `RANKRAT_CONFIG_DIR` is required — the other two can be omitted for a
boundary that uses just the credential-free tools. Every mount is read-only, and
the container runs with no capabilities and a read-only root.

`RANKRAT_IMAGE` overrides the image (default `psyb0t/rankrat`).

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

## Writes

rankrat is read-only by default and its write tools are absent from `tools/list`
entirely, so an agent cannot discover them. On the stdio transport,
`RANKRAT_READ_ONLY` and `RANKRAT_UNBOUNDED` are forwarded to the server if you
set them, which keeps that decision with whoever launched the client rather than
with this plugin. On Streamable HTTP the running server already fixed it.

## License

WTFPL. See [LICENSE](LICENSE).
