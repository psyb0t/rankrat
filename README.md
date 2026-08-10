# rankrat

<!-- mcp-name: io.github.psyb0t/rankrat -->

[![CI](https://github.com/psyb0t/rankrat/actions/workflows/pipeline.yml/badge.svg?branch=main)](https://github.com/psyb0t/rankrat/actions/workflows/pipeline.yml)
[![coverage](https://raw.githubusercontent.com/psyb0t/rankrat/badges/coverage.svg)](https://github.com/psyb0t/rankrat/actions/workflows/pipeline.yml)
[![version](https://raw.githubusercontent.com/psyb0t/rankrat/badges/version.svg)](https://github.com/psyb0t/rankrat/releases)
[![license](https://raw.githubusercontent.com/psyb0t/rankrat/badges/license.svg)](LICENSE)
[![Docker Pulls](https://img.shields.io/docker/pulls/psyb0t/rankrat?style=flat-square)](https://hub.docker.com/r/psyb0t/rankrat)

Search Console, Bing Webmaster Tools, GA4, PageSpeed, Cloudflare, CrUX, and
backlink providers each have their own view of a site. Rankrat puts them behind
one self-hosted service so an agent can join the evidence and apply explicitly
enabled, bounded remediation.

It is a rat, not a burglar. You provide credentials and an explicit boundary
file. Rankrat fixes credential accounts and explicit resource scope there. A
Google account may deliberately opt into read access for every OAuth-visible
Search Console site and GA4 property; writes remain separately gated. Rankrat
is read-only by default, so write tools do not appear until enabled.

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
- [Development](#development)
- [Project information](#project-information)

## Capabilities

| Area | What Rankrat exposes |
| --- | --- |
| Google | Search Console analytics, inspection and sitemaps; GA4 inventory and reports; bounded property, sitemap, indexing, ownership, and rename writes |
| Bing | Search, crawl, indexing, sitemap, backlink, quota, keyword, opportunity, cannibalization, and bounded submission operations |
| Performance | PageSpeed, Core Web Vitals, CrUX history, Cloudflare analytics, and isolated local Lighthouse audits |
| Site intelligence | Whole-site audits, schema eligibility, internal-link graphs, orphan pages, content opportunities, and cross-provider comparisons |
| Ownership and onboarding | Google/Bing checks, provider-neutral DNS verification through Cloudflare, and bounded GA4/Search Console/Bing onboarding |
| Backlinks | Normalized Bing, Ahrefs, Majestic, Moz, Semrush, and DataForSEO evidence with multi-provider deduplication |
| Monitoring and remediation | Persistent monitors and issue history, sitemap/URL resubmission, IndexNow, exact Cloudflare purges, and finite cache templates |

Runtime discovery is authoritative: read-only deployments omit writes, and
agent onboarding has its own gate. See the [MCP tool catalog](docs/tool-reference.md)
and generated [OpenAPI document](openapi.json).

## Quick start

Docker is the only runtime requirement. Bootstrap uses a POSIX shell, `curl`,
`openssl`, and standard core utilities.

```sh
curl -fsSL https://raw.githubusercontent.com/psyb0t/rankrat/main/rankrat.sh -o rankrat.sh
less rankrat.sh
chmod +x rankrat.sh
sudo mv rankrat.sh /usr/local/bin/rankrat.sh

mkdir -p config oauth state \
  secrets/{google,bing,cloudflare,indexnow,rankrat,ahrefs,majestic,moz,semrush,dataforseo}
chmod 700 config oauth state secrets secrets/*

curl -fsSL https://raw.githubusercontent.com/psyb0t/rankrat/main/config/boundaries.json.example \
  -o config/boundaries.json
curl -fsSL https://raw.githubusercontent.com/psyb0t/rankrat/main/.env.example -o .env
chmod 600 config/boundaries.json .env

install -m 600 /dev/null secrets/rankrat/http-bearer-token
openssl rand -base64 32 | tr -d '\n' > secrets/rankrat/http-bearer-token
```

Remove unused example accounts, add only allowed resources, and put credentials
in their owner-readable files. If Google is configured:

```sh
rankrat.sh auth-google --account-id google --print-authorization-url
rankrat.sh setup
```

`setup` performs read-only live readiness checks; it does not create provider
resources or submit URLs. Exact provider console links and permissions are in
[Providers and credentials](docs/providers.md).

## Run it

```sh
rankrat.sh          # MCP over stdio
rankrat.sh http     # REST + Streamable HTTP MCP on 127.0.0.1:8080
```

For HTTP, MCP is at `http://127.0.0.1:8080/mcp`; REST is under `/v1/`.
Stdio uses no port or bearer. The wrapper, plain `docker run`, Docker Compose,
HTTP authentication, and client configurations are in
[Transports and deployment](docs/transports.md).

Compose runs two
long-lived services plus two one-shot volume initializers; details are in the
deployment guide.

Local browser audits use the separate `psyb0t/rankrat-lighthouse` image over a
Unix socket; it receives no provider credentials. See [Lighthouse](docs/lighthouse.md).

## Safety model

- `RANKRAT_READ_ONLY=true` removes write REST routes and MCP tools.
- `RANKRAT_READ_ONLY=false` adds ordinary boundary-limited writes.
- `RANKRAT_UNBOUNDED=true` temporarily relaxes per-resource allow-lists for a
  trusted bootstrap while keeping credential accounts fixed.
- `RANKRAT_ALLOW_AGENT_ONBOARDING=true` separately exposes the operation that
  creates provider resources and persists their exact boundaries.
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
