# Troubleshooting

Start with the smallest layer that can fail: local paths → boundary parsing →
credential readiness → one provider live test → production transport test.

```sh
rankrat.sh setup
```

From a checkout, `make setup` adds permission normalization, provider-specific
live selectors, and production HTTP/MCP checks.

## Contents

- [Startup says configuration is invalid](#startup-says-configuration-is-invalid)
- [A required config, secret, OAuth, or state path is missing](#a-required-config-secret-oauth-or-state-path-is-missing)
- [Boundary file permission denied inside Docker](#boundary-file-permission-denied-inside-docker)
- [Google says the app is unverified or testing](#google-says-the-app-is-unverified-or-testing)
- [Google authorization callback was not accepted](#google-authorization-callback-was-not-accepted)
- [OAuth stored, but Google calls fail](#oauth-stored-but-google-calls-fail)
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
- at least one account or IndexNow target exists;
- no example account remains with a missing credential;
- provider-specific fields are not mixed;
- credential/OAuth/key paths are absolute container paths;
- account/target/resource IDs are unique;
- public roots are HTTPS with no query, fragment, credentials, or nonstandard
  port;
- every intended `RANKRAT_*` name matches `.env.example` (unknown/misspelled
  environment variables are ignored);
- unbounded/agent-onboarding are not combined with read-only mode.

Use [`boundaries.json.example`](../config/boundaries.json.example) and
[Configuration](configuration.md) as the field reference.

## A required config, secret, OAuth, or state path is missing

The wrapper requires a boundary file plus real `secrets/`, `oauth/`, and
`state/` directories. Create them in the current deployment directory:

```sh
mkdir -p config oauth state secrets
chmod 700 config oauth state secrets
```

From a checkout, `make init-config` creates the full tree without overwriting
existing files and generates the HTTP bearer if missing.

Do not replace a required directory with a symlink. Writable config/state paths
must be owned by the current user and owner-only.

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

Verify the site in Bing Webmaster Tools, regenerate/check the API key, and match
the exact HTTPS root in `sites`. Use `bing_url_information`, `bing_feeds`, and
`bing_crawl_issues` to distinguish site visibility, sitemap, and URL status.

```sh
make test-live-bing
```

## Cloudflare readiness or writes fail

Confirm:

- token has Zone Read;
- selected zone is included in token resources;
- boundary `provider_zone_id` is the real 32-character zone ID;
- feature permission exists: DNS Edit, Analytics Read, Cache Purge, or Cache
  Rules Edit as appropriate;
- account ID in the request selects the Cloudflare boundary account.

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
`site_onboarding_submit` additionally requires
`RANKRAT_ALLOW_AGENT_ONBOARDING=true`. Runtime `/openapi.json` and MCP
`tools/list` reflect those choices.

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

Readiness proves a minimal bounded call for the account, not every resource,
date range, quota, product feature, or paid plan. Run the provider-specific live
target with exact selectors, then inspect:

- resource is in the boundary;
- upstream account can access it;
- date range and pagination limits are valid;
- quota/paid units remain;
- requested feature exists on the provider plan;
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
