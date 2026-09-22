from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QProcess as NativeQProcess

from desktop_app.data_access import PlayerRecord
from desktop_app.fpl_account import (
    AccountSyncState,
    FPLAccountError,
    account_state_issues,
    cdp_debug_session_available,
    snapshot_from_my_team,
)
from desktop_app.main_window import MainWindow
from desktop_app.state import DesktopSquadState, load_state, save_state


ROOT = Path(__file__).resolve().parents[1]


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _players():
    positions = ["GK"] * 2 + ["DEF"] * 5 + ["MID"] * 5 + ["FWD"] * 3
    return {
        f"player_{index}": PlayerRecord(
            player_id=f"player_{index}", display_name="Bahoya" if index == 14 else f"Player {index}",
            position=position, team_id=f"team_{index // 2}", current_price=50,
            provider_id=str(index + 1 if index < 14 else 648),
        )
        for index, position in enumerate(positions)
    }


def _payload():
    return {
        "picks": [
            {"element": index + 1 if index < 14 else 648, "position": index + 1,
             "selling_price": 50, "purchase_price": 49,
             "is_captain": index == 0, "is_vice_captain": index == 1}
            for index in range(15)
        ],
        "chips": [],
        "transfers": {"limit": 3, "made": 0, "bank": 1, "status": "cost", "cost": 4},
    }


def test_cdp_probe_closes_successful_connection_and_handles_unavailable():
    class Connection:
        closed = False
        def close(self):
            self.closed = True

    connection = Connection()
    assert cdp_debug_session_available(connector=lambda address, timeout: connection)
    assert connection.closed

    def unavailable(address, timeout):
        raise ConnectionRefusedError("unavailable")
    assert not cdp_debug_session_available(connector=unavailable)


def test_partial_price_state_names_exact_missing_player_without_inventing_price():
    players = _players()
    ids = list(players)
    state = DesktopSquadState(
        player_ids=ids, selling_prices_tenths={player_id: 50 for player_id in ids[:-1]},
        purchase_prices_tenths={player_id: 49 for player_id in ids[:-1]},
    )
    issues = account_state_issues(state, players)
    assert "missing selling price: Bahoya (FPL 648)" in issues
    assert ids[-1] not in state.selling_prices_tenths


def test_snapshot_requires_every_price_and_preserves_official_picks():
    players = _players()
    snapshot = snapshot_from_my_team(_payload(), entry_id=123, players_by_id=players)
    assert len(snapshot.player_ids) == len(snapshot.selling_prices_tenths) == 15
    assert snapshot.starting_player_ids == snapshot.player_ids[:11]
    assert snapshot.bench_player_ids == snapshot.player_ids[11:]

    incomplete = _payload()
    del incomplete["picks"][-1]["selling_price"]
    with pytest.raises(FPLAccountError, match=r"Bahoya \(648\).*selling_price"):
        snapshot_from_my_team(incomplete, entry_id=123, players_by_id=players)


def test_login_required_preflight_and_managed_edge_launch(tmp_path, monkeypatch):
    _app()
    window = MainWindow(ROOT)
    launched = []
    try:
        ids = list(window.players)[:15]
        partial = DesktopSquadState(
            fpl_entry_id=123, player_ids=ids,
            selling_prices_tenths={player_id: 50 for player_id in ids[:-1]},
            purchase_prices_tenths={player_id: 49 for player_id in ids[:-1]},
        )
        window._refresh_account_status(partial)
        assert window.account_sync_state is AccountSyncState.ERROR
        assert "CONNECTED" not in window.account_status_label.text()

        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
        monkeypatch.setattr(window, "_edge_executable", lambda: Path("C:/Program Files/Microsoft/Edge/Application/msedge.exe"))
        monkeypatch.setattr("desktop_app.main_window.subprocess.Popen", lambda arguments, **kwargs: launched.append((arguments, kwargs)))
        window._cdp_probe = lambda: False
        window.sync_fpl_quick_button.click()
        arguments = launched[0][0]
        assert "--remote-debugging-port=9222" in arguments
        assert any(argument.startswith("--user-data-dir=") and "manual_edge_profile" in argument for argument in arguments)
        assert arguments[-1] == "https://fantasy.premierleague.com/my-team"
        assert window.account_sync_state is AccountSyncState.LOGIN_REQUIRED
        assert window.sync_fpl_quick_button.text() == "Retry sync"

        window._login_window_launched = False
        window.start_account_sync()
        assert window.account_sync_state is AccountSyncState.LOGIN_REQUIRED
        assert window.account_process is None
        assert window.sync_fpl_quick_button.text() == "Open FPL login"
    finally:
        window.close()


def test_successful_mocked_sync_requires_complete_account_state(tmp_path):
    _app()
    window = MainWindow(ROOT)
    try:
        baseline = load_state(ROOT / "data" / "user" / "squad_state.json")
        player_ids = list(baseline.player_ids)
        complete = replace(
            baseline,
            fpl_entry_id=7940073,
            selling_prices_tenths={player_id: 50 for player_id in player_ids},
            purchase_prices_tenths={player_id: 49 for player_id in player_ids},
            starting_player_ids=player_ids[:11],
            bench_player_ids=player_ids[11:],
        )
        state_path = tmp_path / "squad_state.json"
        save_state(state_path, complete)
        window.state_path = state_path

        window._account_sync_finished(0, None)

        assert window.account_sync_state is AccountSyncState.CONNECTED
        assert "CONNECTED" in window.account_status_label.text()
        assert "prices 15/15" in window.account_status_label.text()
        assert window._current_state is not None
        assert len(window._current_state.player_ids) == 15
        assert len(window._current_state.selling_prices_tenths) == 15
        assert len(window._current_state.starting_player_ids) == 11
        assert len(window._current_state.bench_player_ids) == 4
    finally:
        window.close()


def test_retry_after_login_starts_read_only_sync_process(monkeypatch):
    class Signal:
        def connect(self, callback):
            self.callback = callback

    class FakeProcess:
        ProcessState = NativeQProcess.ProcessState
        instances = []

        def __init__(self, parent):
            self._state = self.ProcessState.NotRunning
            self.readyReadStandardOutput = Signal()
            self.readyReadStandardError = Signal()
            self.finished = Signal()
            self.errorOccurred = Signal()
            self.started = None
            self.__class__.instances.append(self)

        def state(self):
            return self._state

        def setProcessEnvironment(self, environment):
            self.environment = environment

        def setWorkingDirectory(self, directory):
            self.directory = directory

        def start(self, program, arguments):
            self.started = (program, arguments)
            self._state = self.ProcessState.Running

    _app()
    window = MainWindow(ROOT)
    try:
        monkeypatch.setattr("desktop_app.main_window.QProcess", FakeProcess)
        window._cdp_probe = lambda: True
        window._login_window_launched = True
        window.start_account_sync()

        assert window.account_sync_state is AccountSyncState.SYNCING
        assert len(FakeProcess.instances) == 1
        program, arguments = FakeProcess.instances[0].started
        assert str(program).endswith("python.exe")
        assert arguments[-1].endswith("scripts\\desktop003b3_cdp_sync.py")
        assert "POST" not in window.engine_log.toPlainText()
        assert "Read-only account synchronization" in window.engine_log.toPlainText()
    finally:
        window.close()
