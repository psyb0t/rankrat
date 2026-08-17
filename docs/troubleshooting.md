# Troubleshooting

Start at the smallest layer that can fail and work up: local paths → boundary
parsing → credential readiness → one provider live test → production transport
test. Don't debug OAuth when the boundary file won't parse.

```sh
rankrat setup
```

From a checkout, `make setup` runs the same guided profile setup. It validates
each configured provider account — no separate live-test selector file needed.

## Contents

- [Startup says configuration is invalid](#startup-says-configuration-is-invalid)
- [A required config, secret, OAuth, or state path is missing](#a-required-config-secret-oauth-or-state-path-is-missing)
- [Boundary file permission denied inside Docker](#boundary-file-permission-denied-inside-docker)
- [Google says the app is unverified or testing](#google-says-the-app-is-unverified-or-testing)
- [Google authorization callback was not accepted](#google-authorization-callback-was-not-accepted)
- [OAuth stored, but Google calls fail](#oauth-stored-but-google-calls-fail)
- [Google Tag Manager writes fail after authorization](#google-tag-manager-writes-fail-after-authorization)
- [GA4 account/property cannot be found](#ga4-accountproperty-cannot-be-found)
- [PageSpeed fails while other Google tools work](#pagespeed-fails-while-other-google-tools-work)
- [Google says a sitemap could not be read](#google-says-a-sitemap-could-not-be-read)
- [Bing returns no data or cannot access a site](#bing-returns-no-data-or-cannot-access-a-site)
- [Ownership verify reports a record it just created as not propagated](#ownership-verify-reports-a-record-it-just-created-as-not-propagated)
- [Cloudflare readiness or writes fail](#cloudflare-readiness-or-writes-fail)
- [IndexNow verification fails](#indexnow-verification-fails)
- [HTTP returns 401](#http-returns-401)
- [REST write route or MCP write tool is missing](#rest-write-route-or-mcp-write-tool-is-missing)
- [Runtime OpenAPI is missing](#runtime-openapi-is-missing)
- [Lighthouse returns unavailable](#lighthouse-returns-unavailable)
- [Docker build fails with registry 401](#docker-build-fails-with-registry-401)
- [Provider readiness passes but a report fails](#provider-readiness-passes-but-a-report-fails)
- [Collect useful diagnostics safely](#collect-useful-diagnostics-safely)

## Startup says configuration is invalid

Check, in order:

- `config/boundaries.json` is valid JSON;
- an empty document is fine only before guided setup has added a provider;
- no example account is left behind with a missing credential;
- provider-specific fields aren't mixed;
- credential/OAuth/key paths are absolute container paths;
- account/target/resource IDs are unique;
- public roots are HTTPS with no query, fragment, credentials, or nonstandard
  port;
- every `RANKRAT_*` name matches `.env.example` — an unknown or misspelled
  environment variable is silently ignored, not honored;
- `RANKRAT_READ_ONLY` is exactly `true` or `false`.

Use [`boundaries.json.example`](../config/boundaries.json.example) and
[Configuration](configuration.md) as the field reference.

## A required config, secret, OAuth, or state path is missing

The wrapper needs a boundary file plus real `secrets/`, `oauth/`, and `state/`
directories under one profile. Don't hand-build or hand-repair that tree — run
`rankrat setup`, or `rankrat --data-dir /absolute/profile setup` for a separate
profile. Setup creates only the missing owner-only paths and never overwrites an
existing secret or boundary document.

The profile must be absolute and canonical. Don't swap the profile, a required
child, or the boundary file for a symlink. Writable config/state paths must be
owned by the current user and owner-only.

## Boundary file permission denied inside Docker

Mount `config/` at `/run/config` — the directory, not the file. A single-file
bind leaves the image's baked `/run/config` ownership in place, and the host UID
may not be able to traverse it.

Use the published wrapper or the plain command in
[Transports and deployment](transports.md#plain-docker-stdio-mcp).

## Google says the app is unverified or testing

For an External OAuth app in Testing status, add the signing-in Google user at
[Google Auth Audience](https://console.cloud.google.com/auth/audience). The
client is meant for your own deployment; that user stays an approved tester
until the app's publishing status changes.

## Google authorization callback was not accepted

Keep the authorization command alive until the browser redirects to the exact
loopback callback — kill it early and the handshake never completes. Confirm:

- the OAuth client type is Desktop app;
- the printed URL is from the current command, not a stale attempt;
- callback port `49152` is free, or set `RANKRAT_OAUTH_CALLBACK_PORT` (the
  wrapper publishes that exact port, so it has to be free on the host);
- no proxy or browser extension rewrote state, issuer, code, or callback;
- the user approved instead of canceling.

Authorization failures write a bounded `google-auth.log` under OAuth storage.
Treat it as sensitive local diagnostic state — do not publish it. It records the
failing stage and a finite failure category without dragging OAuth tokens or raw
upstream responses into normal service logs. A rejected callback also carries a
fixed `reason` such as `callback_state_rejected`; it never contains the callback
URL, OAuth state, authorization code, or tokens.

## OAuth stored, but Google calls fail

The required APIs have to be enabled in the same Google Cloud project as the
Desktop OAuth client. Open the exact API link, select that project in the top
bar, and click **Enable**. A button labelled **Manage** means it's already on.

- Site ownership verification reports Google `accessNotConfigured`: enable
  [Site Verification API](https://console.cloud.google.com/apis/library/siteverification.googleapis.com).
- Search Console tools fail: enable
  [Search Console API](https://console.cloud.google.com/apis/library/searchconsole.googleapis.com).
- Analytics tools fail: enable both
  [Google Analytics Data API](https://console.cloud.google.com/apis/library/analyticsdata.googleapis.com)
  and [Google Analytics Admin API](https://console.cloud.google.com/apis/library/analyticsadmin.googleapis.com).
- Tag Manager tools fail: enable
  [Google Tag Manager API](https://console.cloud.google.com/apis/library/tagmanager.googleapis.com).

Enabling an API isn't instant — wait a few minutes, then rerun the failing live
check. Re-authorize only after enabling a newly required OAuth scope. Last,
confirm the signed-in user can actually see the exact Search Console/GA4
resources.

Use:

```sh
make test-live-google-search-console
make test-live-google-analytics
```

`403` usually means upstream user/property permission or an API that isn't
enabled; `AUTHENTICATION` usually means missing, invalid, or insufficient OAuth
state.

## Google Tag Manager writes fail after authorization

Enable the [Google Tag Manager API](https://console.cloud.google.com/apis/library/tagmanager.googleapis.com)
in the OAuth client's project, then authorize again. A pre-GTM grant is missing
the container edit/delete, version-edit, and publish scopes the typed GTM writes
need:

```sh
rankrat auth-google --print-authorization-url
make test-live-google-tag-manager
```

The signed-in user also needs real access to the intended Tag Manager account
and container. `google_tag_manager_accounts_list` shows what the grant can see;
it does not conjure access to an account the user can't manage.

## GA4 account/property cannot be found

Call `google_analytics_account_inventory` — the property may live under an
Analytics account you didn't expect. Call `google_analytics_data_streams` and
compare its `G-` ID against the site tag; a correctly installed tag can be
feeding a different property.

Rankrat cannot create a GA4 account. Create one in
[Google Analytics](https://analytics.google.com/), accept the terms, then use
its numeric account ID for onboarding.

## PageSpeed fails while other Google tools work

PageSpeed doesn't use OAuth — that's the catch. Configure a PageSpeed Insights
API key or live with tighter anonymous quota. CrUX History requires the key.
Confirm the target is inside `pagespeed_sites` and the key is restricted to the
enabled PageSpeed API.

```sh
make test-live-pagespeed
```

## Google says a sitemap could not be read

A successful submission means the API accepted the sitemap URL — not that Google
fetched it. Check the exact public sitemap with a normal unauthenticated client:

- direct HTTPS returns `200`;
- no login, cookie challenge, bot challenge, or redirect loop;
- content is valid XML with an XML content type;
- every nested sitemap is publicly reachable;
- robots/firewall/CDN rules let Googlebot through;
- canonical host/scheme match the Search Console property;
- the sitemap URL shows up in `google_sitemap_get`, and you poll its
  warning/error counts after the processing delay.

For a sitemap index, check each child on its own. Rankrat exposes status for
polling; it can't make Google fetch on command.

## Bing returns no data or cannot access a site

Verify the site in Bing Webmaster Tools and regenerate/check the account API
key. Call `site_ownership_check` with the selected `bing_account_id` to confirm
the exact site is verified — a site can be visible to the account yet unverified,
and Bing will reject sitemap writes on it. Then use `bing_feeds`,
`bing_url_information`, and `bing_crawl_issues` to tell sitemap, URL, and crawl
state apart. The `sites` array is persisted inventory, not a second permission
list.

```sh
make test-live-bing
```

## Ownership verify reports a record it just created as not propagated

`site_ownership_verify` creates the proof record, then checks public DNS for it
in the same call. A resolver asked for that exact name a moment earlier can hold
a cached negative answer from before the record existed, so the first call often
returns `propagated: false` and stops before it can redeem the proof. That is
ordinary DNS negative caching, not a failure — the record was still created.

Confirm the record is actually public, then call again:

```sh
dig +short CNAME <token>.example.com @1.1.1.1
```

Once it resolves on public resolvers and the negative cache has expired, a
repeated `site_ownership_verify` sees it propagated and redeems the proof. Poll
`site_ownership_check` until `complete` is true, and leave the record in place —
providers recheck it.

## Cloudflare readiness or writes fail

Confirm:

- the token has Zone Read across the intended account zones;
- the selected zone's 32-character `provider_zone_id` in the boundary matches a
  zone that token can actually read;
- the feature permission exists — DNS Edit, Analytics Read, Cache Purge, or
  Cache Rules Edit, as appropriate;
- the account ID in the request selects the intended Cloudflare credential.

Rankrat refuses arbitrary records, whole-zone purge, unknown templates, and
ambiguous duplicate managed-rule markers even when Cloudflare itself would allow
them. That's deliberate — don't file it as a bug.

```sh
make test-live-cloudflare
```

## IndexNow verification fails

Confirm the configured `key_location`:

- uses direct HTTPS on the configured host;
- returns `200` with no redirect;
- contains exactly the key, with no HTML or newline transformation;
- is public — no authentication or challenge;
- matches the local key file the target selects.

```sh
make verify-indexnow-key INDEXNOW_TARGET_ID=example
```

This checks public key deployment only. Live submission needs separate writable
and submission opt-ins.

## HTTP returns 401

Read the token file without printing it into shared logs, and configure the
client to send `Authorization: Bearer <token>`. Make sure the service and the
client point at the same file/secret. MCP Streamable HTTP uses the same bearer
as REST.

Stdio never uses the bearer. `/healthz` stays public for liveness probes;
`/ready` and every other HTTP route require the bearer once one is configured.

## REST write route or MCP write tool is missing

Expected in read-only mode — nothing's broken. Restart with
`RANKRAT_READ_ONLY=false`. Runtime `/openapi.json` and MCP `tools/list` reflect
whichever you chose.

## Runtime OpenAPI is missing

Set `RANKRAT_ENABLE_OPENAPI=true` before starting HTTP. The committed
[`openapi.json`](../openapi.json) is available without enabling runtime docs at
all.

## Lighthouse returns unavailable

Check:

- the worker is running and healthy;
- both services share `/run/lighthouse/lighthouse.sock`;
- socket volume ownership matches the configured UID/GID;
- `RANKRAT_LIGHTHOUSE_WORKER_SOCKET` is not empty;
- the requested page is within `pagespeed_sites`.

Busy, timeout, final-URL, and private-address failures are intentional finite
errors, not glitches. See [Lighthouse](lighthouse.md).

## Docker build fails with registry 401

A stale cached Docker Hub login can make anonymous public base-image pulls fail
with `401 Unauthorized`. Inspect your local Docker credential setup, log in with
a valid account or remove just the stale registry credential, then retry. Do not
weaken digest pinning or repoint Dockerfiles at random mirrors as a first
move — that trades a login glitch for a supply-chain hole.

Rankrat already resolves selected bases/tools through reviewed public mirrors; a
credential error can still hit an image whose registry is Docker Hub.

## Provider readiness passes but a report fails

Readiness proves one minimal account call — not every resource, date range,
quota, or product feature. Run the provider-specific live target against the same
profile, then inspect:

- provider inventory can discover the resource;
- the upstream account can actually access it;
- date range and pagination limits are valid;
- free-tier rate limits and quotas allow the request;
- the requested feature is enabled for that provider account;
- the provider even has data for that interval.

## Collect useful diagnostics safely

Record:

- Rankrat image/version;
- tool/operation name;
- the finite error category;
- account/resource IDs that are safe to disclose;
- whether stdio, HTTP MCP, or REST was used;
- relevant configuration field names — never secret values;
- whether `diagnostics`, `provider_readiness`, or a mocked test reproduces it.

Never paste bearer tokens, OAuth records, provider keys, downloaded OAuth client
secrets, or raw `google-auth.log` into a public issue.
