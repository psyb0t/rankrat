# @psyb0t/rankrat

MCP bridge for [rankrat](https://github.com/psyb0t/rankrat) — boundary-limited
SEO and search-analytics reads over Google Search Console, Bing Webmaster Tools,
GA4, PageSpeed and IndexNow.

rankrat speaks MCP itself, over both stdio and Streamable HTTP. This bridge
exists so a client can use either without knowing which one it got.

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

## http

Proxies to a server you are already running.

```bash
export RANKRAT_TRANSPORT=http
export RANKRAT_URL=http://127.0.0.1:8080      # the bridge appends /mcp
export RANKRAT_AUTH_TOKEN=...                 # only if the server requires one
```

## Writes

rankrat is read-only by default and its write tools are absent from `tools/list`
entirely, so an agent cannot discover them. On the stdio transport,
`RANKRAT_READ_ONLY` and `RANKRAT_UNBOUNDED` are forwarded to the server if you
set them, which keeps that decision with whoever launched the client rather than
with this bridge. On the http transport the running server already fixed it.

## License

WTFPL. See [LICENSE](LICENSE).
