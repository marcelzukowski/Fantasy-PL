"""API-Football v3 acquisition with cache, immutable raw evidence and local quotas.

This module deliberately returns API-Football's native response objects.  It does
not resolve provider IDs, derive features, or decide whether a retrieved record
was available at a historical prediction timestamp.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
import json
import math
from threading import Lock
from typing import Any

import httpx

from fpl_engine.data.http_cache import (
    CacheRequest, CachedHttpResponse, HttpCache, HttpCacheError, HttpResponse,
)
from fpl_engine.data.raw_store import RawSnapshot, RawStore, RawStoreError


DEFAULT_BASE_URL = "https://v3.football.api-sports.io"
_PROVIDER = "api_football"


class APIFootballError(Exception):
    """Base error for API-Football acquisition."""


class APIFootballValidationError(APIFootballError):
    """Invalid adapter settings, provider ID, clock or response envelope."""


class APIFootballQuotaExceededError(APIFootballError):
    """The configured local daily request budget is exhausted."""


class APIFootballRequestError(APIFootballError):
    """The transport failed or timed out; the original exception is chained."""


class APIFootballResponseError(APIFootballError):
    """A non-2xx response or API-Football reported an API-level error."""


class APIFootballParseError(APIFootballResponseError):
    """A successful body cannot be parsed as a valid API-Football envelope."""


class APIFootballStorageError(APIFootballError):
    """Raw evidence or operational cache failed safely; cause is chained."""


def _utc(value: datetime, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise APIFootballValidationError(f"{name} must be an aware datetime")
    return value.astimezone(timezone.utc)


def _positive_id(value: int, name: str) -> int:
    if type(value) is not int or value < 1:
        raise APIFootballValidationError(f"{name} must be a strictly positive integer")
    return value


def _season(value: int) -> int:
    # API-Football seasons are start years.  This broad range only rejects
    # malformed identifiers without assuming which seasons a plan covers.
    if type(value) is not int or not 1900 <= value <= 9999:
        raise APIFootballValidationError("season must be a four-digit integer year")
    return value


def _reject_json_constant(value: str) -> None:
    raise ValueError("Non-standard JSON constant")


@dataclass(frozen=True)
class APIFootballQuotaStatus:
    """The local request budget for one UTC day, independent of provider limits."""

    day: date
    daily_request_budget: int
    requests_used: int

    @property
    def requests_remaining(self) -> int:
        return self.daily_request_budget - self.requests_used


class APIFootballQuota:
    """Injectable in-memory UTC-day budget counted only when HTTP is attempted.

    ``daily_request_budget`` is an application policy.  Supplying 80 preserves a
    reserve against a currently advertised 100-request free plan, but this class
    does not encode an external provider quota or retry policy.
    """

    def __init__(self, daily_request_budget: int, *, clock: Callable[[], datetime] | None = None):
        if type(daily_request_budget) is not int or daily_request_budget < 1:
            raise APIFootballValidationError("daily_request_budget must be a positive integer")
        if clock is not None and not callable(clock):
            raise APIFootballValidationError("clock must be callable")
        self._budget = daily_request_budget
        self._clock = clock if clock is not None else lambda: datetime.now(timezone.utc)
        self._day: date | None = None
        self._used = 0
        self._lock = Lock()

    def _today(self) -> date:
        return _utc(self._clock(), "clock result").date()

    def status(self) -> APIFootballQuotaStatus:
        with self._lock:
            today = self._today()
            if self._day != today:
                self._day, self._used = today, 0
            return APIFootballQuotaStatus(today, self._budget, self._used)

    def consume_network_request(self) -> APIFootballQuotaStatus:
        """Reserve one request before a real transport call; cache hits never call this."""
        with self._lock:
            today = self._today()
            if self._day != today:
                self._day, self._used = today, 0
            if self._used >= self._budget:
                raise APIFootballQuotaExceededError(
                    f"API-Football local request budget exhausted for {today.isoformat()}"
                )
            self._used += 1
            return APIFootballQuotaStatus(today, self._budget, self._used)


@dataclass(frozen=True)
class APIFootballRateLimit:
    """Rate-limit values reported by API-Football response headers, when present."""

    limit: int | None
    remaining: int | None
    reset: str | None


@dataclass(frozen=True)
class APIFootballResult:
    """One provider-native envelope and acquisition/provenance timing.

    ``retrieved_at`` is local acquisition time for a network result and cache
    publication time for a cache hit.  It is not an assertion that response data
    was known at a caller's historical prediction timestamp.
    """

    endpoint: str
    parameters: Mapping[str, int]
    envelope: Mapping[str, Any] = field(repr=False)
    response: CachedHttpResponse = field(repr=False)
    raw_snapshot: RawSnapshot | None
    retrieved_at: datetime
    rate_limit: APIFootballRateLimit | None

    @property
    def payload(self) -> list[Any]:
        """Native API-Football ``response`` list, with unknown fields retained."""
        return self.envelope["response"]

    @property
    def from_cache(self) -> bool:
        return self.response.from_cache


@dataclass(frozen=True)
class APIFootballPaginatedResult:
    """All pages requested by ``get_all_player_statistics`` without transformation."""

    pages: tuple[APIFootballResult, ...]

    @property
    def payload(self) -> list[Any]:
        return [item for page in self.pages for item in page.payload]


class APIFootballAdapter:
    """Synchronous API-Football v3 adapter with caller-owned transport.

    Authentication is sent only as the documented ``x-apisports-key`` request
    header.  It is deliberately absent from CacheRequest, RawStore provenance,
    result representations and exception messages.  Successful response bytes
    are stored before JSON/envelope parsing; a fresh cache hit performs neither
    a transport call nor a RawStore write.
    """

    def __init__(
        self, *, client: httpx.Client, api_key: str, cache: HttpCache, raw_store: RawStore,
        quota: APIFootballQuota, ttl: timedelta | None, base_url: str = DEFAULT_BASE_URL,
        timeout: float = 10.0, clock: Callable[[], datetime] | None = None,
    ):
        if not callable(getattr(client, "get", None)):
            raise APIFootballValidationError("client must provide synchronous get()")
        if type(api_key) is not str or not api_key.strip():
            raise APIFootballValidationError("api_key must be a non-empty externally supplied string")
        if not isinstance(cache, HttpCache) or not isinstance(raw_store, RawStore):
            raise APIFootballValidationError("Expected HttpCache and RawStore instances")
        if not isinstance(quota, APIFootballQuota):
            raise APIFootballValidationError("quota must be an APIFootballQuota")
        if ttl is not None and (type(ttl) is not timedelta or ttl < timedelta(0)):
            raise APIFootballValidationError("ttl must be None or a non-negative timedelta")
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
            raise APIFootballValidationError("timeout must be finite positive seconds")
        if clock is not None and not callable(clock):
            raise APIFootballValidationError("clock must be callable")
        if type(base_url) is not str or "?" in base_url or "#" in base_url:
            raise APIFootballValidationError("base_url must be an HTTP URL without query or fragment")
        try:
            CacheRequest(_PROVIDER, "GET", base_url)
        except HttpCacheError as exc:
            raise APIFootballValidationError("Invalid API-Football base_url") from exc
        self._client = client
        self._api_key = api_key
        self._cache = cache
        self._raw_store = raw_store
        self._quota = quota
        self._ttl = ttl
        self._base_url = base_url.rstrip("/")
        self._timeout = float(timeout)
        self._clock = clock if clock is not None else lambda: datetime.now(timezone.utc)

    @property
    def quota_status(self) -> APIFootballQuotaStatus:
        return self._quota.status()

    def get_fixtures(self, *, league: int, season: int, team: int | None = None) -> APIFootballResult:
        params = {"league": _positive_id(league, "league"), "season": _season(season)}
        if team is not None:
            params["team"] = _positive_id(team, "team")
        return self._get("fixtures", "fixtures", params)

    def get_fixture_statistics(self, fixture: int) -> APIFootballResult:
        return self._get("fixtures/statistics", "fixture_statistics", {"fixture": _positive_id(fixture, "fixture")})

    def get_lineups(self, fixture: int) -> APIFootballResult:
        return self._get("fixtures/lineups", "lineups", {"fixture": _positive_id(fixture, "fixture")})

    def get_injuries(self, *, league: int, season: int, team: int | None = None) -> APIFootballResult:
        params = {"league": _positive_id(league, "league"), "season": _season(season)}
        if team is not None:
            params["team"] = _positive_id(team, "team")
        return self._get("injuries", "injuries", params)

    def get_sidelined(self, player: int) -> APIFootballResult:
        return self._get("sidelined", "sidelined", {"player": _positive_id(player, "player")})

    def get_transfers(self, player: int) -> APIFootballResult:
        return self._get("transfers", "transfers", {"player": _positive_id(player, "player")})

    def get_coaches(self, team: int) -> APIFootballResult:
        return self._get("coachs", "coaches", {"team": _positive_id(team, "team")})

    def get_player_statistics(
        self, *, league: int, season: int, team: int | None = None,
        player: int | None = None, page: int = 1,
    ) -> APIFootballResult:
        params = {"league": _positive_id(league, "league"), "season": _season(season)}
        if team is not None:
            params["team"] = _positive_id(team, "team")
        if player is not None:
            params["player"] = _positive_id(player, "player")
        params["page"] = _positive_id(page, "page")
        return self._get("players", "player_statistics", params)

    def get_all_player_statistics(
        self, *, league: int, season: int, team: int | None = None, player: int | None = None,
    ) -> APIFootballPaginatedResult:
        """Read exactly the pages declared by the first valid provider envelope."""
        first = self.get_player_statistics(
            league=league, season=season, team=team, player=player, page=1,
        )
        paging = first.envelope["paging"]
        total = paging["total"]
        current = paging["current"]
        if type(current) is not int or type(total) is not int or current != 1 or total < 1:
            raise APIFootballParseError("Invalid API-Football player-statistics pagination")
        pages = [first]
        for page in range(2, total + 1):
            result = self.get_player_statistics(
                league=league, season=season, team=team, player=player, page=page,
            )
            page_info = result.envelope["paging"]
            if (type(page_info["current"]) is not int or type(page_info["total"]) is not int
                    or page_info["current"] != page or page_info["total"] != total):
                raise APIFootballParseError("Inconsistent API-Football player-statistics pagination")
            pages.append(result)
        return APIFootballPaginatedResult(tuple(pages))

    def _retrieved_at(self) -> datetime:
        return _utc(self._clock(), "clock result")

    def _get(self, endpoint: str, entity: str, params: dict[str, int]) -> APIFootballResult:
        url = f"{self._base_url}/{endpoint}"
        request = CacheRequest(_PROVIDER, "GET", url, params=params)
        snapshot: RawSnapshot | None = None
        rate_limit: APIFootballRateLimit | None = None

        def fetch() -> HttpResponse:
            nonlocal snapshot, rate_limit
            self._quota.consume_network_request()
            try:
                network_response = self._client.get(
                    url, params=params, headers={"x-apisports-key": self._api_key},
                    timeout=self._timeout, follow_redirects=False,
                )
            except httpx.TimeoutException as exc:
                raise APIFootballRequestError(f"API-Football request timed out at {endpoint}") from exc
            except httpx.RequestError as exc:
                raise APIFootballRequestError(f"API-Football transport failed at {endpoint}") from exc
            if not 200 <= network_response.status_code < 300:
                raise APIFootballResponseError(
                    f"API-Football HTTP {network_response.status_code} at {endpoint}"
                )
            body = network_response.content
            try:
                snapshot = self._raw_store.store_bytes(
                    body, source_provider=_PROVIDER, entity=entity,
                    retrieved_at=self._retrieved_at(), source_url=request.redacted_url,
                    source_record_id=_record_id(endpoint, params),
                )
            except RawStoreError:
                raise
            rate_limit = _rate_limit(network_response.headers)
            return HttpResponse(
                status_code=network_response.status_code, body=body, headers=network_response.headers,
            )

        try:
            response = self._cache.get_or_fetch(request, fetch, ttl=self._ttl)
        except (RawStoreError, HttpCacheError) as exc:
            raise APIFootballStorageError(f"API-Football storage failed at {endpoint}") from exc
        envelope = _parse_envelope(response.body, endpoint)
        errors = envelope["errors"]
        if _has_errors(errors):
            raise APIFootballResponseError(f"API-Football reported an error at {endpoint}")
        return APIFootballResult(
            endpoint=endpoint, parameters=dict(params), envelope=envelope, response=response,
            raw_snapshot=snapshot,
            retrieved_at=snapshot.retrieved_at if snapshot is not None else response.stored_at,
            rate_limit=rate_limit,
        )


def _record_id(endpoint: str, params: Mapping[str, int]) -> str:
    return endpoint + "?" + "&".join(f"{key}={params[key]}" for key in sorted(params))


def _has_errors(value: Any) -> bool:
    if isinstance(value, Mapping) or isinstance(value, (list, tuple, set)):
        return bool(value)
    return value not in (None, "", False)


def _parse_envelope(body: bytes, endpoint: str) -> dict[str, Any]:
    try:
        envelope = json.loads(body, parse_constant=_reject_json_constant)
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise APIFootballParseError(f"Invalid API-Football JSON at {endpoint}") from exc
    required = {"get", "parameters", "errors", "results", "paging", "response"}
    if not isinstance(envelope, dict) or not required.issubset(envelope):
        raise APIFootballParseError(f"Invalid API-Football envelope at {endpoint}")
    if (not isinstance(envelope["get"], str) or not isinstance(envelope["parameters"], dict)
            or not isinstance(envelope["results"], int) or isinstance(envelope["results"], bool)
            or not isinstance(envelope["paging"], dict) or not isinstance(envelope["response"], list)):
        raise APIFootballParseError(f"Invalid API-Football envelope fields at {endpoint}")
    return envelope


def _header_int(headers: Mapping[str, str], name: str) -> int | None:
    value = headers.get(name)
    if value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _rate_limit(headers: Mapping[str, str]) -> APIFootballRateLimit | None:
    normalized = {str(key).lower(): str(value) for key, value in headers.items()}
    limit = _header_int(normalized, "x-ratelimit-requests-limit")
    remaining = _header_int(normalized, "x-ratelimit-requests-remaining")
    reset = normalized.get("x-ratelimit-requests-reset")
    if limit is None and remaining is None and reset is None:
        return None
    return APIFootballRateLimit(limit=limit, remaining=remaining, reset=reset)
