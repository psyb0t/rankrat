"""Prepare a single local IndexNow target without enabling any write operation."""

from __future__ import annotations

import contextlib
import json
import os
import re
import secrets
import stat
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final, cast

import httpx
from pydantic import ValidationError

from rankrat.errors import SchemaFetchError
from rankrat.models.boundaries import IndexNowTarget, normalize_indexnow_host
from rankrat.providers.schema_fetch import Resolver, create_pinned_transport, resolve_public_host

_INDEXNOW_KEY_LENGTH: Final = 64
_INDEXNOW_KEY_PATTERN: Final = re.compile(r"[A-Za-z0-9-]{8,128}\Z")
_DEFAULT_TARGET_ID: Final = "site"
_DEFAULT_HOST: Final = "example.com"
_DEFAULT_KEY_FILE_IN_CONTAINER: Final = "/run/secrets/indexnow/key"
_KEY_LOCATION_TEMPLATE: Final = "https://{host}/{key}.txt"
_HTTP_OK_STATUS: Final = 200
_PUBLIC_KEY_TIMEOUT_SECONDS: Final = 10.0
_MAX_PUBLIC_KEY_RESPONSE_BYTES: Final = 130


class IndexNowInitializationError(ValueError):
    """Raised when local IndexNow setup cannot be completed without overwrite."""


class IndexNowPublicKeyVerificationError(ValueError):
    """Raised when the configured public IndexNow ownership file is not exact."""


@dataclass(frozen=True)
class IndexNowInitializationResult:
    """Secret-free result of a local IndexNow initialization."""

    created_key: bool
    configured_target: bool


@dataclass(frozen=True)
class IndexNowPublicKeyVerificationResult:
    """Secret-free proof that one exact public ownership file is directly reachable."""

    host: str


def initialize_indexnow(
    boundary_file: Path,
    key_file: Path,
    *,
    target_id: str = _DEFAULT_TARGET_ID,
    host: str = _DEFAULT_HOST,
) -> IndexNowInitializationResult:
    """Create or retain one key and exact target without modifying runtime settings."""
    boundary_document = _read_boundary_document(boundary_file)
    normalized_target_id, normalized_host = _normalize_target_inputs(target_id, host)
    _validated_target_entries(boundary_document)
    key, created_key = _load_or_create_key(key_file)
    configured_target = _configure_target(
        boundary_document,
        key,
        normalized_target_id,
        normalized_host,
    )
    _write_atomically(boundary_file, _serialize_json(boundary_document), 0o600)
    return IndexNowInitializationResult(created_key, configured_target)


async def verify_indexnow_public_key(
    boundary_file: Path,
    key_file: Path,
    *,
    target_id: str = _DEFAULT_TARGET_ID,
    resolver: Resolver = resolve_public_host,
    transport_factory: Callable[[], httpx.AsyncBaseTransport | None] | None = None,
) -> IndexNowPublicKeyVerificationResult:
    """Verify the exact configured ownership file without redirects or URL submission."""

    key = _load_existing_key(key_file)
    boundary_document = _read_boundary_document(boundary_file)
    target = _require_configured_target(boundary_document, target_id, key)
    transport: httpx.AsyncBaseTransport | None
    try:
        if transport_factory is not None:
            transport = transport_factory()
        else:
            addresses = await resolver(target.host)
            if not addresses:
                raise IndexNowPublicKeyVerificationError("public IndexNow host cannot be resolved")
            transport = create_pinned_transport(target.host, str(addresses[0]))
        async with (
            httpx.AsyncClient(
                transport=transport,
                follow_redirects=False,
                timeout=_PUBLIC_KEY_TIMEOUT_SECONDS,
                trust_env=False,
            ) as client,
            client.stream("GET", target.key_location) as response,
        ):
            if response.is_redirect:
                raise IndexNowPublicKeyVerificationError(
                    "public IndexNow ownership file must not redirect"
                )
            if response.status_code != _HTTP_OK_STATUS:
                raise IndexNowPublicKeyVerificationError(
                    "public IndexNow ownership file did not return HTTP 200"
                )
            body = await _bounded_public_key_body(response)
    except SchemaFetchError as error:
        raise IndexNowPublicKeyVerificationError(
            "public IndexNow host is not safely reachable"
        ) from error
    except httpx.HTTPError as error:
        raise IndexNowPublicKeyVerificationError(
            "public IndexNow ownership file request failed"
        ) from error
    expected_bodies = (
        key.encode("ascii"),
        key.encode("ascii") + b"\n",
        key.encode("ascii") + b"\r\n",
    )
    if body not in expected_bodies:
        raise IndexNowPublicKeyVerificationError(
            "public IndexNow ownership file does not match the local key"
        )
    return IndexNowPublicKeyVerificationResult(host=target.host)


def _normalize_target_inputs(target_id: str, host: str) -> tuple[str, str]:
    try:
        normalized_host = normalize_indexnow_host(host)
        target = IndexNowTarget.model_validate(
            {
                "id": target_id,
                "host": normalized_host,
                "key_location": _key_location(normalized_host, "placeholder"),
                "key_file": _DEFAULT_KEY_FILE_IN_CONTAINER,
            }
        )
    except (ValidationError, ValueError) as error:
        raise IndexNowInitializationError("IndexNow target input is invalid") from error
    return target.id, target.host


def _key_location(host: str, key: str) -> str:
    return _KEY_LOCATION_TEMPLATE.format(host=host, key=key)


def _read_boundary_document(path: Path) -> dict[str, object]:
    try:
        raw_document: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise IndexNowInitializationError("boundary document is not valid JSON") from error
    if not isinstance(raw_document, dict):
        raise IndexNowInitializationError("boundary document must be a JSON object")
    document = cast(dict[str, object], raw_document)
    accounts = document.get("accounts")
    if not isinstance(accounts, list):
        raise IndexNowInitializationError("boundary document accounts must be a JSON list")
    targets = document.get("indexnow_targets", [])
    if not isinstance(targets, list):
        raise IndexNowInitializationError("IndexNow targets must be a JSON list")
    return document


def _load_or_create_key(path: Path) -> tuple[str, bool]:
    if path.exists() or path.is_symlink():
        if not path.is_file() or path.is_symlink():
            raise IndexNowInitializationError("IndexNow key path must be a regular file")
        try:
            key = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as error:
            raise IndexNowInitializationError("IndexNow key is unavailable") from error
        if not _INDEXNOW_KEY_PATTERN.fullmatch(key):
            raise IndexNowInitializationError("IndexNow key is malformed")
        _require_mode_600(path)
        return key, False
    if path.parent.is_symlink():
        raise IndexNowInitializationError("IndexNow key directory must not be a symlink")
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    except OSError as error:
        raise IndexNowInitializationError("IndexNow key directory is unavailable") from error
    key = secrets.token_hex(_INDEXNOW_KEY_LENGTH // 2)
    _write_atomically(path, key, 0o600)
    return key, True


def _load_existing_key(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise IndexNowPublicKeyVerificationError("local IndexNow key must be a regular file")
    try:
        key = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise IndexNowPublicKeyVerificationError("local IndexNow key is unavailable") from error
    if not _INDEXNOW_KEY_PATTERN.fullmatch(key):
        raise IndexNowPublicKeyVerificationError("local IndexNow key is malformed")
    try:
        _require_mode_600(path)
    except IndexNowInitializationError as error:
        raise IndexNowPublicKeyVerificationError("local IndexNow key mode is unsafe") from error
    return key


def _require_configured_target(
    document: dict[str, object],
    target_id: str,
    key: str,
) -> IndexNowTarget:
    raw_targets = document.get("indexnow_targets")
    if not isinstance(raw_targets, list):
        raise IndexNowPublicKeyVerificationError("IndexNow target is not configured")
    targets = cast(list[object], raw_targets)
    for raw_target in targets:
        if not isinstance(raw_target, Mapping):
            continue
        target = cast(Mapping[str, object], raw_target)
        if target.get("id") != target_id:
            continue
        try:
            configured_target = IndexNowTarget.model_validate(target)
        except ValidationError as error:
            raise IndexNowPublicKeyVerificationError(
                "IndexNow target configuration is invalid"
            ) from error
        if configured_target.key_file != Path(
            _DEFAULT_KEY_FILE_IN_CONTAINER
        ) or configured_target.key_location != _key_location(configured_target.host, key):
            raise IndexNowPublicKeyVerificationError("IndexNow target does not match the local key")
        return configured_target
    raise IndexNowPublicKeyVerificationError("IndexNow target is not configured")


async def _bounded_public_key_body(response: httpx.Response) -> bytes:
    body = bytearray()
    async for chunk in response.aiter_bytes():
        body.extend(chunk)
        if len(body) > _MAX_PUBLIC_KEY_RESPONSE_BYTES:
            raise IndexNowPublicKeyVerificationError("public IndexNow ownership file is too large")
    return bytes(body)


def _require_mode_600(path: Path) -> None:
    try:
        permissions = stat.S_IMODE(path.stat().st_mode)
    except OSError as error:
        raise IndexNowInitializationError("IndexNow key is unavailable") from error
    if permissions != 0o600:
        raise IndexNowInitializationError("IndexNow key must have mode 600")


def _configure_target(
    document: dict[str, object],
    key: str,
    target_id: str,
    host: str,
) -> bool:
    exact_target = {
        "id": target_id,
        "host": host,
        "key_location": _key_location(host, key),
        "key_file": _DEFAULT_KEY_FILE_IN_CONTAINER,
    }
    targets = _validated_target_entries(document)
    for raw_target in targets:
        target = cast(Mapping[str, object], raw_target)
        if target.get("id") == target_id or target.get("host") == host:
            if dict(target) != exact_target:
                raise IndexNowInitializationError(
                    "existing IndexNow target conflicts with the requested target"
                )
            return False
    targets.append(exact_target)
    return True


def _validated_target_entries(document: dict[str, object]) -> list[object]:
    raw_targets = document.setdefault("indexnow_targets", [])
    if not isinstance(raw_targets, list):
        raise IndexNowInitializationError("IndexNow targets must be a JSON list")
    targets = cast(list[object], raw_targets)
    for raw_target in targets:
        if not isinstance(raw_target, Mapping):
            raise IndexNowInitializationError("IndexNow target must be a JSON object")
    return targets


def _serialize_json(document: dict[str, object]) -> str:
    return json.dumps(document, indent=2, sort_keys=False) + "\n"


def _write_atomically(path: Path, contents: str, mode: int) -> None:
    temporary_path: Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        temporary_path = Path(temporary_name)
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as output:
            output.write(contents)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary_path, path)
    except OSError as error:
        raise IndexNowInitializationError("could not write local IndexNow setup") from error
    finally:
        if temporary_path is not None:  # pragma: no branch
            with contextlib.suppress(OSError):
                temporary_path.unlink(missing_ok=True)
