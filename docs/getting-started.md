# Getting started

This guide takes a fresh machine to a verified Rankrat deployment. Guided setup
does not create site properties or submit URLs; those operations become
available to the human's agent after setup succeeds.

## Contents

- [Prerequisites](#prerequisites)
- [Install the wrapper](#install-the-wrapper)
- [Create the working layout](#create-the-working-layout)
- [Run guided setup](#run-guided-setup)
- [Start Rankrat](#start-rankrat)
- [First calls](#first-calls)
- [Next steps](#next-steps)

## Prerequisites

- Docker Engine with `docker run` access and the Compose plugin for HTTP mode;
- a POSIX shell;
- `curl`, `openssl`, and standard core utilities.

The easiest setup path also uses Git and GNU Make. Python, Node, uv, pnpm, and
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
export RANKRAT_DATA_DIR="${RANKRAT_DATA_DIR:-$HOME/.config/rankrat}"
mkdir -p "$RANKRAT_DATA_DIR"/{config,oauth,state} \
  "$RANKRAT_DATA_DIR"/secrets/{google,bing,cloudflare,indexnow,rankrat}
chmod 700 "$RANKRAT_DATA_DIR"/{config,oauth,state,secrets} \
  "$RANKRAT_DATA_DIR"/secrets/*

curl -fsSL https://raw.githubusercontent.com/psyb0t/rankrat/main/config/boundaries.json.example \
  -o "$RANKRAT_DATA_DIR/config/boundaries.json"
curl -fsSL https://raw.githubusercontent.com/psyb0t/rankrat/main/.env.example \
  -o "$RANKRAT_DATA_DIR/.env"
chmod 600 "$RANKRAT_DATA_DIR/config/boundaries.json" "$RANKRAT_DATA_DIR/.env"

install -m 600 /dev/null "$RANKRAT_DATA_DIR/secrets/rankrat/http-bearer-token"
openssl rand -base64 32 | tr -d '\n' \
  > "$RANKRAT_DATA_DIR/secrets/rankrat/http-bearer-token"
```

| Host path | Container path | Access | Purpose |
| --- | --- | --- | --- |
| `$RANKRAT_DATA_DIR/config/` | `/run/config` | Read/write normally; read-only in read-only mode | Account registry and discovered inventory |
| `$RANKRAT_DATA_DIR/secrets/` | `/run/secrets` | Read-only | Provider credentials and HTTP bearer |
| `$RANKRAT_DATA_DIR/oauth/` | `/run/oauth` | Read/write | Google refresh records |
| `$RANKRAT_DATA_DIR/state/` | `/run/state` | Read/write | SQLite monitors, snapshots, issues, events |
| `$RANKRAT_DATA_DIR/.env` | Setup, Compose, and live tests | Read-only | Host profile/UID selection, runtime settings, and opt-in selectors; never credentials |

Mount `config/` as a directory, not the boundary file alone. The image owns its
baked `/run/config`; a file-only bind can make the file unreadable when host and
container user IDs differ. Directory mounting also permits validated discovery
and onboarding to replace the inventory atomically.

## Run guided setup

The checkout path is the supported one-command setup:

```sh
git clone https://github.com/psyb0t/rankrat.git
cd rankrat
make setup
```

The checkout is the data profile for Make targets. Its absolute path can be
reused from every other project:

```sh
export RANKRAT_DATA_DIR="$(pwd)"
```

It creates missing local paths without overwriting, rejects symlinks,
normalizes sensitive permissions, then asks which providers to configure. For
each choice it prints the provider console URL and required account-wide
permissions, accepts the credential through a hidden prompt, and stores it at
the standard path with mode `0600`. Google setup accepts the Desktop OAuth
client JSON, runs one full-scope OAuth flow, and saves the refresh record.

Setup is safe to rerun. A selected provider is added or refreshed in place;
accounts for providers you omit remain unchanged, including discovered
inventory. If the registry already contains multiple accounts for a selected
provider, setup stops before reading a secret so you can identify the intended
account in `config/boundaries.json`.

After credentials are present, setup runs provider readiness, selected deep
live checks, and the production HTTP/MCP image smoke. It does not create site
properties, submit URLs/sitemaps, or send IndexNow notifications.

The standalone wrapper provides the same guided setup plus an explicit Google
OAuth reauthorization command for operators who do not use a checkout:

```sh
export RANKRAT_DATA_DIR=/absolute/path/to/rankrat-profile
rankrat.sh setup
rankrat.sh auth-google --account-id google --print-authorization-url
```

See [Providers and credentials](providers.md) for provider-side steps and
permissions.

## Start Rankrat

```sh
export RANKRAT_DATA_DIR=/absolute/path/to/rankrat-profile
rankrat.sh           # stdio MCP
rankrat.sh http      # attached REST + Streamable HTTP MCP + Lighthouse
rankrat.sh http -d   # detached stack with automatic restarts
```

HTTP treats `RANKRAT_DATA_DIR` as the Compose project directory. If
`docker-compose.yml` is absent there, the wrapper creates the reviewed default
atomically; if a safe regular file already exists, the wrapper preserves and
uses it. The profile root and Compose file must be owned by the current UID and
not group/world writable.
The profile root itself is not mounted into a container—only `config`,
`secrets`, `oauth`, and `state` are.

From a checkout, build both local images and attach to the same deployment with:

```sh
make run-http
```

Direct `docker compose up` remains supported through the committed file. Set
the absolute `RANKRAT_DATA_DIR` and numeric `RANKRAT_UID`/`RANKRAT_GID` values
in `.env` first. The wrapper exports those identity values automatically.

These are writable by default. Set `RANKRAT_READ_ONLY=true` before either
command when the caller must not discover or invoke mutations.

HTTP endpoints:

- `GET http://127.0.0.1:8080/healthz`;
- `GET http://127.0.0.1:8080/ready`;
- MCP at `http://127.0.0.1:8080/mcp`;
- REST under `http://127.0.0.1:8080/v1/`.

When bearer auth is configured, only `/healthz` is public. Send the contents of
`$RANKRAT_DATA_DIR/secrets/rankrat/http-bearer-token` as
`Authorization: Bearer <token>` to
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
