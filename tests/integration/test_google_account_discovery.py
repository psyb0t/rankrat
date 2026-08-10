from __future__ import annotations

import json
import os
from pathlib import Path

import httpx
import pytest

from rankrat.config import Settings
from rankrat.constants import (
    GOOGLE_ANALYTICS_ACCOUNT_INVENTORY_PATH,
    GOOGLE_ANALYTICS_READ_SCOPE,
)
from rankrat.providers.google_oauth import (
    GoogleOAuthTokenClient,
    GoogleOAuthTokenRecord,
    GoogleOAuthTokenStore,
)
from rankrat.transports.http import create_http_app
from rankrat.transports.runtime import build_services

_ACCOUNT_ID = "google-main"
_CLIENT_ID = "rankrat.example.apps.googleusercontent.com"


@pytest.mark.asyncio
async def test_runtime_uses_oauth_for_google_analytics_and_api_key_for_pagespeed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret_root = tmp_path / "secrets"
    oauth_root = tmp_path / "oauth"
    secret_root.mkdir()
    oauth_root.mkdir(mode=0o700)
    os.chmod(oauth_root, 0o700)
    client_file = secret_root / "google-oauth-client.json"
    client_file.write_text(
        json.dumps({"installed": {"client_id": _CLIENT_ID}}),
        encoding="utf-8",
    )
    token_file = oauth_root / "google-main.json"
    GoogleOAuthTokenStore(
        token_file,
        _ACCOUNT_ID,
        _CLIENT_ID,
        (GOOGLE_ANALYTICS_READ_SCOPE,),
    ).write(
        GoogleOAuthTokenRecord(
            _ACCOUNT_ID,
            _CLIENT_ID,
            "test-refresh-token",
            (GOOGLE_ANALYTICS_READ_SCOPE,),
        )
    )
    pagespeed_api_key_file = secret_root / "pagespeed-main-api-key"
    pagespeed_api_key_file.write_text("test-pagespeed-api-key", encoding="utf-8")
    boundary_file = tmp_path / "boundaries.json"
    boundary_file.write_text(
        json.dumps(
            {
                "accounts": [
                    {
                        "id": _ACCOUNT_ID,
                        "provider": "google",
                        "credential": str(client_file),
                        "oauth_token_file": str(token_file),
                        "pagespeed_api_key_file": str(pagespeed_api_key_file),
                        "pagespeed_sites": ["https://example.com/"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    settings = Settings(
        boundary_file=boundary_file,
        secret_root=secret_root,
        oauth_token_root=oauth_root,
        log_file=tmp_path / "rankrat.log",
    )
    services = build_services(settings)

    def token_handler(request: httpx.Request) -> httpx.Response:
        assert request.url == httpx.URL("https://oauth2.googleapis.com/token")
        assert b"refresh_token=test-refresh-token" in request.content
        return httpx.Response(
            200,
            json={
                "access_token": "test-access-token",
                "expires_in": 3600,
                "scope": GOOGLE_ANALYTICS_READ_SCOPE,
                "token_type": "Bearer",
            },
        )

    provider_requests: list[httpx.Request] = []
    pagespeed_requests: list[httpx.Request] = []

    def google_admin_handler(request: httpx.Request) -> httpx.Response:
        provider_requests.append(request)
        return httpx.Response(
            200,
            json={
                "accountSummaries": [
                    {
                        "name": "accountSummaries/123",
                        "account": "accounts/123",
                        "displayName": "Example account",
                        "propertySummaries": [
                            {"property": "properties/456", "displayName": "Example property"}
                        ],
                    }
                ]
            },
        )

    def pagespeed_handler(request: httpx.Request) -> httpx.Response:
        pagespeed_requests.append(request)
        return httpx.Response(
            200,
            json={
                "analysisUTCTimestamp": "2026-07-30T00:00:00Z",
                "id": "https://example.com/article",
                "lighthouseResult": {
                    "categories": {"performance": {"id": "performance", "score": 1.0}}
                },
            },
        )

    analytics_client = services.google_analytics._client
    token_provider = analytics_client._access_token_provider
    monkeypatch.setattr(
        token_provider,
        "_oauth_token_client",
        GoogleOAuthTokenClient(lambda: httpx.MockTransport(token_handler)),
    )
    monkeypatch.setattr(
        analytics_client,
        "_transport_factory",
        lambda: httpx.MockTransport(google_admin_handler),
    )
    pagespeed_client = services.pagespeed._client
    monkeypatch.setattr(
        pagespeed_client,
        "_transport_factory",
        lambda: httpx.MockTransport(pagespeed_handler),
    )
    app = create_http_app(settings, services)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://rankrat.test",
    ) as client:
        response = await client.post(
            f"/v1{GOOGLE_ANALYTICS_ACCOUNT_INVENTORY_PATH}",
            json={"account_id": _ACCOUNT_ID},
        )
        pagespeed_response = await client.post(
            "/v1/pagespeed/analyses",
            json={
                "account_id": _ACCOUNT_ID,
                "site_url": "https://example.com/",
                "page_url": "https://example.com/article",
            },
        )

    assert response.status_code == 200
    assert response.json()[0]["properties"][0]["property_id"] == "456"
    assert len(provider_requests) == 1
    assert provider_requests[0].method == "GET"
    assert str(provider_requests[0].url) == (
        "https://analyticsadmin.googleapis.com/v1beta/accountSummaries?pageSize=200"
    )
    assert provider_requests[0].headers["Authorization"] == "Bearer test-access-token"
    assert pagespeed_response.status_code == 200
    assert len(pagespeed_requests) == 1
    assert "Authorization" not in pagespeed_requests[0].headers
    assert pagespeed_requests[0].url.params.get("key") == "test-pagespeed-api-key"
    assert pagespeed_requests[0].url.params.get("access_token") is None
