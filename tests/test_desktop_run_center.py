from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

import desktop_app.main_window as main_window_module
from desktop_app.decision_orchestration import decision_bundle_for_state
from desktop_app.main_window import MainWindow
from desktop_app.run_center import discover_analysis_runs, discover_projection_runs, write_analysis_run
from desktop_app.state import DesktopSquadState, default_chip_state


ROOT = Path(__file__).resolve().parents[1]
AT = datetime(2026, 9, 17, 8, 15, tzinfo=timezone.utc)


def _state() -> DesktopSquadState:
    return DesktopSquadState(
        season="2026/27", gameweek=5, bank_tenths=10, free_transfers=1,
        player_ids=["owned"], chips_used=default_chip_state(),
    )


def _full_state() -> DesktopSquadState:
    positions = ["GK"] * 2 + ["DEF"] * 5 + ["MID"] * 5 + ["FWD"] * 3
    player_ids = [f"p{index}" for index in range(15)]
    return DesktopSquadState(
        season="2026/27", gameweek=5, bank_tenths=10, free_transfers=1,
        player_ids=player_ids, starting_player_ids=["p0", "p2", "p3", "p4", "p7", "p8", "p9", "p10", "p11", "p12", "p14"],
        bench_player_ids=["p1", "p5", "p6", "p13"], chips_used=default_chip_state(),
        selling_prices_tenths={player_id: 50 for player_id in player_ids},
        purchase_prices_tenths={player_id: 50 for player_id in player_ids},
    )


def _projection_run(root: Path, run_id: str, timestamp: datetime, *, complete: bool = True,
                    simulation_count: int = 25_000) -> Path:
    run = root / "data" / "processed" / "predictions" / "2026-27" / run_id
    run.mkdir(parents=True)
    bundle = {
        "season": "2026/27", "current_gameweek": 5,
        "prediction_timestamp": timestamp.isoformat(),
        "pipeline": {
            "simulations_per_fixture": simulation_count,
            "base_seed": 42,
            "simulation_mode": "PRODUCTION",
            "simulator_version": "fixture_simulator_v22_lineup_coherent_logit",
        },
    }
    manifest = {
        "season": "2026/27", "target_gameweek": 5,
        "prediction_timestamp": timestamp.isoformat(),
        "simulation": dict(bundle["pipeline"]),
        "market_shadow": {
            "status": "AVAILABLE", "mapped_fixture_count": 10,
            "current_gameweek_fixture_count": 10, "production_influence": False,
        },
    }
    (run / "shadow_projection_bundle.json").write_text(json.dumps(bundle), encoding="utf-8")
    (run / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (run / "prediction_context.json").write_text(json.dumps({"target_season": "2026/27", "target_gameweek": 5}), encoding="utf-8")
    if complete:
        for name in ("current_players.json", "fixture_horizon.json", "minutes.json", "player_projections.json"):
            (run / name).write_text("[]", encoding="utf-8")
    return run / "shadow_projection_bundle.json"


def test_projection_discovery_excludes_incomplete_or_broken_runs_and_sorts_latest(tmp_path):
    older = _projection_run(tmp_path, "older", AT)
    newer = _projection_run(tmp_path, "newer", AT.replace(hour=9), simulation_count=50_000)
    _projection_run(tmp_path, "incomplete", AT.replace(hour=10), complete=False)
    broken = _projection_run(tmp_path, "broken", AT.replace(hour=11))
    manifest = json.loads((broken.parent / "run_manifest.json").read_text(encoding="utf-8"))
    manifest["simulation"]["simulations_per_fixture"] = 10_000
    (broken.parent / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    runs = discover_projection_runs(tmp_path, season="2026/27", gameweek=5)

    assert [run.run_id for run in runs] == ["newer", "older"]
    assert runs[0].bundle_path == newer
    assert "GW5" in runs[0].label and "50k" in runs[0].label
    assert "coverage 10/10" in runs[0].detail


def test_selected_bundle_is_used_instead_of_the_latest_run(tmp_path):
    older = _projection_run(tmp_path, "older", AT)
    _projection_run(tmp_path, "newer", AT.replace(hour=9))

    assert decision_bundle_for_state(tmp_path, _state(), older) == older


def test_analysis_history_discovers_complete_and_partial_records_without_large_result_copies(tmp_path):
    _projection_run(tmp_path, "run-a", AT)
    decision = tmp_path / "data" / "processed" / "desktop_decisions" / "2026-27" / "decision.json"
    chip = tmp_path / "data" / "processed" / "desktop_chips" / "2026-27" / "chip.json"
    decision.parent.mkdir(parents=True); chip.parent.mkdir(parents=True)
    decision.write_text(json.dumps({"recommendation": {}, "external_mutations": []}), encoding="utf-8")
    chip.write_text(json.dumps({"recommendation": {}, "external_mutations": []}), encoding="utf-8")
    complete = write_analysis_run(
        tmp_path, analysis_run_id="complete", projection_run_id="run-a", state=_state(), status="COMPLETE",
        decision_report=decision, chip_report=chip, recommended_xi_available=True, captaincy_available=True,
    )
    partial = write_analysis_run(
        tmp_path, analysis_run_id="partial", projection_run_id="run-a", state=_state(), status="PARTIAL",
        decision_report=decision, chip_report=None, recommended_xi_available=True, captaincy_available=True,
    )

    records = discover_analysis_runs(tmp_path, season="2026/27", gameweek=5)

    assert {record.analysis_run_id for record in records} == {"complete", "partial"}
    assert all(record.projection_run_id == "run-a" for record in records)
    stored = json.loads(complete.read_text(encoding="utf-8"))
    assert "recommendation" not in stored and stored["decision_report"].replace("\\", "/").startswith("data/")
    assert partial.exists()


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def test_run_center_selects_latest_by_default_and_allows_an_older_run(qapp, tmp_path, monkeypatch):
    older_bundle = _projection_run(tmp_path, "older", AT)
    newer_bundle = _projection_run(tmp_path, "newer", AT.replace(hour=9))
    runs = discover_projection_runs(tmp_path, season="2026/27", gameweek=5)
    window = MainWindow(ROOT)
    try:
        monkeypatch.setattr(main_window_module, "discover_projection_runs", lambda *_args, **_kwargs: runs)
        monkeypatch.setattr(main_window_module, "discover_analysis_runs", lambda *_args, **_kwargs: ())
        window._refresh_run_center()
        assert window.selected_projection_bundle == newer_bundle

        window.projection_run_box.setCurrentIndex(window.projection_run_box.findData("older"))
        assert window.selected_projection_bundle == older_bundle
        calls = []
        monkeypatch.setattr(main_window_module, "decision_bundle_for_state", lambda _root, _state, selected=None: calls.append(selected) or selected)
        assert window._selected_bundle_for_state(_state()) == older_bundle
        assert calls == [older_bundle]
    finally:
        window.close()


def test_run_center_refreshes_and_selects_a_new_projection_run(qapp, tmp_path, monkeypatch):
    _projection_run(tmp_path, "older", AT)
    window = MainWindow(ROOT)
    try:
        monkeypatch.setattr(main_window_module, "discover_projection_runs", discover_projection_runs)
        monkeypatch.setattr(main_window_module, "discover_analysis_runs", discover_analysis_runs)
        monkeypatch.setattr(window, "_state_from_ui", _state)
        monkeypatch.setattr(window, "root", tmp_path)
        window._refresh_run_center()
        assert window.selected_projection_bundle is not None
        newer = _projection_run(tmp_path, "newer", AT.replace(hour=9), simulation_count=50_000)
        window._refresh_run_center(selected_projection_run_id="newer")
        assert window.selected_projection_bundle == newer
        assert "50k" in window.projection_run_box.currentText()
    finally:
        window.close()


def test_analysis_selector_refuses_records_from_another_projection_run(qapp, tmp_path, monkeypatch):
    first = _projection_run(tmp_path, "run-a", AT)
    second = _projection_run(tmp_path, "run-b", AT.replace(hour=9))
    decision = tmp_path / "data" / "processed" / "desktop_decisions" / "2026-27" / "decision.json"
    decision.parent.mkdir(parents=True)
    decision.write_text(json.dumps({"recommendation": {}, "external_mutations": []}), encoding="utf-8")
    write_analysis_run(
        tmp_path, analysis_run_id="for-run-a", projection_run_id="run-a", state=_state(), status="PARTIAL",
        decision_report=decision, chip_report=None, recommended_xi_available=True, captaincy_available=True,
    )
    window = MainWindow(ROOT)
    try:
        monkeypatch.setattr(window, "_state_from_ui", _state)
        monkeypatch.setattr(window, "root", tmp_path)
        window._refresh_run_center(selected_projection_run_id="run-b")
        assert window.selected_projection_bundle == second
        assert window.analysis_run_box.count() == 0
        assert window.load_analysis_button.isEnabled() is False
        assert first != second
    finally:
        window.close()


def test_startup_discovery_and_history_loading_have_no_provider_or_account_mutations(qapp, monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(main_window_module, "discover_projection_runs", lambda *_args, **_kwargs: calls.append("projection") or ())
    monkeypatch.setattr(main_window_module, "discover_analysis_runs", lambda *_args, **_kwargs: calls.append("analysis") or ())
    window = MainWindow(ROOT)
    try:
        assert calls == ["projection", "analysis"]
        assert window.engine_process is None and window.decision_process is None and window.chip_process is None
        assert window.account_process is None
        window.load_selected_analysis()
        assert calls == ["projection", "analysis"]
    finally:
        window.close()


@pytest.mark.parametrize(("status", "with_chip"), (("PARTIAL", False), ("COMPLETE", True)))
def test_load_saved_analysis_restores_complete_and_partial_outputs_without_starting_pipeline(qapp, tmp_path, monkeypatch, status, with_chip):
    bundle = _projection_run(tmp_path, "run-a", AT)
    state = _full_state()
    positions = ["GK"] * 2 + ["DEF"] * 5 + ["MID"] * 5 + ["FWD"] * 3
    current_players = [
        {"player_id": f"p{index}", "display_name": f"Player {index}", "position": position,
         "team_id": f"club-{index // 3}", "current_price": 50, "provider_payload": {"can_select": True}}
        for index, position in enumerate(positions)
    ]
    bundle.parent.joinpath("current_players.json").write_text(json.dumps(current_players), encoding="utf-8")
    report_path = tmp_path / "data" / "processed" / "desktop_decisions" / "2026-27" / "decision.json"
    report_path.parent.mkdir(parents=True)
    report_path.write_text(json.dumps({
            "recommendation": {
                "roll_free_transfer": True, "transfers_out": [], "transfers_in": [],
                "starting_xi": state.starting_player_ids, "bench_order": state.bench_player_ids,
                "captain": "p11", "vice_captain": "p12",
                "resulting_bank": 0, "free_transfers_after": 2,
                "transfer_impacts": {"impact_1gw": 0.0, "impact_3gw": 0.0, "impact_6gw": 0.0},
            },
            "strategy_previews": {
                "strategic": {
                    "transfers_out": [], "transfers_in": [], "resulting_bank": 0,
                    "free_transfers_after": 2, "starting_xi": state.starting_player_ids,
                    "bench_order": state.bench_player_ids, "captain": "p11", "vice_captain": "p12",
                },
                "short_term": {
                    "transfers_out": [], "transfers_in": [], "resulting_bank": 0,
                    "free_transfers_after": 2, "starting_xi": state.starting_player_ids,
                    "bench_order": state.bench_player_ids, "captain": "p11", "vice_captain": "p12",
                },
            },
            "strategic_action": {
                "action": "ROLL_FT", "transfers_out": [], "transfers_in": [],
                "free_transfers_before": 1, "free_transfers_after": 2,
                "resulting_bank": 0, "utility": 3.0,
            },
            "external_mutations": [], "player_metadata": {},
    }), encoding="utf-8")
    chip_path = None
    if with_chip:
        chip_path = tmp_path / "data" / "processed" / "desktop_chips" / "2026-27" / "chip.json"
        chip_path.parent.mkdir(parents=True)
        chip_path.write_text(json.dumps({"recommendation": {}, "external_mutations": []}), encoding="utf-8")
    manifest = write_analysis_run(
        tmp_path, analysis_run_id=status.lower(), projection_run_id="run-a", state=state, status=status,
        decision_report=report_path, chip_report=chip_path, recommended_xi_available=True, captaincy_available=True,
    )
    saved = discover_analysis_runs(tmp_path, season="2026/27", gameweek=5)[0]
    window = MainWindow(ROOT)
    original_state = window.state_path.read_bytes() if window.state_path.exists() else None
    try:
        window.selected_projection_bundle = bundle
        window.selected_analysis_run = saved
        monkeypatch.setattr(window, "_selected_bundle_for_state", lambda _state: bundle)
        assert saved.legacy_unverified
        window.load_selected_analysis()
        assert "LEGACY / UNVERIFIED" in window.engine_log.toPlainText()
        assert "Saved analysis could not be loaded safely" in window.statusBar().currentMessage()
        assert window.latest_decision_report is None
        assert window.engine_process is None and window.decision_process is None and window.chip_process is None
        assert (window.state_path.read_bytes() if window.state_path.exists() else None) == original_state
        assert manifest.exists()
    finally:
        window.close()
