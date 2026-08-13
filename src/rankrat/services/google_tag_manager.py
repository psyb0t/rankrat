"""Application service for typed GTM management through configured OAuth."""

from __future__ import annotations

from dataclasses import dataclass

from rankrat.constants import DEFAULT_PROVIDER_TIMEOUT_SECONDS
from rankrat.providers.base import AccountId, ProviderReadRequest
from rankrat.providers.google_tag_manager import (
    GoogleTagManagerClient,
    GtmAccount,
    GtmContainer,
    GtmEntity,
    GtmEntityDefinition,
    GtmEntityKind,
    GtmUsageContext,
    GtmVersion,
    GtmWorkspace,
)


@dataclass(frozen=True, slots=True)
class GtmContainerRequest:
    account_id: str
    gtm_account_id: str
    timeout_seconds: float = DEFAULT_PROVIDER_TIMEOUT_SECONDS


@dataclass(frozen=True, slots=True)
class GtmContainerCreateRequest(GtmContainerRequest):
    name: str = ""
    usage_contexts: tuple[GtmUsageContext, ...] = ()


@dataclass(frozen=True, slots=True)
class GtmWorkspaceRequest:
    account_id: str
    gtm_account_id: str
    container_id: str
    timeout_seconds: float = DEFAULT_PROVIDER_TIMEOUT_SECONDS


@dataclass(frozen=True, slots=True)
class GtmWorkspaceCreateRequest(GtmWorkspaceRequest):
    name: str = ""
    description: str | None = None


@dataclass(frozen=True, slots=True)
class GtmEntityRequest(GtmWorkspaceRequest):
    workspace_id: str = ""
    kind: GtmEntityKind = GtmEntityKind.TAG


@dataclass(frozen=True, slots=True)
class GtmEntityCreateRequest(GtmEntityRequest):
    definition: GtmEntityDefinition | None = None


@dataclass(frozen=True, slots=True)
class GtmEntityUpdateRequest(GtmEntityCreateRequest):
    entity_id: str = ""


@dataclass(frozen=True, slots=True)
class GtmVersionCreateRequest(GtmWorkspaceRequest):
    workspace_id: str = ""
    name: str = ""
    notes: str | None = None


@dataclass(frozen=True, slots=True)
class GtmVersionPublishRequest(GtmWorkspaceRequest):
    version_id: str = ""


class GoogleTagManagerService:
    """Use the fixed GTM client while keeping transport inputs provider-neutral."""

    def __init__(self, client: GoogleTagManagerClient) -> None:
        self._client = client

    async def list_accounts(
        self, account_id: str, timeout_seconds: float
    ) -> tuple[GtmAccount, ...]:
        return await self._client.list_accounts(_provider_request(account_id, timeout_seconds))

    async def list_containers(self, request: GtmContainerRequest) -> tuple[GtmContainer, ...]:
        return await self._client.list_containers(
            _provider_request(request.account_id, request.timeout_seconds),
            request.gtm_account_id,
        )

    async def create_container(self, request: GtmContainerCreateRequest) -> GtmContainer:
        return await self._client.create_container(
            _provider_request(request.account_id, request.timeout_seconds),
            request.gtm_account_id,
            request.name,
            request.usage_contexts,
        )

    async def delete_container(self, request: GtmContainerRequest, container_id: str) -> None:
        await self._client.delete_container(
            _provider_request(request.account_id, request.timeout_seconds),
            request.gtm_account_id,
            container_id,
        )

    async def list_workspaces(self, request: GtmWorkspaceRequest) -> tuple[GtmWorkspace, ...]:
        return await self._client.list_workspaces(
            _provider_request(request.account_id, request.timeout_seconds),
            request.gtm_account_id,
            request.container_id,
        )

    async def create_workspace(self, request: GtmWorkspaceCreateRequest) -> GtmWorkspace:
        return await self._client.create_workspace(
            _provider_request(request.account_id, request.timeout_seconds),
            request.gtm_account_id,
            request.container_id,
            request.name,
            request.description,
        )

    async def delete_workspace(self, request: GtmWorkspaceRequest, workspace_id: str) -> None:
        await self._client.delete_workspace(
            _provider_request(request.account_id, request.timeout_seconds),
            request.gtm_account_id,
            request.container_id,
            workspace_id,
        )

    async def list_entities(self, request: GtmEntityRequest) -> tuple[GtmEntity, ...]:
        return await self._client.list_entities(
            _provider_request(request.account_id, request.timeout_seconds),
            request.gtm_account_id,
            request.container_id,
            request.workspace_id,
            request.kind,
        )

    async def create_entity(self, request: GtmEntityCreateRequest) -> GtmEntity:
        if request.definition is None:
            raise ValueError("GTM entity definition is required")
        return await self._client.create_entity(
            _provider_request(request.account_id, request.timeout_seconds),
            request.gtm_account_id,
            request.container_id,
            request.workspace_id,
            request.kind,
            request.definition,
        )

    async def update_entity(self, request: GtmEntityUpdateRequest) -> GtmEntity:
        if request.definition is None:
            raise ValueError("GTM entity definition is required")
        return await self._client.update_entity(
            _provider_request(request.account_id, request.timeout_seconds),
            request.gtm_account_id,
            request.container_id,
            request.workspace_id,
            request.kind,
            request.entity_id,
            request.definition,
        )

    async def delete_entity(self, request: GtmEntityRequest, entity_id: str) -> None:
        await self._client.delete_entity(
            _provider_request(request.account_id, request.timeout_seconds),
            request.gtm_account_id,
            request.container_id,
            request.workspace_id,
            request.kind,
            entity_id,
        )

    async def create_version(self, request: GtmVersionCreateRequest) -> GtmVersion:
        return await self._client.create_workspace_version(
            _provider_request(request.account_id, request.timeout_seconds),
            request.gtm_account_id,
            request.container_id,
            request.workspace_id,
            request.name,
            request.notes,
        )

    async def publish_version(self, request: GtmVersionPublishRequest) -> GtmVersion:
        return await self._client.publish_version(
            _provider_request(request.account_id, request.timeout_seconds),
            request.gtm_account_id,
            request.container_id,
            request.version_id,
        )


def _provider_request(account_id: str, timeout_seconds: float) -> ProviderReadRequest:
    return ProviderReadRequest(AccountId(account_id), timeout_seconds)
