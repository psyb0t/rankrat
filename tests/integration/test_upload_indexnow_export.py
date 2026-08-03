from __future__ import annotations

import subprocess
import zipfile
from pathlib import Path

_EXPORT_LIBRARY = Path(__file__).resolve().parents[2] / "scripts" / "indexnow_export.sh"
_VALID_KEY = "a" * 64


def _run_exporter_function(function: str, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 -- only the checked-in exporter library is sourced.
        [
            "/bin/bash",
            "-o",
            "errexit",
            "-o",
            "nounset",
            "-c",
            f'source "$1"; shift; {function} "$@"',
            "--",
            str(_EXPORT_LIBRARY),
            *arguments,
        ],
        check=False,
        capture_output=True,
        text=True,
    )


def _publish_key(static_directory: Path, key_file: Path) -> subprocess.CompletedProcess[str]:
    return _run_exporter_function("publish_indexnow_key", str(static_directory), str(key_file))


def _verify_archive(archive_file: Path, key: str) -> subprocess.CompletedProcess[str]:
    return _run_exporter_function("verify_indexnow_archive", str(archive_file), key)


def test_exporter_copies_only_a_valid_local_indexnow_key(tmp_path: Path) -> None:
    static_directory = tmp_path / "static"
    static_directory.mkdir()
    key_file = tmp_path / "indexnow-main-key"
    key_file.write_text(_VALID_KEY, encoding="utf-8")

    result = _publish_key(static_directory, key_file)

    assert result.returncode == 0
    assert result.stdout == _VALID_KEY
    assert (static_directory / f"{_VALID_KEY}.txt").read_text(encoding="utf-8") == (
        f"{_VALID_KEY}\n"
    )


def test_exporter_skips_a_missing_key_and_rejects_malformed_key(tmp_path: Path) -> None:
    static_directory = tmp_path / "static"
    static_directory.mkdir()
    missing = tmp_path / "missing"

    assert _publish_key(static_directory, missing).returncode == 0
    assert not tuple(static_directory.iterdir())

    malformed = tmp_path / "indexnow-main-key"
    malformed.write_text(f"{_VALID_KEY}\nnot-a-valid-second-line", encoding="utf-8")
    result = _publish_key(static_directory, malformed)

    assert result.returncode != 0
    assert "malformed" in result.stderr


def test_exporter_refuses_a_zip_missing_the_public_indexnow_key(tmp_path: Path) -> None:
    static_directory = tmp_path / "static"
    static_directory.mkdir()
    key_file = tmp_path / "indexnow-main-key"
    key_file.write_text(_VALID_KEY, encoding="utf-8")
    archive_file = tmp_path / "static.zip"

    assert _publish_key(static_directory, key_file).returncode == 0
    with zipfile.ZipFile(archive_file, "w") as archive:
        archive.write(static_directory / f"{_VALID_KEY}.txt", f"{_VALID_KEY}.txt")
    with zipfile.ZipFile(archive_file) as archive:
        assert archive.read(f"{_VALID_KEY}.txt") == f"{_VALID_KEY}\n".encode()

    assert _verify_archive(archive_file, _VALID_KEY).returncode == 0

    missing_file_archive = tmp_path / "missing-key.zip"
    unrelated_file = static_directory / "unrelated.txt"
    unrelated_file.write_text("unrelated", encoding="utf-8")
    with zipfile.ZipFile(missing_file_archive, "w") as archive:
        archive.write(unrelated_file, unrelated_file.name)

    missing_result = _verify_archive(missing_file_archive, _VALID_KEY)

    assert missing_result.returncode != 0
    assert "missing" in missing_result.stderr

    invalid_file_archive = tmp_path / "invalid-key.zip"
    with zipfile.ZipFile(invalid_file_archive, "w") as archive:
        archive.writestr(f"{_VALID_KEY}.txt", "not-the-indexnow-key\n")

    invalid_result = _verify_archive(invalid_file_archive, _VALID_KEY)

    assert invalid_result.returncode != 0
    assert "invalid" in invalid_result.stderr
