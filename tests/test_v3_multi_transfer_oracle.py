from __future__ import annotations

from fpl_engine.optimizer import OptimizerRules, validate_squad
from scripts.diagnostics.v3_multi_transfer_oracle import (
    ROOT, _exhaustive_actions, _fixture, _hold, run_seed, run_club_cycle,
)
from scripts.diagnostics.v3_multi_transfer import generate_actions
from fpl_engine.strategy.strategic_planner_v3 import StrategicPlannerV3, StrategicPlannerV3Config


def test_reduced_fixture_exhaustively_covers_legal_k0_to_k4_sets():
    rules = OptimizerRules.load(ROOT)
    state, pool, projections = _fixture(19, rules)
    validate_squad(state, rules)
    actions = _exhaustive_actions(
        StrategicPlannerV3(rules, StrategicPlannerV3Config(max_transfers_per_action=4)),
        state, pool, projections,
    )
    assert {k: sum(action.transfers_used == k for action in actions) for k in range(5)} == {
        0: 1, 1: 4, 2: 6, 3: 4, 4: 1,
    }


def test_bounded_generators_cover_every_oracle_action_on_the_reduced_fixture():
    rules = OptimizerRules.load(ROOT)
    state, pool, projections = _fixture(23, rules)
    from fpl_engine.strategy.strategic_planner_v3 import StrategicPlannerV3, StrategicPlannerV3Config

    oracle = _exhaustive_actions(
        StrategicPlannerV3(rules, StrategicPlannerV3Config(max_transfers_per_action=4)),
        state, pool, projections,
    )
    oracle_ids = {(row.transfers_out, row.transfers_in) for row in oracle}
    for strategy in ("incremental", "compose"):
        actions = generate_actions(
            state, pool, projections, rules, strategy=strategy, max_transfers=4,
            partial_width=16, max_actions=24, candidates_per_position=8,
        )
        assert {(row.transfers_out, row.transfers_in) for row in actions} == oracle_ids


def test_future_action_cap_distinguishes_current_only_from_symmetric_expansion():
    rules = OptimizerRules.load(ROOT)
    state, pool, projections = _fixture(29, rules)
    planner = StrategicPlannerV3(rules, StrategicPlannerV3Config(max_transfers_per_action=4))
    future_state, _ = planner._evaluate_action(
        state, _hold(state, rules), pool, projections,
        target_gameweek=state.current_gameweek, signals=None, offset=0,
    )
    assert future_state.free_transfers == 5
    current_only = generate_actions(
        future_state, pool, projections, rules, strategy="incremental", max_transfers=2,
        partial_width=16, max_actions=24, candidates_per_position=8,
    )
    symmetric = generate_actions(
        future_state, pool, projections, rules, strategy="incremental", max_transfers=4,
        partial_width=16, max_actions=24, candidates_per_position=8,
    )
    assert max(action.transfers_used for action in current_only) == 2
    assert max(action.transfers_used for action in symmetric) == 4


def test_full_three_gameweek_objective_matches_exhaustive_dp_for_seeded_fixtures():
    for seed in (7, 41, 89):
        result = run_seed(seed, OptimizerRules.load(ROOT))
        assert result["exhaustive_action_counts_by_k"] == {"0": 1, "1": 4, "2": 6, "3": 4, "4": 1}
        for strategy in ("incremental", "compose"):
            bounded = result["strategies"][strategy]
            assert bounded["objective_gap"] == 0
            assert bounded["global_optimum_root_action_retained"]
            assert bounded["root_action_identities_missed"] == 0
            assert all(row["missed"] == 0 for row in bounded["all_reachable_states_action_coverage_by_k"].values())


def test_atomic_club_rotation_exposes_known_prefix_pruning_limit():
    result = run_club_cycle(OptimizerRules.load(ROOT))
    assert result["exhaustive_root_counts"] == {0: 1, 1: 0, 2: 0, 3: 0, 4: 1}
    for row in result["strategies"].values():
        assert not row["global_optimum_root_action_retained"]
        assert row["objective_gap"] > 0
