"""Application service for bounded Microsoft Clarity live-insights reports."""

from __future__ import annotations

from dataclasses import dataclass

from rankrat.constants import (
    DEFAULT_PROVIDER_TIMEOUT_SECONDS,
    MAX_CLARITY_DATE_RANGE_DAYS,
    MAX_CLARITY_DIMENSIONS,
)
from rankrat.errors import InputLimitError
from rankrat.providers.base import AccountId, ProviderReadRequest
from rankrat.providers.clarity import ClarityClient, ClarityDimension, ClarityMetric


@dataclass(frozen=True, slots=True)
class ClarityInsightsRequest:
    """One bounded live-insights report from an explicit Clarity project token."""

    account_id: str
    num_days: int = 1
    dimensions: tuple[ClarityDimension, ...] = ()
    timeout_seconds: float = DEFAULT_PROVIDER_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        if self.num_days < 1 or self.num_days > MAX_CLARITY_DATE_RANGE_DAYS:
            raise InputLimitError("Clarity num_days is outside the documented range")
        if len(self.dimensions) > MAX_CLARITY_DIMENSIONS:
            raise InputLimitError("Clarity dimension count exceeds the documented limit")
        if len(set(self.dimensions)) != len(self.dimensions):
            raise InputLimitError("Clarity dimensions must not repeat")


@dataclass(frozen=True, slots=True)
class ClarityInsightsReport:
    """Live Insights data returned in Microsoft Clarity's UTC reporting window."""

    num_days: int
    dimensions: tuple[ClarityDimension, ...]
    metrics: tuple[ClarityMetric, ...]


class ClarityService:
    """Map one typed request onto the fixed Microsoft Clarity provider client."""

    def __init__(self, client: ClarityClient) -> None:
        self._client = client

    async def live_insights(self, request: ClarityInsightsRequest) -> ClarityInsightsReport:
        """Return the documented 1-3 day Microsoft Clarity insight interval."""

        metrics = await self._client.live_insights(
            ProviderReadRequest(
                AccountId(request.account_id),
                request.timeout_seconds,
            ),
            request.num_days,
            request.dimensions,
        )
        return ClarityInsightsReport(request.num_days, request.dimensions, metrics)
