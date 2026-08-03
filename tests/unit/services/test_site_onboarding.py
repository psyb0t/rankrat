from __future__ import annotations

from typing import cast

import pytest

from rankrat.operator.site_onboarding import (
    SiteOnboardingOperator,
    SiteOnboardingReceipt,
    SiteOnboardingRequest,
)
from rankrat.services.site_onboarding import (
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


@pytest.mark.asyncio
async def test_site_onboarding_validates_before_each_direct_provider_write() -> None:
    operator = _Operator()
    service = SiteOnboardingService(cast(SiteOnboardingOperator, operator))

    receipt = await service.submit(
        SiteOnboardingSubmissionRequest(
            google_account_id="google-main",
            bing_account_id="bing-main",
            site_url="https://new.example.com/",
            display_name="New Example",
        )
    )

    assert receipt.ga4_property_id == "456"
    assert [request.site_url for request in operator.validated] == ["https://new.example.com/"]
    assert [request.site_url for request in operator.onboarded] == ["https://new.example.com/"]
