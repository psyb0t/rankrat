# Configuration and boundaries

Every runtime switch and every boundary field, and what each one actually does.

Rankrat reads recognized configuration once, at startup, and never reloads.
Unknown `RANKRAT_*` variables are ignored — your typos included — so copy names
from [`.env.example`](../.env.example) instead of wondering why a setting did
nothing. The boundary document is the opposite of forgiving: unknown fields,
duplicates, invalid URLs, mismatched provider fields, and relative credential
paths all fail startup outright.

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

Read by the `rankrat` launcher, not the Python process:

| Variable | Default | Meaning |
| --- | --- | --- |
| `RANKRAT_IMAGE` | `psyb0t/rankrat:latest` | Image reference |
| `RANKRAT_LIGHTHOUSE_IMAGE` | `psyb0t/rankrat-lighthouse:latest` | HTTP companion image reference |
| `RANKRAT_DATA_DIR` | `$HOME/.config/rankrat` | Profile root; the env form of `--data-dir` |
| `RANKRAT_HTTP_PORT` | `8080` | Published loopback port |
| `RANKRAT_OAUTH_CALLBACK_PORT` | `49152` | Published OAuth callback |
| `RANKRAT_READ_ONLY` | `false` | Set true to remove every write tool and route |

The launcher derives exactly five paths from that root:
`config/boundaries.json`, `secrets/`, `oauth/`, `state/`, and
`docker-compose.yml`. There are no separate per-path overrides — so one process
can't accidentally splice credentials, OAuth records, and inventory from
different profiles. The root must be absolute, canonical, non-symlinked, and
free of anything that would confuse Docker's `--mount` syntax. Only those fixed
children mount; the root itself does not.

Pass `rankrat --data-dir /absolute/profile ...` for a non-default profile,
nothing at all for `$HOME/.config/rankrat`. `rankrat setup` creates every path
and the HTTP bearer safely. HTTP uses the profile as its Compose project
directory: it writes the reviewed Compose file when one is missing, preserves an
existing regular file, and requires both the directory and the file to be owned
by the current UID and not group/world writable. The Python process ignores the
data-directory and image selectors entirely — those are the wrapper's business.

### Permanent host env file

To set these once instead of per run, put them in a host env file at
`~/.config/rankrat/.env` (override the path with `RANKRAT_ENV_FILE`). The launcher
reads it before it selects a profile, so it can set `RANKRAT_DATA_DIR` — which
profile to use — along with `RANKRAT_READ_ONLY`, `RANKRAT_IMAGE`,
`RANKRAT_LIGHTHOUSE_IMAGE`, `RANKRAT_HTTP_PORT`, `RANKRAT_OAUTH_CALLBACK_PORT`,
and `RANKRAT_ROLLING`. Each variable is filled only when it is unset or empty, so
a `--data-dir` flag or a real environment variable still wins. Every `RANKRAT_*`
line is parsed and never sourced; a symlinked file is rejected and a missing file
is a no-op. This is the layer MCP launchers need, since they run `rankrat` with a
minimal environment that never carries your shell exports.

The host env file is read before any profile is selected: for the default
profile it is that profile's own `.env`, and a profile reached via
`RANKRAT_DATA_DIR` keeps its own `.env` (written by `setup`/`upgrade`, which pins
that profile's images, HTTP port, and read-only flag). Precedence for a host
setting is:
`--data-dir` flag, then a real environment variable, then the host env file, then
the profile `.env`, then the built-in default.

## Process settings

Read by the Python process:

| Variable | Default/example | Meaning |
| --- | --- | --- |
| `RANKRAT_BOUNDARY_FILE` | `/run/config/boundaries.json` | Strict boundary document |
| `RANKRAT_SECRET_ROOT` | `/run/secrets` | Root permitted for credentials |
| `RANKRAT_OAUTH_TOKEN_ROOT` | `/run/oauth` | Root permitted for OAuth records |
| `RANKRAT_STATE_DATABASE` | empty | Persistent monitor database; empty disables it. The shipped HTTP Compose sets `/run/state/rankrat.sqlite3` |
| `RANKRAT_SCHEDULER_INTERVAL_SECONDS` | `60` | HTTP scheduler wake interval (10–3600) |
| `RANKRAT_STATE_RETENTION_DAYS` | `180` | Snapshot/event retention (1–3650) |
| `RANKRAT_LIGHTHOUSE_WORKER_SOCKET` | `/run/lighthouse/lighthouse.sock` | Worker socket; empty disables it |
| `RANKRAT_LOG_FILE` | `/tmp/rankrat/rankrat.log` | Structured log destination |
| `RANKRAT_LOG_LEVEL` | `INFO` | Log threshold |
| `RANKRAT_HTTP_HOST` | `127.0.0.1` | Bind address inside the network namespace |
| `RANKRAT_HTTP_PORT` | `8080` | HTTP listen port |
| `RANKRAT_HTTP_BEARER_SECRET_FILE` | unset on loopback | Bearer-secret file |
| `RANKRAT_ENABLE_OPENAPI` | `false` | Serve `/openapi.json` |
| `RANKRAT_READ_ONLY` | `false` | Remove every write tool and route when true |

Transport is a command — `stdio` or `http` — not an environment mode. The
bounds shown are enforced, and an out-of-range value fails startup. A
non-loopback `RANKRAT_HTTP_HOST` refuses to start without
`RANKRAT_HTTP_BEARER_SECRET_FILE`. Full example in
[`.env.example`](../.env.example).

## Boundary document

Copy [`boundaries.json.example`](../config/boundaries.json.example). Its shape:

```json
{
  "accounts": [],
  "indexnow_targets": []
}
```

An empty document is valid before guided setup. IDs use lowercase letters,
digits, and hyphens, begin with a letter or digit, run at most 63 characters,
and are unique across both collections.

Credential fields are absolute **container paths**: a host file beneath
`./secrets` appears beneath `/run/secrets`.

## Account fields

Every account carries:

| Field | Meaning |
| --- | --- |
| `id` | Caller-facing stable local account ID |
| `provider` | `google`, `bing`, `cloudflare`, or `clarity` |
| `credential` | Absolute mounted account-wide credential path |

Provider-specific fields:

| Field | Provider | Meaning |
| --- | --- | --- |
| `oauth_token_file` | Google | Dedicated writable token path |
| `pagespeed_api_key_file` | Google | Optional PageSpeed/CrUX key |
| `search_console_sites` | Google | Discovered/cached `sc-domain:` or HTTPS properties |
| `pagespeed_sites` | Google | Known HTTPS roots used for public-page containment |
| `ga4_properties` | Google | Discovered/cached numeric GA4 property IDs |
| `sites` | Bing | Discovered/cached HTTPS site roots |
| `dns_zones` | Cloudflare | Discovered/cached provider zone ID/name pairs |

A field from the wrong provider is rejected. Cloudflare accounts carry only DNS
zone inventory; a Clarity account carries only its `id`, `provider`, and
project-token `credential` — one account, one Clarity project. None of these
arrays narrows the credential's authority. Rankrat records resources as
operations need them, but the provider stays the source of truth for what the
credential can reach.

## URL containment

Public site roots must be absolute HTTPS on port 443 with no credentials, query,
or fragment. Rankrat normalizes IDNA hosts and paths; rejects dot segments,
backslashes, invalid percent encoding, and encoded traversal; then authorizes
each child URL by origin and path.

`sc-domain:example.com` covers the domain and its subdomains. A Search Console
URL-prefix property covers only its scheme, host, and path subtree.

For provider-backed operations, the account ID selects a fixed credential and a
fixed provider origin, and the requested property/site is validated against the
inventory that account returns. URL-bearing operations also apply the
public-HTTPS and child-containment rules above. A caller can't pick another
credential or bend Rankrat into an arbitrary URL proxy — and the cached resource
arrays never become a second authorization layer to do it.

## DNS zones

```json
"dns_zones": [
  {
    "provider_zone_id": "00000000000000000000000000000000",
    "name": "example.com"
  }
]
```

Public ownership operations take a neutral `dns_account_id`; Cloudflare is the
shipped adapter. Rankrat discovers zones visible to the configured Cloudflare
account, so an empty list is valid before first discovery.

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

The host is a DNS name, no scheme or path. `key_location` must be HTTPS on that
same host and point at a file. Target IDs and hosts are unique.

From a checkout:

```sh
make init-indexnow INDEXNOW_TARGET_ID=example INDEXNOW_HOST=example.com
make verify-indexnow-key INDEXNOW_TARGET_ID=example
```

Publish the generated key file before verification. This does not submit URLs.

## Runtime policies

| `RANKRAT_READ_ONLY` | Result |
| --- | --- |
| `false` (default) | All supported reads and writes, site onboarding included |
| `true` | Read tools only; write REST routes and MCP tools are never mounted or listed |

This is the only capability switch — provider credentials are the authority.
The wrapper still demands an owner-only, host-owned, non-symlink config
directory before a writable process may persist discovered resources. Fixed
provider origins, typed request validation, public-URL checks, and HTTP bearer
auth stay enforced either way.

## Monitoring state

The SQLite parent and file must be non-symlink paths owned by the runtime user
with no group or other bits. The scheduler runs only in long-lived HTTP mode. An
empty `RANKRAT_STATE_DATABASE` disables persistence, and monitor operations then
return a finite unavailable error.

Back up SQLite with its online-backup tooling, or while Rankrat is stopped —
copying a live main database while WAL state may exist gives you a corrupt one.
