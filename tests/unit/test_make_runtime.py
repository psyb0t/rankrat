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
    assert "RANKRAT_READ_ONLY=$(RANKRAT_READ_ONLY)" in source
    assert "RANKRAT_UNBOUNDED=$(RANKRAT_UNBOUNDED)" in source
    assert "./rankrat.sh" in source
    assert "$(WRAPPER) stdio" in _target(source, "run")
    assert "$(WRAPPER) http" in _target(source, "run-http")


def test_local_dev_image_mode_is_an_explicit_checked_fallback() -> None:
    source = _SOURCE_MAKEFILE.read_text(encoding="utf-8")
    target = _target(source, "dev-image")

    assert "RANKRAT_DEV_IMAGE_SOURCE ?= build" in source
    assert "build) docker build -f Dockerfile.dev -t $(DEV_IMAGE) ." in target
    assert 'local) docker image inspect "$(DEV_IMAGE)" >/dev/null 2>&1' in target
    assert "RANKRAT_DEV_IMAGE_SOURCE must be build or local" in target
    assert "RANKRAT_DEV_IMAGE_SOURCE=local test" in _target(source, "test-local")


def test_wrapper_allows_only_explicit_unbounded_persistence() -> None:
    source = _SOURCE_WRAPPER.read_text(encoding="utf-8")

    assert 'read_only="${RANKRAT_READ_ONLY:-true}"' in source
    assert 'unbounded="${RANKRAT_UNBOUNDED:-false}"' in source
    assert "RANKRAT_UNBOUNDED=true requires RANKRAT_READ_ONLY=false" in source
    assert _READ_ONLY_MOUNT_ASSIGNMENT in source
    assert _WRITABLE_MOUNT_ASSIGNMENT in source
    assert 'serve_boundary_mount="$readonly_boundary_mount"' in source
    assert 'serve_boundary_mount="$writable_boundary_mount"' in source
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
    assert "chmod 700 config oauth secrets secrets/rankrat" in target
    assert 'test -f "$$token" && test ! -L "$$token"' in target
    assert "secrets.token_urlsafe(32)" in target
    assert 'chmod 600 "$$token"' in target


def _target(source: str, name: str) -> str:
    return source.split(f"\n{name}:", maxsplit=1)[1].split("\n\n", maxsplit=1)[0]
