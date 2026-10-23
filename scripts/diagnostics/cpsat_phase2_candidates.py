"""Phase 2 diagnostic CP-SAT candidate generation with native Phase 1 replay."""

import json
from pathlib import Path
import subprocess
from time import perf_counter

from scripts.diagnostics import cpsat_packages

ROOT = Path(__file__).resolve().parents[2]


def explain_diversity_exclusion(k, package, base_packages):
    """Explain whether C's resulting-roster Hamming cut excludes a package."""
    if type(k) is not int or not 0 <= k <= 5:
        raise ValueError("k must be in 0..5")
    threshold = min(4, 2 * k) if k else 1
    roster = set(package["resulting_squad"])
    comparisons = []
    for base in base_packages:
        distance = len(roster.symmetric_difference(base["resulting_squad"]))
        different_out = set(package["transfers_out"]) != set(base["transfers_out"])
        different_in = set(package["transfers_in"]) != set(base["transfers_in"])
        comparisons.append(
            {
                "base_rank": base["rank"],
                "roster_hamming_distance": distance,
                "different_OUT": different_out,
                "different_IN": different_in,
                "excluded": distance < threshold or not different_out or not different_in,
            }
        )
    return {
        "minimum_roster_hamming_distance": threshold,
        "excluded_by_diversity": any(row["excluded"] for row in comparisons),
        "comparisons": comparisons,
    }


def generate_phase2(
    state, pool, projections, rules, *, strategy, context_id, time_limit_seconds=1.0
):
    """Generate bounded A/B/C candidate rosters and validate using native V3 legality."""
    if strategy not in {"A", "B", "C"}:
        raise ValueError("strategy must be A, B, or C")
    if not isinstance(context_id, str) or not context_id.strip():
        raise ValueError("context_id must be nonempty")
    if not 0 < time_limit_seconds <= 1:
        raise ValueError("time_limit_seconds must be in (0, 1]")
    started = perf_counter()
    pool_rows = cpsat_packages._pool_rows(pool)
    problem = cpsat_packages.prepare_problem(state, pool_rows, projections, rules)
    python = ROOT / ".venv-solver/Scripts/python.exe"
    if not python.is_file():
        raise FileNotFoundError("Isolated .venv-solver Python is unavailable")
    config = {"strategy": strategy, "time_limit_seconds": time_limit_seconds}
    try:
        response = subprocess.run(
            [str(python), str(ROOT / "scripts/diagnostics/cpsat_phase2_worker.py")],
            input=json.dumps(
                {
                    "problem": problem,
                    "options": {
                        "strategy": strategy,
                        "context_id": context_id,
                        "time_limit_seconds": time_limit_seconds,
                    },
                }
            ),
            text=True,
            encoding="utf-8",
            capture_output=True,
            cwd=ROOT,
            check=True,
            timeout=6 * time_limit_seconds * (10 if strategy in {"B", "C"} else 5) + 30,
        )
    except subprocess.CalledProcessError as exc:
        raise RuntimeError("Isolated CP-SAT Phase 2 worker failed:\n" + (exc.stderr or "")) from exc
    generation_seconds = perf_counter() - started
    result = json.loads(response.stdout)
    if result.get("api_version") != "cpsat_phase2_candidates_v1":
        raise ValueError("Phase 2 worker version mismatch")
    if (
        result.get("context_id") != context_id
        or result.get("input_sha256") != problem["input_sha256"]
    ):
        raise ValueError("Phase 2 worker context/input digest mismatch")
    expected_count = {"A": 5, "B": 10, "C": 10}[strategy]
    if (
        result.get("solver_config", {}).get("strategy") != strategy
        or result.get("solver_config", {}).get("generation_limit_per_k") != expected_count
        or result.get("solver_config", {}).get("per_solve_seconds") != time_limit_seconds
        or result.get("solver_config", {}).get("workers") != 1
        or result.get("solver_config", {}).get("seed") != 42
    ):
        raise ValueError("Phase 2 worker configuration mismatch")
    if set(result.get("packages_by_k", {})) != {str(k) for k in range(6)}:
        raise ValueError("Missing K allocation")

    # Phase 1's canonical validator intentionally caps one result at five packages per K.
    # Validate each slice with that unchanged checker, then reject duplicates across slices.
    validation_started = perf_counter()
    empty = dict(result, packages_by_k={str(k): [] for k in range(6)})
    cpsat_packages.validate_packages(problem, state, pool_rows, rules, empty)
    for k in range(6):
        packages = result["packages_by_k"][str(k)]
        if len(packages) > expected_count:
            raise ValueError("Worker exceeded strategy allocation")
        rosters = [tuple(package.get("resulting_squad", ())) for package in packages]
        if len(rosters) != len(set(rosters)):
            raise ValueError("Duplicate package roster")
        if [p.get("rank") for p in packages] != list(range(1, len(packages) + 1)):
            raise ValueError("Invalid package rank sequence")
        if strategy == "C":
            for index, package in enumerate(packages[5:], start=5):
                if explain_diversity_exclusion(k, package, packages[:index])[
                    "excluded_by_diversity"
                ]:
                    raise ValueError("Worker violated C structural diversity constraints")
        for offset in range(0, len(packages), 5):
            part = dict(result)
            part["packages_by_k"] = {key: [] for key in result["packages_by_k"]}
            part["packages_by_k"][str(k)] = packages[offset : offset + 5]
            cpsat_packages.validate_packages(problem, state, pool_rows, rules, part)
    validation_seconds = perf_counter() - validation_started
    if strategy == "C":
        result["diversity_metadata_by_k"] = {
            str(k): {
                "minimum_roster_hamming_distance": min(4, 2 * k) if k else 1,
                "additional_cuts": ["different_OUT", "different_IN"],
                "base_packages": [
                    {
                        key: package[key]
                        for key in ("rank", "transfers_out", "transfers_in", "resulting_squad")
                    }
                    for package in result["packages_by_k"][str(k)][:5]
                ],
                "selected_diverse_packages": [
                    {
                        key: package[key]
                        for key in ("rank", "transfers_out", "transfers_in", "resulting_squad")
                    }
                    for package in result["packages_by_k"][str(k)][5:]
                ],
            }
            for k in range(6)
        }
    result.update(
        api_version="cpsat_phase2_candidates_v1",
        context_metadata={
            "context_id": context_id,
            "input_sha256": problem["input_sha256"],
            "config": config,
        },
        problem=problem,
        generation_seconds=generation_seconds,
        validation_seconds=validation_seconds,
        total_seconds=perf_counter() - started,
        full_v3_objective_modeled=False,
    )
    return result
