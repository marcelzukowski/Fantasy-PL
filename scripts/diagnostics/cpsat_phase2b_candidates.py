"""Bounded V3-anchored CP-SAT neighborhoods with unchanged native replay."""

import json
from math import isfinite
from pathlib import Path
import subprocess
from time import perf_counter

from fpl_engine.strategy.strategic_planner_v3 import StrategicPlannerV3, StrategicPlannerV3Config
from scripts.diagnostics import cpsat_packages


ROOT = Path(__file__).resolve().parents[2]


def validate_anchors(anchors):
    if not isinstance(anchors, (list, tuple)) or len(anchors) > 3:
        raise ValueError("Expected at most three V3 anchors")
    allowed = {"transfers_out", "transfers_in", "v3_objective"}
    for anchor in anchors:
        if not isinstance(anchor, dict) or set(anchor) != allowed:
            raise ValueError("Invalid anchor schema")
        if (
            len(anchor["transfers_out"]) != 2
            or len(anchor["transfers_in"]) != 2
            or anchor["transfers_out"] != sorted(set(anchor["transfers_out"]))
            or anchor["transfers_in"] != sorted(set(anchor["transfers_in"]))
            or set(anchor["transfers_out"]) & set(anchor["transfers_in"])
        ):
            raise ValueError("Anchors must be canonical K2 transfer sets")
        if isinstance(anchor["v3_objective"], bool) or not isfinite(anchor["v3_objective"]):
            raise ValueError("Invalid anchor objective")
    if len({(tuple(a["transfers_out"]), tuple(a["transfers_in"])) for a in anchors}) != len(
        anchors
    ):
        raise ValueError("Duplicate anchor identity")
    return anchors


def explain_cell_eligibility(candidate, anchor, *, target_k, position=None, extension=False):
    """Return exact structural cuts that exclude a transfer set from one cell."""
    outs, ins = set(candidate["transfers_out"]), set(candidate["transfers_in"])
    anchor_out, anchor_in = set(anchor["transfers_out"]), set(anchor["transfers_in"])
    cuts = []
    if len(outs) != target_k or len(ins) != target_k:
        cuts.append("target_transfer_count")
    if not anchor_in <= ins:
        cuts.append("anchor_in_not_retained")
    if extension:
        if not anchor_out <= outs:
            cuts.append("extension_does_not_preserve_all_anchor_out")
    elif not anchor_out & outs:
        cuts.append("no_anchor_out_retained")
    if position and not any(
        pid not in anchor_in for pid in ins if candidate.get("positions", {}).get(pid) == position
    ):
        cuts.append(f"no_new_incoming_at_position:{position}")
    return {"eligible": not cuts, "cuts": cuts}


def generate_neighborhoods(shared, anchors, *, time_limit_seconds=0.35):
    """Propose K3..K5 rosters around supplied native V3-evaluated K2 anchors."""
    anchors = validate_anchors(anchors)
    if not 0 < time_limit_seconds <= 0.35:
        raise ValueError("time_limit_seconds must be in (0, 0.35]")
    state, pool, projections, rules = (
        shared.state,
        shared.player_pool,
        shared.projections,
        shared.rules,
    )
    context_id = getattr(shared, "context_id", None) or getattr(shared, "planning_context", None)
    if not isinstance(context_id, str) or not context_id.strip():
        raise ValueError("shared context_id must be nonempty")
    started = perf_counter()
    pool = cpsat_packages._pool_rows(pool)
    problem = cpsat_packages.prepare_problem(state, pool, projections, rules)
    owned = {player.player_id: player for player in state.players}
    planner = StrategicPlannerV3(rules, StrategicPlannerV3Config(max_transfers_per_action=5))
    for anchor in anchors:
        if (
            not set(anchor["transfers_out"]) <= set(owned)
            or set(anchor["transfers_in"]) & set(owned)
            or not set(anchor["transfers_in"]) <= set(pool)
        ):
            raise ValueError("Anchor player identity is outside the shared context")
        if (
            planner._make_action(
                state,
                tuple(owned[pid] for pid in anchor["transfers_out"]),
                tuple(pool[pid] for pid in anchor["transfers_in"]),
            )
            is None
        ):
            raise ValueError("Anchor is not natively legal for this context")
    request_sha256 = cpsat_packages.digest(
        {
            "context_id": context_id,
            "input_sha256": problem["input_sha256"],
            "anchors": anchors,
            "time_limit_seconds": time_limit_seconds,
        }
    )
    python = ROOT / ".venv-solver/Scripts/python.exe"
    if not python.is_file():
        raise FileNotFoundError("Isolated .venv-solver Python is unavailable")
    try:
        response = subprocess.run(
            [str(python), str(ROOT / "scripts/diagnostics/cpsat_phase2b_worker.py")],
            input=json.dumps(
                {
                    "problem": problem,
                    "anchors": anchors,
                    "options": {
                        "context_id": context_id,
                        "request_sha256": request_sha256,
                        "time_limit_seconds": time_limit_seconds,
                    },
                }
            ),
            text=True,
            encoding="utf-8",
            capture_output=True,
            cwd=ROOT,
            check=True,
            timeout=15 * time_limit_seconds * len(anchors) + 15,
        )
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            "Isolated CP-SAT Phase 2B worker failed:\n" + (exc.stderr or "")
        ) from exc
    generation_seconds = perf_counter() - started
    result = json.loads(response.stdout)
    if (
        result.get("api_version") != "cpsat_phase2b_worker_v1"
        or result.get("context_id") != context_id
        or result.get("request_sha256") != request_sha256
        or result.get("input_sha256") != problem["input_sha256"]
    ):
        raise ValueError("Phase 2B worker protocol/context/digest mismatch")
    config = result.get("solver_config", {})
    if (
        config.get("workers") != 1
        or config.get("seed") != 42
        or config.get("per_model_seconds") != time_limit_seconds
        or len(result.get("candidates", [])) > 72
    ):
        raise ValueError("Phase 2B worker configuration/budget mismatch")
    attempts = result.get("attempts", [])
    identities = set()
    statuses = {"OPTIMAL", "FEASIBLE", "INFEASIBLE", "UNKNOWN", "MODEL_INVALID"}
    for attempt in attempts:
        identity = (attempt.get("k"), attempt.get("rank"))
        if (
            identity in identities
            or attempt.get("k") not in range(3, 6)
            or attempt.get("status") not in statuses
        ):
            raise ValueError("Invalid/duplicate Phase 2B attempt")
        identities.add(identity)
    candidates = result.get("candidates", [])
    if len({tuple(p.get("resulting_squad", ())) for p in candidates}) != len(candidates):
        raise ValueError("Duplicate final roster across Phase 2B cells")
    validation_started = perf_counter()
    validation_shell = {
        "input_sha256": problem["input_sha256"],
        "attempts": attempts,
        "packages_by_k": {str(k): [] for k in range(6)},
    }
    cpsat_packages.validate_packages(problem, state, pool, rules, validation_shell)
    for k in range(3, 6):
        packages = [p for p in candidates if p["k"] == k]
        for offset in range(0, len(packages), 5):
            part = dict(validation_shell)
            part["packages_by_k"] = {str(i): [] for i in range(6)}
            part["packages_by_k"][str(k)] = packages[offset : offset + 5]
            cpsat_packages.validate_packages(problem, state, pool, rules, part)
    validation_seconds = perf_counter() - validation_started
    for package in candidates:
        if type(package.get("anchor_index")) is not int or not 0 <= package["anchor_index"] < len(
            anchors
        ):
            raise ValueError("Invalid candidate anchor index")
        anchor = anchors[package["anchor_index"]]
        cell = package.get("cell")
        k = package.get("k")
        allowed_cells = {f"K{k}:{pos}" for pos in ("GK", "DEF", "MID", "FWD", "extension")}
        if k not in (3, 4, 5) or cell not in allowed_cells:
            raise ValueError("Invalid neighborhood cell identity")
        extension = cell.endswith(":extension")
        position = None if extension else cell.split(":")[1]
        check = explain_cell_eligibility(
            {**package, "positions": {pid: p.position for pid, p in pool.items()}},
            anchor,
            target_k=k,
            position=position,
            extension=extension,
        )
        if not check["eligible"]:
            raise ValueError("Worker violated neighborhood structural cuts")
        package.update(
            anchor_identity={
                "transfers_out": anchor["transfers_out"],
                "transfers_in": anchor["transfers_in"],
            },
            anchor_v3_objective=anchor["v3_objective"],
            anchor_native_legal=True,
            cell_metadata={"cell": package["cell"], "restriction": package["restriction"]},
        )
    result.update(
        api_version="cpsat_phase2b_neighborhoods_v1",
        context_id=context_id,
        input_sha256=problem["input_sha256"],
        request_sha256=request_sha256,
        problem=problem,
        generation_seconds=generation_seconds,
        validation_seconds=validation_seconds,
        total_seconds=perf_counter() - started,
        full_v3_objective_modeled=False,
    )
    return result
