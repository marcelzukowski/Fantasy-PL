"""Version-pinned StatsBomb Open Data files, without canonical interpretation."""
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import json, math, re
from typing import Any
import httpx
from fpl_engine.data.http_cache import CacheRequest, CachedHttpResponse, HttpCache, HttpCacheError, HttpResponse
from fpl_engine.data.raw_store import RawSnapshot, RawStore, RawStoreError

DEFAULT_BASE_URL = "https://raw.githubusercontent.com/statsbomb/open-data"
_PROVIDER = "statsbomb_open"
_REF = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]*\Z")

class StatsBombOpenError(Exception): pass
class StatsBombOpenValidationError(StatsBombOpenError): pass
class StatsBombOpenUnavailableError(StatsBombOpenError): pass
class StatsBombOpenRequestError(StatsBombOpenError): pass
class StatsBombOpenResponseError(StatsBombOpenError): pass
class StatsBombOpenParseError(StatsBombOpenResponseError): pass
class StatsBombOpenStorageError(StatsBombOpenError): pass

def _id(v: int, name: str) -> int:
    if type(v) is not int or v < 1: raise StatsBombOpenValidationError(f"{name} must be a strictly positive integer")
    return v
def _utc(v: datetime) -> datetime:
    if not isinstance(v, datetime) or v.tzinfo is None or v.utcoffset() is None: raise StatsBombOpenValidationError("clock must return an aware datetime")
    return v.astimezone(timezone.utc)
def _json(body: bytes, name: str) -> list[Any]:
    try: data=json.loads(body, parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))
    except (UnicodeError, ValueError, RecursionError) as exc: raise StatsBombOpenParseError(f"Invalid StatsBomb JSON for {name}") from exc
    if not isinstance(data, list): raise StatsBombOpenParseError(f"StatsBomb {name} must have a list root")
    return data

@dataclass(frozen=True)
class StatsBombOpenDataset:
    dataset_name: str; repository_ref: str; source_url: str; retrieved_at: datetime
    data: list[Any] = field(repr=False); response: CachedHttpResponse = field(repr=False); raw_snapshot: RawSnapshot | None = None
    @property
    def from_cache(self) -> bool: return self.response.from_cache

class StatsBombOpenAdapter:
    """Read selected Open Data files through a caller-owned synchronous transport."""
    def __init__(self, *, client: httpx.Client, cache: HttpCache, raw_store: RawStore, repository_ref: str, ttl: timedelta|None, base_url: str=DEFAULT_BASE_URL, timeout: float=10.0, clock: Callable[[],datetime]|None=None):
        if not callable(getattr(client,"get",None)) or not isinstance(cache,HttpCache) or not isinstance(raw_store,RawStore): raise StatsBombOpenValidationError("Expected synchronous client, HttpCache and RawStore")
        if type(repository_ref) is not str or not _REF.fullmatch(repository_ref) or ".." in repository_ref.split("/"): raise StatsBombOpenValidationError("repository_ref must be safe")
        if ttl is not None and (type(ttl) is not timedelta or ttl < timedelta(0)): raise StatsBombOpenValidationError("ttl must be None or a non-negative timedelta")
        if type(timeout) not in (int,float) or not math.isfinite(timeout) or timeout<=0: raise StatsBombOpenValidationError("timeout must be finite positive seconds")
        if clock is not None and not callable(clock): raise StatsBombOpenValidationError("clock must be callable")
        try: CacheRequest(_PROVIDER,"GET",base_url)
        except HttpCacheError as exc: raise StatsBombOpenValidationError("Invalid StatsBomb base_url") from exc
        self._client,self._cache,self._raw,self.repository_ref,self._ttl,self._base,self._timeout,self._clock=client,cache,raw_store,repository_ref,ttl,base_url.rstrip("/"),float(timeout),clock or (lambda:datetime.now(timezone.utc))
    def get_competitions(self): return self._get("competitions","competitions.json")
    def get_matches(self, competition_id:int, season_id:int):
        return self._get("matches",f"matches/{_id(competition_id,'competition_id')}/{_id(season_id,'season_id')}.json")
    def get_events(self, match_id:int): return self._get("events",f"events/{_id(match_id,'match_id')}.json")
    def get_lineups(self, match_id:int): return self._get("lineups",f"lineups/{_id(match_id,'match_id')}.json")
    def _get(self, entity:str, path:str)->StatsBombOpenDataset:
        url=f"{self._base}/{self.repository_ref}/data/{path}"; request=CacheRequest(_PROVIDER,"GET",url); snapshot=None
        def fetch():
            nonlocal snapshot
            try: r=self._client.get(url,timeout=self._timeout,follow_redirects=False)
            except httpx.TimeoutException as exc: raise StatsBombOpenRequestError(f"StatsBomb request timed out for {path}") from exc
            except httpx.RequestError as exc: raise StatsBombOpenRequestError(f"StatsBomb transport failed for {path}") from exc
            if r.status_code==404: raise StatsBombOpenUnavailableError(f"StatsBomb data unavailable for {path}")
            if not 200<=r.status_code<300: raise StatsBombOpenResponseError(f"StatsBomb HTTP {r.status_code} for {path}")
            snapshot=self._raw.store_bytes(r.content,source_provider=_PROVIDER,entity=entity,retrieved_at=_utc(self._clock()),source_url=request.redacted_url,source_record_id=f"{self.repository_ref}:{path}")
            return HttpResponse(status_code=r.status_code,body=r.content,headers=r.headers)
        try: response=self._cache.get_or_fetch(request,fetch,ttl=self._ttl)
        except (RawStoreError,HttpCacheError) as exc: raise StatsBombOpenStorageError(f"StatsBomb storage failed for {path}") from exc
        return StatsBombOpenDataset(entity,self.repository_ref,request.redacted_url,snapshot.retrieved_at if snapshot else response.stored_at,_json(response.body,path),response,snapshot)
