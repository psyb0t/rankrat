"""Read-only account and configured-resource listing services."""

from __future__ import annotations

from dataclasses import dataclass

from rankrat.models.boundaries import Provider, ResourceKind
from rankrat.policy.boundaries import BoundaryPolicy


@dataclass(frozen=True, slots=True)
class AccountsListRequest:
    """Optional provider filter for configured account summaries."""

    provider: Provider | None = None


@dataclass(frozen=True, slots=True)
class AccountSummary:
    """Safe account metadata; credential material is deliberately absent."""

    account_id: str
    provider: Provider
    search_console_site_count: int
    pagespeed_site_count: int
    ga4_property_count: int
    bing_site_count: int


@dataclass(frozen=True, slots=True)
class AccountsListResponse:
    """Filtered configured account summaries."""

    accounts: tuple[AccountSummary, ...]


@dataclass(frozen=True, slots=True)
class SitesListRequest:
    """Optional filters for resources already configured by the operator."""

    account_id: str | None = None
    provider: Provider | None = None


@dataclass(frozen=True, slots=True)
class SiteSummary:
    """A configured Search Console site, Bing site, or GA4 property."""

    account_id: str
    provider: Provider
    resource: str
    resource_kind: ResourceKind


@dataclass(frozen=True, slots=True)
class SitesListResponse:
    """Filtered configured-resource summaries."""

    sites: tuple[SiteSummary, ...]


class SitesService:
    """Lists only immutable boundary configuration, never provider discovery."""

    def __init__(self, policy: BoundaryPolicy) -> None:
        self._policy = policy

    def accounts_list(self, request: AccountsListRequest) -> AccountsListResponse:
        """Return configured account summaries, optionally by provider."""
        accounts = self._policy.accounts()
        summaries = tuple(
            AccountSummary(
                account_id=account.id,
                provider=account.provider,
                search_console_site_count=len(account.search_console_sites),
                pagespeed_site_count=len(account.pagespeed_sites),
                ga4_property_count=len(account.ga4_properties),
                bing_site_count=len(account.bing_sites),
            )
            for account in accounts
            if request.provider is None or account.provider == request.provider
        )
        return AccountsListResponse(accounts=summaries)

    def sites_list(self, request: SitesListRequest) -> SitesListResponse:
        """Return resources configured for the requested account/provider only."""
        if request.account_id is None:
            accounts = self._policy.accounts()
        else:
            accounts = (self._policy.resolve_account(request.account_id, request.provider),)
        sites = tuple(
            site
            for account in accounts
            if self._matches_account_filter(account.id, account.provider, request)
            for site in self._resource_summaries(
                account_id=account.id,
                provider=account.provider,
                search_console_sites=account.search_console_sites,
                pagespeed_sites=account.pagespeed_sites,
                ga4_properties=account.ga4_properties,
                bing_sites=account.bing_sites,
            )
        )
        return SitesListResponse(sites=sites)

    @staticmethod
    def _matches_account_filter(
        account_id: str,
        provider: Provider,
        request: SitesListRequest,
    ) -> bool:
        if request.account_id is not None and request.account_id != account_id:
            return False
        return request.provider is None or request.provider == provider

    @staticmethod
    def _resource_summaries(
        account_id: str,
        provider: Provider,
        search_console_sites: tuple[str, ...],
        pagespeed_sites: tuple[str, ...],
        ga4_properties: tuple[str, ...],
        bing_sites: tuple[str, ...],
    ) -> tuple[SiteSummary, ...]:
        search_console = tuple(
            SiteSummary(
                account_id=account_id,
                provider=provider,
                resource=resource,
                resource_kind=ResourceKind.SEARCH_CONSOLE_SITE,
            )
            for resource in search_console_sites
        )
        ga4 = tuple(
            SiteSummary(
                account_id=account_id,
                provider=provider,
                resource=resource,
                resource_kind=ResourceKind.GA4_PROPERTY,
            )
            for resource in ga4_properties
        )
        pagespeed = tuple(
            SiteSummary(
                account_id=account_id,
                provider=provider,
                resource=resource,
                resource_kind=ResourceKind.PAGESPEED_SITE,
            )
            for resource in pagespeed_sites
        )
        bing = tuple(
            SiteSummary(
                account_id=account_id,
                provider=provider,
                resource=resource,
                resource_kind=ResourceKind.BING_SITE,
            )
            for resource in bing_sites
        )
        return search_console + pagespeed + ga4 + bing
