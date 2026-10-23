"""Phase 2 candidate generation worker; run only in the isolated solver venv."""

import ctypes
from itertools import groupby
import json
from math import ceil
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


def _model(problem, k, prior, diverse):
    players = problem["players"]
    owned = [p for p in players if p["owned"]]
    incoming = [p for p in players if not p["owned"]]
    size = problem["squad_size"]
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
    model.add(
        problem["bank"]
        + sum(p["price"] * (1 - x[p["player_id"]]) for p in owned)
        - sum(p["price"] * x[p["player_id"]] for p in incoming)
        >= 0
    )
    for package in prior:
        # C diversifies resulting rosters by at least two swaps when K permits.
        distance = (min(4, 2 * k) if k else 1) if diverse else 1
        squad = set(package["resulting_squad"])
        model.add(sum(1 - x[pid] if pid in squad else x[pid] for pid in x) >= distance)
        if diverse:
            model.add(sum(x[pid] for pid in package["transfers_out"]) >= 1)
            model.add(sum(1 - x[pid] for pid in package["transfers_in"]) >= 1)
    accounting = problem["accounting_by_k"][str(k)]
    model.maximize(
        sum(p["weight"] * x[p["player_id"]] for p in players)
        - accounting["hit_cost_points"] * problem["objective_scale"]
    )
    return model, x, owned, incoming, accounting


def solve(problem, *, strategy, context_id, time_limit_seconds=1.0):
    if strategy not in {"A", "B", "C"} or not isinstance(context_id, str) or not context_id.strip():
        raise ValueError("strategy must be A/B/C and context_id must be nonempty")
    if not 0 < time_limit_seconds <= 1:
        raise ValueError("Each CP-SAT solve is limited to (0,1] seconds")
    started = perf_counter()
    players = sorted(problem["players"], key=lambda p: p["player_id"])
    packages = {str(k): [] for k in range(6)}
    attempts = []
    requested = {"A": (5, False), "B": (10, False), "C": (10, True)}[strategy]
    for k in range(6):
        prior = []
        for rank in range(1, requested[0] + 1):
            diverse = requested[1] and rank > 5
            model, x, owned, incoming, accounting = _model(problem, k, prior, diverse)
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
                "status": name,
                "wall_seconds": solver.wall_time,
                "deterministic_seconds": solver.response_proto.deterministic_time,
                "objective_scaled": None,
                "objective_bound_scaled": None,
                "excluded_squads": len(prior),
                "restriction": (
                    f"roster_hamming>={min(4, 2 * k)};different_OUT;different_IN"
                    if diverse and k
                    else "roster_hamming>=1;different_OUT;different_IN"
                    if diverse
                    else "ranked_nogood"
                ),
            }
            attempts.append(attempt)
            if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
                attempt["solution_info"] = solver.solution_info()
                attempt["rejection_reason"] = "no further legal roster satisfies current exclusions"
                break
            selected = sorted(pid for pid, var in x.items() if solver.value(var))
            selected_set = set(selected)
            outs = sorted(p["player_id"] for p in owned if p["player_id"] not in selected_set)
            ins = sorted(p["player_id"] for p in incoming if p["player_id"] in selected_set)
            objective = (
                sum(p["weight"] for p in players if p["player_id"] in selected_set)
                - accounting["hit_cost_points"] * problem["objective_scale"]
            )
            if abs(objective - solver.objective_value) > 0.5:
                raise ValueError(
                    f"CP-SAT objective reconstruction mismatch: {objective} != {solver.objective_value}"
                )
            # CP-SAT exposes an integer objective bound as float; normalize rounding noise.
            bound = objective if name == "OPTIMAL" else ceil(solver.best_objective_bound)
            attempt.update(objective_scaled=objective, objective_bound_scaled=bound)
            packages[str(k)].append(
                {
                    "transfers_out": outs,
                    "transfers_in": ins,
                    "resulting_squad": selected,
                    "resulting_bank": problem["bank"]
                    + sum(p["price"] for p in owned if p["player_id"] in outs)
                    - sum(p["price"] for p in incoming if p["player_id"] in ins),
                    "hit_cost_points": accounting["hit_cost_points"],
                    "free_transfers_before": problem["free_transfers"],
                    "free_transfers_after": accounting["free_transfers_after"],
                    "objective_scaled": objective,
                    "objective_bound_scaled": bound,
                    "status": name,
                    "rank": rank,
                    "excluded_squads": len(prior),
                }
            )
            prior.append(packages[str(k)][-1])
    return {
        "api_version": "cpsat_phase2_candidates_v1",
        "context_id": context_id,
        "input_sha256": problem["input_sha256"],
        "packages_by_k": packages,
        "attempts": attempts,
        "solver_version": ortools.__version__,
        "solver_python": sys.executable,
        "solver_config": {
            "strategy": strategy,
            "workers": 1,
            "seed": 42,
            "per_solve_seconds": time_limit_seconds,
            "generation_limit_per_k": requested[0],
            "diversity": "roster Hamming>=min(4,2*K), different OUT and IN sets from every prior candidate"
            if strategy == "C"
            else None,
        },
        "worker_seconds": perf_counter() - started,
        "peak_memory_mib": peak_memory_mib(),
    }


if __name__ == "__main__":
    request = json.load(sys.stdin)
    json.dump(solve(request["problem"], **request["options"]), sys.stdout, allow_nan=False)
