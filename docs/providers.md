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
operations. Do this once in the Google account that should own every site,
Analytics property, and Tag Manager container Rankrat manages.

### Create exactly what Rankrat needs

1. Open [Create a Google Cloud project](https://console.cloud.google.com/projectcreate).
   Enter `rankrat` as the project name and click **Create**. Wait for the new
   project to become selected in the top bar.
2. Open [Google Auth Platform](https://console.cloud.google.com/auth/overview).
   If Google shows **Get started**, click it. In **Branding**, use `rankrat` as
   the app name and choose your email for the support contact. Save it.
3. Open [Audience](https://console.cloud.google.com/auth/audience). Select
   **External**, then use **Add users** to add the same Google email that will
   authorize Rankrat. This lets you make the first authorization while the app
   is in testing. If this email is not a test user, Google stops OAuth with
   `403 access_denied`.
4. After the first authorization succeeds, return to
   [Audience](https://console.cloud.google.com/auth/audience). Under
   **Publishing status**, click **Publish app** (or **In production**) and
   confirm it. Do this even for a one-person installation: External apps left
   in **Testing** have refresh tokens that expire after seven days. An
   unverified production app can still be used by its own operator; Google
   shows an unverified-app warning. Verification is only necessary before
   distributing Rankrat to other people.
5. Open each link below and click **Enable** once. A page that says **Manage**
   is already enabled.

   - [Search Console API](https://console.cloud.google.com/apis/library/searchconsole.googleapis.com)
   - [Site Verification API](https://console.cloud.google.com/apis/library/siteverification.googleapis.com)
   - [Google Analytics Data API](https://console.cloud.google.com/apis/library/analyticsdata.googleapis.com)
   - [Google Analytics Admin API](https://console.cloud.google.com/apis/library/analyticsadmin.googleapis.com)
   - [Google Tag Manager API](https://console.cloud.google.com/apis/library/tagmanager.googleapis.com)
   - [Web Search Indexing API](https://console.cloud.google.com/apis/library/indexing.googleapis.com)
   - [PageSpeed Insights API](https://console.cloud.google.com/apis/library/pagespeedonline.googleapis.com)
   - [Chrome UX Report API](https://console.cloud.google.com/apis/library/chromeuxreport.googleapis.com)

6. Open [OAuth Clients](https://console.cloud.google.com/auth/clients). Click
   **Create client**, choose **Desktop app**, name it `rankrat`, then click
   **Create**. Click **Download JSON** and keep the downloaded file. Do not
   create a Web client or a service account.
7. Run setup with the downloaded JSON's host path, then choose `google` when
   setup asks for providers:

   ```sh
   rankrat setup --google-oauth-client-file "/absolute/path/to/client_secret_...json"
   ```

   From a checkout, use the same one-command flow:

   ```sh
   RANKRAT_GOOGLE_OAUTH_CLIENT_FILE="$HOME/Downloads/client_secret_...json" make setup
   ```

   Rankrat reads that host file through a temporary read-only mount, validates
   it, then copies it into its owner-only secret directory. Do not manually move
   it or paste multi-line JSON into the terminal. Setup then opens the one
   browser OAuth consent flow itself.

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

PageSpeed does not use OAuth. An API key increases PageSpeed quota and is
required for CrUX History. `rankrat setup` asks for this key directly after the
Google client file; it stores it safely, so do not create any secret files by
hand.

1. Open [Google API Credentials](https://console.cloud.google.com/apis/credentials).
2. Click **Create credentials → API key**.
3. Open the new key's details. Under **API restrictions**, choose **Restrict
   key**, then select both **PageSpeed Insights API** and **Chrome UX Report
   API**. Click **Save**.
4. Copy the key once. When Rankrat asks for the PageSpeed Insights API key,
   paste it; leave the prompt blank only when you deliberately want to skip
   PageSpeed quota identity and CrUX History.

`pagespeed_sites` supplies the public root used to contain local Lighthouse
requests. Every requested page must be a child of the selected site.

## Bing Webmaster Tools

1. Open [Bing Webmaster Tools](https://www.bing.com/webmasters/home), sign in,
   and click **Add a Site**. Enter one website you own and finish Bing's
   verification flow. You need one verified site before Bing lets the account
   create its API key.
2. Click the gear in the top-right corner, then **Settings → API Access**. If
   Bing shows terms on the first visit, accept them. Click **API Key → Generate
   API Key**, then copy the value shown.
3. Run `rankrat setup` (or `make setup`), choose `bing`, and paste that key.
   Bing creates one key per user, not per site: the same key covers every
   verified site in that Webmaster account and sites Rankrat later adds there.
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

Use a **User API Token**, not Cloudflare's separate **Account API Token**
screen. Zone DNS record operations are granted through the user-token flow.

1. Open [Cloudflare User API Tokens](https://dash.cloudflare.com/profile/api-tokens).
2. Click **Create Token → Create Custom Token** and name the token `rankrat`.
3. Add this complete permission set. It covers every currently shipped
   Cloudflare feature, so a user never has to return to the dashboard later:

   | Feature | Permission to add |
   | --- | --- |
   | Discover zones | **Zone → Zone → Read** |
   | Google/Bing DNS ownership verification | **Zone → DNS → Edit** |
   | Traffic/cache analytics | **Zone → Analytics → Read** |
   | Exact URL purge | **Zone → Cache Purge → Purge** |
   | Rankrat cache templates | **Zone → Cache Rules → Edit** |
   | Rankrat-managed edge redirects | **Zone → Single Redirect → Edit** |
   | Cache-rule API support | **Account → Account Rulesets → Edit** and **Account → Account Filter Lists → Edit** |

4. Under **Zone Resources**, choose **Include → All zones**. Under **Account
   Resources**, choose **Include → All accounts**. Do not use the Global API
   Key or the separate Account API Token screen.
5. Select **Continue to summary → Create Token**. Copy the token value shown
   once and paste it into Rankrat's hidden setup prompt.
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

Ownership proof records are DNS-only and untagged. Rankrat does not consume a
Cloudflare DNS tag quota merely to mark a provider-issued verification record.

Provider readiness can prove that the token reaches Cloudflare and can discover
zones. It deliberately does not create a throwaway DNS record to prove write
permission, so a readiness success does not replace the required **Zone → DNS
→ Edit** setting.

## Microsoft Clarity

Clarity's free Data Export API is project-scoped. Configure one Rankrat
`clarity` account for each Clarity project you want to inspect; its credential
is the project token, not a Microsoft account-wide credential.

1. Open [Microsoft Clarity](https://clarity.microsoft.com/) and sign in. If
   there is no project yet, click **New project**, enter the site name and URL,
   then click **Add new project**. Install that project's tracking code before
   expecting data.
2. Open the project, then choose **Settings → Data Export**. You must be a
   project admin.
3. Click **Generate new API token**, name it `rankrat`, and copy the value.
4. Run `rankrat setup` (or `make setup`), choose `clarity`, and paste the
   token. The token belongs to this one project; repeat these steps for another
   Clarity project.

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
