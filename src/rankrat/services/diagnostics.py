"""Read-only local diagnostics with no provider health traffic."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from rankrat.models.boundaries import Provider
from rankrat.policy.boundaries import BoundaryPolicy

_CONFIGURATION_CHECK_NAME = "configuration"
_PROVIDER_CHECK_NAME = "provider_calls"
_CONFIGURATION_DETAIL = "immutable boundaries loaded"
_PROVIDER_DETAIL = "not checked in the read-only foundation"


class DiagnosticStatus(StrEnum):
    """Stable state for diagnostics that cannot disclose provider details."""

    PASS = "PASS"  # nosec B105  # noqa: S105 - diagnostic state, not a password
    NOT_CHECKED = "NOT_CHECKED"


@dataclass(frozen=True, slots=True)
class DiagnosticsRequest:
    """Input for the parameter-free local diagnostics operation."""


@dataclass(frozen=True, slots=True)
class DiagnosticCheck:
    """A local diagnostic result without an upstream payload or URL."""

    name: str
    status: DiagnosticStatus
    detail: str


@dataclass(frozen=True, slots=True)
class DiagnosticsResponse:
    """Readiness evidence based only on immutable local configuration."""

    ready: bool
    configured_account_count: int
    configured_providers: tuple[Provider, ...]
    checks: tuple[DiagnosticCheck, ...]


class DiagnosticsService:
    """Reports local configuration readiness without using provider clients."""

    def __init__(self, policy: BoundaryPolicy) -> None:
        self._policy = policy

    def diagnostics(self, request: DiagnosticsRequest) -> DiagnosticsResponse:
        """Return local checks; provider reachability remains intentionally absent."""
        del request
        accounts = self._policy.accounts()
        providers = tuple(
            provider
            for provider in Provider
            if any(account.provider == provider for account in accounts)
        )
        return DiagnosticsResponse(
            ready=True,
            configured_account_count=len(accounts),
            configured_providers=providers,
            checks=(
                DiagnosticCheck(
                    name=_CONFIGURATION_CHECK_NAME,
                    status=DiagnosticStatus.PASS,
                    detail=_CONFIGURATION_DETAIL,
                ),
                DiagnosticCheck(
                    name=_PROVIDER_CHECK_NAME,
                    status=DiagnosticStatus.NOT_CHECKED,
                    detail=_PROVIDER_DETAIL,
                ),
            ),
        )
