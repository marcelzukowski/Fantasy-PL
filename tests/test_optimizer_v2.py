from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from fpl_engine.optimizer import (
    ChipState, ChipTimingPlanner, OptimizerRules, OptimizerV2, OptimizerV2Config,
    SquadPlayer, SquadState, generate_candidates,
)


ROOT = Path(__file__).resolve().parents[1]
AT = datetime(2024, 9, 1, tzinfo=timezone.utc)


def _squad():
    positions = ["GK"] * 2 + ["DEF"] * 5 + ["MID"] * 5 + ["FWD"] * 3
    return tuple(SquadPlayer(f"p{i}", position, f"c{i // 3}", 50, 50)
                 for i, position in enumerate(positions))


def _projection(player_id, value, *, future=None, uncertainty=.2):
    future = [value] * 6 if future is None else list(future)
    gameweeks = tuple(SimpleNamespace(expected_points=float(item)) for item in future)
    return SimpleNamespace(
        player_id=player_id, season="2024/25", rule_version=202425,
        prediction_timestamp=AT, gameweeks=gameweeks,
        ev_next_1=float(future[0]), ev_next_3=float(sum(future[:3])),
        ev_next_6=float(sum(future)), weighted_ev_next_1=float(future[0]),
        weighted_ev_next_3=float(sum(future[:3])), weighted_ev_next_6=float(value),
        projection_uncertainty=uncertainty,
    )


def _state(ft=1):
    return SquadState(_squad(), 10, ft, ChipState(), 5, "2024/25", 202425, AT)


def test_v2_configuration_is_season_rule_driven():
    rules = OptimizerRules.load(ROOT, season="2024/25")
    config = OptimizerV2Config.from_rules(rules)
    assert config.future_transfer_need_probability == .25
    assert config.indifference_margin == .25
    assert config.second_transfer_beam_width == 24


def test_broad_candidate_union_has_complete_top_weighted_coverage_and_is_deterministic():
    state = _state()
    projections = {player.player_id: _projection(player.player_id, index + 1)
                   for index, player in enumerate(state.players)}
    pool = []
    for position_index, position in enumerate(("GK", "DEF", "MID", "FWD")):
        for index in range(30):
            player = SquadPlayer(f"{position}-{index}", position, f"new-{position_index}-{index}", 40 + index, 40 + index)
            pool.append(player)
            projections[player.player_id] = _projection(player.player_id, 100-index)
    config = OptimizerV2Config(candidates_per_metric=8, maximum_candidates_per_position=24)
    first, report = generate_candidates(state, pool, projections, config)
    second, _ = generate_candidates(state, pool, projections, config)
    assert first == second
    assert report.selected == 8 * 4
    assert report.top_weighted_coverage == 1.0
    assert report.selected_by_position == {"DEF": 8, "FWD": 8, "GK": 8, "MID": 8}


def test_ft_option_value_and_known_lookahead_prevent_marginal_churn():
    rules = OptimizerRules.load(ROOT, season="2024/25")
    state = _state()
    projections = {player.player_id: _projection(player.player_id, 10) for player in state.players}
    marginal = SquadPlayer("marginal", "FWD", "new", 50, 50)
    projections[marginal.player_id] = _projection(marginal.player_id, 10.5, future=[1, 2, 2, 2, 2, 2])
    optimizer = OptimizerV2(rules, OptimizerV2Config.from_rules(rules))
    recommendation = optimizer.recommend(state, projections, (marginal,), max_transfers=1)
    assert recommendation.roll_ft
    assert optimizer.last_diagnostic.roll_utility > 0
    assert optimizer.last_diagnostic.ft_option_value == 2.0


def test_v2_still_makes_material_transfer_and_reports_deterministic_diagnostics():
    rules = OptimizerRules.load(ROOT, season="2024/25")
    state = _state()
    projections = {player.player_id: _projection(player.player_id, 10) for player in state.players}
    incoming = SquadPlayer("incoming", "FWD", "new", 50, 50)
    projections[incoming.player_id] = _projection(incoming.player_id, 120, future=[30] * 6, uncertainty=.35)
    optimizer = OptimizerV2(rules, OptimizerV2Config.from_rules(rules))
    first = optimizer.recommend(state, projections, (incoming,), max_transfers=1)
    first_diagnostic = optimizer.last_diagnostic
    second = optimizer.recommend(state, projections, (incoming,), max_transfers=1)
    assert first.transfers_in == ("incoming",)
    assert first.hit_cost == 0 and first.gross_gain == 110
    assert first.action_stability == second.action_stability
    assert 0 < first.action_stability <= 1
    assert first_diagnostic.gain_1gw == optimizer.last_diagnostic.gain_1gw
    assert first_diagnostic.projection_uncertainty > 0


def test_chip_timing_uses_incremental_ev_and_known_horizon_opportunity():
    rules = OptimizerRules.load(ROOT, season="2024/25")
    state = _state()
    projections = {}
    for index, player in enumerate(state.players):
        current = 10 if index == 14 else 2
        projections[player.player_id] = _projection(
            player.player_id, current, future=[current, 1, 1, 1, 1, 1]
        )
    decision = ChipTimingPlanner(rules).decide(state, projections, ())
    assert decision.chip == "triple_captain"
    triple = next(row for row in decision.evaluations if row.chip == "triple_captain")
    assert triple.incremental_ev == 10
    assert triple.use_now
    assert all(row.no_chip_ev is not None for row in decision.evaluations)
