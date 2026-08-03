"""Fixed-origin PageSpeed Insights client with optional API-key quota identity."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from math import isfinite
from pathlib import Path
from typing import overload

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from rankrat.constants import (
    MAX_PAGESPEED_CATEGORIES,
    MAX_PAGESPEED_LOADING_EXPERIENCE_METRICS,
    MAX_PAGESPEED_METRIC_CATEGORY_CHARS,
    MAX_PAGESPEED_METRIC_DISTRIBUTIONS,
    MAX_PAGESPEED_METRIC_ID_CHARS,
    MAX_PAGESPEED_METRIC_VALUE,
    MAX_PROVIDER_RESPONSE_BYTES,
    PAGESPEED_DISTRIBUTION_PROPORTION_TOLERANCE,
)
from rankrat.errors import BoundaryDeniedError
from rankrat.models.boundaries import Provider, ResourceKind
from rankrat.policy.boundaries import BoundaryPolicy
from rankrat.providers.base import (
    ProviderFailureCode,
    ProviderOperationError,
    ProviderReadRequest,
)

_PAGESPEED_URL = "https://pagespeedonline.googleapis.com/pagespeedonline/v5/runPagespeed"
_PAGESPEED_URL_PARAMETER = "url"
_PAGESPEED_STRATEGY_PARAMETER = "strategy"
_PAGESPEED_CATEGORY_PARAMETER = "category"
_PAGESPEED_API_KEY_PARAMETER = "key"
_MAX_PAGESPEED_CATEGORY_ID_CHARS = 128
_MAX_PAGESPEED_URL_CHARS = 2_048
_MAX_PAGESPEED_API_KEY_BYTES = 512
_MAX_PAGESPEED_API_KEY_FILE_BYTES = _MAX_PAGESPEED_API_KEY_BYTES + 2
_PAGESPEED_API_KEY_PATTERN = re.compile(r"[!-~]{1,512}\Z")
_REDACTED_QUERY_VALUE = "[REDACTED]"

PageSpeedApiKeyLoader = Callable[[Path], str]


class _PageSpeedQueryParameters(dict[str, str | list[str]]):
    """Query parameters whose diagnostic representation never reveals an API key."""

    def __repr__(self) -> str:
        return repr(
            {
                key: _REDACTED_QUERY_VALUE if key == _PAGESPEED_API_KEY_PARAMETER else value
                for key, value in self.items()
            }
        )


@dataclass(frozen=True, slots=True)
class PageSpeedLighthouseCategory:
    """One validated Lighthouse category score returned by PageSpeed."""

    category: str
    score: float | None


@dataclass(frozen=True, slots=True)
class PageSpeedMetricDistribution:
    """One bounded Chrome UX metric distribution bucket."""

    minimum: int
    maximum: int | None
    proportion: float


@dataclass(frozen=True, slots=True)
class PageSpeedLoadingExperienceMetric:
    """One typed Chrome UX field metric from a PageSpeed loading experience."""

    metric_id: str
    percentile: int | None
    category: str | None
    distributions: tuple[PageSpeedMetricDistribution, ...]


@dataclass(frozen=True, slots=True)
class PageSpeedLoadingExperience:
    """Bounded Chrome UX metrics for either the requested page or its origin."""

    overall_category: str | None
    metrics: tuple[PageSpeedLoadingExperienceMetric, ...]


@dataclass(frozen=True, slots=True)
class PageSpeedAnalysisResult:
    """Validated stable summary of one PageSpeed analysis."""

    analyzed_url: str
    analysis_utc_timestamp: datetime
    categories: tuple[PageSpeedLighthouseCategory, ...]
    loading_experience_category: str | None
    origin_loading_experience_category: str | None
    loading_experience: PageSpeedLoadingExperience | None = None
    origin_loading_experience: PageSpeedLoadingExperience | None = None


class _PageSpeedLighthouseCategoryResponse(BaseModel):
    """The constrained Lighthouse category fields used by Rankrat."""

    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)

    id: str
    score: float | None = None

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        if not value or len(value) > _MAX_PAGESPEED_CATEGORY_ID_CHARS:
            raise ValueError("PageSpeed category ID has an invalid length")
        return value

    @field_validator("score")
    @classmethod
    def validate_score(cls, value: float | None) -> float | None:
        if value is None:
            return value
        if not isfinite(value) or value < 0 or value > 1:
            raise ValueError("PageSpeed category score must be finite and between zero and one")
        return value


class _PageSpeedLighthouseResultResponse(BaseModel):
    """The constrained Lighthouse result fields used by Rankrat."""

    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)

    categories: dict[str, _PageSpeedLighthouseCategoryResponse]

    @field_validator("categories")
    @classmethod
    def validate_categories(
        cls,
        value: dict[str, _PageSpeedLighthouseCategoryResponse],
    ) -> dict[str, _PageSpeedLighthouseCategoryResponse]:
        if not value or len(value) > MAX_PAGESPEED_CATEGORIES:
            raise ValueError("PageSpeed category count is outside the allowed range")
        if any(
            not category or len(category) > _MAX_PAGESPEED_CATEGORY_ID_CHARS for category in value
        ):
            raise ValueError("PageSpeed category key has an invalid length")
        return value


class _PageSpeedMetricDistributionResponse(BaseModel):
    """One bounded PageSpeed Chrome UX distribution bucket."""

    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)

    minimum: int = Field(alias="min", ge=0, le=MAX_PAGESPEED_METRIC_VALUE)
    maximum: int | None = Field(
        default=None,
        alias="max",
        ge=0,
        le=MAX_PAGESPEED_METRIC_VALUE,
    )
    proportion: float = Field(ge=0, le=1)

    @field_validator("proportion", mode="before")
    @classmethod
    def validate_proportion(cls, value: float) -> float:
        if not isfinite(value):
            raise ValueError("PageSpeed metric distribution proportion must be finite")
        return value


def _empty_pagespeed_metric_distributions() -> list[_PageSpeedMetricDistributionResponse]:
    return []


class _PageSpeedLoadingExperienceMetricResponse(BaseModel):
    """One bounded PageSpeed Chrome UX field metric."""

    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)

    metricId: str | None = None
    percentile: int | None = Field(default=None, ge=0, le=MAX_PAGESPEED_METRIC_VALUE)
    category: str | None = None
    distributions: list[_PageSpeedMetricDistributionResponse] = Field(
        default_factory=_empty_pagespeed_metric_distributions,
        max_length=MAX_PAGESPEED_METRIC_DISTRIBUTIONS,
    )

    @field_validator("metricId")
    @classmethod
    def validate_metric_id(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if not value or len(value) > MAX_PAGESPEED_METRIC_ID_CHARS:
            raise ValueError("PageSpeed metric ID has an invalid length")
        return value

    @field_validator("category")
    @classmethod
    def validate_category(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if not value or len(value) > MAX_PAGESPEED_METRIC_CATEGORY_CHARS:
            raise ValueError("PageSpeed metric category has an invalid length")
        return value

    @field_validator("distributions")
    @classmethod
    def validate_distributions(
        cls,
        value: list[_PageSpeedMetricDistributionResponse],
    ) -> list[_PageSpeedMetricDistributionResponse]:
        if any(bucket.maximum is not None and bucket.maximum < bucket.minimum for bucket in value):
            raise ValueError("PageSpeed metric distribution has an invalid range")
        if value and abs(sum(bucket.proportion for bucket in value) - 1) > (
            PAGESPEED_DISTRIBUTION_PROPORTION_TOLERANCE
        ):
            raise ValueError("PageSpeed metric distribution proportions must sum to one")
        return value


class _PageSpeedLoadingExperienceResponse(BaseModel):
    """The constrained Chrome UX category used by Rankrat."""

    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)

    overall_category: str | None = None
    metrics: dict[str, _PageSpeedLoadingExperienceMetricResponse] = Field(default_factory=dict)

    @field_validator("overall_category")
    @classmethod
    def validate_overall_category(cls, value: str | None) -> str | None:
        if value is not None and (not value or len(value) > MAX_PAGESPEED_METRIC_CATEGORY_CHARS):
            raise ValueError("PageSpeed loading experience category has an invalid length")
        return value

    @field_validator("metrics")
    @classmethod
    def validate_metrics(
        cls,
        value: dict[str, _PageSpeedLoadingExperienceMetricResponse],
    ) -> dict[str, _PageSpeedLoadingExperienceMetricResponse]:
        if len(value) > MAX_PAGESPEED_LOADING_EXPERIENCE_METRICS:
            raise ValueError("PageSpeed loading experience metric count exceeds the allowed range")
        if any(
            not metric_id or len(metric_id) > MAX_PAGESPEED_METRIC_ID_CHARS for metric_id in value
        ):
            raise ValueError("PageSpeed loading experience metric ID has an invalid length")
        if any(
            metric.metricId is not None and metric.metricId != metric_id
            for metric_id, metric in value.items()
        ):
            raise ValueError("PageSpeed loading experience metric ID does not match its map key")
        return value


class _PageSpeedAnalysisResponse(BaseModel):
    """The constrained PageSpeed response fields exposed by Rankrat."""

    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)

    analysisUTCTimestamp: str
    id: str
    lighthouseResult: _PageSpeedLighthouseResultResponse
    loadingExperience: _PageSpeedLoadingExperienceResponse | None = None
    originLoadingExperience: _PageSpeedLoadingExperienceResponse | None = None

    @field_validator("analysisUTCTimestamp")
    @classmethod
    def validate_timestamp(cls, value: str) -> str:
        _pagespeed_analysis_time(value)
        return value

    @field_validator("id")
    @classmethod
    def validate_url(cls, value: str) -> str:
        if not value or len(value) > _MAX_PAGESPEED_URL_CHARS:
            raise ValueError("PageSpeed analyzed URL has an invalid length")
        return value


class PageSpeedClient:
    """Analyze only URLs authorized below configured PageSpeed site boundaries."""

    provider = Provider.GOOGLE

    def __init__(
        self,
        boundary_policy: BoundaryPolicy,
        api_key_loader: PageSpeedApiKeyLoader | None = None,
        transport_factory: Callable[[], httpx.AsyncBaseTransport | None] = lambda: None,
    ) -> None:
        self._boundary_policy = boundary_policy
        self._api_key_loader = api_key_loader or self._load_api_key
        self._transport_factory = transport_factory

    async def analyze(
        self,
        request: ProviderReadRequest,
        site_url: str,
        page_url: str,
        strategy: str,
        categories: tuple[str, ...],
    ) -> PageSpeedAnalysisResult:
        """Run one bounded PageSpeed analysis for an authorized child URL."""

        normalized_url = self._boundary_policy.require_pagespeed_url(
            str(request.account_id),
            site_url,
            page_url,
        )
        account = self._boundary_policy.require_resource(
            str(request.account_id),
            Provider.GOOGLE,
            ResourceKind.PAGESPEED_SITE,
            site_url,
        )
        parameters = _PageSpeedQueryParameters(
            {
                _PAGESPEED_URL_PARAMETER: normalized_url,
                _PAGESPEED_STRATEGY_PARAMETER: strategy,
                _PAGESPEED_CATEGORY_PARAMETER: list(categories),
            }
        )
        self._add_api_key(parameters, account.pagespeed_api_key_file)
        payload = await self._request_json(request.timeout_seconds, parameters)
        return _pagespeed_analysis_result(
            payload,
            self._boundary_policy,
            str(request.account_id),
            site_url,
        )

    async def _request_json(
        self,
        timeout_seconds: float,
        parameters: _PageSpeedQueryParameters,
    ) -> object:
        try:
            async with (
                httpx.AsyncClient(
                    transport=self._transport_factory(),
                    trust_env=False,
                    follow_redirects=False,
                    timeout=httpx.Timeout(timeout_seconds),
                ) as client,
                client.stream(
                    "GET",
                    _PAGESPEED_URL,
                    params=parameters,
                ) as response,
            ):
                self._raise_for_status(response)
                body = await self._read_bounded_body(response)
        except httpx.TimeoutException as error:
            _clear_httpx_traceback(error)
            raise ProviderOperationError(
                ProviderFailureCode.TIMEOUT,
                "PageSpeed request timed out",
            ) from error
        except httpx.HTTPError as error:
            _clear_httpx_traceback(error)
            raise ProviderOperationError(
                ProviderFailureCode.UNAVAILABLE,
                "PageSpeed is unavailable",
            ) from error

        try:
            decoded = json.loads(body)
        except json.JSONDecodeError as error:
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "PageSpeed returned invalid JSON",
            ) from error
        return decoded

    def _add_api_key(
        self,
        parameters: _PageSpeedQueryParameters,
        path: Path | None,
    ) -> None:
        if path is None:
            return
        parameters[_PAGESPEED_API_KEY_PARAMETER] = self._api_key_for_account(path)

    @overload
    def _api_key_for_account(self, path: None) -> None: ...

    @overload
    def _api_key_for_account(self, path: Path) -> str: ...

    def _api_key_for_account(self, path: Path | None) -> str | None:
        if path is None:
            return None
        try:
            return self._api_key_loader(path)
        except ProviderOperationError:
            raise
        except Exception as error:
            raise ProviderOperationError(
                ProviderFailureCode.AUTHENTICATION,
                "PageSpeed API key is unavailable",
            ) from error

    @staticmethod
    def _load_api_key(path: Path) -> str:
        try:
            with path.open("rb") as key_file:
                raw_key = key_file.read(_MAX_PAGESPEED_API_KEY_FILE_BYTES + 1)
            api_key = raw_key.decode("utf-8")
        except (OSError, UnicodeDecodeError) as error:
            raise ProviderOperationError(
                ProviderFailureCode.AUTHENTICATION,
                "PageSpeed API key is unavailable",
            ) from error
        if api_key.endswith("\r\n"):
            normalized = api_key.removesuffix("\r\n")
        elif api_key.endswith("\r") or api_key.endswith("\n"):
            normalized = api_key[:-1]
        else:
            normalized = api_key
        if len(
            raw_key
        ) > _MAX_PAGESPEED_API_KEY_FILE_BYTES or not _PAGESPEED_API_KEY_PATTERN.fullmatch(
            normalized
        ):
            raise ProviderOperationError(
                ProviderFailureCode.AUTHENTICATION,
                "PageSpeed API key is unavailable",
            )
        return normalized

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        failure_codes = {
            400: ProviderFailureCode.INVALID_RESPONSE,
            401: ProviderFailureCode.AUTHENTICATION,
            403: ProviderFailureCode.FORBIDDEN,
            429: ProviderFailureCode.RATE_LIMITED,
        }
        if response.status_code in failure_codes:
            raise ProviderOperationError(
                failure_codes[response.status_code],
                "PageSpeed request was rejected",
            )
        if response.status_code >= 500:
            raise ProviderOperationError(
                ProviderFailureCode.UNAVAILABLE,
                "PageSpeed is unavailable",
            )
        if response.is_redirect or response.status_code >= 400:
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "PageSpeed returned an unexpected response",
            )

    @staticmethod
    async def _read_bounded_body(response: httpx.Response) -> bytes:
        content_length = response.headers.get("content-length")
        if (
            content_length is not None
            and content_length.isdigit()
            and int(content_length) > MAX_PROVIDER_RESPONSE_BYTES
        ):
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "PageSpeed response exceeds the allowed size",
            )

        body = bytearray()
        async for chunk in response.aiter_bytes():
            body.extend(chunk)
            if len(body) > MAX_PROVIDER_RESPONSE_BYTES:
                raise ProviderOperationError(
                    ProviderFailureCode.INVALID_RESPONSE,
                    "PageSpeed response exceeds the allowed size",
                )
        return bytes(body)


def _clear_httpx_traceback(error: httpx.HTTPError) -> None:
    """Keep provider query strings out of chained diagnostic tracebacks."""

    error.__traceback__ = None


def _pagespeed_analysis_result(
    payload: object,
    boundary_policy: BoundaryPolicy,
    account_id: str,
    site_url: str,
) -> PageSpeedAnalysisResult:
    try:
        response = _PageSpeedAnalysisResponse.model_validate(payload)
        analyzed_url = boundary_policy.require_pagespeed_url(
            account_id,
            site_url,
            response.id,
        )
        categories = tuple(
            PageSpeedLighthouseCategory(category=row.id, score=row.score)
            for row in response.lighthouseResult.categories.values()
        )
        if len({category.category for category in categories}) != len(categories):
            raise ValueError("PageSpeed returned duplicate Lighthouse categories")
        return PageSpeedAnalysisResult(
            analyzed_url=analyzed_url,
            analysis_utc_timestamp=_pagespeed_analysis_time(response.analysisUTCTimestamp),
            categories=tuple(sorted(categories, key=lambda category: category.category)),
            loading_experience_category=(
                response.loadingExperience.overall_category
                if response.loadingExperience is not None
                else None
            ),
            origin_loading_experience_category=(
                response.originLoadingExperience.overall_category
                if response.originLoadingExperience is not None
                else None
            ),
            loading_experience=_pagespeed_loading_experience(response.loadingExperience),
            origin_loading_experience=_pagespeed_loading_experience(
                response.originLoadingExperience
            ),
        )
    except (BoundaryDeniedError, ValidationError, ValueError) as error:
        raise ProviderOperationError(
            ProviderFailureCode.INVALID_RESPONSE,
            "PageSpeed returned an invalid analysis result",
        ) from error


def _pagespeed_loading_experience(
    response: _PageSpeedLoadingExperienceResponse | None,
) -> PageSpeedLoadingExperience | None:
    if response is None or not response.metrics:
        return None
    return PageSpeedLoadingExperience(
        overall_category=response.overall_category,
        metrics=tuple(
            PageSpeedLoadingExperienceMetric(
                metric_id=metric_id,
                percentile=metric.percentile,
                category=metric.category,
                distributions=tuple(
                    PageSpeedMetricDistribution(
                        minimum=bucket.minimum,
                        maximum=bucket.maximum,
                        proportion=bucket.proportion,
                    )
                    for bucket in metric.distributions
                ),
            )
            for metric_id, metric in sorted(response.metrics.items())
        ),
    )


def _pagespeed_analysis_time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("PageSpeed analysis timestamp is invalid") from error
    if parsed.tzinfo is None:
        raise ValueError("PageSpeed analysis timestamp must include a timezone")
    return parsed.astimezone(UTC)
