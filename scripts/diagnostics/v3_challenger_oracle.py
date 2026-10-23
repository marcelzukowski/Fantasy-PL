"""Reduced exhaustive three-GW oracle for the incumbent-preserving V3 challenger."""

from __future__ import annotations

import argparse
from dataclasses import replace
from itertools import combinations, product
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT, ROOT / "src"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from fpl_engine.optimizer import OptimizerRules, SquadPlayer, validate_squad
from fpl_engine.strategy.strategic_planner_v3 import StrategicPlannerV3, StrategicPlannerV3Config
from scripts.diagnostics.v3_incumbent_challenger import ChallengerPlanner, compare_paths, generate_actions
from scripts.diagnostics.v3_multi_transfer_oracle import (
    SWAP_SLOTS, _fixture, _hold, _projection, _solve, run_club_cycle,
)


def _exhaustive_actions_with_hits(planner, state, pool, projections, max_k=5):
    """Enumerate every legal transfer set, including actions above the FT allowance."""
    owned = {player.player_id: player for player in state.players}
    by_position = {
        position: tuple(sorted((player for player in pool.values()
                                if player.player_id not in owned and player.position == position
                                and planner._gameweek_projection(projections[player.player_id], state.current_gameweek) is not None),
                               key=lambda player: player.player_id))
        for position in ("GK", "DEF", "MID", "FWD")
    }
    actions = {((), ()): _hold(state, planner.rules)}
    for count in range(1, min(max_k, len(state.players)) + 1):
        for outgoing in combinations(state.players, count):
            choices = [by_position[player.position] for player in outgoing]
            if any(not rows for rows in choices):
                continue
            for incoming in product(*choices):
                if len({player.player_id for player in incoming}) != count:
                    continue
                action = planner._make_action(state, outgoing, incoming)
                if action is not None:
                    actions[(action.transfers_out, action.transfers_in)] = action
    return list(actions.values())


def run_seed(seed: int, rules: OptimizerRules) -> dict:
    state, pool, projections = _fixture(seed, rules)
    exact = StrategicPlannerV3(rules, replace(StrategicPlannerV3Config(), max_transfers_per_action=5))
    oracle, counts = _solve(
        exact, state, pool, projections,
        lambda current: _exhaustive_actions_with_hits(exact, current, pool, projections, max_k=5),
    )
    incumbent = StrategicPlannerV3(rules)
    incumbent_result = incumbent.plan(state, pool.values(), projections)
    results = {}
    for strategy in ("package_beam", "atomic"):
        stats = {}
        challenger = ChallengerPlanner(rules, strategy=strategy, stats=stats)
        candidate = challenger.plan(state, pool.values(), projections)
        selected = compare_paths(incumbent_result.best_path, candidate.best_path)
        root = {(a.action, a.transfers_out, a.transfers_in) for a in challenger.root_actions}
        oracle_actions = _exhaustive_actions_with_hits(exact, state, pool, projections, max_k=5)
        oracle_keys = {(a.action, a.transfers_out, a.transfers_in) for a in oracle_actions}
        optimum_root = oracle[3][0]
        results[strategy] = {
            "incumbent_objective": incumbent_result.best_path.total_path_value,
            "challenger_optimum": candidate.best_path.total_path_value,
            "selected_optimum": selected.total_path_value,
            "objective_gap_to_exact": oracle[0] - selected.total_path_value,
            "challenger_gap_to_exact": oracle[0] - candidate.best_path.total_path_value,
            "incumbent_retained": selected is incumbent_result.best_path,
            "exact_optimum_root_action_retained": optimum_root in root,
            "root_action_retention_rate": len(root & oracle_keys) / len(oracle_keys),
            "exact_root_action_count": len(oracle_keys),
            "root_retains_k": sorted({a.transfers_used for a in challenger.root_actions}),
            "root_action_count": len(challenger.root_actions),
            "actions_evaluated": dict(stats["evaluated_by_k"]),
            "path": [
                {"action": step.action.action, "out": list(step.action.transfers_out),
                 "in": list(step.action.transfers_in), "gw": step.gameweek}
                for step in selected.steps
            ],
        }
    return {
        "seed": seed,
        "exact_optimum": oracle[0],
        "exact_path": [{"action": row[0], "out": list(row[1]), "in": list(row[2])} for row in oracle[3]],
        "exact_states": counts["states"],
        "exact_actions_evaluated": counts["actions"],
        "strategies": results,
    }


def _five_transfer_fixture(rules):
    state, pool, projections = _fixture(5, rules)
    # A second movable MID gives a reduced legal K5 case while retaining a 15-player squad.
    owned = list(state.players)
    owned[10] = replace(owned[10], current_price=50, purchase_price=50, selling_price=50)
    state = replace(state, players=tuple(owned), free_transfers=5)
    pool.update({player.player_id: player for player in owned})
    incoming = SquadPlayer("incoming-mid-2", "MID", "incoming-club-mid-2", 50, 50, 50)
    pool[incoming.player_id] = incoming
    projections[incoming.player_id] = _projection(incoming.player_id, (10.0, 10.0, 10.0))
    validate_squad(state, rules)
    return state, pool, projections


def _club_cycle_fixture(rules):
    state, _, _ = _fixture(0, rules)
    clubs = ("A", "B", "C", "D")
    high = list(SWAP_SLOTS.values())
    cheap = [i for i in range(15) if i not in high]
    assignments = {index: clubs[n] for n, index in enumerate(high)}
    assignments.update({index: clubs[n // 2] for n, index in enumerate(cheap[:8])})
    owned = tuple(replace(p, club_id=assignments.get(i, f"other-{i}")) for i, p in enumerate(state.players))
    state = replace(state, players=owned)
    incoming = tuple(SquadPlayer(f"cycle-{position}", position, clubs[(i + 1) % 4], 50, 50, 50)
                     for i, position in enumerate(SWAP_SLOTS))
    pool = {p.player_id: p for p in (*owned, *incoming)}
    from scripts.diagnostics.v3_multi_transfer_oracle import _projection
    projections = {p.player_id: _projection(p.player_id, (4.0, 4.0, 4.0) if p in owned else (10.0, 10.0, 10.0))
                   for p in pool.values()}
    validate_squad(state, rules)
    return state, pool, projections


def _funding_cycle_fixture(rules, transfers):
    state, pool, projections = _club_cycle_fixture(rules)
    swap_indices = list(SWAP_SLOTS.values())[:transfers]
    # The complete club rotation is affordable from its sale proceeds; every proper club prefix is illegal.
    sale_prices = {index: value for index, value in zip(swap_indices, (50, 60, 70, 60))}
    players = tuple(replace(player, selling_price=sale_prices.get(index, player.selling_price))
                    for index, player in enumerate(state.players))
    state = replace(state, players=players, bank=0)
    pool.update({player.player_id: player for player in players})
    remove_id = "cycle-FWD" if transfers == 3 else None
    if remove_id:
        pool.pop(remove_id)
        projections.pop(remove_id)
        if transfers == 3:
            pool["cycle-MID"] = replace(pool["cycle-MID"], club_id="A")
    for player_id, player in tuple(pool.items()):
        if player_id.startswith("cycle-"):
            pool[player_id] = replace(player, current_price=60, purchase_price=60, selling_price=60)
    validate_squad(state, rules)
    return state, pool, projections


def _run_club_cycle(rules):
    state, pool, projections = _club_cycle_fixture(rules)
    exact = StrategicPlannerV3(rules, replace(StrategicPlannerV3Config(), max_transfers_per_action=5))
    oracle, _ = _solve(exact, state, pool, projections,
                       lambda current: _exhaustive_actions_with_hits(exact, current, pool, projections, max_k=5))
    result = {"exact_optimum": oracle[0], "exact_root_action": oracle[3][0], "strategies": {}}
    incumbent = StrategicPlannerV3(rules).plan(state, pool.values(), projections)
    for strategy in ("package_beam", "atomic"):
        challenger = ChallengerPlanner(rules, strategy=strategy)
        candidate = challenger.plan(state, pool.values(), projections)
        selected = compare_paths(incumbent.best_path, candidate.best_path)
        result["strategies"][strategy] = {
            "exact_optimum_root_retained": oracle[3][0] in {
                (a.action, a.transfers_out, a.transfers_in) for a in challenger.root_actions
            },
            "retained_by_k": {str(k): sum(a.transfers_used == k for a in challenger.root_actions) for k in range(5)},
            "incumbent_value": incumbent.best_path.total_path_value,
            "challenger_value": candidate.best_path.total_path_value,
            "selected_value": selected.total_path_value,
            "objective_gap": oracle[0] - selected.total_path_value,
            "incumbent_retained": selected is incumbent.best_path,
        }
    return result


def _run_funding_cases(rules):
    cases = {}
    for transfers in (3, 4):
        state, pool, projections = _funding_cycle_fixture(rules, transfers)
        exact = StrategicPlannerV3(rules, replace(StrategicPlannerV3Config(), max_transfers_per_action=5))
        actions = _exhaustive_actions_with_hits(exact, state, pool, projections, max_k=5)
        cases[str(transfers)] = {
            "oracle_legal_by_k": {str(k): sum(row.transfers_used == k for row in actions) for k in range(5)},
            "legal_package_bank": next((row.resulting_bank for row in actions if row.transfers_used == transfers), None),
            "strategies": {},
        }
        for strategy in ("package_beam", "atomic"):
            stats = {}
            generated = generate_actions(state, pool, projections, rules, strategy=strategy,
                                         max_transfers=transfers, max_actions=31, stats=stats)
            cases[str(transfers)]["strategies"][strategy] = {
                "retained_by_k": stats["retained_by_k"],
                "legal_package_retained": any(row.transfers_used == transfers for row in generated),
                "max_transfer_bank": next((row.resulting_bank for row in generated if row.transfers_used == transfers), None),
            }
    return cases


def run(seeds=range(3)) -> dict:
    rules = OptimizerRules.load(ROOT)
    started = time.perf_counter()
    seeded = [run_seed(seed, rules) for seed in seeds]
    cycle = _run_club_cycle(rules)
    funding = _run_funding_cases(rules)
    state5, pool5, projections5 = _five_transfer_fixture(rules)
    k5 = {}
    for strategy in ("package_beam", "atomic"):
        stats = {}
        actions = generate_actions(state5, pool5, projections5, rules, strategy=strategy,
                                    max_transfers=5, max_actions=31, partial_width=32, stats=stats)
        k5[strategy] = {"retained_by_k": stats["retained_by_k"],
                        "has_k5": any(action.transfers_used == 5 for action in actions),
                        "duplicate_action_count": len(actions) - len({(a.action, a.transfers_out, a.transfers_in) for a in actions})}
    return {
        "oracle": "reduced_exhaustive_v3_three_gameweek_incumbent_preserving_challenger",
        "objective": "native V3 three-GW lineup points after hits plus terminal FT value",
        "fixture_count": len(seeded),
        "runtime_seconds": time.perf_counter() - started,
        "seeded": seeded,
        "atomic_club_cycle": cycle,
        "funding_dependent_k3_k4": funding,
        "previous_prototype_club_cycle": run_club_cycle(rules),
        "ft5": k5,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", type=int, default=3)
    parser.add_argument("--output", type=Path, default=ROOT / "scratch" / "v3_challenger_20261022" / "oracle_report.json")
    args = parser.parse_args()
    report = run(range(args.seeds))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"fixture_count": report["fixture_count"], "runtime_seconds": report["runtime_seconds"],
                      "ft5": report["ft5"], "club_cycle": report["atomic_club_cycle"]}, indent=2))
    print(args.output)


if __name__ == "__main__":
    main()
