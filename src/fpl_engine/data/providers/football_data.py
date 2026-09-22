"""football-data.co.uk historical CSV adapter; columns remain provider-native."""
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from io import BytesIO, TextIOWrapper
import csv, math, re
import pandas as pd
import httpx
from fpl_engine.data.http_cache import CacheRequest, CachedHttpResponse, HttpCache, HttpCacheError, HttpResponse
from fpl_engine.data.raw_store import RawSnapshot, RawStore, RawStoreError

DEFAULT_BASE_URL="https://www.football-data.co.uk/mmz4281"; _PROVIDER="football_data"
_SEASON=re.compile(r"\d{4}\Z"); _LEAGUE=re.compile(r"[A-Z][A-Z0-9_-]{0,15}\Z")
class FootballDataError(Exception): pass
class FootballDataValidationError(FootballDataError): pass
class FootballDataRequestError(FootballDataError): pass
class FootballDataResponseError(FootballDataError): pass
class FootballDataParseError(FootballDataResponseError): pass
class FootballDataStorageError(FootballDataError): pass
def _utc(v):
    if not isinstance(v,datetime) or v.tzinfo is None or v.utcoffset() is None: raise FootballDataValidationError("clock must return an aware datetime")
    return v.astimezone(timezone.utc)
def _validate(season,league):
    if type(season) is not str or not _SEASON.fullmatch(season): raise FootballDataValidationError("season must be a four-digit source season code")
    if type(league) is not str or not _LEAGUE.fullmatch(league): raise FootballDataValidationError("league must be a safe provider league code")
def _parse(body):
    if not body: raise FootballDataParseError("Empty football-data CSV")
    try:
        with TextIOWrapper(BytesIO(body),encoding="utf-8-sig",newline="") as s: rows=list(csv.reader(s,strict=True)); header=rows[0] if rows else []
        if not header or not any(header) or len(header)!=len(set(header)) or any(len(r)!=len(header) for r in rows[1:]): raise ValueError("invalid CSV schema")
        df=pd.read_csv(BytesIO(body),encoding="utf-8-sig",engine="python",on_bad_lines="error")
    except (UnicodeError,csv.Error,ValueError,pd.errors.ParserError) as exc: raise FootballDataParseError("Invalid football-data CSV") from exc
    if tuple(df.columns)!=tuple(header): raise FootballDataParseError("Invalid football-data CSV header")
    return df
@dataclass(frozen=True)
class FootballDataDataset:
    season:str; league:str; source_url:str; retrieved_at:datetime; columns:tuple[str,...]; data:pd.DataFrame=field(repr=False); response:CachedHttpResponse=field(repr=False); raw_snapshot:RawSnapshot|None=None
    @property
    def from_cache(self): return self.response.from_cache
    @property
    def odds_columns(self): return tuple(c for c in self.columns if re.fullmatch(r"(?:B365|BW|IW|LB|PS|WH|VC|Bb|Avg|Max)[HDA](?:C)?",c))
    @property
    def odds_point_in_time_safe(self): return False
class FootballDataAdapter:
    def __init__(self,*,client:httpx.Client,cache:HttpCache,raw_store:RawStore,ttl:timedelta|None,base_url:str=DEFAULT_BASE_URL,timeout:float=10.,clock:Callable[[],datetime]|None=None):
        if not callable(getattr(client,"get",None)) or not isinstance(cache,HttpCache) or not isinstance(raw_store,RawStore): raise FootballDataValidationError("Expected synchronous client, HttpCache and RawStore")
        if ttl is not None and (type(ttl) is not timedelta or ttl<timedelta(0)): raise FootballDataValidationError("ttl must be None or a non-negative timedelta")
        if type(timeout) not in (int,float) or not math.isfinite(timeout) or timeout<=0: raise FootballDataValidationError("timeout must be finite positive seconds")
        if clock is not None and not callable(clock): raise FootballDataValidationError("clock must be callable")
        try: CacheRequest(_PROVIDER,"GET",base_url)
        except HttpCacheError as exc: raise FootballDataValidationError("Invalid football-data base_url") from exc
        self._client,self._cache,self._raw,self._ttl,self._base,self._timeout,self._clock=client,cache,raw_store,ttl,base_url.rstrip("/"),float(timeout),clock or (lambda:datetime.now(timezone.utc))
    def get_results(self,season:str,league:str)->FootballDataDataset:
        _validate(season,league); url=f"{self._base}/{season}/{league}.csv"; request=CacheRequest(_PROVIDER,"GET",url); snapshot=None
        def fetch():
            nonlocal snapshot
            try:r=self._client.get(url,timeout=self._timeout,follow_redirects=False)
            except httpx.TimeoutException as exc:raise FootballDataRequestError(f"football-data request timed out for {season}/{league}") from exc
            except httpx.RequestError as exc:raise FootballDataRequestError(f"football-data transport failed for {season}/{league}") from exc
            if not 200<=r.status_code<300: raise FootballDataResponseError(f"football-data HTTP {r.status_code} for {season}/{league}")
            snapshot=self._raw.store_bytes(r.content,source_provider=_PROVIDER,entity="results",retrieved_at=_utc(self._clock()),source_url=request.redacted_url,source_record_id=f"{season}:{league}")
            return HttpResponse(status_code=r.status_code,body=r.content,headers=r.headers)
        try: response=self._cache.get_or_fetch(request,fetch,ttl=self._ttl)
        except (RawStoreError,HttpCacheError) as exc: raise FootballDataStorageError(f"football-data storage failed for {season}/{league}") from exc
        df=_parse(response.body); return FootballDataDataset(season,league,request.redacted_url,snapshot.retrieved_at if snapshot else response.stored_at,tuple(df.columns),df,response,snapshot)
