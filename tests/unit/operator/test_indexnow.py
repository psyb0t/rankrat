from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import httpx
import pytest

from rankrat.errors import SchemaFetchError
from rankrat.operator import indexnow
from rankrat.operator.indexnow import (
    IndexNowInitializationError,
    IndexNowPublicKeyVerificationError,
    initialize_indexnow,
    verify_indexnow_public_key,
)
from rankrat.providers.schema_fetch import ResolvedAddress


def _boundary_file(path: Path) -> Path:
    boundary_file = path / "boundaries.json"
    boundary_file.write_text(json.dumps({"accounts": []}), encoding="utf-8")
    return boundary_file


def _environment_file(path: Path) -> Path:
    environment_file = path / ".env"
    environment_file.write_text("RANKRAT_ENABLE_WRITES=false\n", encoding="utf-8")
    return environment_file


def test_initialize_creates_a_mode_600_key_and_exact_target(tmp_path: Path) -> None:
    boundary_file = _boundary_file(tmp_path)
    environment_file = _environment_file(tmp_path)
    key_file = tmp_path / "secrets" / "indexnow-main-key"

    result = initialize_indexnow(boundary_file, environment_file, key_file)

    key = key_file.read_text(encoding="utf-8")
    boundary = json.loads(boundary_file.read_text(encoding="utf-8"))
    environment = environment_file.read_text(encoding="utf-8")
    assert result.created_key is True
    assert result.configured_target is True
    assert len(key) == 64
    assert key.isalnum()
    assert stat.S_IMODE(key_file.stat().st_mode) == 0o600
    assert boundary["indexnow_targets"] == [
        {
            "id": "site",
            "host": "example.com",
            "key_location": f"https://example.com/{key}.txt",
            "key_file": "/run/secrets/indexnow/key",
        }
    ]
    assert "RANKRAT_ENABLE_WRITES=false" in environment
    assert "RANKRAT_LIVE_INDEXNOW_TARGET_ID=site" in environment
    assert "RANKRAT_LIVE_INDEXNOW_URL=https://example.com/" in environment


def test_initialize_uses_an_operator_selected_target(tmp_path: Path) -> None:
    boundary_file = _boundary_file(tmp_path)
    environment_file = _environment_file(tmp_path)
    key_file = tmp_path / "secrets" / "indexnow" / "key"

    initialize_indexnow(
        boundary_file,
        environment_file,
        key_file,
        target_id="documentation",
        host="docs.example",
    )

    key = key_file.read_text(encoding="utf-8")
    boundary = json.loads(boundary_file.read_text(encoding="utf-8"))
    assert boundary["indexnow_targets"][0] == {
        "id": "documentation",
        "host": "docs.example",
        "key_location": f"https://docs.example/{key}.txt",
        "key_file": "/run/secrets/indexnow/key",
    }


@pytest.mark.parametrize(
    "host",
    ("127.0.0.1", "localhost", "https://example.com", "example.com/path"),
)
def test_initialize_rejects_unsafe_operator_hosts_before_creating_a_key(
    tmp_path: Path,
    host: str,
) -> None:
    boundary_file = _boundary_file(tmp_path)
    environment_file = _environment_file(tmp_path)
    key_file = tmp_path / "secrets" / "indexnow" / "key"

    with pytest.raises(IndexNowInitializationError, match="target input"):
        initialize_indexnow(
            boundary_file,
            environment_file,
            key_file,
            target_id="documentation",
            host=host,
        )

    assert not key_file.exists()


def test_initialize_is_idempotent_and_does_not_change_explicit_write_values(tmp_path: Path) -> None:
    boundary_file = _boundary_file(tmp_path)
    environment_file = _environment_file(tmp_path)
    environment_file.write_text(
        "RANKRAT_ENABLE_WRITES=true\nRANKRAT_RUN_LIVE_INDEXNOW_SUBMISSION=true\n",
        encoding="utf-8",
    )
    key_file = tmp_path / "secrets" / "indexnow-main-key"

    first = initialize_indexnow(boundary_file, environment_file, key_file)
    key_before = key_file.read_text(encoding="utf-8")
    second = initialize_indexnow(boundary_file, environment_file, key_file)

    assert first.created_key is True
    assert second.created_key is False
    assert second.configured_target is False
    assert key_file.read_text(encoding="utf-8") == key_before
    assert "RANKRAT_ENABLE_WRITES=true" in environment_file.read_text(encoding="utf-8")
    assert "RANKRAT_RUN_LIVE_INDEXNOW_SUBMISSION=true" in environment_file.read_text(
        encoding="utf-8"
    )


@pytest.mark.parametrize(
    "contents",
    ("too short", "x" * 129, "valid-key\n", "key with whitespace"),
)
def test_initialize_rejects_malformed_key_without_replacing_configuration(
    tmp_path: Path,
    contents: str,
) -> None:
    boundary_file = _boundary_file(tmp_path)
    environment_file = _environment_file(tmp_path)
    key_file = tmp_path / "secrets" / "indexnow-main-key"
    key_file.parent.mkdir()
    key_file.write_text(contents, encoding="utf-8")
    os.chmod(key_file, 0o600)
    original_boundary = boundary_file.read_bytes()
    original_environment = environment_file.read_bytes()

    with pytest.raises(IndexNowInitializationError, match="key"):
        initialize_indexnow(boundary_file, environment_file, key_file)

    assert boundary_file.read_bytes() == original_boundary
    assert environment_file.read_bytes() == original_environment


def test_initialize_rejects_conflicting_target_without_overwrite(tmp_path: Path) -> None:
    boundary_file = _boundary_file(tmp_path)
    environment_file = _environment_file(tmp_path)
    key_file = tmp_path / "secrets" / "indexnow-main-key"
    key_file.parent.mkdir()
    key_file.write_text("a" * 64, encoding="utf-8")
    os.chmod(key_file, 0o600)
    boundary_file.write_text(
        json.dumps(
            {
                "accounts": [],
                "indexnow_targets": [
                    {
                        "id": "different-id",
                        "host": "example.com",
                        "key_location": "https://example.com/other.txt",
                        "key_file": "/run/secrets/other",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    original_boundary = boundary_file.read_bytes()

    with pytest.raises(IndexNowInitializationError, match="conflicts"):
        initialize_indexnow(boundary_file, environment_file, key_file)

    assert boundary_file.read_bytes() == original_boundary


@pytest.mark.parametrize(
    ("boundary_contents", "environment_contents"),
    (("not-json", "RANKRAT_ENABLE_WRITES=false\n"), ("{}", "broken assignment")),
)
def test_initialize_rejects_invalid_inputs_without_creating_a_key(
    tmp_path: Path,
    boundary_contents: str,
    environment_contents: str,
) -> None:
    boundary_file = tmp_path / "boundaries.json"
    environment_file = tmp_path / ".env"
    key_file = tmp_path / "secrets" / "indexnow-main-key"
    boundary_file.write_text(boundary_contents, encoding="utf-8")
    environment_file.write_text(environment_contents, encoding="utf-8")

    with pytest.raises(IndexNowInitializationError):
        initialize_indexnow(boundary_file, environment_file, key_file)

    assert not key_file.exists()


@pytest.mark.parametrize(
    "boundary_contents",
    (
        "[]",
        json.dumps({"accounts": {}}),
        json.dumps({"accounts": [], "indexnow_targets": {}}),
    ),
)
def test_initialize_rejects_invalid_boundary_shapes_without_creating_a_key(
    tmp_path: Path,
    boundary_contents: str,
) -> None:
    boundary_file = tmp_path / "boundaries.json"
    environment_file = _environment_file(tmp_path)
    key_file = tmp_path / "secrets" / "indexnow-main-key"
    boundary_file.write_text(boundary_contents, encoding="utf-8")

    with pytest.raises(IndexNowInitializationError, match="boundary document|IndexNow targets"):
        initialize_indexnow(boundary_file, environment_file, key_file)

    assert not key_file.exists()


@pytest.mark.parametrize(
    "environment_contents",
    ("\x00", "# a comment\n\nnot-an-assignment\n"),
)
def test_initialize_rejects_unsafe_environment_contents_without_creating_a_key(
    tmp_path: Path,
    environment_contents: str,
) -> None:
    boundary_file = _boundary_file(tmp_path)
    environment_file = tmp_path / ".env"
    key_file = tmp_path / "secrets" / "indexnow-main-key"
    environment_file.write_text(environment_contents, encoding="utf-8")

    with pytest.raises(IndexNowInitializationError, match="null byte|invalid assignment"):
        initialize_indexnow(boundary_file, environment_file, key_file)

    assert not key_file.exists()


def test_initialize_rejects_nonregular_key_path_and_symlinked_parent(tmp_path: Path) -> None:
    boundary_file = _boundary_file(tmp_path)
    environment_file = _environment_file(tmp_path)
    directory_key_file = tmp_path / "directory-key"
    directory_key_file.mkdir()

    with pytest.raises(IndexNowInitializationError, match="regular file"):
        initialize_indexnow(boundary_file, environment_file, directory_key_file)

    actual_parent = tmp_path / "actual-secrets"
    actual_parent.mkdir()
    symlink_parent = tmp_path / "symlinked-secrets"
    symlink_parent.symlink_to(actual_parent, target_is_directory=True)

    with pytest.raises(IndexNowInitializationError, match="directory"):
        initialize_indexnow(boundary_file, environment_file, symlink_parent / "indexnow-main-key")


def test_initialize_rejects_nonobject_target_without_writing(tmp_path: Path) -> None:
    boundary_file = _boundary_file(tmp_path)
    environment_file = _environment_file(tmp_path)
    key_file = tmp_path / "secrets" / "indexnow-main-key"
    boundary_file.write_text(
        json.dumps({"accounts": [], "indexnow_targets": ["not-an-object"]}),
        encoding="utf-8",
    )

    with pytest.raises(IndexNowInitializationError, match="JSON object"):
        initialize_indexnow(boundary_file, environment_file, key_file)

    assert not key_file.exists()


def test_low_level_key_and_atomic_write_errors_are_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key_file = tmp_path / "secrets" / "indexnow-main-key"

    def raise_os_error(*_: object, **__: object) -> None:
        raise OSError("synthetic filesystem failure")

    monkeypatch.setattr(indexnow.Path, "mkdir", raise_os_error)
    with pytest.raises(IndexNowInitializationError, match="directory is unavailable"):
        indexnow._load_or_create_key(key_file)

    monkeypatch.undo()
    key_file.parent.mkdir()
    key_file.write_text("a" * 64, encoding="utf-8")
    os.chmod(key_file, 0o600)
    monkeypatch.setattr(indexnow.Path, "stat", raise_os_error)
    with pytest.raises(IndexNowInitializationError, match="key is unavailable"):
        indexnow._require_mode_600(key_file)

    monkeypatch.undo()
    monkeypatch.setattr(indexnow.os, "replace", raise_os_error)
    with pytest.raises(IndexNowInitializationError, match="could not write"):
        indexnow._write_atomically(tmp_path / "atomic-target", "contents", 0o600)

    monkeypatch.undo()
    monkeypatch.setattr(indexnow.tempfile, "mkstemp", raise_os_error)
    with pytest.raises(IndexNowInitializationError, match="could not write"):
        indexnow._write_atomically(tmp_path / "atomic-target", "contents", 0o600)

    monkeypatch.undo()
    monkeypatch.setattr(indexnow.Path, "unlink", raise_os_error)
    indexnow._write_atomically(tmp_path / "atomic-target", "contents", 0o600)


def test_unreadable_environment_and_key_files_are_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key_file = tmp_path / "indexnow-main-key"
    key_file.write_text("a" * 64, encoding="utf-8")
    os.chmod(key_file, 0o600)

    with pytest.raises(IndexNowInitializationError, match="environment file is unavailable"):
        indexnow._read_environment_lines(tmp_path / "missing.env")

    def raise_os_error(*_: object, **__: object) -> str:
        raise OSError("synthetic read failure")

    monkeypatch.setattr(indexnow.Path, "read_text", raise_os_error)
    with pytest.raises(IndexNowInitializationError, match="key is unavailable"):
        indexnow._load_or_create_key(key_file)
    with pytest.raises(IndexNowPublicKeyVerificationError, match="key is unavailable"):
        indexnow._load_existing_key(key_file)


def test_target_helpers_reject_invalid_entries_and_preserve_unrelated_targets() -> None:
    key = "a" * 64

    with pytest.raises(IndexNowInitializationError, match="JSON list"):
        indexnow._validated_target_entries({"indexnow_targets": {}})
    with pytest.raises(IndexNowPublicKeyVerificationError, match="not configured"):
        indexnow._require_configured_target({}, "site", key)
    with pytest.raises(IndexNowPublicKeyVerificationError, match="not configured"):
        indexnow._require_configured_target({"indexnow_targets": ["not-an-object"]}, "site", key)
    with pytest.raises(IndexNowPublicKeyVerificationError, match="not configured"):
        indexnow._require_configured_target(
            {"indexnow_targets": [{"id": "other", "host": "other.example"}]},
            "site",
            key,
        )

    document: dict[str, object] = {
        "indexnow_targets": [
            {
                "id": "other",
                "host": "other.example",
                "key_location": "https://other.example/key.txt",
                "key_file": "/run/secrets/other",
            }
        ]
    }
    assert indexnow._configure_target(document, key, "site", "example.com") is True
    assert len(indexnow._validated_target_entries(document)) == 2


@pytest.mark.asyncio
async def test_verify_public_key_requires_the_direct_configured_file(tmp_path: Path) -> None:
    boundary_file = _boundary_file(tmp_path)
    environment_file = _environment_file(tmp_path)
    key_file = tmp_path / "secrets" / "indexnow-main-key"
    initialize_indexnow(boundary_file, environment_file, key_file)
    key = key_file.read_text(encoding="utf-8")
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, content=f"{key}\n".encode("ascii"))

    result = await verify_indexnow_public_key(
        boundary_file,
        key_file,
        transport_factory=lambda: httpx.MockTransport(handler),
    )

    assert result.host == "example.com"
    assert len(requests) == 1
    assert requests[0].method == "GET"
    assert requests[0].url.scheme == "https"
    assert requests[0].url.host == "example.com"
    assert requests[0].url.path == f"/{key}.txt"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    (
        httpx.Response(301, headers={"location": "https://untrusted.example/"}),
        httpx.Response(200, content=b"wrong-key\n"),
        httpx.Response(200, content=b"x" * 131),
    ),
)
async def test_verify_public_key_rejects_redirects_mismatches_and_oversized_bodies(
    tmp_path: Path,
    response: httpx.Response,
) -> None:
    boundary_file = _boundary_file(tmp_path)
    environment_file = _environment_file(tmp_path)
    key_file = tmp_path / "secrets" / "indexnow-main-key"
    initialize_indexnow(boundary_file, environment_file, key_file)

    with pytest.raises(IndexNowPublicKeyVerificationError):
        await verify_indexnow_public_key(
            boundary_file,
            key_file,
            transport_factory=lambda: httpx.MockTransport(lambda _: response),
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    (
        httpx.Response(404),
        httpx.Response(503),
    ),
)
async def test_verify_public_key_rejects_non_success_statuses(
    tmp_path: Path,
    response: httpx.Response,
) -> None:
    boundary_file = _boundary_file(tmp_path)
    environment_file = _environment_file(tmp_path)
    key_file = tmp_path / "secrets" / "indexnow-main-key"
    initialize_indexnow(boundary_file, environment_file, key_file)

    with pytest.raises(IndexNowPublicKeyVerificationError, match="HTTP 200"):
        await verify_indexnow_public_key(
            boundary_file,
            key_file,
            transport_factory=lambda: httpx.MockTransport(lambda _: response),
        )


@pytest.mark.asyncio
async def test_verify_public_key_rejects_transport_failures_without_key_disclosure(
    tmp_path: Path,
) -> None:
    boundary_file = _boundary_file(tmp_path)
    environment_file = _environment_file(tmp_path)
    key_file = tmp_path / "secrets" / "indexnow-main-key"
    initialize_indexnow(boundary_file, environment_file, key_file)
    key = key_file.read_text(encoding="utf-8")

    def raise_transport_error(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("synthetic network failure")

    with pytest.raises(IndexNowPublicKeyVerificationError, match="request failed") as error:
        await verify_indexnow_public_key(
            boundary_file,
            key_file,
            transport_factory=lambda: httpx.MockTransport(raise_transport_error),
        )

    assert key not in str(error.value)


@pytest.mark.asyncio
async def test_verify_public_key_rejects_a_nonpublic_dns_resolution_before_request(
    tmp_path: Path,
) -> None:
    boundary_file = _boundary_file(tmp_path)
    environment_file = _environment_file(tmp_path)
    key_file = tmp_path / "secrets" / "indexnow-main-key"
    initialize_indexnow(boundary_file, environment_file, key_file)

    async def reject_resolution(_: str) -> tuple[ResolvedAddress, ...]:
        raise SchemaFetchError("synthetic nonpublic address")

    with pytest.raises(IndexNowPublicKeyVerificationError, match="safely reachable"):
        await verify_indexnow_public_key(
            boundary_file,
            key_file,
            resolver=reject_resolution,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "key_contents, boundary_update, message",
    (
        (None, None, "regular file"),
        ("invalid key", None, "malformed"),
        ("a" * 64, {"indexnow_targets": []}, "not configured"),
        ("a" * 64, {"indexnow_targets": ["not-an-object"]}, "not configured"),
        (
            "a" * 64,
            {
                "indexnow_targets": [
                    {
                        "id": "site",
                        "host": "example.com",
                        "key_location": "https://example.com/wrong.txt",
                        "key_file": "/run/secrets/indexnow/key",
                    }
                ]
            },
            "does not match",
        ),
    ),
)
async def test_verify_public_key_rejects_local_preconditions_before_network(
    tmp_path: Path,
    key_contents: str | None,
    boundary_update: dict[str, object] | None,
    message: str,
) -> None:
    boundary_file = _boundary_file(tmp_path)
    environment_file = _environment_file(tmp_path)
    key_file = tmp_path / "secrets" / "indexnow-main-key"
    initialize_indexnow(boundary_file, environment_file, key_file)
    if key_contents is None:
        key_file.unlink()
    else:
        key_file.write_text(key_contents, encoding="utf-8")
        os.chmod(key_file, 0o600)
    if boundary_update is not None:
        boundary_file.write_text(json.dumps({"accounts": [], **boundary_update}), encoding="utf-8")
    transport_created = False

    def transport_factory() -> httpx.AsyncBaseTransport:
        nonlocal transport_created
        transport_created = True
        return httpx.MockTransport(lambda _: pytest.fail("network must not be called"))

    with pytest.raises(IndexNowPublicKeyVerificationError, match=message):
        await verify_indexnow_public_key(
            boundary_file,
            key_file,
            transport_factory=transport_factory,
        )

    assert transport_created is False


@pytest.mark.asyncio
async def test_verify_public_key_rejects_unsafe_local_key_mode_before_network(
    tmp_path: Path,
) -> None:
    boundary_file = _boundary_file(tmp_path)
    environment_file = _environment_file(tmp_path)
    key_file = tmp_path / "secrets" / "indexnow-main-key"
    initialize_indexnow(boundary_file, environment_file, key_file)
    os.chmod(key_file, 0o644)

    with pytest.raises(IndexNowPublicKeyVerificationError, match="mode is unsafe"):
        await verify_indexnow_public_key(
            boundary_file,
            key_file,
            transport_factory=lambda: pytest.fail("network must not be called"),
        )
