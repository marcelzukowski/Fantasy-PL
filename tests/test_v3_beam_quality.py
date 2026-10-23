from dataclasses import replace

from fpl_engine.optimizer import OptimizerRules
from fpl_engine.strategy.strategic_planner_v3 import StrategicPlannerV3Config, _Node
from scripts.diagnostics.v3_beam_quality import deduplicate_nodes, state_key
from scripts.diagnostics.v3_beam_quality_oracle import ExactUniversePlanner, ROOT, run
from scripts.diagnostics.v3_multi_transfer_oracle import _fixture


def test_exact_controls_cover_delayed_payoff_ft_rollover_and_horizon_ranking():
    report = run(("delayed_payoff", "valuable_free_transfer", "early_transfer_unlocks", "horizon_vs_raw_points"))
    rows = {row["fixture"]: row for row in report["fixtures"]}
    delayed = rows["delayed_payoff"]["exact_path"]
    assert delayed[0]["action"] == "HOLD"
    assert delayed[1]["action"] == "TRANSFER" and "incoming-mid" in delayed[1]["in"]

    free_transfer = rows["valuable_free_transfer"]["exact_path"]
    assert [step["action"] for step in free_transfer] == ["HOLD", "HOLD", "TRANSFER"]
    assert free_transfer[-1]["gw"] == 8 and free_transfer[-1]["in"] == ["incoming-mid"]

    unlock = rows["early_transfer_unlocks"]["exact_path"]
    assert unlock[0]["in"] == ["incoming-def"] and unlock[1]["in"] == ["incoming-mid"]

    strategies = rows["horizon_vs_raw_points"]["strategies"]
    assert strategies["raw"]["trace"][1]["counterfactual_rank"] > strategies["horizon"]["trace"][1]["counterfactual_rank"]
    assert strategies["horizon"]["heuristic_probes"] > 0


def test_duplicate_histories_are_measured_before_beam_pruning():
    row = run(("duplicate_path_crowding",))["fixtures"][0]
    crowd = row["strategies"]["raw"]["second_layer_crowding"]
    assert crowd["expanded_paths"] > 40 and crowd["retained_paths"] == 40
    assert crowd["duplicate_paths"] > 40
    assert crowd["distinct_states"] < crowd["expanded_paths"]
    assert row["strategies"]["dominance"]["equal_duplicates"] > 0
    assert row["strategies"]["dominance"]["dominated"] > 0


def test_terminal_ft_crowding_exposes_raw_and_dominance_objective_losses():
    row = run(("ft_terminal_crowding",))["fixtures"][0]
    assert row["root_legal_actions"] > 40
    assert row["exact_states"] < 3000 and row["exact_actions"] < 50000
    assert [step["action"] for step in row["exact_path"]] == ["TRANSFER", "HOLD", "HOLD"]
    assert row["exact_advantage_over_forced_hold"] > 0
    assert row["strategies"]["raw"]["objective_gap"] >= 0.8 - 1e-9
    assert row["strategies"]["dominance"]["objective_gap"] >= 0.4 - 1e-9
    assert row["strategies"]["diversity"]["objective_gap"] == 0
    assert row["strategies"]["horizon"]["objective_gap"] == 0
    assert row["strategies"]["raw"]["trace"][1]["counterfactual_rank"] > 40
    assert all(strategy["incumbent_guard_preserved"] and strategy["raw_guard_preserved"]
               for strategy in row["strategies"].values())


def test_seeded_heuristic_and_diversity_regressions_remain_visible():
    rows = {row["fixture"]: row for row in run(("seeded_adversarial_1", "seeded_adversarial_3"))["fixtures"]}
    assert rows["seeded_adversarial_1"]["strategies"]["horizon"]["objective_gap"] == 0.708
    assert rows["seeded_adversarial_3"]["strategies"]["diversity"]["objective_gap"] == 1.943
    assert rows["seeded_adversarial_1"]["root_legal_actions"] > 40


def test_dominance_requires_full_future_state_and_ignores_player_tuple_order():
    rules = OptimizerRules.load(ROOT)
    state, _, _ = _fixture(9, rules)
    assert state_key(state) == state_key(replace(state, players=tuple(reversed(state.players))))
    changed = (
        replace(state, bank=state.bank + 1),
        replace(state, free_transfers=state.free_transfers - 1),
        replace(state, season=state.season + "-different"),
        replace(state, current_gameweek=state.current_gameweek + 1),
        replace(state, chips=replace(state.chips, wildcard_h1=False)),
        replace(state, players=(replace(state.players[0], selling_price=state.players[0].selling_price + 1), *state.players[1:])),
    )
    assert all(state_key(state) != state_key(other) for other in changed)


def test_dominance_discards_lower_and_equal_value_only_for_same_state():
    rules = OptimizerRules.load(ROOT)
    state, _, _ = _fixture(10, rules)
    unique, dominated, equal_duplicates = deduplicate_nodes([
        _Node(state, (), 9.0), _Node(state, (), 10.0), _Node(state, (), 10.0),
    ])
    assert len(unique) == 1 and unique[0].points == 10.0
    assert dominated == 1 and equal_duplicates == 1


def test_neutral_ties_are_deterministic_and_keep_hold():
    rules = OptimizerRules.load(ROOT)
    state, pool, projections = _fixture(11, rules)
    from scripts.diagnostics.v3_beam_quality_oracle import _NEUTRAL, _projection
    projections = {pid: _projection(pid, _NEUTRAL) for pid in projections}
    config = replace(StrategicPlannerV3Config(), max_transfers_per_action=2)
    for strategy in ("dominance", "diversity", "horizon"):
        paths = []
        for _ in range(2):
            result = ExactUniversePlanner(rules, config, strategy=strategy).plan(state, pool.values(), projections)
            paths.append(tuple((step.action.action, step.action.transfers_out, step.action.transfers_in)
                               for step in result.best_path.steps))
        assert paths[0] == paths[1]
        assert paths[0][0][0] == "HOLD"
