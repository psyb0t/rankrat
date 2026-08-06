"""Transport-neutral site ownership verification service."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from rankrat.constants import DEFAULT_PROVIDER_TIMEOUT_SECONDS
from rankrat.errors import RankratError
from rankrat.logging import log_event
from rankrat.operator.site_ownership import (
    SiteOwnershipOperator,
    SiteOwnershipReceipt,
    SiteOwnershipRequest,
)
from rankrat.providers.base import ProviderOperationError

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SiteOwnershipSubmissionRequest:
    """One exact set of provider accounts and an HTTPS site root."""

    google_account_id: str
    bing_account_id: str
    cloudflare_account_id: str
    site_url: str
    timeout_seconds: float = DEFAULT_PROVIDER_TIMEOUT_SECONDS


class SiteOwnershipService:
    """Expose secret-free ownership status and narrowly scoped DNS writes."""

    def __init__(self, operator: SiteOwnershipOperator) -> None:
        self._operator = operator

    async def status(self, request: SiteOwnershipSubmissionRequest) -> SiteOwnershipReceipt:
        """Read ownership status without changing provider state."""

        operator_request = self._operator_request(request)
        return await self._operator.status(operator_request)

    async def apply(self, request: SiteOwnershipSubmissionRequest) -> SiteOwnershipReceipt:
        """Materialize and redeem DNS verification records."""

        operator_request = self._operator_request(request)
        try:
            receipt = await self._operator.apply(operator_request)
        except (ProviderOperationError, RankratError):
            log_event(
                _LOGGER,
                logging.WARNING,
                "Site ownership verification failed",
                google_account_id=request.google_account_id,
                bing_account_id=request.bing_account_id,
                cloudflare_account_id=request.cloudflare_account_id,
                site_url=request.site_url,
            )
            raise
        log_event(
            _LOGGER,
            logging.INFO,
            "Site ownership verification checked",
            google_account_id=request.google_account_id,
            bing_account_id=request.bing_account_id,
            cloudflare_account_id=request.cloudflare_account_id,
            site_url=request.site_url,
            complete=receipt.complete,
        )
        return receipt

    @staticmethod
    def _operator_request(request: SiteOwnershipSubmissionRequest) -> SiteOwnershipRequest:
        return SiteOwnershipRequest(
            google_account_id=request.google_account_id,
            bing_account_id=request.bing_account_id,
            cloudflare_account_id=request.cloudflare_account_id,
            site_url=request.site_url,
            timeout_seconds=request.timeout_seconds,
        )
