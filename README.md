# rankrat

<!-- mcp-name: io.github.psyb0t/rankrat -->

[![CI](https://github.com/psyb0t/rankrat/actions/workflows/pipeline.yml/badge.svg?branch=main)](https://github.com/psyb0t/rankrat/actions/workflows/pipeline.yml)
[![coverage](https://raw.githubusercontent.com/psyb0t/rankrat/badges/coverage.svg)](https://github.com/psyb0t/rankrat/actions/workflows/pipeline.yml)
[![version](https://raw.githubusercontent.com/psyb0t/rankrat/badges/version.svg)](https://github.com/psyb0t/rankrat/releases)
[![license](https://raw.githubusercontent.com/psyb0t/rankrat/badges/license.svg)](LICENSE)
[![Docker Pulls](https://img.shields.io/docker/pulls/psyb0t/rankrat?style=flat-square)](https://hub.docker.com/r/psyb0t/rankrat)

Search Console, Bing Webmaster Tools, GA4, PageSpeed, Cloudflare, CrUX, and
backlink providers each have their own view of a site. Rankrat puts them behind
one self-hosted service so a human can tell an agent what outcome they want and
let the agent inspect, create, update, or remove supported provider resources.

It is a rat, not a burglar. You provide the provider accounts; those credentials
are Rankrat's authority. Resource lists in `boundaries.json` are discovered
inventory and URL-containment data, not a second permission system. Rankrat is
writable by default. Set `RANKRAT_READ_ONLY=true` when a deployment must omit
every mutating REST route and MCP tool.

Rankrat speaks MCP over stdio, MCP over Streamable HTTP at `/mcp`, and a
FastAPI JSON API under `/v1/`. Wrapper-managed HTTP uses a bearer; a custom
loopback-only launch may explicitly omit it.

**Status:** alpha. The API and tool surface may change before 1.0.

## Contents

- [Capabilities](#capabilities)
- [Quick start](#quick-start)
- [Run it](#run-it)
- [Safety model](#safety-model)
- [Documentation](#documentation)
- [Agent integrations](#agent-integrations)
- [Development](#development)
- [Project information](#project-information)

## Capabilities

| Area | What Rankrat exposes |
| --- | --- |
| Google | Search Console analytics, inspection and sitemaps; GA4 inventory and reports; property, sitemap, indexing, ownership, onboarding, and rename writes |
| Bing | Search, crawl, indexing, sitemap, backlink, quota, keyword, opportunity, cannibalization, and site/submission operations |
| Performance | PageSpeed, Core Web Vitals, CrUX history, Cloudflare analytics, and isolated local Lighthouse audits |
| Site intelligence | Whole-site audits, schema eligibility, internal-link graphs, orphan pages, content opportunities, and cross-provider comparisons |
| Ownership and onboarding | Google/Bing checks, provider-neutral DNS verification through Cloudflare, and idempotent GA4/Search Console/Bing onboarding |
| Backlinks | Normalized Bing, Ahrefs, Majestic, Moz, Semrush, and DataForSEO evidence with multi-provider deduplication |
| Monitoring and remediation | Persistent monitors and issue history, sitemap/URL resubmission, IndexNow, exact Cloudflare purges, and finite cache templates |

Runtime discovery is authoritative: read-only deployments omit every write;
writable deployments include onboarding with the other mutations. See the
[MCP tool catalog](docs/tool-reference.md) and generated
[OpenAPI document](openapi.json).

## Quick start

Docker and GNU Make are the only checkout setup requirements. The guided setup
prints the provider console URL and account-wide permissions for each selected
provider, accepts credentials through hidden terminal prompts, stores them in
standard owner-only paths, completes Google OAuth, and runs live capability
checks before declaring the installation ready.

Rerunning setup is additive: selected providers are added or refreshed, while
unselected accounts and their discovered inventory stay unchanged. If a
provider already has multiple account entries, choose the intended entry in
`config/boundaries.json` before refreshing that provider.

```sh
git clone https://github.com/psyb0t/rankrat.git
cd rankrat
make setup
```

Setup does not submit URLs or create site properties. It validates account
access so a later agent session can do those jobs through the normal API/MCP
tools. Exact provider details and the standalone-wrapper path are in
[Getting started](docs/getting-started.md) and
[Providers and credentials](docs/providers.md).

## Run it

```sh
make run             # MCP over stdio
make run-http        # Rankrat + Lighthouse over HTTP, attached to Compose
rankrat.sh http -d   # same HTTP stack detached with automatic restarts
```

For HTTP, MCP is at `http://127.0.0.1:8080/mcp`; REST is under `/v1/`.
Stdio uses no port or bearer. HTTP uses the selected data directory as its
Compose project, creates `docker-compose.yml` there when missing, and preserves
an existing operator file. The wrapper, plain `docker run`, Docker Compose,
HTTP authentication, and client configurations are in
[Transports and deployment](docs/transports.md).

Compose runs two
long-lived services plus one one-shot volume initializer; details are in the
deployment guide.

Local browser audits use the separate `psyb0t/rankrat-lighthouse` image over a
Unix socket; it receives no provider credentials. See [Lighthouse](docs/lighthouse.md).

## Safety model

- Rankrat is writable by default. Configured account credentials authorize all
  supported provider operations and all resources those accounts can reach.
- `RANKRAT_READ_ONLY=true` removes write REST routes and MCP tools from runtime
  discovery. It is the only capability switch.
- The operator decides whether the caller is a careful human-directed agent or
  a fully autonomous one. Remote HTTP still uses the configured bearer.
- Resource arrays are cached inventory and containment data. Onboarding and
  discovery update them so retries reuse existing resources.
- Secrets are read-only mounts; OAuth records and monitor state have separate
  writable mounts.

See [Configuration](docs/configuration.md) and [Security](docs/security.md)
before enabling writes or exposing HTTP beyond loopback.

## Documentation

The [documentation index](docs/README.md) links the complete operator and
contributor manual: setup, configuration, providers, transports, workflows,
security, tools, troubleshooting, and development.

The REST source is YAML-first: [`openapi.yaml`](src/rankrat/api/openapi.yaml)
and [`seo-openapi.yaml`](src/rankrat/api/seo-openapi.yaml) generate
[`openapi.json`](openapi.json). Agent clients can use the repository's skill,
Claude Code and Codex manifests, or OpenClaw integration under [`.agents`](.agents/).

## Agent integrations

The [Rankrat skill](.agents/skills/rankrat) works in agents that read
`.agents/skills/`. The integrations below cover both MCP stdio and a shared
Streamable HTTP server.

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

Installed through the catalog, the skill invokes as `$rankrat:rankrat`. Codex
also discovers it as `$rankrat` directly from a Rankrat checkout.

### OpenClaw

```sh
openclaw skills install @psyb0t/rankrat
openclaw plugins install clawhub:@psyb0t/rankrat
```

The plugin launches the published image over MCP stdio using the standard
`$HOME/.config/rankrat/` layout. Set one absolute `RANKRAT_DATA_DIR` in every
client to reuse the same provider accounts, OAuth authorization, inventory,
and monitor state from any site repository. To use an already-running shared server,
configure OpenClaw for its authenticated `http://127.0.0.1:8080/mcp`
Streamable HTTP endpoint. See [Transports](docs/transports.md#agent-integrations).

## Development

All project tooling runs in containers:

```sh
make help
make lint
make test
```

Mocked tests need no provider credentials. Live tests are explicit and
selector-driven. See [Development](docs/development.md).

## Project information

[WTFPL license](LICENSE) · [Release history](CHANGELOG.md) · [Dependency
attribution](THIRD_PARTY_LICENSES.md) · [Issues](https://github.com/psyb0t/rankrat/issues)
