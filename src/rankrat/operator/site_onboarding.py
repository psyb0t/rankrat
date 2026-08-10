"""Boundary-limited provisioning of one newly launched website."""

from __future__ import annotations

import json
import os
import re
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import ValidationError

from rankrat.constants import (
    DEFAULT_PROVIDER_TIMEOUT_SECONDS,
    ISO_CURRENCY_CODE_CHARS,
    MAX_BOUNDARY_FILE_BYTES,
    MAX_SITE_ONBOARDING_DISPLAY_NAME_CHARS,
    MAX_SITE_ONBOARDING_TIME_ZONE_CHARS,
)
from rankrat.errors import ConfigurationError, InputLimitError, RankratError
from rankrat.models.boundaries import (
    BoundaryDocument,
    ConfiguredAccount,
    Provider,
    normalize_public_https_root_url,
)
from rankrat.policy.boundaries import BoundaryPolicy
from rankrat.providers.base import AccountId, ProviderOperationError, ProviderReadRequest
from rankrat.providers.bing import BingWebmasterClient
from rankrat.providers.google_analytics import Ga4AccountSummary, GoogleAnalyticsDataClient
from rankrat.providers.google_analytics_admin import (
    Ga4SiteProperty,
    Ga4SitePropertyCreateRequest,
    GoogleAnalyticsAdminClient,
)
from rankrat.providers.google_search_console import GoogleSearchConsoleClient

_CURRENCY_CODE_PATTERN = re.compile(r"^[A-Z]{3}$")
_NO_FOLLOW_FLAG = getattr(os, "O_NOFOLLOW", None)
_OWNER_ONLY_MODE_MASK = 0o077
_OWNER_WRITABLE_MODE_MASK = 0o022
_CONFIG_FILE_MODE = 0o600


class SiteOnboardingPartialError(RankratError):
    """A bounded receipt for a provider failure after an earlier remote write succeeded."""

    def __init__(self, completed_stages: tuple[str, ...]) -> None:
        super().__init__("site onboarding partially completed")
        self.completed_stages = completed_stages


@dataclass(frozen=True, slots=True)
class SiteOnboardingRequest:
    """One validated operator request for a public site root."""

    google_account_id: str | None
    bing_account_id: str | None
    site_url: str
    google_analytics_parent_account_id: str | None = None
    display_name: str | None = None
    time_zone: str = "Etc/UTC"
    currency_code: str = "USD"
    timeout_seconds: float = DEFAULT_PROVIDER_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        normalized_url = normalize_public_https_root_url(self.site_url, "site_url")
        parsed = urlparse(normalized_url)
        host = parsed.hostname
        if host is None:
            raise InputLimitError("site_url must include a hostname")
        display_name = self.display_name.strip() if self.display_name is not None else host
        if not display_name or len(display_name) > MAX_SITE_ONBOARDING_DISPLAY_NAME_CHARS:
            raise InputLimitError("site onboarding display_name has an invalid length")
        time_zone = self.time_zone.strip()
        if not time_zone or len(time_zone) > MAX_SITE_ONBOARDING_TIME_ZONE_CHARS:
            raise InputLimitError("site onboarding time_zone has an invalid length")
        try:
            ZoneInfo(time_zone)
        except ZoneInfoNotFoundError as error:
            raise InputLimitError("site onboarding time_zone must be an IANA time zone") from error
        currency_code = self.currency_code.strip().upper()
        if (
            len(currency_code) != ISO_CURRENCY_CODE_CHARS
            or _CURRENCY_CODE_PATTERN.fullmatch(currency_code) is None
        ):
            raise InputLimitError("site onboarding currency_code must be an ISO 4217 code")
        object.__setattr__(self, "site_url", normalized_url)
        object.__setattr__(self, "display_name", display_name)
        object.__setattr__(self, "time_zone", time_zone)
        object.__setattr__(self, "currency_code", currency_code)
        parent_account_id = self.google_analytics_parent_account_id
        if parent_account_id is not None:
            normalized_parent_account_id = parent_account_id.strip()
            if not normalized_parent_account_id.isdigit():
                raise InputLimitError("Google Analytics parent account ID must be numeric")
            object.__setattr__(
                self,
                "google_analytics_parent_account_id",
                normalized_parent_account_id,
            )


@dataclass(frozen=True, slots=True)
class SiteOnboardingReceipt:
    """Safe local-operator receipt with no credential, token, or provider-body fields."""

    site_url: str
    ga4_property_id: str
    ga4_measurement_id: str
    google_search_console_added: bool
    bing_added: bool
    boundary_updated: bool
    google_account_id: str = ""
    bing_account_id: str = ""
    ga4_created: bool = False


class SiteOnboardingOperator:
    """Provision one site only through configured accounts and fixed provider origins."""

    def __init__(
        self,
        boundary_file: Path,
        policy: BoundaryPolicy,
        google_analytics: GoogleAnalyticsAdminClient,
        google_analytics_inventory: GoogleAnalyticsDataClient,
        google_search_console: GoogleSearchConsoleClient,
        bing: BingWebmasterClient,
    ) -> None:
        self._boundary_file = boundary_file
        self._policy = policy
        self._google_analytics = google_analytics
        self._google_analytics_inventory = google_analytics_inventory
        self._google_search_console = google_search_console
        self._bing = bing

    async def onboard(self, request: SiteOnboardingRequest) -> SiteOnboardingReceipt:
        """Create provider resources, then atomically persist their exact local boundaries."""

        google_account = self._policy.select_account(
            Provider.GOOGLE,
            request.google_account_id,
        )
        bing_account = self._policy.select_account(
            Provider.BING,
            request.bing_account_id,
        )
        display_name = request.display_name
        if display_name is None:
            raise RuntimeError("site onboarding request is missing a display name")

        completed_stages: list[str] = []
        try:
            property_result, ga4_created = await self._resolve_ga4_site(
                google_account.id,
                request,
                display_name,
            )
            completed_stages.append("google_analytics")
            google_provider_request = ProviderReadRequest(
                AccountId(google_account.id),
                request.timeout_seconds,
            )
            google_sites = await self._google_search_console.list_sites(google_provider_request)
            google_search_console_added = request.site_url not in google_sites
            if google_search_console_added:
                await self._google_search_console.add_site_for_onboarding(
                    google_provider_request,
                    request.site_url,
                )
            completed_stages.append("google_search_console")
            bing_provider_request = ProviderReadRequest(
                AccountId(bing_account.id),
                request.timeout_seconds,
            )
            bing_sites = await self._bing.list_sites(bing_provider_request)
            bing_added = request.site_url not in bing_sites
            if bing_added:
                await self._bing.add_site_for_onboarding(
                    bing_provider_request,
                    request.site_url,
                )
            completed_stages.append("bing")
        except (ProviderOperationError, RankratError) as error:
            if completed_stages:
                raise SiteOnboardingPartialError(tuple(completed_stages)) from error
            raise

        self._persist_boundary_update(
            google_account.id,
            bing_account.id,
            request.site_url,
            property_result,
        )
        return SiteOnboardingReceipt(
            site_url=request.site_url,
            ga4_property_id=property_result.property_id,
            ga4_measurement_id=property_result.measurement_id,
            google_search_console_added=google_search_console_added,
            bing_added=bing_added,
            boundary_updated=True,
            google_account_id=google_account.id,
            bing_account_id=bing_account.id,
            ga4_created=ga4_created,
        )

    async def _resolve_ga4_site(
        self,
        google_account_id: str,
        request: SiteOnboardingRequest,
        display_name: str,
    ) -> tuple[Ga4SiteProperty, bool]:
        provider_request = ProviderReadRequest(
            AccountId(google_account_id),
            request.timeout_seconds,
        )
        account_summaries = await self._google_analytics_inventory.list_account_summaries(
            provider_request
        )
        parent_account_id = _select_analytics_parent_account(
            account_summaries,
            request.google_analytics_parent_account_id,
        )
        matches: list[Ga4SiteProperty] = []
        for account_summary in account_summaries:
            for property_summary in account_summary.properties:
                streams = await self._google_analytics.list_data_streams(
                    provider_request,
                    property_summary.property_id,
                )
                for stream in streams:
                    if stream.default_uri is None or stream.measurement_id is None:
                        continue
                    try:
                        stream_url = normalize_public_https_root_url(
                            stream.default_uri,
                            "Google Analytics data stream URI",
                        )
                    except ValueError:
                        continue
                    if stream_url == request.site_url:
                        matches.append(
                            Ga4SiteProperty(property_summary.property_id, stream.measurement_id)
                        )
        if len(matches) > 1:
            raise ConfigurationError("multiple GA4 web streams already target this site")
        if matches:
            return matches[0], False
        property_result = await self._google_analytics.create_site_property(
            provider_request,
            Ga4SitePropertyCreateRequest(
                account_id=google_account_id,
                parent_account_id=parent_account_id,
                display_name=display_name,
                site_url=request.site_url,
                time_zone=request.time_zone,
                currency_code=request.currency_code,
            ),
        )
        return property_result, True

    def _persist_boundary_update(
        self,
        google_account_id: str,
        bing_account_id: str,
        site_url: str,
        property_result: Ga4SiteProperty,
    ) -> None:
        document = _read_owner_writable_boundary_document(self._boundary_file)
        updated_accounts = tuple(
            _updated_account(
                account,
                google_account_id,
                bing_account_id,
                site_url,
                property_result.property_id,
            )
            for account in document.accounts
        )
        updated_document = BoundaryDocument.model_validate(
            document.model_dump(mode="json", by_alias=True) | {"accounts": updated_accounts}
        )
        _write_boundary_document(self._boundary_file, updated_document)


def _updated_account(
    account: ConfiguredAccount,
    google_account_id: str,
    bing_account_id: str,
    site_url: str,
    property_id: str,
) -> ConfiguredAccount:
    if account.id == google_account_id:
        update: dict[str, object] = {
            "search_console_sites": _append_unique(account.search_console_sites, site_url),
            "ga4_properties": _append_unique(account.ga4_properties, property_id),
        }
        if account.pagespeed_api_key_file is not None:
            update["pagespeed_sites"] = _append_unique(account.pagespeed_sites, site_url)
        return account.model_copy(update=update)
    if account.id == bing_account_id:
        return account.model_copy(
            update={"bing_sites": _append_unique(account.bing_sites, site_url)}
        )
    return account


def _select_analytics_parent_account(
    account_summaries: tuple[Ga4AccountSummary, ...],
    requested_account_id: str | None,
) -> str:
    if requested_account_id is not None:
        if any(summary.account_id == requested_account_id for summary in account_summaries):
            return requested_account_id
        raise ConfigurationError("requested Google Analytics account is not reachable")
    if len(account_summaries) == 1:
        return account_summaries[0].account_id
    if not account_summaries:
        raise ConfigurationError("Google Analytics has no reachable account")
    raise ConfigurationError(
        "multiple Google Analytics accounts are reachable; parent account ID is required"
    )


def _append_unique(values: tuple[str, ...], value: str) -> tuple[str, ...]:
    if value in values:
        return values
    return (*values, value)


def _read_owner_writable_boundary_document(path: Path) -> BoundaryDocument:
    """Read the local boundary file through a no-follow owner-controlled descriptor."""

    if _NO_FOLLOW_FLAG is None:
        raise ConfigurationError("site onboarding requires no-follow filesystem support")
    try:
        descriptor = os.open(path, os.O_RDONLY | _NO_FOLLOW_FLAG)
        try:
            metadata = os.fstat(descriptor)
            _require_owner_writable_regular_file(metadata)
            content = _read_descriptor(descriptor, MAX_BOUNDARY_FILE_BYTES)
        finally:
            os.close(descriptor)
        return BoundaryDocument.model_validate_json(content)
    except (OSError, ValidationError, ValueError) as error:
        raise ConfigurationError("site onboarding boundary configuration is invalid") from error


def _write_boundary_document(path: Path, document: BoundaryDocument) -> None:
    """Atomically replace the owner-controlled boundary file without following links."""

    if _NO_FOLLOW_FLAG is None:
        raise ConfigurationError("site onboarding requires no-follow filesystem support")
    temporary_path: str | None = None
    try:
        parent = path.parent
        directory_metadata = parent.stat()
        _require_owner_writable_directory(directory_metadata)
        payload = (
            json.dumps(
                document.model_dump(mode="json", by_alias=True),
                indent=2,
                sort_keys=True,
            ).encode("utf-8")
            + b"\n"
        )
        if len(payload) > MAX_BOUNDARY_FILE_BYTES:
            raise ValueError("boundary configuration exceeds the allowed size")
        descriptor, temporary_path = tempfile.mkstemp(prefix=f".{path.name}.", dir=parent)
        try:
            os.fchmod(descriptor, _CONFIG_FILE_MODE)
            _write_all(descriptor, payload)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.replace(temporary_path, path)
        temporary_path = None
        directory_descriptor = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    except (OSError, ValueError) as error:
        if temporary_path is not None:
            try:
                os.unlink(temporary_path)
            except OSError as cleanup_error:
                raise ConfigurationError(
                    "site onboarding boundary update cleanup failed"
                ) from cleanup_error
        raise ConfigurationError("site onboarding boundary update failed") from error


def _require_owner_writable_regular_file(metadata: os.stat_result) -> None:
    if not stat.S_ISREG(metadata.st_mode):
        raise ValueError("boundary configuration is not a regular file")
    if metadata.st_uid != os.geteuid() or metadata.st_mode & _OWNER_WRITABLE_MODE_MASK:
        raise ValueError("boundary configuration permissions are unsafe")


def _require_owner_writable_directory(metadata: os.stat_result) -> None:
    if not stat.S_ISDIR(metadata.st_mode):
        raise ValueError("boundary configuration parent is not a directory")
    if metadata.st_uid != os.geteuid() or metadata.st_mode & _OWNER_ONLY_MODE_MASK:
        raise ValueError("boundary configuration directory permissions are unsafe")


def _read_descriptor(descriptor: int, limit: int) -> bytes:
    content = bytearray()
    while True:
        chunk = os.read(descriptor, min(65_536, limit + 1 - len(content)))
        if not chunk:
            return bytes(content)
        content.extend(chunk)
        if len(content) > limit:
            raise ValueError("boundary configuration exceeds the allowed size")


def _write_all(descriptor: int, payload: bytes) -> None:
    written = 0
    while written < len(payload):
        count = os.write(descriptor, payload[written:])
        if count <= 0:
            raise OSError("boundary configuration write failed")
        written += count
