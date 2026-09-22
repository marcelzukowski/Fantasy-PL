from datetime import datetime, timedelta, timezone
from pathlib import Path

import duckdb
import pytest

from fpl_engine.models.projections import (
    DEFAULT_HORIZON_WEIGHTS, FixtureProjectionInput, ProjectionBuilder,
    ProjectionOutcome, ProjectionStore, validate_projections,
)
from fpl_engine.simulation.fixture import FixtureSimulationResult, PlayerSimulationSummary, SimulationDiagnostics
from fpl_engine.validation.leakage import FutureInformationError


AT = datetime(2026, 9, 1, 12, tzinfo=timezone.utc)


def simulation(fixture_id, player_id="player", *, points={2: 5, 8: 5}, minutes=70, timestamp=AT):
    summary = PlayerSimulationSummary(
        player_id, fixture_id, sum(value * count for value, count in points.items()) / sum(points.values()),
        5, 3, {.1: 2, .5: 5, .9: 8}, .5, .5, .5, .5, .0, .0, minutes, minutes,
        {"goals": .2}, points, sum(points.values()), 42, 99, "sim-v1", 1, "data-v1", "features-v1",
    )
    return FixtureSimulationResult(fixture_id, timestamp, (summary,), SimulationDiagnostics(0,0,0,0,0,0,0,0,0,0),
                                   sum(points.values()), 42, 99, "sim-v1", "model-v1", 1)


def input_for(gw, fixture_id, **kwargs):
    sim = simulation(fixture_id, **kwargs)
    return FixtureProjectionInput("2026/27", 1, gw, AT + timedelta(days=gw), AT - timedelta(hours=1), sim)


def test_fixture_schema_and_single_fixture_projection():
    result = ProjectionBuilder().fixture_projections((input_for(5, "fixture_a"),))
    row = result[0]
    assert row.player_id == "player" and row.fixture_id == "fixture_a" and row.target_gameweek == 5
    assert row.expected_points == 5 and sum(row.points_distribution.values()) == pytest.approx(1)
    assert row.simulation_count == 10 and row.model_version == "model-v1"


def test_dgw_convolves_independent_fixture_distributions_and_sums_minutes():
    builder = ProjectionBuilder()
    projections = builder.build((input_for(5, "fixture_a"), input_for(5, "fixture_b")), current_gameweek=5)
    gw = projections[0].gameweeks[0]
    assert gw.fixture_count == 2 and gw.fixture_ids == ("fixture_a", "fixture_b")
    assert gw.expected_points == 10 and gw.expected_minutes == 140
    assert gw.points_distribution == pytest.approx({4: .25, 10: .5, 16: .25})
    assert gw.p_return == pytest.approx(.75) and gw.p_blank == pytest.approx(.25)


def test_bgw_and_future_fixture_are_explicit_zero_fixture_gameweeks():
    projection = ProjectionBuilder().build((input_for(6, "fixture_later"),), current_gameweek=5, player_ids=("blank_player",))[0]
    blank = projection.gameweeks[0]
    assert blank.fixture_count == 0 and blank.expected_points == 0 and blank.expected_minutes == 0
    assert blank.p_blank == 1 and blank.p_return == 0 and blank.points_distribution == {0: 1.0}
    player = next(row for row in ProjectionBuilder().build((input_for(6, "fixture_later"),), current_gameweek=5) if row.player_id == "player")
    assert player.ev_next_1 == 0 and player.ev_next_3 == 5


def test_horizons_and_configured_decay_keep_raw_ev_separate_from_weighted_value():
    inputs = tuple(input_for(5 + offset, f"fixture_{offset}") for offset in range(6))
    projection = ProjectionBuilder().build(inputs, current_gameweek=5)[0]
    assert projection.ev_next_1 == 5 and projection.ev_next_3 == 15 and projection.ev_next_6 == 30
    assert projection.weighted_ev_next_6 == pytest.approx(5 * sum(DEFAULT_HORIZON_WEIGHTS))
    assert projection.weighted_ev_next_6 != projection.ev_next_6
    assert projection.expected_minutes_next_6 == 420
    assert projection.season == "2026/27" and projection.rule_version == 1
    assert 0 <= projection.projection_uncertainty <= 1 and 0 <= projection.projection_confidence <= 1


def test_reproducible_aggregation_and_timestamp_schedule_guards():
    builder = ProjectionBuilder()
    inputs = (input_for(5, "fixture_a"), input_for(6, "fixture_b"))
    assert builder.build(inputs, current_gameweek=5) == builder.build(reversed(inputs), current_gameweek=5)
    with pytest.raises(FutureInformationError):
        FixtureProjectionInput("2026/27", 1, 5, AT + timedelta(days=1), AT + timedelta(minutes=1), simulation("bad"))
    with pytest.raises(ValueError, match="incompatible"):
        builder.build((input_for(5, "fixture_a"), input_for(6, "fixture_b", timestamp=AT + timedelta(minutes=1))), current_gameweek=5)


def test_projection_validation_is_chronological_and_reports_core_metrics():
    outcomes = (
        ProjectionOutcome("a", AT, AT + timedelta(days=7), 5, 4, .6, True, .2, False, "MID", "low"),
        ProjectionOutcome("b", AT + timedelta(days=1), AT + timedelta(days=8), 3, 5, .4, True, .1, False, "DEF", "high"),
    )
    report = validate_projections(reversed(outcomes))
    assert report.observations == 2 and report.mae == 1.5 and report.rmse == pytest.approx(1.58113883) and report.bias == -.5
    assert report.by_position == {"MID": 1, "DEF": 1} and report.by_minutes_risk == {"low": 1, "high": 1}


def test_projection_store_round_trip_and_parquet_export(tmp_path):
    projections = ProjectionBuilder().build((input_for(5, "fixture_a"),), current_gameweek=5)
    store = ProjectionStore(tmp_path / "projection.duckdb")
    store.persist(projections)
    target = store.export_parquet(tmp_path / "parquet")
    assert duckdb.connect().execute("select count(*) from read_parquet(?)", [str(target)]).fetchone() == (1,)
    payload = store.connection.execute("select payload from player_projection").fetchone()[0]
    assert '"player_id": "player"' in payload and '"ev_next_6"' in payload
    assert store.connection.execute("select season, rule_version from player_projection").fetchone() == ("2026/27", 1)
    store.close()
