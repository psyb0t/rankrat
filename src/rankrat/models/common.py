"""Safe conversion helpers shared by REST and MCP adapters."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any, cast

type JsonPrimitive = str | int | float | bool | None
type JsonValue = JsonPrimitive | list[JsonValue] | dict[str, JsonValue]


def to_json_value(value: object) -> JsonValue:
    """Convert known internal response types to JSON-safe public data."""
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, Enum):
        return to_json_value(value.value)
    if isinstance(value, Path):
        raise TypeError("paths must never be serialized into public responses")
    if is_dataclass(value) and not isinstance(value, type):
        return to_json_value(asdict(cast(Any, value)))
    if isinstance(value, tuple | list):
        return [to_json_value(item) for item in cast(list[object] | tuple[object, ...], value)]
    if isinstance(value, dict):
        mapping = cast(dict[object, object], value)
        if any(not isinstance(key, str) for key in mapping):
            raise TypeError("JSON object keys must be strings")
        return {cast(str, key): to_json_value(item) for key, item in mapping.items()}
    raise TypeError(f"unsupported public response type: {type(value).__name__}")
