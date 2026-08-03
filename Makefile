IMAGE_NAME := psyb0t/rankrat
VERSION ?= $(shell awk -F\" '/^version *= *"/ {print $$2; exit}' pyproject.toml)
IMAGE_TAG := v$(VERSION)
DEV_IMAGE := $(IMAGE_NAME):dev-$(IMAGE_TAG)
LOCK_IMAGE := $(IMAGE_NAME):lock-$(IMAGE_TAG)
SHELLCHECK_IMAGE := koalaman/shellcheck:v0.11.0@sha256:61862eba1fcf09a484ebcc6feea46f1782532571a34ed51fedf90dd25f925a8d
SHFMT_IMAGE := mvdan/shfmt:v3.13.1@sha256:f22f3936140be1ba02d493b5d2b91d0e8b4af93fd903e7f46c477822bca4a3be
GITLEAKS_IMAGE := ghcr.io/gitleaks/gitleaks:v8.30.1@sha256:c00b6bd0aeb3071cbcb79009cb16a60dd9e0a7c60e2be9ab65d25e6bc8abbb7f
SYFT_IMAGE := anchore/syft:v1.49.0@sha256:9a9f85314017f1ea798fb012edfa7fe9259923910f82c8d4bc983ab5c765e60b
GRYPE_IMAGE := anchore/grype:v0.115.0@sha256:8755370228a7c6dd0f2148696bcb8334ca307d9e358301ca2f8fb29704c73c4e
BOUNDARIES ?= $(PWD)/config/boundaries.json
ENV_FILE ?= $(PWD)/.env
SECRETS ?= $(PWD)/secrets
OAUTH ?= $(PWD)/oauth
OAUTH_ACCOUNT_ID ?= google
OAUTH_CALLBACK_PORT ?= 49152
HTTP_PORT ?= 8080
HTTP_BEARER_SECRET_FILE ?= $(SECRETS)/rankrat/http-bearer-token
RANKRAT_READ_ONLY ?= true
RANKRAT_UNBOUNDED ?= false
ONBOARD_GOOGLE_ACCOUNT_ID ?= google
ONBOARD_BING_ACCOUNT_ID ?= bing
ONBOARD_SITE_URL ?=
ONBOARD_DISPLAY_NAME ?=
ONBOARD_TIME_ZONE ?= Etc/UTC
ONBOARD_CURRENCY_CODE ?= USD
INDEXNOW_TARGET_ID ?=
INDEXNOW_HOST ?=
INDEXNOW_KEY_FILE ?= $(SECRETS)/indexnow/key
SBOM_DIR := $(PWD)/.sbom
SBOM_ARCHIVE := $(SBOM_DIR)/rankrat-image.tar
SBOM_SYFT_JSON := $(SBOM_DIR)/rankrat.syft.json
SBOM_CYCLONEDX_JSON := $(SBOM_DIR)/rankrat.cyclonedx.json
VULNERABILITY_DB_DIR := $(PWD)/.grype-db
VULNERABILITY_REPORT := $(SBOM_DIR)/rankrat.grype.json
CPYTHON_STDLIB_VEX := $(PWD)/security/rankrat-cpython.openvex.json
COVERAGE_LOG := $(PWD)/.coverage-report.log
COVERAGE_PERCENT_FILE := $(PWD)/coverage-percent.txt
BUMP_EXCLUDE_NEWER := bash scripts/bump-exclude-newer.sh
PKG_GROUP ?=

UID := $(shell id -u)
GID := $(shell id -g)

# Every production-image invocation goes through the same wrapper users install,
# so `make run` exercises the path they actually take and the docker run flags
# exist in exactly one place. The wrapper reads all of this from the environment.
WRAPPER := RANKRAT_IMAGE=$(IMAGE_NAME):$(IMAGE_TAG) \
	RANKRAT_BOUNDARIES=$(BOUNDARIES) \
	RANKRAT_SECRETS=$(SECRETS) \
	RANKRAT_OAUTH=$(OAUTH) \
	RANKRAT_ENV_FILE=$(ENV_FILE) \
	RANKRAT_HTTP_PORT=$(HTTP_PORT) \
	RANKRAT_OAUTH_CALLBACK_PORT=$(OAUTH_CALLBACK_PORT) \
	RANKRAT_READ_ONLY=$(RANKRAT_READ_ONLY) \
	RANKRAT_UNBOUNDED=$(RANKRAT_UNBOUNDED) \
	./rankrat.sh

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
	-e PYTHONPATH=/work/src \
	-v $(PWD):/work \
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

.PHONY: help version dev-image lock-image init-config setup init-indexnow verify-indexnow-key shell dep pkg-lock pkg-add pkg-update pkg-upgrade pkg-remove \
	lint lint-fix format test test-unit test-contract test-integration test-security test-live test-live-one test-live-google-search-console test-live-google-analytics test-live-pagespeed test-live-bing test-live-indexnow test-live-http test-image \
	test-tooling test-coverage coverage-percent audit audit-secrets audit-compose audit-image sbom build build-test run run-http \
	 auth-google oauth-revoke onboard-site clean generate generate-openapi check-openapi

help: ## Show supported Rankrat commands
	@awk 'BEGIN {FS = ":.*##"}; /^[a-zA-Z0-9_.-]+:.*##/ {printf "%-20s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

version: ## Print the version-derived production image tag
	@echo $(IMAGE_TAG)

dev-image: ## Build the sandboxed development image
	docker build -f Dockerfile.dev -t $(DEV_IMAGE) .

lock-image: ## Build the minimal, sandboxed Python-version-transition lock image
	docker build -f Dockerfile.lock -t $(LOCK_IMAGE) .

init-config: dev-image ## Create gitignored local boundary, secret, and OAuth-state paths without overwriting
	$(DEV_RUN) sh -ec 'mkdir -p config oauth secrets/google secrets/bing secrets/indexnow secrets/rankrat; chmod 700 config oauth secrets secrets/rankrat; cp -n config/boundaries.json.example config/boundaries.json; chmod 600 config/boundaries.json; cp -n .env.example .env; token=secrets/rankrat/http-bearer-token; if test -e "$$token" || test -L "$$token"; then test -f "$$token" && test ! -L "$$token" || { echo "$$token must be a regular file" >&2; exit 1; }; else umask 077; python -c "import secrets; print(secrets.token_urlsafe(32))" > "$$token"; fi; chmod 600 "$$token"'

setup: init-config build ## Check configured provider access, then verify the shipped HTTP/MCP transport
	$(WRAPPER) setup
	@$(MAKE) --no-print-directory test-live-google-search-console
	@$(MAKE) --no-print-directory test-live-google-analytics
	@$(MAKE) --no-print-directory test-live-pagespeed
	@$(MAKE) --no-print-directory test-live-bing
	@$(MAKE) --no-print-directory test-live-http

init-indexnow: init-config ## Create one operator-selected IndexNow target without uploading or submitting
	@test -n "$(INDEXNOW_TARGET_ID)" || (echo "INDEXNOW_TARGET_ID is required" >&2; exit 1)
	@test -n "$(INDEXNOW_HOST)" || (echo "INDEXNOW_HOST is required" >&2; exit 1)
	$(DEV_RUN) uv run --frozen --no-sync python scripts/init_indexnow.py \
		--target-id "$(INDEXNOW_TARGET_ID)" --host "$(INDEXNOW_HOST)"

verify-indexnow-key: dev-image ## Verify the deployed IndexNow key directly without submitting URLs
	@test -n "$(INDEXNOW_TARGET_ID)" || (echo "INDEXNOW_TARGET_ID is required" >&2; exit 1)
	@test -f "$(BOUNDARIES)" || (echo "$(BOUNDARIES) is required" >&2; exit 1)
	@test -f "$(INDEXNOW_KEY_FILE)" || (echo "$(INDEXNOW_KEY_FILE) is required" >&2; exit 1)
	$(DEV_RUN) uv run --frozen --no-sync python scripts/verify_indexnow_public_key.py \
		--boundary-file config/boundaries.json --key-file secrets/indexnow/key \
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

lint: dev-image ## Run format, lint, and type checks in the dev container
	$(DEV_RUN) uv run --frozen --no-sync ruff format --check .
	$(DEV_RUN) uv run --frozen --no-sync ruff check .
	$(DEV_RUN) uv run --frozen --no-sync bandit -q -r src
	$(DEV_RUN) uv run --frozen --no-sync pyright
	$(DEV_RUN) uv run --frozen --no-sync mypy --cache-dir /tmp/mypy src
	docker run --rm --init --user $(UID):$(GID) --network none --cap-drop=ALL \
		--security-opt no-new-privileges:true --pids-limit 64 --memory 128m --cpus 0.5 \
		-v $(PWD):/mnt:ro -w /mnt $(SHELLCHECK_IMAGE) rankrat.sh scripts/*.sh
	docker run --rm --init --user $(UID):$(GID) --network none --cap-drop=ALL \
		--security-opt no-new-privileges:true --pids-limit 64 --memory 128m --cpus 0.5 \
		-v $(PWD):/mnt:ro -w /mnt $(SHFMT_IMAGE) -d rankrat.sh scripts

lint-fix: dev-image ## Apply safe lint and formatting fixes in the dev container
	$(DEV_RUN) uv run --frozen --no-sync ruff check --fix .
	$(DEV_RUN) uv run --frozen --no-sync ruff format .

format: dev-image ## Apply Ruff and shfmt formatting in sandboxed containers
	$(DEV_RUN) uv run --frozen --no-sync ruff format .
	docker run --rm --init --user $(UID):$(GID) --network none --cap-drop=ALL \
		--security-opt no-new-privileges:true --pids-limit 64 --memory 128m --cpus 0.5 \
		-v $(PWD):/mnt -w /mnt $(SHFMT_IMAGE) -w rankrat.sh scripts

test: test-unit test-contract test-integration test-security test-tooling ## Run all mocked tests

test-unit: dev-image ## Run unit tests in the dev container
	$(DEV_RUN) uv run --frozen --no-sync pytest -p no:cacheprovider tests/unit

test-contract: dev-image ## Run transport contract tests in the dev container
	$(DEV_RUN) uv run --frozen --no-sync pytest -p no:cacheprovider tests/contract

test-integration: dev-image ## Run integration tests in the dev container
	$(DEV_RUN) uv run --frozen --no-sync pytest -p no:cacheprovider tests/integration

test-security: dev-image ## Run security regression tests in the dev container
	$(DEV_RUN) uv run --frozen --no-sync pytest -p no:cacheprovider tests/security

test-tooling: dev-image ## Exercise dependency age-gate tooling in container-local scratch
	$(DEV_RUN) sh -ec 'require_fragment() { grep -Fq -- "$$2" "/work/$$1" || { echo "missing required $$1 fragment: $$2" >&2; exit 1; }; }; scratch=$$(mktemp -d); cp pyproject.toml scripts/bump-exclude-newer.sh "$$scratch"; cd "$$scratch"; LOG_FILE="$$scratch/bump.log" bash bump-exclude-newer.sh; test -s bump.log || { echo "dependency age-gate log was not created" >&2; exit 1; }; test "$$(grep -c "^exclude-newer =" pyproject.toml)" -eq 1 || { echo "dependency age-gate setting is not unique" >&2; exit 1; }; require_fragment Makefile "ENV_FILE ?="; require_fragment Makefile "INDEXNOW_TARGET_ID is required"; require_fragment Makefile "RANKRAT_OAUTH_TOKEN_ROOT=/run/oauth"; require_fragment Makefile "test-live-google-analytics: LIVE_SELECTOR := test_live_google_analytics or test_live_ga4"; require_fragment Makefile "WRAPPER) stdio"; require_fragment Makefile "WRAPPER) http"; require_fragment rankrat.sh "CONTAINER_OAUTH_TOKEN_ROOT=\"/run/oauth\""; require_fragment rankrat.sh "CONTAINER_HTTP_HOST=\"0.0.0.0\""; require_fragment rankrat.sh "CONTAINER_HTTP_BEARER_SECRET_FILE=\"/run/secrets/rankrat/http-bearer-token\""; grep -Fq "pagespeed_api_key_file" /work/config/boundaries.json.example; grep -Fq "/run/secrets/google/pagespeed-api-key" /work/config/boundaries.json.example; grep -Fq "target: /run/secrets/google/oauth-client.json" /work/docker-compose.yml.example'

test-live: test-live-google-search-console test-live-google-analytics test-live-pagespeed test-live-bing test-live-indexnow ## Run every opt-in provider check

test-live-google-search-console: LIVE_SELECTOR := test_live_google_search_console
test-live-google-search-console: test-live-one ## Run configured Google Search Console and Indexing metadata checks

test-live-google-analytics: LIVE_SELECTOR := test_live_google_analytics or test_live_ga4
test-live-google-analytics: test-live-one ## Run configured GA4 report and discovery checks

test-live-pagespeed: LIVE_SELECTOR := test_live_pagespeed
test-live-pagespeed: test-live-one ## Run configured PageSpeed key and analysis checks

test-live-bing: LIVE_SELECTOR := test_live_bing
test-live-bing: test-live-one ## Run configured Bing Webmaster checks

test-live-indexnow: LIVE_SELECTOR := test_live_indexnow
test-live-indexnow: test-live-one ## Run the double-opt-in IndexNow submission check

test-live-http: build dev-image ## Exercise configured reads through the shipped production HTTP and MCP transports
	@test -f "$(ENV_FILE)" || (echo "$(ENV_FILE) is required for live HTTP tests" >&2; exit 1)
	@test -f "$(BOUNDARIES)" || (echo "$(BOUNDARIES) is required" >&2; exit 1)
	@test -d "$(SECRETS)" || (echo "$(SECRETS) is required" >&2; exit 1)
	@test -d "$(OAUTH)" || (echo "$(OAUTH) is required" >&2; exit 1)
	@test -f "$(HTTP_BEARER_SECRET_FILE)" || (echo "$(HTTP_BEARER_SECRET_FILE) is required for live HTTP tests" >&2; exit 1)
	bash scripts/test_live_http_image.sh \
		"$(IMAGE_NAME):$(IMAGE_TAG)" "$(DEV_IMAGE)" "$(BOUNDARIES)" "$(SECRETS)" \
		"$(OAUTH)" "$(ENV_FILE)" "$(PWD)"

test-live-one: dev-image ## Run one selected opt-in live-provider test group
	@test -f "$(ENV_FILE)" || (echo "$(ENV_FILE) is required for live tests" >&2; exit 1)
	@test -f "$(BOUNDARIES)" || (echo "$(BOUNDARIES) is required" >&2; exit 1)
	@test -d "$(SECRETS)" || (echo "$(SECRETS) is required" >&2; exit 1)
	@test -d "$(OAUTH)" || (echo "$(OAUTH) is required" >&2; exit 1)
	docker run --rm --init --user $(UID):$(GID) --cap-drop=ALL \
		--security-opt no-new-privileges:true --pids-limit 128 \
		--tmpfs /tmp:rw,noexec,nosuid,size=256m --env-file $(ENV_FILE) \
		-e HOME=/tmp -e XDG_CACHE_HOME=/tmp/cache -e PYTHONDONTWRITEBYTECODE=1 \
		-e PYTHONPATH=/work/src -e RANKRAT_RUN_LIVE_TESTS=true \
		-e RANKRAT_BOUNDARY_FILE=/run/config/boundaries.json \
		-e RANKRAT_SECRET_ROOT=/run/secrets \
		-e RANKRAT_OAUTH_TOKEN_ROOT=/run/oauth \
		--mount type=bind,src=$(BOUNDARIES),dst=/run/config/boundaries.json,readonly \
		--mount type=bind,src=$(SECRETS),dst=/run/secrets,readonly \
		--mount type=bind,src=$(OAUTH),dst=/run/oauth \
		-v $(PWD):/work -w /work $(DEV_IMAGE) \
		uv run --frozen --no-sync pytest -p no:cacheprovider -m live -k "$(LIVE_SELECTOR)" tests/live

test-image: build ## Smoke-test production stdio and loopback HTTP with no real credentials
	bash scripts/test_final_image.sh $(IMAGE_NAME):$(IMAGE_TAG)

test-coverage: dev-image ## Run tests with a container-local coverage report
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

audit: dev-image ## Audit locked Python dependencies in the dev container
	$(DEV_RUN) uv run --frozen --no-sync pip-audit

audit-secrets: ## Scan Rankrat-owned files for credentials with pinned Gitleaks
	docker run --rm --init --user $(UID):$(GID) --network none --cap-drop=ALL \
		--security-opt no-new-privileges:true --pids-limit 64 --memory 128m --cpus 0.5 \
		-v $(PWD):/repo:ro $(GITLEAKS_IMAGE) dir --no-banner --no-color --redact \
		--config=/repo/.gitleaks.toml /repo

audit-compose: dev-image ## Reject banned Docker Compose settings
	docker compose -f docker-compose.yml.example config --quiet
	$(DEV_RUN) sh -ec 'if grep -nE "privileged:[[:space:]]*true|pid:[[:space:]]*host|ipc:[[:space:]]*host|network:[[:space:]]*host|userns_mode:[[:space:]]*host|/var/run/docker\\.sock|[[:space:]]- ./secrets:/run/secrets" docker-compose.yml.example; then exit 1; fi; grep -q "^secrets:" docker-compose.yml.example'

sbom: build ## Generate Syft and CycloneDX SBOMs from the production image without a Docker socket
	mkdir -p "$(SBOM_DIR)"
	docker image save --output "$(SBOM_ARCHIVE)" "$(IMAGE_NAME):$(IMAGE_TAG)"
	docker run --rm --init --user $(UID):$(GID) --network none --read-only --cap-drop=ALL \
		--security-opt no-new-privileges:true --pids-limit 128 --memory 512m --cpus 1 \
		--tmpfs /tmp:rw,noexec,nosuid,mode=1777,uid=$(UID),gid=$(GID),size=256m \
		-e HOME=/tmp -e SYFT_CHECK_FOR_APP_UPDATE=false \
		--mount type=bind,src=$(SBOM_DIR),dst=/work \
		$(SYFT_IMAGE) scan "docker-archive:/work/rankrat-image.tar" \
		-o "syft-json=/work/rankrat.syft.json" \
		-o "cyclonedx-json=/work/rankrat.cyclonedx.json"

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
		--mount type=bind,src=$(VULNERABILITY_DB_DIR),dst=/cache,readonly \
	--mount type=bind,src=$(SBOM_DIR),dst=/work \
	--mount type=bind,src=$(CPYTHON_STDLIB_VEX),dst=/work/rankrat-cpython.openvex.json,readonly \
	$(GRYPE_IMAGE) "sbom:/work/rankrat.syft.json" --vex /work/rankrat-cpython.openvex.json --only-fixed --fail-on high \
	-o "json=/work/rankrat.grype.json"

build: ## Build the production image with version and latest tags
	docker build -f Dockerfile -t $(IMAGE_NAME):$(IMAGE_TAG) -t $(IMAGE_NAME):latest .

build-test: dev-image ## Build the development image used by tests and linting

run: build ## Run the production image as a stdio MCP server
	$(WRAPPER) stdio

run-http: build ## Run REST and Streamable HTTP MCP on a loopback port
	$(WRAPPER) http

auth-google: build ## Authorize every Rankrat Google OAuth scope through one host-loopback callback
	$(WRAPPER) auth-google --account-id "$(OAUTH_ACCOUNT_ID)" --print-authorization-url

oauth-revoke: build ## Revoke and delete one configured Google OAuth account authorization
	@test -n "$(OAUTH_ACCOUNT_ID)" || (echo "usage: make oauth-revoke OAUTH_ACCOUNT_ID=google-oauth" >&2; exit 1)
	$(WRAPPER) revoke-google --account-id "$(OAUTH_ACCOUNT_ID)"

onboard-site: build ## Create GA4, Search Console, and Bing resources for one new HTTPS site and record boundaries
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
	-docker image rm $(IMAGE_NAME):$(IMAGE_TAG) $(IMAGE_NAME):latest $(DEV_IMAGE)
