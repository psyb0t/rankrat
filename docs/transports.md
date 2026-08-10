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
rankrat.sh http         # REST + Streamable HTTP MCP
rankrat.sh setup        # provider readiness
rankrat.sh auth-google --account-id google --print-authorization-url
rankrat.sh revoke-google --account-id google
rankrat.sh onboard-site --help
rankrat.sh --help
```

The wrapper uses `RANKRAT_IMAGE`, `RANKRAT_BOUNDARIES`, `RANKRAT_SECRETS`,
`RANKRAT_OAUTH`, `RANKRAT_STATE`, `RANKRAT_ENV_FILE`,
`RANKRAT_HTTP_PORT`, and `RANKRAT_OAUTH_CALLBACK_PORT` for non-default host
paths/ports. Runtime policies use `RANKRAT_READ_ONLY`, `RANKRAT_UNBOUNDED`, and
`RANKRAT_ALLOW_AGENT_ONBOARDING`.

## Plain Docker: stdio MCP

```sh
docker run -i --rm --init --read-only \
  --user "$(id -u):$(id -g)" \
  --cap-drop=ALL --security-opt no-new-privileges:true \
  --pids-limit 128 --memory 512m --cpus 1 \
  --tmpfs /tmp:rw,noexec,nosuid,size=32m \
  -e RANKRAT_READ_ONLY=true \
  -e RANKRAT_BOUNDARY_FILE=/run/config/boundaries.json \
  -e RANKRAT_OAUTH_TOKEN_ROOT=/run/oauth \
  -e RANKRAT_STATE_DATABASE=/run/state/rankrat.sqlite3 \
  --mount type=bind,src="$PWD/config",dst=/run/config,readonly \
  --mount type=bind,src="$PWD/secrets",dst=/run/secrets,readonly \
  --mount type=bind,src="$PWD/oauth",dst=/run/oauth \
  --mount type=bind,src="$PWD/state",dst=/run/state \
  psyb0t/rankrat:latest stdio
```

Stdout is exclusively MCP protocol traffic. Write logs to the configured log
file/stderr path; do not wrap the command with anything that prints to stdout.

Mount the configuration directory, not one file. OAuth and state are writable;
provider secrets and normal bounded config are read-only.

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
document reflects startup policy: read-only removes write operations, and the
site-onboarding operation appears only when agent onboarding is enabled.

Health/readiness are GETs, but only `/healthz` bypasses configured bearer auth.
Most provider reads use POST because their typed filters and date ranges are
request bodies. Use the OpenAPI schema rather than guessing JSON fields. Error
responses expose finite categories without raw provider bodies or
credential-bearing upstream URLs.

## Docker Compose

The repository's [`docker-compose.yml.example`](../docker-compose.yml.example)
runs:

- one Rankrat HTTP service;
- one isolated Lighthouse worker;
- one networkless state-volume initializer;
- one networkless Lighthouse-socket-volume initializer.

Copy it before local customization:

```sh
cp docker-compose.yml.example docker-compose.yml
docker compose config --quiet
docker compose up --build
```

Or from a checkout:

```sh
make run-http-lighthouse
```

The example uses local builds, loopback HTTP, read-only roots, dropped
capabilities, no-new-privileges, explicit limits, named state/socket volumes,
and Compose secrets. It intentionally remains bounded with a read-only config
mount. Use the wrapper for a validated writable/unbounded onboarding session.

The two volume initializers are the only root processes. Each is networkless,
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

### Codex

```sh
codex plugin marketplace add psyb0t/agents
codex plugin add rankrat@psyb0t
```

The installed skill invokes as `$rankrat:rankrat`; a checkout containing
`.agents/skills/rankrat` also exposes it as `$rankrat`.

### OpenClaw stdio

```sh
openclaw skills install @psyb0t/rankrat
openclaw plugins install clawhub:@psyb0t/rankrat
```

The static plugin starts the published image directly in read-only stdio mode
and uses:

```text
$HOME/.config/rankrat/config/boundaries.json
$HOME/.config/rankrat/secrets/
$HOME/.config/rankrat/oauth/
$HOME/.config/rankrat/state/
```

Only config is mandatory for credential-free tools. Optional direct-launch
overrides are `RANKRAT_CONFIG_DIR`, `RANKRAT_SECRETS_DIR`,
`RANKRAT_OAUTH_DIR`, `RANKRAT_STATE_DIR`, and `RANKRAT_IMAGE`.

The static plugin does not start Lighthouse and intentionally stays read-only.
Use a shared HTTP deployment for browser audits, automatic scheduling, writes,
or custom runtime policy.

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
