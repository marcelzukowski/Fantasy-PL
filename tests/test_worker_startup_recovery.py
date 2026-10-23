"""Real bounded worker faults, without engine computations or provider calls."""

import os
from pathlib import Path
from time import monotonic

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QProcess
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

import desktop_app.main_window as module
from desktop_app.chip_orchestration import ChipRunState
from desktop_app.decision_orchestration import DecisionRunState
from desktop_app.full_analysis import FullAnalysisState
from desktop_app.main_window import MainWindow
from desktop_app.orchestration import DesktopEngineError

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def window(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    view = MainWindow(ROOT)
    view.root = tmp_path
    view.latest_decision_report = tmp_path / "existing-decision.json"
    view.selected_projection_bundle = tmp_path / "bundle.json"
    monkeypatch.setattr(view, "_persist_active_analysis", lambda *_: None)
    monkeypatch.setattr(module, "validate_state", lambda *_: None)
    monkeypatch.setattr(module, "write_decision_request", lambda path, _: path)
    monkeypatch.setattr(module, "chip_bundle_for_state", lambda *_: view.selected_projection_bundle)
    monkeypatch.setattr(
        view, "_selected_bundle_for_state", lambda *_: view.selected_projection_bundle
    )
    monkeypatch.setattr(
        module, "resolve_engine_python", lambda _: ROOT / ".venv/Scripts/python.exe"
    )
    yield view, app
    for name in ("decision_process", "chip_process"):
        process = getattr(view, name)
        if process is not None and process.state() != QProcess.ProcessState.NotRunning:
            process.kill()
            process.waitForFinished(3000)
    view.close()
    app.processEvents()


def wait_for(app, condition, seconds=5):
    deadline = monotonic() + seconds
    while not condition() and monotonic() < deadline:
        app.processEvents()
        QTest.qWait(10)
    assert condition()


def start(view, stage, monkeypatch, arguments):
    monkeypatch.setattr(module, stage + "_arguments", lambda **_: arguments)
    view._set_full_analysis_state(
        FullAnalysisState.DECISION if stage == "decision" else FullAnalysisState.CHIP_SCREEN
    )
    getattr(view, "start_" + stage + "_run")()


@pytest.mark.parametrize("stage", ["decision", "chip"])
def test_real_failed_to_start_releases_workflow_and_allows_retry(window, monkeypatch, stage):
    view, app = window
    previous = view.latest_decision_report
    monkeypatch.setattr(module, "resolve_engine_python", lambda _: view.root / "missing-python.exe")
    start(view, stage, monkeypatch, [])
    expected = DecisionRunState.ERROR if stage == "decision" else ChipRunState.ERROR
    wait_for(app, lambda: getattr(view, stage + "_run_state") is expected)
    assert getattr(view, stage + "_process") is None
    assert view.engine_progress.maximum() == 1
    assert view.run_full.isEnabled()
    assert view.latest_decision_report == previous
    assert "could not start" in view.statusBar().currentMessage().lower()
    assert "missing-python" in view.engine_log.toPlainText()
    if stage == "chip":
        assert view.retry_chip_button.isEnabled()
        view.cancel_chip_run()
        assert not view._chip_cancel_requested
    monkeypatch.setattr(
        module, "resolve_engine_python", lambda _: ROOT / ".venv/Scripts/python.exe"
    )
    start(view, stage, monkeypatch, ["-c", "raise SystemExit(1)"])
    wait_for(app, lambda: getattr(view, stage + "_process") is None)
    assert getattr(view, stage + "_run_state") is expected


@pytest.mark.parametrize("stage", ["decision", "chip"])
def test_missing_python_during_preparation_ends_full_workflow(window, monkeypatch, stage):
    view, _ = window

    def missing(_):
        raise DesktopEngineError("External Python is missing; repair .venv.")

    monkeypatch.setattr(module, "resolve_engine_python", missing)
    start(view, stage, monkeypatch, [])
    assert view.full_analysis_state is (
        FullAnalysisState.ERROR if stage == "decision" else FullAnalysisState.PARTIAL
    )
    assert view.run_full.isEnabled()
    assert "External Python" in view.engine_log.toPlainText()


@pytest.mark.parametrize("stage", ["decision", "chip"])
@pytest.mark.parametrize(
    "script",
    [
        "raise ModuleNotFoundError('audit missing dependency')",
        "raise SystemExit(0)",
        "print('initialization failed', flush=True); raise SystemExit(2)",
    ],
)
def test_immediate_dependency_or_handshake_exit_is_recoverable(window, monkeypatch, stage, script):
    view, app = window
    previous = view.latest_decision_report
    start(view, stage, monkeypatch, ["-c", script])
    wait_for(app, lambda: getattr(view, stage + "_process") is None)
    expected = DecisionRunState.ERROR if stage == "decision" else ChipRunState.ERROR
    assert getattr(view, stage + "_run_state") is expected
    assert view.engine_progress.maximum() == 1 and view.run_full.isEnabled()
    assert view.latest_decision_report == previous
    if "missing dependency" in script:
        assert "audit missing dependency" in view.engine_log.toPlainText()
