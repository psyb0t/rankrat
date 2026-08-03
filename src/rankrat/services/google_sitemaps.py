"""Bounded Google Search Console sitemap mutations."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import StrEnum

from rankrat.constants import DEFAULT_PROVIDER_TIMEOUT_SECONDS
from rankrat.logging import log_event
from rankrat.policy.boundaries import BoundaryPolicy
from rankrat.providers.base import AccountId, ProviderReadRequest
from rankrat.providers.google_search_console import GoogleSearchConsoleClient

_LOGGER = logging.getLogger(__name__)


class GoogleSitemapOperation(StrEnum):
    """The two documented Search Console sitemap mutation operations."""

    SUBMIT = "submit"
    DELETE = "delete"


@dataclass(frozen=True, slots=True)
class GoogleSitemapSubmissionRequest:
    """One configured sitemap mutation for the fixed provider client."""

    account_id: str
    site_url: str
    sitemap_url: str
    operation: GoogleSitemapOperation

    timeout_seconds: float = DEFAULT_PROVIDER_TIMEOUT_SECONDS


@dataclass(frozen=True, slots=True)
class GoogleSitemapSubmissionResponse:
    """Safe mutation receipt without replayable sitemap URLs or credentials."""

    account_id: str
    site_url: str
    operation: GoogleSitemapOperation


class GoogleSitemapService:
    """Bind sitemap mutations to one configured property."""

    def __init__(
        self,
        policy: BoundaryPolicy,
        client: GoogleSearchConsoleClient,
    ) -> None:
        self._policy = policy
        self._client = client

    async def submit(
        self,
        request: GoogleSitemapSubmissionRequest,
    ) -> GoogleSitemapSubmissionResponse:
        """Run one boundary-limited fixed-origin mutation request."""

        sitemap_url = self._normalized_sitemap_url(request)
        provider_request = ProviderReadRequest(
            AccountId(request.account_id),
            request.timeout_seconds,
        )
        try:
            if request.operation is GoogleSitemapOperation.SUBMIT:
                await self._client.submit_sitemap(
                    provider_request,
                    request.site_url,
                    sitemap_url,
                )
            else:
                await self._client.delete_sitemap(
                    provider_request,
                    request.site_url,
                    sitemap_url,
                )
        except Exception:
            log_event(
                _LOGGER,
                logging.WARNING,
                "Google sitemap mutation failed",
                account_id=request.account_id,
                site_url=request.site_url,
                operation=request.operation.value,
            )
            raise
        log_event(
            _LOGGER,
            logging.INFO,
            "Google sitemap mutation accepted",
            account_id=request.account_id,
            site_url=request.site_url,
            operation=request.operation.value,
        )
        return GoogleSitemapSubmissionResponse(
            request.account_id,
            request.site_url,
            request.operation,
        )

    def _normalized_sitemap_url(self, request: GoogleSitemapSubmissionRequest) -> str:
        return self._policy.require_search_console_url(
            request.account_id,
            request.site_url,
            request.sitemap_url,
        )
