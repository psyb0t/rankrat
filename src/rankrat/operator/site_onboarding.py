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
    normalize_public_https_root_url,
)
from rankrat.policy.boundaries import BoundaryPolicy
from rankrat.providers.base import AccountId, ProviderOperationError, ProviderReadRequest
from rankrat.providers.bing import BingWebmasterClient
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

    google_account_id: str
    bing_account_id: str
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


class SiteOnboardingOperator:
    """Provision one site only through configured accounts and fixed provider origins."""

    def __init__(
        self,
        boundary_file: Path,
        policy: BoundaryPolicy,
        google_analytics: GoogleAnalyticsAdminClient,
        google_search_console: GoogleSearchConsoleClient,
        bing: BingWebmasterClient,
    ) -> None:
        self._boundary_file = boundary_file
        self._policy = policy
        self._google_analytics = google_analytics
        self._google_search_console = google_search_console
        self._bing = bing

    async def onboard(self, request: SiteOnboardingRequest) -> SiteOnboardingReceipt:
        """Create provider resources, then atomically persist their exact local boundaries."""

        parent_account_id = self.validate_request(request)
        display_name = request.display_name
        if display_name is None:
            raise RuntimeError("site onboarding request is missing a display name")

        completed_stages: list[str] = []
        try:
            property_result = await self._google_analytics.create_site_property(
                ProviderReadRequest(AccountId(request.google_account_id), request.timeout_seconds),
                Ga4SitePropertyCreateRequest(
                    account_id=request.google_account_id,
                    parent_account_id=parent_account_id,
                    display_name=display_name,
                    site_url=request.site_url,
                    time_zone=request.time_zone,
                    currency_code=request.currency_code,
                ),
            )
            completed_stages.append("google_analytics")
            await self._google_search_console.add_site_for_onboarding(
                ProviderReadRequest(AccountId(request.google_account_id), request.timeout_seconds),
                request.site_url,
            )
            completed_stages.append("google_search_console")
            await self._bing.add_site_for_onboarding(
                ProviderReadRequest(AccountId(request.bing_account_id), request.timeout_seconds),
                request.site_url,
            )
            completed_stages.append("bing")
        except (ProviderOperationError, RankratError) as error:
            if completed_stages:
                raise SiteOnboardingPartialError(tuple(completed_stages)) from error
            raise

        self._persist_boundary_update(
            request.google_account_id,
            request.bing_account_id,
            request.site_url,
            property_result,
        )
        return SiteOnboardingReceipt(
            site_url=request.site_url,
            ga4_property_id=property_result.property_id,
            ga4_measurement_id=property_result.measurement_id,
            google_search_console_added=True,
            bing_added=True,
            boundary_updated=True,
        )

    def validate_request(self, request: SiteOnboardingRequest) -> str:
        """Validate one requested site before any provider write occurs."""

        google_account = self._policy.require_google_onboarding_account(request.google_account_id)
        bing_account = self._policy.require_bing_onboarding_account(request.bing_account_id)
        self._assert_new_site(google_account, bing_account, request.site_url)
        parent_account_id = request.google_analytics_parent_account_id
        if parent_account_id is None:
            raise ConfigurationError(
                "Google onboarding requires google_analytics_parent_account_id"
            )
        return parent_account_id

    @staticmethod
    def _assert_new_site(
        google_account: ConfiguredAccount,
        bing_account: ConfiguredAccount,
        site_url: str,
    ) -> None:
        if (
            site_url in google_account.search_console_sites
            or site_url in google_account.pagespeed_sites
            or site_url in bing_account.bing_sites
        ):
            raise InputLimitError("site onboarding target is already configured")

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
            "search_console_sites": (*account.search_console_sites, site_url),
            "ga4_properties": (*account.ga4_properties, property_id),
        }
        if account.pagespeed_api_key_file is not None:
            update["pagespeed_sites"] = (*account.pagespeed_sites, site_url)
        return account.model_copy(update=update)
    if account.id == bing_account_id:
        return account.model_copy(update={"bing_sites": (*account.bing_sites, site_url)})
    return account


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
