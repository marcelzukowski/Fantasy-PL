from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from types import SimpleNamespace

import httpx

from fpl_engine.current_market_shadow import (
    collect_current_gameweek_market_shadow,
)
from fpl_engine.data.http_cache import HttpCache
from fpl_engine.data.providers.the_odds_api import TheOddsApiAdapter
from fpl_engine.data.raw_store import RawStore
from fpl_engine.models.events.model import (
    AssistEvents,
    BaseBpsParameters,
    CardEvents,
    CleanSheetEvents,
    DefensiveContributionEvents,
    FixtureEventProjection,
    GoalEvents,
    GoalkeeperEvents,
    PenaltyProcess,
    PlayerFixtureEvents,
    PlayerFixtureRate,
    TeamEventProjection,
)


AT = datetime(2026, 9, 10, 10, tzinfo=timezone.utc)


def _event_projection(fixture_id: str) -> FixtureEventProjection:
    rate = PlayerFixtureRate(
        player_id="player-haaland", team_id="team-home", fixture_id=fixture_id,
        prediction_timestamp=AT, position="MID", p_appearance=1.0, p_start=1.0,
        expected_minutes=90.0, minute_distribution=((90, 1.0),),
        starter_minutes_distribution=((90, 1.0),), bench_minutes_distribution=((0, 1.0),),
        fixture_npxg_per90=0.4, fixture_penalty_xg_per90=0.0, fixture_xa_per90=0.2,
        fixture_shots_per90=2.0, fixture_shots_on_target_per90=1.0,
        fixture_defcon_per90=None, raw_expected_npxg=0.4, raw_expected_xa=0.2,
        uncertainty=0.1, confidence=0.9,
    )
    player = PlayerFixtureEvents(
        rates=rate,
        penalty=PenaltyProcess(0.0, 0.0, 0.78, 0.22, 0.0),
        goals=GoalEvents(0.4, 0.4, 0.0, 0.33, (0.67, 0.27, 0.06)),
        assists=AssistEvents(0.2, 0.18, (0.82, 0.16, 0.02)),
        clean_sheet=CleanSheetEvents(0.3, 0.3, 1.0, 1.0),
        goalkeeper=GoalkeeperEvents(None, None, None, None, None, None, None, None, False),
        defensive_contributions=(DefensiveContributionEvents(None, None),),
        cards=CardEvents(0.1, 0.01, "prior", "prior"),
        bps=BaseBpsParameters(0.4, 0.2, 0.3, None, None, 0.1, 0.01, 90.0, None, 1.0, 1.0, 1),
        uncertainty=0.1, confidence=0.9, model_version="event_models_v1",
        dataset_version="event_dataset_v1", feature_version="event_features_v1",
    )
    home = TeamEventProjection(fixture_id, "team-home", AT, 1.5, 0.4, 1.1, 0.0, 0.2, 0.8, 1.0, (player,))
    away = TeamEventProjection(fixture_id, "team-away", AT, 1.0, 0.0, 1.0, 0.0, 0.0, 1.0, 1.0, ())
    return FixtureEventProjection(fixture_id, AT, home, away)


def _fixture(fixture_id: str, gameweek: int, kickoff: datetime):
    return SimpleNamespace(
        fixture_id=fixture_id, target_gameweek=gameweek, kickoff=kickoff,
        home_team_id="team-home", away_team_id="team-away",
    )


def _player():
    return SimpleNamespace(
        player_id="player-haaland", display_name="Haaland",
        provider_payload={"web_name": "Haaland", "first_name": "Erling", "second_name": "Haaland"},
    )


def _event(event_id: str, kickoff: datetime):
    return {
        "id": event_id, "sport_key": "soccer_epl", "sport_title": "EPL",
        "commence_time": kickoff.isoformat().replace("+00:00", "Z"),
        "home_team": "Home FC", "away_team": "Away FC",
    }


def _odds(event_id: str, *, props: bool = True):
    markets = []
    if props:
        markets = [{
            "key": "player_goal_scorer_anytime", "last_update": "2026-09-10T09:55:00Z",
            "outcomes": [
                {"name": "Yes", "description": "Erling Haaland", "price": 2.0},
                {"name": "No", "description": "Erling Haaland", "price": 2.0},
            ],
        }]
    return {
        "id": event_id, "sport_key": "soccer_epl", "sport_title": "EPL",
        "commence_time": "2026-09-11T10:00:00Z",
        "home_team": "Home FC", "away_team": "Away FC",
        "bookmakers": [{"key": "book-a", "last_update": "2026-09-10T09:55:00Z", "markets": markets}],
    }


def _adapter(tmp_path: Path, handler):
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return TheOddsApiAdapter(
        client=client, cache=HttpCache(tmp_path / "cache", clock=lambda: AT),
        raw_store=RawStore(tmp_path / "raw"), api_key="DO-NOT-LOG-ME",
        ttl=timedelta(minutes=10), clock=lambda: AT,
    ), client


def _collect(tmp_path, adapter, *, fixtures, projections, clock=None):
    return collect_current_gameweek_market_shadow(
        adapter=adapter, project_root=tmp_path, run_directory=tmp_path / "production" / "run-a",
        season="2026/27", current_gameweek=5, prediction_timestamp=AT,
        fixtures=fixtures, event_projections=projections, players=(_player(),),
        canonical_team_names={"team-home": "Home FC", "team-away": "Away FC"},
        clock=clock or (lambda: AT),
    )


def test_current_gw_only_uses_one_discovery_plus_one_props_request_per_mapped_fixture(tmp_path):
    calls = []
    gw5 = _fixture("fixture-gw5", 5, AT + timedelta(days=1))
    gw6 = _fixture("fixture-gw6", 6, AT + timedelta(days=2))

    def handler(request):
        calls.append(request.url.path)
        if request.url.path.endswith("/events"):
            return httpx.Response(200, json=[_event("event-gw5", gw5.kickoff), _event("event-gw6", gw6.kickoff)])
        assert request.url.path.endswith("/event-gw5/odds")
        return httpx.Response(200, json=_odds("event-gw5"))

    adapter, client = _adapter(tmp_path, handler)
    try:
        result = _collect(tmp_path, adapter, fixtures=(gw5, gw6), projections=(_event_projection("fixture-gw5"),))
    finally:
        client.close()

    payload = json.loads(result.artifact_path.read_text(encoding="utf-8"))
    assert calls == ["/v4/sports/soccer_epl/events", "/v4/sports/soccer_epl/events/event-gw5/odds"]
    assert result.status == "SUCCESS"
    assert payload["production_influence"] is False
    assert payload["coverage"]["current_gameweek_fixture_count"] == 1
    assert payload["coverage"]["mapped_fixture_count"] == 1
    assert len(payload["comparison"]["candidates"]) == 5
    assert "DO-NOT-LOG-ME" not in result.artifact_path.read_text(encoding="utf-8")


def test_snapshot_is_reused_for_retry_and_all_candidate_weights(tmp_path):
    calls = []
    fixture = _fixture("fixture-gw5", 5, AT + timedelta(days=1))

    def handler(request):
        calls.append(request.url.path)
        if request.url.path.endswith("/events"):
            return httpx.Response(200, json=[_event("event-gw5", fixture.kickoff)])
        return httpx.Response(200, json=_odds("event-gw5"))

    adapter, client = _adapter(tmp_path, handler)
    try:
        first = _collect(tmp_path, adapter, fixtures=(fixture,), projections=(_event_projection("fixture-gw5"),), clock=lambda: AT)
        second = _collect(tmp_path, adapter, fixtures=(fixture,), projections=(_event_projection("fixture-gw5"),), clock=lambda: AT + timedelta(minutes=5))
    finally:
        client.close()

    payload = json.loads(first.artifact_path.read_text(encoding="utf-8"))
    assert len(calls) == 2
    assert second.reused is True and second.artifact_path == first.artifact_path
    assert [item.rsplit("_g", 1)[1] for item in payload["comparison"]["candidates"]] == [
        "0.00_a0.00_s0.00_t0.00", "0.25_a0.25_s0.25_t0.25",
        "0.50_a0.50_s0.50_t0.50", "0.75_a0.75_s0.75_t0.75", "1.00_a1.00_s1.00_t1.00",
    ]


def test_stale_snapshot_is_not_reused_or_overwritten(tmp_path):
    calls = []
    fixture = _fixture("fixture-gw5", 5, AT + timedelta(days=1))

    def handler(request):
        calls.append(request.url.path)
        if request.url.path.endswith("/events"):
            return httpx.Response(200, json=[_event("event-gw5", fixture.kickoff)])
        return httpx.Response(200, json=_odds("event-gw5"))

    adapter, client = _adapter(tmp_path, handler)
    try:
        first = _collect(tmp_path, adapter, fixtures=(fixture,), projections=(_event_projection("fixture-gw5"),), clock=lambda: AT)
        second = _collect(tmp_path, adapter, fixtures=(fixture,), projections=(_event_projection("fixture-gw5"),), clock=lambda: AT + timedelta(minutes=11))
    finally:
        client.close()

    assert first.artifact_path != second.artifact_path
    assert first.artifact_path.exists() and second.artifact_path.exists()
    assert len(calls) == 2  # HttpCache still serves the same fresh provider responses.


def test_missing_player_props_are_recorded_without_fabricating_market_values(tmp_path):
    fixture = _fixture("fixture-gw5", 5, AT + timedelta(days=1))

    def handler(request):
        if request.url.path.endswith("/events"):
            return httpx.Response(200, json=[_event("event-gw5", fixture.kickoff)])
        return httpx.Response(200, json=_odds("event-gw5", props=False))

    adapter, client = _adapter(tmp_path, handler)
    try:
        result = _collect(tmp_path, adapter, fixtures=(fixture,), projections=(_event_projection("fixture-gw5"),))
    finally:
        client.close()

    payload = json.loads(result.artifact_path.read_text(encoding="utf-8"))
    assert result.status == "SKIPPED"
    assert payload["fixture_snapshots"][0]["status"] == "NO_SUPPORTED_PLAYER_PROPS"
    assert payload["comparison"] is None
    assert payload["coverage"]["missing_fixture_ids"] == ["fixture-gw5"]


def test_provider_failure_is_saved_as_shadow_failure_without_raising(tmp_path):
    fixture = _fixture("fixture-gw5", 5, AT + timedelta(days=1))

    def handler(_request):
        return httpx.Response(503, json={"error": "unavailable"})

    adapter, client = _adapter(tmp_path, handler)
    try:
        result = _collect(tmp_path, adapter, fixtures=(fixture,), projections=(_event_projection("fixture-gw5"),))
    finally:
        client.close()

    payload = json.loads(result.artifact_path.read_text(encoding="utf-8"))
    assert result.status == "FAILED"
    assert payload["production_influence"] is False
    assert payload["failure_reason"] == "TheOddsApiResponseError"


def test_shadow_observation_keeps_every_v22_artifact_unmodified(tmp_path):
    fixture = _fixture("fixture-gw5", 5, AT + timedelta(days=1))

    def handler(request):
        if request.url.path.endswith("/events"):
            return httpx.Response(200, json=[_event("event-gw5", fixture.kickoff)])
        return httpx.Response(200, json=_odds("event-gw5"))

    run = tmp_path / "production" / "run-a"
    run.mkdir(parents=True)
    bundle = run / "shadow_projection_bundle.json"
    bundle.write_text('{"pure_v22": true}\n', encoding="utf-8")
    manifest = run / "run_manifest.json"
    manifest.write_text('{"simulation": {}}\n', encoding="utf-8")
    adapter, client = _adapter(tmp_path, handler)
    try:
        result = _collect(tmp_path, adapter, fixtures=(fixture,), projections=(_event_projection("fixture-gw5"),))
    finally:
        client.close()

    assert manifest.read_text(encoding="utf-8") == '{"simulation": {}}\n'
    assert bundle.read_text(encoding="utf-8") == '{"pure_v22": true}\n'


def test_new_shadow_observation_uses_its_own_pre_kickoff_timestamp(tmp_path):
    fixture = _fixture("fixture-gw5", 5, AT + timedelta(days=1))

    def handler(request):
        if request.url.path.endswith("/events"):
            return httpx.Response(200, json=[_event("event-gw5", fixture.kickoff)])
        return httpx.Response(200, json=_odds("event-gw5"))

    adapter, client = _adapter(tmp_path, handler)
    try:
        result = _collect(
            tmp_path, adapter, fixtures=(fixture,),
            projections=(_event_projection("fixture-gw5"),),
            clock=lambda: AT + timedelta(hours=1),
        )
    finally:
        client.close()

    payload = json.loads(result.artifact_path.read_text(encoding="utf-8"))
    assert payload["model_prediction_timestamp"] == AT.isoformat()
    assert payload["shadow_prediction_timestamp"] == (AT + timedelta(hours=1)).isoformat()
    assert payload["shadow_prediction_timestamp"] < fixture.kickoff.isoformat()
    assert payload["comparison"]["model_prediction_timestamp"] == AT.isoformat()
    assert payload["comparison"]["prediction_timestamp"] == (AT + timedelta(hours=1)).isoformat()
    assert payload["comparison"]["selected_quote_count"] == 2


def test_explicit_premier_league_alias_plus_kickoff_maps_safely(tmp_path):
    fixture = SimpleNamespace(
        fixture_id="fixture-gw5", target_gameweek=5, kickoff=AT + timedelta(days=1),
        home_team_id="team-city", away_team_id="team-united",
    )

    def handler(request):
        if request.url.path.endswith("/events"):
            return httpx.Response(200, json=[{
                "id": "event-gw5", "sport_key": "soccer_epl", "sport_title": "EPL",
                "commence_time": fixture.kickoff.isoformat().replace("+00:00", "Z"),
                "home_team": "Manchester City", "away_team": "Manchester United",
            }])
        return httpx.Response(200, json=_odds("event-gw5", props=False))

    adapter, client = _adapter(tmp_path, handler)
    try:
        result = collect_current_gameweek_market_shadow(
            adapter=adapter, project_root=tmp_path, run_directory=tmp_path / "production" / "run-a",
            season="2026/27", current_gameweek=5, prediction_timestamp=AT,
            fixtures=(fixture,), event_projections=(_event_projection("fixture-gw5"),), players=(_player(),),
            canonical_team_names={"team-city": "Man City", "team-united": "Man Utd"},
            clock=lambda: AT,
        )
    finally:
        client.close()

    payload = json.loads(result.artifact_path.read_text(encoding="utf-8"))
    mapping = payload["coverage"]["fixture_mapping"][0]
    assert mapping["status"] == "MAPPED"
    assert mapping["home_team_resolution"] == "EXPLICIT_PREMIER_LEAGUE_ALIAS"
    assert mapping["away_team_resolution"] == "EXPLICIT_PREMIER_LEAGUE_ALIAS"
