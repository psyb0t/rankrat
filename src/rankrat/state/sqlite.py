"""Typed, transaction-safe SQLite storage for monitors and issue history."""

from __future__ import annotations

import json
import os
import sqlite3
import stat
import threading
import uuid
from collections.abc import Iterable
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Self, cast

from rankrat.constants import MAX_STATE_PAGE_SIZE, MONITOR_CLAIM_SECONDS
from rankrat.errors import (
    ConfigurationError,
    InputLimitError,
    StateConflictError,
    StateNotFoundError,
)

_SCHEMA_VERSION = 2
_FILE_MODE = 0o600
_DIRECTORY_FORBIDDEN_MODE = stat.S_IRWXG | stat.S_IRWXO
_FILE_FORBIDDEN_MODE = stat.S_IRWXG | stat.S_IRWXO
_DIRECTORY_OPEN_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
_FILE_CREATE_FLAGS = os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW
_SQLITE_TIMEOUT_SECONDS = 5.0


class MonitorKind(StrEnum):
    """Finite report kinds that can be persisted by the scheduler."""

    SITE_AUDIT = "site_audit"


class IssueStatus(StrEnum):
    """Stable local issue lifecycle states."""

    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"


@dataclass(frozen=True, slots=True)
class MonitorDefinition:
    id: str
    name: str
    kind: MonitorKind
    account_id: str
    site_url: str
    interval_seconds: int
    enabled: bool
    next_run_at: datetime
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class MonitorClaim:
    monitor: MonitorDefinition
    token: str


@dataclass(frozen=True, slots=True)
class MonitorSnapshot:
    id: str
    monitor_id: str
    observed_at: datetime
    score: int
    issue_count: int
    payload: dict[str, object]


@dataclass(frozen=True, slots=True)
class TrackedIssue:
    id: str
    monitor_id: str
    identity: str
    code: str
    resource: str
    severity: str
    message: str
    remediation: str
    status: IssueStatus
    observations: int
    first_seen_at: datetime
    last_seen_at: datetime
    resolved_at: datetime | None


@dataclass(frozen=True, slots=True)
class IssueEvent:
    id: int
    issue_id: str
    event: str
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class StatePage[T]:
    items: tuple[T, ...]
    has_more: bool


@dataclass(frozen=True, slots=True)
class PersistedFinding:
    identity: str
    code: str
    resource: str
    severity: str
    message: str
    remediation: str


class SQLiteStateRepository:
    """Single-process SQLite repository with explicit claims and immutable history."""

    def __init__(self, path: Path, retention_days: int) -> None:
        self._path = path
        self._retention_days = retention_days
        self._lock = threading.RLock()

    @classmethod
    def open(cls, path: Path, retention_days: int) -> Self:
        cls._prepare_path(path)
        repository = cls(path, retention_days)
        repository._initialize()
        return repository

    @staticmethod
    def _prepare_path(path: Path) -> None:
        if not path.is_absolute():
            raise ConfigurationError("state database path must be absolute")
        try:
            parent_descriptor = _open_safe_directory(path.parent)
        except OSError as error:
            raise ConfigurationError("state database directory is unavailable") from error
        try:
            parent_stat = os.fstat(parent_descriptor)
            if parent_stat.st_uid != os.getuid() or parent_stat.st_mode & _DIRECTORY_FORBIDDEN_MODE:
                raise ConfigurationError("state database directory permissions are unsafe")
            try:
                path_stat = os.stat(
                    path.name,
                    dir_fd=parent_descriptor,
                    follow_symlinks=False,
                )
            except FileNotFoundError:
                _create_state_file(parent_descriptor, path.name)
                return
            if not stat.S_ISREG(path_stat.st_mode):
                raise ConfigurationError("state database must be a regular non-symlink file")
            if path_stat.st_uid != os.getuid() or path_stat.st_mode & _FILE_FORBIDDEN_MODE:
                raise ConfigurationError("state database file permissions are unsafe")
        finally:
            os.close(parent_descriptor)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self._path,
            timeout=_SQLITE_TIMEOUT_SECONDS,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = FULL")
        return connection

    def _initialize(self) -> None:
        schema = """
        BEGIN IMMEDIATE;
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER PRIMARY KEY
        );
        CREATE TABLE IF NOT EXISTS monitors (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            kind TEXT NOT NULL,
            account_id TEXT NOT NULL,
            site_url TEXT NOT NULL,
            interval_seconds INTEGER NOT NULL,
            enabled INTEGER NOT NULL,
            next_run_at TEXT NOT NULL,
            claimed_until TEXT,
            claim_token TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(kind, account_id, site_url)
        );
        CREATE TABLE IF NOT EXISTS snapshots (
            id TEXT PRIMARY KEY,
            monitor_id TEXT NOT NULL REFERENCES monitors(id) ON DELETE CASCADE,
            observed_at TEXT NOT NULL,
            score INTEGER NOT NULL,
            issue_count INTEGER NOT NULL,
            payload TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS snapshots_monitor_observed
            ON snapshots(monitor_id, observed_at DESC, id DESC);
        CREATE TABLE IF NOT EXISTS issues (
            id TEXT PRIMARY KEY,
            monitor_id TEXT NOT NULL REFERENCES monitors(id) ON DELETE CASCADE,
            identity TEXT NOT NULL,
            code TEXT NOT NULL,
            resource TEXT NOT NULL,
            severity TEXT NOT NULL,
            message TEXT NOT NULL,
            remediation TEXT NOT NULL,
            status TEXT NOT NULL,
            observations INTEGER NOT NULL,
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            resolved_at TEXT,
            UNIQUE(monitor_id, identity)
        );
        CREATE INDEX IF NOT EXISTS issues_monitor_status
            ON issues(monitor_id, status, last_seen_at DESC, id DESC);
        CREATE TABLE IF NOT EXISTS issue_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            issue_id TEXT NOT NULL REFERENCES issues(id) ON DELETE CASCADE,
            event TEXT NOT NULL,
            occurred_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS issue_events_issue
            ON issue_events(issue_id, occurred_at DESC, id DESC);
        INSERT OR IGNORE INTO schema_version(version) VALUES (2);
        COMMIT;
        """
        with self._lock, closing(self._connect()) as connection:
            try:
                connection.executescript(schema)
                versions = connection.execute("SELECT version FROM schema_version").fetchall()
            except sqlite3.Error as error:
                raise ConfigurationError("state database schema initialization failed") from error
        if tuple(row["version"] for row in versions) != (_SCHEMA_VERSION,):
            raise ConfigurationError("state database schema version is incompatible")

    def create_monitor(
        self,
        name: str,
        kind: MonitorKind,
        account_id: str,
        site_url: str,
        interval_seconds: int,
        now: datetime,
    ) -> MonitorDefinition:
        monitor_id = str(uuid.uuid4())
        timestamp = _timestamp(now)
        parameters = (
            monitor_id,
            name,
            kind.value,
            account_id,
            site_url,
            interval_seconds,
            1,
            timestamp,
            timestamp,
            timestamp,
        )
        with self._lock, closing(self._connect()) as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    """
                    INSERT INTO monitors(
                        id, name, kind, account_id, site_url, interval_seconds,
                        enabled, next_run_at, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    parameters,
                )
                connection.execute("COMMIT")
            except sqlite3.IntegrityError as error:
                connection.execute("ROLLBACK")
                raise StateConflictError("monitor already exists for this site and kind") from error
            except sqlite3.Error as error:
                connection.execute("ROLLBACK")
                raise StateConflictError("monitor could not be created") from error
        return self.get_monitor(monitor_id)

    def get_monitor(self, monitor_id: str) -> MonitorDefinition:
        with self._lock, closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM monitors WHERE id = ?",
                (monitor_id,),
            ).fetchone()
        if row is None:
            raise StateNotFoundError("monitor not found")
        return _monitor(row)

    def list_monitors(
        self,
        account_id: str,
        site_url: str,
        limit: int,
        offset: int,
    ) -> StatePage[MonitorDefinition]:
        _validate_page(limit, offset)
        with self._lock, closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT * FROM monitors
                WHERE account_id = ? AND site_url = ?
                ORDER BY created_at, id LIMIT ? OFFSET ?
                """,
                (account_id, site_url, limit + 1, offset),
            ).fetchall()
        return StatePage(tuple(_monitor(row) for row in rows[:limit]), len(rows) > limit)

    def update_monitor(
        self,
        monitor_id: str,
        name: str,
        interval_seconds: int,
        enabled: bool,
        now: datetime,
    ) -> MonitorDefinition:
        timestamp = _timestamp(now)
        with self._lock, closing(self._connect()) as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                result = connection.execute(
                    """
                    UPDATE monitors
                    SET name = ?, interval_seconds = ?, enabled = ?,
                        next_run_at = CASE WHEN enabled = 0 AND ? = 1
                            THEN ? ELSE next_run_at END,
                        claimed_until = CASE WHEN ? = 0 THEN NULL ELSE claimed_until END,
                        claim_token = CASE WHEN ? = 0 THEN NULL ELSE claim_token END,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        name,
                        interval_seconds,
                        int(enabled),
                        int(enabled),
                        timestamp,
                        int(enabled),
                        int(enabled),
                        timestamp,
                        monitor_id,
                    ),
                )
                connection.execute("COMMIT")
            except sqlite3.Error as error:
                connection.execute("ROLLBACK")
                raise StateConflictError("monitor could not be updated") from error
        if result.rowcount != 1:
            raise StateNotFoundError("monitor not found")
        return self.get_monitor(monitor_id)

    def delete_monitor(self, monitor_id: str) -> None:
        with self._lock, closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            result = connection.execute("DELETE FROM monitors WHERE id = ?", (monitor_id,))
            connection.execute("COMMIT")
        if result.rowcount != 1:
            raise StateNotFoundError("monitor not found")

    def claim_monitor(self, monitor_id: str, now: datetime) -> MonitorClaim:
        claimed_until = _timestamp(now + timedelta(seconds=MONITOR_CLAIM_SECONDS))
        timestamp = _timestamp(now)
        claim_token = str(uuid.uuid4())
        with self._lock, closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            result = connection.execute(
                """
                UPDATE monitors SET claimed_until = ?, claim_token = ?, updated_at = ?
                WHERE id = ? AND enabled = 1
                  AND (claimed_until IS NULL OR claimed_until < ?)
                """,
                (claimed_until, claim_token, timestamp, monitor_id, timestamp),
            )
            connection.execute("COMMIT")
        if result.rowcount != 1:
            raise StateConflictError("monitor is disabled, missing, or already running")
        return MonitorClaim(self.get_monitor(monitor_id), claim_token)

    def claim_due_monitor(self, now: datetime) -> MonitorClaim | None:
        timestamp = _timestamp(now)
        claimed_until = _timestamp(now + timedelta(seconds=MONITOR_CLAIM_SECONDS))
        claim_token = str(uuid.uuid4())
        with self._lock, closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT id FROM monitors
                WHERE enabled = 1 AND next_run_at <= ?
                  AND (claimed_until IS NULL OR claimed_until < ?)
                ORDER BY next_run_at, id LIMIT 1
                """,
                (timestamp, timestamp),
            ).fetchone()
            if row is None:
                connection.execute("COMMIT")
                return None
            connection.execute(
                """
                UPDATE monitors
                SET claimed_until = ?, claim_token = ?, updated_at = ?
                WHERE id = ?
                """,
                (claimed_until, claim_token, timestamp, row["id"]),
            )
            connection.execute("COMMIT")
        monitor_id = cast(str, row["id"])
        return MonitorClaim(self.get_monitor(monitor_id), claim_token)

    def renew_claim(self, claim: MonitorClaim, now: datetime) -> None:
        claimed_until = _timestamp(now + timedelta(seconds=MONITOR_CLAIM_SECONDS))
        with self._lock, closing(self._connect()) as connection:
            result = connection.execute(
                """
                UPDATE monitors SET claimed_until = ?, updated_at = ?
                WHERE id = ? AND claim_token = ? AND enabled = 1
                """,
                (claimed_until, _timestamp(now), claim.monitor.id, claim.token),
            )
        if result.rowcount != 1:
            raise StateConflictError("monitor claim ownership was lost")

    def save_run(
        self,
        claim: MonitorClaim,
        score: int,
        payload: dict[str, object],
        findings: Iterable[PersistedFinding],
        now: datetime,
    ) -> MonitorSnapshot:
        snapshot_id = str(uuid.uuid4())
        timestamp = _timestamp(now)
        finding_list = tuple(findings)
        identities = tuple(finding.identity for finding in finding_list)
        monitor = claim.monitor
        next_run = _timestamp(now + timedelta(seconds=monitor.interval_seconds))
        serialized_payload = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        with self._lock, closing(self._connect()) as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                owner = connection.execute(
                    "SELECT claim_token FROM monitors WHERE id = ?",
                    (monitor.id,),
                ).fetchone()
                if owner is None or owner["claim_token"] != claim.token:
                    connection.execute("ROLLBACK")
                    raise StateConflictError("monitor claim ownership was lost")
                connection.execute(
                    """
                    INSERT INTO snapshots(id, monitor_id, observed_at, score, issue_count, payload)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        snapshot_id,
                        monitor.id,
                        timestamp,
                        score,
                        len(finding_list),
                        serialized_payload,
                    ),
                )
                self._upsert_findings(connection, monitor.id, finding_list, timestamp)
                self._resolve_missing_findings(connection, monitor.id, identities, timestamp)
                connection.execute(
                    """
                    UPDATE monitors
                    SET next_run_at = ?, claimed_until = NULL, claim_token = NULL,
                        updated_at = ?
                    WHERE id = ? AND claim_token = ?
                    """,
                    (next_run, timestamp, monitor.id, claim.token),
                )
                self._prune(connection, now)
                connection.execute("COMMIT")
            except sqlite3.Error as error:
                connection.execute("ROLLBACK")
                raise StateConflictError("monitor result could not be persisted") from error
        return MonitorSnapshot(
            snapshot_id,
            monitor.id,
            now.astimezone(UTC),
            score,
            len(finding_list),
            payload,
        )

    def release_claim(self, claim: MonitorClaim) -> None:
        with self._lock, closing(self._connect()) as connection:
            connection.execute(
                """
                UPDATE monitors SET claimed_until = NULL, claim_token = NULL
                WHERE id = ? AND claim_token = ?
                """,
                (claim.monitor.id, claim.token),
            )

    def list_snapshots(
        self,
        monitor_id: str,
        limit: int,
        offset: int,
    ) -> StatePage[MonitorSnapshot]:
        self.get_monitor(monitor_id)
        _validate_page(limit, offset)
        with self._lock, closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT * FROM snapshots WHERE monitor_id = ?
                ORDER BY observed_at DESC, id DESC LIMIT ? OFFSET ?
                """,
                (monitor_id, limit + 1, offset),
            ).fetchall()
        return StatePage(tuple(_snapshot(row) for row in rows[:limit]), len(rows) > limit)

    def list_issues(
        self,
        monitor_id: str,
        status: IssueStatus | None,
        limit: int,
        offset: int,
    ) -> StatePage[TrackedIssue]:
        self.get_monitor(monitor_id)
        _validate_page(limit, offset)
        parameters: tuple[object, ...] = (monitor_id, limit + 1, offset)
        query = """
            SELECT * FROM issues WHERE monitor_id = ?
            ORDER BY last_seen_at DESC, id DESC LIMIT ? OFFSET ?
        """
        if status is not None:
            query = """
                SELECT * FROM issues WHERE monitor_id = ? AND status = ?
                ORDER BY last_seen_at DESC, id DESC LIMIT ? OFFSET ?
            """
            parameters = (monitor_id, status.value, limit + 1, offset)
        with self._lock, closing(self._connect()) as connection:
            rows = connection.execute(query, parameters).fetchall()
        return StatePage(tuple(_issue(row) for row in rows[:limit]), len(rows) > limit)

    def get_issue(self, issue_id: str) -> TrackedIssue:
        with self._lock, closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM issues WHERE id = ?",
                (issue_id,),
            ).fetchone()
        if row is None:
            raise StateNotFoundError("issue not found")
        return _issue(row)

    def set_issue_status(
        self,
        issue_id: str,
        status: IssueStatus,
        now: datetime,
    ) -> TrackedIssue:
        timestamp = _timestamp(now)
        resolved_at = timestamp if status is IssueStatus.RESOLVED else None
        with self._lock, closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            current = connection.execute(
                "SELECT * FROM issues WHERE id = ?",
                (issue_id,),
            ).fetchone()
            if current is None:
                connection.execute("COMMIT")
                raise StateNotFoundError("issue not found")
            if IssueStatus(cast(str, current["status"])) is status:
                connection.execute("COMMIT")
                return _issue(current)
            result = connection.execute(
                "UPDATE issues SET status = ?, resolved_at = ? WHERE id = ?",
                (status.value, resolved_at, issue_id),
            )
            if result.rowcount == 1:
                connection.execute(
                    "INSERT INTO issue_events(issue_id, event, occurred_at) VALUES (?, ?, ?)",
                    (issue_id, status.value, timestamp),
                )
            connection.execute("COMMIT")
            row = connection.execute("SELECT * FROM issues WHERE id = ?", (issue_id,)).fetchone()
        if row is None:
            raise StateNotFoundError("issue not found")
        return _issue(row)

    def list_issue_events(
        self,
        issue_id: str,
        limit: int,
        offset: int,
    ) -> StatePage[IssueEvent]:
        _validate_page(limit, offset)
        with self._lock, closing(self._connect()) as connection:
            issue_exists = connection.execute(
                "SELECT 1 FROM issues WHERE id = ?",
                (issue_id,),
            ).fetchone()
            if issue_exists is None:
                raise StateNotFoundError("issue not found")
            rows = connection.execute(
                """
                SELECT * FROM issue_events WHERE issue_id = ?
                ORDER BY occurred_at DESC, id DESC LIMIT ? OFFSET ?
                """,
                (issue_id, limit + 1, offset),
            ).fetchall()
        return StatePage(tuple(_event(row) for row in rows[:limit]), len(rows) > limit)

    @staticmethod
    def _upsert_findings(
        connection: sqlite3.Connection,
        monitor_id: str,
        findings: tuple[PersistedFinding, ...],
        timestamp: str,
    ) -> None:
        for finding in findings:
            existing = connection.execute(
                "SELECT id, status FROM issues WHERE monitor_id = ? AND identity = ?",
                (monitor_id, finding.identity),
            ).fetchone()
            if existing is None:
                issue_id = str(uuid.uuid4())
                connection.execute(
                    """
                    INSERT INTO issues(
                        id, monitor_id, identity, code, resource, severity, message,
                        remediation, status, observations, first_seen_at, last_seen_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        issue_id,
                        monitor_id,
                        finding.identity,
                        finding.code,
                        finding.resource,
                        finding.severity,
                        finding.message,
                        finding.remediation,
                        IssueStatus.OPEN.value,
                        1,
                        timestamp,
                        timestamp,
                    ),
                )
                connection.execute(
                    "INSERT INTO issue_events(issue_id, event, occurred_at) VALUES (?, ?, ?)",
                    (issue_id, "opened", timestamp),
                )
                continue
            prior_status = IssueStatus(cast(str, existing["status"]))
            new_status = IssueStatus.OPEN if prior_status is IssueStatus.RESOLVED else prior_status
            connection.execute(
                """
                UPDATE issues SET severity = ?, message = ?, remediation = ?,
                    status = ?, observations = observations + 1,
                    last_seen_at = ?, resolved_at = NULL
                WHERE id = ?
                """,
                (
                    finding.severity,
                    finding.message,
                    finding.remediation,
                    new_status.value,
                    timestamp,
                    existing["id"],
                ),
            )
            event = "reopened" if prior_status is IssueStatus.RESOLVED else "observed"
            connection.execute(
                "INSERT INTO issue_events(issue_id, event, occurred_at) VALUES (?, ?, ?)",
                (existing["id"], event, timestamp),
            )

    @staticmethod
    def _resolve_missing_findings(
        connection: sqlite3.Connection,
        monitor_id: str,
        identities: tuple[str, ...],
        timestamp: str,
    ) -> None:
        rows = connection.execute(
            "SELECT id, identity FROM issues WHERE monitor_id = ? AND status != ?",
            (monitor_id, IssueStatus.RESOLVED.value),
        ).fetchall()
        observed = frozenset(identities)
        for row in rows:
            if row["identity"] in observed:
                continue
            connection.execute(
                "UPDATE issues SET status = ?, resolved_at = ? WHERE id = ?",
                (IssueStatus.RESOLVED.value, timestamp, row["id"]),
            )
            connection.execute(
                "INSERT INTO issue_events(issue_id, event, occurred_at) VALUES (?, ?, ?)",
                (row["id"], "resolved", timestamp),
            )

    def _prune(self, connection: sqlite3.Connection, now: datetime) -> None:
        cutoff = _timestamp(now - timedelta(days=self._retention_days))
        connection.execute("DELETE FROM snapshots WHERE observed_at < ?", (cutoff,))
        connection.execute("DELETE FROM issue_events WHERE occurred_at < ?", (cutoff,))


def _validate_page(limit: int, offset: int) -> None:
    if not 1 <= limit <= MAX_STATE_PAGE_SIZE:
        raise InputLimitError("state page limit is outside the allowed range")
    if offset < 0:
        raise InputLimitError("state page offset must not be negative")


def _timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("state timestamps must be timezone-aware")
    return value.astimezone(UTC).isoformat()


def _open_safe_directory(path: Path) -> int:
    descriptor = os.open("/", _DIRECTORY_OPEN_FLAGS)
    try:
        for component in path.parts[1:]:
            next_descriptor = os.open(
                component,
                _DIRECTORY_OPEN_FLAGS,
                dir_fd=descriptor,
            )
            os.close(descriptor)
            descriptor = next_descriptor
    except OSError:
        os.close(descriptor)
        raise
    return descriptor


def _create_state_file(parent_descriptor: int, name: str) -> None:
    try:
        descriptor = os.open(
            name,
            _FILE_CREATE_FLAGS,
            _FILE_MODE,
            dir_fd=parent_descriptor,
        )
    except OSError as error:
        raise ConfigurationError("state database file could not be created") from error
    os.close(descriptor)


def _datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("stored state timestamp must include a timezone")
    return parsed


def _monitor(row: sqlite3.Row) -> MonitorDefinition:
    try:
        return MonitorDefinition(
            id=cast(str, row["id"]),
            name=cast(str, row["name"]),
            kind=MonitorKind(cast(str, row["kind"])),
            account_id=cast(str, row["account_id"]),
            site_url=cast(str, row["site_url"]),
            interval_seconds=cast(int, row["interval_seconds"]),
            enabled=bool(row["enabled"]),
            next_run_at=cast(datetime, _datetime(cast(str, row["next_run_at"]))),
            created_at=cast(datetime, _datetime(cast(str, row["created_at"]))),
            updated_at=cast(datetime, _datetime(cast(str, row["updated_at"]))),
        )
    except (TypeError, ValueError) as error:
        raise StateConflictError("stored monitor row is invalid") from error


def _snapshot(row: sqlite3.Row) -> MonitorSnapshot:
    try:
        raw_payload = json.loads(cast(str, row["payload"]))
        if not isinstance(raw_payload, dict):
            raise TypeError("snapshot payload is not an object")
        payload = cast(dict[str, object], raw_payload)
        return MonitorSnapshot(
            id=cast(str, row["id"]),
            monitor_id=cast(str, row["monitor_id"]),
            observed_at=cast(datetime, _datetime(cast(str, row["observed_at"]))),
            score=cast(int, row["score"]),
            issue_count=cast(int, row["issue_count"]),
            payload=payload,
        )
    except (json.JSONDecodeError, TypeError, ValueError) as error:
        raise StateConflictError("stored snapshot payload is invalid") from error


def _issue(row: sqlite3.Row) -> TrackedIssue:
    try:
        return TrackedIssue(
            id=cast(str, row["id"]),
            monitor_id=cast(str, row["monitor_id"]),
            identity=cast(str, row["identity"]),
            code=cast(str, row["code"]),
            resource=cast(str, row["resource"]),
            severity=cast(str, row["severity"]),
            message=cast(str, row["message"]),
            remediation=cast(str, row["remediation"]),
            status=IssueStatus(cast(str, row["status"])),
            observations=cast(int, row["observations"]),
            first_seen_at=cast(datetime, _datetime(cast(str, row["first_seen_at"]))),
            last_seen_at=cast(datetime, _datetime(cast(str, row["last_seen_at"]))),
            resolved_at=_datetime(cast(str | None, row["resolved_at"])),
        )
    except (TypeError, ValueError) as error:
        raise StateConflictError("stored issue row is invalid") from error


def _event(row: sqlite3.Row) -> IssueEvent:
    try:
        return IssueEvent(
            id=cast(int, row["id"]),
            issue_id=cast(str, row["issue_id"]),
            event=cast(str, row["event"]),
            occurred_at=cast(datetime, _datetime(cast(str, row["occurred_at"]))),
        )
    except (TypeError, ValueError) as error:
        raise StateConflictError("stored issue event row is invalid") from error
