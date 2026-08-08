from pathlib import Path

_SOURCE_MAKEFILE = Path("Makefile")
_SOURCE_WRAPPER = Path("rankrat.sh")
_READ_ONLY_MOUNT_ASSIGNMENT = (
    'readonly_boundary_mount="type=bind,src=$boundary_directory,'
    'dst=$CONTAINER_CONFIG_DIRECTORY,readonly"'
)
_WRITABLE_MOUNT_ASSIGNMENT = (
    'writable_boundary_mount="type=bind,src=$boundary_directory,dst=$CONTAINER_CONFIG_DIRECTORY"'
)


def test_runtime_make_targets_delegate_to_the_wrapper() -> None:
    source = _SOURCE_MAKEFILE.read_text(encoding="utf-8")

    assert "RANKRAT_READ_ONLY ?= true" in source
    assert "RANKRAT_UNBOUNDED ?= false" in source
    assert "RANKRAT_ALLOW_AGENT_ONBOARDING ?= false" in source
    assert "RANKRAT_READ_ONLY=$(RANKRAT_READ_ONLY)" in source
    assert "RANKRAT_UNBOUNDED=$(RANKRAT_UNBOUNDED)" in source
    assert "RANKRAT_ALLOW_AGENT_ONBOARDING=$(RANKRAT_ALLOW_AGENT_ONBOARDING)" in source
    assert "RANKRAT_STATE=$(STATE)" in source
    assert "./rankrat.sh" in source
    assert "$(WRAPPER) stdio" in _target(source, "run")
    assert "$(WRAPPER) http" in _target(source, "run-http")
    assert "RANKRAT_WRAPPERS := rankrat.sh .agents/skills/rankrat/references/rankrat.sh" in source
    assert "$(SHELLCHECK_IMAGE) $(RANKRAT_WRAPPERS) scripts/*.sh" in source
    assert "$(SHFMT_IMAGE) -d $(RANKRAT_WRAPPERS) scripts" in source
    assert "$(SHFMT_IMAGE) -w $(RANKRAT_WRAPPERS) scripts" in source


def test_local_dev_image_mode_is_an_explicit_checked_fallback() -> None:
    source = _SOURCE_MAKEFILE.read_text(encoding="utf-8")
    target = _target(source, "dev-image")

    assert "RANKRAT_DEV_IMAGE_SOURCE ?= build" in source
    assert "build) docker build -f Dockerfile.dev -t $(DEV_IMAGE) ." in target
    assert 'local) docker image inspect "$(DEV_IMAGE)" >/dev/null 2>&1' in target
    assert "RANKRAT_DEV_IMAGE_SOURCE must be build or local" in target
    assert "RANKRAT_DEV_IMAGE_SOURCE=local test" in _target(source, "test-local")


def test_wrapper_allows_only_explicit_boundary_persistence() -> None:
    source = _SOURCE_WRAPPER.read_text(encoding="utf-8")

    assert 'read_only="${RANKRAT_READ_ONLY:-true}"' in source
    assert 'unbounded="${RANKRAT_UNBOUNDED:-false}"' in source
    assert 'allow_agent_onboarding="${RANKRAT_ALLOW_AGENT_ONBOARDING:-false}"' in source
    assert "Writable boundary persistence requires RANKRAT_READ_ONLY=false" in source
    assert "RANKRAT_ALLOW_AGENT_ONBOARDING=$allow_agent_onboarding" in source
    assert _READ_ONLY_MOUNT_ASSIGNMENT in source
    assert _WRITABLE_MOUNT_ASSIGNMENT in source
    assert 'serve_boundary_mount="$readonly_boundary_mount"' in source
    assert 'serve_boundary_mount="$writable_boundary_mount"' in source
    assert '[[ "$unbounded" == "true" || "$allow_agent_onboarding" == "true" ]]' in source
    assert 'require_writable_boundary_is_safe "$boundary_file" "$boundary_directory"' in source


def test_wrapper_never_bind_mounts_the_boundary_file_on_its_own() -> None:
    """The image bakes /run/config, so a lone file mount there is unreadable."""

    source = _SOURCE_WRAPPER.read_text(encoding="utf-8")

    assert "dst=/run/config/boundaries.json" not in source
    assert "src=$boundary_file" not in source


def test_compose_example_mounts_the_boundary_directory() -> None:
    source = Path("docker-compose.yml.example").read_text(encoding="utf-8")

    assert "- ./config:/run/config:ro" in source
    assert "./config/boundaries.json:/run/config/boundaries.json" not in source


def test_init_config_creates_and_preserves_a_safe_http_bearer_secret() -> None:
    source = _SOURCE_MAKEFILE.read_text(encoding="utf-8")
    target = _target(source, "init-config")

    assert "secrets/rankrat/http-bearer-token" in target
    assert 'test -L "$$path"' in target
    assert "config, OAuth, secret, and state paths must not contain symlinks" in target
    assert "find config oauth secrets state -type d -exec chmod 700 {} +" in target
    assert "find oauth secrets state -type f -exec chmod 600 {} +" in target
    assert "chmod 600 config/boundaries.json .env" in target
    assert 'test -f "$$token" && test ! -L "$$token"' in target
    assert "secrets.token_urlsafe(32)" in target


def test_indexnow_verifier_mounts_the_selected_host_files_read_only() -> None:
    source = _SOURCE_MAKEFILE.read_text(encoding="utf-8")
    target = _target(source, "verify-indexnow-key")

    assert "INDEXNOW_VERIFY_RUN := docker run --rm --init" in source
    assert "src=$(BOUNDARIES),dst=$(INDEXNOW_VERIFY_BOUNDARY_FILE),readonly" in source
    assert "src=$(INDEXNOW_KEY_FILE),dst=$(INDEXNOW_VERIFY_KEY_FILE),readonly" in source
    assert "$(INDEXNOW_VERIFY_RUN) uv run --frozen --no-sync python" in target
    assert "--boundary-file $(INDEXNOW_VERIFY_BOUNDARY_FILE)" in target
    assert "--key-file $(INDEXNOW_VERIFY_KEY_FILE)" in target
    assert "--key-file secrets/indexnow/key" not in target


def test_search_console_live_target_does_not_select_the_whole_live_test_file() -> None:
    source = _SOURCE_MAKEFILE.read_text(encoding="utf-8")

    assert (
        "test-live-google-search-console: LIVE_SELECTOR := "
        "test_live_google_search_console_matches_mocked_contract or "
        "test_live_google_search_console_unique_read_operations"
    ) in source
    assert "LIVE_SELECTOR := test_live_google_search_console\n" not in source


def test_live_target_runs_every_provider_and_transport_target() -> None:
    source = _SOURCE_MAKEFILE.read_text(encoding="utf-8")
    target = _target(source, "test-live")
    expected_targets = (
        "test-live-google-search-console",
        "test-live-google-analytics",
        "test-live-pagespeed",
        "test-live-cloudflare",
        "test-live-bing",
        "test-live-indexnow",
        "test-live-http",
    )

    assert source.split("\ntest-live:", maxsplit=1)[1].startswith(" dev-image ##")
    assert target.count("RANKRAT_DEV_IMAGE_SOURCE=local") == len(expected_targets)
    for expected_target in expected_targets:
        invocation = f"$(MAKE) --no-print-directory {expected_target}"
        assert target.count(invocation) == 1


def test_lighthouse_image_target_drives_the_production_transport() -> None:
    makefile = _SOURCE_MAKEFILE.read_text(encoding="utf-8")
    script = Path("scripts/test_lighthouse_image.sh").read_text(encoding="utf-8")

    assert "scripts/test_lighthouse_image.sh" in _target(makefile, "test-image")
    assert "scripts/test_lighthouse_image.sh" in _target(makefile, "test-lighthouse-image")
    expected_operations = (
        "lighthouse_audit",
        "lighthouse_seo_findings",
        "lighthouse_accessibility_findings",
        "lighthouse_performance_findings",
        "lighthouse_best_practices_findings",
    )
    expected_routes = (
        "audits",
        "seo-findings",
        "accessibility-findings",
        "performance-findings",
        "best-practices-findings",
    )

    for operation in expected_operations:
        assert f'"{operation}"' in script
    for route in expected_routes:
        assert f'"{route}"' in script
    assert '"page_url":"https://example.com/"' in script
    assert "/v1/lighthouse" in script
    assert "Streamable HTTP MCP" in script
    assert "--network none" in script
    assert 'docker run -d --init --name "$worker_container_name"' in script
    assert 'LIGHTHOUSE_RUNNER_TIMEOUT_MS="$WORKER_AUDIT_TIMEOUT_MILLISECONDS"' in script
    assert '--retry "$LIVE_AUDIT_RETRY_COUNT" --retry-all-errors' in script
    assert "RANKRAT_LIGHTHOUSE_WORKER_SOCKET=/run/lighthouse/lighthouse.sock" in script
    assert 'docker rm -f "$worker_container_name"' in script
    assert 'docker volume create "$runtime_volume_name"' in script
    assert 'docker volume rm "$runtime_volume_name"' in script
    assert script.count('--user "$HOST_USER_ID:$HOST_GROUP_ID"') == 5


def test_reusable_workflows_are_pinned_to_one_reviewed_commit() -> None:
    workflow_paths = tuple(Path(".github/workflows").glob("*.yml"))
    reusable_prefix = "psyb0t/reusable-github-workflows/"
    expected_revision = "9b67e6f6f0d5efd3c7061fbdb1c3e0cda003097e"
    references: list[str] = []

    for workflow_path in workflow_paths:
        for line in workflow_path.read_text(encoding="utf-8").splitlines():
            if reusable_prefix in line:
                references.append(line.rsplit("@", maxsplit=1)[-1].strip())

    assert references
    assert set(references) == {expected_revision}


def test_public_docs_describe_the_initializer_as_a_one_shot_service() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")

    assert "two\nlong-lived services plus two one-shot volume initializers" in readme
    assert "two-service Compose" not in readme
    assert "two-service deployment" not in readme


def test_lighthouse_format_rebuilds_the_baked_development_source() -> None:
    makefile = _SOURCE_MAKEFILE.read_text(encoding="utf-8")

    assert "$(MAKE) --no-print-directory lighthouse-dev-image" in _target(
        makefile, "lighthouse-format"
    )


def test_supply_chain_targets_cover_both_production_images() -> None:
    makefile = _SOURCE_MAKEFILE.read_text(encoding="utf-8")
    sbom_target = _target(makefile, "sbom")

    assert "mirror.gcr.io/koalaman/shellcheck:v0.11.0@sha256:61862eba" in makefile
    assert "mirror.gcr.io/mvdan/shfmt:v3.13.1@sha256:f22f3936" in makefile
    assert "ghcr.io/anchore/syft:v1.49.0@sha256:9a9f8531" in makefile
    assert "ghcr.io/anchore/grype:v0.116.0@sha256:fd4ab4d" in makefile
    assert "anchore/grype:v0.115.0" not in makefile
    assert "src=$(VULNERABILITY_DB_DIR),dst=/cache,readonly" not in makefile
    assert _target(makefile, "audit-image").count("src=$(VULNERABILITY_DB_DIR),dst=/cache") == 3
    assert "rankrat-lighthouse-image.tar" in sbom_target
    assert "rankrat-lighthouse.syft.json" in sbom_target
    assert 'mkdir -p "$(SBOM_DIR)" "$(SBOM_TMP_DIR)"' in sbom_target
    assert sbom_target.count("trap 'find \"$(SBOM_TMP_DIR)\" -mindepth 1 -delete' EXIT") == 2
    assert sbom_target.count("-e TMPDIR=/work/tmp") == 2
    assert sbom_target.count("--memory 2g") == 2
    assert "size=256m" not in sbom_target
    assert "sbom:/work/rankrat-lighthouse.syft.json" in _target(
        makefile,
        "audit-image",
    )
    assert "rankrat-lighthouse.grype.json" in _target(makefile, "audit-image")


def test_lighthouse_dependency_lifecycle_is_sandboxed_and_age_gated() -> None:
    makefile = _SOURCE_MAKEFILE.read_text(encoding="utf-8")
    workspace = Path("lighthouse-worker/pnpm-workspace.yaml").read_text(encoding="utf-8")
    dockerfile = Path("Dockerfile.lighthouse").read_text(encoding="utf-8")

    assert "FROM lock AS dependencies" in dockerfile
    assert dockerfile.count("mcr.microsoft.com/playwright:v1.62.1-noble@sha256:") == 2
    assert "mcr.microsoft.com/playwright:v1.62.0-noble" not in dockerfile
    assert "ARG CHROME_FOR_TESTING_VERSION=151.0.7922.72" in dockerfile
    assert "ARG CHROME_FOR_TESTING_SHA256=" in dockerfile
    assert "sha256sum --check --strict" in dockerfile
    assert "python3 -m zipfile -e" in dockerfile
    assert "unzip" not in dockerfile
    assert "chmod 0755 /opt/chrome/chrome /opt/chrome/chrome_crashpad_handler" in dockerfile
    assert 'grep -Fq "${CHROME_FOR_TESTING_VERSION}"' in dockerfile
    assert "rm --recursive --force /ms-playwright /usr/lib/node_modules" in dockerfile
    assert "pnpm@10.34.5" in dockerfile
    assert "LIGHTHOUSE_LOCK_IMAGE :=" in makefile
    assert "$(LIGHTHOUSE_LOCK_IMAGE)" in makefile
    assert "audit: lighthouse-lock-image dev-image ##" in makefile
    assert "$(BUMP_LIGHTHOUSE_RELEASE_AGE)" in _target(
        makefile,
        "lighthouse-pkg-update",
    )
    assert "minimumReleaseAge: 10080" in workspace
    assert "- brace-expansion@5.0.9" in workspace
    assert "brace-expansion: 5.0.9" in workspace
    assert "- nanoid@3.3.17" in workspace
    assert "nanoid: 3.3.17" in workspace
    tooling_target = _target(makefile, "test-tooling")
    assert "bump_lighthouse_minimum_release_age.sh" in tooling_target
    assert "minimumReleaseAge: 10080" in tooling_target


def test_coverage_target_also_runs_the_lighthouse_worker_suite() -> None:
    makefile = _SOURCE_MAKEFILE.read_text(encoding="utf-8")

    assert "test-coverage: lighthouse-test dev-image ##" in makefile


def _target(source: str, name: str) -> str:
    return source.split(f"\n{name}:", maxsplit=1)[1].split("\n\n", maxsplit=1)[0]
