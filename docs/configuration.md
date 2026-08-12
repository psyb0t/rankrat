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

## Host wrapper settings

These are consumed by the `rankrat` launcher, not the Python process:

| Variable | Default | Meaning |
| --- | --- | --- |
| `RANKRAT_IMAGE` | `psyb0t/rankrat:latest` | Image reference |
| `RANKRAT_LIGHTHOUSE_IMAGE` | `psyb0t/rankrat-lighthouse:latest` | HTTP companion image reference |
| `RANKRAT_DATA_DIR` | `$HOME/.config/rankrat` | Optional compatibility override for the persistent profile root |
| `RANKRAT_HTTP_PORT` | `8080` | Published loopback port |
| `RANKRAT_OAUTH_CALLBACK_PORT` | `49152` | Published OAuth callback |
| `RANKRAT_READ_ONLY` | `false` | Set true to remove every write tool and route |

The launcher derives exactly five paths from that root:
`config/boundaries.json`, `secrets/`, `oauth/`, `state/`, and
`docker-compose.yml`. It does not accept separate path overrides, so one
process cannot accidentally combine
credentials, OAuth records, and inventory from different profiles. The root
must be absolute, canonical, non-symlinked, and safe for Docker's `--mount`
syntax. Only the fixed children are mounted; the profile root is not.

Use `rankrat --data-dir /absolute/profile ...` when choosing a non-default
profile; use no path at all for `$HOME/.config/rankrat`. `rankrat setup`
creates every path and the HTTP bearer safely. HTTP uses the profile as its
Compose project directory, creates the reviewed Compose file there when
missing, and preserves an existing regular file. The project directory and
Compose file must be owned by the current UID and not group/world writable.
The Python process ignores the host-only data-directory and image selectors.

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
| `RANKRAT_READ_ONLY` | `false` | Remove every write tool and route when true |

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

An empty document is valid before guided setup. IDs use lowercase letters,
digits, and hyphens, begin with a letter/digit, contain at most 63 characters,
and are unique across both collections.

Credential fields are absolute **container paths**. A host file beneath
`./secrets` appears beneath `/run/secrets`.

## Account fields

Every account has:

| Field | Meaning |
| --- | --- |
| `id` | Caller-facing stable local account ID |
| `provider` | `google`, `bing`, or `cloudflare` |
| `credential` | Absolute mounted account-wide credential path |

Provider fields:

| Field | Provider | Meaning |
| --- | --- | --- |
| `oauth_token_file` | Google | Dedicated writable token path |
| `pagespeed_api_key_file` | Google | Optional PageSpeed/CrUX key |
| `search_console_sites` | Google | Discovered/cached `sc-domain:` or HTTPS properties |
| `pagespeed_sites` | Google | Known HTTPS roots used for public-page containment |
| `ga4_properties` | Google | Discovered/cached numeric GA4 property IDs |
| `sites` | Bing | Discovered/cached HTTPS site roots |
| `dns_zones` | Cloudflare | Discovered/cached provider zone ID/name pairs |

Fields from another provider are rejected. Cloudflare accounts contain only DNS
zone inventory. These arrays do not narrow the configured credential's
authority. Rankrat discovers or records resources as operations need them,
while the provider remains the source of truth for what the credential may
access.

## URL containment

Public site roots must use absolute HTTPS on port 443 with no credentials,
query, or fragment. Rankrat normalizes IDNA hosts and paths; rejects dot
segments, backslashes, invalid percent encoding, and encoded traversal; then
authorizes each child URL by origin and path.

`sc-domain:example.com` includes the domain and subdomains. A Search Console
URL-prefix property includes only its scheme, host, and path subtree.

For provider-backed operations, the configured account ID selects a fixed
credential and fixed provider origin. The requested property/site is then
validated against inventory returned by that account. URL-bearing operations
also apply the public-HTTPS and child-containment rules above. This prevents a
caller from selecting another credential or using Rankrat as an arbitrary URL
proxy without turning cached resource arrays into a second authorization layer.

## DNS zones

```json
"dns_zones": [
  {
    "provider_zone_id": "00000000000000000000000000000000",
    "name": "example.com"
  }
]
```

Public ownership operations accept a neutral `dns_account_id`; Cloudflare is
the shipped adapter. Rankrat can discover zones visible to the configured
Cloudflare account, so an empty list is valid before first discovery.

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

| `RANKRAT_READ_ONLY` | Result |
| --- | --- |
| `false` (default) | All supported reads and writes, including site onboarding |
| `true` | Read tools only; write REST routes and MCP tools are not mounted or listed |

This is the only capability switch. Provider credentials are the authority.
The wrapper still requires an owner-only, host-owned, non-symlink config
directory before a writable process may persist discovered resources. Fixed
provider origins, typed request validation, public-URL checks, and HTTP bearer
authentication remain enforced in either operator style.

## Monitoring state

The SQLite parent and file must be non-symlink paths owned by the runtime user
with no group/other bits. The scheduler runs only in long-lived HTTP mode.
Empty `RANKRAT_STATE_DATABASE` disables persistence and monitor operations
return a finite unavailable error.

Back up SQLite using its online-backup tooling or while Rankrat is stopped. Do
not copy only a live main database while WAL state may exist.
