"""Bounded, opt-in IndexNow submissions shared by REST and MCP."""

from __future__ import annotations

import asyncio
import logging
import time
from collections import OrderedDict, deque
from collections.abc import Callable
from dataclasses import dataclass, field
from urllib.parse import quote, unquote, urlparse, urlunparse

from rankrat.constants import DEFAULT_PROVIDER_TIMEOUT_SECONDS, MAX_INDEXNOW_URLS
from rankrat.errors import BoundaryDeniedError, IndexNowRateLimitError, InputLimitError
from rankrat.logging import log_event
from rankrat.models.boundaries import IndexNowTarget
from rankrat.policy.boundaries import BoundaryPolicy
from rankrat.providers.base import IndexNowSubmitRequest, IndexNowTargetId
from rankrat.providers.indexnow import IndexNowClient

_LOGGER = logging.getLogger(__name__)
_INDEXNOW_RATE_WINDOW_SECONDS = 60.0
_MAX_INDEXNOW_SUBMISSIONS_PER_WINDOW = 10
_MAX_INDEXNOW_DEDUPE_ENTRIES_PER_TARGET = MAX_INDEXNOW_URLS * _MAX_INDEXNOW_SUBMISSIONS_PER_WINDOW
_HTTPS_SCHEME = "https"
_STANDARD_HTTPS_PORT = 443
_SAFE_PATH_CHARACTERS = "/:@-._~!$&'()*+,;="
_ENCODED_PATH_SEPARATOR_PREFIXES = ("%2f", "%5c")


@dataclass(frozen=True, slots=True)
class IndexNowSubmissionRequest:
    """One caller-selected batch constrained to an operator-owned target."""

    target_id: str
    urls: tuple[str, ...]
    timeout_seconds: float = DEFAULT_PROVIDER_TIMEOUT_SECONDS


@dataclass(frozen=True, slots=True)
class IndexNowSubmissionResponse:
    """Safe submission summary that never exposes keys or submitted URLs."""

    target_id: str
    host: str
    submitted_count: int
    deduplicated_count: int
    suppressed_count: int
    key_validation_pending: bool


@dataclass(slots=True)
class _TargetSubmissionState:
    """Bounded in-memory state for one immutable IndexNow target."""

    attempts: deque[float] = field(default_factory=lambda: deque[float]())
    recent_urls: OrderedDict[str, float] = field(default_factory=lambda: OrderedDict[str, float]())
    pending_urls: set[str] = field(default_factory=lambda: set[str]())


class IndexNowService:
    """Serializes write admission without adding caller-controlled egress."""

    def __init__(
        self,
        policy: BoundaryPolicy,
        client: IndexNowClient,
        monotonic_clock: Callable[[], float] = time.monotonic,
        rate_window_seconds: float = _INDEXNOW_RATE_WINDOW_SECONDS,
        max_submissions_per_window: int = _MAX_INDEXNOW_SUBMISSIONS_PER_WINDOW,
        max_dedupe_entries_per_target: int = _MAX_INDEXNOW_DEDUPE_ENTRIES_PER_TARGET,
    ) -> None:
        if rate_window_seconds <= 0:
            raise ValueError("rate_window_seconds must be positive")
        if max_submissions_per_window < 1:
            raise ValueError("max_submissions_per_window must be positive")
        if max_dedupe_entries_per_target < 1:
            raise ValueError("max_dedupe_entries_per_target must be positive")
        self._policy = policy
        self._client = client
        self._monotonic_clock = monotonic_clock
        self._rate_window_seconds = rate_window_seconds
        self._max_submissions_per_window = max_submissions_per_window
        self._max_dedupe_entries_per_target = max_dedupe_entries_per_target
        self._states: dict[str, _TargetSubmissionState] = {}
        self._state_lock = asyncio.Lock()

    async def submit(self, request: IndexNowSubmissionRequest) -> IndexNowSubmissionResponse:
        """Submit only newly eligible URLs to the configured target's fixed client."""
        target = self._policy.resolve_indexnow_target(request.target_id)
        normalized_urls = self._normalize_urls(target, request.urls)
        now = self._monotonic_clock()
        eligible_urls, duplicate_count, suppressed_count = await self._reserve_submission(
            target.id,
            normalized_urls,
            now,
        )
        if not eligible_urls:
            log_event(
                _LOGGER,
                logging.INFO,
                "IndexNow submission suppressed",
                target_id=target.id,
                host=target.host,
                deduplicated_count=duplicate_count,
                suppressed_count=suppressed_count,
            )
            return IndexNowSubmissionResponse(
                target_id=target.id,
                host=target.host,
                submitted_count=0,
                deduplicated_count=duplicate_count,
                suppressed_count=suppressed_count,
                key_validation_pending=False,
            )

        try:
            submitted = await self._client.submit(
                IndexNowSubmitRequest(
                    target_id=IndexNowTargetId(target.id),
                    urls=eligible_urls,
                    timeout_seconds=request.timeout_seconds,
                )
            )
        except Exception:
            await self._release_pending(target.id, eligible_urls)
            log_event(
                _LOGGER,
                logging.WARNING,
                "IndexNow submission failed",
                target_id=target.id,
                host=target.host,
                submitted_count=0,
            )
            raise

        await self._record_success(target.id, eligible_urls, self._monotonic_clock())
        provider_deduplicated_count = len(eligible_urls) - submitted.submitted_count
        deduplicated_count = duplicate_count + max(provider_deduplicated_count, 0)
        log_event(
            _LOGGER,
            logging.INFO,
            "IndexNow submission accepted",
            target_id=target.id,
            host=target.host,
            submitted_count=submitted.submitted_count,
            deduplicated_count=deduplicated_count,
            suppressed_count=suppressed_count,
        )
        return IndexNowSubmissionResponse(
            target_id=submitted.target_id,
            host=submitted.host,
            submitted_count=submitted.submitted_count,
            deduplicated_count=deduplicated_count,
            suppressed_count=suppressed_count,
            key_validation_pending=submitted.key_validation_pending,
        )

    def _normalize_urls(self, target: IndexNowTarget, urls: tuple[str, ...]) -> tuple[str, ...]:
        if not urls:
            raise InputLimitError("IndexNow submissions require at least one URL")
        if len(urls) > MAX_INDEXNOW_URLS:
            raise InputLimitError("IndexNow submission exceeds the URL limit")
        return tuple(self._normalize_url(target, value) for value in urls)

    @staticmethod
    def _normalize_url(target: IndexNowTarget, value: str) -> str:
        if not value or any(ord(character) < 32 or ord(character) == 127 for character in value):
            raise BoundaryDeniedError("IndexNow URL is not allowed for the configured target")
        normalized = value.strip()
        try:
            parsed = urlparse(normalized)
            hostname = parsed.hostname
            port = parsed.port
        except ValueError as error:
            raise BoundaryDeniedError(
                "IndexNow URL is not allowed for the configured target"
            ) from error
        if (
            parsed.scheme.lower() != _HTTPS_SCHEME
            or hostname is None
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
            or port not in (None, _STANDARD_HTTPS_PORT)
        ):
            raise BoundaryDeniedError("IndexNow URL is not allowed for the configured target")
        try:
            canonical_host = hostname.lower().encode("idna").decode("ascii")
        except UnicodeError as error:
            raise BoundaryDeniedError(
                "IndexNow URL is not allowed for the configured target"
            ) from error
        if canonical_host != target.host:
            raise BoundaryDeniedError("IndexNow URL is not allowed for the configured target")

        decoded_path = unquote(parsed.path or "/")
        path_segments = decoded_path.split("/")
        if (
            any(prefix in parsed.path.lower() for prefix in _ENCODED_PATH_SEPARATOR_PREFIXES)
            or "\\" in decoded_path
            or "\x00" in decoded_path
            or any(segment in {".", ".."} for segment in path_segments)
        ):
            raise BoundaryDeniedError("IndexNow URL is not allowed for the configured target")
        canonical_path = quote(decoded_path, safe=_SAFE_PATH_CHARACTERS)
        if not canonical_path.startswith(IndexNowService._key_location_directory(target)):
            raise BoundaryDeniedError("IndexNow URL is not allowed for the configured target")
        return urlunparse((_HTTPS_SCHEME, canonical_host, canonical_path, "", parsed.query, ""))

    @staticmethod
    def _key_location_directory(target: IndexNowTarget) -> str:
        key_path = urlparse(target.key_location).path
        directory, _, _ = key_path.rpartition("/")
        return f"{directory}/" if directory else "/"

    async def _reserve_submission(
        self,
        target_id: str,
        urls: tuple[str, ...],
        now: float,
    ) -> tuple[tuple[str, ...], int, int]:
        async with self._state_lock:
            state = self._states.setdefault(target_id, _TargetSubmissionState())
            self._prune_state(state, now)
            unique_urls = tuple(dict.fromkeys(urls))
            duplicate_count = len(urls) - len(unique_urls)
            eligible_urls = tuple(
                url
                for url in unique_urls
                if url not in state.recent_urls and url not in state.pending_urls
            )
            suppressed_count = len(unique_urls) - len(eligible_urls)
            if not eligible_urls:
                return eligible_urls, duplicate_count, suppressed_count
            if len(state.attempts) >= self._max_submissions_per_window:
                raise IndexNowRateLimitError("IndexNow submission rate limit exceeded")
            state.attempts.append(now)
            state.pending_urls.update(eligible_urls)
            return eligible_urls, duplicate_count, suppressed_count

    async def _release_pending(self, target_id: str, urls: tuple[str, ...]) -> None:
        async with self._state_lock:
            self._states[target_id].pending_urls.difference_update(urls)

    async def _record_success(self, target_id: str, urls: tuple[str, ...], now: float) -> None:
        async with self._state_lock:
            state = self._states[target_id]
            state.pending_urls.difference_update(urls)
            for url in urls:
                state.recent_urls[url] = now
                state.recent_urls.move_to_end(url)
            self._prune_state(state, now)
            while len(state.recent_urls) > self._max_dedupe_entries_per_target:
                state.recent_urls.popitem(last=False)

    def _prune_state(self, state: _TargetSubmissionState, now: float) -> None:
        cutoff = now - self._rate_window_seconds
        while state.attempts and state.attempts[0] <= cutoff:
            state.attempts.popleft()
        while state.recent_urls:
            _, timestamp = next(iter(state.recent_urls.items()))
            if timestamp > cutoff:
                break
            state.recent_urls.popitem(last=False)
