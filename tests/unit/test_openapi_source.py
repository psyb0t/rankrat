from __future__ import annotations

import tomllib
from pathlib import Path
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute

from rankrat.errors import ConfigurationError
from rankrat.transports.openapi import (
    _merge_fragment,
    _validate_document,
    apply_openapi_operation_ids,
    fastapi_drift_document,
    load_openapi_document,
    load_openapi_document_for_routes,
)


def test_openapi_source_is_isolated_between_callers() -> None:
    first_document = load_openapi_document()
    second_document = load_openapi_document()
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    first_document["info"] = {"title": "changed", "version": "0.0.0"}

    assert second_document["info"] == {
        "title": "rankrat",
        "version": project["project"]["version"],
        "description": (
            "Boundary-limited SEO operations over REST and MCP. The source document "
            "lists the full writable contract; a read-only runtime removes write routes "
            "from its served OpenAPI document."
        ),
    }


def test_openapi_source_declares_the_runtime_bearer_boundaries() -> None:
    document = load_openapi_document()

    assert document["security"] == [{"BearerAuth": []}]
    components = _mapping(document["components"])
    security_schemes = _mapping(components["securitySchemes"])
    assert set(security_schemes) == {"BearerAuth"}
    paths = _mapping(document["paths"])
    health = _mapping(paths["/healthz"])
    health_operation = _mapping(health["get"])
    assert health_operation["security"] == []
    assert all(not path.startswith("/v1/admin/") for path in paths)


def test_openapi_source_types_every_lighthouse_success_response() -> None:
    document = load_openapi_document()
    paths = _mapping(document["paths"])
    lighthouse_paths = (
        "/v1/lighthouse/audits",
        "/v1/lighthouse/seo-findings",
        "/v1/lighthouse/accessibility-findings",
        "/v1/lighthouse/performance-findings",
        "/v1/lighthouse/best-practices-findings",
    )

    for path in lighthouse_paths:
        operation = _mapping(_mapping(paths[path])["post"])
        responses = _mapping(operation["responses"])
        success = _mapping(responses["200"])
        content = _mapping(success["content"])
        schema = _mapping(_mapping(content["application/json"])["schema"])
        assert schema == {"$ref": "#/components/schemas/LighthouseAuditReport"}

    components = _mapping(document["components"])
    schemas = _mapping(components["schemas"])
    assert {
        "LighthouseAuditReport",
        "LighthouseCategory",
        "LighthouseCategoryScore",
        "LighthouseFinding",
    }.issubset(schemas)


def test_fastapi_drift_document_removes_manual_error_schemas() -> None:
    document: dict[str, object] = {
        "components": {
            "schemas": {
                "ErrorEnvelope": {"type": "object"},
                "ProviderFailureCode": {"type": "string"},
                "Response": {"type": "object"},
            }
        },
        "paths": {},
    }

    drift_document = fastapi_drift_document(document)

    schemas = _mapping(_mapping(drift_document["components"])["schemas"])
    assert schemas == {"Response": {"type": "object"}}


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


def test_runtime_openapi_hides_source_operations_not_active_in_the_router(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = FastAPI()

    @app.get("/v1/reads")
    def reads() -> dict[str, bool]:
        return {"ok": True}

    monkeypatch.setattr(
        "rankrat.transports.openapi._load_openapi_document",
        lambda: {
            "openapi": "3.1.0",
            "info": {"title": "rankrat", "version": "0.1.0"},
            "paths": {
                "/v1/reads": {"get": {"operationId": "readsList"}},
                "/v1/writes": {"post": {"operationId": "writesCreate"}},
            },
        },
    )

    document = load_openapi_document_for_routes(app.routes)

    assert set(_mapping(document["paths"])) == {"/v1/reads"}


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


@pytest.mark.parametrize(
    ("fragment", "message"),
    (
        (
            {
                "paths": {"/one": {"post": {"operationId": "other"}}},
                "components": {"schemas": {"New": {"type": "object"}}},
            },
            "path must be unique",
        ),
        (
            {
                "paths": {"/two": {"get": {"operationId": "two"}}},
                "components": {"schemas": {"Existing": {"type": "object"}}},
            },
            "schema must be unique",
        ),
    ),
)
def test_openapi_fragment_merge_rejects_duplicate_contract_ownership(
    fragment: dict[str, object],
    message: str,
) -> None:
    document: dict[str, object] = {
        "paths": {"/one": {"get": {"operationId": "one"}}},
        "components": {"schemas": {"Existing": {"type": "object"}}},
    }
    with pytest.raises(ConfigurationError, match=message):
        _merge_fragment(document, fragment)


def test_openapi_fragment_merge_adds_unique_paths_and_schemas() -> None:
    document: dict[str, object] = {
        "paths": {"/one": {"get": {"operationId": "one"}}},
        "components": {"schemas": {"Existing": {"type": "object"}}},
    }
    _merge_fragment(
        document,
        {
            "paths": {"/two": {"get": {"operationId": "two"}}},
            "components": {"schemas": {"New": {"type": "object"}}},
        },
    )
    assert set(_mapping(document["paths"])) == {"/one", "/two"}
    assert set(_mapping(_mapping(document["components"])["schemas"])) == {
        "Existing",
        "New",
    }


def _mapping(value: object) -> dict[str, object]:
    assert isinstance(value, dict)
    return cast(dict[str, object], value)
