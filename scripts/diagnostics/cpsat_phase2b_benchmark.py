"""Frozen-context Phase2B experiment, <=12 new full V3 evaluations within120s."""

from dataclasses import asdict
import json
from pathlib import Path
from time import perf_counter

from scripts.diagnostics import v3_portfolio_contexts as contexts
from scripts.diagnostics.cpsat_packages import digest
from scripts.diagnostics.cpsat_phase2_benchmark import references
from scripts.diagnostics.cpsat_phase2_v3 import root_action
from scripts.diagnostics.cpsat_phase2b import (
    load_phase2,
    choose_anchors,
    hold_suffix_path,
    package_key,
    select_new_candidates,
    evaluate_selected,
    select_portfolio,
)
from scripts.diagnostics.cpsat_phase2b_candidates import (
    generate_neighborhoods,
    explain_cell_eligibility,
)
from scripts.diagnostics.v3_guarded_portfolio import input_digest, validate_path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "scratch/cpsat_phase2b_20261022"


def save(name, data):
    (OUT / name).write_text(
        json.dumps(data, indent=2, default=str, allow_nan=False), encoding="utf-8"
    )


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    contexts.OUT = OUT
    started = perf_counter()
    shared = contexts.load_frozen(
        ROOT
        / "data/processed/desktop_analyses/2026-27/desktop-analysis-20261022T081445787253Z.json"
    )
    cache, incumbent, load_metrics = load_phase2(shared, ROOT / "scratch/cpsat_phase2_20261022")
    existing_keys = set(cache.packages)
    existing_paths = tuple(cache.packages.values())
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
    refs = references(shared, names)
    assert abs(incumbent.total_path_value - 147.42035) < 1e-9
    anchors = choose_anchors(existing_paths)
    report = {
        "schema_version": "cpsat_phase2b_benchmark_v1",
        "context_id": shared.context_id,
        "input_sha256": input_digest(shared),
        "status": "RUNNING",
        "cache_load": load_metrics,
        "incumbent": asdict(incumbent),
        "references": refs,
        "anchors": anchors,
        "limits": {"anchors": 3, "new_full_evaluations": 12, "new_evaluation_seconds": 120},
        "native_future_config": cache.config,
        "new_full_v3_optimality_proven": False,
    }
    print(
        json.dumps(
            {
                "stage": "cache_and_references_verified",
                "seconds": perf_counter() - started,
                "cached_unique": len(existing_keys),
                "anchors": [
                    {
                        **a,
                        "out_names": [names[x] for x in a["transfers_out"]],
                        "in_names": [names[x] for x in a["transfers_in"]],
                    }
                    for a in anchors
                ],
            }
        ),
        flush=True,
    )
    before = perf_counter()
    try:
        generated = generate_neighborhoods(shared, anchors)
        repeated = generate_neighborhoods(shared, anchors)
        deterministic = generated["candidates"] == repeated["candidates"]
        generation_seconds = perf_counter() - before
        save("candidates.json", generated)
        save("candidates_repeat.json", repeated)
        report.update(
            generation_seconds=generation_seconds,
            first_generation_seconds=generated["generation_seconds"],
            repeat_generation_seconds=repeated["generation_seconds"],
            legality_validation_seconds=generated["validation_seconds"]
            + repeated["validation_seconds"],
            deterministic=deterministic,
            generated_counts_by_k={
                str(k): sum(p["k"] == k for p in generated["candidates"]) for k in (3, 4, 5)
            },
        )
    except Exception as exc:
        report.update(
            status="GENERATION_FAILED",
            error=type(exc).__name__ + ": " + str(exc),
            selected=asdict(select_portfolio(incumbent, existing_paths, [])),
            incumbent_preserved=True,
            total_seconds=perf_counter() - started,
            ready_phase3=False,
        )
        report["artifact_payload_sha256"] = digest(report)
        save("results.json", report)
        raise
    before = perf_counter()
    proposals = []
    for package in generated["candidates"]:
        path = hold_suffix_path(shared, package, cache)
        proposals.append(
            {
                **package,
                "neighborhood": package["cell"],
                "hold_suffix_objective": path.total_path_value,
                "ranking_objective_scope": "native current transfer then HOLD/HOLD path, not full future search",
            }
        )
    selected = select_new_candidates(proposals, existing_keys=existing_keys)
    report.update(
        cheap_ranking_seconds=perf_counter() - before,
        new_proposals_by_k={
            str(k): sum(p["k"] == k and package_key(p) not in existing_keys for p in proposals)
            for k in (3, 4, 5)
        },
        selected_counts_by_k={str(k): sum(p["k"] == k for p in selected) for k in (3, 4, 5)},
        selected_candidates=selected,
    )
    target = refs["K3"]["package"]
    matched = [p for p in proposals if package_key(p) == package_key(target)]
    positions = {p.player_id: p.position for p in shared.player_pool}
    ref_action = root_action(shared, target)
    weights = {p["player_id"]: p["weight"] for p in generated["problem"]["players"]}
    ref_surrogate = (
        sum(weights[pid] for pid in ref_action.resulting_squad)
        - ref_action.hit_cost_points * generated["problem"]["objective_scale"]
    )
    eligible = []
    for attempt in generated["attempts"]:
        if attempt["k"] != 3:
            continue
        restriction = attempt["restriction"]
        check = explain_cell_eligibility(
            {**target, "positions": positions},
            anchors[attempt["anchor_index"]],
            target_k=3,
            position=restriction["position_included"],
            extension=restriction["anchor_out_retention"] == "all_preserved",
        )
        eligible.append(
            {
                "anchor_index": attempt["anchor_index"],
                "cell": attempt["cell"],
                **check,
                "status": attempt["status"],
                "winner_surrogate_scaled": attempt["objective_scaled"],
            }
        )
    report["known_k3"] = {
        "generated": bool(matched),
        "selected_for_full_evaluation": any(
            package_key(p) == package_key(target) for p in selected
        ),
        "reference_surrogate_scaled": ref_surrogate,
        "cell_eligibility": eligible,
        "reason": "naturally generated"
        if matched
        else "No eligible neighborhood"
        if not any(c["eligible"] for c in eligible)
        else "Eligible neighborhood exists, but its bounded surrogate winner is another package",
    }
    print(
        json.dumps(
            {
                "stage": "generation_and_selection",
                "seconds": perf_counter() - started,
                "new_counts": report["new_proposals_by_k"],
                "selected": report["selected_counts_by_k"],
                "known_k3": {
                    k: v for k, v in report["known_k3"].items() if k != "cell_eligibility"
                },
                "deterministic": deterministic,
            }
        ),
        flush=True,
    )
    save("results.json", report)
    full_started = perf_counter()
    outcome = evaluate_selected(shared, selected, cache, deadline=full_started + 120)
    report["new_evaluation"] = outcome
    portfolio = select_portfolio(incumbent, cache.packages.values(), [])
    validate_path(shared, portfolio, max_k=5)
    assert portfolio.total_path_value >= incumbent.total_path_value
    best_by_k = {}
    for path in cache.packages.values():
        k = str(path.steps[0].action.transfers_used)
        if k not in best_by_k or path.total_path_value > best_by_k[k]["total_path_value"]:
            best_by_k[k] = asdict(path)
    target_path = cache.packages.get(package_key(target))
    report["known_k3"].update(
        full_evaluation_completed=target_path is not None,
        evaluated_objective=target_path.total_path_value if target_path else None,
    )
    report.update(
        status="PARTIAL"
        if outcome["status"] == "PARTIAL"
        else "COMPLETED_DIAGNOSTIC"
        if outcome["status"] == "PASS"
        else "EVALUATION_FAILED",
        best_by_k=best_by_k,
        selected=asdict(portfolio),
        incumbent_preserved=True,
        completed_new_by_k={
            str(k): sum(len(r["package"]["transfers_out"]) == k for r in outcome["completed"])
            for k in (3, 4, 5)
        },
        cache=cache.metrics(),
        total_seconds=perf_counter() - started,
        oracles="PENDING",
        ready_phase3=False,
    )
    report["artifact_payload_sha256"] = digest(report)
    save("results.json", report)
    print(
        json.dumps(
            {
                "status": report["status"],
                "new_evaluation_seconds": outcome["seconds"],
                "total_seconds": report["total_seconds"],
                "completed_new": report["completed_new_by_k"],
                "objective": portfolio.total_path_value,
                "known_k3": report["known_k3"]["generated"],
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
