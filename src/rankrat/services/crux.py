"""Bounded Chrome UX Report history service."""

from __future__ import annotations

from dataclasses import dataclass

from rankrat.constants import (
    DEFAULT_PROVIDER_TIMEOUT_SECONDS,
    MAX_CRUX_HISTORY_PERIODS,
    MAX_CRUX_METRICS,
)
from rankrat.errors import InputLimitError
from rankrat.providers.base import AccountId, ProviderReadRequest
from rankrat.providers.crux import (
    CruxFormFactor,
    CruxHistoryClient,
    CruxHistoryRecord,
    CruxMetric,
)


@dataclass(frozen=True, slots=True)
class CruxHistoryRequest:
    account_id: str
    site_url: str
    target: str
    target_kind: str = "url"
    form_factor: CruxFormFactor = CruxFormFactor.ALL
    metrics: tuple[CruxMetric, ...] = tuple(CruxMetric)
    collection_period_count: int = 25
    timeout_seconds: float = DEFAULT_PROVIDER_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        if self.target_kind not in {"url", "origin"}:
            raise InputLimitError("CrUX target kind is unsupported")
        if not self.metrics or len(self.metrics) > MAX_CRUX_METRICS:
            raise InputLimitError("CrUX metric count is outside the allowed range")
        if len(set(self.metrics)) != len(self.metrics):
            raise InputLimitError("CrUX metrics must not repeat")
        if not 1 <= self.collection_period_count <= MAX_CRUX_HISTORY_PERIODS:
            raise InputLimitError("CrUX collection period count is outside the allowed range")


class CruxHistoryService:
    def __init__(self, client: CruxHistoryClient) -> None:
        self._client = client

    async def history(self, request: CruxHistoryRequest) -> CruxHistoryRecord:
        return await self._client.query(
            ProviderReadRequest(AccountId(request.account_id), request.timeout_seconds),
            request.site_url,
            request.target,
            request.target_kind,
            request.form_factor,
            request.metrics,
            request.collection_period_count,
        )
