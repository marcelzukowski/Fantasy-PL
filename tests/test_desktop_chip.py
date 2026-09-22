import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from desktop_app.chip_orchestration import ChipRunState, format_chip_summary
from desktop_app.chip_runner import available_chips
from desktop_app.main_window import MainWindow
from fpl_engine.optimizer import ChipState, OptimizerRules, SquadPlayer, SquadState


ROOT = Path(__file__).resolve().parents[1]
AT = datetime(2026, 9, 15, 13, 5, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _report(tmp_path, *, chip=None, mutations=None):
    path = tmp_path / "chip.json"
    path.write_text(json.dumps({
        "external_mutations": [] if mutations is None else mutations,
        "recommendation": {
            "chip": chip,
            "incremental_ev": 4.25 if chip else None,
            "reason": "existing timing-policy result",
            "horizon_gameweeks": 6,
            "available_chips": ["wildcard", "bench_boost"],
        },
    }), encoding="utf-8")
    return path


def test_no_chip_summary_is_explicit():
    text = format_chip_summary({"recommendation": {
        "chip": None, "reason": "No available chip clears the existing timing policy.",
        "horizon_gameweeks": 6, "available_chips": ["wildcard"],
    }})
    assert "NO CHIP / ROLL" in text and "Horizon: 6 GW" in text


def test_chip_summary_renders_existing_fields():
    text = format_chip_summary({"recommendation": {
        "chip": "triple_captain", "incremental_ev": 4.25, "reason": "existing timing-policy result",
        "horizon_gameweeks": 6, "available_chips": ["triple_captain", "bench_boost"],
    }})
    assert "TRIPLE CAPTAIN" in text and "Projected gain: +4.25 EV" in text
    assert "Triple Captain" in text and "Bench Boost" in text


def test_chip_button_requires_existing_decision_result(qapp):
    window = MainWindow(ROOT)
    try:
        window.run_chips.click()
        assert window.chip_run_state is ChipRunState.ERROR
        assert "Decision Engine" in window.statusBar().currentMessage()
    finally:
        window.close()


def test_duplicate_chip_run_is_blocked(qapp):
    class RunningProcess:
        def state(self):
            from PySide6.QtCore import QProcess
            return QProcess.ProcessState.Running

    window = MainWindow(ROOT)
    try:
        window.chip_process = RunningProcess()
        window.start_chip_run()
        assert "already running" in window.statusBar().currentMessage()
    finally:
        window.close()


def test_chip_completion_renders_recommendation_without_account_mutation(qapp, tmp_path):
    window = MainWindow(ROOT)
    try:
        path = _report(tmp_path, chip="bench_boost")
        window._chip_stdout = f"CHIP_REPORT={path}"
        window._chip_finished(0, 0)
        assert window.chip_run_state is ChipRunState.SUCCESS
        assert "BENCH BOOST" in window.analysis_chip_summary.text()
        assert window.latest_chip_report == path
    finally:
        window.close()


def test_mutating_chip_report_is_rejected_cleanly(qapp, tmp_path):
    window = MainWindow(ROOT)
    try:
        path = _report(tmp_path, chip="bench_boost", mutations=["activate_chip"])
        window._chip_stdout = f"CHIP_REPORT={path}"
        window._chip_finished(0, 0)
        assert window.chip_run_state is ChipRunState.ERROR
        assert "read-only safety" in window.engine_log.toPlainText()
    finally:
        window.close()


def test_used_chip_is_not_available_to_existing_chip_calculation():
    rules = OptimizerRules.load(ROOT)
    positions = ["GK"] * 2 + ["DEF"] * 5 + ["MID"] * 5 + ["FWD"] * 3
    players = tuple(SquadPlayer(f"p{i}", position, f"club_{i // 3}", 50, 50, 50) for i, position in enumerate(positions))
    state = SquadState(players, 0, 1, ChipState(wildcard_h1=False), 5, rules.season, rules.version, AT)
    assert "wildcard" not in available_chips(state, rules)
    assert "bench_boost" in available_chips(state, rules)


def test_second_half_wildcard_is_unavailable_before_gw20_and_independent_after_reset():
    rules = OptimizerRules.load(ROOT)
    positions = ["GK"] * 2 + ["DEF"] * 5 + ["MID"] * 5 + ["FWD"] * 3
    players = tuple(SquadPlayer(f"p{i}", position, f"club_{i // 3}", 50, 50, 50) for i, position in enumerate(positions))
    chips = ChipState(wildcard_h1=False, wildcard_h2=True)
    before_reset = SquadState(players, 0, 1, chips, 5, rules.season, rules.version, AT)
    after_reset = SquadState(players, 0, 1, chips, 20, rules.season, rules.version, AT)

    assert "wildcard" not in available_chips(before_reset, rules)
    assert "wildcard" in available_chips(after_reset, rules)


def test_chip_summary_distinguishes_exact_and_strategic_estimate():
    text = format_chip_summary({
        "recommendation": {
            "chip": "bench_boost", "incremental_ev": 8.16, "reason": "existing timing-policy result",
            "horizon_gameweeks": 6, "near_term_start_gameweek": 5, "near_term_end_gameweek": 10,
            "available_chips": ["bench_boost"],
        },
        "chip_period": {"end_gameweek": 19},
        "strategic": {
            "simulations_per_fixture": 3000,
            "error": None,
            "materially_stronger_candidate": {
                "chip": "bench_boost", "gameweek": 17, "incremental_ev": 10.0,
            },
        },
    })
    assert "Near-term horizon: GW5–GW10" in text
    assert "Best later candidate: GW17 — BENCH BOOST" in text
    assert "Strategic simulations: 3000" in text
    assert "Chip period ends: GW19" in text
