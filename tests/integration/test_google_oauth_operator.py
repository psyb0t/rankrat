from __future__ import annotations

import asyncio
import os
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from rankrat.models.boundaries import BoundaryDocument
from rankrat.providers.google_oauth import (
    GoogleOAuthTokenClient,
    GoogleOAuthTokenStore,
    authorize_google_oauth_account,
    google_oauth_authorization_scopes,
    revoke_google_oauth_account,
)

_ACCOUNT_ID = "google-oauth"
_CLIENT_ID = "client-id.example.apps.googleusercontent.com"


@pytest.mark.asyncio
async def test_operator_flow_uses_an_actual_loopback_callback_and_mocked_google_endpoints(
    tmp_path: Path,
) -> None:
    secret_root = tmp_path / "secrets"
    secret_root.mkdir()
    oauth_root = tmp_path / "oauth"
    oauth_root.mkdir(mode=0o700)
    os.chmod(oauth_root, 0o700)
    client_file = secret_root / "oauth-client.json"
    client_file.write_text(
        '{"installed":{"client_id":"client-id.example.apps.googleusercontent.com"}}',
        encoding="utf-8",
    )
    account = BoundaryDocument.model_validate(
        {
            "accounts": [
                {
                    "id": _ACCOUNT_ID,
                    "provider": "google",
                    "credential": str(client_file),
                    "oauth_token_file": str(oauth_root / "google-oauth.json"),
                    "search_console_sites": ["https://example.com/"],
                }
            ]
        }
    ).accounts[0]
    scopes = google_oauth_authorization_scopes()
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/revoke":
            return httpx.Response(200)
        return httpx.Response(
            200,
            json={
                "access_token": "short-lived-access-token",
                "expires_in": 3600,
                "refresh_token": "refresh-token",
                "refresh_token_expires_in": 3600,
                "scope": " ".join(scopes),
                "token_type": "Bearer",
            },
        )

    async def submit_callback(authorization_url: str) -> None:
        query = parse_qs(urlparse(authorization_url).query)
        callback = urlparse(query["redirect_uri"][0])
        async with httpx.AsyncClient(trust_env=False) as client:
            response = await client.get(
                f"http://{callback.netloc}{callback.path}",
                params={
                    "state": query["state"][0],
                    "code": "authorization-code",
                    "iss": "https://accounts.google.com",
                    "scope": " ".join(query["scope"]),
                },
            )
        assert response.status_code == 200

    def browser_opener(authorization_url: str) -> bool:
        asyncio.get_running_loop().create_task(submit_callback(authorization_url))
        return True

    token_client = GoogleOAuthTokenClient(lambda: httpx.MockTransport(handler))
    await authorize_google_oauth_account(
        account,
        enable_writes=False,
        browser_opener=browser_opener,
        token_client=token_client,
    )
    token_store = GoogleOAuthTokenStore(
        oauth_root / "google-oauth.json",
        _ACCOUNT_ID,
        _CLIENT_ID,
        scopes,
    )
    assert token_store.load().refresh_token == "refresh-token"

    await revoke_google_oauth_account(
        account,
        enable_writes=False,
        token_client=token_client,
    )
    assert not (oauth_root / "google-oauth.json").exists()
    assert [str(request.url) for request in requests] == [
        "https://oauth2.googleapis.com/token",
        "https://oauth2.googleapis.com/revoke",
    ]
