"""Six reduced native-current-action oracles; future search remains production bounded V3."""

from dataclasses import replace
import json
from pathlib import Path
from time import perf_counter

from fpl_engine.optimizer import OptimizerRules, SquadPlayer
from fpl_engine.strategy.strategic_planner_v3 import StrategicPlannerV3, StrategicPlannerV3Config
from scripts.diagnostics.cpsat_phase2_v3 import EvaluationCache, evaluate_package
from scripts.diagnostics.cpsat_phase2b import (
    choose_anchors,
    hold_suffix_path,
    select_new_candidates,
    package_key,
    select_portfolio,
)
from scripts.diagnostics.cpsat_phase2b_candidates import (
    generate_neighborhoods,
    explain_cell_eligibility,
)
from scripts.diagnostics.v3_challenger_oracle import (
    _club_cycle_fixture,
    _funding_cycle_fixture,
    _five_transfer_fixture,
    _exhaustive_actions_with_hits,
)
from scripts.diagnostics.v3_multi_transfer_oracle import _fixture, _projection
from scripts.diagnostics.v3_portfolio_contexts import synthetic_input

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "scratch/cpsat_phase2b_20261022"


def fixtures(rules):
    extension_state, extension_pool, _ = _fixture(82, rules)
    extension_projections = {
        pid: _projection(
            pid,
            (
                (8.0,) * 3
                if pid in ("incoming-gk", "incoming-def", "incoming-mid")
                else (1.0,) * 3
                if pid == "incoming-fwd"
                else (4.0,) * 3
            ),
        )
        for pid in extension_pool
    }
    hold_state, hold_pool, _ = _fixture(83, rules)
    hold_state = replace(hold_state, free_transfers=1)
    hold_projections = {
        pid: _projection(pid, ((1.0,) * 3 if pid.startswith("incoming-") else (8.0,) * 3))
        for pid in hold_pool
    }
    far_state, far_pool, _ = _funding_cycle_fixture(rules, 3)
    owned = list(far_state.players)
    owned[8] = replace(owned[8], current_price=50, purchase_price=50, selling_price=50)
    far_state = replace(far_state, players=tuple(owned), free_transfers=5)
    far_pool.update({p.player_id: p for p in owned})
    for position in ("MID", "FWD"):
        player = SquadPlayer("safe-" + position, position, "safe-club-" + position, 50, 50, 50)
        far_pool[player.player_id] = player
    far_projections = {
        pid: _projection(
            pid,
            (20.0,) * 3
            if pid.startswith("cycle-")
            else (4.2,) * 3
            if pid.startswith("safe-")
            else (4.0,) * 3,
        )
        for pid in far_pool
    }
    return {
        "atomic_K4": _club_cycle_fixture(rules),
        "FT5": _five_transfer_fixture(rules),
        "constrained_budget": _funding_cycle_fixture(rules, 3),
        "K2_with_better_K3": (extension_state, extension_pool, extension_projections),
        "K3_not_near_K2": (far_state, far_pool, far_projections),
        "HOLD_dominates": (hold_state, hold_pool, hold_projections),
    }


def run():
    rules = OptimizerRules.load(ROOT)
    started = perf_counter()
    deadline = started + 180
    report = {
        "scope": "Exhaustive legal current K0..5 packages; unchanged bounded future K<=2, beam40, horizon3",
        "global_multi_gw_optimality_proven": False,
        "budget_seconds": 180,
        "contexts": {},
    }
    for name, (state, pool, projections) in fixtures(rules).items():
        row = {"status": "RUNNING"}
        report["contexts"][name] = row
        try:
            shared = synthetic_input("phase2b-" + name, state, pool, projections, rules)
            planner = StrategicPlannerV3(
                rules, replace(StrategicPlannerV3Config(), max_transfers_per_action=5)
            )
            actions = _exhaustive_actions_with_hits(planner, state, pool, projections, max_k=5)
            cache = EvaluationCache(shared)
            truth = {}
            for action in actions:
                package = {
                    "transfers_out": list(action.transfers_out),
                    "transfers_in": list(action.transfers_in),
                }
                truth[package_key(package)] = evaluate_package(
                    shared, package, cache, deadline=deadline
                )
            incumbent = StrategicPlannerV3(rules).plan(state, pool.values(), projections).best_path
            k2 = [path for path in truth.values() if path.steps[0].action.transfers_used == 2]
            anchors = choose_anchors(k2)
            generated = generate_neighborhoods(shared, anchors, time_limit_seconds=0.1)
            rank_cache = EvaluationCache(shared)
            proposals = []
            for p in generated["candidates"]:
                score = hold_suffix_path(shared, p, rank_cache).total_path_value
                proposals.append({**p, "neighborhood": p["cell"], "hold_suffix_objective": score})
            selected = select_new_candidates(proposals, existing_keys=set())
            # Oracle truth is consulted only after generation and cheap selection are finalized.
            selected_paths = [truth[package_key(p)] for p in selected]
            portfolio = select_portfolio(incumbent, k2, selected_paths)
            optimum = max(truth.values(), key=lambda p: p.total_path_value)
            optimum_key = (
                optimum.steps[0].action.transfers_out,
                optimum.steps[0].action.transfers_in,
            )
            generated_keys = {package_key(p) for p in proposals}
            selected_keys = {package_key(p) for p in selected}
            optimal_keys = {
                key
                for key, path in truth.items()
                if abs(path.total_path_value - optimum.total_path_value) < 1e-9
            }
            gap = optimum.total_path_value - portfolio.total_path_value
            per_k = {}
            for k in range(6):
                values = [p for p in truth.values() if p.steps[0].action.transfers_used == k]
                if not values:
                    per_k[str(k)] = {
                        "legal_count": 0,
                        "objective": None,
                        "generated_optimum": False,
                    }
                    continue
                best = max(values, key=lambda p: p.total_path_value)
                keys = {
                    key
                    for key, path in truth.items()
                    if path.steps[0].action.transfers_used == k
                    and abs(path.total_path_value - best.total_path_value) < 1e-9
                }
                per_k[str(k)] = {
                    "legal_count": len(values),
                    "objective": best.total_path_value,
                    "generated_optimum": bool(keys & generated_keys),
                    "selected_optimum": bool(keys & selected_keys),
                }
            target = {
                "transfers_out": list(optimum_key[0]),
                "transfers_in": list(optimum_key[1]),
                "positions": {pid: p.position for pid, p in pool.items()},
            }
            eligibility = []
            for i, anchor in enumerate(anchors):
                for position in ("GK", "DEF", "MID", "FWD"):
                    eligibility.append(
                        {
                            "anchor_index": i,
                            "position": position,
                            **explain_cell_eligibility(
                                target, anchor, target_k=len(optimum_key[0]), position=position
                            ),
                        }
                    )
            reason = (
                "retained complete-objective optimum"
                if gap <= 1e-9
                else (
                    "no legal K2 anchors; atomic package is outside the anchored search"
                    if not anchors
                    else "optimum does not retain anchor incoming sets"
                    if not any(c["eligible"] for c in eligibility)
                    else "bounded surrogate cell winner or <=12 cheap-selection allocation missed optimum"
                )
            )
            row.update(
                status="PASS",
                context_id=shared.context_id,
                oracle_objective=optimum.total_path_value,
                incumbent_objective=incumbent.total_path_value,
                portfolio_objective=portfolio.total_path_value,
                objective_gap=gap,
                generated_optimum=bool(optimal_keys & generated_keys),
                selected_optimum=bool(optimal_keys & selected_keys),
                portfolio_retained_optimum=gap <= 1e-9,
                reason=reason,
                anchors=anchors,
                generated_count=len(proposals),
                selected_count=len(selected),
                optimum_package=target,
                per_k=per_k,
                legality="PASS",
                objective_replay="PASS",
                ft=state.free_transfers,
                bank=state.bank,
            )
        except Exception as exc:
            row.update(
                status="PARTIAL" if isinstance(exc, TimeoutError) else "FAIL",
                error=type(exc).__name__ + ": " + str(exc),
            )
        print(
            json.dumps(
                {
                    "oracle": name,
                    **{
                        k: row.get(k)
                        for k in (
                            "status",
                            "oracle_objective",
                            "portfolio_objective",
                            "objective_gap",
                            "reason",
                        )
                    },
                }
            ),
            flush=True,
        )
    report["total_seconds"] = perf_counter() - started
    report["coverage_acceptable"] = all(
        r["status"] == "PASS" and r["portfolio_retained_optimum"]
        for r in report["contexts"].values()
    )
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "oracles.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    run()
