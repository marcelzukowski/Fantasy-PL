"""Tests-first contracts for diagnostic forced-current-package native V3 evaluation."""

from dataclasses import replace
from time import perf_counter

import pytest
from hypothesis import given, settings, strategies as st

from fpl_engine.optimizer import OptimizerRules
from fpl_engine.strategy.strategic_planner_v3 import StrategicPlannerV3
from scripts.diagnostics.v3_challenger_oracle import (
    ROOT,
    _five_transfer_fixture,
    _club_cycle_fixture,
)
from scripts.diagnostics.v3_multi_transfer_oracle import _fixture, _hold
from scripts.diagnostics.v3_portfolio_contexts import synthetic_input
from scripts.diagnostics.v3_guarded_portfolio import validate_path
from scripts.diagnostics.cpsat_phase2_v3 import EvaluationCache, evaluate_package, guarded_selection

RULES = OptimizerRules.load(ROOT)


def test_windows_peak_memory_probe_has_valid_64bit_handle():
    import sys

    if sys.platform != "win32":
        pytest.skip("Windows working-set counter")
    from scripts.diagnostics.cpsat_phase2_benchmark import peak_memory_mib

    assert 0 < peak_memory_mib() < 100_000


def shared_fixture(seed=31):
    state, pool, projections = _fixture(seed, RULES)
    return synthetic_input("phase2-tests", state, pool, projections, RULES)


def package(action):
    return {"transfers_out": list(action.transfers_out), "transfers_in": list(action.transfers_in)}


@pytest.mark.parametrize("k", range(6))
@pytest.mark.parametrize("ft", (4, 5))
def test_fixed_current_k_keeps_native_future_search_and_complete_objective(k, ft):
    state, pool, projections = _five_transfer_fixture(RULES)
    state = replace(state, free_transfers=ft)
    shared = synthetic_input("phase2-k", state, pool, projections, RULES)
    from scripts.diagnostics.cpsat_packages import generate_packages

    generated = generate_packages(state, pool, projections, RULES, candidates_per_k=1)
    root = generated["packages_by_k"][str(k)][0]
    path = evaluate_package(shared, root, EvaluationCache(shared))
    assert len(path.steps[0].action.transfers_out) == k
    assert all(len(step.action.transfers_out) <= 2 for step in path.steps[1:])
    replay = validate_path(shared, path, max_k=5)
    assert replay["objective"] == pytest.approx(path.total_path_value, abs=1e-9)
    assert path.total_path_value == pytest.approx(
        sum(s.lineup_points - s.action.hit_cost_points for s in path.steps) + path.terminal_ft_value
    )
    assert path.steps[0].action.hit_cost_points == max(0, k - ft) * 4


def test_cache_deduplicates_and_rejects_context_or_input_mutation():
    shared = shared_fixture()
    root = package(_hold(shared.state, RULES))
    cache = EvaluationCache(shared)
    first = evaluate_package(shared, root, cache)
    assert evaluate_package(shared, root, cache) == first
    assert cache.hits["package"] == 1
    other = shared_fixture(32)
    with pytest.raises(ValueError, match="context|integrity"):
        evaluate_package(other, root, cache)
    changed = synthetic_input(
        "phase2-tests",
        replace(shared.state, bank=1),
        {p.player_id: p for p in shared.player_pool},
        shared.projections,
        RULES,
    )
    with pytest.raises(ValueError, match="context|integrity"):
        evaluate_package(changed, root, cache)


def test_atomic_package_and_invalid_membership_and_deadline():
    state, pool, projections = _club_cycle_fixture(RULES)
    shared = synthetic_input("phase2-atomic", state, pool, projections, RULES)
    from scripts.diagnostics.cpsat_packages import generate_packages

    root = generate_packages(state, pool, projections, RULES, candidates_per_k=1)["packages_by_k"][
        "4"
    ][0]
    assert (
        evaluate_package(shared, root, EvaluationCache(shared)).steps[0].action.transfers_used == 4
    )
    with pytest.raises(ValueError):
        evaluate_package(
            shared,
            {"transfers_out": ["unknown"], "transfers_in": ["unknown"]},
            EvaluationCache(shared),
        )
    with pytest.raises(TimeoutError):
        evaluate_package(shared, root, EvaluationCache(shared), deadline=perf_counter() - 1)


def test_native_forced_hold_matches_uncached_native_search():
    shared = shared_fixture()
    native = StrategicPlannerV3(RULES)
    expected = native._search(
        shared.state,
        {p.player_id: p for p in shared.player_pool},
        shared.projections,
        signals=None,
        force_hold_now=True,
    )
    actual = evaluate_package(shared, package(_hold(shared.state, RULES)), EvaluationCache(shared))
    assert actual.total_path_value == expected.total_path_value


def test_transfer_root_cached_search_matches_native_and_replay_rejects_bad_total():
    from scripts.diagnostics.cpsat_phase2_v3 import root_action

    shared = shared_fixture()
    root = {"transfers_out": ["owned-2"], "transfers_in": ["incoming-def"]}
    action = root_action(shared, root)
    native = StrategicPlannerV3(RULES)
    original_actions = native._actions_for_state
    native._actions_for_state = lambda state, pool, projections, *, target_gameweek: (
        [action]
        if target_gameweek == shared.state.current_gameweek
        else original_actions(state, pool, projections, target_gameweek=target_gameweek)
    )
    expected = native._search(
        shared.state,
        {p.player_id: p for p in shared.player_pool},
        shared.projections,
        signals=None,
        force_hold_now=False,
    )
    cache = EvaluationCache(shared)
    evaluate_package(shared, package(_hold(shared.state, RULES)), cache)
    actual = evaluate_package(shared, root, cache)
    assert actual.total_path_value == expected.total_path_value
    assert cache.hits["resulting_squad_lineup"] > 0
    with pytest.raises(ValueError, match="Complete objective"):
        validate_path(
            shared, replace(actual, total_path_value=actual.total_path_value + 1), max_k=5
        )


@settings(max_examples=8, derandomize=True, deadline=None)
@given(delta=st.floats(min_value=-5, max_value=5, allow_nan=False, allow_infinity=False))
def test_incumbent_no_regression_and_failure_fallback(delta):
    from types import SimpleNamespace

    incumbent = SimpleNamespace(total_path_value=147.42035)
    challenger = SimpleNamespace(total_path_value=147.42035 + delta)
    selected, error = guarded_selection(incumbent, lambda: challenger)
    assert selected.total_path_value >= incumbent.total_path_value
    assert error is None

    def fail():
        raise RuntimeError("solver failure")

    assert guarded_selection(incumbent, fail)[0] is incumbent
    assert (
        guarded_selection(incumbent, lambda: SimpleNamespace(total_path_value=float("nan")))[0]
        is incumbent
    )
