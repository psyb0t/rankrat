"""Fixed-origin Google Analytics Admin API writes for local site onboarding."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from rankrat.constants import (
    GOOGLE_ANALYTICS_EDIT_SCOPE as _GOOGLE_ANALYTICS_EDIT_SCOPE,
)
from rankrat.constants import (
    MAX_PROVIDER_RESPONSE_BYTES,
    MAX_SITE_ONBOARDING_DISPLAY_NAME_CHARS,
)
from rankrat.errors import InputLimitError
from rankrat.models.boundaries import Provider, ResourceKind
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
_GOOGLE_ANALYTICS_LIST_DATA_STREAMS_URL = (
    f"{_GOOGLE_ANALYTICS_ADMIN_ROOT}/properties/{{property_id}}/dataStreams"
)
_GOOGLE_ANALYTICS_UPDATE_ACCOUNT_URL = f"{_GOOGLE_ANALYTICS_ADMIN_ROOT}/accounts/{{account_id}}"
_GOOGLE_ANALYTICS_UPDATE_PROPERTY_URL = f"{_GOOGLE_ANALYTICS_ADMIN_ROOT}/properties/{{property_id}}"
_AUTHORIZATION_HEADER = "Authorization"
_BEARER_PREFIX = "Bearer "
_HTTP_POST = "POST"
_HTTP_GET = "GET"
_HTTP_PATCH = "PATCH"
# The Admin API ignores any field absent from updateMask, and the mask is in
# snake case while the body is camel case.
_GA4_DISPLAY_NAME_UPDATE_MASK = "display_name"
_GA4_DATA_STREAM_PAGE_SIZE = 200
_GA4_MAX_DATA_STREAM_PAGES = 10
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


@dataclass(frozen=True, slots=True)
class Ga4DataStream:
    """One configured property's data stream, with its measurement ID when it is a web stream."""

    stream_id: str
    display_name: str
    stream_type: str
    default_uri: str | None
    measurement_id: str | None


@dataclass(frozen=True, slots=True)
class Ga4RenamedResource:
    """The post-rename state of one GA4 account or property."""

    resource_id: str
    display_name: str


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
    """Strict subset of the Admin API data-stream response.

    webStreamData is optional because a property's streams may be Android or iOS
    app streams, which carry no measurement ID. The create path still requires
    one and checks for it explicitly.
    """

    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)

    name: str
    displayName: str
    type: str
    webStreamData: _Ga4WebStreamDataResponse | None = None


class _Ga4DataStreamListResponse(BaseModel):
    """Strict subset of the Admin API data-stream list page."""

    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)

    dataStreams: list[_Ga4DataStreamResponse] = Field(
        default_factory=list[_Ga4DataStreamResponse],
    )
    nextPageToken: str | None = None


class _Ga4AccountResponse(BaseModel):
    """Strict subset of the Admin API account response."""

    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)

    name: str
    displayName: str


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

    async def list_data_streams(
        self,
        request: ProviderReadRequest,
        property_id: str,
    ) -> tuple[Ga4DataStream, ...]:
        """List one configured property's data streams, including their measurement IDs."""

        account = self._boundary_policy.require_resource(
            str(request.account_id),
            Provider.GOOGLE,
            ResourceKind.GA4_PROPERTY,
            property_id,
        )
        token = await self._token_for_account(account.credential)
        streams: list[Ga4DataStream] = []
        page_token: str | None = None
        for _ in range(_GA4_MAX_DATA_STREAM_PAGES):
            params = {"pageSize": str(_GA4_DATA_STREAM_PAGE_SIZE)}
            if page_token is not None:
                params["pageToken"] = page_token
            payload = await self._request_json(
                _GOOGLE_ANALYTICS_LIST_DATA_STREAMS_URL.format(property_id=property_id),
                token,
                request.timeout_seconds,
                method=_HTTP_GET,
                params=params,
            )
            page, page_token = self._validate_data_stream_page(payload, property_id)
            streams.extend(page)
            if page_token is None:
                return tuple(streams)
        raise ProviderOperationError(
            ProviderFailureCode.INVALID_RESPONSE,
            "Google Analytics Admin returned more data-stream pages than allowed",
        )

    async def update_account_display_name(
        self,
        request: ProviderReadRequest,
        analytics_account_id: str,
        display_name: str,
    ) -> Ga4RenamedResource:
        """Rename one GA4 account the configured credential can administer."""

        # Renaming reaches an account-wide resource rather than a listed one, so
        # it rides the same explicit switch that permits account discovery.
        account = self._boundary_policy.require_google_account_discovery(str(request.account_id))
        _require_ga4_resource_id(analytics_account_id, "account")
        token = await self._token_for_account(account.credential)
        payload = await self._request_json(
            _GOOGLE_ANALYTICS_UPDATE_ACCOUNT_URL.format(account_id=analytics_account_id),
            token,
            request.timeout_seconds,
            {"displayName": display_name},
            method=_HTTP_PATCH,
            params={"updateMask": _GA4_DISPLAY_NAME_UPDATE_MASK},
        )
        return self._validate_renamed_account(payload, analytics_account_id, display_name)

    async def update_property_display_name(
        self,
        request: ProviderReadRequest,
        property_id: str,
        display_name: str,
    ) -> Ga4RenamedResource:
        """Rename one configured GA4 property."""

        account = self._boundary_policy.require_resource(
            str(request.account_id),
            Provider.GOOGLE,
            ResourceKind.GA4_PROPERTY,
            property_id,
        )
        token = await self._token_for_account(account.credential)
        payload = await self._request_json(
            _GOOGLE_ANALYTICS_UPDATE_PROPERTY_URL.format(property_id=property_id),
            token,
            request.timeout_seconds,
            {"displayName": display_name},
            method=_HTTP_PATCH,
            params={"updateMask": _GA4_DISPLAY_NAME_UPDATE_MASK},
        )
        return self._validate_renamed_property(payload, property_id, display_name)

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
        payload: dict[str, object] | None = None,
        *,
        method: str = _HTTP_POST,
        params: dict[str, str] | None = None,
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
                    method,
                    url,
                    headers={_AUTHORIZATION_HEADER: f"{_BEARER_PREFIX}{token}"},
                    json=payload,
                    params=params,
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
            # webStreamData is optional on the shared model because app streams
            # have none; a create response for a web stream must still carry it.
            web_data = response.webStreamData
            if web_data is None:
                raise ValueError("Google Analytics web stream response has no web stream data")
            if (
                response.displayName != request.display_name
                or response.type != _GA4_WEB_STREAM_TYPE
                or web_data.defaultUri != request.site_url
                or _MEASUREMENT_ID_PATTERN.fullmatch(web_data.measurementId) is None
            ):
                raise ValueError("Google Analytics stream response does not match the request")
            return web_data.measurementId
        except (ValidationError, ValueError) as error:
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "Google Analytics Admin returned an invalid web-stream response",
            ) from error

    @staticmethod
    def _validate_data_stream_page(
        payload: object,
        property_id: str,
    ) -> tuple[tuple[Ga4DataStream, ...], str | None]:
        try:
            page = _Ga4DataStreamListResponse.model_validate(payload)
            expected_prefix = f"{_GA4_PROPERTY_RESOURCE_PREFIX}{property_id}/dataStreams/"
            streams: list[Ga4DataStream] = []
            for stream in page.dataStreams:
                # A stream naming another property would mean the response does
                # not belong to the resource that was authorized.
                if not stream.name.startswith(expected_prefix):
                    raise ValueError("Google Analytics stream belongs to another property")
                stream_id = stream.name.removeprefix(expected_prefix)
                if _GA4_RESOURCE_ID_PATTERN.fullmatch(stream_id) is None:
                    raise ValueError("Google Analytics stream ID is invalid")
                web_data = stream.webStreamData
                measurement_id = web_data.measurementId if web_data is not None else None
                if (
                    measurement_id is not None
                    and _MEASUREMENT_ID_PATTERN.fullmatch(measurement_id) is None
                ):
                    raise ValueError("Google Analytics measurement ID is invalid")
                streams.append(
                    Ga4DataStream(
                        stream_id=stream_id,
                        display_name=stream.displayName,
                        stream_type=stream.type,
                        default_uri=web_data.defaultUri if web_data is not None else None,
                        measurement_id=measurement_id,
                    )
                )
            return tuple(streams), page.nextPageToken or None
        except (ValidationError, ValueError) as error:
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "Google Analytics Admin returned an invalid data-stream response",
            ) from error

    @staticmethod
    def _validate_renamed_account(
        payload: object,
        analytics_account_id: str,
        display_name: str,
    ) -> Ga4RenamedResource:
        try:
            response = _Ga4AccountResponse.model_validate(payload)
            if response.name != f"{_GA4_ACCOUNT_RESOURCE_PREFIX}{analytics_account_id}":
                raise ValueError("Google Analytics renamed a different account")
            if response.displayName != display_name:
                raise ValueError("Google Analytics account name does not match the request")
            return Ga4RenamedResource(analytics_account_id, response.displayName)
        except (ValidationError, ValueError) as error:
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "Google Analytics Admin returned an invalid account response",
            ) from error

    @staticmethod
    def _validate_renamed_property(
        payload: object,
        property_id: str,
        display_name: str,
    ) -> Ga4RenamedResource:
        try:
            response = _Ga4AccountResponse.model_validate(payload)
            if response.name != f"{_GA4_PROPERTY_RESOURCE_PREFIX}{property_id}":
                raise ValueError("Google Analytics renamed a different property")
            if response.displayName != display_name:
                raise ValueError("Google Analytics property name does not match the request")
            return Ga4RenamedResource(property_id, response.displayName)
        except (ValidationError, ValueError) as error:
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "Google Analytics Admin returned an invalid property response",
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


def _require_ga4_resource_id(value: str, kind: str) -> None:
    """Reject anything that is not a bare numeric ID before it reaches a URL path.

    The request models validate this too; this is the last check before the value
    is interpolated into an Admin API path.
    """

    if _GA4_RESOURCE_ID_PATTERN.fullmatch(value) is None:
        raise InputLimitError(f"Google Analytics {kind} ID is invalid")
