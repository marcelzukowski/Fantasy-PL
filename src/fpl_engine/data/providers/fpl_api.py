"""Public Official FPL endpoints with operational caching and immutable evidence."""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import json
import math
from typing import Any

import httpx

from fpl_engine.data.http_cache import (
    CacheRequest, CachedHttpResponse, HttpCache, HttpCacheError, HttpResponse,
)
from fpl_engine.data.raw_store import RawSnapshot, RawStore, RawStoreError


DEFAULT_BASE_URL = "https://fantasy.premierleague.com/api/"
_PROVIDER = "official_fpl_api"


class FPLApiError(Exception):
    """Base error for Official FPL acquisition."""


class FPLApiValidationError(FPLApiError):
    """Invalid adapter settings, provider ID, gameweek or operational clock."""


class FPLApiRequestError(FPLApiError):
    """The transport failed or timed out; the original exception is chained."""


class FPLApiResponseError(FPLApiError):
    """Non-success HTTP status or incompatible endpoint root shape."""


class FPLApiParseError(FPLApiResponseError):
    """Successful HTTP body cannot be parsed as JSON."""


class FPLApiStorageError(FPLApiError):
    """Raw evidence or operational cache could not be read/persisted safely."""


@dataclass(frozen=True)
class FPLApiResult:
    """Provider payload and exact HTTP response; no canonical ID interpretation.

    payload is a freshly parsed, mutable dict/list retaining extra provider fields.
    raw_snapshot exists only for an actual fetch in this call. Cache stored_at is
    operational write time, not inferred source publication/retrieval time.
    """

    payload: dict[str, Any] | list[Any] = field(repr=False)
    response: CachedHttpResponse = field(repr=False)
    raw_snapshot: RawSnapshot | None

    @property
    def from_cache(self) -> bool:
        return self.response.from_cache


def _positive_id(value: int, name: str, maximum: int | None = None) -> None:
    if type(value) is not int or value < 1 or (maximum is not None and value > maximum):
        limit = f"1..{maximum}" if maximum is not None else "a positive integer"
        raise FPLApiValidationError(f"{name} must be strictly {limit}")


def _reject_json_constant(value: str) -> None:
    raise ValueError("Non-standard JSON constant")


class OfficialFPLAdapter:
    """Synchronous public API adapter using a caller-owned httpx.Client.

    The caller supplies cache, raw store and TTL (None means immutable), owns
    client lifetime and may inject a clock/base URL. timeout is finite positive
    seconds for httpx's request phases. Redirects are not followed. No retries,
    authentication, logging configuration or normalization are added.

    Flow: cache lookup -> on miss/stale, HTTP -> status -> raw bytes -> cache
    -> JSON/root validation. Consequently invalid JSON in a 2xx response remains
    available for audit and may be served by the HTTP cache; every adapter read
    still raises a parse/shape error. Cache hits never create raw snapshots.
    """

    def __init__(
        self, *, client: httpx.Client, cache: HttpCache, raw_store: RawStore,
        ttl: timedelta | None, base_url: str = DEFAULT_BASE_URL,
        timeout: float = 10.0, clock: Callable[[], datetime] | None = None,
    ):
        if not callable(getattr(client, "get", None)):
            raise FPLApiValidationError("client must provide synchronous get()")
        if not isinstance(cache, HttpCache) or not isinstance(raw_store, RawStore):
            raise FPLApiValidationError("Expected HttpCache and RawStore instances")
        if ttl is not None and (type(ttl) is not timedelta or ttl < timedelta(0)):
            raise FPLApiValidationError("ttl must be None or a non-negative timedelta")
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
            raise FPLApiValidationError("timeout must be finite positive seconds")
        if clock is not None and not callable(clock):
            raise FPLApiValidationError("clock must be callable")
        if type(base_url) is not str or "?" in base_url or "#" in base_url:
            raise FPLApiValidationError("base_url must be an HTTP URL without query or fragment")
        try:
            CacheRequest(_PROVIDER, "GET", base_url)
        except HttpCacheError as exc:
            raise FPLApiValidationError("Invalid public API base_url") from exc
        self._client = client
        self._cache = cache
        self._raw_store = raw_store
        self._ttl = ttl
        self._base_url = base_url.rstrip("/") + "/"
        self._timeout = float(timeout)
        self._clock = clock if clock is not None else lambda: datetime.now(timezone.utc)

    def get_bootstrap_static(self) -> FPLApiResult:
        """Fetch public current-state data without interpreting provider fields."""
        return self._get("bootstrap-static/", "bootstrap_static",
                         required_keys=("events", "elements", "teams", "element_types"))

    def get_fixtures(self, event: int | None = None) -> FPLApiResult:
        """Fetch all fixtures in one request, or filter by an explicit FPL GW."""
        if event is not None:
            _positive_id(event, "event", 38)
        return self._get("fixtures/", "fixtures", params=None if event is None else {"event": event},
                         source_record_id=None if event is None else str(event))

    def get_element_summary(self, player_id: int) -> FPLApiResult:
        """player_id is a positive Official FPL provider ID, never a canonical ID."""
        _positive_id(player_id, "player_id")
        return self._get(f"element-summary/{player_id}/", "element_summary",
                         source_record_id=str(player_id),
                         required_keys=("fixtures", "history", "history_past"))

    def get_event_live(self, gameweek: int) -> FPLApiResult:
        """Fetch public live data for an Official FPL gameweek in 1..38."""
        _positive_id(gameweek, "gameweek", 38)
        return self._get(f"event/{gameweek}/live/", "event_live",
                         source_record_id=str(gameweek), required_keys=("elements",))

    def _retrieved_at(self) -> datetime:
        now = self._clock()
        if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
            raise FPLApiValidationError("clock must return an aware retrieval datetime")
        return now.astimezone(timezone.utc)

    def _get(
        self, endpoint: str, entity: str, *, params: dict[str, int] | None = None,
        source_record_id: str | None = None, required_keys: tuple[str, ...] | None = None,
    ) -> FPLApiResult:
        url = self._base_url + endpoint
        request = CacheRequest(_PROVIDER, "GET", url, params=params)
        snapshot = None

        def fetch() -> HttpResponse:
            nonlocal snapshot
            try:
                network_response = self._client.get(
                    url, params=params, timeout=self._timeout, follow_redirects=False,
                )
            except httpx.TimeoutException as exc:
                raise FPLApiRequestError(f"FPL request timed out at {endpoint}") from exc
            except httpx.RequestError as exc:
                raise FPLApiRequestError(f"FPL transport failed at {endpoint}") from exc
            if not 200 <= network_response.status_code < 300:
                raise FPLApiResponseError(f"FPL HTTP {network_response.status_code} at {endpoint}")
            # httpx.content is the exact body delivered to the adapter, including
            # httpx's transport decompression; it is never JSON re-serialized here.
            body = network_response.content
            snapshot = self._raw_store.store_bytes(
                body, source_provider=_PROVIDER, entity=entity,
                retrieved_at=self._retrieved_at(), source_url=request.redacted_url,
                source_record_id=source_record_id,
            )
            return HttpResponse(status_code=network_response.status_code,
                                body=body, headers=network_response.headers)

        try:
            response = self._cache.get_or_fetch(request, fetch, ttl=self._ttl)
        except (RawStoreError, HttpCacheError) as exc:
            raise FPLApiStorageError(f"FPL storage failed at {endpoint}") from exc
        try:
            payload = json.loads(response.body, parse_constant=_reject_json_constant)
        except (ValueError, UnicodeError, RecursionError) as exc:
            raise FPLApiParseError(f"Invalid FPL JSON at {endpoint}") from exc
        if required_keys is None:
            valid = isinstance(payload, list)
        else:
            valid = isinstance(payload, dict) and all(key in payload for key in required_keys)
        if not valid:
            raise FPLApiResponseError(f"Invalid FPL root shape or missing root keys at {endpoint}")
        return FPLApiResult(payload=payload, response=response, raw_snapshot=snapshot)
