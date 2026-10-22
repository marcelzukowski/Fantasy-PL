from __future__ import annotations

import subprocess

import pytest

import desktop_app.chip_runner as runner


class _Child:
    def __init__(self, *, exits_on_terminate=True):
        self.returncode = None
        self.exits_on_terminate = exits_on_terminate
        self.terminated = 0
        self.killed = 0
        self.waited = 0
        self.pid = 4242

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated += 1
        if self.exits_on_terminate:
            self.returncode = -15

    def kill(self):
        self.killed += 1
        self.returncode = -9

    def wait(self, timeout=None):
        self.waited += 1
        if self.returncode is None:
            raise subprocess.TimeoutExpired('child', timeout)
        return self.returncode


def test_cancel_before_strategic_child_start_does_not_spawn(tmp_path, monkeypatch):
    base = tmp_path / 'base.json'; base.write_text('{}')
    monkeypatch.setattr(runner, '_verified_bundle_identity', lambda _: {'verified': True})
    monkeypatch.setattr(runner.subprocess, 'Popen', lambda *a, **k: pytest.fail('child must not spawn'))
    with pytest.raises(runner.DesktopChipCancelled):
        runner._strategic_bundle(project_root=tmp_path, state=type('S', (), {'season': '2026/27', 'current_gameweek': 5})(),
            base_bundle=base, strategic_gameweeks=(11,), chip_period_end=19, cancel_requested=lambda: True)


def test_owned_child_gracefully_terminates_and_reaps():
    child = _Child()
    runner._terminate_owned_child(child)
    assert child.terminated == 1 and child.killed == 0 and child.waited == 1


def test_owned_child_uses_kill_fallback_and_reaps(monkeypatch):
    child = _Child(exits_on_terminate=False)
    monkeypatch.setattr(runner.os, 'name', 'posix')
    runner._terminate_owned_child(child)
    assert child.terminated == 1 and child.killed == 1 and child.returncode == -9


def test_completed_child_is_not_terminated_or_waited_twice():
    child = _Child(); child.returncode = 0
    runner._terminate_owned_child(child)
    assert child.terminated == 0 and child.killed == 0 and child.waited == 0
