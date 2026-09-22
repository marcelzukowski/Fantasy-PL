"""Vaastav historical CSV acquisition with explicit source versions and provenance."""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import csv
from io import BytesIO, TextIOWrapper
import math
import re
from typing import Any

import httpx
import pandas as pd

from fpl_engine.data.http_cache import (
    CacheRequest, CachedHttpResponse, HttpCache, HttpCacheError, HttpResponse,
)
from fpl_engine.data.raw_store import RawSnapshot, RawStore, RawStoreError


DEFAULT_BASE_URL = "https://raw.githubusercontent.com/vaastav/Fantasy-Premier-League"
_PROVIDER = "vaastav"
_SEASON = re.compile(r"(?:19|20)\d{2}-(?:0\d|[1-9]\d)", re.ASCII)
_REF_PART = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*", re.ASCII)


class VaastavError(Exception):
    """Base error for Vaastav historical dataset acquisition."""


class VaastavValidationError(VaastavError):
    """Invalid source reference, season, gameweek, policy or clock."""


class VaastavRequestError(VaastavError):
    """A synchronous HTTP transport failure; the original cause is chained."""


class VaastavResponseError(VaastavError):
    """A non-success response or an invalid requested-gameweek CSV value."""


class VaastavParseError(VaastavResponseError):
    """A successful source body is not a structurally valid UTF-8 CSV."""


class VaastavStorageError(VaastavError):
    """Raw evidence or operational cache cannot be persisted/read safely."""


def _validate_season(season: str) -> str:
    if type(season) is not str or not _SEASON.fullmatch(season):
        raise VaastavValidationError("season must have canonical YYYY-YY form")
    start, end = map(int, season.split("-"))
    if end != (start + 1) % 100:
        raise VaastavValidationError("season end year must follow start year")
    return season


def _validate_gameweek(gameweek: int) -> int:
    if type(gameweek) is not int or not 1 <= gameweek <= 38:
        raise VaastavValidationError("gameweek must be a strict integer in 1..38")
    return gameweek


def _validate_ref(repository_ref: str) -> str:
    # Git refs may contain '/', but never empty, dot, traversal or Windows path parts.
    if type(repository_ref) is not str or not repository_ref or len(repository_ref) > 255:
        raise VaastavValidationError("repository_ref must be a non-empty safe Git ref")
    parts = repository_ref.split("/")
    devices = {"CON", "PRN", "AUX", "NUL"} | {
        f"{prefix}{number}" for prefix in ("COM", "LPT") for number in range(1, 10)
    }
    if any(not _REF_PART.fullmatch(part) or part.upper() in devices for part in parts):
        raise VaastavValidationError("repository_ref must be a safe Git ref")
    return repository_ref


@dataclass(frozen=True)
class VaastavDataset:
    """Immutable dataset receipt; ``data`` is a newly parsed pandas DataFrame.

    The wrapper's provenance cannot be reassigned. Pandas remains a mutable table
    by design, so callers that transform it must keep this receipt separately.
    ``xP`` stays in ``data`` but is unsafe by default because its upstream timing
    cannot establish pre-deadline availability. This is metadata, not a feature
    selection or leakage-validation system.
    """

    season: str
    dataset_name: str
    gameweek: int | None
    repository_ref: str
    source_url: str
    retrieved_at: datetime
    raw_snapshot: RawSnapshot | None
    columns: tuple[str, ...]
    unsafe_columns: frozenset[str]
    data: pd.DataFrame = field(repr=False, compare=False)
    response: CachedHttpResponse = field(repr=False, compare=False)

    @property
    def from_cache(self) -> bool:
        return self.response.from_cache

    @property
    def safe_feature_columns(self) -> tuple[str, ...]:
        """A convenience list only; later feature code still needs PIT review."""
        return tuple(column for column in self.columns if column not in self.unsafe_columns)


class VaastavAdapter:
    """Load two version-pinned Vaastav CSV contracts through a caller-owned client.

    ``repository_ref`` is required and recorded verbatim. A commit SHA is the
    preferred value for reproducible historical backtests. Tags and branches are
    allowed, but mutable refs such as ``master`` are not resolved or represented
    as immutable versions. The caller explicitly chooses TTL: ``None`` is useful
    for a commit SHA, while a mutable ref normally needs a finite TTL.

    On miss/staleness the exact HTTP body is stored in RawStore before CSV parsing
    and then placed in HttpCache. Fresh hits parse cached bytes only and create no
    new raw evidence. No GitHub API, git subprocess, retries, local checkout mode,
    canonical identity conversion or provider-column renaming is performed.
    """

    def __init__(
        self, *, client: httpx.Client, cache: HttpCache, raw_store: RawStore,
        repository_ref: str, ttl: timedelta | None,
        base_url: str = DEFAULT_BASE_URL, timeout: float = 10.0,
        clock: Callable[[], datetime] | None = None,
    ):
        if not callable(getattr(client, "get", None)):
            raise VaastavValidationError("client must provide synchronous get()")
        if not isinstance(cache, HttpCache) or not isinstance(raw_store, RawStore):
            raise VaastavValidationError("Expected HttpCache and RawStore instances")
        if ttl is not None and (type(ttl) is not timedelta or ttl < timedelta(0)):
            raise VaastavValidationError("ttl must be None or a non-negative timedelta")
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
            raise VaastavValidationError("timeout must be finite positive seconds")
        if clock is not None and not callable(clock):
            raise VaastavValidationError("clock must be callable")
        if type(base_url) is not str or "?" in base_url or "#" in base_url:
            raise VaastavValidationError("base_url must be an HTTP URL without query or fragment")
        try:
            CacheRequest(_PROVIDER, "GET", base_url)
        except HttpCacheError as exc:
            raise VaastavValidationError("Invalid raw-file base_url") from exc
        self._client = client
        self._cache = cache
        self._raw_store = raw_store
        self.repository_ref = _validate_ref(repository_ref)
        self._ttl = ttl
        self._base_url = base_url.rstrip("/")
        self._timeout = float(timeout)
        self._clock = clock if clock is not None else lambda: datetime.now(timezone.utc)

    def get_merged_gameweeks(self, season: str) -> VaastavDataset:
        """Fetch ``data/{season}/gws/merged_gw.csv`` without column conversion."""
        season = _validate_season(season)
        return self._get(season=season, dataset_name="merged_gameweeks", gameweek=None,
                         filename="merged_gw.csv")

    def get_gameweek(self, season: str, gameweek: int) -> VaastavDataset:
        """Fetch one Vaastav GW file; only a present ``GW`` column is checked."""
        season, gameweek = _validate_season(season), _validate_gameweek(gameweek)
        return self._get(season=season, dataset_name="gameweek", gameweek=gameweek,
                         filename=f"gw{gameweek}.csv")

    def get_fixture_schedule(self, season: str) -> VaastavDataset:
        """Fetch the version-pinned ``data/{season}/fixtures.csv`` schedule.

        A caller performing a historical reconstruction must choose a commit
        whose commit timestamp is strictly before its prediction timestamp.
        This adapter deliberately records the chosen ref but does not decide
        whether that ref was available in time.
        """
        season = _validate_season(season)
        return self._get(season=season, dataset_name="fixture_schedule", gameweek=None,
                         filename="fixtures.csv", directory="")

    def _retrieved_at(self) -> datetime:
        now = self._clock()
        if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
            raise VaastavValidationError("clock must return an aware retrieval datetime")
        return now.astimezone(timezone.utc)

    def _get(self, *, season: str, dataset_name: str, gameweek: int | None,
             filename: str, directory: str = "gws") -> VaastavDataset:
        relative = f"data/{season}/{directory}/{filename}" if directory else f"data/{season}/{filename}"
        url = f"{self._base_url}/{self.repository_ref}/{relative}"
        source_record_id = (
            f"{self.repository_ref}:{season}:fixtures" if dataset_name == "fixture_schedule"
            else f"{self.repository_ref}:{season}:merged_gw" if gameweek is None
            else f"{self.repository_ref}:{season}:gw:{gameweek}"
        )
        request = CacheRequest(_PROVIDER, "GET", url)
        snapshot = None

        def fetch() -> HttpResponse:
            nonlocal snapshot
            try:
                network_response = self._client.get(url, timeout=self._timeout, follow_redirects=False)
            except httpx.TimeoutException as exc:
                raise VaastavRequestError(f"Vaastav request timed out for {season} {filename}") from exc
            except httpx.RequestError as exc:
                raise VaastavRequestError(f"Vaastav transport failed for {season} {filename}") from exc
            if not 200 <= network_response.status_code < 300:
                raise VaastavResponseError(
                    f"Vaastav HTTP {network_response.status_code} for {season} {filename}"
                )
            body = network_response.content
            snapshot = self._raw_store.store_bytes(
                body, source_provider=_PROVIDER, entity=dataset_name,
                retrieved_at=self._retrieved_at(), source_url=request.redacted_url,
                source_record_id=source_record_id,
            )
            return HttpResponse(status_code=network_response.status_code,
                                body=body, headers=network_response.headers)

        try:
            response = self._cache.get_or_fetch(request, fetch, ttl=self._ttl)
        except (RawStoreError, HttpCacheError) as exc:
            raise VaastavStorageError(f"Vaastav storage failed for {season} {filename}") from exc
        dataframe = _parse_csv(response.body, season, filename)
        if gameweek is not None and "GW" in dataframe.columns:
            values = dataframe["GW"].dropna()
            if not values.empty and not values.eq(gameweek).all():
                raise VaastavResponseError(
                    f"Vaastav GW column does not match requested gameweek {gameweek} for {season}"
                )
        return VaastavDataset(
            season=season, dataset_name=dataset_name, gameweek=gameweek,
            repository_ref=self.repository_ref, source_url=request.redacted_url,
            retrieved_at=snapshot.retrieved_at if snapshot is not None else response.stored_at,
            raw_snapshot=snapshot, columns=tuple(dataframe.columns),
            unsafe_columns=frozenset({"xP"} & set(dataframe.columns)), data=dataframe,
            response=response,
        )


def _parse_csv(body: bytes, season: str, filename: str) -> pd.DataFrame:
    if not body:
        raise VaastavParseError(f"Empty Vaastav CSV body for {season} {filename}")
    try:
        with TextIOWrapper(BytesIO(body), encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.reader(stream, strict=True))
            header = rows[0] if rows else None
        if header is None or not header or not any(header):
            raise ValueError("CSV has no header")
        if len(header) != len(set(header)):
            raise ValueError("CSV has duplicate column names")
        if any(len(row) != len(header) for row in rows[1:]):
            raise ValueError("CSV row has a different field count")
        dataframe = pd.read_csv(BytesIO(body), encoding="utf-8-sig", engine="python", on_bad_lines="error")
    except (UnicodeError, UnicodeDecodeError, pd.errors.ParserError, csv.Error, ValueError) as exc:
        raise VaastavParseError(f"Invalid Vaastav CSV for {season} {filename}") from exc
    if tuple(dataframe.columns) != tuple(header):
        raise VaastavParseError(f"Invalid Vaastav CSV header for {season} {filename}")
    return dataframe
