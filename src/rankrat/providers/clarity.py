"""Fixed-origin Microsoft Clarity live-insights reads for one project token."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import cast

import httpx

from rankrat.constants import (
    MAX_CLARITY_DATE_RANGE_DAYS,
    MAX_CLARITY_DIMENSIONS,
    MAX_CLARITY_ROWS,
    MAX_CLARITY_TOKEN_BYTES,
)
from rankrat.models.boundaries import Provider
from rankrat.policy.boundaries import BoundaryPolicy
from rankrat.providers.base import (
    ProviderFailureCode,
    ProviderOperationError,
    ProviderReadRequest,
    read_limited_response,
)

_API_URL = "https://www.clarity.ms/export-data/api/v1/project-live-insights"
_AUTHORIZATION_HEADER = "Authorization"
_BEARER_PREFIX = "Bearer "
_CONTENT_TYPE_HEADER = "Content-Type"
_JSON_CONTENT_TYPE = "application/json"
_TOKEN_PATTERN = re.compile(r"[!-~]{1,512}\Z")
_MAX_INFORMATION_FIELDS = 64

HttpTransportFactory = Callable[[], httpx.AsyncBaseTransport | None]
type ClarityScalar = str | int | float | bool | None


class ClarityDimension(StrEnum):
    """Documented Microsoft Clarity live-insights breakdown dimensions."""

    BROWSER = "Browser"
    DEVICE = "Device"
    COUNTRY_REGION = "Country/Region"
    OPERATING_SYSTEM = "OS"
    SOURCE = "Source"
    MEDIUM = "Medium"
    CAMPAIGN = "Campaign"
    CHANNEL = "Channel"
    URL = "URL"


@dataclass(frozen=True, slots=True)
class ClarityMetric:
    """One live-insights metric and its bounded tabular observations."""

    metric_name: str
    information: tuple[dict[str, ClarityScalar], ...]


class ClarityClient:
    """Read Microsoft Clarity's documented live-insights endpoint only."""

    provider = Provider.CLARITY

    def __init__(
        self,
        policy: BoundaryPolicy,
        transport_factory: HttpTransportFactory = lambda: None,
    ) -> None:
        self._policy = policy
        self._transport_factory = transport_factory

    async def live_insights(
        self,
        request: ProviderReadRequest,
        num_days: int,
        dimensions: tuple[ClarityDimension, ...],
    ) -> tuple[ClarityMetric, ...]:
        if num_days < 1 or num_days > MAX_CLARITY_DATE_RANGE_DAYS:
            raise ValueError("Clarity num_days is outside the documented range")
        if len(dimensions) > MAX_CLARITY_DIMENSIONS:
            raise ValueError("Clarity dimension count exceeds the documented limit")
        if len(set(dimensions)) != len(dimensions):
            raise ValueError("Clarity dimensions must not repeat")
        account = self._policy.resolve_account(str(request.account_id), Provider.CLARITY)
        token = _load_token(account.credential)
        parameters: dict[str, str | int] = {"numOfDays": num_days}
        for index, dimension in enumerate(dimensions, start=1):
            parameters[f"dimension{index}"] = dimension.value
        payload = await self._request_json(request, token, parameters)
        return _metrics_from_payload(payload)

    async def _request_json(
        self,
        request: ProviderReadRequest,
        token: str,
        parameters: dict[str, str | int],
    ) -> object:
        try:
            async with (
                httpx.AsyncClient(
                    transport=self._transport_factory(),
                    trust_env=False,
                    follow_redirects=False,
                    timeout=httpx.Timeout(request.timeout_seconds),
                ) as client,
                client.stream(
                    "GET",
                    _API_URL,
                    params=parameters,
                    headers={
                        _AUTHORIZATION_HEADER: f"{_BEARER_PREFIX}{token}",
                        _CONTENT_TYPE_HEADER: _JSON_CONTENT_TYPE,
                    },
                ) as response,
            ):
                _raise_for_status(response)
                body = await read_limited_response(response, description="Microsoft Clarity")
        except ProviderOperationError:
            raise
        except httpx.TimeoutException as error:
            raise ProviderOperationError(
                ProviderFailureCode.TIMEOUT,
                "Microsoft Clarity request timed out",
            ) from error
        except httpx.HTTPError as error:
            raise ProviderOperationError(
                ProviderFailureCode.UNAVAILABLE,
                "Microsoft Clarity is unavailable",
            ) from error
        try:
            return json.loads(body)
        except json.JSONDecodeError as error:
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "Microsoft Clarity returned invalid JSON",
            ) from error


def _load_token(path: Path) -> str:
    try:
        if path.is_symlink() or not path.is_file():
            raise ProviderOperationError(
                ProviderFailureCode.AUTHENTICATION,
                "Microsoft Clarity token file is invalid",
            )
        raw = path.read_bytes()
    except OSError as error:
        raise ProviderOperationError(
            ProviderFailureCode.AUTHENTICATION,
            "Microsoft Clarity token file is unavailable",
        ) from error
    if len(raw) > MAX_CLARITY_TOKEN_BYTES + 2:
        raise ProviderOperationError(
            ProviderFailureCode.AUTHENTICATION,
            "Microsoft Clarity token file is invalid",
        )
    try:
        token = raw.decode("ascii").strip()
    except UnicodeDecodeError as error:
        raise ProviderOperationError(
            ProviderFailureCode.AUTHENTICATION,
            "Microsoft Clarity token file is invalid",
        ) from error
    if _TOKEN_PATTERN.fullmatch(token) is None:
        raise ProviderOperationError(
            ProviderFailureCode.AUTHENTICATION,
            "Microsoft Clarity token file is invalid",
        )
    return token


def _metrics_from_payload(payload: object) -> tuple[ClarityMetric, ...]:
    if not isinstance(payload, list):
        raise ProviderOperationError(
            ProviderFailureCode.INVALID_RESPONSE,
            "Microsoft Clarity returned an invalid live-insights response",
        )
    items = cast(list[object], payload)
    if len(items) > MAX_CLARITY_ROWS:
        raise ProviderOperationError(
            ProviderFailureCode.INVALID_RESPONSE,
            "Microsoft Clarity returned an invalid live-insights response",
        )
    metrics: list[ClarityMetric] = []
    for item in items:
        if not isinstance(item, dict):
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "Microsoft Clarity returned an invalid live-insights metric",
            )
        metric = cast(dict[str, object], item)
        metric_name = metric.get("metricName")
        rows = metric.get("information")
        if not isinstance(rows, list):
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "Microsoft Clarity returned an invalid live-insights metric",
            )
        information_rows = cast(list[object], rows)
        if (
            not isinstance(metric_name, str)
            or not metric_name.strip()
            or len(metric_name) > 512
            or len(information_rows) > MAX_CLARITY_ROWS
        ):
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "Microsoft Clarity returned an invalid live-insights metric",
            )
        information = tuple(_information_row(row) for row in information_rows)
        metrics.append(ClarityMetric(metric_name, information))
    return tuple(metrics)


def _information_row(value: object) -> dict[str, ClarityScalar]:
    if not isinstance(value, dict):
        raise ProviderOperationError(
            ProviderFailureCode.INVALID_RESPONSE,
            "Microsoft Clarity returned an invalid live-insights row",
        )
    values = cast(dict[object, object], value)
    if len(values) > _MAX_INFORMATION_FIELDS:
        raise ProviderOperationError(
            ProviderFailureCode.INVALID_RESPONSE,
            "Microsoft Clarity returned an invalid live-insights row",
        )
    row: dict[str, ClarityScalar] = {}
    for key, item in values.items():
        if not isinstance(key, str) or not key or len(key) > 256:
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "Microsoft Clarity returned an invalid live-insights row",
            )
        if not isinstance(item, str | int | float | bool) and item is not None:
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "Microsoft Clarity returned an invalid live-insights row",
            )
        row[key] = item
    return row


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
    raise ProviderOperationError(code, "Microsoft Clarity request failed")
