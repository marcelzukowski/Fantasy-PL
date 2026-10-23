"""Small exact three-GW oracles for V3 beam pruning quality."""

from __future__ import annotations

import argparse
from dataclasses import replace
import json
from pathlib import Path
import random
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT, ROOT / "src"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from fpl_engine.optimizer import OptimizerRules, SquadPlayer
from fpl_engine.strategy.strategic_planner_v3 import StrategicPlannerV3, StrategicPlannerV3Config, _Node
from scripts.diagnostics.v3_beam_quality import BeamAuditPlanner, state_key
from scripts.diagnostics.v3_challenger_oracle import _exhaustive_actions_with_hits
from scripts.diagnostics.v3_incumbent_challenger import compare_paths
from scripts.diagnostics.v3_multi_transfer_oracle import SWAP_SLOTS, _fixture, _hold, _projection, _solve


STRATEGIES = ("raw", "dominance", "diversity", "horizon")
_NEUTRAL = (5.0, 5.0, 5.0)


class ExactUniversePlanner(BeamAuditPlanner):
    """Use the same complete legal K<=2 actions at every visited state."""

    def _actions_for_state(self, state, pool_by_id, projections, *, target_gameweek):
        return _exhaustive_actions_with_hits(self, state, pool_by_id, projections, max_k=2)


def _fixture_for(case: str, rules):
    state, pool, projections = _fixture(180, rules)
    schedules = {pid: _NEUTRAL for pid in projections}
    for player in state.players:
        schedules[player.player_id] = _NEUTRAL

    for position in SWAP_SLOTS:
        primary_id = f"incoming-{position.lower()}"
        primary = pool[primary_id]
        alternate_id = f"incoming-{position.lower()}-alt"
        alternate = SquadPlayer(alternate_id, position, f"alternate-club-{position.lower()}", 50, 50, 50)
        pool[alternate_id] = alternate
        projections[alternate_id] = _projection(alternate_id, _NEUTRAL)
        if case.startswith("seeded_adversarial_") or case == "ft_terminal_crowding":
            third_id = f"incoming-{position.lower()}-alt-2"
            pool[third_id] = SquadPlayer(third_id, position, f"third-club-{position.lower()}", 50, 50, 50)
            projections[third_id] = _projection(third_id, _NEUTRAL)

    ids = {position: f"incoming-{position.lower()}" for position in SWAP_SLOTS}
    alt_ids = {position: f"incoming-{position.lower()}-alt" for position in SWAP_SLOTS}
    if case == "delayed_payoff":
        schedules[ids["MID"]] = (2.0, 18.0, 18.0)
        schedules[alt_ids["MID"]] = (2.0, 12.0, 12.0)
    elif case == "valuable_free_transfer":
        schedules[ids["MID"]] = (5.0, 5.0, 22.0)
        schedules[alt_ids["MID"]] = (5.0, 5.0, 7.0)
    elif case == "early_transfer_unlocks":
        schedules[ids["DEF"]] = (14.0, 14.0, 14.0)
        schedules[ids["MID"]] = (5.0, 18.0, 18.0)
        schedules[alt_ids["DEF"]] = (9.0, 9.0, 9.0)
        schedules[alt_ids["MID"]] = (5.0, 10.0, 10.0)
    elif case == "duplicate_path_crowding":
        schedules[ids["DEF"]] = schedules[alt_ids["DEF"]] = (7.0, 7.0, 7.0)
        schedules[ids["MID"]] = schedules[alt_ids["MID"]] = (7.0, 7.0, 7.0)
    elif case == "horizon_vs_raw_points":
        schedules[ids["DEF"]] = (20.0, 1.0, 1.0)
        schedules[alt_ids["DEF"]] = (15.0, 2.0, 2.0)
        schedules[ids["MID"]] = (1.0, 18.0, 18.0)
        schedules[alt_ids["MID"]] = (2.0, 14.0, 14.0)
    elif case == "transfer_vs_forced_hold":
        schedules[ids["FWD"]] = (16.0, 16.0, 16.0)
        schedules[alt_ids["FWD"]] = (11.0, 11.0, 11.0)
    elif case == "ft_terminal_crowding":
        mutable_ids = {state.players[index].player_id for index in SWAP_SLOTS.values()}
        for player in state.players:
            schedules[player.player_id] = (4.0, 4.0, 4.0) if player.player_id in mutable_ids else (0.2, 0.2, 0.2)
        for position in SWAP_SLOTS:
            schedules[ids[position]] = (4.1, 4.1, 4.1)
            schedules[alt_ids[position]] = (4.2, 4.2, 4.2)
            schedules[f"incoming-{position.lower()}-alt-2"] = (4.3, 4.3, 4.3)
        state = replace(state, free_transfers=4)
    elif case.startswith("seeded_adversarial_"):
        seed = int(case.rsplit("_", 1)[1]) + 20261022
        rng = random.Random(seed)
        mutable_ids = {state.players[index].player_id for index in SWAP_SLOTS.values()}
        for player in state.players:
            schedules[player.player_id] = tuple(round(rng.uniform(1.0, 22.0), 3) for _ in range(3)) if player.player_id in mutable_ids else (0.2, 0.2, 0.2)
        for player_id in pool:
            if player_id not in {player.player_id for player in state.players}:
                schedules[player_id] = tuple(round(rng.uniform(0.2, 25.0), 3) for _ in range(3))
        state = replace(state, free_transfers=1)
    else:
        raise ValueError(f"Unknown fixture: {case}")

    for player_id, values in schedules.items():
        if player_id in projections:
            projections[player_id] = _projection(player_id, values)
    if case == "valuable_free_transfer":
        state = replace(state, free_transfers=1)
    if case == "early_transfer_unlocks":
        state = replace(state, free_transfers=1)
    return state, pool, projections


def _action_row(step):
    action = step.action
    return {"gw": step.gameweek, "action": action.action,
            "out": list(action.transfers_out), "in": list(action.transfers_in),
            "points_after_hit": step.points_after_hit, "ft_after": action.free_transfers_after,
            "bank_after": action.resulting_bank}


def _node_for_exact_path(planner, state, pool, projections, path):
    pool_by_id = {**pool, **{player.player_id: player for player in state.players}}
    nodes = {}
    current, steps, points = state, (), 0.0
    for offset, identity in enumerate(path):
        actions = _exhaustive_actions_with_hits(planner, current, pool_by_id, projections, max_k=2)
        action = next(row for row in actions if (row.action, row.transfers_out, row.transfers_in) == identity)
        current, step = planner._evaluate_action(current, action, pool_by_id, projections,
            target_gameweek=current.current_gameweek, signals=None, offset=offset)
        steps += (step,)
        points += step.points_after_hit
        nodes[offset] = _Node(current, steps, points)
    return nodes


def _raw_second_layer_crowding(planner, state, pool, projections, beam_width):
    pool_by_id = {**pool, **{player.player_id: player for player in state.players}}
    first_layer = []
    for first in planner._actions_for_state(state, pool_by_id, projections, target_gameweek=state.current_gameweek):
        next_state, step = StrategicPlannerV3._evaluate_action(planner, state, first, pool_by_id, projections,
            target_gameweek=state.current_gameweek, signals=None, offset=0)
        first_layer.append(_Node(next_state, (step,), step.points_after_hit))
    expanded = []
    for node in first_layer:
        for action in planner._actions_for_state(node.state, pool_by_id, projections,
                target_gameweek=node.state.current_gameweek):
            next_state, step = StrategicPlannerV3._evaluate_action(planner, node.state, action, pool_by_id, projections,
                target_gameweek=node.state.current_gameweek, signals=None, offset=1)
            expanded.append(_Node(next_state, node.steps + (step,), node.points + step.points_after_hit))
    ranked = sorted(expanded, key=lambda node: (-node.points, planner._path_key(node.steps)))
    beam = ranked[:beam_width]
    unique_states = len({state_key(node.state) for node in expanded})
    return {"expanded_paths": len(expanded), "distinct_states": unique_states,
            "duplicate_paths": len(expanded)-unique_states,
            "retained_paths": len(beam),
            "duplicate_paths_retained_in_raw_beam": len(beam)-len({state_key(node.state) for node in beam})}


def _run_case(case, rules, *, beam_width=40):
    state, pool, projections = _fixture_for(case, rules)
    exact = StrategicPlannerV3(rules, replace(StrategicPlannerV3Config(),
        beam_width=beam_width, max_transfers_per_action=2))
    exact_result, exact_counts = _solve(exact, state, pool, projections,
        lambda current: _exhaustive_actions_with_hits(exact, current, pool, projections, max_k=2))
    exact_value, exact_points, exact_terminal, exact_identity_path = exact_result
    def hold_now_actions(current):
        actions = _exhaustive_actions_with_hits(exact, current, pool, projections, max_k=2)
        return [action for action in actions if action.is_hold] if current.current_gameweek == state.current_gameweek else actions
    forced_hold, _ = _solve(exact, state, pool, projections, hold_now_actions)
    exact_nodes = _node_for_exact_path(exact, state, pool, projections, exact_identity_path)
    config = replace(StrategicPlannerV3Config(), beam_width=beam_width, max_transfers_per_action=2)
    incumbent = StrategicPlannerV3(rules, config).plan(state, pool.values(), projections).best_path
    strategy_rows = {}
    raw_reference = None
    for strategy in STRATEGIES:
        stats = {}
        planner = ExactUniversePlanner(rules, config, strategy=strategy, candidate_mode="native",
                                       stats=stats, trace_target=exact_nodes)
        result = planner.plan(state, pool.values(), projections)
        candidate = result.best_path
        if strategy == "raw":
            raw_reference = candidate
        selected_native = compare_paths(incumbent, candidate)
        selected_raw = compare_paths(raw_reference, candidate)
        path = tuple((step.action.action, step.action.transfers_out, step.action.transfers_in)
                     for step in candidate.steps)
        strategy_rows[strategy] = {
            "objective": candidate.total_path_value,
            "objective_gap": round(exact_value - candidate.total_path_value, 8),
            "exact_path_retained": path == exact_identity_path,
            "path": [_action_row(step) for step in candidate.steps],
            "selected_after_incumbent_guard": selected_native.total_path_value,
            "selected_after_raw_guard": selected_raw.total_path_value,
            "incumbent_objective": incumbent.total_path_value,
            "incumbent_guard_preserved": selected_native.total_path_value >= incumbent.total_path_value - 1e-9,
            "raw_guard_preserved": selected_raw.total_path_value >= raw_reference.total_path_value - 1e-9,
            "expanded_by_k": {str(k): v for k, v in sorted(stats["expanded_by_k"].items())},
            "dominated": stats["dominated"], "equal_duplicates": stats["equal_duplicates"],
            "lineup_computations": stats["lineup_computations"],
            "lineup_cache_hits": stats["lineup_cache_hits"],
            "heuristic_lineup_computations": stats["heuristic_lineup_computations"],
            "heuristic_cache_hits": stats["heuristic_cache_hits"],
            "heuristic_probes": stats["heuristic_probes"],
            "layer_stats": stats["layer_stats"], "trace": stats["trace"],
        }
        if case == "duplicate_path_crowding" and strategy == "raw":
            strategy_rows[strategy]["second_layer_crowding"] = _raw_second_layer_crowding(
                planner, state, pool, projections, beam_width)
    return {
        "fixture": case,
        "root_legal_actions": len(_exhaustive_actions_with_hits(exact, state, pool, projections, max_k=2)),
        "exact_objective": exact_value, "exact_points": exact_points, "exact_terminal_ft": exact_terminal,
        "forced_hold_objective": forced_hold[0],
        "exact_advantage_over_forced_hold": round(exact_value-forced_hold[0], 8),
        "exact_path": [_action_row(step) for step in exact_nodes[len(exact_nodes)-1].steps],
        "exact_states": exact_counts["states"], "exact_actions": exact_counts["actions"],
        "beam_width": beam_width, "strategies": strategy_rows,
    }


def run(cases=None, *, beam_width=40):
    rules = OptimizerRules.load(ROOT)
    cases = tuple(cases or (
        "delayed_payoff", "valuable_free_transfer", "early_transfer_unlocks",
        "duplicate_path_crowding", "horizon_vs_raw_points", "transfer_vs_forced_hold",
        "seeded_adversarial_1", "seeded_adversarial_3", "ft_terminal_crowding",
    ))
    started = perf_counter()
    results = [_run_case(case, rules, beam_width=beam_width) for case in cases]
    return {"oracle": "reduced_exhaustive_v3_beam_quality", "objective":
            "native V3 three-GW lineup points after hits plus terminal FT value",
            "candidate_universe": "complete reduced fixture, max 2 transfers/action, identical for all strategies",
            "runtime_seconds": round(perf_counter()-started, 3), "fixtures": results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "scratch" / "v3_beam_quality_20261022" / "oracle_report.json")
    parser.add_argument("--beam-width", type=int, default=40)
    args = parser.parse_args()
    report = run(beam_width=args.beam_width)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"runtime_seconds": report["runtime_seconds"], "fixtures": [
        {"fixture": row["fixture"], "exact_objective": row["exact_objective"],
         "exact_states": row["exact_states"], "exact_actions": row["exact_actions"],
         "gaps": {name: strategy["objective_gap"] for name, strategy in row["strategies"].items()}}
        for row in report["fixtures"]]}, indent=2))
    print(args.output)


if __name__ == "__main__":
    main()
