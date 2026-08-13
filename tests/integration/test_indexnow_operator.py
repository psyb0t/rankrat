from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_SCRIPT = Path("scripts/init_indexnow.py")
_MAKEFILE = Path("Makefile")
_PINNED_PYTHON = "uv run --frozen --no-sync python"
_INITIALIZER_SCRIPT = "scripts/init_indexnow.py"
_VERIFIER_SCRIPT = "scripts/verify_indexnow_public_key.py"
_CONTAINER_BOUNDARY_FILE = "$(INDEXNOW_VERIFY_BOUNDARY_FILE)"
_CONTAINER_KEY_FILE = "$(INDEXNOW_VERIFY_KEY_FILE)"
_TARGET_ID = "example-site"
_TARGET_HOST = "example.com"


def test_indexnow_make_targets_use_the_pinned_project_python_runtime() -> None:
    makefile = _MAKEFILE.read_text(encoding="utf-8")
    initializer_target = makefile.split("init-indexnow:", maxsplit=1)[1].split("\n\n", maxsplit=1)[
        0
    ]
    verifier_target = makefile.split("verify-indexnow-key:", maxsplit=1)[1].split(
        "\n\n", maxsplit=1
    )[0]

    assert f"$(INDEXNOW_INIT_RUN) {_PINNED_PYTHON} {_INITIALIZER_SCRIPT}" in initializer_target
    assert f"$(INDEXNOW_VERIFY_RUN) {_PINNED_PYTHON} {_VERIFIER_SCRIPT}" in verifier_target
    assert _CONTAINER_BOUNDARY_FILE in verifier_target
    assert _CONTAINER_KEY_FILE in verifier_target


def test_indexnow_initializer_script_is_idempotent_and_never_submits(tmp_path: Path) -> None:
    boundary_file = tmp_path / "boundaries.json"
    key_file = tmp_path / "secrets" / "indexnow" / "key"
    boundary_file.write_text(json.dumps({"accounts": []}), encoding="utf-8")
    command = [
        sys.executable,
        str(_SCRIPT),
        "--boundary-file",
        str(boundary_file),
        "--key-file",
        str(key_file),
        "--target-id",
        _TARGET_ID,
        "--host",
        _TARGET_HOST,
    ]

    first = subprocess.run(  # noqa: S603 -- fixed local Python script and tmp-only arguments.
        command,
        check=False,
        capture_output=True,
        text=True,
    )
    key = key_file.read_text(encoding="utf-8")
    second = subprocess.run(  # noqa: S603 -- fixed local Python script and tmp-only arguments.
        command,
        check=False,
        capture_output=True,
        text=True,
    )

    assert first.returncode == 0
    assert second.returncode == 0
    assert key not in first.stdout
    assert key not in second.stdout
    assert key_file.read_text(encoding="utf-8") == key
    assert (
        json.loads(boundary_file.read_text(encoding="utf-8"))["indexnow_targets"][0]["key_location"]
        == f"https://{_TARGET_HOST}/{key}.txt"
    )
