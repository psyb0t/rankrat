"""Fixed-origin Google Tag Manager v2 management for one OAuth account."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import cast

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from rankrat.constants import (
    MAX_GTM_ENTITIES,
    MAX_GTM_NAME_CHARS,
    MAX_GTM_NOTES_CHARS,
    MAX_GTM_PARAMETER_DEPTH,
    MAX_GTM_PARAMETERS,
    MAX_PROVIDER_RESPONSE_BYTES,
)
from rankrat.models.boundaries import Provider
from rankrat.policy.boundaries import BoundaryPolicy
from rankrat.providers.base import (
    AccessTokenProvider,
    ProviderFailureCode,
    ProviderOperationError,
    ProviderReadRequest,
)

_API_ROOT = "https://tagmanager.googleapis.com/tagmanager/v2"
_AUTHORIZATION_HEADER = "Authorization"
_BEARER_PREFIX = "Bearer "
_ID_PATTERN = re.compile(r"^[0-9]{1,64}$")
_TEXT_PATTERN = re.compile(r"\S")

HttpTransportFactory = Callable[[], httpx.AsyncBaseTransport | None]


class GtmEntityKind(StrEnum):
    """The GTM workspace resource families Rankrat manages."""

    TAG = "tag"
    TRIGGER = "trigger"
    VARIABLE = "variable"


class GtmUsageContext(StrEnum):
    """Documented GTM container usage contexts."""

    WEB = "web"
    ANDROID = "android"
    IOS = "ios"
    AMP = "amp"
    SERVER = "server"


class GtmParameter(BaseModel):
    """One bounded GTM parameter, including nested list or map parameters."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    key: str = Field(min_length=1, max_length=MAX_GTM_NAME_CHARS)
    type: str = Field(min_length=1, max_length=MAX_GTM_NAME_CHARS)
    value: str | None = Field(default=None, max_length=MAX_GTM_NOTES_CHARS)
    list_items: tuple[GtmParameter, ...] = ()
    map_items: tuple[GtmParameter, ...] = ()

    @model_validator(mode="after")
    def validate_value_shape(self) -> GtmParameter:
        values = (
            int(self.value is not None) + int(bool(self.list_items)) + int(bool(self.map_items))
        )
        if values != 1:
            raise ValueError("a GTM parameter requires exactly one value, list, or map")
        return self

    def as_payload(self) -> dict[str, object]:
        """Map Rankrat's descriptive fields to the documented GTM wire shape."""

        payload: dict[str, object] = {"key": self.key, "type": self.type}
        if self.value is not None:
            payload["value"] = self.value
            return payload
        if self.list_items:
            payload["list"] = [item.as_payload() for item in self.list_items]
            return payload
        payload["map"] = [item.as_payload() for item in self.map_items]
        return payload


GtmParameter.model_rebuild()


class GtmEntityDefinition(BaseModel):
    """Typed mutable fields shared by GTM tags, triggers, and variables."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1, max_length=MAX_GTM_NAME_CHARS)
    type: str = Field(min_length=1, max_length=MAX_GTM_NAME_CHARS)
    parameters: tuple[GtmParameter, ...] = ()
    filters: tuple[GtmParameter, ...] = ()
    firing_trigger_ids: tuple[str, ...] = ()
    blocking_trigger_ids: tuple[str, ...] = ()
    notes: str | None = Field(default=None, max_length=MAX_GTM_NOTES_CHARS)

    @model_validator(mode="after")
    def validate_nested_parameters(self) -> GtmEntityDefinition:
        identifiers = (*self.firing_trigger_ids, *self.blocking_trigger_ids)
        if any(_ID_PATTERN.fullmatch(value) is None for value in identifiers):
            raise ValueError("GTM trigger IDs must be numeric identifiers")
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("GTM trigger IDs must not repeat")
        parameter_count = sum(
            _parameter_count(parameter, 1) for parameter in (*self.parameters, *self.filters)
        )
        if parameter_count > MAX_GTM_PARAMETERS:
            raise ValueError("GTM entity has too many parameters")
        return self

    def as_payload(self) -> dict[str, object]:
        """Return only the documented mutable GTM entity fields."""

        payload: dict[str, object] = {"name": self.name, "type": self.type}
        if self.parameters:
            payload["parameter"] = [parameter.as_payload() for parameter in self.parameters]
        if self.filters:
            payload["filter"] = [parameter.as_payload() for parameter in self.filters]
        if self.firing_trigger_ids:
            payload["firingTriggerId"] = list(self.firing_trigger_ids)
        if self.blocking_trigger_ids:
            payload["blockingTriggerId"] = list(self.blocking_trigger_ids)
        if self.notes is not None:
            payload["notes"] = self.notes
        return payload


@dataclass(frozen=True, slots=True)
class GtmAccount:
    account_id: str
    name: str
    path: str


@dataclass(frozen=True, slots=True)
class GtmContainer:
    account_id: str
    container_id: str
    name: str
    path: str
    public_id: str | None


@dataclass(frozen=True, slots=True)
class GtmWorkspace:
    account_id: str
    container_id: str
    workspace_id: str
    name: str
    path: str


@dataclass(frozen=True, slots=True)
class GtmEntity:
    kind: GtmEntityKind
    account_id: str
    container_id: str
    workspace_id: str
    entity_id: str
    name: str
    type: str
    path: str


@dataclass(frozen=True, slots=True)
class GtmVersion:
    account_id: str
    container_id: str
    version_id: str
    name: str
    path: str


class _GtmAccountResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)

    accountId: str
    name: str
    path: str


class _GtmContainerResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)

    accountId: str
    containerId: str
    name: str
    path: str
    publicId: str | None = None


class _GtmWorkspaceResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)

    accountId: str
    containerId: str
    workspaceId: str
    name: str
    path: str


class _GtmEntityResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)

    accountId: str
    containerId: str
    workspaceId: str
    name: str
    path: str
    type: str


class _GtmVersionResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)

    accountId: str
    containerId: str
    containerVersionId: str
    name: str
    path: str


class GoogleTagManagerClient:
    """Call only documented fixed GTM v2 account/container/workspace routes."""

    provider = Provider.GOOGLE

    def __init__(
        self,
        policy: BoundaryPolicy,
        access_token_provider: AccessTokenProvider,
        transport_factory: HttpTransportFactory = lambda: None,
    ) -> None:
        self._policy = policy
        self._access_token_provider = access_token_provider
        self._transport_factory = transport_factory

    async def list_accounts(self, request: ProviderReadRequest) -> tuple[GtmAccount, ...]:
        payload = await self._request_json(request, "GET", "accounts")
        return tuple(
            _gtm_account(item) for item in _response_items(payload, "account", "GTM account list")
        )

    async def list_containers(
        self,
        request: ProviderReadRequest,
        gtm_account_id: str,
    ) -> tuple[GtmContainer, ...]:
        account_id = _require_id(gtm_account_id, "GTM account ID")
        payload = await self._request_json(request, "GET", f"accounts/{account_id}/containers")
        return tuple(
            _gtm_container(item)
            for item in _response_items(payload, "container", "GTM container list")
        )

    async def create_container(
        self,
        request: ProviderReadRequest,
        gtm_account_id: str,
        name: str,
        usage_contexts: tuple[GtmUsageContext, ...],
    ) -> GtmContainer:
        account_id = _require_id(gtm_account_id, "GTM account ID")
        if not _TEXT_PATTERN.search(name) or len(name) > MAX_GTM_NAME_CHARS:
            raise ValueError("GTM container name is invalid")
        if not usage_contexts:
            raise ValueError("GTM container requires one usage context")
        if len(set(usage_contexts)) != len(usage_contexts):
            raise ValueError("GTM container usage contexts must not repeat")
        payload = await self._request_json(
            request,
            "POST",
            f"accounts/{account_id}/containers",
            {"name": name, "usageContext": [context.value for context in usage_contexts]},
        )
        return _gtm_container(payload)

    async def delete_container(
        self,
        request: ProviderReadRequest,
        gtm_account_id: str,
        container_id: str,
    ) -> None:
        await self._request_empty(
            request,
            "DELETE",
            _container_path(gtm_account_id, container_id),
        )

    async def list_workspaces(
        self,
        request: ProviderReadRequest,
        gtm_account_id: str,
        container_id: str,
    ) -> tuple[GtmWorkspace, ...]:
        payload = await self._request_json(
            request,
            "GET",
            f"{_container_path(gtm_account_id, container_id)}/workspaces",
        )
        return tuple(
            _gtm_workspace(item)
            for item in _response_items(payload, "workspace", "GTM workspace list")
        )

    async def create_workspace(
        self,
        request: ProviderReadRequest,
        gtm_account_id: str,
        container_id: str,
        name: str,
        description: str | None,
    ) -> GtmWorkspace:
        if not _TEXT_PATTERN.search(name) or len(name) > MAX_GTM_NAME_CHARS:
            raise ValueError("GTM workspace name is invalid")
        if description is not None and len(description) > MAX_GTM_NOTES_CHARS:
            raise ValueError("GTM workspace description is too long")
        payload = await self._request_json(
            request,
            "POST",
            f"{_container_path(gtm_account_id, container_id)}/workspaces",
            {"name": name, "description": description} if description else {"name": name},
        )
        return _gtm_workspace(payload)

    async def delete_workspace(
        self,
        request: ProviderReadRequest,
        gtm_account_id: str,
        container_id: str,
        workspace_id: str,
    ) -> None:
        await self._request_empty(
            request,
            "DELETE",
            _workspace_path(gtm_account_id, container_id, workspace_id),
        )

    async def list_entities(
        self,
        request: ProviderReadRequest,
        gtm_account_id: str,
        container_id: str,
        workspace_id: str,
        kind: GtmEntityKind,
    ) -> tuple[GtmEntity, ...]:
        payload = await self._request_json(
            request,
            "GET",
            f"{_workspace_path(gtm_account_id, container_id, workspace_id)}/{kind.value}s",
        )
        return tuple(
            _gtm_entity(kind, item)
            for item in _response_items(payload, kind.value, f"GTM {kind.value} list")
        )

    async def create_entity(
        self,
        request: ProviderReadRequest,
        gtm_account_id: str,
        container_id: str,
        workspace_id: str,
        kind: GtmEntityKind,
        definition: GtmEntityDefinition,
    ) -> GtmEntity:
        payload = await self._request_json(
            request,
            "POST",
            f"{_workspace_path(gtm_account_id, container_id, workspace_id)}/{kind.value}s",
            definition.as_payload(),
        )
        return _gtm_entity(kind, payload)

    async def update_entity(
        self,
        request: ProviderReadRequest,
        gtm_account_id: str,
        container_id: str,
        workspace_id: str,
        kind: GtmEntityKind,
        entity_id: str,
        definition: GtmEntityDefinition,
    ) -> GtmEntity:
        payload = await self._request_json(
            request,
            "PUT",
            _entity_path(gtm_account_id, container_id, workspace_id, kind, entity_id),
            definition.as_payload(),
        )
        return _gtm_entity(kind, payload)

    async def delete_entity(
        self,
        request: ProviderReadRequest,
        gtm_account_id: str,
        container_id: str,
        workspace_id: str,
        kind: GtmEntityKind,
        entity_id: str,
    ) -> None:
        await self._request_empty(
            request,
            "DELETE",
            _entity_path(gtm_account_id, container_id, workspace_id, kind, entity_id),
        )

    async def create_workspace_version(
        self,
        request: ProviderReadRequest,
        gtm_account_id: str,
        container_id: str,
        workspace_id: str,
        name: str,
        notes: str | None,
    ) -> GtmVersion:
        if not _TEXT_PATTERN.search(name) or len(name) > MAX_GTM_NAME_CHARS:
            raise ValueError("GTM version name is invalid")
        if notes is not None and len(notes) > MAX_GTM_NOTES_CHARS:
            raise ValueError("GTM version notes are too long")
        payload = await self._request_json(
            request,
            "POST",
            f"{_workspace_path(gtm_account_id, container_id, workspace_id)}:create_version",
            {"name": name, "notes": notes} if notes else {"name": name},
        )
        version_payload = payload.get("containerVersion")
        if not isinstance(version_payload, dict):
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "Google Tag Manager returned an invalid workspace version",
            )
        return _gtm_version(cast(dict[str, object], version_payload))

    async def publish_version(
        self,
        request: ProviderReadRequest,
        gtm_account_id: str,
        container_id: str,
        version_id: str,
    ) -> GtmVersion:
        version_path = _version_path(gtm_account_id, container_id, version_id)
        payload = await self._request_json(request, "POST", f"{version_path}:publish", {})
        version_payload = payload.get("containerVersion", payload)
        if not isinstance(version_payload, dict):
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "Google Tag Manager returned an invalid published version",
            )
        return _gtm_version(cast(dict[str, object], version_payload))

    async def _request_json(
        self,
        request: ProviderReadRequest,
        method: str,
        path: str,
        payload: dict[str, object] | None = None,
    ) -> dict[str, object]:
        token = await self._token(request)
        body = await self._request_body(request, method, path, token, payload)
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError as error:
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "Google Tag Manager returned invalid JSON",
            ) from error
        if not isinstance(parsed, dict):
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "Google Tag Manager returned an invalid response",
            )
        return cast(dict[str, object], parsed)

    async def _request_empty(
        self,
        request: ProviderReadRequest,
        method: str,
        path: str,
    ) -> None:
        token = await self._token(request)
        body = await self._request_body(request, method, path, token, None)
        if body:
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "Google Tag Manager returned an unexpected response",
            )

    async def _token(self, request: ProviderReadRequest) -> str:
        account = self._policy.require_google_account(str(request.account_id))
        try:
            return await self._access_token_provider(account.credential)
        except ProviderOperationError:
            raise
        except Exception as error:
            raise ProviderOperationError(
                ProviderFailureCode.AUTHENTICATION,
                "Google Tag Manager authentication failed",
            ) from error

    async def _request_body(
        self,
        request: ProviderReadRequest,
        method: str,
        path: str,
        token: str,
        payload: dict[str, object] | None,
    ) -> bytes:
        try:
            async with (
                httpx.AsyncClient(
                    transport=self._transport_factory(),
                    trust_env=False,
                    follow_redirects=False,
                    timeout=httpx.Timeout(request.timeout_seconds),
                ) as client,
                client.stream(
                    method,
                    f"{_API_ROOT}/{path}",
                    headers={_AUTHORIZATION_HEADER: f"{_BEARER_PREFIX}{token}"},
                    json=payload,
                ) as response,
            ):
                _raise_for_status(response)
                return await _read_bounded_body(response)
        except ProviderOperationError:
            raise
        except httpx.TimeoutException as error:
            raise ProviderOperationError(
                ProviderFailureCode.TIMEOUT,
                "Google Tag Manager request timed out",
            ) from error
        except httpx.HTTPError as error:
            raise ProviderOperationError(
                ProviderFailureCode.UNAVAILABLE,
                "Google Tag Manager is unavailable",
            ) from error


def _parameter_count(parameter: GtmParameter, depth: int) -> int:
    if depth > MAX_GTM_PARAMETER_DEPTH:
        raise ValueError("GTM parameter nesting exceeds the allowed depth")
    return 1 + sum(
        _parameter_count(child, depth + 1)
        for child in (*parameter.list_items, *parameter.map_items)
    )


def _require_id(value: str, subject: str) -> str:
    if _ID_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{subject} must be numeric")
    return value


def _container_path(gtm_account_id: str, container_id: str) -> str:
    account = _require_id(gtm_account_id, "GTM account ID")
    container = _require_id(container_id, "GTM container ID")
    return f"accounts/{account}/containers/{container}"


def _workspace_path(gtm_account_id: str, container_id: str, workspace_id: str) -> str:
    workspace = _require_id(workspace_id, "GTM workspace ID")
    return f"{_container_path(gtm_account_id, container_id)}/workspaces/{workspace}"


def _entity_path(
    gtm_account_id: str,
    container_id: str,
    workspace_id: str,
    kind: GtmEntityKind,
    entity_id: str,
) -> str:
    entity = _require_id(entity_id, f"GTM {kind.value} ID")
    return f"{_workspace_path(gtm_account_id, container_id, workspace_id)}/{kind.value}s/{entity}"


def _version_path(gtm_account_id: str, container_id: str, version_id: str) -> str:
    version = _require_id(version_id, "GTM version ID")
    return f"{_container_path(gtm_account_id, container_id)}/versions/{version}"


def _response_items(payload: dict[str, object], field: str, subject: str) -> tuple[object, ...]:
    values = payload.get(field, [])
    if not isinstance(values, list):
        raise ProviderOperationError(
            ProviderFailureCode.INVALID_RESPONSE,
            f"Google Tag Manager returned an invalid {subject}",
        )
    items = cast(list[object], values)
    if len(items) > MAX_GTM_ENTITIES:
        raise ProviderOperationError(
            ProviderFailureCode.INVALID_RESPONSE,
            f"Google Tag Manager returned an invalid {subject}",
        )
    return tuple(items)


def _gtm_account(value: object) -> GtmAccount:
    try:
        response = _GtmAccountResponse.model_validate(value)
        return GtmAccount(
            _require_id(response.accountId, "GTM account ID"),
            _require_text(response.name, "GTM account name"),
            _require_path(response.path, "GTM account path"),
        )
    except (ValidationError, ValueError) as error:
        raise ProviderOperationError(
            ProviderFailureCode.INVALID_RESPONSE,
            "Google Tag Manager returned an invalid account",
        ) from error


def _gtm_container(value: object) -> GtmContainer:
    try:
        response = _GtmContainerResponse.model_validate(value)
        return GtmContainer(
            _require_id(response.accountId, "GTM account ID"),
            _require_id(response.containerId, "GTM container ID"),
            _require_text(response.name, "GTM container name"),
            _require_path(response.path, "GTM container path"),
            response.publicId,
        )
    except (ValidationError, ValueError) as error:
        raise ProviderOperationError(
            ProviderFailureCode.INVALID_RESPONSE,
            "Google Tag Manager returned an invalid container",
        ) from error


def _gtm_workspace(value: object) -> GtmWorkspace:
    try:
        response = _GtmWorkspaceResponse.model_validate(value)
        return GtmWorkspace(
            _require_id(response.accountId, "GTM account ID"),
            _require_id(response.containerId, "GTM container ID"),
            _require_id(response.workspaceId, "GTM workspace ID"),
            _require_text(response.name, "GTM workspace name"),
            _require_path(response.path, "GTM workspace path"),
        )
    except (ValidationError, ValueError) as error:
        raise ProviderOperationError(
            ProviderFailureCode.INVALID_RESPONSE,
            "Google Tag Manager returned an invalid workspace",
        ) from error


def _gtm_entity(kind: GtmEntityKind, value: object) -> GtmEntity:
    identifier_field = f"{kind.value}Id"
    try:
        response = _GtmEntityResponse.model_validate(value)
        if not isinstance(value, dict):
            raise ValueError("GTM entity response must be an object")
        identifier = cast(dict[str, object], value).get(identifier_field)
        if not isinstance(identifier, str):
            raise ValueError("GTM entity response is missing its ID")
        return GtmEntity(
            kind,
            _require_id(response.accountId, "GTM account ID"),
            _require_id(response.containerId, "GTM container ID"),
            _require_id(response.workspaceId, "GTM workspace ID"),
            _require_id(identifier, f"GTM {kind.value} ID"),
            _require_text(response.name, f"GTM {kind.value} name"),
            _require_text(response.type, f"GTM {kind.value} type"),
            _require_path(response.path, f"GTM {kind.value} path"),
        )
    except (ValidationError, ValueError) as error:
        raise ProviderOperationError(
            ProviderFailureCode.INVALID_RESPONSE,
            f"Google Tag Manager returned an invalid {kind.value}",
        ) from error


def _gtm_version(value: object) -> GtmVersion:
    try:
        response = _GtmVersionResponse.model_validate(value)
        return GtmVersion(
            _require_id(response.accountId, "GTM account ID"),
            _require_id(response.containerId, "GTM container ID"),
            _require_id(response.containerVersionId, "GTM version ID"),
            _require_text(response.name, "GTM version name"),
            _require_path(response.path, "GTM version path"),
        )
    except (ValidationError, ValueError) as error:
        raise ProviderOperationError(
            ProviderFailureCode.INVALID_RESPONSE,
            "Google Tag Manager returned an invalid version",
        ) from error


def _require_text(value: str, subject: str) -> str:
    if not _TEXT_PATTERN.search(value) or len(value) > MAX_GTM_NAME_CHARS:
        raise ValueError(f"{subject} is invalid")
    return value


def _require_path(value: str, subject: str) -> str:
    if not value.startswith("accounts/") or len(value) > MAX_GTM_NAME_CHARS:
        raise ValueError(f"{subject} is invalid")
    return value


def _raise_for_status(response: httpx.Response) -> None:
    failure_codes = {
        401: ProviderFailureCode.AUTHENTICATION,
        403: ProviderFailureCode.FORBIDDEN,
        429: ProviderFailureCode.RATE_LIMITED,
    }
    failure_code = failure_codes.get(response.status_code)
    if failure_code is not None:
        raise ProviderOperationError(failure_code, "Google Tag Manager request was rejected")
    if response.status_code >= 500:
        raise ProviderOperationError(
            ProviderFailureCode.UNAVAILABLE,
            "Google Tag Manager is unavailable",
        )
    if response.is_redirect or response.status_code >= 400:
        raise ProviderOperationError(
            ProviderFailureCode.INVALID_RESPONSE,
            "Google Tag Manager returned an unexpected response",
        )


async def _read_bounded_body(response: httpx.Response) -> bytes:
    content_length = response.headers.get("content-length")
    if (
        content_length is not None
        and content_length.isdigit()
        and int(content_length) > MAX_PROVIDER_RESPONSE_BYTES
    ):
        raise ProviderOperationError(
            ProviderFailureCode.INVALID_RESPONSE,
            "Google Tag Manager response exceeds the allowed size",
        )
    body = bytearray()
    async for chunk in response.aiter_bytes():
        body.extend(chunk)
        if len(body) > MAX_PROVIDER_RESPONSE_BYTES:
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "Google Tag Manager response exceeds the allowed size",
            )
    return bytes(body)
