from datetime import datetime, timezone
from types import SimpleNamespace

from scripts.run_strict_model_backtest import (
    BACKTEST_RANDOM_SEED, BACKTEST_SIMULATIONS_PER_FIXTURE,
    CONVERGENCE_MINIMUM_RANK_SPEARMAN, CONVERGENCE_MINIMUM_TOP_10_OVERLAP,
    CONVERGENCE_PLAYER_METRIC_TOLERANCE, CONVERGENCE_PROBABILITY_TOLERANCE,
    CONVERGENCE_SIMULATION_COUNTS,
    _availability, _ci95, _json_safe, _projection_observations,
)
from fpl_engine.simulation import SimulationConfig


def test_missing_injury_probability_remains_unknown_instead_of_healthy():
    assert _availability({"status": "d", "chance_of_playing_next_round": None}) == (None, False)
    assert _availability({"status": "i", "chance_of_playing_next_round": None}) == (None, False)


def test_explicit_snapshot_availability_and_unavailability_are_preserved():
    assert _availability({"status": "a", "chance_of_playing_next_round": None}) == (1.0, False)
    assert _availability({"status": "s", "chance_of_playing_next_round": None}) == (0.0, True)
    assert _availability({"status": "d", "chance_of_playing_next_round": 25}) == (0.25, False)


def test_report_serialization_is_json_compatible_and_uncertainty_is_deterministic():
    assert _json_safe({"metric": float("inf")}) == {"metric": "Infinity"}
    first = _ci95([1.0, 2.0, 3.0])
    assert first == _ci95([1.0, 2.0, 3.0])
    assert first[0] < 2 < first[1]


def test_backtest_simulation_budget_is_explicit_without_changing_production_default():
    assert BACKTEST_SIMULATIONS_PER_FIXTURE == 32
    assert BACKTEST_RANDOM_SEED == 202425
    assert SimulationConfig().simulations_per_fixture == 10_000
    assert CONVERGENCE_SIMULATION_COUNTS == (32, 128, 512, 2_000, 10_000)
    assert CONVERGENCE_PLAYER_METRIC_TOLERANCE == .30
    assert CONVERGENCE_PROBABILITY_TOLERANCE == .03
    assert CONVERGENCE_MINIMUM_RANK_SPEARMAN == .90
    assert CONVERGENCE_MINIMUM_TOP_10_OVERLAP == .80


def test_projection_outcome_adapter_rejects_later_rescheduled_result():
    at = datetime(2024, 8, 16, tzinfo=timezone.utc)
    gameweek = SimpleNamespace(
        target_gameweek=1, fixture_ids=("fixture",), expected_minutes=80,
        p_return=.25, points_distribution={2: .5, 8: .5},
    )
    projection = SimpleNamespace(
        player_id="player", prediction_timestamp=at, gameweeks=(gameweek,),
        ev_next_1=5, ev_next_3=5, ev_next_6=5,
    )
    base = {
        "goals_scored": 1, "assists": 0, "total_points": 8, "GW": 1,
    }
    target = (base, SimpleNamespace(known_at=datetime(2024, 8, 18, tzinfo=timezone.utc)))
    arguments = dict(
        current_gameweek=1, provider_player_by_canonical={"player": 7},
        provider_fixture_by_canonical={"fixture": "11"},
        positions_by_player={"player": "MID"},
    )
    rows = _projection_observations(
        (projection,), outcome_by_fixture_player={("11", 7): target}, **arguments,
    )
    assert [row.horizon for row in rows] == [1, 3, 6]
    rescheduled = ({**base, "GW": 2}, target[1])
    assert _projection_observations(
        (projection,), outcome_by_fixture_player={("11", 7): rescheduled}, **arguments,
    ) == []
