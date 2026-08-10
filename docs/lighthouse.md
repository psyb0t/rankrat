# Local Lighthouse audits

Rankrat can run Chromium locally and return Lighthouse scores/findings without
sending the page to PageSpeed Insights. Browser execution is optional and lives
in the separate `psyb0t/rankrat-lighthouse` image.

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

| MCP tool | REST route | Result |
| --- | --- | --- |
| `lighthouse_audit` | `POST /v1/lighthouse/audits` | Performance, accessibility, best-practices, and SEO scores/findings |
| `lighthouse_seo_findings` | `POST /v1/lighthouse/seo-findings` | Failed SEO audits |
| `lighthouse_accessibility_findings` | `POST /v1/lighthouse/accessibility-findings` | Failed accessibility audits |
| `lighthouse_performance_findings` | `POST /v1/lighthouse/performance-findings` | Failed performance audits |
| `lighthouse_best_practices_findings` | `POST /v1/lighthouse/best-practices-findings` | Failed best-practices audits |

Every call takes `account_id`, a configured `site_url`, a child `page_url`, and
an optional timeout between 5 and 300 seconds. The account's `pagespeed_sites`
allow-list authorizes PageSpeed and Lighthouse; enabling the browser creates no
second URL scope.

## Architecture

```text
MCP or REST caller
        |
        v
Rankrat image -- /run/lighthouse/lighthouse.sock --> Lighthouse image
  provider credentials                            Chromium + local proxy
  boundary checks                                 no provider credentials
```

The worker has no TCP listener. Rankrat reaches it through a shared Unix socket.
The worker receives no Google, Bing, Cloudflare, backlink, IndexNow, OAuth, or
Rankrat HTTP bearer mounts.

Requests and reports are schema-validated on both sides. Rankrat checks the
requested page before dispatch and checks Lighthouse's actual final document
URL before returning a result.

## Run the two-image stack

From a checkout:

```sh
make run-http-lighthouse
```

Equivalent Compose flow:

```sh
cp docker-compose.yml.example docker-compose.yml
docker compose config --quiet
docker compose up --build
```

The example:

- binds Rankrat HTTP to host loopback;
- uses a named Unix-socket volume as the only service-to-service channel;
- drops all capabilities and sets no-new-privileges;
- uses read-only root filesystems;
- applies PID, CPU, memory, tmpfs, and shared-memory limits;
- runs both services as the configured non-root UID/GID;
- gives the worker no provider-secret mounts;
- uses networkless one-shot volume initializers.

## Disable browser execution

Set `RANKRAT_LIGHTHOUSE_WORKER_SOCKET` to an empty value or omit the socket
mount. The five tools remain discoverable and return a finite `UNAVAILABLE`
error. Rankrat does not silently fall back to PageSpeed Insights.

## Network policy

The worker routes normal browser requests through its local public-address-only
proxy. It:

- permits only HTTP/HTTPS and ports 80/443;
- resolves target names itself;
- rejects loopback, link-local, private, multicast, documentation, reserved,
  and other non-public address classes;
- applies response/body and audit time limits;
- serializes audits one at a time.

Allowed pages may load public third-party subresources. A public cross-origin
redirect can be fetched before Rankrat rejects its final URL as outside the
configured site. Private/special destinations remain blocked by the worker
proxy. Treat public cross-origin traffic as part of the audit's network effect.

## Chromium sandbox caveat

Chromium runs with `--no-sandbox`. The documented non-root, capability-free,
no-new-privileges container cannot provide Chromium's namespace/setuid sandbox.
The worker's container limits, missing credentials, and outbound proxy reduce
blast radius but are not a renderer exploit boundary equivalent to Chromium's
own sandbox.

Run it only against operator-controlled, trusted content. For untrusted pages,
put the entire worker inside a stronger outer runtime such as gVisor or Kata
Containers. Do not run its Chromium command directly on the host and do not add
provider credential mounts to the worker.

## Timeouts and concurrency

The public request timeout is bounded. The worker also enforces its own runner
timeout. It accepts one audit at a time and returns a finite busy response for
concurrent work instead of launching an unbounded browser fleet.

Lighthouse scores vary with machine load, network conditions, and page changes.
Use repeated measurements and findings, not one score as an immutable truth.

## Verification

Mocked worker tests:

```sh
make lighthouse-test
make lighthouse-lint
```

Production-image and real browser transport test:

```sh
make test-lighthouse-image
```

That gate builds both production images and exercises real audits through stdio
MCP, authenticated REST, and authenticated Streamable HTTP MCP. The mocked
contract/security suites additionally cover invalid boundaries, private address
classes, malformed worker responses, oversized bodies, busy responses,
timeouts, and transport parity.

Image inventory and vulnerability checks cover both images:

```sh
make sbom
make audit-image
```

## Common failures

| Symptom | Check |
| --- | --- |
| `UNAVAILABLE` | Socket disabled/missing, worker unhealthy, or wrong UID/volume permissions |
| URL rejected | `page_url` is not under the selected `pagespeed_sites` boundary |
| Busy | Another audit is running; retry after it completes |
| Timeout | Increase the bounded request timeout or fix a page that never settles |
| Final URL rejected | Navigation ended outside the configured site |
| Private-address rejection | DNS resolved to a non-public address; the worker is intentionally not an intranet browser |

See [Troubleshooting](troubleshooting.md) for the complete startup checklist.
