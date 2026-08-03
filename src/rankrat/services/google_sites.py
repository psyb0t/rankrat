"""Bounded Google Search Console property mutations."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import StrEnum

from rankrat.constants import DEFAULT_PROVIDER_TIMEOUT_SECONDS
from rankrat.logging import log_event
from rankrat.models.boundaries import ResourceKind
from rankrat.policy.boundaries import BoundaryPolicy
from rankrat.providers.base import AccountId, ProviderReadRequest
from rankrat.providers.google_search_console import GoogleSearchConsoleClient

_LOGGER = logging.getLogger(__name__)


class GoogleSiteOperation(StrEnum):
    """The documented Search Console property mutation operations."""

    ADD = "add"
    DELETE = "delete"


@dataclass(frozen=True, slots=True)
class GoogleSiteSubmissionRequest:
    """One configured property mutation for the fixed provider client."""

    account_id: str
    site_url: str
    operation: GoogleSiteOperation

    timeout_seconds: float = DEFAULT_PROVIDER_TIMEOUT_SECONDS


@dataclass(frozen=True, slots=True)
class GoogleSiteSubmissionResponse:
    """Safe receipt of one accepted Google Search Console property mutation."""

    account_id: str
    site_url: str
    operation: GoogleSiteOperation


class GoogleSiteService:
    """Bind each property mutation to an exact configured resource."""

    def __init__(
        self,
        policy: BoundaryPolicy,
        client: GoogleSearchConsoleClient,
    ) -> None:
        self._policy = policy
        self._client = client

    async def submit(
        self,
        request: GoogleSiteSubmissionRequest,
    ) -> GoogleSiteSubmissionResponse:
        """Run one boundary-limited fixed-origin mutation request."""

        self._authorize_site(request)
        provider_request = ProviderReadRequest(
            AccountId(request.account_id),
            request.timeout_seconds,
        )
        try:
            if request.operation is GoogleSiteOperation.ADD:
                await self._client.add_site(provider_request, request.site_url)
            else:
                await self._client.delete_site(provider_request, request.site_url)
        except Exception:
            # Provider errors are already redacted; audit only bounded identifiers.
            log_event(
                _LOGGER,
                logging.WARNING,
                "Google Search Console property mutation failed",
                account_id=request.account_id,
                site_url=request.site_url,
                operation=request.operation.value,
            )
            raise
        log_event(
            _LOGGER,
            logging.INFO,
            "Google Search Console property mutation accepted",
            account_id=request.account_id,
            site_url=request.site_url,
            operation=request.operation.value,
        )
        return GoogleSiteSubmissionResponse(
            request.account_id,
            request.site_url,
            request.operation,
        )

    def _authorize_site(self, request: GoogleSiteSubmissionRequest) -> None:
        self._policy.require_resource(
            request.account_id,
            self._client.provider,
            ResourceKind.SEARCH_CONSOLE_SITE,
            request.site_url,
        )
