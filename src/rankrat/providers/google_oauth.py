"""Fixed-origin Google OAuth primitives for local operator authorization."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import stat
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from http import HTTPStatus
from pathlib import Path
from typing import cast
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from rankrat.constants import (
    DEFAULT_PROVIDER_TIMEOUT_SECONDS,
    GOOGLE_ANALYTICS_EDIT_SCOPE,
    GOOGLE_ANALYTICS_READ_SCOPE,
    GOOGLE_INDEXING_SCOPE,
    GOOGLE_SEARCH_CONSOLE_READ_SCOPE,
    GOOGLE_SEARCH_CONSOLE_WRITE_SCOPE,
    GOOGLE_SITE_VERIFICATION_SCOPE,
    GOOGLE_TAG_MANAGER_DELETE_SCOPE,
    GOOGLE_TAG_MANAGER_EDIT_SCOPE,
    GOOGLE_TAG_MANAGER_PUBLISH_SCOPE,
    GOOGLE_TAG_MANAGER_VERSION_EDIT_SCOPE,
    MAX_OAUTH_TOKEN_FILE_BYTES,
    MAX_PROVIDER_RESPONSE_BYTES,
    OAUTH_CONTAINER_LISTENER_HOST,
    OAUTH_DYNAMIC_CALLBACK_PORT,
    OAUTH_LOOPBACK_HOST,
)
from rankrat.logging import log_event
from rankrat.models.boundaries import ConfiguredAccount, Provider
from rankrat.providers.base import ProviderFailureCode, ProviderOperationError

_GOOGLE_OAUTH_ISSUER = "https://accounts.google.com"
_GOOGLE_AUTHORIZATION_URL = f"{_GOOGLE_OAUTH_ISSUER}/o/oauth2/v2/auth"
_GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"  # nosec B105  # noqa: S105
_GOOGLE_REVOCATION_URL = "https://oauth2.googleapis.com/revoke"
_GOOGLE_TOKEN_TYPE = "Bearer"  # nosec B105  # noqa: S105
_GOOGLE_AUTHORIZATION_SCOPES = (
    GOOGLE_SEARCH_CONSOLE_WRITE_SCOPE,
    GOOGLE_INDEXING_SCOPE,
    GOOGLE_ANALYTICS_READ_SCOPE,
    GOOGLE_ANALYTICS_EDIT_SCOPE,
    GOOGLE_SITE_VERIFICATION_SCOPE,
    GOOGLE_TAG_MANAGER_EDIT_SCOPE,
    GOOGLE_TAG_MANAGER_DELETE_SCOPE,
    GOOGLE_TAG_MANAGER_VERSION_EDIT_SCOPE,
    GOOGLE_TAG_MANAGER_PUBLISH_SCOPE,
)
_OAUTH_AUTHORIZATION_PROMPT = "consent"
_OAUTH_CALLBACK_PATH = "/oauth2/callback"
_OAUTH_CALLBACK_ISSUER_KEY = "iss"
_OAUTH_CALLBACK_SCOPE_KEY = "scope"
_OAUTH_CODE_VERIFIER_BYTES = 64
_OAUTH_STATE_BYTES = 32
_OAUTH_CODE_VERIFIER_MIN_CHARS = 43
_OAUTH_CODE_VERIFIER_MAX_CHARS = 128
_OAUTH_TOKEN_TEXT_CHARS = 4_096
_OAUTH_CLIENT_CONFIG_BYTES = 65_536
_OAUTH_TOKEN_RESPONSE_BYTES = 32_768
_OAUTH_MAX_SCOPES = 10
_OAUTH_TOKEN_FILE_MODE = 0o600
_OAUTH_DIRECTORY_MODE_MASK = 0o077
_OAUTH_AUTH_DIAGNOSTIC_FILE_NAME = "google-auth.log"
_OAUTH_AUTH_DIAGNOSTIC_MAX_BYTES = 65_536
_OAUTH_AUTH_DIAGNOSTIC_EVENT = "google_oauth_authorization_failed"
_OAUTH_AUTH_DIAGNOSTIC_STAGE_CONFIGURATION = "configuration"
_OAUTH_AUTH_DIAGNOSTIC_STAGE_CALLBACK = "callback"
_OAUTH_AUTH_DIAGNOSTIC_STAGE_TOKEN_EXCHANGE = "token_exchange"  # nosec B105  # noqa: S105
_OAUTH_AUTH_DIAGNOSTIC_STAGE_TOKEN_PERSISTENCE = "token_persistence"  # nosec B105  # noqa: S105
_OAUTH_CALLBACK_REQUEST_BYTES = 8_192
_OAUTH_CALLBACK_TIMEOUT_SECONDS = 300.0
_HTTP_REQUEST_LINE_PARTS = 3
_HTTP_SUCCESS_STATUS = "HTTP/1.1 200 OK"
_HTTP_BAD_REQUEST_STATUS = "HTTP/1.1 400 Bad Request"
_HTTP_CONFLICT_STATUS = "HTTP/1.1 409 Conflict"
_HTTP_CONTENT_TYPE = "Content-Type: text/html; charset=utf-8"
_HTTP_CONNECTION_CLOSE = "Connection: close"
_OAUTH_CALLBACK_SUCCESS_BODY = b"Authorization complete. You may close this window."
_OAUTH_CALLBACK_FAILURE_BODY = b"Authorization was not accepted. You may close this window."

HttpTransportFactory = Callable[[], httpx.AsyncBaseTransport | None]
BrowserOpener = Callable[[str], bool]
AuthorizationURLSink = Callable[[str], None]

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class GoogleOAuthClientConfiguration:
    """The small installed-client subset Rankrat needs for fixed Google endpoints."""

    client_id: str
    client_secret: str | None


@dataclass(frozen=True, slots=True)
class GoogleOAuthTokenRecord:
    """Refresh-only persistent authorization material for one configured account."""

    account_id: str
    client_id: str
    refresh_token: str
    scopes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GoogleOAuthAuthorizationSession:
    """One high-entropy PKCE authorization session, held only in memory."""

    code_verifier: str
    state: str
    redirect_uri: str
    scopes: tuple[str, ...]

    @classmethod
    def create(
        cls,
        redirect_port: int,
        scopes: tuple[str, ...],
    ) -> GoogleOAuthAuthorizationSession:
        if redirect_port < 1 or redirect_port > 65_535:
            raise ValueError("OAuth redirect port is outside the valid range")
        _require_scopes(scopes)
        code_verifier = secrets.token_urlsafe(_OAUTH_CODE_VERIFIER_BYTES)
        if not (
            _OAUTH_CODE_VERIFIER_MIN_CHARS <= len(code_verifier) <= _OAUTH_CODE_VERIFIER_MAX_CHARS
        ):
            raise RuntimeError("OAuth verifier length is outside the PKCE requirement")
        return cls(
            code_verifier=code_verifier,
            state=secrets.token_urlsafe(_OAUTH_STATE_BYTES),
            redirect_uri=f"http://127.0.0.1:{redirect_port}{_OAUTH_CALLBACK_PATH}",
            scopes=scopes,
        )

    @property
    def code_challenge(self) -> str:
        """Return the S256 PKCE challenge without retaining a second secret copy."""
        digest = hashlib.sha256(self.code_verifier.encode("ascii")).digest()
        return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")

    def authorization_url(self, client_id: str) -> str:
        """Build the fixed Google authorization URL for this one session."""
        if not client_id or len(client_id) > _OAUTH_TOKEN_TEXT_CHARS:
            raise ValueError("Google OAuth client ID is invalid")
        query = urlencode(
            {
                "access_type": "offline",
                "client_id": client_id,
                "code_challenge": self.code_challenge,
                "code_challenge_method": "S256",
                "prompt": _OAUTH_AUTHORIZATION_PROMPT,
                "redirect_uri": self.redirect_uri,
                "response_type": "code",
                "scope": " ".join(self.scopes),
                "state": self.state,
            }
        )
        return f"{_GOOGLE_AUTHORIZATION_URL}?{query}"

    def validate_callback(self, query: Mapping[str, tuple[str, ...]]) -> str:
        """Return the one authorization code only after a constant-time state check."""
        state_values = query.get("state", ())
        code_values = query.get("code", ())
        error_values = query.get("error", ())
        issuer_values = query.get(_OAUTH_CALLBACK_ISSUER_KEY, ())
        if error_values or len(state_values) != 1 or len(code_values) != 1:
            raise ProviderOperationError(
                ProviderFailureCode.AUTHENTICATION,
                "Google OAuth authorization was not completed",
            )
        if issuer_values and (
            len(issuer_values) != 1
            or not hmac.compare_digest(issuer_values[0], _GOOGLE_OAUTH_ISSUER)
        ):
            raise ProviderOperationError(
                ProviderFailureCode.AUTHENTICATION,
                "Google OAuth callback issuer was rejected",
            )
        state = state_values[0]
        code = code_values[0]
        if not hmac.compare_digest(state, self.state):
            raise ProviderOperationError(
                ProviderFailureCode.AUTHENTICATION,
                "Google OAuth callback state was rejected",
            )
        if not code or len(code) > _OAUTH_TOKEN_TEXT_CHARS:
            raise ProviderOperationError(
                ProviderFailureCode.AUTHENTICATION,
                "Google OAuth callback code was rejected",
            )
        return code


class GoogleOAuthLoopbackReceiver:
    """Receive one exact callback on a short-lived literal IPv4 loopback listener."""

    def __init__(
        self,
        scopes: tuple[str, ...],
        *,
        listener_host: str = OAUTH_LOOPBACK_HOST,
        redirect_port: int = OAUTH_DYNAMIC_CALLBACK_PORT,
    ) -> None:
        _require_scopes(scopes)
        if listener_host not in {OAUTH_LOOPBACK_HOST, OAUTH_CONTAINER_LISTENER_HOST}:
            raise ValueError("OAuth listener host is invalid")
        if redirect_port < OAUTH_DYNAMIC_CALLBACK_PORT or redirect_port > 65_535:
            raise ValueError("OAuth redirect port is outside the valid range")
        self._scopes = scopes
        self._listener_host = listener_host
        self._redirect_port = redirect_port
        self._server: asyncio.AbstractServer | None = None
        self._session: GoogleOAuthAuthorizationSession | None = None
        self._result: asyncio.Future[str] | None = None

    async def start(self) -> GoogleOAuthAuthorizationSession:
        """Bind an ephemeral local port before constructing the exact redirect URI."""
        if self._server is not None:
            raise RuntimeError("OAuth loopback receiver is already running")
        loop = asyncio.get_running_loop()
        self._result = loop.create_future()
        self._server = await asyncio.start_server(
            self._handle_connection,
            host=self._listener_host,
            port=self._redirect_port,
            limit=_OAUTH_CALLBACK_REQUEST_BYTES,
        )
        socket = self._server.sockets[0] if self._server.sockets else None
        if socket is None:
            await self.aclose()
            raise RuntimeError("OAuth loopback receiver did not expose a socket")
        socket_address = socket.getsockname()
        if not isinstance(socket_address, tuple) or not isinstance(socket_address[1], int):
            await self.aclose()
            raise RuntimeError("OAuth loopback receiver returned an invalid socket address")
        self._session = GoogleOAuthAuthorizationSession.create(socket_address[1], self._scopes)
        return self._session

    async def wait_for_code(self, timeout_seconds: float = _OAUTH_CALLBACK_TIMEOUT_SECONDS) -> str:
        """Wait for one validated callback, then close the listener regardless of outcome."""
        if timeout_seconds <= 0:
            raise ValueError("OAuth callback timeout must be positive")
        if self._result is None:
            raise RuntimeError("OAuth loopback receiver has not started")
        try:
            return await asyncio.wait_for(asyncio.shield(self._result), timeout_seconds)
        except TimeoutError as error:
            raise ProviderOperationError(
                ProviderFailureCode.AUTHENTICATION,
                "Google OAuth callback timed out",
            ) from error
        finally:
            await self.aclose()

    async def aclose(self) -> None:
        """Close the exact listener owned by this receiver."""
        if self._server is None:
            return
        self._server.close()
        await self._server.wait_closed()
        self._server = None

    async def _handle_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        success = False
        status = _HTTP_BAD_REQUEST_STATUS
        try:
            if not self._is_callback_peer_allowed(writer):
                raise ProviderOperationError(
                    ProviderFailureCode.AUTHENTICATION,
                    "Google OAuth callback peer was rejected",
                )
            if self._result is None or self._session is None:
                raise RuntimeError("OAuth loopback receiver is not initialized")
            if self._result.done():
                status = _HTTP_CONFLICT_STATUS
                return
            request = await reader.readuntil(b"\r\n\r\n")
            code = self._parse_callback(request)
            self._result.set_result(code)
            success = True
            status = _HTTP_SUCCESS_STATUS
        except (
            asyncio.IncompleteReadError,
            asyncio.LimitOverrunError,
            ProviderOperationError,
            ValueError,
        ):
            log_event(
                _LOGGER,
                logging.DEBUG,
                "Google OAuth callback was rejected",
                reason="callback_validation_failed",
            )
        finally:
            body = _OAUTH_CALLBACK_SUCCESS_BODY if success else _OAUTH_CALLBACK_FAILURE_BODY
            writer.write(_callback_response(status, body))
            try:
                await writer.drain()
            except (ConnectionError, OSError):
                log_event(
                    _LOGGER,
                    logging.DEBUG,
                    "Google OAuth callback response was interrupted",
                    reason="callback_peer_disconnected",
                )
            writer.close()

    def _parse_callback(self, request: bytes) -> str:
        try:
            header = request.decode("ascii")
        except UnicodeDecodeError as error:
            raise ValueError("OAuth callback is not ASCII") from error
        request_line = header.split("\r\n", 1)[0]
        parts = request_line.split(" ")
        if len(parts) != _HTTP_REQUEST_LINE_PARTS or parts[0] != "GET":
            raise ValueError("OAuth callback request method is invalid")
        target = urlsplit(parts[1])
        if target.scheme or target.netloc or target.path != _OAUTH_CALLBACK_PATH:
            raise ValueError("OAuth callback path is invalid")
        query = parse_qs(target.query, keep_blank_values=True, strict_parsing=True)
        callback_values = {key: tuple(values) for key, values in query.items()}
        if self._session is None:
            raise RuntimeError("OAuth loopback receiver is not initialized")
        return self._session.validate_callback(callback_values)

    def _is_callback_peer_allowed(self, writer: asyncio.StreamWriter) -> bool:
        # Docker rewrites the peer address when forwarding a host-loopback port.
        # The port publication and state/PKCE checks remain the access controls.
        if self._listener_host == OAUTH_CONTAINER_LISTENER_HOST:
            return True
        peer = cast(object, writer.get_extra_info("peername"))
        if not isinstance(peer, tuple):
            return False
        typed_peer = cast(tuple[object, ...], peer)
        return bool(typed_peer) and typed_peer[0] == "127.0.0.1"


class _GoogleOAuthInstalledClientResponse(BaseModel):
    """The strict installed-client fields that reach Rankrat's OAuth boundary."""

    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)

    client_id: str = Field(min_length=1, max_length=_OAUTH_TOKEN_TEXT_CHARS)
    client_secret: str | None = Field(default=None, max_length=_OAUTH_TOKEN_TEXT_CHARS)


class _GoogleOAuthClientDocument(BaseModel):
    """The downloaded Google installed-client JSON envelope."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    installed: _GoogleOAuthInstalledClientResponse


class _GoogleOAuthTokenResponse(BaseModel):
    """The narrow token response subset used internally by Rankrat."""

    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)

    access_token: str = Field(min_length=1, max_length=_OAUTH_TOKEN_TEXT_CHARS)
    token_type: str = Field(min_length=1, max_length=32)
    expires_in: int = Field(ge=1, le=86_400)
    refresh_token: str | None = Field(
        default=None,
        min_length=1,
        max_length=_OAUTH_TOKEN_TEXT_CHARS,
    )
    scope: str | None = Field(default=None, min_length=1, max_length=_OAUTH_TOKEN_TEXT_CHARS)

    @field_validator("token_type")
    @classmethod
    def validate_token_type(cls, value: str) -> str:
        if value != _GOOGLE_TOKEN_TYPE:
            raise ValueError("Google OAuth token type is unsupported")
        return value


class _GoogleOAuthTokenRecordResponse(BaseModel):
    """The only JSON shape permitted in an OAuth token file."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    account_id: str = Field(min_length=1, max_length=_OAUTH_TOKEN_TEXT_CHARS)
    client_id: str = Field(min_length=1, max_length=_OAUTH_TOKEN_TEXT_CHARS)
    refresh_token: str = Field(min_length=1, max_length=_OAUTH_TOKEN_TEXT_CHARS)
    scopes: list[str] = Field(min_length=1, max_length=_OAUTH_MAX_SCOPES)

    @field_validator("scopes")
    @classmethod
    def validate_scopes(cls, value: list[str]) -> list[str]:
        if any(not scope or len(scope) > _OAUTH_TOKEN_TEXT_CHARS for scope in value):
            raise ValueError("OAuth token scopes are invalid")
        if len(set(value)) != len(value):
            raise ValueError("OAuth token scopes must not contain duplicates")
        return value


def load_google_oauth_client_configuration(path: Path) -> GoogleOAuthClientConfiguration:
    """Load a bounded Google installed-client document without exposing its contents."""
    try:
        contents = path.read_bytes()
        if len(contents) > _OAUTH_CLIENT_CONFIG_BYTES:
            raise ValueError("OAuth client configuration exceeds the allowed size")
        document = _GoogleOAuthClientDocument.model_validate_json(contents)
        return GoogleOAuthClientConfiguration(
            client_id=document.installed.client_id,
            client_secret=document.installed.client_secret,
        )
    except (OSError, ValueError, ValidationError) as error:
        raise ProviderOperationError(
            ProviderFailureCode.AUTHENTICATION,
            "Google OAuth client configuration is unavailable",
        ) from error


class GoogleOAuthTokenStore:
    """Read and atomically replace exactly one owner-only refresh-token record."""

    def __init__(
        self,
        path: Path,
        account_id: str,
        client_id: str,
        required_scopes: tuple[str, ...],
    ) -> None:
        _require_scopes(required_scopes)
        self._path = path
        self._account_id = account_id
        self._client_id = client_id
        self._required_scopes = frozenset(required_scopes)

    def load(self) -> GoogleOAuthTokenRecord:
        """Load one verified refresh record, rejecting unsafe filesystem metadata."""
        try:
            file_descriptor = os.open(
                self._path,
                os.O_RDONLY | _no_follow_flag(),
            )
        except OSError as error:
            raise ProviderOperationError(
                ProviderFailureCode.AUTHENTICATION,
                "Google OAuth refresh token is unavailable",
            ) from error
        try:
            metadata = os.fstat(file_descriptor)
            _require_owner_only_regular_file(metadata)
            contents = _read_file_descriptor(file_descriptor, MAX_OAUTH_TOKEN_FILE_BYTES)
        except (OSError, ValueError) as error:
            raise ProviderOperationError(
                ProviderFailureCode.AUTHENTICATION,
                "Google OAuth refresh token is unavailable",
            ) from error
        finally:
            os.close(file_descriptor)

        try:
            parsed = _GoogleOAuthTokenRecordResponse.model_validate_json(contents)
            record = GoogleOAuthTokenRecord(
                account_id=parsed.account_id,
                client_id=parsed.client_id,
                refresh_token=parsed.refresh_token,
                scopes=tuple(parsed.scopes),
            )
        except (ValueError, ValidationError) as error:
            raise ProviderOperationError(
                ProviderFailureCode.AUTHENTICATION,
                "Google OAuth refresh token is invalid",
            ) from error
        if record.account_id != self._account_id or record.client_id != self._client_id:
            raise ProviderOperationError(
                ProviderFailureCode.AUTHENTICATION,
                "Google OAuth refresh token does not match its configured account",
            )
        if not _has_required_scopes(self._required_scopes, frozenset(record.scopes)):
            raise ProviderOperationError(
                ProviderFailureCode.FORBIDDEN,
                "Google OAuth refresh token lacks required scopes",
            )
        return record

    def write(self, record: GoogleOAuthTokenRecord) -> None:
        """Atomically persist a refresh-only record with owner-only permissions."""
        if record.account_id != self._account_id or record.client_id != self._client_id:
            raise ProviderOperationError(
                ProviderFailureCode.AUTHENTICATION,
                "Google OAuth refresh token does not match its configured account",
            )
        if not _has_required_scopes(self._required_scopes, frozenset(record.scopes)):
            raise ProviderOperationError(
                ProviderFailureCode.FORBIDDEN,
                "Google OAuth refresh token lacks required scopes",
            )
        self._require_owner_only_parent()
        payload = json.dumps(
            {
                "account_id": record.account_id,
                "client_id": record.client_id,
                "refresh_token": record.refresh_token,
                "scopes": list(record.scopes),
            },
            separators=(",", ":"),
        ).encode("utf-8")
        if len(payload) > MAX_OAUTH_TOKEN_FILE_BYTES:
            raise ProviderOperationError(
                ProviderFailureCode.AUTHENTICATION,
                "Google OAuth refresh token is too large to persist",
            )
        temporary_path: str | None = None
        try:
            file_descriptor, temporary_path = tempfile.mkstemp(
                prefix=f".{self._path.name}.",
                dir=self._path.parent,
            )
            try:
                os.fchmod(file_descriptor, _OAUTH_TOKEN_FILE_MODE)
                _write_all(file_descriptor, payload)
                os.fsync(file_descriptor)
            finally:
                os.close(file_descriptor)
            os.replace(temporary_path, self._path)
            temporary_path = None
            os.chmod(self._path, _OAUTH_TOKEN_FILE_MODE)
        except OSError as error:
            if temporary_path is not None:
                try:
                    os.unlink(temporary_path)
                except OSError as cleanup_error:
                    raise ProviderOperationError(
                        ProviderFailureCode.AUTHENTICATION,
                        "Google OAuth temporary token file could not be removed",
                    ) from cleanup_error
            raise ProviderOperationError(
                ProviderFailureCode.AUTHENTICATION,
                "Google OAuth refresh token could not be persisted",
            ) from error

    def delete(self) -> None:
        """Delete the one verified record and prove that it is gone."""
        try:
            metadata = self._path.lstat()
            _require_owner_only_regular_file(metadata)
            self._path.unlink()
            if self._path.exists():
                raise OSError("OAuth token file still exists")
        except (OSError, ValueError) as error:
            raise ProviderOperationError(
                ProviderFailureCode.AUTHENTICATION,
                "Google OAuth refresh token could not be deleted",
            ) from error

    def _require_owner_only_parent(self) -> None:
        _require_owner_only_directory(self._path.parent)


class GoogleOAuthAuthorizationDiagnosticLog:
    """Append redacted, owner-only operator diagnostics beside OAuth state."""

    def __init__(self, token_file: Path) -> None:
        self._path = token_file.with_name(_OAUTH_AUTH_DIAGNOSTIC_FILE_NAME)

    def record_failure(self, stage: str, failure: ProviderOperationError) -> None:
        """Best-effort record fixed failure metadata without upstream payloads or secrets."""
        payload = (
            json.dumps(
                {
                    "event": _OAUTH_AUTH_DIAGNOSTIC_EVENT,
                    "failure_code": failure.code.value,
                    "occurred_at": datetime.now(UTC).isoformat(),
                    "stage": stage,
                },
                separators=(",", ":"),
            ).encode("utf-8")
            + b"\n"
        )
        try:
            _require_owner_only_directory(self._path.parent)
            file_descriptor = os.open(
                self._path,
                os.O_WRONLY | os.O_APPEND | os.O_CREAT | _no_follow_flag(),
                _OAUTH_TOKEN_FILE_MODE,
            )
            try:
                metadata = os.fstat(file_descriptor)
                _require_owner_only_regular_file(metadata)
                if metadata.st_size > _OAUTH_AUTH_DIAGNOSTIC_MAX_BYTES - len(payload):
                    return
                _write_all(file_descriptor, payload)
                os.fsync(file_descriptor)
            finally:
                os.close(file_descriptor)
        except (OSError, ProviderOperationError, ValueError):
            # Diagnostics must not replace the original OAuth authorization failure.
            log_event(
                _LOGGER,
                logging.DEBUG,
                "Google OAuth diagnostic file could not be updated",
                reason="diagnostic_log_write_failed",
            )


def _require_owner_only_directory(path: Path) -> None:
    """Reject a missing, non-directory, or non-private OAuth state parent."""
    try:
        metadata = path.stat()
    except OSError as error:
        raise ProviderOperationError(
            ProviderFailureCode.AUTHENTICATION,
            "Google OAuth token directory is unavailable",
        ) from error
    if not stat.S_ISDIR(metadata.st_mode):
        raise ProviderOperationError(
            ProviderFailureCode.AUTHENTICATION,
            "Google OAuth token directory is invalid",
        )
    if metadata.st_uid != os.geteuid() or metadata.st_mode & _OAUTH_DIRECTORY_MODE_MASK:
        raise ProviderOperationError(
            ProviderFailureCode.AUTHENTICATION,
            "Google OAuth token directory permissions are unsafe",
        )


class GoogleOAuthTokenClient:
    """Exchange, refresh, and revoke only against Google's documented fixed endpoints."""

    def __init__(self, transport_factory: HttpTransportFactory = lambda: None) -> None:
        self._transport_factory = transport_factory

    async def exchange(
        self,
        account_id: str,
        configuration: GoogleOAuthClientConfiguration,
        session: GoogleOAuthAuthorizationSession,
        code: str,
    ) -> tuple[str, GoogleOAuthTokenRecord]:
        """Exchange one validated authorization code for short-lived and refresh material."""
        values = {
            "client_id": configuration.client_id,
            "code": code,
            "code_verifier": session.code_verifier,
            "grant_type": "authorization_code",
            "redirect_uri": session.redirect_uri,
        }
        if configuration.client_secret is not None:
            values["client_secret"] = configuration.client_secret
        response = await self._token_response(values)
        if response.refresh_token is None:
            raise ProviderOperationError(
                ProviderFailureCode.AUTHENTICATION,
                "Google OAuth authorization did not return a refresh token",
            )
        scopes = _response_scopes(response.scope, session.scopes)
        return response.access_token, GoogleOAuthTokenRecord(
            account_id=account_id,
            client_id=configuration.client_id,
            refresh_token=response.refresh_token,
            scopes=scopes,
        )

    async def refresh(
        self,
        configuration: GoogleOAuthClientConfiguration,
        record: GoogleOAuthTokenRecord,
    ) -> tuple[str, GoogleOAuthTokenRecord]:
        """Refresh one stored grant and preserve it unless Google rotates it."""
        values = {
            "client_id": configuration.client_id,
            "grant_type": "refresh_token",
            "refresh_token": record.refresh_token,
        }
        if configuration.client_secret is not None:
            values["client_secret"] = configuration.client_secret
        response = await self._token_response(values)
        scopes = _response_scopes(response.scope, record.scopes)
        return response.access_token, GoogleOAuthTokenRecord(
            account_id=record.account_id,
            client_id=record.client_id,
            refresh_token=response.refresh_token or record.refresh_token,
            scopes=scopes,
        )

    async def revoke(self, record: GoogleOAuthTokenRecord) -> None:
        """Revoke a refresh token through Google's fixed revocation endpoint."""
        try:
            async with (
                httpx.AsyncClient(
                    transport=self._transport_factory(),
                    trust_env=False,
                    follow_redirects=False,
                    timeout=httpx.Timeout(DEFAULT_PROVIDER_TIMEOUT_SECONDS),
                ) as client,
                client.stream(
                    "POST",
                    _GOOGLE_REVOCATION_URL,
                    data={"token": record.refresh_token},
                ) as response,
            ):
                if response.status_code != HTTPStatus.OK:
                    raise ProviderOperationError(
                        ProviderFailureCode.AUTHENTICATION,
                        "Google OAuth revocation was rejected",
                    )
        except ProviderOperationError:
            raise
        except httpx.TimeoutException as error:
            raise ProviderOperationError(
                ProviderFailureCode.TIMEOUT,
                "Google OAuth revocation timed out",
            ) from error
        except httpx.HTTPError as error:
            raise ProviderOperationError(
                ProviderFailureCode.UNAVAILABLE,
                "Google OAuth revocation is unavailable",
            ) from error

    async def _token_response(self, values: dict[str, str]) -> _GoogleOAuthTokenResponse:
        try:
            async with (
                httpx.AsyncClient(
                    transport=self._transport_factory(),
                    trust_env=False,
                    follow_redirects=False,
                    timeout=httpx.Timeout(DEFAULT_PROVIDER_TIMEOUT_SECONDS),
                ) as client,
                client.stream("POST", _GOOGLE_TOKEN_URL, data=values) as response,
            ):
                _raise_for_token_status(response)
                body = await _read_response_body(response)
        except ProviderOperationError:
            raise
        except httpx.TimeoutException as error:
            raise ProviderOperationError(
                ProviderFailureCode.TIMEOUT,
                "Google OAuth token request timed out",
            ) from error
        except httpx.HTTPError as error:
            raise ProviderOperationError(
                ProviderFailureCode.UNAVAILABLE,
                "Google OAuth token request is unavailable",
            ) from error
        try:
            return _GoogleOAuthTokenResponse.model_validate_json(body)
        except ValidationError as error:
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "Google OAuth token response is invalid",
            ) from error


def required_google_oauth_scopes(
    account: ConfiguredAccount,
    enable_writes: bool,
) -> tuple[str, ...]:
    """Return the Google scopes required by the selected runtime posture."""
    if account.provider != Provider.GOOGLE:
        raise ValueError("configured account is not a Google OAuth account")
    scopes = [
        GOOGLE_SEARCH_CONSOLE_READ_SCOPE,
        GOOGLE_ANALYTICS_READ_SCOPE,
    ]
    if enable_writes:
        scopes.append(GOOGLE_INDEXING_SCOPE)
        scopes.append(GOOGLE_SEARCH_CONSOLE_WRITE_SCOPE)
        scopes.append(GOOGLE_SITE_VERIFICATION_SCOPE)
        scopes.append(GOOGLE_ANALYTICS_EDIT_SCOPE)
        scopes.append(GOOGLE_TAG_MANAGER_EDIT_SCOPE)
        scopes.append(GOOGLE_TAG_MANAGER_DELETE_SCOPE)
        scopes.append(GOOGLE_TAG_MANAGER_VERSION_EDIT_SCOPE)
        scopes.append(GOOGLE_TAG_MANAGER_PUBLISH_SCOPE)
    normalized_scopes = tuple(scopes)
    _require_scopes(normalized_scopes)
    return normalized_scopes


def google_oauth_authorization_scopes() -> tuple[str, ...]:
    """Return the complete fixed scope set issued by the local authorization flow."""
    return _GOOGLE_AUTHORIZATION_SCOPES


async def authorize_google_oauth_account(
    account: ConfiguredAccount,
    enable_writes: bool,
    browser_opener: BrowserOpener | None,
    authorization_url_sink: AuthorizationURLSink | None = None,
    token_client: GoogleOAuthTokenClient | None = None,
    listener_host: str = OAUTH_LOOPBACK_HOST,
    callback_port: int = OAUTH_DYNAMIC_CALLBACK_PORT,
) -> None:
    """Authorize one configured account through an external browser and local callback."""
    token_file = account.oauth_token_file
    if token_file is None:
        raise ProviderOperationError(
            ProviderFailureCode.AUTHENTICATION,
            "Google OAuth account is missing a refresh token path",
        )
    diagnostic_log = GoogleOAuthAuthorizationDiagnosticLog(token_file)
    stage = _OAUTH_AUTH_DIAGNOSTIC_STAGE_CONFIGURATION
    try:
        configuration = load_google_oauth_client_configuration(account.credential)
        del enable_writes
        scopes = google_oauth_authorization_scopes()
        receiver = GoogleOAuthLoopbackReceiver(
            scopes,
            listener_host=listener_host,
            redirect_port=callback_port,
        )
        stage = _OAUTH_AUTH_DIAGNOSTIC_STAGE_CALLBACK
        session = await receiver.start()
        authorization_url = session.authorization_url(configuration.client_id)
        if authorization_url_sink is not None:
            authorization_url_sink(authorization_url)
        if browser_opener is not None and not browser_opener(authorization_url):
            await receiver.aclose()
            raise ProviderOperationError(
                ProviderFailureCode.AUTHENTICATION,
                "Google OAuth browser could not be opened",
            )
        code = await receiver.wait_for_code()
        client = token_client or GoogleOAuthTokenClient()
        stage = _OAUTH_AUTH_DIAGNOSTIC_STAGE_TOKEN_EXCHANGE
        access_token, record = await client.exchange(account.id, configuration, session, code)
        del access_token
        stage = _OAUTH_AUTH_DIAGNOSTIC_STAGE_TOKEN_PERSISTENCE
        GoogleOAuthTokenStore(token_file, account.id, configuration.client_id, scopes).write(record)
    except ProviderOperationError as error:
        diagnostic_log.record_failure(stage, error)
        raise


async def revoke_google_oauth_account(
    account: ConfiguredAccount,
    enable_writes: bool,
    token_client: GoogleOAuthTokenClient | None = None,
) -> None:
    """Revoke and delete the exact configured account's stored refresh material."""
    token_file = account.oauth_token_file
    if token_file is None:
        raise ProviderOperationError(
            ProviderFailureCode.AUTHENTICATION,
            "Google OAuth account is missing a refresh token path",
        )
    configuration = load_google_oauth_client_configuration(account.credential)
    token_store = GoogleOAuthTokenStore(
        token_file,
        account.id,
        configuration.client_id,
        required_google_oauth_scopes(account, enable_writes),
    )
    record = token_store.load()
    client = token_client or GoogleOAuthTokenClient()
    await client.revoke(record)
    token_store.delete()


def _require_scopes(scopes: tuple[str, ...]) -> None:
    if not scopes or len(scopes) > _OAUTH_MAX_SCOPES:
        raise ValueError("OAuth requires a bounded non-empty scope set")
    if any(not scope or len(scope) > _OAUTH_TOKEN_TEXT_CHARS for scope in scopes):
        raise ValueError("OAuth scope is invalid")
    if len(set(scopes)) != len(scopes):
        raise ValueError("OAuth scope set contains duplicates")


def _has_required_scopes(required_scopes: frozenset[str], granted_scopes: frozenset[str]) -> bool:
    """Accept only documented scope aliases that retain the required capability."""
    missing_scopes = required_scopes - granted_scopes
    if not missing_scopes:
        return True
    if missing_scopes == frozenset({GOOGLE_SEARCH_CONSOLE_READ_SCOPE}):
        return GOOGLE_SEARCH_CONSOLE_WRITE_SCOPE in granted_scopes
    return False


def _callback_response(status: str, body: bytes) -> bytes:
    return (
        "\r\n".join(
            (
                status,
                _HTTP_CONTENT_TYPE,
                _HTTP_CONNECTION_CLOSE,
                f"Content-Length: {len(body)}",
                "",
                "",
            )
        ).encode("ascii")
        + body
    )


def _response_scopes(scope_value: str | None, expected: tuple[str, ...]) -> tuple[str, ...]:
    scopes = tuple(scope_value.split(" ")) if scope_value is not None else expected
    _require_scopes(scopes)
    if not _has_required_scopes(frozenset(expected), frozenset(scopes)):
        raise ProviderOperationError(
            ProviderFailureCode.FORBIDDEN,
            "Google OAuth token response lacks required scopes",
        )
    return scopes


def _no_follow_flag() -> int:
    flag = getattr(os, "O_NOFOLLOW", None)
    if not isinstance(flag, int):
        raise ValueError("OAuth token storage requires no-follow filesystem support")
    return flag


def _require_owner_only_regular_file(metadata: os.stat_result) -> None:
    if not stat.S_ISREG(metadata.st_mode):
        raise ValueError("OAuth token path is not a regular file")
    if metadata.st_uid != os.geteuid() or metadata.st_mode & _OAUTH_DIRECTORY_MODE_MASK:
        raise ValueError("OAuth token file permissions are unsafe")


def _read_file_descriptor(file_descriptor: int, limit: int) -> bytes:
    chunks: list[bytes] = []
    size = 0
    while True:
        chunk = os.read(file_descriptor, limit + 1 - size)
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)
        size += len(chunk)
        if size > limit:
            raise ValueError("OAuth token file exceeds the allowed size")


def _write_all(file_descriptor: int, payload: bytes) -> None:
    offset = 0
    while offset < len(payload):
        written = os.write(file_descriptor, payload[offset:])
        if written <= 0:
            raise OSError("OAuth token file write did not progress")
        offset += written


async def _read_response_body(response: httpx.Response) -> bytes:
    chunks: list[bytes] = []
    size = 0
    async for chunk in response.aiter_bytes():
        size += len(chunk)
        if size > _OAUTH_TOKEN_RESPONSE_BYTES or size > MAX_PROVIDER_RESPONSE_BYTES:
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "Google OAuth token response exceeds the allowed size",
            )
        chunks.append(chunk)
    return b"".join(chunks)


def _raise_for_token_status(response: httpx.Response) -> None:
    if response.status_code == HTTPStatus.OK:
        return
    if response.status_code in {HTTPStatus.BAD_REQUEST, HTTPStatus.UNAUTHORIZED}:
        code = ProviderFailureCode.AUTHENTICATION
    elif response.status_code == HTTPStatus.FORBIDDEN:
        code = ProviderFailureCode.FORBIDDEN
    elif response.status_code == HTTPStatus.TOO_MANY_REQUESTS:
        code = ProviderFailureCode.RATE_LIMITED
    elif response.status_code >= HTTPStatus.INTERNAL_SERVER_ERROR:
        code = ProviderFailureCode.UNAVAILABLE
    else:
        code = ProviderFailureCode.INVALID_RESPONSE
    raise ProviderOperationError(code, "Google OAuth token request was rejected")
