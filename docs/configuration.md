# Configuration and boundaries

Rankrat parses recognized configuration once at startup. Unknown environment
variables are ignored, including misspelled `RANKRAT_*` names, so copy names
from [`.env.example`](../.env.example) instead of guessing. The boundary
document itself is strict: unknown fields, duplicates, invalid URLs,
incompatible provider fields, and relative credential paths fail startup.

## Contents

- [Host wrapper settings](#host-wrapper-settings)
- [Process settings](#process-settings)
- [Boundary document](#boundary-document)
- [Account fields](#account-fields)
- [URL containment](#url-containment)
- [DNS zones](#dns-zones)
- [IndexNow targets](#indexnow-targets)
- [Runtime policies](#runtime-policies)
- [Monitoring state](#monitoring-state)
- [Live selectors](#live-selectors)

## Host wrapper settings

These are consumed by `rankrat.sh`, not the Python process:

| Variable | Default | Meaning |
| --- | --- | --- |
| `RANKRAT_IMAGE` | `psyb0t/rankrat:latest` | Image reference |
| `RANKRAT_BOUNDARIES` | `./config/boundaries.json` | Host boundary file |
| `RANKRAT_SECRETS` | `./secrets` | Host secret directory |
| `RANKRAT_OAUTH` | `./oauth` | Host OAuth directory |
| `RANKRAT_STATE` | `./state` | Host state directory |
| `RANKRAT_ENV_FILE` | `./.env` | Setup-only env file |
| `RANKRAT_HTTP_PORT` | `8080` | Published loopback port |
| `RANKRAT_OAUTH_CALLBACK_PORT` | `49152` | Published OAuth callback |
| `RANKRAT_READ_ONLY` | `true` | Tool and route write policy |
| `RANKRAT_UNBOUNDED` | `false` | Trusted discovery bootstrap |
| `RANKRAT_ALLOW_AGENT_ONBOARDING` | `false` | Expose agent onboarding |

Keep host paths out of `.env`; setup passes that file into the container, where
unsupported names fail fast.

## Process settings

| Variable | Default/example | Meaning |
| --- | --- | --- |
| `RANKRAT_BOUNDARY_FILE` | `/run/config/boundaries.json` | Strict boundary document |
| `RANKRAT_SECRET_ROOT` | `/run/secrets` | Root permitted for credentials |
| `RANKRAT_OAUTH_TOKEN_ROOT` | `/run/oauth` | Root permitted for OAuth records |
| `RANKRAT_STATE_DATABASE` | `/run/state/rankrat.sqlite3` | Persistent monitor database; empty disables it |
| `RANKRAT_SCHEDULER_INTERVAL_SECONDS` | `60` | HTTP scheduler wake interval |
| `RANKRAT_STATE_RETENTION_DAYS` | `180` | Snapshot/event retention |
| `RANKRAT_LIGHTHOUSE_WORKER_SOCKET` | `/run/lighthouse/lighthouse.sock` | Optional worker socket; empty disables it |
| `RANKRAT_LOG_FILE` | `/tmp/rankrat/rankrat.log` | Structured log destination |
| `RANKRAT_LOG_LEVEL` | `INFO` | Log threshold |
| `RANKRAT_HTTP_HOST` | `127.0.0.1` | Bind address inside the network namespace |
| `RANKRAT_HTTP_PORT` | `8080` | HTTP listen port |
| `RANKRAT_HTTP_BEARER_SECRET_FILE` | unset on loopback | Bearer-secret file |
| `RANKRAT_ENABLE_OPENAPI` | `false` | Serve `/openapi.json` and API docs |
| `RANKRAT_READ_ONLY` | `true` | Remove writes when true |
| `RANKRAT_UNBOUNDED` | `false` | Relax per-resource allow-lists |
| `RANKRAT_ALLOW_AGENT_ONBOARDING` | `false` | Add agent onboarding when writable |

Transport is a command (`stdio` or `http`), not an environment mode. See the
complete process example in [`.env.example`](../.env.example).

## Boundary document

Copy [`boundaries.json.example`](../config/boundaries.json.example). Its shape:

```json
{
  "accounts": [],
  "indexnow_targets": []
}
```

At least one account or IndexNow target is required. IDs use lowercase letters,
digits, and hyphens, begin with a letter/digit, contain at most 63 characters,
and are unique across both collections.

Credential fields are absolute **container paths**. A host file beneath
`./secrets` appears beneath `/run/secrets`.

## Account fields

Every account has:

| Field | Meaning |
| --- | --- |
| `id` | Caller-facing stable account ID |
| `provider` | `google`, `bing`, `cloudflare`, `ahrefs`, `majestic`, `moz`, `semrush`, or `dataforseo` |
| `credential` | Absolute mounted credential path |

Provider fields:

| Field | Provider | Meaning |
| --- | --- | --- |
| `oauth_token_file` | Google | Dedicated writable token path |
| `pagespeed_api_key_file` | Google | Optional PageSpeed/CrUX key |
| `google_account_discovery` | Google | Authorize read-only discovery and targeting of OAuth-visible Search Console/GA4 resources |
| `search_console_sites` | Google | Exact `sc-domain:` or HTTPS prefix properties |
| `pagespeed_sites` | Google | HTTPS boundaries for PageSpeed/Lighthouse |
| `ga4_properties` | Google | Numeric GA4 property IDs |
| `sites` | Bing | Exact HTTPS site roots |
| `dns_zones` | Cloudflare | Exact provider zone ID/name pairs |
| `backlink_targets` | Commercial backlink providers | Exact HTTPS targets or domains |

Fields from another provider are rejected. Cloudflare accounts contain only DNS
zones; backlink accounts contain only backlink targets.

## URL containment

Public site roots must use absolute HTTPS on port 443 with no credentials,
query, or fragment. Rankrat normalizes IDNA hosts and paths; rejects dot
segments, backslashes, invalid percent encoding, and encoded traversal; then
authorizes each child URL by origin and path.

`sc-domain:example.com` includes the domain and subdomains. A Search Console
URL-prefix property includes only its scheme, host, and path subtree.

`google_account_discovery=true` deliberately broadens Google **read** scope:
inventory and report/query operations may target any Search Console site or GA4
property visible to that OAuth user, even when the resource is not listed.
Set it to `false` when reads must remain strictly list-only. It does not broaden
Search Console writes or GA4 property writes. One narrow exception exists when
writable mode is separately enabled: the same flag authorizes renaming an
OAuth-visible GA4 account by numeric ID. It never exposes a new credential
account or makes OAuth files caller-selectable.

## DNS zones

```json
"dns_zones": [
  {
    "provider_zone_id": "00000000000000000000000000000000",
    "name": "example.com"
  }
]
```

Replace the all-zero example. Public ownership operations accept a neutral
`dns_account_id`; Cloudflare is the shipped adapter.

## IndexNow targets

```json
"indexnow_targets": [
  {
    "id": "example",
    "host": "example.com",
    "key_location": "https://example.com/example-key.txt",
    "key_file": "/run/secrets/indexnow/key"
  }
]
```

The host is a DNS name without scheme/path. `key_location` must use HTTPS on
that host and identify a file. Target IDs and hosts are unique.

From a checkout:

```sh
make init-indexnow INDEXNOW_TARGET_ID=example INDEXNOW_HOST=example.com
make verify-indexnow-key INDEXNOW_TARGET_ID=example
```

Publish the generated key file before verification. This does not submit URLs.

## Runtime policies

| Read only | Unbounded | Agent onboarding | Result |
| --- | --- | --- | --- |
| `true` | `false` | `false` | Default read tools with fixed resources |
| `false` | `false` | `false` | Ordinary bounded writes added |
| `false` | `true` | `false` | Trusted resource discovery; onboarding tool absent |
| `false` | either | `true` | Agent onboarding added; safe writable config required |

Unbounded and agent onboarding require writes. Before mounting config writable,
the wrapper requires owner-only, host-owned, non-symlink paths. Unbounded mode
does not expose arbitrary credential paths, provider origins, DNS record bodies,
or IndexNow targets. It is reusable: enable it for a trusted bootstrap, persist
exact resources, then restart bounded.

## Monitoring state

The SQLite parent and file must be non-symlink paths owned by the runtime user
with no group/other bits. The scheduler runs only in long-lived HTTP mode.
Empty `RANKRAT_STATE_DATABASE` disables persistence and monitor operations
return a finite unavailable error.

Back up SQLite using its online-backup tooling or while Rankrat is stopped. Do
not copy only a live main database while WAL state may exist.

## Live selectors

`RANKRAT_LIVE_*` values in [`.env.example`](../.env.example) select exact
accounts/resources for opt-in live tests. Leave unused providers blank.
IndexNow additionally requires `RANKRAT_RUN_LIVE_INDEXNOW_SUBMISSION=true` so a
general live-test run cannot submit by accident. See the selector matrix in
[Providers and credentials](providers.md#live-provider-verification).
