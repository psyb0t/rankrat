from __future__ import annotations

from typing import cast

import pytest

from rankrat.errors import ApprovalDeniedError
from rankrat.operator.site_onboarding import (
    SiteOnboardingOperator,
    SiteOnboardingReceipt,
    SiteOnboardingRequest,
)
from rankrat.policy.approvals import WriteApprovalStore
from rankrat.services.site_onboarding import (
    SiteOnboardingApprovalRequest,
    SiteOnboardingService,
    SiteOnboardingSubmissionRequest,
)


class _Operator:
    def __init__(self) -> None:
        self.validated: list[SiteOnboardingRequest] = []
        self.onboarded: list[SiteOnboardingRequest] = []

    def validate_request(self, request: SiteOnboardingRequest) -> str:
        self.validated.append(request)
        return "123"

    async def onboard(self, request: SiteOnboardingRequest) -> SiteOnboardingReceipt:
        self.onboarded.append(request)
        return SiteOnboardingReceipt(
            site_url=request.site_url,
            ga4_property_id="456",
            ga4_measurement_id="G-ABC123",
            google_search_console_added=True,
            bing_added=True,
            boundary_updated=True,
        )


def _approval_request() -> SiteOnboardingApprovalRequest:
    return SiteOnboardingApprovalRequest(
        google_account_id="google-main",
        bing_account_id="bing-main",
        site_url="https://new.example.com",
        display_name="New Example",
    )


@pytest.mark.asyncio
async def test_site_onboarding_binds_each_approval_to_every_provider_write_parameter() -> None:
    operator = _Operator()
    service = SiteOnboardingService(
        cast(SiteOnboardingOperator, operator),
        WriteApprovalStore(token_factory=lambda _: "approval-1"),
    )
    approval = await service.approve(_approval_request())

    with pytest.raises(ApprovalDeniedError):
        await service.submit(
            SiteOnboardingSubmissionRequest(
                google_account_id="google-main",
                bing_account_id="bing-main",
                site_url="https://new.example.com",
                display_name="New Example",
                currency_code="EUR",
                approval_id=approval.approval_id,
            )
        )
    assert operator.onboarded == []

    approval = await service.approve(_approval_request())
    receipt = await service.submit(
        SiteOnboardingSubmissionRequest(
            google_account_id="google-main",
            bing_account_id="bing-main",
            site_url="https://new.example.com/",
            display_name="New Example",
            approval_id=approval.approval_id,
        )
    )
    assert receipt.ga4_property_id == "456"
    assert [request.site_url for request in operator.onboarded] == ["https://new.example.com/"]
    with pytest.raises(ApprovalDeniedError):
        await service.submit(
            SiteOnboardingSubmissionRequest(
                google_account_id="google-main",
                bing_account_id="bing-main",
                site_url="https://new.example.com/",
                display_name="New Example",
                approval_id=approval.approval_id,
            )
        )
