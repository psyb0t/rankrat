from __future__ import annotations

import asyncio

import pytest

from rankrat.errors import ApprovalDeniedError, InputLimitError
from rankrat.policy.approvals import WriteApprovalRequest, WriteApprovalStore


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def _request(**changes: object) -> WriteApprovalRequest:
    values: dict[str, object] = {
        "operation": "indexnow_submit",
        "account_id": "site-main",
        "resource": "https://example.com/article",
        "arguments": {"urls": ["https://example.com/article"]},
    }
    values.update(changes)
    return WriteApprovalRequest(**values)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_approval_consumes_once_for_canonical_equivalent_arguments() -> None:
    clock = _Clock()
    store = WriteApprovalStore(clock, lambda _: "approval-1")
    approval = await store.mint(
        _request(arguments={"strategy": "MOBILE", "categories": ["SEO", "PERFORMANCE"]})
    )
    assert approval.approval_id == "approval-1"
    await store.consume(
        approval.approval_id,
        _request(arguments={"categories": ["SEO", "PERFORMANCE"], "strategy": "MOBILE"}),
    )
    with pytest.raises(ApprovalDeniedError):
        await store.consume(approval.approval_id, _request())


@pytest.mark.asyncio
async def test_approval_rejects_mismatch_expiry_and_concurrent_replay() -> None:
    clock = _Clock()
    issued = iter(
        (
            "approval-operation",
            "approval-account",
            "approval-resource",
            "approval-args",
            "expiring",
            "race",
        )
    )
    store = WriteApprovalStore(clock, lambda _: next(issued))
    for change in (
        {"operation": "other"},
        {"account_id": "other"},
        {"resource": "https://example.com/other"},
        {"arguments": {"urls": ["https://example.com/other"]}},
    ):
        approval = await store.mint(_request())
        with pytest.raises(ApprovalDeniedError):
            await store.consume(approval.approval_id, _request(**change))

    expiring = await store.mint(_request(), lifetime_seconds=1.0)
    clock.now = 1.0
    with pytest.raises(ApprovalDeniedError):
        await store.consume(expiring.approval_id, _request())

    clock.now = 0.0
    replay = await store.mint(_request())
    results = await asyncio.gather(
        store.consume(replay.approval_id, _request()),
        store.consume(replay.approval_id, _request()),
        return_exceptions=True,
    )
    assert sum(result is None for result in results) == 1
    assert sum(isinstance(result, ApprovalDeniedError) for result in results) == 1
    with pytest.raises(ApprovalDeniedError):
        await store.consume("", _request())


def test_approval_rejects_invalid_configuration_requests_and_json() -> None:
    for change in ({"operation": ""}, {"account_id": ""}, {"resource": ""}):
        with pytest.raises(InputLimitError):
            _request(**change)
    with pytest.raises(ValueError):
        WriteApprovalStore(maximum_lifetime_seconds=0.0)
    store = WriteApprovalStore(token_factory=lambda _: "")
    with pytest.raises(InputLimitError):
        asyncio.run(store.mint(_request(), lifetime_seconds=0.0))
    with pytest.raises(InputLimitError):
        asyncio.run(store.mint(_request(), lifetime_seconds=61.0))
    with pytest.raises(RuntimeError):
        asyncio.run(store.mint(_request()))
    malformed = _request(arguments={"invalid": float("nan")})
    with pytest.raises(InputLimitError):
        WriteApprovalStore._arguments_hash(malformed.arguments)
