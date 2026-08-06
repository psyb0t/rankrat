"""Boundary-limited provider remediation for audited site discovery defects."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from rankrat.constants import DEFAULT_PROVIDER_TIMEOUT_SECONDS, MAX_BING_SUBMISSION_URLS
from rankrat.errors import InputLimitError
from rankrat.logging import log_event
from rankrat.policy.boundaries import BoundaryPolicy
from rankrat.providers.base import AccountId, ProviderOperationError, ProviderReadRequest
from rankrat.providers.bing import BingWebmasterClient
from rankrat.providers.google_search_console import GoogleSearchConsoleClient

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SiteRemediationRequest:
    """One verified site, sitemap, and bounded changed-URL discovery batch."""

    google_account_id: str
    google_site_url: str
    bing_account_id: str
    bing_site_url: str
    sitemap_url: str
    changed_urls: tuple[str, ...]
    timeout_seconds: float = DEFAULT_PROVIDER_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        if not self.changed_urls or len(self.changed_urls) > MAX_BING_SUBMISSION_URLS:
            raise InputLimitError("site remediation URL count is outside the allowed range")
        if len(set(self.changed_urls)) != len(self.changed_urls):
            raise InputLimitError("site remediation URLs must not contain duplicates")


@dataclass(frozen=True, slots=True)
class SiteRemediationReceipt:
    """Secret-free acknowledgement of accepted search-provider remediation writes."""

    google_sitemap_submitted: bool
    bing_sitemap_submitted: bool
    bing_urls_submitted: int


class SiteRemediationService:
    """Apply sitemap and changed-URL discovery fixes to Google and Bing."""

    def __init__(
        self,
        policy: BoundaryPolicy,
        google: GoogleSearchConsoleClient,
        bing: BingWebmasterClient,
    ) -> None:
        self._policy = policy
        self._google = google
        self._bing = bing

    async def apply(self, request: SiteRemediationRequest) -> SiteRemediationReceipt:
        """Submit the configured sitemap and changed URLs after all boundary checks."""

        google_sitemap_url = self._policy.require_search_console_url(
            request.google_account_id,
            request.google_site_url,
            request.sitemap_url,
        )
        bing_sitemap_url = self._policy.require_bing_site_url(
            request.bing_account_id,
            request.bing_site_url,
            request.sitemap_url,
        )
        changed_urls = tuple(
            self._policy.require_bing_site_url(
                request.bing_account_id,
                request.bing_site_url,
                url,
            )
            for url in request.changed_urls
        )
        google_request = ProviderReadRequest(
            AccountId(request.google_account_id),
            request.timeout_seconds,
        )
        bing_request = ProviderReadRequest(
            AccountId(request.bing_account_id),
            request.timeout_seconds,
        )
        try:
            await self._google.submit_sitemap(
                google_request,
                request.google_site_url,
                google_sitemap_url,
            )
            await self._bing.submit_feed(
                bing_request,
                request.bing_site_url,
                bing_sitemap_url,
            )
            await self._bing.submit_url_batch(
                bing_request,
                request.bing_site_url,
                changed_urls,
            )
        except ProviderOperationError:
            log_event(
                _LOGGER,
                logging.WARNING,
                "Site discovery remediation failed",
                google_account_id=request.google_account_id,
                bing_account_id=request.bing_account_id,
                google_site_url=request.google_site_url,
                bing_site_url=request.bing_site_url,
            )
            raise
        log_event(
            _LOGGER,
            logging.INFO,
            "Site discovery remediation accepted",
            google_account_id=request.google_account_id,
            bing_account_id=request.bing_account_id,
            google_site_url=request.google_site_url,
            bing_site_url=request.bing_site_url,
            submitted_count=len(changed_urls),
        )
        return SiteRemediationReceipt(True, True, len(changed_urls))
