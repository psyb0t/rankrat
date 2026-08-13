IMAGE_NAME := psyb0t/rankrat
VERSION ?= $(shell awk -F\" '/^version *= *"/ {print $$2; exit}' pyproject.toml)
IMAGE_TAG := v$(VERSION)
DEV_IMAGE := $(IMAGE_NAME):dev-$(IMAGE_TAG)
LIGHTHOUSE_IMAGE_NAME := psyb0t/rankrat-lighthouse
LIGHTHOUSE_IMAGE := $(LIGHTHOUSE_IMAGE_NAME):$(IMAGE_TAG)
LIGHTHOUSE_LATEST_IMAGE := $(LIGHTHOUSE_IMAGE_NAME):latest
LIGHTHOUSE_DEV_IMAGE := $(LIGHTHOUSE_IMAGE_NAME):dev-$(IMAGE_TAG)
LIGHTHOUSE_LOCK_IMAGE := $(LIGHTHOUSE_IMAGE_NAME):lock-$(IMAGE_TAG)
RANKRAT_DEV_IMAGE_SOURCE ?= build
LOCK_IMAGE := $(IMAGE_NAME):lock-$(IMAGE_TAG)
SHELLCHECK_IMAGE := mirror.gcr.io/koalaman/shellcheck:v0.11.0@sha256:61862eba1fcf09a484ebcc6feea46f1782532571a34ed51fedf90dd25f925a8d
SHFMT_IMAGE := mirror.gcr.io/mvdan/shfmt:v3.13.1@sha256:f22f3936140be1ba02d493b5d2b91d0e8b4af93fd903e7f46c477822bca4a3be
GITLEAKS_IMAGE := ghcr.io/gitleaks/gitleaks:v8.30.1@sha256:c00b6bd0aeb3071cbcb79009cb16a60dd9e0a7c60e2be9ab65d25e6bc8abbb7f
SYFT_IMAGE := ghcr.io/anchore/syft:v1.49.0@sha256:9a9f85314017f1ea798fb012edfa7fe9259923910f82c8d4bc983ab5c765e60b
GRYPE_IMAGE := ghcr.io/anchore/grype:v0.116.0@sha256:fd4ab4d1042b522c896e73bdf09ab8bf384fa417df99d6dd0d6e1008c7e7c821
RANKRAT_PROFILE ?= $(HOME)/.config/rankrat
PROFILE_CONFIG := $(RANKRAT_PROFILE)/config
BOUNDARIES := $(PROFILE_CONFIG)/boundaries.json
SECRETS := $(RANKRAT_PROFILE)/secrets
OAUTH := $(RANKRAT_PROFILE)/oauth
STATE := $(RANKRAT_PROFILE)/state
OAUTH_CALLBACK_PORT ?= 49152
HTTP_PORT ?= 8080
HTTP_BEARER_SECRET_FILE ?= $(SECRETS)/rankrat/http-bearer-token
RANKRAT_READ_ONLY ?= false
ONBOARD_GOOGLE_ACCOUNT_ID ?=
ONBOARD_BING_ACCOUNT_ID ?=
ONBOARD_SITE_URL ?=
ONBOARD_DISPLAY_NAME ?=
ONBOARD_TIME_ZONE ?= Etc/UTC
ONBOARD_CURRENCY_CODE ?= USD
INDEXNOW_TARGET_ID ?=
INDEXNOW_HOST ?=
INDEXNOW_KEY_FILE ?= $(SECRETS)/indexnow/key
INDEXNOW_VERIFY_BOUNDARY_FILE := /tmp/rankrat-boundaries.json
INDEXNOW_VERIFY_KEY_FILE := /tmp/rankrat-indexnow-key
SBOM_DIR := $(PWD)/.sbom
SBOM_TMP_DIR := $(SBOM_DIR)/tmp
SBOM_ARCHIVE := $(SBOM_DIR)/rankrat-image.tar
SBOM_SYFT_JSON := $(SBOM_DIR)/rankrat.syft.json
SBOM_CYCLONEDX_JSON := $(SBOM_DIR)/rankrat.cyclonedx.json
LIGHTHOUSE_SBOM_ARCHIVE := $(SBOM_DIR)/rankrat-lighthouse-image.tar
LIGHTHOUSE_SBOM_SYFT_JSON := $(SBOM_DIR)/rankrat-lighthouse.syft.json
LIGHTHOUSE_SBOM_CYCLONEDX_JSON := $(SBOM_DIR)/rankrat-lighthouse.cyclonedx.json
VULNERABILITY_DB_DIR := $(PWD)/.grype-db
VULNERABILITY_REPORT := $(SBOM_DIR)/rankrat.grype.json
LIGHTHOUSE_VULNERABILITY_REPORT := $(SBOM_DIR)/rankrat-lighthouse.grype.json
CPYTHON_STDLIB_VEX := $(PWD)/security/rankrat-cpython.openvex.json
COVERAGE_LOG := $(PWD)/.coverage-report.log
COVERAGE_PERCENT_FILE := $(PWD)/coverage-percent.txt
BUMP_EXCLUDE_NEWER := bash scripts/bump-exclude-newer.sh
BUMP_LIGHTHOUSE_RELEASE_AGE := bash scripts/bump_lighthouse_minimum_release_age.sh
TOOLING_LOG_FLUSH_ATTEMPTS ?= 20
TOOLING_LOG_FLUSH_DELAY_SECONDS ?= 0.1
PKG_GROUP ?=
LIGHTHOUSE_PKG ?=
RANKRAT_WRAPPERS := rankrat
RANKRAT_RELEASE_VERSION := $(value V)

export RANKRAT_RELEASE_VERSION

UID := $(shell id -u)
GID := $(shell id -g)

# Every production-image invocation goes through the same wrapper users install,
# so `make run` exercises the path they actually take and the docker run flags
# exist in exactly one place. The wrapper reads all of this from the environment.
WRAPPER := RANKRAT_IMAGE=$(IMAGE_NAME):$(IMAGE_TAG) \
	RANKRAT_LIGHTHOUSE_IMAGE=$(LIGHTHOUSE_IMAGE) \
	RANKRAT_HTTP_PORT=$(HTTP_PORT) \
	RANKRAT_OAUTH_CALLBACK_PORT=$(OAUTH_CALLBACK_PORT) \
	RANKRAT_READ_ONLY=$(RANKRAT_READ_ONLY) \
	./rankrat --data-dir "$(RANKRAT_PROFILE)"

DEV_RUN := docker run --rm --init \
	--user $(UID):$(GID) \
	--cap-drop=ALL \
	--security-opt no-new-privileges:true \
	--pids-limit 256 \
	--tmpfs /tmp:rw,noexec,nosuid,size=256m \
	-e HOME=/tmp \
	-e XDG_CACHE_HOME=/tmp/cache \
	-e COVERAGE_FILE=/tmp/.coverage \
	-e PYTHONDONTWRITEBYTECODE=1 \
	-e RANKRAT_RELEASE_VERSION \
	-e PYTHONPATH=/work/src \
	-v $(PWD):/work \
	-w /work \
	$(DEV_IMAGE)

INDEXNOW_VERIFY_RUN := docker run --rm --init \
	--user $(UID):$(GID) \
	--network bridge \
	--read-only \
	--cap-drop=ALL \
	--security-opt no-new-privileges:true \
	--pids-limit 64 \
	--tmpfs /tmp:rw,noexec,nosuid,size=64m \
	-e HOME=/tmp \
	-e XDG_CACHE_HOME=/tmp/cache \
	-e PYTHONDONTWRITEBYTECODE=1 \
	-e PYTHONPATH=/work/src \
	--mount type=bind,src=$(PWD),dst=/work,readonly \
	--mount type=bind,src=$(BOUNDARIES),dst=$(INDEXNOW_VERIFY_BOUNDARY_FILE),readonly \
	--mount type=bind,src=$(INDEXNOW_KEY_FILE),dst=$(INDEXNOW_VERIFY_KEY_FILE),readonly \
	-w /work \
	$(DEV_IMAGE)

INDEXNOW_INIT_RUN := docker run --rm --init \
	--user $(UID):$(GID) \
	--cap-drop=ALL \
	--security-opt no-new-privileges:true \
	--pids-limit 64 \
	--tmpfs /tmp:rw,noexec,nosuid,size=64m \
	-e HOME=/tmp \
	-e XDG_CACHE_HOME=/tmp/cache \
	-e PYTHONDONTWRITEBYTECODE=1 \
	-e PYTHONPATH=/work/src \
	--mount type=bind,src=$(PWD),dst=/work,readonly \
	--mount type=bind,src=$(PROFILE_CONFIG),dst=/profile/config \
	--mount type=bind,src=$(RANKRAT_PROFILE)/secrets/indexnow,dst=/profile/secrets/indexnow \
	-w /work \
	$(DEV_IMAGE)

LOCK_RUN := docker run --rm --init \
	--user $(UID):$(GID) \
	--network bridge \
	--cap-drop=ALL \
	--security-opt no-new-privileges:true \
	--pids-limit 128 \
	--tmpfs /tmp:rw,noexec,nosuid,mode=1777,uid=$(UID),gid=$(GID),size=256m \
	-e HOME=/tmp \
	-e UV_CACHE_DIR=/tmp/uv-cache \
	-e PYTHONDONTWRITEBYTECODE=1 \
	-v $(PWD):/work \
	-w /work \
	$(LOCK_IMAGE)

LIGHTHOUSE_DEV_RUN := docker run --rm --init \
	--user $(UID):$(GID) \
	--network none \
	--cap-drop=ALL \
	--security-opt no-new-privileges:true \
	--pids-limit 256 \
	--tmpfs /tmp:rw,noexec,nosuid,size=256m \
	-e HOME=/tmp \
	-w /app \
	$(LIGHTHOUSE_DEV_IMAGE)

LIGHTHOUSE_MUTATE_RUN := docker run --rm --init \
	--user $(UID):$(GID) \
	--network bridge \
	--cap-drop=ALL \
	--security-opt no-new-privileges:true \
	--pids-limit 256 \
	--tmpfs /tmp:rw,noexec,nosuid,size=256m \
	-e HOME=/tmp \
	-v $(PWD)/lighthouse-worker:/work \
	-w /work \
	$(LIGHTHOUSE_LOCK_IMAGE)

.PHONY: help version dev-image lighthouse-dev-image lighthouse-lock-image lighthouse-image rankrat-image lock-image setup init-indexnow verify-indexnow-key shell dep pkg-lock pkg-add pkg-update pkg-upgrade pkg-remove lighthouse-pkg-lock lighthouse-pkg-add lighthouse-pkg-update lighthouse-pkg-upgrade lighthouse-pkg-remove \
	lint lighthouse-lint lint-fix format lighthouse-format test lighthouse-test test-local test-unit test-contract test-integration test-security test-live test-live-one test-live-google-search-console test-live-google-analytics test-live-google-tag-manager test-live-pagespeed test-live-cloudflare test-live-clarity test-live-bing test-live-indexnow test-live-http test-image test-lighthouse-image \
	test-tooling test-coverage coverage-percent audit audit-secrets audit-compose audit-image sbom build build-test run run-http \
	auth-google oauth-revoke onboard-site clean generate generate-openapi check-openapi

help: ## Show supported Rankrat commands
	@awk 'BEGIN {FS = ":.*##"}; /^[a-zA-Z0-9_.-]+:.*##/ {printf "%-20s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

version: dev-image ## Print the release tag, or update every static version carrier: make version V=X.Y.Z
ifndef V
	@echo $(IMAGE_TAG)
else
	$(DEV_RUN) sh -ceu 'printf "%s\n" "$$RANKRAT_RELEASE_VERSION" | grep -qE "^[0-9]+\.[0-9]+\.[0-9]+$$" || { echo "RANKRAT_RELEASE_VERSION must be a release version (X.Y.Z)" >&2; exit 1; }'
	$(DEV_RUN) sh -ceu 'uv version --no-sync "$$RANKRAT_RELEASE_VERSION" >/dev/null'
	$(DEV_RUN) node -e 'const fs = require("node:fs"); const path = ".agents/.codex-plugin/plugin.json"; if (fs.existsSync(path)) { const manifest = JSON.parse(fs.readFileSync(path, "utf8")); manifest.version = process.env.RANKRAT_RELEASE_VERSION; fs.writeFileSync(path, JSON.stringify(manifest, null, 2) + "\n", "utf8"); }'
	$(DEV_RUN) sh -ceu 'source_file="src/rankrat/api/openapi.yaml"; temporary_file="$$(mktemp)"; trap '\''rm -f "$$temporary_file"'\'' EXIT; sed -E "0,/^  version: \"[^\"]+\"$$/s//  version: \"$$RANKRAT_RELEASE_VERSION\"/" "$$source_file" >"$$temporary_file"; if ! cmp -s "$$source_file" "$$temporary_file"; then mv "$$temporary_file" "$$source_file"; fi'
	@$(MAKE) --no-print-directory generate-openapi
	@echo "[make version] updated static version carriers to v$$RANKRAT_RELEASE_VERSION; run git-update.sh to commit and tag"
endif

dev-image: ## Build the sandboxed development image
	@case "$(RANKRAT_DEV_IMAGE_SOURCE)" in \
		build) docker build -f Dockerfile.dev -t $(DEV_IMAGE) . ;; \
		local) docker image inspect "$(DEV_IMAGE)" >/dev/null 2>&1 || { echo "local Rankrat development image is missing: $(DEV_IMAGE)" >&2; exit 1; }; echo "using existing local Rankrat development image: $(DEV_IMAGE)" ;; \
		*) echo "RANKRAT_DEV_IMAGE_SOURCE must be build or local, got: $(RANKRAT_DEV_IMAGE_SOURCE)" >&2; exit 1 ;; \
	esac

lighthouse-dev-image: ## Build the pinned Playwright/Lighthouse development stage
	docker build --target development -f Dockerfile.lighthouse -t $(LIGHTHOUSE_DEV_IMAGE) .

lighthouse-lock-image: ## Build the sandboxed Lighthouse lockfile mutation image
	docker build --target lock -f Dockerfile.lighthouse -t $(LIGHTHOUSE_LOCK_IMAGE) .

lighthouse-image: ## Build the hardened Lighthouse companion image
	docker build -f Dockerfile.lighthouse -t $(LIGHTHOUSE_IMAGE) -t $(LIGHTHOUSE_LATEST_IMAGE) .

lock-image: ## Build the minimal, sandboxed Python-version-transition lock image
	docker build -f Dockerfile.lock -t $(LOCK_IMAGE) .

setup: rankrat-image ## Create a local profile, guide credentials/OAuth, and validate providers
	$(WRAPPER) setup

init-indexnow: dev-image ## Create one operator-selected IndexNow target without uploading or submitting
	@test -n "$(INDEXNOW_TARGET_ID)" || (echo "INDEXNOW_TARGET_ID is required" >&2; exit 1)
	@test -n "$(INDEXNOW_HOST)" || (echo "INDEXNOW_HOST is required" >&2; exit 1)
	@test -f "$(BOUNDARIES)" || (echo "$(BOUNDARIES) is required; run rankrat setup first" >&2; exit 1)
	@test -d "$(SECRETS)/indexnow" || (echo "$(SECRETS)/indexnow is required; run rankrat setup first" >&2; exit 1)
	$(INDEXNOW_INIT_RUN) uv run --frozen --no-sync python scripts/init_indexnow.py \
		--boundary-file /profile/config/boundaries.json \
		--key-file /profile/secrets/indexnow/key \
		--target-id "$(INDEXNOW_TARGET_ID)" --host "$(INDEXNOW_HOST)"

verify-indexnow-key: dev-image ## Verify the deployed IndexNow key directly without submitting URLs
	@test -n "$(INDEXNOW_TARGET_ID)" || (echo "INDEXNOW_TARGET_ID is required" >&2; exit 1)
	@test -f "$(BOUNDARIES)" || (echo "$(BOUNDARIES) is required" >&2; exit 1)
	@test -f "$(INDEXNOW_KEY_FILE)" || (echo "$(INDEXNOW_KEY_FILE) is required" >&2; exit 1)
	$(INDEXNOW_VERIFY_RUN) uv run --frozen --no-sync python scripts/verify_indexnow_public_key.py \
		--boundary-file $(INDEXNOW_VERIFY_BOUNDARY_FILE) --key-file $(INDEXNOW_VERIFY_KEY_FILE) \
		--target-id "$(INDEXNOW_TARGET_ID)"

shell: dev-image ## Start a shell in the development container
	$(DEV_RUN) sh

dep: dev-image ## Verify frozen development dependencies in the dev container
	$(DEV_RUN) uv lock --check

pkg-lock: lock-image ## Refresh uv.lock under the frozen age gate with the declared Python interpreter
	$(LOCK_RUN) uv lock

pkg-add: lock-image ## Add a package (usage: make pkg-add PKG=name==version [PKG_GROUP=dev])
	@test -n "$(PKG)" || (echo "usage: make pkg-add PKG=name==version" >&2; exit 1)
	$(BUMP_EXCLUDE_NEWER)
	$(LOCK_RUN) uv add --no-sync $(if $(PKG_GROUP),--group "$(PKG_GROUP)") "$(PKG)"

pkg-update: lock-image ## Upgrade one package (usage: make pkg-update PKG=name)
	@test -n "$(PKG)" || (echo "usage: make pkg-update PKG=name" >&2; exit 1)
	$(BUMP_EXCLUDE_NEWER)
	$(LOCK_RUN) uv lock --upgrade-package "$(PKG)"

pkg-upgrade: lock-image ## Upgrade all packages after advancing the age gate
	$(BUMP_EXCLUDE_NEWER)
	$(LOCK_RUN) uv lock --upgrade

pkg-remove: lock-image ## Remove a package (usage: make pkg-remove PKG=name [PKG_GROUP=dev])
	@test -n "$(PKG)" || (echo "usage: make pkg-remove PKG=name" >&2; exit 1)
	$(BUMP_EXCLUDE_NEWER)
	$(LOCK_RUN) uv remove --no-sync $(if $(PKG_GROUP),--group "$(PKG_GROUP)") "$(PKG)"

lighthouse-pkg-lock: lighthouse-lock-image ## Refresh the frozen Lighthouse pnpm lockfile
	$(LIGHTHOUSE_MUTATE_RUN) pnpm install --lockfile-only --ignore-scripts

lighthouse-pkg-add: lighthouse-lock-image ## Add an exact Lighthouse dependency (LIGHTHOUSE_PKG=name@version)
	@test -n "$(LIGHTHOUSE_PKG)" || (echo "usage: make lighthouse-pkg-add LIGHTHOUSE_PKG=name@version" >&2; exit 1)
	$(BUMP_LIGHTHOUSE_RELEASE_AGE)
	$(LIGHTHOUSE_MUTATE_RUN) pnpm add --save-exact --ignore-scripts "$(LIGHTHOUSE_PKG)"

lighthouse-pkg-update: lighthouse-lock-image ## Update one Lighthouse dependency (LIGHTHOUSE_PKG=name@version)
	@test -n "$(LIGHTHOUSE_PKG)" || (echo "usage: make lighthouse-pkg-update LIGHTHOUSE_PKG=name@version" >&2; exit 1)
	$(BUMP_LIGHTHOUSE_RELEASE_AGE)
	$(LIGHTHOUSE_MUTATE_RUN) pnpm update --save-exact --ignore-scripts "$(LIGHTHOUSE_PKG)"

lighthouse-pkg-upgrade: lighthouse-lock-image ## Update all Lighthouse dependencies under the age gate
	$(BUMP_LIGHTHOUSE_RELEASE_AGE)
	$(LIGHTHOUSE_MUTATE_RUN) pnpm update --latest --save-exact --ignore-scripts

lighthouse-pkg-remove: lighthouse-lock-image ## Remove one Lighthouse dependency (LIGHTHOUSE_PKG=name)
	@test -n "$(LIGHTHOUSE_PKG)" || (echo "usage: make lighthouse-pkg-remove LIGHTHOUSE_PKG=name" >&2; exit 1)
	$(BUMP_LIGHTHOUSE_RELEASE_AGE)
	$(LIGHTHOUSE_MUTATE_RUN) pnpm remove --ignore-scripts "$(LIGHTHOUSE_PKG)"

lint: lighthouse-lint dev-image ## Run format, lint, and type checks in the dev containers
	$(DEV_RUN) uv run --frozen --no-sync ruff format --check .
	$(DEV_RUN) uv run --frozen --no-sync ruff check .
	$(DEV_RUN) uv run --frozen --no-sync bandit -q -r src
	$(DEV_RUN) uv run --frozen --no-sync pyright
	$(DEV_RUN) uv run --frozen --no-sync mypy --cache-dir /tmp/mypy src
	docker run --rm --init --user $(UID):$(GID) --network none --cap-drop=ALL \
		--security-opt no-new-privileges:true --pids-limit 64 --memory 128m --cpus 0.5 \
		-v $(PWD):/mnt:ro -w /mnt $(SHELLCHECK_IMAGE) $(RANKRAT_WRAPPERS) scripts/*.sh
	docker run --rm --init --user $(UID):$(GID) --network none --cap-drop=ALL \
		--security-opt no-new-privileges:true --pids-limit 64 --memory 128m --cpus 0.5 \
		-v $(PWD):/mnt:ro -w /mnt $(SHFMT_IMAGE) -d $(RANKRAT_WRAPPERS) scripts

lighthouse-lint: lighthouse-dev-image ## Run Lighthouse worker formatting, lint, and type checks
	$(LIGHTHOUSE_DEV_RUN) pnpm format:check
	$(LIGHTHOUSE_DEV_RUN) pnpm lint

lint-fix: dev-image ## Apply safe lint and formatting fixes in the dev container
	$(DEV_RUN) uv run --frozen --no-sync ruff check --fix .
	$(DEV_RUN) uv run --frozen --no-sync ruff format .

format: lighthouse-format dev-image ## Apply Python, TypeScript, and shell formatting
	$(DEV_RUN) uv run --frozen --no-sync ruff format .
	docker run --rm --init --user $(UID):$(GID) --network none --cap-drop=ALL \
		--security-opt no-new-privileges:true --pids-limit 64 --memory 128m --cpus 0.5 \
		-v $(PWD):/mnt -w /mnt $(SHFMT_IMAGE) -w $(RANKRAT_WRAPPERS) scripts

lighthouse-format: lighthouse-dev-image ## Format Lighthouse worker source and tests
	docker run --rm --init --user $(UID):$(GID) --network none --cap-drop=ALL \
		--security-opt no-new-privileges:true --pids-limit 128 \
		--tmpfs /tmp:rw,noexec,nosuid,size=128m -e HOME=/tmp \
		-v $(PWD)/lighthouse-worker:/work -w /app $(LIGHTHOUSE_DEV_IMAGE) \
		pnpm prettier --write /work/src /work/tests /work/package.json /work/tsconfig.json /work/tsconfig.build.json /work/eslint.config.js
	@$(MAKE) --no-print-directory lighthouse-dev-image

test: lighthouse-test test-unit test-contract test-integration test-security test-tooling ## Run all mocked tests

lighthouse-test: lighthouse-dev-image ## Run the Lighthouse worker unit suite
	$(LIGHTHOUSE_DEV_RUN) pnpm test

test-local: ## Run all mocked tests with the existing versioned development image
	@$(MAKE) --no-print-directory RANKRAT_DEV_IMAGE_SOURCE=local test

test-unit: dev-image ## Run unit tests in the dev container
	$(DEV_RUN) uv run --frozen --no-sync pytest -p no:cacheprovider tests/unit

test-contract: dev-image ## Run transport contract tests in the dev container
	$(DEV_RUN) uv run --frozen --no-sync pytest -p no:cacheprovider tests/contract

test-integration: dev-image ## Run integration tests in the dev container
	$(DEV_RUN) uv run --frozen --no-sync pytest -p no:cacheprovider tests/integration

test-security: dev-image ## Run security regression tests in the dev container
	$(DEV_RUN) uv run --frozen --no-sync pytest -p no:cacheprovider tests/security

test-tooling: dev-image ## Exercise dependency age-gate tooling in container-local scratch
	$(DEV_RUN) sh -ec 'require_fragment() { grep -Fq -- "$$2" "/work/$$1" || { echo "missing required $$1 fragment: $$2" >&2; exit 1; }; }; wait_for_log() { attempts=1; while ! test -s "$$1" && [ "$$attempts" -le "$(TOOLING_LOG_FLUSH_ATTEMPTS)" ]; do sleep "$(TOOLING_LOG_FLUSH_DELAY_SECONDS)"; attempts=$$((attempts + 1)); done; test -s "$$1"; }; scratch=$$(mktemp -d); cp pyproject.toml scripts/bump-exclude-newer.sh "$$scratch"; cd "$$scratch"; LOG_FILE="$$scratch/bump.log" bash bump-exclude-newer.sh; wait_for_log "$$scratch/bump.log" || { echo "dependency age-gate log was not created" >&2; exit 1; }; test "$$(grep -c "^exclude-newer =" pyproject.toml)" -eq 1 || { echo "dependency age-gate setting is not unique" >&2; exit 1; }; require_fragment Makefile "RANKRAT_PROFILE ?= \$$(HOME)/.config/rankrat"; require_fragment Makefile "./rankrat --data-dir \"\$$(RANKRAT_PROFILE)\""; require_fragment Makefile "RANKRAT_LIGHTHOUSE_IMAGE=\$$(LIGHTHOUSE_IMAGE)"; require_fragment Makefile "INDEXNOW_TARGET_ID is required"; require_fragment Makefile "--boundary-file /profile/config/boundaries.json"; require_fragment Makefile "RANKRAT_OAUTH_TOKEN_ROOT=/run/oauth"; require_fragment Makefile "test-live-google-analytics: LIVE_SELECTOR := test_live_google_analytics or test_live_ga4"; require_fragment Makefile "WRAPPER) stdio"; require_fragment Makefile "WRAPPER) http"; require_fragment rankrat "CONTAINER_OAUTH_TOKEN_ROOT=\"/run/oauth\""; require_fragment rankrat "COMPOSE_FILE_RELATIVE_PATH=\"docker-compose.yml\""; require_fragment rankrat "--project-directory \"\$$profile_directory\""; require_fragment rankrat "--detach"; grep -Fq '"'"'"accounts"'"'"' /work/config/boundaries.json.example; grep -Fq "\$${RANKRAT_DATA_DIR:-.}/secrets:/run/secrets:ro" /work/docker-compose.yml'
	$(DEV_RUN) sh -ec 'wait_for_log() { attempts=1; while ! test -s "$$1" && [ "$$attempts" -le "$(TOOLING_LOG_FLUSH_ATTEMPTS)" ]; do sleep "$(TOOLING_LOG_FLUSH_DELAY_SECONDS)"; attempts=$$((attempts + 1)); done; test -s "$$1"; }; scratch=$$(mktemp -d); mkdir -p "$$scratch/lighthouse-worker"; cp scripts/bump_lighthouse_minimum_release_age.sh "$$scratch"; cp lighthouse-worker/pnpm-workspace.yaml "$$scratch/lighthouse-worker"; cd "$$scratch"; LOG_FILE="$$scratch/bump-lighthouse.log" bash bump_lighthouse_minimum_release_age.sh; wait_for_log "$$scratch/bump-lighthouse.log" || { echo "Lighthouse dependency age-gate log was not created" >&2; exit 1; }; test "$$(grep -c "^minimumReleaseAge: 10080$$" lighthouse-worker/pnpm-workspace.yaml)" -eq 1 || { echo "Lighthouse dependency age gate is not exact" >&2; exit 1; }; grep -Fq -- "- brace-expansion@5.0.9" lighthouse-worker/pnpm-workspace.yaml; grep -Fq "brace-expansion: 5.0.9" lighthouse-worker/pnpm-workspace.yaml'

test-live: dev-image ## Run every configured provider and shipped transport check
	@$(MAKE) --no-print-directory test-live-google-search-console RANKRAT_DEV_IMAGE_SOURCE=local
	@$(MAKE) --no-print-directory test-live-google-analytics RANKRAT_DEV_IMAGE_SOURCE=local
	@$(MAKE) --no-print-directory test-live-google-tag-manager RANKRAT_DEV_IMAGE_SOURCE=local
	@$(MAKE) --no-print-directory test-live-pagespeed RANKRAT_DEV_IMAGE_SOURCE=local
	@$(MAKE) --no-print-directory test-live-cloudflare RANKRAT_DEV_IMAGE_SOURCE=local
	@$(MAKE) --no-print-directory test-live-clarity RANKRAT_DEV_IMAGE_SOURCE=local
	@$(MAKE) --no-print-directory test-live-bing RANKRAT_DEV_IMAGE_SOURCE=local
	@$(MAKE) --no-print-directory test-live-indexnow RANKRAT_DEV_IMAGE_SOURCE=local
	@$(MAKE) --no-print-directory test-live-http RANKRAT_DEV_IMAGE_SOURCE=local

test-live-google-search-console: LIVE_SELECTOR := test_live_google_search_console_matches_mocked_contract or test_live_google_search_console_unique_read_operations
test-live-google-search-console: test-live-one ## Run configured Google Search Console and Indexing metadata checks

test-live-google-analytics: LIVE_SELECTOR := test_live_google_analytics or test_live_ga4
test-live-google-analytics: test-live-one ## Run configured GA4 report and discovery checks

test-live-google-tag-manager: LIVE_SELECTOR := test_live_google_tag_manager
test-live-google-tag-manager: test-live-one ## Run configured Google Tag Manager account read checks

test-live-pagespeed: LIVE_SELECTOR := test_live_pagespeed
test-live-pagespeed: test-live-one ## Run configured PageSpeed key and analysis checks

test-live-cloudflare: LIVE_SELECTOR := test_live_cloudflare
test-live-cloudflare: test-live-one ## Run configured Cloudflare readiness and analytics checks

test-live-clarity: LIVE_SELECTOR := test_live_clarity
test-live-clarity: test-live-one ## Run configured Microsoft Clarity export checks

test-live-bing: LIVE_SELECTOR := test_live_bing
test-live-bing: test-live-one ## Run configured Bing Webmaster checks

test-live-indexnow: LIVE_SELECTOR := test_live_indexnow
test-live-indexnow: test-live-one ## Run the double-opt-in IndexNow submission check

test-live-http: build dev-image ## Exercise configured reads through the shipped production HTTP and MCP transports
	@test -f "$(BOUNDARIES)" || (echo "$(BOUNDARIES) is required" >&2; exit 1)
	@test -d "$(SECRETS)" || (echo "$(SECRETS) is required" >&2; exit 1)
	@test -d "$(OAUTH)" || (echo "$(OAUTH) is required" >&2; exit 1)
	@test -f "$(HTTP_BEARER_SECRET_FILE)" || (echo "$(HTTP_BEARER_SECRET_FILE) is required for live HTTP tests" >&2; exit 1)
	bash scripts/test_live_http_image.sh \
		"$(IMAGE_NAME):$(IMAGE_TAG)" "$(DEV_IMAGE)" "$(BOUNDARIES)" "$(SECRETS)" \
		"$(OAUTH)" "$(PWD)"

test-live-one: dev-image ## Run one selected opt-in live-provider test group
	@test -f "$(BOUNDARIES)" || (echo "$(BOUNDARIES) is required" >&2; exit 1)
	@test -d "$(PROFILE_CONFIG)" || (echo "$(PROFILE_CONFIG) is required" >&2; exit 1)
	@test -d "$(SECRETS)" || (echo "$(SECRETS) is required" >&2; exit 1)
	@test -d "$(OAUTH)" || (echo "$(OAUTH) is required" >&2; exit 1)
	docker run --rm --init --user $(UID):$(GID) --cap-drop=ALL \
		--security-opt no-new-privileges:true --pids-limit 128 \
		--tmpfs /tmp:rw,noexec,nosuid,size=256m \
		-e HOME=/tmp -e XDG_CACHE_HOME=/tmp/cache -e PYTHONDONTWRITEBYTECODE=1 \
		-e PYTHONPATH=/work/src -e RANKRAT_RUN_LIVE_TESTS=true \
		-e RANKRAT_BOUNDARY_FILE=/run/config/boundaries.json \
		-e RANKRAT_SECRET_ROOT=/run/secrets \
		-e RANKRAT_OAUTH_TOKEN_ROOT=/run/oauth \
		--mount type=bind,src=$(PROFILE_CONFIG),dst=/run/config,readonly \
		--mount type=bind,src=$(SECRETS),dst=/run/secrets,readonly \
		--mount type=bind,src=$(OAUTH),dst=/run/oauth \
		-v $(PWD):/work -w /work $(DEV_IMAGE) \
		uv run --frozen --no-sync pytest -p no:cacheprovider -m live -k "$(LIVE_SELECTOR)" tests/live

test-image: build ## Smoke-test both production images, stdio MCP, and loopback HTTP
	bash scripts/test_final_image.sh $(IMAGE_NAME):$(IMAGE_TAG)
	bash scripts/test_lighthouse_image.sh $(IMAGE_NAME):$(IMAGE_TAG) $(LIGHTHOUSE_IMAGE)

test-lighthouse-image: build ## Run real Lighthouse audits through production REST and both MCP transports
	bash scripts/test_lighthouse_image.sh $(IMAGE_NAME):$(IMAGE_TAG) $(LIGHTHOUSE_IMAGE)

test-coverage: lighthouse-test dev-image ## Run every test with Python coverage reporting
	$(DEV_RUN) uv run --frozen --no-sync pytest -p no:cacheprovider --cov=rankrat --cov-report=term tests

# create-badges.yml is a dumb reader: it renders whatever number is in
# coverage-percent.txt and fails when the file is absent, so producing that
# number is this Makefile's job. The report goes to a log instead of a pipe
# because the default Make shell is /bin/sh, which has no pipefail -- a pipe
# would swallow a failing test run and publish a badge for a red build.
coverage-percent: ## Write the total coverage percentage to coverage-percent.txt for the badges job
	@$(MAKE) --no-print-directory test-coverage > $(COVERAGE_LOG) 2>&1 \
		|| { cat $(COVERAGE_LOG); rm -f $(COVERAGE_LOG); exit 1; }
	@cat $(COVERAGE_LOG)
	@awk '/^TOTAL/ { gsub("%", "", $$NF); print $$NF }' $(COVERAGE_LOG) > $(COVERAGE_PERCENT_FILE)
	@rm -f $(COVERAGE_LOG)
	@test -s $(COVERAGE_PERCENT_FILE) \
		|| { echo "no TOTAL line in the coverage report" >&2; rm -f $(COVERAGE_PERCENT_FILE); exit 1; }
	@echo "coverage: $$(cat $(COVERAGE_PERCENT_FILE))%"

audit: lighthouse-lock-image dev-image ## Audit locked Python and Lighthouse dependencies
	$(DEV_RUN) uv run --frozen --no-sync pip-audit
	$(LIGHTHOUSE_MUTATE_RUN) pnpm audit --audit-level high

audit-secrets: ## Scan Rankrat-owned files for credentials with pinned Gitleaks
	@bash -euo pipefail -c 'scan_root=$$(mktemp -d "$(PWD)/.gitleaks-scan.XXXXXX"); trap '\''rm -rf "$$scan_root"'\'' EXIT; git ls-files -co --exclude-standard -z | while IFS= read -r -d "" path; do if [[ -e "$$path" || -L "$$path" ]]; then printf "%s\0" "$$path"; fi; done | tar --null --files-from=- --create | tar --extract --directory "$$scan_root"; docker run --rm --init --user $(UID):$(GID) --network none --cap-drop=ALL --security-opt no-new-privileges:true --pids-limit 64 --memory 128m --cpus 0.5 --mount type=bind,src="$$scan_root",dst=/repo,readonly $(GITLEAKS_IMAGE) dir --no-banner --no-color --redact --config=/repo/.gitleaks.toml /repo'

audit-compose: dev-image ## Reject banned Docker Compose settings
	docker compose config --quiet
	$(DEV_RUN) sh -ec 'if grep -nE "privileged:[[:space:]]*true|pid:[[:space:]]*host|ipc:[[:space:]]*host|network:[[:space:]]*host|userns_mode:[[:space:]]*host|/var/run/docker\\.sock" docker-compose.yml; then exit 1; fi; grep -Fq "\$${RANKRAT_DATA_DIR:-.}/secrets:/run/secrets:ro" docker-compose.yml'

sbom: build ## Generate Syft and CycloneDX SBOMs from both production images
	mkdir -p "$(SBOM_DIR)" "$(SBOM_TMP_DIR)"
	docker image save --output "$(SBOM_ARCHIVE)" "$(IMAGE_NAME):$(IMAGE_TAG)"
	docker image save --output "$(LIGHTHOUSE_SBOM_ARCHIVE)" "$(LIGHTHOUSE_IMAGE)"
	@set -eu; trap 'find "$(SBOM_TMP_DIR)" -mindepth 1 -delete' EXIT; \
	docker run --rm --init --user $(UID):$(GID) --network none --read-only --cap-drop=ALL \
		--security-opt no-new-privileges:true --pids-limit 128 --memory 2g --cpus 1 \
		--tmpfs /tmp:rw,noexec,nosuid,mode=1777,uid=$(UID),gid=$(GID),size=64m \
		-e HOME=/tmp -e TMPDIR=/work/tmp -e SYFT_CHECK_FOR_APP_UPDATE=false \
		--mount type=bind,src=$(SBOM_DIR),dst=/work \
		$(SYFT_IMAGE) scan "docker-archive:/work/rankrat-image.tar" \
		-o "syft-json=/work/rankrat.syft.json" \
		-o "cyclonedx-json=/work/rankrat.cyclonedx.json"
	@set -eu; trap 'find "$(SBOM_TMP_DIR)" -mindepth 1 -delete' EXIT; \
	docker run --rm --init --user $(UID):$(GID) --network none --read-only --cap-drop=ALL \
		--security-opt no-new-privileges:true --pids-limit 128 --memory 2g --cpus 1 \
		--tmpfs /tmp:rw,noexec,nosuid,mode=1777,uid=$(UID),gid=$(GID),size=64m \
		-e HOME=/tmp -e TMPDIR=/work/tmp -e SYFT_CHECK_FOR_APP_UPDATE=false \
		--mount type=bind,src=$(SBOM_DIR),dst=/work \
		$(SYFT_IMAGE) scan "docker-archive:/work/rankrat-lighthouse-image.tar" \
		-o "syft-json=/work/rankrat-lighthouse.syft.json" \
		-o "cyclonedx-json=/work/rankrat-lighthouse.cyclonedx.json"

audit-image: sbom ## Refresh Grype's vulnerability DB then fail for fixable high or critical image findings
	mkdir -p "$(VULNERABILITY_DB_DIR)"
	docker run --rm --init --user $(UID):$(GID) --network bridge --cap-drop=ALL \
		--security-opt no-new-privileges:true --pids-limit 128 --memory 2g --cpus 1 \
		--tmpfs /tmp:rw,noexec,nosuid,mode=1777,uid=$(UID),gid=$(GID),size=256m \
		-e HOME=/tmp \
		-e GRYPE_DB_CACHE_DIR=/cache -e GRYPE_CHECK_FOR_APP_UPDATE=false \
		-e GRYPE_EXTERNAL_SOURCES_ENABLE=false \
		--mount type=bind,src=$(VULNERABILITY_DB_DIR),dst=/cache \
		$(GRYPE_IMAGE) db update
	docker run --rm --init --user $(UID):$(GID) --network none --read-only --cap-drop=ALL \
		--security-opt no-new-privileges:true --pids-limit 128 --memory 512m --cpus 1 \
		--tmpfs /tmp:rw,noexec,nosuid,mode=1777,uid=$(UID),gid=$(GID),size=256m \
		-e HOME=/tmp \
		-e GRYPE_DB_CACHE_DIR=/cache -e GRYPE_DB_AUTO_UPDATE=false \
		-e GRYPE_CHECK_FOR_APP_UPDATE=false -e GRYPE_EXTERNAL_SOURCES_ENABLE=false \
		--mount type=bind,src=$(VULNERABILITY_DB_DIR),dst=/cache \
		--mount type=bind,src=$(SBOM_DIR),dst=/work \
		--mount type=bind,src=$(CPYTHON_STDLIB_VEX),dst=/work/rankrat-cpython.openvex.json,readonly \
		$(GRYPE_IMAGE) "sbom:/work/rankrat.syft.json" --vex /work/rankrat-cpython.openvex.json --only-fixed --fail-on high \
		-o "json=/work/rankrat.grype.json"
	docker run --rm --init --user $(UID):$(GID) --network none --read-only --cap-drop=ALL \
		--security-opt no-new-privileges:true --pids-limit 128 --memory 512m --cpus 1 \
		--tmpfs /tmp:rw,noexec,nosuid,mode=1777,uid=$(UID),gid=$(GID),size=256m \
		-e HOME=/tmp \
		-e GRYPE_DB_CACHE_DIR=/cache -e GRYPE_DB_AUTO_UPDATE=false \
		-e GRYPE_CHECK_FOR_APP_UPDATE=false -e GRYPE_EXTERNAL_SOURCES_ENABLE=false \
		--mount type=bind,src=$(VULNERABILITY_DB_DIR),dst=/cache \
		--mount type=bind,src=$(SBOM_DIR),dst=/work \
		$(GRYPE_IMAGE) "sbom:/work/rankrat-lighthouse.syft.json" --only-fixed --fail-on high \
		-o "json=/work/rankrat-lighthouse.grype.json"

rankrat-image: ## Build only the Rankrat production image
	docker build -f Dockerfile -t $(IMAGE_NAME):$(IMAGE_TAG) -t $(IMAGE_NAME):latest .

build: lighthouse-image rankrat-image ## Build Rankrat and its Lighthouse companion images

build-test: dev-image ## Build the development image used by tests and linting

run: rankrat-image ## Run the production image as a stdio MCP server
	$(WRAPPER) stdio

run-http: build ## Run Rankrat, HTTP MCP, and Lighthouse through Docker Compose
	$(WRAPPER) http

auth-google: rankrat-image ## Authorize the one configured Google account through host-loopback OAuth
	$(WRAPPER) auth-google --print-authorization-url

oauth-revoke: rankrat-image ## Revoke the one configured Google OAuth account authorization
	$(WRAPPER) revoke-google

onboard-site: rankrat-image ## Create GA4, Search Console, and Bing resources for one new HTTPS site and record boundaries
	@test -n "$(ONBOARD_SITE_URL)" || (echo "ONBOARD_SITE_URL is required" >&2; exit 1)
	$(WRAPPER) onboard-site \
		--google-account-id "$(ONBOARD_GOOGLE_ACCOUNT_ID)" \
		--bing-account-id "$(ONBOARD_BING_ACCOUNT_ID)" \
		--site-url "$(ONBOARD_SITE_URL)" \
		--display-name "$(ONBOARD_DISPLAY_NAME)" \
		--time-zone "$(ONBOARD_TIME_ZONE)" \
		--currency-code "$(ONBOARD_CURRENCY_CODE)"

generate: generate-openapi ## Generate all checked-in API artifacts

generate-openapi: dev-image ## Generate openapi.json from the YAML-first OAS source
	$(DEV_RUN) uv run --frozen --no-sync python scripts/generate_openapi.py

check-openapi: dev-image ## Fail if the JSON OpenAPI artifact is stale
	$(DEV_RUN) uv run --frozen --no-sync python scripts/generate_openapi.py --check

clean: ## Remove only Rankrat images built by these Make targets
	-docker image rm $(IMAGE_NAME):$(IMAGE_TAG) $(IMAGE_NAME):latest $(DEV_IMAGE) \
		$(LIGHTHOUSE_IMAGE) $(LIGHTHOUSE_LATEST_IMAGE) $(LIGHTHOUSE_DEV_IMAGE) \
		$(LIGHTHOUSE_LOCK_IMAGE)
