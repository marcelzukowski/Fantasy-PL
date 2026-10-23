import os
from functools import lru_cache

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from time import perf_counter
import sys

import pytest
from PySide6.QtCore import QPoint, QProcess, QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from desktop_app.manual_comparator import ManualComparator


@pytest.fixture
def widget(tmp_path):
    app = QApplication.instance() or QApplication([])
    state = {"bank_tenths": 0, "free_transfers": 4, "player_ids": [f"p{i}" for i in range(15)]}
    view = ManualComparator(tmp_path, lambda: dict(state), lambda: tmp_path / "bundle.json")
    view.resize(1550, 820)
    view.show()
    app.processEvents()
    players = []
    for owned, prefix, count in ((True, "p", 15), (False, "new", 15)):
        for i in range(count):
            players.append(
                {
                    "player_id": f"{prefix}{i}",
                    "name": f"{prefix}{i} Very long player surname without truncation",
                    "position": "GK" if i < 2 else "DEF" if i < 7 else "MID" if i < 12 else "FWD",
                    "club": "Club " + str(i % 5),
                    "price": 50 + i,
                    "selling_price": 50 if owned else None,
                    "owned": owned,
                    "points_so_far": i * 10,
                    "next_gw_projection": float(15 - i),
                    "next_5gw_total": float(i) / 2,
                    "projection_coverage": 5,
                    "fixtures_5gw": [
                        {"gameweek": gw, "opponent": "AVL", "venue": "H", "projected_points": 4.5}
                        for gw in range(8, 13)
                    ],
                }
            )
    view.handle_message(
        {
            "type": "ready",
            "context_id": "ctx",
            "input_sha256": "input",
            "players": players,
            "bank": 0,
            "free_transfers": 4,
            "owned_ids": state["player_ids"],
        }
    )
    app.processEvents()
    yield view, state
    view.shutdown()
    view.close()
    app.processEvents()


def mouse_toggle(panel, pid, checkbox=False):
    row = next(i for i, p in enumerate(panel.source.records) if p["player_id"] == pid)
    index = panel.proxy.mapFromSource(panel.source.index(row, 0))
    assert index.isValid()
    panel.table.scrollTo(index)
    QApplication.processEvents()
    rect = panel.table.visualRect(index)
    point = rect.topLeft() + QPoint(10, rect.height() // 2) if checkbox else rect.center()
    QTest.mouseClick(panel.table.viewport(), Qt.MouseButton.LeftButton, pos=point)


def valid(view, k=0):
    view._validation_id = "validation"
    view.handle_message(
        {
            "type": "validation",
            "id": "validation",
            "context_id": "ctx",
            "valid": True,
            "summary": {
                "k": k,
                "initial_ft": 4,
                "hit_points": 4 if k == 5 else 0,
                "bank_after": 0,
                "ft_after": 1,
                "final_squad": [f"p{i}" for i in range(15)],
            },
        }
    )


def result(view, outs, ins):
    from copy import deepcopy

    payload = deepcopy(_native_result(tuple(outs), tuple(ins)))
    payload.update(type="result", id="evaluation", context_id="ctx", input_sha256="input")
    return payload


@lru_cache(maxsize=8)
def _native_result(outs, ins):
    from desktop_app.manual_scenario_engine import ManualScenarioEvaluator
    from tests.test_manual_scenario_engine import _shared

    return ManualScenarioEvaluator(_shared()).evaluate(outs, ins)


def test_filters_validation_and_hold_reset(widget):
    view, _ = widget
    assert not view.evaluate_button.isEnabled()
    view.in_panel.filter()
    assert view.in_panel.proxy.rowCount() == 15
    view.in_panel.search.setText("new14")
    assert view.in_panel.proxy.rowCount() == 1
    view.in_panel.position.setCurrentText("GK")
    assert view.in_panel.proxy.rowCount() == 0
    view.in_panel.search.clear()
    assert view.in_panel.proxy.rowCount() == 2
    view.in_panel.max_price.setValue(4.9)
    assert view.in_panel.proxy.rowCount() == 0
    view.in_panel.max_price.setValue(30)
    view.in_panel.position.setCurrentIndex(0)
    mouse_toggle(view.in_panel, "new0")
    assert len(view.incoming_ids) == 1
    view.reset_hold()
    assert view._package() == ([], [])
    valid(view)
    assert view.evaluate_button.isEnabled()
    assert "FT 4" in view.squad.toPlainText()


def test_long_lists_side_by_side_persistence_and_stale_result_rejection(widget):
    view, state = widget
    for i in range(5):
        mouse_toggle(view.out_panel, f"p{i}")
    view.incoming_ids = [f"new{i}" for i in range(5)]
    view._edited()
    valid(view, 5)
    outs, ins = view._package()
    view._evaluation_id = "evaluation"
    view.name.setText("Five transfers")
    view.handle_message(result(view, outs, ins))
    view.save_scenario()
    assert view.comparison.columnCount() == 4
    for pid in outs:
        assert view.players[pid]["name"] in view.comparison.item(4, 2).text()
    for pid in ins:
        assert view.players[pid]["name"] in view.comparison.item(5, 2).text()
    assert view.comparison.rowHeight(4) >= view.fontMetrics().lineSpacing() * 5
    assert view.comparison.textElideMode() == Qt.TextElideMode.ElideNone
    assert len(view.store.load()) == 1
    view.name.setText("Renamed")
    view.rename_saved()
    assert view.store.load()[0]["name"] == "Renamed"
    view.reset_hold()
    view.load_saved()
    assert view._package() == (outs, ins)
    assert view.out_panel.counter.text() == "OUT selected: 5/5"
    assert view.out_panel.source.data(
        view.out_panel.source.index(0, 0), Qt.ItemDataRole.FontRole
    ).bold()
    assert (
        view.out_panel.source.data(
            view.out_panel.source.index(0, 0), Qt.ItemDataRole.BackgroundRole
        )
        is not None
    )
    view._fingerprint = view._context_fingerprint()
    state["bank_tenths"] = 1
    view._watch_context()
    assert view.context_id is None and not view.evaluate_button.isEnabled()
    assert any(
        view.comparison.item(0, c).text() == "stale" for c in range(view.comparison.columnCount())
    )
    assert all(
        view.comparison.item(1, c).text() == "—" for c in range(view.comparison.columnCount())
    )
    view.delete_saved()
    assert view.store.load() == []


def test_external_worker_does_not_block_gui_and_cancellation_stops_owned_process(widget):
    view, _ = widget
    process = QProcess(view)
    process.start(
        sys.executable,
        [
            "-c",
            "from desktop_app.manual_worker_guard import watch_parent; watch_parent(); import time,os; print(os.getpid(),flush=True); time.sleep(20)",
        ],
    )
    assert process.waitForStarted(3000)
    assert process.waitForReadyRead(3000)
    worker_pid = int(bytes(process.readAllStandardOutput()).strip())
    if os.name == "nt":
        import ctypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_bool, ctypes.c_ulong]
        kernel.OpenProcess.restype = ctypes.c_void_p
        kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel.OpenProcess(0x100000, False, worker_pid)
        assert handle
    view.process = process
    view._set_busy(True)
    ticks = []
    timer = QTimer(view)
    timer.setInterval(10)
    timer.timeout.connect(lambda: ticks.append(1))
    timer.start()
    QTest.qWait(120)
    assert len(ticks) >= 3
    before = perf_counter()
    view.cancel()
    elapsed = perf_counter() - before
    assert process.state() == QProcess.ProcessState.NotRunning
    assert elapsed < 1.5
    assert not view._busy and "Cancelled" in view.status.text()
    if os.name == "nt":
        assert kernel.WaitForSingleObject(handle, 1500) == 0, "Venv child worker was orphaned"
        kernel.CloseHandle(handle)


def test_worker_error_is_visible_and_never_enables_evaluation(widget):
    view, _ = widget
    valid(view)
    view._evaluation_id = "evaluation"
    view._set_busy(True)
    view.handle_message({"type": "error", "id": "evaluation", "message": "controlled failure"})
    assert "controlled failure" in view.status.text()
    assert not view.evaluate_button.isEnabled() and not view.save_button.isEnabled()
    assert view.comparison.item(0, 0).text() == "failed"


def test_out_mouse_selection_invalidates_preview_and_matching_validation_restores_it(widget):
    view, _ = widget
    valid(view)
    view._evaluation_id = "evaluation"
    view.handle_message(result(view, [], []))
    assert view._current_result is not None
    assert view.evaluate_button.isEnabled() and view.save_button.isEnabled()

    mouse_toggle(view.out_panel, "p0", checkbox=True)
    assert view.out_panel.counter.text() == "OUT selected: 1/5"
    assert view.selection_message.text().startswith("OUT 1 / IN 0")
    assert not view.evaluate_button.isEnabled() and not view.save_button.isEnabled()
    assert view._current_result is None
    assert (
        "pending" in view.squad.toPlainText().lower()
        or "mismatch" in view.squad.toPlainText().lower()
    )

    mouse_toggle(view.out_panel, "p1")
    assert view.out_panel.counter.text() == "OUT selected: 2/5"
    mouse_toggle(view.in_panel, "new0")
    mouse_toggle(view.in_panel, "new1")
    valid(view, 2)
    assert "OUT 2 / IN 2" in view.selection_message.text()
    assert "valid" in view.selection_message.text().lower()
    assert view.evaluate_button.isEnabled() and view.save_button.isEnabled()


def test_out_selection_cap_rejects_sixth_with_status(widget):
    view, _ = widget
    for i in range(5):
        mouse_toggle(view.out_panel, f"p{i}")
    assert view.out_panel.counter.text() == "OUT selected: 5/5"
    mouse_toggle(view.out_panel, "p5")
    assert "p5" not in view.out_panel.checked_ids
    assert view.out_panel.counter.text() == "OUT selected: 5/5"
    assert "5" in view.status.text() or "5" in view.selection_message.text()
    view.reset_hold()
    assert view.out_panel.counter.text() == "OUT selected: 0/5"
    assert not view.out_panel.checked_ids and not view.in_panel.checked_ids


def test_selection_parity_filters_preserve_hidden_choices_and_in_limit(widget):
    view, _ = widget
    for panel, prefix in ((view.out_panel, "p"), (view.in_panel, "new")):
        for i in range(5):
            mouse_toggle(panel, f"{prefix}{i}", checkbox=(i == 0))
        mouse_toggle(panel, f"{prefix}5")
        assert len(panel.checked_ids) == 5
        panel.search.setText("14 Very")
        assert panel.proxy.rowCount() == 1
        assert len(panel.checked_ids) == 5
        panel.search.clear()
        panel.selected_only.setChecked(True)
        assert panel.proxy.rowCount() == 5
        mouse_toggle(panel, f"{prefix}0")
        assert len(panel.checked_ids) == 4
        assert panel.proxy.rowCount() == 4
    assert view._package() == ([f"p{i}" for i in range(1, 5)], [f"new{i}" for i in range(1, 5)])
    view.reset_hold()
    assert view.out_panel.counter.text() == "OUT selected: 0/5"
    assert view.in_panel.counter.text() == "IN selected: 0/5"


@pytest.mark.parametrize("column", [0, 3, 4, 5, 6])
def test_local_numeric_and_name_sorting_extended_columns(widget, column):
    view, _ = widget
    panel = view.in_panel
    assert panel.sort_by.currentText() == "Next 5 GW total"
    panel.sort_by.setCurrentIndex(panel.sort_by.findData(column))
    for direction, reverse in (("Asc", False), ("Desc", True)):
        panel.direction.setCurrentText(direction)
        rows = [
            panel.proxy.mapToSource(panel.proxy.index(i, column)).row()
            for i in range(panel.proxy.rowCount())
        ]
        values = [panel.source.value(row, column) for row in rows]
        assert values == sorted(
            values, key=lambda x: x.casefold() if isinstance(x, str) else x, reverse=reverse
        )
    assert panel.source.columnCount() == 8
    assert "Points so far" == panel.source.headerData(4, Qt.Orientation.Horizontal).replace(
        "\n", " "
    )
    assert "GW8 AVL H (4.5)" in panel.source.data(panel.source.index(0, 7))
    assert "GW12 AVL H (4.5)" in panel.source.data(panel.source.index(0, 7))


def test_missing_values_sort_last_and_local_filter_sort_stays_responsive(widget):
    view, _ = widget
    panel = view.in_panel
    rows = [dict(panel.source.records[i % 15], player_id=f"large{i}") for i in range(700)]
    rows[0]["next_5gw_total"] = None
    panel.set_players(rows)
    started = perf_counter()
    for direction in ("Asc", "Desc"):
        panel.direction.setCurrentText(direction)
        last = panel.proxy.mapToSource(panel.proxy.index(panel.proxy.rowCount() - 1, 6))
        assert panel.source.value(last.row(), 6) is None
        panel.search.setText("new1")
        panel.search.clear()
    assert perf_counter() - started < 2.0


@pytest.mark.parametrize("damage", ["objective", "partial", "captain"])
def test_corrupt_saved_result_never_renders_and_selections_can_be_re_evaluated(widget, damage):
    import json

    view, _ = widget
    payload = result(view, ["p0"], ["new0"])
    row = view.store.save("Recover", ["p0"], ["new0"], "ctx", "input", None)
    if damage == "objective":
        payload["scenario"]["objective"] += 100
    elif damage == "partial":
        del payload["scenario"]["path"]
    else:
        payload["scenario"]["captain"] = "missing"
    row["result"] = payload
    row["status"] = "evaluated"
    original = json.dumps({"schema_version": 1, "scenarios": [row]})
    view.store.path.write_text(original, encoding="utf-8")
    view._render_comparison()
    assert view.comparison.item(0, 1).text() == "invalid"
    assert view.comparison.item(1, 1).text() == "—"
    view.load_saved()
    assert view._package() == (["p0"], ["new0"])
    assert "re-evaluat" in view.status.text().lower()
    assert view._current_result is None
    valid(view, 1)
    assert view.evaluate_button.isEnabled()
    assert view.store.path.read_text(encoding="utf-8") == original


def test_invalid_worker_result_is_not_consumed(widget):
    view, _ = widget
    valid(view)
    payload = result(view, [], [])
    payload["scenario"]["objective"] += 100
    view._evaluation_id = "evaluation"
    view.handle_message(payload)
    assert view._current_result is None
    assert "invalid" in view.status.text().lower()
