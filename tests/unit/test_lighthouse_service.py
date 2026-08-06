from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from rankrat.errors import BoundaryDeniedError
from rankrat.models.boundaries import BoundaryDocument
from rankrat.policy.boundaries import BoundaryPolicy
from rankrat.providers.base import ProviderFailureCode, ProviderOperationError
from rankrat.providers.lighthouse import LighthouseWorkerClient
from rankrat.services.lighthouse import (
    LighthouseAuditRequest,
    LighthouseCategory,
    LighthouseService,
)


def _policy(tmp_path: Path) -> BoundaryPolicy:
    document = BoundaryDocument.model_validate(
        {
            "accounts": [
                {
                    "id": "pagespeed-main",
                    "provider": "google",
                    "credential": str(tmp_path / "google.json"),
                    "pagespeed_sites": ["https://example.com/docs/"],
                }
            ]
        }
    )
    return BoundaryPolicy(document)


def _response(
    *,
    requested_url: str = "https://example.com/docs/page",
    final_url: str = "https://example.com/docs/final",
    categories: dict[str, object] | None = None,
) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "requestedUrl": requested_url,
            "finalUrl": final_url,
            "fetchTime": "2026-08-05T18:30:32+00:00",
            "lighthouseVersion": "13.4.1",
            "categories": categories or {"seo": {"score": 0.5}},
            "findings": [],
        },
    )


def _request() -> LighthouseAuditRequest:
    return LighthouseAuditRequest(
        account_id="pagespeed-main",
        site_url="https://example.com/docs/",
        page_url="https://example.com/docs/page",
    )


def _service(tmp_path: Path, response: httpx.Response) -> LighthouseService:
    client = LighthouseWorkerClient(
        Path("/run/lighthouse/test.sock"),
        lambda _: httpx.MockTransport(lambda __: response),
    )
    return LighthouseService(_policy(tmp_path), client)


@pytest.mark.asyncio
async def test_lighthouse_service_runs_only_the_selected_category(tmp_path: Path) -> None:
    service = _service(tmp_path, _response())

    report = await service.findings(_request(), LighthouseCategory.SEO)

    assert [item.category for item in report.categories] == ["seo"]


@pytest.mark.asyncio
async def test_lighthouse_service_rejects_page_outside_configured_boundary(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path, _response())
    outside = LighthouseAuditRequest(
        account_id="pagespeed-main",
        site_url="https://example.com/docs/",
        page_url="https://example.com/private",
    )

    with pytest.raises(BoundaryDeniedError):
        await service.findings(outside, LighthouseCategory.SEO)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        _response(final_url="https://attacker.example/final"),
        _response(requested_url="https://example.com/docs/different"),
        _response(categories={"performance": {"score": 1}}),
    ],
)
async def test_lighthouse_service_rejects_inconsistent_worker_report(
    tmp_path: Path,
    response: httpx.Response,
) -> None:
    service = _service(tmp_path, response)

    with pytest.raises(ProviderOperationError) as caught:
        await service.findings(_request(), LighthouseCategory.SEO)

    assert caught.value.code is ProviderFailureCode.INVALID_RESPONSE


@pytest.mark.parametrize("timeout", [4.99, 300.01])
def test_lighthouse_request_rejects_timeout_outside_limits(timeout: float) -> None:
    with pytest.raises(ValueError, match="timeout"):
        LighthouseAuditRequest(
            account_id="pagespeed-main",
            site_url="https://example.com/",
            page_url="https://example.com/page",
            timeout_seconds=timeout,
        )
