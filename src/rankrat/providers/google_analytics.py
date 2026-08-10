"""Fixed-origin, read-only Google Analytics Data API provider client."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from rankrat.constants import (
    GOOGLE_ANALYTICS_DISCOVERY_PAGE_SIZE,
    MAX_GA4_FIELD_NAME_CHARS,
    MAX_GA4_ROWS,
    MAX_GA4_VALUE_CHARS,
    MAX_GOOGLE_ANALYTICS_DISCOVERY_PAGES,
    MAX_PROVIDER_RESPONSE_BYTES,
)
from rankrat.constants import (
    GOOGLE_ANALYTICS_READ_SCOPE as _GOOGLE_ANALYTICS_READ_SCOPE,
)
from rankrat.models.boundaries import Provider, ResourceKind
from rankrat.policy.boundaries import BoundaryPolicy
from rankrat.providers.base import (
    AccessTokenProvider,
    ProviderFailureCode,
    ProviderOperationError,
    ProviderReadRequest,
)
from rankrat.providers.google_search_console import HttpTransportFactory

_GOOGLE_ANALYTICS_DATA_URL = (
    "https://analyticsdata.googleapis.com/v1beta/properties/{property_id}:{operation}"
)
_GOOGLE_ANALYTICS_FUNNEL_URL = (
    "https://analyticsdata.googleapis.com/v1alpha/properties/{property_id}:runFunnelReport"
)
_GOOGLE_ANALYTICS_ACCOUNT_SUMMARIES_URL = (
    "https://analyticsadmin.googleapis.com/v1beta/accountSummaries"
)
GOOGLE_ANALYTICS_READ_SCOPE = _GOOGLE_ANALYTICS_READ_SCOPE
_AUTHORIZATION_HEADER = "Authorization"
_BEARER_PREFIX = "Bearer "
_RUN_REPORT_OPERATION = "runReport"
_RUN_REALTIME_REPORT_OPERATION = "runRealtimeReport"
_HTTP_GET = "GET"
_HTTP_POST = "POST"
_PAGE_SIZE_QUERY_PARAMETER = "pageSize"
_PAGE_CURSOR_PARAMETER = "pageToken"
_ACCOUNT_SUMMARY_RESOURCE_PREFIX = "accountSummaries/"
_ACCOUNT_RESOURCE_PREFIX = "accounts/"
_PROPERTY_RESOURCE_PREFIX = "properties/"
_GA4_RESOURCE_ID_PATTERN = re.compile(r"^[0-9]+$")


class Ga4MetricType(StrEnum):
    """Google Analytics metric data types exposed in report headers."""

    UNSPECIFIED = "METRIC_TYPE_UNSPECIFIED"
    INTEGER = "TYPE_INTEGER"
    FLOAT = "TYPE_FLOAT"
    SECONDS = "TYPE_SECONDS"
    MILLISECONDS = "TYPE_MILLISECONDS"
    MINUTES = "TYPE_MINUTES"
    HOURS = "TYPE_HOURS"
    STANDARD = "TYPE_STANDARD"
    CURRENCY = "TYPE_CURRENCY"
    FEET = "TYPE_FEET"
    MILES = "TYPE_MILES"
    METERS = "TYPE_METERS"
    KILOMETERS = "TYPE_KILOMETERS"


@dataclass(frozen=True, slots=True)
class Ga4DateRangeInput:
    """One already-authorized GA4 date range passed to the provider boundary."""

    start_date: str
    end_date: str


@dataclass(frozen=True, slots=True)
class Ga4ReportQuery:
    """A fixed-shape GA4 report request built only by the service layer."""

    date_ranges: tuple[Ga4DateRangeInput, ...] | None
    dimensions: tuple[str, ...]
    metrics: tuple[str, ...]
    limit: int
    offset: int | None

    def as_payload(self) -> dict[str, object]:
        """Return the fixed Google Analytics request body for this query."""

        payload: dict[str, object] = {
            "dimensions": [{"name": name} for name in self.dimensions],
            "metrics": [{"name": name} for name in self.metrics],
            "limit": str(self.limit),
        }
        if self.date_ranges is not None:
            payload["dateRanges"] = [
                {
                    "startDate": date_range.start_date,
                    "endDate": date_range.end_date,
                }
                for date_range in self.date_ranges
            ]
        if self.offset is not None:
            payload["offset"] = str(self.offset)
        return payload


@dataclass(frozen=True, slots=True)
class Ga4FunnelQuery:
    """A constrained event-step funnel request built only by the service layer."""

    date_range: Ga4DateRangeInput
    event_names: tuple[str, ...]
    limit: int

    def as_payload(self) -> dict[str, object]:
        """Return the exact alpha funnel request with no caller-supplied filters."""

        return {
            "dateRanges": [
                {
                    "startDate": self.date_range.start_date,
                    "endDate": self.date_range.end_date,
                }
            ],
            "funnel": {
                "isOpenFunnel": False,
                "steps": [
                    {
                        "name": event_name,
                        "filterExpression": {"funnelEventFilter": {"eventName": event_name}},
                    }
                    for event_name in self.event_names
                ],
            },
            "limit": str(self.limit),
        }


@dataclass(frozen=True, slots=True)
class Ga4MetricHeader:
    """One typed GA4 metric column definition."""

    name: str
    metric_type: Ga4MetricType


@dataclass(frozen=True, slots=True)
class Ga4ReportRow:
    """One typed GA4 table row aligned with its report headers."""

    dimension_values: tuple[str, ...]
    metric_values: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Ga4ReportResult:
    """Validated GA4 table response shared by historical and realtime reads."""

    dimension_headers: tuple[str, ...]
    metric_headers: tuple[Ga4MetricHeader, ...]
    rows: tuple[Ga4ReportRow, ...]
    row_count: int | None


@dataclass(frozen=True, slots=True)
class Ga4FunnelReport:
    """Validated table and visualization subreports from one GA4 funnel read."""

    funnel_table: Ga4ReportResult
    funnel_visualization: Ga4ReportResult


@dataclass(frozen=True, slots=True)
class Ga4PropertySummary:
    """One GA4 property reachable by the configured OAuth account."""

    property_id: str
    display_name: str


@dataclass(frozen=True, slots=True)
class Ga4AccountSummary:
    """One GA4 account and its OAuth-visible properties."""

    account_id: str
    display_name: str
    properties: tuple[Ga4PropertySummary, ...]


class _Ga4DimensionHeaderResponse(BaseModel):
    """The GA4 dimension header fields exposed by Rankrat."""

    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)

    name: str

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return _ga4_text(value, "dimension header")


class _Ga4MetricHeaderResponse(BaseModel):
    """The GA4 metric header fields exposed by Rankrat."""

    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)

    name: str
    metric_type: Ga4MetricType = Field(alias="type")

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return _ga4_text(value, "metric header")

    @field_validator("metric_type", mode="before")
    @classmethod
    def validate_metric_type(cls, value: object) -> Ga4MetricType:
        if not isinstance(value, str):
            raise ValueError("GA4 metric type must be a string")
        try:
            return Ga4MetricType(value)
        except ValueError as error:
            raise ValueError("GA4 metric type is unsupported") from error


class _Ga4ValueResponse(BaseModel):
    """One bounded dimension or metric cell returned by GA4."""

    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)

    value: str

    @field_validator("value")
    @classmethod
    def validate_value(cls, value: str) -> str:
        if len(value) > MAX_GA4_VALUE_CHARS:
            raise ValueError("GA4 row value exceeds the allowed length")
        return value


class _Ga4RowResponse(BaseModel):
    """The constrained GA4 table row fields exposed by Rankrat."""

    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)

    dimensionValues: list[_Ga4ValueResponse] = Field(default_factory=list[_Ga4ValueResponse])
    metricValues: list[_Ga4ValueResponse] = Field(default_factory=list[_Ga4ValueResponse])


class _Ga4ReportResponse(BaseModel):
    """The constrained GA4 report response fields exposed by Rankrat."""

    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)

    dimensionHeaders: list[_Ga4DimensionHeaderResponse]
    metricHeaders: list[_Ga4MetricHeaderResponse]
    rows: list[_Ga4RowResponse] = Field(default_factory=list[_Ga4RowResponse])
    rowCount: int | None = None

    @field_validator("rowCount")
    @classmethod
    def validate_row_count(cls, value: int | None) -> int | None:
        if value is not None and value < 0:
            raise ValueError("GA4 row count must be non-negative")
        return value


class _Ga4FunnelResponse(BaseModel):
    """The two GA4 funnel subreports Rankrat exposes to callers."""

    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)

    funnelTable: _Ga4ReportResponse
    funnelVisualization: _Ga4ReportResponse


class _Ga4PropertySummaryResponse(BaseModel):
    """The GA4 Admin property summary fields Rankrat exposes."""

    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)

    property: str = Field(min_length=1, max_length=MAX_GA4_VALUE_CHARS)
    displayName: str = Field(min_length=1, max_length=MAX_GA4_VALUE_CHARS)


class _Ga4AccountSummaryResponse(BaseModel):
    """The GA4 Admin account summary fields Rankrat exposes."""

    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)

    name: str = Field(min_length=1, max_length=MAX_GA4_VALUE_CHARS)
    account: str = Field(min_length=1, max_length=MAX_GA4_VALUE_CHARS)
    displayName: str = Field(min_length=1, max_length=MAX_GA4_VALUE_CHARS)
    propertySummaries: list[_Ga4PropertySummaryResponse] = Field(
        default_factory=list[_Ga4PropertySummaryResponse],
        max_length=GOOGLE_ANALYTICS_DISCOVERY_PAGE_SIZE,
    )


class _Ga4AccountSummaryPageResponse(BaseModel):
    """One bounded GA4 Admin account-summary page."""

    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)

    accountSummaries: list[_Ga4AccountSummaryResponse] = Field(
        default_factory=list[_Ga4AccountSummaryResponse],
        max_length=GOOGLE_ANALYTICS_DISCOVERY_PAGE_SIZE,
    )
    nextPageToken: str | None = Field(default=None, min_length=1, max_length=MAX_GA4_VALUE_CHARS)


class GoogleAnalyticsDataClient:
    """Read explicit or account-discovered GA4 properties through the Analytics Data API."""

    provider = Provider.GOOGLE

    def __init__(
        self,
        boundary_policy: BoundaryPolicy,
        access_token_provider: AccessTokenProvider,
        transport_factory: HttpTransportFactory = lambda: None,
    ) -> None:
        self._boundary_policy = boundary_policy
        self._access_token_provider = access_token_provider
        self._transport_factory = transport_factory

    async def run_report(
        self,
        request: ProviderReadRequest,
        property_id: str,
        query: Ga4ReportQuery,
    ) -> Ga4ReportResult:
        """Run one bounded historical report for an exact configured property."""

        return await self._run(
            request,
            property_id,
            _RUN_REPORT_OPERATION,
            query,
        )

    async def run_realtime_report(
        self,
        request: ProviderReadRequest,
        property_id: str,
        query: Ga4ReportQuery,
    ) -> Ga4ReportResult:
        """Run one bounded realtime report for an exact configured property."""

        return await self._run(
            request,
            property_id,
            _RUN_REALTIME_REPORT_OPERATION,
            query,
        )

    async def run_funnel_report(
        self,
        request: ProviderReadRequest,
        property_id: str,
        query: Ga4FunnelQuery,
    ) -> Ga4FunnelReport:
        """Run one constrained alpha event-step funnel for a configured property."""

        account = self._boundary_policy.require_google_read_resource(
            str(request.account_id),
            ResourceKind.GA4_PROPERTY,
            property_id,
        )
        token = await self._token_for_account(account.credential)
        response = await self._request_json(
            _HTTP_POST,
            self._funnel_url(property_id),
            token,
            request.timeout_seconds,
            query.as_payload(),
        )
        return _ga4_funnel_report_result(response)

    async def list_account_summaries(
        self,
        request: ProviderReadRequest,
    ) -> tuple[Ga4AccountSummary, ...]:
        """List every bounded GA4 account/property summary visible to this OAuth account."""

        account = self._boundary_policy.require_google_account(str(request.account_id))
        token = await self._token_for_account(account.credential)
        account_summaries: list[Ga4AccountSummary] = []
        seen_account_ids: set[str] = set()
        seen_page_tokens: set[str] = set()
        next_page_token: str | None = None

        for _ in range(MAX_GOOGLE_ANALYTICS_DISCOVERY_PAGES):
            params = {_PAGE_SIZE_QUERY_PARAMETER: str(GOOGLE_ANALYTICS_DISCOVERY_PAGE_SIZE)}
            if next_page_token is not None:
                params[_PAGE_CURSOR_PARAMETER] = next_page_token
            response = await self._request_json(
                _HTTP_GET,
                _GOOGLE_ANALYTICS_ACCOUNT_SUMMARIES_URL,
                token,
                request.timeout_seconds,
                params=params,
            )
            page_summaries, next_page_token = _ga4_account_summary_page(response)
            for account_summary in page_summaries:
                if account_summary.account_id in seen_account_ids:
                    raise ProviderOperationError(
                        ProviderFailureCode.INVALID_RESPONSE,
                        "Google Analytics returned duplicate account summaries",
                    )
                seen_account_ids.add(account_summary.account_id)
                account_summaries.append(account_summary)

            if next_page_token is None:
                return tuple(account_summaries)
            if next_page_token in seen_page_tokens:
                raise ProviderOperationError(
                    ProviderFailureCode.INVALID_RESPONSE,
                    "Google Analytics returned a repeated account-summary page token",
                )
            seen_page_tokens.add(next_page_token)

        raise ProviderOperationError(
            ProviderFailureCode.INVALID_RESPONSE,
            "Google Analytics account-summary pagination exceeds the configured limit",
        )

    async def _run(
        self,
        request: ProviderReadRequest,
        property_id: str,
        operation: str,
        query: Ga4ReportQuery,
    ) -> Ga4ReportResult:
        account = self._boundary_policy.require_google_read_resource(
            str(request.account_id),
            ResourceKind.GA4_PROPERTY,
            property_id,
        )
        token = await self._token_for_account(account.credential)
        response = await self._request_json(
            _HTTP_POST,
            self._report_url(property_id, operation),
            token,
            request.timeout_seconds,
            query.as_payload(),
        )
        return _ga4_report_result(response, query)

    async def _token_for_account(self, credential_path: Path) -> str:
        try:
            return await self._access_token_provider(credential_path)
        except ProviderOperationError:
            raise
        except Exception as error:
            raise ProviderOperationError(
                ProviderFailureCode.AUTHENTICATION,
                "Google Analytics authentication failed",
            ) from error

    @staticmethod
    def _report_url(property_id: str, operation: str) -> str:
        return _GOOGLE_ANALYTICS_DATA_URL.format(
            property_id=property_id,
            operation=operation,
        )

    @staticmethod
    def _funnel_url(property_id: str) -> str:
        return _GOOGLE_ANALYTICS_FUNNEL_URL.format(property_id=property_id)

    async def _request_json(
        self,
        method: str,
        url: str,
        token: str,
        timeout_seconds: float,
        payload: dict[str, object] | None = None,
        params: dict[str, str] | None = None,
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
                    method,
                    url,
                    headers={_AUTHORIZATION_HEADER: f"{_BEARER_PREFIX}{token}"},
                    json=payload,
                    params=params,
                ) as response,
            ):
                self._raise_for_status(response)
                body = await self._read_bounded_body(response)
        except httpx.TimeoutException as error:
            raise ProviderOperationError(
                ProviderFailureCode.TIMEOUT,
                "Google Analytics request timed out",
            ) from error
        except httpx.HTTPError as error:
            raise ProviderOperationError(
                ProviderFailureCode.UNAVAILABLE,
                "Google Analytics is unavailable",
            ) from error

        try:
            decoded = json.loads(body)
        except json.JSONDecodeError as error:
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "Google Analytics returned invalid JSON",
            ) from error
        return decoded

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        failure_codes = {
            401: ProviderFailureCode.AUTHENTICATION,
            403: ProviderFailureCode.FORBIDDEN,
            429: ProviderFailureCode.RATE_LIMITED,
        }
        if response.status_code in failure_codes:
            raise ProviderOperationError(
                failure_codes[response.status_code],
                "Google Analytics request was rejected",
            )
        if response.status_code >= 500:
            raise ProviderOperationError(
                ProviderFailureCode.UNAVAILABLE,
                "Google Analytics is unavailable",
            )
        if response.is_redirect or response.status_code >= 400:
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "Google Analytics returned an unexpected response",
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
                "Google Analytics response exceeds the allowed size",
            )

        body = bytearray()
        async for chunk in response.aiter_bytes():
            body.extend(chunk)
            if len(body) > MAX_PROVIDER_RESPONSE_BYTES:
                raise ProviderOperationError(
                    ProviderFailureCode.INVALID_RESPONSE,
                    "Google Analytics response exceeds the allowed size",
                )
        return bytes(body)


def _ga4_text(value: str, subject: str) -> str:
    if not value or len(value) > MAX_GA4_FIELD_NAME_CHARS:
        raise ValueError(f"GA4 {subject} has an invalid length")
    return value


def _ga4_report_result(payload: object, query: Ga4ReportQuery) -> Ga4ReportResult:
    try:
        response = _Ga4ReportResponse.model_validate(payload)
        if len(response.rows) > MAX_GA4_ROWS:
            raise ValueError("GA4 response has too many rows")

        dimension_headers = tuple(header.name for header in response.dimensionHeaders)
        metric_headers = tuple(
            Ga4MetricHeader(header.name, header.metric_type) for header in response.metricHeaders
        )
        if len(set(dimension_headers)) != len(dimension_headers):
            raise ValueError("GA4 response repeats a dimension header")
        if len({header.name for header in metric_headers}) != len(metric_headers):
            raise ValueError("GA4 response repeats a metric header")
        if dimension_headers != query.dimensions:
            raise ValueError("GA4 response has unexpected dimension headers")
        if tuple(header.name for header in metric_headers) != query.metrics:
            raise ValueError("GA4 response has unexpected metric headers")

        rows = tuple(
            _ga4_report_row(row, len(dimension_headers), len(metric_headers))
            for row in response.rows
        )
        if response.rowCount is not None and response.rowCount < len(rows):
            raise ValueError("GA4 row count is less than returned rows")
        return Ga4ReportResult(
            dimension_headers=dimension_headers,
            metric_headers=metric_headers,
            rows=rows,
            row_count=response.rowCount,
        )
    except (ValidationError, ValueError) as error:
        raise ProviderOperationError(
            ProviderFailureCode.INVALID_RESPONSE,
            "Google Analytics returned an invalid report",
        ) from error


def _ga4_funnel_report_result(payload: object) -> Ga4FunnelReport:
    try:
        response = _Ga4FunnelResponse.model_validate(payload)
        return Ga4FunnelReport(
            funnel_table=_ga4_subreport_result(response.funnelTable),
            funnel_visualization=_ga4_subreport_result(response.funnelVisualization),
        )
    except (ValidationError, ValueError) as error:
        raise ProviderOperationError(
            ProviderFailureCode.INVALID_RESPONSE,
            "Google Analytics returned an invalid funnel report",
        ) from error


def _ga4_account_summary_page(
    payload: object,
) -> tuple[tuple[Ga4AccountSummary, ...], str | None]:
    try:
        response = _Ga4AccountSummaryPageResponse.model_validate(payload)
        account_summaries = tuple(_ga4_account_summary(item) for item in response.accountSummaries)
        return account_summaries, response.nextPageToken
    except (ValidationError, ValueError) as error:
        raise ProviderOperationError(
            ProviderFailureCode.INVALID_RESPONSE,
            "Google Analytics returned an invalid account-summary page",
        ) from error


def _ga4_account_summary(response: _Ga4AccountSummaryResponse) -> Ga4AccountSummary:
    account_id = _ga4_resource_id(
        response.account,
        _ACCOUNT_RESOURCE_PREFIX,
        "account summary account",
    )
    if (
        _ga4_resource_id(response.name, _ACCOUNT_SUMMARY_RESOURCE_PREFIX, "account summary")
        != account_id
    ):
        raise ValueError("GA4 account summary resource names disagree")

    properties = tuple(
        Ga4PropertySummary(
            property_id=_ga4_resource_id(
                item.property,
                _PROPERTY_RESOURCE_PREFIX,
                "property summary",
            ),
            display_name=item.displayName,
        )
        for item in response.propertySummaries
    )
    if len({item.property_id for item in properties}) != len(properties):
        raise ValueError("GA4 account summary repeats a property")
    return Ga4AccountSummary(account_id, response.displayName, properties)


def _ga4_resource_id(value: str, prefix: str, subject: str) -> str:
    resource_id = value.removeprefix(prefix)
    if resource_id == value or _GA4_RESOURCE_ID_PATTERN.fullmatch(resource_id) is None:
        raise ValueError(f"GA4 {subject} has an invalid resource name")
    return resource_id


def _ga4_subreport_result(response: _Ga4ReportResponse) -> Ga4ReportResult:
    if len(response.rows) > MAX_GA4_ROWS:
        raise ValueError("GA4 funnel response has too many rows")
    dimension_headers = tuple(header.name for header in response.dimensionHeaders)
    metric_headers = tuple(
        Ga4MetricHeader(header.name, header.metric_type) for header in response.metricHeaders
    )
    if len(set(dimension_headers)) != len(dimension_headers):
        raise ValueError("GA4 funnel response repeats a dimension header")
    if len({header.name for header in metric_headers}) != len(metric_headers):
        raise ValueError("GA4 funnel response repeats a metric header")
    rows = tuple(
        _ga4_report_row(row, len(dimension_headers), len(metric_headers)) for row in response.rows
    )
    return Ga4ReportResult(
        dimension_headers=dimension_headers,
        metric_headers=metric_headers,
        rows=rows,
        row_count=None,
    )


def _ga4_report_row(
    row: _Ga4RowResponse,
    dimension_count: int,
    metric_count: int,
) -> Ga4ReportRow:
    if len(row.dimensionValues) != dimension_count:
        raise ValueError("GA4 row has a mismatched dimension value count")
    if len(row.metricValues) != metric_count:
        raise ValueError("GA4 row has a mismatched metric value count")
    return Ga4ReportRow(
        dimension_values=tuple(value.value for value in row.dimensionValues),
        metric_values=tuple(value.value for value in row.metricValues),
    )
