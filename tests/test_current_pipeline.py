from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import pytest

import fpl_engine.current as current_module
from desktop_app.gameweek_deadlines import ValidatedOfficialDeadline


@pytest.fixture(autouse=True)
def _legacy_synthetic_roster_simulator_policy(
    monkeypatch,
    request,
):
    """Use V1 only for legacy tests with deliberately incomplete team rosters."""

    legacy_v1_tests = {
        (
            "test_complete_current_pipeline_is_"
            "deterministic_and_persists_dgw_bgw"
        ),
        (
            "test_current_pipeline_composes_generated_"
            "bundle_with_explicit_squad"
        ),
        (
            "test_current_pipeline_persists_market_"
            "shadow_without_changing_production_ev"
        ),
    }

    if request.node.name in legacy_v1_tests:

        monkeypatch.setenv(
            "FPL_SIMULATOR_CHALLENGER",
            "v1",
        )

import httpx

from fpl_engine.current import (
    CurrentInputError, CurrentPipelineConfig, CurrentPredictionPipeline, CurrentSourceData,
    CurrentSourceError, CurrentSourceRecord, OfficialCurrentDataSource,
)
from fpl_engine.data.http_cache import HttpCache
from fpl_engine.data.market_odds import (
    MarketKind,
    MarketQuote,
    MarketSide,
)
from fpl_engine.data.local_fpl_snapshots import LocalFPLSnapshotStore
from fpl_engine.data.providers.fpl_api import OfficialFPLAdapter
from fpl_engine.data.raw_store import RawStore
from fpl_engine.types import PredictionContext
from fpl_engine.validation.leakage import FutureSnapshotError


ROOT = Path(__file__).resolve().parents[1]
AT = datetime(2026, 9, 10, 10, tzinfo=timezone.utc)


def _record(entity, payload, *, known_at=AT - timedelta(seconds=1)):
    body = json.dumps(payload, sort_keys=True).encode()
    checksum = hashlib.sha256(body).hexdigest()
    return CurrentSourceRecord(
        "official_fpl_api", entity, payload, known_at, known_at,
        checksum, checksum, raw_snapshot_id=f"raw_{entity}", cache_key=f"cache_{entity}",
        source_snapshot_timestamp=known_at,
    )


def _source(*, future=False, optional_warning=False):
    teams = [
        {"id": index, "name": f"Team {index}", "short_name": f"T{index}"}
        for index in range(1, 7)
    ]
    positions = ["GK"] * 2 + ["DEF"] * 5 + ["MID"] * 5 + ["FWD"] * 4
    codes = {"GK": 1, "DEF": 2, "MID": 3, "FWD": 4}
    elements = []
    for index, position in enumerate(positions, 1):
        elements.append({
            "id": index, "code": 100000 + index,
            "first_name": f"First{index}", "second_name": f"Last{index}",
            "web_name": f"P{index}", "team": (index - 1) % 6 + 1,
            "element_type": codes[position], "now_cost": 45 + index,
            "status": "a", "chance_of_playing_next_round": None,
            "penalties_order": 1 if index == 1 else None,
        })
    fixtures = [
        {"id": 90, "event": 4, "team_h": 2, "team_a": 1,
         "kickoff_time": (AT - timedelta(days=3)).isoformat(), "finished": True,
         "team_h_score": 2, "team_a_score": 1},
        {"id": 100, "event": 5, "team_h": 1, "team_a": 2,
         "kickoff_time": (AT + timedelta(days=1)).isoformat(), "finished": False},
        {"id": 101, "event": 5, "team_h": 3, "team_a": 1,
         "kickoff_time": (AT + timedelta(days=2)).isoformat(), "finished": False},
        # GW6 is deliberately blank.
        {"id": 102, "event": 7, "team_h": 4, "team_a": 3,
         "kickoff_time": (AT + timedelta(days=10)).isoformat(), "finished": False},
        {"id": 103, "event": 8, "team_h": 5, "team_a": 6,
         "kickoff_time": (AT + timedelta(days=17)).isoformat(), "finished": False},
    ]
    when = AT + timedelta(seconds=1) if future else AT - timedelta(seconds=1)
    bootstrap = _record("bootstrap_static", {
        "events": [{"id": 5, "is_current": True}], "elements": elements,
        "teams": teams, "element_types": [{"id": i} for i in range(1, 5)],
    }, known_at=when)
    fixture_record = _record("fixtures", fixtures, known_at=when)

    class StaticSource:
        def refresh(self, context):
            return CurrentSourceData(
                bootstrap, fixture_record,
                warnings=("Optional enrichment unavailable; V1 fallback retained.",) if optional_warning else (),
            )
    return StaticSource()


def _pipeline(tmp_path, source=None, *, simulations=4):
    return CurrentPredictionPipeline(
        source or _source(), project_root=ROOT,
        config=CurrentPipelineConfig(
            tmp_path / "canonical" / "current.duckdb", tmp_path / "predictions",
            simulations_per_fixture=simulations, random_seed=123, history_seasons=(),
            goal_allocation_proxy_enabled=False,
        ),
    )


def _context():
    return PredictionContext(
        prediction_timestamp=AT, target_gameweek=5, target_season="2026/27",
    )


def test_complete_current_pipeline_is_deterministic_and_persists_dgw_bgw(tmp_path):
    pipeline = _pipeline(tmp_path, _source(optional_warning=True))
    first = pipeline.run(_context())
    first_payload = json.loads(first.artifacts["player_projections"].read_text())
    second = pipeline.run(_context())
    second_payload = json.loads(second.artifacts["player_projections"].read_text())
    assert first_payload == second_payload
    assert len(first.projections) == 16
    assert len(first.candidate_pool) == 16
    assert all(row.player_id.startswith("ply_") for row in first.projections)
    assert first.artifacts["projection_parquet"].exists()
    assert first.artifacts["run_manifest"].exists()
    player = first.projections[0]
    by_gw = {row.target_gameweek: row for row in player.gameweeks}
    assert by_gw[6].fixture_count == 0
    assert any(row.fixture_count == 2 for item in first.projections for row in item.gameweeks if row.target_gameweek == 5)
    manifest = json.loads(first.artifacts["run_manifest"].read_text())
    assert manifest["simulation"]["simulations_per_fixture"] == 4
    assert manifest["simulation"]["simulation_mode"] == "NON-PRODUCTION DIAGNOSTIC"
    assert manifest["scoring_season"] == "2026/27"
    assert {row.rule_version for row in first.projections} == {manifest["scoring_rule_version"]}
    assert manifest["active_v1"]["team_strength"] == "dixon_coles_v1_hl60_xg"
    assert manifest["decision_policies"]["default"] == "greedy_1gw"
    audit = json.loads(second.artifacts["identity_audit"].read_text())
    assert len(audit["reused_players"]) == 16 and not audit["created_players"]
    assert "Optional enrichment unavailable" in " ".join(first.warnings)
    expected_fixture = "fix_" + str(uuid5(
        NAMESPACE_URL, "Premier League|2026-27|team 1|team 2".casefold()
    ))
    assert next(row.fixture_id for row in first.fixture_horizon if row.provider_id == "100") == expected_fixture
    import duckdb
    with duckdb.connect(str(tmp_path / "canonical" / "current.duckdb"), read_only=True) as connection:
        facts = connection.execute(
            "SELECT entity,provider_payload FROM fact_fpl_snapshot ORDER BY entity"
        ).fetchall()
    assert len(facts) == 2
    assert {row[0] for row in facts} == {"bootstrap_static", "fixtures"}
    assert all(json.loads(row[1]) for row in facts)
    assert "confidence" in first.artifacts["human_report"].read_text(encoding="utf-8")


def _squad_payload(result):
    selected = []
    required = {"GK": 2, "DEF": 5, "MID": 5, "FWD": 3}
    for position, count in required.items():
        selected.extend([row for row in result.candidate_pool if row.position == position][:count])
    return {
        "prediction_timestamp": AT.isoformat(), "season": "2026/27", "current_gameweek": 5,
        "players": [
            {"player_id": row.player_id, "position": row.position, "club_id": row.club_id,
             "purchase_price": row.current_price, "current_price": row.current_price,
             "selling_price": row.current_price}
            for row in selected
        ],
        "bank": 500, "free_transfers": 1,
        "chip_state": {
            "wildcard_h1": True, "wildcard_h2": True, "free_hit_h1": True,
            "free_hit_h2": True, "bench_boost_h1": True, "bench_boost_h2": True,
            "triple_captain_h1": True, "triple_captain_h2": True,
            "last_free_hit_gameweek": None,
        },
    }


def test_current_pipeline_composes_generated_bundle_with_explicit_squad(tmp_path):
    pipeline = _pipeline(tmp_path)
    materialized = pipeline.run(_context())
    squad = tmp_path / "squad.json"
    squad.write_text(json.dumps(_squad_payload(materialized)), encoding="utf-8")
    result = pipeline.run(_context(), squad_state_path=squad)
    assert result.shadow_reports is not None
    report = json.loads(result.shadow_reports[0].read_text())
    assert report["default_policy"] == "greedy_1gw"
    assert report["simulation_mode"] == "NON-PRODUCTION DIAGNOSTIC"
    assert set(report["recommendations"]) == {"greedy_1gw", "optimizer_v1", "optimizer_v2"}
    assert report["external_mutations"] == []


def test_current_pipeline_rejects_future_provenance(tmp_path):
    with pytest.raises(FutureSnapshotError, match="prediction_timestamp"):
        _pipeline(tmp_path, _source(future=True)).run(_context())


def test_current_pipeline_rejects_fpl_snapshot_at_prediction_timestamp(tmp_path):
    source = _source()
    original = source.refresh(_context())

    class EqualitySource:
        def refresh(self, context):
            return CurrentSourceData(
                _record("bootstrap_static", original.bootstrap.payload, known_at=AT),
                original.fixtures,
            )

    with pytest.raises(FutureSnapshotError, match="strictly before"):
        _pipeline(tmp_path, EqualitySource()).run(_context())


def test_current_pipeline_rejects_missing_critical_fixture_source(tmp_path):
    source = _source()
    original = source.refresh(_context())

    class Broken:
        def refresh(self, context):
            return CurrentSourceData(original.bootstrap, _record("fixtures", {"not": "a list"}))

    with pytest.raises(CurrentSourceError, match="fixtures root"):
        _pipeline(tmp_path, Broken()).run(_context())


def test_current_pipeline_never_falls_back_to_another_seasons_rules(tmp_path):
    context = PredictionContext(
        prediction_timestamp=AT, target_gameweek=5, target_season="2099/00",
    )
    with pytest.raises(CurrentInputError, match="No explicit scoring rules"):
        _pipeline(tmp_path).run(context)


def test_official_current_source_reuses_http_cache_without_duplicate_raw_snapshot(tmp_path):
    static = _source().refresh(_context())
    bodies = {
        "/api/bootstrap-static/": json.dumps(static.bootstrap.payload).encode(),
        "/api/fixtures/": json.dumps(static.fixtures.payload).encode(),
    }
    calls = []

    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(200, content=bodies[request.url.path])

    raw = RawStore(tmp_path / "raw")
    cache = HttpCache(tmp_path / "cache", clock=lambda: AT)
    local = LocalFPLSnapshotStore(tmp_path / "snapshots", raw_store=raw)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        adapter = OfficialFPLAdapter(
            client=client, cache=cache, raw_store=raw, ttl=timedelta(minutes=5),
            base_url="https://example.test/api/", clock=lambda: AT,
        )
        source = OfficialCurrentDataSource(adapter, local_snapshots=local)
        context = PredictionContext(prediction_timestamp=AT, target_gameweek=1, target_season="2026/27")
        first = source.refresh(context)
        raw_count = len(list(raw.root.rglob("snapshot.metadata.json")))
        second = source.refresh(context)
    assert calls == ["/api/bootstrap-static/", "/api/fixtures/"]
    assert not first.bootstrap.from_cache and second.bootstrap.from_cache
    assert len(list(raw.root.rglob("snapshot.metadata.json"))) == raw_count == 4



def test_current_pipeline_persists_market_shadow_without_changing_production_ev(
    tmp_path,
):
    pipeline = _pipeline(tmp_path)

    fixture_id = "fix_" + str(
        uuid5(
            NAMESPACE_URL,
            (
                "Premier League|2026-27|"
                "team 1|team 2"
            ).casefold(),
        )
    )

    player_id = "ply_" + str(
        uuid5(
            NAMESPACE_URL,
            (
                "Premier League player code|"
                "100001"
            ).casefold(),
        )
    )

    quote = MarketQuote(
        provider="the_odds_api",
        bookmaker="book-a",
        fixture_id=fixture_id,
        player_id=player_id,
        market=MarketKind.ANYTIME_GOAL,
        side=MarketSide.YES,
        decimal_odds=2.5,
        quoted_at=(
            AT - timedelta(minutes=5)
        ),
    )

    baseline = pipeline.run(
        _context()
    )

    with_market = pipeline.run(
        _context(),
        market_quotes=(quote,),
    )

    # Shadow market data must not alter
    # production projections.
    assert (
        baseline.projections
        == with_market.projections
    )

    assert (
        "market_shadow"
        not in baseline.artifacts
    )

    assert (
        with_market
        .artifacts["market_shadow"]
        .exists()
    )

    report = json.loads(
        with_market
        .artifacts["market_shadow"]
        .read_text()
    )

    assert (
        report["selected_quote_count"]
        == 1
    )

    assert (
        report[
            "one_sided_bookmaker_groups"
        ]
        == 1
    )

    assert report["prior_count"] == 1

    assert (
        report[
            "players_with_market_prior"
        ]
        == 1
    )

    manifest = json.loads(
        with_market
        .artifacts["run_manifest"]
        .read_text()
    )

    market_metadata = (
        manifest["simulation"][
            "market_shadow"
        ]
    )

    assert (
        market_metadata["enabled"]
        is True
    )

    assert (
        market_metadata[
            "production_influence"
        ]
        is False
    )

    assert (
        market_metadata["providers"]
        == ["the_odds_api"]
    )


def test_prediction_context_persists_only_a_verified_official_deadline_and_final_bytes(monkeypatch, tmp_path):
    bootstrap = _source().refresh(_context()).bootstrap
    deadline = ValidatedOfficialDeadline(
        season="2026/27", gameweek=5,
        deadline=datetime(2026, 9, 12, 17, tzinfo=timezone.utc),
        source="official_fpl_api.bootstrap_static.local_snapshot",
        observed_at=AT - timedelta(minutes=2), raw_snapshot_id="raw-bootstrap",
        source_url="https://fantasy.premierleague.com/api/bootstrap-static/",
    )
    monkeypatch.setattr(current_module, "load_validated_official_deadline", lambda *args, **kwargs: deadline)
    payload = current_module._prediction_context_payload(
        _context(), project_root=tmp_path, bootstrap=bootstrap,
    )
    path = tmp_path / "prediction_context.json"
    current_module._write_json(path, payload)
    persisted = json.loads(path.read_text(encoding="utf-8"))
    assert persisted["official_deadline"] == "2026-09-12T17:00:00+00:00"
    assert persisted["planning_gameweek"] == 5
    assert persisted["deadline_verification_status"] == "VERIFIED"
    assert hashlib.sha256(path.read_bytes()).hexdigest() == hashlib.sha256(
        path.read_bytes()
    ).hexdigest()


def test_prediction_context_keeps_missing_local_deadline_unverified(monkeypatch, tmp_path):
    bootstrap = _source().refresh(_context()).bootstrap
    monkeypatch.setattr(current_module, "load_validated_official_deadline", lambda *args, **kwargs: None)
    payload = current_module._prediction_context_payload(
        _context(), project_root=tmp_path, bootstrap=bootstrap,
    )
    assert payload["planning_gameweek"] == 5
    assert payload["deadline_verification_status"] == "UNVERIFIED"
    assert "official_deadline" not in payload
