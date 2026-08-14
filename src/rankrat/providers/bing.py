"""Fixed-origin Bing Webmaster client constrained to configured sites."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, timezone
from enum import StrEnum
from math import isfinite
from pathlib import Path
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, field_validator

from rankrat.constants import (
    BING_UNKNOWN_AVERAGE_POSITION,
    MAX_BING_LINK_PAGE,
    MAX_BING_STATS_LABEL_CHARS,
    MAX_HTTP_STATUS_CODE,
    MAX_PROVIDER_ITEMS,
    MAX_PROVIDER_RESPONSE_BYTES,
    MIN_HTTP_STATUS_CODE,
)
from rankrat.errors import BoundaryDeniedError
from rankrat.logging import log_event
from rankrat.models.boundaries import Provider, ResourceKind
from rankrat.policy.boundaries import BoundaryPolicy
from rankrat.providers.base import (
    ProviderFailureCode,
    ProviderOperationError,
    ProviderReadiness,
    ProviderReadRequest,
)

_BING_API_ROOT = "https://ssl.bing.com/webmaster/api.svc/json"
_API_KEY_PARAMETER = "apikey"
_SITE_URL_PARAMETER = "siteUrl"
_BING_ERROR_CODE_FIELD = "ErrorCode"
_BING_NOT_AUTHORIZED_ERROR_CODE = 14
_MAX_API_KEY_BYTES = 512
_API_KEY_PATTERN = re.compile(r"[!-~]{1,512}\Z")
_BING_LEGACY_DATE_PATTERN = re.compile(r"/Date\((-?\d+)([+-]\d{4})?\)/")
_BING_URL_INFO_HTTP_STATUS_UNAVAILABLE = 0
_JSON_LIST_ADAPTER = TypeAdapter(list[object], config=ConfigDict(strict=True))
_JSON_OBJECT_ADAPTER = TypeAdapter(dict[str, object], config=ConfigDict(strict=True))
_LOGGER = logging.getLogger(__name__)

HttpTransportFactory = Callable[[], httpx.AsyncBaseTransport | None]


@dataclass(frozen=True, slots=True)
class BingTrafficRow:
    """One validated daily traffic row emitted by Bing Webmaster."""

    day: date
    clicks: float
    impressions: float


@dataclass(frozen=True, slots=True)
class BingQueryStatsRow:
    """One validated Bing query or page performance row."""

    label: str
    day: date
    clicks: float
    impressions: float
    average_click_position: float | None
    average_impression_position: float | None


@dataclass(frozen=True, slots=True)
class BingUrlSubmissionQuota:
    """Validated remaining URL-submission quotas for one Bing site."""

    daily: int
    monthly: int


@dataclass(frozen=True, slots=True)
class BingCrawlIssueRow:
    """One validated crawl issue reported for a configured Bing site."""

    url: str
    http_code: int
    issues: int
    in_links: int


@dataclass(frozen=True, slots=True)
class BingCrawlStatsRow:
    """One validated daily Bing crawl-statistics row."""

    day: date
    all_other_codes: int
    blocked_by_robots_txt: int
    code_2xx: int
    code_301: int
    code_302: int
    code_4xx: int
    code_5xx: int
    contains_malware: int
    connection_timeout: int | None
    crawl_errors: int
    crawled_pages: int
    dns_failures: int | None
    in_index: int
    in_links: int


@dataclass(frozen=True, slots=True)
class BingFeedRow:
    """One validated sitemap or feed record reported by Bing Webmaster."""

    url: str
    feed_type: str
    status: str
    compressed: bool
    file_size: int
    url_count: int
    last_crawled: date
    submitted: date


@dataclass(frozen=True, slots=True)
class BingLinkCountRow:
    """One validated inbound-link count record reported by Bing Webmaster."""

    url: str
    count: int


@dataclass(frozen=True, slots=True)
class BingLinkCounts:
    """One validated fixed Bing link-count page."""

    links: tuple[BingLinkCountRow, ...]
    total_pages: int


@dataclass(frozen=True, slots=True)
class BingLinkDetail:
    """One validated inbound link and its reported anchor text."""

    url: str
    anchor_text: str


@dataclass(frozen=True, slots=True)
class BingUrlLinks:
    """One fixed page of inbound links for one configured target URL."""

    links: tuple[BingLinkDetail, ...]
    total_pages: int


@dataclass(frozen=True, slots=True)
class BingSiteVerification:
    """Provider-issued verification material and current state for one site."""

    site_url: str
    dns_verification_code: str
    verified: bool


@dataclass(frozen=True, slots=True)
class BingUrlInformation:
    """Validated indexing and crawl information for one configured Bing child URL."""

    url: str
    anchor_count: int
    discovery_date: date
    document_size: int
    http_status: int | None
    is_page: bool
    last_crawled_date: date
    total_child_url_count: int


@dataclass(frozen=True, slots=True)
class BingKeywordStatsRow:
    """One validated daily Bing keyword-statistics row."""

    query: str
    day: date
    impressions: int
    broad_impressions: int


@dataclass(frozen=True, slots=True)
class BingRelatedKeywordRow:
    """One validated Bing related-keyword row."""

    query: str
    impressions: int
    broad_impressions: int


class _BingSiteResponse(BaseModel):
    """The constrained upstream fields used when listing Bing sites."""

    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)

    Url: str
    DnsVerificationCode: str | None = Field(default=None, max_length=2_048)
    IsVerified: bool | None = None


class _BingTrafficResponseRow(BaseModel):
    """The constrained upstream fields used for Bing daily traffic reports."""

    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)

    Date: str
    Clicks: float
    Impressions: float

    @field_validator("Date")
    @classmethod
    def validate_date(cls, value: str) -> str:
        _bing_traffic_day(value)
        return value

    @field_validator("Clicks", "Impressions")
    @classmethod
    def validate_metric(cls, value: float) -> float:
        if not isfinite(value) or value < 0:
            raise ValueError("traffic metric must be finite and non-negative")
        return value


class _BingQueryStatsResponseRow(BaseModel):
    """The documented constrained fields used for Bing query/page statistics."""

    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)

    Query: str
    Date: str
    Clicks: float
    Impressions: float
    AvgClickPosition: float
    AvgImpressionPosition: float

    @field_validator("Query")
    @classmethod
    def validate_label(cls, value: str) -> str:
        if not value or len(value) > MAX_BING_STATS_LABEL_CHARS:
            raise ValueError("query stats label has an invalid length")
        return value

    @field_validator("Date")
    @classmethod
    def validate_date(cls, value: str) -> str:
        _bing_traffic_day(value)
        return value

    @field_validator("Clicks", "Impressions")
    @classmethod
    def validate_metric(cls, value: float) -> float:
        if not isfinite(value) or value < 0:
            raise ValueError("query stats metric must be finite and non-negative")
        return value

    @field_validator("AvgClickPosition", "AvgImpressionPosition")
    @classmethod
    def validate_position(cls, value: float) -> float:
        if not isfinite(value) or (value <= 0 and value != BING_UNKNOWN_AVERAGE_POSITION):
            raise ValueError("query stats position must be finite and positive")
        return value


class _BingUrlSubmissionQuotaResponse(BaseModel):
    """The documented remaining Bing URL-submission quota fields."""

    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)

    DailyQuota: int
    MonthlyQuota: int

    @field_validator("DailyQuota", "MonthlyQuota")
    @classmethod
    def validate_quota(cls, value: int) -> int:
        if value < 0:
            raise ValueError("URL submission quota must be non-negative")
        return value


class _BingCrawlIssueResponseRow(BaseModel):
    """The documented fields returned by Bing's crawl-issues operation."""

    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)

    HttpCode: int
    Issues: int
    Url: str
    InLinks: int

    @field_validator("HttpCode", "Issues", "InLinks")
    @classmethod
    def validate_non_negative_count(cls, value: int) -> int:
        if value < 0:
            raise ValueError("crawl issue count must be non-negative")
        return value

    @field_validator("Url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        if not value or len(value) > MAX_BING_STATS_LABEL_CHARS:
            raise ValueError("crawl issue URL has an invalid length")
        return value


class _BingCrawlStatsResponseRow(BaseModel):
    """The documented fields returned by Bing's daily crawl-statistics operation."""

    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)

    AllOtherCodes: int
    BlockedByRobotsTxt: int
    Code2xx: int
    Code301: int
    Code302: int
    Code4xx: int
    Code5xx: int
    ContainsMalware: int
    CrawlErrors: int
    CrawledPages: int
    Date: str
    InIndex: int
    InLinks: int
    ConnectionTimeout: int | None = None
    DnsFailures: int | None = None

    @field_validator(
        "AllOtherCodes",
        "BlockedByRobotsTxt",
        "Code2xx",
        "Code301",
        "Code302",
        "Code4xx",
        "Code5xx",
        "ContainsMalware",
        "CrawlErrors",
        "CrawledPages",
        "InIndex",
        "InLinks",
        "ConnectionTimeout",
        "DnsFailures",
    )
    @classmethod
    def validate_non_negative_count(cls, value: int | None) -> int | None:
        if value is not None and value < 0:
            raise ValueError("crawl statistic must be non-negative")
        return value

    @field_validator("Date")
    @classmethod
    def validate_date(cls, value: str) -> str:
        _bing_traffic_day(value)
        return value


class _BingFeedResponseRow(BaseModel):
    """The documented fields returned by Bing's configured-feed operation."""

    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)

    Compressed: bool
    FileSize: int
    LastCrawled: str
    Status: str
    Submitted: str
    Type: str
    Url: str
    UrlCount: int

    @field_validator("FileSize", "UrlCount")
    @classmethod
    def validate_non_negative_count(cls, value: int) -> int:
        if value < 0:
            raise ValueError("feed count must be non-negative")
        return value

    @field_validator("Status", "Type", "Url")
    @classmethod
    def validate_non_empty_text(cls, value: str) -> str:
        if not value or len(value) > MAX_BING_STATS_LABEL_CHARS:
            raise ValueError("feed text field has an invalid length")
        return value

    @field_validator("LastCrawled", "Submitted")
    @classmethod
    def validate_date(cls, value: str) -> str:
        _bing_traffic_day(value)
        return value


class _BingLinkCountResponseRow(BaseModel):
    """The documented fields in one Bing link-count record."""

    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)

    Count: int
    Url: str

    @field_validator("Count")
    @classmethod
    def validate_count(cls, value: int) -> int:
        if value < 0:
            raise ValueError("link count must be non-negative")
        return value

    @field_validator("Url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        if not value or len(value) > MAX_BING_STATS_LABEL_CHARS:
            raise ValueError("link URL has an invalid length")
        return value


class _BingLinkCountsResponse(BaseModel):
    """The documented fixed Bing link-count response."""

    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)

    Links: list[_BingLinkCountResponseRow]
    TotalPages: int

    @field_validator("TotalPages")
    @classmethod
    def validate_total_pages(cls, value: int) -> int:
        if value < 0:
            raise ValueError("link total pages must be non-negative")
        return value


class _BingLinkDetailResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    Url: str = Field(min_length=1, max_length=2_048)
    AnchorText: str = Field(default="", max_length=2_048)


class _BingUrlLinksResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    Details: list[_BingLinkDetailResponse]
    TotalPages: int

    @field_validator("TotalPages")
    @classmethod
    def validate_total_pages(cls, value: int) -> int:
        if value < 0 or value > MAX_BING_LINK_PAGE:
            raise ValueError("Bing URL links total pages is out of range")
        return value


class _BingUrlInformationResponse(BaseModel):
    """The documented constrained fields returned by Bing's URL-info operation."""

    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)

    AnchorCount: int
    DiscoveryDate: str
    DocumentSize: int
    HttpStatus: int
    IsPage: bool
    LastCrawledDate: str
    TotalChildUrlCount: int
    Url: str

    @field_validator("AnchorCount", "DocumentSize", "TotalChildUrlCount")
    @classmethod
    def validate_non_negative_count(cls, value: int) -> int:
        if value < 0:
            raise ValueError("URL information count must be non-negative")
        return value

    @field_validator("HttpStatus")
    @classmethod
    def validate_http_status(cls, value: int) -> int:
        if value == _BING_URL_INFO_HTTP_STATUS_UNAVAILABLE:
            return value
        if value < MIN_HTTP_STATUS_CODE or value > MAX_HTTP_STATUS_CODE:
            raise ValueError("URL information HTTP status must be a valid HTTP status code")
        return value

    @field_validator("DiscoveryDate", "LastCrawledDate")
    @classmethod
    def validate_date(cls, value: str) -> str:
        _bing_traffic_day(value)
        return value

    @field_validator("Url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        if not value or len(value) > MAX_BING_STATS_LABEL_CHARS:
            raise ValueError("URL information URL has an invalid length")
        return value


class _BingKeywordStatsResponseRow(BaseModel):
    """The documented fields returned by Bing's keyword-statistics operation."""

    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)

    BroadImpressions: int
    Date: str
    Impressions: int
    Query: str

    @field_validator("BroadImpressions", "Impressions")
    @classmethod
    def validate_non_negative_count(cls, value: int) -> int:
        if value < 0:
            raise ValueError("keyword statistic must be non-negative")
        return value

    @field_validator("Date")
    @classmethod
    def validate_date(cls, value: str) -> str:
        _bing_traffic_day(value)
        return value

    @field_validator("Query")
    @classmethod
    def validate_query(cls, value: str) -> str:
        if not value or len(value) > MAX_BING_STATS_LABEL_CHARS:
            raise ValueError("keyword query has an invalid length")
        return value


class _BingRelatedKeywordResponseRow(BaseModel):
    """The documented fields returned by Bing's related-keywords operation."""

    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)

    BroadImpressions: int
    Impressions: int
    Query: str

    @field_validator("BroadImpressions", "Impressions")
    @classmethod
    def validate_non_negative_count(cls, value: int) -> int:
        if value < 0:
            raise ValueError("related keyword impression count must be non-negative")
        return value

    @field_validator("Query")
    @classmethod
    def validate_query(cls, value: str) -> str:
        if not value or len(value) > MAX_BING_STATS_LABEL_CHARS:
            raise ValueError("related keyword query has an invalid length")
        return value


class BingReadOperation(StrEnum):
    """Supported fixed Bing Webmaster read methods."""

    QUERY_STATS = "GetQueryStats"
    PAGE_STATS = "GetPageStats"
    PAGE_QUERY_STATS = "GetPageQueryStats"
    QUERY_PAGE_STATS = "GetQueryPageStats"
    RANK_AND_TRAFFIC_STATS = "GetRankAndTrafficStats"
    CRAWL_ISSUES = "GetCrawlIssues"
    CRAWL_STATS = "GetCrawlStats"
    FEEDS = "GetFeeds"
    URL_SUBMISSION_QUOTA = "GetUrlSubmissionQuota"
    LINK_COUNTS = "GetLinkCounts"
    URL_LINKS = "GetUrlLinks"
    KEYWORD_STATS = "GetKeywordStats"
    RELATED_KEYWORDS = "GetRelatedKeywords"
    URL_INFO = "GetUrlInfo"


class BingWebmasterClient:
    """Read one configured Bing account without caller-controlled origin or key."""

    provider = Provider.BING

    def __init__(
        self,
        boundary_policy: BoundaryPolicy,
        transport_factory: HttpTransportFactory = lambda: None,
    ) -> None:
        self._boundary_policy = boundary_policy
        self._transport_factory = transport_factory

    async def readiness(self, request: ProviderReadRequest) -> ProviderReadiness:
        """Verify configured Bing access by listing user sites."""
        await self.list_sites(request)
        return ProviderReadiness(
            account_id=request.account_id,
            provider=Provider.BING,
            available=True,
            detail="configured Bing Webmaster access is available",
        )

    async def list_sites(self, request: ProviderReadRequest) -> tuple[str, ...]:
        """Return every Bing site visible to the configured account credential."""
        account = self._boundary_policy.resolve_account(str(request.account_id), Provider.BING)
        payload = await self._request_json(
            "GetUserSites",
            self._load_api_key(account.credential),
            request.timeout_seconds,
            {},
        )
        entries = _json_list(payload)
        if entries is None:
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "Bing Webmaster returned an invalid site list",
            )
        if len(entries) > MAX_PROVIDER_ITEMS:
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "Bing Webmaster returned an invalid site list",
            )
        visible: list[str] = []
        for entry in entries:
            try:
                site = _BingSiteResponse.model_validate(entry)
            except ValidationError as error:
                raise ProviderOperationError(
                    ProviderFailureCode.INVALID_RESPONSE,
                    "Bing Webmaster returned an invalid site entry",
                ) from error
            visible.append(site.Url)
        return tuple(visible)

    async def read_site_data(
        self,
        request: ProviderReadRequest,
        site_url: str,
        operation: BingReadOperation,
        extra_parameters: dict[str, str] | None = None,
    ) -> object:
        """Read one enumerated Bing data set for one exact configured site."""
        account = self._boundary_policy.require_resource(
            str(request.account_id),
            Provider.BING,
            ResourceKind.BING_SITE,
            site_url,
        )
        parameters = {_SITE_URL_PARAMETER: site_url}
        if extra_parameters:
            parameters.update(extra_parameters)
        return await self._request_json(
            operation.value,
            self._load_api_key(account.credential),
            request.timeout_seconds,
            parameters,
        )

    async def read_rank_and_traffic_stats(
        self,
        request: ProviderReadRequest,
        site_url: str,
    ) -> tuple[BingTrafficRow, ...]:
        """Read Bing's fixed traffic report and expose only validated typed rows."""

        payload = await self.read_site_data(
            request,
            site_url,
            BingReadOperation.RANK_AND_TRAFFIC_STATS,
        )
        values = _json_list(payload)
        if values is None:
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "Bing Webmaster returned an invalid traffic report",
            )
        if len(values) > MAX_PROVIDER_ITEMS:
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "Bing Webmaster returned an invalid traffic report",
            )
        rows = tuple(_bing_traffic_row(value) for value in values)
        if len({row.day for row in rows}) != len(rows):
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "Bing Webmaster returned duplicate traffic days",
            )
        return rows

    async def read_query_stats(
        self,
        request: ProviderReadRequest,
        site_url: str,
    ) -> tuple[BingQueryStatsRow, ...]:
        """Read typed top-query statistics from Bing's fixed operation."""

        return await self._read_query_stats(request, site_url, BingReadOperation.QUERY_STATS)

    async def read_page_stats(
        self,
        request: ProviderReadRequest,
        site_url: str,
    ) -> tuple[BingQueryStatsRow, ...]:
        """Read typed top-page statistics from Bing's fixed operation."""

        return await self._read_query_stats(request, site_url, BingReadOperation.PAGE_STATS)

    async def read_query_page_stats(
        self,
        request: ProviderReadRequest,
        site_url: str,
        query: str,
    ) -> tuple[BingQueryStatsRow, ...]:
        """Read typed page statistics for one exact Bing query."""

        return await self._read_query_stats(
            request,
            site_url,
            BingReadOperation.QUERY_PAGE_STATS,
            {"query": query},
        )

    async def read_page_query_stats(
        self,
        request: ProviderReadRequest,
        site_url: str,
        page_url: str,
    ) -> tuple[BingQueryStatsRow, ...]:
        """Read typed query statistics for one configured Bing child page."""

        authorized_page_url = self._boundary_policy.require_bing_site_url(
            str(request.account_id),
            site_url,
            page_url,
        )
        return await self._read_query_stats(
            request,
            site_url,
            BingReadOperation.PAGE_QUERY_STATS,
            {"page": authorized_page_url},
        )

    async def read_url_submission_quota(
        self,
        request: ProviderReadRequest,
        site_url: str,
    ) -> BingUrlSubmissionQuota:
        """Read only typed remaining URL-submission quotas for one configured site."""

        payload = await self.read_site_data(
            request,
            site_url,
            BingReadOperation.URL_SUBMISSION_QUOTA,
        )
        try:
            quota = _BingUrlSubmissionQuotaResponse.model_validate(payload)
        except ValidationError as error:
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "Bing Webmaster returned an invalid URL submission quota",
            ) from error
        return BingUrlSubmissionQuota(quota.DailyQuota, quota.MonthlyQuota)

    async def read_crawl_issues(
        self,
        request: ProviderReadRequest,
        site_url: str,
    ) -> tuple[BingCrawlIssueRow, ...]:
        """Read and validate Bing's fixed crawl-issues report for one site."""

        payload = await self.read_site_data(request, site_url, BingReadOperation.CRAWL_ISSUES)
        values = _validated_bing_list(payload, "crawl issues")
        rows = tuple(_bing_crawl_issue_row(value) for value in values)
        if len({row.url for row in rows}) != len(rows):
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "Bing Webmaster returned duplicate crawl issue URLs",
            )
        return rows

    async def read_crawl_stats(
        self,
        request: ProviderReadRequest,
        site_url: str,
    ) -> tuple[BingCrawlStatsRow, ...]:
        """Read and validate Bing's fixed daily crawl-statistics report."""

        payload = await self.read_site_data(request, site_url, BingReadOperation.CRAWL_STATS)
        values = _validated_bing_list(payload, "crawl statistics")
        rows = tuple(_bing_crawl_stats_row(value) for value in values)
        if len({row.day for row in rows}) != len(rows):
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "Bing Webmaster returned duplicate crawl statistic days",
            )
        return rows

    async def read_feeds(
        self,
        request: ProviderReadRequest,
        site_url: str,
    ) -> tuple[BingFeedRow, ...]:
        """Read and validate Bing's fixed configured-feed report for one site."""

        payload = await self.read_site_data(request, site_url, BingReadOperation.FEEDS)
        values = _validated_bing_list(payload, "feeds")
        rows = tuple(_bing_feed_row(value) for value in values)
        if len({row.url for row in rows}) != len(rows):
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "Bing Webmaster returned duplicate feed URLs",
            )
        return rows

    async def read_link_counts(
        self,
        request: ProviderReadRequest,
        site_url: str,
        page: int,
    ) -> BingLinkCounts:
        """Read one typed fixed page of Bing inbound-link counts."""

        payload = await self.read_site_data(
            request,
            site_url,
            BingReadOperation.LINK_COUNTS,
            {"page": str(page)},
        )
        try:
            response = _BingLinkCountsResponse.model_validate(payload)
        except ValidationError as error:
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "Bing Webmaster returned an invalid link-count report",
            ) from error
        if len(response.Links) > MAX_PROVIDER_ITEMS:
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "Bing Webmaster returned an invalid link-count report",
            )
        links = tuple(_bing_link_count_row(row) for row in response.Links)
        if len({link.url for link in links}) != len(links):
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "Bing Webmaster returned duplicate link-count URLs",
            )
        return BingLinkCounts(links=links, total_pages=response.TotalPages)

    async def read_url_links(
        self,
        request: ProviderReadRequest,
        site_url: str,
        target_url: str,
        page: int,
    ) -> BingUrlLinks:
        """Read one typed page of inbound links for a configured child URL."""

        if page < 0 or page > MAX_BING_LINK_PAGE:
            raise ValueError("Bing URL links page is out of range")
        authorized_target_url = self._boundary_policy.require_bing_site_url(
            str(request.account_id),
            site_url,
            target_url,
        )
        payload = await self.read_site_data(
            request,
            site_url,
            BingReadOperation.URL_LINKS,
            {"link": authorized_target_url, "page": str(page)},
        )
        try:
            response = _BingUrlLinksResponse.model_validate(payload)
        except ValidationError as error:
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "Bing Webmaster returned an invalid URL links report",
            ) from error
        if len(response.Details) > MAX_PROVIDER_ITEMS:
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "Bing Webmaster returned an invalid URL links report",
            )
        links = tuple(_bing_link_detail(row) for row in response.Details)
        if len({(link.url, link.anchor_text) for link in links}) != len(links):
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "Bing Webmaster returned duplicate URL links",
            )
        return BingUrlLinks(links=links, total_pages=response.TotalPages)

    async def site_verification_for_onboarding(
        self,
        request: ProviderReadRequest,
        site_url: str,
    ) -> BingSiteVerification | None:
        """Read verification material for one site being added by the local operator."""

        account = self._boundary_policy.require_bing_onboarding_account(str(request.account_id))
        payload = await self._request_json(
            "GetUserSites",
            self._load_api_key(account.credential),
            request.timeout_seconds,
            {},
        )
        entries = _validated_bing_list(payload, "site list")
        for entry in entries:
            try:
                site = _BingSiteResponse.model_validate(entry)
            except ValidationError as error:
                raise ProviderOperationError(
                    ProviderFailureCode.INVALID_RESPONSE,
                    "Bing Webmaster returned an invalid site entry",
                ) from error
            if site.Url != site_url:
                continue
            code = (site.DnsVerificationCode or "").strip()
            if not code:
                raise ProviderOperationError(
                    ProviderFailureCode.INVALID_RESPONSE,
                    "Bing Webmaster did not return DNS verification material",
                )
            return BingSiteVerification(site.Url, code, bool(site.IsVerified))
        return None

    async def verify_site_for_onboarding(
        self,
        request: ProviderReadRequest,
        site_url: str,
    ) -> bool:
        """Ask Bing to verify one local-operator site after DNS materialization."""

        account = self._boundary_policy.require_bing_onboarding_account(str(request.account_id))
        response = await self._request_json(
            "VerifySite",
            self._load_api_key(account.credential),
            request.timeout_seconds,
            {},
            http_method="POST",
            request_payload={"siteUrl": site_url},
        )
        if not isinstance(response, bool):
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "Bing Webmaster returned an invalid verification response",
            )
        return response

    async def read_url_information(
        self,
        request: ProviderReadRequest,
        site_url: str,
        page_url: str,
    ) -> BingUrlInformation:
        """Read typed URL information for one exact configured Bing child URL."""

        authorized_page_url = self._boundary_policy.require_bing_site_url(
            str(request.account_id),
            site_url,
            page_url,
        )
        payload = await self.read_site_data(
            request,
            site_url,
            BingReadOperation.URL_INFO,
            {"url": authorized_page_url},
        )
        try:
            response = _BingUrlInformationResponse.model_validate(payload)
        except ValidationError as error:
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "Bing Webmaster returned invalid URL information",
            ) from error
        try:
            returned_url = self._boundary_policy.require_bing_site_url(
                str(request.account_id),
                site_url,
                response.Url,
            )
        except BoundaryDeniedError as error:
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "Bing Webmaster returned URL information outside the requested site",
            ) from error
        if returned_url != authorized_page_url:
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "Bing Webmaster returned URL information for a different URL",
            )
        return BingUrlInformation(
            url=returned_url,
            anchor_count=response.AnchorCount,
            discovery_date=_bing_traffic_day(response.DiscoveryDate),
            document_size=response.DocumentSize,
            http_status=(
                None
                if response.HttpStatus == _BING_URL_INFO_HTTP_STATUS_UNAVAILABLE
                else response.HttpStatus
            ),
            is_page=response.IsPage,
            last_crawled_date=_bing_traffic_day(response.LastCrawledDate),
            total_child_url_count=response.TotalChildUrlCount,
        )

    async def _read_query_stats(
        self,
        request: ProviderReadRequest,
        site_url: str,
        operation: BingReadOperation,
        parameters: dict[str, str] | None = None,
    ) -> tuple[BingQueryStatsRow, ...]:
        payload = await self.read_site_data(request, site_url, operation, parameters)
        values = _json_list(payload)
        if values is None or len(values) > MAX_PROVIDER_ITEMS:
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "Bing Webmaster returned an invalid query statistics report",
            )
        rows = tuple(_bing_query_stats_row(value) for value in values)
        unavailable_position_fields = sum(
            int(row.average_click_position is None) + int(row.average_impression_position is None)
            for row in rows
        )
        if unavailable_position_fields:
            log_event(
                _LOGGER,
                logging.INFO,
                "Bing Webmaster normalized unavailable average positions",
                operation=operation.value,
                unavailable_position_fields=unavailable_position_fields,
            )
        if len({(row.label, row.day) for row in rows}) != len(rows):
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "Bing Webmaster returned duplicate query statistics records",
            )
        return rows

    async def read_keyword_stats(
        self,
        request: ProviderReadRequest,
        query: str,
        country: str | None,
        language: str | None,
    ) -> tuple[BingKeywordStatsRow, ...]:
        """Read a strict fixed Bing keyword-statistics report."""

        account = self._boundary_policy.resolve_account(str(request.account_id), Provider.BING)
        parameters = _bing_keyword_parameters(query, country, language)
        payload = await self._request_json(
            BingReadOperation.KEYWORD_STATS.value,
            self._load_api_key(account.credential),
            request.timeout_seconds,
            parameters,
        )
        values = _validated_bing_list(payload, "keyword statistics")
        rows = tuple(_bing_keyword_stats_row(value) for value in values)
        if len({(row.day, row.query) for row in rows}) != len(rows):
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "Bing Webmaster returned duplicate keyword statistics rows",
            )
        return rows

    async def read_related_keywords(
        self,
        request: ProviderReadRequest,
        query: str,
        country: str | None,
        language: str | None,
        start_date: date,
        end_date: date,
    ) -> tuple[BingRelatedKeywordRow, ...]:
        """Read a strict fixed Bing related-keywords report for one date interval."""

        account = self._boundary_policy.resolve_account(str(request.account_id), Provider.BING)
        parameters = _bing_keyword_parameters(query, country, language)
        parameters.update({"startDate": start_date.isoformat(), "endDate": end_date.isoformat()})
        payload = await self._request_json(
            BingReadOperation.RELATED_KEYWORDS.value,
            self._load_api_key(account.credential),
            request.timeout_seconds,
            parameters,
        )
        values = _validated_bing_list(payload, "related keywords")
        rows = tuple(_bing_related_keyword_row(value) for value in values)
        if len({row.query for row in rows}) != len(rows):
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "Bing Webmaster returned duplicate related keywords",
            )
        return rows

    async def submit_url_batch(
        self,
        request: ProviderReadRequest,
        site_url: str,
        urls: tuple[str, ...],
    ) -> None:
        """Submit already-authorized URLs to one configured Bing site."""
        account = self._boundary_policy.require_resource(
            str(request.account_id),
            Provider.BING,
            ResourceKind.BING_SITE,
            site_url,
        )
        await self._request_json(
            "SubmitUrlBatch",
            self._load_api_key(account.credential),
            request.timeout_seconds,
            {},
            http_method="POST",
            request_payload={"siteUrl": site_url, "urlList": list(urls)},
        )

    async def submit_content(
        self,
        request: ProviderReadRequest,
        site_url: str,
        page_url: str,
        http_message: str,
        dynamic_serving: bool,
    ) -> None:
        """Submit one Rankrat-fetched page representation through Bing's fixed API."""

        account = self._boundary_policy.require_resource(
            str(request.account_id),
            Provider.BING,
            ResourceKind.BING_SITE,
            site_url,
        )
        await self._request_json(
            "SubmitContent",
            self._load_api_key(account.credential),
            request.timeout_seconds,
            {},
            http_method="POST",
            request_payload={
                "siteUrl": site_url,
                "url": page_url,
                "httpMessage": http_message,
                "dynamicServing": dynamic_serving,
            },
        )

    async def add_site(
        self,
        request: ProviderReadRequest,
        site_url: str,
    ) -> None:
        """Add one already-configured site through Bing's fixed JSON API method."""

        await self._mutate_site(request, site_url, "AddSite")

    async def add_site_for_onboarding(
        self,
        request: ProviderReadRequest,
        site_url: str,
    ) -> None:
        """Add one local-operator site before it enters the immutable boundary document."""

        account = self._boundary_policy.require_bing_onboarding_account(str(request.account_id))
        response = await self._request_json(
            "AddSite",
            self._load_api_key(account.credential),
            request.timeout_seconds,
            {},
            http_method="POST",
            request_payload={"siteUrl": site_url},
        )
        if response is not None:
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "Bing Webmaster returned an unexpected site mutation response",
            )

    async def remove_site(
        self,
        request: ProviderReadRequest,
        site_url: str,
    ) -> None:
        """Remove one already-configured site through Bing's fixed JSON API method."""

        await self._mutate_site(request, site_url, "RemoveSite")

    async def submit_feed(
        self,
        request: ProviderReadRequest,
        site_url: str,
        feed_url: str,
    ) -> None:
        """Submit one already-authorized sitemap or feed to a configured Bing site."""
        await self._mutate_feed(request, site_url, feed_url, "SubmitFeed")

    async def remove_feed(
        self,
        request: ProviderReadRequest,
        site_url: str,
        feed_url: str,
    ) -> None:
        """Remove one already-authorized sitemap or feed from a configured Bing site."""
        await self._mutate_feed(request, site_url, feed_url, "RemoveFeed")

    async def _mutate_feed(
        self,
        request: ProviderReadRequest,
        site_url: str,
        feed_url: str,
        operation: str,
    ) -> None:
        account = self._boundary_policy.require_resource(
            str(request.account_id),
            Provider.BING,
            ResourceKind.BING_SITE,
            site_url,
        )
        response = await self._request_json(
            operation,
            self._load_api_key(account.credential),
            request.timeout_seconds,
            {},
            http_method="POST",
            request_payload={"siteUrl": site_url, "feedUrl": feed_url},
        )
        if response is not None:
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "Bing Webmaster returned an unexpected feed mutation response",
            )

    async def _mutate_site(
        self,
        request: ProviderReadRequest,
        site_url: str,
        operation: str,
    ) -> None:
        account = self._boundary_policy.require_resource(
            str(request.account_id),
            Provider.BING,
            ResourceKind.BING_SITE,
            site_url,
        )
        response = await self._request_json(
            operation,
            self._load_api_key(account.credential),
            request.timeout_seconds,
            {},
            http_method="POST",
            request_payload={"siteUrl": site_url},
        )
        if response is not None:
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "Bing Webmaster returned an unexpected site mutation response",
            )

    async def _request_json(
        self,
        method: str,
        api_key: str,
        timeout_seconds: float,
        parameters: dict[str, str],
        *,
        http_method: str = "GET",
        request_payload: dict[str, object] | None = None,
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
                    http_method,
                    f"{_BING_API_ROOT}/{method}",
                    params={_API_KEY_PARAMETER: api_key, **parameters},
                    json=request_payload,
                ) as response,
            ):
                if response.status_code != 400:
                    self._raise_for_status(response)
                body = await self._read_bounded_body(response)
                self._raise_for_status(response, body)
        except httpx.TimeoutException as error:
            raise ProviderOperationError(
                ProviderFailureCode.TIMEOUT,
                "Bing Webmaster request timed out",
            ) from error
        except httpx.HTTPError as error:
            raise ProviderOperationError(
                ProviderFailureCode.UNAVAILABLE,
                "Bing Webmaster is unavailable",
            ) from error
        try:
            payload: object = json.loads(body)
        except json.JSONDecodeError as error:
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "Bing Webmaster returned invalid JSON",
            ) from error
        if (typed_payload := _json_object(payload)) is not None:
            return typed_payload.get("d", typed_payload)
        return payload

    @staticmethod
    def _load_api_key(path: Path) -> str:
        try:
            raw_key = path.read_bytes()[: _MAX_API_KEY_BYTES + 1]
            api_key = raw_key.decode("utf-8")
        except (OSError, UnicodeDecodeError) as error:
            raise ProviderOperationError(
                ProviderFailureCode.AUTHENTICATION,
                "Bing Webmaster API key is unavailable",
            ) from error
        normalized = api_key.rstrip("\r\n")
        if len(raw_key) > _MAX_API_KEY_BYTES or not _API_KEY_PATTERN.fullmatch(normalized):
            raise ProviderOperationError(
                ProviderFailureCode.AUTHENTICATION,
                "Bing Webmaster API key is unavailable",
            )
        return normalized

    @staticmethod
    def _raise_for_status(response: httpx.Response, body: bytes | None = None) -> None:
        if response.status_code in {401, 403}:
            raise ProviderOperationError(
                ProviderFailureCode.AUTHENTICATION,
                "Bing Webmaster request was rejected",
            )
        if response.status_code == 429:
            raise ProviderOperationError(
                ProviderFailureCode.RATE_LIMITED,
                "Bing Webmaster request was rate limited",
            )
        if response.status_code >= 500:
            raise ProviderOperationError(
                ProviderFailureCode.UNAVAILABLE,
                "Bing Webmaster is unavailable",
            )
        if response.status_code == 400 and _is_bing_not_authorized_error(body):
            raise ProviderOperationError(
                ProviderFailureCode.FORBIDDEN,
                "Bing Webmaster access to the selected site was denied",
            )
        if response.is_redirect or response.status_code >= 400:
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "Bing Webmaster returned an unexpected response",
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
                "Bing Webmaster response exceeds the allowed size",
            )
        body = bytearray()
        async for chunk in response.aiter_bytes():
            body.extend(chunk)
            if len(body) > MAX_PROVIDER_RESPONSE_BYTES:
                raise ProviderOperationError(
                    ProviderFailureCode.INVALID_RESPONSE,
                    "Bing Webmaster response exceeds the allowed size",
                )
        return bytes(body)


def _json_object(value: object) -> dict[str, object] | None:
    try:
        return _JSON_OBJECT_ADAPTER.validate_python(value)
    except ValidationError:
        return None


def _json_list(value: object) -> list[object] | None:
    try:
        return _JSON_LIST_ADAPTER.validate_python(value)
    except ValidationError:
        return None


def _is_bing_not_authorized_error(body: bytes | None) -> bool:
    if body is None:
        return False
    try:
        payload: object = json.loads(body)
    except json.JSONDecodeError:
        return False
    typed_payload = _json_object(payload)
    if typed_payload is None:
        return False
    return typed_payload.get(_BING_ERROR_CODE_FIELD) == _BING_NOT_AUTHORIZED_ERROR_CODE


def _bing_traffic_row(value: object) -> BingTrafficRow:
    try:
        row = _BingTrafficResponseRow.model_validate(value)
        return BingTrafficRow(
            day=_bing_traffic_day(row.Date),
            clicks=row.Clicks,
            impressions=row.Impressions,
        )
    except (ValidationError, ValueError) as error:
        raise ProviderOperationError(
            ProviderFailureCode.INVALID_RESPONSE,
            "Bing Webmaster returned an invalid traffic row",
        ) from error


def _bing_query_stats_row(value: object) -> BingQueryStatsRow:
    try:
        row = _BingQueryStatsResponseRow.model_validate(value)
        return BingQueryStatsRow(
            label=row.Query,
            day=_bing_traffic_day(row.Date),
            clicks=row.Clicks,
            impressions=row.Impressions,
            average_click_position=_bing_optional_average_position(row.AvgClickPosition),
            average_impression_position=_bing_optional_average_position(row.AvgImpressionPosition),
        )
    except (ValidationError, ValueError) as error:
        raise ProviderOperationError(
            ProviderFailureCode.INVALID_RESPONSE,
            "Bing Webmaster returned an invalid query statistics row",
        ) from error


def _bing_optional_average_position(value: float) -> float | None:
    if value == BING_UNKNOWN_AVERAGE_POSITION:
        return None
    return value


def _bing_crawl_issue_row(value: object) -> BingCrawlIssueRow:
    try:
        row = _BingCrawlIssueResponseRow.model_validate(value)
        return BingCrawlIssueRow(
            url=row.Url,
            http_code=row.HttpCode,
            issues=row.Issues,
            in_links=row.InLinks,
        )
    except ValidationError as error:
        raise ProviderOperationError(
            ProviderFailureCode.INVALID_RESPONSE,
            "Bing Webmaster returned an invalid crawl issue row",
        ) from error


def _bing_crawl_stats_row(value: object) -> BingCrawlStatsRow:
    try:
        row = _BingCrawlStatsResponseRow.model_validate(value)
        return BingCrawlStatsRow(
            day=_bing_traffic_day(row.Date),
            all_other_codes=row.AllOtherCodes,
            blocked_by_robots_txt=row.BlockedByRobotsTxt,
            code_2xx=row.Code2xx,
            code_301=row.Code301,
            code_302=row.Code302,
            code_4xx=row.Code4xx,
            code_5xx=row.Code5xx,
            contains_malware=row.ContainsMalware,
            connection_timeout=row.ConnectionTimeout,
            crawl_errors=row.CrawlErrors,
            crawled_pages=row.CrawledPages,
            dns_failures=row.DnsFailures,
            in_index=row.InIndex,
            in_links=row.InLinks,
        )
    except (ValidationError, ValueError) as error:
        raise ProviderOperationError(
            ProviderFailureCode.INVALID_RESPONSE,
            "Bing Webmaster returned an invalid crawl statistics row",
        ) from error


def _bing_feed_row(value: object) -> BingFeedRow:
    try:
        row = _BingFeedResponseRow.model_validate(value)
        return BingFeedRow(
            url=row.Url,
            feed_type=row.Type,
            status=row.Status,
            compressed=row.Compressed,
            file_size=row.FileSize,
            url_count=row.UrlCount,
            last_crawled=_bing_traffic_day(row.LastCrawled),
            submitted=_bing_traffic_day(row.Submitted),
        )
    except (ValidationError, ValueError) as error:
        raise ProviderOperationError(
            ProviderFailureCode.INVALID_RESPONSE,
            "Bing Webmaster returned an invalid feed row",
        ) from error


def _bing_link_count_row(value: _BingLinkCountResponseRow) -> BingLinkCountRow:
    return BingLinkCountRow(url=value.Url, count=value.Count)


def _bing_link_detail(value: _BingLinkDetailResponse) -> BingLinkDetail:
    parsed = urlparse(value.Url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ProviderOperationError(
            ProviderFailureCode.INVALID_RESPONSE,
            "Bing Webmaster returned an invalid backlink URL",
        )
    if parsed.username or parsed.password or len(value.Url) > MAX_BING_STATS_LABEL_CHARS:
        raise ProviderOperationError(
            ProviderFailureCode.INVALID_RESPONSE,
            "Bing Webmaster returned an invalid backlink URL",
        )
    return BingLinkDetail(url=value.Url, anchor_text=value.AnchorText)


def _bing_keyword_stats_row(value: object) -> BingKeywordStatsRow:
    try:
        row = _BingKeywordStatsResponseRow.model_validate(value)
        return BingKeywordStatsRow(
            query=row.Query,
            day=_bing_traffic_day(row.Date),
            impressions=row.Impressions,
            broad_impressions=row.BroadImpressions,
        )
    except (ValidationError, ValueError) as error:
        raise ProviderOperationError(
            ProviderFailureCode.INVALID_RESPONSE,
            "Bing Webmaster returned an invalid keyword statistics row",
        ) from error


def _bing_related_keyword_row(value: object) -> BingRelatedKeywordRow:
    try:
        row = _BingRelatedKeywordResponseRow.model_validate(value)
        return BingRelatedKeywordRow(
            query=row.Query,
            impressions=row.Impressions,
            broad_impressions=row.BroadImpressions,
        )
    except ValidationError as error:
        raise ProviderOperationError(
            ProviderFailureCode.INVALID_RESPONSE,
            "Bing Webmaster returned an invalid related keyword row",
        ) from error


def _bing_keyword_parameters(
    query: str,
    country: str | None,
    language: str | None,
) -> dict[str, str]:
    parameters = {"q": query}
    if country is not None:
        parameters["country"] = country
    if language is not None:
        parameters["language"] = language
    return parameters


def _validated_bing_list(payload: object, label: str) -> list[object]:
    values = _json_list(payload)
    if values is None or len(values) > MAX_PROVIDER_ITEMS:
        raise ProviderOperationError(
            ProviderFailureCode.INVALID_RESPONSE,
            f"Bing Webmaster returned an invalid {label} report",
        )
    return values


def _bing_traffic_day(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        pass
    matched = _BING_LEGACY_DATE_PATTERN.fullmatch(value)
    if matched is None:
        raise ValueError("Bing traffic day has an unsupported format")
    milliseconds = int(matched.group(1))
    offset = _bing_legacy_offset(matched.group(2))
    return (
        (datetime(1970, 1, 1, tzinfo=UTC) + timedelta(milliseconds=milliseconds))
        .astimezone(offset)
        .date()
    )


def _bing_legacy_offset(value: str | None) -> timezone:
    if value is None:
        return UTC
    sign = 1 if value[0] == "+" else -1
    hours = int(value[1:3])
    minutes = int(value[3:5])
    return timezone(sign * timedelta(hours=hours, minutes=minutes))
