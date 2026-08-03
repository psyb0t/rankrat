"""Resolve only exact, operator-configured account and resource boundaries."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from rankrat.errors import BoundaryDeniedError, ConfigurationError
from rankrat.models.boundaries import (
    BoundaryDocument,
    ConfiguredAccount,
    IndexNowTarget,
    Provider,
    ResourceKind,
    configured_site_contains_url,
    normalize_public_https_url,
    search_console_property_contains_url,
)
from rankrat.policy.limits import require_boundary_file_size


class BoundaryPolicy:
    """Immutable authorization policy derived from one validated document."""

    def __init__(self, document: BoundaryDocument, *, unbounded: bool = False) -> None:
        self._document = document
        self._unbounded = unbounded

    @classmethod
    def from_file(
        cls,
        path: Path,
        secret_root: Path,
        oauth_token_root: Path | None = None,
        *,
        unbounded: bool = False,
    ) -> BoundaryPolicy:
        """Read and validate a bounded JSON document once at startup."""
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
        return cls(document, unbounded=unbounded)

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

    def resolve_indexnow_target(self, target_id: str) -> IndexNowTarget:
        """Resolve one exact IndexNow target without an implicit host fallback."""
        for target in self._document.indexnow_targets:
            if target.id == target_id:
                return target
        raise BoundaryDeniedError("configured IndexNow target boundary not found")

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
        """Authorize an exact resource under a single configured account."""
        account = self.resolve_account(account_id, provider)
        if self._unbounded:
            return account
        resources = self._resources_for_kind(account, resource_kind)
        if resource in resources:
            return account
        raise BoundaryDeniedError("configured resource boundary not found")

    def require_google_read_resource(
        self,
        account_id: str,
        resource_kind: ResourceKind,
        resource: str,
    ) -> ConfiguredAccount:
        """Authorize an explicit Google resource or an operator-enabled read discovery resource."""

        account = self.resolve_account(account_id, Provider.GOOGLE)
        if self._unbounded:
            return account
        if resource in self._resources_for_kind(account, resource_kind):
            return account
        if account.allows_google_read_discovery(resource_kind):
            return account
        raise BoundaryDeniedError("configured Google read resource boundary not found")

    def require_google_account_discovery(self, account_id: str) -> ConfiguredAccount:
        """Authorize the account-wide Google inventory endpoint only when explicitly enabled."""

        account = self.resolve_account(account_id, Provider.GOOGLE)
        if self._unbounded:
            return account
        if not account.google_account_discovery:
            raise BoundaryDeniedError("Google account discovery is not enabled for this account")
        return account

    def require_google_analytics_onboarding_account(
        self,
        account_id: str,
        parent_account_id: str,
    ) -> ConfiguredAccount:
        """Authorize local GA4 provisioning only under one configured parent account."""

        account = self.resolve_account(account_id, Provider.GOOGLE)
        if self._unbounded:
            return account
        if account.google_analytics_parent_account_id != parent_account_id:
            raise BoundaryDeniedError("configured Google Analytics parent account was not selected")
        return account

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
        raise BoundaryDeniedError("unsupported configured resource kind")
