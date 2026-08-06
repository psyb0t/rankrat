"""Strict Unix-socket client for the optional secret-free Lighthouse worker."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from rankrat.constants import (
    MAX_LIGHTHOUSE_CATEGORIES,
    MAX_LIGHTHOUSE_DISPLAY_VALUE_CHARS,
    MAX_LIGHTHOUSE_FINDINGS,
    MAX_LIGHTHOUSE_ID_CHARS,
    MAX_LIGHTHOUSE_RESPONSE_BYTES,
    MAX_LIGHTHOUSE_TEXT_CHARS,
    MAX_LIGHTHOUSE_TITLE_CHARS,
    MAX_LIGHTHOUSE_URL_CHARS,
)
from rankrat.providers.base import ProviderFailureCode, ProviderOperationError

_WORKER_BASE_URL = "http://lighthouse"
_WORKER_AUDIT_PATH = "/v1/audits"
_HTTP_OK = 200
_HTTP_CONFLICT = 409
_LIGHTHOUSE_CATEGORIES = frozenset({"performance", "accessibility", "best-practices", "seo"})

type LighthouseTransportFactory = Callable[[Path], httpx.AsyncBaseTransport]


def _default_transport(socket_path: Path) -> httpx.AsyncBaseTransport:
    return httpx.AsyncHTTPTransport(uds=str(socket_path), retries=0)


class _CategoryScoreResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    score: float | None

    @field_validator("score")
    @classmethod
    def validate_score(cls, value: float | None) -> float | None:
        if value is not None and (not math.isfinite(value) or not 0 <= value <= 1):
            raise ValueError("Lighthouse category score is outside the allowed range")
        return value


class _FindingResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    id: str = Field(min_length=1, max_length=MAX_LIGHTHOUSE_ID_CHARS)
    categories: tuple[str, ...] = Field(min_length=1, max_length=MAX_LIGHTHOUSE_CATEGORIES)
    score: float | None
    scoreDisplayMode: str = Field(min_length=1, max_length=MAX_LIGHTHOUSE_ID_CHARS)
    title: str = Field(min_length=1, max_length=MAX_LIGHTHOUSE_TITLE_CHARS)
    description: str = Field(max_length=MAX_LIGHTHOUSE_TEXT_CHARS)
    displayValue: str | None = Field(
        default=None,
        max_length=MAX_LIGHTHOUSE_DISPLAY_VALUE_CHARS,
    )
    numericValue: float | None = None
    numericUnit: str | None = Field(default=None, max_length=MAX_LIGHTHOUSE_ID_CHARS)

    @field_validator("score")
    @classmethod
    def validate_score(cls, value: float | None) -> float | None:
        if value is not None and (not math.isfinite(value) or not 0 <= value <= 1):
            raise ValueError("Lighthouse finding score is outside the allowed range")
        return value

    @field_validator("categories")
    @classmethod
    def validate_categories(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value) or not set(value).issubset(_LIGHTHOUSE_CATEGORIES):
            raise ValueError("Lighthouse finding categories are invalid")
        return value

    @field_validator("numericValue")
    @classmethod
    def validate_numeric_value(cls, value: float | None) -> float | None:
        if value is not None and not math.isfinite(value):
            raise ValueError("Lighthouse numeric value must be finite")
        return value


class _AuditReportResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    requestedUrl: str = Field(min_length=1, max_length=MAX_LIGHTHOUSE_URL_CHARS)
    finalUrl: str = Field(min_length=1, max_length=MAX_LIGHTHOUSE_URL_CHARS)
    fetchTime: str = Field(min_length=1, max_length=MAX_LIGHTHOUSE_ID_CHARS)
    lighthouseVersion: str = Field(min_length=1, max_length=MAX_LIGHTHOUSE_ID_CHARS)
    categories: dict[str, _CategoryScoreResponse] = Field(
        min_length=1,
        max_length=MAX_LIGHTHOUSE_CATEGORIES,
    )
    findings: tuple[_FindingResponse, ...] = Field(max_length=MAX_LIGHTHOUSE_FINDINGS)

    @field_validator("requestedUrl", "finalUrl")
    @classmethod
    def validate_url(cls, value: str) -> str:
        try:
            parsed = urlsplit(value)
            port = parsed.port
        except ValueError as error:
            raise ValueError("Lighthouse report URL is invalid") from error
        if (
            parsed.scheme != "https"
            or parsed.hostname is None
            or parsed.username is not None
            or parsed.password is not None
            or port not in (None, 443)
            or parsed.fragment
        ):
            raise ValueError("Lighthouse report URL is invalid")
        return value

    @field_validator("fetchTime")
    @classmethod
    def validate_fetch_time(cls, value: str) -> str:
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as error:
            raise ValueError("Lighthouse fetch time is invalid") from error
        if parsed.tzinfo is None:
            raise ValueError("Lighthouse fetch time requires an offset")
        return value

    @field_validator("categories")
    @classmethod
    def validate_categories(
        cls,
        value: dict[str, _CategoryScoreResponse],
    ) -> dict[str, _CategoryScoreResponse]:
        if not set(value).issubset(_LIGHTHOUSE_CATEGORIES):
            raise ValueError("Lighthouse report categories are invalid")
        return value

    @model_validator(mode="after")
    def validate_findings(self) -> _AuditReportResponse:
        finding_ids = [finding.id for finding in self.findings]
        if len(set(finding_ids)) != len(finding_ids):
            raise ValueError("Lighthouse finding IDs must not repeat")
        report_categories = set(self.categories)
        finding_category_is_invalid = any(
            not set(finding.categories).issubset(report_categories) for finding in self.findings
        )
        if finding_category_is_invalid:
            raise ValueError("Lighthouse finding category is missing from the report")
        return self


@dataclass(frozen=True, slots=True)
class LighthouseCategoryScore:
    category: str
    score: float | None


@dataclass(frozen=True, slots=True)
class LighthouseFinding:
    id: str
    categories: tuple[str, ...]
    score: float | None
    score_display_mode: str
    title: str
    description: str
    display_value: str | None
    numeric_value: float | None
    numeric_unit: str | None


@dataclass(frozen=True, slots=True)
class LighthouseAuditResult:
    requested_url: str
    final_url: str
    fetch_time: str
    lighthouse_version: str
    categories: tuple[LighthouseCategoryScore, ...]
    findings: tuple[LighthouseFinding, ...]


class LighthouseWorkerClient:
    def __init__(
        self,
        socket_path: Path | None,
        transport_factory: LighthouseTransportFactory = _default_transport,
    ) -> None:
        self._socket_path = socket_path
        self._transport_factory = transport_factory

    async def audit(
        self,
        page_url: str,
        categories: tuple[str, ...],
        timeout_seconds: float,
    ) -> LighthouseAuditResult:
        if self._socket_path is None:
            raise ProviderOperationError(
                ProviderFailureCode.UNAVAILABLE,
                "Lighthouse worker is not configured",
            )
        transport = self._transport_factory(self._socket_path)
        try:
            async with (
                httpx.AsyncClient(
                    transport=transport,
                    base_url=_WORKER_BASE_URL,
                    follow_redirects=False,
                    timeout=timeout_seconds,
                ) as client,
                client.stream(
                    "POST",
                    _WORKER_AUDIT_PATH,
                    json={"url": page_url, "categories": categories},
                ) as response,
            ):
                body = await _bounded_response_body(response)
        except httpx.TimeoutException as error:
            raise ProviderOperationError(
                ProviderFailureCode.TIMEOUT,
                "Lighthouse worker timed out",
            ) from error
        except (httpx.HTTPError, OSError) as error:
            raise ProviderOperationError(
                ProviderFailureCode.UNAVAILABLE,
                "Lighthouse worker is unavailable",
            ) from error
        if response.status_code == _HTTP_CONFLICT:
            raise ProviderOperationError(
                ProviderFailureCode.RATE_LIMITED,
                "Lighthouse worker is busy",
            )
        if response.status_code != _HTTP_OK:
            raise ProviderOperationError(
                ProviderFailureCode.UNAVAILABLE,
                "Lighthouse worker rejected the audit",
            )
        try:
            parsed = _AuditReportResponse.model_validate_json(body)
        except ValidationError as error:
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "Lighthouse worker returned an invalid response",
            ) from error
        return _audit_result(parsed)


async def _bounded_response_body(response: httpx.Response) -> bytes:
    chunks: list[bytes] = []
    size = 0
    async for chunk in response.aiter_bytes():
        size += len(chunk)
        if size > MAX_LIGHTHOUSE_RESPONSE_BYTES:
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "Lighthouse worker response exceeded the allowed size",
            )
        chunks.append(chunk)
    return b"".join(chunks)


def _audit_result(response: _AuditReportResponse) -> LighthouseAuditResult:
    return LighthouseAuditResult(
        requested_url=response.requestedUrl,
        final_url=response.finalUrl,
        fetch_time=response.fetchTime,
        lighthouse_version=response.lighthouseVersion,
        categories=tuple(
            LighthouseCategoryScore(category=category, score=value.score)
            for category, value in sorted(response.categories.items())
        ),
        findings=tuple(
            LighthouseFinding(
                id=finding.id,
                categories=finding.categories,
                score=finding.score,
                score_display_mode=finding.scoreDisplayMode,
                title=finding.title,
                description=finding.description,
                display_value=finding.displayValue,
                numeric_value=finding.numericValue,
                numeric_unit=finding.numericUnit,
            )
            for finding in response.findings
        ),
    )
