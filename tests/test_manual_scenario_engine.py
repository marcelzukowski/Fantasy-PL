from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from hypothesis import given, settings, strategies as st

from fpl_engine.optimizer import ChipState, OptimizerRules, SquadPlayer, SquadState
from desktop_app.manual_scenario_engine import ManualScenarioEvaluator, ManualScenarioError


ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]
AT = datetime(2026, 9, 20, 10, tzinfo=timezone.utc)


def _shared(ft=4):
    rules = OptimizerRules.load(ROOT)
    positions = ["GK"] * 2 + ["DEF"] * 5 + ["MID"] * 5 + ["FWD"] * 3
    owned = tuple(
        SquadPlayer(f"p{i}", pos, f"club-{i}", 50, 50, 50) for i, pos in enumerate(positions)
    )
    incoming = tuple(
        SquadPlayer(f"new{i}", pos, f"newclub-{i}", 50, 50, 50) for i, pos in enumerate(positions)
    )
    state = SquadState(owned, 50, ft, ChipState(), 6, "2026/27", rules.version, AT)
    projections = {}
    from tests.test_strategic_planner_v3 import _projection

    for player in (*owned, *incoming):
        projections[player.player_id] = _projection(player.player_id, (4, 4, 4))
    return SimpleNamespace(
        state=state,
        rules=rules,
        player_pool=(*owned, *incoming),
        projections=projections,
        context_id="ctx",
        planning_context=SimpleNamespace(context_id="ctx"),
        input_sha256="digest",
    )


@pytest.mark.parametrize("k", range(6))
def test_atomic_validation_supports_k0_through_k5_and_exact_ft_hits(k):
    evaluator = ManualScenarioEvaluator(_shared(ft=4))
    summary = evaluator.validate([f"p{i}" for i in range(k)], [f"new{i}" for i in range(k)])
    assert summary["k"] == k
    assert summary["hit_points"] == max(0, k - 4) * 4
    assert summary["bank_after"] == 50
    assert len(summary["final_squad"]) == 15


def test_ft5_k5_and_hold_preserve_canonical_capped_rollover():
    evaluator = ManualScenarioEvaluator(_shared(ft=5))
    assert (
        evaluator.validate([f"p{i}" for i in range(5)], [f"new{i}" for i in range(5)])["hit_points"]
        == 0
    )
    assert evaluator.validate([], [])["ft_after"] == 5


def test_atomic_package_uses_aggregate_final_bank_without_ordering_transfers():
    shared = _shared()
    shared.state = replace(shared.state, bank=0)
    shared.player_pool = tuple(
        replace(player, current_price=60)
        if player.player_id == "new0"
        else replace(player, current_price=40)
        if player.player_id == "new1"
        else player
        for player in shared.player_pool
    )
    summary = ManualScenarioEvaluator(shared).validate(["p0", "p1"], ["new0", "new1"])
    assert summary["bank_after"] == 0


def test_rejects_wrong_position_final_squad_and_replays_native_objective():
    evaluator = ManualScenarioEvaluator(_shared())
    with pytest.raises(ManualScenarioError, match="squad rules"):
        evaluator.validate(["p0"], ["new2"])
    result = evaluator.evaluate([], [])
    assert result["scenario"]["objective"] == pytest.approx(
        sum(step["lineup_points"] - step["hit_points"] for step in result["scenario"]["path"])
        + result["scenario"]["terminal_ft_value"]
    )
    assert result["hold"]["objective"] == result["scenario"]["objective"]
    changed = evaluator.evaluate(["p14"], ["new14"])
    assert changed["scenario"]["transfers_out"] == ["p14"]
    assert changed["scenario"]["transfers_in"] == ["new14"]
    assert changed["scenario"]["path"][0]["starting_xi"]
    assert changed["scenario"]["captain"] in changed["scenario"]["starting_xi"]


def test_exact_duplicate_scenario_is_cached_and_context_change_is_rejected():
    shared = _shared()
    evaluator = ManualScenarioEvaluator(shared)
    first = evaluator.evaluate([], [])
    second = evaluator.evaluate([], [])
    assert first["cached"] is False and second["cached"] is True
    other_shared = SimpleNamespace(**vars(shared))
    other_shared.context_id = "other"
    other = ManualScenarioEvaluator(other_shared)
    with pytest.raises(ManualScenarioError, match="PlanningContext"):
        other.evaluate([], [], context_id="ctx")


def test_timeout_is_checked_inside_native_planner_calls():
    evaluator = ManualScenarioEvaluator(_shared())
    with pytest.raises(TimeoutError, match="timed out"):
        evaluator.evaluate([], [], timeout_seconds=-1)


@pytest.fixture(scope="module")
def evaluated():
    return ManualScenarioEvaluator(_shared())


@pytest.mark.parametrize("k", range(6))
def test_each_manual_k_reconstructs_objective_xi_and_future_limit(evaluated, k):
    result = evaluated.evaluate([f"p{i}" for i in range(k)], [f"new{i}" for i in range(k)])
    scenario = result["scenario"]
    assert scenario["k"] == k
    assert scenario["objective"] == pytest.approx(
        sum(s["lineup_points"] - s["hit_points"] for s in scenario["path"])
        + scenario["terminal_ft_value"],
        abs=1e-9,
    )
    assert all(len(s["transfers_in"]) <= 2 for s in scenario["path"][1:])
    assert len(set(scenario["starting_xi"])) == 11
    assert (
        scenario["captain"] in scenario["starting_xi"]
        and scenario["vice_captain"] in scenario["starting_xi"]
    )
    assert scenario["delta_hold"] == pytest.approx(
        scenario["objective"] - result["hold"]["objective"]
    )
    assert scenario["delta_production"] == pytest.approx(
        scenario["objective"] - result["production"]["objective"]
    )


@settings(max_examples=15, derandomize=True, deadline=None)
@given(ft=st.integers(1, 5), k=st.integers(0, 5), bank=st.integers(0, 100))
def test_hypothesis_canonical_free_transfers_hits_bank_and_unique_final_roster(ft, k, bank):
    from fpl_engine.optimizer import next_free_transfers

    shared = _shared(ft)
    shared.state = replace(shared.state, bank=bank)
    summary = ManualScenarioEvaluator(shared).validate(
        [f"p{i}" for i in range(k)], [f"new{i}" for i in range(k)]
    )
    assert summary["ft_after"] == next_free_transfers(ft, k, shared.rules)
    assert summary["hit_points"] == max(0, k - ft) * 4
    assert summary["bank_after"] == bank and len(set(summary["final_squad"])) == 15


def test_personal_prices_club_limit_and_input_mutation_are_checked():
    shared = _shared()
    owned = list(shared.state.players)
    owned[0] = replace(owned[0], selling_price=65)
    shared.state = replace(shared.state, players=tuple(owned), bank=0)
    shared.player_pool = tuple(
        replace(p, current_price=60) if p.player_id == "new0" else p for p in shared.player_pool
    )
    evaluator = ManualScenarioEvaluator(shared)
    assert evaluator.validate(["p0"], ["new0"])["bank_after"] == 5
    shared.state = replace(shared.state, free_transfers=5)
    with pytest.raises(ManualScenarioError, match="PlanningContext"):
        evaluator.validate([], [])
    shared = _shared()
    owned = list(shared.state.players)
    for i in (2, 3, 4):
        owned[i] = replace(owned[i], club_id="cap-club")
    shared.state = replace(shared.state, players=tuple(owned))
    shared.player_pool = tuple(
        replace(p, club_id="cap-club") if p.player_id == "new0" else p for p in shared.player_pool
    )
    with pytest.raises(ManualScenarioError, match="squad rules"):
        ManualScenarioEvaluator(shared).validate(["p0"], ["new0"])


def test_atomic_club_rotation_does_not_require_legal_prefixes():
    from scripts.diagnostics.v3_challenger_oracle import _club_cycle_fixture

    rules = OptimizerRules.load(ROOT)
    state, pool, projections = _club_cycle_fixture(rules)
    shared = SimpleNamespace(
        state=state,
        player_pool=tuple(pool.values()),
        projections=projections,
        rules=rules,
        context_id="atomic",
    )
    evaluator = ManualScenarioEvaluator(shared)
    outs = ["owned-0", "owned-2", "owned-7", "owned-12"]
    ins = ["cycle-GK", "cycle-DEF", "cycle-MID", "cycle-FWD"]
    assert evaluator.validate(outs, ins)["k"] == 4
    for k in (1, 2, 3):
        with pytest.raises(ManualScenarioError):
            evaluator.validate(outs[:k], ins[:k])
