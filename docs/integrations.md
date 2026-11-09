---
title: "Agent integrations"
description: "Install the Rankrat skill and plugins in Claude Code, Codex, and OpenClaw from the psyb0t/agents marketplace, and register the MCP server."
nav_order: 6
---

# Agent integrations

The [Rankrat skill](https://github.com/psyb0t/rankrat/tree/main/.agents/skills/rankrat)
teaches an agent which tools to reach for and how to stay inside the boundary.
It ships through the [`psyb0t/agents`](https://github.com/psyb0t/agents)
marketplace for Claude Code and Codex, and through ClawHub for OpenClaw. Agents
that read `.agents/skills/` from a checkout, such as
[peen](https://github.com/psyb0t/peen), pick it up without installing anything.

## Contents

- [Before you install](#before-you-install)
- [Claude Code](#claude-code)
- [Codex](#codex)
- [OpenClaw bridge plugin](#openclaw-bridge-plugin)
- [OpenClaw native Streamable HTTP](#openclaw-native-streamable-http)

## Before you install

Installing an integration adds instructions or an MCP client definition. It
does not create a boundary, provider credentials, OAuth authorization, or state
paths; those are still yours to set up. Every client below talks to a running
`rankrat http` server.

Load the bearer once per shell from its owner-readable file, so it never hits
shell history:

```sh
export RANKRAT_TOKEN="$(<"$HOME/.config/rankrat/secrets/rankrat/http-bearer-token")"
```

## Claude Code

```sh
claude plugin marketplace add psyb0t/agents
claude plugin install rankrat@psyb0t
```

The plugin asks for the server URL and the bearer, stored as a sensitive value.
Register the MCP server itself once at user scope so every project shares one
Rankrat:

```sh
claude mcp add --transport http --scope user rankrat \
  http://127.0.0.1:8080/mcp \
  --header "Authorization: Bearer $RANKRAT_TOKEN"
```

## Codex

```sh
codex plugin marketplace add psyb0t/agents
codex plugin add rankrat@psyb0t
```

Register the same server in Codex; it reads the bearer from the environment
variable you name:

```sh
codex mcp add rankrat \
  --url http://127.0.0.1:8080/mcp \
  --bearer-token-env-var RANKRAT_TOKEN
```

The installed skill invokes as `$rankrat:rankrat`; a checkout containing
`.agents/skills/rankrat` also exposes it as `$rankrat`.

## OpenClaw bridge plugin

```sh
openclaw skills install @psyb0t/rankrat
openclaw plugins install clawhub:@psyb0t/rankrat
```

The plugin is a stdio-to-HTTP bridge built on `mcp-remote`. Set `RANKRAT_URL`
(for example `http://127.0.0.1:8080`; the bridge appends `/mcp`) and
`RANKRAT_TOKEN` in the plugin environment. The bridge passes the header as the
literal `${RANKRAT_TOKEN}` placeholder, which `mcp-remote` fills from its own
environment, so the token never lands in a process argument list.

## OpenClaw native Streamable HTTP

```sh
export RANKRAT_AUTH_TOKEN="$RANKRAT_TOKEN"
openclaw mcp set rankrat '{
  "url": "http://127.0.0.1:8080/mcp",
  "transport": "streamable-http",
  "headers": {
    "Authorization": "Bearer ${RANKRAT_AUTH_TOKEN}"
  }
}'
openclaw mcp doctor rankrat --probe
```

Single quotes keep `${RANKRAT_AUTH_TOKEN}` intact for OpenClaw to expand.
`openclaw mcp unset rankrat` drops the override and returns to the bridge
plugin.

See the repository
[agent setup reference](https://github.com/psyb0t/rankrat/blob/main/.agents/skills/rankrat/references/setup.md)
and
[OpenClaw plugin README](https://github.com/psyb0t/rankrat/blob/main/.agents/plugins/rankrat/README.md)
for the distribution-specific details.
