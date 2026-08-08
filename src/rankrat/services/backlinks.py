"""Provider-neutral backlink reports and cross-source deduplication."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass

from rankrat.constants import (
    DEFAULT_PROVIDER_TIMEOUT_SECONDS,
    MAX_BACKLINK_OFFSET,
    MAX_BACKLINK_RESULTS,
    MAX_BACKLINK_TARGETS,
)
from rankrat.errors import BoundaryDeniedError, InputLimitError
from rankrat.models.boundaries import BACKLINK_PROVIDERS, Provider
from rankrat.providers.backlinks import (
    BacklinkClient,
    BacklinkRecord,
    BacklinkRequestBudget,
    BacklinkResult,
)
from rankrat.providers.base import (
    AccountId,
    ProviderFailureCode,
    ProviderOperationError,
    ProviderReadRequest,
)


@dataclass(frozen=True, slots=True)
class BacklinkReadRequest:
    account_id: str
    provider: Provider
    target: str
    site_url: str | None = None
    limit: int = 100
    offset: int = 0
    timeout_seconds: float = DEFAULT_PROVIDER_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        if self.provider not in BACKLINK_PROVIDERS | {Provider.BING}:
            raise InputLimitError("provider does not implement the backlink adapter contract")
        if self.provider is Provider.BING and self.site_url is None:
            raise InputLimitError("Bing backlink reads require site_url")
        if self.provider is not Provider.BING and self.site_url is not None:
            raise InputLimitError("site_url is only valid for Bing backlink reads")
        if not 1 <= self.limit <= MAX_BACKLINK_RESULTS:
            raise InputLimitError("backlink result limit is outside the allowed range")
        if not 0 <= self.offset <= MAX_BACKLINK_OFFSET:
            raise InputLimitError("backlink offset is outside the allowed range")


@dataclass(frozen=True, slots=True)
class BacklinkAggregateSource:
    account_id: str
    provider: Provider
    target: str
    site_url: str | None = None


@dataclass(frozen=True, slots=True)
class BacklinkAggregateRequest:
    sources: tuple[BacklinkAggregateSource, ...]
    limit_per_source: int = 100
    timeout_seconds: float = DEFAULT_PROVIDER_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        if not self.sources or len(self.sources) > MAX_BACKLINK_TARGETS:
            raise InputLimitError("backlink source count is outside the allowed range")
        if not 1 <= self.limit_per_source <= MAX_BACKLINK_RESULTS:
            raise InputLimitError("backlink source limit is outside the allowed range")
        identities = {
            (source.account_id, source.provider, source.target, source.site_url)
            for source in self.sources
        }
        if len(identities) != len(self.sources):
            raise InputLimitError("backlink aggregate sources must be unique")


@dataclass(frozen=True, slots=True)
class BacklinkSourceFailure:
    provider: Provider
    account_id: str
    code: ProviderFailureCode


@dataclass(frozen=True, slots=True)
class BacklinkAggregateReport:
    links: tuple[BacklinkRecord, ...]
    referring_domains: tuple[str, ...]
    successful_sources: tuple[Provider, ...]
    failures: tuple[BacklinkSourceFailure, ...]


class BacklinkService:
    def __init__(self, clients: Mapping[Provider, BacklinkClient]) -> None:
        self._clients = dict(clients)

    async def read(self, request: BacklinkReadRequest) -> BacklinkResult:
        try:
            async with asyncio.timeout(request.timeout_seconds):
                return await self._read(request, BacklinkRequestBudget())
        except TimeoutError as error:
            raise ProviderOperationError(
                ProviderFailureCode.TIMEOUT,
                "backlink operation timed out",
            ) from error

    async def _read(
        self,
        request: BacklinkReadRequest,
        request_budget: BacklinkRequestBudget,
    ) -> BacklinkResult:
        client = self._clients.get(request.provider)
        if client is None:
            raise BoundaryDeniedError("backlink provider adapter is unavailable")
        return await client.links(
            ProviderReadRequest(AccountId(request.account_id), request.timeout_seconds),
            request.target,
            request.limit,
            request.offset,
            request.site_url,
            request_budget=request_budget,
        )

    async def aggregate(self, request: BacklinkAggregateRequest) -> BacklinkAggregateReport:
        try:
            async with asyncio.timeout(request.timeout_seconds):
                return await self._aggregate(request)
        except TimeoutError as error:
            raise ProviderOperationError(
                ProviderFailureCode.TIMEOUT,
                "backlink aggregate operation timed out",
            ) from error

    async def _aggregate(
        self,
        request: BacklinkAggregateRequest,
    ) -> BacklinkAggregateReport:
        links_by_identity: dict[tuple[str, str, str], BacklinkRecord] = {}
        successful: list[Provider] = []
        failures: list[BacklinkSourceFailure] = []
        request_budget = BacklinkRequestBudget()
        for source in request.sources:
            try:
                result = await self._read(
                    BacklinkReadRequest(
                        source.account_id,
                        source.provider,
                        source.target,
                        source.site_url,
                        request.limit_per_source,
                        timeout_seconds=request.timeout_seconds,
                    ),
                    request_budget,
                )
            except ProviderOperationError as error:
                failures.append(
                    BacklinkSourceFailure(source.provider, source.account_id, error.code)
                )
                continue
            successful.append(source.provider)
            for link in result.links:
                identity = (link.source_url, link.target_url, link.anchor)
                links_by_identity.setdefault(identity, link)
        if not successful and failures:
            raise ProviderOperationError(
                ProviderFailureCode.UNAVAILABLE,
                "all backlink sources failed",
            )
        links = tuple(
            sorted(
                links_by_identity.values(),
                key=lambda item: (
                    item.source_domain,
                    item.source_url,
                    item.target_url,
                    item.anchor,
                ),
            )
        )
        return BacklinkAggregateReport(
            links,
            tuple(sorted({link.source_domain for link in links})),
            tuple(successful),
            tuple(failures),
        )
