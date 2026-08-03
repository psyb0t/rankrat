"""Bounded Google Indexing notifications with local eligibility evidence."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from enum import StrEnum

from rankrat.constants import DEFAULT_PROVIDER_TIMEOUT_SECONDS, MAX_GOOGLE_INDEXING_BATCH
from rankrat.errors import BoundaryDeniedError, InputLimitError
from rankrat.logging import log_event
from rankrat.policy.boundaries import BoundaryPolicy
from rankrat.providers.google_indexing import (
    URL_DELETED,
    URL_UPDATED,
    GoogleIndexingBatchReceipt,
    GoogleIndexingClient,
    GoogleIndexingPublishReceipt,
)
from rankrat.providers.schema_fetch import PublicSchemaFetcher
from rankrat.services.schema import assess_google_indexing_eligibility

_LOGGER = logging.getLogger(__name__)
_GOOGLE_INDEXING_BATCH_VALIDATION_CONCURRENCY = 8


class GoogleIndexingNotificationType(StrEnum):
    """The two notification types documented by Google's Indexing API."""

    UPDATED = URL_UPDATED
    DELETED = URL_DELETED


@dataclass(frozen=True, slots=True)
class GoogleIndexingSubmissionRequest:
    account_id: str
    site_url: str
    url: str
    notification_type: GoogleIndexingNotificationType

    timeout_seconds: float = DEFAULT_PROVIDER_TIMEOUT_SECONDS


@dataclass(frozen=True, slots=True)
class GoogleIndexingBatchNotification:
    """One requested notification in an ordered Google Indexing batch."""

    url: str
    notification_type: GoogleIndexingNotificationType


@dataclass(frozen=True, slots=True)
class GoogleIndexingBatchSubmissionRequest:
    """One ordered batch for a configured property."""

    account_id: str
    site_url: str
    notifications: tuple[GoogleIndexingBatchNotification, ...]

    timeout_seconds: float = DEFAULT_PROVIDER_TIMEOUT_SECONDS


@dataclass(frozen=True, slots=True)
class GoogleIndexingBatchSubmission:
    """Ordered batch receipts without raw upstream response bodies."""

    receipts: tuple[GoogleIndexingBatchReceipt, ...]
    accepted_count: int
    rejected_count: int


class GoogleIndexingService:
    """Require site ownership and eligibility evidence before publishing."""

    def __init__(
        self,
        policy: BoundaryPolicy,
        client: GoogleIndexingClient,
        schema_fetcher: PublicSchemaFetcher,
    ) -> None:
        self._policy = policy
        self._client = client
        self._schema_fetcher = schema_fetcher

    async def submit(
        self, request: GoogleIndexingSubmissionRequest
    ) -> GoogleIndexingPublishReceipt:
        normalized = await self._eligible_url(request, request.timeout_seconds)
        try:
            result = await self._client.publish(
                request.account_id,
                normalized,
                request.notification_type.value,
                request.timeout_seconds,
            )
        except Exception:
            log_event(
                _LOGGER,
                logging.WARNING,
                "Google Indexing notification failed",
                account_id=request.account_id,
                site_url=request.site_url,
                notification_type=request.notification_type.value,
            )
            raise
        log_event(
            _LOGGER,
            logging.INFO,
            "Google Indexing notification accepted",
            account_id=request.account_id,
            site_url=request.site_url,
            notification_type=request.notification_type.value,
        )
        return result

    async def submit_batch(
        self,
        request: GoogleIndexingBatchSubmissionRequest,
    ) -> GoogleIndexingBatchSubmission:
        """Validate every notification and make one multipart provider call."""

        normalized = await self._eligible_batch(request, request.timeout_seconds)
        try:
            receipts = await self._client.publish_batch(
                request.account_id,
                normalized,
                request.timeout_seconds,
            )
        except Exception:
            log_event(
                _LOGGER,
                logging.WARNING,
                "Google Indexing batch failed",
                account_id=request.account_id,
                site_url=request.site_url,
                notification_count=len(normalized),
            )
            raise
        accepted_count = sum(receipt.accepted for receipt in receipts)
        result = GoogleIndexingBatchSubmission(
            receipts=receipts,
            accepted_count=accepted_count,
            rejected_count=len(receipts) - accepted_count,
        )
        log_event(
            _LOGGER,
            logging.INFO,
            "Google Indexing batch completed",
            account_id=request.account_id,
            site_url=request.site_url,
            notification_count=len(normalized),
            accepted_count=result.accepted_count,
            rejected_count=result.rejected_count,
        )
        return result

    async def _eligible_url(
        self,
        request: GoogleIndexingSubmissionRequest,
        timeout_seconds: float,
    ) -> str:
        normalized = self._policy.require_search_console_url(
            request.account_id,
            request.site_url,
            request.url,
        )
        if request.notification_type is GoogleIndexingNotificationType.DELETED:
            return normalized
        fetched = await self._schema_fetcher.fetch(normalized, timeout_seconds)
        eligibility = assess_google_indexing_eligibility(fetched.body)
        if not eligibility.eligible:
            raise BoundaryDeniedError("Google Indexing URL is not eligible")
        return normalized

    async def _eligible_batch(
        self,
        request: GoogleIndexingBatchSubmissionRequest,
        timeout_seconds: float,
    ) -> tuple[tuple[str, str], ...]:
        if not request.notifications:
            raise InputLimitError("Google Indexing batch must include one notification")
        if len(request.notifications) > MAX_GOOGLE_INDEXING_BATCH:
            raise InputLimitError("Google Indexing batch exceeds the submission limit")

        normalized: list[tuple[str, GoogleIndexingNotificationType]] = []
        seen_urls: set[str] = set()
        for notification in request.notifications:
            url = self._policy.require_search_console_url(
                request.account_id,
                request.site_url,
                notification.url,
            )
            if url in seen_urls:
                raise InputLimitError("Google Indexing batch URLs must be distinct")
            seen_urls.add(url)
            normalized.append((url, notification.notification_type))

        semaphore = asyncio.Semaphore(_GOOGLE_INDEXING_BATCH_VALIDATION_CONCURRENCY)

        async def validate(notification: tuple[str, GoogleIndexingNotificationType]) -> None:
            url, notification_type = notification
            if notification_type is GoogleIndexingNotificationType.DELETED:
                return
            async with semaphore:
                fetched = await self._schema_fetcher.fetch(url, timeout_seconds)
            eligibility = assess_google_indexing_eligibility(fetched.body)
            if not eligibility.eligible:
                raise BoundaryDeniedError("Google Indexing URL is not eligible")

        await asyncio.gather(*(validate(notification) for notification in normalized))
        return tuple((url, notification_type.value) for url, notification_type in normalized)
