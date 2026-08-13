# Providers and credentials

Rankrat ships only integrations that work without a paid provider subscription.
Configure only providers you use. Store every secret in an owner-readable file
under `secrets/`; never put credential values in `.env`, JSON examples,
Compose, source, or chat. The boundary file contains container paths, account
IDs, and discovered resource inventory—not credential contents.

## Contents

- [Standard credential paths](#standard-credential-paths)
- [Google OAuth](#google-oauth)
- [PageSpeed and CrUX](#pagespeed-and-crux)
- [Bing Webmaster Tools](#bing-webmaster-tools)
- [Cloudflare](#cloudflare)
- [Microsoft Clarity](#microsoft-clarity)
- [IndexNow](#indexnow)
- [HTTP bearer](#http-bearer)
- [Live provider verification](#live-provider-verification)

## Standard credential paths

| Purpose | Host path | File contents |
| --- | --- | --- |
| Google OAuth Desktop client | `secrets/google/oauth-client.json` | Downloaded installed-client JSON |
| Google refresh record | `oauth/google.json` | Written and rotated by Rankrat |
| PageSpeed/CrUX key | `secrets/google/pagespeed-api-key` | API key only |
| Bing Webmaster | `secrets/bing/api-key` | API key only |
| Cloudflare | `secrets/cloudflare/api-token` | Scoped API token only |
| Microsoft Clarity | `secrets/clarity/api-token` | Project Data Export API token only |
| IndexNow | `secrets/indexnow/key` | IndexNow key only |
| HTTP auth | `secrets/rankrat/http-bearer-token` | Random bearer only |

Use `chmod 700` on the directories and `chmod 600` on files. The wrapper mounts
`secrets/` read-only and `oauth/` read/write because Google may rotate refresh
material.

From a checkout, `make setup` creates these paths, explains every provider-side
step, accepts secrets without echoing them, and validates the configured
account. Manual file creation remains available for automated deployments.

## Google OAuth

One OAuth Desktop client and one consent flow cover Search Console, Site
Verification, Google Indexing, GA4 Data, GA4 Admin, and Google Tag Manager
operations.

### Create the Google project

1. Create or select a project in [Google Cloud Console](https://console.cloud.google.com/).
2. Configure the [Google Auth platform](https://console.cloud.google.com/auth/overview).
3. If the app is External/Testing, add every signing-in user under
   [Audience](https://console.cloud.google.com/auth/audience). Otherwise Google
   returns `403 access_denied` before Rankrat receives a callback.
4. Enable the APIs used by your deployment:

   - [Search Console API](https://console.cloud.google.com/apis/library/searchconsole.googleapis.com)
   - [Site Verification API](https://console.cloud.google.com/apis/library/siteverification.googleapis.com)
   - [Google Analytics Data API](https://console.cloud.google.com/apis/library/analyticsdata.googleapis.com)
   - [Google Analytics Admin API](https://console.cloud.google.com/apis/library/analyticsadmin.googleapis.com)
   - [Google Tag Manager API](https://console.cloud.google.com/apis/library/tagmanager.googleapis.com)
   - [Web Search Indexing API](https://console.cloud.google.com/apis/library/indexing.googleapis.com)
   - [PageSpeed Insights API](https://console.cloud.google.com/apis/library/pagespeedonline.googleapis.com)

5. At [OAuth Clients](https://console.cloud.google.com/auth/clients), create a
   **Desktop app** client. Download the JSON as
   `secrets/google/oauth-client.json`.

Do not create a service account for Rankrat. The supported Google identity is
the user who completes this OAuth consent flow.

### Boundary and authorization

The usual Google account shape is:

```json
{
  "id": "google",
  "provider": "google",
  "credential": "/run/secrets/google/oauth-client.json",
  "oauth_token_file": "/run/oauth/google.json",
  "pagespeed_api_key_file": "/run/secrets/google/pagespeed-api-key",
  "search_console_sites": [],
  "pagespeed_sites": [],
  "ga4_properties": []
}
```

Authorize:

```sh
rankrat auth-google --print-authorization-url
```

The fixed authorization flow requests:

- `https://www.googleapis.com/auth/webmasters`
- `https://www.googleapis.com/auth/indexing`
- `https://www.googleapis.com/auth/analytics.readonly`
- `https://www.googleapis.com/auth/analytics.edit`
- `https://www.googleapis.com/auth/siteverification`
- `https://www.googleapis.com/auth/tagmanager.edit.containers`
- `https://www.googleapis.com/auth/tagmanager.delete.containers`
- `https://www.googleapis.com/auth/tagmanager.edit.containerversions`
- `https://www.googleapis.com/auth/tagmanager.publish`

It uses PKCE, a high-entropy state, an exact loopback callback, and offline
access. Rankrat persists only the refresh record required for later calls.
Re-run authorization after a scope change or if a stored grant predates a newly
enabled API.

Revoke:

```sh
rankrat revoke-google
```

### Google permissions and product limits

OAuth can only exercise permissions the signed-in Google user already has.
Rankrat discovers and can operate on every Search Console site, Analytics
account, GA4 property, and Tag Manager account visible to that user. The
resource arrays are cached inventory and URL-containment data, not a second
permission gate. OAuth does not grant ownership of a property the user cannot
already manage.

The Google Analytics Admin API cannot create a GA4 **account**. It can create a
property inside an existing account. If no Analytics account exists, create it
in [Google Analytics](https://analytics.google.com/), accept the terms, then use
`google_analytics_account_inventory` to find its numeric ID.

The Google Indexing API is restricted by Google to eligible structured-data
content; Rankrat validates supported eligibility before publishing but cannot
make an ordinary page eligible or guarantee indexing.

## PageSpeed and CrUX

PageSpeed does not use OAuth. It accepts a query-string API key. Without one,
PageSpeed analysis may work under tighter anonymous quota; CrUX History requires
the key.

1. Open [Google API Credentials](https://console.cloud.google.com/apis/credentials).
2. Choose **Create credentials → API key**.
3. Edit it and set **API restrictions → Restrict key → PageSpeed Insights API**.
4. Save only the key value:

   ```sh
   install -m 600 /dev/null secrets/google/pagespeed-api-key
   read -rsp 'PageSpeed API key: ' RANKRAT_PAGESPEED_KEY
   printf '%s' "$RANKRAT_PAGESPEED_KEY" > secrets/google/pagespeed-api-key
   unset RANKRAT_PAGESPEED_KEY
   printf '\n'
   ```

5. Use the container path in the Google account:

   ```json
   "pagespeed_api_key_file": "/run/secrets/google/pagespeed-api-key"
   ```

`pagespeed_sites` supplies the public root used to contain local Lighthouse
requests. Every requested page must be a child of the selected site.

## Bing Webmaster Tools

1. Add and verify sites in [Bing Webmaster Tools](https://www.bing.com/webmasters/).
2. Open **Settings → API Access** and create an API key.
3. Save only the key at `secrets/bing/api-key`.
4. Let Rankrat discover the account's sites, or seed known roots:

   ```json
   {
     "id": "bing",
     "provider": "bing",
     "credential": "/run/secrets/bing/api-key",
     "sites": []
   }
   ```

The Bing key sees what that Webmaster account can see. Rankrat can create and
manage sites for that account, records discovered sites for reuse, and still
applies child-URL containment within the selected site.

## Cloudflare

Cloudflare is currently the DNS ownership adapter and also supplies traffic,
cache analytics, exact cache purges, two finite cache templates, and the
currently shipped provider adapter for Rankrat-managed edge redirects.

Rankrat's Cloudflare operations work on the Free plan: the analytics report is
limited to the most recent 24-hour query window, exact URL purges are supported,
and its two cache templates fit inside the Free plan's ten Cache Rules. Existing
zone rules still count toward that Cloudflare limit.

1. Open [Cloudflare API Tokens](https://dash.cloudflare.com/profile/api-tokens).
2. Choose **Create Token → Create Custom Token**.
3. Add **Zone → Zone → Read** plus only the features you use:

   | Feature | Permission |
   | --- | --- |
   | Ownership verification | DNS → Edit |
   | Traffic/cache analytics | Analytics → Read |
   | Exact URL purge | Cache Purge → Purge |
   | Rankrat cache templates | Cache Rules → Edit; some interfaces call it Cache Settings Write |
   | Rankrat-managed edge redirects | Zone Rulesets → Edit; some interfaces call it Dynamic Redirects or Rulesets Write |

   Cloudflare changes dashboard labels over time; cross-check the current
   [API token permission reference](https://developers.cloudflare.com/fundamentals/api/reference/permissions/)
   and choose the zone-scoped permission matching the API operation above.

4. Under Zone Resources, include **All zones** when one Rankrat account must
   onboard multiple current and future domains. Do not use the Global API Key.
5. Save the token at `secrets/cloudflare/api-token`.
6. Start with empty zone inventory; Rankrat discovers visible zones:

   ```json
   {
     "id": "cloudflare",
     "provider": "cloudflare",
     "credential": "/run/secrets/cloudflare/api-token",
     "dns_zones": []
   }
   ```

Rankrat exposes provider-neutral ownership and edge-redirect operations so
future DNS and CDN adapters do not change callers. The current tool surface
uses DNS for issued ownership proofs and separate Cloudflare tools for
analytics/cache/managed-redirect operations; it does not expose arbitrary
record bodies, whole-zone purges, or arbitrary existing Cloudflare ruleset
replacement.

## Microsoft Clarity

Clarity's free Data Export API is project-scoped. Configure one Rankrat
`clarity` account for each Clarity project you want to inspect; its credential
is the project token, not a Microsoft account-wide credential.

1. Open the relevant project in [Microsoft Clarity](https://clarity.microsoft.com/).
2. Select **Settings → Data Export**.
3. Choose **Generate new API token** and store only the token at
   `secrets/clarity/api-token`.
4. Add an account whose `provider` is `clarity` and whose `credential` is
   `/run/secrets/clarity/api-token`, or let `make setup` create it from a
   hidden prompt.

Rankrat calls only Clarity's fixed project-insights endpoint. It does not
write Clarity configuration or replay session recordings. The upstream export
API limits each project to ten requests per day; use
`make test-live-clarity` deliberately rather than placing it in a frequent
polling loop. See [Microsoft's Data Export API documentation](https://learn.microsoft.com/en-us/clarity/setup-and-installation/clarity-data-export-api)
for the current upstream dimensions, metrics, and quota.

## IndexNow

IndexNow is an open push protocol, not a dashboard or credentialed reporting
account. It tells participating engines that bounded URLs changed; it does not
promise crawl, indexing, or ranking.

Create and verify a target from a checkout:

```sh
make init-indexnow INDEXNOW_TARGET_ID=example INDEXNOW_HOST=example.com
make verify-indexnow-key INDEXNOW_TARGET_ID=example
```

Publish the generated `<key>.txt` at the configured HTTPS `key_location`.
Verification requires exact contents and no redirect. See the
[IndexNow documentation](https://www.indexnow.org/documentation?hl=en).

## HTTP bearer

Generate a random token rather than reusing a provider secret:

```sh
install -m 600 /dev/null secrets/rankrat/http-bearer-token
openssl rand -base64 32 | tr -d '\n' > secrets/rankrat/http-bearer-token
```

This protects REST and Streamable HTTP MCP. It is unrelated to provider
authentication and unused by stdio.

## Live provider verification

Each test derives its account and a safe target from the selected Rankrat
profile. There is no second selector matrix to maintain. A test skips with a
specific explanation when that provider is absent or the account has no usable
site/property/zone yet.

| Target | What it verifies |
| --- | --- |
| `make test-live-google-search-console` | Site list, analytics, sitemap status, and URL inspection for the sole Google account |
| `make test-live-google-analytics` | GA4 account/property discovery, report, and realtime read |
| `make test-live-pagespeed` | PageSpeed analysis for a configured public site |
| `make test-live-google-tag-manager` | Google Tag Manager account discovery through the stored OAuth grant |
| `make test-live-cloudflare` | Free-plan-compatible 24-hour analytics for a discovered zone |
| `make test-live-clarity` | One bounded Data Export insight request for the configured Clarity project |
| `make test-live-bing` | Site list plus traffic, query/page, crawl, feed, quota, and link reads |
| `make test-live-indexnow` | One real submission only with an explicit one-command opt-in |
| `make test-live-http` | Production image plus authenticated REST and both MCP transports |

`make test-live` runs every provider target then the authenticated HTTP/MCP
transport check. Individual targets are faster while configuring one provider.

Use `RANKRAT_PROFILE=/absolute/profile make test-live-<provider>` for a
non-default profile. The IndexNow test is the destructive exception: it sends
nothing unless `RANKRAT_RUN_LIVE_INDEXNOW_SUBMISSION=true` is present on that
one command. Use [Troubleshooting](troubleshooting.md) if readiness and a deep
live test disagree.
