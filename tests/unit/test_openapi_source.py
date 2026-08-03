from __future__ import annotations

from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute

from rankrat.errors import ConfigurationError
from rankrat.transports.openapi import (
    _validate_document,
    apply_openapi_operation_ids,
    load_openapi_document,
)


def test_openapi_source_is_isolated_between_callers() -> None:
    first_document = load_openapi_document()
    second_document = load_openapi_document()

    first_document["info"] = {"title": "changed", "version": "0.0.0"}

    assert second_document["info"] == {"title": "rankrat", "version": "0.1.0"}


def test_openapi_source_declares_the_runtime_bearer_boundaries() -> None:
    document = load_openapi_document()

    assert document["security"] == [{"BearerAuth": []}]
    components = _mapping(document["components"])
    security_schemes = _mapping(components["securitySchemes"])
    assert set(security_schemes) == {"AdminBearerAuth", "BearerAuth"}
    paths = _mapping(document["paths"])
    health = _mapping(paths["/healthz"])
    health_operation = _mapping(health["get"])
    assert health_operation["security"] == []
    admin_approval = _mapping(paths["/v1/admin/site-onboarding-approvals"])
    admin_operation = _mapping(admin_approval["post"])
    assert admin_operation["security"] == [{"AdminBearerAuth": []}]


def test_openapi_operation_ids_are_applied_from_the_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = FastAPI()

    @app.get("/v1/example")
    def example() -> dict[str, bool]:
        return {"ok": True}

    monkeypatch.setattr(
        "rankrat.transports.openapi._load_openapi_document",
        lambda: {
            "openapi": "3.1.0",
            "info": {"title": "rankrat", "version": "0.1.0"},
            "paths": {"/v1/example": {"get": {"operationId": "exampleRead"}}},
        },
    )

    apply_openapi_operation_ids(app.routes)

    route = next(route for route in app.routes if isinstance(route, APIRoute))
    assert route.operation_id == "exampleRead"


def test_openapi_operation_ids_reject_an_implementation_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = FastAPI()

    @app.get("/v1/example")
    def example() -> dict[str, bool]:
        return {"ok": True}

    monkeypatch.setattr(
        "rankrat.transports.openapi._load_openapi_document",
        lambda: {
            "openapi": "3.1.0",
            "info": {"title": "rankrat", "version": "0.1.0"},
            "paths": {"/v1/other": {"get": {"operationId": "otherRead"}}},
        },
    )

    with pytest.raises(ConfigurationError, match="routes do not match"):
        apply_openapi_operation_ids(app.routes, require_complete=True)


@pytest.mark.parametrize(
    ("document", "message"),
    [
        ({}, "must use OAS 3.1"),
        (
            {"openapi": "3.1.0", "info": {"title": "rankrat", "version": "0.1.0"}, "paths": {}},
            "requires paths",
        ),
        (
            {
                "openapi": "3.1.0",
                "info": {"title": "rankrat", "version": "0.1.0"},
                "paths": {"not-a-path": {}},
            },
            "invalid path",
        ),
        (
            {
                "openapi": "3.1.0",
                "info": {"title": "rankrat", "version": "0.1.0"},
                "paths": {"/one": {"get": {}}},
            },
            "requires operationId",
        ),
        (
            {
                "openapi": "3.1.0",
                "info": {"title": "rankrat", "version": "0.1.0"},
                "paths": {
                    "/one": {"get": {"operationId": "duplicate"}},
                    "/two": {"post": {"operationId": "duplicate"}},
                },
            },
            "operationId must be unique",
        ),
    ],
)
def test_openapi_source_validation_rejects_invalid_documents(
    document: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ConfigurationError, match=message):
        _validate_document(document)


def _mapping(value: object) -> dict[str, object]:
    assert isinstance(value, dict)
    return cast(dict[str, object], value)
