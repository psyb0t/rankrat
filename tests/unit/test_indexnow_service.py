from __future__ import annotations

from collections.abc import Callable
from typing import cast

import pytest

from rankrat.constants import MAX_INDEXNOW_URLS
from rankrat.errors import (
    ApprovalDeniedError,
    BoundaryDeniedError,
    IndexNowRateLimitError,
    InputLimitError,
)
from rankrat.models.boundaries import BoundaryDocument
from rankrat.policy.approvals import WriteApprovalStore
from rankrat.policy.boundaries import BoundaryPolicy
from rankrat.providers.base import (
    IndexNowSubmission,
    IndexNowSubmitRequest,
    IndexNowTargetId,
    ProviderFailureCode,
    ProviderOperationError,
)
from rankrat.providers.indexnow import IndexNowClient
from rankrat.services.indexnow import (
    IndexNowApprovalRequest,
    IndexNowService,
    IndexNowSubmissionRequest,
)


class _Client:
    def __init__(self, results: list[IndexNowSubmission | Exception]) -> None:
        self._results = results
        self.requests: list[IndexNowSubmitRequest] = []

    async def submit(self, request: IndexNowSubmitRequest) -> IndexNowSubmission:
        self.requests.append(request)
        result = self._results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def _policy() -> BoundaryPolicy:
    return BoundaryPolicy(
        BoundaryDocument.model_validate(
            {
                "indexnow_targets": [
                    {
                        "id": "site-main",
                        "host": "example.com",
                        "key_location": "https://example.com/keys/indexnow-key.txt",
                        "key_file": "/run/secrets/indexnow/key",
                    }
                ]
            }
        )
    )


def _submission(count: int = 1, pending: bool = False) -> IndexNowSubmission:
    return IndexNowSubmission(IndexNowTargetId("site-main"), "example.com", count, pending)


def _service(
    client: _Client,
    clock: Callable[[], float] = lambda: 1.0,
    *,
    rate_limit: int = 10,
    dedupe_limit: int = 10_000,
) -> IndexNowService:
    return IndexNowService(
        _policy(),
        cast(IndexNowClient, client),
        WriteApprovalStore(),
        monotonic_clock=clock,
        max_submissions_per_window=rate_limit,
        max_dedupe_entries_per_target=dedupe_limit,
    )


async def _approved_request(
    service: IndexNowService,
    target_id: str,
    urls: tuple[str, ...],
) -> IndexNowSubmissionRequest:
    approval = await service.approve(IndexNowApprovalRequest(target_id, urls))
    return IndexNowSubmissionRequest(target_id, urls, approval.approval_id)


@pytest.mark.asyncio
async def test_service_deduplicates_and_suppresses_prior_successes() -> None:
    client = _Client([_submission()])
    service = _service(client)
    first = await service.submit(
        await _approved_request(
            service,
            "site-main",
            ("https://Example.com/keys/article", "https://example.com/keys/article"),
        )
    )
    second = await service.submit(
        await _approved_request(
            service,
            "site-main",
            ("https://example.com/keys/article",),
        )
    )

    assert first.submitted_count == 1
    assert first.deduplicated_count == 1
    assert first.suppressed_count == 0
    assert second.submitted_count == 0
    assert second.suppressed_count == 1
    assert len(client.requests) == 1


@pytest.mark.asyncio
async def test_service_releases_failed_pending_urls_and_tracks_provider_deduplication() -> None:
    error = ProviderOperationError(ProviderFailureCode.UNAVAILABLE, "safe")
    client = _Client([error, _submission(count=0, pending=True)])
    service = _service(client)
    request = await _approved_request(
        service,
        "site-main",
        ("https://example.com/keys/article",),
    )

    with pytest.raises(ProviderOperationError):
        await service.submit(request)
    response = await service.submit(
        await _approved_request(
            service,
            "site-main",
            ("https://example.com/keys/article",),
        )
    )

    assert response.submitted_count == 0
    assert response.deduplicated_count == 1
    assert response.key_validation_pending is True
    assert len(client.requests) == 2


@pytest.mark.asyncio
async def test_service_rate_limit_recovers_after_window_and_prunes_dedupe_state() -> None:
    now = [1.0]
    client = _Client([_submission(), _submission(), _submission()])
    service = _service(
        client,
        clock=lambda: now[0],
        rate_limit=1,
        dedupe_limit=1,
    )
    await service.submit(
        await _approved_request(service, "site-main", ("https://example.com/keys/one",))
    )
    with pytest.raises(IndexNowRateLimitError):
        await service.submit(
            await _approved_request(service, "site-main", ("https://example.com/keys/two",))
        )

    now[0] = 62.0
    await service.submit(
        await _approved_request(service, "site-main", ("https://example.com/keys/two",))
    )
    now[0] = 123.0
    response = await service.submit(
        await _approved_request(service, "site-main", ("https://example.com/keys/one",))
    )

    assert response.submitted_count == 1
    assert len(client.requests) == 3


@pytest.mark.asyncio
async def test_service_evicts_oldest_dedupe_entry_when_capacity_is_reached() -> None:
    client = _Client([_submission(count=2)])
    service = _service(client, dedupe_limit=1)
    await service.submit(
        await _approved_request(
            service,
            "site-main",
            ("https://example.com/keys/one", "https://example.com/keys/two"),
        )
    )
    state = service._states["site-main"]
    assert tuple(state.recent_urls) == ("https://example.com/keys/two",)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "urls",
    (
        (),
        tuple("https://example.com/keys/article" for _ in range(MAX_INDEXNOW_URLS + 1)),
    ),
)
async def test_service_rejects_empty_and_oversized_batches(urls: tuple[str, ...]) -> None:
    service = _service(_Client([]))
    with pytest.raises(InputLimitError):
        await service.submit(IndexNowSubmissionRequest("site-main", urls, "unused"))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    (
        "http://example.com/keys/article",
        "https://attacker.example/keys/article",
        "https://example.com/other/article",
        "https://example.com/keys/../article",
        "https://example.com/keys/%2farticle",
        "https://example.com/keys/%5carticle",
        "https://example.com/keys/article#fragment",
        "https://example.com:444/keys/article",
        "https://example.com/keys/article\x00",
        "https://example.com:invalid/keys/article",
    ),
)
async def test_service_rejects_urls_outside_immutable_scope(url: str) -> None:
    service = _service(_Client([]))
    with pytest.raises(BoundaryDeniedError):
        await service.submit(IndexNowSubmissionRequest("site-main", (url,), "unused"))


def test_service_rejects_invalid_unicode_host() -> None:
    target = _policy().resolve_indexnow_target("site-main")
    with pytest.raises(BoundaryDeniedError):
        IndexNowService._normalize_url(
            target,
            f"https://{chr(0xD800)}.example/keys/article",
        )


def test_service_and_provider_request_validate_limits() -> None:
    client = _Client([])
    for arguments in ((0.0, 1, 1), (1.0, 0, 1), (1.0, 1, 0)):
        with pytest.raises(ValueError):
            IndexNowService(
                _policy(),
                cast(IndexNowClient, client),
                WriteApprovalStore(),
                rate_window_seconds=arguments[0],
                max_submissions_per_window=arguments[1],
                max_dedupe_entries_per_target=arguments[2],
            )
    invalid_requests = (
        ((), 1.0),
        (("https://example.com/",) * (MAX_INDEXNOW_URLS + 1), 1.0),
        (("https://example.com/",), 0.01),
        (("https://example.com/",), 31.0),
    )
    for urls, timeout in invalid_requests:
        with pytest.raises(ValueError):
            IndexNowSubmitRequest(IndexNowTargetId("site-main"), urls, timeout)


@pytest.mark.asyncio
async def test_service_rejects_missing_or_replayed_approval_before_network_submission() -> None:
    client = _Client([_submission()])
    service = _service(client)
    urls = ("https://example.com/keys/article",)
    with pytest.raises(ApprovalDeniedError):
        await service.submit(IndexNowSubmissionRequest("site-main", urls, "missing"))

    approved = await _approved_request(service, "site-main", urls)
    await service.submit(approved)
    with pytest.raises(ApprovalDeniedError):
        await service.submit(approved)

    assert len(client.requests) == 1
