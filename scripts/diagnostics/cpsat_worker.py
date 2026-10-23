"""Diagnostic JSON worker. Run only with .venv-solver; imports no FPL production module."""

import ctypes
from itertools import groupby
import json
import sys
from time import perf_counter

import ortools
from ortools.sat.python import cp_model


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


def solve(problem, *, candidates_per_k=5, time_limit_seconds=1.0):
    if type(candidates_per_k) is not int or not 1 <= candidates_per_k <= 5:
        raise ValueError("Per-K candidate allocation must be 1..5")
    if not 0 < time_limit_seconds <= 10:
        raise ValueError("Per-solve time limit must be positive and <=10s")
    started = perf_counter()
    players = sorted(problem["players"], key=lambda p: p["player_id"])
    owned = [p for p in players if p["owned"]]
    incoming = [p for p in players if not p["owned"]]
    size = problem["squad_size"]
    packages = {str(k): [] for k in range(6)}
    attempts = []
    for k in range(6):
        model = cp_model.CpModel()
        x = {p["player_id"]: model.new_bool_var(p["player_id"]) for p in players}
        model.add(sum(x.values()) == size)
        for position, quota in sorted(problem["position_quotas"].items()):
            model.add(sum(x[p["player_id"]] for p in players if p["position"] == position) == quota)
        for _, group in groupby(
            sorted(players, key=lambda p: p["club_id"]), key=lambda p: p["club_id"]
        ):
            model.add(sum(x[p["player_id"]] for p in group) <= problem["max_per_club"])
        model.add(sum(1 - x[p["player_id"]] for p in owned) == k)
        model.add(sum(x[p["player_id"]] for p in incoming) == k)
        bank = (
            problem["bank"]
            + sum(p["price"] * (1 - x[p["player_id"]]) for p in owned)
            - sum(p["price"] * x[p["player_id"]] for p in incoming)
        )
        model.add(bank >= 0)
        accounting = problem["accounting_by_k"][str(k)]
        hit = accounting["hit_cost_points"]
        model.maximize(
            sum(p["weight"] * x[p["player_id"]] for p in players) - hit * problem["objective_scale"]
        )
        for rank in range(1, candidates_per_k + 1):
            solver = cp_model.CpSolver()
            solver.parameters.num_search_workers = 1
            solver.parameters.random_seed = 42
            solver.parameters.randomize_search = False
            solver.parameters.max_time_in_seconds = time_limit_seconds
            solver.parameters.absolute_gap_limit = 0.0
            solver.parameters.relative_gap_limit = 0.0
            status = solver.solve(model)
            status_name = solver.status_name(status)
            attempt = {
                "k": k,
                "rank": rank,
                "status": status_name,
                "wall_seconds": solver.wall_time,
                "deterministic_seconds": solver.response_proto.deterministic_time,
                "objective_scaled": None,
                "objective_bound_scaled": None,
                "excluded_squads": rank - 1,
            }
            attempts.append(attempt)
            if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
                attempt["solution_info"] = solver.solution_info()
                break
            selected = sorted(pid for pid, variable in x.items() if solver.value(variable))
            selected_set = set(selected)
            outs = sorted(p["player_id"] for p in owned if p["player_id"] not in selected_set)
            ins = sorted(p["player_id"] for p in incoming if p["player_id"] in selected_set)
            objective = (
                sum(p["weight"] for p in players if p["player_id"] in selected_set)
                - hit * problem["objective_scale"]
            )
            assert objective == solver.objective_value
            attempt.update(
                objective_scaled=objective, objective_bound_scaled=solver.best_objective_bound
            )
            packages[str(k)].append(
                {
                    "transfers_out": outs,
                    "transfers_in": ins,
                    "resulting_squad": selected,
                    "resulting_bank": problem["bank"]
                    + sum(p["price"] for p in owned if p["player_id"] in outs)
                    - sum(p["price"] for p in incoming if p["player_id"] in ins),
                    "hit_cost_points": hit,
                    "free_transfers_before": problem["free_transfers"],
                    "free_transfers_after": accounting["free_transfers_after"],
                    "objective_scaled": objective,
                    "objective_bound_scaled": solver.best_objective_bound,
                    "status": status_name,
                    "rank": rank,
                    "excluded_squads": rank - 1,
                }
            )
            model.add(sum(x[pid] for pid in selected) <= size - 1)
    return {
        "input_sha256": problem["input_sha256"],
        "packages_by_k": packages,
        "attempts": attempts,
        "solver_version": ortools.__version__,
        "solver_python": sys.executable,
        "solver_config": {
            "workers": 1,
            "seed": 42,
            "per_solve_seconds": time_limit_seconds,
            "absolute_gap_limit": 0,
            "relative_gap_limit": 0,
            "allocation_per_k": candidates_per_k,
        },
        "worker_seconds": perf_counter() - started,
        "peak_memory_mib": peak_memory_mib(),
    }


if __name__ == "__main__":
    request = json.load(sys.stdin)
    result = solve(request["problem"], **request["options"])
    json.dump(result, sys.stdout, allow_nan=False)
