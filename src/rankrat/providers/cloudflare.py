"""Fixed-origin Cloudflare DNS operations for ownership-verification records."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from rankrat.constants import (
    MAX_CLOUDFLARE_API_RESULTS,
    MAX_CLOUDFLARE_DNS_RECORD_CONTENT_CHARS,
    MAX_CLOUDFLARE_DNS_RECORD_NAME_CHARS,
    MAX_CLOUDFLARE_TOKEN_BYTES,
    MAX_PROVIDER_RESPONSE_BYTES,
)
from rankrat.errors import BoundaryDeniedError, InputLimitError
from rankrat.models.boundaries import DnsZone, Provider, normalize_indexnow_host
from rankrat.policy.boundaries import BoundaryPolicy
from rankrat.providers.base import (
    ProviderFailureCode,
    ProviderOperationError,
    ProviderReadiness,
    ProviderReadRequest,
)
from rankrat.providers.dns import DnsRecordReceipt, DnsRecordType

_CLOUDFLARE_API_ROOT = "https://api.cloudflare.com/client/v4"
_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{16,512}$")
_DNS_RECORD_COMMENT = "Managed by Rankrat site ownership verification"
_AUTOMATIC_TTL = 1
_MAX_IDENTIFIER_CHARS = 32
_ZONE_ID_PATTERN_TEXT = r"^[0-9a-f]{32}$"
_ZONE_ID_PATTERN = re.compile(_ZONE_ID_PATTERN_TEXT)

HttpTransportFactory = Callable[[], httpx.AsyncBaseTransport | None]


class _CloudflareZoneResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    id: str = Field(pattern=_ZONE_ID_PATTERN_TEXT)
    name: str = Field(min_length=1, max_length=MAX_CLOUDFLARE_DNS_RECORD_NAME_CHARS)


class _CloudflareDnsRecordResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    id: str = Field(min_length=1, max_length=_MAX_IDENTIFIER_CHARS)
    type: DnsRecordType
    name: str = Field(min_length=1, max_length=MAX_CLOUDFLARE_DNS_RECORD_NAME_CHARS)
    content: str = Field(min_length=1, max_length=MAX_CLOUDFLARE_DNS_RECORD_CONTENT_CHARS)


class _CloudflareListResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    success: bool
    result: list[object]


class _CloudflareRecordResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    success: bool
    result: object


class CloudflareDnsClient:
    """Create only exact TXT/CNAME verification records in configured zones."""

    provider = Provider.CLOUDFLARE

    def __init__(
        self,
        boundary_policy: BoundaryPolicy,
        transport_factory: HttpTransportFactory = lambda: None,
    ) -> None:
        self._boundary_policy = boundary_policy
        self._transport_factory = transport_factory

    async def readiness(self, request: ProviderReadRequest) -> ProviderReadiness:
        account = self._boundary_policy.resolve_account(
            str(request.account_id),
            Provider.CLOUDFLARE,
        )
        await self._list_zones(
            account.credential,
            request.timeout_seconds,
            name=None,
        )
        return ProviderReadiness(
            account_id=request.account_id,
            provider=Provider.CLOUDFLARE,
            available=True,
            detail="Cloudflare DNS API is reachable",
        )

    async def resolve_zone(
        self,
        request: ProviderReadRequest,
        hostname: str,
    ) -> DnsZone:
        normalized_hostname = normalize_indexnow_host(hostname)
        try:
            zone = self._boundary_policy.resolve_dns_zone(
                str(request.account_id),
                normalized_hostname,
            )
            self._validate_zone_id(zone.provider_zone_id)
            return zone
        except BoundaryDeniedError:
            pass
        account = self._boundary_policy.resolve_account(
            str(request.account_id),
            Provider.CLOUDFLARE,
        )
        labels = normalized_hostname.split(".")
        for index in range(len(labels) - 1):
            candidate_name = ".".join(labels[index:])
            zones = await self._list_zones(
                account.credential,
                request.timeout_seconds,
                name=candidate_name,
            )
            exact = tuple(zone for zone in zones if zone.name == candidate_name)
            if len(exact) == 1:
                return exact[0]
            if len(exact) > 1:
                raise ProviderOperationError(
                    ProviderFailureCode.INVALID_RESPONSE,
                    "Cloudflare returned duplicate zones",
                )
        raise BoundaryDeniedError("Cloudflare zone is outside the reachable account")

    async def ensure_verification_record(
        self,
        request: ProviderReadRequest,
        hostname: str,
        record_type: DnsRecordType,
        name: str,
        content: str,
    ) -> DnsRecordReceipt:
        zone = await self.resolve_zone(request, hostname)
        normalized_name = self._validate_record_name(name, zone.name)
        normalized_content = self._validate_record_content(record_type, content)
        account = self._boundary_policy.resolve_account(
            str(request.account_id),
            Provider.CLOUDFLARE,
        )
        existing = await self._list_records(
            account.credential,
            zone.provider_zone_id,
            request.timeout_seconds,
            record_type,
            normalized_name,
        )
        for record in existing:
            if record.content == normalized_content:
                return DnsRecordReceipt(
                    provider_zone_id=zone.provider_zone_id,
                    record_id=record.id,
                    record_type=record_type,
                    name=normalized_name,
                    created=False,
                )
        if record_type is DnsRecordType.CNAME and existing:
            raise BoundaryDeniedError("Cloudflare CNAME verification name is already occupied")
        record = await self._create_record(
            account.credential,
            zone.provider_zone_id,
            request.timeout_seconds,
            record_type,
            normalized_name,
            normalized_content,
        )
        return DnsRecordReceipt(
            provider_zone_id=zone.provider_zone_id,
            record_id=record.id,
            record_type=record_type,
            name=normalized_name,
            created=True,
        )

    async def _list_zones(
        self,
        credential: Path,
        timeout_seconds: float,
        name: str | None,
    ) -> tuple[DnsZone, ...]:
        parameters: dict[str, str | int] = {"per_page": MAX_CLOUDFLARE_API_RESULTS}
        if name is not None:
            parameters["name"] = name
        payload = await self._request_json(
            credential,
            timeout_seconds,
            "GET",
            "/zones",
            parameters=parameters,
        )
        try:
            response = _CloudflareListResponse.model_validate(payload)
            zones = tuple(_CloudflareZoneResponse.model_validate(item) for item in response.result)
        except ValidationError as error:
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "Cloudflare returned an invalid zone response",
            ) from error
        if not response.success or len(zones) > MAX_CLOUDFLARE_API_RESULTS:
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "Cloudflare returned an invalid zone response",
            )
        return tuple(DnsZone(provider_zone_id=zone.id, name=zone.name) for zone in zones)

    async def _list_records(
        self,
        credential: Path,
        zone_id: str,
        timeout_seconds: float,
        record_type: DnsRecordType,
        name: str,
    ) -> tuple[_CloudflareDnsRecordResponse, ...]:
        payload = await self._request_json(
            credential,
            timeout_seconds,
            "GET",
            f"/zones/{zone_id}/dns_records",
            parameters={
                "type": record_type.value,
                "name.exact": name,
                "per_page": MAX_CLOUDFLARE_API_RESULTS,
            },
        )
        try:
            response = _CloudflareListResponse.model_validate(payload)
            records = tuple(
                _CloudflareDnsRecordResponse.model_validate(item) for item in response.result
            )
        except ValidationError as error:
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "Cloudflare returned an invalid DNS record response",
            ) from error
        if not response.success or len(records) > MAX_CLOUDFLARE_API_RESULTS:
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "Cloudflare returned an invalid DNS record response",
            )
        return records

    async def _create_record(
        self,
        credential: Path,
        zone_id: str,
        timeout_seconds: float,
        record_type: DnsRecordType,
        name: str,
        content: str,
    ) -> _CloudflareDnsRecordResponse:
        payload = await self._request_json(
            credential,
            timeout_seconds,
            "POST",
            f"/zones/{zone_id}/dns_records",
            json_body={
                "type": record_type.value,
                "name": name,
                "content": content,
                "ttl": _AUTOMATIC_TTL,
                "proxied": False,
                "comment": _DNS_RECORD_COMMENT,
            },
        )
        try:
            response = _CloudflareRecordResponse.model_validate(payload)
            record = _CloudflareDnsRecordResponse.model_validate(response.result)
        except ValidationError as error:
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "Cloudflare returned an invalid DNS record response",
            ) from error
        if not response.success:
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "Cloudflare returned an invalid DNS record response",
            )
        return record

    async def _request_json(
        self,
        credential: Path,
        timeout_seconds: float,
        method: str,
        path: str,
        *,
        parameters: dict[str, str | int] | None = None,
        json_body: dict[str, object] | None = None,
    ) -> object:
        token = self._load_token(credential)
        try:
            async with httpx.AsyncClient(
                transport=self._transport_factory(),
                trust_env=False,
                follow_redirects=False,
                timeout=httpx.Timeout(timeout_seconds),
            ) as client:
                response = await client.request(
                    method,
                    f"{_CLOUDFLARE_API_ROOT}{path}",
                    params=parameters,
                    json=json_body,
                    headers={"Authorization": f"Bearer {token}"},
                )
                self._raise_for_status(response)
                body = await self._read_bounded_body(response)
        except httpx.TimeoutException as error:
            raise ProviderOperationError(
                ProviderFailureCode.TIMEOUT,
                "Cloudflare request timed out",
            ) from error
        except httpx.HTTPError as error:
            raise ProviderOperationError(
                ProviderFailureCode.UNAVAILABLE,
                "Cloudflare is unavailable",
            ) from error
        try:
            return json.loads(body)
        except json.JSONDecodeError as error:
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "Cloudflare returned invalid JSON",
            ) from error

    @staticmethod
    def _validate_record_name(name: str, zone_name: str) -> str:
        normalized = normalize_indexnow_host(name)
        if normalized != zone_name and not normalized.endswith(f".{zone_name}"):
            raise BoundaryDeniedError("Cloudflare verification record escapes its zone")
        if len(normalized) > MAX_CLOUDFLARE_DNS_RECORD_NAME_CHARS:
            raise InputLimitError("Cloudflare verification record name is too long")
        return normalized

    @staticmethod
    def _validate_record_content(
        record_type: DnsRecordType,
        content: str,
    ) -> str:
        normalized = content.strip()
        if not normalized or len(normalized) > MAX_CLOUDFLARE_DNS_RECORD_CONTENT_CHARS:
            raise InputLimitError("Cloudflare verification record content is invalid")
        if any(character in normalized for character in "\r\n\x00"):
            raise InputLimitError("Cloudflare verification record content is invalid")
        if record_type is DnsRecordType.CNAME:
            return normalize_indexnow_host(normalized)
        return normalized

    @staticmethod
    def _validate_zone_id(zone_id: str) -> None:
        if not _ZONE_ID_PATTERN.fullmatch(zone_id):
            raise BoundaryDeniedError("Cloudflare zone identifier is invalid")

    @staticmethod
    def _load_token(path: Path) -> str:
        try:
            raw_token = path.read_bytes()[: MAX_CLOUDFLARE_TOKEN_BYTES + 1]
            token = raw_token.decode("ascii").rstrip("\r\n")
        except (OSError, UnicodeDecodeError) as error:
            raise ProviderOperationError(
                ProviderFailureCode.AUTHENTICATION,
                "Cloudflare API token is unavailable",
            ) from error
        if len(raw_token) > MAX_CLOUDFLARE_TOKEN_BYTES or not _TOKEN_PATTERN.fullmatch(token):
            raise ProviderOperationError(
                ProviderFailureCode.AUTHENTICATION,
                "Cloudflare API token is unavailable",
            )
        return token

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        if response.status_code in {401, 403}:
            raise ProviderOperationError(
                ProviderFailureCode.AUTHENTICATION,
                "Cloudflare request was rejected",
            )
        if response.status_code == 429:
            raise ProviderOperationError(
                ProviderFailureCode.RATE_LIMITED,
                "Cloudflare request was rate limited",
            )
        if response.status_code >= 500:
            raise ProviderOperationError(
                ProviderFailureCode.UNAVAILABLE,
                "Cloudflare is unavailable",
            )
        if response.is_redirect or response.status_code >= 400:
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "Cloudflare returned an unexpected response",
            )

    @staticmethod
    async def _read_bounded_body(response: httpx.Response) -> bytes:
        content_length = response.headers.get("content-length")
        if (
            content_length is not None
            and content_length.isdigit()
            and int(content_length) > MAX_PROVIDER_RESPONSE_BYTES
        ):
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "Cloudflare response exceeds the allowed size",
            )
        body = await response.aread()
        if len(body) > MAX_PROVIDER_RESPONSE_BYTES:
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "Cloudflare response exceeds the allowed size",
            )
        return body
