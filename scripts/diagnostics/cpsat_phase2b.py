"""Diagnostic Phase2B cache boundary, native HOLD-suffix ranking and bounded evaluation."""

from dataclasses import asdict
from hashlib import sha256
import json
from math import isfinite
from pathlib import Path
from time import perf_counter

from fpl_engine.strategy.strategic_planner_v3 import (
    StrategicAction,
    StrategicPath,
    StrategicPathStep,
    StrategicPlannerV3Config,
)
from scripts.diagnostics.cpsat_packages import digest, prepare_problem
from scripts.diagnostics.cpsat_phase2_v3 import (
    EvaluationCache,
    ForcedRootPlanner,
    evaluate_package,
    guarded_selection,
    root_action,
)
from scripts.diagnostics.v3_guarded_portfolio import input_digest, validate_path
from scripts.diagnostics.v3_multi_transfer_oracle import _hold


def package_key(package):
    return tuple(package["transfers_out"]), tuple(package["transfers_in"])


def decode_path(row):
    steps = []
    for item in row["steps"]:
        action = dict(item["action"])
        for key in ("transfers_out", "transfers_in", "resulting_squad"):
            action[key] = tuple(action[key])
        step = dict(item, action=StrategicAction(**action))
        for key in ("starting_xi", "bench_order"):
            step[key] = tuple(step[key])
        steps.append(StrategicPathStep(**step))
    return StrategicPath(
        tuple(steps),
        row["projected_3gw_path_points"],
        row["terminal_ft_value"],
        row["total_path_value"],
    )


def hydrate_phase2(shared, report, candidate_blobs):
    started = perf_counter()
    payload = {k: v for k, v in report.items() if k != "artifact_payload_sha256"}
    if digest(payload) != report.get("artifact_payload_sha256"):
        raise ValueError("Phase2 report integrity hash mismatch")
    if (
        report.get("schema_version") != "cpsat_phase2_benchmark_v1"
        or report.get("status") != "COMPLETED_DIAGNOSTIC"
        or report.get("evaluation_status") != "PASS"
        or report.get("context_id") != shared.context_id
        or report.get("input_sha256") != input_digest(shared)
        or report.get("config") != asdict(StrategicPlannerV3Config())
    ):
        raise ValueError("Phase2 context/input/configuration mismatch")
    if set(candidate_blobs) != {"A", "B", "C"}:
        raise ValueError("Missing Phase2 artifact identity")
    if set(report.get("strategies", {})) != {"A", "B", "C"}:
        raise ValueError("Missing Phase2 strategy results")
    problem = prepare_problem(shared.state, shared.player_pool, shared.projections, shared.rules)
    source_keys = {}
    for name, blob in candidate_blobs.items():
        if sha256(blob).hexdigest() != report["candidate_artifact_sha256"].get(name):
            raise ValueError("Phase2 candidate artifact integrity hash mismatch")
        data = json.loads(blob)
        if (
            data.get("api_version") != "cpsat_phase2_candidates_v1"
            or data.get("context_id") != shared.context_id
            or data.get("problem") != problem
        ):
            raise ValueError("Phase2 candidate input/context mismatch")
        source_keys[name] = {
            package_key(p) for rows in data["packages_by_k"].values() for p in rows
        }
    incumbent = decode_path(report["incumbent"])
    validate_path(shared, incumbent, max_k=2)
    cache = EvaluationCache(shared)
    entries = 0
    for name, strategy in report["strategies"].items():
        if strategy["status"] != "PASS":
            raise ValueError("Incomplete Phase2 strategy cannot be cached")
        evaluated_keys = set()
        for entry in strategy["evaluations"]:
            entries += 1
            path = decode_path(entry["path"])
            action = path.steps[0].action
            key = action.transfers_out, action.transfers_in
            evaluated_keys.add(key)
            if (
                key not in source_keys[name]
                or entry["k"] != len(key[0])
                or entry["objective"] != path.total_path_value
                or any(s.action.transfers_used > 2 for s in path.steps[1:])
            ):
                raise ValueError("Phase2 cached path identity/objective mismatch")
            if key not in cache.packages:
                validate_path(shared, path, max_k=5)
                cache.packages[key] = path
            elif cache.packages[key].total_path_value != path.total_path_value:
                raise ValueError("Conflicting cached package objective")
        if evaluated_keys != source_keys[name]:
            raise ValueError("Missing Phase2 candidate evaluations")
    return (
        cache,
        incumbent,
        {
            "unique_cache_hits": len(cache.packages),
            "entries": entries,
            "load_and_native_replay_seconds": perf_counter() - started,
        },
    )


def load_phase2(shared, directory):
    directory = Path(directory)
    manifest = json.loads((directory / "protected_before.json").read_text(encoding="utf-8"))
    root = Path(__file__).resolve().parents[2]
    checked = 0
    for filename, expected in manifest.items():
        # Only source/rule identities influence cached evaluations; old user reports are not inputs.
        if filename.replace("\\", "/").startswith(("src/", "config/")):
            if sha256((root / filename).read_bytes()).hexdigest() != expected:
                raise ValueError("Phase2 native source/rule identity mismatch: " + filename)
            checked += 1
    if not checked:
        raise ValueError("Missing Phase2 native source identities")
    report = json.loads((directory / "results.json").read_text(encoding="utf-8"))
    blobs = {
        name: (directory / (name + "_candidates.json")).read_bytes() for name in ("A", "B", "C")
    }
    cache, incumbent, metrics = hydrate_phase2(shared, report, blobs)
    metrics["native_source_identities"] = checked
    return cache, incumbent, metrics


def choose_anchors(paths):
    rows = []
    for path in paths:
        action = path.steps[0].action
        if len(action.transfers_out) == 2 and isfinite(path.total_path_value):
            rows.append(
                {
                    "transfers_out": list(action.transfers_out),
                    "transfers_in": list(action.transfers_in),
                    "v3_objective": path.total_path_value,
                }
            )
    rows.sort(key=lambda p: (-p["v3_objective"], package_key(p)))
    selected = []
    seen = set()
    for row in rows:
        incoming = tuple(row["transfers_in"])
        if incoming not in seen:
            selected.append(row)
            seen.add(incoming)
        if len(selected) == 3:
            break
    return selected


def hold_suffix_path(shared, package, cache):
    """Exact value of one legal path for ranking only; does not run native future search."""
    action = root_action(shared, package)
    planner = ForcedRootPlanner(shared.rules, shared.state.current_gameweek, action, cache, None)
    state = shared.state
    pool = {p.player_id: p for p in shared.player_pool}
    steps = []
    for offset in range(3):
        current = action if offset == 0 else _hold(state, shared.rules)
        state, step = planner._evaluate_action(
            state,
            current,
            pool,
            shared.projections,
            target_gameweek=state.current_gameweek,
            signals=None,
            offset=offset,
        )
        steps.append(step)
    points = sum(s.points_after_hit for s in steps)
    terminal = planner._terminal_ft_value(state)
    return StrategicPath(tuple(steps), points, terminal, points + terminal)


def select_new_candidates(candidates, *, existing_keys):
    def rank(p):
        return (
            -p["hold_suffix_objective"],
            -p["anchor_v3_objective"],
            package_key(p),
            p["anchor_index"],
            str(p.get("neighborhood", "")),
        )

    unique = {}
    rosters = set()
    for row in sorted(candidates, key=rank):
        key = package_key(row)
        roster = tuple(sorted(row["resulting_squad"]))
        if key not in existing_keys and key not in unique and roster not in rosters:
            unique[key] = row
            rosters.add(roster)
    selected = []
    for k in (3, 4, 5):
        group = [row for row in unique.values() if len(row["transfers_out"]) == k]
        chosen = []
        # First retain the best native path from each anchor, then a structurally distinct fourth.
        for row in group:
            if row["anchor_index"] not in {p["anchor_index"] for p in chosen}:
                chosen.append(row)
        for row in group:
            if len(chosen) >= 4:
                break
            if row not in chosen and all(package_key(row) != package_key(p) for p in chosen):
                chosen.append(row)
        selected.extend(sorted(chosen, key=rank)[:4])
    return selected


def evaluate_selected(shared, selected, cache, *, deadline):
    if len(selected) > 12:
        raise ValueError("At most12 new full V3 evaluations")
    started = perf_counter()
    result = {"status": "PASS", "completed": [], "failures": [], "pending": []}
    for index, package in enumerate(selected):
        if perf_counter() >= deadline:
            result.update(status="PARTIAL", pending=selected[index:])
            break
        before = perf_counter()
        try:
            path = evaluate_package(shared, package, cache, deadline=deadline)
            result["completed"].append(
                {
                    "package": package,
                    "path": asdict(path),
                    "objective": path.total_path_value,
                    "seconds": perf_counter() - before,
                }
            )
        except TimeoutError as exc:
            result.update(status="PARTIAL", pending=selected[index:])
            result["failures"].append({"package": package, "error": str(exc), "incomplete": True})
            break
        except Exception as exc:
            result["status"] = "FAIL"
            result["failures"].append(
                {
                    "package": package,
                    "error": type(exc).__name__ + ": " + str(exc),
                    "incomplete": False,
                }
            )
    result["seconds"] = perf_counter() - started
    return result


def select_portfolio(incumbent, cached_paths, new_paths):
    selected = incumbent
    for path in (*cached_paths, *new_paths):
        selected, _ = guarded_selection(selected, lambda: path)
    return selected
