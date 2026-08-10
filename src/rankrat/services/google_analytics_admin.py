"""Read and rename GA4 containers the configured credential can administer.

Reads use the same account credential and discovered property inventory as the
other GA4 tools.
Renames are the only mutation here: the Admin API also exposes account and
property deletion, which is deliberately not wrapped — `accounts.delete`
soft-deletes an entire container and everything beneath it, and no report this
server serves is worth putting that one call behind an agent-reachable tool.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from rankrat.errors import InputLimitError
from rankrat.models.boundaries import ACCOUNT_ID_PATTERN
from rankrat.policy.boundaries import BoundaryPolicy
from rankrat.providers.base import AccountId, ProviderReadRequest
from rankrat.providers.google_analytics_admin import (
    Ga4DataStream,
    Ga4RenamedResource,
    GoogleAnalyticsAdminClient,
)

_DEFAULT_TIMEOUT_SECONDS = 10.0
_GA4_RESOURCE_ID_PATTERN = re.compile(r"^[0-9]+$")
_MIN_DISPLAY_NAME_CHARS = 1
_MAX_DISPLAY_NAME_CHARS = 255


def _require_account_id(value: str) -> None:
    if re.fullmatch(ACCOUNT_ID_PATTERN, value) is None:
        raise InputLimitError("account_id has an invalid format")


def _require_ga4_resource_id(value: str, kind: str) -> None:
    if _GA4_RESOURCE_ID_PATTERN.fullmatch(value) is None:
        raise InputLimitError(f"{kind} must be a numeric Google Analytics ID")


def _require_display_name(value: str) -> None:
    if not _MIN_DISPLAY_NAME_CHARS <= len(value) <= _MAX_DISPLAY_NAME_CHARS:
        raise InputLimitError("display_name has an invalid length")
    if value.strip() != value or not value.strip():
        raise InputLimitError("display_name must not be padded or blank")


@dataclass(frozen=True, slots=True)
class Ga4DataStreamsRequest:
    """List the data streams of one configured GA4 property."""

    account_id: str
    property_id: str
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        _require_account_id(self.account_id)
        _require_ga4_resource_id(self.property_id, "property_id")


@dataclass(frozen=True, slots=True)
class Ga4DataStreamsReport:
    """Every stream on one property, with the measurement ID of each web stream."""

    property_id: str
    streams: tuple[Ga4DataStream, ...] = field(default_factory=tuple[Ga4DataStream, ...])


@dataclass(frozen=True, slots=True)
class Ga4AccountRenameRequest:
    """Rename one GA4 account reachable by the configured credential."""

    account_id: str
    analytics_account_id: str
    display_name: str
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        _require_account_id(self.account_id)
        _require_ga4_resource_id(self.analytics_account_id, "analytics_account_id")
        _require_display_name(self.display_name)


@dataclass(frozen=True, slots=True)
class Ga4PropertyRenameRequest:
    """Rename one configured GA4 property."""

    account_id: str
    property_id: str
    display_name: str
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        _require_account_id(self.account_id)
        _require_ga4_resource_id(self.property_id, "property_id")
        _require_display_name(self.display_name)


class GoogleAnalyticsAdminService:
    """Application layer for GA4 container reads and renames."""

    def __init__(self, policy: BoundaryPolicy, client: GoogleAnalyticsAdminClient) -> None:
        self._policy = policy
        self._client = client

    async def list_data_streams(self, request: Ga4DataStreamsRequest) -> Ga4DataStreamsReport:
        """Return one configured property's streams so a tag can be matched to it."""

        streams = await self._client.list_data_streams(
            ProviderReadRequest(AccountId(request.account_id), request.timeout_seconds),
            request.property_id,
        )
        return Ga4DataStreamsReport(property_id=request.property_id, streams=streams)

    async def rename_account(self, request: Ga4AccountRenameRequest) -> Ga4RenamedResource:
        """Rename one GA4 account, gated by the account-discovery switch."""

        return await self._client.update_account_display_name(
            ProviderReadRequest(AccountId(request.account_id), request.timeout_seconds),
            request.analytics_account_id,
            request.display_name,
        )

    async def rename_property(self, request: Ga4PropertyRenameRequest) -> Ga4RenamedResource:
        """Rename one configured GA4 property."""

        return await self._client.update_property_display_name(
            ProviderReadRequest(AccountId(request.account_id), request.timeout_seconds),
            request.property_id,
            request.display_name,
        )
