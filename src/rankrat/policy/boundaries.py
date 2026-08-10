"""Resolve only exact, operator-configured account and resource boundaries."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from rankrat.errors import BoundaryDeniedError, ConfigurationError
from rankrat.models.boundaries import (
    DNS_OWNERSHIP_PROVIDERS,
    BoundaryDocument,
    ConfiguredAccount,
    DnsZone,
    IndexNowTarget,
    Provider,
    ResourceKind,
    configured_site_contains_url,
    normalize_indexnow_host,
    normalize_public_https_url,
    search_console_property_contains_url,
)
from rankrat.policy.limits import require_boundary_file_size


class BoundaryPolicy:
    """Authorize operations through exact configured provider accounts."""

    def __init__(self, document: BoundaryDocument) -> None:
        self._document = document

    @classmethod
    def from_file(
        cls,
        path: Path,
        secret_root: Path,
        oauth_token_root: Path | None = None,
    ) -> BoundaryPolicy:
        """Read and validate the provider-account document once at startup."""
        try:
            contents = require_boundary_file_size(path.read_bytes())
            raw_document = json.loads(contents)
            document = BoundaryDocument.model_validate(raw_document)
            resolved_secret_root = secret_root.resolve(strict=True)
            for account in document.accounts:
                credential = account.credential.resolve(strict=False)
                if not credential.is_relative_to(resolved_secret_root):
                    raise ConfigurationError("credential path escapes the configured secret root")
                if account.pagespeed_api_key_file is not None:
                    pagespeed_api_key_file = account.pagespeed_api_key_file.resolve(strict=False)
                    if not pagespeed_api_key_file.is_relative_to(resolved_secret_root):
                        raise ConfigurationError(
                            "PageSpeed API key path escapes the configured secret root"
                        )
            oauth_accounts = tuple(
                (account, account.oauth_token_file)
                for account in document.accounts
                if account.provider == Provider.GOOGLE and account.oauth_token_file is not None
            )
            if oauth_accounts:
                if oauth_token_root is None:
                    raise ConfigurationError("OAuth accounts require an OAuth token root")
                resolved_oauth_token_root = oauth_token_root.resolve(strict=True)
                if not resolved_oauth_token_root.is_dir():
                    raise ConfigurationError("OAuth token root must be a directory")
                for _, token_file in oauth_accounts:
                    resolved_token_file = token_file.resolve(strict=False)
                    if not resolved_token_file.is_relative_to(resolved_oauth_token_root):
                        raise ConfigurationError(
                            "OAuth token path escapes the configured token root"
                        )
            for target in document.indexnow_targets:
                key_file = target.key_file.resolve(strict=False)
                if not key_file.is_relative_to(resolved_secret_root):
                    raise ConfigurationError("IndexNow key path escapes the configured secret root")
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValidationError) as error:
            raise ConfigurationError("invalid Rankrat boundary configuration") from error
        return cls(document)

    def accounts(self) -> tuple[ConfiguredAccount, ...]:
        """Return immutable accounts for safe read-only summaries."""
        return self._document.accounts

    def resolve_account(
        self,
        account_id: str,
        provider: Provider | None = None,
    ) -> ConfiguredAccount:
        """Resolve one exact account without any credential fallback."""
        for account in self._document.accounts:
            if account.id != account_id:
                continue
            if provider is None or account.provider == provider:
                return account
            break
        raise BoundaryDeniedError("configured account boundary not found")

    def select_account(
        self,
        provider: Provider,
        account_id: str | None = None,
    ) -> ConfiguredAccount:
        """Select an explicit account or the sole account for one provider."""

        if account_id is not None:
            return self.resolve_account(account_id, provider)
        candidates = tuple(
            account for account in self._document.accounts if account.provider == provider
        )
        if len(candidates) == 1:
            return candidates[0]
        if not candidates:
            raise ConfigurationError(f"no {provider.value} account is configured")
        raise ConfigurationError(
            f"multiple {provider.value} accounts are configured; account_id is required"
        )

    def resolve_indexnow_target(self, target_id: str) -> IndexNowTarget:
        """Resolve one exact IndexNow target without an implicit host fallback."""
        for target in self._document.indexnow_targets:
            if target.id == target_id:
                return target
        raise BoundaryDeniedError("configured IndexNow target boundary not found")

    def resolve_dns_account(self, account_id: str) -> ConfiguredAccount:
        """Resolve an exact account backed by a supported DNS ownership provider."""

        account = self.resolve_account(account_id)
        if account.provider not in DNS_OWNERSHIP_PROVIDERS:
            raise BoundaryDeniedError("configured account is not a DNS provider")
        return account

    def resolve_dns_zone(self, account_id: str, hostname: str) -> DnsZone:
        """Resolve the most-specific configured DNS zone containing a hostname."""

        account = self.resolve_dns_account(account_id)
        normalized_hostname = normalize_indexnow_host(hostname)
        candidates = tuple(
            zone
            for zone in account.dns_zones
            if normalized_hostname == zone.name or normalized_hostname.endswith(f".{zone.name}")
        )
        if not candidates:
            raise BoundaryDeniedError("DNS zone is outside the configured boundary")
        return max(candidates, key=lambda zone: len(zone.name))

    def resolve_google_oauth_account(self, credential_path: Path) -> ConfiguredAccount | None:
        """Resolve an internal OAuth client path without allowing a credential fallback."""
        resolved_credential = credential_path.resolve(strict=False)
        for account in self._document.accounts:
            if account.provider != Provider.GOOGLE or account.oauth_token_file is None:
                continue
            if account.credential.resolve(strict=False) == resolved_credential:
                return account
        return None

    def require_resource(
        self,
        account_id: str,
        provider: Provider,
        resource_kind: ResourceKind,
        resource: str,
    ) -> ConfiguredAccount:
        """Authorize any supported resource through an exact configured account."""
        del resource_kind, resource
        return self.resolve_account(account_id, provider)

    def require_google_read_resource(
        self,
        account_id: str,
        resource_kind: ResourceKind,
        resource: str,
    ) -> ConfiguredAccount:
        """Authorize any Google read reachable through the configured OAuth account."""

        del resource_kind, resource
        return self.resolve_account(account_id, Provider.GOOGLE)

    def require_google_account(self, account_id: str) -> ConfiguredAccount:
        """Resolve one Google OAuth account for account-wide operations."""

        return self.resolve_account(account_id, Provider.GOOGLE)

    def require_google_onboarding_account(self, account_id: str) -> ConfiguredAccount:
        """Resolve the exact Google account for a local onboarding operation."""

        return self.resolve_account(account_id, Provider.GOOGLE)

    def require_bing_onboarding_account(self, account_id: str) -> ConfiguredAccount:
        """Resolve the exact Bing account for a local onboarding operation."""

        return self.resolve_account(account_id, Provider.BING)

    def require_google_search_console_read_url(
        self,
        account_id: str,
        property_url: str,
        candidate_url: str,
    ) -> str:
        """Authorize a normalized page URL under an explicit or discovered GSC property."""

        self.require_google_read_resource(
            account_id,
            ResourceKind.SEARCH_CONSOLE_SITE,
            property_url,
        )
        normalized_url = normalize_public_https_url(candidate_url, "inspection_url")
        if not search_console_property_contains_url(property_url, normalized_url):
            raise BoundaryDeniedError("URL is outside the configured Search Console property")
        return normalized_url

    def require_search_console_url(
        self,
        account_id: str,
        property_url: str,
        candidate_url: str,
    ) -> str:
        """Normalize and authorize a page URL beneath one exact GSC property."""
        self.require_resource(
            account_id,
            Provider.GOOGLE,
            ResourceKind.SEARCH_CONSOLE_SITE,
            property_url,
        )
        normalized_url = normalize_public_https_url(candidate_url, "inspection_url")
        if not search_console_property_contains_url(property_url, normalized_url):
            raise BoundaryDeniedError("URL is outside the configured Search Console property")
        return normalized_url

    def require_pagespeed_url(
        self,
        account_id: str,
        site_url: str,
        candidate_url: str,
    ) -> str:
        """Normalize and authorize a child URL beneath one exact PageSpeed site."""

        self.require_resource(
            account_id,
            Provider.GOOGLE,
            ResourceKind.PAGESPEED_SITE,
            site_url,
        )
        normalized_url = normalize_public_https_url(candidate_url, "page_url")
        if not configured_site_contains_url(site_url, normalized_url):
            raise BoundaryDeniedError("URL is outside the configured PageSpeed site")
        return normalized_url

    def require_bing_site_url(
        self,
        account_id: str,
        site_url: str,
        candidate_url: str,
    ) -> str:
        """Normalize and authorize a child URL beneath one exact Bing site."""
        self.require_resource(account_id, Provider.BING, ResourceKind.BING_SITE, site_url)
        normalized_url = normalize_public_https_url(candidate_url, "url")
        if not configured_site_contains_url(site_url, normalized_url):
            raise BoundaryDeniedError("URL is outside the configured Bing site")
        return normalized_url

    def require_backlink_target(
        self,
        account_id: str,
        provider: Provider,
        target: str,
    ) -> tuple[ConfiguredAccount, str]:
        """Normalize and authorize one exact provider-neutral backlink target."""

        stripped = target.strip()
        normalized = (
            normalize_public_https_url(stripped, "backlink_target")
            if "://" in stripped
            else normalize_indexnow_host(stripped)
        )
        account = self.require_resource(
            account_id,
            provider,
            ResourceKind.BACKLINK_TARGET,
            normalized,
        )
        return account, normalized

    @staticmethod
    def _resources_for_kind(
        account: ConfiguredAccount,
        resource_kind: ResourceKind,
    ) -> tuple[str, ...]:
        if resource_kind == ResourceKind.SEARCH_CONSOLE_SITE:
            return account.search_console_sites
        if resource_kind == ResourceKind.PAGESPEED_SITE:
            return account.pagespeed_sites
        if resource_kind == ResourceKind.GA4_PROPERTY:
            return account.ga4_properties
        if resource_kind == ResourceKind.BING_SITE:
            return account.bing_sites
        if resource_kind == ResourceKind.DNS_ZONE:
            return tuple(zone.provider_zone_id for zone in account.dns_zones)
        if resource_kind == ResourceKind.BACKLINK_TARGET:
            return account.backlink_targets
        raise BoundaryDeniedError("unsupported configured resource kind")
