from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest

from rankrat.errors import (
    BoundaryDeniedError,
    InputLimitError,
    StateConflictError,
    StateUnavailableError,
)
from rankrat.operator import monitoring as monitoring_module
from rankrat.operator.monitoring import (
    IssueHistoryRequest,
    IssueStatusRequest,
    MonitorCreateRequest,
    MonitorHistoryRequest,
    MonitoringOperator,
    MonitorIssueListRequest,
    MonitorListRequest,
    MonitorUpdateRequest,
)
from rankrat.services.site_audit import (
    SiteAuditIssue,
    SiteAuditReport,
    SiteAuditService,
    SiteAuditSeverity,
)
from rankrat.state.sqlite import IssueStatus, SQLiteStateRepository


class _SiteAuditFake:
    def __init__(self) -> None:
        self.delay_seconds = 0.0
        self.fail = False
        self.issue_enabled = True

    def authorize(self, account_id: str, site_url: str) -> str:
        if account_id != "pagespeed-main" or site_url != "https://example.com/":
            raise BoundaryDeniedError("site is outside the configured boundary")
        return site_url

    async def audit(self, _: object) -> SiteAuditReport:
        if self.delay_seconds:
            await asyncio.sleep(self.delay_seconds)
        if self.fail:
            raise RuntimeError("audit failed")
        issues = (
            (
                SiteAuditIssue(
                    "missing_title",
                    SiteAuditSeverity.ERROR,
                    "https://example.com/page",
                    "Page has no title.",
                    "Add a descriptive title.",
                ),
            )
            if self.issue_enabled
            else ()
        )
        return SiteAuditReport("https://example.com/", 80, (), issues, (), False)


def _operator(
    tmp_path: Path,
) -> tuple[MonitoringOperator, _SiteAuditFake, SQLiteStateRepository]:
    state_dir = tmp_path / "state"
    state_dir.mkdir(mode=0o700)
    repository = SQLiteStateRepository.open(state_dir / "rankrat.sqlite3", 30)
    audit = _SiteAuditFake()
    return MonitoringOperator(repository, cast(SiteAuditService, audit)), audit, repository


@pytest.mark.asyncio
async def test_monitor_operator_runs_and_tracks_issue_lifecycle(tmp_path: Path) -> None:
    operator, audit, _ = _operator(tmp_path)
    monitor = operator.create_monitor(
        MonitorCreateRequest(
            "Daily audit",
            "pagespeed-main",
            "https://example.com/",
            300,
        )
    )
    scope = MonitorHistoryRequest(
        monitor_id=monitor.id,
        account_id="pagespeed-main",
        site_url="https://example.com/",
    )
    first = await operator.run_monitor(scope)
    assert first.snapshot.issue_count == 1
    issues_scope = MonitorIssueListRequest(
        monitor_id=monitor.id,
        account_id="pagespeed-main",
        site_url="https://example.com/",
    )
    issue = operator.list_issues(issues_scope).items[0]
    assert issue.status is IssueStatus.OPEN

    audit.issue_enabled = False
    await operator.run_monitor(scope)
    issue = operator.list_issues(issues_scope).items[0]
    assert issue.status is IssueStatus.RESOLVED


@pytest.mark.asyncio
async def test_monitor_operator_releases_failed_claim_and_enforces_scope(
    tmp_path: Path,
) -> None:
    operator, audit, _ = _operator(tmp_path)
    monitor = operator.create_monitor(
        MonitorCreateRequest(
            "Daily audit",
            "pagespeed-main",
            "https://example.com/",
            300,
        )
    )
    scope = MonitorHistoryRequest(
        monitor_id=monitor.id,
        account_id="pagespeed-main",
        site_url="https://example.com/",
    )
    audit.fail = True
    with pytest.raises(RuntimeError, match="audit failed"):
        await operator.run_monitor(scope)
    audit.fail = False
    assert (await operator.run_monitor(scope)).snapshot.score == 80

    with pytest.raises(BoundaryDeniedError):
        await operator.run_monitor(
            MonitorHistoryRequest(
                monitor_id=monitor.id,
                account_id="other",
                site_url="https://example.com/",
            )
        )


def test_monitor_operator_reports_disabled_state() -> None:
    operator = MonitoringOperator(None, cast(SiteAuditService, _SiteAuditFake()))
    assert operator.available is False
    with pytest.raises(StateUnavailableError):
        operator.create_monitor(
            MonitorCreateRequest(
                "Daily audit",
                "pagespeed-main",
                "https://example.com/",
                300,
            )
        )


@pytest.mark.asyncio
async def test_monitor_operator_renews_a_long_running_claim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operator, audit, repository = _operator(tmp_path)
    monitor = operator.create_monitor(
        MonitorCreateRequest(
            "Daily audit",
            "pagespeed-main",
            "https://example.com/",
            300,
        )
    )
    audit.delay_seconds = 0.08
    monkeypatch.setattr(monitoring_module, "MONITOR_CLAIM_RENEWAL_SECONDS", 0.01)
    monkeypatch.setattr("rankrat.state.sqlite.MONITOR_CLAIM_SECONDS", 0.03)

    run = asyncio.create_task(
        operator.run_monitor(
            MonitorHistoryRequest(
                monitor_id=monitor.id,
                account_id="pagespeed-main",
                site_url="https://example.com/",
            )
        )
    )
    await asyncio.sleep(0.05)
    with pytest.raises(StateConflictError, match="already running"):
        repository.claim_monitor(monitor.id, datetime.now(UTC))
    assert (await run).snapshot.score == 80


@pytest.mark.asyncio
async def test_monitor_operator_covers_crud_history_and_manual_status(
    tmp_path: Path,
) -> None:
    operator, _, _ = _operator(tmp_path)
    monitor = operator.create_monitor(
        MonitorCreateRequest(
            " Daily audit ",
            "pagespeed-main",
            "https://example.com/",
            300,
        )
    )
    history = MonitorHistoryRequest(
        monitor_id=monitor.id,
        account_id="pagespeed-main",
        site_url="https://example.com/",
    )
    await operator.run_monitor(history)

    assert (
        operator.list_monitors(
            MonitorListRequest(account_id="pagespeed-main", site_url="https://example.com/")
        )
        .items[0]
        .name
        == "Daily audit"
    )
    assert operator.list_snapshots(history).items[0].score == 80
    issue = operator.list_issues(
        MonitorIssueListRequest(
            monitor_id=monitor.id,
            account_id="pagespeed-main",
            site_url="https://example.com/",
        )
    ).items[0]
    updated_issue = operator.set_issue_status(
        IssueStatusRequest(
            issue.id,
            monitor.id,
            "pagespeed-main",
            "https://example.com/",
            IssueStatus.ACKNOWLEDGED,
        )
    )
    assert updated_issue.status is IssueStatus.ACKNOWLEDGED
    assert operator.list_issue_events(
        IssueHistoryRequest(
            issue_id=issue.id,
            monitor_id=monitor.id,
            account_id="pagespeed-main",
            site_url="https://example.com/",
        )
    ).items

    updated_monitor = operator.update_monitor(
        MonitorUpdateRequest(
            monitor.id,
            "pagespeed-main",
            "https://example.com/",
            "Weekly audit",
            600,
            False,
        )
    )
    assert updated_monitor.name == "Weekly audit"
    assert await operator.run_next_due() is None
    operator.delete_monitor(history)
    assert (
        operator.list_monitors(
            MonitorListRequest(account_id="pagespeed-main", site_url="https://example.com/")
        ).items
        == ()
    )


def test_monitor_requests_reject_invalid_names_and_intervals() -> None:
    with pytest.raises(InputLimitError):
        MonitorCreateRequest(" ", "pagespeed-main", "https://example.com/", 300)
    with pytest.raises(InputLimitError):
        MonitorCreateRequest("audit", "pagespeed-main", "https://example.com/", 1)
    with pytest.raises(InputLimitError):
        MonitorUpdateRequest(
            "monitor",
            "pagespeed-main",
            "https://example.com/",
            " ",
            300,
            True,
        )
    with pytest.raises(InputLimitError):
        MonitorUpdateRequest(
            "monitor",
            "pagespeed-main",
            "https://example.com/",
            "audit",
            1,
            True,
        )
