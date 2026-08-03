from __future__ import annotations

from pathlib import Path

import pytest

from rankrat.errors import ApprovalDeniedError, BoundaryDeniedError
from rankrat.models.boundaries import BoundaryDocument
from rankrat.policy.approvals import WriteApprovalStore
from rankrat.policy.boundaries import BoundaryPolicy
from rankrat.providers.google_search_console import GoogleSearchConsoleClient
from rankrat.services.google_sitemaps import (
    GoogleSitemapApprovalRequest,
    GoogleSitemapOperation,
    GoogleSitemapService,
    GoogleSitemapSubmissionRequest,
)


async def _token(credential_path: Path) -> str:
    del credential_path
    return "test-token"


def _service() -> GoogleSitemapService:
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
    return GoogleSitemapService(
        policy,
        GoogleSearchConsoleClient(policy, _token),
        WriteApprovalStore(),
    )


@pytest.mark.asyncio
async def test_google_sitemap_submit_requires_exact_one_use_approval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service()
    submitted: list[tuple[object, ...]] = []

    async def submit_sitemap(*args: object) -> None:
        submitted.append(args)

    monkeypatch.setattr(service._client, "submit_sitemap", submit_sitemap)
    approval_request = GoogleSitemapApprovalRequest(
        "google-main",
        "sc-domain:example.com",
        "https://example.com/sitemap.xml",
        GoogleSitemapOperation.SUBMIT,
    )
    approval = await service.approve(approval_request)
    response = await service.submit(
        GoogleSitemapSubmissionRequest(
            "google-main",
            "sc-domain:example.com",
            "https://example.com/sitemap.xml",
            GoogleSitemapOperation.SUBMIT,
            approval.approval_id,
        )
    )

    assert response.operation is GoogleSitemapOperation.SUBMIT
    assert submitted[0][1:] == (
        "sc-domain:example.com",
        "https://example.com/sitemap.xml",
    )
    with pytest.raises(ApprovalDeniedError):
        await service.submit(
            GoogleSitemapSubmissionRequest(
                "google-main",
                "sc-domain:example.com",
                "https://example.com/sitemap.xml",
                GoogleSitemapOperation.SUBMIT,
                approval.approval_id,
            )
        )
    assert len(submitted) == 1


@pytest.mark.asyncio
async def test_google_sitemap_delete_rejects_changed_or_out_of_scope_intent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service()
    deleted = False

    async def delete_sitemap(*_: object) -> None:
        nonlocal deleted
        deleted = True

    monkeypatch.setattr(service._client, "delete_sitemap", delete_sitemap)
    approval = await service.approve(
        GoogleSitemapApprovalRequest(
            "google-main",
            "sc-domain:example.com",
            "https://example.com/sitemap.xml",
            GoogleSitemapOperation.DELETE,
        )
    )
    with pytest.raises(ApprovalDeniedError):
        await service.submit(
            GoogleSitemapSubmissionRequest(
                "google-main",
                "sc-domain:example.com",
                "https://example.com/changed.xml",
                GoogleSitemapOperation.DELETE,
                approval.approval_id,
            )
        )
    with pytest.raises(BoundaryDeniedError):
        await service.approve(
            GoogleSitemapApprovalRequest(
                "google-main",
                "sc-domain:example.com",
                "https://outside.example.net/sitemap.xml",
                GoogleSitemapOperation.DELETE,
            )
        )
    assert deleted is False


@pytest.mark.asyncio
async def test_google_sitemap_submit_logs_and_preserves_provider_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service()

    async def submit_sitemap(*_: object) -> None:
        raise RuntimeError("upstream failure")

    monkeypatch.setattr(service._client, "submit_sitemap", submit_sitemap)
    request = GoogleSitemapApprovalRequest(
        "google-main",
        "sc-domain:example.com",
        "https://example.com/sitemap.xml",
        GoogleSitemapOperation.SUBMIT,
    )
    approval = await service.approve(request)
    with pytest.raises(RuntimeError, match="upstream failure"):
        await service.submit(
            GoogleSitemapSubmissionRequest(
                "google-main",
                "sc-domain:example.com",
                "https://example.com/sitemap.xml",
                GoogleSitemapOperation.SUBMIT,
                approval.approval_id,
            )
        )
