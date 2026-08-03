from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol, cast

import httpx
import pytest
from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

from rankrat.config import Settings
from rankrat.transports.http import create_http_app
from rankrat.transports.openapi import fastapi_drift_document, load_openapi_document
from rankrat.transports.runtime import ApplicationServices

_OPENAPI_SNAPSHOT = Path("openapi.json")


class _WrappedApplication(Protocol):
    _app: object


def _fastapi_application(application: object) -> FastAPI:
    current = application
    while not isinstance(current, FastAPI):
        current = cast(_WrappedApplication, current)._app
    return current


@pytest.mark.asyncio
async def test_yaml_source_matches_fastapi_routes_and_generated_json_artifact(
    indexnow_deployment: tuple[Settings, ApplicationServices],
) -> None:
    settings, services = indexnow_deployment
    app = create_http_app(settings.model_copy(update={"enable_openapi": True}), services)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://rankrat.test",
    ) as client:
        response = await client.get("/openapi.json")

    assert response.status_code == 200
    source_document = load_openapi_document()
    assert response.json() == source_document
    assert json.loads(_OPENAPI_SNAPSHOT.read_text(encoding="utf-8")) == source_document
    fastapi_application = _fastapi_application(app)
    assert get_openapi(
        title=fastapi_application.title,
        version=fastapi_application.version,
        routes=fastapi_application.routes,
    ) == fastapi_drift_document(source_document)
