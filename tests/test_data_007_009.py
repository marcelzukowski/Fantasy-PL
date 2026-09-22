"""DATA-007..009: all remote interactions are httpx.MockTransport only."""
from datetime import datetime,timedelta,timezone
import json
from pathlib import Path
from types import SimpleNamespace
import httpx, pytest
from fpl_engine.data.http_cache import HttpCache
from fpl_engine.data.raw_store import RawStore
from fpl_engine.data.providers.statsbomb_open import StatsBombOpenAdapter,StatsBombOpenUnavailableError
from fpl_engine.data.providers.football_data import FootballDataAdapter,FootballDataParseError
from fpl_engine.data.providers.fpl_api import OfficialFPLAdapter
from fpl_engine.data.local_fpl_snapshots import LocalFPLSnapshotStore,LocalFPLSnapshotExistsError,LocalFPLSnapshotNotFoundError
NOW=datetime(2026,9,7,12,tzinfo=timezone.utc); REF="0123456789abcdef0123456789abcdef01234567"
@pytest.fixture
def env(tmp_path):
    s=SimpleNamespace(now=NOW,calls=[],status=200,body=b"[]",headers={})
    def handler(request):s.calls.append(request);return httpx.Response(s.status,content=s.body,headers=s.headers)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        s.client=client;s.cache=HttpCache(tmp_path/"cache",clock=lambda:s.now);s.raw=RawStore(tmp_path/"raw");yield s
def test_statsbomb_datasets_refs_missing_coverage_and_cache_raw(env):
    adapter=StatsBombOpenAdapter(client=env.client,cache=env.cache,raw_store=env.raw,repository_ref=REF,ttl=timedelta(minutes=1),clock=lambda:env.now)
    env.body=json.dumps([{"competition_id":2,"unknown":True}]).encode(); first=adapter.get_competitions(); second=adapter.get_competitions()
    assert len(env.calls)==1 and first.raw_snapshot and second.raw_snapshot is None and second.from_cache
    assert env.raw.read_bytes(first.raw_snapshot)==env.body and first.data[0]["unknown"]
    env.body=b"[]"; adapter.get_matches(2,44);adapter.get_events(77);adapter.get_lineups(77)
    assert [r.url.path for r in env.calls[1:]]==[f"/statsbomb/open-data/{REF}/data/matches/2/44.json",f"/statsbomb/open-data/{REF}/data/events/77.json",f"/statsbomb/open-data/{REF}/data/lineups/77.json"]
    env.status=404
    with pytest.raises(StatsBombOpenUnavailableError): adapter.get_matches(999,1)
    assert len(list(env.raw.root.rglob("snapshot.metadata.json"))) == 4
def test_football_data_preserves_columns_odds_and_raw_cache(env):
    body=b"Date,HomeTeam,AwayTeam,FTHG,HS,B365H,B365D,B365A,Unknown\n01/08/2025,A,B,2,9,1.2,3.0,5.0,x\n"; env.body=body
    adapter=FootballDataAdapter(client=env.client,cache=env.cache,raw_store=env.raw,ttl=timedelta(minutes=1),clock=lambda:env.now)
    first=adapter.get_results("2526","E0");second=adapter.get_results("2526","E0")
    assert list(first.columns)==["Date","HomeTeam","AwayTeam","FTHG","HS","B365H","B365D","B365A","Unknown"]
    assert first.odds_columns==("B365H","B365D","B365A") and first.odds_point_in_time_safe is False
    assert len(env.calls)==1 and first.raw_snapshot and second.raw_snapshot is None and env.raw.read_bytes(first.raw_snapshot)==body
def test_football_data_malformed_csv_is_raw_preserved_but_not_returned(env):
    env.body=b"A,A\n1,2\n"; adapter=FootballDataAdapter(client=env.client,cache=env.cache,raw_store=env.raw,ttl=timedelta(minutes=1),clock=lambda:env.now)
    with pytest.raises(FootballDataParseError):adapter.get_results("2526","E0")
    assert len(env.calls)==1 and len(list(env.raw.root.rglob("snapshot.metadata.json")))==1
def test_local_snapshot_append_only_and_strict_selection_reuses_official_result(env,tmp_path):
    env.body=b'{"events":[],"elements":[],"teams":[],"element_types":[]}'
    api=OfficialFPLAdapter(client=env.client,cache=env.cache,raw_store=env.raw,ttl=timedelta(minutes=1),clock=lambda:env.now)
    result=api.get_bootstrap_static(); store=LocalFPLSnapshotStore(tmp_path/"snapshots",raw_store=env.raw)
    first=store.capture("bootstrap_static",result,snapshot_timestamp=datetime(2026,9,7,11,tzinfo=timezone.utc))
    fixture_receipt=store.capture("fixtures",result,snapshot_timestamp=first.snapshot_timestamp)
    assert first.path.as_posix().endswith("official_fpl_api/2026-09-07T11-00-00.000000Z/bootstrap_static.snapshot.json")
    assert fixture_receipt.path.parent == first.path.parent
    assert first.checksum==result.response.checksum and store.select_before(datetime(2026,9,7,12,tzinfo=timezone.utc))==first
    with pytest.raises(LocalFPLSnapshotExistsError):store.capture("bootstrap_static",result,snapshot_timestamp=first.snapshot_timestamp)
    with pytest.raises(LocalFPLSnapshotNotFoundError):store.select_before(first.snapshot_timestamp)
