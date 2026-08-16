# Providers and credentials

Every credential Rankrat needs, plus exactly what each one lets the rat touch.

Every integration here runs on a free provider tier — a paid subscription buys
you nothing extra. Set up only the providers you use. Secrets go in
owner-readable files under `secrets/` and nowhere else: not `.env`, not a JSON
example, not Compose, not source, not a chat window. The boundary file holds
container paths, account IDs, and discovered inventory — never a credential
value.

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

`chmod 700` the directories, `chmod 600` the files. The wrapper mounts
`secrets/` read-only and `oauth/` read/write — Google rotates refresh material
and the rat has to write the new record somewhere.

Do it by hand only if a deployment demands it. Otherwise run `make setup` (from
a checkout) or `rankrat setup`: it creates these paths, walks you through each
provider-side step, takes your secrets without echoing them, and validates the
account. The rest of this page is that same walkthrough, written down.

## Google OAuth

One OAuth Desktop client and one consent flow cover Search Console, Site
Verification, Google Indexing, GA4 Data, GA4 Admin, and Google Tag Manager. Do
it once, in the Google account that should own every site, Analytics property,
and Tag Manager container the rat manages.

### Create exactly what Rankrat needs

1. Open [Create a Google Cloud project](https://console.cloud.google.com/projectcreate).
   Name it `rankrat`, click **Create**, and wait until the new project is
   selected in the top bar.
2. Open [Google Auth Platform](https://console.cloud.google.com/auth/overview).
   If Google shows **Get started**, click it. In **Branding**, set the app name
   to `rankrat` and pick your email as the support contact. Save.
3. Open [Audience](https://console.cloud.google.com/auth/audience). Select
   **External**, then **Add users** and add the same Google email that will
   authorize Rankrat — that's what lets you make the first authorization while
   the app is in testing. Skip this and Google kills the flow with
   `403 access_denied`.
4. After the first authorization goes through, come back to
   [Audience](https://console.cloud.google.com/auth/audience). Under
   **Publishing status**, click **Publish app** (or **In production**) and
   confirm. Do this even for a one-person install — an External app left in
   **Testing** hands out refresh tokens that die after seven days. An unverified
   production app still works for its own operator; Google just shows an
   unverified-app warning. Verification only matters if you're handing Rankrat
   to other people.
5. Open each link and click **Enable** once. If a page says **Manage**, it's
   already on.

   - [Search Console API](https://console.cloud.google.com/apis/library/searchconsole.googleapis.com)
   - [Site Verification API](https://console.cloud.google.com/apis/library/siteverification.googleapis.com)
   - [Google Analytics Data API](https://console.cloud.google.com/apis/library/analyticsdata.googleapis.com)
   - [Google Analytics Admin API](https://console.cloud.google.com/apis/library/analyticsadmin.googleapis.com)
   - [Google Tag Manager API](https://console.cloud.google.com/apis/library/tagmanager.googleapis.com)
   - [Web Search Indexing API](https://console.cloud.google.com/apis/library/indexing.googleapis.com)
   - [PageSpeed Insights API](https://console.cloud.google.com/apis/library/pagespeedonline.googleapis.com)
   - [Chrome UX Report API](https://console.cloud.google.com/apis/library/chromeuxreport.googleapis.com)

6. Open [OAuth Clients](https://console.cloud.google.com/auth/clients). Click
   **Create client**, choose **Desktop app**, name it `rankrat`, click
   **Create**, then **Download JSON** and keep the file. Not a Web client, not a
   service account — Desktop app.
7. Hand setup the downloaded JSON's host path, then choose `google` when it asks
   for providers:

   ```sh
   rankrat setup --google-oauth-client-file "/absolute/path/to/client_secret_...json"
   ```

   From a checkout, same one-command flow:

   ```sh
   RANKRAT_GOOGLE_OAUTH_CLIENT_FILE="$HOME/Downloads/client_secret_...json" make setup
   ```

   Rankrat reads that host file through a temporary read-only mount, validates
   it, and copies it into its owner-only secret directory. Don't move it by hand
   and don't paste multi-line JSON into the terminal. Setup opens the one
   browser consent flow itself.

The supported Google identity is the user who completes this consent flow. There
is no service-account path — don't build one.

### Boundary and authorization

A Google account entry looks like this:

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

The flow is fixed. It requests exactly these scopes:

- `https://www.googleapis.com/auth/webmasters`
- `https://www.googleapis.com/auth/indexing`
- `https://www.googleapis.com/auth/analytics.readonly`
- `https://www.googleapis.com/auth/analytics.edit`
- `https://www.googleapis.com/auth/siteverification`
- `https://www.googleapis.com/auth/tagmanager.edit.containers`
- `https://www.googleapis.com/auth/tagmanager.delete.containers`
- `https://www.googleapis.com/auth/tagmanager.edit.containerversions`
- `https://www.googleapis.com/auth/tagmanager.publish`

PKCE, high-entropy state, an exact loopback callback, offline access. Rankrat
keeps only the refresh record it needs for later calls. Re-run authorization
after a scope change, or when a stored grant predates an API you just enabled.

Revoke:

```sh
rankrat revoke-google
```

### Google permissions and product limits

OAuth only exercises permissions the signed-in user already has. Rankrat
discovers and operates on every Search Console site, Analytics account, GA4
property, and Tag Manager account that user can see. The resource arrays are
cached inventory and URL-containment data, not a second permission gate — OAuth
doesn't hand you a property the user can't already manage.

The Analytics Admin API can't create a GA4 **account**, only a property inside
an existing one. No account yet? Create it in
[Google Analytics](https://analytics.google.com/), accept the terms, then find
its numeric ID with `google_analytics_account_inventory`.

The Indexing API is restricted by Google to eligible structured-data content.
Rankrat checks supported eligibility before publishing, but it can't make an
ordinary page eligible or promise indexing.

## PageSpeed and CrUX

PageSpeed doesn't use OAuth. An API key raises its quota and is required for CrUX
History. `rankrat setup` asks for it right after the Google client file and
stores it for you — don't create the secret file by hand.

1. Open [Google API Credentials](https://console.cloud.google.com/apis/credentials).
2. Click **Create credentials → API key**.
3. Open the new key's details. Under **API restrictions**, choose **Restrict
   key**, select both **PageSpeed Insights API** and **Chrome UX Report API**,
   and **Save**.
4. Copy the key once. Paste it when Rankrat asks for the PageSpeed Insights API
   key. Leave it blank only if you're deliberately skipping PageSpeed quota
   identity and CrUX History.

`pagespeed_sites` sets the public root that contains local Lighthouse requests —
every requested page must be a child of the selected site.

## Bing Webmaster Tools

1. Open [Bing Webmaster Tools](https://www.bing.com/webmasters/home), sign in,
   click **Add a Site**, enter one site you own, and finish Bing's verification.
   Bing won't mint an API key until the account has one verified site.
2. Click the gear top-right, then **Settings → API Access**. Accept the terms if
   Bing shows them, then **API Key → Generate API Key** and copy the value.
3. Run `rankrat setup` (or `make setup`), choose `bing`, and paste the key. Bing
   issues one key per user, not per site — the same key covers every verified
   site in that Webmaster account, plus any Rankrat adds later.
4. Let Rankrat discover the account's sites, or seed known roots:

   ```json
   {
     "id": "bing",
     "provider": "bing",
     "credential": "/run/secrets/bing/api-key",
     "sites": []
   }
   ```

The key sees whatever that Webmaster account sees. Rankrat can create and manage
sites for the account, records discovered sites for reuse, and still enforces
child-URL containment within the selected site.

## Cloudflare

Cloudflare is the DNS ownership adapter, and it also supplies traffic and cache
analytics, exact cache purges, two finite cache templates, and the currently
shipped adapter for Rankrat-managed edge redirects.

All of it works on the Free plan: the analytics report is limited to the most
recent 24-hour window, exact URL purges work, and the two cache templates fit
inside the Free plan's ten Cache Rules. Rules already on the zone count against
that same limit, so budget accordingly.

Use a **User API Token**, not the separate **Account API Token** screen. Zone
DNS record operations are only granted through the user-token flow.

1. Open [Cloudflare User API Tokens](https://dash.cloudflare.com/profile/api-tokens).
2. Click **Create Token → Create Custom Token** and name it `rankrat`.
3. Add this exact permission set. It covers every shipped Cloudflare feature, so
   you never have to come back to the dashboard:

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
   Resources**, choose **Include → All accounts**. Both are required. Don't use
   the Global API Key or the separate Account API Token screen.
5. Hit **Continue to summary → Create Token**, copy the value once, and paste it
   into Rankrat's hidden setup prompt.
6. Start with empty zone inventory; Rankrat discovers what the token can see:

   ```json
   {
     "id": "cloudflare",
     "provider": "cloudflare",
     "credential": "/run/secrets/cloudflare/api-token",
     "dns_zones": []
   }
   ```

The tool surface is provider-neutral so a future DNS or CDN adapter doesn't
change callers: DNS for issued ownership proofs, separate Cloudflare tools for
analytics, cache, and managed redirects. It does not expose arbitrary record
bodies, whole-zone purges, or replacement of arbitrary existing rulesets.

Ownership proof records are DNS-only and untagged — Rankrat won't burn a
Cloudflare DNS tag quota just to mark a verification record.

Readiness proves the token reaches Cloudflare and can discover zones. It
deliberately won't create a throwaway record to test write permission, so a
green readiness check does **not** stand in for the **Zone → DNS → Edit**
setting. Set it anyway.

## Microsoft Clarity

Clarity's free Data Export API is project-scoped. Configure one Rankrat
`clarity` account per Clarity project — the credential is that project's token,
not a Microsoft account-wide credential.

1. Open [Microsoft Clarity](https://clarity.microsoft.com/) and sign in. No
   project yet? Click **New project**, enter the site name and URL, then **Add
   new project**. Install that project's tracking code before you expect any
   data back.
2. Open the project, then **Settings → Data Export**. You have to be a project
   admin.
3. Click **Generate new API token**, name it `rankrat`, and copy the value.
4. Run `rankrat setup` (or `make setup`), choose `clarity`, and paste the token.
   It belongs to this one project — repeat for each project you want.

Rankrat calls only Clarity's fixed project-insights endpoint. It doesn't write
Clarity config or replay session recordings. The upstream export API caps each
project at ten requests per day, so run `make test-live-clarity` on purpose,
not inside a polling loop. See
[Microsoft's Data Export API documentation](https://learn.microsoft.com/en-us/clarity/setup-and-installation/clarity-data-export-api)
for the current dimensions, metrics, and quota.

## IndexNow

IndexNow is an open push protocol — no dashboard, no credentialed reporting
account. It tells participating engines that bounded URLs changed. It does not
promise crawl, indexing, or ranking.

Create and verify a target from a checkout:

```sh
make init-indexnow INDEXNOW_TARGET_ID=example INDEXNOW_HOST=example.com
make verify-indexnow-key INDEXNOW_TARGET_ID=example
```

Publish the generated `<key>.txt` at the configured HTTPS `key_location`.
Verification needs exact contents and no redirect. See the
[IndexNow documentation](https://www.indexnow.org/documentation?hl=en).

## HTTP bearer

Generate a random token — don't reuse a provider secret:

```sh
install -m 600 /dev/null secrets/rankrat/http-bearer-token
openssl rand -base64 32 | tr -d '\n' > secrets/rankrat/http-bearer-token
```

This guards REST and Streamable HTTP MCP. It has nothing to do with provider
auth and stdio never touches it.

## Live provider verification

Each test pulls its account and a safe target straight from the selected Rankrat
profile — there's no second selector matrix to keep in sync. A test skips with a
specific reason when the provider is absent or the account has no usable
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
| `make test-live-indexnow` | One real submission only, behind an explicit one-command opt-in |
| `make test-live-http` | Production image plus authenticated REST and both MCP transports |

`make test-live` runs every provider target, then the authenticated HTTP/MCP
check. Individual targets are faster while you're configuring one provider.

Use `RANKRAT_PROFILE=/absolute/profile make test-live-<provider>` for a
non-default profile. IndexNow is the destructive exception: it sends nothing
unless `RANKRAT_RUN_LIVE_INDEXNOW_SUBMISSION=true` is on that one command. If
readiness and a deep live test disagree, go to
[Troubleshooting](troubleshooting.md).
