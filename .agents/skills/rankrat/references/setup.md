# rankrat — setup reference

Everything the [skill](../SKILL.md) needs but does not need loaded up front:
configuration, credentials, and how to run it.

## Configuration

All settings are read from the environment with the `RANKRAT_` prefix, so a
field named `http_port` is set by `RANKRAT_HTTP_PORT`. The defaults below are
the ones in the settings model, not example values.

| Variable | Default | Purpose |
|---|---|---|
| `RANKRAT_HTTP_HOST` | `127.0.0.1` | Listen address in `http` mode. Loopback by default — bind wider only deliberately. |
| `RANKRAT_HTTP_PORT` | `8080` | Listen port in `http` mode. |
| `RANKRAT_BOUNDARY_FILE` | `/run/config/boundaries.json` | The accounts and sites this server is allowed to touch. |
| `RANKRAT_SECRET_ROOT` | `/run/secrets` | Directory holding provider credentials. |
| `RANKRAT_OAUTH_TOKEN_ROOT` | `/run/oauth` | Directory holding stored Google OAuth tokens. |
| `RANKRAT_LOG_FILE` | `/tmp/rankrat/rankrat.log` | Log destination. |
| `RANKRAT_LOG_LEVEL` | `INFO` | Standard Python log levels. |
| `RANKRAT_LIGHTHOUSE_WORKER_SOCKET` | `/run/lighthouse/lighthouse.sock` | Optional Unix socket for the isolated local Lighthouse worker. Empty disables it. |
| `RANKRAT_ENABLE_OPENAPI` | `false` | Serve the OpenAPI document. |
| `RANKRAT_READ_ONLY` | `true` | See "Write access" below. |
| `RANKRAT_UNBOUNDED` | `false` | Reusable trusted-onboarding mode; see "Unbounded mode". Requires `RANKRAT_READ_ONLY=false`. |
| `RANKRAT_ALLOW_AGENT_ONBOARDING` | `false` | Expose agent-reachable onboarding when writes are enabled; see "Onboarding" below. |
| `RANKRAT_HTTP_BEARER_SECRET_FILE` | unset | File holding the bearer token required on HTTP requests. Unset means no auth, so only do that on loopback. |

The supported names and safe defaults are in `.env.example`. Invalid values for
supported settings fail startup instead of being silently accepted.
`make run-http` always supplies a bearer-secret file, including for loopback
use; a custom loopback launch may deliberately omit it.

The `RANKRAT_LIVE_*` variables select the deeper provider-specific live suites
that `make setup` runs after the image's setup check. They are blank in
`.env.example`: set them only for providers you configured and leave all
unused-provider selectors blank so those extra live suites skip. The image's
`setup` command itself checks every account represented in the boundary file.

## The boundary file

`boundaries.json` is what fixes the scope. It lists the accounts and the sites
or properties within them that this server may read. Ordinary bounded tools
cannot add to it, and nothing in the normal tool surface enumerates properties
outside it — a site that is not listed is not reachable, whatever the underlying
account can see. The sole exception is separately gated agent onboarding, which
can persist only the exact resources it creates when
`RANKRAT_ALLOW_AGENT_ONBOARDING=true` and the config mount passes its ownership
and mode checks.

Keep it to the properties you actually want an agent reading.

## Write access

`RANKRAT_READ_ONLY` defaults to `true`, and the effect is stronger than a
refusal at call time: the tool catalog is built from that setting, so the write
tools are absent from `tools/list` and the REST write routes are not mounted. An
agent cannot discover them, let alone call them.

Set it to `false` and they appear. There is no approval ID, admin API, or second
bearer token — the trusted caller gets direct access, with writes still confined
to the configured boundaries and to what the provider account itself permits.
Writes cover IndexNow submission, Bing URL/sitemap/property changes, Google
Indexing notifications, Search Console site/sitemap changes, DNS-provider-backed
ownership verification, discovery remediation, and new-site onboarding, and
are marked as writes in MCP.

## Unbounded mode

`RANKRAT_UNBOUNDED=true` is a bootstrap escape hatch for onboarding a resource
that is not in the boundary file yet. It requires `RANKRAT_READ_ONLY=false`;
setting it alone is a startup error.

What it changes: authorization still resolves the credential **account** from
the boundary file, so accounts stay fixed, but resource allow-list checks are
skipped — including Google resource/account discovery and the GA4
  parent-account pin and DNS zone allow-list.

What it does *not* change is worth knowing, because it is narrower than "the
boundary is off":

- **URL containment still applies.** A candidate page URL must still normalize
  as public HTTPS and sit beneath the property or site it was requested under,
  so naming an unlisted property does not let a caller reach a URL outside that
  property.
- **IndexNow targets stay resolved from the boundary file**, so no new key
  target appears.
- **The OAuth credential path stays resolved from the boundary file**, so no new
  credential becomes reachable.
- Non-loopback HTTP still requires the bearer secret.

Use it for a trusted discovery/onboarding session: start unbounded, discover
and onboard, let onboarding write the discovered IDs back into the boundary
file, then restart without it so the now-expanded allow-list is enforced again.
It is reusable: enable it again later when a trusted agent needs to expand the
boundary. A server left running unbounded is a trusted-caller deployment; treat
it that way.

## Provider credentials

Each provider is optional. Read tools stay discoverable regardless of local
credential state and return a finite unavailable/configuration error when their
provider cannot run. Ask `provider_readiness` which providers are live rather
than inferring it from discovery or an empty result. Write tools are the
exception: they are absent unless writable mode enables them.

- **Google Search Console / Google Analytics 4 / Google Indexing** — OAuth. The
  CLI runs one authorization flow and stores the resulting token under
  `RANKRAT_OAUTH_TOKEN_ROOT`. It requests Search Console management, Google
  Indexing, and GA4 read/edit scopes; provider-side ownership still controls
  what the account can do.
- **Bing Webmaster Tools** — an API key from the Bing Webmaster dashboard,
  placed under `RANKRAT_SECRET_ROOT`.
- **Cloudflare** — a scoped API token with Zone Read and DNS Edit only for the
  selected zones, stored at the credential path in the Cloudflare boundary
  account. Put each zone in the provider-neutral `dns_zones` array with its
  Cloudflare Zone ID in `provider_zone_id`. Ownership calls accept
  `dns_account_id`; they do not expose a Cloudflare-specific request field.
  Rankrat exposes only Google TXT and Bing CNAME verification records.
- **PageSpeed Insights** — an API key, same location, and the one Google surface
  that does not use OAuth: the key goes on the query string, so the Google
  consent flow grants it nothing. It is optional — with no key configured the
  call still goes out, unauthenticated, under a much tighter quota.
- **Local Lighthouse** — no credential. The optional companion image receives
  only a shared Unix socket and outbound browser network access. Rankrat accepts
  only requested URLs beneath the account's `pagespeed_sites` and rejects a
  report whose final URL escapes that boundary. A public cross-origin redirect
  can be fetched before this post-navigation check, while private and special
  destinations are blocked by the worker's enforced proxy.

Credentials stay on the host running rankrat. They are used to call the provider
APIs over HTTPS and are not sent anywhere else.

## Running it

An agent runs the published image directly. The boundary file, the credentials
and the Google authorization are created by a human beforehand. This skill
includes [`rankrat.sh`](rankrat.sh), a byte-identical copy of the repository
wrapper around these same invocations. Run it from its installed skill path with
`bash references/rankrat.sh` when the wrapper is more convenient than the plain
Docker commands below; no system-wide installation is required.

Both transports take the same three mounts. Container-side paths are the
server's defaults, so only the host side changes:

| Host | Container | Access | Holds |
|---|---|---|---|
| `./config` | `/run/config` | read-only normally; validated writable mount for unbounded mode or agent onboarding | `boundaries.json` |
| `./secrets` | `/run/secrets` | read-only | provider credentials, HTTP bearer secret |
| `./oauth` | `/run/oauth` | writable | stored Google OAuth token; refresh may rotate it |

**stdio** — the default mode, for a client that owns the process:

```bash
docker run -i --rm --init --read-only \
  --user "$(id -u):$(id -g)" \
  --cap-drop=ALL --security-opt no-new-privileges:true \
  --pids-limit 128 --memory 512m --cpus 1 \
  --tmpfs /tmp:rw,noexec,nosuid,size=32m \
  --mount type=bind,src="$PWD/config",dst=/run/config,readonly \
  --mount type=bind,src="$PWD/secrets",dst=/run/secrets,readonly \
  --mount type=bind,src="$PWD/oauth",dst=/run/oauth \
  psyb0t/rankrat stdio
```

**Streamable HTTP** — for a shared server. MCP lands at `/mcp` and the REST API
shares the port:

```bash
docker run --rm --init --read-only \
  --user "$(id -u):$(id -g)" \
  --cap-drop=ALL --security-opt no-new-privileges:true \
  --pids-limit 128 --memory 512m --cpus 1 \
  --tmpfs /tmp:rw,noexec,nosuid,size=32m \
  -p 127.0.0.1:8080:8080 \
  -e RANKRAT_HTTP_HOST=0.0.0.0 \
  -e RANKRAT_HTTP_BEARER_SECRET_FILE=/run/secrets/rankrat/http-bearer-token \
  --mount type=bind,src="$PWD/config",dst=/run/config,readonly \
  --mount type=bind,src="$PWD/secrets",dst=/run/secrets,readonly \
  --mount type=bind,src="$PWD/oauth",dst=/run/oauth \
  psyb0t/rankrat http
```

`RANKRAT_HTTP_HOST=0.0.0.0` binds inside the container while `-p` keeps it on
loopback. MCP is then at `http://127.0.0.1:8080/mcp`; send
`Authorization: Bearer <token>` whenever a bearer secret is configured.

The commands above are bounded and read-only. In unbounded mode, set
`RANKRAT_READ_ONLY=false` and `RANKRAT_UNBOUNDED=true`; for agent onboarding,
set `RANKRAT_READ_ONLY=false` and `RANKRAT_ALLOW_AGENT_ONBOARDING=true`. Either
case needs `readonly` removed only from `/run/config`, after verifying that the
resolved config directory is owner-only, that `boundaries.json` itself is not a
symlink, that both are owned by the current UID, and that the file is not group-
or world-writable. The bundled `rankrat.sh` resolves the directory path, checks
that resulting target, and applies the mount change automatically. The OpenClaw
launcher is stricter and rejects any symlinked path component. Do not make the
secret mount writable.

Local Lighthouse audits require the separate published browser image. Start it
once against a private named volume:

```bash
docker volume create rankrat-lighthouse-runtime
docker run --rm --network none --user 0:0 --read-only \
  --cap-drop=ALL --cap-add=CHOWN --cap-add=FOWNER \
  --security-opt no-new-privileges:true \
  --pids-limit 16 --memory 64m --cpus 0.25 \
  --mount type=volume,src=rankrat-lighthouse-runtime,dst=/run/lighthouse \
  --entrypoint /bin/sh psyb0t/rankrat-lighthouse \
  -c 'chmod 1777 /run/lighthouse && touch /run/lighthouse/.initialized && chown -R 10001:10001 /run/lighthouse && chmod 0750 /run/lighthouse'
docker run --rm -d --name rankrat-lighthouse-worker --init --read-only \
  --user 10001:10001 --cap-drop=ALL --security-opt no-new-privileges:true \
  --pids-limit 256 --memory 2g --cpus 2 --shm-size 1g \
  --tmpfs /tmp:rw,noexec,nosuid,size=1g,mode=1777 \
  --mount type=volume,src=rankrat-lighthouse-runtime,dst=/run/lighthouse \
  psyb0t/rankrat-lighthouse
```

The self-removing initializer assigns the private volume root to the non-root
UID shared by Rankrat and the worker. When using a different UID/GID, change the
initializer's `chown` pair and the worker's `--user` pair to the same values.
Run Rankrat under that pair as well if the primary image's built-in `10001:10001`
user is overridden. The provided Compose file applies `RANKRAT_UID` and
`RANKRAT_GID` consistently to both long-lived services after running this
hardened initializer.

Add this read-only volume mount to either published Rankrat invocation above:

```bash
--mount type=volume,src=rankrat-lighthouse-runtime,dst=/run/lighthouse,readonly
```

The normal `psyb0t/rankrat stdio` command then exposes the five Lighthouse tools
over stdio. The normal `psyb0t/rankrat http` command exposes the same tools over
Streamable HTTP at `/mcp` and REST under `/v1/lighthouse/`. Leave
`RANKRAT_LIGHTHOUSE_WORKER_SOCKET` empty to disable the worker explicitly. Stop
and remove only the worker and volume you created when they are no longer
needed.

The worker is for pages you control and trust. Chromium runs with
`--no-sandbox` because its built-in namespace/setuid sandbox cannot coexist with
the documented non-root, capability-free, `no-new-privileges` container. The
credential-free, read-only worker and public-address-only proxy reduce blast
radius but do not replace the renderer sandbox after a browser exploit. Use an
outer sandbox such as gVisor or Kata Containers before auditing hostile content.

| MCP tool | REST route |
|---|---|
| `lighthouse_audit` | `POST /v1/lighthouse/audits` |
| `lighthouse_seo_findings` | `POST /v1/lighthouse/seo-findings` |
| `lighthouse_accessibility_findings` | `POST /v1/lighthouse/accessibility-findings` |
| `lighthouse_performance_findings` | `POST /v1/lighthouse/performance-findings` |
| `lighthouse_best_practices_findings` | `POST /v1/lighthouse/best-practices-findings` |

Every operation accepts the same strict body: `account_id`, a configured
`site_url`, a child `page_url`, and optional `timeout_seconds` in the inclusive
5–300 second range. The aggregate audit returns all four category scores and
failed findings; the other four operations return only that category's failed
findings.

## Onboarding

`RANKRAT_READ_ONLY=false` does not by itself expose onboarding. It is the only
operation that rewrites the boundary file the server enforces, so it needs
`RANKRAT_ALLOW_AGENT_ONBOARDING=true` as well; without that,
`site_onboarding_submit` is absent from `tools/list` and its REST route is not
mounted. The config directory must be writable for the enabled operation; the
bundled wrapper validates its ownership/mode and changes only that mount. The
operator's own `rankrat onboard-site` command is unaffected.

The guidance is available either way, read-only, on every server:

| Surface | What it gives |
|---|---|
| `rankrat://onboarding` resource | The whole procedure and this server's onboarding posture |
| `rankrat://onboarding/{site_url}` template | Same, narrowed to one percent-encoded site |
| `onboarding_guide` tool | The identical document, for clients without resource support |

With a configured DNS provider account, `site_ownership_verify` requests the
real Google TXT and Bing CNAME proofs, publishes only those records through the
adapter selected by the account's `provider`, checks public DNS, and redeems
each provider. Poll `site_ownership_check` until it reports `complete`; DNS
propagation is asynchronous. Cloudflare is the currently shipped DNS adapter.
Without a supported adapter, a `sc-domain:` property accepts only DNS TXT,
while a `https://` URL-prefix property also accepts the GA4 tag, an HTML file,
or a meta tag.

The SEO expansion has the same names over stdio and Streamable HTTP MCP:

| MCP tool | REST route |
|---|---|
| `site_ownership_check` | `POST /v1/site-ownership-checks` |
| `site_ownership_verify` | `POST /v1/site-ownership-verifications` |
| `site_audit` | `POST /v1/site-audits` |
| `site_remediation_apply` | `POST /v1/site-remediations` |
| `bing_backlink_intelligence` | `POST /v1/bing/backlink-intelligence` |

## Complete MCP tool catalog

`tools/list` is authoritative for a running server because startup settings
decide which tools exist. The grouped inventory below mirrors the tool catalog
in the source. The exact REST paths and schemas live in the
[OpenAPI source](https://github.com/psyb0t/rankrat/blob/main/src/rankrat/api/openapi.yaml);
when enabled, `/openapi.json` removes write routes from a read-only server.

### Read-only tools

- **Server, boundaries, and guidance:** `server_info`, `accounts_list`,
  `sites_list`, `diagnostics`, `provider_readiness`, `onboarding_guide`.
- **Site, ownership, schema, and backlinks:** `site_audit`,
  `site_ownership_check`, `schema_validate_url`, `schema_validate_html`,
  `schema_validate_json_ld`, `bing_backlink_intelligence`.
- **Google Search Console and Indexing metadata:**
  `google_search_analytics_summary`, `google_search_analytics_comparison`,
  `google_search_analytics_dimension_report`,
  `google_search_analytics_drop_attribution`, `google_search_analytics_trend`,
  `google_search_analytics_anomalies`,
  `google_search_analytics_page_performance`,
  `google_search_analytics_query`, `google_sites_list`, `google_site_get`,
  `google_sitemaps_list`, `google_sitemap_get`, `google_url_inspection`,
  `google_url_inspection_batch`, `google_indexing_metadata`.
- **Google Analytics 4:** `google_analytics_account_inventory`,
  `google_analytics_data_streams`, `google_analytics_report`,
  `google_analytics_realtime_report`, `google_analytics_content_performance`,
  `google_analytics_landing_page_performance`,
  `google_analytics_organic_search_landing_pages`,
  `google_analytics_traffic_source_performance`,
  `google_analytics_ecommerce_performance`,
  `google_analytics_audience_segments`, `google_analytics_user_behavior`,
  `google_analytics_conversion_funnel`.
- **PageSpeed and local Lighthouse:** `pagespeed_analyze`,
  `pagespeed_core_web_vitals`, `lighthouse_audit`,
  `lighthouse_seo_findings`, `lighthouse_accessibility_findings`,
  `lighthouse_performance_findings`,
  `lighthouse_best_practices_findings`.
- **Cross-provider analysis:** `ga4_pagespeed_correlation`,
  `ga4_search_console_comparison`, `search_engine_comparison`,
  `search_engine_traffic_health`.
- **Bing Webmaster Tools:** `bing_keyword_statistics`,
  `bing_related_keywords`, `bing_traffic_trend`, `bing_traffic_anomalies`,
  `bing_traffic_comparison`, `bing_query_performance`,
  `bing_page_performance`, `bing_brand_analysis`, `bing_ranking_buckets`,
  `bing_query_opportunities`, `bing_page_opportunities`,
  `bing_opportunity_matrix`, `bing_query_page_performance`,
  `bing_query_cannibalization`, `bing_page_query_performance`,
  `bing_url_submission_quota`, `bing_crawl_issues`, `bing_crawl_stats`,
  `bing_feeds`, `bing_link_counts`, `bing_url_information`.

### Writable tools

These appear only when `RANKRAT_READ_ONLY=false`:

- **IndexNow:** `indexnow_submit`. IndexNow is an open change-notification
  protocol, not a dashboard: one participating endpoint shares an accepted
  notification with the other participating engines, while each engine makes
  its own crawl and indexing decisions.
- **Bing:** `bing_url_submit`, `bing_sitemap_submit`, `bing_site_submit`.
- **Google Search Console and Indexing:** `google_indexing_submit`,
  `google_indexing_batch_submit`, `google_site_submit`,
  `google_sitemap_submit`.
- **Google Analytics 4:** `google_analytics_account_rename`,
  `google_analytics_property_rename`.
- **Ownership and discovery remediation:** `site_ownership_verify`,
  `site_remediation_apply`.

`site_onboarding_submit` is the additional writable tool exposed only when
`RANKRAT_ALLOW_AGENT_ONBOARDING=true`. It is kept separate because it persists
the exact resources it creates into the boundary file.

## Checking it works

- `server_info` — the server is up and which mode it is in.
- `provider_readiness` — which providers are actually configured.
- `accounts_list` / `sites_list` — the boundary as the server sees it.
- `diagnostics` — deeper detail when one of the above is not what you expected.

If a provider-specific tool returns nothing, check `provider_readiness` before
assuming the data is missing upstream.
