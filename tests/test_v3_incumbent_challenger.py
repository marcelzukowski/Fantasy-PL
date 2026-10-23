from dataclasses import replace

from fpl_engine.optimizer import OptimizerRules, validate_squad
from fpl_engine.strategy.strategic_planner_v3 import StrategicPlannerV3, StrategicPlannerV3Config
from scripts.diagnostics.v3_incumbent_challenger import ChallengerPlanner, compare_paths, generate_actions
from scripts.diagnostics.v3_challenger_oracle import (
    ROOT, _club_cycle_fixture, _exhaustive_actions_with_hits, _five_transfer_fixture,
    _funding_cycle_fixture, _run_club_cycle, run_seed,
)
from scripts.diagnostics.v3_multi_transfer_oracle import _exhaustive_actions, _fixture, _projection


def _action_ids(actions):
    return [(row.action, row.transfers_out, row.transfers_in) for row in actions]


def test_both_strategies_are_deterministic_and_return_only_legal_unique_actions():
    rules = OptimizerRules.load(ROOT)
    state, pool, projections = _fixture(23, rules)
    for strategy in ("package_beam", "atomic"):
        first = generate_actions(state, pool, projections, rules, strategy=strategy, max_transfers=4)
        second = generate_actions(state, pool, projections, rules, strategy=strategy, max_transfers=4)
        assert _action_ids(first) == _action_ids(second)
        assert first[0].is_hold
        assert len(_action_ids(first)) == len(set(_action_ids(first)))
        for action in first:
            assert len(action.transfers_in) == len(set(action.transfers_in))
            assert set(action.transfers_out).isdisjoint(action.transfers_in)
            assert action.resulting_bank >= 0
            if action.is_hold:
                assert action.resulting_squad == tuple(sorted(p.player_id for p in state.players))
                continue
            by_id = {**pool, **{p.player_id: p for p in state.players}}
            result = replace(state, players=tuple(by_id[p] for p in action.resulting_squad), bank=action.resulting_bank)
            validate_squad(result, rules)


def test_ordinary_k1_k2_match_the_reduced_exhaustive_universe():
    rules = OptimizerRules.load(ROOT)
    state, pool, projections = _fixture(31, rules)
    planner = StrategicPlannerV3(rules, replace(StrategicPlannerV3Config(), max_transfers_per_action=2))
    oracle = _exhaustive_actions(planner, state, pool, projections, max_k=2)
    expected = {(row.transfers_out, row.transfers_in) for row in oracle}
    for strategy in ("package_beam", "atomic"):
        actual = generate_actions(state, pool, projections, rules, strategy=strategy,
                                  max_transfers=2, max_actions=31)
        assert {(row.transfers_out, row.transfers_in) for row in actual} == expected


def test_atomic_four_club_cycle_is_present_in_the_exact_oracle():
    rules = OptimizerRules.load(ROOT)
    state, pool, projections = _club_cycle_fixture(rules)
    planner = StrategicPlannerV3(rules, replace(StrategicPlannerV3Config(), max_transfers_per_action=5))
    oracle = _exhaustive_actions(planner, state, pool, projections, max_k=5)
    assert {k: sum(row.transfers_used == k for row in oracle) for k in range(5)} == {
        0: 1, 1: 0, 2: 0, 3: 0, 4: 1,
    }
    for strategy in ("package_beam", "atomic"):
        actions = generate_actions(state, pool, projections, rules, strategy=strategy,
                                   max_transfers=4, max_actions=31)
        assert actions[0].is_hold
        assert any(row.transfers_used == 4 for row in actions)


def test_known_full_objective_237_club_cycle_is_retained_by_both_challengers():
    rules = OptimizerRules.load(ROOT)
    result = _run_club_cycle(rules)
    assert result["exact_optimum"] == 237
    for row in result["strategies"].values():
        assert row["exact_optimum_root_retained"]
        assert row["challenger_value"] == 237
        assert row["selected_value"] == 237
        assert row["selected_value"] >= row["incumbent_value"] - 1e-9


def test_k5_ft5_reduced_universe_contains_a_legal_five_transfer_action():
    rules = OptimizerRules.load(ROOT)
    state, pool, projections = _five_transfer_fixture(rules)
    planner = StrategicPlannerV3(rules, replace(StrategicPlannerV3Config(), max_transfers_per_action=5))
    oracle = _exhaustive_actions(planner, state, pool, projections, max_k=5)
    assert state.free_transfers == 5
    assert any(row.transfers_used == 5 for row in oracle)
    for strategy in ("package_beam", "atomic"):
        actions = generate_actions(state, pool, projections, rules, strategy=strategy,
                                   max_transfers=5, max_actions=31)
        assert len(_action_ids(actions)) == len(set(_action_ids(actions)))
        assert any(row.transfers_used == 5 and row.hit_cost_points == 0 for row in actions)


def test_funding_dependent_k3_and_k4_packages_are_legally_generated():
    rules = OptimizerRules.load(ROOT)
    for transfers in (3, 4):
        state, pool, projections = _funding_cycle_fixture(rules, transfers)
        planner = StrategicPlannerV3(rules, replace(StrategicPlannerV3Config(), max_transfers_per_action=5))
        oracle = _exhaustive_actions(planner, state, pool, projections, max_k=5)
        assert {k: sum(row.transfers_used == k for row in oracle) for k in range(5)} == {
            0: 1, 1: 0, 2: 0, 3: int(transfers == 3), 4: int(transfers == 4),
        }
        package = next(row for row in oracle if row.transfers_used == transfers)
        assert package.resulting_bank == 0
        for strategy in ("package_beam", "atomic"):
            generated = generate_actions(state, pool, projections, rules, strategy=strategy,
                                         max_transfers=transfers, max_actions=31)
            assert any(row.transfers_used == transfers and row.resulting_bank == 0 for row in generated)


def test_hits_terminal_ft_and_hold_ties_use_native_v3_values():
    rules = OptimizerRules.load(ROOT)
    state, pool, projections = _fixture(47, rules)
    state = replace(state, free_transfers=1)
    normal_hit = int(rules.value("transfers", "normal_gameweek", "points_cost_per_transfer_above_allowance"))
    for strategy in ("package_beam", "atomic"):
        actions = generate_actions(state, pool, projections, rules, strategy=strategy, max_transfers=3)
        k3 = next(row for row in actions if row.transfers_used == 3)
        assert k3.hit_cost_points == 2 * normal_hit
    exact = StrategicPlannerV3(rules, replace(StrategicPlannerV3Config(), max_transfers_per_action=5))
    exact_k3 = next(row for row in _exhaustive_actions_with_hits(exact, state, pool, projections)
                    if row.transfers_used == 3)
    assert exact_k3.hit_cost_points == 2 * normal_hit

    tied_projections = {pid: _projection(pid, (6.0, 6.0, 6.0)) for pid in projections}
    planner = StrategicPlannerV3(rules)
    result = planner.plan(state, pool.values(), tied_projections).best_path
    assert result.steps[0].action.is_hold
    expected_terminal = planner._terminal_ft_value(
        replace(state, free_transfers=result.steps[-1].action.free_transfers_after)
    )
    assert result.terminal_ft_value == expected_terminal
    transfer_tie = replace(result, steps=(replace(result.steps[0], action=replace(result.steps[0].action, action="TRANSFER")), *result.steps[1:]))
    assert compare_paths(result, transfer_tie) is result


def test_compare_paths_keeps_the_incumbent_on_ties_and_never_loses_value():
    rules = OptimizerRules.load(ROOT)
    state, pool, projections = _fixture(41, rules)
    incumbent = StrategicPlannerV3(rules).plan(state, pool.values(), projections).best_path
    tied_transfer = replace(incumbent, steps=tuple(
        replace(step, action=replace(step.action, action="TRANSFER")) for step in incumbent.steps
    ))
    assert compare_paths(incumbent, tied_transfer) is incumbent
    assert compare_paths(tied_transfer, incumbent) is incumbent
    lower_hold = replace(incumbent, total_path_value=incumbent.total_path_value - 5e-10)
    assert compare_paths(tied_transfer, lower_hold) is tied_transfer
    for strategy in ("package_beam", "atomic"):
        result = ChallengerPlanner(rules, strategy=strategy).plan(state, pool.values(), projections)
        selected = compare_paths(incumbent, result.best_path)
        assert selected.total_path_value >= incumbent.total_path_value - 1e-9


def test_seeded_full_three_gameweek_oracle_reports_gaps_and_retention_without_claiming_success():
    rules = OptimizerRules.load(ROOT)
    for seed in (7, 41):
        report = run_seed(seed, rules)
        assert report["exact_actions_evaluated"] > 0
        for strategy in ("package_beam", "atomic"):
            row = report["strategies"][strategy]
            assert row["selected_optimum"] >= row["incumbent_objective"] - 1e-9
            assert isinstance(row["exact_optimum_root_action_retained"], bool)
            assert isinstance(row["objective_gap_to_exact"], float)
            assert 0.0 <= row["root_action_retention_rate"] <= 1.0
