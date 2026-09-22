import json
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

import desktop_app.main_window as main_window_module
from desktop_app.chip_orchestration import ChipRunState
from desktop_app.full_analysis import FullAnalysisState, full_analysis_summary
from desktop_app.main_window import MainWindow


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def test_full_analysis_summary_distinguishes_partial_chip_result():
    result = full_analysis_summary(
        state=FullAnalysisState.PARTIAL, gameweek=5, bundle_label="20260915T130524Z",
        chip_status="Decision and Recommended XI are ready; Chip Screen failed.",
    )
    assert "PARTIAL" in result and "GW 5" in result and "Chip Screen failed" in result


def test_full_analysis_reuses_matching_bundle_then_starts_decision(qapp, monkeypatch):
    window = MainWindow(ROOT)
    try:
        state = window._state_from_ui()
        bundle = ROOT / "data" / "processed" / "predictions" / "2026-27" / "test-run" / "shadow_projection_bundle.json"
        started = []
        monkeypatch.setattr(main_window_module, "decision_bundle_for_state", lambda *_: bundle)
        monkeypatch.setattr(main_window_module, "projection_run_summary", lambda *_: {"season": state.season, "gameweek": state.gameweek})
        monkeypatch.setattr(window, "start_decision_run", lambda: started.append(True))
        window.start_full_analysis()
        assert started == [True]
        assert window.full_analysis_state is FullAnalysisState.DECISION
        assert window.latest_projection_run == bundle.parent
        assert "reused" in window.engine_log.toPlainText().lower()
    finally:
        window.close()


def test_full_analysis_does_not_start_decision_without_valid_bundle(qapp, monkeypatch):
    window = MainWindow(ROOT)
    try:
        started = []
        monkeypatch.setattr(main_window_module, "decision_bundle_for_state", lambda *_: (_ for _ in ()).throw(main_window_module.DesktopEngineError("missing")))
        monkeypatch.setattr(window, "start_decision_run", lambda: started.append(True))
        window.start_full_analysis()
        assert started == []
        assert window.full_analysis_state is FullAnalysisState.ERROR
        assert "matching production projection bundle" in window.statusBar().currentMessage()
    finally:
        window.close()


def test_full_analysis_starts_chip_only_after_decision_and_keeps_partial_results(qapp, monkeypatch):
    window = MainWindow(ROOT)
    try:
        started = []
        window._set_full_analysis_state(FullAnalysisState.DECISION)
        window.analysis_transfer_summary.setText("OUT: Existing\nIN: Existing")
        monkeypatch.setattr(window, "start_chip_run", lambda: started.append(True))
        window._full_analysis_after_decision(succeeded=True)
        assert started == [True]
        assert window.full_analysis_state is FullAnalysisState.CHIP_SCREEN
        assert "still calculating" in window.analysis_chip_summary.text()
        window._full_analysis_after_chip(outcome="failed")
        assert window.full_analysis_state is FullAnalysisState.PARTIAL
        assert "Recommended XI are ready" in window.statusBar().currentMessage()
        assert window.analysis_transfer_summary.text() == "OUT: Existing\nIN: Existing"
    finally:
        window.close()


def test_cancelled_chip_preserves_full_analysis_decision_result(qapp):
    window = MainWindow(ROOT)
    try:
        window._set_full_analysis_state(FullAnalysisState.CHIP_SCREEN)
        window._chip_cancel_requested = True
        window._chip_finished(1, 0)
        assert window.chip_run_state is ChipRunState.CANCELLED
        assert window.full_analysis_state is FullAnalysisState.PARTIAL
        assert "cancelled" in window.statusBar().currentMessage().lower()
    finally:
        window.close()


def test_fast_chip_completion_marks_full_analysis_complete(qapp, tmp_path):
    window = MainWindow(ROOT)
    try:
        report_path = tmp_path / "chip.json"
        report_path.write_text(json.dumps({
            "external_mutations": [],
            "recommendation": {"chip": None, "reason": "existing result", "available_chips": []},
        }), encoding="utf-8")
        window._set_full_analysis_state(FullAnalysisState.CHIP_SCREEN)
        window._chip_stdout = f"CHIP_REPORT={report_path}"
        window._chip_finished(0, 0)
        assert window.full_analysis_state is FullAnalysisState.COMPLETE
        assert window.chip_run_state is ChipRunState.SUCCESS
        assert "NO CHIP / ROLL" in window.analysis_chip_summary.text()
    finally:
        window.close()


def test_cancel_requests_only_child_chip_process(qapp):
    class RunningProcess:
        def __init__(self): self.terminated = False
        def state(self):
            from PySide6.QtCore import QProcess
            return QProcess.ProcessState.Running
        def terminate(self): self.terminated = True

    window = MainWindow(ROOT)
    try:
        process = RunningProcess()
        window.chip_process = process
        window.analysis_transfer_summary.setText("Decision remains available")
        window.cancel_chip_run()
        assert process.terminated
        assert window._chip_cancel_requested
        assert window.analysis_transfer_summary.text() == "Decision remains available"
    finally:
        window.close()


def test_duplicate_full_analysis_is_blocked(qapp):
    window = MainWindow(ROOT)
    try:
        window._set_full_analysis_state(FullAnalysisState.DECISION)
        window.start_full_analysis()
        assert "already running" in window.statusBar().currentMessage()
    finally:
        window.close()
