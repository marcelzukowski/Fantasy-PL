"""Protocol, context, and native legality checks for bounded Phase 2 candidates."""

import json
from types import SimpleNamespace
from unittest.mock import patch

from hypothesis import given, settings, strategies as st
import pytest

from fpl_engine.optimizer import OptimizerRules
from scripts.diagnostics import cpsat_packages, cpsat_phase2_candidates
from scripts.diagnostics.v3_multi_transfer_oracle import ROOT, _fixture


RULES = OptimizerRules.load(ROOT)


@pytest.mark.parametrize(
    "field,value", [("api_version", "old-version"), ("input_sha256", "forged")]
)
def test_worker_version_and_integrity_mismatch_are_rejected(monkeypatch, field, value):
    state, pool, projections = _fixture(65, RULES)
    body = _worker_result(cpsat_packages.prepare_problem(state, pool, projections, RULES))
    body[field] = value
    monkeypatch.setattr(
        cpsat_phase2_candidates.subprocess,
        "run",
        lambda *a, **kw: SimpleNamespace(stdout=json.dumps(body)),
    )
    with pytest.raises(ValueError, match="version|digest"):
        cpsat_phase2_candidates.generate_phase2(
            state, pool, projections, RULES, strategy="A", context_id="gw-test"
        )


def test_invalid_attempt_is_rejected_even_without_any_packages(monkeypatch):
    state, pool, projections = _fixture(66, RULES)
    body = _worker_result(cpsat_packages.prepare_problem(state, pool, projections, RULES))
    body["packages_by_k"] = {str(k): [] for k in range(6)}
    body["attempts"] = [{"k": 0, "rank": 1, "status": "FABRICATED"}]
    monkeypatch.setattr(
        cpsat_phase2_candidates.subprocess,
        "run",
        lambda *a, **kw: SimpleNamespace(stdout=json.dumps(body)),
    )
    with pytest.raises(ValueError, match="status"):
        cpsat_phase2_candidates.generate_phase2(
            state, pool, projections, RULES, strategy="A", context_id="gw-test"
        )


def test_real_worker_determinism_reduced_surrogate_oracle_and_structural_cuts():
    from tests.test_cpsat_transfer_packages import _exact_by_k

    state, pool, projections = _fixture(71, RULES)
    problem = cpsat_packages.prepare_problem(state, pool, projections, RULES)
    exact = _exact_by_k(state, pool, projections, RULES, problem)
    for strategy, allocation in (("A", 5), ("B", 10), ("C", 10)):
        first = cpsat_phase2_candidates.generate_phase2(
            state, pool, projections, RULES, strategy=strategy, context_id="reduced-real-worker"
        )
        second = cpsat_phase2_candidates.generate_phase2(
            state, pool, projections, RULES, strategy=strategy, context_id="reduced-real-worker"
        )
        assert first["packages_by_k"] == second["packages_by_k"]
        for k, packages in first["packages_by_k"].items():
            n = min(5, len(packages)) if strategy == "C" else len(packages)
            assert [p["objective_scaled"] for p in packages[:n]] == [
                x[0] for x in exact[int(k)][:n]
            ]
            assert len(packages) <= allocation
            assert all(p["native_legality"] == "PASS" for p in packages)
            if strategy == "C":
                for index, package in enumerate(packages[5:], start=5):
                    assert not cpsat_phase2_candidates.explain_diversity_exclusion(
                        int(k), package, packages[:index]
                    )["excluded_by_diversity"]


def _worker_result(problem, strategy="A", context_id="gw-test"):
    roster = sorted(row["player_id"] for row in problem["players"] if row["owned"])
    score = sum(row["weight"] for row in problem["players"] if row["owned"])
    package = {
        "transfers_out": [],
        "transfers_in": [],
        "resulting_squad": roster,
        "resulting_bank": problem["bank"],
        "hit_cost_points": 0,
        "free_transfers_before": problem["free_transfers"],
        "free_transfers_after": problem["accounting_by_k"]["0"]["free_transfers_after"],
        "objective_scaled": score,
        "objective_bound_scaled": score,
        "status": "OPTIMAL",
        "rank": 1,
        "excluded_squads": 0,
    }
    attempts = [
        {
            "k": 0,
            "rank": 1,
            "status": "OPTIMAL",
            "objective_scaled": score,
            "objective_bound_scaled": score,
            "excluded_squads": 0,
        }
    ]
    return {
        "api_version": "cpsat_phase2_candidates_v1",
        "context_id": context_id,
        "input_sha256": problem["input_sha256"],
        "packages_by_k": {str(k): ([package] if k == 0 else []) for k in range(6)},
        "attempts": attempts,
        "solver_config": {
            "strategy": strategy,
            "generation_limit_per_k": {"A": 5, "B": 10, "C": 10}[strategy],
            "per_solve_seconds": 1.0,
            "workers": 1,
            "seed": 42,
        },
        "solver_version": "9.15.6755",
        "worker_seconds": 0.01,
        "peak_memory_mib": 1.0,
    }


def _call(state, pool, projections, monkeypatch, *, result=None):
    problem = cpsat_packages.prepare_problem(state, pool, projections, RULES)
    payloads = []

    def worker(args, **kwargs):
        payloads.append(json.loads(kwargs["input"]))
        body = result or _worker_result(problem)
        return SimpleNamespace(stdout=json.dumps(body))

    monkeypatch.setattr(cpsat_phase2_candidates.subprocess, "run", worker)
    result = cpsat_phase2_candidates.generate_phase2(
        state, pool, projections, RULES, strategy="A", context_id="gw-test"
    )
    return result, payloads


def test_json_boundary_echoes_context_and_native_replay_validates_hold(monkeypatch):
    state, pool, projections = _fixture(61, RULES)
    result, payloads = _call(state, pool, projections, monkeypatch)
    request = payloads[0]
    assert set(request) == {"problem", "options"}
    assert request["options"] == {
        "strategy": "A",
        "context_id": "gw-test",
        "time_limit_seconds": 1.0,
    }
    assert result["api_version"] == "cpsat_phase2_candidates_v1"
    assert result["context_metadata"]["input_sha256"] == request["problem"]["input_sha256"]
    assert result["packages_by_k"]["0"][0]["native_legality"] == "PASS"
    assert set(result["packages_by_k"]) == {str(k) for k in range(6)}


def test_worker_context_mismatch_and_duplicate_rosters_are_rejected(monkeypatch):
    state, pool, projections = _fixture(62, RULES)
    problem = cpsat_packages.prepare_problem(state, pool, projections, RULES)
    forged = _worker_result(problem)
    forged["context_id"] = "other-context"
    monkeypatch.setattr(
        cpsat_phase2_candidates.subprocess,
        "run",
        lambda *a, **kw: SimpleNamespace(stdout=json.dumps(forged)),
    )
    with pytest.raises(ValueError, match="context/input"):
        cpsat_phase2_candidates.generate_phase2(
            state, pool, projections, RULES, strategy="A", context_id="gw-test"
        )
    duplicate = _worker_result(problem)
    duplicate["packages_by_k"]["0"].append(dict(duplicate["packages_by_k"]["0"][0], rank=2))
    duplicate["attempts"].append(
        {
            "k": 0,
            "rank": 2,
            "status": "OPTIMAL",
            "objective_scaled": duplicate["attempts"][0]["objective_scaled"],
            "objective_bound_scaled": duplicate["attempts"][0]["objective_bound_scaled"],
            "excluded_squads": 1,
        }
    )
    monkeypatch.setattr(
        cpsat_phase2_candidates.subprocess,
        "run",
        lambda *a, **kw: SimpleNamespace(stdout=json.dumps(duplicate)),
    )
    with pytest.raises(ValueError, match="Duplicate package roster"):
        cpsat_phase2_candidates.generate_phase2(
            state, pool, projections, RULES, strategy="A", context_id="gw-test"
        )


def test_c_diversity_explanation_reports_exact_roster_hamming_cut():
    base = {
        "rank": 1,
        "transfers_out": ["o1", "o2"],
        "transfers_in": ["i1", "i2"],
        "resulting_squad": [str(i) for i in range(15)],
    }
    one_swap = {
        "transfers_out": ["o2", "o3"],
        "transfers_in": ["i2", "i3"],
        "resulting_squad": [str(i) for i in range(1, 15)] + ["x"],
    }
    two_swaps = {
        "transfers_out": ["o3", "o4"],
        "transfers_in": ["i3", "i4"],
        "resulting_squad": [str(i) for i in range(2, 15)] + ["x", "y"],
    }
    assert cpsat_phase2_candidates.explain_diversity_exclusion(2, one_swap, [base]) == {
        "minimum_roster_hamming_distance": 4,
        "excluded_by_diversity": True,
        "comparisons": [
            {
                "base_rank": 1,
                "roster_hamming_distance": 2,
                "different_OUT": True,
                "different_IN": True,
                "excluded": True,
            }
        ],
    }
    assert not cpsat_phase2_candidates.explain_diversity_exclusion(2, two_swaps, [base])[
        "excluded_by_diversity"
    ]


@settings(max_examples=8, derandomize=True, deadline=None)
@given(
    strategy=st.sampled_from(["A", "B", "C"]),
    context_id=st.text(min_size=1, max_size=20).filter(lambda value: bool(value.strip())),
)
def test_strategy_and_context_are_serializable_and_preserved(strategy, context_id):
    state, pool, projections = _fixture(63, RULES)
    problem = cpsat_packages.prepare_problem(state, pool, projections, RULES)
    body = _worker_result(problem, strategy=strategy, context_id=context_id)
    with patch.object(
        cpsat_phase2_candidates.subprocess,
        "run",
        lambda *a, **kw: SimpleNamespace(stdout=json.dumps(body)),
    ):
        result = cpsat_phase2_candidates.generate_phase2(
            state, pool, projections, RULES, strategy=strategy, context_id=context_id
        )
    assert result["context_metadata"]["context_id"] == context_id
    assert result["context_metadata"]["config"]["strategy"] == strategy
