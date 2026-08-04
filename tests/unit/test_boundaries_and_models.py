from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import cast

import pytest
from pydantic import ValidationError

from rankrat.errors import BoundaryDeniedError, ConfigurationError, InputLimitError
from rankrat.models.boundaries import (
    BoundaryDocument,
    Provider,
    ResourceKind,
    _normalize_https_url,
    configured_site_contains_url,
    normalize_indexnow_host,
    search_console_property_contains_url,
)
from rankrat.models.common import to_json_value
from rankrat.policy.boundaries import BoundaryPolicy
from rankrat.policy.limits import require_boundary_file_size, require_http_body_size
from rankrat.providers.google_oauth import required_google_oauth_scopes


def _document(account: Mapping[str, object]) -> BoundaryDocument:
    return BoundaryDocument.model_validate({"accounts": [dict(account)]})


def test_shipped_boundary_example_configures_google_oauth() -> None:
    example_path = Path(__file__).parents[2] / "config" / "boundaries.json.example"
    document = BoundaryDocument.model_validate(json.loads(example_path.read_text(encoding="utf-8")))
    google_account = next(account for account in document.accounts if account.id == "google")
    bing_account = next(account for account in document.accounts if account.id == "bing")

    assert google_account.credential == Path("/run/secrets/google/oauth-client.json")
    assert google_account.oauth_token_file == Path("/run/oauth/google.json")
    assert google_account.pagespeed_api_key_file == Path("/run/secrets/google/pagespeed-api-key")
    assert google_account.search_console_sites == ("sc-domain:example.com",)
    assert google_account.pagespeed_sites == ("https://example.com/",)
    assert bing_account.credential == Path("/run/secrets/bing/api-key")


def test_boundary_models_normalize_sites_and_reject_invalid_shapes(tmp_path: Path) -> None:
    credential = tmp_path / "credential"
    document = _document(
        {
            "id": "google-main",
            "provider": "google",
            "credential": str(credential),
            "search_console_sites": [
                "sc-domain:Example.COM",
                "https://Example.COM:443/path",
            ],
            "ga4_properties": ["123"],
        }
    )
    assert document.accounts[0].search_console_sites == (
        "sc-domain:example.com",
        "https://example.com/path",
    )

    invalid_accounts = [
        {"id": "BAD", "provider": "google", "credential": str(credential)},
        {"id": "ok", "provider": "google", "credential": "relative"},
        {
            "id": "ok",
            "provider": "google",
            "credential": str(credential),
            "search_console_sites": ["sc-domain:not_domain"],
        },
        {
            "id": "ok",
            "provider": "google",
            "credential": str(credential),
            "pagespeed_sites": ["sc-domain:example.com"],
        },
        {
            "id": "ok",
            "provider": "google",
            "credential": str(credential),
            "search_console_sites": ["http://example.com"],
        },
        {
            "id": "ok",
            "provider": "google",
            "credential": str(credential),
            "search_console_sites": ["https://user@example.com"],
        },
        {
            "id": "ok",
            "provider": "google",
            "credential": str(credential),
            "ga4_properties": ["not-numeric"],
        },
        {
            "id": "ok",
            "provider": "bing",
            "credential": str(credential),
            "sites": ["https://example.com:444/"],
        },
        {
            "id": "ok",
            "provider": "bing",
            "credential": str(credential),
            "search_console_sites": ["sc-domain:example.com"],
        },
        {
            "id": "ok",
            "provider": "bing",
            "credential": str(credential),
            "pagespeed_sites": ["https://example.com/"],
        },
        {
            "id": "ok",
            "provider": "google",
            "credential": str(credential),
            "search_console_sites": "not-a-list",
        },
        {
            "id": "ok",
            "provider": "google",
            "credential": str(credential),
            "search_console_sites": [1],
        },
        {
            "id": "ok",
            "provider": "google",
            "credential": str(credential),
            "ga4_properties": ["123", "123"],
        },
        {
            "id": "ok",
            "provider": "bing",
            "credential": str(credential),
            "sites": "not-a-list",
        },
        {
            "id": "ok",
            "provider": "bing",
            "credential": str(credential),
            "sites": [1],
        },
        {
            "id": "ok",
            "provider": "bing",
            "credential": str(credential),
            "sites": ["https://example.com", "https://EXAMPLE.com:443/"],
        },
        {
            "id": "ok",
            "provider": "google",
            "credential": str(credential),
            "sites": ["https://example.com/"],
        },
        {
            "id": "ok",
            "provider": "google",
            "credential": str(credential),
            "auth_mode": "oauth",
        },
        {
            "id": "ok",
            "provider": "google",
            "credential": str(credential),
            "service_account": str(credential),
        },
        {
            "id": "ok",
            "provider": "bing",
            "credential": str(credential),
            "oauth_token_file": str(tmp_path / "oauth" / "token.json"),
        },
        {
            "id": "ok",
            "provider": "bing",
            "credential": str(credential),
            "pagespeed_api_key_file": str(tmp_path / "pagespeed-api-key"),
        },
    ]
    for invalid in invalid_accounts:
        with pytest.raises(ValidationError):
            _document(invalid)


def test_google_account_discovery_allows_only_google_read_resources(tmp_path: Path) -> None:
    credential = tmp_path / "credential"
    document = _document(
        {
            "id": "google-main",
            "provider": "google",
            "credential": str(credential),
            "oauth_token_file": str(tmp_path / "oauth" / "google-main.json"),
            "google_account_discovery": True,
        }
    )
    policy = BoundaryPolicy(document)

    assert document.accounts[0].google_account_discovery is True
    assert policy.require_google_account_discovery("google-main") == document.accounts[0]
    assert (
        policy.require_google_read_resource(
            "google-main",
            ResourceKind.SEARCH_CONSOLE_SITE,
            "sc-domain:example.com",
        )
        == document.accounts[0]
    )
    assert (
        policy.require_google_read_resource(
            "google-main",
            ResourceKind.GA4_PROPERTY,
            "123456789",
        )
        == document.accounts[0]
    )
    assert (
        policy.require_google_search_console_read_url(
            "google-main",
            "sc-domain:example.com",
            "https://www.example.com/article",
        )
        == "https://www.example.com/article"
    )
    with pytest.raises(BoundaryDeniedError):
        policy.require_resource(
            "google-main",
            Provider.GOOGLE,
            ResourceKind.SEARCH_CONSOLE_SITE,
            "sc-domain:example.com",
        )

    with pytest.raises(ValidationError):
        _document(
            {
                "id": "bing-main",
                "provider": "bing",
                "credential": str(credential),
                "google_account_discovery": True,
            }
        )
    with pytest.raises(ValidationError):
        _document(
            {
                "id": "google-string",
                "provider": "google",
                "credential": str(credential),
                "google_account_discovery": "true",
            }
        )
    with pytest.raises(ValidationError, match="requires oauth_token_file"):
        _document(
            {
                "id": "google-no-oauth",
                "provider": "google",
                "credential": str(credential),
                "google_account_discovery": True,
            }
        )


def test_unbounded_policy_preserves_accounts_but_bypasses_resource_allow_lists(
    tmp_path: Path,
) -> None:
    credential = tmp_path / "credential"
    document = BoundaryDocument.model_validate(
        {
            "accounts": [
                {
                    "id": "google-main",
                    "provider": "google",
                    "credential": str(credential),
                },
                {
                    "id": "bing-main",
                    "provider": "bing",
                    "credential": str(credential),
                    "sites": [],
                },
            ]
        }
    )
    bounded_policy = BoundaryPolicy(document)
    with pytest.raises(BoundaryDeniedError):
        bounded_policy.require_resource(
            "google-main",
            Provider.GOOGLE,
            ResourceKind.GA4_PROPERTY,
            "456",
        )

    policy = BoundaryPolicy(document, unbounded=True)
    assert (
        policy.require_resource(
            "google-main",
            Provider.GOOGLE,
            ResourceKind.GA4_PROPERTY,
            "456",
        )
        == document.accounts[0]
    )
    assert policy.require_google_account_discovery("google-main") == document.accounts[0]
    with pytest.raises(BoundaryDeniedError):
        policy.require_resource(
            "missing",
            Provider.GOOGLE,
            ResourceKind.GA4_PROPERTY,
            "456",
        )


def test_google_account_discovery_requests_only_its_read_scopes(tmp_path: Path) -> None:
    account = _document(
        {
            "id": "google-main",
            "provider": "google",
            "credential": str(tmp_path / "oauth-client.json"),
            "oauth_token_file": str(tmp_path / "oauth" / "google-main.json"),
            "google_account_discovery": True,
        }
    ).accounts[0]

    assert required_google_oauth_scopes(account, enable_writes=False) == (
        "https://www.googleapis.com/auth/webmasters.readonly",
        "https://www.googleapis.com/auth/analytics.readonly",
    )


def test_https_url_normalization_rejects_bad_path_encoding_and_separators() -> None:
    assert _normalize_https_url("https://example.com/%3a", "site") == "https://example.com/%3A"
    with pytest.raises(ValueError, match="valid percent-encoding"):
        _normalize_https_url("https://example.com/%zz", "site")
    with pytest.raises(ValueError, match="backslash"):
        _normalize_https_url("https://example.com/path\\separator", "site")


def test_oauth_boundary_model_requires_a_distinct_absolute_token_file(tmp_path: Path) -> None:
    credential = tmp_path / "secrets" / "oauth-client.json"
    token_file = tmp_path / "oauth" / "google-main.json"
    document = _document(
        {
            "id": "google-main",
            "provider": "google",
            "credential": str(credential),
            "oauth_token_file": str(token_file),
        }
    )
    assert document.accounts[0].oauth_token_file == token_file

    with pytest.raises(ValidationError):
        _document(
            {
                "id": "google-main",
                "provider": "google",
                "credential": str(credential),
                "oauth_token_file": "relative.json",
            }
        )

    with pytest.raises(ValidationError):
        BoundaryDocument.model_validate(
            {
                "accounts": [
                    {
                        "id": "google-one",
                        "provider": "google",
                        "credential": str(credential),
                        "oauth_token_file": str(token_file),
                    },
                    {
                        "id": "google-two",
                        "provider": "google",
                        "credential": str(tmp_path / "secrets" / "other-client.json"),
                        "oauth_token_file": str(token_file),
                    },
                ]
            }
        )


def test_boundary_document_rejects_duplicates(tmp_path: Path) -> None:
    credential = str(tmp_path / "credential")
    with pytest.raises(ValidationError):
        BoundaryDocument.model_validate(
            {
                "accounts": [
                    {"id": "same", "provider": "google", "credential": credential},
                    {"id": "same", "provider": "google", "credential": credential},
                ]
            }
        )
    with pytest.raises(ValidationError, match="client configurations must not be shared"):
        BoundaryDocument.model_validate(
            {
                "accounts": [
                    {
                        "id": "oauth-one",
                        "provider": "google",
                        "credential": credential,
                        "oauth_token_file": str(tmp_path / "oauth" / "one.json"),
                    },
                    {
                        "id": "oauth-two",
                        "provider": "google",
                        "credential": credential,
                        "oauth_token_file": str(tmp_path / "oauth" / "two.json"),
                    },
                ]
            }
        )
    with pytest.raises(ValidationError):
        BoundaryDocument.model_validate(
            {
                "accounts": [
                    {
                        "id": "one",
                        "provider": "google",
                        "credential": credential,
                        "ga4_properties": ["123"],
                    },
                    {
                        "id": "two",
                        "provider": "google",
                        "credential": credential,
                        "ga4_properties": ["123"],
                    },
                ]
            }
        )


def test_indexnow_boundaries_normalize_and_fail_closed(tmp_path: Path) -> None:
    secret_root = tmp_path / "secrets"
    secret_root.mkdir()
    key_file = secret_root / "indexnow-key"
    document = BoundaryDocument.model_validate(
        {
            "indexnow_targets": [
                {
                    "id": "site-main",
                    "host": " Example.COM. ",
                    "key_location": "https://example.com:443/keys/indexnow-key.txt",
                    "key_file": str(key_file),
                }
            ]
        }
    )
    assert document.indexnow_targets[0].host == "example.com"
    assert document.indexnow_targets[0].key_location == "https://example.com/keys/indexnow-key.txt"
    policy = BoundaryPolicy(document)
    assert policy.resolve_indexnow_target("site-main").id == "site-main"
    with pytest.raises(BoundaryDeniedError):
        policy.resolve_indexnow_target("missing")

    invalid_documents: tuple[Mapping[str, object], ...] = (
        {},
        {
            "indexnow_targets": [
                {
                    "id": "site-main",
                    "host": "https://example.com",
                    "key_location": "https://example.com/key.txt",
                    "key_file": str(key_file),
                }
            ]
        },
        {
            "indexnow_targets": [
                {
                    "id": "site-main",
                    "host": "example.com",
                    "key_location": "https://other.example/key.txt",
                    "key_file": str(key_file),
                }
            ]
        },
        {
            "indexnow_targets": [
                {
                    "id": "site-main",
                    "host": "example.com",
                    "key_location": "https://example.com/",
                    "key_file": "relative",
                }
            ]
        },
    )
    for invalid in invalid_documents:
        with pytest.raises(ValidationError):
            BoundaryDocument.model_validate(invalid)

    boundary_file = tmp_path / "boundaries-indexnow.json"
    boundary_file.write_text(
        json.dumps(
            {
                "indexnow_targets": [
                    {
                        "id": "site-main",
                        "host": "example.com",
                        "key_location": "https://example.com/key.txt",
                        "key_file": str(tmp_path / "outside-key"),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ConfigurationError):
        BoundaryPolicy.from_file(boundary_file, secret_root)

    for invalid_host in ("localhost", chr(0xD800)):
        with pytest.raises(ValueError):
            normalize_indexnow_host(invalid_host)

    duplicate_targets = {
        "indexnow_targets": [
            {
                "id": "site-main",
                "host": "example.com",
                "key_location": "https://example.com/one.txt",
                "key_file": str(key_file),
            },
            {
                "id": "site-main",
                "host": "other.example",
                "key_location": "https://other.example/two.txt",
                "key_file": str(key_file),
            },
        ]
    }
    with pytest.raises(ValidationError):
        BoundaryDocument.model_validate(duplicate_targets)

    duplicate_host = {
        "indexnow_targets": [
            {
                "id": "site-one",
                "host": "example.com",
                "key_location": "https://example.com/one.txt",
                "key_file": str(key_file),
            },
            {
                "id": "site-two",
                "host": "example.com",
                "key_location": "https://example.com/two.txt",
                "key_file": str(key_file),
            },
        ]
    }
    with pytest.raises(ValidationError):
        BoundaryDocument.model_validate(duplicate_host)

    with pytest.raises(ValidationError):
        BoundaryDocument.model_validate(
            {
                "accounts": [
                    {
                        "id": "site-main",
                        "provider": "google",
                        "credential": str(key_file),
                    }
                ],
                "indexnow_targets": [
                    {
                        "id": "site-main",
                        "host": "example.com",
                        "key_location": "https://example.com/key.txt",
                        "key_file": str(key_file),
                    }
                ],
            }
        )


def test_boundary_policy_loads_and_fails_closed(tmp_path: Path) -> None:
    secret_root = tmp_path / "secrets"
    secret_root.mkdir()
    boundary_file = tmp_path / "boundaries.json"
    boundary_file.write_text(
        json.dumps(
            {
                "accounts": [
                    {
                        "id": "main",
                        "provider": "google",
                        "credential": str(secret_root / "google.json"),
                        "ga4_properties": ["123"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    policy = BoundaryPolicy.from_file(boundary_file, secret_root)
    assert policy.resolve_account("main", Provider.GOOGLE).id == "main"
    assert (
        policy.require_resource("main", Provider.GOOGLE, ResourceKind.GA4_PROPERTY, "123").id
        == "main"
    )
    with pytest.raises(BoundaryDeniedError):
        policy.resolve_account("missing")
    with pytest.raises(BoundaryDeniedError):
        policy.resolve_account("main", Provider.BING)
    with pytest.raises(BoundaryDeniedError):
        policy.require_resource("main", Provider.GOOGLE, ResourceKind.GA4_PROPERTY, "999")

    bing_document = _document(
        {
            "id": "bing",
            "provider": "bing",
            "credential": str(secret_root / "bing"),
            "sites": ["https://example.com/"],
        }
    )
    bing_policy = BoundaryPolicy(bing_document)
    assert (
        bing_policy.require_resource(
            "bing",
            Provider.BING,
            ResourceKind.BING_SITE,
            "https://example.com/",
        ).id
        == "bing"
    )
    with pytest.raises(BoundaryDeniedError):
        bing_policy._resources_for_kind(
            bing_policy.resolve_account("bing"),
            cast(ResourceKind, "invalid"),
        )

    boundary_file.write_text("not-json", encoding="utf-8")
    with pytest.raises(ConfigurationError):
        BoundaryPolicy.from_file(boundary_file, secret_root)

    boundary_file.write_text(
        json.dumps(
            {
                "accounts": [
                    {
                        "id": "escape",
                        "provider": "google",
                        "credential": str(tmp_path / "outside.json"),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ConfigurationError):
        BoundaryPolicy.from_file(boundary_file, secret_root)


def test_oauth_token_paths_stay_inside_the_configured_writable_root(tmp_path: Path) -> None:
    secret_root = tmp_path / "secrets"
    secret_root.mkdir()
    oauth_root = tmp_path / "oauth"
    oauth_root.mkdir()
    boundary_file = tmp_path / "boundaries-oauth.json"
    boundary_file.write_text(
        json.dumps(
            {
                "accounts": [
                    {
                        "id": "google-main",
                        "provider": "google",
                        "credential": str(secret_root / "oauth-client.json"),
                        "oauth_token_file": str(oauth_root / "google-main.json"),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    policy = BoundaryPolicy.from_file(boundary_file, secret_root, oauth_root)
    assert policy.resolve_account("google-main").oauth_token_file == oauth_root / "google-main.json"

    with pytest.raises(ConfigurationError):
        BoundaryPolicy.from_file(boundary_file, secret_root)

    boundary_file.write_text(
        json.dumps(
            {
                "accounts": [
                    {
                        "id": "google-main",
                        "provider": "google",
                        "credential": str(secret_root / "oauth-client.json"),
                        "oauth_token_file": str(tmp_path / "outside.json"),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ConfigurationError):
        BoundaryPolicy.from_file(boundary_file, secret_root, oauth_root)

    boundary_file.write_text(
        json.dumps(
            {
                "accounts": [
                    {
                        "id": "google-main",
                        "provider": "google",
                        "credential": str(secret_root / "oauth-client.json"),
                        "oauth_token_file": str(oauth_root / "google-main.json"),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    oauth_root.rmdir()
    oauth_root.write_text("not-a-directory", encoding="utf-8")
    with pytest.raises(ConfigurationError, match="token root must be a directory"):
        BoundaryPolicy.from_file(boundary_file, secret_root, oauth_root)

    oauth_root.unlink()
    oauth_root.mkdir()


def test_pagespeed_api_key_path_stays_inside_the_configured_secret_root(tmp_path: Path) -> None:
    secret_root = tmp_path / "secrets"
    secret_root.mkdir()
    boundary_file = tmp_path / "boundaries-pagespeed.json"
    key_file = secret_root / "pagespeed-main-api-key"
    boundary_file.write_text(
        json.dumps(
            {
                "accounts": [
                    {
                        "id": "google-main",
                        "provider": "google",
                        "credential": str(secret_root / "oauth-client.json"),
                        "pagespeed_api_key_file": str(key_file),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    policy = BoundaryPolicy.from_file(boundary_file, secret_root)
    assert policy.resolve_account("google-main").pagespeed_api_key_file == key_file

    boundary_file.write_text(
        json.dumps(
            {
                "accounts": [
                    {
                        "id": "google-main",
                        "provider": "google",
                        "credential": str(secret_root / "oauth-client.json"),
                        "pagespeed_api_key_file": str(tmp_path / "outside-api-key"),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ConfigurationError, match="PageSpeed API key path escapes"):
        BoundaryPolicy.from_file(boundary_file, secret_root)


def test_input_limits_reject_oversized_values() -> None:
    assert require_boundary_file_size(b"{}") == b"{}"
    assert require_http_body_size(b"body") == b"body"
    with pytest.raises(InputLimitError):
        require_boundary_file_size(b"x" * 1_048_577)
    with pytest.raises(InputLimitError):
        require_http_body_size(b"x" * 1_048_577)


@dataclass
class _Payload:
    provider: Provider
    values: tuple[str, ...]


class _PlainEnum(Enum):
    VALUE = "value"


def test_json_conversion_accepts_safe_types_and_rejects_paths() -> None:
    assert to_json_value(_Payload(Provider.GOOGLE, ("one",))) == {
        "provider": "google",
        "values": ["one"],
    }
    assert to_json_value(_PlainEnum.VALUE) == "value"
    with pytest.raises(TypeError):
        to_json_value(Path("/secret"))
    with pytest.raises(TypeError):
        to_json_value({1: "value"})
    with pytest.raises(TypeError):
        to_json_value(object())


def test_search_console_property_requires_a_parseable_candidate_host() -> None:
    assert not search_console_property_contains_url(
        "sc-domain:example.com", "https:///missing-host"
    )


@pytest.mark.parametrize(
    ("candidate_url", "expected"),
    (
        ("https://example.com/blog", True),
        ("https://example.com/blog/article", True),
        ("https://example.com/blogger/article", False),
        ("https://example.com/", False),
    ),
)
def test_url_prefix_helpers_require_a_complete_path_segment(
    candidate_url: str,
    expected: bool,
) -> None:
    configured_url = "https://example.com/blog"

    assert search_console_property_contains_url(configured_url, candidate_url) is expected
    assert configured_site_contains_url(configured_url, candidate_url) is expected


def test_root_url_prefix_helpers_allow_same_authority_children() -> None:
    configured_url = "https://example.com/"
    candidate_url = "https://example.com/blogger/article"

    assert search_console_property_contains_url(configured_url, candidate_url)
    assert configured_site_contains_url(configured_url, candidate_url)


@pytest.mark.parametrize(
    "candidate_url",
    (
        "https://example.com/blog/../private",
        "https://example.com/blog/%2e%2e/private",
        "https://example.com/blog/%2F..%2Fprivate",
        "https://example.com/blog/%252e%252e/private",
    ),
)
def test_url_prefix_helpers_reject_ambiguous_path_traversal(candidate_url: str) -> None:
    configured_url = "https://example.com/blog"

    assert not search_console_property_contains_url(configured_url, candidate_url)
    assert not configured_site_contains_url(configured_url, candidate_url)


def test_url_prefix_policy_rejects_sibling_paths_before_provider_use(tmp_path: Path) -> None:
    configured_url = "https://example.com/blog"
    child_url = "https://example.com/blog/article"
    sibling_url = "https://example.com/blogger/article"
    google_policy = BoundaryPolicy(
        _document(
            {
                "id": "google-main",
                "provider": "google",
                "credential": str(tmp_path / "google-credential"),
                "search_console_sites": [configured_url],
                "pagespeed_sites": [configured_url],
            }
        )
    )
    bing_policy = BoundaryPolicy(
        _document(
            {
                "id": "bing-main",
                "provider": "bing",
                "credential": str(tmp_path / "bing-credential"),
                "sites": [configured_url],
            }
        )
    )

    assert (
        google_policy.require_search_console_url("google-main", configured_url, child_url)
        == child_url
    )
    assert (
        google_policy.require_pagespeed_url("google-main", configured_url, child_url) == child_url
    )
    assert bing_policy.require_bing_site_url("bing-main", configured_url, child_url) == child_url
    with pytest.raises(BoundaryDeniedError):
        google_policy.require_search_console_url("google-main", configured_url, sibling_url)
    with pytest.raises(BoundaryDeniedError):
        google_policy.require_pagespeed_url("google-main", configured_url, sibling_url)
    with pytest.raises(BoundaryDeniedError):
        bing_policy.require_bing_site_url("bing-main", configured_url, sibling_url)
    for traversal_url in (
        "https://example.com/blog/../private",
        "https://example.com/blog/%2e%2e/private",
        "https://example.com/blog/%2F..%2Fprivate",
        "https://example.com/blog/%252e%252e/private",
    ):
        with pytest.raises(ValueError):
            google_policy.require_search_console_url(
                "google-main",
                configured_url,
                traversal_url,
            )
        with pytest.raises(ValueError):
            google_policy.require_pagespeed_url(
                "google-main",
                configured_url,
                traversal_url,
            )
        with pytest.raises(ValueError):
            bing_policy.require_bing_site_url(
                "bing-main",
                configured_url,
                traversal_url,
            )
