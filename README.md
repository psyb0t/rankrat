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
out provider resources through a single surface: REST and MCP, no dashboards.

It's a rat, not a burglar. You hand it the provider accounts; those credentials
are the only authority it has. The resource lists in `boundaries.json` are
inventory and URL-containment data, not a second permission system pretending
to keep you safe. Rankrat writes by default; set `RANKRAT_READ_ONLY=true` and
every mutating route and tool disappears from discovery. That's the one switch.

It speaks MCP over Streamable HTTP at `/mcp` and a FastAPI JSON API under `/v1/`,
both from one long-lived process. Wrapper-managed HTTP gets a bearer; a
hand-rolled loopback-only launch can drop it if you know what you're doing. The
stdio transport is gone as of 0.21.0; see
[moving off stdio](https://psyb0t.github.io/rankrat/transports/#moving-off-stdio).

**Status:** alpha. The API and tool surface can still move before 1.0. Minor
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
- [Sponsor](#sponsor)
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

What the runtime advertises is what it does. No hidden endpoints. A read-only
deployment drops every write from discovery; a writable one exposes onboarding
alongside the rest. The whole list is the [MCP tool catalog](https://psyb0t.github.io/rankrat/tool-reference/)
and the generated [OpenAPI document](openapi.json).

## Quick start

Install the `rankrat` command, create the credentials for the providers you
want, then run it. Docker is the only runtime requirement.

### Install

Download the installer, read it, then run it, per-user (no root) or
system-wide:

```sh
curl -fsSL https://raw.githubusercontent.com/psyb0t/rankrat/main/install.sh \
  -o rankrat-install.sh
less rankrat-install.sh
bash rankrat-install.sh                # per-user   -> ~/.local/bin/rankrat
sudo bash rankrat-install.sh --system  # system-wide -> /usr/local/bin/rankrat
```

The mode auto-detects from who runs it; `--user` / `--system` force it and
`--uninstall` removes the command. This puts the `rankrat` wrapper (a readable
script that drives the published Docker images) on your PATH. Prefer to work
from a source checkout? Clone the repo and use `./rankrat` or the `make` targets
instead; see [Getting started](https://psyb0t.github.io/rankrat/getting-started/).

### Set up

Run setup. It lists every provider, you pick the ones you actually use, and it
walks you through creating each credential (the exact console clicks for Google
OAuth, the Bing Webmaster key, the Cloudflare token, the Clarity token), then
hides every value you paste. No copying token permissions out of a README:

```sh
rankrat setup
```

Configuring Google? Paste the one-line Desktop OAuth client JSON at the hidden
prompt when setup asks, same as every other credential.

Setup validates account access. It does not submit URLs or create properties.
Your profile lives in `~/.config/rankrat`; override it per launch with
`rankrat --data-dir /absolute/path` or `RANKRAT_DATA_DIR` for a separate profile
per account or workspace. Want to read the credential steps ahead of time, or
what each provider actually gives you? See
[Providers and credentials](https://psyb0t.github.io/rankrat/providers/). From a source checkout the setup
step is `make setup`.

## Run it

```sh
rankrat http -d    # REST + Streamable HTTP MCP + Lighthouse, detached with restarts
rankrat http       # same stack, attached to the logs
rankrat upgrade    # re-pin to the latest release, pull it, drop the previous image
```

From a source checkout: `make run-http` (HTTP over Compose, attached).

`rankrat setup` pins both `psyb0t/rankrat` and `psyb0t/rankrat-lighthouse` to the
latest release tag (recorded, along with the HTTP port and read-only flag, in a
`.env` at your profile root) rather than tracking the moving `:latest`. `rankrat
upgrade` re-pins the images to the newest release, pulls both, restarts a running
HTTP stack (reusing the recorded port and read-only flag), and removes the
superseded images; it leaves the port and read-only lines untouched. Pass
`--rolling` (or set `RANKRAT_ROLLING=1`) to use the moving `:latest` images for a
single run without touching the recorded pin. `RANKRAT_IMAGE`,
`RANKRAT_LIGHTHOUSE_IMAGE`, `RANKRAT_HTTP_PORT`, and `RANKRAT_READ_ONLY` still
override the recorded values per run.

To set the host settings once instead of per run, put them in a permanent host
env file at `~/.config/rankrat/.env` (override the path with `RANKRAT_ENV_FILE`).
The wrapper reads it before selecting a profile, so it can set `RANKRAT_DATA_DIR`
(which profile to use) along with `RANKRAT_READ_ONLY`, `RANKRAT_IMAGE`,
`RANKRAT_LIGHTHOUSE_IMAGE`, `RANKRAT_HTTP_PORT`, `RANKRAT_OAUTH_CALLBACK_PORT`,
and `RANKRAT_ROLLING`. It only fills a variable that is unset or empty, so a
`--data-dir` flag or a real env var still overrides it. This is especially handy
for MCP launchers that run `rankrat` with a minimal environment and never see
your shell exports. It is separate from the per-profile `.env`: the host file
selects the profile and the host defaults, while a profile's `.env` pins that
profile's images, port, and read-only flag.

MCP lives at `http://127.0.0.1:8080/mcp` and REST under `/v1/`, both behind the
bearer in your profile's `secrets/rankrat/http-bearer-token`. HTTP treats your data directory as its Compose
project: it drops a `docker-compose.yml` in there if one's missing and never
touches yours if it isn't. Under the hood that's two
long-lived services plus one one-shot volume initializer. The wrapper, plain
`docker run`, raw Compose, HTTP auth, and client wiring all live in
[Transports and deployment](https://psyb0t.github.io/rankrat/transports/).

Browser audits run in a separate `psyb0t/rankrat-lighthouse` image over a Unix
socket, and it never sees a single provider credential. The HTTP Compose stack
starts it next to Rankrat. See [Lighthouse](https://psyb0t.github.io/rankrat/lighthouse/).

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

See [Configuration](https://psyb0t.github.io/rankrat/configuration/) and [Security](https://psyb0t.github.io/rankrat/security/)
before enabling writes or exposing HTTP beyond loopback.

## Documentation

The full manual lives at **[psyb0t.github.io/rankrat](https://psyb0t.github.io/rankrat/)**.

| Page | What's in it |
| --- | --- |
| [Getting started](https://psyb0t.github.io/rankrat/getting-started/) | Install, file locations, verifying setup |
| [Configuration](https://psyb0t.github.io/rankrat/configuration/) | Every boundary field and runtime switch |
| [Providers and credentials](https://psyb0t.github.io/rankrat/providers/) | Getting each credential and its permissions |
| [Transports and deployment](https://psyb0t.github.io/rankrat/transports/) | Streamable HTTP MCP, REST, Compose, moving off stdio |
| [Agent integrations](https://psyb0t.github.io/rankrat/integrations/) | Claude Code, Codex, and OpenClaw installs and MCP registration |
| [Feature workflows](https://psyb0t.github.io/rankrat/features/) | Operations for common SEO, analytics, backlink, and indexing questions |
| [Lighthouse](https://psyb0t.github.io/rankrat/lighthouse/) | The browser worker and its security limits |
| [Ownership and onboarding](https://psyb0t.github.io/rankrat/ownership-and-onboarding/) | Google/Bing property creation and DNS verification |
| [Monitoring and remediation](https://psyb0t.github.io/rankrat/monitoring-and-remediation/) | Persistent monitors and provider-write behavior |
| [Security](https://psyb0t.github.io/rankrat/security/) | Trust boundaries and production rules |
| [MCP tool reference](https://psyb0t.github.io/rankrat/tool-reference/) | Every discoverable MCP tool |
| [Troubleshooting](https://psyb0t.github.io/rankrat/troubleshooting/) | Startup, OAuth, provider, sitemap, and browser-audit failures |
| [Development](https://psyb0t.github.io/rankrat/development/) | Build, test, generate contracts, audit dependencies, contribute |

The REST source is YAML-first: [`openapi.yaml`](src/rankrat/api/openapi.yaml),
[`seo-openapi.yaml`](src/rankrat/api/seo-openapi.yaml), and
[`free-seo-openapi.yaml`](src/rankrat/api/free-seo-openapi.yaml) generate
[`openapi.json`](openapi.json). Agent clients can use the repository's skill,
Claude Code and Codex manifests, or OpenClaw integration under [`.agents`](.agents/).

## Agent integrations

The [Rankrat skill](.agents/skills/rankrat) works in agents that read
`.agents/skills/` (such as [peen](https://github.com/psyb0t/peen)). Every
integration below talks to a running `rankrat http` server at
`http://127.0.0.1:8080/mcp`.

### Claude Code

```sh
claude plugin marketplace add psyb0t/agents
claude plugin install rankrat@psyb0t
```

The plugin asks for the server URL and the bearer.

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

The plugin is a stdio-to-HTTP bridge built on `mcp-remote`. Set `RANKRAT_URL`
(for example `http://127.0.0.1:8080`) and `RANKRAT_TOKEN` (the profile's bearer)
in its environment. Registering the server URL directly in Claude Code, Codex,
or OpenClaw is covered in
[Agent integrations](https://psyb0t.github.io/rankrat/integrations/).

## Development

Everything runs in containers. No "works on my machine" roulette:

```sh
make help
make lint
make test
```

Mocked tests need zero credentials. Live tests are opt-in and pull their one
account plus a safe target straight from your profile, so they can't wander off
and touch something they shouldn't. Full contributor guide in
[Development](https://psyb0t.github.io/rankrat/development/).

## Sponsor

<a href="https://www.buymeacoffee.com/psyb0t"><img src="https://cdn.buymeacoffee.com/buttons/v2/default-blue.png" alt="Buy Me a Coffee" height="60" width="217"></a>

## Project information

[WTFPL license](LICENSE) · [Release history](CHANGELOG.md) · [Dependency
attribution](THIRD_PARTY_LICENSES.md) · [Issues](https://github.com/psyb0t/rankrat/issues)
