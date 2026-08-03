"""Conservative eligibility detection for Google Indexing API structured data."""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from typing import cast

from rankrat.constants import (
    MAX_SCHEMA_FETCH_RESPONSE_BYTES,
    MAX_SCHEMA_JSON_DEPTH,
    MAX_SCHEMA_JSON_ITEMS,
    MAX_SCHEMA_JSON_LD_SCRIPT_BYTES,
    MAX_SCHEMA_JSON_LD_SCRIPTS,
    MAX_SCHEMA_LOCAL_DOCUMENT_CHARS,
)
from rankrat.errors import InputLimitError
from rankrat.providers.schema_fetch import PublicSchemaFetcher

type JsonObject = dict[str, object]
type JsonValue = str | int | float | bool | None | JsonObject | list[object]
_JOB_POSTING = "JobPosting"
_VIDEO_OBJECT = "VideoObject"
_BROADCAST_EVENT = "BroadcastEvent"
_SCRIPT_TAG_NAME = "script"
_SCRIPT_TYPE_ATTRIBUTE = "type"
_JSON_LD_CONTENT_TYPE = "application/ld+json"
_TAG_OPEN = "<"
_TAG_CLOSE = ">"
_TAG_END_PREFIX = "</"
_COMMENT_OPEN = "<!--"
_COMMENT_CLOSE = "-->"
_ASCII_HTML_WHITESPACE = " \t\n\r\f"


@dataclass(frozen=True, slots=True)
class _ScriptOpenTag:
    content_start: int
    is_json_ld: bool


@dataclass(frozen=True, slots=True)
class IndexingEligibility:
    """Whether local page evidence supports a restricted Google notification."""

    eligible: bool
    reason: str


@dataclass(frozen=True, slots=True)
class LocalSchemaValidationRequest:
    """One bounded local HTML or JSON-LD document with no network side effect."""

    document: str

    def __post_init__(self) -> None:
        if len(self.document) > MAX_SCHEMA_LOCAL_DOCUMENT_CHARS:
            raise InputLimitError("local schema document exceeds the allowed size")
        if len(self.document.encode("utf-8")) > MAX_SCHEMA_FETCH_RESPONSE_BYTES:
            raise InputLimitError("local schema document exceeds the allowed size")


@dataclass(frozen=True, slots=True)
class PublicSchemaValidationRequest:
    """One public HTTPS page to retrieve through the hardened schema fetcher."""

    url: str
    timeout_seconds: float


@dataclass(frozen=True, slots=True)
class PublicSchemaValidationReport:
    """Eligibility evidence for one fetched public HTML page."""

    url: str
    eligibility: IndexingEligibility


class LocalSchemaValidationService:
    """Expose local and hardened-public eligibility checks without provider credentials."""

    def __init__(self, fetcher: PublicSchemaFetcher | None = None) -> None:
        self._fetcher = fetcher or PublicSchemaFetcher()

    def validate_html(self, request: LocalSchemaValidationRequest) -> IndexingEligibility:
        """Evaluate one local raw HTML document."""

        return assess_google_indexing_eligibility(request.document.encode("utf-8"))

    def validate_json_ld(self, request: LocalSchemaValidationRequest) -> IndexingEligibility:
        """Evaluate one local JSON-LD document."""

        return assess_google_indexing_json_ld(request.document)

    async def validate_url(
        self,
        request: PublicSchemaValidationRequest,
    ) -> PublicSchemaValidationReport:
        """Fetch one public page under SSRF policy, then assess its local HTML evidence."""

        fetched = await self._fetcher.fetch(request.url, request.timeout_seconds)
        return PublicSchemaValidationReport(
            url=fetched.url,
            eligibility=assess_google_indexing_eligibility(fetched.body),
        )


def assess_google_indexing_eligibility(html: bytes) -> IndexingEligibility:
    """Accept only JobPosting or VideoObject-embedded BroadcastEvent evidence."""

    if len(html) > MAX_SCHEMA_FETCH_RESPONSE_BYTES:
        return IndexingEligibility(False, "page exceeds the allowed size")
    try:
        decoded = html.decode("utf-8")
    except UnicodeDecodeError:
        return IndexingEligibility(False, "page is not valid UTF-8 HTML")
    scripts = _extract_json_ld_scripts(decoded)
    if len(scripts) > MAX_SCHEMA_JSON_LD_SCRIPTS:
        return IndexingEligibility(False, "page contains too many JSON-LD scripts")
    for script in scripts:
        if len(script.encode("utf-8")) > MAX_SCHEMA_JSON_LD_SCRIPT_BYTES:
            return IndexingEligibility(False, "page contains an oversized JSON-LD script")
        try:
            payload = cast(JsonValue, json.loads(script))
        except (json.JSONDecodeError, RecursionError):
            continue
        result = _assess_payload(payload, "page")
        if result.eligible:
            return result
        if "exceeds" in result.reason:
            return result
    return IndexingEligibility(False, "page lacks eligible Google Indexing API structured data")


def _extract_json_ld_scripts(document: str) -> tuple[str, ...]:
    """Extract only strict JSON-LD script elements in one forward pass."""

    scripts: list[str] = []
    cursor = 0
    while cursor < len(document):
        tag_start = document.find(_TAG_OPEN, cursor)
        if tag_start < 0:
            break
        if not _is_named_tag(document, tag_start, _SCRIPT_TAG_NAME):
            next_cursor = _skip_markup(document, tag_start)
            if next_cursor is None:
                return ()
            cursor = next_cursor
            continue
        opening_tag = _parse_script_open_tag(document, tag_start)
        if opening_tag is None:
            return ()
        closing_tag = _find_script_end_tag(document, opening_tag.content_start)
        if closing_tag is None:
            return ()
        content_end, cursor = closing_tag
        if opening_tag.is_json_ld:
            scripts.append(document[opening_tag.content_start : content_end])
        if len(scripts) > MAX_SCHEMA_JSON_LD_SCRIPTS:
            return tuple(scripts)
    return tuple(scripts)


def _is_named_tag(document: str, tag_start: int, expected_name: str) -> bool:
    name_start = tag_start + len(_TAG_OPEN)
    name_end = name_start + len(expected_name)
    if document[name_start:name_end].lower() != expected_name:
        return False
    if name_end >= len(document):
        return False
    return document[name_end] in _ASCII_HTML_WHITESPACE + _TAG_CLOSE + "/"


def _parse_script_open_tag(document: str, tag_start: int) -> _ScriptOpenTag | None:
    """Read one strict opening script tag, rejecting ambiguous attributes."""

    cursor = tag_start + len(_TAG_OPEN) + len(_SCRIPT_TAG_NAME)
    type_value: str | None = None
    while cursor < len(document):
        cursor = _skip_html_whitespace(document, cursor)
        if cursor >= len(document):
            return None
        if document[cursor] == _TAG_CLOSE:
            return _ScriptOpenTag(
                cursor + len(_TAG_CLOSE),
                type_value == _JSON_LD_CONTENT_TYPE,
            )
        attribute_start = cursor
        while cursor < len(document) and document[cursor] not in _ASCII_HTML_WHITESPACE + "=/>":
            cursor += 1
        if attribute_start == cursor:
            return None
        attribute_name = document[attribute_start:cursor].lower()
        cursor = _skip_html_whitespace(document, cursor)
        attribute_value: str | None = None
        if cursor < len(document) and document[cursor] == "=":
            cursor = _skip_html_whitespace(document, cursor + 1)
            attribute_value, cursor = _parse_html_attribute_value(document, cursor)
            if attribute_value is None:
                return None
        if attribute_name != _SCRIPT_TYPE_ATTRIBUTE:
            continue
        if type_value is not None:
            return None
        if attribute_value is None:
            return None
        type_value = attribute_value.lower()
    return None


def _parse_html_attribute_value(document: str, cursor: int) -> tuple[str | None, int]:
    if cursor >= len(document):
        return None, cursor
    quote = document[cursor]
    if quote in "\"'":
        value_start = cursor + 1
        value_end = document.find(quote, value_start)
        if value_end < 0:
            return None, len(document)
        return document[value_start:value_end], value_end + 1
    value_start = cursor
    while cursor < len(document) and document[cursor] not in _ASCII_HTML_WHITESPACE + _TAG_CLOSE:
        cursor += 1
    if value_start == cursor:
        return None, cursor
    return document[value_start:cursor], cursor


def _find_script_end_tag(document: str, cursor: int) -> tuple[int, int] | None:
    while cursor < len(document):
        tag_start = document.find(_TAG_OPEN, cursor)
        if tag_start < 0:
            return None
        end_name_start = tag_start + len(_TAG_END_PREFIX)
        end_name_end = end_name_start + len(_SCRIPT_TAG_NAME)
        if document[end_name_start:end_name_end].lower() != _SCRIPT_TAG_NAME:
            cursor = tag_start + len(_TAG_OPEN)
            continue
        if end_name_end >= len(document):
            return None
        if document[end_name_end] not in _ASCII_HTML_WHITESPACE + _TAG_CLOSE:
            cursor = tag_start + len(_TAG_OPEN)
            continue
        end_cursor = _skip_html_whitespace(document, end_name_end)
        if end_cursor >= len(document) or document[end_cursor] != _TAG_CLOSE:
            cursor = tag_start + len(_TAG_OPEN)
            continue
        return tag_start, end_cursor + len(_TAG_CLOSE)
    return None


def _skip_markup(document: str, tag_start: int) -> int | None:
    if document.startswith(_COMMENT_OPEN, tag_start):
        comment_end = document.find(_COMMENT_CLOSE, tag_start + len(_COMMENT_OPEN))
        if comment_end < 0:
            return None
        return comment_end + len(_COMMENT_CLOSE)
    cursor = tag_start + len(_TAG_OPEN)
    quote: str | None = None
    while cursor < len(document):
        character = document[cursor]
        if quote is not None:
            if character == quote:
                quote = None
            cursor += 1
            continue
        if character in "\"'":
            quote = character
            cursor += 1
            continue
        if character == _TAG_CLOSE:
            return cursor + len(_TAG_CLOSE)
        cursor += 1
    return None


def _skip_html_whitespace(document: str, cursor: int) -> int:
    while cursor < len(document) and document[cursor] in _ASCII_HTML_WHITESPACE:
        cursor += 1
    return cursor


def assess_google_indexing_json_ld(document: str) -> IndexingEligibility:
    """Evaluate local JSON-LD without an HTML parser or external request."""

    try:
        payload = cast(JsonValue, json.loads(document))
    except (json.JSONDecodeError, RecursionError):
        return IndexingEligibility(False, "JSON-LD document is malformed")
    return _assess_payload(payload, "JSON-LD document")


def _assess_payload(payload: JsonValue, subject: str) -> IndexingEligibility:
    limit_reason = _limit_reason(payload)
    if limit_reason is not None:
        return IndexingEligibility(False, f"{subject} {limit_reason}")
    if _contains_type(payload, _JOB_POSTING):
        return IndexingEligibility(True, f"{subject} contains JobPosting structured data")
    if _contains_video_broadcast_event(payload):
        return IndexingEligibility(
            True,
            f"{subject} contains BroadcastEvent structured data embedded in VideoObject",
        )
    return IndexingEligibility(
        False, f"{subject} lacks eligible Google Indexing API structured data"
    )


def _limit_reason(payload: JsonValue) -> str | None:
    items = 0
    pending: list[tuple[object, int]] = [(payload, 1)]
    while pending:
        value, depth = pending.pop()
        items += 1
        if items > MAX_SCHEMA_JSON_ITEMS:
            return "exceeds the allowed item count"
        if depth > MAX_SCHEMA_JSON_DEPTH:
            return "exceeds the allowed nesting depth"
        if isinstance(value, dict):
            typed_object = cast(JsonObject, value)
            pending.extend((child, depth + 1) for child in typed_object.values())
        elif isinstance(value, list):
            typed_list = cast(list[JsonValue], value)
            pending.extend((child, depth + 1) for child in typed_list)
    return None


def _contains_type(value: object, expected: str) -> bool:
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, dict):
            typed_item = cast(JsonObject, item)
            if expected in _types(typed_item.get("@type")):
                return True
            pending.extend(typed_item.values())
        elif isinstance(item, list):
            pending.extend(cast(list[JsonValue], item))
    return False


def _contains_video_broadcast_event(value: object) -> bool:
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, dict):
            typed_item = cast(JsonObject, item)
            if _VIDEO_OBJECT in _types(typed_item.get("@type")) and _contains_type(
                typed_item,
                _BROADCAST_EVENT,
            ):
                return True
            pending.extend(typed_item.values())
        elif isinstance(item, list):
            pending.extend(cast(list[JsonValue], item))
    return False


def _types(value: object) -> Iterable[str]:
    if isinstance(value, str):
        return (value,)
    if isinstance(value, list):
        items = cast(list[object], value)
        if all(isinstance(item, str) for item in items):
            return tuple(cast(list[str], items))
    return ()
