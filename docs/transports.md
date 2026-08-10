# Transports and deployment

Rankrat is one application with three public transports. MCP stdio and MCP
Streamable HTTP expose the same tools under the same startup policy. REST uses
the same services and schemas through OpenAPI-defined routes.

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
| MCP stdio | One agent client spawning its own child | Host process/mount access | No persistent scheduler |
| MCP Streamable HTTP | Multiple clients or a long-lived agent service | HTTP bearer when configured | Yes |
| REST | Scripts, applications, and OpenAPI clients | HTTP bearer when configured | Yes |

The long-lived HTTP process runs the monitor scheduler. Stdio can create, run,
and inspect monitors when writable, but nothing remains alive to claim later
scheduled work after the child exits.

## Wrapper commands

```sh
rankrat.sh              # stdio MCP (default)
rankrat.sh stdio        # explicit stdio
rankrat.sh http         # attached Rankrat + Lighthouse Compose stack
rankrat.sh http -d      # detached restartable HTTP stack
rankrat.sh setup        # guided credentials, Google OAuth, and readiness
rankrat.sh auth-google --account-id google --print-authorization-url
rankrat.sh revoke-google --account-id google
rankrat.sh onboard-site --help
rankrat.sh --help
```

The wrapper uses one persistent host profile:

```sh
export RANKRAT_DATA_DIR=/absolute/path/to/rankrat-profile
rankrat.sh stdio
```

The fixed layout beneath it is `config/boundaries.json`, `secrets/`, `oauth/`,
`state/`, `.env`, and the HTTP deployment's `docker-compose.yml`. With no
override, the wrapper uses `$HOME/.config/rankrat`. `RANKRAT_IMAGE`,
`RANKRAT_LIGHTHOUSE_IMAGE`, `RANKRAT_HTTP_PORT`, and
`RANKRAT_OAUTH_CALLBACK_PORT` select images and published ports;
`RANKRAT_READ_ONLY=true` is the only capability switch. HTTP creates the
reviewed Compose file atomically when it is missing and never overwrites an
existing regular file.

## Plain Docker: stdio MCP

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

Stdout is exclusively MCP protocol traffic. Write logs to the configured log
file/stderr path; do not wrap the command with anything that prints to stdout.

Mount the configuration directory, not one file. OAuth, state, and normal
writable-mode inventory are writable; provider secrets are read-only. For a
read-only deployment, set `RANKRAT_READ_ONLY=true` and add `readonly` to the
config mount.

## Plain Docker: HTTP

Use the stdio command with these changes:

- remove `-i`;
- publish `-p 127.0.0.1:8080:8080`;
- add `-e RANKRAT_HTTP_HOST=0.0.0.0`;
- add `-e RANKRAT_HTTP_BEARER_SECRET_FILE=/run/secrets/rankrat/http-bearer-token`;
- replace the final `stdio` with `http`.

`0.0.0.0` is the bind **inside** the container. The host publish stays on
`127.0.0.1`. If another machine must reach Rankrat, place a TLS-authenticated,
access-controlled proxy or private network in front; do not casually publish
the bearer-protected service to the public internet.

Endpoints:

| Endpoint | Purpose | Bearer configured |
| --- | --- | --- |
| `/healthz` | Process health | Public exception |
| `/ready` | Startup readiness | Required |
| `/mcp` | Streamable HTTP MCP | Required |
| `/v1/...` | JSON API | Required |
| `/openapi.json` and docs UI | Runtime contract/UI when enabled | Required |

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

Do not put the real bearer in a URL, command history, tracked client config, or
log. Prefer client environment expansion or a secret manager.

## REST and OpenAPI

The complete committed contract is [`openapi.json`](../openapi.json). It is
generated from the [base](../src/rankrat/api/openapi.yaml) and
[SEO](../src/rankrat/api/seo-openapi.yaml) YAML sources.

Set `RANKRAT_ENABLE_OPENAPI=true` to serve the runtime contract. The runtime
document reflects startup policy: read-only removes every write operation,
including site onboarding.

Health/readiness are GETs, but only `/healthz` bypasses configured bearer auth.
Most provider reads use POST because their typed filters and date ranges are
request bodies. Use the OpenAPI schema rather than guessing JSON fields. Error
responses expose finite categories without raw provider bodies or
credential-bearing upstream URLs.

## Docker Compose

The repository's runnable [`docker-compose.yml`](../docker-compose.yml), also
embedded in `rankrat.sh` as the default profile deployment, runs:

- one Rankrat HTTP service;
- one isolated Lighthouse worker;
- one networkless Lighthouse-socket-volume initializer.

The normal launcher path needs only the selected profile. Foreground mode stays
attached to logs; detached mode uses `restart: unless-stopped` for both
long-lived services:

```sh
export RANKRAT_DATA_DIR=/absolute/path/to/rankrat-profile
rankrat.sh http
rankrat.sh http -d
```

From a checkout, `make run-http` builds both local images and starts the same
Compose stack in the foreground:

```sh
make run-http
```

To run Compose directly, set `RANKRAT_DATA_DIR`, `RANKRAT_UID`, and
`RANKRAT_GID` in `.env`, then run `docker compose up` or
`docker compose up -d`. The committed deployment uses published image defaults;
the Make target exports locally built tags.

The selected profile is the Compose project directory, not a wholesale bind
mount. Only its fixed `config`, `secrets`, `oauth`, and `state` children enter
containers. A pre-existing profile Compose file is operator-controlled and is
used unchanged. The launcher requires the project directory and Compose file to
be owned by the current UID and not group/world writable, and rejects symlinked
or non-regular Compose paths.

The deployment uses loopback HTTP, read-only roots, dropped
capabilities, no-new-privileges, explicit limits, a named socket volume, and
the same profile bind mounts as `rankrat.sh`. Normal writable mode persists
discovered inventory, OAuth refresh records, and monitor state. Provider
secrets are always read-only. Set `RANKRAT_READ_ONLY=true`; the default Compose
file then mounts config read-only and the application omits every write route
and MCP tool.

The Lighthouse socket initializer is the only root process. It is networkless,
has only `CHOWN`/`FOWNER`, prepares one private volume, and exits.

## Lighthouse deployment

One-container Rankrat remains functional without the browser worker; the five
Lighthouse tools return finite `UNAVAILABLE` responses rather than falling back
to PageSpeed. For the two-image topology and browser threat model, read
[Lighthouse](lighthouse.md).

## Agent integrations

Installing an integration adds instructions or an MCP server definition. It
does not create a boundary, provider credentials, OAuth authorization, or
state paths.

### Claude Code

```sh
claude plugin marketplace add psyb0t/agents
claude plugin install rankrat@psyb0t
```

Register the actual stdio MCP server once at user scope when every project
should use the same Rankrat login:

```sh
claude mcp add --transport stdio --scope user \
  --env RANKRAT_DATA_DIR=/absolute/path/to/rankrat-profile \
  rankrat -- /absolute/path/to/rankrat.sh stdio
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
  rankrat -- /absolute/path/to/rankrat.sh stdio
```

The installed skill invokes as `$rankrat:rankrat`; a checkout containing
`.agents/skills/rankrat` also exposes it as `$rankrat`.

### OpenClaw stdio

```sh
openclaw skills install @psyb0t/rankrat
openclaw plugins install clawhub:@psyb0t/rankrat
```

The static plugin starts the published image directly in writable stdio mode
and uses:

```text
$HOME/.config/rankrat/config/boundaries.json
$HOME/.config/rankrat/secrets/
$HOME/.config/rankrat/oauth/
$HOME/.config/rankrat/state/
```

Set `RANKRAT_DATA_DIR=/absolute/path/to/rankrat-profile` in the plugin
environment to select another shared profile. The launcher requires the four
directories and the boundary file, validates them before Docker, and never
mounts the profile root wholesale. `RANKRAT_IMAGE` selects another image.

The static plugin does not start Lighthouse. Use a shared HTTP deployment for
browser audits, automatic scheduling, multiple clients, or centralized bearer
authentication. Set `RANKRAT_READ_ONLY=true` in a direct launcher environment
when OpenClaw should see reads only.

### OpenClaw Streamable HTTP

```sh
export RANKRAT_AUTH_TOKEN="$(<secrets/rankrat/http-bearer-token)"
openclaw mcp set rankrat '{"url":"http://127.0.0.1:8080/mcp","transport":"streamable-http","headers":{"Authorization":"Bearer ${RANKRAT_AUTH_TOKEN}"}}'
openclaw mcp doctor rankrat --probe
```

The command loads the secret from its owner-readable file instead of placing it
in shell history. Single quotes preserve `${RANKRAT_AUTH_TOKEN}` for OpenClaw
expansion. Remove the override with `openclaw mcp unset rankrat` to return to
plugin stdio.

See the repository [agent setup reference](../.agents/skills/rankrat/references/setup.md)
and [OpenClaw plugin README](../.agents/plugins/rankrat/README.md) for their
distribution-specific details.
