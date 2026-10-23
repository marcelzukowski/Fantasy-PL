"""Frozen GW8 Phase1 candidate audit. No V3 evaluation or production writes."""
# Standalone diagnostic entry point resolves the repository before engine imports.
# ruff: noqa: E402

from collections import Counter
from dataclasses import replace
import json
from pathlib import Path
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

from fpl_engine.strategy.strategic_planner_v3 import StrategicPlannerV3, StrategicPlannerV3Config
from scripts.diagnostics.cpsat_packages import generate_packages, SCALE
from scripts.diagnostics import v3_portfolio_contexts as contexts
from scripts.diagnostics.v3_challenger_benchmark import peak_memory

OUT = ROOT / "scratch/cpsat_phase1_20261022"


def reference_check(label, outs, ins, names, shared, result):
    out_ids = sorted(pid for pid, name in names.items() if name in outs)
    in_ids = sorted(pid for pid, name in names.items() if name in ins)
    assert len(out_ids) == len(outs) and len(in_ids) == len(ins)
    rows = {p["player_id"]: p for p in result["problem"]["players"]}
    if not set(out_ids + in_ids) <= set(rows):
        return {
            "reference": label,
            "generated": False,
            "cause": "candidate_pool",
            "missing_ids": sorted(set(out_ids + in_ids) - set(rows)),
        }
    pool = {p.player_id: p for p in shared.player_pool}
    owned = {p.player_id: p for p in shared.state.players}
    native = StrategicPlannerV3(
        shared.rules, replace(StrategicPlannerV3Config(), max_transfers_per_action=5)
    )
    action = native._make_action(
        shared.state, tuple(owned[x] for x in out_ids), tuple(pool[x] for x in in_ids)
    )
    if action is None:
        return {"reference": label, "generated": False, "cause": "native_constraints"}
    score = (
        sum(rows[pid]["weight"] for pid in action.resulting_squad) - action.hit_cost_points * SCALE
    )
    packages = result["packages_by_k"][str(len(outs))]
    generated = any(p["transfers_out"] == out_ids and p["transfers_in"] == in_ids for p in packages)
    cause = "generated"
    if not generated:
        if len(packages) == 5 and all(p["status"] == "OPTIMAL" for p in packages):
            cutoff = min(p["objective_scaled"] for p in packages)
            assert score <= cutoff, "Known legal package violates reported top-five optimum"
            cause = (
                "surrogate_ranking_below_top_five"
                if score < cutoff
                else "surrogate_tie_at_top_five_boundary"
            )
        else:
            cause = "bounded_search_or_allocation"
    return {
        "reference": label,
        "out": sorted(outs),
        "in": sorted(ins),
        "generated": generated,
        "cause": cause,
        "native_legality": "PASS",
        "surrogate_scaled": score,
        "surrogate_points": score / SCALE,
        "fifth_surrogate_points": packages[-1]["objective_scaled"] / SCALE if packages else None,
    }


def main():
    OUT.mkdir(exist_ok=True)
    contexts.OUT = OUT
    shared = contexts.load_frozen(
        ROOT
        / "data/processed/desktop_analyses/2026-27/desktop-analysis-20261022T081445787253Z.json"
    )
    assert shared.context_id == "9362daa92b379107175befb935f70b38d755f7fd5c9196560e28791d3e0c1208"
    names = {
        p["player_id"]: p["display_name"]
        for p in json.loads(
            (
                ROOT
                / "data/processed/predictions/2026-27"
                / shared.bundle_identity
                / "current_players.json"
            ).read_text(encoding="utf-8")
        )
    }
    started = perf_counter()
    result = generate_packages(
        shared.state, shared.player_pool, shared.projections, shared.rules, time_limit_seconds=2.0
    )
    result["frozen_context_id"] = shared.context_id
    result["projection_run_id"] = shared.bundle_identity
    result["projection_artifact_hashes"] = shared.artifact_identities
    result["native_parent_peak_memory_mib"] = peak_memory()
    result["diagnostic_wall_seconds"] = perf_counter() - started
    result["candidate_counts"] = {k: len(v) for k, v in result["packages_by_k"].items()}
    result["candidate_universe"] = {
        "total": len(result["problem"]["players"]),
        "owned": sum(p["owned"] for p in result["problem"]["players"]),
        "incoming": sum(not p["owned"] for p in result["problem"]["players"]),
        "excluded": result["problem"]["excluded_candidates"],
    }
    result["known_packages"] = [
        reference_check(
            "known_K2", {"Giles", "B.Fernandes"}, {"Gabriel", "Mbeumo"}, names, shared, result
        ),
        reference_check(
            "known_K3",
            {"De Cuyper", "Sels", "B.Fernandes"},
            {"Gabriel", "Mbeumo", "Raya"},
            names,
            shared,
            result,
        ),
    ]
    result["top_packages_named"] = {
        k: [
            {
                **p,
                "out_names": [names[x] for x in p["transfers_out"]],
                "in_names": [names[x] for x in p["transfers_in"]],
                "surrogate_points": p["objective_scaled"] / SCALE,
            }
            for p in packages
        ]
        for k, packages in result["packages_by_k"].items()
    }
    (OUT / "gw8_candidates.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    repeat = generate_packages(
        shared.state, shared.player_pool, shared.projections, shared.rules, time_limit_seconds=2.0
    )
    assert repeat["packages_by_k"] == result["packages_by_k"], (
        "GW8 candidate output is nondeterministic"
    )
    result["deterministic_repeat"] = True
    (OUT / "gw8_candidates.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                key: result[key]
                for key in (
                    "candidate_counts",
                    "candidate_universe",
                    "known_packages",
                    "total_seconds",
                    "worker_seconds",
                    "peak_memory_mib",
                    "native_parent_peak_memory_mib",
                    "deterministic_repeat",
                )
            }
        )
    )
    print("STATUSES", dict(Counter(a["status"] for a in result["attempts"])))


if __name__ == "__main__":
    main()
