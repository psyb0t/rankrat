# Rankrat documentation

The root [README](../README.md) is the product overview and shortest working
path. These guides carry the operational and contributor detail.

## Choose a guide

| Guide | Questions it answers |
| --- | --- |
| [Getting started](getting-started.md) | What do I install, where do files go, and how do I verify setup? |
| [Configuration](configuration.md) | What does every boundary field and runtime switch mean? |
| [Providers and credentials](providers.md) | Where do I obtain each credential and which permissions does it need? |
| [Transports and deployment](transports.md) | How do I run stdio MCP, Streamable HTTP MCP, REST, Compose, or an agent integration? |
| [Feature workflows](features.md) | Which operations answer common SEO, analytics, backlink, and indexing questions? |
| [Lighthouse](lighthouse.md) | How does the browser worker run and what are its security limits? |
| [Ownership and onboarding](ownership-and-onboarding.md) | How are Google/Bing properties created and verified through DNS? |
| [Monitoring and remediation](monitoring-and-remediation.md) | How do persistent monitors and provider writes behave? |
| [Security](security.md) | What are the trust boundaries and production rules? |
| [MCP tool reference](tool-reference.md) | What does every discoverable MCP tool do? |
| [Troubleshooting](troubleshooting.md) | Why did startup, OAuth, a provider call, sitemap, or browser audit fail? |
| [Development](development.md) | How do I build, test, generate contracts, audit dependencies, and contribute? |

## Contract sources

- MCP clients should use `tools/list` from the running process.
  `RANKRAT_READ_ONLY=true` removes every write tool, including onboarding.
- REST clients should use runtime `/openapi.json` when
  `RANKRAT_ENABLE_OPENAPI=true` or the committed merged
  [`openapi.json`](../openapi.json).
- The YAML sources are [`openapi.yaml`](../src/rankrat/api/openapi.yaml) and
  [`seo-openapi.yaml`](../src/rankrat/api/seo-openapi.yaml).
- Runtime examples are [`.env.example`](../.env.example),
  [`boundaries.json.example`](../config/boundaries.json.example), and
  the runnable [`docker-compose.yml`](../docker-compose.yml).

## Suggested reading order

New deployment: Getting started → Providers → Configuration → Transports →
Security. Agent/API client: Transports → Feature workflows → Tool reference or
OpenAPI. Contributor: Development → OpenAPI sources → focused feature guide.
