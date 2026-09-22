"""Transport-independent operational HTTP cache; separate from raw evidence.

Entries are uncompressed ZIPs containing exact response bytes and JSON metadata.
Publishing one complete file makes refresh atomic without two-file transactions.
No HTTP requests, retries, automatic logging or RawStore integration occur here.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path, PureWindowsPath
import re
from tempfile import NamedTemporaryFile
from threading import RLock
from types import MappingProxyType
from typing import Annotated, Any, Literal, Self
from urllib.parse import parse_qsl, urlencode, urlsplit
from zipfile import BadZipFile, ZIP_STORED, ZipFile, ZipInfo

from pydantic import (
    AfterValidator, AwareDatetime, BaseModel, ConfigDict, Field,
    model_validator,
)


class HttpCacheError(Exception):
    """Base error for HTTP cache operations."""


class HttpCacheValidationError(HttpCacheError):
    """Invalid request identity, response, policy, clock or unsafe path."""


class HttpCacheReadError(HttpCacheError):
    """The filesystem could not read an entry."""


class HttpCacheWriteError(HttpCacheError):
    """The filesystem could not publish or invalidate an entry."""


class HttpCacheIntegrityError(HttpCacheError):
    """An entry's container, metadata or body is inconsistent."""


_SAFE_HEADERS = frozenset({"content-type", "etag", "last-modified", "cache-control"})
_METHOD = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+", re.ASCII)
_NAMESPACE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_-]{0,63}", re.ASCII)
_DEVICES = {"CON", "PRN", "AUX", "NUL"} | {
    f"{prefix}{number}" for prefix in ("COM", "LPT") for number in range(1, 10)
}
# Close Python file handles before replace/unlink on Windows, across instances.
# Fetchers and serialization run outside this short process-local I/O lock.
_IO_LOCK = RLock()


def _json_bytes(value: Any) -> bytes:
    def check(item: Any) -> None:
        if type(item) is dict:
            if any(type(key) is not str for key in item):
                raise HttpCacheValidationError("JSON keys must be strings")
            for child in item.values():
                check(child)
        elif type(item) is list:
            for child in item:
                check(child)
        elif item is not None and type(item) not in (str, int, float, bool):
            raise HttpCacheValidationError("Expected JSON-compatible values")

    try:
        check(value)
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, RecursionError) as exc:
        # Do not interpolate caller values into errors (they may be secrets).
        raise HttpCacheValidationError("Cannot encode JSON identity/metadata") from exc


@dataclass(frozen=True, init=False)
class CacheRequest:
    """Validated identity, retaining only a hash and redacted description.

    Params are a mapping or sequence of (str, str|int) pairs. Query names sort
    stably; repeated values keep their order. Query encoding follows UTF-8 form
    conventions. URL authority/path spelling is preserved; userinfo, fragments,
    controls and malformed percent escapes are rejected. JSON bodies sort keys;
    bytes, text, JSON and absent bodies have distinct identity tags.

    sensitive_params is explicit and case-sensitive, covering URL and params.
    It affects only redaction, not the fingerprint. No request headers are
    accepted. Use non-secret vary discriminators for account/header variation.
    The caller retains the original URL/body for its transport.
    """

    namespace: str
    method: str
    redacted_url: str
    cache_key: str

    def __init__(
        self, namespace: str, method: str, url: str, *,
        params: Mapping[str, str | int] | Sequence[tuple[str, str | int]] | None = None,
        body: Any = None, vary: Mapping[str, str] | None = None,
        sensitive_params: Sequence[str] | frozenset[str] = (),
    ):
        if (type(namespace) is not str or not _NAMESPACE.fullmatch(namespace)
                or namespace.upper() in _DEVICES):
            raise HttpCacheValidationError("Unsafe cache namespace")
        if type(method) is not str or not _METHOD.fullmatch(method):
            raise HttpCacheValidationError("Invalid HTTP method")
        if (type(url) is not str or not url or "#" in url
                or re.search(r"[\x00-\x20\x7f\\]", url)
                or re.search(r"%(?![0-9A-Fa-f]{2})", url)):
            raise HttpCacheValidationError("Invalid HTTP URL")
        try:
            parts = urlsplit(url)
            if (parts.scheme not in {"http", "https"} or not parts.hostname
                    or parts.username is not None or parts.password is not None):
                raise HttpCacheValidationError("Expected HTTP URL without userinfo")
            parts.port  # Validate a supplied port without normalizing authority.
            pairs = parse_qsl(parts.query, keep_blank_values=True,
                              encoding="utf-8", errors="strict")
        except ValueError as exc:
            raise HttpCacheValidationError("Invalid HTTP URL/query") from exc
        if (not isinstance(sensitive_params, (list, tuple, set, frozenset))
                or any(type(name) is not str for name in sensitive_params)):
            raise HttpCacheValidationError("sensitive_params must contain query names")
        if params is not None:
            if not isinstance(params, (Mapping, list, tuple)):
                raise HttpCacheValidationError("Invalid query parameters")
            for pair in (params.items() if isinstance(params, Mapping) else params):
                if (not isinstance(pair, (tuple, list)) or len(pair) != 2
                        or type(pair[0]) is not str or type(pair[1]) not in (str, int)):
                    raise HttpCacheValidationError("Query pairs require str names and str/int values")
                pairs.append((pair[0], str(pair[1])))
        pairs.sort(key=lambda pair: pair[0])  # Preserve order within repeated names.
        if vary is not None and (not isinstance(vary, Mapping) or any(
            type(key) is not str or type(value) is not str for key, value in vary.items()
        )):
            raise HttpCacheValidationError("vary must map strings to strings")
        if body is None:
            body_kind, body_bytes = "none", b""
        elif type(body) is bytes:
            body_kind, body_bytes = "bytes", body
        elif type(body) is str:
            body_kind, body_bytes = "text", _json_bytes(body)
        else:
            body_kind, body_bytes = "json", _json_bytes(body)
        base_url = url.split("?", 1)[0]
        identity = {
            "identity_version": 1, "namespace": namespace, "method": method.upper(),
            "url": base_url, "query": [list(pair) for pair in pairs],
            "body_kind": body_kind, "body_sha256": hashlib.sha256(body_bytes).hexdigest(),
            "vary": dict(vary) if vary is not None else {},
        }
        key = hashlib.sha256(_json_bytes(identity)).hexdigest()
        redacted = [(name, "[REDACTED]" if name in sensitive_params else value)
                    for name, value in pairs]
        object.__setattr__(self, "namespace", namespace)
        object.__setattr__(self, "method", method.upper())
        object.__setattr__(self, "cache_key", key)
        object.__setattr__(self, "redacted_url", base_url + ("?" + urlencode(redacted) if pairs else ""))


def _safe_headers(headers: Mapping[str, str]) -> Mapping[str, str]:
    if not isinstance(headers, Mapping):
        raise HttpCacheValidationError("Response headers must be a mapping")
    safe = {}
    for name, value in headers.items():
        if type(name) is not str or type(value) is not str:
            raise HttpCacheValidationError("Response headers require string names and values")
        name = name.lower()
        if name in _SAFE_HEADERS:
            if name in safe and safe[name] != value:
                raise HttpCacheValidationError("Conflicting case-insensitive response headers")
            if "\r" in value or "\n" in value:
                raise HttpCacheValidationError("Invalid response header value")
            safe[name] = value
    return MappingProxyType(dict(sorted(safe.items())))


@dataclass(frozen=True, kw_only=True)
class HttpResponse:
    """Small fetcher result; exact bytes and a copied, immutable header allowlist."""

    status_code: int
    body: bytes = field(repr=False)
    headers: Mapping[str, str] = field(default_factory=dict, repr=False)

    def __post_init__(self):
        if type(self.status_code) is not int or not 100 <= self.status_code <= 599:
            raise HttpCacheValidationError("HTTP status must be an integer from 100 to 599")
        if type(self.body) is not bytes:
            raise HttpCacheValidationError("Response body must be exact bytes")
        object.__setattr__(self, "headers", _safe_headers(self.headers))


@dataclass(frozen=True, kw_only=True)
class CachedHttpResponse(HttpResponse):
    """Immutable result; from_cache is false after put/fetch, true after a hit."""

    cache_key: str
    namespace: str
    stored_at: datetime
    expires_at: datetime | None
    content_length: int
    checksum: str
    from_cache: bool


class CacheState(str, Enum):
    MISS = "MISS"
    HIT_FRESH = "HIT_FRESH"
    HIT_STALE = "HIT_STALE"


@dataclass(frozen=True)
class CacheLookup:
    state: CacheState
    response: CachedHttpResponse | None = None


_UTCDateTime = Annotated[AwareDatetime, AfterValidator(lambda dt: dt.astimezone(timezone.utc))]
_Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


class _Metadata(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="forbid", hide_input_in_errors=True)

    metadata_version: Literal[1] = 1
    cache_key: _Digest
    namespace: str
    request_method: str
    request_url: str
    request_fingerprint: _Digest
    status_code: int = Field(ge=200, le=299)
    headers: dict[str, str]
    stored_at: _UTCDateTime
    expires_at: _UTCDateTime | None
    body_checksum: _Digest
    checksum_algorithm: Literal["sha256"] = "sha256"
    content_length: int = Field(ge=0)
    payload_path: Literal["response.bin"] = "response.bin"  # Relative to the ZIP.

    @model_validator(mode="after")
    def _validate_entry(self) -> Self:
        if self.expires_at is not None and self.expires_at < self.stored_at:
            raise ValueError("Expiry precedes storage")
        if self.headers != dict(_safe_headers(self.headers)):
            raise ValueError("Non-canonical response headers")
        return self


def _comparison_path(path: Path) -> Path | PureWindowsPath:
    # Match RawStore's Windows extended-prefix handling without private imports.
    if os.name == "nt":
        text = str(path)
        if text.startswith("\\\\?\\UNC\\"):
            text = "\\\\" + text[8:]
        elif text.startswith("\\\\?\\"):
            text = text[4:]
        return PureWindowsPath(text)
    return path


def _validate_ttl(ttl: timedelta | None) -> None:
    if ttl is not None and (type(ttl) is not timedelta or ttl < timedelta(0)):
        raise HttpCacheValidationError("ttl must be None (immutable) or a non-negative timedelta")


class HttpCache:
    """Local cache under an explicit root with an injectable aware UTC clock.

    ttl=None means immutable; ttl=0 means immediately stale. Only 2xx responses
    are persisted. HTTP Cache-Control is recorded but not interpreted: callers
    choose whether a resource can be cached and supply policy explicitly.

    An fsynced, closed temporary ZIP is published by os.replace on the same
    filesystem. Readers consume a single complete file. Threads across cache
    instances share a short I/O lock; simultaneous misses may both fetch. Other
    processes use atomic replacement too, but Windows sharing violations may
    fail a writer explicitly. No power-loss directory durability is promised.
    Resolved paths must stay inside root; hostile concurrent link replacement
    is outside this local layer's guarantees.
    """

    def __init__(self, root: Path, *, clock: Callable[[], datetime] | None = None):
        try:
            self.root = Path(root).resolve()
        except (TypeError, OSError, RuntimeError) as exc:
            raise HttpCacheValidationError("Cannot resolve cache root") from exc
        if clock is not None and not callable(clock):
            raise HttpCacheValidationError("clock must be callable")
        self._clock = clock if clock is not None else lambda: datetime.now(timezone.utc)

    def _now(self) -> datetime:
        now = self._clock()
        if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
            raise HttpCacheValidationError("clock must return an aware datetime")
        return now.astimezone(timezone.utc)

    def _path(self, request: CacheRequest) -> Path:
        if not isinstance(request, CacheRequest):
            raise HttpCacheValidationError("Expected CacheRequest")
        key = request.cache_key
        candidate = self.root / request.namespace / key[:2] / f"{key}.zip"
        try:
            resolved = candidate.resolve()
        except (OSError, RuntimeError) as exc:
            raise HttpCacheValidationError("Cannot resolve cache path") from exc
        if not _comparison_path(resolved).is_relative_to(_comparison_path(self.root)):
            raise HttpCacheValidationError("Cache path resolves outside root")
        return candidate

    def get(self, request: CacheRequest) -> CacheLookup:
        """Verify a read-only lookup; stale responses are explicitly labelled."""
        try:
            with _IO_LOCK:
                data = self._path(request).read_bytes()
        except FileNotFoundError:
            return CacheLookup(CacheState.MISS)
        except OSError as exc:
            raise HttpCacheReadError("Cannot read HTTP cache entry") from exc
        try:
            with ZipFile(BytesIO(data)) as archive:
                if sorted(archive.namelist()) != ["cache.metadata.json", "response.bin"]:
                    raise HttpCacheIntegrityError("Unexpected cache archive members")
                if any(info.compress_type != ZIP_STORED for info in archive.infolist()):
                    raise HttpCacheIntegrityError("Cache members must be uncompressed")
                metadata = _Metadata.model_validate_json(archive.read("cache.metadata.json"))
                body = archive.read("response.bin")
            if (metadata.cache_key != request.cache_key
                    or metadata.request_fingerprint != request.cache_key
                    or metadata.namespace != request.namespace
                    or metadata.request_method != request.method
                    or metadata.request_url != request.redacted_url):
                raise HttpCacheIntegrityError("Cache request identity mismatch")
            if (len(body) != metadata.content_length
                    or hashlib.sha256(body).hexdigest() != metadata.body_checksum):
                raise HttpCacheIntegrityError("Cache body checksum/length mismatch")
        except (BadZipFile, ValueError, KeyError, RuntimeError, HttpCacheValidationError) as exc:
            raise HttpCacheIntegrityError("Invalid cache container or metadata") from exc
        response = CachedHttpResponse(
            status_code=metadata.status_code, headers=metadata.headers, body=body,
            cache_key=metadata.cache_key, namespace=metadata.namespace,
            stored_at=metadata.stored_at, expires_at=metadata.expires_at,
            content_length=metadata.content_length, checksum=metadata.body_checksum,
            from_cache=True,
        )
        stale = response.expires_at is not None and self._now() >= response.expires_at
        return CacheLookup(CacheState.HIT_STALE if stale else CacheState.HIT_FRESH, response)

    def put(
        self, request: CacheRequest, response: HttpResponse, *, ttl: timedelta | None,
    ) -> CachedHttpResponse:
        """Store a 2xx response, replacing any old entry; other statuses pass through.

        A non-cacheable response never replaces/removes an existing entry.
        Returned from_cache=False does not claim that a non-2xx was persisted.
        """
        self._path(request)
        _validate_ttl(ttl)
        if not isinstance(response, HttpResponse):
            raise HttpCacheValidationError("Expected HttpResponse from caller/fetcher")
        now = self._now()
        try:
            expires_at = None if ttl is None else now + ttl
        except OverflowError as exc:
            raise HttpCacheValidationError("TTL exceeds datetime range") from exc
        result = CachedHttpResponse(
            status_code=response.status_code, body=response.body, headers=response.headers,
            cache_key=request.cache_key, namespace=request.namespace, stored_at=now,
            expires_at=expires_at, checksum=hashlib.sha256(response.body).hexdigest(),
            content_length=len(response.body), from_cache=False,
        )
        if not 200 <= response.status_code < 300:
            return result
        metadata = _Metadata(
            cache_key=request.cache_key, namespace=request.namespace,
            request_method=request.method, request_url=request.redacted_url,
            request_fingerprint=request.cache_key, status_code=response.status_code,
            headers=dict(response.headers), stored_at=now, expires_at=expires_at,
            body_checksum=result.checksum, content_length=result.content_length,
        )
        self._publish(request, response.body, _json_bytes(metadata.model_dump(mode="json")))
        return result

    def _publish(self, request: CacheRequest, body: bytes, metadata: bytes) -> None:
        temporary = None
        try:
            with _IO_LOCK:
                destination = self._path(request)
                destination.parent.mkdir(parents=True, exist_ok=True)
                self._path(request)
                with NamedTemporaryFile(mode="w+b", prefix=".http-", suffix=".tmp",
                                        dir=destination.parent, delete=False) as stream:
                    temporary = Path(stream.name)
                    with ZipFile(stream, "w", compression=ZIP_STORED) as archive:
                        # Fixed ZIP timestamps: only metadata uses the injected clock.
                        archive.writestr(ZipInfo("response.bin"), body)
                        archive.writestr(ZipInfo("cache.metadata.json"), metadata)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, self._path(request))
        except OSError as exc:
            raise HttpCacheWriteError("Cannot publish HTTP cache entry") from exc
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass  # Only our unpublished temporary file may remain.

    def get_or_fetch(
        self, request: CacheRequest, fetcher: Callable[[], HttpResponse], *,
        ttl: timedelta | None,
    ) -> CachedHttpResponse:
        """Return a fresh hit or call fetcher once; errors propagate without fallback."""
        _validate_ttl(ttl)
        if not callable(fetcher):
            raise HttpCacheValidationError("fetcher must be callable")
        lookup = self.get(request)
        if lookup.state is CacheState.HIT_FRESH:
            assert lookup.response is not None
            return lookup.response
        return self.put(request, fetcher(), ttl=ttl)

    def invalidate(self, request: CacheRequest) -> bool:
        """Unlink only this request's ZIP; return false if absent. No tree cleanup."""
        try:
            with _IO_LOCK:
                self._path(request).unlink()
            return True
        except FileNotFoundError:
            return False
        except OSError as exc:
            raise HttpCacheWriteError("Cannot invalidate HTTP cache entry") from exc
