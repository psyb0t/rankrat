"""Fixed-origin DNS-over-HTTPS checks for verification-record propagation."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from rankrat.constants import MAX_PROVIDER_RESPONSE_BYTES
from rankrat.models.boundaries import Provider, normalize_indexnow_host
from rankrat.providers.base import ProviderFailureCode, ProviderOperationError, ProviderReadRequest

_DNS_OVER_HTTPS_URL = "https://cloudflare-dns.com/dns-query"
_DNS_JSON_MEDIA_TYPE = "application/dns-json"
_DNS_SUCCESS_STATUS = 0
_MAX_DNS_ANSWERS = 100
_MAX_DNS_DATA_CHARS = 4_096

HttpTransportFactory = Callable[[], httpx.AsyncBaseTransport | None]


class DnsRecordType(StrEnum):
    """DNS record kinds permitted for provider-issued ownership proofs."""

    TXT = "TXT"
    CNAME = "CNAME"


@dataclass(frozen=True, slots=True)
class DnsRecordReceipt:
    """Secret-free receipt for an idempotently ensured DNS record."""

    provider_zone_id: str
    record_id: str
    record_type: DnsRecordType
    name: str
    created: bool


class DnsOwnershipClient(Protocol):
    """Provider adapter capable only of ensuring exact ownership records."""

    provider: Provider

    async def ensure_verification_record(
        self,
        request: ProviderReadRequest,
        hostname: str,
        record_type: DnsRecordType,
        name: str,
        content: str,
    ) -> DnsRecordReceipt: ...


@dataclass(frozen=True, slots=True)
class DnsPropagationResult:
    """Whether one exact expected DNS value is publicly observable."""

    propagated: bool
    answer_count: int


class _DnsAnswer(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    data: str = Field(alias="data", min_length=1, max_length=_MAX_DNS_DATA_CHARS)


class _DnsResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    status: int = Field(alias="Status")
    answers: tuple[_DnsAnswer, ...] = Field(default=(), alias="Answer")


class PublicDnsClient:
    """Query only Cloudflare's fixed DNS-over-HTTPS origin."""

    def __init__(
        self,
        transport_factory: HttpTransportFactory = lambda: None,
    ) -> None:
        self._transport_factory = transport_factory

    async def has_record(
        self,
        name: str,
        record_type: DnsRecordType,
        expected_content: str,
        timeout_seconds: float,
    ) -> DnsPropagationResult:
        normalized_name = normalize_indexnow_host(name)
        try:
            async with httpx.AsyncClient(
                transport=self._transport_factory(),
                trust_env=False,
                follow_redirects=False,
                timeout=httpx.Timeout(timeout_seconds),
            ) as client:
                response = await client.get(
                    _DNS_OVER_HTTPS_URL,
                    params={"name": normalized_name, "type": record_type.value},
                    headers={"Accept": _DNS_JSON_MEDIA_TYPE},
                )
                if response.is_redirect or response.status_code != 200:
                    raise ProviderOperationError(
                        ProviderFailureCode.UNAVAILABLE,
                        "public DNS lookup is unavailable",
                    )
                body = await response.aread()
        except httpx.TimeoutException as error:
            raise ProviderOperationError(
                ProviderFailureCode.TIMEOUT,
                "public DNS lookup timed out",
            ) from error
        except httpx.HTTPError as error:
            raise ProviderOperationError(
                ProviderFailureCode.UNAVAILABLE,
                "public DNS lookup is unavailable",
            ) from error
        if len(body) > MAX_PROVIDER_RESPONSE_BYTES:
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "public DNS response exceeds the allowed size",
            )
        try:
            payload = json.loads(body)
            parsed = _DnsResponse.model_validate(payload)
        except (json.JSONDecodeError, ValidationError) as error:
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "public DNS returned an invalid response",
            ) from error
        if parsed.status != _DNS_SUCCESS_STATUS:
            return DnsPropagationResult(False, 0)
        if len(parsed.answers) > _MAX_DNS_ANSWERS:
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "public DNS returned too many answers",
            )
        expected = self._normalize_answer(record_type, expected_content)
        observed = {self._normalize_answer(record_type, answer.data) for answer in parsed.answers}
        return DnsPropagationResult(expected in observed, len(parsed.answers))

    @staticmethod
    def _normalize_answer(
        record_type: DnsRecordType,
        value: str,
    ) -> str:
        normalized = value.strip()
        if record_type is DnsRecordType.CNAME:
            return normalized.removesuffix(".").lower()
        if normalized.startswith('"') and normalized.endswith('"'):
            normalized = normalized[1:-1]
        return normalized.replace('" "', "")
