"""Read-only provider readiness checks through configured client boundaries."""

from __future__ import annotations

from dataclasses import dataclass

from rankrat.constants import DEFAULT_PROVIDER_TIMEOUT_SECONDS
from rankrat.models.boundaries import Provider
from rankrat.policy.boundaries import BoundaryPolicy
from rankrat.providers.base import (
    AccountId,
    ProviderClient,
    ProviderReadiness,
    ProviderReadRequest,
)

_CLIENT_UNAVAILABLE_DETAIL = "configured provider client is unavailable"


@dataclass(frozen=True, slots=True)
class ProviderReadinessRequest:
    """Select one exact configured account for a bounded read-only check."""

    account_id: str
    timeout_seconds: float = DEFAULT_PROVIDER_TIMEOUT_SECONDS


class ProviderReadinessService:
    """Dispatch readiness only to a client fixed to the account's provider."""

    def __init__(
        self,
        policy: BoundaryPolicy,
        clients: dict[Provider, ProviderClient],
    ) -> None:
        self._policy = policy
        self._clients = clients

    async def readiness(self, request: ProviderReadinessRequest) -> ProviderReadiness:
        """Check one configured account without provider or origin overrides."""
        account = self._policy.resolve_account(request.account_id)
        client = self._clients.get(account.provider)
        if client is None:
            return ProviderReadiness(
                account_id=AccountId(account.id),
                provider=account.provider,
                available=False,
                detail=_CLIENT_UNAVAILABLE_DETAIL,
            )
        return await client.readiness(
            ProviderReadRequest(
                account_id=AccountId(account.id),
                timeout_seconds=request.timeout_seconds,
            )
        )
