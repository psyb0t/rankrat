from __future__ import annotations

from pathlib import Path

import pytest

from rankrat.models.boundaries import BoundaryDocument
from rankrat.policy.boundaries import BoundaryPolicy
from rankrat.providers.google_search_console import GoogleSearchConsoleClient
from rankrat.services.google_sites import (
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
    )


@pytest.mark.asyncio
async def test_google_site_add_is_boundary_limited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service()
    added: list[tuple[object, ...]] = []

    async def add_site(*args: object) -> None:
        added.append(args)

    monkeypatch.setattr(service._client, "add_site", add_site)
    response = await service.submit(
        GoogleSiteSubmissionRequest(
            "google-main",
            "sc-domain:example.com",
            GoogleSiteOperation.ADD,
        )
    )

    assert response.operation is GoogleSiteOperation.ADD
    assert added[0][1:] == ("sc-domain:example.com",)
    assert len(added) == 1


@pytest.mark.asyncio
async def test_google_site_accepts_account_scoped_property_intent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service()
    deleted = False

    async def delete_site(*_: object) -> None:
        nonlocal deleted
        deleted = True

    monkeypatch.setattr(service._client, "delete_site", delete_site)
    await service.submit(
        GoogleSiteSubmissionRequest(
            "google-main",
            "sc-domain:outside.example.com",
            GoogleSiteOperation.DELETE,
        )
    )
    assert deleted is True


@pytest.mark.asyncio
async def test_google_site_submit_logs_and_preserves_provider_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service()

    async def delete_site(*_: object) -> None:
        raise RuntimeError("upstream failure")

    monkeypatch.setattr(service._client, "delete_site", delete_site)
    request = GoogleSiteSubmissionRequest(
        "google-main",
        "sc-domain:example.com",
        GoogleSiteOperation.DELETE,
    )
    with pytest.raises(RuntimeError, match="upstream failure"):
        await service.submit(request)
