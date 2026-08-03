"""Provider-neutral contracts for Rankrat's future provider clients."""

from rankrat.providers.base import (
    AccountId,
    IndexNowSubmission,
    IndexNowSubmitRequest,
    IndexNowTargetId,
    ProviderClient,
    ProviderOperationError,
    ProviderReadiness,
    ProviderReadRequest,
)
from rankrat.providers.google_analytics import GoogleAnalyticsDataClient
from rankrat.providers.google_search_console import GoogleSearchConsoleClient
from rankrat.providers.indexnow import IndexNowClient
from rankrat.providers.pagespeed import PageSpeedClient

__all__ = [
    "AccountId",
    "IndexNowClient",
    "IndexNowSubmission",
    "IndexNowSubmitRequest",
    "IndexNowTargetId",
    "PageSpeedClient",
    "ProviderClient",
    "ProviderOperationError",
    "ProviderReadRequest",
    "ProviderReadiness",
    "GoogleSearchConsoleClient",
    "GoogleAnalyticsDataClient",
]
