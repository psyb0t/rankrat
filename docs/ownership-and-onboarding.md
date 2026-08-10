# Ownership and onboarding

Creating provider resources and proving ownership are separate workflows.
Rankrat can create one GA4 property and stream, add Google Search Console and
Bing properties, persist exact boundaries, and—with a supported DNS
adapter—publish/redeem provider-issued ownership proofs. It cannot create a GA4
account, deploy the GA4 tag, or modify DNS through an unsupported provider.

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
5. Exact GA4/Search Console/Bing resource entries in `boundaries.json` after all
   preceding provider stages succeed.

The GA4 tag is not deployed. Collection begins only after the operator installs
the returned measurement ID. Search Console and Bing data also begin after
ownership verification; they are not retroactive.

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

Pass that ID as `google_analytics_parent_account_id` during onboarding.

## Operator-driven onboarding

This is a human terminal command, so it does not depend on the agent-onboarding
switch. It does require writes and a safely writable boundary directory:

```sh
RANKRAT_READ_ONLY=false rankrat.sh onboard-site \
  --google-account-id google \
  --bing-account-id bing \
  --google-analytics-parent-account-id 123456789 \
  --site-url https://example.com/ \
  --display-name example \
  --time-zone Etc/UTC \
  --currency-code USD
```

The wrapper refuses unsafe config ownership/modes and mounts the config
directory writable only for this operator operation. Provider secrets stay
read-only.

## Agent-driven onboarding

The MCP tool `site_onboarding_submit` and REST route
`POST /v1/site-onboarding-submissions` appear only when both are set:

```dotenv
RANKRAT_READ_ONLY=false
RANKRAT_ALLOW_AGENT_ONBOARDING=true
```

Ordinary writable mode is insufficient because onboarding is the one operation
allowed to expand the boundary file the server later enforces. HTTP bearer auth
still applies. Restrict access to a trusted caller.

If the new site's resources are not yet allow-listed, a trusted bootstrap can
also set:

```dotenv
RANKRAT_UNBOUNDED=true
```

Unbounded mode keeps credential account IDs/paths fixed, discovers or uses
resources outside current per-resource lists, and permits the onboarding result
to persist exact IDs. Restart with it disabled after onboarding. It can be
enabled again for a later trusted bootstrap; it is not a one-use token.

## Ownership status

`site_ownership_check` / `POST /v1/site-ownership-checks` reads:

- Google Search Console permission/verification state;
- Bing verification state;
- expected public DNS proof presence when known.

It returns no verification token. An added provider resource can exist while
still being unverified; do not interpret empty reports until ownership is
complete.

## Automated DNS verification

`site_ownership_verify` / `POST /v1/site-ownership-verifications`:

1. obtains Google/Bing-issued proof values through their APIs;
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

1. Install the returned GA4 measurement ID in the public site `<head>`.
2. Verify Search Console and Bing through automated DNS or a manual method.
3. Poll ownership until complete.
4. Confirm provider readiness before trusting empty reports.
5. Publish an IndexNow key only if IndexNow submission will be used.

## Partial failure semantics

Onboarding is sequential and not transactional. It creates GA4 first, then
Search Console, then Bing, and persists the boundary only after all three
succeed. If a later stage fails, earlier provider resources remain real but may
not be in the boundary file. Re-running can create a duplicate GA4 property.

Before retrying:

1. Inspect `google_analytics_account_inventory` for the created property.
2. Inspect Google/Bing consoles for accepted resources.
3. Add/reconcile exact existing IDs manually if appropriate.
4. Fix the failing permission/provider.
5. Retry only after deciding how to handle prior resources.

There is no rollback or delete tool. Renaming an account/property is supported;
deleting an Analytics container is deliberately not exposed.
