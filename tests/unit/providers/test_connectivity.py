from __future__ import annotations

import ipaddress

import httpx
import mcp.types as types
import pytest

from rankrat.providers.base import ProviderFailureCode, ProviderOperationError
from rankrat.providers.connectivity import (
    DiagnosticConnectError,
    _DiagnosticTransport,
    diagnose_unreachable_host,
    provider_error_detail,
)
from rankrat.transports.mcp import _tool_error

_HOST = "analyticsadmin.googleapis.com"
_URL = f"https://{_HOST}/v1beta/accountSummaries"


def _resolver_for(*addresses: str):
    async def resolver(_: str) -> tuple[ipaddress.IPv4Address | ipaddress.IPv6Address, ...]:
        return tuple(ipaddress.ip_address(address) for address in addresses)

    return resolver


async def _failing_resolver(_: str) -> tuple[ipaddress.IPv4Address, ...]:
    raise OSError("name resolution refused")


async def _crashing_resolver(_: str) -> tuple[ipaddress.IPv4Address, ...]:
    raise ValueError("diagnosis fault")


class _RaisingTransport(httpx.AsyncBaseTransport):
    def __init__(self, error: Exception) -> None:
        self._error = error

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        raise self._error


class _RespondingTransport(httpx.AsyncBaseTransport):
    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code=204, request=request)


@pytest.mark.asyncio
@pytest.mark.parametrize("sinkhole", ["0.0.0.0", "127.0.0.1", "::", "::1"])
async def test_diagnose_flags_sinkhole_addresses(sinkhole: str) -> None:
    hint = await diagnose_unreachable_host(_HOST, _resolver_for(sinkhole))
    assert hint is not None
    assert _HOST in hint
    assert sinkhole in hint
    assert "AdGuard" in hint


@pytest.mark.asyncio
async def test_diagnose_ignores_public_addresses() -> None:
    hint = await diagnose_unreachable_host(_HOST, _resolver_for("1.1.1.1", "8.8.8.8"))
    assert hint is None


@pytest.mark.asyncio
async def test_diagnose_reports_unresolvable_host() -> None:
    hint = await diagnose_unreachable_host(_HOST, _failing_resolver)
    assert hint is not None
    assert _HOST in hint
    assert "could not be resolved" in hint


@pytest.mark.asyncio
async def test_transport_annotates_sinkhole_connect_error() -> None:
    request = httpx.Request("GET", _URL)
    inner = _RaisingTransport(httpx.ConnectError("connection refused", request=request))
    transport = _DiagnosticTransport(inner, resolver=_resolver_for("0.0.0.0"))
    with pytest.raises(DiagnosticConnectError) as raised:
        await transport.handle_async_request(request)
    assert "AdGuard" in raised.value.safe_detail


@pytest.mark.asyncio
async def test_transport_passes_through_public_connect_error() -> None:
    request = httpx.Request("GET", _URL)
    inner = _RaisingTransport(httpx.ConnectError("connection refused", request=request))
    transport = _DiagnosticTransport(inner, resolver=_resolver_for("1.1.1.1"))
    with pytest.raises(httpx.ConnectError) as raised:
        await transport.handle_async_request(request)
    assert not isinstance(raised.value, DiagnosticConnectError)


@pytest.mark.asyncio
async def test_transport_passes_through_non_connect_error() -> None:
    request = httpx.Request("GET", _URL)
    inner = _RaisingTransport(httpx.ReadError("read failed", request=request))
    transport = _DiagnosticTransport(inner, resolver=_resolver_for("0.0.0.0"))
    with pytest.raises(httpx.ReadError):
        await transport.handle_async_request(request)


@pytest.mark.asyncio
async def test_transport_diagnosis_fault_reraises_original() -> None:
    request = httpx.Request("GET", _URL)
    inner = _RaisingTransport(httpx.ConnectError("connection refused", request=request))
    transport = _DiagnosticTransport(inner, resolver=_crashing_resolver)
    with pytest.raises(httpx.ConnectError) as raised:
        await transport.handle_async_request(request)
    assert not isinstance(raised.value, DiagnosticConnectError)


@pytest.mark.asyncio
async def test_transport_returns_successful_response() -> None:
    request = httpx.Request("GET", _URL)
    transport = _DiagnosticTransport(_RespondingTransport(), resolver=_resolver_for("0.0.0.0"))
    response = await transport.handle_async_request(request)
    assert response.status_code == 204


def test_provider_error_detail_prefers_explicit_detail() -> None:
    error = ProviderOperationError(ProviderFailureCode.UNAVAILABLE, "unavailable", "EXPLICIT")
    assert provider_error_detail(error) == "EXPLICIT"


def test_provider_error_detail_reads_diagnostic_cause() -> None:
    request = httpx.Request("GET", _URL)
    cause = DiagnosticConnectError("refused", request=request, safe_detail="HINT")
    try:
        raise ProviderOperationError(ProviderFailureCode.UNAVAILABLE, "unavailable") from cause
    except ProviderOperationError as error:
        assert provider_error_detail(error) == "HINT"


def test_provider_error_detail_is_none_for_plain_error() -> None:
    error = ProviderOperationError(ProviderFailureCode.UNAVAILABLE, "unavailable")
    assert provider_error_detail(error) is None


def test_tool_error_surfaces_detail_only_when_present() -> None:
    with_detail = _tool_error("UNAVAILABLE", "provider operation failed", "HINT")
    with_detail_content = with_detail.content[0]
    assert isinstance(with_detail_content, types.TextContent)
    assert '"detail":"HINT"' in with_detail_content.text

    without_detail = _tool_error("UNAVAILABLE", "provider operation failed")
    without_detail_content = without_detail.content[0]
    assert isinstance(without_detail_content, types.TextContent)
    assert "detail" not in without_detail_content.text
