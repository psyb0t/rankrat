"""Fixed-origin backlink adapters with one normalized public result shape."""

from __future__ import annotations

import base64
import re
from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from typing import Protocol
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from rankrat.constants import (
    MAX_BACKLINK_ANCHOR_CHARS,
    MAX_BACKLINK_PROVIDER_REQUESTS,
    MAX_BACKLINK_RESULTS,
    MAX_BACKLINK_TOKEN_BYTES,
)
from rankrat.errors import InputLimitError
from rankrat.models.boundaries import BACKLINK_PROVIDERS, Provider
from rankrat.policy.boundaries import BoundaryPolicy
from rankrat.providers.base import (
    ProviderFailureCode,
    ProviderOperationError,
    ProviderReadiness,
    ProviderReadRequest,
    read_limited_response,
)
from rankrat.providers.bing import BingWebmasterClient

_AHREFS_URL = "https://api.ahrefs.com/v3/site-explorer/all-backlinks"
_MAJESTIC_URL = "https://api.majestic.com/api/json"
_MOZ_URL = "https://lsapi.seomoz.com/v2/links"
_SEMRUSH_URL = "https://api.semrush.com/apis/v4/backlinks/v1/links"
_DATAFORSEO_URL = "https://api.dataforseo.com/v3/backlinks/backlinks/live"
_TOKEN_PATTERN = re.compile(r"[!-~]{1,2048}\Z")
_MAX_URL_CHARS = 2_048
_MOZ_PAGE_SIZE = 50

HttpTransportFactory = Callable[[], httpx.AsyncBaseTransport | None]


@dataclass(frozen=True, slots=True)
class BacklinkRecord:
    source_url: str
    target_url: str
    source_domain: str
    anchor: str
    follow: bool | None
    authority: float | None
    first_seen: str | None
    last_seen: str | None


@dataclass(frozen=True, slots=True)
class BacklinkResult:
    provider: Provider
    target: str
    links: tuple[BacklinkRecord, ...]
    has_more: bool


@dataclass(slots=True)
class BacklinkRequestBudget:
    remaining: int = MAX_BACKLINK_PROVIDER_REQUESTS

    def consume(self) -> None:
        if self.remaining <= 0:
            raise InputLimitError("backlink operation exceeded its provider request budget")
        self.remaining -= 1


class BacklinkClient(Protocol):
    provider: Provider

    async def links(
        self,
        request: ProviderReadRequest,
        target: str,
        limit: int,
        offset: int,
        site_url: str | None = None,
        request_budget: BacklinkRequestBudget | None = None,
    ) -> BacklinkResult: ...


class _AhrefsLink(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)

    url_from: str
    url_to: str
    anchor: str = ""
    is_dofollow: bool | None = None
    domain_rating_source: float | None = None
    first_seen: str | None = None
    last_seen: str | None = None


class _AhrefsResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)

    backlinks: list[_AhrefsLink] = Field(max_length=MAX_BACKLINK_RESULTS)


class _SemrushMeta(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)

    success: bool
    total: int = Field(default=0, ge=0)


class _SemrushLink(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)

    source_url: str
    target_url: str
    source_domain: str | None = None
    anchor: str = ""
    is_nofollow: bool | None = None
    domain_score: float | None = None
    first_seen_at: str | None = None
    last_seen_at: str | None = None


class _SemrushResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)

    meta: _SemrushMeta
    data: list[_SemrushLink] = Field(max_length=MAX_BACKLINK_RESULTS)


class _MajesticLink(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)

    SourceURL: str
    TargetURL: str
    AnchorText: str = ""
    SourceTrustFlow: float | None = None
    FirstIndexedDate: str | None = None
    LastSeenDate: str | None = None
    FlagNoFollow: bool | None = None


class _MajesticTable(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)

    Data: list[_MajesticLink] = Field(
        default_factory=list[_MajesticLink],
        max_length=MAX_BACKLINK_RESULTS,
    )


class _MajesticResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)

    Code: str
    DataTables: dict[str, _MajesticTable]


class _MozPage(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)

    page: str
    domain_authority: int | float | None = None


class _MozLink(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)

    source: _MozPage
    target: _MozPage
    anchor_text: str = ""
    nofollow: bool | None = None
    date_first_seen: str | None = None
    date_last_seen: str | None = None


class _MozResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)

    results: list[_MozLink] = Field(
        default_factory=list[_MozLink],
        max_length=MAX_BACKLINK_RESULTS,
    )
    next_token: str | None = None


class _DataForSeoLink(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)

    url_from: str
    url_to: str
    anchor: str = ""
    dofollow: bool | None = None
    domain_from_rank: float | None = None
    first_seen: str | None = None
    last_seen: str | None = None


class _DataForSeoResult(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)

    items: list[_DataForSeoLink] = Field(
        default_factory=list[_DataForSeoLink],
        max_length=MAX_BACKLINK_RESULTS,
    )
    total_count: int = Field(default=0, ge=0)


class _DataForSeoTask(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)

    status_code: int
    result: list[_DataForSeoResult] = Field(default_factory=list[_DataForSeoResult], max_length=1)


class _DataForSeoResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)

    status_code: int
    tasks: list[_DataForSeoTask] = Field(max_length=1)


def _finite_authority(value: float | None) -> float | None:
    if value is not None and (not isfinite(value) or value < 0):
        raise ProviderOperationError(
            ProviderFailureCode.INVALID_RESPONSE,
            "backlink provider returned an invalid authority metric",
        )
    return value


def _record(
    source_url: str,
    target_url: str,
    anchor: str,
    follow: bool | None,
    authority: float | None,
    first_seen: str | None,
    last_seen: str | None,
) -> BacklinkRecord:
    source = _web_url(source_url, "source URL")
    target = _web_url(target_url, "target URL")
    source_domain = urlparse(source).hostname
    if source_domain is None:
        raise ProviderOperationError(
            ProviderFailureCode.INVALID_RESPONSE,
            "backlink provider returned an invalid source domain",
        )
    if len(anchor) > MAX_BACKLINK_ANCHOR_CHARS:
        raise ProviderOperationError(
            ProviderFailureCode.INVALID_RESPONSE,
            "backlink provider returned an oversized anchor",
        )
    return BacklinkRecord(
        source,
        target,
        source_domain.lower(),
        anchor,
        follow,
        _finite_authority(authority),
        first_seen,
        last_seen,
    )


def _web_url(value: str, subject: str) -> str:
    if len(value) > _MAX_URL_CHARS:
        raise ProviderOperationError(
            ProviderFailureCode.INVALID_RESPONSE,
            f"backlink provider returned an oversized {subject}",
        )
    parsed = urlparse(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ProviderOperationError(
            ProviderFailureCode.INVALID_RESPONSE,
            f"backlink provider returned an invalid {subject}",
        )
    return value


def _moz_url(value: str, subject: str) -> str:
    return _web_url(value if "://" in value else f"https://{value}", subject)


class _BaseBacklinkClient(ABC):
    provider: Provider

    def __init__(
        self,
        policy: BoundaryPolicy,
        transport_factory: HttpTransportFactory = lambda: None,
    ) -> None:
        if self.provider not in BACKLINK_PROVIDERS:
            raise ValueError("unsupported backlink provider")
        self._policy = policy
        self._transport_factory = transport_factory

    @abstractmethod
    async def links(
        self,
        request: ProviderReadRequest,
        target: str,
        limit: int,
        offset: int,
        site_url: str | None = None,
        request_budget: BacklinkRequestBudget | None = None,
    ) -> BacklinkResult:
        """Read one bounded page from this provider."""
        raise NotImplementedError

    async def readiness(self, request: ProviderReadRequest) -> ProviderReadiness:
        """Validate credentials with one bounded read against the first allowed target."""
        account = self._policy.resolve_account(str(request.account_id), self.provider)
        await self.links(request, account.backlink_targets[0], 1, 0)
        return ProviderReadiness(
            account_id=request.account_id,
            provider=self.provider,
            available=True,
            detail=f"configured {self.provider.value} backlink access is available",
        )

    def _authorize(self, request: ProviderReadRequest, target: str) -> tuple[Path, str]:
        account, normalized = self._policy.require_backlink_target(
            str(request.account_id),
            self.provider,
            target,
        )
        return account.credential, normalized

    async def _request_json(
        self,
        request: ProviderReadRequest,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        parameters: Mapping[str, str | int] | None = None,
        json_body: object | None = None,
        request_budget: BacklinkRequestBudget,
    ) -> bytes:
        request_budget.consume()
        try:
            async with (
                httpx.AsyncClient(
                    transport=self._transport_factory(),
                    trust_env=False,
                    follow_redirects=False,
                    timeout=httpx.Timeout(request.timeout_seconds),
                ) as client,
                client.stream(
                    method,
                    url,
                    headers=headers,
                    params=parameters,
                    json=json_body,
                ) as response,
            ):
                self._raise_for_status(response)
                body = await read_limited_response(
                    response,
                    description="backlink provider",
                )
        except httpx.TimeoutException as error:
            raise ProviderOperationError(
                ProviderFailureCode.TIMEOUT,
                "backlink provider request timed out",
            ) from error
        except httpx.HTTPError as error:
            raise ProviderOperationError(
                ProviderFailureCode.UNAVAILABLE,
                "backlink provider is unavailable",
            ) from error
        return body

    @staticmethod
    def _load_credential(path: Path) -> str:
        try:
            if path.is_symlink() or not path.is_file():
                raise ProviderOperationError(
                    ProviderFailureCode.AUTHENTICATION,
                    "backlink credential file is invalid",
                )
            raw = path.read_bytes()
        except OSError as error:
            raise ProviderOperationError(
                ProviderFailureCode.AUTHENTICATION,
                "backlink credential file is unavailable",
            ) from error
        if len(raw) > MAX_BACKLINK_TOKEN_BYTES + 2:
            raise ProviderOperationError(
                ProviderFailureCode.AUTHENTICATION,
                "backlink credential file is invalid",
            )
        try:
            credential = raw.decode("ascii").strip()
        except UnicodeDecodeError as error:
            raise ProviderOperationError(
                ProviderFailureCode.AUTHENTICATION,
                "backlink credential file is invalid",
            ) from error
        if _TOKEN_PATTERN.fullmatch(credential) is None:
            raise ProviderOperationError(
                ProviderFailureCode.AUTHENTICATION,
                "backlink credential file is invalid",
            )
        return credential

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
        raise ProviderOperationError(code, "backlink provider request failed")


class AhrefsBacklinkClient(_BaseBacklinkClient):
    provider = Provider.AHREFS

    async def links(
        self,
        request: ProviderReadRequest,
        target: str,
        limit: int,
        offset: int,
        site_url: str | None = None,
        request_budget: BacklinkRequestBudget | None = None,
    ) -> BacklinkResult:
        if offset != 0:
            raise InputLimitError("Ahrefs does not expose offset or cursor pagination")
        credential_path, normalized = self._authorize(request, target)
        token = self._load_credential(credential_path)
        body = await self._request_json(
            request,
            "GET",
            _AHREFS_URL,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            parameters={
                "target": normalized,
                "mode": "exact" if "://" in normalized else "subdomains",
                "aggregation": "all",
                "history": "live",
                "select": (
                    "url_from,url_to,anchor,is_dofollow,domain_rating_source,first_seen,last_seen"
                ),
                "limit": limit,
            },
            request_budget=request_budget or BacklinkRequestBudget(),
        )
        try:
            response = _AhrefsResponse.model_validate_json(body)
        except ValidationError as error:
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "Ahrefs returned an invalid response",
            ) from error
        links = tuple(
            _record(
                item.url_from,
                item.url_to,
                item.anchor,
                item.is_dofollow,
                item.domain_rating_source,
                item.first_seen,
                item.last_seen,
            )
            for item in response.backlinks
        )
        return BacklinkResult(self.provider, normalized, links, False)


class MajesticBacklinkClient(_BaseBacklinkClient):
    provider = Provider.MAJESTIC

    async def links(
        self,
        request: ProviderReadRequest,
        target: str,
        limit: int,
        offset: int,
        site_url: str | None = None,
        request_budget: BacklinkRequestBudget | None = None,
    ) -> BacklinkResult:
        credential_path, normalized = self._authorize(request, target)
        token = self._load_credential(credential_path)
        body = await self._request_json(
            request,
            "GET",
            _MAJESTIC_URL,
            headers={"Accept": "application/json"},
            parameters={
                "app_api_key": token,
                "cmd": "GetBackLinkData",
                "item": normalized,
                "Count": limit,
                "From": offset,
                "Mode": 1,
                "datasource": "fresh",
            },
            request_budget=request_budget or BacklinkRequestBudget(),
        )
        try:
            response = _MajesticResponse.model_validate_json(body)
            if response.Code != "OK":
                raise ValueError("Majestic command did not succeed")
            table = response.DataTables.get("BackLinks")
            items = table.Data if table is not None else []
        except (ValidationError, ValueError) as error:
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "Majestic returned an invalid response",
            ) from error
        links = tuple(
            _record(
                item.SourceURL,
                item.TargetURL,
                item.AnchorText,
                None if item.FlagNoFollow is None else not item.FlagNoFollow,
                item.SourceTrustFlow,
                item.FirstIndexedDate,
                item.LastSeenDate,
            )
            for item in items
        )
        return BacklinkResult(self.provider, normalized, links, len(links) == limit)


class MozBacklinkClient(_BaseBacklinkClient):
    provider = Provider.MOZ

    async def links(
        self,
        request: ProviderReadRequest,
        target: str,
        limit: int,
        offset: int,
        site_url: str | None = None,
        request_budget: BacklinkRequestBudget | None = None,
    ) -> BacklinkResult:
        credential_path, normalized = self._authorize(request, target)
        credential = self._load_credential(credential_path)
        if ":" not in credential:
            raise ProviderOperationError(
                ProviderFailureCode.AUTHENTICATION,
                "Moz credential must contain access ID and secret separated by a colon",
            )
        encoded = base64.b64encode(credential.encode()).decode()
        remaining_to_skip = offset
        remaining_to_take = limit
        next_token: str | None = None
        results: list[_MozLink] = []
        budget = request_budget or BacklinkRequestBudget()
        required_pages = (offset + limit + _MOZ_PAGE_SIZE - 1) // _MOZ_PAGE_SIZE
        if required_pages > budget.remaining:
            raise InputLimitError("Moz pagination exceeds the provider request budget")
        while remaining_to_take > 0:
            page_limit = min(_MOZ_PAGE_SIZE, remaining_to_skip + remaining_to_take)
            request_body: dict[str, object] = {
                "target": normalized,
                "target_scope": "page" if "://" in normalized else "root_domain",
                "filter": "external",
                "limit": page_limit,
            }
            if next_token is not None:
                request_body["next_token"] = next_token
            body = await self._request_json(
                request,
                "POST",
                _MOZ_URL,
                headers={"Authorization": f"Basic {encoded}", "Accept": "application/json"},
                json_body=request_body,
                request_budget=budget,
            )
            try:
                response = _MozResponse.model_validate_json(body)
            except ValidationError as error:
                raise ProviderOperationError(
                    ProviderFailureCode.INVALID_RESPONSE,
                    "Moz returned an invalid response",
                ) from error
            page_results = response.results
            if remaining_to_skip:
                skipped = min(remaining_to_skip, len(page_results))
                remaining_to_skip -= skipped
                page_results = page_results[skipped:]
            accepted = page_results[:remaining_to_take]
            results.extend(accepted)
            remaining_to_take -= len(accepted)
            next_token = response.next_token
            if next_token is None or not response.results:
                break
        links = tuple(
            _record(
                _moz_url(item.source.page, "source URL"),
                _moz_url(item.target.page, "target URL"),
                item.anchor_text,
                None if item.nofollow is None else not item.nofollow,
                item.source.domain_authority,
                item.date_first_seen,
                item.date_last_seen,
            )
            for item in results
        )
        return BacklinkResult(self.provider, normalized, links, next_token is not None)


class SemrushBacklinkClient(_BaseBacklinkClient):
    provider = Provider.SEMRUSH

    async def links(
        self,
        request: ProviderReadRequest,
        target: str,
        limit: int,
        offset: int,
        site_url: str | None = None,
        request_budget: BacklinkRequestBudget | None = None,
    ) -> BacklinkResult:
        credential_path, normalized = self._authorize(request, target)
        token = self._load_credential(credential_path)
        body = await self._request_json(
            request,
            "GET",
            _SEMRUSH_URL,
            headers={"Authorization": f"Apikey {token}", "Accept": "application/json"},
            parameters={
                "url": normalized,
                "scope": "PAGE" if "://" in normalized else "ROOT_DOMAIN",
                "fields": (
                    "source_url,target_url,source_domain,anchor,is_nofollow,"
                    "domain_score,first_seen_at,last_seen_at"
                ),
                "limit": limit,
                "offset": offset,
                "format": "json",
            },
            request_budget=request_budget or BacklinkRequestBudget(),
        )
        try:
            response = _SemrushResponse.model_validate_json(body)
            if not response.meta.success:
                raise ValueError("Semrush response was unsuccessful")
        except (ValidationError, ValueError) as error:
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "Semrush returned an invalid response",
            ) from error
        links = tuple(
            _record(
                item.source_url,
                item.target_url,
                item.anchor,
                None if item.is_nofollow is None else not item.is_nofollow,
                item.domain_score,
                item.first_seen_at,
                item.last_seen_at,
            )
            for item in response.data
        )
        return BacklinkResult(
            self.provider,
            normalized,
            links,
            offset + len(links) < response.meta.total,
        )


class DataForSeoBacklinkClient(_BaseBacklinkClient):
    provider = Provider.DATAFORSEO

    async def links(
        self,
        request: ProviderReadRequest,
        target: str,
        limit: int,
        offset: int,
        site_url: str | None = None,
        request_budget: BacklinkRequestBudget | None = None,
    ) -> BacklinkResult:
        credential_path, normalized = self._authorize(request, target)
        credential = self._load_credential(credential_path)
        if ":" not in credential:
            raise ProviderOperationError(
                ProviderFailureCode.AUTHENTICATION,
                "DataForSEO credential must contain login and password separated by a colon",
            )
        encoded = base64.b64encode(credential.encode()).decode()
        body = await self._request_json(
            request,
            "POST",
            _DATAFORSEO_URL,
            headers={"Authorization": f"Basic {encoded}", "Accept": "application/json"},
            json_body=[
                {
                    "target": normalized,
                    "mode": "as_is",
                    "limit": limit,
                    "offset": offset,
                    "backlinks_status_type": "live",
                    "exclude_internal_backlinks": True,
                }
            ],
            request_budget=request_budget or BacklinkRequestBudget(),
        )
        try:
            response = _DataForSeoResponse.model_validate_json(body)
            if response.status_code != 20000 or len(response.tasks) != 1:
                raise ValueError("DataForSEO request did not succeed")
            task = response.tasks[0]
            if task.status_code != 20000 or len(task.result) != 1:
                raise ValueError("DataForSEO task did not succeed")
            result = task.result[0]
        except (ValidationError, ValueError) as error:
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "DataForSEO returned an invalid response",
            ) from error
        links = tuple(
            _record(
                item.url_from,
                item.url_to,
                item.anchor,
                item.dofollow,
                item.domain_from_rank,
                item.first_seen,
                item.last_seen,
            )
            for item in result.items
        )
        return BacklinkResult(
            self.provider,
            normalized,
            links,
            offset + len(links) < result.total_count,
        )


class BingBacklinkClient:
    """Adapt Bing Webmaster backlink pages to the shared report shape."""

    provider = Provider.BING

    def __init__(self, client: BingWebmasterClient) -> None:
        self._client = client

    async def links(
        self,
        request: ProviderReadRequest,
        target: str,
        limit: int,
        offset: int,
        site_url: str | None = None,
        request_budget: BacklinkRequestBudget | None = None,
    ) -> BacklinkResult:
        if site_url is None:
            raise InputLimitError("Bing backlink reads require site_url")
        collected: list[BacklinkRecord] = []
        skipped = 0
        page = 0
        total_pages = 1
        budget = request_budget or BacklinkRequestBudget()
        while len(collected) < limit and page < total_pages:
            budget.consume()
            response = await self._client.read_url_links(request, site_url, target, page)
            total_pages = response.total_pages
            for link in response.links:
                if skipped < offset:
                    skipped += 1
                    continue
                collected.append(
                    _record(
                        link.url,
                        target,
                        link.anchor_text,
                        None,
                        None,
                        None,
                        None,
                    )
                )
                if len(collected) == limit:
                    break
            page += 1
        return BacklinkResult(
            self.provider,
            target,
            tuple(collected),
            page < total_pages,
        )
