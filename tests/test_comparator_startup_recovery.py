import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QProcess
from PySide6.QtTest import QTest

import desktop_app.manual_comparator as module
from tests.test_manual_comparator_ui import widget as widget
from tests.test_worker_startup_recovery import ROOT, wait_for


def test_synchronous_startup_failure_cannot_restore_busy_state(widget, monkeypatch):
    view, _ = widget

    class FailedProcess(QProcess):
        def start(self, *_):
            self.errorOccurred.emit(QProcess.ProcessError.FailedToStart)

    monkeypatch.setattr(module, "QProcess", FailedProcess)
    monkeypatch.setattr(
        module, "resolve_engine_python", lambda _: ROOT / ".venv/Scripts/python.exe"
    )
    monkeypatch.setattr(view, "_context_fingerprint", lambda: "startup-test")
    view.load_context()
    assert not view._busy
    assert view.load_button.isEnabled()
    assert not view._timeout.isActive()
    assert "Worker failure" in view.status.text()


@pytest.mark.parametrize(
    "mode", ["missing", "dependency", "json-initialization", "silent-cancel", "silent-timeout"]
)
def test_failed_or_partial_comparator_startup_stops_owned_process(widget, monkeypatch, mode):
    view, _ = widget

    class FaultProcess(QProcess):
        def start(self, *_):
            if mode == "missing":
                super().start(str(view.root / "missing-python.exe"), [])
            else:
                code = (
                    "raise ModuleNotFoundError('startup dependency')"
                    if mode == "dependency"
                    else "import time; time.sleep(10)"
                )
                if mode == "json-initialization":
                    code = "import json; print(json.dumps(dict(type='error', id='', message='invalid frozen context')), flush=True); raise SystemExit(1)"
                super().start(str(ROOT / ".venv/Scripts/python.exe"), ["-c", code])

    monkeypatch.setattr(module, "QProcess", FaultProcess)
    monkeypatch.setattr(
        module, "resolve_engine_python", lambda _: ROOT / ".venv/Scripts/python.exe"
    )
    monkeypatch.setattr(view, "_context_fingerprint", lambda: "startup-test")
    view.load_context()
    process = view.process
    if mode.startswith("silent"):
        assert process.waitForStarted(3000)
        if mode == "silent-cancel":
            view.cancel()
        else:
            view._timeout.start(30)
    from PySide6.QtWidgets import QApplication

    wait_for(QApplication.instance(), lambda: not view._busy)
    assert view.process is None and view.load_button.isEnabled()
    assert view.progress.maximum() == 1 and not view.evaluate_button.isEnabled()
    assert not view._timeout.isActive()
    if mode == "dependency":
        assert "startup dependency" in view.status.text()
    if mode == "json-initialization":
        assert "invalid frozen context" in view.status.text()
    view.cancel()
    QTest.qWait(10)
    assert view.process is None and not view._busy
