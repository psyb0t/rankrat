# Getting started

Fresh machine to a running, verified Rankrat deployment.

Guided setup validates provider access and nothing else — it does not create
site properties or submit URLs. Those are your agent's job, once setup succeeds.

## Contents

- [Prerequisites](#prerequisites)
- [Install the wrapper](#install-the-wrapper)
- [Run guided setup](#run-guided-setup)
- [Start Rankrat](#start-rankrat)
- [First calls](#first-calls)
- [Next steps](#next-steps)

## Prerequisites

- Docker Engine you can `docker run` against, plus the Compose plugin for HTTP mode;
- a POSIX shell;
- `curl`, `openssl`, and the usual core utilities.

That is the whole list for the wrapper path — Python, Node, uv, pnpm, and the
security scanners all run in pinned containers, so you never install them.
Working from a source checkout instead adds Git and GNU Make.

## Install the wrapper

Rankrat is the `psyb0t/rankrat` image. The `rankrat` wrapper is a readable
script over the supported `docker run` contract — nothing in it you can't audit
first. Download the installer, read it, then run it — per-user (no root) or
system-wide:

```sh
curl -fsSL https://raw.githubusercontent.com/psyb0t/rankrat/main/install.sh -o rankrat-install.sh
less rankrat-install.sh
bash rankrat-install.sh                # per-user   -> ~/.local/bin/rankrat
sudo bash rankrat-install.sh --system  # system-wide -> /usr/local/bin/rankrat
```

Mode auto-detects from who runs it; `--user` / `--system` force it, and
`--uninstall` removes the command. A per-user install that lands `~/.local/bin`
off your PATH prints the exact bash/zsh line to fix it.

Rather place the wrapper by hand? Download it, read it, move it yourself:

```sh
curl -fsSL https://raw.githubusercontent.com/psyb0t/rankrat/main/rankrat -o rankrat
less rankrat
chmod +x rankrat
mv rankrat ~/.local/bin/rankrat         # or: sudo mv rankrat /usr/local/bin/rankrat
rankrat --help
```

No write access to either bin directory? Keep it in the checkout and run
`./rankrat`.

Either way, the profile lives owner-only at `~/.config/rankrat` (override per
launch with `rankrat --data-dir DIR` or `RANKRAT_DATA_DIR`). A system-wide
install shares the command and nothing else — every user still runs `rankrat
setup` into their own private profile, and the wrapper refuses to share one.

## Run guided setup

Create the credentials first. Skip any provider you don't use — setup only asks
about the ones you pick.

- **Google:** start at <https://console.cloud.google.com/projectcreate> and
  create the project, Desktop OAuth client JSON, and optional PageSpeed/CrUX
  key exactly as described in [Google OAuth](providers.md#google-oauth).
- **Bing:** start at <https://www.bing.com/webmasters/home> and create the one
  account-wide API key as described in
  [Bing Webmaster Tools](providers.md#bing-webmaster-tools).
- **Microsoft Clarity:** start at <https://clarity.microsoft.com/> and create
  one Data Export API token per project as described in
  [Microsoft Clarity](providers.md#microsoft-clarity).

Cloudflare is the one with sharp edges. Create a dedicated **User API Token**
before you pick `cloudflare` in setup. Open
<https://dash.cloudflare.com/profile/api-tokens>, then **Create Token → Create
Custom Token**. Name it `rankrat`; add **Zone → Zone → Read**, **Zone → DNS →
Edit**, **Zone → Analytics → Read**, **Zone → Cache Purge → Purge**, **Zone →
Cache Rules → Edit**, **Zone → Single Redirect → Edit**, **Account → Account
Rulesets → Edit**, and **Account → Account Filter Lists → Edit**. Set **Zone
Resources → Include → All zones** and **Account Resources → Include → All
accounts**. Select **Continue to summary → Create Token**, copy the value
(shown once), and paste it at Rankrat's hidden prompt. Do not use the Account
API Token screen or the Global API Key. This one token covers every Cloudflare
feature Rankrat ships; the feature mapping is in
[Providers and credentials](providers.md#cloudflare).

Now run setup:

```sh
rankrat setup
```

From a source checkout it's `make setup`.

Setup builds `$HOME/.config/rankrat` owner-only — a minimal valid boundary file,
the HTTP bearer, and the credential/OAuth/state directories — before it asks you
for anything. Want a separate account or a throwaway test profile? Point it
somewhere else:

```sh
rankrat --data-dir /absolute/path/to/rankrat-profile setup
```

It creates missing paths without overwriting, rejects symlinks, normalizes
sensitive permissions, then walks each provider you selected: prints the console
URL and the account-wide permissions it needs, takes the credential through a
hidden prompt, and writes it at mode `0600`. For Google you paste the Desktop
OAuth client JSON at that prompt — it's a single line, paste it as-is — and
setup then runs one full-scope OAuth flow and saves the refresh record.

Rerun it as often as you like. A selected provider is added or refreshed in
place; the ones you skip stay untouched, discovered inventory included. If the
registry already holds several accounts for a provider you selected, setup stops
before reading the secret so you can name the intended account in
`config/boundaries.json`.

Once credentials exist, setup runs provider readiness. It does not create site
properties, submit URLs or sitemaps, fire IndexNow, or spin up a throwaway DNS
record just to prove a Cloudflare token — which is exactly why the explicit
Cloudflare permissions above are required even though readiness can list zones.

No checkout? The wrapper gives you the same guided setup plus an explicit Google
reauthorization command:

```sh
rankrat --data-dir /absolute/path/to/rankrat-profile setup
rankrat --data-dir /absolute/path/to/rankrat-profile auth-google --print-authorization-url
```

Provider-side steps and permissions live in
[Providers and credentials](providers.md).

## Start Rankrat

```sh
rankrat           # stdio MCP using ~/.config/rankrat
rankrat http      # attached REST + Streamable HTTP MCP + Lighthouse
rankrat http -d   # detached stack with automatic restarts
```

HTTP uses the selected profile as its Compose project directory. If there's no
`docker-compose.yml` there, the wrapper drops in its reviewed default
atomically; if a safe regular file is already there, it leaves yours alone and
uses it. The profile root and that Compose file must be owned by the current UID
and not group- or world-writable. The profile root itself never gets mounted —
only `config`, `secrets`, `oauth`, and `state` do.

From a checkout, build both local images and attach to the same deployment:

```sh
make run-http
```

Raw `docker compose up` still works through the committed file — export the
absolute `RANKRAT_DATA_DIR` and numeric `RANKRAT_UID`/`RANKRAT_GID` in that
shell first; the wrapper derives them for you.

All of this is writable by default. Set `RANKRAT_READ_ONLY=true` before either
command when the caller must not even discover a mutation.

HTTP endpoints:

- `GET http://127.0.0.1:8080/healthz`;
- `GET http://127.0.0.1:8080/ready`;
- MCP at `http://127.0.0.1:8080/mcp`;
- REST under `http://127.0.0.1:8080/v1/`.

With bearer auth configured, only `/healthz` stays public. Send the contents of
`$HOME/.config/rankrat/secrets/rankrat/http-bearer-token` as
`Authorization: Bearer <token>` to `/ready`, `/mcp`, `/v1/`, and `/openapi.json`.
Stdio uses no bearer and no port.

## First calls

Four calls that touch nothing you'd regret:

1. `server_info` — process policy and capability metadata.
2. `accounts_list` and `sites_list` — configured, non-secret scope.
3. `diagnostics` — local checks, no provider calls.
4. `provider_readiness` — live access for one account.

Want the REST contract at runtime? Turn it on:

```dotenv
RANKRAT_ENABLE_OPENAPI=true
```

Then read `/openapi.json`. The committed [`openapi.json`](../openapi.json) is the
full writable contract; the runtime document drops whatever routes you disabled.

## Next steps

- [Configuration and boundaries](configuration.md)
- [Transports and deployment](transports.md)
- [Feature workflows](features.md)
- [Security](security.md)
- [Troubleshooting](troubleshooting.md)
