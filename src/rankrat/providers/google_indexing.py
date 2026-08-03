"""Fixed-origin Google Indexing API client for eligible notifications."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from rankrat.constants import GOOGLE_INDEXING_SCOPE as _GOOGLE_INDEXING_SCOPE
from rankrat.constants import MAX_GOOGLE_INDEXING_TEXT_CHARS
from rankrat.providers.base import ProviderFailureCode, ProviderOperationError
from rankrat.providers.google_search_console import (
    GoogleIndexingBatchPartResponse,
    GoogleSearchConsoleClient,
)

GOOGLE_INDEXING_SCOPE = _GOOGLE_INDEXING_SCOPE
URL_UPDATED = "URL_UPDATED"
URL_DELETED = "URL_DELETED"


class GoogleIndexingNotificationType(StrEnum):
    """The only Google Indexing notification types Rankrat accepts or returns."""

    UPDATED = URL_UPDATED
    DELETED = URL_DELETED


@dataclass(frozen=True, slots=True)
class GoogleIndexingNotification:
    """One typed Google Indexing notification receipt."""

    url: str
    notification_type: GoogleIndexingNotificationType
    notify_time: str | None


@dataclass(frozen=True, slots=True)
class GoogleIndexingMetadata:
    """The last known update and removal receipts for one owned URL."""

    url: str
    latest_update: GoogleIndexingNotification | None
    latest_remove: GoogleIndexingNotification | None


@dataclass(frozen=True, slots=True)
class GoogleIndexingPublishReceipt:
    """The typed metadata returned when Google accepts one notification."""

    metadata: GoogleIndexingMetadata


class _GoogleIndexingNotificationResponse(BaseModel):
    """The constrained notification fields Rankrat consumes from Google."""

    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)

    url: str = Field(min_length=1, max_length=MAX_GOOGLE_INDEXING_TEXT_CHARS)
    type: GoogleIndexingNotificationType
    notifyTime: str | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_GOOGLE_INDEXING_TEXT_CHARS,
    )

    @field_validator("type", mode="before")
    @classmethod
    def validate_notification_type(cls, value: object) -> GoogleIndexingNotificationType:
        if not isinstance(value, str):
            raise ValueError("Google Indexing notification type must be a string")
        try:
            return GoogleIndexingNotificationType(value)
        except ValueError as error:
            raise ValueError("Google Indexing notification type is unsupported") from error

    @field_validator("notifyTime")
    @classmethod
    def validate_notify_time(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            timestamp = datetime.fromisoformat(value)
        except ValueError as error:
            raise ValueError("Google Indexing notifyTime must be an RFC 3339 timestamp") from error
        if timestamp.tzinfo is None:
            raise ValueError("Google Indexing notifyTime must include a timezone")
        return value


class _GoogleIndexingMetadataResponse(BaseModel):
    """The constrained metadata fields Rankrat exposes."""

    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)

    url: str = Field(min_length=1, max_length=MAX_GOOGLE_INDEXING_TEXT_CHARS)
    latestUpdate: _GoogleIndexingNotificationResponse | None = None
    latestRemove: _GoogleIndexingNotificationResponse | None = None


class _GoogleIndexingPublishResponse(BaseModel):
    """The documented wrapper used by Google Indexing publish responses."""

    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)

    urlNotificationMetadata: _GoogleIndexingMetadataResponse


@dataclass(frozen=True, slots=True)
class GoogleIndexingBatchReceipt:
    """A bounded, secret-free acknowledgement for one submitted notification."""

    url: str
    notification_type: str
    accepted: bool
    failure_code: ProviderFailureCode | None


class GoogleIndexingClient:
    """Publish one notification through the sole supported Google Indexing URL."""

    def __init__(self, client: GoogleSearchConsoleClient) -> None:
        self._client = client

    async def publish(
        self,
        account_id: str,
        url: str,
        notification_type: str,
        timeout_seconds: float,
    ) -> GoogleIndexingPublishReceipt:
        """Send a validated update or deletion notification."""

        if notification_type not in (URL_UPDATED, URL_DELETED):
            raise ValueError("unsupported Google Indexing notification type")
        payload = await self._client.publish_indexing_notification(
            account_id,
            url,
            notification_type,
            timeout_seconds,
        )
        try:
            return _publish_receipt(payload, url)
        except ValueError as error:
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "Google Indexing returned an invalid publish receipt",
            ) from error

    async def metadata(
        self,
        account_id: str,
        url: str,
        timeout_seconds: float,
    ) -> GoogleIndexingMetadata:
        """Read receipt metadata for one already-authorized URL notification."""

        payload = await self._client.get_indexing_notification_metadata(
            account_id,
            url,
            timeout_seconds,
        )
        try:
            return _metadata(payload, url)
        except ValueError as error:
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "Google Indexing returned invalid notification metadata",
            ) from error

    async def publish_batch(
        self,
        account_id: str,
        notifications: tuple[tuple[str, str], ...],
        timeout_seconds: float,
    ) -> tuple[GoogleIndexingBatchReceipt, ...]:
        """Publish one bounded notification set through Google's multipart endpoint."""

        if not notifications:
            raise ValueError("Google Indexing batch must include one notification")
        for _, notification_type in notifications:
            if notification_type not in (URL_UPDATED, URL_DELETED):
                raise ValueError("unsupported Google Indexing notification type")
        parts = await self._client.publish_indexing_notification_batch(
            account_id,
            notifications,
            timeout_seconds,
        )
        return tuple(
            self._batch_receipt(notification, part)
            for notification, part in zip(notifications, parts, strict=True)
        )

    @staticmethod
    def _batch_receipt(
        notification: tuple[str, str],
        part: GoogleIndexingBatchPartResponse,
    ) -> GoogleIndexingBatchReceipt:
        if 200 <= part.status_code < 300:
            return GoogleIndexingBatchReceipt(
                url=notification[0],
                notification_type=notification[1],
                accepted=True,
                failure_code=None,
            )
        failure_codes = {
            401: ProviderFailureCode.AUTHENTICATION,
            403: ProviderFailureCode.FORBIDDEN,
            429: ProviderFailureCode.RATE_LIMITED,
        }
        failure_code = failure_codes.get(part.status_code)
        if failure_code is None:
            failure_code = (
                ProviderFailureCode.UNAVAILABLE
                if part.status_code >= 500
                else ProviderFailureCode.INVALID_RESPONSE
            )
        return GoogleIndexingBatchReceipt(
            url=notification[0],
            notification_type=notification[1],
            accepted=False,
            failure_code=failure_code,
        )


def _notification(response: _GoogleIndexingNotificationResponse) -> GoogleIndexingNotification:
    return GoogleIndexingNotification(response.url, response.type, response.notifyTime)


def _metadata(payload: object, expected_url: str) -> GoogleIndexingMetadata:
    try:
        response = _GoogleIndexingMetadataResponse.model_validate(payload)
        if response.url != expected_url:
            raise ValueError("Google Indexing returned metadata for a different URL")
        latest_update = response.latestUpdate
        latest_remove = response.latestRemove
        if latest_update is not None and latest_update.url != expected_url:
            raise ValueError("Google Indexing returned metadata for a different URL")
        if latest_remove is not None and latest_remove.url != expected_url:
            raise ValueError("Google Indexing returned metadata for a different URL")
        if (
            latest_update is not None
            and latest_update.type is not GoogleIndexingNotificationType.UPDATED
        ):
            raise ValueError("Google Indexing latest update had the wrong notification type")
        if (
            latest_remove is not None
            and latest_remove.type is not GoogleIndexingNotificationType.DELETED
        ):
            raise ValueError("Google Indexing latest removal had the wrong notification type")
        return GoogleIndexingMetadata(
            url=response.url,
            latest_update=_notification(latest_update) if latest_update is not None else None,
            latest_remove=_notification(latest_remove) if latest_remove is not None else None,
        )
    except (ValidationError, ValueError) as error:
        raise ValueError("Google Indexing returned invalid notification metadata") from error


def _publish_receipt(payload: object, expected_url: str) -> GoogleIndexingPublishReceipt:
    try:
        response = _GoogleIndexingPublishResponse.model_validate(payload)
        return GoogleIndexingPublishReceipt(
            _metadata(response.urlNotificationMetadata, expected_url)
        )
    except (ValidationError, ValueError) as error:
        raise ValueError("Google Indexing returned an invalid publish receipt") from error
