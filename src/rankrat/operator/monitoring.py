"""Monitor orchestration over bounded report services and persistent state."""

from __future__ import annotations

import asyncio
import contextvars
import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime

from rankrat.constants import (
    DEFAULT_MONITOR_INTERVAL_SECONDS,
    DEFAULT_STATE_PAGE_SIZE,
    MAX_MONITOR_INTERVAL_SECONDS,
    MAX_MONITOR_NAME_CHARS,
    MIN_MONITOR_INTERVAL_SECONDS,
    MONITOR_CLAIM_RENEWAL_SECONDS,
)
from rankrat.errors import BoundaryDeniedError, InputLimitError, StateUnavailableError
from rankrat.models.common import JsonValue, to_json_value
from rankrat.services.site_audit import SiteAuditRequest, SiteAuditService
from rankrat.state.sqlite import (
    IssueEvent,
    IssueStatus,
    MonitorClaim,
    MonitorDefinition,
    MonitorKind,
    MonitorSnapshot,
    PersistedFinding,
    SQLiteStateRepository,
    StatePage,
    TrackedIssue,
)


@dataclass(frozen=True, slots=True)
class MonitorCreateRequest:
    name: str
    account_id: str
    site_url: str
    interval_seconds: int = DEFAULT_MONITOR_INTERVAL_SECONDS

    def __post_init__(self) -> None:
        if not self.name.strip() or len(self.name) > MAX_MONITOR_NAME_CHARS:
            raise InputLimitError("monitor name is outside the allowed range")
        if (
            not MIN_MONITOR_INTERVAL_SECONDS
            <= self.interval_seconds
            <= (MAX_MONITOR_INTERVAL_SECONDS)
        ):
            raise InputLimitError("monitor interval is outside the allowed range")


@dataclass(frozen=True, slots=True)
class StateListRequest:
    limit: int = DEFAULT_STATE_PAGE_SIZE
    offset: int = 0


@dataclass(frozen=True, slots=True)
class MonitorListRequest(StateListRequest):
    account_id: str = ""
    site_url: str = ""


@dataclass(frozen=True, slots=True)
class MonitorHistoryRequest(StateListRequest):
    monitor_id: str = ""
    account_id: str = ""
    site_url: str = ""


@dataclass(frozen=True, slots=True)
class MonitorIssueListRequest(MonitorHistoryRequest):
    status: IssueStatus | None = None


@dataclass(frozen=True, slots=True)
class IssueHistoryRequest(StateListRequest):
    issue_id: str = ""
    monitor_id: str = ""
    account_id: str = ""
    site_url: str = ""


@dataclass(frozen=True, slots=True)
class MonitorUpdateRequest:
    monitor_id: str
    account_id: str
    site_url: str
    name: str
    interval_seconds: int
    enabled: bool

    def __post_init__(self) -> None:
        if not self.name.strip() or len(self.name) > MAX_MONITOR_NAME_CHARS:
            raise InputLimitError("monitor name is outside the allowed range")
        if (
            not MIN_MONITOR_INTERVAL_SECONDS
            <= self.interval_seconds
            <= (MAX_MONITOR_INTERVAL_SECONDS)
        ):
            raise InputLimitError("monitor interval is outside the allowed range")


@dataclass(frozen=True, slots=True)
class IssueStatusRequest:
    issue_id: str
    monitor_id: str
    account_id: str
    site_url: str
    status: IssueStatus


@dataclass(frozen=True, slots=True)
class MonitorRunResult:
    monitor: MonitorDefinition
    snapshot: MonitorSnapshot


class MonitoringOperator:
    """Execute bounded audits and persist deduplicated lifecycle evidence."""

    def __init__(
        self,
        repository: SQLiteStateRepository | None,
        site_audit: SiteAuditService,
    ) -> None:
        self._repository = repository
        self._site_audit = site_audit

    @property
    def available(self) -> bool:
        return self._repository is not None

    def create_monitor(self, request: MonitorCreateRequest) -> MonitorDefinition:
        self._site_audit.authorize(request.account_id, request.site_url)
        return self._require_repository().create_monitor(
            request.name.strip(),
            MonitorKind.SITE_AUDIT,
            request.account_id,
            request.site_url,
            request.interval_seconds,
            datetime.now(UTC),
        )

    def list_monitors(self, request: MonitorListRequest) -> StatePage[MonitorDefinition]:
        self._site_audit.authorize(request.account_id, request.site_url)
        return self._require_repository().list_monitors(
            request.account_id,
            request.site_url,
            request.limit,
            request.offset,
        )

    def update_monitor(self, request: MonitorUpdateRequest) -> MonitorDefinition:
        repository = self._require_repository()
        self._authorize_monitor(
            repository,
            request.monitor_id,
            request.account_id,
            request.site_url,
        )
        return repository.update_monitor(
            request.monitor_id,
            request.name.strip(),
            request.interval_seconds,
            request.enabled,
            datetime.now(UTC),
        )

    def delete_monitor(self, request: MonitorHistoryRequest) -> None:
        repository = self._require_repository()
        self._authorize_monitor(
            repository,
            request.monitor_id,
            request.account_id,
            request.site_url,
        )
        repository.delete_monitor(request.monitor_id)

    async def run_monitor(self, request: MonitorHistoryRequest) -> MonitorRunResult:
        repository = self._require_repository()
        self._authorize_monitor(
            repository,
            request.monitor_id,
            request.account_id,
            request.site_url,
        )
        claim = repository.claim_monitor(request.monitor_id, datetime.now(UTC))
        return await self._execute(repository, claim)

    async def run_next_due(self) -> MonitorRunResult | None:
        repository = self._require_repository()
        claim = repository.claim_due_monitor(datetime.now(UTC))
        if claim is None:
            return None
        return await self._execute(repository, claim)

    def list_snapshots(
        self,
        request: MonitorHistoryRequest,
    ) -> StatePage[MonitorSnapshot]:
        repository = self._require_repository()
        self._authorize_monitor(
            repository,
            request.monitor_id,
            request.account_id,
            request.site_url,
        )
        return repository.list_snapshots(
            request.monitor_id,
            request.limit,
            request.offset,
        )

    def list_issues(self, request: MonitorIssueListRequest) -> StatePage[TrackedIssue]:
        repository = self._require_repository()
        self._authorize_monitor(
            repository,
            request.monitor_id,
            request.account_id,
            request.site_url,
        )
        return repository.list_issues(
            request.monitor_id,
            request.status,
            request.limit,
            request.offset,
        )

    def set_issue_status(self, request: IssueStatusRequest) -> TrackedIssue:
        repository = self._require_repository()
        self._authorize_issue(
            repository,
            request.issue_id,
            request.monitor_id,
            request.account_id,
            request.site_url,
        )
        return repository.set_issue_status(
            request.issue_id,
            request.status,
            datetime.now(UTC),
        )

    def list_issue_events(self, request: IssueHistoryRequest) -> StatePage[IssueEvent]:
        repository = self._require_repository()
        self._authorize_issue(
            repository,
            request.issue_id,
            request.monitor_id,
            request.account_id,
            request.site_url,
        )
        return repository.list_issue_events(
            request.issue_id,
            request.limit,
            request.offset,
        )

    async def _execute(
        self,
        repository: SQLiteStateRepository,
        claim: MonitorClaim,
    ) -> MonitorRunResult:
        monitor = claim.monitor
        completed = False
        stop_heartbeat = asyncio.Event()
        context = contextvars.copy_context()
        heartbeat = context.run(
            asyncio.create_task,
            self._renew_claim(repository, claim, stop_heartbeat),
            name=f"rankrat-monitor-claim-{monitor.id}",
        )
        try:
            context = contextvars.copy_context()
            audit = context.run(
                asyncio.create_task,
                self._site_audit.audit(
                    SiteAuditRequest(
                        account_id=monitor.account_id,
                        site_url=monitor.site_url,
                    )
                ),
                name=f"rankrat-monitor-audit-{monitor.id}",
            )
            completed_tasks, _ = await asyncio.wait(
                {audit, heartbeat},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if heartbeat in completed_tasks:
                audit.cancel()
                await asyncio.gather(audit, return_exceptions=True)
                heartbeat.result()
            report = await audit
            stop_heartbeat.set()
            await heartbeat
            payload_value = to_json_value(report)
            if not isinstance(payload_value, dict):
                raise TypeError("monitor report must serialize to an object")
            payload = _json_object(payload_value)
            findings = tuple(
                PersistedFinding(
                    identity=_finding_identity(issue.code, issue.url),
                    code=issue.code,
                    resource=issue.url,
                    severity=issue.severity.value,
                    message=issue.message,
                    remediation=issue.remediation,
                )
                for issue in report.issues
            )
            snapshot = repository.save_run(
                claim,
                report.score,
                payload,
                findings,
                datetime.now(UTC),
            )
            completed = True
            return MonitorRunResult(repository.get_monitor(monitor.id), snapshot)
        finally:
            stop_heartbeat.set()
            if not heartbeat.done():
                await heartbeat
            if not completed:
                repository.release_claim(claim)

    @staticmethod
    async def _renew_claim(
        repository: SQLiteStateRepository,
        claim: MonitorClaim,
        stop: asyncio.Event,
    ) -> None:
        while True:
            try:
                await asyncio.wait_for(
                    stop.wait(),
                    timeout=MONITOR_CLAIM_RENEWAL_SECONDS,
                )
                return
            except TimeoutError:
                repository.renew_claim(claim, datetime.now(UTC))

    def _require_repository(self) -> SQLiteStateRepository:
        if self._repository is None:
            raise StateUnavailableError("persistent state is disabled")
        return self._repository

    def _authorize_monitor(
        self,
        repository: SQLiteStateRepository,
        monitor_id: str,
        account_id: str,
        site_url: str,
    ) -> MonitorDefinition:
        self._site_audit.authorize(account_id, site_url)
        monitor = repository.get_monitor(monitor_id)
        if monitor.account_id != account_id or monitor.site_url != site_url:
            raise BoundaryDeniedError("monitor is outside the requested site boundary")
        return monitor

    def _authorize_issue(
        self,
        repository: SQLiteStateRepository,
        issue_id: str,
        monitor_id: str,
        account_id: str,
        site_url: str,
    ) -> TrackedIssue:
        self._authorize_monitor(repository, monitor_id, account_id, site_url)
        issue = repository.get_issue(issue_id)
        if issue.monitor_id != monitor_id:
            raise BoundaryDeniedError("issue is outside the requested monitor boundary")
        return issue


def _finding_identity(code: str, resource: str) -> str:
    return hashlib.sha256(f"{code}\0{resource}".encode()).hexdigest()


def _json_object(value: dict[str, JsonValue]) -> dict[str, object]:
    return {key: item for key, item in value.items()}
