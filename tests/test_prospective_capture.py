"""Capture must preserve existing Decision bytes and never require Chip execution."""

from datetime import timedelta
from hashlib import sha256
import json

import pytest

from test_replay_archive import AT, _root
from fpl_engine.validation.prospective_capture import capture_decision
from fpl_engine.validation.replay_archive import ReplayArchiveError, validate_archive_case


def test_standalone_decision_archives_without_chip_and_is_idempotent(tmp_path):
    root, _, decision, _ = _root(tmp_path)
    original = decision.read_bytes()
    first = capture_decision(root, decision, now=AT + timedelta(minutes=3))
    first_bytes = first.read_bytes()
    second = capture_decision(root, decision, now=AT + timedelta(minutes=4))
    assert first == second and first.read_bytes() == first_bytes
    assert decision.read_bytes() == original
    validation = validate_archive_case(root, first)
    assert validation.status.value == "PRE_DEADLINE_COMPLETE"
    case = json.loads(first.read_text())
    analysis = json.loads((root / case["analysis_manifest"]["path"]).read_text())
    assert analysis["status"] == "PARTIAL" and analysis["chip_report"] is None
    assert analysis["decision_report_reference"]["sha256"] == sha256(original).hexdigest()


def test_postdeadline_capture_cannot_create_retrospective_archive(tmp_path):
    root, _, decision, _ = _root(tmp_path)
    before = set(root.rglob("*"))
    with pytest.raises(ReplayArchiveError, match="deadline"):
        capture_decision(root, decision, now=AT + timedelta(hours=2))
    assert set(root.rglob("*")) == before


def test_capture_rejects_tampered_projection_before_writing_manifest(tmp_path):
    root, _, decision, manifest = _root(tmp_path)
    (manifest.parent / "minutes.json").write_text("changed")
    with pytest.raises(ReplayArchiveError, match="integrity"):
        capture_decision(root, decision, now=AT + timedelta(minutes=3))
    assert not list((root / "data/processed/prospective_captures").rglob("prospective-*"))


def test_capture_never_overwrites_existing_manifest(tmp_path):
    root, _, decision, _ = _root(tmp_path)
    first = capture_decision(root, decision, now=AT + timedelta(minutes=3))
    case = json.loads(first.read_text())
    path = root / case["analysis_manifest"]["path"]
    path.write_text("{}")
    with pytest.raises(ReplayArchiveError):
        capture_decision(root, decision, now=AT + timedelta(minutes=4))
    assert path.read_text() == "{}"


def test_capture_rejects_report_outside_project(tmp_path):
    root, _, decision, _ = _root(tmp_path / "project")
    outside = tmp_path / "outside.json"
    outside.write_bytes(decision.read_bytes())
    with pytest.raises(ReplayArchiveError, match="outside"):
        capture_decision(root, outside, now=AT + timedelta(minutes=3))


@pytest.mark.parametrize("failure", [False, True])
def test_external_worker_main_captures_after_decision_without_changing_its_result(
    tmp_path,
    monkeypatch,
    capsys,
    failure,
):
    import sys
    import desktop_app.decision_runner as runner
    import fpl_engine.validation.prospective_capture as capture

    root, _, decision, _ = _root(tmp_path)
    calls = []

    def finished_decision(**kwargs):
        calls.append("decision")
        return decision

    def capture_completed(project, report):
        assert calls == ["decision"] and report == decision
        calls.append("capture")
        if failure:
            raise ReplayArchiveError("past deadline")
        return root / "archive.json"

    monkeypatch.setattr(runner, "run_desktop_decision", finished_decision)
    monkeypatch.setattr(capture, "capture_decision", capture_completed)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "decision_runner",
            "--desktop-state",
            "unused",
            "--prediction-bundle",
            "unused",
            "--output-dir",
            "unused",
        ],
    )
    assert runner.main() == 0
    assert calls == ["decision", "capture"]
    output = capsys.readouterr().out
    assert f"DECISION_REPORT={decision}" in output
    assert ("PROSPECTIVE_CAPTURE=UNAVAILABLE" if failure else "PROSPECTIVE_ARCHIVE=") in output
