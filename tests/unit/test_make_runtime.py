import json
import os
import shutil
import subprocess
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

_SOURCE_MAKEFILE = Path("Makefile")
_SOURCE_WRAPPER = Path("rankrat")
_BASH_EXECUTABLE = "/bin/bash"
_READ_ONLY_MOUNT_ASSIGNMENT = (
    'readonly_boundary_mount="type=bind,src=$boundary_directory,'
    'dst=$CONTAINER_CONFIG_DIRECTORY,readonly"'
)
_WRITABLE_MOUNT_ASSIGNMENT = (
    'writable_boundary_mount="type=bind,src=$boundary_directory,dst=$CONTAINER_CONFIG_DIRECTORY"'
)


def test_runtime_make_targets_delegate_to_the_wrapper() -> None:
    source = _SOURCE_MAKEFILE.read_text(encoding="utf-8")

    assert "RANKRAT_READ_ONLY ?= false" in source
    assert "TOOLING_LOG_FLUSH_ATTEMPTS ?= 20" in source
    assert "TOOLING_LOG_FLUSH_DELAY_SECONDS ?= 0.1" in source
    assert 'wait_for_log "$$scratch/bump.log"' in _target(source, "test-tooling")
    assert 'wait_for_log "$$scratch/bump-lighthouse.log"' in _target(source, "test-tooling")
    assert "RANKRAT_READ_ONLY=$(RANKRAT_READ_ONLY)" in source
    assert "RANKRAT_PROFILE ?= $(HOME)/.config/rankrat" in source
    assert "PROFILE_CONFIG := $(RANKRAT_PROFILE)/config" in source
    assert './rankrat --data-dir "$(RANKRAT_PROFILE)"' in source
    assert "RANKRAT_STATE=$(STATE)" not in source
    assert "./rankrat.sh" not in source
    assert "$(WRAPPER) stdio" in _target(source, "run")
    assert "$(WRAPPER) http" in _target(source, "run-http")
    assert "RANKRAT_WRAPPERS := rankrat" in source
    assert "$(SHELLCHECK_IMAGE) $(RANKRAT_WRAPPERS) scripts/*.sh" in source
    assert "$(SHFMT_IMAGE) -d $(RANKRAT_WRAPPERS) scripts" in source
    assert "$(SHFMT_IMAGE) -w $(RANKRAT_WRAPPERS) scripts" in source


def test_live_tests_mount_the_selected_profile_config_directory() -> None:
    source = _SOURCE_MAKEFILE.read_text(encoding="utf-8")
    target = _target(source, "test-live-one")

    assert "$(PROFILE_CONFIG) is required" in target
    assert "--mount type=bind,src=$(PROFILE_CONFIG),dst=/run/config,readonly" in target
    assert "src=$(BOUNDARIES),dst=/run/config/boundaries.json,readonly" not in target


def test_local_dev_image_mode_is_an_explicit_checked_fallback() -> None:
    source = _SOURCE_MAKEFILE.read_text(encoding="utf-8")
    target = _target(source, "dev-image")

    assert "RANKRAT_DEV_IMAGE_SOURCE ?= build" in source
    assert "build) docker build -f Dockerfile.dev -t $(DEV_IMAGE) ." in target
    assert 'local) docker image inspect "$(DEV_IMAGE)" >/dev/null 2>&1' in target
    assert "RANKRAT_DEV_IMAGE_SOURCE must be build or local" in target
    assert "RANKRAT_DEV_IMAGE_SOURCE=local test" in _target(source, "test-local")


def test_version_target_treats_the_release_version_as_data() -> None:
    source = _SOURCE_MAKEFILE.read_text(encoding="utf-8")
    target = _target(source, "version")

    assert "RANKRAT_RELEASE_VERSION := $(value V)" in source
    assert "export RANKRAT_RELEASE_VERSION" in source
    assert "-e RANKRAT_RELEASE_VERSION" in source
    assert '"$$RANKRAT_RELEASE_VERSION"' in target
    assert "process.env.RANKRAT_RELEASE_VERSION" in target
    assert "$(V)" not in target


def test_wrapper_mounts_config_writable_exactly_when_writes_are_enabled() -> None:
    source = _SOURCE_WRAPPER.read_text(encoding="utf-8")

    assert (
        'read_only="$(resolve_setting "${RANKRAT_READ_ONLY:-}" '
        '"$env_file" RANKRAT_READ_ONLY "false")"'
    ) in source
    assert _READ_ONLY_MOUNT_ASSIGNMENT in source
    assert _WRITABLE_MOUNT_ASSIGNMENT in source
    assert 'serve_boundary_mount="$readonly_boundary_mount"' in source
    assert 'serve_boundary_mount="$writable_boundary_mount"' in source
    assert 'require_writable_boundary_is_safe "$boundary_file" "$boundary_directory"' in source


def test_wrapper_runs_setup_interactively_with_owner_only_writable_paths() -> None:
    source = _SOURCE_WRAPPER.read_text(encoding="utf-8")
    target = source.split("\nsetup)\n", maxsplit=1)[1].split("\n\t;;", maxsplit=1)[0]

    assert "-i" in target
    assert '--mount "$writable_boundary_mount"' in target
    assert '--mount "$secret_mount"' in source
    assert 'require_owner_only_directory "$secrets_directory"' in source
    assert "--interactive-setup" in target
    assert '--callback-port "$oauth_callback_port"' in target
    assert "--docker-loopback-proxy" in target


def test_wrapper_setup_bootstraps_a_fresh_default_profile(
    tmp_path: Path,
) -> None:
    home_directory = tmp_path / "home"
    home_directory.mkdir(mode=0o700)
    data_directory = home_directory / ".config/rankrat"
    docker_arguments = tmp_path / "docker-arguments"
    environment = {
        **os.environ,
        "HOME": str(home_directory),
        "RANKRAT_READ_ONLY": "false",
        "RANKRAT_TEST_DOCKER_ARGS": str(docker_arguments),
    }

    with _fake_bin_directory() as fake_bin:
        environment["PATH"] = f"{fake_bin}:{os.environ['PATH']}"
        result = _run_wrapper(environment, tmp_path, mode="setup")

    assert result.returncode == 0, result.stderr
    assert json.loads((data_directory / "config/boundaries.json").read_text()) == {
        "accounts": [],
        "indexnow_targets": [],
    }
    assert (data_directory / "secrets/rankrat/http-bearer-token").stat().st_mode & 0o777 == 0o600
    for directory in (
        data_directory,
        data_directory / "config",
        data_directory / "secrets",
        data_directory / "oauth",
        data_directory / "state",
    ):
        assert directory.stat().st_mode & 0o777 == 0o700
    assert "setup" in docker_arguments.read_text(encoding="utf-8").splitlines()


def test_wrapper_never_bind_mounts_the_boundary_file_on_its_own() -> None:
    """The image bakes /run/config, so a lone file mount there is unreadable."""

    source = _SOURCE_WRAPPER.read_text(encoding="utf-8")

    assert "dst=/run/config/boundaries.json" not in source
    assert "src=$boundary_file" not in source


def test_wrapper_uses_one_shared_profile_independently_of_cwd(tmp_path: Path) -> None:
    data_directory = _create_data_directory(tmp_path / "shared profile")
    stable_invocations: list[list[str]] = []

    for site_name in ("site-a", "site-b"):
        docker_all_arguments = tmp_path / f"docker-all-{site_name}"
        with _fake_bin_directory() as fake_bin:
            environment = {
                **os.environ,
                "PATH": f"{fake_bin}:{os.environ['PATH']}",
                "RANKRAT_DATA_DIR": str(data_directory),
                "RANKRAT_READ_ONLY": "true",
                "RANKRAT_TEST_DOCKER_ARGS": str(tmp_path / f"docker-args-{site_name}"),
                "RANKRAT_TEST_DOCKER_ALL_ARGS": str(docker_all_arguments),
                "RANKRAT_BOUNDARIES": "/ignored/old/boundaries.json",
                "RANKRAT_SECRETS": "/ignored/old/secrets",
            }
            site_directory = tmp_path / site_name
            site_directory.mkdir()
            result = _run_wrapper(environment, site_directory)
            assert result.returncode == 0, result.stderr

        arguments = _stdio_main_run(docker_all_arguments)
        expected_mounts = {
            f"type=bind,src={data_directory}/config,dst=/run/config,readonly",
            f"type=bind,src={data_directory}/secrets,dst=/run/secrets,readonly",
            f"type=bind,src={data_directory}/oauth,dst=/run/oauth",
            f"type=bind,src={data_directory}/state,dst=/run/state",
        }
        assert expected_mounts.issubset(set(arguments))
        assert not any(str(data_directory) == argument for argument in arguments)
        assert not any("/ignored/old/" in argument for argument in arguments)
        # Drop the per-session Lighthouse volume name so the profile-derived
        # invocation can be compared across working directories.
        stable_invocations.append(
            [argument for argument in arguments if "rankrat-lighthouse-stdio-" not in argument]
        )

    assert stable_invocations[0] == stable_invocations[1]


def test_stdio_launches_ephemeral_lighthouse_sidecar(tmp_path: Path) -> None:
    data_directory = _create_data_directory(tmp_path / "profile")
    docker_all_arguments = tmp_path / "docker-all-arguments"
    with _fake_bin_directory() as fake_bin:
        environment = {
            **os.environ,
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "RANKRAT_DATA_DIR": str(data_directory),
            "RANKRAT_IMAGE": "example/rankrat:test",
            "RANKRAT_LIGHTHOUSE_IMAGE": "example/lighthouse:test",
            "RANKRAT_READ_ONLY": "true",
            "RANKRAT_TEST_DOCKER_ARGS": str(tmp_path / "docker-arguments"),
            "RANKRAT_TEST_DOCKER_ALL_ARGS": str(docker_all_arguments),
        }
        result = _run_wrapper(environment, tmp_path, mode="stdio")

    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    invocations = _docker_invocations(docker_all_arguments)

    def volume_source(invocation: list[str]) -> str | None:
        for argument in invocation:
            if argument.startswith("type=volume,src=rankrat-lighthouse-stdio-"):
                return argument.split("src=", 1)[1].split(",", 1)[0]
        return None

    # (a) The worker runs the resolved Lighthouse image, hardened and networked.
    worker_runs = [
        invocation
        for invocation in invocations
        if invocation[:2] == ["run", "-d"] and invocation[-1] == "example/lighthouse:test"
    ]
    assert len(worker_runs) == 1, invocations
    worker_run = worker_runs[0]
    assert "bridge" in worker_run
    assert "LIGHTHOUSE_SOCKET_PATH=/run/lighthouse/lighthouse.sock" in worker_run
    assert "LIGHTHOUSE_RUNNER_TIMEOUT_MS=120000" in worker_run

    # The networkless one-shot initializer chowns the volume to the host UID/GID.
    init_runs = [
        invocation
        for invocation in invocations
        if invocation[:2] == ["run", "--rm"] and "--cap-add=CHOWN" in invocation
    ]
    assert len(init_runs) == 1, invocations
    init_run = init_runs[0]
    assert "none" in init_run
    assert "0:0" in init_run
    assert init_run[-2:] == [str(os.getuid()), str(os.getgid())]

    # (b) The main container gets the worker socket env and the read-only volume.
    main_run = _stdio_main_run(docker_all_arguments)
    assert "RANKRAT_LIGHTHOUSE_WORKER_SOCKET=/run/lighthouse/lighthouse.sock" in main_run
    assert any(
        argument.startswith("type=volume,src=rankrat-lighthouse-stdio-")
        and argument.endswith(",dst=/run/lighthouse,readonly")
        for argument in main_run
    )
    assert main_run[-2:] == ["example/rankrat:test", "stdio"]

    # All three containers share one per-session socket volume.
    volume_names = {
        volume_source(init_run),
        volume_source(worker_run),
        volume_source(main_run),
    }
    assert len(volume_names) == 1 and None not in volume_names

    # (c) A cleanup trap removes the container and the volume on exit.
    assert any(
        invocation[:2] == ["rm", "-f"] and invocation[-1].startswith("rankrat-lighthouse-stdio-")
        for invocation in invocations
    )
    assert any(
        invocation[:2] == ["volume", "rm"]
        and invocation[-1].startswith("rankrat-lighthouse-stdio-")
        for invocation in invocations
    )

    source = _SOURCE_WRAPPER.read_text(encoding="utf-8")
    assert "trap lighthouse_stdio_cleanup EXIT INT TERM" in source
    assert 'docker rm -f "$lighthouse_stdio_container" >/dev/null 2>&1 || true' in source
    assert 'docker volume rm "$lighthouse_stdio_volume" >/dev/null 2>&1 || true' in source


def test_wrapper_rejects_unsafe_data_directories_before_docker(tmp_path: Path) -> None:
    data_directory = _create_data_directory(tmp_path / "profile")
    docker_marker = tmp_path / "docker-was-called"
    linked_directory = tmp_path / "linked-profile"
    linked_directory.symlink_to(data_directory, target_is_directory=True)
    invalid_directories = (
        "relative/profile",
        "/",
        f"{data_directory},readonly",
        f"{data_directory}\nforged-log-line",
        f"{data_directory}/../profile",
        str(linked_directory),
    )

    with _fake_bin_directory() as fake_bin:
        base_environment = {
            **os.environ,
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "RANKRAT_READ_ONLY": "true",
            "RANKRAT_TEST_DOCKER_ARGS": str(docker_marker),
        }
        for invalid_directory in invalid_directories:
            result = _run_wrapper(
                {**base_environment, "RANKRAT_DATA_DIR": invalid_directory},
                tmp_path,
            )
            assert result.returncode != 0
            assert result.stdout == ""

    assert not docker_marker.exists()


def test_compose_deployment_mounts_one_shared_profile() -> None:
    source = Path("docker-compose.yml").read_text(encoding="utf-8")

    assert "source: ${RANKRAT_DATA_DIR:-.}/config" in source
    assert "target: /run/config" in source
    assert "read_only: ${RANKRAT_READ_ONLY:-false}" in source
    assert "- ${RANKRAT_DATA_DIR:-.}/secrets:/run/secrets:ro" in source
    assert "- ${RANKRAT_DATA_DIR:-.}/oauth:/run/oauth:rw" in source
    assert "- ${RANKRAT_DATA_DIR:-.}/state:/run/state:rw" in source
    assert "./config/boundaries.json:/run/config/boundaries.json" not in source
    assert "source: ${RANKRAT_DATA_DIR:-.}\n        target: /" not in source


def test_wrapper_generates_profile_compose_and_runs_http_foreground(tmp_path: Path) -> None:
    data_directory = _create_data_directory(tmp_path / "shared profile")
    docker_arguments = tmp_path / "docker-arguments"
    docker_environment = tmp_path / "docker-environment"
    environment = {
        **os.environ,
        "RANKRAT_DATA_DIR": str(data_directory),
        "RANKRAT_HTTP_PORT": "18080",
        "RANKRAT_IMAGE": "example/rankrat:test",
        "RANKRAT_LIGHTHOUSE_IMAGE": "example/lighthouse:test",
        "RANKRAT_READ_ONLY": "true",
        "RANKRAT_TEST_DOCKER_ARGS": str(docker_arguments),
        "RANKRAT_TEST_DOCKER_ENV": str(docker_environment),
    }

    with _fake_bin_directory() as fake_bin:
        environment["PATH"] = f"{fake_bin}:{os.environ['PATH']}"
        result = _run_wrapper(environment, tmp_path, mode="http")

    assert result.returncode == 0, result.stderr
    compose_file = data_directory / "docker-compose.yml"
    assert compose_file.read_bytes() == Path("docker-compose.yml").read_bytes()
    assert compose_file.stat().st_mode & 0o777 == 0o600
    assert not tuple(data_directory.glob(".rankrat-compose.*"))
    assert docker_arguments.read_text(encoding="utf-8").splitlines() == [
        "compose",
        "--project-directory",
        str(data_directory),
        "--file",
        str(compose_file),
        "up",
        "--remove-orphans",
    ]
    assert docker_environment.read_text(encoding="utf-8").splitlines() == [
        str(data_directory),
        "example/rankrat:test",
        "example/lighthouse:test",
        "18080",
        "true",
    ]


def test_wrapper_runs_http_detached_with_both_supported_flags(tmp_path: Path) -> None:
    data_directory = _create_data_directory(tmp_path / "profile")
    (data_directory / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")

    for flag in ("-d", "--detach"):
        docker_arguments = tmp_path / f"docker-arguments-{flag.lstrip('-')}"
        with _fake_bin_directory() as fake_bin:
            environment = {
                **os.environ,
                "PATH": f"{fake_bin}:{os.environ['PATH']}",
                "RANKRAT_DATA_DIR": str(data_directory),
                "RANKRAT_READ_ONLY": "true",
                "RANKRAT_TEST_DOCKER_ARGS": str(docker_arguments),
            }
            result = _run_wrapper(
                environment,
                tmp_path,
                mode="http",
                arguments=(flag,),
            )

        assert result.returncode == 0, result.stderr
        assert docker_arguments.read_text(encoding="utf-8").splitlines()[-3:] == [
            "up",
            "--detach",
            "--remove-orphans",
        ]


def test_wrapper_preserves_existing_profile_compose(tmp_path: Path) -> None:
    data_directory = _create_data_directory(tmp_path / "profile")
    compose_file = data_directory / "docker-compose.yml"
    custom_compose = "services:\n  custom-service:\n    image: example/custom:1\n"
    compose_file.write_text(custom_compose, encoding="utf-8")
    docker_arguments = tmp_path / "docker-arguments"

    with _fake_bin_directory() as fake_bin:
        environment = {
            **os.environ,
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "RANKRAT_DATA_DIR": str(data_directory),
            "RANKRAT_READ_ONLY": "true",
            "RANKRAT_TEST_DOCKER_ARGS": str(docker_arguments),
        }
        result = _run_wrapper(environment, tmp_path, mode="http")

    assert result.returncode == 0, result.stderr
    assert compose_file.read_text(encoding="utf-8") == custom_compose
    assert str(compose_file) in docker_arguments.read_text(encoding="utf-8").splitlines()


def test_wrapper_rejects_symlinked_profile_compose_before_docker(tmp_path: Path) -> None:
    data_directory = _create_data_directory(tmp_path / "profile")
    custom_compose = tmp_path / "custom-compose.yml"
    custom_compose.write_text("services: {}\n", encoding="utf-8")
    (data_directory / "docker-compose.yml").symlink_to(custom_compose)
    docker_marker = tmp_path / "docker-was-called"

    with _fake_bin_directory() as fake_bin:
        environment = {
            **os.environ,
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "RANKRAT_DATA_DIR": str(data_directory),
            "RANKRAT_READ_ONLY": "true",
            "RANKRAT_TEST_DOCKER_ARGS": str(docker_marker),
        }
        result = _run_wrapper(environment, tmp_path, mode="http")

    assert result.returncode != 0
    assert "must be a regular file" in result.stderr
    assert not docker_marker.exists()


def test_wrapper_rejects_directory_at_profile_compose_path(tmp_path: Path) -> None:
    data_directory = _create_data_directory(tmp_path / "profile")
    (data_directory / "docker-compose.yml").mkdir()
    docker_marker = tmp_path / "docker-was-called"

    with _fake_bin_directory() as fake_bin:
        environment = {
            **os.environ,
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "RANKRAT_DATA_DIR": str(data_directory),
            "RANKRAT_READ_ONLY": "true",
            "RANKRAT_TEST_DOCKER_ARGS": str(docker_marker),
        }
        result = _run_wrapper(environment, tmp_path, mode="http")

    assert result.returncode != 0
    assert "must be a regular file" in result.stderr
    assert not docker_marker.exists()


def test_wrapper_rejects_unsafe_profile_before_compose_generation(tmp_path: Path) -> None:
    data_directory = _create_data_directory(tmp_path / "profile")
    data_directory.chmod(0o770)
    docker_marker = tmp_path / "docker-was-called"

    with _fake_bin_directory() as fake_bin:
        environment = {
            **os.environ,
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "RANKRAT_DATA_DIR": str(data_directory),
            "RANKRAT_READ_ONLY": "true",
            "RANKRAT_TEST_DOCKER_ARGS": str(docker_marker),
        }
        result = _run_wrapper(environment, tmp_path, mode="http")

    assert result.returncode != 0
    assert "must not be group- or world-writable" in result.stderr
    assert not (data_directory / "docker-compose.yml").exists()
    assert not docker_marker.exists()


def test_wrapper_rejects_group_writable_existing_compose(tmp_path: Path) -> None:
    data_directory = _create_data_directory(tmp_path / "profile")
    compose_file = data_directory / "docker-compose.yml"
    compose_file.write_text("services: {}\n", encoding="utf-8")
    compose_file.chmod(0o660)
    docker_marker = tmp_path / "docker-was-called"

    with _fake_bin_directory() as fake_bin:
        environment = {
            **os.environ,
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "RANKRAT_DATA_DIR": str(data_directory),
            "RANKRAT_READ_ONLY": "true",
            "RANKRAT_TEST_DOCKER_ARGS": str(docker_marker),
        }
        result = _run_wrapper(environment, tmp_path, mode="http")

    assert result.returncode != 0
    assert "must not be group- or world-writable" in result.stderr
    assert not docker_marker.exists()


def test_wrapper_rejects_unknown_http_arguments_before_docker(tmp_path: Path) -> None:
    data_directory = _create_data_directory(tmp_path / "profile")
    docker_marker = tmp_path / "docker-was-called"

    with _fake_bin_directory() as fake_bin:
        environment = {
            **os.environ,
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "RANKRAT_DATA_DIR": str(data_directory),
            "RANKRAT_READ_ONLY": "true",
            "RANKRAT_TEST_DOCKER_ARGS": str(docker_marker),
        }
        for arguments in (("--project-name",), ("-d", "extra")):
            result = _run_wrapper(
                environment,
                tmp_path,
                mode="http",
                arguments=arguments,
            )
            assert result.returncode != 0
            assert "http accepts only -d or --detach" in result.stderr

    assert not docker_marker.exists()


def test_wrapper_requires_http_bearer_before_compose_generation(tmp_path: Path) -> None:
    data_directory = _create_data_directory(tmp_path / "profile")
    (data_directory / "secrets/rankrat/http-bearer-token").unlink()
    docker_marker = tmp_path / "docker-was-called"

    with _fake_bin_directory() as fake_bin:
        environment = {
            **os.environ,
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "RANKRAT_DATA_DIR": str(data_directory),
            "RANKRAT_READ_ONLY": "true",
            "RANKRAT_TEST_DOCKER_ARGS": str(docker_marker),
        }
        result = _run_wrapper(environment, tmp_path, mode="http")

    assert result.returncode != 0
    assert "Rankrat HTTP bearer secret must be a regular file" in result.stderr
    assert not (data_directory / "docker-compose.yml").exists()
    assert not docker_marker.exists()


def test_make_setup_delegates_profile_bootstrap_to_the_public_wrapper() -> None:
    source = _SOURCE_MAKEFILE.read_text(encoding="utf-8")
    target = _target(source, "setup")

    assert "init-config" not in source
    assert "$(WRAPPER) setup" in target


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


def test_indexnow_initializer_uses_the_selected_profile() -> None:
    source = _SOURCE_MAKEFILE.read_text(encoding="utf-8")
    target = _target(source, "init-indexnow")

    assert "INDEXNOW_INIT_RUN := docker run --rm --init" in source
    assert "src=$(PROFILE_CONFIG),dst=/profile/config" in source
    assert "src=$(RANKRAT_PROFILE)/secrets/indexnow,dst=/profile/secrets/indexnow" in source
    assert "$(INDEXNOW_INIT_RUN) uv run --frozen --no-sync python" in target
    assert "--boundary-file /profile/config/boundaries.json" in target
    assert "--key-file /profile/secrets/indexnow/key" in target


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
        "test-live-google-tag-manager",
        "test-live-pagespeed",
        "test-live-cloudflare",
        "test-live-clarity",
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
    assert "SMOKE_BOUNDARY_DOCUMENT" in script
    assert '"pagespeed_sites": ["https://example.com/"]' in script
    assert "boundaries.json.example" not in script
    assert script.count('--user "$HOST_USER_ID:$HOST_GROUP_ID"') == 5


def test_reusable_workflows_follow_the_current_shared_release_line() -> None:
    workflow_paths = tuple(Path(".github/workflows").glob("*.yml"))
    reusable_prefix = "psyb0t/reusable-github-workflows/"
    expected_revision = "master"
    references: list[str] = []

    for workflow_path in workflow_paths:
        for line in workflow_path.read_text(encoding="utf-8").splitlines():
            if reusable_prefix in line:
                references.append(line.rsplit("@", maxsplit=1)[-1].strip())

    assert references
    assert set(references) == {expected_revision}


def test_public_docs_describe_the_initializer_as_a_one_shot_service() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")

    assert "two\nlong-lived services plus one one-shot volume initializer" in readme
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
    assert "ARG CHROME_FOR_TESTING_VERSION=152.0.7977.42" in dockerfile
    assert (
        "ARG CHROME_FOR_TESTING_SHA256="
        "cb77f4781cad7d5e06fcc78b4476e6a6375616e7278dc313abaa9db22ed4674e"
    ) in dockerfile
    assert "sha256sum --check --strict" in dockerfile
    assert "python3 -m zipfile -e" in dockerfile
    assert "unzip" not in dockerfile
    assert "chmod 0755 /opt/chrome/chrome /opt/chrome/chrome_crashpad_handler" in dockerfile
    assert 'grep -Fq "${CHROME_FOR_TESTING_VERSION}"' in dockerfile
    assert "DEBIAN_FRONTEND=noninteractive apt-get --yes upgrade" in dockerfile
    assert "rm --recursive --force /var/lib/apt/lists/* /ms-playwright" in dockerfile
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
    assert "- nanoid@3.3.18" in workspace
    assert "nanoid: 3.3.18" in workspace
    tooling_target = _target(makefile, "test-tooling")
    assert "bump_lighthouse_minimum_release_age.sh" in tooling_target
    assert "minimumReleaseAge: 10080" in tooling_target


def test_coverage_target_also_runs_the_lighthouse_worker_suite() -> None:
    makefile = _SOURCE_MAKEFILE.read_text(encoding="utf-8")

    assert "test-coverage: lighthouse-test dev-image ##" in makefile


def test_host_env_file_selects_the_profile_without_a_flag_or_env_var(
    tmp_path: Path,
) -> None:
    data_directory = _create_data_directory(tmp_path / "profile")
    host_env_file = tmp_path / "rankrat.env"
    host_env_file.write_text(f"RANKRAT_DATA_DIR={data_directory}\n", encoding="utf-8")
    docker_all_arguments = tmp_path / "docker-all-arguments"

    with _fake_bin_directory() as fake_bin:
        environment = {
            **os.environ,
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "RANKRAT_ENV_FILE": str(host_env_file),
            "RANKRAT_READ_ONLY": "true",
            "RANKRAT_TEST_DOCKER_ARGS": str(tmp_path / "docker-arguments"),
            "RANKRAT_TEST_DOCKER_ALL_ARGS": str(docker_all_arguments),
        }
        environment.pop("RANKRAT_DATA_DIR", None)
        result = _run_wrapper(environment, tmp_path, mode="stdio")

    assert result.returncode == 0, result.stderr
    main_run = _stdio_main_run(docker_all_arguments)
    expected_mounts = {
        f"type=bind,src={data_directory}/config,dst=/run/config,readonly",
        f"type=bind,src={data_directory}/secrets,dst=/run/secrets,readonly",
        f"type=bind,src={data_directory}/oauth,dst=/run/oauth",
        f"type=bind,src={data_directory}/state,dst=/run/state",
    }
    assert expected_mounts.issubset(set(main_run))


def test_host_env_file_enables_read_only_mode(tmp_path: Path) -> None:
    data_directory = _create_data_directory(tmp_path / "profile")
    host_env_file = tmp_path / "rankrat.env"
    host_env_file.write_text(
        f"RANKRAT_DATA_DIR={data_directory}\nRANKRAT_READ_ONLY=true\n",
        encoding="utf-8",
    )
    docker_all_arguments = tmp_path / "docker-all-arguments"

    with _fake_bin_directory() as fake_bin:
        environment = {
            **os.environ,
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "RANKRAT_ENV_FILE": str(host_env_file),
            "RANKRAT_TEST_DOCKER_ARGS": str(tmp_path / "docker-arguments"),
            "RANKRAT_TEST_DOCKER_ALL_ARGS": str(docker_all_arguments),
        }
        environment.pop("RANKRAT_DATA_DIR", None)
        environment.pop("RANKRAT_READ_ONLY", None)
        result = _run_wrapper(environment, tmp_path, mode="stdio")

    assert result.returncode == 0, result.stderr
    main_run = _stdio_main_run(docker_all_arguments)
    assert "RANKRAT_READ_ONLY=true" in main_run
    assert f"type=bind,src={data_directory}/config,dst=/run/config,readonly" in main_run


def test_host_env_file_yields_to_a_real_env_var_and_the_flag(tmp_path: Path) -> None:
    file_profile = _create_data_directory(tmp_path / "file-profile")
    env_profile = _create_data_directory(tmp_path / "env-profile")
    flag_profile = _create_data_directory(tmp_path / "flag-profile")
    host_env_file = tmp_path / "rankrat.env"
    host_env_file.write_text(f"RANKRAT_DATA_DIR={file_profile}\n", encoding="utf-8")

    base_environment = {
        **os.environ,
        "RANKRAT_ENV_FILE": str(host_env_file),
        "RANKRAT_READ_ONLY": "true",
        "RANKRAT_DATA_DIR": str(env_profile),
    }

    # A real RANKRAT_DATA_DIR env var wins over the host env file.
    docker_all_env = tmp_path / "docker-all-env"
    with _fake_bin_directory() as fake_bin:
        environment = {
            **base_environment,
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "RANKRAT_TEST_DOCKER_ARGS": str(tmp_path / "docker-args-env"),
            "RANKRAT_TEST_DOCKER_ALL_ARGS": str(docker_all_env),
        }
        result = _run_wrapper(environment, tmp_path, mode="stdio")

    assert result.returncode == 0, result.stderr
    env_main_run = _stdio_main_run(docker_all_env)
    assert f"type=bind,src={env_profile}/config,dst=/run/config,readonly" in env_main_run
    assert not any(str(file_profile) in argument for argument in env_main_run)

    # The --data-dir flag is parsed before the mode, so it must sit ahead of it.
    # _run_wrapper always places the mode first, so invoke bash directly here to
    # reproduce a real `rankrat --data-dir DIR stdio` launch.
    docker_all_flag = tmp_path / "docker-all-flag"
    with _fake_bin_directory() as fake_bin:
        environment = {
            **base_environment,
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "RANKRAT_TEST_DOCKER_ARGS": str(tmp_path / "docker-args-flag"),
            "RANKRAT_TEST_DOCKER_ALL_ARGS": str(docker_all_flag),
        }
        result = subprocess.run(  # noqa: S603
            [
                _BASH_EXECUTABLE,
                str(_SOURCE_WRAPPER.resolve()),
                "--data-dir",
                str(flag_profile),
                "stdio",
            ],
            capture_output=True,
            check=False,
            cwd=tmp_path,
            encoding="utf-8",
            env=environment,
        )

    assert result.returncode == 0, result.stderr
    flag_main_run = _stdio_main_run(docker_all_flag)
    assert f"type=bind,src={flag_profile}/config,dst=/run/config,readonly" in flag_main_run
    assert not any(str(file_profile) in argument for argument in flag_main_run)
    assert not any(str(env_profile) in argument for argument in flag_main_run)


def _target(source: str, name: str) -> str:
    return source.split(f"\n{name}:", maxsplit=1)[1].split("\n\n", maxsplit=1)[0]


def _docker_invocations(all_args_file: Path) -> list[list[str]]:
    records = all_args_file.read_text(encoding="utf-8").split("\0")
    return [record.splitlines() for record in records if record.strip()]


def _stdio_main_run(all_args_file: Path) -> list[str]:
    invocations = _docker_invocations(all_args_file)
    main_runs = [
        invocation
        for invocation in invocations
        if invocation[:1] == ["run"] and invocation[-1:] == ["stdio"]
    ]
    assert len(main_runs) == 1, invocations
    return main_runs[0]


def _create_data_directory(path: Path) -> Path:
    path.mkdir(mode=0o700)
    config = path / "config"
    config.mkdir(mode=0o700)
    for name in ("secrets", "oauth", "state"):
        (path / name).mkdir(mode=0o700)
    rankrat_secrets = path / "secrets/rankrat"
    rankrat_secrets.mkdir(mode=0o700)
    bearer_secret = rankrat_secrets / "http-bearer-token"
    bearer_secret.write_text("test-http-bearer-token\n", encoding="utf-8")
    bearer_secret.chmod(0o600)
    boundary = config / "boundaries.json"
    boundary.write_text("{}", encoding="utf-8")
    boundary.chmod(0o600)
    return path


def _create_fake_docker(path: Path) -> None:
    # RANKRAT_TEST_DOCKER_ARGS keeps the last invocation (overwritten each call);
    # RANKRAT_TEST_DOCKER_ALL_ARGS, when set, records every invocation as a
    # NUL-terminated record so the multi-call stdio Lighthouse flow (volume
    # create, init, worker, main run, cleanup) can be inspected call by call.
    path.write_text(
        """#!/bin/sh
printf '%s\\n' "$@" > "$RANKRAT_TEST_DOCKER_ARGS"
if [ -n "${RANKRAT_TEST_DOCKER_ALL_ARGS:-}" ]; then
    { printf '%s\\n' "$@"; printf '\\0'; } >> "$RANKRAT_TEST_DOCKER_ALL_ARGS"
fi
if [ -n "${RANKRAT_TEST_DOCKER_ENV:-}" ]; then
    printf '%s\\n' \\
        "$RANKRAT_DATA_DIR" \\
        "$RANKRAT_IMAGE" \\
        "$RANKRAT_LIGHTHOUSE_IMAGE" \\
        "$RANKRAT_HTTP_PORT" \\
        "$RANKRAT_READ_ONLY" > "$RANKRAT_TEST_DOCKER_ENV"
fi
""",
        encoding="utf-8",
    )
    path.chmod(0o700)


def _create_fake_curl(path: Path) -> None:
    # The wrapper curls the GitHub latest-release API in resolve_latest_tag
    # (setup pins to it). Stub it with a canned tag_name so setup runs offline.
    path.write_text(
        """#!/bin/sh
printf '%s\\n' '{"tag_name": "v1.2.3"}'
""",
        encoding="utf-8",
    )
    path.chmod(0o700)


@contextmanager
def _fake_bin_directory() -> Iterator[Path]:
    scratch_root = Path(".testing/runtime-fixtures").resolve()
    scratch_root.mkdir(parents=True, exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix="rankrat-wrapper-", dir=scratch_root))
    try:
        _create_fake_docker(directory / "docker")
        _create_fake_curl(directory / "curl")
        yield directory
    finally:
        shutil.rmtree(directory)


def _run_wrapper(
    environment: dict[str, str],
    working_directory: Path,
    mode: str = "stdio",
    arguments: tuple[str, ...] = (),
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        [_BASH_EXECUTABLE, str(_SOURCE_WRAPPER.resolve()), mode, *arguments],
        capture_output=True,
        check=False,
        cwd=working_directory,
        encoding="utf-8",
        env=environment,
    )
