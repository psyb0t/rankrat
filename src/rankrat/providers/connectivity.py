"""Best-effort DNS diagnostics that turn opaque connect failures into safe hints.

A DNS-level content blocker such as AdGuard or Pi-hole answers a filtered domain
with a sinkhole address (``0.0.0.0`` / ``::`` / ``127.0.0.1`` / ``::1``), so a
fixed-origin provider connection is refused before it leaves the host. The
transport wrapper here notices that shape and attaches a curated hint, which the
MCP and REST adapters may surface next to the generic failure message. Everything
reported derives only from the fixed public host and the address it resolved to,
never from a credential or an upstream payload.
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
from collections.abc import Awaitable, Callable

import httpx

from rankrat.logging import log_event

_RESOLVE_PORT = 443

_LOGGER = logging.getLogger(__name__)

ResolvedAddress = ipaddress.IPv4Address | ipaddress.IPv6Address
Resolver = Callable[[str], Awaitable[tuple[ResolvedAddress, ...]]]


async def _default_resolver(hostname: str) -> tuple[ResolvedAddress, ...]:
    """Resolve a hostname to addresses without imposing any routability policy."""

    records = await asyncio.get_running_loop().getaddrinfo(hostname, _RESOLVE_PORT, type=0)
    addresses: set[ResolvedAddress] = set()
    for record in records:
        try:
            addresses.add(ipaddress.ip_address(record[4][0]))
        except ValueError:
            continue
    return tuple(sorted(addresses, key=str))


async def diagnose_unreachable_host(
    host: str,
    resolver: Resolver = _default_resolver,
) -> str | None:
    """Return a safe hint when a host looks DNS-blocked, otherwise ``None``.

    A sinkhole answer or a failed resolution is the signature of a DNS-level
    content blocker; anything else returns ``None``.
    """

    try:
        addresses = await resolver(host)
    except OSError:
        return (
            f"the host {host} could not be resolved; a DNS-level blocker "
            "or an offline resolver may be preventing the connection"
        )
    for address in addresses:
        if not (address.is_unspecified or address.is_loopback):
            continue
        return (
            f"{host} resolved to {address}; a DNS-level blocker such as AdGuard "
            "or Pi-hole may be filtering this domain — allowlist it or disable "
            "the blocker"
        )
    return None


class DiagnosticConnectError(httpx.ConnectError):
    """A connect failure carrying a curated, surface-safe diagnostic detail."""

    def __init__(self, message: str, *, request: httpx.Request, safe_detail: str) -> None:
        super().__init__(message, request=request)
        self.safe_detail = safe_detail


class _DiagnosticTransport(httpx.AsyncBaseTransport):
    """Wrap a transport and annotate sinkhole-style connect failures with a hint."""

    def __init__(
        self,
        inner: httpx.AsyncBaseTransport,
        resolver: Resolver = _default_resolver,
    ) -> None:
        self._inner = inner
        self._resolver = resolver

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        try:
            return await self._inner.handle_async_request(request)
        except httpx.ConnectError as error:
            detail = await self._safe_diagnose(request.url.host)
            if detail is None:
                raise
            raise DiagnosticConnectError(
                str(error) or "connection failed",
                request=request,
                safe_detail=detail,
            ) from error

    async def _safe_diagnose(self, host: str) -> str | None:
        try:
            return await diagnose_unreachable_host(host, self._resolver)
        except Exception:
            # A diagnosis fault must never mask or replace the real connect error.
            log_event(_LOGGER, logging.DEBUG, "host connection diagnosis failed", host=host)
            return None

    async def aclose(self) -> None:
        await self._inner.aclose()


def create_diagnostic_transport() -> httpx.AsyncBaseTransport:
    """Build the default provider transport that explains DNS-sinkhole failures."""

    return _DiagnosticTransport(httpx.AsyncHTTPTransport())


def provider_error_detail(error: BaseException) -> str | None:
    """Extract a curated, surface-safe detail from a provider error's cause chain.

    Only an explicit ``detail`` attribute set on the error, or the ``safe_detail``
    of a :class:`DiagnosticConnectError` in its ``__cause__`` chain, is returned.
    Raw exception text is never surfaced.
    """

    explicit = getattr(error, "detail", None)
    if isinstance(explicit, str) and explicit:
        return explicit
    cause = error.__cause__
    seen: set[int] = set()
    while cause is not None and id(cause) not in seen:
        seen.add(id(cause))
        if isinstance(cause, DiagnosticConnectError):
            return cause.safe_detail
        cause = cause.__cause__
    return None
