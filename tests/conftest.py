from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import httpx
import pytest

from rankrat.config import Settings
from rankrat.policy.approvals import WriteApprovalStore
from rankrat.policy.boundaries import BoundaryPolicy
from rankrat.providers.indexnow import IndexNowClient
from rankrat.services.indexnow import IndexNowService
from rankrat.transports.runtime import ApplicationServices, build_services


@pytest.fixture
def deployment(tmp_path: Path) -> tuple[Settings, ApplicationServices]:
    secret_root = tmp_path / "secrets"
    secret_root.mkdir()
    oauth_root = tmp_path / "oauth"
    oauth_root.mkdir(mode=0o700)
    pagespeed_api_key_file = secret_root / "pagespeed-main-api-key"
    pagespeed_api_key_file.write_text("test-pagespeed-api-key", encoding="utf-8")
    boundary_file = tmp_path / "boundaries.json"
    boundary_file.write_text(
        json.dumps(
            {
                "accounts": [
                    {
                        "id": "google-main",
                        "provider": "google",
                        "credential": str(secret_root / "google.json"),
                        "search_console_sites": ["sc-domain:example.com"],
                        "ga4_properties": ["123456789"],
                    },
                    {
                        "id": "bing-main",
                        "provider": "bing",
                        "credential": str(secret_root / "bing-key"),
                        "sites": ["https://example.com/"],
                    },
                    {
                        "id": "pagespeed-main",
                        "provider": "google",
                        "credential": str(secret_root / "pagespeed-client.json"),
                        "pagespeed_api_key_file": str(pagespeed_api_key_file),
                        "pagespeed_sites": ["https://example.com/"],
                    },
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
    return settings, build_services(settings)


@pytest.fixture
def indexnow_deployment(tmp_path: Path) -> tuple[Settings, ApplicationServices]:
    secret_root = tmp_path / "secrets"
    secret_root.mkdir()
    key_file = secret_root / "indexnow-main-key"
    key_file.write_text("test-indexnow-key", encoding="utf-8")
    bing_key_file = secret_root / "bing-main-key"
    bing_key_file.write_text("test-bing-key", encoding="utf-8")
    admin_bearer_file = secret_root / "admin-bearer"
    admin_bearer_file.write_text("a" * 32, encoding="utf-8")
    admin_bearer_file.chmod(0o600)
    boundary_file = tmp_path / "boundaries.json"
    boundary_file.write_text(
        json.dumps(
            {
                "accounts": [
                    {
                        "id": "google-main",
                        "provider": "google",
                        "credential": str(secret_root / "google.json"),
                        "search_console_sites": ["sc-domain:example.com"],
                        "google_analytics_parent_account_id": "123",
                    },
                    {
                        "id": "bing-main",
                        "provider": "bing",
                        "credential": str(bing_key_file),
                        "sites": ["https://example.com/"],
                    },
                ],
                "indexnow_targets": [
                    {
                        "id": "site-main",
                        "host": "example.com",
                        "key_location": "https://example.com/indexnow-main-key.txt",
                        "key_file": str(key_file),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    settings = Settings(
        boundary_file=boundary_file,
        secret_root=secret_root,
        log_file=tmp_path / "rankrat.log",
        enable_writes=True,
        admin_bearer_secret_file=admin_bearer_file,
    )
    policy = BoundaryPolicy.from_file(boundary_file, secret_root)
    client = IndexNowClient(
        policy,
        transport_factory=lambda: httpx.MockTransport(lambda _: httpx.Response(200)),
    )
    services = build_services(settings)
    return settings, replace(
        services,
        indexnow=IndexNowService(policy, client, WriteApprovalStore()),
    )
