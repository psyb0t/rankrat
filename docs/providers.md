# Providers and credentials

Configure only providers you use. Store every secret in an owner-readable file
under `secrets/`; never put credential values in `.env`, JSON examples,
Compose, source, or chat. The boundary file contains container paths, account
IDs, and allowed resources—not credential contents.

## Contents

- [Standard credential paths](#standard-credential-paths)
- [Google OAuth](#google-oauth)
- [PageSpeed and CrUX](#pagespeed-and-crux)
- [Bing Webmaster Tools](#bing-webmaster-tools)
- [Cloudflare](#cloudflare)
- [Commercial backlink providers](#commercial-backlink-providers)
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
| Ahrefs | `secrets/ahrefs/api-token` | API token only |
| Majestic | `secrets/majestic/api-key` | API key only |
| Moz | `secrets/moz/credentials` | `ACCESS_ID:SECRET` |
| Semrush | `secrets/semrush/api-key` | API key only |
| DataForSEO | `secrets/dataforseo/credentials` | `LOGIN:PASSWORD` |
| IndexNow | `secrets/indexnow/key` | IndexNow key only |
| HTTP auth | `secrets/rankrat/http-bearer-token` | Random bearer only |

Use `chmod 700` on the directories and `chmod 600` on files. The wrapper mounts
`secrets/` read-only and `oauth/` read/write because Google may rotate refresh
material.

## Google OAuth

One OAuth Desktop client and one consent flow cover Search Console, Site
Verification, Google Indexing, GA4 Data, and GA4 Admin operations.

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
  "google_account_discovery": true,
  "search_console_sites": ["sc-domain:example.com"],
  "pagespeed_sites": ["https://example.com/"],
  "ga4_properties": ["123456789"]
}
```

Authorize:

```sh
rankrat.sh auth-google --account-id google --print-authorization-url
```

The fixed authorization flow requests:

- `https://www.googleapis.com/auth/webmasters`
- `https://www.googleapis.com/auth/indexing`
- `https://www.googleapis.com/auth/analytics.readonly`
- `https://www.googleapis.com/auth/analytics.edit`
- `https://www.googleapis.com/auth/siteverification`

It uses PKCE, a high-entropy state, an exact loopback callback, and offline
access. Rankrat persists only the refresh record required for later calls.
Re-run authorization after a scope change or if a stored grant predates a newly
enabled API.

Revoke:

```sh
rankrat.sh revoke-google --account-id google
```

### Google permissions and product limits

OAuth can only exercise permissions the signed-in Google user already has.
Search Console properties and GA4 properties not visible to that user remain
unavailable. `google_account_discovery=true` authorizes read-only discovery and
targeting of every Search Console site and GA4 property visible to that user,
including resources not explicitly listed in the boundary. Set it to `false`
for strict list-only reads. It never grants ownership and does not broaden
Search Console writes or GA4 property writes. If writable mode is separately
enabled, the flag is also the explicit authorization gate for renaming an
OAuth-visible GA4 account by numeric ID.

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

`pagespeed_sites` is also the authority for local Lighthouse requests. Every
requested page must be a child of a configured site.

## Bing Webmaster Tools

1. Add and verify sites in [Bing Webmaster Tools](https://www.bing.com/webmasters/).
2. Open **Settings → API Access** and create an API key.
3. Save only the key at `secrets/bing/api-key`.
4. Configure exact HTTPS roots:

   ```json
   {
     "id": "bing",
     "provider": "bing",
     "credential": "/run/secrets/bing/api-key",
     "sites": ["https://example.com/"]
   }
   ```

The Bing key sees what that Webmaster account can see. Rankrat still applies
the explicit `sites` allow-list and child-URL containment.

## Cloudflare

Cloudflare is currently the DNS ownership adapter and also supplies traffic,
cache analytics, exact cache purges, and two finite cache templates.

1. Open [Cloudflare API Tokens](https://dash.cloudflare.com/profile/api-tokens).
2. Choose **Create Token → Create Custom Token**.
3. Add **Zone → Zone → Read** plus only the features you use:

   | Feature | Permission |
   | --- | --- |
   | Ownership verification | DNS → Edit |
   | Traffic/cache analytics | Analytics → Read |
   | Exact URL purge | Cache Purge → Purge |
   | Rankrat cache templates | Cache Rules → Edit; some interfaces call it Cache Settings Write |

   Cloudflare changes dashboard labels over time; cross-check the current
   [API token permission reference](https://developers.cloudflare.com/fundamentals/api/reference/permissions/)
   and choose the zone-scoped permission matching the API operation above.

4. Under Zone Resources, include only zones Rankrat may manage. Do not use the
   Global API Key.
5. Save the token at `secrets/cloudflare/api-token`.
6. Copy each 32-character Zone ID from the zone Overview into the boundary:

   ```json
   {
     "id": "cloudflare",
     "provider": "cloudflare",
     "credential": "/run/secrets/cloudflare/api-token",
     "dns_zones": [
       {
         "provider_zone_id": "00000000000000000000000000000000",
         "name": "example.com"
       }
     ]
   }
   ```

Replace the all-zero ID. Rankrat exposes no generic DNS CRUD, arbitrary rule
body, or whole-zone purge even if the token could perform them. Public ownership
operations are provider-neutral so future DNS adapters need not change callers.

## Commercial backlink providers

Every adapter needs its own paid provider account and exact allowed targets.
Rankrat does not substitute one provider for another.

Credential consoles:

- [Ahrefs API](https://app.ahrefs.com/api)
- [Majestic API](https://majestic.com/account/api)
- [Moz API](https://moz.com/products/api)
- [Semrush API](https://www.semrush.com/api-use/)
- [DataForSEO API](https://app.dataforseo.com/api-access)

Example:

```json
{
  "id": "ahrefs",
  "provider": "ahrefs",
  "credential": "/run/secrets/ahrefs/api-token",
  "backlink_targets": ["https://example.com/"]
}
```

Use `ACCESS_ID:SECRET` for Moz and `LOGIN:PASSWORD` for DataForSEO. Ahrefs,
Majestic, and Semrush files contain one token/key. Readiness performs a
one-result query and may consume paid units.

Backlink reports have one whole-operation deadline and a shared ceiling of 20
provider requests. Aggregates reject duplicate identical sources, return typed
source failures alongside successful evidence, and fail completely only when
all sources fail.

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

Configure selectors in `.env`; leave unused ones blank.

| Target | Required selectors |
| --- | --- |
| `make test-live-google-search-console` | Google account, site; optional sitemap, inspection URL, indexing URL |
| `make test-live-google-analytics` | Google account and GA4 property; optional funnel events |
| `make test-live-pagespeed` | PageSpeed account/site and target URL |
| `make test-live-cloudflare` | Cloudflare account and zone ID |
| `make test-live-bing` | Bing account/site; optional query, page, country, language |
| `make test-live-indexnow` | Target ID, public URL, writable mode, and explicit submission opt-in |
| `make test-live-http` | Configured accounts plus production image, bearer, and both HTTP transports |

`make test-live` runs every provider target then the authenticated HTTP/MCP
transport check. Individual targets are faster while configuring one provider.

Use [Troubleshooting](troubleshooting.md) if readiness and a deep live test
disagree.
