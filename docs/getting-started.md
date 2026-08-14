# Getting started

This guide takes a fresh machine to a verified Rankrat deployment. Guided setup
does not create site properties or submit URLs; those operations become
available to the human's agent after setup succeeds.

## Contents

- [Prerequisites](#prerequisites)
- [Install the wrapper](#install-the-wrapper)
- [Run guided setup](#run-guided-setup)
- [Start Rankrat](#start-rankrat)
- [First calls](#first-calls)
- [Next steps](#next-steps)

## Prerequisites

- Docker Engine with `docker run` access and the Compose plugin for HTTP mode;
- a POSIX shell;
- `curl`, `openssl`, and standard core utilities.

The easiest setup path also uses Git and GNU Make. Python, Node, uv, pnpm, and
security scanners run in pinned containers.

## Install the wrapper

Rankrat ships as `psyb0t/rankrat`. The wrapper is readable convenience around
the supported `docker run` contract.

```sh
curl -fsSL https://raw.githubusercontent.com/psyb0t/rankrat/main/rankrat -o rankrat
less rankrat
chmod +x rankrat
sudo mv rankrat /usr/local/bin/rankrat
rankrat --help
```

Without access to `/usr/local/bin`, keep it locally and use `./rankrat`.

## Run guided setup

Create credentials before running setup. If you do not use a provider, skip
its credential; Rankrat asks only for the providers you select.

- **Google:** start at <https://console.cloud.google.com/projectcreate> and
  create the project, Desktop OAuth client JSON, and optional PageSpeed/CrUX
  key exactly as described in [Google OAuth](providers.md#google-oauth).
- **Bing:** start at <https://www.bing.com/webmasters/home> and create the one
  account-wide API key as described in
  [Bing Webmaster Tools](providers.md#bing-webmaster-tools).
- **Microsoft Clarity:** start at <https://clarity.microsoft.com/> and create
  one Data Export API token for each project as described in
  [Microsoft Clarity](providers.md#microsoft-clarity).

For Cloudflare, create a dedicated **User API Token** before choosing
`cloudflare` in setup. Open
<https://dash.cloudflare.com/profile/api-tokens>, then click **Create Token →
Create Custom Token**. Name it `rankrat`; add **Zone → Zone → Read**, **Zone →
DNS → Edit**, **Zone → Analytics → Read**, **Zone → Cache Purge → Purge**,
**Zone → Cache Rules → Edit**, **Zone → Single Redirect → Edit**, **Account →
Account Rulesets → Edit**, and **Account → Account Filter Lists → Edit**. Set
**Zone Resources → Include → All zones** and **Account Resources → Include →
All accounts**. Select **Continue to summary → Create Token**, copy the value
shown once, then paste it at Rankrat's hidden prompt. Do not use Cloudflare's
Account API Token screen or the Global API Key. This one token covers every
Cloudflare feature Rankrat currently ships; the feature mapping is in
[Providers and credentials](providers.md#cloudflare).

Now start the standalone launcher:

```sh
rankrat setup --google-oauth-client-file "/absolute/path/to/client_secret_...json"
```

Omit `--google-oauth-client-file` when you are not configuring Google. From a
checkout, pass the same host path through the environment:

```sh
RANKRAT_GOOGLE_OAUTH_CLIENT_FILE="$HOME/Downloads/client_secret_...json" make setup
```

It creates `$HOME/.config/rankrat` with owner-only permissions, a minimal valid
boundary file, the HTTP bearer, and all credential/OAuth/state directories
before it asks for anything. To keep a distinct account or test profile, pass
one absolute directory:

```sh
rankrat --data-dir /absolute/path/to/rankrat-profile setup
```

It creates missing local paths without overwriting, rejects symlinks,
normalizes sensitive permissions, then asks which providers to configure. For
each choice it prints the provider console URL and required account-wide
permissions, accepts the credential through a hidden prompt, and stores it at
the standard path with mode `0600`. For Google, it imports the Desktop OAuth
client JSON file you passed to the wrapper—do not paste its multi-line contents.
Google setup then runs one full-scope OAuth flow and saves the refresh record.

Setup is safe to rerun. A selected provider is added or refreshed in place;
accounts for providers you omit remain unchanged, including discovered
inventory. If the registry already contains multiple accounts for a selected
provider, setup stops before reading a secret so you can identify the intended
account in `config/boundaries.json`.

After credentials are present, setup runs provider readiness. It does not
create site properties, submit URLs/sitemaps, send IndexNow notifications, or
create a disposable DNS record solely to test a Cloudflare token. The explicit
Cloudflare permission above is therefore required even when readiness can list
zones.

The standalone wrapper provides the same guided setup plus an explicit Google
OAuth reauthorization command for operators who do not use a checkout:

```sh
rankrat --data-dir /absolute/path/to/rankrat-profile setup
rankrat --data-dir /absolute/path/to/rankrat-profile auth-google --print-authorization-url
```

See [Providers and credentials](providers.md) for provider-side steps and
permissions.

## Start Rankrat

```sh
rankrat           # stdio MCP using ~/.config/rankrat
rankrat http      # attached REST + Streamable HTTP MCP + Lighthouse
rankrat http -d   # detached stack with automatic restarts
```

HTTP treats the selected profile directory as the Compose project directory. If
`docker-compose.yml` is absent there, the wrapper creates the reviewed default
atomically; if a safe regular file already exists, the wrapper preserves and
uses it. The profile root and Compose file must be owned by the current UID and
not group/world writable.
The profile root itself is not mounted into a container—only `config`,
`secrets`, `oauth`, and `state` are.

From a checkout, build both local images and attach to the same deployment with:

```sh
make run-http
```

Direct `docker compose up` remains supported through the committed file. Export
the absolute `RANKRAT_DATA_DIR` and numeric `RANKRAT_UID`/`RANKRAT_GID` in the
shell that runs Compose; the launcher derives them automatically.

These are writable by default. Set `RANKRAT_READ_ONLY=true` before either
command when the caller must not discover or invoke mutations.

HTTP endpoints:

- `GET http://127.0.0.1:8080/healthz`;
- `GET http://127.0.0.1:8080/ready`;
- MCP at `http://127.0.0.1:8080/mcp`;
- REST under `http://127.0.0.1:8080/v1/`.

When bearer auth is configured, only `/healthz` is public. Send the contents of
`$HOME/.config/rankrat/secrets/rankrat/http-bearer-token` as
`Authorization: Bearer <token>` to
`/ready`, `/mcp`, `/v1/`, `/openapi.json`, and the docs UI. Stdio does not use
the bearer.

## First calls

1. `server_info` — process policy and capability metadata.
2. `accounts_list` and `sites_list` — configured non-secret scope.
3. `diagnostics` — local checks without provider calls.
4. `provider_readiness` — live access for one account.

Enable runtime OpenAPI only when wanted:

```dotenv
RANKRAT_ENABLE_OPENAPI=true
```

Then inspect `/openapi.json`. The committed [`openapi.json`](../openapi.json)
contains the full writable contract; the runtime document removes disabled
routes.

## Next steps

- [Configuration and boundaries](configuration.md)
- [Transports and deployment](transports.md)
- [Feature workflows](features.md)
- [Security](security.md)
- [Troubleshooting](troubleshooting.md)
