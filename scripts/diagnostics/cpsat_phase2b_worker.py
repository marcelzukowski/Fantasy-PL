"""V3-anchored CP-SAT neighborhoods; run only in the isolated solver venv."""

import ctypes
from itertools import groupby
import json
from math import ceil
import sys
from time import perf_counter

import ortools
from ortools.sat.python import cp_model


POSITIONS = ("GK", "DEF", "MID", "FWD")


def peak_memory_mib():
    if sys.platform != "win32":
        return None

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
    if not query(ctypes.windll.kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
        raise ctypes.WinError()
    return counters.peak / 1024**2


def _model(problem, anchor, k, position, extension, exclusions):
    players = problem["players"]
    owned = [p for p in players if p["owned"]]
    incoming = [p for p in players if not p["owned"]]
    model = cp_model.CpModel()
    x = {p["player_id"]: model.new_bool_var(p["player_id"]) for p in players}
    model.add(sum(x.values()) == problem["squad_size"])
    for pos, quota in sorted(problem["position_quotas"].items()):
        model.add(sum(x[p["player_id"]] for p in players if p["position"] == pos) == quota)
    for _, group in groupby(
        sorted(players, key=lambda p: p["club_id"]), key=lambda p: p["club_id"]
    ):
        model.add(sum(x[p["player_id"]] for p in group) <= problem["max_per_club"])
    model.add(sum(1 - x[p["player_id"]] for p in owned) == k)
    model.add(sum(x[p["player_id"]] for p in incoming) == k)
    model.add(
        problem["bank"]
        + sum(p["price"] * (1 - x[p["player_id"]]) for p in owned)
        - sum(p["price"] * x[p["player_id"]] for p in incoming)
        >= 0
    )
    for pid in anchor["transfers_in"]:
        model.add(x[pid] == 1)
    anchor_out = set(anchor["transfers_out"])
    if extension:
        for pid in anchor_out:
            model.add(x[pid] == 0)
    else:
        model.add(sum(1 - x[pid] for pid in anchor_out) >= 1)
        position_in = [
            p["player_id"]
            for p in incoming
            if p["position"] == position and p["player_id"] not in anchor["transfers_in"]
        ]
        model.add(sum(x[pid] for pid in position_in) >= 1)
    for roster in exclusions:
        model.add(sum(1 - x[pid] if pid in roster else x[pid] for pid in x) >= 1)
    accounting = problem["accounting_by_k"][str(k)]
    model.maximize(
        sum(p["weight"] * x[p["player_id"]] for p in players)
        - accounting["hit_cost_points"] * problem["objective_scale"]
    )
    return model, x, owned, incoming, accounting


def solve(problem, anchors, *, context_id, request_sha256, time_limit_seconds=0.35):
    if len(anchors) > 3:
        raise ValueError("At most3 K2 anchors")
    if not isinstance(context_id, str) or not context_id.strip():
        raise ValueError("context_id must be nonempty")
    if not 0 < time_limit_seconds <= 0.35:
        raise ValueError("per-model time limit must be in (0, 0.35]")
    started = perf_counter()
    candidates, attempts, exclusions, per_k_rank = [], [], [], {k: 0 for k in range(3, 6)}
    for anchor_index, anchor in enumerate(anchors):
        cells = [(pos, False) for pos in POSITIONS] + [("ALL", True)]
        for k in range(3, 6):
            for position, extension in cells:
                per_k_rank[k] += 1
                rank = per_k_rank[k]
                cell = f"K{k}:{'extension' if extension else position}"
                model, x, owned, incoming, accounting = _model(
                    problem, anchor, k, position, extension, exclusions
                )
                solver = cp_model.CpSolver()
                solver.parameters.num_search_workers = 1
                solver.parameters.random_seed = 42
                solver.parameters.randomize_search = False
                solver.parameters.max_time_in_seconds = time_limit_seconds
                solver.parameters.absolute_gap_limit = 0.0
                solver.parameters.relative_gap_limit = 0.0
                status = solver.solve(model)
                name = solver.status_name(status)
                attempt = {
                    "k": k,
                    "rank": rank,
                    "solver_rank": 1,
                    "anchor_index": anchor_index,
                    "cell": cell,
                    "status": name,
                    "wall_seconds": solver.wall_time,
                    "deterministic_seconds": solver.response_proto.deterministic_time,
                    "objective_scaled": None,
                    "objective_bound_scaled": None,
                    "excluded_squads": len(exclusions),
                    "restriction": {
                        "anchor_in_retained": list(anchor["transfers_in"]),
                        "anchor_out_retention": "all_preserved" if extension else ">=1 retained",
                        "position_included": None if extension else position,
                    },
                }
                attempts.append(attempt)
                if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
                    attempt["solution_info"] = solver.solution_info()
                    continue
                roster = sorted(pid for pid, var in x.items() if solver.value(var))
                roster_set = set(roster)
                outs = sorted(p["player_id"] for p in owned if p["player_id"] not in roster_set)
                ins = sorted(p["player_id"] for p in incoming if p["player_id"] in roster_set)
                objective = sum(
                    p["weight"] for p in problem["players"] if p["player_id"] in roster_set
                )
                objective -= accounting["hit_cost_points"] * problem["objective_scale"]
                if abs(objective - solver.objective_value) > 0.5:
                    raise ValueError("CP-SAT surrogate reconstruction mismatch")
                bound = objective if name == "OPTIMAL" else ceil(solver.best_objective_bound)
                attempt.update(objective_scaled=objective, objective_bound_scaled=bound)
                exclusions.append(roster_set)
                candidates.append(
                    {
                        "k": k,
                        "rank": rank,
                        "solver_rank": 1,
                        "anchor_index": anchor_index,
                        "cell": cell,
                        "transfers_out": outs,
                        "transfers_in": ins,
                        "resulting_squad": roster,
                        "resulting_bank": problem["bank"]
                        + sum(p["price"] for p in owned if p["player_id"] in outs)
                        - sum(p["price"] for p in incoming if p["player_id"] in ins),
                        "hit_cost_points": accounting["hit_cost_points"],
                        "free_transfers_before": problem["free_transfers"],
                        "free_transfers_after": accounting["free_transfers_after"],
                        "objective_scaled": objective,
                        "objective_bound_scaled": bound,
                        "status": name,
                        "excluded_squads": len(exclusions) - 1,
                        "restriction": attempt["restriction"],
                    }
                )
    return {
        "api_version": "cpsat_phase2b_worker_v1",
        "context_id": context_id,
        "request_sha256": request_sha256,
        "input_sha256": problem["input_sha256"],
        "candidates": candidates,
        "attempts": attempts,
        "solver_version": ortools.__version__,
        "solver_python": sys.executable,
        "solver_config": {
            "workers": 1,
            "seed": 42,
            "per_model_seconds": time_limit_seconds,
            "max_proposals": 72,
            "cells_per_anchor_k": 5,
        },
        "worker_seconds": perf_counter() - started,
        "peak_memory_mib": peak_memory_mib(),
    }


if __name__ == "__main__":
    request = json.load(sys.stdin)
    json.dump(
        solve(request["problem"], request["anchors"], **request["options"]),
        sys.stdout,
        allow_nan=False,
    )
