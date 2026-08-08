from __future__ import annotations

import asyncio
from typing import cast

import pytest

from rankrat.constants import MAX_BACKLINK_OFFSET
from rankrat.errors import InputLimitError
from rankrat.models.boundaries import Provider
from rankrat.providers.backlinks import (
    BacklinkClient,
    BacklinkRecord,
    BacklinkRequestBudget,
    BacklinkResult,
)
from rankrat.providers.base import ProviderFailureCode, ProviderOperationError
from rankrat.services.backlinks import (
    BacklinkAggregateRequest,
    BacklinkAggregateSource,
    BacklinkReadRequest,
    BacklinkService,
)


class _BacklinkClientFake:
    def __init__(
        self,
        provider: Provider,
        result: BacklinkResult | ProviderOperationError,
    ) -> None:
        self.provider = provider
        self._result = result

    async def links(self, *_: object, **__: object) -> BacklinkResult:
        if isinstance(self._result, ProviderOperationError):
            raise self._result
        return self._result


class _BudgetBacklinkClientFake:
    provider = Provider.AHREFS

    async def links(self, *_: object, **kwargs: object) -> BacklinkResult:
        budget = cast(BacklinkRequestBudget, kwargs["request_budget"])
        budget.consume()
        return BacklinkResult(self.provider, "https://example.com/", (), False)


class _SlowBacklinkClientFake:
    provider = Provider.AHREFS

    async def links(self, *_: object, **__: object) -> BacklinkResult:
        await asyncio.sleep(1)
        return BacklinkResult(self.provider, "https://example.com/", (), False)


class _DoubleBudgetBacklinkClientFake:
    provider = Provider.AHREFS

    async def links(self, *_: object, **kwargs: object) -> BacklinkResult:
        budget = cast(BacklinkRequestBudget, kwargs["request_budget"])
        budget.consume()
        budget.consume()
        return BacklinkResult(self.provider, "https://example.com/", (), False)


def _link(anchor: str = "reference") -> BacklinkRecord:
    return BacklinkRecord(
        "https://source.example/page",
        "https://example.com/page",
        "source.example",
        anchor,
        True,
        20,
        None,
        None,
    )


@pytest.mark.asyncio
async def test_backlink_aggregate_deduplicates_and_keeps_partial_failures() -> None:
    link = _link()
    service = BacklinkService(
        {
            Provider.AHREFS: cast(
                BacklinkClient,
                _BacklinkClientFake(
                    Provider.AHREFS,
                    BacklinkResult(Provider.AHREFS, link.target_url, (link,), False),
                ),
            ),
            Provider.MOZ: cast(
                BacklinkClient,
                _BacklinkClientFake(
                    Provider.MOZ,
                    BacklinkResult(Provider.MOZ, link.target_url, (link,), False),
                ),
            ),
            Provider.SEMRUSH: cast(
                BacklinkClient,
                _BacklinkClientFake(
                    Provider.SEMRUSH,
                    ProviderOperationError(ProviderFailureCode.RATE_LIMITED, "limited"),
                ),
            ),
        }
    )
    report = await service.aggregate(
        BacklinkAggregateRequest(
            (
                BacklinkAggregateSource("ahrefs-main", Provider.AHREFS, link.target_url),
                BacklinkAggregateSource("moz-main", Provider.MOZ, link.target_url),
                BacklinkAggregateSource("semrush-main", Provider.SEMRUSH, link.target_url),
            )
        )
    )
    assert report.links == (link,)
    assert report.referring_domains == ("source.example",)
    assert report.successful_sources == (Provider.AHREFS, Provider.MOZ)
    assert report.failures[0].code is ProviderFailureCode.RATE_LIMITED


@pytest.mark.asyncio
async def test_backlink_aggregate_fails_when_every_source_fails() -> None:
    failure = ProviderOperationError(ProviderFailureCode.UNAVAILABLE, "unavailable")
    service = BacklinkService(
        {
            Provider.AHREFS: cast(
                BacklinkClient,
                _BacklinkClientFake(Provider.AHREFS, failure),
            )
        }
    )
    with pytest.raises(ProviderOperationError) as error:
        await service.aggregate(
            BacklinkAggregateRequest(
                (
                    BacklinkAggregateSource(
                        "ahrefs-main",
                        Provider.AHREFS,
                        "https://example.com/",
                    ),
                )
            )
        )
    assert error.value.code is ProviderFailureCode.UNAVAILABLE


def test_backlink_read_request_caps_paid_provider_pagination() -> None:
    BacklinkReadRequest(
        "ahrefs-main",
        Provider.AHREFS,
        "https://example.com/",
        offset=MAX_BACKLINK_OFFSET,
    )
    with pytest.raises(InputLimitError, match="offset"):
        BacklinkReadRequest(
            "ahrefs-main",
            Provider.AHREFS,
            "https://example.com/",
            offset=MAX_BACKLINK_OFFSET + 1,
        )


def test_backlink_aggregate_rejects_duplicate_sources() -> None:
    source = BacklinkAggregateSource(
        "ahrefs-main",
        Provider.AHREFS,
        "https://example.com/",
    )
    with pytest.raises(InputLimitError, match="unique"):
        BacklinkAggregateRequest((source, source))


@pytest.mark.asyncio
async def test_backlink_aggregate_shares_one_provider_request_budget() -> None:
    source = BacklinkAggregateSource(
        "ahrefs-main",
        Provider.AHREFS,
        "https://example.com/",
    )
    service = BacklinkService({Provider.AHREFS: cast(BacklinkClient, _BudgetBacklinkClientFake())})
    report = await service.aggregate(BacklinkAggregateRequest((source,)))
    assert report.successful_sources == (Provider.AHREFS,)


@pytest.mark.asyncio
async def test_backlink_aggregate_cannot_multiply_provider_request_budget() -> None:
    sources = tuple(
        BacklinkAggregateSource(
            f"ahrefs-{index}",
            Provider.AHREFS,
            f"https://example.com/{index}",
        )
        for index in range(11)
    )
    service = BacklinkService(
        {Provider.AHREFS: cast(BacklinkClient, _DoubleBudgetBacklinkClientFake())}
    )
    with pytest.raises(InputLimitError, match="request budget"):
        await service.aggregate(BacklinkAggregateRequest(sources))


@pytest.mark.asyncio
async def test_backlink_read_has_a_whole_operation_deadline() -> None:
    service = BacklinkService({Provider.AHREFS: cast(BacklinkClient, _SlowBacklinkClientFake())})
    with pytest.raises(ProviderOperationError) as raised:
        await service.read(
            BacklinkReadRequest(
                "ahrefs-main",
                Provider.AHREFS,
                "https://example.com/",
                timeout_seconds=0.1,
            )
        )
    assert raised.value.code is ProviderFailureCode.TIMEOUT


@pytest.mark.asyncio
async def test_backlink_aggregate_has_a_whole_operation_deadline() -> None:
    service = BacklinkService({Provider.AHREFS: cast(BacklinkClient, _SlowBacklinkClientFake())})
    with pytest.raises(ProviderOperationError) as raised:
        await service.aggregate(
            BacklinkAggregateRequest(
                (
                    BacklinkAggregateSource(
                        "ahrefs-main",
                        Provider.AHREFS,
                        "https://example.com/",
                    ),
                ),
                timeout_seconds=0.1,
            )
        )
    assert raised.value.code is ProviderFailureCode.TIMEOUT
