# Ownership and onboarding

Creating provider resources and proving ownership are separate workflows.
Rankrat can create or reuse one GA4 property and stream, add or reuse Google
Search Console and Bing properties, persist discovered inventory, and—with a supported DNS
adapter—publish/redeem provider-issued ownership proofs. It cannot create a GA4
account or modify DNS through an unsupported provider. Site onboarding does not
automatically deploy a GA4 tag.

## Contents

- [Read the runtime guide first](#read-the-runtime-guide-first)
- [What onboarding creates](#what-onboarding-creates)
- [The GA4 account prerequisite](#the-ga4-account-prerequisite)
- [Operator-driven onboarding](#operator-driven-onboarding)
- [Agent-driven onboarding](#agent-driven-onboarding)
- [Ownership status](#ownership-status)
- [Automated DNS verification](#automated-dns-verification)
- [Manual verification alternatives](#manual-verification-alternatives)
- [Required operator follow-up](#required-operator-follow-up)
- [Partial failure semantics](#partial-failure-semantics)

## Read the runtime guide first

Every process exposes onboarding guidance even in read-only mode:

- MCP resource `rankrat://onboarding`;
- MCP resource template `rankrat://onboarding/{site_url}`;
- MCP tool `onboarding_guide`;
- REST `POST /v1/onboarding-guides`.

The guide reports current write/onboarding posture, configured sites,
property-specific verification methods, manual steps, and which actor performs
each action. Use it instead of assuming all Search Console property forms accept
the same verification method.

## What onboarding creates

For one HTTPS site root:

1. A GA4 property inside an existing Analytics account.
2. A web data stream and returned `G-` measurement ID.
3. An unverified Google Search Console URL-prefix property.
4. An unverified Bing Webmaster site.
5. GA4/Search Console/Bing inventory entries in `boundaries.json` after all
   preceding provider stages succeed.

Site onboarding does not deploy a GA4 tag. In writable mode, the operator may
use the typed Tag Manager container, workspace, entity, version, and publication
tools to deploy an explicit tag using the returned measurement ID, or install it
through the site's normal integration. Collection begins only after that tag is
published. Search Console and Bing data also begin after ownership verification;
they are not retroactive.

## The GA4 account prerequisite

Google Analytics has accounts containing properties. The Analytics Admin API
has no `accounts.create`; `provisionAccountTicket` still ends at a Terms of
Service page a human must accept.

If the user has no account:

1. Open [Google Analytics](https://analytics.google.com/) as the OAuth user.
2. Go to **Admin → Create → Account**.
3. Name it and set data-sharing preferences.
4. Accept the Analytics Terms of Service.
5. Run `google_analytics_account_inventory` and copy the numeric account ID.

When exactly one Analytics account is visible, Rankrat selects it automatically.
When several are visible, pass the intended numeric ID as
`google_analytics_parent_account_id` during onboarding.

## Operator-driven onboarding

This terminal command requires writes and a safely writable config directory:

```sh
RANKRAT_READ_ONLY=false rankrat onboard-site \
  --site-url https://example.com/ \
  --display-name example \
  --time-zone Etc/UTC \
  --currency-code USD
```

When exactly one Google account and one Bing account are configured, those IDs
are selected automatically. Pass explicit IDs only to resolve ambiguity. The
wrapper refuses unsafe config ownership/modes. Provider secrets stay read-only.

## Agent-driven onboarding

The MCP tool `site_onboarding_submit` and REST route
`POST /v1/site-onboarding-submissions` are present in normal writable mode:

```dotenv
RANKRAT_READ_ONLY=false
```

HTTP bearer auth still applies. `RANKRAT_READ_ONLY=true` removes this operation
from both REST and MCP discovery; no other capability switch exists.

## Ownership status

`site_ownership_check` / `POST /v1/site-ownership-checks` reads:

- Google Search Console permission/verification state when `google_account_id`
  is selected;
- Bing verification state when `bing_account_id` is selected;
- expected public DNS proof presence when known.

It returns no verification token. An added provider resource can exist while
still being unverified; do not interpret empty reports until ownership is
complete for every selected provider. Select at least one provider. A
Bing-only request does not call Google, and a Google-only request does not call
Bing.

## Automated DNS verification

`site_ownership_verify` / `POST /v1/site-ownership-verifications`:

1. obtains proof values only from the selected Google and/or Bing APIs;
2. selects the configured DNS account and exact zone;
3. creates only those proof records through the DNS adapter;
4. checks public propagation;
5. redeems proofs when visible;
6. returns a bounded receipt without token values/raw provider bodies.

Cloudflare is the current adapter. Public operation names and requests remain
provider-neutral (`dns_account_id`, `dns_zones`, `provider_zone_id`) so another
adapter can implement the same contract.

Application is idempotent: an exact existing record is reused. Conflicting
CNAMEs are refused. Rankrat exposes no arbitrary DNS name/type/value CRUD.

For example, verify Bing independently when Google Site Verification is not
available:

```json
{
  "bing_account_id": "bing-main",
  "dns_account_id": "cloudflare-main",
  "site_url": "https://example.com/"
}
```

The receipt contains `null` for an unselected provider; `complete` means every
selected provider is verified.

DNS propagation is asynchronous:

1. Call `site_ownership_verify`.
2. Poll `site_ownership_check`.
3. Stop only when `complete` is true or a finite provider error needs operator
   action.

Keep verification records in place; providers may recheck them.

## Manual verification alternatives

### Search Console Domain property

`sc-domain:example.com` accepts DNS TXT only. A GA4 tag, HTML file, or meta tag
does not verify a Domain property.

### Search Console URL-prefix property

An `https://` property may use:

- the installed Google Analytics tag;
- Google's issued HTML verification file;
- Google's issued meta tag;
- Google's issued DNS TXT record.

Rankrat does not invent proof values. Provider consoles issue them.

### Bing

Bing may use:

- import from a verified Search Console property;
- Bing's XML verification file;
- Bing's meta tag;
- Bing's DNS CNAME.

The runtime onboarding guide returns the currently relevant method list.

## Required operator follow-up

After resource creation:

1. Deploy a tag with the returned GA4 measurement ID through the typed Tag
   Manager write tools, or install it through the public site's normal
   integration.
2. Verify Search Console and Bing through automated DNS or a manual method.
3. Poll ownership until complete.
4. Confirm provider readiness before trusting empty reports.
5. Publish an IndexNow key only if IndexNow submission will be used.

## Partial failure semantics

Onboarding is sequential and not transactional. It resolves or creates GA4
first, then Search Console, then Bing, and persists inventory only after all
three succeed. If a later stage fails, earlier provider resources remain real
but may not yet be in local inventory. The receipt names completed stages.

Before retrying:

1. Inspect `google_analytics_account_inventory` and Google/Bing site lists.
2. Fix the failing permission/provider.
3. Retry the same request. Rankrat matches an existing GA4 stream by site URL
   and reuses existing Search Console/Bing sites instead of duplicating them.

There is no rollback or delete tool. Renaming an account/property is supported;
deleting an Analytics container is deliberately not exposed.
