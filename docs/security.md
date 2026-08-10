# Security

Rankrat is designed for an operator's own accounts and sites. It is not a
public arbitrary-URL proxy, competitor crawler, generic DNS API, or public
multi-tenant gateway. Its safety depends on intentional account-wide provider
credentials, controlled transport access, validated input, fixed provider
origins, and hardened mounts working together.

## Contents

- [Trust model](#trust-model)
- [Boundary enforcement](#boundary-enforcement)
- [Read-only discovery](#read-only-discovery)
- [HTTP exposure](#http-exposure)
- [Secret handling](#secret-handling)
- [Public fetch and SSRF controls](#public-fetch-and-ssrf-controls)
- [Lighthouse isolation](#lighthouse-isolation)
- [DNS write limits](#dns-write-limits)
- [Provider write limits](#provider-write-limits)
- [Container hardening](#container-hardening)
- [Logs and diagnostics](#logs-and-diagnostics)
- [Production checklist](#production-checklist)
- [Reporting security issues](#reporting-security-issues)

## Trust model

Trusted:

- the operator who creates boundaries and mounts;
- callers allowed to reach stdio or authenticated HTTP;
- the provider accounts/permissions intentionally configured.

Untrusted:

- all HTTP/MCP request data;
- provider responses;
- public DNS and web content;
- redirects and page subresources;
- mounted files until type, ownership, permissions, and roots are validated.

## Boundary enforcement

The strict startup document fixes credential accounts and records discovered
resource inventory. Rankrat validates account IDs, provider-specific fields, URLs, child
containment, DNS zones, GA4 IDs, IndexNow hosts/key locations, and duplicate
ownership. Unknown fields fail startup.

Normal callers cannot choose provider origins or credential paths. A configured
account credential deliberately authorizes every supported operation and every
resource that provider account can reach. Inventory arrays are not per-site
permission lists. Onboarding may persist newly discovered resource IDs.

Read [Configuration](configuration.md) for the field and mode matrix.

## Read-only discovery

`RANKRAT_READ_ONLY=true` is stronger than returning "forbidden": write services,
MCP tools, and REST routes are not mounted or listed. Agents cannot discover a
write schema on that process.

Writable mode trusts its caller to invoke account-authorized provider actions.
If you do not trust a caller with every visible write tool, give it a read-only
process instead.

## HTTP exposure

- The wrapper publishes HTTP on `127.0.0.1`.
- Inside the container Rankrat binds `0.0.0.0` so Docker port publishing works.
- Non-loopback process binds require `RANKRAT_HTTP_BEARER_SECRET_FILE`.
- Only `/healthz` bypasses a configured bearer. `/ready`, `/v1/`, `/mcp`,
  runtime OpenAPI, and the docs UI use the same bearer policy.
- Stdio authorization is the ability to start the process and access mounts.

Keep HTTP on loopback or a private network. For remote access, use TLS,
network-level restriction, and secret-backed bearer injection. Never place a
real bearer in a URL, tracked file, shell example, or child-process argument.

## Secret handling

- Provider secrets live in owner-only files under `secrets/` and are mounted
  read-only.
- Google OAuth records live under the separate writable `oauth/` mount because
  refresh rotation must persist.
- Monitoring state uses a separate writable owner-only mount.
- Credential paths must be absolute, within configured roots, and cannot be
  shared in ways the boundary model forbids.
- `make setup` temporarily mounts the secret/config trees writable, rejects
  symlinks, stores credentials with owner-only modes, then normal runtime mounts
  provider secrets read-only.
- Provider credential values, refresh records, raw bodies, and key-bearing URLs
  are not returned or logged.

Provider errors crossing REST or either MCP transport retain a finite category
such as authentication, authorization, rate limit, not found, invalid response,
or upstream failure, but replace upstream text with `provider operation failed`.

If a credential ever enters tracked history or logs, treat it as compromised:
rotate it and audit provider access.

## Public fetch and SSRF controls

The site crawler and URL schema validator accept only authorized public HTTPS
targets. They reject:

- credentials, query/fragment where the boundary forbids them, and nonstandard
  ports;
- IP literals;
- loopback, private, link-local, multicast, reserved, documentation, and other
  non-public address classes;
- mixed DNS answers containing any disallowed address;
- encoded traversal, dot segments, and backslash separators;
- out-of-bound origins/paths;
- redirects for the strict site-audit fetch path.

Resolution is pinned for the request so a name cannot pass one check then
rebind to an internal address during the fetch.

## Lighthouse isolation

The browser runs in a separate image with no provider-secret mounts and no TCP
listener. A local proxy performs public-address-only resolution and traffic
control; Rankrat reauthorizes requested and final URLs.

Chromium uses `--no-sandbox` in the non-root, capability-free worker. Container
limits and the proxy are not equivalent to Chromium's renderer sandbox. Audit
only trusted operator-controlled pages, or place the worker in a stronger outer
runtime such as gVisor/Kata. Public third-party subresources and a public
cross-origin redirect can still be fetched. Read [Lighthouse](lighthouse.md).

## DNS write limits

Cloudflare tokens may have DNS Edit, but Rankrat exposes no arbitrary record
name/type/value operation. Ownership verification obtains proof records from
Google/Bing, authorizes an exact configured zone, reuses exact records, refuses
conflicting CNAMEs, and does not return proof values.

The public contract is provider-neutral. Adding another adapter must preserve
the same narrow proof-only behavior rather than expose generic DNS CRUD.

## Provider write limits

- Search Console/Bing sites are resolved through the selected account; child
  URLs and sitemaps must remain inside the selected site/property.
- Google Indexing submissions must pass supported eligibility checks.
- IndexNow URLs must belong to the fixed target host and key location.
- Cloudflare purges are exact URLs; no whole-zone purge.
- Cache writes choose one of two named templates; no arbitrary ruleset body.
- GA4 writes rename account-visible resources or create/reuse a property during
  onboarding; no Analytics deletion.
- Backlink providers are read-only; target inventory supplies report inputs and
  containment rather than credential authorization.

Upstream acceptance may be asynchronous and does not guarantee indexing,
ownership completion, or ranking.

## Container hardening

The wrapper and Compose examples use:

- non-root UID/GID;
- read-only root filesystems;
- `cap_drop: ALL` / `--cap-drop=ALL`;
- `no-new-privileges`;
- explicit process, memory, and CPU limits;
- small noexec/nosuid tmpfs mounts;
- loopback host ports;
- explicit read-only secret/config mounts;
- separate writable OAuth/state volumes;
- health checks and init processes.

Compose's two volume initializers run as root only long enough to set volume
ownership. They are networkless, get only `CHOWN`/`FOWNER`, and exit.

Do not add Docker socket mounts, host PID/network namespaces, privileged mode,
or provider credentials to the Lighthouse worker.

## Logs and diagnostics

Structured logs should go to the configured file/stderr path. Stdio stdout is
reserved for MCP framing. OAuth authorization failures may write bounded
diagnostic information to `google-auth.log` in the OAuth area; protect it like
OAuth state and inspect it locally rather than pasting it publicly.

`diagnostics` returns local non-secret checks. `provider_readiness` performs a
bounded provider call and returns typed state rather than raw responses.

## Production checklist

- [ ] Config, secrets, OAuth, and state are owner-only real paths without
  symlinks.
- [ ] Unused example provider accounts are removed.
- [ ] Provider tokens cover the intended account and every Rankrat feature the
  operator expects; unrelated provider products remain excluded where the
  provider supports that distinction.
- [ ] `RANKRAT_READ_ONLY=true` is set for any caller that must not mutate state.
- [ ] Writable callers are intentionally trusted with all visible Rankrat
  mutations, including onboarding.
- [ ] HTTP is loopback/private, bearer-protected, and TLS-proxied if remote.
- [ ] Provider secrets are never mounted into Lighthouse.
- [ ] State and the boundary are backed up before onboarding.
- [ ] `rankrat.sh setup` and intended provider live checks pass.
- [ ] Production image, MCP, REST, and security regression tests pass for the
  release being deployed.
- [ ] Dependency/image audits and secret scanning are green.

## Reporting security issues

Open a private security report through the repository's GitHub Security page
when the issue would expose credentials, cross boundaries, or permit arbitrary
network/file access. Do not place live secrets or exploit data in a public issue.
