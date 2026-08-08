from __future__ import annotations

import asyncio
import logging
from typing import cast

import pytest

from rankrat.errors import StateConflictError
from rankrat.transports import http as http_transport
from rankrat.transports.runtime import ApplicationServices


class _MonitoringFake:
    async def run_next_due(self) -> None:
        raise StateConflictError("claimed by another scheduler")


class _ServicesFake:
    monitoring = _MonitoringFake()


class _UnexpectedMonitoringFake:
    async def run_next_due(self) -> None:
        raise TypeError("corrupt scheduler result")


class _UnexpectedServicesFake:
    monitoring = _UnexpectedMonitoringFake()


@pytest.mark.asyncio
async def test_monitor_scheduler_logs_known_failure_and_waits(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    services = cast(ApplicationServices, _ServicesFake())
    sleeps: list[int] = []

    async def stop_after_sleep(seconds: int) -> None:
        sleeps.append(seconds)
        raise asyncio.CancelledError

    monkeypatch.setattr(http_transport.asyncio, "sleep", stop_after_sleep)
    with caplog.at_level(logging.WARNING), pytest.raises(asyncio.CancelledError):
        await http_transport._run_monitor_scheduler(services, 10)
    assert sleeps == [10]
    assert any(record.message == "scheduled monitor run was rejected" for record in caplog.records)


@pytest.mark.asyncio
async def test_monitor_scheduler_survives_unexpected_failures(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    services = cast(ApplicationServices, _UnexpectedServicesFake())
    sleeps: list[int] = []

    async def stop_after_sleep(seconds: int) -> None:
        sleeps.append(seconds)
        raise asyncio.CancelledError

    monkeypatch.setattr(http_transport.asyncio, "sleep", stop_after_sleep)
    with caplog.at_level(logging.ERROR), pytest.raises(asyncio.CancelledError):
        await http_transport._run_monitor_scheduler(services, 10)
    assert sleeps == [10]
    assert any(
        record.message == "scheduled monitor run failed unexpectedly" for record in caplog.records
    )
