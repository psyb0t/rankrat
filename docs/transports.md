---
title: "Transports and deployment"
description: "Run Rankrat's HTTP server with the wrapper, Compose, or plain Docker, with bearer auth, REST and OpenAPI, and the move off stdio."
nav_order: 5
---

# Transports and deployment

One long-lived HTTP process, two ways in: MCP over Streamable HTTP at `/mcp`
and a FastAPI JSON API under `/v1/`. Both ride the same services, schemas, and
startup policy, so pick by client, not by capability. The stdio MCP transport
is gone as of 0.21.0; `rankrat stdio` and the image's `stdio` command now exit
with directions to the HTTP server.

## Contents

- [Transport choice](#transport-choice)
- [Wrapper commands](#wrapper-commands)
- [Docker Compose](#docker-compose)
- [Plain Docker](#plain-docker)
- [HTTP bearer](#http-bearer)
- [REST and OpenAPI](#rest-and-openapi)
- [Lighthouse deployment](#lighthouse-deployment)
- [Agent integrations](#agent-integrations)
- [Moving off stdio](#moving-off-stdio)

## Transport choice

| Transport | Best for | Authentication |
| --- | --- | --- |
| MCP Streamable HTTP at `/mcp` | Agents and MCP clients, one or many | HTTP bearer when configured |
| REST under `/v1/` | Scripts, apps, and OpenAPI clients | HTTP bearer when configured |

Both run inside the same process, which also runs the monitor scheduler, so
monitors fire on schedule without any client connected.

## Wrapper commands

`rankrat` is a readable host script that drives the published images: HTTP goes
through Compose, the operator commands go through plain `docker run`.

```sh
rankrat http         # attached Rankrat + Lighthouse Compose stack
rankrat http -d      # detached, restartable HTTP stack
rankrat setup        # bootstrap profile, credentials, Google OAuth, readiness
rankrat auth-google --print-authorization-url
rankrat revoke-google
rankrat onboard-site --help
rankrat upgrade      # re-pin to the latest release, pull it, drop the old images
rankrat --help
```

Run without a mode, `rankrat` prints usage and exits with status 2.

Everything hangs off one persistent host profile:

```sh
rankrat --data-dir /absolute/path/to/rankrat-profile http -d
```

The layout under it is fixed: `config/boundaries.json`, `secrets/`, `oauth/`,
`state/`, and the HTTP deployment's `docker-compose.yml`. No `--data-dir` and it
lands in `$HOME/.config/rankrat`. `RANKRAT_IMAGE`, `RANKRAT_LIGHTHOUSE_IMAGE`,
`RANKRAT_HTTP_PORT`, and `RANKRAT_OAUTH_CALLBACK_PORT` pick images and published
ports; `RANKRAT_READ_ONLY=true` is the only capability switch. When the Compose
file is missing, HTTP writes the reviewed default atomically, and it never
overwrites one you already have.

## Docker Compose

The repository's
[`docker-compose.yml`](https://github.com/psyb0t/rankrat/blob/main/docker-compose.yml),
the same file `rankrat` embeds as the default profile deployment, runs three
things:

- one Rankrat HTTP service;
- one isolated Lighthouse worker;
- one networkless, one-shot Lighthouse-socket-volume initializer.

The normal path only needs the selected profile. Foreground stays attached to
logs; detached runs the two long-lived services with `restart: unless-stopped`:

```sh
rankrat --data-dir /absolute/path/to/rankrat-profile http
rankrat --data-dir /absolute/path/to/rankrat-profile http -d
```

From a checkout, `make run-http` (or its alias `make run`) builds both local
images and starts the same stack in the foreground:

```sh
make run-http
```

To drive Compose directly, export `RANKRAT_DATA_DIR`, `RANKRAT_UID`, and
`RANKRAT_GID`, then `docker compose up` (or `up -d`). The committed file defaults
to the published images; the Make target exports the locally built tags.

The profile is the Compose project directory, not a wholesale bind mount of it.
Only its fixed `config`, `secrets`, `oauth`, and `state` children ever reach a
container. A profile that already has a Compose file is operator-controlled and
used unchanged. The launcher demands the project directory and Compose file be
owned by your UID and not group- or world-writable, and rejects a symlinked or
otherwise non-regular Compose path outright.

The deployment is loopback-only HTTP, read-only roots, all capabilities dropped,
no-new-privileges, explicit PID/CPU/memory limits, a named socket volume, and
the same profile mounts as the wrapper. Writable mode persists discovered
inventory, OAuth refresh records, and monitor state; provider secrets stay
read-only regardless. Set `RANKRAT_READ_ONLY=true` and the default Compose file
mounts config read-only while the app drops every write route and MCP tool.

The socket initializer is the only root process in the whole stack. It's
networkless, holds only `CHOWN`/`FOWNER`, preps one private volume, and exits.

## Plain Docker

Don't want the wrapper or Compose? Run the app container yourself. This bare
command has no Lighthouse worker (see [Lighthouse deployment](#lighthouse-deployment)):

```sh
export RANKRAT_DATA_DIR=/absolute/path/to/rankrat-profile
docker run --rm --init --read-only \
  --user "$(id -u):$(id -g)" \
  --cap-drop=ALL --security-opt no-new-privileges:true \
  --pids-limit 128 --memory 512m --cpus 1 \
  --tmpfs /tmp:rw,noexec,nosuid,size=32m \
  -p 127.0.0.1:8080:8080 \
  -e RANKRAT_HTTP_HOST=0.0.0.0 \
  -e RANKRAT_HTTP_BEARER_SECRET_FILE=/run/secrets/rankrat/http-bearer-token \
  -e RANKRAT_READ_ONLY=false \
  -e RANKRAT_BOUNDARY_FILE=/run/config/boundaries.json \
  -e RANKRAT_OAUTH_TOKEN_ROOT=/run/oauth \
  -e RANKRAT_STATE_DATABASE=/run/state/rankrat.sqlite3 \
  --mount type=bind,src="$RANKRAT_DATA_DIR/config",dst=/run/config \
  --mount type=bind,src="$RANKRAT_DATA_DIR/secrets",dst=/run/secrets,readonly \
  --mount type=bind,src="$RANKRAT_DATA_DIR/oauth",dst=/run/oauth \
  --mount type=bind,src="$RANKRAT_DATA_DIR/state",dst=/run/state \
  psyb0t/rankrat:latest http
```

`http` is also the image's default command. `0.0.0.0` binds **inside** the
container; the host publish still pins to `127.0.0.1`. Without
`RANKRAT_HTTP_HOST=0.0.0.0` the server listens on the container's own loopback
and nothing outside can reach it. A non-loopback bind refuses to start without
a bearer secret file.

Mount the config directory, not the single boundary file. OAuth, state, and
writable-mode inventory are read-write; provider secrets are read-only, always.
For a read-only deployment, set `RANKRAT_READ_ONLY=true` and add `readonly` to
the config mount.

If another machine has to reach Rankrat, put a TLS-authenticated,
access-controlled proxy or a private network in front of it. Do not fling the
bearer-protected service at the public internet and call it a day.

| Endpoint | Purpose | Bearer configured |
| --- | --- | --- |
| `/healthz` | Process health | Public exception |
| `/ready` | Startup readiness | Required |
| `/mcp` | Streamable HTTP MCP | Required |
| `/v1/...` | JSON API | Required |
| `/openapi.json` and docs UI | Runtime contract/UI when enabled | Required |

`/healthz` is the one route that skips the bearer. Everything else, `/ready`
included, gets rejected without a valid token.

## HTTP bearer

`rankrat setup` creates the secret for you. To make one by hand:

```sh
install -m 600 /dev/null secrets/rankrat/http-bearer-token
openssl rand -base64 32 | tr -d '\n' > secrets/rankrat/http-bearer-token
```

Clients send:

```http
Authorization: Bearer REPLACE_ME
```

Never put the real bearer in a URL, shell history, tracked client config, or a
log line. Expand it from the client environment or a secret manager instead.

## REST and OpenAPI

The committed contract is
[`openapi.json`](https://github.com/psyb0t/rankrat/blob/main/openapi.json),
generated from three YAML sources:
[base](https://github.com/psyb0t/rankrat/blob/main/src/rankrat/api/openapi.yaml),
[SEO](https://github.com/psyb0t/rankrat/blob/main/src/rankrat/api/seo-openapi.yaml), and
[free SEO](https://github.com/psyb0t/rankrat/blob/main/src/rankrat/api/free-seo-openapi.yaml).

Set `RANKRAT_ENABLE_OPENAPI=true` to serve the contract at runtime. It mirrors
startup policy: read-only strips every write operation, site onboarding
included, so the doc never advertises a route the runtime won't honor.

Health and readiness are GETs, but only `/healthz` bypasses the bearer. Most
provider reads are POST because their typed filters and date ranges live in the
request body; read the schema instead of guessing field names. Errors come back
as finite categories, never raw provider bodies or credential-bearing upstream
URLs.

## Lighthouse deployment

One-container Rankrat runs fine without the browser worker: the five Lighthouse
tools just return a finite `UNAVAILABLE` instead of silently degrading to
PageSpeed. The `rankrat http` Compose stack wires the worker in; the bare
`docker run` above has no worker unless you add one. For the two-image topology
and the browser threat model, read [Lighthouse](lighthouse.md).

## Agent integrations

The Rankrat skill and plugins for Claude Code, Codex, and OpenClaw install from
the `psyb0t/agents` marketplace and ClawHub. Commands and direct MCP
registration for each client are on [Agent integrations](integrations.md).

## Moving off stdio

Clients registered with `rankrat stdio` (or the image's `stdio` command) stop
working in 0.21.0. To move over:

1. Start the server once: `rankrat http -d`. It restarts with Docker.
2. Remove the old registration, for example `claude mcp remove rankrat` or
   `codex mcp remove rankrat`.
3. Register `http://127.0.0.1:8080/mcp` with the bearer as shown in
   [Agent integrations](integrations.md).
4. For OpenClaw, update the plugin and set `RANKRAT_URL` and `RANKRAT_TOKEN`.

Lighthouse sidecars named `rankrat-lighthouse-stdio-*` left behind by earlier
stdio sessions are safe to remove with `docker rm -f`.
