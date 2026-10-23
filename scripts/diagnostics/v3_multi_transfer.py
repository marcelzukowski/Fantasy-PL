"""Opt-in bounded multi-transfer action generator for V3 diagnostics."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from itertools import combinations
import time
from typing import Mapping

from fpl_engine.models.projections import PlayerProjection
from fpl_engine.optimizer import (
    OptimizerError, OptimizerRules, SquadPlayer, SquadState, next_free_transfers, validate_squad,
)
from fpl_engine.strategy.strategic_planner_v3 import (
    StrategicAction,
    StrategicPlannerV3,
    StrategicPlannerV3Config,
)


def generate_actions(
    state,
    pool_by_id: Mapping[str, SquadPlayer],
    projections: Mapping[str, PlayerProjection],
    rules: OptimizerRules,
    *,
    strategy="incremental",
    max_transfers=5,
    partial_width=16,
    max_actions=24,
    candidates_per_position=8,
    stats=None,
) -> list[StrategicAction]:
    """Generate exact-legal HOLD and bounded transfer actions; never called by production."""
    if strategy not in {"incremental", "compose"}:
        raise ValueError("strategy must be 'incremental' or 'compose'")
    if max_transfers < 0 or min(partial_width, max_actions, candidates_per_position) < 1:
        raise ValueError("max_transfers must be non-negative; other action limits must be positive")
    if state.free_transfers < 1:
        raise ValueError("V3 SquadState must have at least one free transfer")
    validate_squad(state, rules)
    started = time.perf_counter()
    pool = dict(pool_by_id)
    owned = {p.player_id: p for p in state.players}
    missing_owned = set(owned) - set(projections)
    if missing_owned:
        raise ValueError(f"missing owned-player projections: {sorted(missing_owned)}")
    for player_id in owned:
        pool.setdefault(player_id, owned[player_id])
    planner = StrategicPlannerV3(rules, replace(
        StrategicPlannerV3Config(),
        max_transfers_per_action=max(1, max_transfers),
        candidates_per_position=candidates_per_position,
        max_actions_per_state=max_actions,
    ))
    target_gw = state.current_gameweek
    shortlist = {}
    for position in ("GK", "DEF", "MID", "FWD"):
        shortlist[position] = sorted(
            (p for p in pool.values() if p.player_id not in owned and p.position == position
             and p.player_id in projections
             and planner._gameweek_projection(projections[p.player_id], target_gw) is not None),
            key=lambda p: (-planner._points(projections[p.player_id], target_gw), p.current_price, p.player_id),
        )[:candidates_per_position]
    raw_shortlist_pairs = sum(
        sum(p.position == position for p in state.players) * len(shortlist[position])
        for position in ("GK", "DEF", "MID", "FWD")
    )

    hold = StrategicAction(
        "HOLD", (), (), 0, 0, state.bank, state.free_transfers,
        next_free_transfers(state.free_transfers, 0, rules),
        tuple(sorted(owned)),
    )
    if max_transfers == 0 or max_actions == 1:
        if stats is not None:
            stats.update({
                "attempted_by_k": {0: 0}, "legal_by_k": {0: 0}, "retained_by_k": {0: 1},
                "seed_pairs": 0, "runtime_seconds": time.perf_counter() - started,
            })
        return [hold]
    attempted = defaultdict(int)
    legal = defaultdict(int)
    canonical = {}

    def add(outs, ins):
        outs, ins = tuple(sorted(outs)), tuple(sorted(ins))
        k = len(outs)
        attempted[k] += 1
        if not k or len(outs) != len(ins) or len(set(outs)) != k or len(set(ins)) != k:
            return None
        if set(outs) & set(ins) or not set(outs) <= owned.keys() or set(ins) & owned.keys():
            return None
        action = planner._make_action(state, tuple(owned[x] for x in outs), tuple(pool[x] for x in ins))
        if action is None:
            return None
        try:
            next_players = tuple(pool[x] if x in ins else owned[x] for x in action.resulting_squad)
            validate_squad(replace(state, players=next_players, bank=action.resulting_bank), rules)
        except (KeyError, OptimizerError):
            return None
        key = (action.transfers_out, action.transfers_in)
        if key not in canonical:
            canonical[key] = action
            legal[k] += 1
        return canonical[key]

    singles = []
    if strategy == "compose":
        for out in state.players:
            for incoming in shortlist[out.position]:
                row = add((out.player_id,), (incoming.player_id,))
                if row is not None:
                    singles.append(row)
        singles.sort(key=lambda a: (-planner._quick_gain(a, owned, pool, projections, target_gw), a.transfers_out, a.transfers_in))

    if strategy == "incremental":
        # shortcut: every prefix must be legal and affordable; upgrade if only an invalid subset reaches a valid package.
        layers = {0: [((), ())]}
        for k in range(1, max_transfers + 1):
            generated = {}
            for prev_outs, prev_ins in layers[k - 1]:
                used_out, used_in = set(prev_outs), set(prev_ins)
                for out in state.players:
                    if out.player_id in used_out:
                        continue
                    for incoming in shortlist[out.position]:
                        if incoming.player_id in used_in:
                            continue
                        outs, ins = (*prev_outs, out.player_id), (*prev_ins, incoming.player_id)
                        row = add(outs, ins)
                        if row is not None:
                            generated[(row.transfers_out, row.transfers_in)] = row
            ranked = sorted(generated.values(), key=lambda a: (
                -planner._quick_gain(a, owned, pool, projections, target_gw), a.transfers_out, a.transfers_in
            ))[:partial_width]
            layers[k] = [(a.transfers_out, a.transfers_in) for a in ranked]
    else:
        # Seed with top legal singles and legal disjoint pairs; each later layer
        # composes those bounded moves and validates the complete union exactly.
        pair_seeds = []
        for left, right in combinations(singles[:24], 2):
            if set(left.transfers_out) & set(right.transfers_out) or set(left.transfers_in) & set(right.transfers_in):
                continue
            row = add((*left.transfers_out, *right.transfers_out), (*left.transfers_in, *right.transfers_in))
            if row is not None:
                pair_seeds.append(row)
        pair_seeds.sort(key=lambda a: (-planner._quick_gain(a, owned, pool, projections, target_gw),
                                       a.transfers_out, a.transfers_in))
        seed = [*singles[:20], *pair_seeds[:4]]
        layers = {0: [((), ())]}
        for k in range(1, max_transfers + 1):
            generated = {}
            for move in seed:
                previous_k = k - move.transfers_used
                if previous_k < 0:
                    continue
                for prev_outs, prev_ins in layers.get(previous_k, ()):
                    if set(prev_outs) & set(move.transfers_out) or set(prev_ins) & set(move.transfers_in):
                        continue
                    row = add((*prev_outs, *move.transfers_out), (*prev_ins, *move.transfers_in))
                    if row is not None:
                        generated[(row.transfers_out, row.transfers_in)] = row
            ranked = sorted(generated.values(), key=lambda a: (
                -planner._quick_gain(a, owned, pool, projections, target_gw), a.transfers_out, a.transfers_in
            ))[:partial_width]
            layers[k] = [(a.transfers_out, a.transfers_in) for a in ranked]

    by_k = defaultdict(list)
    for action in canonical.values():
        by_k[action.transfers_used].append(action)
    for rows in by_k.values():
        rows.sort(key=lambda a: (-planner._quick_gain(a, owned, pool, projections, target_gw), a.transfers_out, a.transfers_in))
    chosen = [hold]
    for k in range(1, max_transfers + 1):
        if by_k[k] and len(chosen) < max_actions:
            chosen.append(by_k[k][0])
    rest = sorted((a for k, rows in by_k.items() if k <= max_transfers for a in rows if a not in chosen),
                  key=lambda a: (-planner._quick_gain(a, owned, pool, projections, target_gw), a.transfers_used,
                                 a.transfers_out, a.transfers_in))
    chosen.extend(rest[:max(0, max_actions - len(chosen))])
    retained = {k: sum(a.transfers_used == k for a in chosen) for k in range(max_transfers + 1)}
    if stats is not None:
        stats.update({
            "attempted_by_k": {k: attempted[k] for k in range(max_transfers + 1)},
            "legal_by_k": {k: legal[k] for k in range(max_transfers + 1)},
            "retained_by_k": retained,
            "seed_pairs": raw_shortlist_pairs,
            "compose_pair_seeds": len(pair_seeds[:4]) if strategy == "compose" else 0,
            "runtime_seconds": time.perf_counter() - started,
        })
    return chosen
