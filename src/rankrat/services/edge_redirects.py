"""Provider-neutral edge redirect operations backed by configured DNS providers."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit

from rankrat.constants import (
    DEFAULT_PROVIDER_TIMEOUT_SECONDS,
    MAX_EDGE_REDIRECT_SOURCE_PATH_CHARS,
)
from rankrat.errors import InputLimitError
from rankrat.models.boundaries import normalize_public_https_root_url, normalize_public_https_url
from rankrat.providers.base import AccountId, ProviderReadRequest
from rankrat.providers.cloudflare import CloudflareDnsClient
from rankrat.providers.cloudflare_performance import (
    CloudflareEdgeRedirect,
    CloudflareEdgeRedirectReceipt,
    CloudflarePerformanceClient,
    CloudflareRedirectStatus,
)


@dataclass(frozen=True, slots=True)
class EdgeRedirectListRequest:
    """List redirects for one public HTTPS source site through its DNS account."""

    account_id: str
    site_url: str
    timeout_seconds: float = DEFAULT_PROVIDER_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "site_url",
            normalize_public_https_root_url(self.site_url, "site_url"),
        )


@dataclass(frozen=True, slots=True)
class EdgeRedirectUpsertRequest(EdgeRedirectListRequest):
    """Create or update one explicit source-path redirect to any public HTTPS target."""

    source_path: str = "/"
    target_url: str = ""
    status_code: CloudflareRedirectStatus = CloudflareRedirectStatus.MOVED_PERMANENTLY
    preserve_query_string: bool = True

    def __post_init__(self) -> None:
        super().__post_init__()
        _validate_source_path(self.source_path)
        object.__setattr__(
            self,
            "target_url",
            normalize_public_https_url(self.target_url, "target_url"),
        )


@dataclass(frozen=True, slots=True)
class EdgeRedirectDeleteRequest(EdgeRedirectListRequest):
    """Delete one previously listed provider-managed redirect by its opaque rule ID."""

    rule_id: str = ""


class EdgeRedirectService:
    """Use a provider-neutral site boundary with Cloudflare's first DNS adapter."""

    def __init__(
        self,
        dns_client: CloudflareDnsClient,
        performance_client: CloudflarePerformanceClient,
    ) -> None:
        self._dns_client = dns_client
        self._performance_client = performance_client

    async def list(self, request: EdgeRedirectListRequest) -> tuple[CloudflareEdgeRedirect, ...]:
        """List only redirects Rankrat owns for the source site's resolved DNS zone."""

        zone_id = await self._zone_id(request)
        return await self._performance_client.list_edge_redirects(
            _provider_request(request),
            zone_id,
        )

    async def upsert(
        self,
        request: EdgeRedirectUpsertRequest,
    ) -> CloudflareEdgeRedirectReceipt:
        """Apply one provider-neutral redirect through the resolved DNS-zone adapter."""

        zone_id = await self._zone_id(request)
        return await self._performance_client.upsert_edge_redirect(
            _provider_request(request),
            zone_id,
            request.source_path,
            request.target_url,
            request.status_code,
            request.preserve_query_string,
        )

    async def delete(self, request: EdgeRedirectDeleteRequest) -> None:
        """Delete only a Rankrat-managed redirect from the source site's DNS zone."""

        zone_id = await self._zone_id(request)
        await self._performance_client.delete_edge_redirect(
            _provider_request(request),
            zone_id,
            request.rule_id,
        )

    async def _zone_id(self, request: EdgeRedirectListRequest) -> str:
        host = urlsplit(request.site_url).hostname
        if host is None:
            raise InputLimitError("edge redirect source site must include a hostname")
        zone = await self._dns_client.resolve_zone(
            _provider_request(request),
            host,
        )
        return zone.provider_zone_id


def _provider_request(request: EdgeRedirectListRequest) -> ProviderReadRequest:
    return ProviderReadRequest(AccountId(request.account_id), request.timeout_seconds)


def _validate_source_path(value: str) -> None:
    if (
        not value.startswith("/")
        or len(value) > MAX_EDGE_REDIRECT_SOURCE_PATH_CHARS
        or any(character in value for character in ('"', "\\", "\r", "\n"))
    ):
        raise InputLimitError("edge redirect source_path is invalid")
