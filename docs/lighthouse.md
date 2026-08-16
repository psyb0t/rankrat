# Local Lighthouse audits

Run Chromium on your own box and get Lighthouse scores back without shipping the
page off to PageSpeed Insights. Browser execution is optional and lives entirely
in the separate `psyb0t/rankrat-lighthouse` image — it never touches the main
Rankrat process.

## Contents

- [Tool surface](#tool-surface)
- [Architecture](#architecture)
- [Run the two-image stack](#run-the-two-image-stack)
- [Disable browser execution](#disable-browser-execution)
- [Network policy](#network-policy)
- [Chromium sandbox caveat](#chromium-sandbox-caveat)
- [Timeouts and concurrency](#timeouts-and-concurrency)
- [Verification](#verification)
- [Common failures](#common-failures)

## Tool surface

Five tools, five REST routes:

| MCP tool | REST route | Result |
| --- | --- | --- |
| `lighthouse_audit` | `POST /v1/lighthouse/audits` | Performance, accessibility, best-practices, and SEO scores/findings |
| `lighthouse_seo_findings` | `POST /v1/lighthouse/seo-findings` | Failed SEO audits |
| `lighthouse_accessibility_findings` | `POST /v1/lighthouse/accessibility-findings` | Failed accessibility audits |
| `lighthouse_performance_findings` | `POST /v1/lighthouse/performance-findings` | Failed performance audits |
| `lighthouse_best_practices_findings` | `POST /v1/lighthouse/best-practices-findings` | Failed best-practices audits |

Every call takes `account_id`, a known `site_url`, a child `page_url`, and an
optional timeout between 5 and 300 seconds. The account's `pagespeed_sites`
inventory is what defines the site roots for both PageSpeed and Lighthouse
child-URL containment — turning on the browser creates no second credential
scope. Same accounts, same boundaries.

## Architecture

```text
MCP or REST caller
        |
        v
Rankrat image -- /run/lighthouse/lighthouse.sock --> Lighthouse image
  provider credentials                            Chromium + local proxy
  boundary checks                                 no provider credentials
```

The worker exposes no TCP listener — Rankrat reaches it over a shared Unix socket
and nothing else. It gets zero Google, Bing, Cloudflare, IndexNow, OAuth, or
Rankrat HTTP bearer mounts. If a rendered page pops the Chromium process, there
are no credentials sitting there to steal.

Requests and reports are schema-validated on both sides. Rankrat checks the
requested page before dispatch, and checks Lighthouse's actual final document URL
before it hands you a result — a mid-flight redirect off your site gets caught.

## Run the two-image stack

From a checkout:

```sh
make run-http
```

Published-image wrapper equivalent:

```sh
rankrat --data-dir /absolute/path/to/rankrat-profile http -d
```

The wrapper writes the reviewed Compose deployment into the profile when it's
missing and leaves an existing operator file alone. Drop `-d` to attach to both
services' logs.

The committed Compose deployment:

- binds Rankrat HTTP to host loopback;
- uses a named Unix-socket volume as the only service-to-service channel;
- drops all capabilities and sets no-new-privileges;
- runs read-only root filesystems;
- applies PID, CPU, memory, tmpfs, and shared-memory limits;
- runs both services as the configured non-root UID/GID;
- gives the worker no provider-secret mounts;
- initializes its volume through a networkless one-shot container.

## Disable browser execution

Set `RANKRAT_LIGHTHOUSE_WORKER_SOCKET` to an empty value or omit the socket
mount. The five tools stay discoverable and return a finite `UNAVAILABLE`.
Rankrat does not quietly fall back to PageSpeed Insights — if you asked for a
local audit and the worker isn't there, you get told, not swapped onto a
different provider behind your back.

## Network policy

The worker sends normal browser traffic through its own local, public-address-only
proxy. That proxy:

- permits HTTP/HTTPS only, ports 80 and 443 only;
- resolves target names itself;
- rejects loopback, link-local, private, multicast, documentation, reserved, and
  every other non-public address class;
- enforces response/body and audit time limits;
- runs one audit at a time.

Allowed pages can pull public third-party subresources, and a public cross-origin
redirect may get fetched before Rankrat rejects its final URL as off-site.
Private and special destinations stay blocked by the proxy the whole way. Treat
public cross-origin traffic as part of the audit's network footprint — because it
is.

## Chromium sandbox caveat

Chromium runs with `--no-sandbox`. The non-root, capability-free,
no-new-privileges container this ships in cannot give Chromium its
namespace/setuid sandbox. The container limits, missing credentials, and
outbound proxy shrink the blast radius — they are not a renderer exploit boundary
equivalent to Chromium's own sandbox. Don't pretend otherwise.

So point it at operator-controlled, trusted content only. For untrusted pages,
wrap the whole worker in a stronger outer runtime — gVisor, Kata Containers, that
class of thing. Do not run its Chromium command straight on the host, and do not
bolt provider-credential mounts onto the worker to "make it convenient."

## Timeouts and concurrency

The public request timeout is bounded (5–300 seconds), and the worker enforces
its own runner timeout on top. It takes one audit at a time and returns a finite
busy response for anything concurrent, rather than spawning an unbounded fleet of
browsers and melting the host.

Lighthouse scores drift with machine load, network conditions, and the page
itself. Read repeated measurements and the findings — never treat a single score
as gospel.

## Verification

Mocked worker tests:

```sh
make lighthouse-test
make lighthouse-lint
```

Production-image, real-browser transport test:

```sh
make test-lighthouse-image
```

That gate builds both production images and drives real audits through stdio MCP,
authenticated REST, and authenticated Streamable HTTP MCP. The mocked
contract/security suites additionally cover invalid boundaries, private address
classes, malformed worker responses, oversized bodies, busy responses, timeouts,
and transport parity.

Image inventory and vulnerability checks span both images:

```sh
make sbom
make audit-image
```

## Common failures

| Symptom | Check |
| --- | --- |
| `UNAVAILABLE` | Socket disabled/missing, worker unhealthy, or wrong UID/volume permissions |
| URL rejected | `page_url` isn't under the selected `pagespeed_sites` boundary |
| Busy | Another audit is running; retry once it finishes |
| Timeout | Raise the bounded request timeout, or fix a page that never settles |
| Final URL rejected | Navigation ended outside the configured site |
| Private-address rejection | DNS resolved to a non-public address; the worker is not an intranet browser, on purpose |

See [Troubleshooting](troubleshooting.md) for the full startup checklist.
