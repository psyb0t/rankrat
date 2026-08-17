# Transports and deployment

One application, three ways in. MCP stdio and MCP Streamable HTTP expose the
exact same tools under the exact same startup policy — the wire format is the
only difference. REST rides the same services and schemas through
OpenAPI-defined routes. Pick a transport for how you run it, not for what it can
do.

## Contents

- [Transport choice](#transport-choice)
- [Wrapper commands](#wrapper-commands)
- [Plain Docker: stdio MCP](#plain-docker-stdio-mcp)
- [Plain Docker: HTTP](#plain-docker-http)
- [HTTP bearer](#http-bearer)
- [REST and OpenAPI](#rest-and-openapi)
- [Docker Compose](#docker-compose)
- [Lighthouse deployment](#lighthouse-deployment)
- [Agent integrations](#agent-integrations)

## Transport choice

| Transport | Best for | Authentication | Scheduler |
| --- | --- | --- | --- |
| MCP stdio | One agent client spawning its own child | Host process/mount access | None |
| MCP Streamable HTTP | Multiple clients or a long-lived agent service | HTTP bearer when configured | Yes |
| REST | Scripts, apps, and OpenAPI clients | HTTP bearer when configured | Yes |

Only the long-lived HTTP process runs the monitor scheduler. Stdio can create,
run, and inspect monitors when writable — but the child exits and nothing stays
alive to pick up scheduled work later. Want monitors that actually fire? Run
HTTP.

## Wrapper commands

`rankrat` is a readable host script that drives the published images: HTTP goes
through Compose, stdio and the operator commands go through plain `docker run`.

```sh
rankrat              # stdio MCP (default)
rankrat stdio        # explicit stdio
rankrat http         # attached Rankrat + Lighthouse Compose stack
rankrat http -d      # detached, restartable HTTP stack
rankrat setup        # bootstrap profile, credentials, Google OAuth, readiness
rankrat auth-google --print-authorization-url
rankrat revoke-google
rankrat onboard-site --help
rankrat --help
```

Everything hangs off one persistent host profile:

```sh
rankrat --data-dir /absolute/path/to/rankrat-profile stdio
```

The layout under it is fixed: `config/boundaries.json`, `secrets/`, `oauth/`,
`state/`, and the HTTP deployment's `docker-compose.yml`. No `--data-dir` and it
lands in `$HOME/.config/rankrat`. `RANKRAT_IMAGE`, `RANKRAT_LIGHTHOUSE_IMAGE`,
`RANKRAT_HTTP_PORT`, and `RANKRAT_OAUTH_CALLBACK_PORT` pick images and published
ports; `RANKRAT_READ_ONLY=true` is the only capability switch. When the Compose
file is missing, HTTP writes the reviewed default atomically — and never
overwrites one you already have.

## Plain Docker: stdio MCP

Don't want the wrapper? Run the image yourself. This is the app container
`rankrat stdio` runs — but the wrapper also starts an ephemeral Lighthouse
sidecar for the session (see [Lighthouse deployment](#lighthouse-deployment)) and
mounts its socket read-only, which this bare command omits:

```sh
export RANKRAT_DATA_DIR=/absolute/path/to/rankrat-profile
docker run -i --rm --init --read-only \
  --user "$(id -u):$(id -g)" \
  --cap-drop=ALL --security-opt no-new-privileges:true \
  --pids-limit 128 --memory 512m --cpus 1 \
  --tmpfs /tmp:rw,noexec,nosuid,size=32m \
  -e RANKRAT_READ_ONLY=false \
  -e RANKRAT_BOUNDARY_FILE=/run/config/boundaries.json \
  -e RANKRAT_OAUTH_TOKEN_ROOT=/run/oauth \
  -e RANKRAT_STATE_DATABASE=/run/state/rankrat.sqlite3 \
  --mount type=bind,src="$RANKRAT_DATA_DIR/config",dst=/run/config \
  --mount type=bind,src="$RANKRAT_DATA_DIR/secrets",dst=/run/secrets,readonly \
  --mount type=bind,src="$RANKRAT_DATA_DIR/oauth",dst=/run/oauth \
  --mount type=bind,src="$RANKRAT_DATA_DIR/state",dst=/run/state \
  psyb0t/rankrat:latest stdio
```

Stdout is MCP protocol traffic and nothing else. Logs go to the configured log
file or stderr — do not wrap this command in anything that prints to stdout, or
you corrupt the stream.

Mount the config directory, not the single boundary file. OAuth, state, and
writable-mode inventory are read-write; provider secrets are read-only, always.
For a read-only deployment, set `RANKRAT_READ_ONLY=true` and add `readonly` to
the config mount.

## Plain Docker: HTTP

Same command, five edits:

- drop `-i`;
- publish `-p 127.0.0.1:8080:8080`;
- add `-e RANKRAT_HTTP_HOST=0.0.0.0`;
- add `-e RANKRAT_HTTP_BEARER_SECRET_FILE=/run/secrets/rankrat/http-bearer-token`;
- swap the trailing `stdio` for `http`.

`0.0.0.0` binds **inside** the container — the host publish still pins to
`127.0.0.1`. If another machine has to reach Rankrat, put a TLS-authenticated,
access-controlled proxy or a private network in front of it. Do not fling the
bearer-protected service at the public internet and call it a day.

| Endpoint | Purpose | Bearer configured |
| --- | --- | --- |
| `/healthz` | Process health | Public exception |
| `/ready` | Startup readiness | Required |
| `/mcp` | Streamable HTTP MCP | Required |
| `/v1/...` | JSON API | Required |
| `/openapi.json` and docs UI | Runtime contract/UI when enabled | Required |

`/healthz` is the one route that skips the bearer. Everything else — `/ready`
included — gets rejected without a valid token.

## HTTP bearer

Generate a dedicated random secret:

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

The committed contract is [`openapi.json`](../openapi.json), generated from three
YAML sources: [base](../src/rankrat/api/openapi.yaml),
[SEO](../src/rankrat/api/seo-openapi.yaml), and
[free SEO](../src/rankrat/api/free-seo-openapi.yaml).

Set `RANKRAT_ENABLE_OPENAPI=true` to serve the contract at runtime. It mirrors
startup policy: read-only strips every write operation, site onboarding
included — the doc never advertises a route the runtime won't honor.

Health and readiness are GETs, but only `/healthz` bypasses the bearer. Most
provider reads are POST because their typed filters and date ranges live in the
request body — read the schema instead of guessing field names. Errors come back
as finite categories, never raw provider bodies or credential-bearing upstream
URLs.

## Docker Compose

The repository's [`docker-compose.yml`](../docker-compose.yml) — the same file
`rankrat` embeds as the default profile deployment — runs three things:

- one Rankrat HTTP service;
- one isolated Lighthouse worker;
- one networkless, one-shot Lighthouse-socket-volume initializer.

The normal path only needs the selected profile. Foreground stays attached to
logs; detached runs the two long-lived services with `restart: unless-stopped`:

```sh
rankrat --data-dir /absolute/path/to/rankrat-profile http
rankrat --data-dir /absolute/path/to/rankrat-profile http -d
```

From a checkout, `make run-http` builds both local images and starts the same
stack in the foreground:

```sh
make run-http
```

To drive Compose directly, export `RANKRAT_DATA_DIR`, `RANKRAT_UID`, and
`RANKRAT_GID`, then `docker compose up` (or `up -d`). The committed file defaults
to the published images; the Make target exports the locally built tags.

The profile is the Compose project directory — not a wholesale bind mount of it.
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

## Lighthouse deployment

One-container Rankrat runs fine without the browser worker — the five Lighthouse
tools just return a finite `UNAVAILABLE` instead of silently degrading to
PageSpeed. The `rankrat` wrapper wires the worker in for both transports: HTTP
through Compose, and stdio through a per-session ephemeral sidecar the wrapper
starts host-side and tears down on exit. The bare `docker run` above has no
worker unless you add one. For the two-image topology and the browser threat
model, read [Lighthouse](lighthouse.md).

## Agent integrations

Installing an integration adds instructions or an MCP server definition. It does
not create a boundary, provider credentials, OAuth authorization, or state paths
— those are still yours to set up.

### Claude Code

```sh
claude plugin marketplace add psyb0t/agents
claude plugin install rankrat@psyb0t
```

Register the actual stdio MCP server once at user scope when every project should
share one Rankrat login:

```sh
claude mcp add --transport stdio --scope user \
  --env RANKRAT_DATA_DIR=/absolute/path/to/rankrat-profile \
  rankrat -- /absolute/path/to/rankrat stdio
```

### Codex

```sh
codex plugin marketplace add psyb0t/agents
codex plugin add rankrat@psyb0t
```

Register the same shared profile in Codex:

```sh
codex mcp add \
  --env RANKRAT_DATA_DIR=/absolute/path/to/rankrat-profile \
  rankrat -- /absolute/path/to/rankrat stdio
```

The installed skill invokes as `$rankrat:rankrat`; a checkout containing
`.agents/skills/rankrat` also exposes it as `$rankrat`.

### OpenClaw stdio

```sh
openclaw skills install @psyb0t/rankrat
openclaw plugins install clawhub:@psyb0t/rankrat
```

The static plugin starts the published image directly in writable stdio mode and
uses:

```text
$HOME/.config/rankrat/config/boundaries.json
$HOME/.config/rankrat/secrets/
$HOME/.config/rankrat/oauth/
$HOME/.config/rankrat/state/
```

Point it at another shared profile with
`RANKRAT_DATA_DIR=/absolute/path/to/rankrat-profile` in the plugin environment.
The launcher requires the four directories and the boundary file, checks them
before touching Docker, and never mounts the profile root wholesale.
`RANKRAT_IMAGE` selects another image.

The static plugin does not start Lighthouse. Use a shared HTTP deployment when
you want browser audits, automatic scheduling, multiple clients, or one central
bearer. Set `RANKRAT_READ_ONLY=true` in a direct launcher environment when
OpenClaw should see reads only.

### OpenClaw Streamable HTTP

```sh
export RANKRAT_AUTH_TOKEN="$(<secrets/rankrat/http-bearer-token)"
openclaw mcp set rankrat '{"url":"http://127.0.0.1:8080/mcp","transport":"streamable-http","headers":{"Authorization":"Bearer ${RANKRAT_AUTH_TOKEN}"}}'
openclaw mcp doctor rankrat --probe
```

The secret loads from its owner-readable file, so it never hits shell history.
Single quotes keep `${RANKRAT_AUTH_TOKEN}` intact for OpenClaw to expand.
`openclaw mcp unset rankrat` drops the override and returns to plugin stdio.

See the repository [agent setup reference](../.agents/skills/rankrat/references/setup.md)
and [OpenClaw plugin README](../.agents/plugins/rankrat/README.md) for the
distribution-specific details.
