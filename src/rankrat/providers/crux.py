"""Fixed-origin Chrome UX Report History API client."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from math import isfinite
from pathlib import Path
from typing import cast
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from rankrat.constants import (
    MAX_CRUX_HISTORY_PERIODS,
    MAX_CRUX_METRIC_ID_CHARS,
    MAX_CRUX_METRICS,
)
from rankrat.errors import BoundaryDeniedError, InputLimitError
from rankrat.models.boundaries import Provider, ResourceKind, normalize_public_https_url
from rankrat.policy.boundaries import BoundaryPolicy
from rankrat.providers.base import (
    ProviderFailureCode,
    ProviderOperationError,
    ProviderReadRequest,
    read_limited_response,
)

_CRUX_HISTORY_URL = "https://chromeuxreport.googleapis.com/v1/records:queryHistoryRecord"
_API_KEY_PATTERN = re.compile(r"[!-~]{1,512}\Z")
_MAX_API_KEY_FILE_BYTES = 514
_MAX_DENSITY_BUCKETS = 8

HttpTransportFactory = Callable[[], httpx.AsyncBaseTransport | None]


class CruxFormFactor(StrEnum):
    ALL = "ALL_FORM_FACTORS"
    PHONE = "PHONE"
    DESKTOP = "DESKTOP"
    TABLET = "TABLET"


class CruxMetric(StrEnum):
    LARGEST_CONTENTFUL_PAINT = "largest_contentful_paint"
    CUMULATIVE_LAYOUT_SHIFT = "cumulative_layout_shift"
    INTERACTION_TO_NEXT_PAINT = "interaction_to_next_paint"
    FIRST_CONTENTFUL_PAINT = "first_contentful_paint"
    EXPERIMENTAL_TIME_TO_FIRST_BYTE = "experimental_time_to_first_byte"


@dataclass(frozen=True, slots=True)
class CruxCollectionPeriod:
    first_date: str
    last_date: str


@dataclass(frozen=True, slots=True)
class CruxHistoryPoint:
    collection_period: CruxCollectionPeriod
    p75: float | None
    densities: tuple[float | None, ...]


@dataclass(frozen=True, slots=True)
class CruxMetricHistory:
    metric: CruxMetric
    points: tuple[CruxHistoryPoint, ...]


@dataclass(frozen=True, slots=True)
class CruxHistoryRecord:
    target: str
    target_kind: str
    form_factor: CruxFormFactor
    metrics: tuple[CruxMetricHistory, ...]
    no_data: bool


class _CruxDate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    year: int = Field(ge=2000, le=3000)
    month: int = Field(ge=1, le=12)
    day: int = Field(ge=1, le=31)

    def iso(self) -> str:
        return f"{self.year:04d}-{self.month:02d}-{self.day:02d}"


class _CruxCollectionPeriod(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)

    firstDate: _CruxDate
    lastDate: _CruxDate


class _CruxPercentiles(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)

    p75s: list[int | float | None] = Field(max_length=MAX_CRUX_HISTORY_PERIODS)

    @field_validator("p75s")
    @classmethod
    def validate_finite(
        cls,
        values: list[int | float | None],
    ) -> list[int | float | None]:
        if any(value is not None and not isfinite(value) for value in values):
            raise ValueError("CrUX percentile values must be finite")
        return values


class _CruxDensity(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)

    densities: list[int | float | None] = Field(max_length=MAX_CRUX_HISTORY_PERIODS)

    @field_validator("densities", mode="before")
    @classmethod
    def normalize_missing_values(cls, values: object) -> object:
        if not isinstance(values, list):
            return values
        typed_values = cast(list[object], values)
        return [None if value == "NaN" else value for value in typed_values]

    @field_validator("densities")
    @classmethod
    def validate_finite(
        cls,
        values: list[int | float | None],
    ) -> list[int | float | None]:
        if any(
            value is not None and (not isfinite(value) or value < 0 or value > 1)
            for value in values
        ):
            raise ValueError("CrUX density values must be finite proportions")
        return values


class _CruxMetricTimeseries(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)

    histogramTimeseries: list[_CruxDensity] = Field(
        default_factory=list[_CruxDensity],
        max_length=_MAX_DENSITY_BUCKETS,
    )
    percentilesTimeseries: _CruxPercentiles | None = None


class _CruxRecord(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)

    collectionPeriods: list[_CruxCollectionPeriod] = Field(max_length=MAX_CRUX_HISTORY_PERIODS)
    metrics: dict[str, _CruxMetricTimeseries]

    @field_validator("metrics")
    @classmethod
    def validate_metrics(
        cls,
        values: dict[str, _CruxMetricTimeseries],
    ) -> dict[str, _CruxMetricTimeseries]:
        if len(values) > MAX_CRUX_METRICS:
            raise ValueError("CrUX metric count exceeds the allowed range")
        if any(not key or len(key) > MAX_CRUX_METRIC_ID_CHARS for key in values):
            raise ValueError("CrUX metric identifier is invalid")
        return values


class _CruxResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)

    record: _CruxRecord


class CruxHistoryClient:
    provider = Provider.GOOGLE

    def __init__(
        self,
        policy: BoundaryPolicy,
        transport_factory: HttpTransportFactory = lambda: None,
    ) -> None:
        self._policy = policy
        self._transport_factory = transport_factory

    async def query(
        self,
        request: ProviderReadRequest,
        site_url: str,
        target: str,
        target_kind: str,
        form_factor: CruxFormFactor,
        metrics: tuple[CruxMetric, ...],
        collection_period_count: int,
    ) -> CruxHistoryRecord:
        account = self._policy.require_resource(
            str(request.account_id),
            Provider.GOOGLE,
            ResourceKind.PAGESPEED_SITE,
            site_url,
        )
        if target_kind == "url":
            normalized_target = self._policy.require_pagespeed_url(
                str(request.account_id),
                site_url,
                target,
            )
            target_field = "url"
        elif target_kind == "origin":
            normalized_target = normalize_public_https_url(target, "origin")
            parsed_target = urlsplit(normalized_target)
            if parsed_target.path not in {"", "/"} or parsed_target.query:
                raise InputLimitError("CrUX origin target must not contain a path or query")
            configured_site = urlsplit(normalize_public_https_url(site_url, "site_url"))
            if (
                parsed_target.scheme != configured_site.scheme
                or parsed_target.netloc != configured_site.netloc
            ):
                raise BoundaryDeniedError("CrUX origin is outside the configured site origin")
            normalized_target = f"{parsed_target.scheme}://{parsed_target.netloc}"
            target_field = "origin"
        else:
            raise ValueError("unsupported CrUX target kind")
        if account.pagespeed_api_key_file is None:
            raise ProviderOperationError(
                ProviderFailureCode.AUTHENTICATION,
                "CrUX requires a configured PageSpeed API key file",
            )
        api_key = self._load_key(account.pagespeed_api_key_file)
        body: dict[str, object] = {
            target_field: normalized_target,
            "formFactor": form_factor.value,
            "metrics": [metric.value for metric in metrics],
            "collectionPeriodCount": collection_period_count,
        }
        try:
            async with (
                httpx.AsyncClient(
                    transport=self._transport_factory(),
                    trust_env=False,
                    follow_redirects=False,
                    timeout=httpx.Timeout(request.timeout_seconds),
                ) as client,
                client.stream(
                    "POST",
                    _CRUX_HISTORY_URL,
                    params={"key": api_key},
                    json=body,
                ) as response,
            ):
                if response.status_code == 404:
                    return CruxHistoryRecord(
                        normalized_target,
                        target_kind,
                        form_factor,
                        (),
                        True,
                    )
                self._raise_for_status(response)
                raw_body = await read_limited_response(
                    response,
                    description="CrUX",
                )
        except httpx.TimeoutException as error:
            raise ProviderOperationError(
                ProviderFailureCode.TIMEOUT,
                "CrUX request timed out",
            ) from error
        except httpx.HTTPError as error:
            raise ProviderOperationError(
                ProviderFailureCode.UNAVAILABLE,
                "CrUX is unavailable",
            ) from error
        try:
            parsed = _CruxResponse.model_validate_json(raw_body)
            return self._record(
                normalized_target,
                target_kind,
                form_factor,
                parsed.record,
                metrics,
            )
        except ValidationError as error:
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "CrUX returned an invalid response",
            ) from error

    @staticmethod
    def _record(
        target: str,
        target_kind: str,
        form_factor: CruxFormFactor,
        record: _CruxRecord,
        requested_metrics: tuple[CruxMetric, ...],
    ) -> CruxHistoryRecord:
        histories: list[CruxMetricHistory] = []
        periods = tuple(
            CruxCollectionPeriod(item.firstDate.iso(), item.lastDate.iso())
            for item in record.collectionPeriods
        )
        for metric in requested_metrics:
            series = record.metrics.get(metric.value)
            if series is None:
                continue
            p75s = series.percentilesTimeseries.p75s if series.percentilesTimeseries else []
            if len(p75s) not in (0, len(periods)):
                raise ProviderOperationError(
                    ProviderFailureCode.INVALID_RESPONSE,
                    "CrUX percentile series length is invalid",
                )
            if any(len(bucket.densities) != len(periods) for bucket in series.histogramTimeseries):
                raise ProviderOperationError(
                    ProviderFailureCode.INVALID_RESPONSE,
                    "CrUX histogram series length is invalid",
                )
            points = tuple(
                CruxHistoryPoint(
                    period,
                    _optional_float(p75s[index]) if p75s else None,
                    tuple(
                        _optional_float(bucket.densities[index])
                        for bucket in series.histogramTimeseries
                    ),
                )
                for index, period in enumerate(periods)
            )
            histories.append(CruxMetricHistory(metric, points))
        return CruxHistoryRecord(target, target_kind, form_factor, tuple(histories), False)

    @staticmethod
    def _load_key(path: Path) -> str:
        try:
            if path.is_symlink() or not path.is_file():
                raise ProviderOperationError(
                    ProviderFailureCode.AUTHENTICATION,
                    "CrUX API key file is invalid",
                )
            raw = path.read_bytes()
        except OSError as error:
            raise ProviderOperationError(
                ProviderFailureCode.AUTHENTICATION,
                "CrUX API key file is unavailable",
            ) from error
        if len(raw) > _MAX_API_KEY_FILE_BYTES:
            raise ProviderOperationError(
                ProviderFailureCode.AUTHENTICATION,
                "CrUX API key file is invalid",
            )
        try:
            value = raw.decode("ascii").strip()
        except UnicodeDecodeError as error:
            raise ProviderOperationError(
                ProviderFailureCode.AUTHENTICATION,
                "CrUX API key file is invalid",
            ) from error
        if _API_KEY_PATTERN.fullmatch(value) is None:
            raise ProviderOperationError(
                ProviderFailureCode.AUTHENTICATION,
                "CrUX API key file is invalid",
            )
        return value

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        if response.status_code == 401:
            code = ProviderFailureCode.AUTHENTICATION
        elif response.status_code == 403:
            code = ProviderFailureCode.FORBIDDEN
        elif response.status_code == 429:
            code = ProviderFailureCode.RATE_LIMITED
        elif response.status_code >= 500:
            code = ProviderFailureCode.UNAVAILABLE
        elif response.is_redirect or response.status_code >= 400:
            code = ProviderFailureCode.INVALID_RESPONSE
        else:
            return
        raise ProviderOperationError(code, "CrUX request failed")


def _optional_float(value: int | float | None) -> float | None:
    return float(value) if value is not None else None
