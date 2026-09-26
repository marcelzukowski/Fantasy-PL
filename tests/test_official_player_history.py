from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path
from types import SimpleNamespace

from fpl_engine.data.raw_store import RawStore
from fpl_engine.planning.official_player_history import (
    OfficialPlayerHistoryAcquirer, write_official_player_history_acquisition,
)

NOW = datetime(2026, 9, 26, 10, tzinfo=timezone.utc)


def _bundle(tmp_path: Path):
    rows = [
        {"player_id": "a", "provider_id": "1"}, {"player_id": "b", "provider_id": "2"},
        {"player_id": "target", "provider_id": "3"},
    ]
    (tmp_path / "current_players.json").write_text(json.dumps(rows), encoding="utf-8")
    (tmp_path / "candidate_pool.json").write_text(json.dumps([
        {"player_id": "target", "weighted_ev_next_6": 12.0}, {"player_id": "b", "weighted_ev_next_6": 9.0},
    ]), encoding="utf-8")


def _response(payload, *, cache=False, checksum="x", raw=None):
    return SimpleNamespace(payload=payload, from_cache=cache, raw_snapshot=raw, response=SimpleNamespace(
        checksum=checksum, cache_key="key-" + checksum, stored_at=NOW,
    ))


class FakeAdapter:
    def __init__(self, fixture, summaries, *, fail=()):
        self.fixture, self.summaries, self.fail = fixture, summaries, set(fail)
        self.fixture_calls = 0; self.player_calls = []
    def get_fixtures(self):
        self.fixture_calls += 1
        return self.fixture
    def get_element_summary(self, player_id):
        self.player_calls.append(player_id)
        if player_id in self.fail: raise RuntimeError("offline")
        return self.summaries[player_id]


def test_fresh_acquisition_deduplicates_and_writes_raw_provenance(tmp_path: Path):
    _bundle(tmp_path); raw = RawStore(tmp_path / "raw")
    fixture_raw = raw.store_bytes(b"fixture", source_provider="official_fpl_api", entity="fixtures", retrieved_at=NOW)
    player_raw = {number: raw.store_bytes(f"p{number}".encode(), source_provider="official_fpl_api", entity="element_summary", source_record_id=str(number), retrieved_at=NOW) for number in (1,2,3)}
    fixture = _response([{"id": 11, "finished": True, "kickoff_time": (NOW-timedelta(days=2)).isoformat()}], checksum=fixture_raw.checksum, raw=fixture_raw)
    summaries = {number: _response({"history": [{"fixture": 11, "round": 5, "minutes": 90, "starts": 1}]}, checksum=player_raw[number].checksum, raw=player_raw[number]) for number in (1,2,3)}
    adapter = FakeAdapter(fixture, summaries)
    result = OfficialPlayerHistoryAcquirer(adapter=adapter, raw_store=raw, clock=lambda: NOW).refresh(
        bundle_directory=tmp_path, season="2026/27", gameweek=6, squad_player_ids=("a", "a", "b"), top_targets=1,
    )
    assert adapter.player_calls == [1, 2, 3]
    assert result.statistics["network_requests"] == 4
    assert result.statistics["appearance_rows"] == 3
    assert all(row["started"] is True for row in result.appearances)
    target = write_official_player_history_acquisition(tmp_path, result)
    assert target.name.startswith("player_minutes_history_records_")
    assert json.loads(target.read_text(encoding="utf-8"))["raw_source_references"]["a"]["raw_snapshot_id"] == player_raw[1].snapshot_id


def test_cache_hit_reuses_existing_raw_receipts_without_network_count(tmp_path: Path):
    _bundle(tmp_path); raw = RawStore(tmp_path / "raw")
    fixture_raw = raw.store_bytes(b"fixture", source_provider="official_fpl_api", entity="fixtures", retrieved_at=NOW)
    player_raw = raw.store_bytes(b"player", source_provider="official_fpl_api", entity="element_summary", source_record_id="1", retrieved_at=NOW)
    fixture = _response([{"id": 11, "finished": True, "kickoff_time": (NOW-timedelta(days=2)).isoformat()}], cache=True, checksum=fixture_raw.checksum)
    summaries = {1: _response({"history": [{"fixture": 11, "round": 5, "minutes": 62}]}, cache=True, checksum=player_raw.checksum)}
    result = OfficialPlayerHistoryAcquirer(adapter=FakeAdapter(fixture, summaries), raw_store=raw, clock=lambda: NOW).refresh(
        bundle_directory=tmp_path, season="2026/27", gameweek=6, squad_player_ids=("a",), top_targets=0,
    )
    assert result.statistics["cache_hits"] == 2 and result.statistics["network_requests"] == 0
    assert result.raw_source_references["a"]["raw_snapshot_id"] == player_raw.snapshot_id
    assert result.appearances[0]["started"] is None


def test_partial_or_complete_provider_failure_is_advisory(tmp_path: Path):
    _bundle(tmp_path); raw = RawStore(tmp_path / "raw")
    fixture_raw = raw.store_bytes(b"fixture", source_provider="official_fpl_api", entity="fixtures", retrieved_at=NOW)
    player_raw = raw.store_bytes(b"player", source_provider="official_fpl_api", entity="element_summary", source_record_id="1", retrieved_at=NOW)
    fixture = _response([{"id": 11, "finished": True, "kickoff_time": (NOW-timedelta(days=2)).isoformat()}], checksum=fixture_raw.checksum, raw=fixture_raw)
    summary = _response({"history": [{"fixture": 11, "minutes": 90}]}, checksum=player_raw.checksum, raw=player_raw)
    result = OfficialPlayerHistoryAcquirer(adapter=FakeAdapter(fixture, {1: summary, 2: summary}, fail=(2,)), raw_store=raw, clock=lambda: NOW).refresh(
        bundle_directory=tmp_path, season="2026/27", gameweek=6, squad_player_ids=("a", "b"), top_targets=0,
    )
    assert result.statistics["successes"] == 1 and result.statistics["failures"] == 1
    assert "b" in result.failures and result.appearances

def test_fixture_failure_is_explicitly_unavailable_without_player_requests(tmp_path: Path):
    _bundle(tmp_path); raw = RawStore(tmp_path / "raw")
    class BrokenFixture(FakeAdapter):
        def get_fixtures(self): raise RuntimeError("offline")
    result = OfficialPlayerHistoryAcquirer(
        adapter=BrokenFixture(None, {}), raw_store=raw, clock=lambda: NOW,
    ).refresh(bundle_directory=tmp_path, season="2026/27", gameweek=6, squad_player_ids=("a",), top_targets=0)
    assert result.appearances == () and result.statistics["successes"] == 0
    assert "fixture completion state unavailable" in result.warnings[0]


def test_extra_frozen_player_ids_are_deduplicated_without_expanding_target_ranking(tmp_path: Path):
    _bundle(tmp_path); raw = RawStore(tmp_path / "raw")
    fixture_raw = raw.store_bytes(b"fixture", source_provider="official_fpl_api", entity="fixtures", retrieved_at=NOW)
    player_raw = {
        number: raw.store_bytes(f"p{number}".encode(), source_provider="official_fpl_api",
            entity="element_summary", source_record_id=str(number), retrieved_at=NOW)
        for number in (1, 2, 3)
    }
    fixture = _response([{"id": 11, "finished": True, "kickoff_time": (NOW-timedelta(days=2)).isoformat()}],
                        checksum=fixture_raw.checksum, raw=fixture_raw)
    summaries = {
        number: _response({"history": [{"fixture": 11, "round": 5, "minutes": 90}]},
                          checksum=player_raw[number].checksum, raw=player_raw[number])
        for number in (1, 2, 3)
    }
    adapter = FakeAdapter(fixture, summaries)
    result = OfficialPlayerHistoryAcquirer(adapter=adapter, raw_store=raw, clock=lambda: NOW).refresh(
        bundle_directory=tmp_path, season="2026/27", gameweek=6, squad_player_ids=("a",),
        top_targets=0, extra_player_ids=("target", "target", "a"),
    )
    assert result.requested_player_ids == ("a", "target")
    assert adapter.player_calls == [1, 3]
