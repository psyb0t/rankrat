"""Load and validate Rankrat's YAML-first OpenAPI source document."""

from __future__ import annotations

from collections.abc import Sequence
from copy import deepcopy
from functools import cache
from importlib.resources import files
from typing import cast

import yaml
from fastapi.routing import APIRoute, iter_route_contexts
from starlette.routing import BaseRoute

from rankrat.errors import ConfigurationError

_SPECIFICATION_PACKAGE = "rankrat.api"
_SPECIFICATION_FILE = "openapi.yaml"
_OPERATION_METHODS = frozenset({"delete", "get", "head", "options", "patch", "post", "put"})
_MANUAL_OPERATION_FIELDS = frozenset({"security"})


def load_openapi_document() -> dict[str, object]:
    """Return an isolated copy of the validated bundled OpenAPI source document."""

    return deepcopy(_load_openapi_document())


def openapi_info_version() -> str:
    """Return the API document version used by the FastAPI application."""

    info = _mapping(_load_openapi_document()["info"], "OpenAPI source document has invalid info")
    version = info.get("version")
    if not isinstance(version, str):
        raise ConfigurationError("OpenAPI source document has invalid info version")
    return version


def fastapi_drift_document(document: dict[str, object]) -> dict[str, object]:
    """Strip YAML-only authorization metadata before comparing FastAPI route output."""

    expected_document = deepcopy(document)
    expected_document.pop("security", None)
    components = expected_document.get("components")
    if components is not None:
        _mapping(components, "OpenAPI source document has invalid components").pop(
            "securitySchemes",
            None,
        )
    paths = _mapping(
        expected_document.get("paths"),
        "OpenAPI source document requires paths",
    )
    for path_item_value in paths.values():
        path_item = _mapping(path_item_value, "OpenAPI source document has an invalid path")
        for method, operation in path_item.items():
            if method in _OPERATION_METHODS:
                operation_mapping = _mapping(
                    operation,
                    "OpenAPI source document has an invalid operation",
                )
                for field in _MANUAL_OPERATION_FIELDS:
                    operation_mapping.pop(field, None)
    return expected_document


def apply_openapi_operation_ids(
    routes: Sequence[BaseRoute],
    *,
    require_complete: bool = False,
) -> None:
    """Make the OAS source own the operation IDs for the supplied FastAPI routes."""

    source_operations = _source_operations(_load_openapi_document())
    application_operations: dict[tuple[str, str], APIRoute] = {}
    for route_context in iter_route_contexts(routes):
        route = route_context.original_route
        if not isinstance(route, APIRoute) or not route.include_in_schema:
            continue
        if route_context.path_format is None or route_context.methods is None:
            raise ConfigurationError("FastAPI route requires a documented path and method")
        methods = {
            method.lower()
            for method in route_context.methods
            if method.lower() in _OPERATION_METHODS
        }
        if len(methods) != 1:
            raise ConfigurationError("FastAPI route must define exactly one documented method")
        method = methods.pop()
        key = (route_context.path_format, method)
        if key in application_operations:
            raise ConfigurationError("FastAPI route must be unique in the OpenAPI contract")
        application_operations[key] = route
    missing_routes = sorted(source_operations.keys() - application_operations.keys())
    unexpected_routes = sorted(application_operations.keys() - source_operations.keys())
    if unexpected_routes or (require_complete and missing_routes):
        raise ConfigurationError(
            "FastAPI routes do not match the OpenAPI source document: "
            f"missing={missing_routes}, unexpected={unexpected_routes}"
        )
    for key, route in application_operations.items():
        route.operation_id = source_operations[key]


@cache
def _load_openapi_document() -> dict[str, object]:
    try:
        raw_document = (
            files(_SPECIFICATION_PACKAGE).joinpath(_SPECIFICATION_FILE).read_text(encoding="utf-8")
        )
        parsed_document: object = yaml.safe_load(raw_document)
    except (OSError, yaml.YAMLError) as error:
        raise ConfigurationError("OpenAPI source document could not be loaded") from error
    if not isinstance(parsed_document, dict):
        raise ConfigurationError("OpenAPI source document must be an object")
    document = cast(dict[str, object], parsed_document)
    _validate_document(document)
    return document


def _validate_document(document: dict[str, object]) -> None:
    openapi_version = document.get("openapi")
    if not isinstance(openapi_version, str) or not openapi_version.startswith("3.1."):
        raise ConfigurationError("OpenAPI source document must use OAS 3.1")
    info = _mapping(document.get("info"), "OpenAPI source document has invalid info")
    if not isinstance(info.get("title"), str) or not isinstance(info.get("version"), str):
        raise ConfigurationError("OpenAPI source document requires title and version")
    paths = _mapping(document.get("paths"), "OpenAPI source document requires paths")
    if not paths:
        raise ConfigurationError("OpenAPI source document requires paths")
    operation_ids: set[str] = set()
    for path, path_item_value in paths.items():
        if not path.startswith("/"):
            raise ConfigurationError("OpenAPI source document has an invalid path")
        path_item = _mapping(path_item_value, "OpenAPI source document has an invalid path")
        for method, operation_value in path_item.items():
            if method not in _OPERATION_METHODS:
                continue
            operation = _mapping(
                operation_value,
                "OpenAPI source document has an invalid operation",
            )
            operation_id = operation.get("operationId")
            if not isinstance(operation_id, str) or not operation_id:
                raise ConfigurationError("OpenAPI source operation requires operationId")
            if operation_id in operation_ids:
                raise ConfigurationError("OpenAPI source operationId must be unique")
            operation_ids.add(operation_id)


def _source_operations(document: dict[str, object]) -> dict[tuple[str, str], str]:
    paths = _mapping(document.get("paths"), "OpenAPI source document requires paths")
    source_operations: dict[tuple[str, str], str] = {}
    for path, path_item_value in paths.items():
        path_item = _mapping(path_item_value, "OpenAPI source document has an invalid path")
        for method, operation_value in path_item.items():
            if method not in _OPERATION_METHODS:
                continue
            operation = _mapping(
                operation_value,
                "OpenAPI source document has an invalid operation",
            )
            operation_id = operation.get("operationId")
            if not isinstance(operation_id, str):
                raise ConfigurationError("OpenAPI source operation requires operationId")
            source_operations[(path, method)] = operation_id
    return source_operations


def _mapping(value: object, message: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ConfigurationError(message)
    return cast(dict[str, object], value)
