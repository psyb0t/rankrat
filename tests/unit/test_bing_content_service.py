from __future__ import annotations

import base64
from pathlib import Path
from typing import cast

import pytest

from rankrat.errors import BoundaryDeniedError, InputLimitError
from rankrat.models.boundaries import BoundaryDocument
from rankrat.policy.boundaries import BoundaryPolicy
from rankrat.providers.bing import BingWebmasterClient
from rankrat.providers.site_fetch import PublicSiteFetcher, SiteFetchResult
from rankrat.services.bing_content import (
    BingContentSubmissionRequest,
    BingContentSubmissionService,
)


def _policy(tmp_path: Path) -> BoundaryPolicy:
    return BoundaryPolicy(
        BoundaryDocument.model_validate(
            {
                "accounts": [
                    {
                        "id": "bing-main",
                        "provider": "bing",
                        "credential": str(tmp_path / "bing-api-key"),
                        "sites": ["https://example.com/"],
                    }
                ]
            }
        )
    )


class _Fetcher:
    def __init__(self, result: SiteFetchResult) -> None:
        self._result = result
        self.urls: list[str] = []

    async def fetch(self, url: str, _: float) -> SiteFetchResult:
        self.urls.append(url)
        return self._result


class _BingClient:
    def __init__(self) -> None:
        self.submissions: list[tuple[str, str, str, bool]] = []

    async def submit_content(
        self,
        _: object,
        site_url: str,
        page_url: str,
        http_message: str,
        dynamic_serving: bool,
    ) -> None:
        self.submissions.append((site_url, page_url, http_message, dynamic_serving))


@pytest.mark.asyncio
async def test_bing_content_submission_constructs_a_safe_message_from_the_fresh_fetch(
    tmp_path: Path,
) -> None:
    fetcher = _Fetcher(
        SiteFetchResult(
            "https://example.com/article",
            200,
            "text/html",
            b"<html>\xc5\x9f</html>",
            (("set-cookie", "must-not-leak"),),
        )
    )
    client = _BingClient()
    service = BingContentSubmissionService(
        _policy(tmp_path),
        cast(PublicSiteFetcher, fetcher),
        cast(BingWebmasterClient, client),
    )

    receipt = await service.submit(
        BingContentSubmissionRequest(
            account_id="bing-main",
            site_url="https://example.com/",
            page_url="https://example.com/article",
            dynamic_serving=True,
        )
    )

    assert receipt.content_bytes == len(b"<html>\xc5\x9f</html>")
    assert fetcher.urls == ["https://example.com/article"]
    site_url, page_url, encoded_message, dynamic_serving = client.submissions[0]
    assert (site_url, page_url, dynamic_serving) == (
        "https://example.com/",
        "https://example.com/article",
        True,
    )
    assert base64.b64decode(encoded_message) == (
        b"HTTP/1.1 200 OK\r\n"
        b"Content-Type: text/html; charset=utf-8\r\n"
        b"Content-Length: 15\r\n\r\n"
        b"<html>\xc5\x9f</html>"
    )
    assert "cookie" not in encoded_message.casefold()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "result",
    (
        SiteFetchResult("https://example.com/article", 302, "text/html", b"<html />"),
        SiteFetchResult("https://example.com/article", 200, "text/plain", b"body"),
        SiteFetchResult("https://example.com/article", 200, "text/html", b""),
    ),
)
async def test_bing_content_submission_rejects_unsafe_fetch_outcomes(
    tmp_path: Path,
    result: SiteFetchResult,
) -> None:
    client = _BingClient()
    service = BingContentSubmissionService(
        _policy(tmp_path),
        cast(PublicSiteFetcher, _Fetcher(result)),
        cast(BingWebmasterClient, client),
    )
    with pytest.raises(InputLimitError):
        await service.submit(
            BingContentSubmissionRequest(
                account_id="bing-main",
                site_url="https://example.com/",
                page_url="https://example.com/article",
            )
        )
    assert client.submissions == []


@pytest.mark.asyncio
async def test_bing_content_submission_rejects_pages_outside_the_site_before_fetch(
    tmp_path: Path,
) -> None:
    fetcher = _Fetcher(SiteFetchResult("https://evil.example/", 200, "text/html", b"body"))
    service = BingContentSubmissionService(
        _policy(tmp_path),
        cast(PublicSiteFetcher, fetcher),
        cast(BingWebmasterClient, _BingClient()),
    )
    with pytest.raises(BoundaryDeniedError):
        await service.submit(
            BingContentSubmissionRequest(
                account_id="bing-main",
                site_url="https://example.com/",
                page_url="https://evil.example/",
            )
        )
    assert fetcher.urls == []
