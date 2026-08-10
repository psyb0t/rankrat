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
        self.onboarded: list[SiteOnboardingRequest] = []

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
async def test_site_onboarding_delegates_one_typed_request_to_the_operator() -> None:
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
    assert [request.site_url for request in operator.onboarded] == ["https://new.example.com/"]
