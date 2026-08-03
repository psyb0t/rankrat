"""In-memory, single-use approvals for explicitly enabled provider writes."""

from __future__ import annotations

import asyncio
import hashlib
import json
import secrets
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from rankrat.errors import ApprovalDeniedError, InputLimitError
from rankrat.models.common import JsonValue

_MAX_APPROVAL_LIFETIME_SECONDS = 60.0
_TOKEN_BYTES = 32


@dataclass(frozen=True, slots=True)
class WriteApprovalRequest:
    """The exact write intent an administrator can approve once."""

    operation: str
    account_id: str
    resource: str
    arguments: Mapping[str, JsonValue]

    def __post_init__(self) -> None:
        if not self.operation or not self.account_id or not self.resource:
            raise InputLimitError("write approval requires operation, account, and resource")


@dataclass(frozen=True, slots=True)
class WriteApproval:
    """Opaque, short-lived approval returned only by an administrative surface."""

    approval_id: str


@dataclass(frozen=True, slots=True)
class _StoredApproval:
    operation: str
    account_id: str
    resource: str
    arguments_hash: str
    expires_at: float


class WriteApprovalStore:
    """Atomically mints and consumes short-lived, exact-match write approvals."""

    def __init__(
        self,
        monotonic_clock: Callable[[], float] = time.monotonic,
        token_factory: Callable[[int], str] = secrets.token_urlsafe,
        maximum_lifetime_seconds: float = _MAX_APPROVAL_LIFETIME_SECONDS,
    ) -> None:
        if maximum_lifetime_seconds <= 0:
            raise ValueError("maximum approval lifetime must be positive")
        self._monotonic_clock = monotonic_clock
        self._token_factory = token_factory
        self._maximum_lifetime_seconds = maximum_lifetime_seconds
        self._approvals: dict[str, _StoredApproval] = {}
        self._lock = asyncio.Lock()

    async def mint(
        self,
        request: WriteApprovalRequest,
        lifetime_seconds: float = _MAX_APPROVAL_LIFETIME_SECONDS,
    ) -> WriteApproval:
        """Mint one opaque approval limited to the exact requested write intent."""

        if not 0 < lifetime_seconds <= self._maximum_lifetime_seconds:
            raise InputLimitError("write approval lifetime is outside the allowed range")
        approval_id = self._token_factory(_TOKEN_BYTES)
        if not approval_id:
            raise RuntimeError("approval token factory returned an empty token")
        stored = _StoredApproval(
            request.operation,
            request.account_id,
            request.resource,
            self._arguments_hash(request.arguments),
            self._monotonic_clock() + lifetime_seconds,
        )
        async with self._lock:
            self._prune_expired(self._monotonic_clock())
            self._approvals[approval_id] = stored
        return WriteApproval(approval_id)

    async def consume(self, approval_id: str, request: WriteApprovalRequest) -> None:
        """Atomically consume an approval only when every bound value matches."""

        if not approval_id:
            raise ApprovalDeniedError("write approval was rejected")
        async with self._lock:
            now = self._monotonic_clock()
            self._prune_expired(now)
            stored = self._approvals.pop(approval_id, None)
            if stored is None or not self._matches(stored, request):
                raise ApprovalDeniedError("write approval was rejected")

    @staticmethod
    def _arguments_hash(arguments: Mapping[str, JsonValue]) -> str:
        try:
            canonical = json.dumps(
                arguments,
                allow_nan=False,
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            )
        except (TypeError, ValueError) as error:
            raise InputLimitError("write approval arguments must be JSON values") from error
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @classmethod
    def _matches(cls, stored: _StoredApproval, request: WriteApprovalRequest) -> bool:
        return (
            stored.operation == request.operation
            and stored.account_id == request.account_id
            and stored.resource == request.resource
            and stored.arguments_hash == cls._arguments_hash(request.arguments)
        )

    def _prune_expired(self, now: float) -> None:
        expired_ids = [
            approval_id
            for approval_id, approval in self._approvals.items()
            if approval.expires_at <= now
        ]
        for approval_id in expired_ids:
            del self._approvals[approval_id]
