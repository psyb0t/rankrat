from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from rankrat.constants import MONITOR_CLAIM_SECONDS
from rankrat.errors import ConfigurationError, StateConflictError
from rankrat.state.sqlite import (
    IssueStatus,
    MonitorClaim,
    MonitorKind,
    PersistedFinding,
    SQLiteStateRepository,
)

_START = datetime(2025, 1, 1, tzinfo=UTC)


def _repository(tmp_path: Path, retention_days: int = 30) -> SQLiteStateRepository:
    state_directory = tmp_path / "state"
    state_directory.mkdir(mode=0o700)
    return SQLiteStateRepository.open(
        state_directory / "rankrat.sqlite3",
        retention_days,
    )


def _create_monitor(repository: SQLiteStateRepository) -> str:
    return repository.create_monitor(
        "Daily audit",
        MonitorKind.SITE_AUDIT,
        "pagespeed-main",
        "https://example.com/",
        300,
        _START,
    ).id


def _finding() -> PersistedFinding:
    return PersistedFinding(
        "missing-title:https://example.com/",
        "missing_title",
        "https://example.com/",
        "error",
        "Page has no title.",
        "Add a descriptive title.",
    )


def _save(
    repository: SQLiteStateRepository,
    monitor_id: str,
    observed_at: datetime,
) -> None:
    claim = repository.claim_monitor(monitor_id, observed_at)
    repository.save_run(
        claim,
        80,
        {"score": 80},
        (_finding(),),
        observed_at,
    )


def test_state_survives_restart_and_walks_every_snapshot_page(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    monitor_id = _create_monitor(repository)
    for index in range(13):
        _save(repository, monitor_id, _START + timedelta(minutes=index))

    reopened = SQLiteStateRepository.open(
        tmp_path / "state" / "rankrat.sqlite3",
        30,
    )
    assert reopened.get_monitor(monitor_id).name == "Daily audit"

    pages = tuple(reopened.list_snapshots(monitor_id, 5, offset) for offset in (0, 5, 10, 13))
    assert tuple(len(page.items) for page in pages) == (5, 5, 3, 0)
    assert tuple(page.has_more for page in pages) == (True, True, False, False)
    observed = tuple(snapshot.observed_at for page in pages for snapshot in page.items)
    assert observed == tuple(sorted(observed, reverse=True))


def test_concurrent_repositories_issue_one_claim_and_reject_stale_owner(
    tmp_path: Path,
) -> None:
    first = _repository(tmp_path)
    monitor_id = _create_monitor(first)
    second = SQLiteStateRepository.open(
        tmp_path / "state" / "rankrat.sqlite3",
        30,
    )

    def claim(repository: SQLiteStateRepository) -> object:
        try:
            return repository.claim_monitor(monitor_id, _START)
        except StateConflictError as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = tuple(executor.map(claim, (first, second)))

    claims = tuple(outcome for outcome in outcomes if isinstance(outcome, MonitorClaim))
    conflicts = tuple(outcome for outcome in outcomes if isinstance(outcome, StateConflictError))
    assert len(claims) == 1
    assert len(conflicts) == 1

    stale_claim = claims[0]
    replacement = second.claim_monitor(
        monitor_id,
        _START + timedelta(seconds=MONITOR_CLAIM_SECONDS + 1),
    )
    with pytest.raises(StateConflictError, match="ownership was lost"):
        first.save_run(stale_claim, 80, {}, (), _START + timedelta(hours=1))
    second.save_run(replacement, 80, {}, (), _START + timedelta(hours=1))


def test_retention_prunes_old_snapshots_and_events_for_open_issues(tmp_path: Path) -> None:
    repository = _repository(tmp_path, retention_days=30)
    monitor_id = _create_monitor(repository)
    _save(repository, monitor_id, _START)
    issue = repository.list_issues(monitor_id, IssueStatus.OPEN, 10, 0).items[0]

    current = _START + timedelta(days=31)
    _save(repository, monitor_id, current)

    snapshots = repository.list_snapshots(monitor_id, 10, 0)
    events = repository.list_issue_events(issue.id, 10, 0)
    assert tuple(snapshot.observed_at for snapshot in snapshots.items) == (current,)
    assert tuple(event.event for event in events.items) == ("observed",)


def test_corrupt_rows_fail_as_typed_state_errors(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    monitor_id = _create_monitor(repository)
    _save(repository, monitor_id, _START)
    database = tmp_path / "state" / "rankrat.sqlite3"

    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute(
            "UPDATE monitors SET kind = ? WHERE id = ?",
            ("invalid", monitor_id),
        )
    with pytest.raises(StateConflictError, match="stored monitor row is invalid"):
        repository.get_monitor(monitor_id)

    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute(
            "UPDATE monitors SET kind = ? WHERE id = ?",
            (MonitorKind.SITE_AUDIT.value, monitor_id),
        )
        connection.execute(
            "UPDATE snapshots SET payload = ? WHERE monitor_id = ?",
            ("not-json", monitor_id),
        )
    with pytest.raises(StateConflictError, match="stored snapshot payload is invalid"):
        repository.list_snapshots(monitor_id, 10, 0)


def test_state_path_rejects_an_ancestor_symlink(tmp_path: Path) -> None:
    real_directory = tmp_path / "real"
    real_directory.mkdir(mode=0o700)
    alias = tmp_path / "alias"
    alias.symlink_to(real_directory, target_is_directory=True)

    with pytest.raises(ConfigurationError, match="directory is unavailable"):
        SQLiteStateRepository.open(alias / "rankrat.sqlite3", 30)
