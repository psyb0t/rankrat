from __future__ import annotations

import os
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from rankrat.errors import ConfigurationError, InputLimitError, StateConflictError
from rankrat.state.sqlite import (
    IssueStatus,
    MonitorDefinition,
    MonitorKind,
    PersistedFinding,
    SQLiteStateRepository,
)

_NOW = datetime(2025, 1, 1, tzinfo=UTC)


def _repository(tmp_path: Path, retention_days: int = 30) -> SQLiteStateRepository:
    state_dir = tmp_path / "state"
    state_dir.mkdir(mode=0o700)
    return SQLiteStateRepository.open(state_dir / "rankrat.sqlite3", retention_days)


def _monitor(repository: SQLiteStateRepository) -> MonitorDefinition:
    return repository.create_monitor(
        "Site audit",
        MonitorKind.SITE_AUDIT,
        "pagespeed-main",
        "https://example.com/",
        300,
        _NOW,
    )


def _finding(identity: str = "identity-1") -> PersistedFinding:
    return PersistedFinding(
        identity,
        "missing_title",
        "https://example.com/page",
        "error",
        "Page has no title.",
        "Add a descriptive title.",
    )


def test_state_database_requires_private_real_paths(tmp_path: Path) -> None:
    unsafe_dir = tmp_path / "unsafe"
    unsafe_dir.mkdir(mode=0o755)
    with pytest.raises(ConfigurationError, match="permissions"):
        SQLiteStateRepository.open(unsafe_dir / "state.sqlite3", 30)

    safe_dir = tmp_path / "safe"
    safe_dir.mkdir(mode=0o700)
    target = safe_dir / "target.sqlite3"
    target.touch(mode=0o600)
    symlink = safe_dir / "state.sqlite3"
    symlink.symlink_to(target)
    with pytest.raises(ConfigurationError, match="non-symlink"):
        SQLiteStateRepository.open(symlink, 30)

    repository = SQLiteStateRepository.open(safe_dir / "valid.sqlite3", 30)
    assert repository is not None
    assert os.stat(safe_dir / "valid.sqlite3").st_mode & 0o777 == 0o600


def test_monitor_create_update_claim_and_duplicate_controls(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    monitor = _monitor(repository)
    with pytest.raises(StateConflictError, match="already exists"):
        _monitor(repository)

    claimed = repository.claim_monitor(monitor.id, _NOW)
    assert claimed.monitor.id == monitor.id
    with pytest.raises(StateConflictError, match="already running"):
        repository.claim_monitor(monitor.id, _NOW)

    repository.release_claim(claimed)
    disabled = repository.update_monitor(
        monitor.id,
        "Paused",
        600,
        False,
        _NOW + timedelta(seconds=1),
    )
    assert disabled.enabled is False
    assert repository.claim_due_monitor(_NOW + timedelta(days=1)) is None

    enabled = repository.update_monitor(
        monitor.id,
        "Resumed",
        900,
        True,
        _NOW + timedelta(seconds=2),
    )
    assert enabled.enabled is True
    assert enabled.next_run_at == _NOW + timedelta(seconds=2)


def test_issue_lifecycle_and_idempotent_manual_status(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    monitor = _monitor(repository)
    finding = _finding()

    claim = repository.claim_monitor(monitor.id, _NOW)
    repository.save_run(claim, 80, {"run": 1}, (finding,), _NOW)
    issue = repository.list_issues(monitor.id, None, 10, 0).items[0]
    assert issue.status is IssueStatus.OPEN
    assert issue.observations == 1

    claim = repository.claim_monitor(monitor.id, _NOW + timedelta(minutes=5))
    repository.save_run(
        claim,
        80,
        {"run": 2},
        (finding,),
        _NOW + timedelta(minutes=5),
    )
    issue = repository.get_issue(issue.id)
    assert issue.observations == 2

    claim = repository.claim_monitor(monitor.id, _NOW + timedelta(minutes=10))
    repository.save_run(
        claim,
        100,
        {"run": 3},
        (),
        _NOW + timedelta(minutes=10),
    )
    assert repository.get_issue(issue.id).status is IssueStatus.RESOLVED

    claim = repository.claim_monitor(monitor.id, _NOW + timedelta(minutes=15))
    repository.save_run(
        claim,
        80,
        {"run": 4},
        (finding,),
        _NOW + timedelta(minutes=15),
    )
    assert repository.get_issue(issue.id).status is IssueStatus.OPEN

    repository.set_issue_status(issue.id, IssueStatus.ACKNOWLEDGED, _NOW)
    before = repository.list_issue_events(issue.id, 100, 0)
    repository.set_issue_status(issue.id, IssueStatus.ACKNOWLEDGED, _NOW)
    after = repository.list_issue_events(issue.id, 100, 0)
    assert len(after.items) == len(before.items)
    assert {event.event for event in after.items} >= {
        "opened",
        "observed",
        "resolved",
        "reopened",
        "acknowledged",
    }


def test_snapshot_pagination_walks_every_page(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    monitor = _monitor(repository)
    for index in range(13):
        claim = repository.claim_monitor(monitor.id, _NOW + timedelta(minutes=index))
        repository.save_run(
            claim,
            index,
            {"index": index},
            (),
            _NOW + timedelta(minutes=index),
        )

    expected: tuple[tuple[int, int, list[int], bool], ...] = (
        (0, 5, [12, 11, 10, 9, 8], True),
        (5, 5, [7, 6, 5, 4, 3], True),
        (10, 3, [2, 1, 0], False),
        (13, 0, [], False),
        (100, 0, [], False),
    )
    for offset, count, indices, has_more in expected:
        page = repository.list_snapshots(monitor.id, 5, offset)
        assert len(page.items) == count
        assert [item.payload["index"] for item in page.items] == indices
        assert page.has_more is has_more

    with pytest.raises(InputLimitError):
        repository.list_snapshots(monitor.id, 0, 0)
    with pytest.raises(InputLimitError):
        repository.list_snapshots(monitor.id, 1, -1)


def test_monitor_claim_is_atomic_across_threads(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    monitor = _monitor(repository)
    barrier = threading.Barrier(3)
    outcomes: list[str] = []

    def claim() -> None:
        barrier.wait()
        try:
            repository.claim_monitor(monitor.id, _NOW)
            outcomes.append("claimed")
        except StateConflictError:
            outcomes.append("conflict")

    threads = [threading.Thread(target=claim), threading.Thread(target=claim)]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join()

    assert sorted(outcomes) == ["claimed", "conflict"]
