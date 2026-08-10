"""Interactive, owner-local provider credential setup."""

from __future__ import annotations

import getpass
import json
import os
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Final, cast

from pydantic import ValidationError

from rankrat.errors import ConfigurationError
from rankrat.models.boundaries import BoundaryDocument, ConfiguredAccount, Provider

Prompt = Callable[[str], str]
SecretPrompt = Callable[[str], str]
Output = Callable[[str], object]

_PROVIDER_ORDER: Final = (
    Provider.GOOGLE,
    Provider.BING,
    Provider.CLOUDFLARE,
    Provider.AHREFS,
    Provider.MAJESTIC,
    Provider.MOZ,
    Provider.SEMRUSH,
    Provider.DATAFORSEO,
)
_PROVIDER_HELP: Final = {
    Provider.GOOGLE: (
        "Google Cloud OAuth desktop client JSON; enable Search Console, Analytics Data/Admin, "
        "Site Verification, Indexing, and PageSpeed Insights APIs. "
        "https://console.cloud.google.com/apis/credentials"
    ),
    Provider.BING: (
        "Bing Webmaster API key with access to the whole signed-in Webmaster account. "
        "https://www.bing.com/webmasters/home"
    ),
    Provider.CLOUDFLARE: (
        "Account token covering all zones with Zone Read, DNS Edit, Analytics Read, Cache Purge, "
        "and Zone Settings/Rules Edit. https://dash.cloudflare.com/profile/api-tokens"
    ),
    Provider.AHREFS: "Ahrefs API v3 token. https://app.ahrefs.com/api",
    Provider.MAJESTIC: "Majestic OpenApps API key. https://developer-support.majestic.com/",
    Provider.MOZ: "Moz access ID and secret. https://moz.com/products/api/keys",
    Provider.SEMRUSH: "Semrush API key. https://www.semrush.com/api-documentation/",
    Provider.DATAFORSEO: (
        "DataForSEO API login and password. https://app.dataforseo.com/api-access"
    ),
}
_SECRET_RELATIVE_PATHS: Final = {
    Provider.GOOGLE: Path("google/oauth-client.json"),
    Provider.BING: Path("bing/api-key"),
    Provider.CLOUDFLARE: Path("cloudflare/api-token"),
    Provider.AHREFS: Path("ahrefs/api-token"),
    Provider.MAJESTIC: Path("majestic/api-key"),
    Provider.MOZ: Path("moz/credentials"),
    Provider.SEMRUSH: Path("semrush/api-key"),
    Provider.DATAFORSEO: Path("dataforseo/credentials"),
}


def configure_interactively(
    boundary_file: Path,
    secret_root: Path,
    oauth_root: Path,
    prompt: Prompt = input,
    secret_prompt: SecretPrompt = getpass.getpass,
    output: Output = print,
) -> BoundaryDocument:
    """Select provider accounts and store their credentials without echoing values."""

    current = _read_document(boundary_file)
    output("Rankrat setup: credentials grant every supported operation their account can perform.")
    output("Set RANKRAT_READ_ONLY=true later if a deployment must expose reads only.\n")
    for provider in _PROVIDER_ORDER:
        output(f"  {provider.value}: {_PROVIDER_HELP[provider]}")
    selected = _select_providers(prompt)
    current_accounts = {
        provider: tuple(account for account in current.accounts if account.provider == provider)
        for provider in selected
    }
    for provider, accounts in current_accounts.items():
        if len(accounts) > 1:
            raise ConfigurationError(
                f"multiple {provider.value} accounts are configured; edit the account registry"
            )
    configured_accounts = {
        provider: _configure_account(
            provider,
            current_accounts[provider][0] if current_accounts[provider] else None,
            secret_root,
            oauth_root,
            secret_prompt,
            output,
        )
        for provider in selected
    }
    accounts = _merge_accounts(current.accounts, configured_accounts)
    try:
        document = BoundaryDocument(accounts=accounts, indexnow_targets=current.indexnow_targets)
    except ValidationError as error:
        raise ConfigurationError("guided setup produced invalid account configuration") from error
    _write_document(boundary_file, document)
    output("Provider configuration saved with owner-only permissions.")
    return document


def _merge_accounts(
    current: tuple[ConfiguredAccount, ...],
    configured: dict[Provider, ConfiguredAccount],
) -> tuple[ConfiguredAccount, ...]:
    remaining = dict(configured)
    merged: list[ConfiguredAccount] = []
    for account in current:
        merged.append(remaining.pop(account.provider, account))
    for provider in _PROVIDER_ORDER:
        new_account = remaining.get(provider)
        if new_account is not None:
            merged.append(new_account)
    return tuple(merged)


def _select_providers(prompt: Prompt) -> tuple[Provider, ...]:
    rendered = ",".join(provider.value for provider in _PROVIDER_ORDER)
    raw = prompt(f"Providers to configure (comma-separated: {rendered}): ").strip().lower()
    if not raw:
        raise ConfigurationError("setup requires at least one provider")
    names = tuple(dict.fromkeys(part.strip() for part in raw.split(",") if part.strip()))
    try:
        selected = tuple(Provider(name) for name in names)
    except ValueError as error:
        raise ConfigurationError("setup received an unsupported provider") from error
    return tuple(provider for provider in _PROVIDER_ORDER if provider in selected)


def _configure_account(
    provider: Provider,
    current: ConfiguredAccount | None,
    secret_root: Path,
    oauth_root: Path,
    secret_prompt: SecretPrompt,
    output: Output,
) -> ConfiguredAccount:
    relative_path = _SECRET_RELATIVE_PATHS[provider]
    credential = secret_root / relative_path
    prompt_label = (
        "Paste OAuth desktop client JSON"
        if provider is Provider.GOOGLE
        else _credential_prompt_label(provider)
    )
    value = secret_prompt(f"{provider.value}: {prompt_label} (blank keeps existing file): ")
    if value:
        if provider is Provider.GOOGLE:
            _validate_google_oauth_json(value)
        _write_secret(secret_root, credential, value)
        output(f"Stored {provider.value} credential at {credential}.")
    else:
        _require_existing_secret(secret_root, credential, provider)

    account_id = current.id if current is not None else provider.value
    account_data: dict[str, object] = (
        current.model_dump(mode="python", by_alias=True) if current is not None else {}
    )
    account_data.update(
        {
            "id": account_id,
            "provider": provider,
            "credential": credential,
        }
    )
    if provider is Provider.GOOGLE:
        account_data["oauth_token_file"] = oauth_root / f"{account_id}.json"
        pagespeed_key = secret_root / "google/pagespeed-api-key"
        pagespeed_value = secret_prompt(
            "google: paste PageSpeed Insights API key (blank keeps/skips it): "
        )
        if pagespeed_value:
            _write_secret(secret_root, pagespeed_key, pagespeed_value)
            output(f"Stored PageSpeed API key at {pagespeed_key}.")
        if pagespeed_key.is_file():
            account_data["pagespeed_api_key_file"] = pagespeed_key
    return ConfiguredAccount.model_validate(account_data)


def _credential_prompt_label(provider: Provider) -> str:
    if provider is Provider.MOZ:
        return "paste access-id:secret"
    if provider is Provider.DATAFORSEO:
        return "paste login:password"
    return "paste account-wide API token/key"


def _validate_google_oauth_json(value: str) -> None:
    try:
        document = json.loads(value)
    except json.JSONDecodeError as error:
        raise ConfigurationError("Google OAuth client value is not valid JSON") from error
    if not isinstance(document, dict):
        raise ConfigurationError("Google OAuth client JSON must be an object")
    typed_document = cast(dict[str, object], document)
    client = typed_document.get("installed")
    if not isinstance(client, dict):
        raise ConfigurationError("Google OAuth client must be an installed/desktop application")
    typed_client = cast(dict[str, object], client)
    required = ("client_id", "client_secret", "auth_uri", "token_uri", "redirect_uris")
    if any(not typed_client.get(field) for field in required):
        raise ConfigurationError("Google OAuth desktop client JSON is incomplete")


def _read_document(path: Path) -> BoundaryDocument:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return BoundaryDocument.model_validate(raw)
    except (OSError, json.JSONDecodeError, ValidationError) as error:
        raise ConfigurationError("boundary file is unavailable or invalid") from error


def _write_secret(root: Path, path: Path, value: str) -> None:
    resolved_root = _resolved_secret_root(root)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    _reject_secret_path_symlinks(root, path)
    resolved_parent = path.parent.resolve(strict=True)
    if not resolved_parent.is_relative_to(resolved_root):
        raise ConfigurationError("credential path escapes the configured secret root")
    if path.is_symlink():
        raise ConfigurationError("credential file must not be a symlink")
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(value.strip() + "\n")
        path.chmod(0o600)
    except OSError as error:
        raise ConfigurationError("credential file could not be stored") from error


def _require_existing_secret(root: Path, path: Path, provider: Provider) -> None:
    resolved_root = _resolved_secret_root(root)
    _reject_secret_path_symlinks(root, path)
    try:
        resolved_path = path.resolve(strict=True)
    except OSError as error:
        raise ConfigurationError(f"{provider.value} credential was not supplied") from error
    if not resolved_path.is_relative_to(resolved_root) or not resolved_path.is_file():
        raise ConfigurationError(f"{provider.value} credential was not supplied")


def _resolved_secret_root(root: Path) -> Path:
    if root.is_symlink():
        raise ConfigurationError("configured secret root must not be a symlink")
    try:
        resolved_root = root.resolve(strict=True)
    except OSError as error:
        raise ConfigurationError("configured secret root is unavailable") from error
    if not resolved_root.is_dir():
        raise ConfigurationError("configured secret root must be a directory")
    return resolved_root


def _reject_secret_path_symlinks(root: Path, path: Path) -> None:
    try:
        relative_path = path.relative_to(root)
    except ValueError as error:
        raise ConfigurationError("credential path escapes the configured secret root") from error
    candidate = root
    for part in relative_path.parts:
        candidate /= part
        if candidate.is_symlink():
            raise ConfigurationError("credential path must not contain symbolic links")


def _write_document(path: Path, document: BoundaryDocument) -> None:
    if path.is_symlink():
        raise ConfigurationError("boundary file must not be a symlink")
    parent = path.parent.resolve(strict=True)
    rendered = json.dumps(document.model_dump(mode="json", by_alias=True), indent=2) + "\n"
    temporary: Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(prefix=".rankrat-setup-", dir=parent)
        temporary = Path(temporary_name)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(rendered)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.chmod(0o600)
        os.replace(temporary, path)
    except OSError as error:
        raise ConfigurationError("boundary file could not be updated") from error
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
