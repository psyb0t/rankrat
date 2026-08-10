"""Strict immutable account and resource boundary models."""

from __future__ import annotations

import re
from collections.abc import Sequence
from enum import StrEnum
from pathlib import Path
from typing import cast
from urllib.parse import urlparse, urlunparse

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)

from rankrat.constants import MAX_DNS_PROVIDER_ZONE_ID_CHARS

ACCOUNT_ID_PATTERN = r"^[a-z0-9][a-z0-9-]{0,62}$"
_ROOT_URL_PATH = "/"
_DOT_PATH_SEGMENTS = frozenset((".", ".."))
_DANGEROUS_ENCODED_PATH_CHARACTERS = frozenset((_ROOT_URL_PATH, "\\", "%"))
_UNRESERVED_URL_CHARACTERS = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~"
)
_INVALID_PERCENT_ENCODING_PATTERN = re.compile(r"%(?![0-9A-Fa-f]{2})")
_PERCENT_ENCODED_OCTET_PATTERN = re.compile(r"%([0-9A-Fa-f]{2})")
_DOMAIN_PATTERN = re.compile(
    r"^(?=.{1,253}\Z)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}\Z"
)


def _normalize_https_url(value: str, subject: str) -> str:
    normalized = value.strip()
    parsed = urlparse(normalized)
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        raise ValueError(f"{subject} must be an absolute HTTPS URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError(f"{subject} must not contain credentials, query, or fragment")
    if parsed.port not in (None, 443):
        raise ValueError(f"{subject} must use the standard HTTPS port")
    hostname = parsed.hostname.lower().encode("idna").decode("ascii")
    netloc = hostname
    path = _normalize_url_path(parsed.path or _ROOT_URL_PATH, subject)
    return urlunparse(("https", netloc, path, "", "", ""))


def _normalize_url_path(path: str, subject: str) -> str:
    if _INVALID_PERCENT_ENCODING_PATTERN.search(path):
        raise ValueError(f"{subject} must contain valid percent-encoding")

    def decode_unreserved_character(match: re.Match[str]) -> str:
        decoded_character = chr(int(match.group(1), 16))
        if decoded_character in _DANGEROUS_ENCODED_PATH_CHARACTERS:
            raise ValueError(f"{subject} must not encode path traversal characters")
        if decoded_character in _UNRESERVED_URL_CHARACTERS:
            return decoded_character
        return match.group(0).upper()

    normalized_path = _PERCENT_ENCODED_OCTET_PATTERN.sub(decode_unreserved_character, path)
    if "\\" in normalized_path:
        raise ValueError(f"{subject} must not contain a backslash path separator")
    if any(segment in _DOT_PATH_SEGMENTS for segment in normalized_path.split(_ROOT_URL_PATH)):
        raise ValueError(f"{subject} must not contain dot path segments")
    return normalized_path


def normalize_indexnow_host(value: str) -> str:
    """Normalize one operator-supplied public DNS hostname for an IndexNow target."""

    normalized = value.strip().removesuffix(".").lower()
    if not normalized or any(character in normalized for character in "/:@"):
        raise ValueError("host must be a DNS hostname without a scheme, port, or path")
    try:
        normalized = normalized.encode("idna").decode("ascii")
    except UnicodeError as error:
        raise ValueError("host must be a valid DNS hostname") from error
    if not _DOMAIN_PATTERN.fullmatch(normalized):
        raise ValueError("host must be a valid DNS hostname")
    return normalized


def normalize_public_https_url(value: str, subject: str) -> str:
    """Normalize a caller-supplied HTTPS URL before a boundary ownership check."""
    return _normalize_https_url(value, subject)


def normalize_public_https_root_url(value: str, subject: str) -> str:
    """Normalize one public HTTPS site root used by the local onboarding operator."""

    normalized = _normalize_https_url(value, subject)
    if urlparse(normalized).path != _ROOT_URL_PATH:
        raise ValueError(f"{subject} must be an HTTPS site root")
    return normalized


def _path_is_within_boundary(boundary_path: str, candidate_path: str) -> bool:
    try:
        normalized_boundary_path = _normalize_url_path(boundary_path, "boundary path")
        normalized_candidate_path = _normalize_url_path(candidate_path, "candidate path")
    except ValueError:
        return False
    normalized_boundary_path = normalized_boundary_path.rstrip(_ROOT_URL_PATH) or _ROOT_URL_PATH
    if normalized_boundary_path == _ROOT_URL_PATH:
        return normalized_candidate_path.startswith(_ROOT_URL_PATH)
    return (
        normalized_candidate_path == normalized_boundary_path
        or normalized_candidate_path.startswith(f"{normalized_boundary_path}{_ROOT_URL_PATH}")
    )


def search_console_property_contains_url(property_url: str, candidate_url: str) -> bool:
    """Return whether a normalized URL is owned by one configured GSC property."""
    parsed_candidate = urlparse(candidate_url)
    candidate_host = parsed_candidate.hostname
    if candidate_host is None:
        return False
    if property_url.startswith("sc-domain:"):
        domain = property_url.removeprefix("sc-domain:")
        return candidate_host == domain or candidate_host.endswith(f".{domain}")
    parsed_property = urlparse(property_url)
    return (
        parsed_candidate.scheme == parsed_property.scheme
        and parsed_candidate.netloc == parsed_property.netloc
        and _path_is_within_boundary(parsed_property.path, parsed_candidate.path)
    )


def configured_site_contains_url(site_url: str, candidate_url: str) -> bool:
    """Return whether a normalized child URL belongs to an HTTPS site boundary."""
    parsed_site = urlparse(site_url)
    parsed_candidate = urlparse(candidate_url)
    return (
        parsed_candidate.scheme == parsed_site.scheme
        and parsed_candidate.netloc == parsed_site.netloc
        and _path_is_within_boundary(parsed_site.path, parsed_candidate.path)
    )


class Provider(StrEnum):
    """Providers supported by Rankrat."""

    GOOGLE = "google"
    BING = "bing"
    CLOUDFLARE = "cloudflare"
    AHREFS = "ahrefs"
    MAJESTIC = "majestic"
    MOZ = "moz"
    SEMRUSH = "semrush"
    DATAFORSEO = "dataforseo"


DNS_OWNERSHIP_PROVIDERS = frozenset((Provider.CLOUDFLARE,))
BACKLINK_PROVIDERS = frozenset(
    (
        Provider.AHREFS,
        Provider.MAJESTIC,
        Provider.MOZ,
        Provider.SEMRUSH,
        Provider.DATAFORSEO,
    )
)


class ResourceKind(StrEnum):
    """Kinds of configured provider resource."""

    SEARCH_CONSOLE_SITE = "search_console_site"
    PAGESPEED_SITE = "pagespeed_site"
    GA4_PROPERTY = "ga4_property"
    BING_SITE = "bing_site"
    DNS_ZONE = "dns_zone"
    BACKLINK_TARGET = "backlink_target"


class DnsZone(BaseModel):
    """One cached provider DNS zone associated with a configured account."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider_zone_id: str = Field(min_length=1, max_length=MAX_DNS_PROVIDER_ZONE_ID_CHARS)
    name: str

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return normalize_indexnow_host(value)


class ConfiguredAccount(BaseModel):
    """One provider account whose credential defines the reachable authority."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=ACCOUNT_ID_PATTERN)
    provider: Provider
    credential: Path
    oauth_token_file: Path | None = None
    pagespeed_api_key_file: Path | None = None
    pagespeed_sites: tuple[str, ...] = ()
    search_console_sites: tuple[str, ...] = ()
    ga4_properties: tuple[str, ...] = ()
    dns_zones: tuple[DnsZone, ...] = ()
    backlink_targets: tuple[str, ...] = ()
    bing_sites: tuple[str, ...] = Field(
        default=(),
        validation_alias="sites",
        serialization_alias="sites",
    )

    @field_validator("credential")
    @classmethod
    def validate_credential_path(cls, value: Path) -> Path:
        if not value.is_absolute():
            raise ValueError("credential must be an absolute mounted path")
        return value

    @field_validator("oauth_token_file", "pagespeed_api_key_file")
    @classmethod
    def validate_optional_secret_path(cls, value: Path | None) -> Path | None:
        if value is not None and not value.is_absolute():
            raise ValueError("configured secret paths must be absolute")
        return value

    @field_validator("search_console_sites", "pagespeed_sites", mode="before")
    @classmethod
    def validate_google_site_boundaries(
        cls,
        values: object,
        info: ValidationInfo,
    ) -> tuple[str, ...]:
        field_name = info.field_name
        if field_name is None:
            raise ValueError("Google site boundary validator requires a field name")
        if not isinstance(values, list | tuple):
            raise ValueError(f"{field_name} must be a list")
        typed_values = cast(Sequence[object], values)
        normalized_values: list[str] = []
        for value in typed_values:
            if not isinstance(value, str):
                raise ValueError(f"{field_name} must contain strings")
            stripped = value.strip()
            if field_name == "search_console_sites" and stripped.startswith("sc-domain:"):
                domain = stripped.removeprefix("sc-domain:").lower()
                if not _DOMAIN_PATTERN.fullmatch(domain):
                    raise ValueError("search_console_sites contains an invalid domain")
                normalized_values.append(f"sc-domain:{domain}")
                continue
            normalized_values.append(_normalize_https_url(stripped, field_name))
        if len(set(normalized_values)) != len(normalized_values):
            raise ValueError(f"{field_name} must not contain duplicates")
        return tuple(normalized_values)

    @field_validator("ga4_properties")
    @classmethod
    def validate_ga4_properties(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not value.isdigit() for value in values):
            raise ValueError("ga4_properties must contain numeric property IDs")
        if len(set(values)) != len(values):
            raise ValueError("ga4_properties must not contain duplicates")
        return values

    @field_validator("bing_sites", mode="before")
    @classmethod
    def validate_bing_sites(cls, values: object) -> tuple[str, ...]:
        if not isinstance(values, list | tuple):
            raise ValueError("sites must be a list")
        typed_values = cast(Sequence[object], values)
        if any(not isinstance(value, str) for value in typed_values):
            raise ValueError("sites must contain strings")
        string_values = cast(Sequence[str], typed_values)
        normalized_values = tuple(_normalize_https_url(value, "sites") for value in string_values)
        if len(set(normalized_values)) != len(normalized_values):
            raise ValueError("sites must not contain duplicates")
        return normalized_values

    @field_validator("backlink_targets", mode="before")
    @classmethod
    def validate_backlink_targets(cls, values: object) -> tuple[str, ...]:
        if not isinstance(values, list | tuple):
            raise ValueError("backlink_targets must be a list")
        typed_values = cast(Sequence[object], values)
        normalized: list[str] = []
        for value in typed_values:
            if not isinstance(value, str):
                raise ValueError("backlink_targets must contain strings")
            stripped = value.strip()
            normalized.append(
                _normalize_https_url(stripped, "backlink_targets")
                if "://" in stripped
                else normalize_indexnow_host(stripped)
            )
        if len(set(normalized)) != len(normalized):
            raise ValueError("backlink_targets must not contain duplicates")
        return tuple(normalized)

    @model_validator(mode="after")
    def validate_provider_resources(self) -> ConfiguredAccount:
        if self.provider == Provider.GOOGLE and (self.bing_sites or self.backlink_targets):
            raise ValueError("Google accounts cannot configure Bing sites")
        if self.provider == Provider.BING and (
            self.search_console_sites
            or self.pagespeed_sites
            or self.ga4_properties
            or self.dns_zones
            or self.backlink_targets
        ):
            raise ValueError("Bing accounts cannot configure non-Bing resources")
        if self.provider == Provider.GOOGLE and self.dns_zones:
            raise ValueError("Google accounts cannot configure DNS zones")
        if self.provider in DNS_OWNERSHIP_PROVIDERS and (
            self.search_console_sites
            or self.pagespeed_sites
            or self.ga4_properties
            or self.bing_sites
            or self.oauth_token_file is not None
            or self.pagespeed_api_key_file is not None
            or self.backlink_targets
        ):
            raise ValueError("DNS provider accounts can configure only DNS zones")
        if self.provider not in DNS_OWNERSHIP_PROVIDERS and self.dns_zones:
            raise ValueError("only DNS provider accounts can configure dns_zones")
        if self.provider != Provider.GOOGLE and self.oauth_token_file is not None:
            raise ValueError("only Google accounts can configure oauth_token_file")
        if self.provider != Provider.GOOGLE and self.pagespeed_api_key_file is not None:
            raise ValueError("only Google accounts can configure pagespeed_api_key_file")
        if self.provider != Provider.GOOGLE and self.pagespeed_sites:
            raise ValueError("only Google accounts can configure pagespeed_sites")
        if self.provider in BACKLINK_PROVIDERS:
            if (
                self.search_console_sites
                or self.pagespeed_sites
                or self.ga4_properties
                or self.bing_sites
                or self.dns_zones
                or self.oauth_token_file is not None
                or self.pagespeed_api_key_file is not None
            ):
                raise ValueError("backlink provider accounts can configure only backlink targets")
        elif self.backlink_targets:
            raise ValueError("only backlink provider accounts can configure backlink_targets")
        zone_ids = tuple(zone.provider_zone_id for zone in self.dns_zones)
        zone_names = tuple(zone.name for zone in self.dns_zones)
        if len(set(zone_ids)) != len(zone_ids) or len(set(zone_names)) != len(zone_names):
            raise ValueError("DNS zones must not contain duplicates")
        return self


class IndexNowTarget(BaseModel):
    """One exact IndexNow host and its operator-mounted key material."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=ACCOUNT_ID_PATTERN)
    host: str
    key_location: str
    key_file: Path

    @field_validator("host")
    @classmethod
    def validate_host(cls, value: str) -> str:
        return normalize_indexnow_host(value)

    @field_validator("key_location")
    @classmethod
    def validate_key_location(cls, value: str, info: ValidationInfo) -> str:
        normalized = _normalize_https_url(value, "key_location")
        parsed = urlparse(normalized)
        if parsed.hostname != info.data.get("host"):
            raise ValueError("key_location must use the configured host")
        if parsed.path == "/" or parsed.path.endswith("/"):
            raise ValueError("key_location must identify a public key file")
        return normalized

    @field_validator("key_file")
    @classmethod
    def validate_key_file(cls, value: Path) -> Path:
        if not value.is_absolute():
            raise ValueError("key_file must be an absolute mounted path")
        return value


class BoundaryDocument(BaseModel):
    """The complete immutable operator-managed boundary configuration."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    accounts: tuple[ConfiguredAccount, ...] = ()
    indexnow_targets: tuple[IndexNowTarget, ...] = ()

    @model_validator(mode="after")
    def validate_unique_accounts_and_resources(self) -> BoundaryDocument:
        if not self.accounts and not self.indexnow_targets:
            raise ValueError("at least one account or IndexNow target is required")

        account_ids = tuple(account.id for account in self.accounts)
        if len(set(account_ids)) != len(account_ids):
            raise ValueError("account IDs must be unique")

        target_ids = tuple(target.id for target in self.indexnow_targets)
        if len(set(target_ids)) != len(target_ids):
            raise ValueError("IndexNow target IDs must be unique")
        if set(account_ids).intersection(target_ids):
            raise ValueError("account and IndexNow target IDs must not overlap")

        target_hosts = tuple(target.host for target in self.indexnow_targets)
        if len(set(target_hosts)) != len(target_hosts):
            raise ValueError("IndexNow target hosts must be unique")

        oauth_token_files = tuple(
            account.oauth_token_file
            for account in self.accounts
            if account.oauth_token_file is not None
        )
        if len(set(oauth_token_files)) != len(oauth_token_files):
            raise ValueError("OAuth token files must not be shared between accounts")

        oauth_credentials = tuple(
            account.credential for account in self.accounts if account.oauth_token_file is not None
        )
        if len(set(oauth_credentials)) != len(oauth_credentials):
            raise ValueError("OAuth client configurations must not be shared between accounts")

        seen_resources: set[tuple[Provider, ResourceKind, str]] = set()
        for account in self.accounts:
            resources = (
                *(
                    (ResourceKind.SEARCH_CONSOLE_SITE, item)
                    for item in account.search_console_sites
                ),
                *((ResourceKind.PAGESPEED_SITE, item) for item in account.pagespeed_sites),
                *((ResourceKind.GA4_PROPERTY, item) for item in account.ga4_properties),
                *((ResourceKind.BING_SITE, item) for item in account.bing_sites),
                *((ResourceKind.DNS_ZONE, item.provider_zone_id) for item in account.dns_zones),
                *((ResourceKind.BACKLINK_TARGET, item) for item in account.backlink_targets),
            )
            for kind, resource in resources:
                key = (account.provider, kind, resource)
                if key in seen_resources:
                    raise ValueError("configured resources must not be duplicated")
                seen_resources.add(key)
        return self
