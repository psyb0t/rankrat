# Development

Rankrat's dev toolchain lives in containers. You bring Docker and GNU Make; the
pinned Python, uv, Node, pnpm, browsers, linters, test runners, SBOM tools, and
scanners ship inside the project images. No "works on my machine" — the image is
the machine.

## Contents

- [Project layout](#project-layout)
- [Discover commands](#discover-commands)
- [Build images](#build-images)
- [Format and lint](#format-and-lint)
- [Mocked tests](#mocked-tests)
- [Production transport tests](#production-transport-tests)
- [Live provider tests](#live-provider-tests)
- [Spec-first REST development](#spec-first-rest-development)
- [Dependency changes](#dependency-changes)
- [Security and supply-chain gates](#security-and-supply-chain-gates)
- [Local runtime](#local-runtime)
- [CI and release surface](#ci-and-release-surface)
- [Contribution checklist](#contribution-checklist)

## Project layout

```text
src/rankrat/
  api/          YAML-first REST contract sources
  models/       strict immutable public/boundary models
  operator/     multi-provider workflows and local file persistence
  policy/       resource boundaries and limits
  providers/    fixed-origin upstream clients
  services/     typed business operations
  state/        SQLite monitor persistence
  transports/   stdio MCP, Streamable HTTP MCP, REST, OpenAPI wiring
lighthouse-worker/  isolated TypeScript/Chromium worker
tests/              unit, contract, integration, security, and opt-in live tests
scripts/            generation, setup helpers, and production-image smoke tests
.agents/            distributable skill and client/plugin manifests
security/           reviewed OpenVEX statements for image scanning
docs/               operator and contributor guides
```

The package is Python 3.14 with strict Pydantic models at the request, provider,
configuration, and persistence boundaries. The Lighthouse worker is TypeScript.

## Discover commands

```sh
make help
make version
make version V=X.Y.Z
```

`make help` is the source of truth for commands — read it before reaching for
anything else. Don't call host Python/pnpm directly and quietly test a different
dependency graph than CI does. `make version` prints the next image tag;
`make version V=X.Y.Z` validates the SemVer and updates the package metadata,
lockfile, Codex manifest, YAML-first OpenAPI source, and generated
`openapi.json`. It does not commit or tag — the repository release process does
that, and only after everything's verified.

## Build images

```sh
make dev-image             # Python development/test image
make lighthouse-dev-image  # Lighthouse development stage
make build                 # both production images
make build-test            # development image used by tests/lint
```

Production images:

- `psyb0t/rankrat:v<version>` and `:latest`;
- `psyb0t/rankrat-lighthouse:v<version>` and `:latest`.

The version in `pyproject.toml` is the local image-tag source. Bump it there,
nowhere else.

## Format and lint

```sh
make format
make lint
make lint-fix
make lighthouse-format
make lighthouse-lint
```

`make lint` runs Python formatting, Ruff, Bandit, Pyright, strict mypy,
ShellCheck, shfmt, and the Lighthouse TypeScript formatter/linter/typecheck — the
whole gate, one target. `lint-fix` applies only the Python formatter and Ruff
safe fixes; review every change it makes.

## Mocked tests

```sh
make test                 # all mocked Python suites + Lighthouse tests + tooling checks
make test-unit
make test-contract
make test-integration
make test-security
make lighthouse-test
make test-tooling
make test-coverage
```

Test layers:

| Layer | Scope |
| --- | --- |
| Unit | Models, provider parsing, policies, service behavior, local operators |
| Contract | REST and MCP operation presence, schemas, policy-dependent discovery, OpenAPI snapshot |
| Integration | Runtime wiring, stdio process exchange, state persistence, OAuth/onboarding orchestration |
| Security | SSRF, auth, boundaries, secret/error redaction, container/dependency regressions |
| Lighthouse | Worker protocol, network policy, report parsing, concurrency, error handling |
| Tooling | Frozen dependency policy and critical Make/wrapper/example invariants |

`make test-local` reuses the exact already-built versioned dev image and nothing
else. It's a registry-outage fallback, not the release gate — go back to fresh
builds before you ship.

## Production transport tests

```sh
make test-image
make test-lighthouse-image
```

`test-image` drives production startup, stdio MCP, loopback REST, and
authenticated Streamable HTTP MCP. `test-lighthouse-image` runs real
public-page Lighthouse audits across all three public transports.

These scripts create explicit temporary containers and paths for their run.
Don't swap their cleanup for a blanket Docker removal/prune — you'll take out
things you didn't mean to.

## Live provider tests

Live tests are opt-in and pull their account/resource inputs straight from the
selected Rankrat profile. No `.env` selector matrix to maintain:

```sh
make test-live
make test-live-google-search-console
make test-live-google-analytics
make test-live-google-tag-manager
make test-live-pagespeed
make test-live-cloudflare
make test-live-clarity
make test-live-bing
make test-live-http
```

IndexNow is a real write, so it takes an extra explicit opt-in:

```sh
RANKRAT_READ_ONLY=false \
RANKRAT_RUN_LIVE_INDEXNOW_SUBMISSION=true \
make test-live-indexnow
```

Unused providers skip cleanly. Use
`RANKRAT_PROFILE=/absolute/profile make test-live-<provider>` when the default
profile isn't the one you mean. Mocked tests never touch live credentials. See
[Providers and credentials](providers.md#live-provider-verification).

## Spec-first REST development

The REST contract is YAML-first — you edit the YAML, not the JSON:

- [`src/rankrat/api/openapi.yaml`](../src/rankrat/api/openapi.yaml) — base
  provider/operation surface;
- [`src/rankrat/api/seo-openapi.yaml`](../src/rankrat/api/seo-openapi.yaml) —
  intelligence, monitoring, Bing backlink, CrUX, and Cloudflare surface;
- [`src/rankrat/api/free-seo-openapi.yaml`](../src/rankrat/api/free-seo-openapi.yaml) —
  Google Tag Manager, Microsoft Clarity, provider-neutral edge redirects, and
  safe Bing content-submission surface;
- [`openapi.json`](../openapi.json) — the generated merged artifact.

After editing any source fragment:

```sh
make generate-openapi
make check-openapi
```

`check-openapi` fails when the committed JSON is stale. Contract tests verify
operation IDs, runtime route parity, policy-dependent route removal, and the
snapshot. Do not hand-edit `openapi.json` — it's generated, and the check will
catch you.

MCP contracts are transport-neutral typed catalogs in
`src/rankrat/transports/tool_contracts.py` plus the SEO catalog in
`src/rankrat/transports/seo_mcp.py`. A feature isn't done until stdio MCP,
Streamable HTTP MCP, REST, contracts, and documentation all agree where they
overlap.

## Dependency changes

Python dependencies are exact in `pyproject.toml`/`uv.lock`; Lighthouse uses an
exact pnpm lock. Changes go through the containerized targets, never a manual
edit:

```sh
make pkg-add PKG=name==version
make pkg-update PKG=name
make pkg-upgrade
make pkg-remove PKG=name

make lighthouse-pkg-add LIGHTHOUSE_PKG=name@version
make lighthouse-pkg-update LIGHTHOUSE_PKG=name@version
make lighthouse-pkg-upgrade
make lighthouse-pkg-remove LIGHTHOUSE_PKG=name
```

The project enforces a seven-day minimum release-age gate and immutable image
digests. Before adding anything, check package identity, maintainers, provenance,
release age, licenses, and advisories — a fresh upload is exactly when a
supply-chain attack looks freshest. Lockfile mutation is kept separate from the
normal test images so ordinary builds stay frozen.

## Security and supply-chain gates

```sh
make audit            # pip-audit + pnpm audit
make audit-secrets    # pinned Gitleaks scan of owned files
make audit-compose    # render Compose and reject banned settings
make sbom             # Syft + CycloneDX for both production images
make audit-image      # Grype; fixable high/critical findings fail
```

`security/rankrat-cpython.openvex.json` holds narrow reviewed statements for
specific CPython stdlib findings whose affected code paths aren't reachable.
Security tests bind every statement to package/runtime evidence. Never add a VEX
statement just to turn a scanner green — document and test the call-path
justification, or don't add it.

## Local runtime

```sh
make run        # locally built stdio MCP
make run-http   # Compose Rankrat + Lighthouse on loopback HTTP
```

These targets call the same `rankrat` launcher published-image users get. They
default to `$HOME/.config/rankrat`; override that only with
`RANKRAT_PROFILE=/absolute/profile`. Config and credentials stay local and
gitignored. `make run-http` stays attached; use `rankrat http -d` with the same
profile for a detached, restartable deployment.

## CI and release surface

The GitHub pipeline:

- runs repository checks and coverage;
- publishes badges from the completed coverage artifact;
- builds/scans/publishes both Docker images;
- publishes tagged Rankrat releases to the MCP registry through OIDC;
- validates agent artifacts on every push and publishes them to ClawHub on tags.

Reusable workflows are pinned to reviewed commit SHAs. Registry publish waits on
the Rankrat image workflow; fixable high/critical image findings block the MCP
registry publication.

Change a public behavior and everything it touches moves in the same commit:

- OpenAPI YAML and generated JSON;
- MCP contracts and annotations;
- `.env.example`, boundary/Compose examples, and wrapper/Make help;
- root summary and the focused `docs/` guide;
- `.agents` skill/setup/plugin documentation;
- `CHANGELOG.md` when release behavior changes.

## Contribution checklist

1. Open an issue before a large behavior or contract change.
2. Keep changes focused and preserve boundary/security invariants.
3. Add unit, contract, integration, and security coverage proportional to the
   surface you touched.
4. Run format, lint, mocked tests, the relevant production-image tests, OpenAPI
   freshness, and the applicable audits.
5. Never put real credentials, OAuth records, live provider bodies, or personal
   site data in fixtures or docs.
6. Keep public docs observable and code-backed — if the code doesn't do it,
   don't write that it does.
