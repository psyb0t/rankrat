"""Approval-gated creation of a newly launched website across supported providers."""

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
from rankrat.policy.approvals import WriteApproval, WriteApprovalRequest, WriteApprovalStore
from rankrat.providers.base import ProviderOperationError

_LOGGER = logging.getLogger(__name__)
_SITE_ONBOARDING_OPERATION = "site_onboarding"


@dataclass(frozen=True, slots=True)
class SiteOnboardingApprovalRequest:
    """One exact website onboarding request an administrator can approve once."""

    google_account_id: str
    bing_account_id: str
    site_url: str
    display_name: str | None = None
    time_zone: str = "Etc/UTC"
    currency_code: str = "USD"


@dataclass(frozen=True, slots=True)
class SiteOnboardingSubmissionRequest(SiteOnboardingApprovalRequest):
    """One approved website onboarding request ready for provider writes."""

    approval_id: str = ""
    timeout_seconds: float = DEFAULT_PROVIDER_TIMEOUT_SECONDS


class SiteOnboardingService:
    """Bind one multi-provider site onboarding write to an exact single-use approval."""

    def __init__(
        self,
        operator: SiteOnboardingOperator,
        approvals: WriteApprovalStore,
    ) -> None:
        self._operator = operator
        self._approvals = approvals

    async def approve(self, request: SiteOnboardingApprovalRequest) -> WriteApproval:
        """Mint one short-lived approval after configured-account validation."""

        operator_request = self._operator_request(request)
        self._operator.validate_request(operator_request)
        return await self._approvals.mint(self._approval_request(operator_request))

    async def submit(self, request: SiteOnboardingSubmissionRequest) -> SiteOnboardingReceipt:
        """Consume one exact approval before creating any remote provider resources."""

        operator_request = self._operator_request(request)
        self._operator.validate_request(operator_request)
        await self._approvals.consume(
            request.approval_id,
            self._approval_request(operator_request),
        )
        try:
            receipt = await self._operator.onboard(operator_request)
        except (ProviderOperationError, RankratError):
            log_event(
                _LOGGER,
                logging.WARNING,
                "Site onboarding mutation failed",
                google_account_id=operator_request.google_account_id,
                bing_account_id=operator_request.bing_account_id,
                site_url=operator_request.site_url,
            )
            raise
        log_event(
            _LOGGER,
            logging.INFO,
            "Site onboarding mutation accepted",
            google_account_id=operator_request.google_account_id,
            bing_account_id=operator_request.bing_account_id,
            site_url=operator_request.site_url,
        )
        return receipt

    @staticmethod
    def _operator_request(
        request: SiteOnboardingApprovalRequest,
    ) -> SiteOnboardingRequest:
        return SiteOnboardingRequest(
            google_account_id=request.google_account_id,
            bing_account_id=request.bing_account_id,
            site_url=request.site_url,
            display_name=request.display_name,
            time_zone=request.time_zone,
            currency_code=request.currency_code,
            timeout_seconds=(
                request.timeout_seconds
                if isinstance(request, SiteOnboardingSubmissionRequest)
                else DEFAULT_PROVIDER_TIMEOUT_SECONDS
            ),
        )

    @staticmethod
    def _approval_request(request: SiteOnboardingRequest) -> WriteApprovalRequest:
        display_name = request.display_name
        if display_name is None:
            raise RuntimeError("site onboarding request is missing a display name")
        return WriteApprovalRequest(
            operation=_SITE_ONBOARDING_OPERATION,
            account_id=request.google_account_id,
            resource=request.site_url,
            arguments={
                "bing_account_id": request.bing_account_id,
                "display_name": display_name,
                "time_zone": request.time_zone,
                "currency_code": request.currency_code,
            },
        )
