"""Reduced exhaustive oracle for the opt-in V3 multi-transfer generator."""

from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache
from itertools import combinations, product
import argparse
import json
from pathlib import Path
import random
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from fpl_engine.models.projections import GameweekPlayerProjection, PlayerProjection
from fpl_engine.optimizer import (
    ChipState, OptimizerRules, SquadPlayer, SquadState,
    next_free_transfers, validate_squad,
)
from fpl_engine.strategy.strategic_planner_v3 import (
    StrategicAction, StrategicPlannerV3, StrategicPlannerV3Config,
)
from scripts.diagnostics.v3_multi_transfer import generate_actions


AT = datetime(2026, 10, 20, 10, tzinfo=timezone.utc)
POSITIONS = ("GK", "GK", "DEF", "DEF", "DEF", "DEF", "DEF", "MID", "MID", "MID", "MID", "MID", "FWD", "FWD", "FWD")
SWAP_SLOTS = {"GK": 0, "DEF": 2, "MID": 7, "FWD": 12}


def _projection(player_id: str, values: tuple[float, float, float]) -> PlayerProjection:
    gameweeks = tuple(
        GameweekPlayerProjection(
            "2026/27", 1, player_id, 6 + offset, AT, (f"oracle-{offset}",), 1,
            value, value, 1.0, {0.5: value}, .2, .5, .4, .2, .1, .05, 80.0,
            {int(value): 1.0}, 1.0,
        )
        for offset, value in enumerate(values)
    )
    return PlayerProjection(
        player_id, "2026/27", 1, AT, 6, gameweeks, values[0], sum(values), sum(values),
        values[0], sum(values), sum(values), 80.0, 240.0, 240.0, .2, .8, 1.0,
        ("oracle",), ("oracle",), ("oracle",), ("oracle",), (42,), (1,),
    )


def _fixture(seed: int, rules: OptimizerRules):
    rng = random.Random(seed)
    owned = tuple(
        SquadPlayer(
            f"owned-{index}", position, f"owned-club-{index}",
            50 if index in SWAP_SLOTS.values() else 1, 50 if index in SWAP_SLOTS.values() else 1,
            50 if index in SWAP_SLOTS.values() else 1,
        )
        for index, position in enumerate(POSITIONS)
    )
    incoming = tuple(
        SquadPlayer(f"incoming-{position.lower()}", position, f"incoming-club-{position.lower()}", 50, 50, 50)
        for position in SWAP_SLOTS
    )
    state = SquadState(owned, 0, 4, ChipState(), 6, "2026/27", rules.version, AT)
    pool = {player.player_id: player for player in (*owned, *incoming)}
    projections = {
        player.player_id: _projection(
            player.player_id,
            tuple(round(rng.uniform(2.0, 16.0), 3) for _ in range(3)),
        )
        for player in pool.values()
    }
    validate_squad(state, rules)
    return state, pool, projections


def _hold(state, rules) -> StrategicAction:
    return StrategicAction(
        "HOLD", (), (), 0, 0, state.bank, state.free_transfers,
        next_free_transfers(state.free_transfers, 0, rules),
        tuple(sorted(player.player_id for player in state.players)),
    )


def _exhaustive_actions(planner, state, pool, projections, max_k: int = 4):
    """Enumerate legal transfer sets, deduplicating unordered action identity."""
    owned = {player.player_id: player for player in state.players}
    incoming_by_position = {
        position: tuple(sorted((
            player for player in pool.values()
            if player.player_id not in owned and player.position == position
            and planner._gameweek_projection(projections[player.player_id], state.current_gameweek) is not None
        ), key=lambda player: player.player_id))
        for position in ("GK", "DEF", "MID", "FWD")
    }
    actions = {((), ()): _hold(state, planner.rules)}
    for k in range(1, min(max_k, state.free_transfers) + 1):
        for outgoing in combinations(state.players, k):
            choices = [incoming_by_position[player.position] for player in outgoing]
            if any(not rows for rows in choices):
                continue
            for incoming in product(*choices):
                if len({player.player_id for player in incoming}) != k:
                    continue
                action = planner._make_action(state, outgoing, incoming)
                if action is None:
                    continue
                key = (action.transfers_out, action.transfers_in)
                actions[key] = action
    return list(actions.values())


def _state_key(state):
    return (
        state.current_gameweek, state.free_transfers, state.bank,
        tuple(sorted((p.player_id, p.position, p.club_id, p.current_price,
                      p.purchase_price, p.selling_price) for p in state.players)),
    )


def _action_key(action):
    return action.action, action.transfers_out, action.transfers_in


def _solve(planner, state, pool, projections, action_provider):
    """Exact three-GW DP over legal states, using native V3 lineup/action scoring."""
    counters = {"states": 0, "actions": 0}

    @lru_cache(maxsize=None)
    def visit(key):
        counters["states"] += 1
        current = states[key]
        offset = current.current_gameweek - state.current_gameweek
        if offset == planner.config.planning_horizon:
            terminal = planner._terminal_ft_value(current)
            return terminal, 0.0, terminal, ()
        actions = action_provider(current)
        rows = []
        for action in actions:
            counters["actions"] += 1
            next_state, step = planner._evaluate_action(
                current, action, pool, projections, target_gameweek=current.current_gameweek,
                signals=None, offset=offset,
            )
            next_key = _state_key(next_state)
            states.setdefault(next_key, next_state)
            total, points, terminal, suffix = visit(next_key)
            path = (_action_key(action), *suffix)
            rows.append((step.points_after_hit + total, step.points_after_hit + points, terminal, path))
        rows.sort(key=lambda row: (-row[0], row[3]))
        return rows[0]

    states = {_state_key(state): state}
    result = visit(_state_key(state))
    counters["reachable_states"] = tuple(states.values())
    return result, counters


def run_seed(seed: int, rules: OptimizerRules) -> dict:
    state, pool, projections = _fixture(seed, rules)
    config = StrategicPlannerV3Config(
        beam_width=40, candidates_per_position=8, max_actions_per_state=24,
        max_transfers_per_action=4,
    )
    exhaustive_planner = StrategicPlannerV3(rules, config)
    exhaustive_actions = _exhaustive_actions(exhaustive_planner, state, pool, projections)
    exhaustive_by_k = {k: sum(a.transfers_used == k for a in exhaustive_actions) for k in range(5)}
    exhaustive_keys = {(a.transfers_out, a.transfers_in) for a in exhaustive_actions}

    exhaustive_result, exhaustive_counts = _solve(
        exhaustive_planner, state, pool, projections,
        lambda current: _exhaustive_actions(exhaustive_planner, current, pool, projections),
    )
    strategies = {}
    for strategy in ("incremental", "compose"):
        planner = StrategicPlannerV3(rules, config)

        def provide(current, selected=strategy):
            return generate_actions(
                current, pool, projections, rules, strategy=selected,
                max_transfers=min(4, current.free_transfers), partial_width=16,
                max_actions=24, candidates_per_position=8,
            )

        bounded_result, bounded_counts = _solve(planner, state, pool, projections, provide)
        root_actions = provide(state)
        root_keys = {(a.transfers_out, a.transfers_in) for a in root_actions}
        exhaustive_total_by_k = {k: 0 for k in range(5)}
        bounded_total_by_k = {k: 0 for k in range(5)}
        missed_total_by_k = {k: 0 for k in range(5)}
        for current in exhaustive_counts["reachable_states"]:
            if current.current_gameweek >= state.current_gameweek + 3:
                continue
            oracle_rows = _exhaustive_actions(exhaustive_planner, current, pool, projections)
            generated_rows = provide(current)
            oracle_ids = {(a.transfers_out, a.transfers_in): a for a in oracle_rows}
            generated_ids = {(a.transfers_out, a.transfers_in): a for a in generated_rows}
            for k in range(5):
                exhaustive_total_by_k[k] += sum(a.transfers_used == k for a in oracle_rows)
                bounded_total_by_k[k] += sum(a.transfers_used == k for a in generated_rows)
                missed_total_by_k[k] += sum(
                    oracle_ids[key].transfers_used == k for key in oracle_ids.keys() - generated_ids.keys()
                )
        retained_by_k = {
            str(k): sum(a.transfers_used == k for a in root_actions) for k in range(5)
        }
        path_root = (exhaustive_result[3][0][1], exhaustive_result[3][0][2])
        strategies[strategy] = {
            "bounded_optimum": bounded_result[0],
            "objective_gap": exhaustive_result[0] - bounded_result[0],
            "global_optimum_root_action_retained": path_root in root_keys,
            "root_action_coverage_by_k": retained_by_k,
            "root_action_identities_missed": len(exhaustive_keys - root_keys),
            "all_reachable_states_action_coverage_by_k": {
                str(k): {
                    "exhaustive": exhaustive_total_by_k[k],
                    "bounded": bounded_total_by_k[k],
                    "missed": missed_total_by_k[k],
                }
                for k in range(5)
            },
            "states": bounded_counts["states"],
            "actions_evaluated": bounded_counts["actions"],
            "root_actions": len(root_actions),
            "bounded_path": [
                {"action": key[0], "out": list(key[1]), "in": list(key[2])}
                for key in bounded_result[3]
            ],
        }
    return {
        "seed": seed,
        "exhaustive_optimum": exhaustive_result[0],
        "exhaustive_path": [
            {"action": key[0], "out": list(key[1]), "in": list(key[2])}
            for key in exhaustive_result[3]
        ],
        "exhaustive_action_counts_by_k": {str(k): n for k, n in exhaustive_by_k.items()},
        "exhaustive_states": exhaustive_counts["states"],
        "exhaustive_actions_evaluated": exhaustive_counts["actions"],
        "strategies": strategies,
    }


def run(seeds=range(10)) -> dict:
    rules = OptimizerRules.load(ROOT)
    started = time.perf_counter()
    fixtures = [run_seed(seed, rules) for seed in seeds]
    return {
        "oracle": "reduced_exhaustive_v3_three_gameweek_dp",
        "scope": "15-player legal squads; four 50-tenths swappable owned slots and same-price position replacements; eleven 1-tenth fixed slots; zero bank; K<=min(FT,4); native V3 action, lineup, hit, rollover, terminal valuation",
        "beam_width": 40,
        "fixture_count": len(fixtures),
        "runtime_seconds": time.perf_counter() - started,
        "all_exhaustive_actions_retained": all(
            row["strategies"][strategy]["root_action_identities_missed"] == 0
            and all(item["missed"] == 0 for item in row["strategies"][strategy]["all_reachable_states_action_coverage_by_k"].values())
            for row in fixtures for strategy in ("incremental", "compose")
        ),
        "all_optima_retained": all(
            row["strategies"][strategy]["global_optimum_root_action_retained"]
            and abs(row["strategies"][strategy]["objective_gap"]) <= 1e-9
            for row in fixtures for strategy in ("incremental", "compose")
        ),
        "fixtures": fixtures,
    }


def run_club_cycle(rules: OptimizerRules) -> dict:
    """A legal atomic four-club rotation has no legal smaller prefix."""
    from dataclasses import replace

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
    projections = {p.player_id: _projection(p.player_id, (4.0, 4.0, 4.0) if p in owned else (10.0, 10.0, 10.0))
                   for p in pool.values()}
    validate_squad(state, rules)
    config = StrategicPlannerV3Config(max_transfers_per_action=4)
    exact = StrategicPlannerV3(rules, config)
    roots = _exhaustive_actions(exact, state, pool, projections)
    oracle, _ = _solve(exact, state, pool, projections,
                       lambda current: _exhaustive_actions(exact, current, pool, projections))
    result = {"case": "four_clubs_at_cap_atomic_K4_cycle", "exhaustive_optimum": oracle[0],
              "exhaustive_root_counts": {k: sum(a.transfers_used == k for a in roots) for k in range(5)},
              "strategies": {}}
    for strategy in ("incremental", "compose"):
        planner = StrategicPlannerV3(rules, config)
        def provide(current):
            return generate_actions(current, pool, projections, rules, strategy=strategy,
                                    max_transfers=min(current.free_transfers, 4))
        bounded, _ = _solve(planner, state, pool, projections, provide)
        root_actions = provide(state)
        result["strategies"][strategy] = {"bounded_optimum": bounded[0],
            "objective_gap": oracle[0] - bounded[0],
            "global_optimum_root_action_retained": any(a.transfers_used == 4 for a in root_actions),
            "retained_root_counts": {k: sum(a.transfers_used == k for a in root_actions) for k in range(5)}}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", type=int, default=10)
    parser.add_argument("--output", type=Path, default=ROOT / "scratch" / "v3_multi_transfer_20261022" / "oracle_report.json")
    args = parser.parse_args()
    report = run(range(args.seeds))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("fixture_count", "runtime_seconds", "all_exhaustive_actions_retained", "all_optima_retained")}, indent=2))
    print(args.output)


if __name__ == "__main__":
    main()
