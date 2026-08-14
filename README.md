# rankrat

<!-- mcp-name: io.github.psyb0t/rankrat -->

[![CI](https://github.com/psyb0t/rankrat/actions/workflows/pipeline.yml/badge.svg?branch=main)](https://github.com/psyb0t/rankrat/actions/workflows/pipeline.yml)
[![coverage](https://raw.githubusercontent.com/psyb0t/rankrat/badges/coverage.svg)](https://github.com/psyb0t/rankrat/actions/workflows/pipeline.yml)
[![version](https://raw.githubusercontent.com/psyb0t/rankrat/badges/version.svg)](https://github.com/psyb0t/rankrat/releases)
[![license](https://raw.githubusercontent.com/psyb0t/rankrat/badges/license.svg)](LICENSE)
[![Docker Pulls](https://img.shields.io/docker/pulls/psyb0t/rankrat?style=flat-square)](https://hub.docker.com/r/psyb0t/rankrat)

Search Console, Google Tag Manager, Bing Webmaster Tools, GA4, Microsoft
Clarity, PageSpeed, Cloudflare, CrUX, and Bing's backlink data each have their
own view of a site. Rankrat puts them behind one self-hosted service so a human
can tell an agent what outcome they want and let the agent inspect, create,
update, or remove supported provider resources.

It is a rat, not a burglar. You provide the provider accounts; those credentials
are Rankrat's authority. Resource lists in `boundaries.json` are discovered
inventory and URL-containment data, not a second permission system. Rankrat is
writable by default. Set `RANKRAT_READ_ONLY=true` when a deployment must omit
every mutating REST route and MCP tool.

Rankrat speaks MCP over stdio, MCP over Streamable HTTP at `/mcp`, and a
FastAPI JSON API under `/v1/`. Wrapper-managed HTTP uses a bearer; a custom
loopback-only launch may explicitly omit it.

**Status:** alpha. The API and tool surface may change before 1.0; minor
releases can include documented incompatible changes, so pin an exact release
if your integration requires stability.

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
| Google | Search Console analytics, inspection and sitemaps; GA4 inventory and reports; Google Tag Manager containers, workspaces, tags, triggers, variables, versions, and publication; property, sitemap, indexing, ownership, onboarding, and rename writes |
| Bing | Search, crawl, indexing, sitemap, backlink, quota, keyword, opportunity, cannibalization, site/submission, and safe content-submission operations |
| Performance | PageSpeed, Core Web Vitals, CrUX history, Microsoft Clarity insights, Cloudflare analytics, provider-neutral managed edge redirects, and isolated local Lighthouse audits |
| Site intelligence | Whole-site audits, schema eligibility, internal-link graphs, orphan pages, content opportunities, and cross-provider comparisons |
| Ownership and onboarding | Google/Bing checks, provider-neutral DNS verification through Cloudflare, and idempotent GA4/Search Console/Bing onboarding |
| Backlinks | Bing Webmaster backlink intelligence for configured sites |
| Monitoring and remediation | Persistent monitors and issue history, sitemap/URL resubmission, IndexNow, exact Cloudflare purges, finite cache templates, and managed edge redirects |

Runtime discovery is authoritative: read-only deployments omit every write;
writable deployments include onboarding with the other mutations. See the
[MCP tool catalog](docs/tool-reference.md) and generated
[OpenAPI document](openapi.json).

## Quick start

Docker and GNU Make are the only checkout setup requirements. You do not need
a database or local configuration before cloning. Before setup, create the
credential only for each provider you actually want to use; setup asks which
ones to configure and hides every value you paste.

```sh
git clone https://github.com/psyb0t/rankrat.git
cd rankrat
```

### Create provider credentials once

| Provider | Exact first link | Create exactly this | Full click-by-click guide |
| --- | --- | --- | --- |
| Google | <https://console.cloud.google.com/projectcreate> | A project, a Desktop OAuth client JSON, and an optional PageSpeed/CrUX API key | [Google OAuth](docs/providers.md#google-oauth) |
| Bing | <https://www.bing.com/webmasters/home> | One account-wide Webmaster API key | [Bing Webmaster Tools](docs/providers.md#bing-webmaster-tools) |
| Cloudflare | <https://dash.cloudflare.com/profile/api-tokens> | One account-wide User API Token | Steps below |
| Microsoft Clarity | <https://clarity.microsoft.com/> | One Data Export token per Clarity project | [Microsoft Clarity](docs/providers.md#microsoft-clarity) |

The linked provider guides say precisely which buttons to click, which APIs or
permissions to add, and what Rankrat asks you to paste. Do not create a Google
service account, a Cloudflare Account API Token, or a Cloudflare Global API
Key: those are the wrong credential types for Rankrat.

### Create the Cloudflare token

When you want Rankrat to manage Cloudflare-backed sites, create one dedicated
token exactly like this:

1. Open <https://dash.cloudflare.com/profile/api-tokens>.
2. Click **Create Token → Create Custom Token** and name it `rankrat`.
3. Add these permissions:
   - **Zone → Zone → Read**
   - **Zone → DNS → Edit**
   - **Zone → Analytics → Read**
   - **Zone → Cache Purge → Purge**
   - **Zone → Cache Rules → Edit**
   - **Zone → Single Redirect → Edit**
   - **Account → Account Rulesets → Edit**
   - **Account → Account Filter Lists → Edit**
4. Set **Zone Resources → Include → All zones** and **Account Resources →
   Include → All accounts**.
5. Click **Continue to summary → Create Token**, copy the value shown once,
   and keep it ready to paste at Rankrat's hidden prompt.

Use a **User API Token**, never the Account API Token screen or Global API Key.
This one token covers every Cloudflare feature Rankrat currently ships:
ownership DNS, analytics, exact purges, cache templates, and managed redirects.

Now run setup and select only the providers you want to configure. If you are
configuring Google, give the wrapper the downloaded Desktop OAuth JSON's host
path. For Bing, Cloudflare, and Clarity, setup asks you to paste the newly
created token/key:

```sh
RANKRAT_GOOGLE_OAUTH_CLIENT_FILE="$HOME/Downloads/client_secret_...json" make setup
```

If you are not configuring Google, omit that environment variable and run
`make setup`. Installed users can use the identical direct command:

```sh
rankrat setup --google-oauth-client-file "/absolute/path/to/client_secret_...json"
```

`make setup` uses `$HOME/.config/rankrat`. Set
`RANKRAT_PROFILE=/absolute/path/to/rankrat-profile` only when this checkout
must use a different existing profile; installed users use the clearer
`rankrat --data-dir ...` form instead.

Setup does not submit URLs or create site properties. It validates account
access so a later agent session can do those jobs through the normal API/MCP
tools. Exact provider details and the standalone-wrapper path are in
[Getting started](docs/getting-started.md) and
[Providers and credentials](docs/providers.md).

## Run it

```sh
make run             # MCP over stdio
make run-http        # Rankrat + Lighthouse over HTTP, attached to Compose
rankrat http -d      # same HTTP stack detached with automatic restarts
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

All project tooling runs in containers:

```sh
make help
make lint
make test
```

Mocked tests need no provider credentials. Live tests are explicit and derive
their sole account plus a safe target from the selected profile. See
[Development](docs/development.md).

## Project information

[WTFPL license](LICENSE) · [Release history](CHANGELOG.md) · [Dependency
attribution](THIRD_PARTY_LICENSES.md) · [Issues](https://github.com/psyb0t/rankrat/issues)
