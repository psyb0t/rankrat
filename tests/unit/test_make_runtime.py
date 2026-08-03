from pathlib import Path

_SOURCE_MAKEFILE = Path("Makefile")
_DEFAULT_READ_ONLY_MOUNT = "dst=/run/config/boundaries.json,readonly"
_UNBOUNDED_DIRECTORY_MOUNT = "dst=/run/config"
_UNBOUNDED_MOUNT_ASSIGNMENT = (
    "RUNTIME_BOUNDARY_MOUNT := --mount type=bind,src=$(BOUNDARY_DIRECTORY),dst=/run/config"
)
_BOUNDED_MOUNT_ASSIGNMENT = (
    "RUNTIME_BOUNDARY_MOUNT := "
    "--mount type=bind,src=$(BOUNDARIES),dst=/run/config/boundaries.json,readonly"
)


def test_runtime_make_targets_allow_only_explicit_unbounded_persistence() -> None:
    source = _SOURCE_MAKEFILE.read_text(encoding="utf-8")
    runtime_target = _target(source, "run-http")

    assert "RANKRAT_READ_ONLY ?= true" in source
    assert "RANKRAT_UNBOUNDED ?= false" in source
    assert "RANKRAT_UNBOUNDED=true requires RANKRAT_READ_ONLY=false" in source
    assert "RUNTIME_BOUNDARY_FILE := /run/config/$(BOUNDARY_FILENAME)" in source
    assert _UNBOUNDED_MOUNT_ASSIGNMENT in source
    assert _BOUNDED_MOUNT_ASSIGNMENT in source
    assert "-e RANKRAT_READ_ONLY=$(RANKRAT_READ_ONLY)" in runtime_target
    assert "-e RANKRAT_UNBOUNDED=$(RANKRAT_UNBOUNDED)" in runtime_target
    assert "-e RANKRAT_BOUNDARY_FILE=$(RUNTIME_BOUNDARY_FILE)" in runtime_target
    assert "$(RUNTIME_BOUNDARY_MOUNT)" in runtime_target
    assert _DEFAULT_READ_ONLY_MOUNT in source
    assert _UNBOUNDED_DIRECTORY_MOUNT in source


def test_init_config_creates_and_preserves_a_safe_http_bearer_secret() -> None:
    source = _SOURCE_MAKEFILE.read_text(encoding="utf-8")
    target = _target(source, "init-config")

    assert "secrets/rankrat/http-bearer-token" in target
    assert "chmod 700 config oauth secrets secrets/rankrat" in target
    assert 'test -f "$$token" && test ! -L "$$token"' in target
    assert "secrets.token_urlsafe(32)" in target
    assert 'chmod 600 "$$token"' in target


def _target(source: str, name: str) -> str:
    return source.split(f"{name}:", maxsplit=1)[1].split("\n\n", maxsplit=1)[0]
