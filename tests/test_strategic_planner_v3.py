from __future__ import annotations

from datetime import datetime, timezone

import pytest

from fpl_engine.models.projections import GameweekPlayerProjection, PlayerProjection
from fpl_engine.optimizer import ChipState, OptimizerRules, SquadPlayer, SquadState
from fpl_engine.strategy import PriceChangeSignal, StrategicPlannerV3, StrategicPlannerV3Config, StrategicPlannerV3Error


ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]
AT = datetime(2026, 9, 20, 10, tzinfo=timezone.utc)


def _projection(player_id: str, values: tuple[float, float, float]) -> PlayerProjection:
    gameweeks = tuple(
        GameweekPlayerProjection(
            "2026/27", 1, player_id, 6 + index, AT, (f"fixture-{index}",), 1,
            value, value, 1.0, {0.5: value}, .2, .5, .4, .2, .1, .05, 80.0, {int(value): 1.0}, 1.0,
        )
        for index, value in enumerate(values)
    )
    return PlayerProjection(
        player_id, "2026/27", 1, AT, 6, gameweeks, values[0], sum(values), sum(values),
        values[0], sum(values), sum(values), 80.0, 240.0, 240.0, .2, .8, 1.0,
        ("test",), ("test",), ("test",), ("test",), (42,), (1,),
    )


def _inputs():
    rules = OptimizerRules.load(ROOT)
    positions = ["GK"] * 2 + ["DEF"] * 5 + ["MID"] * 5 + ["FWD"] * 3
    owned = tuple(
        SquadPlayer(f"p{index}", position, f"club-{index}", 50, 50, 50)
        for index, position in enumerate(positions)
    )
    future_star = SquadPlayer("future-star", "FWD", "new-club", 60, 60, 60)
    current_star = SquadPlayer("current-star", "FWD", "other-club", 60, 60, 60)
    state = SquadState(owned, 10, 1, ChipState(), 6, "2026/27", rules.version, AT)
    projections = {player.player_id: _projection(player.player_id, (4.0, 4.0, 4.0)) for player in owned}
    projections["future-star"] = _projection("future-star", (4.1, 14.0, 14.0))
    projections["current-star"] = _projection("current-star", (15.0, 5.0, 5.0))
    return rules, state, (future_star, current_star), projections


def test_v3_returns_best_and_forced_hold_paths_in_the_same_metric_space():
    rules, state, pool, projections = _inputs()
    result = StrategicPlannerV3(rules, StrategicPlannerV3Config(beam_width=8, candidates_per_position=2, max_actions_per_state=8)).plan(state, pool, projections)

    assert len(result.best_path.steps) == 3
    assert len(result.hold_now_path.steps) == 3
    assert result.hold_now_path.steps[0].action.action == "HOLD"
    assert result.delta_vs_hold_now == result.best_path.total_path_value - result.hold_now_path.total_path_value
    assert result.best_path.terminal_ft_value >= 0
    assert result.best_path.terminal_ft_value < result.best_path.projected_3gw_path_points
    assert result.diagnostics["states_expanded"] > 0
    assert result.diagnostics["candidate_actions_evaluated"] <= 8 * 8 * 3 * 2


def test_v3_rollover_bank_hits_and_legality_propagate_through_steps():
    rules, state, pool, projections = _inputs()
    planner = StrategicPlannerV3(rules, StrategicPlannerV3Config(beam_width=8, candidates_per_position=2, max_actions_per_state=8))
    result = planner.plan(state, pool, projections)

    hold_step = result.hold_now_path.steps[0]
    assert hold_step.action.free_transfers_before == 1
    assert hold_step.action.free_transfers_after == 2
    assert hold_step.action.resulting_bank == state.bank
    for path in (result.best_path, result.hold_now_path):
        for step in path.steps:
            assert len(step.action.resulting_squad) == 15
            assert step.action.hit_cost_points >= 0
            assert step.points_after_hit == step.lineup_points - step.action.hit_cost_points
        assert all(
            path.steps[index].action.free_transfers_after == path.steps[index + 1].action.free_transfers_before
            for index in range(2)
        )


def test_v3_price_risk_is_optional_and_never_changes_projection_points():
    rules, state, pool, projections = _inputs()
    config = StrategicPlannerV3Config(beam_width=8, candidates_per_position=2, max_actions_per_state=8)
    without = StrategicPlannerV3(rules, config).plan(state, pool, projections)
    signals = {
        "future-star": PriceChangeSignal(
            "future-star", 60, "rise", AT, "cached-test", confidence=.9, expected_next_change=1,
        )
    }
    with_signals = StrategicPlannerV3(rules, config).plan(state, pool, projections, price_signals=signals)

    assert without.diagnostics["price_signal_status"] == "UNAVAILABLE"
    assert with_signals.diagnostics["price_signal_status"] == "AVAILABLE"
    assert with_signals.best_path.projected_3gw_path_points == without.best_path.projected_3gw_path_points
    assert all(step.price_risk["level"] in {"LOW", "MEDIUM", "HIGH", "STATIC_ASSUMPTION"} for step in with_signals.best_path.steps)


def test_v3_is_deterministic_for_fixed_inputs_and_keeps_actions_bounded():
    rules, state, pool, projections = _inputs()
    config = StrategicPlannerV3Config(beam_width=6, candidates_per_position=2, max_actions_per_state=6)
    first = StrategicPlannerV3(rules, config).plan(state, pool, projections)
    second = StrategicPlannerV3(rules, config).plan(state, pool, projections)

    assert first.best_path == second.best_path
    assert first.hold_now_path == second.hold_now_path
    assert first.diagnostics["candidate_actions_evaluated"] <= 6 * 6 * 3 * 2


def test_v3_rejects_a_future_price_signal_without_changing_prices_or_points():
    rules, state, pool, projections = _inputs()
    signal = PriceChangeSignal("future-star", 60, "rise", datetime(2026, 9, 21, 10, tzinfo=timezone.utc), "cached-test")

    with pytest.raises(StrategicPlannerV3Error, match="observed no later"):
        StrategicPlannerV3(rules).plan(state, pool, projections, price_signals={signal.player_id: signal})


def test_four_gw_control_requires_explicit_diagnostic_opt_in_without_changing_default():
    with pytest.raises(ValueError, match="diagnostic_horizon=True"):
        StrategicPlannerV3Config(planning_horizon=4)
    control = StrategicPlannerV3Config(planning_horizon=4, diagnostic_horizon=True)
    assert StrategicPlannerV3Config().planning_horizon == 3
    assert control.planning_horizon == 4 and control.beam_width == 40


def test_terminal_ft_value_is_considered_before_final_beam_pruning():
    rules = OptimizerRules.load(ROOT)
    positions = ["GK"] * 2 + ["DEF"] * 5 + ["MID"] * 5 + ["FWD"] * 3
    owned = tuple(
        SquadPlayer(f"p{index}", position, f"club-{index}", 50, 50, 50)
        for index, position in enumerate(positions)
    )
    edge_target = SquadPlayer("edge-target", "FWD", "new-club", 50, 50, 50)
    state = SquadState(owned, 0, 1, ChipState(), 6, "2026/27", rules.version, AT)
    projections = {player.player_id: _projection(player.player_id, (4.0, 4.0, 4.0)) for player in owned}
    # The final-GW transfer is worth only +0.5 lineup points but costs one
    # retained FT worth 1.0 terminal points under the unchanged V3 policy.
    projections[edge_target.player_id] = _projection(edge_target.player_id, (4.0, 4.0, 4.5))
    result = StrategicPlannerV3(
        rules, StrategicPlannerV3Config(beam_width=1, candidates_per_position=1, max_actions_per_state=2),
    ).plan(state, (edge_target,), projections)

    final_step = result.best_path.steps[-1]
    assert final_step.action.is_hold
    assert result.best_path.terminal_ft_value == 4.0
