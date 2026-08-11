# Development

Rankrat's development toolchain runs in containers. A contributor needs Docker
and GNU Make; the pinned Python, uv, Node, pnpm, browsers, linters, test runners,
SBOM tools, and scanners live in project images.

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

The package uses Python 3.14 and strict Pydantic models at request, provider,
configuration, and persistence boundaries. The Lighthouse worker is TypeScript.

## Discover commands

```sh
make help
make version
```

Make target help is the command source of truth. Do not invoke host Python/pnpm
directly and accidentally test a different dependency graph.

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

The version in `pyproject.toml` is the local image-tag source.

## Format and lint

```sh
make format
make lint
make lint-fix
make lighthouse-format
make lighthouse-lint
```

`make lint` covers Python formatting, Ruff, Bandit, Pyright, strict mypy,
ShellCheck, shfmt, and the Lighthouse TypeScript formatter/linter/typecheck.
`lint-fix` applies only Python formatter/Ruff safe fixes; review every change.

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

`make test-local` reuses only the exact already-built versioned development
image. It is a registry-outage fallback, not the normal release gate; return to
fresh builds before release.

## Production transport tests

```sh
make test-image
make test-lighthouse-image
```

`test-image` exercises production startup, stdio MCP, loopback REST, and
authenticated Streamable HTTP MCP. `test-lighthouse-image` runs real public-page
Lighthouse audits through all three public transports.

The scripts create explicit temporary containers and paths for their run. Do
not replace their cleanup with blanket Docker removal/pruning.

## Live provider tests

Live tests are opt-in and use `.env` selectors plus the local boundary/secrets/
OAuth mounts:

```sh
make test-live
make test-live-google-search-console
make test-live-google-analytics
make test-live-pagespeed
make test-live-cloudflare
make test-live-bing
make test-live-http
```

IndexNow is a real write and requires an additional explicit opt-in:

```sh
RANKRAT_READ_ONLY=false \
RANKRAT_RUN_LIVE_INDEXNOW_SUBMISSION=true \
make test-live-indexnow
```

Leave selectors for unused providers blank. Mocked tests never need live
credentials. See [Providers and credentials](providers.md#live-provider-verification).

## Spec-first REST development

The REST contract is YAML-first:

- [`src/rankrat/api/openapi.yaml`](../src/rankrat/api/openapi.yaml) — base
  provider/operation surface;
- [`src/rankrat/api/seo-openapi.yaml`](../src/rankrat/api/seo-openapi.yaml) —
  intelligence, monitoring, Bing backlink, CrUX, and Cloudflare surface;
- [`openapi.json`](../openapi.json) — generated merged artifact.

After editing either source:

```sh
make generate-openapi
make check-openapi
```

`check-openapi` fails when the committed JSON is stale. Contract tests verify
operation IDs, runtime route parity, policy-dependent route removal, and the
snapshot. Do not hand-edit `openapi.json`.

MCP contracts are transport-neutral typed catalogs in
`src/rankrat/transports/tool_contracts.py` plus the SEO catalog in
`src/rankrat/transports/seo_mcp.py`. A feature is not complete until stdio MCP,
Streamable HTTP MCP, REST, contracts, and documentation agree where applicable.

## Dependency changes

Python dependencies are exact in `pyproject.toml`/`uv.lock`; Lighthouse uses an
exact pnpm lock. Dependency changes go through containerized targets:

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

The project applies a seven-day minimum release-age gate and immutable image
digests. Verify package identity, maintainers, provenance, release age,
licenses, and advisories before adding anything. Lockfile mutation is separate
from normal test images so normal builds remain frozen.

## Security and supply-chain gates

```sh
make audit            # pip-audit + pnpm audit
make audit-secrets    # pinned Gitleaks scan of owned files
make audit-compose    # render Compose and reject banned settings
make sbom             # Syft + CycloneDX for both production images
make audit-image      # Grype; fixable high/critical findings fail
```

`security/rankrat-cpython.openvex.json` contains narrow reviewed statements for
specific CPython stdlib findings whose affected code paths are not reachable.
Security tests bind every statement to package/runtime evidence. Do not add a
VEX statement merely to make a scanner green; document and test the call-path
justification.

## Local runtime

```sh
make run        # locally built stdio MCP
make run-http   # Compose Rankrat + Lighthouse on loopback HTTP
```

These targets call the same `rankrat.sh` wrapper used by published-image users.
Configuration and credentials remain local/gitignored. `make run-http` stays
attached; use `rankrat.sh http -d` with the same profile for a detached
restartable deployment.

## CI and release surface

The GitHub pipeline:

- runs repository checks and coverage;
- publishes badges from the completed coverage artifact;
- builds/scans/publishes both Docker images;
- publishes tagged Rankrat releases to the MCP registry through OIDC;
- validates agent artifacts on every push and publishes them to ClawHub on
  tags.

Reusable workflows are pinned to reviewed commit SHAs. Registry publish waits
for the Rankrat image workflow; fixable high/critical image findings block the
MCP registry publication.

When changing a public behavior, update in the same change:

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
   changed surface.
4. Run format, lint, mocked tests, relevant production-image tests, OpenAPI
   freshness, and applicable audits.
5. Never include real credentials, OAuth records, live provider bodies, or
   personal site data in fixtures/docs.
6. Keep public docs observable and code-backed.
