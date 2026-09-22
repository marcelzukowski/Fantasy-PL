"""Point-in-time FPL bootstrap snapshots from Randdalf/fplcache."""

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import json
import lzma
import math
import re
from typing import Any

import httpx

from fpl_engine.data.http_cache import (
    CacheRequest, CachedHttpResponse, HttpCache, HttpCacheError, HttpResponse,
)
from fpl_engine.data.raw_store import RawSnapshot, RawStore, RawStoreError


DEFAULT_BASE_URL = "https://raw.githubusercontent.com/Randdalf/fplcache"
_PROVIDER = "fplcache"
_PATH = re.compile(
    r"cache/(\d{4})/(\d{1,2})/(\d{1,2})/((?:[01]\d|2[0-3])[0-5]\d)\.json\.xz",
    re.ASCII,
)
_REF_PART = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*", re.ASCII)


class FPLCacheError(Exception):
    """Base error for fplcache snapshot acquisition and selection."""


class FPLCacheValidationError(FPLCacheError):
    """Invalid archive index, repository reference, clock or timestamp."""


class FPLCacheNoSnapshotError(FPLCacheError):
    """The index has no snapshot strictly earlier than the requested cutoff."""


class FPLCacheRequestError(FPLCacheError):
    """A synchronous HTTP request failed; the transport cause is chained."""


class FPLCacheResponseError(FPLCacheError):
    """A non-2xx response or incompatible decompressed bootstrap root."""


class FPLCacheParseError(FPLCacheResponseError):
    """A cached xz body cannot be safely decompressed or parsed as JSON."""


class FPLCacheStorageError(FPLCacheError):
    """Raw evidence or operational cache failed safely; cause is chained."""


def _to_utc(value: datetime, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise FPLCacheValidationError(f"{name} must be an aware datetime")
    return value.astimezone(timezone.utc)


def _validate_ref(repository_ref: str) -> str:
    if type(repository_ref) is not str or not repository_ref or len(repository_ref) > 255:
        raise FPLCacheValidationError("repository_ref must be a non-empty safe Git ref")
    devices = {"CON", "PRN", "AUX", "NUL"} | {
        f"{prefix}{number}" for prefix in ("COM", "LPT") for number in range(1, 10)
    }
    if any(not _REF_PART.fullmatch(part) or part.upper() in devices
           for part in repository_ref.split("/")):
        raise FPLCacheValidationError("repository_ref must be a safe Git ref")
    return repository_ref


@dataclass(frozen=True, order=True)
class FPLCacheSnapshotReference:
    """One verified archive path and the UTC time encoded by its path."""

    snapshot_timestamp: datetime
    path: str = field(compare=False)

    @classmethod
    def from_path(cls, path: str) -> "FPLCacheSnapshotReference":
        if type(path) is not str:
            raise FPLCacheValidationError("snapshot path must be a string")
        match = _PATH.fullmatch(path)
        if match is None:
            raise FPLCacheValidationError("snapshot path must be cache/YYYY/M/D/HHMM.json.xz")
        year, month, day, hour_minute = match.groups()
        try:
            timestamp = datetime(
                int(year), int(month), int(day), int(hour_minute[:2]), int(hour_minute[2:]),
                tzinfo=timezone.utc,
            )
        except ValueError as exc:
            raise FPLCacheValidationError("snapshot path contains an invalid UTC date/time") from exc
        return cls(snapshot_timestamp=timestamp, path=path)


def _build_index(
    snapshot_index: Iterable[str | FPLCacheSnapshotReference],
) -> tuple[FPLCacheSnapshotReference, ...]:
    if isinstance(snapshot_index, (str, bytes)):
        raise FPLCacheValidationError("snapshot_index must be an iterable of paths/references")
    try:
        references = tuple(FPLCacheSnapshotReference.from_path(value.path)
                           if isinstance(value, FPLCacheSnapshotReference)
                           else FPLCacheSnapshotReference.from_path(value)
                           for value in snapshot_index)
    except TypeError as exc:
        raise FPLCacheValidationError("snapshot_index must be iterable") from exc
    if len({reference.path for reference in references}) != len(references):
        raise FPLCacheValidationError("snapshot_index contains duplicate paths")
    if len({reference.snapshot_timestamp for reference in references}) != len(references):
        raise FPLCacheValidationError("snapshot_index contains ambiguous snapshot timestamps")
    return tuple(sorted(references))


@dataclass(frozen=True)
class FPLCacheSnapshot:
    """Frozen provider result containing faithful bootstrap data and timing metadata.

    ``snapshot_timestamp`` is the UTC time encoded by the source archive path and
    is the availability cutoff used for selection. ``prediction_timestamp`` is
    the caller's target cutoff. ``retrieved_at`` is when this system obtained the
    remote bytes (or the cache's original write time on a hit). They are distinct
    values. The payload is a freshly parsed mutable mapping with all provider
    fields preserved; this adapter creates no canonical features or identities.
    """

    snapshot_timestamp: datetime
    prediction_timestamp: datetime
    repository_ref: str
    snapshot_path: str
    source_url: str
    retrieved_at: datetime
    raw_snapshot: RawSnapshot | None
    data: dict[str, Any] = field(repr=False)
    response: CachedHttpResponse = field(repr=False)

    @property
    def from_cache(self) -> bool:
        return self.response.from_cache


class FPLCacheAdapter:
    """Read explicit-index historical bootstrap snapshots through cache and RawStore.

    Discovery is intentionally caller-supplied as a verified index of current
    fplcache relative paths. This avoids an undocumented GitHub directory crawl,
    keeps test selection deterministic, and lets a caller pin the exact archive
    listing alongside a commit SHA. Selectors use only the source path timestamp:
    the latest ``snapshot_timestamp < prediction_timestamp`` wins; equality and
    future snapshots are never eligible.

    Every successful selected remote ``.xz`` response is stored byte-for-byte in
    RawStore before decompression. The same compressed bytes are held by HttpCache
    under namespace ``fplcache``. No retries, GitHub API, repository traversal,
    canonical conversion or feature/leakage decision is included here.
    """

    def __init__(
        self, *, client: httpx.Client, cache: HttpCache, raw_store: RawStore,
        repository_ref: str, snapshot_index: Iterable[str | FPLCacheSnapshotReference],
        ttl: timedelta | None, base_url: str = DEFAULT_BASE_URL, timeout: float = 10.0,
        clock: Callable[[], datetime] | None = None,
        max_decompressed_bytes: int = 64 * 1024 * 1024,
    ):
        if not callable(getattr(client, "get", None)):
            raise FPLCacheValidationError("client must provide synchronous get()")
        if not isinstance(cache, HttpCache) or not isinstance(raw_store, RawStore):
            raise FPLCacheValidationError("Expected HttpCache and RawStore instances")
        if ttl is not None and (type(ttl) is not timedelta or ttl < timedelta(0)):
            raise FPLCacheValidationError("ttl must be None or a non-negative timedelta")
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
            raise FPLCacheValidationError("timeout must be finite positive seconds")
        if clock is not None and not callable(clock):
            raise FPLCacheValidationError("clock must be callable")
        if type(max_decompressed_bytes) is not int or max_decompressed_bytes < 1:
            raise FPLCacheValidationError("max_decompressed_bytes must be a positive integer")
        if type(base_url) is not str or "?" in base_url or "#" in base_url:
            raise FPLCacheValidationError("base_url must be an HTTP URL without query or fragment")
        try:
            CacheRequest(_PROVIDER, "GET", base_url)
        except HttpCacheError as exc:
            raise FPLCacheValidationError("Invalid raw-file base_url") from exc
        self._client = client
        self._cache = cache
        self._raw_store = raw_store
        self.repository_ref = _validate_ref(repository_ref)
        self._index = _build_index(snapshot_index)
        self._ttl = ttl
        self._base_url = base_url.rstrip("/")
        self._timeout = float(timeout)
        self._clock = clock if clock is not None else lambda: datetime.now(timezone.utc)
        self._max_decompressed_bytes = max_decompressed_bytes

    @property
    def snapshot_index(self) -> tuple[FPLCacheSnapshotReference, ...]:
        """Sorted immutable archive index retained exactly as validated."""
        return self._index

    def select_snapshot(self, prediction_timestamp: datetime) -> FPLCacheSnapshotReference:
        """Select the latest archive snapshot strictly before the UTC cutoff."""
        prediction_timestamp = _to_utc(prediction_timestamp, "prediction_timestamp")
        candidates = (item for item in self._index if item.snapshot_timestamp < prediction_timestamp)
        selected = max(candidates, default=None)
        if selected is None:
            raise FPLCacheNoSnapshotError(
                "No fplcache snapshot exists strictly before the prediction timestamp"
            )
        return selected

    def get_snapshot_before(self, prediction_timestamp: datetime) -> FPLCacheSnapshot:
        """Select then obtain/decompress/parse one bootstrap snapshot safely."""
        prediction_timestamp = _to_utc(prediction_timestamp, "prediction_timestamp")
        reference = self.select_snapshot(prediction_timestamp)
        url = f"{self._base_url}/{self.repository_ref}/{reference.path}"
        source_record_id = f"{self.repository_ref}:{reference.path}"
        request = CacheRequest(_PROVIDER, "GET", url)
        snapshot = None

        def fetch() -> HttpResponse:
            nonlocal snapshot
            try:
                network_response = self._client.get(url, timeout=self._timeout, follow_redirects=False)
            except httpx.TimeoutException as exc:
                raise FPLCacheRequestError("fplcache request timed out for selected snapshot") from exc
            except httpx.RequestError as exc:
                raise FPLCacheRequestError("fplcache transport failed for selected snapshot") from exc
            if not 200 <= network_response.status_code < 300:
                raise FPLCacheResponseError(
                    f"fplcache HTTP {network_response.status_code} for {reference.path}"
                )
            body = network_response.content
            snapshot = self._raw_store.store_bytes(
                body, source_provider=_PROVIDER, entity="bootstrap_snapshot",
                retrieved_at=self._retrieved_at(), source_url=request.redacted_url,
                source_record_id=source_record_id,
            )
            return HttpResponse(status_code=network_response.status_code,
                                body=body, headers=network_response.headers)

        try:
            response = self._cache.get_or_fetch(request, fetch, ttl=self._ttl)
        except (RawStoreError, HttpCacheError) as exc:
            raise FPLCacheStorageError("fplcache storage failed for selected snapshot") from exc
        data = _parse_bootstrap(response.body, self._max_decompressed_bytes)
        return FPLCacheSnapshot(
            snapshot_timestamp=reference.snapshot_timestamp,
            prediction_timestamp=prediction_timestamp, repository_ref=self.repository_ref,
            snapshot_path=reference.path, source_url=request.redacted_url,
            retrieved_at=snapshot.retrieved_at if snapshot is not None else response.stored_at,
            raw_snapshot=snapshot, data=data, response=response,
        )

    def _retrieved_at(self) -> datetime:
        return _to_utc(self._clock(), "clock result")


def _parse_bootstrap(body: bytes, maximum: int) -> dict[str, Any]:
    if not body:
        raise FPLCacheParseError("Empty fplcache xz body")
    try:
        decompressor = lzma.LZMADecompressor(format=lzma.FORMAT_XZ)
        data = decompressor.decompress(body, max_length=maximum + 1)
        if not decompressor.eof or decompressor.unused_data or len(data) > maximum:
            raise ValueError("incomplete, concatenated or oversized xz stream")
        parsed = json.loads(data.decode("utf-8"), parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
    except (lzma.LZMAError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        raise FPLCacheParseError("Invalid fplcache xz bootstrap payload") from exc
    if not isinstance(parsed, dict):
        raise FPLCacheResponseError("fplcache bootstrap payload must have an object root")
    return parsed
