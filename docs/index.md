---
title: "Home"
description: "Rankrat puts Search Console, Bing Webmaster, GA4, Tag Manager, Clarity, Cloudflare, PageSpeed and CrUX behind one self-hosted MCP and REST server."
nav_order: 1
permalink: /
seo:
  type: WebSite
---

# rankrat

Every SEO signal lives in its own walled garden with its own dashboard, its own
API, and its own auth dance: Search Console over here, GA4 over there, Bing
Webmaster somewhere else, plus Cloudflare, Clarity, PageSpeed, CrUX, GTM, and
Bing's backlink data. Rankrat drags all of them behind one self-hosted service,
so you tell an agent the outcome you want and it inspects, creates, updates, or
rips out provider resources through a single surface: MCP over Streamable HTTP
at `/mcp` and a JSON API under `/v1/`.

You hand it the provider accounts; those credentials are the only authority it
has. The resource lists in `boundaries.json` are inventory and URL-containment
data, not a second permission system. Rankrat writes by default; set
`RANKRAT_READ_ONLY=true` and every mutating route and tool disappears from
discovery. That's the one switch.

**Status:** alpha. Minor releases before 1.0 may break things on purpose, and
the [changelog](https://github.com/psyb0t/rankrat/blob/main/CHANGELOG.md) says
how. Pin an exact release if you need it to hold still.

## What it covers

| Area | What Rankrat exposes |
| --- | --- |
| Google | Search Console analytics, inspection and sitemaps; GA4 inventory, historical and realtime reports, ecommerce, funnels, and audiences; Google Tag Manager containers, workspaces, tags, triggers, variables, versions, and publication; property, sitemap, indexing, ownership, onboarding, and rename writes |
| Bing | Search, crawl, indexing, sitemap, backlink, quota, keyword, opportunity, cannibalization, site/submission, and safe content-submission operations |
| Performance | PageSpeed, Core Web Vitals, CrUX history, Microsoft Clarity insights, Cloudflare analytics, and isolated local Lighthouse audits |
| Site intelligence | Whole-site audits, schema eligibility, internal-link graphs, orphan pages, content opportunities, and cross-provider comparisons |
| Ownership and onboarding | Google/Bing checks, provider-neutral DNS verification through Cloudflare, and idempotent GA4/Search Console/Bing onboarding |
| Backlinks | Bing Webmaster backlink intelligence for configured sites |
| Monitoring and remediation | Persistent monitors and issue history, sitemap/URL resubmission, IndexNow, exact Cloudflare purges, finite cache templates, and managed edge redirects |

What the runtime advertises is what it does. The full list is the
[MCP tool reference](tool-reference.md) and the generated
[OpenAPI document](https://github.com/psyb0t/rankrat/blob/main/openapi.json).

## Quick start

Docker is the only runtime requirement. Download the installer, read it, run it:

```sh
curl -fsSL https://raw.githubusercontent.com/psyb0t/rankrat/main/install.sh \
  -o rankrat-install.sh
less rankrat-install.sh
bash rankrat-install.sh                # per-user   -> ~/.local/bin/rankrat
sudo bash rankrat-install.sh --system  # system-wide -> /usr/local/bin/rankrat
```

Create the profile and credentials. Setup lists every provider, walks you
through each credential, and hides every value you paste:

```sh
rankrat setup
```

Start the server, with the Lighthouse worker, detached and restarting:

```sh
rankrat http -d
```

Point an MCP client at `http://127.0.0.1:8080/mcp` with the bearer from
`~/.config/rankrat/secrets/rankrat/http-bearer-token`. For Claude Code:

```sh
export RANKRAT_TOKEN="$(<"$HOME/.config/rankrat/secrets/rankrat/http-bearer-token")"
claude mcp add --transport http --scope user rankrat \
  http://127.0.0.1:8080/mcp \
  --header "Authorization: Bearer $RANKRAT_TOKEN"
```

Other clients, plain Docker and Compose are in
[Transports and deployment](transports.md). The full walkthrough with checks
is [Getting started](getting-started.md).

## Where to go next

| Page | What's in it |
| --- | --- |
| [Getting started](getting-started.md) | Install, file locations, verifying setup |
| [Configuration](configuration.md) | Every boundary field and runtime switch |
| [Providers and credentials](providers.md) | Getting each credential and its permissions |
| [Transports and deployment](transports.md) | Streamable HTTP MCP, REST, Compose, agent integrations, moving off stdio |
| [Feature workflows](features.md) | Which tools answer common SEO, analytics, backlink, and indexing questions |
| [MCP tool reference](tool-reference.md) | Every discoverable MCP tool |
| [Lighthouse](lighthouse.md) | The browser worker and its security limits |
| [Ownership and onboarding](ownership-and-onboarding.md) | Google/Bing property creation and DNS verification |
| [Monitoring and remediation](monitoring-and-remediation.md) | Persistent monitors and provider-write behavior |
| [Security](security.md) | Trust boundaries and production rules |
| [Troubleshooting](troubleshooting.md) | Startup, OAuth, provider, sitemap, and browser-audit failures |
| [Development](development.md) | Build, test, generate contracts, audit dependencies, contribute |
