from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from rankrat.errors import ConfigurationError
from rankrat.operator.guided_setup import configure_interactively

_OAUTH_CLIENT = json.dumps(
    {
        "installed": {
            "client_id": "client.example.apps.googleusercontent.com",
            "client_secret": "not-a-real-secret",
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }
)


def _paths(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    config = tmp_path / "config"
    secrets = tmp_path / "secrets"
    oauth = tmp_path / "oauth"
    for directory in (config, secrets, oauth):
        directory.mkdir(mode=0o700)
    boundary = config / "boundaries.json"
    boundary.write_text(
        json.dumps(
            {
                "accounts": [
                    {
                        "id": "google",
                        "provider": "google",
                        "credential": str(secrets / "google/oauth-client.json"),
                        "oauth_token_file": str(oauth / "google.json"),
                    },
                    {
                        "id": "bing",
                        "provider": "bing",
                        "credential": str(secrets / "bing/api-key"),
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    boundary.chmod(0o600)
    return boundary, config, secrets, oauth


def test_guided_setup_stores_selected_credentials_without_echoing_values(
    tmp_path: Path,
) -> None:
    boundary, _, secrets, oauth = _paths(tmp_path)
    secret_values = iter((_OAUTH_CLIENT, "", "bing-key-value"))
    output: list[str] = []

    document = configure_interactively(
        boundary,
        secrets,
        oauth,
        prompt=lambda _: "google,bing",
        secret_prompt=lambda _: next(secret_values),
        output=output.append,
    )

    assert [account.id for account in document.accounts] == ["google", "bing"]
    google_secret = secrets / "google/oauth-client.json"
    bing_secret = secrets / "bing/api-key"
    assert google_secret.read_text(encoding="utf-8").strip() == _OAUTH_CLIENT
    assert bing_secret.read_text(encoding="utf-8").strip() == "bing-key-value"
    assert os.stat(google_secret).st_mode & 0o777 == 0o600
    assert os.stat(bing_secret).st_mode & 0o777 == 0o600
    assert os.stat(boundary).st_mode & 0o777 == 0o600
    rendered_output = "\n".join(output)
    assert "bing-key-value" not in rendered_output
    assert "not-a-real-secret" not in rendered_output


def test_guided_setup_rejects_unknown_provider_before_secret_prompt(tmp_path: Path) -> None:
    boundary, _, secrets, oauth = _paths(tmp_path)
    with pytest.raises(ConfigurationError, match="unsupported provider"):
        configure_interactively(
            boundary,
            secrets,
            oauth,
            prompt=lambda _: "unknown",
            secret_prompt=lambda _: pytest.fail("secret prompt must not run"),
            output=lambda _: None,
        )


def test_guided_setup_rejects_symlinked_credential_target(tmp_path: Path) -> None:
    boundary, _, secrets, oauth = _paths(tmp_path)
    target = secrets / "bing-target"
    target.write_text("existing", encoding="utf-8")
    (secrets / "bing").mkdir(mode=0o700)
    (secrets / "bing/api-key").symlink_to(target)

    with pytest.raises(ConfigurationError, match="must not contain symbolic links"):
        configure_interactively(
            boundary,
            secrets,
            oauth,
            prompt=lambda _: "bing",
            secret_prompt=lambda _: "replacement",
            output=lambda _: None,
        )


def test_guided_setup_rejects_existing_symlinked_credential(tmp_path: Path) -> None:
    boundary, _, secrets, oauth = _paths(tmp_path)
    target = secrets / "bing-target"
    target.write_text("existing", encoding="utf-8")
    (secrets / "bing").mkdir(mode=0o700)
    (secrets / "bing/api-key").symlink_to(target)

    with pytest.raises(ConfigurationError, match="must not contain symbolic links"):
        configure_interactively(
            boundary,
            secrets,
            oauth,
            prompt=lambda _: "bing",
            secret_prompt=lambda _: "",
            output=lambda _: None,
        )


def test_guided_setup_preserves_discovered_inventory_for_existing_account(
    tmp_path: Path,
) -> None:
    boundary, _, secrets, oauth = _paths(tmp_path)
    boundary.write_text(
        json.dumps(
            {
                "accounts": [
                    {
                        "id": "google",
                        "provider": "google",
                        "credential": str(secrets / "google/oauth-client.json"),
                        "oauth_token_file": str(oauth / "google.json"),
                        "search_console_sites": ["sc-domain:example.com"],
                        "ga4_properties": ["123456789"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    google_secret = secrets / "google/oauth-client.json"
    google_secret.parent.mkdir(mode=0o700)
    google_secret.write_text(_OAUTH_CLIENT, encoding="utf-8")

    document = configure_interactively(
        boundary,
        secrets,
        oauth,
        prompt=lambda _: "google",
        secret_prompt=lambda _: "",
        output=lambda _: None,
    )

    account = document.accounts[0]
    assert account.search_console_sites == ("sc-domain:example.com",)
    assert account.ga4_properties == ("123456789",)


def test_guided_setup_preserves_accounts_for_unselected_providers(tmp_path: Path) -> None:
    boundary, _, secrets, oauth = _paths(tmp_path)
    secret_values = iter((_OAUTH_CLIENT, ""))

    document = configure_interactively(
        boundary,
        secrets,
        oauth,
        prompt=lambda _: "google",
        secret_prompt=lambda _: next(secret_values),
        output=lambda _: None,
    )

    assert [(account.id, account.provider.value) for account in document.accounts] == [
        ("google", "google"),
        ("bing", "bing"),
    ]


def test_guided_setup_rejects_ambiguous_existing_provider_before_secret_prompt(
    tmp_path: Path,
) -> None:
    boundary, _, secrets, oauth = _paths(tmp_path)
    boundary.write_text(
        json.dumps(
            {
                "accounts": [
                    {
                        "id": "google-one",
                        "provider": "google",
                        "credential": str(secrets / "google/one.json"),
                        "oauth_token_file": str(oauth / "google-one.json"),
                    },
                    {
                        "id": "google-two",
                        "provider": "google",
                        "credential": str(secrets / "google/two.json"),
                        "oauth_token_file": str(oauth / "google-two.json"),
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError, match="multiple google accounts"):
        configure_interactively(
            boundary,
            secrets,
            oauth,
            prompt=lambda _: "google",
            secret_prompt=lambda _: pytest.fail("secret prompt must not run"),
            output=lambda _: None,
        )


def test_guided_setup_rejects_incomplete_google_oauth_client(tmp_path: Path) -> None:
    boundary, _, secrets, oauth = _paths(tmp_path)

    with pytest.raises(ConfigurationError, match="incomplete"):
        configure_interactively(
            boundary,
            secrets,
            oauth,
            prompt=lambda _: "google",
            secret_prompt=lambda _: '{"installed":{"client_id":"only-one-field"}}',
            output=lambda _: None,
        )
