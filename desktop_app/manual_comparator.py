"""Lightweight, read-only manual scenario UI; scientific work stays in QProcess."""

from dataclasses import asdict
import json
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QProcess, QProcessEnvironment, Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from .manual_scenario_store import ScenarioStore
from .manual_player_table import PlayerSelectionPanel
from .orchestration import resolve_engine_python


class ManualComparator(QWidget):
    def __init__(self, root, state_provider, bundle_provider, parent=None):
        super().__init__(parent)
        self.root = Path(root)
        self.state_provider = state_provider
        self.bundle_provider = bundle_provider
        self.store = ScenarioStore(self.root / "data/user/manual_transfer_scenarios.json")
        self.process = None
        self.context_id = None
        self.input_sha256 = None
        self.players = {}
        self.incoming_ids = []
        self._missing_out = []
        self._busy = False
        self._valid = False
        self._stdout = ""
        self._stderr = ""
        self._validation_id = None
        self._evaluation_id = None
        self._fingerprint = None
        self._bundle = None
        self._current_result = None
        self._baseline_result = None
        self._scenario_id = None
        self._restoring = False
        self._closing = False
        self._generation = 0
        self._request_path = None
        self._build()
        self._timeout = QTimer(self)
        self._timeout.setSingleShot(True)
        self._timeout.timeout.connect(
            lambda: self.cancel("Evaluation timed out. Reload context to retry.")
        )
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(250)
        self._debounce.timeout.connect(self._validate)
        self._watch = QTimer(self)
        self._watch.setInterval(1000)
        self._watch.timeout.connect(self._watch_context)
        self._watch.start()
        self._refresh_saved()

    def _button(self, text, slot, name):
        button = QPushButton(text)
        button.setObjectName(name)
        button.setAccessibleName(text)
        button.clicked.connect(slot)
        return button

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        top = QHBoxLayout()
        self.load_button = self._button("Load current context", self.load_context, "comparatorLoad")
        self.load_button.setShortcut("Alt+L")
        top.addWidget(self.load_button)
        self.reset_button = self._button("Reset to HOLD", self.reset_hold, "comparatorHold")
        top.addWidget(self.reset_button)
        self.evaluate_button = self._button(
            "Evaluate scenario", self.evaluate, "comparatorEvaluate"
        )
        self.evaluate_button.setShortcut("Alt+E")
        self.evaluate_button.setEnabled(False)
        top.addWidget(self.evaluate_button)
        self.cancel_button = self._button("Cancel", self.cancel, "comparatorCancel")
        self.cancel_button.setEnabled(False)
        top.addWidget(self.cancel_button)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        top.addWidget(self.progress, 1)
        layout.addLayout(top)
        note = QLabel(
            "Manual scenarios only — no account changes or automatic recommendations. V3 uses approximate 3-GW planning; future actions evaluate up to 2 transfers per GW. HOLD means hold now with V3 future planning. The 5-GW player columns are display-only."
        )
        note.setWordWrap(True)
        note.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(note)
        self.status = QLabel("Load a verified compatible V22 context to begin.")
        self.status.setWordWrap(True)
        self.status.setObjectName("comparatorStatus")
        self.status.setAccessibleName("Comparator status")
        layout.addWidget(self.status)
        self.selection_message = QLabel("OUT 0 / IN 0 — HOLD selected.")
        self.selection_message.setObjectName("comparatorSelectionMessage")
        self.selection_message.setWordWrap(True)
        layout.addWidget(self.selection_message)
        self.editor = QSplitter(Qt.Orientation.Horizontal)
        self.out_panel = PlayerSelectionPanel(True)
        self.in_panel = PlayerSelectionPanel(False)
        self.editor.addWidget(self.out_panel)
        self.editor.addWidget(self.in_panel)
        summary = QWidget()
        summary_layout = QVBoxLayout(summary)
        summary_layout.setContentsMargins(0, 0, 0, 0)
        summary_layout.addWidget(QLabel("Final squad and finance"))
        self.squad = QPlainTextEdit()
        self.squad.setReadOnly(True)
        self.squad.setAccessibleName("Final squad and transfer finance")
        self.squad.setObjectName("comparatorFinalSquad")
        summary_layout.addWidget(self.squad)
        self.editor.addWidget(summary)
        self.editor.setChildrenCollapsible(False)
        self.editor.setSizes([600, 960, 440])
        self.editor.setStretchFactor(0, 30)
        self.editor.setStretchFactor(1, 48)
        self.editor.setStretchFactor(2, 22)
        self.workspace = QSplitter(Qt.Orientation.Vertical)
        self.workspace.setChildrenCollapsible(False)
        self.workspace.addWidget(self.editor)
        layout.addWidget(self.workspace, 1)
        saved = QHBoxLayout()
        self.name = QLineEdit()
        self.name.setPlaceholderText("Scenario name")
        self.name.setMaxLength(120)
        self.name.setAccessibleName("Scenario name")
        saved.addWidget(self.name, 1)
        self.save_button = self._button("Save scenario", self.save_scenario, "comparatorSave")
        self.save_button.setEnabled(False)
        saved.addWidget(self.save_button)
        self.saved = QComboBox()
        self.saved.setAccessibleName("Saved scenarios")
        self.saved.setMinimumWidth(160)
        saved.addWidget(self.saved, 1)
        self.load_saved_button = self._button("Load saved", self.load_saved, "comparatorLoadSaved")
        saved.addWidget(self.load_saved_button)
        self.rename_button = self._button("Rename", self.rename_saved, "comparatorRename")
        saved.addWidget(self.rename_button)
        self.delete_button = self._button("Delete", self.delete_saved, "comparatorDelete")
        saved.addWidget(self.delete_button)
        results = QWidget()
        results_layout = QVBoxLayout(results)
        results_layout.setContentsMargins(0, 0, 0, 0)
        results_layout.addLayout(saved)
        self.comparison = QTableWidget()
        self.comparison.setAccessibleName("Scenario comparison")
        self.comparison.setObjectName("comparatorResults")
        self.comparison.setWordWrap(True)
        self.comparison.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.comparison.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.comparison.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        results_layout.addWidget(self.comparison, 1)
        self.workspace.addWidget(results)
        self.workspace.setSizes([560, 240])
        self.workspace.setStretchFactor(0, 7)
        self.workspace.setStretchFactor(1, 3)
        self.out_panel.source.checked_changed.connect(self._selection_changed)
        self.in_panel.source.checked_changed.connect(self._selection_changed)
        self.out_panel.source.limit_reached.connect(lambda: self._selection_limit("OUT"))
        self.in_panel.source.limit_reached.connect(lambda: self._selection_limit("IN"))

    def _state(self):
        state = self.state_provider()
        return asdict(state) if not isinstance(state, dict) else dict(state)

    def _context_fingerprint(self):
        state = self._state()
        state.pop("starting_player_ids", None)
        state.pop("bench_player_ids", None)
        paths = []
        if self._bundle:
            for name in (
                "shadow_projection_bundle.json",
                "run_manifest.json",
                "prediction_context.json",
                "current_players.json",
            ):
                path = self._bundle.parent / name
                paths.append((str(path), path.stat().st_mtime_ns, path.stat().st_size))
        # The selected projection selector can change even when account state stays identical.
        parent = self.window()
        selected = str(getattr(parent, "selected_projection_bundle", "")) if parent else ""
        return json.dumps([state, paths, selected], sort_keys=True)

    def _watch_context(self):
        if self._fingerprint is None or self._closing:
            return
        try:
            changed = self._context_fingerprint() != self._fingerprint
        except Exception:
            changed = True
        if changed:
            self.cancel(
                "Context changed. Load current context; saved results remain stale until re-evaluated."
            )

    def load_context(self):
        self.shutdown()
        self._closing = False
        self._current_result = None
        self._scenario_id = None
        try:
            state = self._state()
            self._bundle = Path(self.bundle_provider())
            python = resolve_engine_python(self.root)
            folder = self.root / "data/user/manual_comparator_runtime"
            folder.mkdir(parents=True, exist_ok=True)
            self._request_path = folder / (str(uuid4()) + ".json")
            self._request_path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
            self._fingerprint = self._context_fingerprint()
            process = QProcess(self)
            self.process = process
            self._generation += 1
            generation = self._generation
            environment = QProcessEnvironment.systemEnvironment()
            environment.insert("PYTHONUTF8", "1")
            environment.insert("PYTHONIOENCODING", "utf-8")
            environment.remove("FPL_SIMULATOR_CHALLENGER")
            process.setProcessEnvironment(environment)
            process.setWorkingDirectory(str(self.root))
            process.readyReadStandardOutput.connect(lambda: self._read_stdout(process, generation))
            process.readyReadStandardError.connect(lambda: self._read_stderr(process, generation))
            process.finished.connect(lambda code, status: self._finished(process, generation, code))
            process.errorOccurred.connect(
                lambda error: self._process_error(process, generation, error)
            )
            # start() can emit FailedToStart synchronously; never overwrite its cleanup.
            self._stdout = ""
            self._stderr = ""
            self._set_busy(True)
            self.status.setText("Loading verified context in the external scientific worker…")
            self._timeout.start(60000)
            process.start(
                str(python),
                [
                    "-m",
                    "desktop_app.manual_scenario_runner",
                    "--desktop-state",
                    str(self._request_path),
                    "--prediction-bundle",
                    str(self._bundle),
                    "--root",
                    str(self.root),
                ],
            )
        except Exception as exc:
            self.cancel(str(exc))

    def _set_busy(self, busy):
        self._busy = busy
        self.editor.setEnabled(not busy)
        self.load_button.setEnabled(not busy)
        self.reset_button.setEnabled(not busy)
        self.cancel_button.setEnabled(busy)
        self.evaluate_button.setEnabled(not busy and self._valid and bool(self.context_id))
        self.save_button.setEnabled(not busy and self._valid and bool(self.context_id))
        for button in (self.load_saved_button, self.rename_button, self.delete_button):
            button.setEnabled(not busy)
        self.progress.setRange(0, 0 if busy else 1)
        self.progress.setValue(0)

    def _read_stderr(self, process, generation):
        if generation == self._generation:
            self._stderr += bytes(process.readAllStandardError()).decode("utf-8", errors="replace")

    def _read_stdout(self, process, generation):
        if generation != self._generation:
            return
        self._stdout += bytes(process.readAllStandardOutput()).decode("utf-8", errors="replace")
        while "\n" in self._stdout:
            line, self._stdout = self._stdout.split("\n", 1)
            if not line.strip():
                continue
            try:
                self.handle_message(json.loads(line))
            except (ValueError, KeyError, TypeError) as exc:
                self.cancel("Invalid comparator worker response: " + str(exc))
                return

    def _send(self, command):
        if not self.process or self.process.state() != QProcess.ProcessState.Running:
            return
        self.process.write((json.dumps(command) + "\n").encode())

    def _package(self):
        outs = self._missing_out + list(self.out_panel.checked_ids)
        return sorted(outs), sorted(self.incoming_ids)

    def _edited(self, *_):
        if self._restoring:
            return
        self._debounce.stop()
        self._refresh_out_selection()
        self._valid = False
        self._current_result = None
        self._validation_id = None
        self.evaluate_button.setEnabled(False)
        self.save_button.setEnabled(False)
        outs, ins = self._package()
        counts = f"OUT {len(outs)} / IN {len(ins)}"
        mismatch = len(outs) != len(ins)
        message = (
            counts + " — select the same number of OUT and IN players."
            if mismatch
            else counts + " — validating the final simultaneous squad…"
        )
        self.selection_message.setText(message)
        self.status.setText(message)
        self.squad.setPlainText(
            message + "\nBank and final-squad preview pending a complete, valid package."
        )
        self._render_comparison()
        if self.context_id and not self._busy and not mismatch:
            self._debounce.start()

    def _refresh_out_selection(self):
        self.out_panel.counter.setText(f"OUT selected: {len(self._package()[0])}/5")
        self.in_panel.set_checked(self.incoming_ids)

    def _selection_changed(self, *_):
        if self._restoring:
            return
        self.incoming_ids = sorted(self.in_panel.checked_ids)
        self._edited()

    def _selection_limit(self, side):
        message = f"Choose at most 5 {side} players. Deselect a player before adding another."
        self.selection_message.setText(message)
        self.status.setText(message)

    def _validate(self):
        if not self.context_id or self._busy:
            return
        outs, ins = self._package()
        self._validation_id = str(uuid4())
        self._send(
            {
                "id": self._validation_id,
                "command": "validate",
                "context_id": self.context_id,
                "transfers_out": outs,
                "transfers_in": ins,
            }
        )

    def handle_message(self, message):
        kind = message.get("type")
        if kind == "ready":
            self._timeout.stop()
            self.context_id = message["context_id"]
            self.input_sha256 = message["input_sha256"]
            self.players = {p["player_id"]: p for p in message["players"]}
            self._restoring = True
            self.out_panel.set_players([self.players[pid] for pid in message["owned_ids"]])
            self.in_panel.set_players([p for p in self.players.values() if not p["owned"]])
            self.incoming_ids = []
            self._missing_out = []
            self._restoring = False
            self._set_busy(False)
            self.status.setText(
                f"Verified context · FT {message['free_transfers']} · bank £{message['bank'] / 10:.1f}m"
            )
            self._edited()
            return
        if kind == "progress":
            if message.get("id") == self._evaluation_id:
                self.status.setText(message["message"])
            return
        if kind == "validation":
            if (
                message.get("id") != self._validation_id
                or message.get("context_id") != self.context_id
            ):
                return
            self._valid = bool(message["valid"])
            self._set_busy(False)
            if self._valid:
                summary = message["summary"]
                lines = [
                    f"K{summary['k']} · FT {summary['initial_ft']} · hit {summary['hit_points']} pts",
                    f"Bank £{summary['bank_after'] / 10:.1f}m · next-GW FT {summary['ft_after']}",
                ]
                lines += [self._player_label(pid) for pid in summary["final_squad"]]
                self.squad.setPlainText("\n".join(lines))
                self.status.setText("Valid final simultaneous squad. Ready to evaluate.")
                self.selection_message.setText(
                    f"OUT {summary['k']} / IN {summary['k']} — "
                    + ("HOLD selected." if summary["k"] == 0 else "Final package is valid.")
                )
                self.progress.setValue(1)
            else:
                self.squad.setPlainText("Final squad invalid: " + str(message.get("error", "")))
                self.status.setText(str(message.get("error") or "Invalid final squad."))
            return
        if kind == "result":
            if message.get("id") != self._evaluation_id:
                return
            if (
                message.get("context_id") != self.context_id
                or message.get("input_sha256") != self.input_sha256
            ):
                self.cancel("Result context mismatch; reload context.")
                return
            try:
                self.store._result(message, self.context_id, self.input_sha256, *self._package())
            except ValueError as exc:
                self._timeout.stop()
                self._current_result = None
                self._baseline_result = None
                self._set_busy(False)
                self.status.setText(str(exc) + " Re-evaluate these selections.")
                self._render_comparison(status="invalid")
                return
            self._timeout.stop()
            self._current_result = message
            self._baseline_result = message
            self._set_busy(False)
            self.progress.setValue(1)
            self.status.setText(
                "Evaluated"
                + (" · reused verified duplicate result" if message.get("cached") else "")
                + ". Manual result does not change production recommendations."
            )
            if self._scenario_id:
                self.save_scenario()
            self._render_comparison()
            return
        if kind == "error":
            if message.get("id") not in ("", self._evaluation_id, self._validation_id):
                return
            if self.context_id is None:
                self.cancel(
                    "Worker initialization failed: " + str(message.get("message", "Worker error"))
                )
                return
            self._timeout.stop()
            self._valid = False
            self._set_busy(False)
            self.status.setText("Failed: " + message.get("message", "Worker error"))
            self._render_comparison(status="failed")

    def _player_label(self, pid):
        p = self.players.get(pid)
        return f"{p['name']} · {p['position']}" if p else str(pid)

    def reset_hold(self):
        self.out_panel.set_checked([])
        self.incoming_ids = []
        self._missing_out = []
        self._scenario_id = None
        self._edited()

    def evaluate(self):
        self._watch_context()
        if not self._valid or not self.context_id or self._busy:
            return
        outs, ins = self._package()
        self._evaluation_id = str(uuid4())
        self._current_result = None
        self._set_busy(True)
        self.status.setText(
            "Pending — evaluating independent HOLD / production and this manual scenario…"
        )
        self._render_comparison(status="pending")
        self._timeout.start(185000)
        self._send(
            {
                "id": self._evaluation_id,
                "command": "evaluate",
                "context_id": self.context_id,
                "transfers_out": outs,
                "transfers_in": ins,
            }
        )

    def _refresh_saved(self):
        try:
            rows = self.store.load()
        except ValueError as exc:
            self.status.setText(str(exc))
            rows = []
        selected = self.saved.currentData()
        self.saved.clear()
        for row in rows:
            stale = row["context_id"] != self.context_id or row["input_sha256"] != self.input_sha256
            self.saved.addItem(
                row["name"] + (" [stale]" if stale else " [" + row.get("status", "pending") + "]"),
                row["id"],
            )
        index = self.saved.findData(selected)
        if index >= 0:
            self.saved.setCurrentIndex(index)
        return rows

    def save_scenario(self):
        if not self._valid or not self.context_id:
            return
        try:
            outs, ins = self._package()
            row = self.store.save(
                self.name.text(),
                outs,
                ins,
                self.context_id,
                self.input_sha256,
                self._current_result,
                self._scenario_id,
            )
            self._scenario_id = row["id"]
            self._refresh_saved()
            self.saved.setCurrentIndex(self.saved.findData(row["id"]))
            self._render_comparison()
        except (ValueError, OSError) as exc:
            self.status.setText(str(exc))

    def load_saved(self):
        try:
            row = next((r for r in self.store.load() if r["id"] == self.saved.currentData()), None)
            if row is None:
                return
            if not self.context_id:
                self.status.setText("Load current context before reconstructing a saved scenario.")
                return
            self._restoring = True
            self._scenario_id = row["id"]
            self.name.setText(row["name"])
            out = set(row["transfers_out"])
            owned = {p["player_id"] for p in self.out_panel.source.records}
            self.out_panel.set_checked(out & owned)
            self._missing_out = sorted(out - owned)
            self.incoming_ids = list(row["transfers_in"])
            self._restoring = False
            self._edited()
            if row.get("result_error"):
                self.status.setText(row["result_error"])
            elif row["context_id"] != self.context_id or row["input_sha256"] != self.input_sha256:
                self.status.setText("Saved result is stale. Re-evaluate these selections.")
        except (ValueError, OSError) as exc:
            self._restoring = False
            self.status.setText(str(exc))

    def rename_saved(self):
        try:
            self.store.rename(self.saved.currentData(), self.name.text())
            self._refresh_saved()
            self._render_comparison()
        except (ValueError, OSError) as exc:
            self.status.setText(str(exc))

    def delete_saved(self):
        try:
            self.store.delete(self.saved.currentData())
            self._scenario_id = None
            self._refresh_saved()
            self._render_comparison()
        except (ValueError, OSError) as exc:
            self.status.setText(str(exc))

    def _render_comparison(self, status="pending"):
        columns = []
        result = self._current_result
        baseline = self._baseline_result
        for payload in (result, baseline):
            if payload is None:
                continue
            try:
                scenario = payload.get("scenario", {})
                package = (
                    self._package()
                    if payload is result
                    else (scenario.get("transfers_out"), scenario.get("transfers_in"))
                )
                self.store._result(
                    payload,
                    self.context_id,
                    self.input_sha256,
                    *package,
                )
            except (ValueError, AttributeError) as exc:
                if payload is result:
                    result = self._current_result = None
                if payload is baseline:
                    baseline = self._baseline_result = None
                status = "invalid"
                self.status.setText(str(exc) + " Re-evaluate these selections.")
        if (
            baseline
            and self.context_id
            and baseline.get("context_id") == self.context_id
            and baseline.get("input_sha256") == self.input_sha256
        ):
            columns = [
                ("HOLD now", "evaluated", baseline["hold"]),
                ("Production V3", "evaluated", baseline["production"]),
            ]
        if (
            result
            and self.context_id
            and result.get("context_id") == self.context_id
            and result.get("input_sha256") == self.input_sha256
        ):
            columns.append(("Current manual", "evaluated", result["scenario"]))
        else:
            outs, ins = self._package()
            columns.append(("Current manual", status, {"transfers_out": outs, "transfers_in": ins}))
        for row in self._refresh_saved():
            compatible = (
                self.context_id
                and row["context_id"] == self.context_id
                and row["input_sha256"] == self.input_sha256
            )
            payload = row.get("result")
            scenario = (
                payload.get("scenario", {})
                if compatible and payload
                else {"transfers_out": row["transfers_out"], "transfers_in": row["transfers_in"]}
            )
            columns.append(
                (
                    row["name"],
                    "evaluated"
                    if compatible and payload
                    else row.get("status", "pending")
                    if compatible
                    else "stale",
                    scenario,
                )
            )
        metrics = [
            "Status",
            "OUT",
            "IN",
            "K",
            "Initial FT",
            "Hit points",
            "Bank after",
            "FT after current GW",
            "3-GW objective",
            "Δ HOLD",
            "Δ production V3",
            "Starting XI",
            "Captain",
            "Vice-captain",
            "Future path",
        ]
        self.comparison.clear()
        self.comparison.setRowCount(len(metrics))
        self.comparison.setColumnCount(len(columns))
        self.comparison.setVerticalHeaderLabels(metrics)
        self.comparison.setHorizontalHeaderLabels([c[0] for c in columns])
        for col, (_, state, scenario) in enumerate(columns):

            def names(ids):
                return "\n".join(self._player_label(pid) for pid in ids) or "HOLD"

            evaluated = state == "evaluated"
            values = [
                state,
                names(scenario.get("transfers_out", [])),
                names(scenario.get("transfers_in", [])),
            ]
            values += [
                str(scenario.get(k, "—")) if evaluated else "—"
                for k in ("k", "initial_ft", "hit_points")
            ]
            values += [
                f"£{scenario['bank_after'] / 10:.1f}m" if evaluated else "—",
                str(scenario.get("ft_after", "—")) if evaluated else "—",
            ]
            values += [
                f"{scenario[k]:+.5f}" if evaluated and k in scenario else "—"
                for k in ("objective", "delta_hold", "delta_production")
            ]
            values += [
                names(scenario.get("starting_xi", [])) if evaluated else "—",
                self._player_label(scenario.get("captain", "—")) if evaluated else "—",
                self._player_label(scenario.get("vice_captain", "—")) if evaluated else "—",
            ]
            future = []
            for step in scenario.get("path", []) if evaluated else []:
                action = (
                    "HOLD"
                    if not step["transfers_out"]
                    else "OUT: "
                    + names(step["transfers_out"]).replace("\n", ", ")
                    + "\nIN: "
                    + names(step["transfers_in"]).replace("\n", ", ")
                )
                future.append(f"GW{step['gw']}: {action}")
            values.append("\n".join(future) or "—")
            for r, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setToolTip(str(value))
                self.comparison.setItem(r, col, item)
            self.comparison.setColumnWidth(col, 300)
        self.comparison.resizeRowsToContents()
        # Put the comparable objectives above the long, scrollable player/lineup detail rows.
        order = [0, 8, 9, 10, 1, 2, 3, 4, 5, 6, 7, 11, 12, 13, 14]
        items = [
            [self.comparison.takeItem(row, col) for col in range(len(columns))]
            for row in range(len(metrics))
        ]
        self.comparison.setVerticalHeaderLabels([metrics[row] for row in order])
        for new_row, old_row in enumerate(order):
            for col, item in enumerate(items[old_row]):
                self.comparison.setItem(new_row, col, item)
        self.comparison.resizeRowsToContents()

    def _process_error(self, process, generation, error):
        if generation == self._generation:
            self.cancel("Worker failure: " + process.errorString())

    def _finished(self, process, generation, code):
        if generation != self._generation or self._closing:
            return
        self._read_stdout(process, generation)
        if generation != self._generation or self._closing:
            return
        self._read_stderr(process, generation)
        self.cancel(
            "Worker stopped"
            + (
                f" (exit {code}): " + self._stderr[-1000:]
                if code
                else ". Reload context to continue."
            )
        )

    def cancel(self, message="Cancelled. Reload current context to continue."):
        if isinstance(message, bool):
            message = "Cancelled. Reload current context to continue."
        self.shutdown()
        self._closing = False
        self._current_result = None
        self._valid = False
        self._set_busy(False)
        self.status.setText(str(message))
        self._render_comparison(status="cancelled")

    def shutdown(self):
        self._closing = True
        self._generation += 1
        self._timeout.stop()
        self._debounce.stop()
        process = self.process
        self.process = None
        if process and process.state() != QProcess.ProcessState.NotRunning:
            if not self._busy:
                process.write(b'{"command":"quit"}\n')
                process.waitForFinished(150)
            if process.state() != QProcess.ProcessState.NotRunning:
                process.kill()
                process.waitForFinished(500)
        if process:
            process.deleteLater()
        if self._request_path:
            try:
                self._request_path.unlink(missing_ok=True)
            except OSError:
                pass
        self._request_path = None
        self._fingerprint = None
        self.context_id = None
        self.input_sha256 = None
        self._valid = False
        self._baseline_result = None
