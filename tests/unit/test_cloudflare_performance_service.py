from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from rankrat.constants import MAX_CLOUDFLARE_ANALYTICS_RANGE_DAYS
from rankrat.errors import InputLimitError
from rankrat.services.cloudflare_performance import CloudflareAnalyticsRequest


def test_cloudflare_analytics_request_caps_provider_query_range() -> None:
    start = datetime(2025, 1, 1, tzinfo=UTC)
    CloudflareAnalyticsRequest(
        "cloudflare-main",
        "a" * 32,
        start,
        start + timedelta(days=MAX_CLOUDFLARE_ANALYTICS_RANGE_DAYS),
    )

    with pytest.raises(InputLimitError, match="date range"):
        CloudflareAnalyticsRequest(
            "cloudflare-main",
            "a" * 32,
            start,
            start + timedelta(days=MAX_CLOUDFLARE_ANALYTICS_RANGE_DAYS + 1),
        )
    with pytest.raises(InputLimitError, match="date range"):
        CloudflareAnalyticsRequest(
            "cloudflare-main",
            "a" * 32,
            start,
            start + timedelta(days=MAX_CLOUDFLARE_ANALYTICS_RANGE_DAYS, seconds=1),
        )
