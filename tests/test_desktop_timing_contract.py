from __future__ import annotations

import inspect

import desktop_app.chip_runner as chip_runner
import desktop_app.decision_runner as decision_runner
import fpl_engine.shadow as shadow


DECISION_KEYS = {
    "decision_input", "greedy", "v1", "v2", "v3_unrestricted", "v3_forced_hold",
    "v3_total", "previews", "captaincy", "top_targets", "chip_opportunity_forecast",
    "advisory_history", "report_serialization", "decision_total",
}
CHIP_KEYS = {
    "load_data", "candidate_generation", "current_squad_evaluation", "triple_captain",
    "bench_boost", "free_hit", "strategic_cache_lookup", "strategic_predict_current",
    "strategic_bundle_load", "strategic_chip_evaluation", "report_serialization", "chip_total",
}


def _assert_declared_contract(source: str, keys: set[str], event: str) -> None:
    for key in keys:
        assert f'"{key}"' in source
    assert event in source
    assert 'perf_counter' in source


def test_decision_timing_contract_includes_all_stages_and_optimizer_diagnostics():
    source = inspect.getsource(decision_runner.run_desktop_decision)
    _assert_declared_contract(source, DECISION_KEYS, 'DECISION_TIMING=')
    assert 'DECISION_DIAGNOSTIC=' in source
    assert '"v1"' in source and '"v2"' in source and '"v3"' in source


def test_chip_timing_contract_includes_cache_hit_and_miss_stages():
    source = inspect.getsource(chip_runner.run_desktop_chip_screen)
    _assert_declared_contract(source, CHIP_KEYS, 'CHIP_TIMING=')
    # A hit reports zero child-process work; a miss records the measured lookup/run span.
    assert '0.0 if strategic_reused' in source
    assert 'timings["strategic_cache_lookup"]' in source


def test_shadow_uses_only_elapsed_time_diagnostics_not_decision_semantics():
    source = inspect.getsource(shadow)
    assert '"timings": timings' in source
    for key in ("greedy", "v1", "v2"):
        assert f'timings["{key}"]' in source
