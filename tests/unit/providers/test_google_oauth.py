from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from rankrat.constants import OAUTH_CONTAINER_LISTENER_HOST
from rankrat.models.boundaries import BoundaryDocument
from rankrat.policy.boundaries import BoundaryPolicy
from rankrat.providers import google_oauth as oauth
from rankrat.providers.base import ProviderFailureCode, ProviderOperationError
from rankrat.providers.google_oauth import (
    GoogleOAuthAuthorizationDiagnosticLog,
    GoogleOAuthAuthorizationSession,
    GoogleOAuthClientConfiguration,
    GoogleOAuthLoopbackReceiver,
    GoogleOAuthTokenClient,
    GoogleOAuthTokenRecord,
    GoogleOAuthTokenStore,
    authorize_google_oauth_account,
    google_oauth_authorization_scopes,
    load_google_oauth_client_configuration,
    required_google_oauth_scopes,
    revoke_google_oauth_account,
)
from rankrat.providers.google_search_console import GoogleConfiguredTokenProvider

_ACCOUNT_ID = "google-main"
_CLIENT_ID = "client-id.example.apps.googleusercontent.com"
_SCOPE = "https://www.googleapis.com/auth/webmasters.readonly"
_CALLBACK_URI = "http://127.0.0.1:8765/oauth2/callback"


def _record() -> GoogleOAuthTokenRecord:
    return GoogleOAuthTokenRecord(
        account_id=_ACCOUNT_ID,
        client_id=_CLIENT_ID,
        refresh_token="refresh-token",
        scopes=(_SCOPE,),
    )


def _store(tmp_path: Path) -> GoogleOAuthTokenStore:
    token_root = tmp_path / "oauth"
    token_root.mkdir(mode=0o700)
    os.chmod(token_root, 0o700)
    return GoogleOAuthTokenStore(
        token_root / "google-main.json",
        _ACCOUNT_ID,
        _CLIENT_ID,
        (_SCOPE,),
    )


def test_authorization_session_uses_s256_fixed_origin_and_constant_time_state_validation() -> None:
    session = GoogleOAuthAuthorizationSession(
        code_verifier="dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk",
        state="state-value",
        redirect_uri=_CALLBACK_URI,
        scopes=(_SCOPE,),
    )
    assert session.code_challenge == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"

    authorization = urlparse(session.authorization_url(_CLIENT_ID))
    assert authorization.scheme == "https"
    assert authorization.netloc == "accounts.google.com"
    assert authorization.path == "/o/oauth2/v2/auth"
    query = parse_qs(authorization.query)
    assert query["access_type"] == ["offline"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["prompt"] == [oauth._OAUTH_AUTHORIZATION_PROMPT]
    assert query["redirect_uri"] == [_CALLBACK_URI]
    assert session.validate_callback({"state": ("state-value",), "code": ("code",)}) == "code"

    with pytest.raises(ProviderOperationError) as error:
        session.validate_callback({"state": ("wrong",), "code": ("code",)})
    assert error.value.code is ProviderFailureCode.AUTHENTICATION


def test_google_authorization_requests_every_google_account_data_scope() -> None:
    assert google_oauth_authorization_scopes() == (
        oauth.GOOGLE_SEARCH_CONSOLE_WRITE_SCOPE,
        oauth.GOOGLE_INDEXING_SCOPE,
        oauth.GOOGLE_ANALYTICS_READ_SCOPE,
        oauth.GOOGLE_ANALYTICS_EDIT_SCOPE,
        oauth.GOOGLE_SITE_VERIFICATION_SCOPE,
        oauth.GOOGLE_TAG_MANAGER_EDIT_SCOPE,
        oauth.GOOGLE_TAG_MANAGER_DELETE_SCOPE,
        oauth.GOOGLE_TAG_MANAGER_VERSION_EDIT_SCOPE,
        oauth.GOOGLE_TAG_MANAGER_PUBLISH_SCOPE,
    )


def test_google_oauth_rejects_a_google_grant_missing_account_data_scope(
    tmp_path: Path,
) -> None:
    requested_scopes = google_oauth_authorization_scopes()
    granted_scopes = (
        oauth.GOOGLE_SEARCH_CONSOLE_WRITE_SCOPE,
        oauth.GOOGLE_INDEXING_SCOPE,
    )
    token_path = tmp_path / "token.json"
    token_store = GoogleOAuthTokenStore(
        token_path,
        _ACCOUNT_ID,
        _CLIENT_ID,
        requested_scopes,
    )
    complete_record = GoogleOAuthTokenRecord(
        _ACCOUNT_ID,
        _CLIENT_ID,
        "existing-refresh-token",
        requested_scopes,
    )
    token_store.write(complete_record)
    with pytest.raises(ProviderOperationError) as error:
        oauth._response_scopes(" ".join(granted_scopes), requested_scopes)
    assert error.value.code is ProviderFailureCode.FORBIDDEN
    assert token_store.load() == complete_record
    with pytest.raises(ProviderOperationError) as error:
        token_store.write(
            GoogleOAuthTokenRecord(
                _ACCOUNT_ID,
                _CLIENT_ID,
                "refresh-token",
                granted_scopes,
            )
        )
    assert error.value.code is ProviderFailureCode.FORBIDDEN

    analytics_token_store = GoogleOAuthTokenStore(
        tmp_path / "missing-analytics-token.json",
        _ACCOUNT_ID,
        _CLIENT_ID,
        (oauth.GOOGLE_ANALYTICS_READ_SCOPE,),
    )
    partial_token_store = GoogleOAuthTokenStore(
        tmp_path / "missing-analytics-token.json",
        _ACCOUNT_ID,
        _CLIENT_ID,
        (oauth.GOOGLE_SEARCH_CONSOLE_WRITE_SCOPE,),
    )
    partial_token_store.write(
        GoogleOAuthTokenRecord(
            _ACCOUNT_ID,
            _CLIENT_ID,
            "refresh-token",
            (oauth.GOOGLE_SEARCH_CONSOLE_WRITE_SCOPE,),
        )
    )
    with pytest.raises(ProviderOperationError) as error:
        analytics_token_store.load()
    assert error.value.code is ProviderFailureCode.FORBIDDEN


def test_authorization_session_rejects_invalid_ports_scopes_and_callbacks() -> None:
    with pytest.raises(ValueError):
        GoogleOAuthAuthorizationSession.create(0, (_SCOPE,))
    with pytest.raises(ValueError):
        GoogleOAuthAuthorizationSession.create(8765, ())

    session = GoogleOAuthAuthorizationSession.create(8765, (_SCOPE,))
    assert session.redirect_uri == _CALLBACK_URI
    assert 43 <= len(session.code_verifier) <= 128
    for query in (
        {},
        {"state": (session.state, "duplicate"), "code": ("code",)},
        {"state": (session.state,), "code": ("code",), "error": ("access_denied",)},
        {"state": (session.state,), "code": ("",)},
    ):
        with pytest.raises(ProviderOperationError):
            session.validate_callback(query)


def test_oauth_token_record_rejects_an_empty_scope() -> None:
    with pytest.raises(ValueError, match="scopes are invalid"):
        oauth._GoogleOAuthTokenRecordResponse.model_validate(
            {
                "account_id": _ACCOUNT_ID,
                "client_id": _CLIENT_ID,
                "refresh_token": "refresh-token",
                "scopes": [""],
            }
        )


@pytest.mark.asyncio
async def test_loopback_receiver_accepts_google_success_callback_annotations() -> None:
    receiver = GoogleOAuthLoopbackReceiver((_SCOPE,))
    session = await receiver.start()
    callback = urlparse(session.redirect_uri)
    callback_url = f"http://{callback.netloc}{callback.path}"
    callback_params = {
        "state": session.state,
        "code": "authorization-code",
        "iss": oauth._GOOGLE_OAUTH_ISSUER,
        "scope": _SCOPE,
    }
    async with httpx.AsyncClient(trust_env=False) as client:
        first_response = await client.get(callback_url, params=callback_params)
        second_response = await client.get(callback_url, params=callback_params)

    assert first_response.status_code == 200
    assert second_response.status_code == 409
    assert await receiver.wait_for_code() == "authorization-code"


@pytest.mark.asyncio
async def test_loopback_receiver_rejects_wrong_path_and_times_out_safely() -> None:
    receiver = GoogleOAuthLoopbackReceiver((_SCOPE,))
    session = await receiver.start()
    callback = urlparse(session.redirect_uri)
    async with httpx.AsyncClient(trust_env=False) as client:
        response = await client.get(
            f"http://{callback.netloc}/wrong?state={session.state}&code=authorization-code"
        )
    assert response.status_code == 400
    with pytest.raises(ProviderOperationError) as error:
        await receiver.wait_for_code(0.001)
    assert error.value.code is ProviderFailureCode.AUTHENTICATION

    timeout_receiver = GoogleOAuthLoopbackReceiver((_SCOPE,))
    await timeout_receiver.start()
    with pytest.raises(ProviderOperationError) as timeout_error:
        await timeout_receiver.wait_for_code(0.001)
    assert timeout_error.value.code is ProviderFailureCode.AUTHENTICATION


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "extra_params",
    (
        {
            "authuser": "0",
            "hd": "example.com",
            "prompt": "consent",
            "scope": _SCOPE,
        },
        {"unexpected": "value"},
    ),
)
async def test_loopback_receiver_ignores_unrecognized_google_callback_parameters(
    extra_params: dict[str, str],
) -> None:
    receiver = GoogleOAuthLoopbackReceiver((_SCOPE,))
    session = await receiver.start()
    callback = urlparse(session.redirect_uri)
    async with httpx.AsyncClient(trust_env=False) as client:
        response = await client.get(
            f"http://{callback.netloc}{callback.path}",
            params={
                "state": session.state,
                "code": "authorization-code",
                **extra_params,
            },
        )
    assert response.status_code == 200
    assert await receiver.wait_for_code() == "authorization-code"


@pytest.mark.asyncio
async def test_loopback_receiver_rejects_a_forged_google_callback_issuer() -> None:
    receiver = GoogleOAuthLoopbackReceiver((_SCOPE,))
    session = await receiver.start()
    callback = urlparse(session.redirect_uri)
    async with httpx.AsyncClient(trust_env=False) as client:
        response = await client.get(
            f"http://{callback.netloc}{callback.path}",
            params={
                "state": session.state,
                "code": "authorization-code",
                "iss": "https://attacker.invalid",
            },
        )
    assert response.status_code == 400
    with pytest.raises(ProviderOperationError) as error:
        await receiver.wait_for_code(0.001)
    assert error.value.code is ProviderFailureCode.AUTHENTICATION


@pytest.mark.asyncio
async def test_rejected_callback_records_only_a_fixed_redacted_diagnostic_reason(
    tmp_path: Path,
) -> None:
    oauth_root = tmp_path / "oauth"
    oauth_root.mkdir(mode=0o700)
    os.chmod(oauth_root, 0o700)
    receiver = GoogleOAuthLoopbackReceiver((_SCOPE,))
    session = await receiver.start()
    callback = urlparse(session.redirect_uri)
    rejected_state = "wrong-state-not-for-log"
    rejected_code = "authorization-code-not-for-log"
    async with httpx.AsyncClient(trust_env=False) as client:
        response = await client.get(
            f"http://{callback.netloc}{callback.path}",
            params={"state": rejected_state, "code": rejected_code},
        )
    assert response.status_code == 400

    with pytest.raises(ProviderOperationError) as error:
        await receiver.wait_for_code(0.001)
    assert str(error.value) == "Google OAuth callback state was rejected"

    GoogleOAuthAuthorizationDiagnosticLog(oauth_root / "google-main.json").record_failure(
        oauth._OAUTH_AUTH_DIAGNOSTIC_STAGE_CALLBACK,
        error.value,
    )
    diagnostic_contents = (oauth_root / "google-auth.log").read_text(encoding="utf-8")
    assert rejected_state not in diagnostic_contents
    assert rejected_code not in diagnostic_contents
    diagnostic = json.loads(diagnostic_contents)
    assert isinstance(diagnostic.pop("occurred_at"), str)
    assert diagnostic == {
        "event": oauth._OAUTH_AUTH_DIAGNOSTIC_EVENT,
        "failure_code": ProviderFailureCode.AUTHENTICATION.value,
        "reason": "callback_state_rejected",
        "stage": oauth._OAUTH_AUTH_DIAGNOSTIC_STAGE_CALLBACK,
    }


@pytest.mark.asyncio
async def test_rejected_callback_does_not_consume_the_valid_callback() -> None:
    receiver = GoogleOAuthLoopbackReceiver((_SCOPE,))
    session = await receiver.start()
    callback = urlparse(session.redirect_uri)
    async with httpx.AsyncClient(trust_env=False) as client:
        rejected = await client.get(
            f"http://{callback.netloc}{callback.path}?state=incorrect&code=authorization-code"
        )
        accepted = await client.get(
            f"http://{callback.netloc}{callback.path}?state={session.state}&code=authorization-code"
        )
    assert rejected.status_code == 400
    assert accepted.status_code == 200
    assert await receiver.wait_for_code() == "authorization-code"


@pytest.mark.asyncio
async def test_container_callback_listener_keeps_the_redirect_uri_on_literal_loopback() -> None:
    receiver = GoogleOAuthLoopbackReceiver(
        (_SCOPE,),
        listener_host=OAUTH_CONTAINER_LISTENER_HOST,
    )
    session = await receiver.start()
    callback = urlparse(session.redirect_uri)
    assert callback.hostname == "127.0.0.1"
    assert callback.port is not None
    await receiver.aclose()


def test_client_configuration_is_bounded_and_installed_only(tmp_path: Path) -> None:
    client_file = tmp_path / "client.json"
    client_file.write_text(
        '{"installed":{"client_id":"client-id.example.apps.googleusercontent.com","client_secret":"client-secret"}}',
        encoding="utf-8",
    )
    configuration = load_google_oauth_client_configuration(client_file)
    assert configuration == GoogleOAuthClientConfiguration(_CLIENT_ID, "client-secret")

    client_file.write_text('{"web":{"client_id":"wrong"}}', encoding="utf-8")
    with pytest.raises(ProviderOperationError) as error:
        load_google_oauth_client_configuration(client_file)
    assert error.value.code is ProviderFailureCode.AUTHENTICATION


def test_token_store_persists_only_refresh_material_with_owner_only_permissions(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    record = _record()
    store.write(record)

    token_file = tmp_path / "oauth" / "google-main.json"
    contents = token_file.read_text(encoding="utf-8")
    assert "refresh-token" in contents
    assert "access_token" not in contents
    assert os.stat(token_file).st_mode & 0o777 == 0o600
    assert store.load() == record

    token_file.chmod(0o644)
    with pytest.raises(ProviderOperationError) as error:
        store.load()
    assert error.value.code is ProviderFailureCode.AUTHENTICATION


def test_token_store_rejects_cross_account_records_and_unsafe_symlinks(tmp_path: Path) -> None:
    store = _store(tmp_path)
    wrong_account = GoogleOAuthTokenRecord(
        account_id="other-account",
        client_id=_CLIENT_ID,
        refresh_token="refresh-token",
        scopes=(_SCOPE,),
    )
    with pytest.raises(ProviderOperationError) as error:
        store.write(wrong_account)
    assert error.value.code is ProviderFailureCode.AUTHENTICATION

    target = tmp_path / "target.json"
    target.write_text('{"refresh_token":"untrusted"}', encoding="utf-8")
    token_file = tmp_path / "oauth" / "google-main.json"
    token_file.symlink_to(target)
    with pytest.raises(ProviderOperationError) as error:
        store.load()
    assert error.value.code is ProviderFailureCode.AUTHENTICATION


@pytest.mark.asyncio
async def test_token_client_exchanges_refreshes_and_revokes_at_fixed_origins() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/revoke":
            return httpx.Response(200)
        if b"grant_type=authorization_code" in request.content:
            return httpx.Response(
                200,
                json={
                    "access_token": "access-token",
                    "expires_in": 3600,
                    "refresh_token": "new-refresh-token",
                    "refresh_token_expires_in": 3600,
                    "scope": _SCOPE,
                    "token_type": "Bearer",
                    "unrecognized_google_field": "ignored",
                },
            )
        return httpx.Response(
            200,
            json={
                "access_token": "refreshed-access-token",
                "expires_in": 3600,
                "scope": _SCOPE,
                "token_type": "Bearer",
            },
        )

    client = GoogleOAuthTokenClient(lambda: httpx.MockTransport(handler))
    configuration = GoogleOAuthClientConfiguration(_CLIENT_ID, "client-secret")
    session = GoogleOAuthAuthorizationSession(
        code_verifier="dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk",
        state="state",
        redirect_uri=_CALLBACK_URI,
        scopes=(_SCOPE,),
    )
    access_token, exchanged = await client.exchange(_ACCOUNT_ID, configuration, session, "code")
    assert access_token == "access-token"
    assert exchanged == GoogleOAuthTokenRecord(
        _ACCOUNT_ID,
        _CLIENT_ID,
        "new-refresh-token",
        (_SCOPE,),
    )

    refreshed_access_token, refreshed = await client.refresh(configuration, exchanged)
    assert refreshed_access_token == "refreshed-access-token"
    assert refreshed == exchanged
    await client.revoke(refreshed)

    assert [str(request.url) for request in requests] == [
        "https://oauth2.googleapis.com/token",
        "https://oauth2.googleapis.com/token",
        "https://oauth2.googleapis.com/revoke",
    ]
    assert b"code_verifier=" in requests[0].content
    assert b"client_secret=client-secret" in requests[0].content
    assert b"refresh_token=new-refresh-token" in requests[1].content
    assert b"token=new-refresh-token" in requests[2].content


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "payload", "expected_code"),
    (
        (400, {}, ProviderFailureCode.AUTHENTICATION),
        (403, {}, ProviderFailureCode.FORBIDDEN),
        (429, {}, ProviderFailureCode.RATE_LIMITED),
        (500, {}, ProviderFailureCode.UNAVAILABLE),
    ),
)
async def test_token_client_maps_failures_without_upstream_body_leakage(
    status_code: int,
    payload: object,
    expected_code: ProviderFailureCode,
) -> None:
    client = GoogleOAuthTokenClient(
        lambda: httpx.MockTransport(lambda _: httpx.Response(status_code, json=payload))
    )
    session = GoogleOAuthAuthorizationSession(
        code_verifier="dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk",
        state="state",
        redirect_uri=_CALLBACK_URI,
        scopes=(_SCOPE,),
    )
    with pytest.raises(ProviderOperationError) as error:
        await client.exchange(
            _ACCOUNT_ID,
            GoogleOAuthClientConfiguration(_CLIENT_ID, None),
            session,
            "code",
        )
    assert error.value.code is expected_code
    assert "body-must-not-leak" not in str(error.value)


@pytest.mark.asyncio
async def test_configured_token_provider_rejects_an_unmapped_credential_path(
    tmp_path: Path,
) -> None:
    secret_root = tmp_path / "secrets"
    secret_root.mkdir()
    oauth_root = tmp_path / "oauth"
    oauth_root.mkdir(mode=0o700)
    os.chmod(oauth_root, 0o700)
    oauth_client_file = secret_root / "oauth-client.json"
    oauth_client_file.write_text(
        '{"installed":{"client_id":"client-id.example.apps.googleusercontent.com"}}',
        encoding="utf-8",
    )
    unmapped_client_file = secret_root / "unmapped-client.json"
    policy = BoundaryPolicy(
        BoundaryDocument.model_validate(
            {
                "accounts": [
                    {
                        "id": _ACCOUNT_ID,
                        "provider": "google",
                        "credential": str(oauth_client_file),
                        "oauth_token_file": str(oauth_root / "google-main.json"),
                    },
                ]
            }
        )
    )
    GoogleOAuthTokenStore(
        oauth_root / "google-main.json",
        _ACCOUNT_ID,
        _CLIENT_ID,
        (_SCOPE,),
    ).write(_record())

    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.url == httpx.URL("https://oauth2.googleapis.com/token")
        return httpx.Response(
            200,
            json={
                "access_token": "oauth-access-token",
                "expires_in": 3600,
                "scope": _SCOPE,
                "token_type": "Bearer",
            },
        )

    provider = GoogleConfiguredTokenProvider(
        policy,
        (_SCOPE,),
        GoogleOAuthTokenClient(lambda: httpx.MockTransport(handler)),
    )
    assert await provider(oauth_client_file) == "oauth-access-token"
    with pytest.raises(ProviderOperationError) as error:
        await provider(unmapped_client_file)
    assert error.value.code is ProviderFailureCode.AUTHENTICATION
    assert "not configured" in str(error.value)
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_operator_authorizes_and_revokes_exact_configured_account(tmp_path: Path) -> None:
    secret_root = tmp_path / "secrets"
    secret_root.mkdir()
    oauth_root = tmp_path / "oauth"
    oauth_root.mkdir(mode=0o700)
    os.chmod(oauth_root, 0o700)
    oauth_client_file = secret_root / "oauth-client.json"
    oauth_client_file.write_text(
        '{"installed":{"client_id":"client-id.example.apps.googleusercontent.com"}}',
        encoding="utf-8",
    )
    account = BoundaryDocument.model_validate(
        {
            "accounts": [
                {
                    "id": _ACCOUNT_ID,
                    "provider": "google",
                    "credential": str(oauth_client_file),
                    "oauth_token_file": str(oauth_root / "google-main.json"),
                    "search_console_sites": ["https://example.com/"],
                    "ga4_properties": ["123"],
                }
            ]
        }
    ).accounts[0]
    assert required_google_oauth_scopes(account, enable_writes=False) == (
        _SCOPE,
        "https://www.googleapis.com/auth/analytics.readonly",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/revoke":
            return httpx.Response(200)
        return httpx.Response(
            200,
            json={
                "access_token": "access-token",
                "expires_in": 3600,
                "refresh_token": "refresh-token",
                "scope": " ".join(google_oauth_authorization_scopes()),
                "token_type": "Bearer",
            },
        )

    async def submit_callback(authorization_url: str) -> None:
        query = parse_qs(urlparse(authorization_url).query)
        callback = urlparse(query["redirect_uri"][0])
        async with httpx.AsyncClient(trust_env=False) as client:
            response = await client.get(
                f"http://{callback.netloc}{callback.path}?"
                f"state={query['state'][0]}&code=authorization-code"
            )
        assert response.status_code == 200

    def browser_opener(authorization_url: str) -> bool:
        asyncio.get_running_loop().create_task(submit_callback(authorization_url))
        return True

    authorization_urls: list[str] = []
    client = GoogleOAuthTokenClient(lambda: httpx.MockTransport(handler))
    await authorize_google_oauth_account(
        account,
        enable_writes=False,
        browser_opener=browser_opener,
        authorization_url_sink=authorization_urls.append,
        token_client=client,
    )
    assert len(authorization_urls) == 1
    assert (
        GoogleOAuthTokenStore(
            oauth_root / "google-main.json",
            _ACCOUNT_ID,
            _CLIENT_ID,
            google_oauth_authorization_scopes(),
        )
        .load()
        .refresh_token
        == "refresh-token"
    )

    await revoke_google_oauth_account(account, enable_writes=False, token_client=client)
    assert not (oauth_root / "google-main.json").exists()


@pytest.mark.asyncio
async def test_operator_authorization_failure_writes_only_redacted_owner_diagnostic(
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
                    "oauth_token_file": str(oauth_root / "google-main.json"),
                    "search_console_sites": ["https://example.com/"],
                }
            ]
        }
    ).accounts[0]
    secrets_in_response = ("access-token-not-for-logs", "refresh-token-not-for-logs")

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "access_token": secrets_in_response[0],
                "expires_in": "not-an-integer",
                "refresh_token": secrets_in_response[1],
                "token_type": "Bearer",
            },
        )

    async def submit_callback(authorization_url: str) -> None:
        query = parse_qs(urlparse(authorization_url).query)
        callback = urlparse(query["redirect_uri"][0])
        async with httpx.AsyncClient(trust_env=False) as client:
            response = await client.get(
                f"http://{callback.netloc}{callback.path}?"
                f"state={query['state'][0]}&code=authorization-code"
            )
        assert response.status_code == 200

    def browser_opener(authorization_url: str) -> bool:
        asyncio.get_running_loop().create_task(submit_callback(authorization_url))
        return True

    with pytest.raises(ProviderOperationError) as error:
        await authorize_google_oauth_account(
            account,
            enable_writes=False,
            browser_opener=browser_opener,
            token_client=GoogleOAuthTokenClient(lambda: httpx.MockTransport(handler)),
        )
    assert error.value.code is ProviderFailureCode.INVALID_RESPONSE

    diagnostic_file = oauth_root / "google-auth.log"
    diagnostic_contents = diagnostic_file.read_text(encoding="utf-8")
    assert all(secret not in diagnostic_contents for secret in secrets_in_response)
    diagnostic = json.loads(diagnostic_contents)
    assert isinstance(diagnostic.pop("occurred_at"), str)
    assert diagnostic == {
        "event": oauth._OAUTH_AUTH_DIAGNOSTIC_EVENT,
        "failure_code": ProviderFailureCode.INVALID_RESPONSE.value,
        "stage": oauth._OAUTH_AUTH_DIAGNOSTIC_STAGE_TOKEN_EXCHANGE,
    }
    assert diagnostic_file.stat().st_mode & 0o777 == 0o600
    assert diagnostic_file.stat().st_uid == os.geteuid()


def test_oauth_local_boundaries_fail_closed_before_any_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def short_token_urlsafe(_: int | None = None) -> str:
        return "too-short"

    monkeypatch.setattr(oauth.secrets, "token_urlsafe", short_token_urlsafe)
    with pytest.raises(RuntimeError, match="verifier length"):
        GoogleOAuthAuthorizationSession.create(8765, (_SCOPE,))

    session = GoogleOAuthAuthorizationSession(
        code_verifier="dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk",
        state="state",
        redirect_uri=_CALLBACK_URI,
        scopes=(_SCOPE,),
    )
    for client_id in ("", "x" * (oauth._OAUTH_TOKEN_TEXT_CHARS + 1)):
        with pytest.raises(ValueError, match="client ID"):
            session.authorization_url(client_id)

    with pytest.raises(ValueError, match="listener host"):
        GoogleOAuthLoopbackReceiver((_SCOPE,), listener_host="external.example")
    with pytest.raises(ValueError, match="redirect port"):
        GoogleOAuthLoopbackReceiver((_SCOPE,), redirect_port=65_536)

    receiver = GoogleOAuthLoopbackReceiver((_SCOPE,))
    with pytest.raises(ValueError, match="positive"):
        asyncio.run(receiver.wait_for_code(0))
    with pytest.raises(RuntimeError, match="has not started"):
        asyncio.run(receiver.wait_for_code(1))
    asyncio.run(receiver.aclose())


def test_oauth_callback_parser_and_peer_validation_reject_untrusted_input() -> None:
    receiver = GoogleOAuthLoopbackReceiver((_SCOPE,))
    for payload in (
        b"\xff",
        b"POST /oauth2/callback HTTP/1.1\r\n\r\n",
        b"GET https://external.example/oauth2/callback HTTP/1.1\r\n\r\n",
    ):
        with pytest.raises(ValueError):
            receiver._parse_callback(payload)
    with pytest.raises(RuntimeError, match="not initialized"):
        receiver._parse_callback(b"GET /oauth2/callback HTTP/1.1\r\n\r\n")

    class Writer:
        def __init__(self, peer: object) -> None:
            self._peer = peer

        def get_extra_info(self, _: str) -> object:
            return self._peer

    assert not receiver._is_callback_peer_allowed(Writer("not-a-peer"))  # type: ignore[arg-type]
    assert not receiver._is_callback_peer_allowed(Writer(("127.0.0.2", 1)))  # type: ignore[arg-type]
    assert receiver._is_callback_peer_allowed(Writer(("127.0.0.1", 1)))  # type: ignore[arg-type]
    container_receiver = GoogleOAuthLoopbackReceiver(
        (_SCOPE,),
        listener_host=OAUTH_CONTAINER_LISTENER_HOST,
    )
    assert container_receiver._is_callback_peer_allowed(Writer(None))  # type: ignore[arg-type]


def test_oauth_file_boundaries_reject_invalid_records_and_unsafe_parent(tmp_path: Path) -> None:
    store = _store(tmp_path)
    token_file = tmp_path / "oauth" / "google-main.json"
    token_file.write_text("not-json", encoding="utf-8")
    token_file.chmod(0o600)
    with pytest.raises(ProviderOperationError, match="token is invalid"):
        store.load()

    token_file.write_text(
        '{"account_id":"other","client_id":"client-id.example.apps.googleusercontent.com",'
        '"refresh_token":"refresh-token","scopes":["https://www.googleapis.com/auth/webmasters.readonly"]}',
        encoding="utf-8",
    )
    token_file.chmod(0o600)
    with pytest.raises(ProviderOperationError, match="does not match"):
        store.load()

    token_file.write_text(
        '{"account_id":"google-main","client_id":"client-id.example.apps.googleusercontent.com",'
        '"refresh_token":"refresh-token","scopes":["other-scope"]}',
        encoding="utf-8",
    )
    token_file.chmod(0o600)
    with pytest.raises(ProviderOperationError, match="lacks required") as error:
        store.load()
    assert error.value.code is ProviderFailureCode.FORBIDDEN

    unsafe_parent = tmp_path / "unsafe"
    unsafe_parent.mkdir(mode=0o755)
    unsafe_store = GoogleOAuthTokenStore(
        unsafe_parent / "token.json",
        _ACCOUNT_ID,
        _CLIENT_ID,
        (_SCOPE,),
    )
    with pytest.raises(ProviderOperationError, match="permissions are unsafe"):
        unsafe_store.write(_record())


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("operation", "exception", "expected_code"),
    (
        ("token", httpx.ReadTimeout("timeout"), ProviderFailureCode.TIMEOUT),
        ("token", httpx.ConnectError("offline"), ProviderFailureCode.UNAVAILABLE),
        ("revoke", httpx.ReadTimeout("timeout"), ProviderFailureCode.TIMEOUT),
        ("revoke", httpx.ConnectError("offline"), ProviderFailureCode.UNAVAILABLE),
    ),
)
async def test_oauth_http_failures_map_to_safe_typed_errors(
    operation: str,
    exception: httpx.HTTPError,
    expected_code: ProviderFailureCode,
) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        raise exception

    client = GoogleOAuthTokenClient(lambda: httpx.MockTransport(handler))
    configuration = GoogleOAuthClientConfiguration(_CLIENT_ID, None)
    session = GoogleOAuthAuthorizationSession(
        code_verifier="dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk",
        state="state",
        redirect_uri=_CALLBACK_URI,
        scopes=(_SCOPE,),
    )
    with pytest.raises(ProviderOperationError) as error:
        if operation == "token":
            await client.exchange(_ACCOUNT_ID, configuration, session, "code")
        else:
            await client.revoke(_record())
    assert error.value.code is expected_code


@pytest.mark.asyncio
async def test_oauth_token_responses_require_refresh_and_expected_scopes() -> None:
    session = GoogleOAuthAuthorizationSession(
        code_verifier="dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk",
        state="state",
        redirect_uri=_CALLBACK_URI,
        scopes=(_SCOPE,),
    )
    payloads = (
        {
            "access_token": "access-token",
            "expires_in": 3600,
            "scope": _SCOPE,
            "token_type": "Bearer",
        },
        {
            "access_token": "access-token",
            "expires_in": 3600,
            "refresh_token": "refresh-token",
            "scope": "different-scope",
            "token_type": "Bearer",
        },
        {
            "access_token": "access-token",
            "expires_in": 3600,
            "refresh_token": "refresh-token",
            "scope": _SCOPE,
            "token_type": "not-bearer",
        },
    )
    for payload in payloads:
        client = GoogleOAuthTokenClient(
            lambda payload=payload: httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
        )
        with pytest.raises(ProviderOperationError) as error:
            await client.exchange(
                _ACCOUNT_ID, GoogleOAuthClientConfiguration(_CLIENT_ID, None), session, "code"
            )
        assert error.value.code in {
            ProviderFailureCode.AUTHENTICATION,
            ProviderFailureCode.FORBIDDEN,
            ProviderFailureCode.INVALID_RESPONSE,
        }


@pytest.mark.asyncio
async def test_oauth_operator_rejects_missing_token_path_and_browser_open_failure(
    tmp_path: Path,
) -> None:
    client_path = tmp_path / "client.json"
    client_path.write_text(
        '{"installed":{"client_id":"client-id.example.apps.googleusercontent.com"}}'
    )
    account = BoundaryDocument.model_validate(
        {
            "accounts": [
                {
                    "id": _ACCOUNT_ID,
                    "provider": "google",
                    "credential": str(client_path),
                    "oauth_token_file": str(tmp_path / "oauth" / "token.json"),
                    "search_console_sites": ["https://example.com/"],
                }
            ]
        }
    ).accounts[0]
    missing_token_path = account.model_copy(update={"oauth_token_file": None})
    with pytest.raises(ProviderOperationError, match="missing a refresh token"):
        await authorize_google_oauth_account(missing_token_path, False, None)
    with pytest.raises(ProviderOperationError, match="browser could not be opened"):
        await authorize_google_oauth_account(account, False, lambda _: False)
    with pytest.raises(ProviderOperationError, match="missing a refresh token"):
        await revoke_google_oauth_account(missing_token_path, False)


def test_oauth_pure_scope_and_filesystem_guards_are_bounded(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    for scopes in ((), ("duplicate", "duplicate"), ("x" * (oauth._OAUTH_TOKEN_TEXT_CHARS + 1),)):
        with pytest.raises(ValueError):
            oauth._require_scopes(scopes)
    monkeypatch.delattr(oauth.os, "O_NOFOLLOW")
    with pytest.raises(ValueError, match="no-follow"):
        oauth._no_follow_flag()

    client_file = tmp_path / "client.json"
    client_file.write_bytes(b"x" * (oauth._OAUTH_CLIENT_CONFIG_BYTES + 1))
    with pytest.raises(ProviderOperationError, match="configuration is unavailable"):
        load_google_oauth_client_configuration(client_file)

    with pytest.raises(ValueError):
        oauth._GoogleOAuthTokenRecordResponse.model_validate(
            {
                "account_id": _ACCOUNT_ID,
                "client_id": _CLIENT_ID,
                "refresh_token": "refresh-token",
                "scopes": [_SCOPE, _SCOPE],
            }
        )

    non_google = BoundaryDocument.model_validate(
        {"accounts": [{"id": "bing-main", "provider": "bing", "credential": str(client_file)}]}
    ).accounts[0]
    with pytest.raises(ValueError, match="not a Google OAuth"):
        required_google_oauth_scopes(non_google, False)

    analytics_account = BoundaryDocument.model_validate(
        {
            "accounts": [
                {
                    "id": _ACCOUNT_ID,
                    "provider": "google",
                    "credential": str(client_file),
                    "oauth_token_file": str(tmp_path / "oauth" / "token.json"),
                    "ga4_properties": ["123"],
                }
            ]
        }
    ).accounts[0]
    assert required_google_oauth_scopes(analytics_account, True) == (
        oauth.GOOGLE_SEARCH_CONSOLE_READ_SCOPE,
        oauth.GOOGLE_ANALYTICS_READ_SCOPE,
        oauth.GOOGLE_INDEXING_SCOPE,
        oauth.GOOGLE_SEARCH_CONSOLE_WRITE_SCOPE,
        oauth.GOOGLE_SITE_VERIFICATION_SCOPE,
        oauth.GOOGLE_ANALYTICS_EDIT_SCOPE,
        oauth.GOOGLE_TAG_MANAGER_EDIT_SCOPE,
        oauth.GOOGLE_TAG_MANAGER_DELETE_SCOPE,
        oauth.GOOGLE_TAG_MANAGER_VERSION_EDIT_SCOPE,
        oauth.GOOGLE_TAG_MANAGER_PUBLISH_SCOPE,
    )


def test_oauth_token_store_rejects_bad_write_delete_and_file_descriptor_paths(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    with pytest.raises(ProviderOperationError, match="could not be deleted"):
        store.delete()
    with pytest.raises(ProviderOperationError, match="lacks required"):
        store.write(
            GoogleOAuthTokenRecord(
                _ACCOUNT_ID,
                _CLIENT_ID,
                "refresh-token",
                ("other-scope",),
            )
        )
    with pytest.raises(ProviderOperationError, match="too large"):
        store.write(
            GoogleOAuthTokenRecord(
                _ACCOUNT_ID,
                _CLIENT_ID,
                "x" * (oauth.MAX_OAUTH_TOKEN_FILE_BYTES + 1),
                (_SCOPE,),
            )
        )

    read_descriptor, write_descriptor = os.pipe()
    try:
        os.write(write_descriptor, b"oversized")
        with pytest.raises(ValueError, match="exceeds"):
            oauth._read_file_descriptor(read_descriptor, 1)
    finally:
        os.close(read_descriptor)
        os.close(write_descriptor)

    def write_returns_zero(_: int, __: bytes) -> int:
        return 0

    monkeypatch.setattr(oauth.os, "write", write_returns_zero)
    with pytest.raises(OSError, match="did not progress"):
        oauth._write_all(1, b"x")


@pytest.mark.asyncio
async def test_oauth_token_http_status_and_size_guards() -> None:
    session = GoogleOAuthAuthorizationSession(
        code_verifier="dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk",
        state="state",
        redirect_uri=_CALLBACK_URI,
        scopes=(_SCOPE,),
    )
    responses = (
        httpx.Response(418),
        httpx.Response(200, content=b"x" * (oauth._OAUTH_TOKEN_RESPONSE_BYTES + 1)),
    )
    for response in responses:
        client = GoogleOAuthTokenClient(
            lambda response=response: httpx.MockTransport(lambda _: response)
        )
        with pytest.raises(ProviderOperationError) as error:
            await client.exchange(
                _ACCOUNT_ID, GoogleOAuthClientConfiguration(_CLIENT_ID, None), session, "code"
            )
        assert error.value.code is ProviderFailureCode.INVALID_RESPONSE

    revoke_client = GoogleOAuthTokenClient(
        lambda: httpx.MockTransport(lambda _: httpx.Response(403))
    )
    with pytest.raises(ProviderOperationError) as error:
        await revoke_client.revoke(_record())
    assert error.value.code is ProviderFailureCode.AUTHENTICATION


@pytest.mark.asyncio
async def test_oauth_loopback_receiver_handles_owned_listener_edge_states(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receiver = GoogleOAuthLoopbackReceiver((_SCOPE,))
    await receiver.start()
    with pytest.raises(RuntimeError, match="already running"):
        await receiver.start()
    await receiver.aclose()

    class Server:
        def __init__(self, sockets: list[object]) -> None:
            self.sockets = sockets

        def close(self) -> None:
            return None

        async def wait_closed(self) -> None:
            return None

    async def no_socket_server(*_: object, **__: object) -> Server:
        return Server([])

    monkeypatch.setattr(oauth.asyncio, "start_server", no_socket_server)
    with pytest.raises(RuntimeError, match="did not expose"):
        await GoogleOAuthLoopbackReceiver((_SCOPE,)).start()

    class InvalidSocket:
        def getsockname(self) -> object:
            return "invalid"

    async def invalid_socket_server(*_: object, **__: object) -> Server:
        return Server([InvalidSocket()])

    monkeypatch.setattr(oauth.asyncio, "start_server", invalid_socket_server)
    with pytest.raises(RuntimeError, match="invalid socket"):
        await GoogleOAuthLoopbackReceiver((_SCOPE,)).start()


@pytest.mark.asyncio
async def test_oauth_loopback_handler_rejects_untrusted_peers_and_disconnects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Reader:
        async def readuntil(self, _: bytes) -> bytes:
            return b"GET /oauth2/callback HTTP/1.1\r\n\r\n"

    class Writer:
        def __init__(self, peer: object, interrupted: bool = False) -> None:
            self.peer = peer
            self.interrupted = interrupted
            self.closed = False

        def get_extra_info(self, _: str) -> object:
            return self.peer

        def write(self, _: bytes) -> None:
            return None

        async def drain(self) -> None:
            if self.interrupted:
                raise ConnectionError

        def close(self) -> None:
            self.closed = True

    receiver = GoogleOAuthLoopbackReceiver((_SCOPE,))
    rejected_writer = Writer(("127.0.0.2", 1))
    await receiver._handle_connection(Reader(), rejected_writer)  # type: ignore[arg-type]
    assert rejected_writer.closed is True

    uninitialized_writer = Writer(("127.0.0.1", 1), interrupted=True)
    with pytest.raises(RuntimeError, match="not initialized"):
        await receiver._handle_connection(Reader(), uninitialized_writer)  # type: ignore[arg-type]
    assert uninitialized_writer.closed is True


def test_oauth_owner_and_write_failure_guards(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path)
    with pytest.raises(ValueError, match="not a regular"):
        oauth._require_owner_only_regular_file(os.stat(tmp_path))

    missing_parent_store = GoogleOAuthTokenStore(
        tmp_path / "missing" / "token.json",
        _ACCOUNT_ID,
        _CLIENT_ID,
        (_SCOPE,),
    )
    with pytest.raises(ProviderOperationError, match="directory is unavailable"):
        missing_parent_store.write(_record())

    parent_file = tmp_path / "parent-file"
    parent_file.write_text("not-a-directory", encoding="utf-8")
    file_parent_store = GoogleOAuthTokenStore(
        parent_file / "token.json",
        _ACCOUNT_ID,
        _CLIENT_ID,
        (_SCOPE,),
    )
    with pytest.raises(ProviderOperationError, match="directory is invalid"):
        file_parent_store.write(_record())

    def replace_failure(_: str, __: Path) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr(oauth.os, "replace", replace_failure)
    with pytest.raises(ProviderOperationError, match="could not be persisted"):
        store.write(_record())


def test_oauth_diagnostic_log_refuses_to_follow_an_existing_symlink(tmp_path: Path) -> None:
    oauth_root = tmp_path / "oauth"
    oauth_root.mkdir(mode=0o700)
    os.chmod(oauth_root, 0o700)
    diagnostic_target = tmp_path / "must-not-change"
    diagnostic_target.write_text("unchanged", encoding="utf-8")
    diagnostic_file = oauth_root / "google-auth.log"
    diagnostic_file.symlink_to(diagnostic_target)

    GoogleOAuthAuthorizationDiagnosticLog(oauth_root / "google-main.json").record_failure(
        oauth._OAUTH_AUTH_DIAGNOSTIC_STAGE_TOKEN_EXCHANGE,
        ProviderOperationError(ProviderFailureCode.INVALID_RESPONSE, "safe test failure"),
    )

    assert diagnostic_file.is_symlink()
    assert diagnostic_target.read_text(encoding="utf-8") == "unchanged"


def test_oauth_diagnostic_log_skips_append_when_its_size_limit_is_reached(tmp_path: Path) -> None:
    oauth_root = tmp_path / "oauth"
    oauth_root.mkdir(mode=0o700)
    os.chmod(oauth_root, 0o700)
    diagnostic_file = oauth_root / "google-auth.log"
    original = b"x" * oauth._OAUTH_AUTH_DIAGNOSTIC_MAX_BYTES
    diagnostic_file.write_bytes(original)
    os.chmod(diagnostic_file, 0o600)

    GoogleOAuthAuthorizationDiagnosticLog(oauth_root / "google-main.json").record_failure(
        oauth._OAUTH_AUTH_DIAGNOSTIC_STAGE_TOKEN_EXCHANGE,
        ProviderOperationError(ProviderFailureCode.INVALID_RESPONSE, "safe test failure"),
    )

    assert diagnostic_file.read_bytes() == original


def test_oauth_write_cleanup_failure_and_remaining_scope_guard(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path)

    def replace_failure(_: object, __: object) -> None:
        raise OSError("replace")

    def unlink_failure(_: object) -> None:
        raise OSError("unlink")

    monkeypatch.setattr(oauth.os, "replace", replace_failure)
    monkeypatch.setattr(oauth.os, "unlink", unlink_failure)
    with pytest.raises(ProviderOperationError, match="temporary token file"):
        store.write(_record())

    account = BoundaryDocument.model_validate(
        {
            "accounts": [
                {
                    "id": _ACCOUNT_ID,
                    "provider": "google",
                    "credential": str(tmp_path / "client.json"),
                    "oauth_token_file": str(tmp_path / "oauth" / "token.json"),
                    "search_console_sites": ["https://example.com/"],
                }
            ]
        }
    ).accounts[0]
    assert oauth.GOOGLE_SEARCH_CONSOLE_WRITE_SCOPE in required_google_oauth_scopes(account, True)


def test_oauth_delete_and_replace_failure_cover_both_cleanup_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path)
    store.write(_record())

    def path_exists(_: Path) -> bool:
        return True

    monkeypatch.setattr(Path, "exists", path_exists)
    with pytest.raises(ProviderOperationError, match="could not be deleted"):
        store.delete()

    second_directory = tmp_path / "second"
    second_directory.mkdir()
    second_store = _store(second_directory)

    def chmod_failure(_: object, __: object) -> None:
        raise OSError("chmod")

    monkeypatch.setattr(oauth.os, "chmod", chmod_failure)
    with pytest.raises(ProviderOperationError, match="could not be persisted"):
        second_store.write(_record())
