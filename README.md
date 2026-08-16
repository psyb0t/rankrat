# rankrat

<!-- mcp-name: io.github.psyb0t/rankrat -->

[![CI](https://github.com/psyb0t/rankrat/actions/workflows/pipeline.yml/badge.svg?branch=main)](https://github.com/psyb0t/rankrat/actions/workflows/pipeline.yml)
[![coverage](https://raw.githubusercontent.com/psyb0t/rankrat/badges/coverage.svg)](https://github.com/psyb0t/rankrat/actions/workflows/pipeline.yml)
[![version](https://raw.githubusercontent.com/psyb0t/rankrat/badges/version.svg)](https://github.com/psyb0t/rankrat/releases)
[![license](https://raw.githubusercontent.com/psyb0t/rankrat/badges/license.svg)](LICENSE)
[![Docker Pulls](https://img.shields.io/docker/pulls/psyb0t/rankrat?style=flat-square)](https://hub.docker.com/r/psyb0t/rankrat)

Every SEO signal lives in its own walled garden with its own dashboard, its own
API, and its own bullshit auth dance: Search Console over here, GA4 over there,
Bing Webmaster somewhere else, plus Cloudflare, Clarity, PageSpeed, CrUX, GTM,
and Bing's backlink data. Point an agent at your rankings and it drowns juggling
eight consoles. Rankrat drags all of them behind one self-hosted service, so you
tell an agent the outcome you want and it inspects, creates, updates, or rips
out provider resources through a single surface — REST and MCP, no dashboards.

It's a rat, not a burglar. You hand it the provider accounts; those credentials
are the only authority it has. The resource lists in `boundaries.json` are
inventory and URL-containment data — not a second permission system pretending
to keep you safe. Rankrat writes by default; set `RANKRAT_READ_ONLY=true` and
every mutating route and tool disappears from discovery. That's the one switch.

It speaks MCP over stdio, MCP over Streamable HTTP at `/mcp`, and a FastAPI JSON
API under `/v1/`. Wrapper-managed HTTP gets a bearer; a hand-rolled loopback-only
launch can drop it if you know what you're doing.

**Status:** alpha. The API and tool surface can still move before 1.0 — minor
releases may break things on purpose (documented), so pin an exact release if
you need it to hold still.

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
| Google | Search Console analytics, inspection and sitemaps; GA4 inventory, historical and realtime reports, ecommerce, funnels, and audiences; Google Tag Manager containers, workspaces, tags, triggers, variables, versions, and publication; property, sitemap, indexing, ownership, onboarding, and rename writes |
| Bing | Search, crawl, indexing, sitemap, backlink, quota, keyword, opportunity, cannibalization, site/submission, and safe content-submission operations |
| Performance | PageSpeed, Core Web Vitals, CrUX history, Microsoft Clarity insights, Cloudflare analytics, and isolated local Lighthouse audits |
| Site intelligence | Whole-site audits, schema eligibility, internal-link graphs, orphan pages, content opportunities, and cross-provider comparisons |
| Ownership and onboarding | Google/Bing checks, provider-neutral DNS verification through Cloudflare, and idempotent GA4/Search Console/Bing onboarding |
| Backlinks | Bing Webmaster backlink intelligence for configured sites |
| Monitoring and remediation | Persistent monitors and issue history, sitemap/URL resubmission, IndexNow, exact Cloudflare purges, finite cache templates, and managed edge redirects |

What the runtime advertises is what it does — no hidden endpoints. A read-only
deployment drops every write from discovery; a writable one exposes onboarding
alongside the rest. The whole list is the [MCP tool catalog](docs/tool-reference.md)
and the generated [OpenAPI document](openapi.json).

## Quick start

Install the `rankrat` command, create the credentials for the providers you
want, then run it. Docker is the only runtime requirement.

### Install

Download the installer, read it, then run it — per-user (no root) or
system-wide:

```sh
curl -fsSL https://raw.githubusercontent.com/psyb0t/rankrat/main/install.sh -o rankrat-install.sh
less rankrat-install.sh
bash rankrat-install.sh                # per-user   -> ~/.local/bin/rankrat
sudo bash rankrat-install.sh --system  # system-wide -> /usr/local/bin/rankrat
```

The mode auto-detects from who runs it; `--user` / `--system` force it and
`--uninstall` removes the command. This puts the `rankrat` wrapper — a readable
script that drives the published Docker images — on your PATH. Prefer to work
from a source checkout? Clone the repo and use `./rankrat` or the `make` targets
instead; see [Getting started](docs/getting-started.md).

### Set up

Run setup. It lists every provider, you pick the ones you actually use, and it
walks you through creating each credential — the exact console clicks for Google
OAuth, the Bing Webmaster key, the Cloudflare token, the Clarity token — then
hides every value you paste. No copying token permissions out of a README:

```sh
rankrat setup
```

Configuring Google? Paste the one-line Desktop OAuth JSON when it asks, or hand
it the downloaded file up front so you don't have to:

```sh
rankrat setup --google-oauth-client-file "/absolute/path/to/client_secret_...json"
```

Setup validates account access — it does not submit URLs or create properties.
Your profile lives in `~/.config/rankrat`; override it per launch with
`rankrat --data-dir /absolute/path` or `RANKRAT_DATA_DIR` for a separate profile
per account or workspace. Want to read the credential steps ahead of time, or
what each provider actually gives you? See
[Providers and credentials](docs/providers.md). From a source checkout the setup
step is `make setup`.

## Run it

```sh
rankrat            # MCP over stdio (default)
rankrat http -d    # REST + Streamable-HTTP MCP + Lighthouse, detached with restarts
```

From a source checkout: `make run` (stdio) and `make run-http` (HTTP over
Compose, attached).

Over HTTP, MCP lives at `http://127.0.0.1:8080/mcp` and REST under `/v1/`; stdio
needs no port and no bearer. HTTP treats your data directory as its Compose
project — it drops a `docker-compose.yml` in there if one's missing and never
touches yours if it isn't. Under the hood that's two long-lived services plus a
one-shot volume init. The wrapper, plain `docker run`, raw Compose, HTTP auth,
and client wiring all live in [Transports and deployment](docs/transports.md).

Browser audits run in a separate `psyb0t/rankrat-lighthouse` image over a Unix
socket, and it never sees a single provider credential. See [Lighthouse](docs/lighthouse.md).

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

- [Getting started](docs/getting-started.md) — install, file locations, verifying setup
- [Configuration](docs/configuration.md) — every boundary field and runtime switch
- [Providers and credentials](docs/providers.md) — obtaining each credential and its permissions
- [Transports and deployment](docs/transports.md) — stdio MCP, Streamable HTTP MCP, REST, Compose, agent integrations
- [Feature workflows](docs/features.md) — operations for common SEO, analytics, backlink, and indexing questions
- [Lighthouse](docs/lighthouse.md) — the browser worker and its security limits
- [Ownership and onboarding](docs/ownership-and-onboarding.md) — Google/Bing property creation and DNS verification
- [Monitoring and remediation](docs/monitoring-and-remediation.md) — persistent monitors and provider-write behavior
- [Security](docs/security.md) — trust boundaries and production rules
- [MCP tool reference](docs/tool-reference.md) — every discoverable MCP tool
- [Troubleshooting](docs/troubleshooting.md) — startup, OAuth, provider, sitemap, and browser-audit failures
- [Development](docs/development.md) — build, test, generate contracts, audit dependencies, contribute

The REST source is YAML-first: [`openapi.yaml`](src/rankrat/api/openapi.yaml),
[`seo-openapi.yaml`](src/rankrat/api/seo-openapi.yaml), and
[`free-seo-openapi.yaml`](src/rankrat/api/free-seo-openapi.yaml) generate
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

Everything runs in containers — no "works on my machine" roulette:

```sh
make help
make lint
make test
```

Mocked tests need zero credentials. Live tests are opt-in and pull their one
account plus a safe target straight from your profile, so they can't wander off
and touch something they shouldn't. Full contributor guide in
[Development](docs/development.md).

## Project information

[WTFPL license](LICENSE) · [Release history](CHANGELOG.md) · [Dependency
attribution](THIRD_PARTY_LICENSES.md) · [Issues](https://github.com/psyb0t/rankrat/issues)
