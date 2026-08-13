# Troubleshooting

Start with the smallest layer that can fail: local paths → boundary parsing →
credential readiness → one provider live test → production transport test.

```sh
rankrat setup
```

From a checkout, `make setup` runs the same guided profile setup. It validates
each configured provider account without a second live-test selector file.

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

Check:

- `config/boundaries.json` is valid JSON;
- an empty document is expected only before guided setup has added a provider;
- no example account remains with a missing credential;
- provider-specific fields are not mixed;
- credential/OAuth/key paths are absolute container paths;
- account/target/resource IDs are unique;
- public roots are HTTPS with no query, fragment, credentials, or nonstandard
  port;
- every intended `RANKRAT_*` name matches `.env.example` (unknown/misspelled
  environment variables are ignored);
- `RANKRAT_READ_ONLY` is exactly `true` or `false`.

Use [`boundaries.json.example`](../config/boundaries.json.example) and
[Configuration](configuration.md) as the field reference.

## A required config, secret, OAuth, or state path is missing

The wrapper requires a boundary file plus real `secrets/`, `oauth/`, and
`state/` directories beneath one profile. Do not create or repair that tree by
hand: run `rankrat setup`, or `rankrat --data-dir /absolute/profile setup` for
a separate profile. Setup creates only missing owner-only paths and never
replaces an existing secret or boundary document.

The profile must be absolute and canonical. Do not replace the profile, a
required child, or the boundary file with a symlink. Writable config/state
paths must be owned by the current user and owner-only.

## Boundary file permission denied inside Docker

Mount `config/` at `/run/config`, not the file directly. A single-file bind
leaves the image's baked `/run/config` ownership in place and may prevent the
host UID from traversing it.

Use the published wrapper or the plain command in
[Transports and deployment](transports.md#plain-docker-stdio-mcp).

## Google says the app is unverified or testing

For an External OAuth app in Testing status, add the signing-in Google user at
[Google Auth Audience](https://console.cloud.google.com/auth/audience). The
client is intended for the operator's own deployment; the user must be an
approved tester until the Google app's publishing status changes.

## Google authorization callback was not accepted

Keep the authorization command alive until the browser redirects to the exact
loopback callback. Confirm:

- the OAuth client type is Desktop app;
- the printed URL is from the current command, not an older attempt;
- callback port `49152` is free, or set `RANKRAT_OAUTH_CALLBACK_PORT`;
- no proxy/browser extension rewrote state, issuer, code, or callback;
- the user approved rather than canceled.

Authorization failures write a bounded `google-auth.log` under OAuth storage.
Treat it as sensitive local diagnostic state; do not publish it. It records the
failing stage and finite failure category without making OAuth tokens or raw
upstream responses part of normal service logs.

## OAuth stored, but Google calls fail

Check the required APIs are enabled in the same Google Cloud project as the
client. Re-run authorization after enabling new APIs/scopes. Then confirm the
signed-in user can see the exact Search Console/GA4 resources.

Use:

```sh
make test-live-google-search-console
make test-live-google-analytics
```

`403` usually means upstream user/property permission or an API not enabled;
`AUTHENTICATION` usually means missing/invalid/insufficient OAuth state.

## Google Tag Manager writes fail after authorization

Enable the [Google Tag Manager API](https://console.cloud.google.com/apis/library/tagmanager.googleapis.com)
in the OAuth client's project, then authorize again. A pre-GTM grant lacks the
container edit/delete, version-edit, and publish scopes used by typed GTM
writes:

```sh
rankrat auth-google --print-authorization-url
make test-live-google-tag-manager
```

The signed-in user also needs sufficient access to the intended Tag Manager
account and container. `google_tag_manager_accounts_list` confirms what the
grant can see; it does not create access to an account the user cannot manage.

## GA4 account/property cannot be found

Call `google_analytics_account_inventory`; properties may live under an
unexpected Analytics account. Call `google_analytics_data_streams` and compare
its `G-` ID with the site tag. A correctly installed tag can send to a different
property.

Rankrat cannot create a GA4 account. Create one in
[Google Analytics](https://analytics.google.com/), accept terms, then use its
numeric account ID for onboarding.

## PageSpeed fails while other Google tools work

PageSpeed does not use OAuth. Configure a PageSpeed Insights API key or accept
tighter anonymous quota. CrUX History requires the key. Confirm the target is
inside `pagespeed_sites` and the key is restricted to the enabled PageSpeed API.

```sh
make test-live-pagespeed
```

## Google says a sitemap could not be read

A successful submission means the API accepted the sitemap URL, not that Google
fetched it. Check the exact public sitemap with a normal unauthenticated client:

- direct HTTPS returns `200`;
- no login, cookie challenge, bot challenge, or redirect loop;
- content is valid XML with an XML content type;
- every nested sitemap is publicly reachable;
- robots/firewall/CDN rules permit Googlebot;
- canonical host/scheme match the Search Console property;
- the sitemap URL appears in `google_sitemap_get` and its warning/error counts
  are polled after processing delay.

For a sitemap index, check each child independently. Rankrat exposes status for
polling; it cannot make Google fetch immediately.

## Bing returns no data or cannot access a site

Verify the site in Bing Webmaster Tools and regenerate/check the account API
key. Use `bing_site_inventory` to confirm the credential can see the site, then
use `bing_url_information`, `bing_feeds`, and `bing_crawl_issues` to distinguish
site visibility, sitemap, and URL status. The `sites` array is persisted
inventory, not a second permission list.

```sh
make test-live-bing
```

## Cloudflare readiness or writes fail

Confirm:

- token has Zone Read across the intended account zones;
- `dns_zone_inventory` can discover the selected zone and its 32-character
  provider zone ID;
- feature permission exists: DNS Edit, Analytics Read, Cache Purge, or Cache
  Rules Edit as appropriate;
- account ID in the request selects the intended Cloudflare credential.

Rankrat will refuse arbitrary records, whole-zone purge, unknown templates, and
ambiguous duplicate managed-rule markers even if Cloudflare would allow them.

```sh
make test-live-cloudflare
```

## IndexNow verification fails

Confirm the configured `key_location`:

- uses direct HTTPS on the configured host;
- returns `200` without redirect;
- contains exactly the key and no HTML/newline transformation;
- is public without authentication/challenge;
- matches the local key file selected by the target.

```sh
make verify-indexnow-key INDEXNOW_TARGET_ID=example
```

This verifies only public key deployment. Live submission requires separate
writable and submission opt-ins.

## HTTP returns 401

Read the token file without printing it to shared logs and configure the client
to send `Authorization: Bearer <token>`. Ensure the service and client reference
the same file/secret. MCP Streamable HTTP uses the same bearer as REST.

Stdio never uses the bearer. `/healthz` remains public for liveness probes;
`/ready` and every other HTTP route require the bearer when one is configured.

## REST write route or MCP write tool is missing

That is expected in read-only mode. Restart with `RANKRAT_READ_ONLY=false`.
Runtime `/openapi.json` and MCP `tools/list` reflect that choice.

## Runtime OpenAPI is missing

Set `RANKRAT_ENABLE_OPENAPI=true` before starting HTTP. The committed
[`openapi.json`](../openapi.json) is available without enabling runtime docs.

## Lighthouse returns unavailable

Check:

- worker is running and healthy;
- both services share `/run/lighthouse/lighthouse.sock`;
- socket volume ownership matches the configured UID/GID;
- `RANKRAT_LIGHTHOUSE_WORKER_SOCKET` is not empty;
- requested page is within `pagespeed_sites`.

Busy, timeout, final-URL, and private-address failures are intentional finite
errors. See [Lighthouse](lighthouse.md).

## Docker build fails with registry 401

An invalid cached Docker Hub login can cause anonymous public base-image pulls
to fail with `401 Unauthorized`. Inspect your local Docker credential setup,
log in with a valid account or remove only the stale registry credential, then
retry. Do not weaken digest pinning or rewrite Dockerfiles to random mirrors as
the first response.

Rankrat already resolves selected bases/tools through reviewed public mirrors;
a credential error may still affect an image whose registry is Docker Hub.

## Provider readiness passes but a report fails

Readiness proves a minimal account call, not every resource, date range, quota,
or product feature. Run the provider-specific live target against the same
profile, then inspect:

- provider inventory can discover the resource;
- the upstream account can access it;
- date range and pagination limits are valid;
- free-tier rate limits and quotas allow the request;
- requested feature is enabled for the provider account;
- provider has data for that interval.

## Collect useful diagnostics safely

Record:

- Rankrat image/version;
- tool/operation name;
- finite error category;
- account/resource IDs that are safe to disclose;
- whether stdio, HTTP MCP, or REST was used;
- relevant configuration field names, never values of secrets;
- reproducibility with `diagnostics`, `provider_readiness`, or a mocked test.

Never paste bearer tokens, OAuth records, provider keys, downloaded OAuth client
secrets, or raw `google-auth.log` into a public issue.
