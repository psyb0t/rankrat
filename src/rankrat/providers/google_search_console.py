"""Fixed-origin Google Search Console provider client for configured properties."""

from __future__ import annotations

import asyncio
import json
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from email import policy
from email.parser import BytesParser
from enum import StrEnum
from math import isfinite
from pathlib import Path
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from rankrat.constants import (
    GOOGLE_SEARCH_CONSOLE_READ_SCOPE,
    GOOGLE_SEARCH_CONSOLE_WRITE_SCOPE,
    MAX_GOOGLE_INDEXING_BATCH_PART_RESPONSE_BYTES,
    MAX_PROVIDER_ITEMS,
    MAX_PROVIDER_RESPONSE_BYTES,
    MAX_SEARCH_CONSOLE_TEXT_CHARS,
)
from rankrat.errors import BoundaryDeniedError
from rankrat.models.boundaries import Provider, ResourceKind
from rankrat.policy.boundaries import BoundaryPolicy
from rankrat.providers.base import (
    AccessTokenProvider,
    ProviderFailureCode,
    ProviderOperationError,
    ProviderReadiness,
    ProviderReadRequest,
)
from rankrat.providers.google_oauth import (
    GoogleOAuthTokenClient,
    GoogleOAuthTokenStore,
    load_google_oauth_client_configuration,
)

_SEARCH_CONSOLE_SITES_URL = "https://www.googleapis.com/webmasters/v3/sites"
_SEARCH_CONSOLE_SITE_URL = "https://www.googleapis.com/webmasters/v3/sites/{site_url}"
_SEARCH_CONSOLE_SITEMAPS_PATH = "/sitemaps"
_SEARCH_CONSOLE_ANALYTICS_PATH = "/searchAnalytics/query"
_URL_INSPECTION_URL = "https://searchconsole.googleapis.com/v1/urlInspection/index:inspect"
_GOOGLE_INDEXING_PUBLISH_URL = "https://indexing.googleapis.com/v3/urlNotifications:publish"
_GOOGLE_INDEXING_METADATA_URL = "https://indexing.googleapis.com/v3/urlNotifications/metadata"
_GOOGLE_INDEXING_BATCH_URL = "https://indexing.googleapis.com/batch"
_SEARCH_CONSOLE_READ_SCOPE = GOOGLE_SEARCH_CONSOLE_READ_SCOPE
SEARCH_CONSOLE_WRITE_SCOPE = GOOGLE_SEARCH_CONSOLE_WRITE_SCOPE
_AUTHORIZATION_HEADER = "Authorization"
_BEARER_PREFIX = "Bearer "
_INDEXING_BATCH_CONTENT_ID_PREFIX = "rankrat-"
_INDEXING_BATCH_RESPONSE_CONTENT_ID_PREFIX = f"response-{_INDEXING_BATCH_CONTENT_ID_PREFIX}"
_GOOGLE_API_INT64_MAX = 9_223_372_036_854_775_807
_GOOGLE_API_INT64_MAX_DIGITS = 19


def _parse_google_sitemap_counter(value: object) -> int | None:
    """Validate Google API int64 counters encoded as canonical decimal strings."""

    if value is None:
        return None
    if type(value) is int:
        counter = value
    elif (
        isinstance(value, str)
        and value.isascii()
        and value.isdecimal()
        and len(value) <= _GOOGLE_API_INT64_MAX_DIGITS
        and (value == "0" or not value.startswith("0"))
    ):
        counter = int(value)
    else:
        raise ValueError("Google Search Console sitemap counter must be an int64")

    if counter < 0 or counter > _GOOGLE_API_INT64_MAX:
        raise ValueError("Google Search Console sitemap counter is outside the int64 range")
    return counter


@dataclass(frozen=True, slots=True)
class GoogleIndexingBatchPartResponse:
    """One validated response part from Google's fixed batch endpoint."""

    index: int
    status_code: int


class SearchAnalyticsAggregationType(StrEnum):
    """Documented Search Console Search Analytics response aggregations."""

    AUTO = "auto"
    BY_PAGE = "byPage"
    BY_PROPERTY = "byProperty"


class SearchConsolePermissionLevel(StrEnum):
    """Documented permission levels for a Search Console property."""

    FULL_USER = "siteFullUser"
    OWNER = "siteOwner"
    RESTRICTED_USER = "siteRestrictedUser"
    UNVERIFIED_USER = "siteUnverifiedUser"


class SearchConsoleSitemapType(StrEnum):
    """Documented sitemap resource types."""

    ATOM_FEED = "atomFeed"
    NOT_SITEMAP = "notSitemap"
    PATTERN_SITEMAP = "patternSitemap"
    RSS_FEED = "rssFeed"
    SITEMAP = "sitemap"
    URL_LIST = "urlList"


class SearchConsoleSitemapContentType(StrEnum):
    """Documented content types reported for a Search Console sitemap."""

    ANDROID_APP = "androidApp"
    IMAGE = "image"
    IOS_APP = "iosApp"
    MOBILE = "mobile"
    NEWS = "news"
    PATTERN = "pattern"
    VIDEO = "video"
    WEB = "web"


@dataclass(frozen=True, slots=True)
class SearchConsoleSite:
    """One validated Search Console property and its permission level."""

    site_url: str
    permission_level: SearchConsolePermissionLevel


@dataclass(frozen=True, slots=True)
class SearchConsoleSitemapContent:
    """One content-type count reported for a sitemap."""

    content_type: SearchConsoleSitemapContentType
    submitted: int | None
    indexed: int | None


@dataclass(frozen=True, slots=True)
class SearchConsoleSitemap:
    """One validated sitemap record for an exact configured property."""

    path: str
    last_submitted: str | None
    is_pending: bool | None
    is_sitemaps_index: bool | None
    sitemap_type: SearchConsoleSitemapType | None
    last_downloaded: str | None
    warnings: int | None
    errors: int | None
    contents: tuple[SearchConsoleSitemapContent, ...]


@dataclass(frozen=True, slots=True)
class SearchConsoleSitemapList:
    """A bounded immutable sitemap collection."""

    sitemaps: tuple[SearchConsoleSitemap, ...]


@dataclass(frozen=True, slots=True)
class SearchConsoleIndexStatus:
    """The stable index-status fields returned for an inspected URL."""

    verdict: str | None
    coverage_state: str | None
    robots_txt_state: str | None
    indexing_state: str | None
    last_crawl_time: str | None
    page_fetch_state: str | None
    google_canonical: str | None
    user_canonical: str | None
    crawled_as: str | None
    referring_urls: tuple[str, ...]
    sitemaps: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SearchConsoleUrlInspection:
    """A bounded typed URL Inspection result."""

    inspection_result_link: str | None
    index_status: SearchConsoleIndexStatus | None


@dataclass(frozen=True, slots=True)
class SearchAnalyticsQuery:
    """A fixed-shape Search Analytics request built by the service layer."""

    start_date: str
    end_date: str
    dimensions: tuple[str, ...]
    search_type: str
    row_limit: int
    start_row: int
    filters: tuple[tuple[str, str, str], ...]

    def as_payload(self) -> dict[str, object]:
        """Return the sole allowed Search Analytics provider request shape."""

        payload: dict[str, object] = {
            "startDate": self.start_date,
            "endDate": self.end_date,
            "dimensions": list(self.dimensions),
            "type": self.search_type,
            "rowLimit": self.row_limit,
            "startRow": self.start_row,
        }
        if self.filters:
            payload["dimensionFilterGroups"] = [
                {
                    "groupType": "and",
                    "filters": [
                        {
                            "dimension": dimension,
                            "operator": operator,
                            "expression": expression,
                        }
                        for dimension, operator, expression in self.filters
                    ],
                }
            ]
        return payload


@dataclass(frozen=True, slots=True)
class SearchAnalyticsRow:
    """One validated Search Analytics row aligned to its query dimensions."""

    keys: tuple[str, ...]
    clicks: float
    impressions: float
    ctr: float
    position: float


@dataclass(frozen=True, slots=True)
class SearchAnalyticsReport:
    """A bounded typed Search Analytics response."""

    rows: tuple[SearchAnalyticsRow, ...]
    aggregation_type: SearchAnalyticsAggregationType | None


class _SearchAnalyticsRowResponse(BaseModel):
    """The bounded untrusted Search Analytics row fields Rankrat exposes."""

    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)

    keys: list[str] = Field(default_factory=list[str])
    clicks: float
    impressions: float
    ctr: float
    position: float

    @field_validator("keys")
    @classmethod
    def validate_keys(cls, value: list[str]) -> list[str]:
        if any(not key for key in value):
            raise ValueError("Search Analytics key must not be empty")
        return value

    @field_validator("clicks", "impressions", "ctr", "position", mode="before")
    @classmethod
    def validate_metric(cls, value: object) -> float:
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise ValueError("Search Analytics metric must be numeric")
        metric = float(value)
        if not isfinite(metric) or metric < 0:
            raise ValueError("Search Analytics metric must be finite and non-negative")
        return metric

    @field_validator("ctr")
    @classmethod
    def validate_ctr(cls, value: float) -> float:
        if value > 1:
            raise ValueError("Search Analytics CTR must not exceed one")
        return value


class _SearchAnalyticsResponse(BaseModel):
    """The constrained Search Analytics response fields Rankrat exposes."""

    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)

    rows: list[_SearchAnalyticsRowResponse] = Field(
        default_factory=list[_SearchAnalyticsRowResponse]
    )
    responseAggregationType: SearchAnalyticsAggregationType | None = None

    @field_validator("responseAggregationType", mode="before")
    @classmethod
    def validate_aggregation_type(
        cls,
        value: object,
    ) -> SearchAnalyticsAggregationType | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("Search Analytics aggregation type must be a string")
        try:
            return SearchAnalyticsAggregationType(value)
        except ValueError as error:
            raise ValueError("Search Analytics aggregation type is unsupported") from error


class _SearchConsoleSiteResponse(BaseModel):
    """The only site fields accepted from Search Console's sites resource."""

    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)

    siteUrl: str = Field(min_length=1, max_length=MAX_SEARCH_CONSOLE_TEXT_CHARS)
    permissionLevel: SearchConsolePermissionLevel

    @field_validator("permissionLevel", mode="before")
    @classmethod
    def validate_permission_level(cls, value: object) -> SearchConsolePermissionLevel:
        if not isinstance(value, str):
            raise ValueError("Search Console permission level must be a string")
        try:
            return SearchConsolePermissionLevel(value)
        except ValueError as error:
            raise ValueError("Search Console permission level is unsupported") from error


class _SearchConsoleSiteListResponse(BaseModel):
    """The bounded sites-list fields Rankrat consumes."""

    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)

    siteEntry: list[_SearchConsoleSiteResponse] = Field(
        default_factory=list[_SearchConsoleSiteResponse],
        max_length=MAX_PROVIDER_ITEMS,
    )


class _SearchConsoleSitemapContentResponse(BaseModel):
    """The bounded sitemap content counters Rankrat exposes."""

    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)

    type: SearchConsoleSitemapContentType
    submitted: int | None = Field(default=None, ge=0, le=_GOOGLE_API_INT64_MAX)
    indexed: int | None = Field(default=None, ge=0, le=_GOOGLE_API_INT64_MAX)

    @field_validator("type", mode="before")
    @classmethod
    def validate_content_type(cls, value: object) -> SearchConsoleSitemapContentType:
        if not isinstance(value, str):
            raise ValueError("Search Console sitemap content type must be a string")
        try:
            return SearchConsoleSitemapContentType(value)
        except ValueError as error:
            raise ValueError("Search Console sitemap content type is unsupported") from error

    @field_validator("submitted", "indexed", mode="before")
    @classmethod
    def parse_counter(cls, value: object) -> int | None:
        return _parse_google_sitemap_counter(value)


class _SearchConsoleSitemapResponse(BaseModel):
    """The bounded sitemap fields Rankrat exposes."""

    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)

    path: str = Field(min_length=1, max_length=MAX_SEARCH_CONSOLE_TEXT_CHARS)
    lastSubmitted: str | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_SEARCH_CONSOLE_TEXT_CHARS,
    )
    isPending: bool | None = None
    isSitemapsIndex: bool | None = None
    type: SearchConsoleSitemapType | None = None
    lastDownloaded: str | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_SEARCH_CONSOLE_TEXT_CHARS,
    )
    warnings: int | None = Field(default=None, ge=0, le=_GOOGLE_API_INT64_MAX)
    errors: int | None = Field(default=None, ge=0, le=_GOOGLE_API_INT64_MAX)
    contents: list[_SearchConsoleSitemapContentResponse] = Field(
        default_factory=list[_SearchConsoleSitemapContentResponse],
        max_length=MAX_PROVIDER_ITEMS,
    )

    @field_validator("type", mode="before")
    @classmethod
    def validate_sitemap_type(cls, value: object) -> SearchConsoleSitemapType | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("Search Console sitemap type must be a string")
        try:
            return SearchConsoleSitemapType(value)
        except ValueError as error:
            raise ValueError("Search Console sitemap type is unsupported") from error

    @field_validator("warnings", "errors", mode="before")
    @classmethod
    def parse_counter(cls, value: object) -> int | None:
        return _parse_google_sitemap_counter(value)


class _SearchConsoleSitemapListResponse(BaseModel):
    """The bounded sitemap-list fields Rankrat consumes."""

    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)

    sitemap: list[_SearchConsoleSitemapResponse] = Field(
        default_factory=list[_SearchConsoleSitemapResponse],
        max_length=MAX_PROVIDER_ITEMS,
    )


class _SearchConsoleIndexStatusResponse(BaseModel):
    """The stable index-status fields Rankrat exposes from URL Inspection."""

    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)

    verdict: str | None = Field(
        default=None, min_length=1, max_length=MAX_SEARCH_CONSOLE_TEXT_CHARS
    )
    coverageState: str | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_SEARCH_CONSOLE_TEXT_CHARS,
    )
    robotsTxtState: str | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_SEARCH_CONSOLE_TEXT_CHARS,
    )
    indexingState: str | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_SEARCH_CONSOLE_TEXT_CHARS,
    )
    lastCrawlTime: str | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_SEARCH_CONSOLE_TEXT_CHARS,
    )
    pageFetchState: str | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_SEARCH_CONSOLE_TEXT_CHARS,
    )
    googleCanonical: str | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_SEARCH_CONSOLE_TEXT_CHARS,
    )
    userCanonical: str | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_SEARCH_CONSOLE_TEXT_CHARS,
    )
    crawledAs: str | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_SEARCH_CONSOLE_TEXT_CHARS,
    )
    referringUrls: list[str] = Field(default_factory=list[str], max_length=MAX_PROVIDER_ITEMS)
    sitemap: list[str] = Field(default_factory=list[str], max_length=MAX_PROVIDER_ITEMS)

    @field_validator("referringUrls", "sitemap")
    @classmethod
    def validate_urls(cls, value: list[str]) -> list[str]:
        if any(not item or len(item) > MAX_SEARCH_CONSOLE_TEXT_CHARS for item in value):
            raise ValueError("URL Inspection returned an invalid URL list")
        return value


class _SearchConsoleUrlInspectionResultResponse(BaseModel):
    """The typed inner URL Inspection result."""

    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)

    inspectionResultLink: str | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_SEARCH_CONSOLE_TEXT_CHARS,
    )
    indexStatusResult: _SearchConsoleIndexStatusResponse | None = None


class _SearchConsoleUrlInspectionResponse(BaseModel):
    """The bounded URL Inspection response fields Rankrat exposes."""

    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)

    inspectionResult: _SearchConsoleUrlInspectionResultResponse


HttpTransportFactory = Callable[[], httpx.AsyncBaseTransport | None]


class GoogleConfiguredTokenProvider:
    """Refresh one exact configured Google OAuth account without fallback."""

    def __init__(
        self,
        boundary_policy: BoundaryPolicy,
        scopes: tuple[str, ...] = (_SEARCH_CONSOLE_READ_SCOPE,),
        oauth_token_client: GoogleOAuthTokenClient | None = None,
    ) -> None:
        if not scopes:
            raise ValueError("at least one Google OAuth scope is required")
        self._boundary_policy = boundary_policy
        self._scopes = scopes
        self._oauth_token_client = oauth_token_client or GoogleOAuthTokenClient()
        self._lock = asyncio.Lock()

    async def __call__(self, credential_path: Path) -> str:
        account = self._boundary_policy.resolve_google_oauth_account(credential_path)
        if account is None:
            raise ProviderOperationError(
                ProviderFailureCode.AUTHENTICATION,
                "Google OAuth account is not configured for this credential path",
            )
        token_file = account.oauth_token_file
        if token_file is None:
            raise ProviderOperationError(
                ProviderFailureCode.AUTHENTICATION,
                "Google OAuth account is missing a refresh token path",
            )

        async with self._lock:
            configuration = load_google_oauth_client_configuration(account.credential)
            token_store = GoogleOAuthTokenStore(
                token_file,
                account.id,
                configuration.client_id,
                self._scopes,
            )
            record = token_store.load()
            access_token, refreshed_record = await self._oauth_token_client.refresh(
                configuration,
                record,
            )
            if refreshed_record != record:
                token_store.write(refreshed_record)
            return access_token


class GoogleSearchConsoleClient:
    """Access explicit or account-discovered Search Console properties through fixed endpoints."""

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

    async def readiness(self, request: ProviderReadRequest) -> ProviderReadiness:
        """Check configured access without returning upstream payloads."""

        await self.list_sites(request)
        return ProviderReadiness(
            account_id=request.account_id,
            provider=Provider.GOOGLE,
            available=True,
            detail="configured Google Search Console access is available",
        )

    async def list_sites(self, request: ProviderReadRequest) -> tuple[str, ...]:
        """Return configured sites or the complete OAuth-visible inventory in discovery mode."""

        account = self._boundary_policy.resolve_account(
            str(request.account_id),
            Provider.GOOGLE,
        )
        try:
            token = await self._access_token_provider(account.credential)
        except ProviderOperationError:
            raise
        except Exception as error:
            # Token providers can wrap several auth backends; their detail is never safe to surface.
            raise ProviderOperationError(
                ProviderFailureCode.AUTHENTICATION,
                "Google Search Console authentication failed",
            ) from error
        payload = await self._request_json(
            "GET",
            _SEARCH_CONSOLE_SITES_URL,
            token,
            request.timeout_seconds,
        )
        sites = _search_console_site_list(payload)
        if account.google_account_discovery:
            return tuple(site.site_url for site in sites)

        allowed = set(account.search_console_sites)
        visible: list[str] = []
        for site in sites:
            if site.site_url not in allowed:
                continue
            self._boundary_policy.require_google_read_resource(
                str(request.account_id),
                ResourceKind.SEARCH_CONSOLE_SITE,
                site.site_url,
            )
            visible.append(site.site_url)
        return tuple(visible)

    async def search_analytics(
        self,
        request: ProviderReadRequest,
        site_url: str,
        query: SearchAnalyticsQuery,
    ) -> SearchAnalyticsReport:
        """Run a bounded analytics query for one exact configured property."""
        self._boundary_policy.require_google_read_resource(
            str(request.account_id),
            ResourceKind.SEARCH_CONSOLE_SITE,
            site_url,
        )
        token = await self._token_for_account(str(request.account_id))
        payload = await self._request_json(
            "POST",
            f"{self._site_url(site_url)}{_SEARCH_CONSOLE_ANALYTICS_PATH}",
            token,
            request.timeout_seconds,
            query.as_payload(),
        )
        return _search_analytics_report(payload, query)

    async def get_site(
        self,
        request: ProviderReadRequest,
        site_url: str,
    ) -> SearchConsoleSite:
        """Return one exact configured property through the documented fixed path."""

        self._boundary_policy.require_google_read_resource(
            str(request.account_id),
            ResourceKind.SEARCH_CONSOLE_SITE,
            site_url,
        )
        token = await self._token_for_account(str(request.account_id))
        payload = await self._request_json(
            "GET",
            self._site_url(site_url),
            token,
            request.timeout_seconds,
        )
        site = _search_console_site(payload)
        if site.site_url != site_url:
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "Google Search Console returned a mismatched site",
            )
        return site

    async def add_site(
        self,
        request: ProviderReadRequest,
        site_url: str,
    ) -> None:
        """Add one pre-authorized configured property using the write-scoped client."""

        self._boundary_policy.require_resource(
            str(request.account_id),
            Provider.GOOGLE,
            ResourceKind.SEARCH_CONSOLE_SITE,
            site_url,
        )
        token = await self._token_for_account(str(request.account_id))
        await self._request_empty(
            "PUT",
            self._site_url(site_url),
            token,
            request.timeout_seconds,
        )

    async def add_site_for_onboarding(
        self,
        request: ProviderReadRequest,
        site_url: str,
    ) -> None:
        """Add one local-operator site before it enters the immutable boundary document."""

        self._boundary_policy.require_google_onboarding_account(str(request.account_id))
        token = await self._token_for_account(str(request.account_id))
        await self._request_empty(
            "PUT",
            self._site_url(site_url),
            token,
            request.timeout_seconds,
        )

    async def delete_site(
        self,
        request: ProviderReadRequest,
        site_url: str,
    ) -> None:
        """Delete one pre-authorized configured property using the write-scoped client."""

        self._boundary_policy.require_resource(
            str(request.account_id),
            Provider.GOOGLE,
            ResourceKind.SEARCH_CONSOLE_SITE,
            site_url,
        )
        token = await self._token_for_account(str(request.account_id))
        await self._request_empty(
            "DELETE",
            self._site_url(site_url),
            token,
            request.timeout_seconds,
        )

    async def list_sitemaps(
        self,
        request: ProviderReadRequest,
        site_url: str,
    ) -> SearchConsoleSitemapList:
        """List sitemaps for one exact configured Search Console property."""
        self._boundary_policy.require_google_read_resource(
            str(request.account_id),
            ResourceKind.SEARCH_CONSOLE_SITE,
            site_url,
        )
        token = await self._token_for_account(str(request.account_id))
        payload = await self._request_json(
            "GET",
            f"{self._site_url(site_url)}{_SEARCH_CONSOLE_SITEMAPS_PATH}",
            token,
            request.timeout_seconds,
        )
        return self._search_console_sitemap_list(request, site_url, payload)

    async def get_sitemap(
        self,
        request: ProviderReadRequest,
        site_url: str,
        sitemap_url: str,
    ) -> SearchConsoleSitemap:
        """Get one already-authorized sitemap through one fixed API path."""

        self._boundary_policy.require_google_read_resource(
            str(request.account_id),
            ResourceKind.SEARCH_CONSOLE_SITE,
            site_url,
        )
        token = await self._token_for_account(str(request.account_id))
        payload = await self._request_json(
            "GET",
            self._sitemap_url(site_url, sitemap_url),
            token,
            request.timeout_seconds,
        )
        sitemap = self._search_console_sitemap(request, site_url, payload)
        if sitemap.path != sitemap_url:
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "Google Search Console returned a mismatched sitemap",
            )
        return sitemap

    async def submit_sitemap(
        self,
        request: ProviderReadRequest,
        site_url: str,
        sitemap_url: str,
    ) -> None:
        """Submit one already-authorized sitemap to one fixed Search Console path."""

        self._boundary_policy.require_resource(
            str(request.account_id),
            Provider.GOOGLE,
            ResourceKind.SEARCH_CONSOLE_SITE,
            site_url,
        )
        token = await self._token_for_account(str(request.account_id))
        await self._request_empty(
            "PUT",
            self._sitemap_url(site_url, sitemap_url),
            token,
            request.timeout_seconds,
        )

    async def delete_sitemap(
        self,
        request: ProviderReadRequest,
        site_url: str,
        sitemap_url: str,
    ) -> None:
        """Delete one already-authorized sitemap through one fixed API path."""

        self._boundary_policy.require_resource(
            str(request.account_id),
            Provider.GOOGLE,
            ResourceKind.SEARCH_CONSOLE_SITE,
            site_url,
        )
        token = await self._token_for_account(str(request.account_id))
        await self._request_empty(
            "DELETE",
            self._sitemap_url(site_url, sitemap_url),
            token,
            request.timeout_seconds,
        )

    async def inspect_url(
        self,
        request: ProviderReadRequest,
        site_url: str,
        inspection_url: str,
    ) -> SearchConsoleUrlInspection:
        """Inspect one URL under an exact configured Search Console property."""
        self._boundary_policy.require_google_read_resource(
            str(request.account_id),
            ResourceKind.SEARCH_CONSOLE_SITE,
            site_url,
        )
        token = await self._token_for_account(str(request.account_id))
        payload = await self._request_json(
            "POST",
            _URL_INSPECTION_URL,
            token,
            request.timeout_seconds,
            {"inspectionUrl": inspection_url, "siteUrl": site_url},
        )
        return _search_console_url_inspection(payload)

    def _search_console_sitemap_list(
        self,
        request: ProviderReadRequest,
        site_url: str,
        payload: object,
    ) -> SearchConsoleSitemapList:
        try:
            response = _SearchConsoleSitemapListResponse.model_validate(payload)
            return SearchConsoleSitemapList(
                tuple(
                    self._search_console_sitemap(request, site_url, sitemap)
                    for sitemap in response.sitemap
                )
            )
        except (ValidationError, ValueError) as error:
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "Google Search Console returned an invalid sitemap list",
            ) from error

    def _search_console_sitemap(
        self,
        request: ProviderReadRequest,
        site_url: str,
        payload: object,
    ) -> SearchConsoleSitemap:
        try:
            response = _SearchConsoleSitemapResponse.model_validate(payload)
            path = self._boundary_policy.require_google_search_console_read_url(
                str(request.account_id),
                site_url,
                response.path,
            )
            return SearchConsoleSitemap(
                path=path,
                last_submitted=response.lastSubmitted,
                is_pending=response.isPending,
                is_sitemaps_index=response.isSitemapsIndex,
                sitemap_type=response.type,
                last_downloaded=response.lastDownloaded,
                warnings=response.warnings,
                errors=response.errors,
                contents=tuple(
                    SearchConsoleSitemapContent(
                        content_type=content.type,
                        submitted=content.submitted,
                        indexed=content.indexed,
                    )
                    for content in response.contents
                ),
            )
        except (BoundaryDeniedError, ValidationError, ValueError) as error:
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "Google Search Console returned an invalid sitemap",
            ) from error

    async def _token_for_account(self, account_id: str) -> str:
        account = self._boundary_policy.resolve_account(account_id, Provider.GOOGLE)
        try:
            return await self._access_token_provider(account.credential)
        except ProviderOperationError:
            raise
        except Exception as error:
            raise ProviderOperationError(
                ProviderFailureCode.AUTHENTICATION,
                "Google Search Console authentication failed",
            ) from error

    async def publish_indexing_notification(
        self,
        account_id: str,
        url: str,
        notification_type: str,
        timeout_seconds: float,
    ) -> dict[str, object]:
        """Publish through the one fixed Google Indexing API endpoint."""

        token = await self._token_for_account(account_id)
        return await self._request_json(
            "POST",
            _GOOGLE_INDEXING_PUBLISH_URL,
            token,
            timeout_seconds,
            {"url": url, "type": notification_type},
        )

    async def get_indexing_notification_metadata(
        self,
        account_id: str,
        url: str,
        timeout_seconds: float,
    ) -> dict[str, object]:
        """Get notification receipt metadata from the one documented Indexing endpoint."""

        token = await self._token_for_account(account_id)
        metadata_url = f"{_GOOGLE_INDEXING_METADATA_URL}?url={quote(url, safe='')}"
        return await self._request_json("GET", metadata_url, token, timeout_seconds)

    async def publish_indexing_notification_batch(
        self,
        account_id: str,
        notifications: tuple[tuple[str, str], ...],
        timeout_seconds: float,
    ) -> tuple[GoogleIndexingBatchPartResponse, ...]:
        """Publish validated Indexing notifications through Google's multipart batch API."""

        token = await self._token_for_account(account_id)
        boundary = f"rankrat-{secrets.token_hex(16)}"
        request_body = self._build_indexing_batch_body(boundary, notifications)
        content_type, response_body = await self._request_indexing_batch(
            token,
            boundary,
            request_body,
            timeout_seconds,
        )
        return self._parse_indexing_batch_response(
            content_type,
            response_body,
            len(notifications),
        )

    @staticmethod
    def _build_indexing_batch_body(
        boundary: str,
        notifications: tuple[tuple[str, str], ...],
    ) -> bytes:
        parts: list[bytes] = []
        for index, (url, notification_type) in enumerate(notifications):
            payload = json.dumps(
                {"url": url, "type": notification_type},
                separators=(",", ":"),
            ).encode("utf-8")
            parts.extend(
                (
                    f"--{boundary}\r\n".encode(),
                    b"Content-Type: application/http\r\n",
                    b"Content-Transfer-Encoding: binary\r\n",
                    f"Content-ID: <{_INDEXING_BATCH_CONTENT_ID_PREFIX}{index}>\r\n\r\n".encode(),
                    b"POST /v3/urlNotifications:publish HTTP/1.1\r\n",
                    b"Content-Type: application/json\r\n\r\n",
                    payload,
                    b"\r\n",
                )
            )
        parts.append(f"--{boundary}--\r\n".encode())
        return b"".join(parts)

    async def _request_indexing_batch(
        self,
        token: str,
        boundary: str,
        request_body: bytes,
        timeout_seconds: float,
    ) -> tuple[str, bytes]:
        try:
            async with (
                httpx.AsyncClient(
                    transport=self._transport_factory(),
                    trust_env=False,
                    follow_redirects=False,
                    timeout=httpx.Timeout(timeout_seconds),
                ) as client,
                client.stream(
                    "POST",
                    _GOOGLE_INDEXING_BATCH_URL,
                    headers={
                        _AUTHORIZATION_HEADER: f"{_BEARER_PREFIX}{token}",
                        "Content-Type": f"multipart/mixed; boundary={boundary}",
                    },
                    content=request_body,
                ) as response,
            ):
                self._raise_for_status(response)
                content_type = response.headers.get("content-type", "")
                if not content_type or "\r" in content_type or "\n" in content_type:
                    raise ProviderOperationError(
                        ProviderFailureCode.INVALID_RESPONSE,
                        "Google Indexing batch returned an invalid content type",
                    )
                response_body = await self._read_bounded_body(response)
        except ProviderOperationError:
            raise
        except httpx.TimeoutException as error:
            raise ProviderOperationError(
                ProviderFailureCode.TIMEOUT,
                "Google Indexing batch request timed out",
            ) from error
        except httpx.HTTPError as error:
            raise ProviderOperationError(
                ProviderFailureCode.UNAVAILABLE,
                "Google Indexing batch is unavailable",
            ) from error
        return content_type, response_body

    @classmethod
    def _parse_indexing_batch_response(
        cls,
        content_type: str,
        response_body: bytes,
        expected_parts: int,
    ) -> tuple[GoogleIndexingBatchPartResponse, ...]:
        message = BytesParser(policy=policy.default).parsebytes(
            f"MIME-Version: 1.0\r\nContent-Type: {content_type}\r\n\r\n".encode("ascii")
            + response_body
        )
        if message.defects or message.get_content_type() != "multipart/mixed":
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "Google Indexing batch returned an invalid multipart response",
            )
        parts = tuple(message.iter_parts())
        if len(parts) != expected_parts:
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "Google Indexing batch returned an incomplete response",
            )

        responses: dict[int, GoogleIndexingBatchPartResponse] = {}
        for part in parts:
            if part.get_content_type() != "application/http":
                raise ProviderOperationError(
                    ProviderFailureCode.INVALID_RESPONSE,
                    "Google Indexing batch returned an invalid response part",
                )
            index = cls._batch_response_index(part.get("Content-ID"), expected_parts)
            if index in responses:
                raise ProviderOperationError(
                    ProviderFailureCode.INVALID_RESPONSE,
                    "Google Indexing batch returned duplicate response parts",
                )
            payload = part.get_payload(decode=True)
            if (
                not isinstance(payload, bytes)
                or len(payload) > MAX_GOOGLE_INDEXING_BATCH_PART_RESPONSE_BYTES
            ):
                raise ProviderOperationError(
                    ProviderFailureCode.INVALID_RESPONSE,
                    "Google Indexing batch returned an oversized response part",
                )
            status_code = cls._batch_part_status(payload)
            responses[index] = GoogleIndexingBatchPartResponse(index, status_code)

        return tuple(responses[index] for index in range(expected_parts))

    @staticmethod
    def _batch_response_index(content_id: str | None, expected_parts: int) -> int:
        if content_id is None:
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "Google Indexing batch response omitted a content ID",
            )
        normalized = content_id.strip()
        if not normalized.startswith("<") or not normalized.endswith(">"):
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "Google Indexing batch returned an invalid content ID",
            )
        value = normalized[1:-1]
        if not value.startswith(_INDEXING_BATCH_RESPONSE_CONTENT_ID_PREFIX):
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "Google Indexing batch returned an unknown content ID",
            )
        suffix = value.removeprefix(_INDEXING_BATCH_RESPONSE_CONTENT_ID_PREFIX)
        if not suffix.isascii() or not suffix.isdecimal():
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "Google Indexing batch returned an invalid content ID",
            )
        index = int(suffix)
        if index >= expected_parts:
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "Google Indexing batch returned an unknown content ID",
            )
        return index

    @staticmethod
    def _batch_part_status(payload: bytes) -> int:
        header_block, separator, response_body = payload.partition(b"\r\n\r\n")
        if not separator or len(response_body) > MAX_GOOGLE_INDEXING_BATCH_PART_RESPONSE_BYTES:
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "Google Indexing batch returned an invalid response part",
            )
        status_line, _, headers = header_block.partition(b"\r\n")
        del headers
        fields = status_line.split(b" ", maxsplit=2)
        if (
            len(fields) < 2
            or fields[0] not in (b"HTTP/1.0", b"HTTP/1.1", b"HTTP/2")
            or len(fields[1]) != 3
            or not fields[1].isdigit()
        ):
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "Google Indexing batch returned an invalid response status",
            )
        status_code = int(fields[1])
        if not 100 <= status_code <= 599:
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "Google Indexing batch returned an invalid response status",
            )
        if 200 <= status_code < 300:
            try:
                parsed = json.loads(response_body)
            except json.JSONDecodeError as error:
                raise ProviderOperationError(
                    ProviderFailureCode.INVALID_RESPONSE,
                    "Google Indexing batch returned invalid JSON",
                ) from error
            if not isinstance(parsed, dict):
                raise ProviderOperationError(
                    ProviderFailureCode.INVALID_RESPONSE,
                    "Google Indexing batch returned an invalid response part",
                )
        return status_code

    @staticmethod
    def _site_url(site_url: str) -> str:
        return _SEARCH_CONSOLE_SITE_URL.format(site_url=quote(site_url, safe=""))

    @classmethod
    def _sitemap_url(cls, site_url: str, sitemap_url: str) -> str:
        encoded_sitemap_url = quote(sitemap_url, safe="")
        return f"{cls._site_url(site_url)}{_SEARCH_CONSOLE_SITEMAPS_PATH}/{encoded_sitemap_url}"

    async def _request_empty(
        self,
        method: str,
        url: str,
        token: str,
        timeout_seconds: float,
    ) -> None:
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
                ) as response,
            ):
                self._raise_for_status(response)
                if response.status_code != 204:
                    raise ProviderOperationError(
                        ProviderFailureCode.INVALID_RESPONSE,
                        "Google Search Console returned an unexpected response",
                    )
                if await self._read_bounded_body(response):
                    raise ProviderOperationError(
                        ProviderFailureCode.INVALID_RESPONSE,
                        "Google Search Console returned an unexpected response",
                    )
        except ProviderOperationError:
            raise
        except httpx.TimeoutException as error:
            raise ProviderOperationError(
                ProviderFailureCode.TIMEOUT,
                "Google Search Console request timed out",
            ) from error
        except httpx.HTTPError as error:
            raise ProviderOperationError(
                ProviderFailureCode.UNAVAILABLE,
                "Google Search Console is unavailable",
            ) from error

    async def _request_json(
        self,
        method: str,
        url: str,
        token: str,
        timeout_seconds: float,
        payload: dict[str, object] | None = None,
    ) -> dict[str, object]:
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
                ) as response,
            ):
                self._raise_for_status(response)
                body = await self._read_bounded_body(response)
        except httpx.TimeoutException as error:
            raise ProviderOperationError(
                ProviderFailureCode.TIMEOUT,
                "Google Search Console request timed out",
            ) from error
        except httpx.HTTPError as error:
            raise ProviderOperationError(
                ProviderFailureCode.UNAVAILABLE,
                "Google Search Console is unavailable",
            ) from error

        try:
            payload = json.loads(body)
        except json.JSONDecodeError as error:
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "Google Search Console returned invalid JSON",
            ) from error
        if not isinstance(payload, dict):
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "Google Search Console returned an invalid response",
            )
        return payload

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
                "Google Search Console request was rejected",
            )
        if response.status_code >= 500:
            raise ProviderOperationError(
                ProviderFailureCode.UNAVAILABLE,
                "Google Search Console is unavailable",
            )
        if response.is_redirect or response.status_code >= 400:
            raise ProviderOperationError(
                ProviderFailureCode.INVALID_RESPONSE,
                "Google Search Console returned an unexpected response",
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
                "Google Search Console response exceeds the allowed size",
            )

        body = bytearray()
        async for chunk in response.aiter_bytes():
            body.extend(chunk)
            if len(body) > MAX_PROVIDER_RESPONSE_BYTES:
                raise ProviderOperationError(
                    ProviderFailureCode.INVALID_RESPONSE,
                    "Google Search Console response exceeds the allowed size",
                )
        return bytes(body)


def _search_analytics_report(
    payload: object,
    query: SearchAnalyticsQuery,
) -> SearchAnalyticsReport:
    try:
        response = _SearchAnalyticsResponse.model_validate(payload)
        if len(response.rows) > query.row_limit:
            raise ValueError("Search Analytics response exceeds the requested row limit")
        rows = tuple(
            SearchAnalyticsRow(
                keys=tuple(row.keys),
                clicks=row.clicks,
                impressions=row.impressions,
                ctr=row.ctr,
                position=row.position,
            )
            for row in response.rows
        )
        if any(len(row.keys) != len(query.dimensions) for row in rows):
            raise ValueError("Search Analytics row has a mismatched key count")
        if len({row.keys for row in rows}) != len(rows):
            raise ValueError("Search Analytics response repeats a row key")
        return SearchAnalyticsReport(rows, response.responseAggregationType)
    except (ValidationError, ValueError) as error:
        raise ProviderOperationError(
            ProviderFailureCode.INVALID_RESPONSE,
            "Google Search Console returned an invalid Search Analytics report",
        ) from error


def _search_console_site(payload: object) -> SearchConsoleSite:
    try:
        response = _SearchConsoleSiteResponse.model_validate(payload)
        return SearchConsoleSite(response.siteUrl, response.permissionLevel)
    except ValidationError as error:
        raise ProviderOperationError(
            ProviderFailureCode.INVALID_RESPONSE,
            "Google Search Console returned an invalid site",
        ) from error


def _search_console_site_list(payload: object) -> tuple[SearchConsoleSite, ...]:
    try:
        response = _SearchConsoleSiteListResponse.model_validate(payload)
        sites = tuple(
            SearchConsoleSite(site.siteUrl, site.permissionLevel) for site in response.siteEntry
        )
        if len({site.site_url for site in sites}) != len(sites):
            raise ValueError("Google Search Console returned duplicate sites")
        return sites
    except (ValidationError, ValueError) as error:
        raise ProviderOperationError(
            ProviderFailureCode.INVALID_RESPONSE,
            "Google Search Console returned an invalid site list",
        ) from error


def _search_console_url_inspection(payload: object) -> SearchConsoleUrlInspection:
    try:
        response = _SearchConsoleUrlInspectionResponse.model_validate(payload)
        index_status = response.inspectionResult.indexStatusResult
        typed_index_status = None
        if index_status is not None:
            typed_index_status = SearchConsoleIndexStatus(
                verdict=index_status.verdict,
                coverage_state=index_status.coverageState,
                robots_txt_state=index_status.robotsTxtState,
                indexing_state=index_status.indexingState,
                last_crawl_time=index_status.lastCrawlTime,
                page_fetch_state=index_status.pageFetchState,
                google_canonical=index_status.googleCanonical,
                user_canonical=index_status.userCanonical,
                crawled_as=index_status.crawledAs,
                referring_urls=tuple(index_status.referringUrls),
                sitemaps=tuple(index_status.sitemap),
            )
        return SearchConsoleUrlInspection(
            inspection_result_link=response.inspectionResult.inspectionResultLink,
            index_status=typed_index_status,
        )
    except ValidationError as error:
        raise ProviderOperationError(
            ProviderFailureCode.INVALID_RESPONSE,
            "Google Search Console returned an invalid URL Inspection result",
        ) from error
