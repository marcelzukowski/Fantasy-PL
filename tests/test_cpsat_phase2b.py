"""Tests-first contracts for bounded, exact-context V3 anchored diagnostics."""

from dataclasses import asdict
from hashlib import sha256
import json
from time import perf_counter

import pytest
from hypothesis import given, settings, strategies as st

from fpl_engine.optimizer import OptimizerRules
from fpl_engine.strategy.strategic_planner_v3 import StrategicPlannerV3Config
from scripts.diagnostics.cpsat_packages import digest, prepare_problem
from scripts.diagnostics.cpsat_phase2_v3 import EvaluationCache, evaluate_package, root_action
from scripts.diagnostics.v3_multi_transfer_oracle import ROOT, _fixture
from scripts.diagnostics.v3_guarded_portfolio import input_digest, validate_path
from scripts.diagnostics.v3_portfolio_contexts import synthetic_input
from scripts.diagnostics.cpsat_phase2b import (
    decode_path,
    hydrate_phase2,
    choose_anchors,
    select_new_candidates,
    hold_suffix_path,
    evaluate_selected,
    select_portfolio,
)

RULES = OptimizerRules.load(ROOT)


def context(seed=81):
    state, pool, projections = _fixture(seed, RULES)
    return synthetic_input("phase2b-tests", state, pool, projections, RULES)


def cached_fixture(shared):
    path = hold_suffix_path(
        shared, {"transfers_out": [], "transfers_in": []}, EvaluationCache(shared)
    )
    action = asdict(path.steps[0].action)
    candidate = {
        "api_version": "cpsat_phase2_candidates_v1",
        "context_id": shared.context_id,
        "problem": prepare_problem(shared.state, shared.player_pool, shared.projections, RULES),
        "packages_by_k": {str(k): ([action] if k == 0 else []) for k in range(6)},
    }
    blobs = {name: json.dumps(candidate).encode() for name in ("A", "B", "C")}
    report = {
        "schema_version": "cpsat_phase2_benchmark_v1",
        "status": "COMPLETED_DIAGNOSTIC",
        "evaluation_status": "PASS",
        "context_id": shared.context_id,
        "input_sha256": input_digest(shared),
        "config": asdict(StrategicPlannerV3Config()),
        "incumbent": asdict(path),
        "candidate_artifact_sha256": {
            name: sha256(blob).hexdigest() for name, blob in blobs.items()
        },
        "strategies": {
            name: {
                "status": "PASS",
                "evaluations": [{"k": 0, "objective": path.total_path_value, "path": asdict(path)}],
            }
            for name in ("A", "B", "C")
        },
    }
    report["artifact_payload_sha256"] = digest(report)
    return report, blobs, path


def test_cache_roundtrip_and_artifact_context_config_rejection():
    from copy import deepcopy

    shared = context()
    report, blobs, path = cached_fixture(shared)
    cache, incumbent, metrics = hydrate_phase2(shared, report, blobs)
    assert incumbent == path
    assert decode_path(asdict(path)) == path
    assert len(cache.packages) == 1
    assert metrics["unique_cache_hits"] == 1
    for field, value in (("context_id", "wrong"), ("input_sha256", "wrong"), ("config", {})):
        bad = deepcopy(report)
        bad[field] = value
        bad["artifact_payload_sha256"] = digest(
            {k: v for k, v in bad.items() if k != "artifact_payload_sha256"}
        )
        with pytest.raises(ValueError):
            hydrate_phase2(shared, bad, blobs)
    with pytest.raises(ValueError, match="integrity|hash"):
        hydrate_phase2(shared, report, {**blobs, "A": b"changed"})
    bad = deepcopy(report)
    bad["incumbent"]["total_path_value"] += 1
    bad["artifact_payload_sha256"] = digest(
        {k: v for k, v in bad.items() if k != "artifact_payload_sha256"}
    )
    with pytest.raises(ValueError):
        hydrate_phase2(shared, bad, blobs)


def test_native_hold_suffix_is_a_verified_path_not_a_future_search_claim():
    shared = context()
    package = {"transfers_out": ["owned-2"], "transfers_in": ["incoming-def"]}
    cache = EvaluationCache(shared)
    lower = hold_suffix_path(shared, package, cache)
    exact = evaluate_package(shared, package, cache)
    assert validate_path(shared, lower, max_k=5)["objective"] == lower.total_path_value
    assert exact.total_path_value + 1e-9 >= lower.total_path_value
    assert all(s.action.is_hold for s in lower.steps[1:])


def test_anchors_use_real_v3_scores_and_different_incoming_sets():
    from types import SimpleNamespace

    def path(score, outs, ins):
        return SimpleNamespace(
            total_path_value=score,
            steps=(
                SimpleNamespace(
                    action=SimpleNamespace(
                        transfers_out=tuple(outs), transfers_in=tuple(ins), transfers_used=2
                    )
                ),
            ),
        )

    rows = [
        path(10, ["a", "b"], ["x", "y"]),
        path(9, ["a", "c"], ["x", "y"]),
        path(8, ["d", "e"], ["z", "w"]),
        path(7, ["f", "g"], ["j", "k"]),
    ]
    anchors = choose_anchors(rows)
    assert len(anchors) == 3
    assert [a["v3_objective"] for a in anchors] == [10, 8, 7]


@settings(max_examples=8, derandomize=True, deadline=None)
@given(reverse=st.booleans(), copies=st.integers(1, 3))
def test_selection_deduplicates_limits_and_is_deterministic(reverse, copies):
    candidates = []
    for k in (3, 4, 5):
        for rank in range(6):
            candidates.append(
                {
                    "transfers_out": [f"o{i}-{rank}" for i in range(k)],
                    "transfers_in": [f"i{i}-{rank}" for i in range(k)],
                    "resulting_squad": [f"p{k}-{rank}"],
                    "anchor_index": rank % 3,
                    "anchor_v3_objective": 100 - rank % 3,
                    "hold_suffix_objective": 200 - rank,
                    "neighborhood": "position-GK" if rank % 2 else "extension",
                }
            )
    rows = candidates * copies
    if reverse:
        rows.reverse()
    selected = select_new_candidates(rows, existing_keys=set())
    assert len(selected) == 12
    assert [len(p["transfers_out"]) for p in selected].count(3) == 4
    assert len({tuple(p["resulting_squad"]) for p in selected}) == 12
    assert selected == select_new_candidates(list(reversed(rows)), existing_keys=set())


def test_deadline_reports_pending_and_portfolio_keeps_verified_results_on_failure():
    shared = context()
    report, blobs, path = cached_fixture(shared)
    cache, incumbent, _ = hydrate_phase2(shared, report, blobs)
    candidate = {"transfers_out": ["owned-2"], "transfers_in": ["incoming-def"]}
    outcome = evaluate_selected(shared, [candidate], cache, deadline=perf_counter() - 1)
    assert outcome["status"] == "PARTIAL" and len(outcome["pending"]) == 1
    assert outcome["completed"] == []
    assert select_portfolio(incumbent, cache.packages.values(), []) is incumbent
    with pytest.raises(ValueError):
        root_action(shared, {"transfers_out": ["unknown"], "transfers_in": ["unknown"]})


def test_worker_and_invalid_evaluation_failures_preserve_verified_incumbent(monkeypatch):
    import subprocess
    from scripts.diagnostics import cpsat_phase2b_candidates as generator
    from scripts.diagnostics import cpsat_phase2b as evaluator

    shared = context()
    report, blobs, _ = cached_fixture(shared)
    cache, incumbent, _ = hydrate_phase2(shared, report, blobs)
    before = input_digest(shared)

    def fail(*args, **kwargs):
        raise subprocess.CalledProcessError(1, "worker", stderr="controlled worker failure")

    monkeypatch.setattr(generator.subprocess, "run", fail)
    with pytest.raises(RuntimeError, match="controlled worker failure"):
        generator.generate_neighborhoods(shared, [])
    invalid = {"transfers_out": ["unknown"], "transfers_in": ["unknown"]}
    result = evaluator.evaluate_selected(shared, [invalid], cache, deadline=perf_counter() + 10)
    assert result["status"] == "FAIL" and result["completed"] == [] and len(result["failures"]) == 1
    assert select_portfolio(incumbent, cache.packages.values(), []) is incumbent
    assert input_digest(shared) == before
    with pytest.raises(ValueError, match="12"):
        evaluator.evaluate_selected(shared, [invalid] * 13, cache, deadline=perf_counter() + 10)
