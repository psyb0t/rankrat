"""Fixed-origin Google Site Verification client for DNS ownership checks."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from rankrat.constants import MAX_PROVIDER_RESPONSE_BYTES
from rankrat.models.boundaries import Provider, normalize_indexnow_host
from rankrat.policy.boundaries import BoundaryPolicy
from rankrat.providers.base import (
    AccessTokenProvider,
    AccountId,
    ProviderFailureCode,
    ProviderOperationError,
    ProviderReadRequest,
)

_GOOGLE_SITE_VERIFICATION_ROOT = "https://www.googleapis.com/siteVerification/v1"
_DOMAIN_RESOURCE_TYPE = "INET_DOMAIN"
_MAX_VERIFICATION_TOKEN_CHARS = 4_096
_MAX_WEB_RESOURCE_ID_CHARS = 4_096

HttpTransportFactory = Callable[[], httpx.AsyncBaseTransport | None]


class GoogleVerificationMethod(StrEnum):
    """Google verification methods Rankrat can safely materialize through DNS."""

    DNS_TXT = "DNS_TXT"
    DNS_CNAME = "DNS_CNAME"


@dataclass(frozen=True, slots=True)
class GoogleVerificationToken:
    """Provider-issued token retained only inside the verification orchestrator."""

    method: GoogleVerificationMethod
    token: str


@dataclass(frozen=True, slots=True)
class GoogleVerifiedWebResource:
    """Safe receipt proving Google accepted ownership of one domain."""

    resource_id: str
    domain: str


class _TokenResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    method: GoogleVerificationMethod
    token: str = Field(min_length=1, max_length=_MAX_VERIFICATION_TOKEN_CHARS)


class _SiteResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    identifier: str
    type: str


class _WebResourceResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    id: str = Field(min_length=1, max_length=_MAX_WEB_RESOURCE_ID_CHARS)
    site: _SiteResponse


class _WebResourceListResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    items: tuple[_WebResourceResponse, ...] = ()


class GoogleSiteVerificationClient:
    """Issue and redeem domain verification tokens through Google's fixed API."""

    provider = Provider.GOOGLE

    def __init__(
        self,
        boundary_policy: BoundaryPolicy,
        token_provider: AccessTokenProvider,
        transport_factory: HttpTransportFactory = lambda: None,
    ) -> None:
        self._boundary_policy = boundary_policy
        self._token_provider = token_provider
        self._transport_factory = transport_factory

    async def get_token(
        self,
        request: ProviderReadRequest,
        domain: str,
        method: GoogleVerificationMethod = GoogleVerificationMethod.DNS_TXT,
    ) -> GoogleVerificationToken:
        normalized_domain = normalize_indexnow_host(domain)
        token = await self._access_token(request.account_id)
        payload = await self._request_json(
            request.timeout_seconds,
            token,
            "POST",
            "/token",
            json_body={
                "site": {
                    "type": _DOMAIN_RESOURCE_TYPE,
                    "identifier": normalized_domain,
                },
                "verificationMethod": method.value,
            },
        )
        try:
            response = _TokenResponse.model_validate(payload)
        except ValidationError as error:
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "Google Site Verification returned an invalid token response",
            ) from error
        if response.method is not method:
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "Google Site Verification returned a different verification method",
            )
        return GoogleVerificationToken(response.method, response.token)

    async def verify(
        self,
        request: ProviderReadRequest,
        domain: str,
        method: GoogleVerificationMethod = GoogleVerificationMethod.DNS_TXT,
    ) -> GoogleVerifiedWebResource:
        normalized_domain = normalize_indexnow_host(domain)
        token = await self._access_token(request.account_id)
        payload = await self._request_json(
            request.timeout_seconds,
            token,
            "POST",
            "/webResource",
            parameters={"verificationMethod": method.value},
            json_body={
                "site": {
                    "type": _DOMAIN_RESOURCE_TYPE,
                    "identifier": normalized_domain,
                }
            },
        )
        try:
            response = _WebResourceResponse.model_validate(payload)
        except ValidationError as error:
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "Google Site Verification returned an invalid resource response",
            ) from error
        if response.site.type != _DOMAIN_RESOURCE_TYPE:
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "Google Site Verification returned a different resource type",
            )
        returned_domain = normalize_indexnow_host(response.site.identifier)
        if returned_domain != normalized_domain:
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "Google Site Verification returned a different domain",
            )
        return GoogleVerifiedWebResource(response.id, returned_domain)

    async def is_verified(self, request: ProviderReadRequest, domain: str) -> bool:
        """Return whether the authorized user already owns one exact domain."""

        normalized_domain = normalize_indexnow_host(domain)
        token = await self._access_token(request.account_id)
        payload = await self._request_json(
            request.timeout_seconds,
            token,
            "GET",
            "/webResource",
        )
        try:
            response = _WebResourceListResponse.model_validate(payload)
        except ValidationError as error:
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "Google Site Verification returned an invalid resource list",
            ) from error
        for resource in response.items:
            if resource.site.type != _DOMAIN_RESOURCE_TYPE:
                continue
            if normalize_indexnow_host(resource.site.identifier) == normalized_domain:
                return True
        return False

    async def _access_token(self, account_id: AccountId) -> str:
        account = self._boundary_policy.resolve_account(str(account_id), Provider.GOOGLE)
        return await self._token_provider(account.credential)

    async def _request_json(
        self,
        timeout_seconds: float,
        token: str,
        method: str,
        path: str,
        *,
        parameters: dict[str, str] | None = None,
        json_body: dict[str, object] | None = None,
    ) -> object:
        try:
            async with httpx.AsyncClient(
                transport=self._transport_factory(),
                trust_env=False,
                follow_redirects=False,
                timeout=httpx.Timeout(timeout_seconds),
            ) as client:
                response = await client.request(
                    method,
                    f"{_GOOGLE_SITE_VERIFICATION_ROOT}{path}",
                    params=parameters,
                    json=json_body,
                    headers={"Authorization": f"Bearer {token}"},
                )
                self._raise_for_status(response)
                body = await self._read_bounded_body(response)
        except httpx.TimeoutException as error:
            raise ProviderOperationError(
                ProviderFailureCode.TIMEOUT,
                "Google Site Verification request timed out",
            ) from error
        except httpx.HTTPError as error:
            raise ProviderOperationError(
                ProviderFailureCode.UNAVAILABLE,
                "Google Site Verification is unavailable",
            ) from error
        try:
            return json.loads(body)
        except json.JSONDecodeError as error:
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "Google Site Verification returned invalid JSON",
            ) from error

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        if response.status_code == 401:
            raise ProviderOperationError(
                ProviderFailureCode.AUTHENTICATION,
                "Google Site Verification request was rejected",
            )
        if response.status_code in {403, 404}:
            raise ProviderOperationError(
                ProviderFailureCode.FORBIDDEN,
                "Google Site Verification request was forbidden",
            )
        if response.status_code == 429:
            raise ProviderOperationError(
                ProviderFailureCode.RATE_LIMITED,
                "Google Site Verification request was rate limited",
            )
        if response.status_code >= 500:
            raise ProviderOperationError(
                ProviderFailureCode.UNAVAILABLE,
                "Google Site Verification is unavailable",
            )
        if response.is_redirect or response.status_code >= 400:
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "Google Site Verification returned an unexpected response",
            )

    @staticmethod
    async def _read_bounded_body(response: httpx.Response) -> bytes:
        body = await response.aread()
        if len(body) > MAX_PROVIDER_RESPONSE_BYTES:
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "Google Site Verification response exceeds the allowed size",
            )
        return body
