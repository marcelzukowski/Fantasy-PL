"""Bounded offline GW8 CP-SAT + native V3 evidence. No production entrypoint."""

from dataclasses import asdict, replace
import ctypes
import json
from pathlib import Path
from time import perf_counter

from fpl_engine.strategy.strategic_planner_v3 import (
    StrategicPlannerV3,
    StrategicPlannerV3Config,
    StrategicPath,
)
from scripts.diagnostics import v3_portfolio_contexts as contexts
from scripts.diagnostics.cpsat_packages import digest
from scripts.diagnostics.cpsat_phase2_v3 import (
    EvaluationCache,
    evaluate_package,
    root_action,
    guarded_selection,
)
from scripts.diagnostics.v3_guarded_portfolio import input_digest, validate_path, execute_policy
from scripts.diagnostics.v3_multi_transfer_oracle import _hold

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "scratch/cpsat_phase2_20261022"
BUDGET_SECONDS = 900
MAX_UNIQUE = 80


def peak_memory_mib():
    class Counters(ctypes.Structure):
        _fields_ = [("cb", ctypes.c_ulong), ("faults", ctypes.c_ulong)] + [
            (name, ctypes.c_size_t)
            for name in (
                "peak",
                "working",
                "peak_paged",
                "paged",
                "peak_nonpaged",
                "nonpaged",
                "pagefile",
                "peak_pagefile",
            )
        ]

    counters = Counters()
    counters.cb = ctypes.sizeof(counters)
    ctypes.windll.kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    query = ctypes.windll.psapi.GetProcessMemoryInfo
    query.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong]
    handle = ctypes.windll.kernel32.GetCurrentProcess()
    if not query(handle, ctypes.byref(counters), counters.cb):
        raise OSError("Cannot read peak working set")
    return counters.peak / 1024**2


def save(name, payload):
    (OUT / name).write_text(
        json.dumps(payload, indent=2, default=str, allow_nan=False), encoding="utf-8"
    )


def references(shared, names):
    """Observation only: never passed to generation or its ranking/constraints."""
    rows = {}
    for label, outs, ins, expected in (
        ("K2", {"Giles", "B.Fernandes"}, {"Gabriel", "Mbeumo"}, 148.26775),
        ("K3", {"De Cuyper", "Sels", "B.Fernandes"}, {"Gabriel", "Mbeumo", "Raya"}, 148.61620),
    ):
        package = {
            "transfers_out": sorted(pid for pid, name in names.items() if name in outs),
            "transfers_in": sorted(pid for pid, name in names.items() if name in ins),
        }
        assert len(package["transfers_out"]) == len(outs) and len(package["transfers_in"]) == len(
            ins
        )
        first = root_action(shared, package)
        planner = StrategicPlannerV3(
            shared.rules, replace(StrategicPlannerV3Config(), max_transfers_per_action=5)
        )
        state, steps = shared.state, []
        pool = {p.player_id: p for p in shared.player_pool}
        for offset in range(3):
            action = first if offset == 0 else _hold(state, shared.rules)
            state, step = planner._evaluate_action(
                state,
                action,
                pool,
                shared.projections,
                target_gameweek=state.current_gameweek,
                signals=None,
                offset=offset,
            )
            steps.append(step)
        points = sum(s.points_after_hit for s in steps)
        terminal = planner._terminal_ft_value(state)
        path = StrategicPath(tuple(steps), points, terminal, points + terminal)
        replay = validate_path(shared, path, max_k=5)
        assert abs(path.total_path_value - expected) < 1e-9, (label, path.total_path_value)
        rows[label] = {
            "package": package,
            "objective": path.total_path_value,
            "path": asdict(path),
            "replay": replay,
        }
    return rows


def main():
    from scripts.diagnostics.cpsat_phase2_candidates import generate_phase2

    OUT.mkdir(parents=True, exist_ok=True)
    contexts.OUT = OUT
    started = perf_counter()
    deadline = started + BUDGET_SECONDS
    shared = contexts.load_frozen(
        ROOT
        / "data/processed/desktop_analyses/2026-27/desktop-analysis-20261022T081445787253Z.json"
    )
    original = input_digest(shared)
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
    report = {
        "schema_version": "cpsat_phase2_benchmark_v1",
        "context_id": shared.context_id,
        "input_sha256": original,
        "config": asdict(StrategicPlannerV3Config()),
        "budget_seconds": BUDGET_SECONDS,
        "max_unique": MAX_UNIQUE,
        "status": "RUNNING",
        "strategies": {},
        "full_multi_gw_optimality_proven": False,
    }
    before = perf_counter()
    incumbent = execute_policy(shared)
    report["incumbent_seconds"] = perf_counter() - before
    report["incumbent"] = asdict(incumbent.result.best_path)
    report["incumbent_replay"] = validate_path(shared, incumbent.result.best_path, max_k=2)
    assert abs(incumbent.result.best_path.total_path_value - 147.42035) < 1e-9
    report["references"] = references(shared, names)
    print(
        json.dumps(
            {
                "stage": "independent_references",
                "seconds": perf_counter() - started,
                "incumbent": incumbent.result.best_path.total_path_value,
            }
        ),
        flush=True,
    )
    cache = EvaluationCache(shared)
    best = incumbent.result.best_path
    partial = False
    for strategy in ("A", "B", "C"):
        # Reserve the full bounded worker timeout before starting another strategy.
        if deadline - perf_counter() < 90:
            partial = True
            break
        strategy_start = perf_counter()
        try:
            generated = generate_phase2(
                shared.state,
                shared.player_pool,
                shared.projections,
                shared.rules,
                strategy=strategy,
                context_id=shared.context_id,
                time_limit_seconds=1.0,
            )
            save(strategy + "_candidates.json", generated)
        except Exception as exc:
            report["strategies"][strategy] = {
                "status": "FAILED",
                "error": type(exc).__name__ + ": " + str(exc),
                "incumbent_preserved": True,
            }
            save("results.json", report)
            continue
        row = {
            "status": "RUNNING",
            "counts_by_k": {k: len(v) for k, v in generated["packages_by_k"].items()},
            "generation_seconds": generated.get("generation_seconds"),
            "validation_seconds": generated.get("validation_seconds"),
            "worker_peak_memory_mib": generated.get("peak_memory_mib"),
            "evaluations": [],
            "best_by_k": {},
            "recall": {},
        }
        report["strategies"][strategy] = row
        for label, reference in report["references"].items():
            key = reference["package"]
            matching = [
                p
                for p in generated["packages_by_k"][str(len(key["transfers_out"]))]
                if p["transfers_out"] == key["transfers_out"]
                and p["transfers_in"] == key["transfers_in"]
            ]
            weights = {p["player_id"]: p["weight"] for p in generated["problem"]["players"]}
            action = root_action(shared, key)
            surrogate = (
                sum(weights[pid] for pid in action.resulting_squad)
                - action.hit_cost_points * generated["problem"]["objective_scale"]
            )
            row["recall"][label] = {
                "generated": bool(matching),
                "reference_surrogate_scaled": surrogate,
                "rank": matching[0]["rank"] if matching else None,
                "reason": "generated; fixed root keeps all <=24 GW9 actions in beam40"
                if matching
                else "outside bounded surrogate allocation"
                if strategy in ("A", "B")
                else "outside top5 surrogate and/or structural-distance allocation; inspect diversity metadata",
            }
            if strategy == "C" and not matching:
                from scripts.diagnostics.cpsat_phase2_candidates import explain_diversity_exclusion

                previous = generated["packages_by_k"][str(len(key["transfers_out"]))]
                row["recall"][label]["diversity_exclusion"] = explain_diversity_exclusion(
                    len(key["transfers_out"]),
                    {**key, "resulting_squad": list(action.resulting_squad)},
                    previous,
                )
        v3_seconds = 0.0
        for k, packages in generated["packages_by_k"].items():
            for package in packages:
                key = (tuple(package["transfers_out"]), tuple(package["transfers_in"]))
                if perf_counter() >= deadline or (
                    key not in cache.packages and len(cache.packages) >= MAX_UNIQUE
                ):
                    row["status"] = "PARTIAL"
                    partial = True
                    break
                before = perf_counter()
                try:
                    path = evaluate_package(shared, package, cache, deadline=deadline)
                    elapsed = perf_counter() - before
                    v3_seconds += elapsed
                    selection, error = guarded_selection(best, lambda: path)
                    assert (
                        error is None
                        and selection.total_path_value
                        >= incumbent.result.best_path.total_path_value
                    )
                    best = selection
                    record = {
                        "k": int(k),
                        "rank": package["rank"],
                        "objective": path.total_path_value,
                        "seconds": elapsed,
                        "out_names": [names[x] for x in package["transfers_out"]],
                        "in_names": [names[x] for x in package["transfers_in"]],
                        "path": asdict(path),
                    }
                    for label, reference in report["references"].items():
                        if (
                            package["transfers_out"] == reference["package"]["transfers_out"]
                            and package["transfers_in"] == reference["package"]["transfers_in"]
                        ):
                            assert path.total_path_value + 1e-9 >= reference["objective"], (
                                "Known suffix lost by native future search"
                            )
                            row["recall"][label].update(
                                evaluated_objective=path.total_path_value,
                                future_reference_lost=False,
                                pruning_stage=None,
                                explanation="GW9 <=24 nodes fit beam40; GW10 sorts complete objective including terminal FT before pruning",
                            )
                    row["evaluations"].append(record)
                    old = row["best_by_k"].get(k)
                    if old is None or record["objective"] > old["objective"]:
                        row["best_by_k"][k] = record
                    print(
                        json.dumps(
                            {
                                "strategy": strategy,
                                "k": int(k),
                                "rank": package["rank"],
                                "objective": path.total_path_value,
                                "seconds": round(elapsed, 3),
                                "unique": len(cache.packages),
                            }
                        ),
                        flush=True,
                    )
                except Exception as exc:
                    row.setdefault("failures", []).append(
                        {
                            "k": int(k),
                            "rank": package["rank"],
                            "error": type(exc).__name__ + ": " + str(exc),
                            "incumbent_preserved": True,
                        }
                    )
                    if isinstance(exc, TimeoutError):
                        row["status"] = "PARTIAL"
                        partial = True
                        break
                report["cache"] = cache.metrics()
                save("results.json", report)
            if row["status"] == "PARTIAL":
                break
        row["v3_seconds_including_replay"] = v3_seconds
        row["total_seconds"] = perf_counter() - strategy_start
        if row["status"] == "RUNNING":
            row["status"] = "FAIL" if row.get("failures") else "PASS"
        if row["evaluations"]:
            top = max(row["evaluations"], key=lambda r: r["objective"])
            row.update(
                best_overall=top,
                delta_vs_incumbent=top["objective"] - incumbent.result.best_path.total_path_value,
                delta_vs_hold=top["objective"] - incumbent.result.hold_now_path.total_path_value,
            )
        save("results.json", report)
        if partial:
            break
    assert input_digest(shared) == original
    report.update(
        status="PARTIAL"
        if partial
        else "PASS"
        if all(r["status"] == "PASS" for r in report["strategies"].values())
        and len(report["strategies"]) == 3
        else "FAIL",
        selected=asdict(best),
        cache=cache.metrics(),
        total_seconds=perf_counter() - started,
        peak_memory_mib=peak_memory_mib(),
        production_input_unchanged=True,
    )
    report["artifact_payload_sha256"] = digest(report)
    save("results.json", report)
    print(
        json.dumps({k: report[k] for k in ("status", "total_seconds", "peak_memory_mib", "cache")}),
        flush=True,
    )


if __name__ == "__main__":
    main()
