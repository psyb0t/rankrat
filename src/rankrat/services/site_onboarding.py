"""Boundary-limited creation of a newly launched website across supported providers."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from rankrat.constants import DEFAULT_PROVIDER_TIMEOUT_SECONDS
from rankrat.errors import RankratError
from rankrat.logging import log_event
from rankrat.operator.site_onboarding import (
    SiteOnboardingOperator,
    SiteOnboardingReceipt,
    SiteOnboardingRequest,
)
from rankrat.providers.base import ProviderOperationError

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SiteOnboardingSubmissionRequest:
    """One configured website onboarding request ready for provider writes."""

    google_account_id: str | None
    bing_account_id: str | None
    site_url: str
    google_analytics_parent_account_id: str | None = None
    display_name: str | None = None
    time_zone: str = "Etc/UTC"
    currency_code: str = "USD"

    timeout_seconds: float = DEFAULT_PROVIDER_TIMEOUT_SECONDS


class SiteOnboardingService:
    """Bind one multi-provider site onboarding write to configured boundaries."""

    def __init__(
        self,
        operator: SiteOnboardingOperator,
    ) -> None:
        self._operator = operator

    async def submit(self, request: SiteOnboardingSubmissionRequest) -> SiteOnboardingReceipt:
        """Create remote provider resources within configured account boundaries."""

        operator_request = self._operator_request(request)
        try:
            receipt = await self._operator.onboard(operator_request)
        except (ProviderOperationError, RankratError):
            log_event(
                _LOGGER,
                logging.WARNING,
                "Site onboarding mutation failed",
                google_account_id=operator_request.google_account_id or "automatic",
                bing_account_id=operator_request.bing_account_id or "automatic",
                site_url=operator_request.site_url,
            )
            raise
        log_event(
            _LOGGER,
            logging.INFO,
            "Site onboarding mutation accepted",
            google_account_id=receipt.google_account_id,
            bing_account_id=receipt.bing_account_id,
            site_url=operator_request.site_url,
        )
        return receipt

    @staticmethod
    def _operator_request(
        request: SiteOnboardingSubmissionRequest,
    ) -> SiteOnboardingRequest:
        return SiteOnboardingRequest(
            google_account_id=request.google_account_id,
            bing_account_id=request.bing_account_id,
            site_url=request.site_url,
            google_analytics_parent_account_id=request.google_analytics_parent_account_id,
            display_name=request.display_name,
            time_zone=request.time_zone,
            currency_code=request.currency_code,
            timeout_seconds=request.timeout_seconds,
        )
