"""FastAPI REST and Streamable HTTP MCP with raw-ASGI safety middleware."""

from __future__ import annotations

import asyncio
import contextlib
import contextvars
import json
import logging
import re
import uuid
from collections.abc import AsyncIterator
from typing import cast

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.routing import Mount
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from rankrat import __version__
from rankrat.config import Settings
from rankrat.constants import (
    HEALTH_PATH,
    MAX_HTTP_BODY_BYTES,
    MCP_PATH,
    PROVIDER_OPERATION_FAILED_MESSAGE,
)
from rankrat.errors import (
    IndexNowRateLimitError,
    InputLimitError,
    RankratError,
    StateConflictError,
    StateNotFoundError,
    StateUnavailableError,
)
from rankrat.logging import reset_log_scope, with_log_scope
from rankrat.models.common import to_json_value
from rankrat.providers.base import ProviderFailureCode, ProviderOperationError
from rankrat.providers.connectivity import provider_error_detail
from rankrat.services.diagnostics import DiagnosticsRequest
from rankrat.transports.auth import bearer_is_valid, load_bearer_secret
from rankrat.transports.mcp import build_mcp_server
from rankrat.transports.openapi import (
    apply_openapi_operation_ids,
    load_openapi_document_for_routes,
    openapi_info_version,
)
from rankrat.transports.rest import build_api_router
from rankrat.transports.runtime import ApplicationServices

_JSON_CONTENT_TYPE = b"application/json"
_REQUEST_ID_HEADER = b"x-request-id"
_AUTHORIZATION_HEADER = b"authorization"
_CONTENT_LENGTH_HEADER = b"content-length"
_UUID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
_ULID_PATTERN = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")
_SECURITY_HEADERS: tuple[tuple[bytes, bytes], ...] = (
    (
        b"content-security-policy",
        b"default-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'",
    ),
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"strict-origin-when-cross-origin"),
    (b"permissions-policy", b"geolocation=(), microphone=(), camera=()"),
)
logger = logging.getLogger(__name__)


async def _send_json_error(send: Send, status: int, code: str, message: str) -> None:
    body = json.dumps({"code": code, "message": message}, separators=(",", ":")).encode()
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": (
                (b"content-type", _JSON_CONTENT_TYPE),
                (b"content-length", str(len(body)).encode()),
            ),
        }
    )
    await send({"type": "http.response.body", "body": body})


def _header(scope: Scope, target: bytes) -> str | None:
    values = [value for name, value in scope.get("headers", []) if name.lower() == target]
    if len(values) != 1:
        return None
    return cast(bytes, values[0]).decode("latin-1")


def _request_id_is_valid(value: str) -> bool:
    return bool(_UUID_PATTERN.fullmatch(value) or _ULID_PATTERN.fullmatch(value))


class _BodyLimitASGI:
    """Reject oversized bodies before FastAPI or the MCP manager consumes them."""

    def __init__(self, app: ASGIApp, maximum_bytes: int) -> None:
        self._app = app
        self._maximum_bytes = maximum_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        content_length_values = [
            value
            for name, value in scope.get("headers", [])
            if name.lower() == _CONTENT_LENGTH_HEADER
        ]
        if len(content_length_values) > 1:
            await _send_json_error(send, 400, "VALIDATION_FAILED", "invalid content length")
            return
        content_length = _header(scope, _CONTENT_LENGTH_HEADER)
        if content_length is not None:
            try:
                parsed_content_length = int(content_length)
                if parsed_content_length < 0:
                    await _send_json_error(send, 400, "VALIDATION_FAILED", "invalid content length")
                    return
                if parsed_content_length > self._maximum_bytes:
                    await _send_json_error(
                        send,
                        413,
                        "INPUT_TOO_LARGE",
                        "request body is too large",
                    )
                    return
            except ValueError:
                await _send_json_error(send, 400, "VALIDATION_FAILED", "invalid content length")
                return

        received_bytes = 0

        async def limited_receive() -> Message:
            nonlocal received_bytes
            message = await receive()
            if message["type"] != "http.request":
                return message
            received_bytes += len(message.get("body", b""))
            if received_bytes > self._maximum_bytes:
                raise InputLimitError("HTTP request body exceeds the maximum allowed size")
            return message

        response_started = False

        async def tracked_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self._app(scope, limited_receive, tracked_send)
        except InputLimitError:
            if response_started:
                raise
            await _send_json_error(send, 413, "INPUT_TOO_LARGE", "request body is too large")


class _BearerAuthASGI:
    """Pure ASGI auth wrapper that does not buffer MCP streaming responses."""

    def __init__(
        self,
        app: ASGIApp,
        secret: str | None,
    ) -> None:
        self._app = app
        self._secret = secret

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("path") == HEALTH_PATH:
            await self._app(scope, receive, send)
            return
        if not bearer_is_valid(_header(scope, _AUTHORIZATION_HEADER), self._secret):
            await _send_json_error(send, 401, "UNAUTHORIZED", "missing or invalid bearer token")
            return
        await self._app(scope, receive, send)


class _SecurityHeadersASGI:
    """Append the API's fixed browser-safety header baseline to every response."""

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        async def secure_send(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.extend(_SECURITY_HEADERS)
                message["headers"] = headers
            await send(message)

        await self._app(scope, receive, secure_send)


class _RequestIDASGI:
    """Echo a bounded request ID without using buffering middleware."""

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        incoming = _header(scope, _REQUEST_ID_HEADER)
        request_id = incoming if incoming and _request_id_is_valid(incoming) else str(uuid.uuid4())
        scope_token = with_log_scope(request_id=request_id)

        async def request_id_send(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((_REQUEST_ID_HEADER, request_id.encode()))
                message["headers"] = headers
            await send(message)

        try:
            await self._app(scope, receive, request_id_send)
        finally:
            reset_log_scope(scope_token)


def create_http_app(settings: Settings, services: ApplicationServices) -> ASGIApp:
    """Create the HTTP application with REST and `/mcp` mounted together."""
    server = build_mcp_server(services)
    manager = StreamableHTTPSessionManager(server, json_response=True, stateless=True)

    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        scheduler_task: asyncio.Task[None] | None = None
        if services.monitoring.available:
            context = contextvars.copy_context()
            scheduler_task = context.run(
                asyncio.create_task,
                _run_monitor_scheduler(
                    services,
                    settings.scheduler_interval_seconds,
                ),
                name="rankrat-monitor-scheduler",
            )
        try:
            async with manager.run():
                yield
        finally:
            if scheduler_task is not None:
                scheduler_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await scheduler_task

    app = FastAPI(
        title="rankrat",
        version=openapi_info_version(),
        docs_url=None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.enable_openapi else None,
        lifespan=lifespan,
    )
    app.router.routes.append(Mount(MCP_PATH, app=manager.handle_request))
    api_router = build_api_router(services)
    apply_openapi_operation_ids(api_router.routes)
    app.include_router(api_router)
    if settings.enable_openapi:
        # The YAML document is the published contract. Use FastAPI's documented
        # override: its cached schema is regenerated after route changes.
        app.openapi = lambda: load_openapi_document_for_routes(app.routes)  # type: ignore[method-assign]

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, __: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={"code": "VALIDATION_FAILED", "message": "request validation failed"},
        )

    @app.exception_handler(RankratError)
    async def rankrat_error(_: Request, error: RankratError) -> JSONResponse:
        status_code = _rankrat_error_status(error)
        return JSONResponse(
            status_code=status_code,
            content={"code": "REQUEST_REJECTED", "message": str(error)},
        )

    @app.exception_handler(ProviderOperationError)
    async def provider_error(_: Request, error: ProviderOperationError) -> JSONResponse:
        status_code = 429 if error.code is ProviderFailureCode.RATE_LIMITED else 502
        content: dict[str, object] = {
            "code": error.code.value,
            "message": PROVIDER_OPERATION_FAILED_MESSAGE,
        }
        detail = provider_error_detail(error)
        if detail is not None:
            content["detail"] = detail
        return JSONResponse(status_code=status_code, content=content)

    @app.get(HEALTH_PATH)
    def health() -> dict[str, object]:
        return {"ok": True, "version": __version__}

    @app.get("/ready", response_model=None)
    def ready() -> object:
        return to_json_value(services.diagnostics.diagnostics(DiagnosticsRequest()))

    apply_openapi_operation_ids(app.routes)

    wrapped: ASGIApp = _BearerAuthASGI(
        app,
        load_bearer_secret(settings.http_bearer_secret_file),
    )
    wrapped = _BodyLimitASGI(wrapped, MAX_HTTP_BODY_BYTES)
    wrapped = _RequestIDASGI(wrapped)
    return _SecurityHeadersASGI(wrapped)


async def _run_monitor_scheduler(
    services: ApplicationServices,
    interval_seconds: int,
) -> None:
    logger.info("monitor scheduler started", extra={"interval_seconds": interval_seconds})
    while True:
        try:
            result = await services.monitoring.run_next_due()
            if result is None:
                await asyncio.sleep(interval_seconds)
                continue
            logger.info(
                "monitor run completed",
                extra={
                    "monitor_id": result.monitor.id,
                    "site_url": result.monitor.site_url,
                    "score": result.snapshot.score,
                    "issue_count": result.snapshot.issue_count,
                },
            )
        except ProviderOperationError as error:
            logger.warning(
                "scheduled monitor provider operation failed",
                extra={"provider_failure_code": error.code.value},
            )
            await asyncio.sleep(interval_seconds)
        except RankratError as error:
            logger.warning(
                "scheduled monitor run was rejected",
                extra={"error_type": type(error).__name__},
            )
            await asyncio.sleep(interval_seconds)
        # Keep the supervisor alive after malformed state or unexpected errors.
        except Exception as error:
            logger.error(
                "scheduled monitor run failed unexpectedly",
                extra={"error_type": type(error).__name__},
            )
            await asyncio.sleep(interval_seconds)


def _rankrat_error_status(error: RankratError) -> int:
    if isinstance(error, IndexNowRateLimitError):
        return 429
    if isinstance(error, StateUnavailableError):
        return 503
    if isinstance(error, StateNotFoundError):
        return 404
    if isinstance(error, StateConflictError):
        return 409
    return 400
