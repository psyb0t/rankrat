# Ownership and onboarding

Creating provider resources and proving you own them are two different jobs — Rankrat does both, in that order, and never pretends one is the other.

Rankrat creates or reuses one GA4 property and stream, adds or reuses Google
Search Console and Bing properties, and writes what it made into local
inventory. Hand it a supported DNS adapter and it also publishes and redeems the
ownership proofs the providers issue. What it can't do: create a GA4 account, or
touch DNS through a provider it has no adapter for. And onboarding never deploys
a GA4 tag — that's your move, later.

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

Every process serves the onboarding guide, read-only mode included:

- MCP resource `rankrat://onboarding`;
- MCP resource template `rankrat://onboarding/{site_url}`;
- MCP tool `onboarding_guide`;
- REST `POST /v1/onboarding-guides`.

It tells you the live write/onboarding posture, the configured sites, the
verification methods each specific property form accepts, the manual steps, and
who performs each action. Read it instead of assuming every Search Console
property takes the same proof — Domain and URL-prefix don't.

## What onboarding creates

For one HTTPS site root:

1. A GA4 property inside an existing Analytics account.
2. A web data stream and the `G-` measurement ID it returns.
3. An unverified Google Search Console URL-prefix property.
4. An unverified Bing Webmaster site.
5. GA4/Search Console/Bing inventory entries in `boundaries.json` — written only
   once all three provider stages have succeeded.

No GA4 tag gets deployed. In writable mode, deploy one yourself with the typed
Tag Manager tools (container, workspace, entity, version, publish) using the
returned measurement ID, or drop it in through however the site normally loads
tags. GA4 collects nothing until that tag is live. Search Console and Bing data
also start at verification — none of it is retroactive.

## The GA4 account prerequisite

Analytics has accounts, and properties live inside them. The Admin API has no
`accounts.create`, and `provisionAccountTicket` dead-ends at a Terms of Service
page only a human can accept. So if there's no account yet, no tool finishes
this — you do:

1. Open [Google Analytics](https://analytics.google.com/) as the OAuth user.
2. Go to **Admin → Create → Account**.
3. Name it and set data-sharing preferences.
4. Accept the Analytics Terms of Service.
5. Run `google_analytics_account_inventory` and copy the numeric account ID.

One account visible, Rankrat picks it. Several visible, it can't guess — pass
the numeric ID as `google_analytics_parent_account_id` when you onboard.

## Operator-driven onboarding

Needs writes and a config directory it can trust:

```sh
RANKRAT_READ_ONLY=false rankrat onboard-site \
  --site-url https://example.com/ \
  --display-name example \
  --time-zone Etc/UTC \
  --currency-code USD
```

Exactly one Google account and one Bing account configured? Those get selected
automatically. Pass explicit IDs only to break a tie. The wrapper refuses unsafe
config ownership or modes, and provider secrets stay mounted read-only.

## Agent-driven onboarding

MCP tool `site_onboarding_submit` and REST `POST /v1/site-onboarding-submissions`,
both present in normal writable mode:

```dotenv
RANKRAT_READ_ONLY=false
```

HTTP still wants its bearer. `RANKRAT_READ_ONLY=true` drops this operation from
REST and MCP discovery — that's the only switch.

## Ownership status

`site_ownership_check` / `POST /v1/site-ownership-checks` reads:

- Google Search Console permission/verification state when `google_account_id`
  is selected;
- Bing verification state when `bing_account_id` is selected;
- expected public DNS proof presence when it's known.

It returns no verification token. A property can exist and still be unverified,
so don't read anything into an empty report until ownership is complete for every
selected provider. Select at least one — a Bing-only request never calls Google,
a Google-only request never calls Bing.

## Automated DNS verification

`site_ownership_verify` / `POST /v1/site-ownership-verifications`:

1. pulls proof values only from the selected Google and/or Bing APIs;
2. selects the configured DNS account and its exact zone;
3. creates only those proof records through the DNS adapter — Google TXT, Bing
   CNAME to `verify.bing.com`, nothing else;
4. checks public propagation;
5. redeems each proof once it's visible;
6. returns a bounded receipt with no token values and no raw provider bodies.

Cloudflare is the adapter today. The public operation names and request fields
stay provider-neutral (`dns_account_id`, `dns_zones`, `provider_zone_id`) so the
next adapter fills the same contract without changing the surface.

It's idempotent: an exact existing record is reused, and a CNAME name that's
already occupied is refused rather than clobbered. There is no arbitrary
DNS name/type/value CRUD here — only these proofs.

Verify Bing on its own, for instance, when Google Site Verification isn't in
play:

```json
{
  "bing_account_id": "bing-main",
  "dns_account_id": "cloudflare-main",
  "site_url": "https://example.com/"
}
```

The receipt carries `null` for any provider you didn't select; `complete` means
every provider you did select is verified.

Propagation is asynchronous, so don't expect one call to finish it:

1. Call `site_ownership_verify`.
2. Poll `site_ownership_check`.
3. Stop only when `complete` is true, or a finite provider error lands on your
   desk.

Leave the verification records in place — providers recheck them.

## Manual verification alternatives

### Search Console Domain property

`sc-domain:example.com` takes DNS TXT and nothing else. A GA4 tag, an HTML file,
a meta tag — none of them verify a Domain property.

### Search Console URL-prefix property

An `https://` property accepts:

- the installed Google Analytics tag;
- Google's issued HTML verification file;
- Google's issued meta tag;
- Google's issued DNS TXT record.

Rankrat doesn't invent proof values — the provider consoles issue them.

### Bing

Bing accepts:

- import from a verified Search Console property;
- Bing's XML verification file;
- Bing's meta tag;
- Bing's DNS CNAME.

The runtime onboarding guide returns whichever methods actually apply right now.

## Required operator follow-up

Once the resources exist:

1. Deploy a tag with the returned GA4 measurement ID — through the typed Tag
   Manager write tools, or the site's normal integration.
2. Verify Search Console and Bing, by automated DNS or a manual method.
3. Poll ownership until it's complete.
4. Confirm provider readiness before you trust an empty report.
5. Publish an IndexNow key only if you're going to submit through IndexNow.

## Partial failure semantics

Onboarding runs in sequence and does not roll back. It resolves or creates GA4
first, then Search Console, then Bing, and writes inventory only after all three
land. If a later stage fails, the earlier provider resources are real — they just
aren't in local inventory yet. The receipt names the stages that completed.

Before you retry:

1. Inspect `google_analytics_account_inventory` and the Google/Bing site lists.
2. Fix the permission or provider that broke.
3. Retry the exact same request. Rankrat matches an existing GA4 stream by site
   URL and reuses existing Search Console/Bing sites — it won't duplicate them.

There's no rollback and no delete tool. Renaming an account or property is
supported; deleting an Analytics container is left out on purpose.
