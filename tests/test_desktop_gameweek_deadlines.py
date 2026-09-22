from datetime import datetime, timedelta, timezone
import json

import pytest
from PySide6.QtWidgets import QApplication

from desktop_app.gameweek_deadlines import (
    OfficialEventDeadline,
    event_deadlines,
    first_actionable_gameweek,
    load_cached_event_deadlines,
)
import desktop_app.main_window as main_window_module
from desktop_app.main_window import MainWindow


ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


UTC = timezone.utc


def test_first_actionable_gameweek_moves_only_after_the_official_deadline():
    deadline = datetime(2026, 9, 20, 17, tzinfo=UTC)
    events = (
        OfficialEventDeadline(5, deadline - timedelta(days=7)),
        OfficialEventDeadline(6, deadline),
        OfficialEventDeadline(7, deadline + timedelta(days=7)),
    )

    assert first_actionable_gameweek(events, now=deadline - timedelta(seconds=1)) == 6
    assert first_actionable_gameweek(events, now=deadline) == 6
    assert first_actionable_gameweek(events, now=deadline + timedelta(seconds=1)) == 7


def test_first_actionable_gameweek_requires_an_aware_clock():
    with pytest.raises(ValueError, match="timezone-aware"):
        first_actionable_gameweek((), now=datetime(2026, 9, 20, 17))


def test_load_cached_event_deadlines_uses_latest_readable_official_raw_snapshot(tmp_path):
    root = tmp_path
    older = root / "data" / "snapshots" / "official_fpl_api" / "2026-09-20T10-00-00.000000Z"
    latest = root / "data" / "snapshots" / "official_fpl_api" / "2026-09-21T10-00-00.000000Z"
    raw_path = root / "data" / "raw" / "local_fpl_archive" / "bootstrap_static" / "2026-09-20" / "one" / "payload.bin"
    raw_path.parent.mkdir(parents=True)
    raw_path.write_text(json.dumps({"events": [{"id": 6, "deadline_time": "2026-09-20T17:00:00Z"}]}), encoding="utf-8")
    older.mkdir(parents=True)
    older.joinpath("bootstrap_static.snapshot.json").write_text(json.dumps({"raw_snapshot": {"payload_path": raw_path.relative_to(root / "data" / "raw").as_posix()}}), encoding="utf-8")
    latest.mkdir(parents=True)
    latest.joinpath("bootstrap_static.snapshot.json").write_text("{broken", encoding="utf-8")

    assert load_cached_event_deadlines(root) == (OfficialEventDeadline(6, datetime(2026, 9, 20, 17, tzinfo=UTC)),)


def test_event_deadlines_ignores_invalid_official_rows():
    assert event_deadlines({"events": [
        {"id": 3, "deadline_time": "2026-09-01T12:00:00Z"},
        {"id": "4", "deadline_time": "2026-09-08T12:00:00Z"},
        {"id": 5, "deadline_time": "not-a-date"},
    ]}) == (OfficialEventDeadline(3, datetime(2026, 9, 1, 12, tzinfo=UTC)),)


def test_main_window_moves_live_selector_to_the_first_unpassed_official_deadline(qapp, monkeypatch):
    deadline = datetime(2026, 9, 20, 17, tzinfo=UTC)
    events = (
        OfficialEventDeadline(5, deadline - timedelta(days=7)),
        OfficialEventDeadline(6, deadline),
        OfficialEventDeadline(7, deadline + timedelta(days=7)),
    )

    class BeforeDeadline:
        @staticmethod
        def now(_timezone):
            return deadline - timedelta(seconds=1)

    monkeypatch.setattr(main_window_module, "load_cached_event_deadlines", lambda _root: events)
    monkeypatch.setattr(main_window_module, "datetime", BeforeDeadline)
    window = MainWindow(ROOT)
    try:
        window.gw_spin.setValue(1)
        window._refresh_actionable_gameweek_minimum()
        assert window.gw_spin.value() == 6
        window.gw_spin.setValue(5)
        assert window.gw_spin.value() == 6

        class AfterDeadline:
            @staticmethod
            def now(_timezone):
                return deadline + timedelta(seconds=1)

        monkeypatch.setattr(main_window_module, "datetime", AfterDeadline)
        window._refresh_actionable_gameweek_minimum()
        assert window.gw_spin.value() == 7
    finally:
        window.close()
