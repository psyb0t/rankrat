"""Read-only configured capability summaries."""

from __future__ import annotations

from dataclasses import dataclass

from rankrat.config import Settings
from rankrat.models.boundaries import Provider
from rankrat.policy.boundaries import BoundaryPolicy

_SERVER_NAME = "rankrat"


@dataclass(frozen=True, slots=True)
class ServerInfoRequest:
    """Input for the parameter-free server information operation."""


@dataclass(frozen=True, slots=True)
class ProviderCapability:
    """Non-sensitive provider capability derived solely from boundaries."""

    provider: Provider
    configured_account_count: int


@dataclass(frozen=True, slots=True)
class ServerInfoResponse:
    """Read-only server metadata safe for REST and MCP responses."""

    name: str
    version: str
    read_only: bool
    unbounded: bool
    http_bearer_auth_configured: bool
    providers: tuple[ProviderCapability, ...]


class CapabilityService:
    """Returns only the deployment's enabled-provider metadata."""

    def __init__(
        self,
        settings: Settings,
        policy: BoundaryPolicy,
        version: str,
    ) -> None:
        self._settings = settings
        self._policy = policy
        self._version = version

    def server_info(self, request: ServerInfoRequest) -> ServerInfoResponse:
        """Summarize immutable configuration without reading credentials."""
        del request
        accounts = self._policy.accounts()
        capabilities = tuple(
            ProviderCapability(
                provider=provider,
                configured_account_count=sum(account.provider == provider for account in accounts),
            )
            for provider in Provider
            if any(account.provider == provider for account in accounts)
        )
        return ServerInfoResponse(
            name=_SERVER_NAME,
            version=self._version,
            read_only=self._settings.read_only,
            unbounded=self._settings.unbounded,
            http_bearer_auth_configured=(self._settings.http_bearer_secret_file is not None),
            providers=capabilities,
        )
