from __future__ import annotations

from pathlib import Path

import pytest

from rankrat.errors import ApprovalDeniedError, BoundaryDeniedError, InputLimitError
from rankrat.models.boundaries import BoundaryDocument
from rankrat.policy.approvals import WriteApprovalStore
from rankrat.policy.boundaries import BoundaryPolicy
from rankrat.providers.base import ProviderFailureCode
from rankrat.providers.google_indexing import (
    GoogleIndexingBatchReceipt,
    GoogleIndexingClient,
    GoogleIndexingMetadata,
    GoogleIndexingPublishReceipt,
)
from rankrat.providers.google_search_console import GoogleSearchConsoleClient
from rankrat.providers.schema_fetch import PublicSchemaFetcher, SchemaFetchResult
from rankrat.services.google_indexing import (
    GoogleIndexingApprovalRequest,
    GoogleIndexingBatchApprovalRequest,
    GoogleIndexingBatchNotification,
    GoogleIndexingBatchSubmissionRequest,
    GoogleIndexingNotificationType,
    GoogleIndexingService,
    GoogleIndexingSubmissionRequest,
)
from rankrat.services.google_indexing_metadata import (
    GoogleIndexingMetadataRequest,
    GoogleIndexingMetadataService,
)


async def _token(credential_path: Path) -> str:
    del credential_path
    return "test-token"


def _publish_receipt(url: str) -> GoogleIndexingPublishReceipt:
    return GoogleIndexingPublishReceipt(GoogleIndexingMetadata(url, None, None))


def _service() -> GoogleIndexingService:
    policy = BoundaryPolicy(
        BoundaryDocument.model_validate(
            {
                "accounts": [
                    {
                        "id": "google-main",
                        "provider": "google",
                        "credential": "/run/secrets/google.json",
                        "search_console_sites": ["sc-domain:example.com"],
                    }
                ]
            }
        )
    )
    client = GoogleIndexingClient(GoogleSearchConsoleClient(policy, _token))
    return GoogleIndexingService(policy, client, WriteApprovalStore(), PublicSchemaFetcher())


@pytest.mark.asyncio
async def test_google_indexing_update_requires_eligible_schema_and_exact_one_use_approval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service()
    fetched: list[tuple[str, float]] = []
    published: list[tuple[str, str, str, float]] = []

    async def fetch(url: str, timeout_seconds: float) -> SchemaFetchResult:
        fetched.append((url, timeout_seconds))
        return SchemaFetchResult(
            url,
            "text/html",
            b'<script type="application/ld+json">{"@type":"JobPosting"}</script>',
        )

    async def publish(
        account_id: str,
        url: str,
        notification_type: str,
        timeout_seconds: float,
    ) -> GoogleIndexingPublishReceipt:
        published.append((account_id, url, notification_type, timeout_seconds))
        return _publish_receipt(url)

    monkeypatch.setattr(service._schema_fetcher, "fetch", fetch)
    monkeypatch.setattr(service._client, "publish", publish)
    approval_request = GoogleIndexingApprovalRequest(
        "google-main",
        "sc-domain:example.com",
        "https://example.com/jobs/one",
        GoogleIndexingNotificationType.UPDATED,
    )
    approval = await service.approve(approval_request)
    result = await service.submit(
        GoogleIndexingSubmissionRequest(
            "google-main",
            "sc-domain:example.com",
            "https://example.com/jobs/one",
            GoogleIndexingNotificationType.UPDATED,
            approval.approval_id,
            1.5,
        )
    )

    assert result == _publish_receipt("https://example.com/jobs/one")
    assert fetched == [
        ("https://example.com/jobs/one", 10.0),
        ("https://example.com/jobs/one", 1.5),
    ]
    assert published == [
        (
            "google-main",
            "https://example.com/jobs/one",
            "URL_UPDATED",
            1.5,
        )
    ]
    with pytest.raises(ApprovalDeniedError):
        await service.submit(
            GoogleIndexingSubmissionRequest(
                "google-main",
                "sc-domain:example.com",
                "https://example.com/jobs/one",
                GoogleIndexingNotificationType.UPDATED,
                approval.approval_id,
            )
        )
    assert len(published) == 1


@pytest.mark.asyncio
async def test_google_indexing_rejects_ineligible_or_out_of_scope_updates_before_publish(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service()
    published = False

    async def fetch(url: str, _: float) -> SchemaFetchResult:
        return SchemaFetchResult(url, "text/html", b"<html><body>no schema</body></html>")

    async def publish(*_: object) -> GoogleIndexingPublishReceipt:
        nonlocal published
        published = True
        return _publish_receipt("https://example.com/post")

    monkeypatch.setattr(service._schema_fetcher, "fetch", fetch)
    monkeypatch.setattr(service._client, "publish", publish)
    with pytest.raises(ApprovalDeniedError):
        await service.approve(
            GoogleIndexingApprovalRequest(
                "google-main",
                "sc-domain:example.com",
                "https://example.com/post",
                GoogleIndexingNotificationType.UPDATED,
            )
        )
    with pytest.raises(BoundaryDeniedError):
        await service.approve(
            GoogleIndexingApprovalRequest(
                "google-main",
                "sc-domain:example.com",
                "https://outside.example.net/post",
                GoogleIndexingNotificationType.UPDATED,
            )
        )
    assert published is False


@pytest.mark.asyncio
async def test_google_indexing_delete_skips_schema_but_rejects_changed_approval_intent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service()
    fetch_called = False
    published: list[str] = []

    async def fetch(*_: object) -> SchemaFetchResult:
        nonlocal fetch_called
        fetch_called = True
        raise AssertionError("deleted pages must not be fetched")

    async def publish(
        _: str,
        url: str,
        __: str,
        ___: float,
    ) -> GoogleIndexingPublishReceipt:
        published.append(url)
        return _publish_receipt(url)

    monkeypatch.setattr(service._schema_fetcher, "fetch", fetch)
    monkeypatch.setattr(service._client, "publish", publish)
    approval_request = GoogleIndexingApprovalRequest(
        "google-main",
        "sc-domain:example.com",
        "https://example.com/deleted",
        GoogleIndexingNotificationType.DELETED,
    )
    approval = await service.approve(approval_request)
    with pytest.raises(ApprovalDeniedError):
        await service.submit(
            GoogleIndexingSubmissionRequest(
                "google-main",
                "sc-domain:example.com",
                "https://example.com/changed",
                GoogleIndexingNotificationType.DELETED,
                approval.approval_id,
            )
        )
    assert fetch_called is False
    assert published == []


@pytest.mark.asyncio
async def test_google_indexing_logs_and_preserves_provider_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service()

    async def publish(*_: object) -> GoogleIndexingPublishReceipt:
        raise RuntimeError("upstream failure")

    monkeypatch.setattr(service._client, "publish", publish)
    approval_request = GoogleIndexingApprovalRequest(
        "google-main",
        "sc-domain:example.com",
        "https://example.com/deleted",
        GoogleIndexingNotificationType.DELETED,
    )
    approval = await service.approve(approval_request)
    with pytest.raises(RuntimeError, match="upstream failure"):
        await service.submit(
            GoogleIndexingSubmissionRequest(
                "google-main",
                "sc-domain:example.com",
                "https://example.com/deleted",
                GoogleIndexingNotificationType.DELETED,
                approval.approval_id,
            )
        )


@pytest.mark.asyncio
async def test_google_indexing_metadata_requires_owned_url_before_client_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    indexing_service = _service()
    service = GoogleIndexingMetadataService(indexing_service._policy, indexing_service._client)
    calls: list[tuple[str, str, float]] = []

    async def metadata(
        account_id: str,
        url: str,
        timeout_seconds: float,
    ) -> GoogleIndexingMetadata:
        calls.append((account_id, url, timeout_seconds))
        return GoogleIndexingMetadata(url, None, None)

    monkeypatch.setattr(indexing_service._client, "metadata", metadata)
    result = await service.metadata(
        GoogleIndexingMetadataRequest(
            "google-main",
            "sc-domain:example.com",
            "https://example.com/metadata",
            2.0,
        )
    )

    assert result == GoogleIndexingMetadata("https://example.com/metadata", None, None)
    assert calls == [("google-main", "https://example.com/metadata", 2.0)]
    with pytest.raises(BoundaryDeniedError):
        await service.metadata(
            GoogleIndexingMetadataRequest(
                "google-main",
                "sc-domain:example.com",
                "https://outside.example.net/metadata",
            )
        )
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_google_indexing_batch_requires_exact_ordered_approval_and_reports_partial_receipts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service()
    fetched: list[str] = []
    published: list[tuple[str, tuple[tuple[str, str], ...], float]] = []

    async def fetch(url: str, _: float) -> SchemaFetchResult:
        fetched.append(url)
        return SchemaFetchResult(
            url,
            "text/html",
            b'<script type="application/ld+json">{"@type":"JobPosting"}</script>',
        )

    async def publish_batch(
        account_id: str,
        notifications: tuple[tuple[str, str], ...],
        timeout_seconds: float,
    ) -> tuple[GoogleIndexingBatchReceipt, ...]:
        published.append((account_id, notifications, timeout_seconds))
        return (
            GoogleIndexingBatchReceipt(notifications[0][0], notifications[0][1], True, None),
            GoogleIndexingBatchReceipt(
                notifications[1][0],
                notifications[1][1],
                False,
                ProviderFailureCode.RATE_LIMITED,
            ),
        )

    monkeypatch.setattr(service._schema_fetcher, "fetch", fetch)
    monkeypatch.setattr(service._client, "publish_batch", publish_batch)
    notifications = (
        GoogleIndexingBatchNotification(
            "https://example.com/jobs/one", GoogleIndexingNotificationType.UPDATED
        ),
        GoogleIndexingBatchNotification(
            "https://example.com/jobs/two", GoogleIndexingNotificationType.DELETED
        ),
    )
    approval = await service.approve_batch(
        GoogleIndexingBatchApprovalRequest("google-main", "sc-domain:example.com", notifications)
    )
    result = await service.submit_batch(
        GoogleIndexingBatchSubmissionRequest(
            "google-main",
            "sc-domain:example.com",
            notifications,
            approval.approval_id,
            1.5,
        )
    )

    assert result.accepted_count == 1
    assert result.rejected_count == 1
    assert [receipt.failure_code for receipt in result.receipts] == [
        None,
        ProviderFailureCode.RATE_LIMITED,
    ]
    assert fetched == ["https://example.com/jobs/one", "https://example.com/jobs/one"]
    assert published == [
        (
            "google-main",
            (
                ("https://example.com/jobs/one", "URL_UPDATED"),
                ("https://example.com/jobs/two", "URL_DELETED"),
            ),
            1.5,
        )
    ]

    with pytest.raises(ApprovalDeniedError):
        await service.submit_batch(
            GoogleIndexingBatchSubmissionRequest(
                "google-main",
                "sc-domain:example.com",
                tuple(reversed(notifications)),
                approval.approval_id,
            )
        )
    assert len(published) == 1


@pytest.mark.asyncio
async def test_google_indexing_batch_rejects_invalid_entries_before_fetch_or_publish(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service()
    fetch_called = False
    publish_called = False

    async def fetch(*_: object) -> SchemaFetchResult:
        nonlocal fetch_called
        fetch_called = True
        raise AssertionError("invalid batch must not fetch")

    async def publish_batch(*_: object) -> tuple[GoogleIndexingBatchReceipt, ...]:
        nonlocal publish_called
        publish_called = True
        raise AssertionError("invalid batch must not publish")

    monkeypatch.setattr(service._schema_fetcher, "fetch", fetch)
    monkeypatch.setattr(service._client, "publish_batch", publish_batch)
    with pytest.raises(InputLimitError, match="distinct"):
        await service.approve_batch(
            GoogleIndexingBatchApprovalRequest(
                "google-main",
                "sc-domain:example.com",
                (
                    GoogleIndexingBatchNotification(
                        "https://example.com/one", GoogleIndexingNotificationType.DELETED
                    ),
                    GoogleIndexingBatchNotification(
                        "https://example.com/one", GoogleIndexingNotificationType.DELETED
                    ),
                ),
            )
        )
    with pytest.raises(BoundaryDeniedError):
        await service.approve_batch(
            GoogleIndexingBatchApprovalRequest(
                "google-main",
                "sc-domain:example.com",
                (
                    GoogleIndexingBatchNotification(
                        "https://outside.example.net/one",
                        GoogleIndexingNotificationType.DELETED,
                    ),
                ),
            )
        )
    assert fetch_called is False
    assert publish_called is False


@pytest.mark.asyncio
async def test_google_indexing_batch_rejects_empty_oversized_and_ineligible_updates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service()

    async def fetch(url: str, _: float) -> SchemaFetchResult:
        return SchemaFetchResult(url, "text/html", b"<html></html>")

    monkeypatch.setattr(service._schema_fetcher, "fetch", fetch)
    with pytest.raises(InputLimitError, match="must include"):
        await service.approve_batch(
            GoogleIndexingBatchApprovalRequest("google-main", "sc-domain:example.com", ())
        )
    with pytest.raises(InputLimitError, match="exceeds"):
        await service.approve_batch(
            GoogleIndexingBatchApprovalRequest(
                "google-main",
                "sc-domain:example.com",
                tuple(
                    GoogleIndexingBatchNotification(
                        f"https://example.com/{index}", GoogleIndexingNotificationType.DELETED
                    )
                    for index in range(101)
                ),
            )
        )
    with pytest.raises(ApprovalDeniedError, match="not eligible"):
        await service.approve_batch(
            GoogleIndexingBatchApprovalRequest(
                "google-main",
                "sc-domain:example.com",
                (
                    GoogleIndexingBatchNotification(
                        "https://example.com/no-schema", GoogleIndexingNotificationType.UPDATED
                    ),
                ),
            )
        )


@pytest.mark.asyncio
async def test_google_indexing_batch_logs_and_preserves_provider_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service()

    async def publish_batch(*_: object) -> tuple[GoogleIndexingBatchReceipt, ...]:
        raise RuntimeError("upstream failure")

    monkeypatch.setattr(service._client, "publish_batch", publish_batch)
    notifications = (
        GoogleIndexingBatchNotification(
            "https://example.com/deleted", GoogleIndexingNotificationType.DELETED
        ),
    )
    approval = await service.approve_batch(
        GoogleIndexingBatchApprovalRequest("google-main", "sc-domain:example.com", notifications)
    )
    with pytest.raises(RuntimeError, match="upstream failure"):
        await service.submit_batch(
            GoogleIndexingBatchSubmissionRequest(
                "google-main",
                "sc-domain:example.com",
                notifications,
                approval.approval_id,
            )
        )
