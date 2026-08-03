from __future__ import annotations

from pathlib import Path

import pytest

from rankrat.errors import ApprovalDeniedError, BoundaryDeniedError
from rankrat.models.boundaries import BoundaryDocument
from rankrat.policy.approvals import WriteApprovalStore
from rankrat.policy.boundaries import BoundaryPolicy
from rankrat.providers.google_search_console import GoogleSearchConsoleClient
from rankrat.services.google_sites import (
    GoogleSiteApprovalRequest,
    GoogleSiteOperation,
    GoogleSiteService,
    GoogleSiteSubmissionRequest,
)


async def _token(credential_path: Path) -> str:
    del credential_path
    return "test-token"


def _service() -> GoogleSiteService:
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
    return GoogleSiteService(
        policy,
        GoogleSearchConsoleClient(policy, _token),
        WriteApprovalStore(),
    )


@pytest.mark.asyncio
async def test_google_site_add_requires_exact_one_use_approval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service()
    added: list[tuple[object, ...]] = []

    async def add_site(*args: object) -> None:
        added.append(args)

    monkeypatch.setattr(service._client, "add_site", add_site)
    approval_request = GoogleSiteApprovalRequest(
        "google-main",
        "sc-domain:example.com",
        GoogleSiteOperation.ADD,
    )
    approval = await service.approve(approval_request)
    response = await service.submit(
        GoogleSiteSubmissionRequest(
            "google-main",
            "sc-domain:example.com",
            GoogleSiteOperation.ADD,
            approval.approval_id,
        )
    )

    assert response.operation is GoogleSiteOperation.ADD
    assert added[0][1:] == ("sc-domain:example.com",)
    with pytest.raises(ApprovalDeniedError):
        await service.submit(
            GoogleSiteSubmissionRequest(
                "google-main",
                "sc-domain:example.com",
                GoogleSiteOperation.ADD,
                approval.approval_id,
            )
        )
    assert len(added) == 1


@pytest.mark.asyncio
async def test_google_site_delete_rejects_changed_or_out_of_scope_intent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service()
    deleted = False

    async def delete_site(*_: object) -> None:
        nonlocal deleted
        deleted = True

    monkeypatch.setattr(service._client, "delete_site", delete_site)
    approval = await service.approve(
        GoogleSiteApprovalRequest(
            "google-main",
            "sc-domain:example.com",
            GoogleSiteOperation.DELETE,
        )
    )
    with pytest.raises(ApprovalDeniedError):
        await service.submit(
            GoogleSiteSubmissionRequest(
                "google-main",
                "sc-domain:example.com",
                GoogleSiteOperation.ADD,
                approval.approval_id,
            )
        )
    with pytest.raises(BoundaryDeniedError):
        await service.approve(
            GoogleSiteApprovalRequest(
                "google-main",
                "sc-domain:outside.example.com",
                GoogleSiteOperation.DELETE,
            )
        )
    assert deleted is False


@pytest.mark.asyncio
async def test_google_site_submit_logs_and_preserves_provider_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service()

    async def delete_site(*_: object) -> None:
        raise RuntimeError("upstream failure")

    monkeypatch.setattr(service._client, "delete_site", delete_site)
    request = GoogleSiteApprovalRequest(
        "google-main",
        "sc-domain:example.com",
        GoogleSiteOperation.DELETE,
    )
    approval = await service.approve(request)
    with pytest.raises(RuntimeError, match="upstream failure"):
        await service.submit(
            GoogleSiteSubmissionRequest(
                "google-main",
                "sc-domain:example.com",
                GoogleSiteOperation.DELETE,
                approval.approval_id,
            )
        )
