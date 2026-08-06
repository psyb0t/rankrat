"""Boundary-authorized local Lighthouse audits and category finding reports."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from rankrat.constants import (
    DEFAULT_LIGHTHOUSE_TIMEOUT_SECONDS,
    MAX_LIGHTHOUSE_TIMEOUT_SECONDS,
    MIN_LIGHTHOUSE_TIMEOUT_SECONDS,
)
from rankrat.errors import BoundaryDeniedError
from rankrat.policy.boundaries import BoundaryPolicy
from rankrat.providers.base import ProviderFailureCode, ProviderOperationError
from rankrat.providers.lighthouse import (
    LighthouseAuditResult,
    LighthouseCategoryScore,
    LighthouseFinding,
    LighthouseWorkerClient,
)


class LighthouseCategory(StrEnum):
    PERFORMANCE = "performance"
    ACCESSIBILITY = "accessibility"
    BEST_PRACTICES = "best-practices"
    SEO = "seo"


_ALL_CATEGORIES = tuple(LighthouseCategory)


@dataclass(frozen=True, slots=True)
class LighthouseAuditRequest:
    account_id: str
    site_url: str
    page_url: str
    timeout_seconds: float = DEFAULT_LIGHTHOUSE_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        if (
            not MIN_LIGHTHOUSE_TIMEOUT_SECONDS
            <= self.timeout_seconds
            <= (MAX_LIGHTHOUSE_TIMEOUT_SECONDS)
        ):
            raise ValueError("Lighthouse timeout is outside the allowed range")


@dataclass(frozen=True, slots=True)
class LighthouseAuditReport:
    requested_url: str
    final_url: str
    fetch_time: str
    lighthouse_version: str
    categories: tuple[LighthouseCategoryScore, ...]
    findings: tuple[LighthouseFinding, ...]


class LighthouseService:
    def __init__(
        self,
        policy: BoundaryPolicy,
        client: LighthouseWorkerClient,
    ) -> None:
        self._policy = policy
        self._client = client

    async def audit(self, request: LighthouseAuditRequest) -> LighthouseAuditReport:
        return await self._run(request, _ALL_CATEGORIES)

    async def findings(
        self,
        request: LighthouseAuditRequest,
        category: LighthouseCategory,
    ) -> LighthouseAuditReport:
        return await self._run(request, (category,))

    async def _run(
        self,
        request: LighthouseAuditRequest,
        categories: tuple[LighthouseCategory, ...],
    ) -> LighthouseAuditReport:
        normalized_url = self._policy.require_pagespeed_url(
            request.account_id,
            request.site_url,
            request.page_url,
        )
        result = await self._client.audit(
            normalized_url,
            tuple(category.value for category in categories),
            request.timeout_seconds,
        )
        _validate_result(self._policy, request, normalized_url, categories, result)
        return _audit_report(result)


def _validate_result(
    policy: BoundaryPolicy,
    request: LighthouseAuditRequest,
    normalized_url: str,
    categories: tuple[LighthouseCategory, ...],
    result: LighthouseAuditResult,
) -> None:
    expected_categories = {category.value for category in categories}
    returned_categories = {category.category for category in result.categories}
    try:
        returned_requested_url = policy.require_pagespeed_url(
            request.account_id,
            request.site_url,
            result.requested_url,
        )
        policy.require_pagespeed_url(
            request.account_id,
            request.site_url,
            result.final_url,
        )
    except (BoundaryDeniedError, ValueError) as error:
        raise ProviderOperationError(
            ProviderFailureCode.INVALID_RESPONSE,
            "Lighthouse worker returned an out-of-bound URL",
        ) from error
    if returned_requested_url != normalized_url or returned_categories != expected_categories:
        raise ProviderOperationError(
            ProviderFailureCode.INVALID_RESPONSE,
            "Lighthouse worker returned an inconsistent report",
        )


def _audit_report(result: LighthouseAuditResult) -> LighthouseAuditReport:
    return LighthouseAuditReport(
        requested_url=result.requested_url,
        final_url=result.final_url,
        fetch_time=result.fetch_time,
        lighthouse_version=result.lighthouse_version,
        categories=result.categories,
        findings=result.findings,
    )
