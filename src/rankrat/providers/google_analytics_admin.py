"""Fixed-origin Google Analytics Admin API writes for local site onboarding."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from rankrat.constants import (
    GOOGLE_ANALYTICS_EDIT_SCOPE as _GOOGLE_ANALYTICS_EDIT_SCOPE,
)
from rankrat.constants import (
    MAX_PROVIDER_RESPONSE_BYTES,
    MAX_SITE_ONBOARDING_DISPLAY_NAME_CHARS,
)
from rankrat.models.boundaries import Provider
from rankrat.policy.boundaries import BoundaryPolicy
from rankrat.providers.base import (
    AccessTokenProvider,
    ProviderFailureCode,
    ProviderOperationError,
    ProviderReadRequest,
)
from rankrat.providers.google_search_console import HttpTransportFactory

GOOGLE_ANALYTICS_EDIT_SCOPE = _GOOGLE_ANALYTICS_EDIT_SCOPE
_GOOGLE_ANALYTICS_ADMIN_ROOT = "https://analyticsadmin.googleapis.com/v1beta"
_GOOGLE_ANALYTICS_CREATE_PROPERTY_URL = f"{_GOOGLE_ANALYTICS_ADMIN_ROOT}/properties"
_GOOGLE_ANALYTICS_CREATE_WEB_STREAM_URL = (
    f"{_GOOGLE_ANALYTICS_ADMIN_ROOT}/properties/{{property_id}}/dataStreams"
)
_AUTHORIZATION_HEADER = "Authorization"
_BEARER_PREFIX = "Bearer "
_HTTP_POST = "POST"
_GA4_ACCOUNT_RESOURCE_PREFIX = "accounts/"
_GA4_PROPERTY_RESOURCE_PREFIX = "properties/"
_GA4_WEB_STREAM_TYPE = "WEB_DATA_STREAM"
_GA4_RESOURCE_ID_PATTERN = re.compile(r"^[0-9]+$")
_MEASUREMENT_ID_PATTERN = re.compile(r"^G-[A-Z0-9]+$")


@dataclass(frozen=True, slots=True)
class Ga4SitePropertyCreateRequest:
    """One validated GA4 property and its first web stream to create."""

    account_id: str
    parent_account_id: str
    display_name: str
    site_url: str
    time_zone: str
    currency_code: str


@dataclass(frozen=True, slots=True)
class Ga4SiteProperty:
    """Bounded identifiers needed to deploy and later query a newly created GA4 property."""

    property_id: str
    measurement_id: str


class _Ga4PropertyResponse(BaseModel):
    """Strict subset of the Admin API Property create response."""

    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)

    name: str
    parent: str
    displayName: str
    timeZone: str
    currencyCode: str

    @field_validator("name", "parent", "displayName", "timeZone", "currencyCode")
    @classmethod
    def validate_text(cls, value: str) -> str:
        if not value or len(value) > MAX_SITE_ONBOARDING_DISPLAY_NAME_CHARS:
            raise ValueError("Google Analytics property response has invalid text")
        return value


class _Ga4WebStreamDataResponse(BaseModel):
    """Strict subset of the Admin API web stream fields Rankrat needs."""

    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)

    defaultUri: str
    measurementId: str


class _Ga4DataStreamResponse(BaseModel):
    """Strict subset of the Admin API data-stream create response."""

    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)

    name: str
    displayName: str
    type: str
    webStreamData: _Ga4WebStreamDataResponse


class GoogleAnalyticsAdminClient:
    """Create a GA4 property and web stream only under an exact configured parent account."""

    provider = Provider.GOOGLE

    def __init__(
        self,
        boundary_policy: BoundaryPolicy,
        access_token_provider: AccessTokenProvider,
        transport_factory: HttpTransportFactory = lambda: None,
    ) -> None:
        self._boundary_policy = boundary_policy
        self._access_token_provider = access_token_provider
        self._transport_factory = transport_factory

    async def create_site_property(
        self,
        request: ProviderReadRequest,
        create_request: Ga4SitePropertyCreateRequest,
    ) -> Ga4SiteProperty:
        """Create one GA4 property and its web stream at documented fixed endpoints."""

        # The parent GA4 account comes from the caller, not the boundary file. The
        # credential account is still pinned; which of that identity's own GA4
        # accounts the new property lands under is the caller's choice.
        account = self._boundary_policy.require_google_onboarding_account(
            str(request.account_id),
        )
        token = await self._token_for_account(account.credential)
        property_payload: dict[str, object] = {
            "parent": f"{_GA4_ACCOUNT_RESOURCE_PREFIX}{create_request.parent_account_id}",
            "displayName": create_request.display_name,
            "timeZone": create_request.time_zone,
            "currencyCode": create_request.currency_code,
        }
        property_response = await self._request_json(
            _GOOGLE_ANALYTICS_CREATE_PROPERTY_URL,
            token,
            request.timeout_seconds,
            property_payload,
        )
        property_id = self._validate_property_response(property_response, create_request)
        stream_payload: dict[str, object] = {
            "displayName": create_request.display_name,
            "type": _GA4_WEB_STREAM_TYPE,
            "webStreamData": {"defaultUri": create_request.site_url},
        }
        stream_response = await self._request_json(
            _GOOGLE_ANALYTICS_CREATE_WEB_STREAM_URL.format(property_id=property_id),
            token,
            request.timeout_seconds,
            stream_payload,
        )
        measurement_id = self._validate_web_stream_response(
            stream_response,
            property_id,
            create_request,
        )
        return Ga4SiteProperty(property_id, measurement_id)

    async def _token_for_account(self, credential_path: Path) -> str:
        try:
            return await self._access_token_provider(credential_path)
        except ProviderOperationError:
            raise
        except Exception as error:
            raise ProviderOperationError(
                ProviderFailureCode.AUTHENTICATION,
                "Google Analytics Admin authentication failed",
            ) from error

    async def _request_json(
        self,
        url: str,
        token: str,
        timeout_seconds: float,
        payload: dict[str, object],
    ) -> object:
        try:
            async with (
                httpx.AsyncClient(
                    transport=self._transport_factory(),
                    trust_env=False,
                    follow_redirects=False,
                    timeout=httpx.Timeout(timeout_seconds),
                ) as client,
                client.stream(
                    _HTTP_POST,
                    url,
                    headers={_AUTHORIZATION_HEADER: f"{_BEARER_PREFIX}{token}"},
                    json=payload,
                ) as response,
            ):
                self._raise_for_status(response)
                body = await self._read_bounded_body(response)
        except ProviderOperationError:
            raise
        except httpx.TimeoutException as error:
            raise ProviderOperationError(
                ProviderFailureCode.TIMEOUT,
                "Google Analytics Admin request timed out",
            ) from error
        except httpx.HTTPError as error:
            raise ProviderOperationError(
                ProviderFailureCode.UNAVAILABLE,
                "Google Analytics Admin is unavailable",
            ) from error
        try:
            return json.loads(body)
        except json.JSONDecodeError as error:
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "Google Analytics Admin returned invalid JSON",
            ) from error

    @staticmethod
    def _validate_property_response(
        payload: object,
        request: Ga4SitePropertyCreateRequest,
    ) -> str:
        try:
            response = _Ga4PropertyResponse.model_validate(payload)
            property_id = _resource_id(response.name, _GA4_PROPERTY_RESOURCE_PREFIX)
            if response.parent != f"{_GA4_ACCOUNT_RESOURCE_PREFIX}{request.parent_account_id}":
                raise ValueError("Google Analytics property has an unexpected parent")
            if (
                response.displayName != request.display_name
                or response.timeZone != request.time_zone
                or response.currencyCode != request.currency_code
            ):
                raise ValueError("Google Analytics property response does not match the request")
            return property_id
        except (ValidationError, ValueError) as error:
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "Google Analytics Admin returned an invalid property response",
            ) from error

    @staticmethod
    def _validate_web_stream_response(
        payload: object,
        property_id: str,
        request: Ga4SitePropertyCreateRequest,
    ) -> str:
        try:
            response = _Ga4DataStreamResponse.model_validate(payload)
            expected_prefix = f"{_GA4_PROPERTY_RESOURCE_PREFIX}{property_id}/dataStreams/"
            if not response.name.startswith(expected_prefix):
                raise ValueError("Google Analytics stream belongs to another property")
            stream_id = response.name.removeprefix(expected_prefix)
            if _GA4_RESOURCE_ID_PATTERN.fullmatch(stream_id) is None:
                raise ValueError("Google Analytics stream ID is invalid")
            if (
                response.displayName != request.display_name
                or response.type != _GA4_WEB_STREAM_TYPE
                or response.webStreamData.defaultUri != request.site_url
                or _MEASUREMENT_ID_PATTERN.fullmatch(response.webStreamData.measurementId) is None
            ):
                raise ValueError("Google Analytics stream response does not match the request")
            return response.webStreamData.measurementId
        except (ValidationError, ValueError) as error:
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "Google Analytics Admin returned an invalid web-stream response",
            ) from error

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        failure_codes = {
            401: ProviderFailureCode.AUTHENTICATION,
            403: ProviderFailureCode.FORBIDDEN,
            429: ProviderFailureCode.RATE_LIMITED,
        }
        if response.status_code in failure_codes:
            raise ProviderOperationError(
                failure_codes[response.status_code],
                "Google Analytics Admin request was rejected",
            )
        if response.status_code >= 500:
            raise ProviderOperationError(
                ProviderFailureCode.UNAVAILABLE,
                "Google Analytics Admin is unavailable",
            )
        if response.is_redirect or response.status_code >= 400:
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "Google Analytics Admin returned an unexpected response",
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
                "Google Analytics Admin response exceeds the allowed size",
            )
        body = bytearray()
        async for chunk in response.aiter_bytes():
            body.extend(chunk)
            if len(body) > MAX_PROVIDER_RESPONSE_BYTES:
                raise ProviderOperationError(
                    ProviderFailureCode.INVALID_RESPONSE,
                    "Google Analytics Admin response exceeds the allowed size",
                )
        return bytes(body)


def _resource_id(value: str, prefix: str) -> str:
    resource_id = value.removeprefix(prefix)
    if resource_id == value or _GA4_RESOURCE_ID_PATTERN.fullmatch(resource_id) is None:
        raise ValueError("Google Analytics resource name is invalid")
    return resource_id
