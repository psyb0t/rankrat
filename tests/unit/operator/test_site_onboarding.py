from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from rankrat.errors import ConfigurationError, InputLimitError
from rankrat.models.boundaries import BoundaryDocument
from rankrat.operator import site_onboarding
from rankrat.operator.site_onboarding import SiteOnboardingRequest

_MINIMAL_BOUNDARY_DOCUMENT = {
    "indexnow_targets": [
        {
            "id": "site-main",
            "host": "example.com",
            "key_location": "https://example.com/key.txt",
            "key_file": "/run/secrets/indexnow/key",
        }
    ]
}


@pytest.mark.parametrize(
    "site_url",
    (
        "http://example.com/",
        "https://example.com/path",
        "https://example.com/?x=1",
        "https://user@example.com/",
        "https://example.com:444/",
    ),
)
def test_site_onboarding_rejects_non_root_or_unsafe_targets(site_url: str) -> None:
    with pytest.raises((InputLimitError, ValueError)):
        SiteOnboardingRequest("google-main", "bing-main", site_url)


def test_site_onboarding_normalizes_a_root_and_derives_display_name() -> None:
    request = SiteOnboardingRequest("google-main", "bing-main", "https://EXAMPLE.com/")
    assert request.site_url == "https://example.com/"
    assert request.display_name == "example.com"


def test_site_onboarding_rejects_an_unknown_iana_time_zone() -> None:
    with pytest.raises(InputLimitError, match="IANA time zone"):
        SiteOnboardingRequest(
            "google-main",
            "bing-main",
            "https://example.com/",
            time_zone="Invalid/TimeZone",
        )


@pytest.mark.parametrize("parent_account_id", ("", "account-id", "123\\n456"))
def test_site_onboarding_rejects_invalid_google_analytics_parent_account_id(
    parent_account_id: str,
) -> None:
    with pytest.raises(InputLimitError, match="parent account ID"):
        SiteOnboardingRequest(
            "google-main",
            "bing-main",
            "https://example.com/",
            google_analytics_parent_account_id=parent_account_id,
        )


def test_boundary_write_failure_preserves_the_original_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    boundary_file = tmp_path / "boundaries.json"
    original_payload = json.dumps(_MINIMAL_BOUNDARY_DOCUMENT, separators=(",", ":")) + "\n"
    boundary_file.write_text(original_payload, encoding="utf-8")
    document = BoundaryDocument.model_validate_json(original_payload)

    def fail_replace(_: str, __: Path) -> None:
        raise OSError("simulated replacement failure")

    monkeypatch.setattr(site_onboarding.os, "replace", fail_replace)

    with pytest.raises(ConfigurationError, match="boundary update failed"):
        site_onboarding._write_boundary_document(boundary_file, document)

    assert boundary_file.read_text(encoding="utf-8") == original_payload
    assert not list(tmp_path.glob(".boundaries.json.*"))


def test_boundary_write_replaces_with_owner_only_permissions(tmp_path: Path) -> None:
    boundary_file = tmp_path / "boundaries.json"
    boundary_file.write_text(json.dumps(_MINIMAL_BOUNDARY_DOCUMENT), encoding="utf-8")
    document = BoundaryDocument.model_validate(_MINIMAL_BOUNDARY_DOCUMENT)

    site_onboarding._write_boundary_document(boundary_file, document)

    assert stat.S_IMODE(boundary_file.stat().st_mode) == 0o600
