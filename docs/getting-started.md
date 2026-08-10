# Getting started

This guide takes a fresh machine to a verified read-only deployment. It does
not create or modify provider resources.

## Contents

- [Prerequisites](#prerequisites)
- [Install the wrapper](#install-the-wrapper)
- [Create the working layout](#create-the-working-layout)
- [Configure providers incrementally](#configure-providers-incrementally)
- [Authorize Google](#authorize-google)
- [Run readiness](#run-readiness)
- [Start read-only Rankrat](#start-read-only-rankrat)
- [First calls](#first-calls)
- [Next steps](#next-steps)

## Prerequisites

- Docker Engine with `docker run` access;
- a POSIX shell;
- `curl`, `openssl`, and standard core utilities.

Contributor commands additionally use GNU Make. Python, Node, uv, pnpm, and
security scanners run in pinned containers.

## Install the wrapper

Rankrat ships as `psyb0t/rankrat`. The wrapper is readable convenience around
the supported `docker run` contract.

```sh
curl -fsSL https://raw.githubusercontent.com/psyb0t/rankrat/main/rankrat.sh -o rankrat.sh
less rankrat.sh
chmod +x rankrat.sh
sudo mv rankrat.sh /usr/local/bin/rankrat.sh
rankrat.sh --help
```

Without access to `/usr/local/bin`, keep it locally and use `./rankrat.sh`.

## Create the working layout

```sh
mkdir -p config oauth state \
  secrets/{google,bing,cloudflare,indexnow,rankrat,ahrefs,majestic,moz,semrush,dataforseo}
chmod 700 config oauth state secrets secrets/*

curl -fsSL https://raw.githubusercontent.com/psyb0t/rankrat/main/config/boundaries.json.example \
  -o config/boundaries.json
curl -fsSL https://raw.githubusercontent.com/psyb0t/rankrat/main/.env.example -o .env
chmod 600 config/boundaries.json .env

install -m 600 /dev/null secrets/rankrat/http-bearer-token
openssl rand -base64 32 | tr -d '\n' > secrets/rankrat/http-bearer-token
```

| Host path | Container path | Access | Purpose |
| --- | --- | --- | --- |
| `config/` | `/run/config` | Read-only normally | Resource allow-list |
| `secrets/` | `/run/secrets` | Read-only | Provider credentials and HTTP bearer |
| `oauth/` | `/run/oauth` | Read/write | Google refresh records |
| `state/` | `/run/state` | Read/write | SQLite monitors, snapshots, issues, events |
| `.env` | Setup/live tests only | Read-only | Runtime examples and opt-in selectors, never credentials |

Mount `config/` as a directory, not the boundary file alone. The image owns its
baked `/run/config`; a file-only bind can make the file unreadable when host and
container user IDs differ. Directory mounting also permits validated onboarding
to replace the boundary atomically.

## Configure providers incrementally

Remove every example account you do not use. Replace all example resources and
the all-zero Cloudflare zone ID. The document must retain at least one account
or IndexNow target.

For each provider:

1. Put its credential in the documented file.
2. Add the account and exact resources to the boundary.
3. Run readiness.
4. Add the next provider only after the first passes.

[Providers and credentials](providers.md) contains exact console links,
permissions, formats, and boundary fields.

## Authorize Google

Put an OAuth Desktop client JSON at `secrets/google/oauth-client.json`, then:

```sh
rankrat.sh auth-google --account-id google --print-authorization-url
```

Open the URL and allow the loopback callback to finish. The default callback is
`127.0.0.1:49152`; set `RANKRAT_OAUTH_CALLBACK_PORT` if needed. The resulting
refresh-only record normally lives at `oauth/google.json`.

Revoke and remove it with:

```sh
rankrat.sh revoke-google --account-id google
```

See [Google OAuth](providers.md#google-oauth) for project setup and APIs.

## Run readiness

```sh
rankrat.sh setup
```

This reports missing files, OAuth grants, provider permissions, and configured
resources. It does not create provider resources, submit URLs/sitemaps, or
perform an IndexNow write. Commercial backlink readiness performs a one-result
read and may consume a paid API unit.

From a checkout:

```sh
make setup
```

This also creates missing paths without overwriting, rejects symlinks,
normalizes sensitive permissions, builds images, runs configured deep live
selectors, and verifies shipped HTTP/MCP transports. Leave unused
`RANKRAT_LIVE_*` selectors blank.

## Start read-only Rankrat

```sh
rankrat.sh          # stdio MCP
rankrat.sh http     # REST + Streamable HTTP MCP
```

HTTP endpoints:

- `GET http://127.0.0.1:8080/healthz`;
- `GET http://127.0.0.1:8080/ready`;
- MCP at `http://127.0.0.1:8080/mcp`;
- REST under `http://127.0.0.1:8080/v1/`.

When bearer auth is configured, only `/healthz` is public. Send the contents of
`secrets/rankrat/http-bearer-token` as `Authorization: Bearer <token>` to
`/ready`, `/mcp`, `/v1/`, `/openapi.json`, and the docs UI. Stdio does not use
the bearer.

## First calls

1. `server_info` — process policy and capability metadata.
2. `accounts_list` and `sites_list` — configured non-secret scope.
3. `diagnostics` — local checks without provider calls.
4. `provider_readiness` — live access for one account.

Enable runtime OpenAPI only when wanted:

```dotenv
RANKRAT_ENABLE_OPENAPI=true
```

Then inspect `/openapi.json`. The committed [`openapi.json`](../openapi.json)
contains the full writable contract; the runtime document removes disabled
routes.

## Next steps

- [Configuration and boundaries](configuration.md)
- [Transports and deployment](transports.md)
- [Feature workflows](features.md)
- [Security](security.md)
- [Troubleshooting](troubleshooting.md)
