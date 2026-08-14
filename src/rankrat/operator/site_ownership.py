"""Idempotent DNS ownership verification across search and DNS providers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlparse

from rankrat.errors import BoundaryDeniedError, InputLimitError
from rankrat.models.boundaries import (
    Provider,
    normalize_indexnow_host,
    normalize_public_https_root_url,
)
from rankrat.policy.boundaries import BoundaryPolicy
from rankrat.providers.base import AccountId, ProviderReadRequest
from rankrat.providers.bing import BingSiteVerification, BingWebmasterClient
from rankrat.providers.dns import DnsOwnershipClient, DnsRecordType, PublicDnsClient
from rankrat.providers.google_site_verification import (
    GoogleSiteVerificationClient,
    GoogleVerificationMethod,
    GoogleVerificationToken,
)

_BING_VERIFICATION_TARGET = "verify.bing.com"


@dataclass(frozen=True, slots=True)
class SiteOwnershipRequest:
    """Accounts and one HTTPS site root selected for ownership verification."""

    google_account_id: str | None
    bing_account_id: str | None
    site_url: str
    timeout_seconds: float

    def __post_init__(self) -> None:
        normalized_url = normalize_public_https_root_url(self.site_url, "site_url")
        object.__setattr__(self, "site_url", normalized_url)
        if self.google_account_id is None and self.bing_account_id is None:
            raise InputLimitError("site ownership requires a Google or Bing account")


@dataclass(frozen=True, slots=True)
class SiteOwnershipWriteRequest(SiteOwnershipRequest):
    """Ownership request plus the configured DNS provider account used for writes."""

    dns_account_id: str


@dataclass(frozen=True, slots=True)
class SiteOwnershipProviderStatus:
    """Secret-free status for one provider's verification record."""

    record_created: bool
    propagated: bool
    verified: bool


@dataclass(frozen=True, slots=True)
class SiteOwnershipReceipt:
    """Safe ownership result that never returns provider-issued token material."""

    site_url: str
    domain: str
    google: SiteOwnershipProviderStatus | None
    bing: SiteOwnershipProviderStatus | None
    complete: bool


@dataclass(frozen=True, slots=True)
class _VerificationMaterial:
    google: GoogleVerificationToken | None
    bing: BingSiteVerification | None


class SiteOwnershipOperator:
    """Materialize and verify only provider-issued DNS ownership records."""

    def __init__(
        self,
        policy: BoundaryPolicy,
        google: GoogleSiteVerificationClient,
        bing: BingWebmasterClient,
        dns_clients: Mapping[Provider, DnsOwnershipClient],
        public_dns: PublicDnsClient,
    ) -> None:
        self._policy = policy
        self._google = google
        self._bing = bing
        self._dns_clients = dict(dns_clients)
        self._public_dns = public_dns

    async def check(self, request: SiteOwnershipRequest) -> SiteOwnershipReceipt:
        """Read public propagation and provider verification without changing DNS."""

        google_request, bing_request = self._provider_requests(request)
        material = await self._verification_material(
            request,
            google_request,
            bing_request,
            add_bing=False,
        )
        return await self._status_from_material(
            request,
            google_request,
            bing_request,
            material,
            google_created=False,
            bing_created=False,
        )

    async def verify(self, request: SiteOwnershipWriteRequest) -> SiteOwnershipReceipt:
        """Ensure selected verification records and redeem each propagated proof."""

        dns_client = self._dns_client(request.dns_account_id)
        google_request, bing_request = self._provider_requests(request)
        material = await self._verification_material(
            request,
            google_request,
            bing_request,
            add_bing=True,
        )
        if bing_request is not None and material.bing is None:
            raise InputLimitError("Bing did not expose verification material for the site")
        domain = self._domain(request.site_url)
        dns_request = ProviderReadRequest(
            AccountId(request.dns_account_id),
            request.timeout_seconds,
        )
        google_created = False
        if material.google is not None:
            google_record = await dns_client.ensure_verification_record(
                dns_request,
                domain,
                DnsRecordType.TXT,
                domain,
                material.google.token,
            )
            google_created = google_record.created
        bing_created = False
        if material.bing is not None:
            bing_record = await dns_client.ensure_verification_record(
                dns_request,
                domain,
                DnsRecordType.CNAME,
                material.bing.dns_verification_code,
                _BING_VERIFICATION_TARGET,
            )
            bing_created = bing_record.created
        return await self._status_from_material(
            request,
            google_request,
            bing_request,
            material,
            google_created=google_created,
            bing_created=bing_created,
            redeem=True,
        )

    def _provider_requests(
        self,
        request: SiteOwnershipRequest,
    ) -> tuple[ProviderReadRequest | None, ProviderReadRequest | None]:
        google_request = None
        if request.google_account_id is not None:
            self._policy.require_google_onboarding_account(request.google_account_id)
            google_request = ProviderReadRequest(
                AccountId(request.google_account_id),
                request.timeout_seconds,
            )
        bing_request = None
        if request.bing_account_id is not None:
            self._policy.require_bing_onboarding_account(request.bing_account_id)
            bing_request = ProviderReadRequest(
                AccountId(request.bing_account_id),
                request.timeout_seconds,
            )
        return google_request, bing_request

    async def _verification_material(
        self,
        request: SiteOwnershipRequest,
        google_request: ProviderReadRequest | None,
        bing_request: ProviderReadRequest | None,
        *,
        add_bing: bool,
    ) -> _VerificationMaterial:
        google_token = None
        if google_request is not None:
            google_token = await self._google.get_token(
                google_request,
                self._domain(request.site_url),
                GoogleVerificationMethod.DNS_TXT,
            )
        bing_verification = None
        if bing_request is not None:
            bing_verification = await self._bing.site_verification_for_onboarding(
                bing_request,
                request.site_url,
            )
        if bing_request is not None and bing_verification is None and add_bing:
            await self._bing.add_site_for_onboarding(bing_request, request.site_url)
            bing_verification = await self._bing.site_verification_for_onboarding(
                bing_request,
                request.site_url,
            )
        return _VerificationMaterial(google_token, bing_verification)

    async def _status_from_material(
        self,
        request: SiteOwnershipRequest,
        google_request: ProviderReadRequest | None,
        bing_request: ProviderReadRequest | None,
        material: _VerificationMaterial,
        *,
        google_created: bool,
        bing_created: bool,
        redeem: bool = False,
    ) -> SiteOwnershipReceipt:
        domain = self._domain(request.site_url)
        google_status = None
        if google_request is not None and material.google is not None:
            google_dns = await self._public_dns.has_record(
                domain,
                DnsRecordType.TXT,
                material.google.token,
                request.timeout_seconds,
            )
            google_verified = await self._google.is_verified(google_request, domain)
            if redeem and google_dns.propagated and not google_verified:
                await self._google.verify(
                    google_request,
                    domain,
                    GoogleVerificationMethod.DNS_TXT,
                )
                google_verified = True
            google_status = SiteOwnershipProviderStatus(
                google_created,
                google_dns.propagated,
                google_verified,
            )
        bing_status = None
        if bing_request is not None:
            if material.bing is None:
                bing_status = SiteOwnershipProviderStatus(False, False, False)
            else:
                bing_dns = await self._public_dns.has_record(
                    material.bing.dns_verification_code,
                    DnsRecordType.CNAME,
                    _BING_VERIFICATION_TARGET,
                    request.timeout_seconds,
                )
                bing_verified = material.bing.verified
                if redeem and bing_dns.propagated and not bing_verified:
                    bing_verified = await self._bing.verify_site_for_onboarding(
                        bing_request,
                        request.site_url,
                    )
                bing_status = SiteOwnershipProviderStatus(
                    bing_created,
                    bing_dns.propagated,
                    bing_verified,
                )
        return self._receipt(request, google_status, bing_status)

    @classmethod
    def _receipt(
        cls,
        request: SiteOwnershipRequest,
        google: SiteOwnershipProviderStatus | None,
        bing: SiteOwnershipProviderStatus | None,
    ) -> SiteOwnershipReceipt:
        statuses = tuple(status for status in (google, bing) if status is not None)
        return SiteOwnershipReceipt(
            site_url=request.site_url,
            domain=cls._domain(request.site_url),
            google=google,
            bing=bing,
            complete=all(status.verified for status in statuses),
        )

    @staticmethod
    def _domain(site_url: str) -> str:
        hostname = urlparse(site_url).hostname
        if hostname is None:
            raise InputLimitError("site ownership URL does not have a hostname")
        return normalize_indexnow_host(hostname)

    def _dns_client(self, account_id: str) -> DnsOwnershipClient:
        account = self._policy.resolve_dns_account(account_id)
        client = self._dns_clients.get(account.provider)
        if client is None:
            raise BoundaryDeniedError("configured DNS provider adapter is unavailable")
        return client
