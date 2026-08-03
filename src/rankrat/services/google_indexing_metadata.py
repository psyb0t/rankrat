"""Bounded read-only Google Indexing notification metadata."""

from __future__ import annotations

from dataclasses import dataclass

from rankrat.constants import DEFAULT_PROVIDER_TIMEOUT_SECONDS
from rankrat.policy.boundaries import BoundaryPolicy
from rankrat.providers.google_indexing import GoogleIndexingClient, GoogleIndexingMetadata


@dataclass(frozen=True, slots=True)
class GoogleIndexingMetadataRequest:
    """One notification-receipt metadata read under an exact configured property."""

    account_id: str
    site_url: str
    url: str
    timeout_seconds: float = DEFAULT_PROVIDER_TIMEOUT_SECONDS


class GoogleIndexingMetadataService:
    """Read notification receipts without exposing a publishing operation."""

    def __init__(self, policy: BoundaryPolicy, client: GoogleIndexingClient) -> None:
        self._policy = policy
        self._client = client

    async def metadata(self, request: GoogleIndexingMetadataRequest) -> GoogleIndexingMetadata:
        """Return Google receipt metadata for one owned, normalized URL."""

        normalized_url = self._policy.require_google_search_console_read_url(
            request.account_id,
            request.site_url,
            request.url,
        )
        return await self._client.metadata(
            request.account_id,
            normalized_url,
            request.timeout_seconds,
        )
