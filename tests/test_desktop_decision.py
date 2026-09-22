from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from desktop_app.decision_orchestration import (
    DecisionRunState, decision_arguments, decision_bundle_for_state,
    format_decision_summary, load_decision_report, validate_decision_bundle,
    write_decision_request,
)
from desktop_app.decision_runner import DesktopDecisionError, run_desktop_decision, shadow_input
import desktop_app.main_window as main_window_module
from desktop_app.orchestration import DesktopEngineError
from desktop_app.main_window import MainWindow
from desktop_app.fixture_display import FixtureDisplayRepository
from desktop_app.fixture_display import FixtureBadgeData
from desktop_app.recommended_lineup import build_recommended_lineup
from desktop_app.recommended_lineup import RecommendedLineup
from desktop_app.squad_pitch import SquadPitchWidget
from desktop_app.transfer_plans import horizon_transfer_plans
from desktop_app.data_access import PlayerRecord
from desktop_app.state import DesktopSquadState, default_chip_state
from fpl_engine.models.projections import GameweekPlayerProjection, PlayerProjection


AT = datetime(2026, 9, 10, 10, tzinfo=timezone.utc)
ROOT = Path(__file__).resolve().parents[1]


def _projection(player_id: str, ev: float) -> PlayerProjection:
    gameweeks = tuple(
        GameweekPlayerProjection("2026/27", 1, player_id, 5 + offset, AT, (f"fix_{offset}",), 1,
            ev, ev, 1.0, {0.5: ev}, 0.25, 0.5, 0.5, 0.25, 0.1, 0.05, 80.0, {int(ev): 1.0}, 1.0)
        for offset in range(6)
    )
    return PlayerProjection(player_id, "2026/27", 1, AT, 5, gameweeks, ev, ev * 3, ev * 6,
        ev, ev * 3, ev * 6, 80.0, 240.0, 480.0, 0.2, 0.8, 1.0,
        ("model",), ("dataset",), ("features",), ("simulator",), (42,), (1,))


def _jsonable(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _bundle_and_state(tmp_path, *, simulation_count=10_000):
    positions = ["GK"] * 2 + ["DEF"] * 5 + ["MID"] * 5 + ["FWD"] * 3
    players = [
        {"player_id": f"p{index}", "position": position, "club_id": f"club_{index // 3}",
         "purchase_price": 50, "current_price": 50, "selling_price": 50}
        for index, position in enumerate(positions)
    ]
    candidates = [
        {"player_id": f"candidate{suffix}", "position": "FWD", "club_id": f"candidate_club{suffix}",
         "purchase_price": 50, "current_price": 50, "selling_price": 50}
        for suffix in ("", "_2", "_3")
    ]
    projections = [_projection(row["player_id"], 1.0 if row["player_id"] == "p14" else 5.0) for row in players]
    projections.extend(_projection(row["player_id"], value) for row, value in zip(candidates, (12.0, 11.0, 10.0)))
    run = tmp_path / "data" / "processed" / "predictions" / "2026-27" / "run"
    run.mkdir(parents=True)
    bundle = {
        "prediction_timestamp": AT.isoformat(), "season": "2026/27", "current_gameweek": 5,
        "candidate_pool": players + candidates, "projections": [_jsonable(asdict(row)) for row in projections],
        "pipeline": {
            "simulations_per_fixture": simulation_count,
            "seed_strategy": "fixture-scoped",
            "simulation_mode": "PRODUCTION",
            "simulator_version": "fixture_simulator_v22",
        },
        "data_freshness": [{"source": "official_fpl", "known_at": AT.isoformat(), "raw_snapshot_id": "raw"}],
    }
    (run / "shadow_projection_bundle.json").write_text(json.dumps(bundle), encoding="utf-8")
    (run / "player_projections.json").write_text("[]", encoding="utf-8")
    (run / "run_manifest.json").write_text(json.dumps({
        "season": "2026/27", "target_gameweek": 5,
        "simulation": {
            "simulations_per_fixture": simulation_count,
            "simulation_mode": "PRODUCTION",
            "simulator_version": "fixture_simulator_v22",
        },
    }), encoding="utf-8")
    (run / "prediction_context.json").write_text(json.dumps({"target_season": "2026/27", "target_gameweek": 5}), encoding="utf-8")
    (run / "current_players.json").write_text(json.dumps([
        {"player_id": row["player_id"], "display_name": f"Player {row['player_id']}"}
        for row in players + candidates
    ]), encoding="utf-8")
    state = DesktopSquadState(
        season="2026/27", gameweek=5, bank_tenths=20, free_transfers=1,
        player_ids=[row["player_id"] for row in players], chips_used=default_chip_state(),
        purchase_prices_tenths={row["player_id"]: 50 for row in players},
        selling_prices_tenths={row["player_id"]: 50 for row in players},
    )
    source = tmp_path / "state.json"
    write_decision_request(source, state)
    return state, source, run / "shadow_projection_bundle.json"


def test_decision_bridge_runs_existing_engine_and_preserves_account_state(tmp_path):
    state, source, bundle = _bundle_and_state(tmp_path)
    original = source.read_text(encoding="utf-8")
    output = tmp_path / "reports"
    report_path = run_desktop_decision(
        desktop_state_path=source, prediction_bundle_path=bundle, output_dir=output, project_root=Path(__file__).resolve().parents[1],
    )
    report = load_decision_report(report_path)
    assert source.read_text(encoding="utf-8") == original
    assert report["external_mutations"] == []
    assert report["recommendation"]["transfers_out"] == ["p14"]
    assert report["recommendation"]["transfers_in"] == ["candidate"]
    assert report["feasible_plans"]
    assert all(plan["resulting_bank"] >= 0 for plan in report["feasible_plans"])
    assert all("impact_6gw" in plan for plan in report["feasible_plans"])
    assert set(report["strategy_previews"]) == {"strategic", "short_term", "balanced", "long_term"}
    action = report["strategic_v2"]
    assert action["action"] in {"ROLL_FT", "TRANSFER"}
    assert action["utility"] is not None
    assert report["strategic_action"] == action
    assert report["strategic_v3"]["current_action"]["action"] in {"HOLD", "TRANSFER"}
    assert len(report["strategic_v3"]["path"]) == 3
    assert report["strategic_v3"]["hold_now_counterfactual"]["path"][0]["action"] == "HOLD"
    strategic_preview = report["strategy_previews"]["strategic"]
    assert tuple(strategic_preview["transfers_out"]) == tuple(report["strategic_v3"]["current_action"]["transfers_out"])
    assert tuple(strategic_preview["transfers_in"]) == tuple(report["strategic_v3"]["current_action"]["transfers_in"])
    for preview in report["strategy_previews"].values():
        assert len(preview["starting_xi"]) == 11
        assert len(preview["bench_order"]) == 4
        assert preview["captain"] in preview["starting_xi"]
        assert preview["vice_captain"] in preview["starting_xi"]
        assert preview["captain"] != preview["vice_captain"]
    key_for_title = {
        "Best short-term": "short_term",
        "Best balanced": "balanced",
        "Best long-term": "long_term",
    }
    for display_plan in horizon_transfer_plans(report):
        preview = report["strategy_previews"][key_for_title[display_plan.title]]
        assert tuple(preview["transfers_out"]) == display_plan.plan.transfers_out
        assert tuple(preview["transfers_in"]) == display_plan.plan.transfers_in
    rendered = format_decision_summary(report, state.selling_prices_tenths)
    assert "OUT: Player p14" in rendered
    assert "IN: Player candidate" in rendered
    assert "sell £5.0m" in rendered and "price £5.0m" in rendered


def test_decision_bridge_rejects_incomplete_personal_prices(tmp_path):
    state, source, bundle = _bundle_and_state(tmp_path)
    raw = json.loads(source.read_text(encoding="utf-8"))
    raw["selling_prices_tenths"].pop("p14")
    source.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(DesktopDecisionError, match="selling prices: p14"):
        run_desktop_decision(desktop_state_path=source, prediction_bundle_path=bundle, output_dir=tmp_path / "reports", project_root=Path(__file__).resolve().parents[1])


def test_roll_result_is_rendered_explicitly():
    report = {"recommendation": {"roll_free_transfer": True, "transfers_out": [], "transfers_in": [], "hit_cost": 0}}
    assert "ROLL FREE TRANSFER" in format_decision_summary(report, {})


def test_orchestration_uses_matching_production_bundle_and_child_arguments(tmp_path):
    state, _, bundle = _bundle_and_state(tmp_path)
    assert decision_bundle_for_state(tmp_path, state) == bundle
    args = decision_arguments(request_path=tmp_path / "request.json", prediction_bundle=bundle, output_dir=tmp_path / "output")
    assert args[:2] == ["-m", "desktop_app.decision_runner"]
    assert DecisionRunState.IDLE.value == "IDLE" and DecisionRunState.RUNNING.value == "RUNNING"


@pytest.mark.parametrize("simulation_count", (1, 10_000, 25_000, 50_000))
def test_decision_accepts_supported_canonical_bundle_counts(
    tmp_path,
    simulation_count,
):
    state, _, bundle = _bundle_and_state(
        tmp_path,
        simulation_count=simulation_count,
    )
    assert decision_bundle_for_state(tmp_path, state) == bundle


def test_decision_rejects_manifest_simulation_count_mismatch(tmp_path):
    state, _, bundle = _bundle_and_state(tmp_path, simulation_count=25_000)
    manifest_path = bundle.parent / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["simulation"]["simulations_per_fixture"] = 10_000
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(DesktopEngineError, match="different simulation counts"):
        decision_bundle_for_state(tmp_path, state)


def test_decision_rejects_scratch_bundle_path(tmp_path):
    state, _, bundle = _bundle_and_state(tmp_path)
    scratch_bundle = tmp_path / "scratch" / "run" / bundle.name
    with pytest.raises(DesktopEngineError, match="only canonical production"):
        validate_decision_bundle(
            tmp_path,
            scratch_bundle,
            season=state.season,
            gameweek=state.gameweek,
        )


def test_shadow_input_rejects_mismatched_projection_gameweek(tmp_path):
    _, source, bundle = _bundle_and_state(tmp_path)
    desktop = json.loads(source.read_text(encoding="utf-8"))
    bundle_payload = json.loads(bundle.read_text(encoding="utf-8"))
    bundle_payload["current_gameweek"] = 6
    with pytest.raises(DesktopDecisionError, match="do not match"):
        shadow_input(desktop, bundle_payload)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def test_decision_button_triggers_friendly_missing_artifact_error(qapp, monkeypatch):
    root = Path(__file__).resolve().parents[1]
    monkeypatch.setattr(
        main_window_module,
        "decision_bundle_for_state",
        lambda *_: (_ for _ in ()).throw(DesktopEngineError("No saved production projection run matches the selected season and gameweek.")),
    )
    window = MainWindow(root)
    try:
        window.run_decision.click()
        assert window.decision_run_state is DecisionRunState.ERROR
        assert "No saved production projection run" in window.engine_log.toPlainText()
    finally:
        window.close()


def test_duplicate_decision_run_is_blocked_before_any_second_start(qapp):
    class RunningProcess:
        def state(self):
            from PySide6.QtCore import QProcess
            return QProcess.ProcessState.Running

    root = Path(__file__).resolve().parents[1]
    window = MainWindow(root)
    try:
        window.decision_process = RunningProcess()
        window.start_decision_run()
        assert "already running" in window.statusBar().currentMessage()
    finally:
        window.close()


def test_recommended_xi_uses_engine_output_and_preserves_current_state(qapp):
    positions = ["GK"] * 2 + ["DEF"] * 5 + ["MID"] * 5 + ["FWD"] * 3
    players = {f"p{i}": PlayerRecord(f"p{i}", f"Player {i}", position, f"club_{i // 3}", 50) for i, position in enumerate(positions)}
    players["candidate"] = PlayerRecord("candidate", "Incoming", "FWD", "candidate_club", 50)
    current_starters = ["p0", "p2", "p3", "p4", "p7", "p8", "p9", "p10", "p11", "p12", "p14"]
    state = DesktopSquadState(player_ids=[f"p{i}" for i in range(15)], starting_player_ids=current_starters, bench_player_ids=["p1", "p5", "p6", "p13"])
    original_ids = list(state.player_ids)
    engine_output = {"transfers_out": ["p14"], "transfers_in": ["candidate"], "starting_xi": current_starters[:-1] + ["candidate"], "bench_order": state.bench_player_ids, "captain": "p11", "vice_captain": "p12"}
    preview = build_recommended_lineup(state, players, engine_output)
    assert len(preview.squad_ids) == 15 and len(preview.starting_xi_ids) == 11
    assert len(preview.bench_ids) == 4
    assert preview.captain_id in preview.starting_xi_ids and preview.vice_captain_id in preview.starting_xi_ids
    assert preview.transfers_out[0] not in preview.squad_ids and preview.transfers_in[0] in preview.squad_ids
    assert state.player_ids == original_ids

    class Fixtures:
        def entries_for(self, *_): return []
    pitch = SquadPitchWidget(Fixtures())
    current_xi = list(state.starting_player_ids)
    pitch._players = players; pitch._owned_ids = list(state.player_ids); pitch._current_xi_ids = current_xi; pitch._bench_ids = list(state.bench_player_ids)
    pitch.set_recommendation(starting_xi_ids=preview.starting_xi_ids, bench_ids=preview.bench_ids,
        captain_id=preview.captain_id, vice_captain_id=preview.vice_captain_id,
        transfers_out=preview.transfers_out, transfers_in=preview.transfers_in)
    pitch._show_recommended()
    assert pitch._showing_recommended and pitch._recommended_xi_ids == list(preview.starting_xi_ids)
    assert pitch._recommended_bench_ids == list(preview.bench_ids)
    assert pitch._recommended_captain_id == preview.captain_id and pitch._recommended_vice_id == preview.vice_captain_id
    pitch._show_current()
    assert not pitch._showing_recommended and pitch._current_xi_ids == current_xi


def test_roll_preview_keeps_the_current_squad():
    positions = ["GK"] * 2 + ["DEF"] * 5 + ["MID"] * 5 + ["FWD"] * 3
    players = {f"p{i}": PlayerRecord(f"p{i}", f"Player {i}", position, f"club_{i // 3}", 50) for i, position in enumerate(positions)}
    starters = ["p0", "p2", "p3", "p4", "p7", "p8", "p9", "p10", "p11", "p12", "p14"]
    bench = ["p1", "p5", "p6", "p13"]
    state = DesktopSquadState(player_ids=[f"p{i}" for i in range(15)], starting_player_ids=starters, bench_player_ids=bench)
    preview = build_recommended_lineup(state, players, {"roll_free_transfer": True, "transfers_out": [], "transfers_in": [], "starting_xi": starters, "bench_order": bench, "captain": "p11", "vice_captain": "p12"})
    assert preview.squad_ids == tuple(state.player_ids)
    assert preview.starting_xi_ids == tuple(starters) and preview.bench_ids == tuple(bench)


def test_v2_remains_a_separate_diagnostic_renderer(qapp):
    window = MainWindow(ROOT)
    state = DesktopSquadState(bank_tenths=0, free_transfers=1)
    try:
        window._render_strategic_v2_diagnostic({
            "strategic_action": {
                "action": "ROLL_FT", "transfers_out": [], "transfers_in": [],
                "free_transfers_before": 1, "free_transfers_after": 2,
                "resulting_bank": 0, "utility": 3.315446,
            },
        }, state)
        text = window.analysis_strategic_summary.text()
        assert "Strategic action: ROLL FT" in text
        assert "Free transfers: 1 → 2 next GW" in text
        assert "V2 utility: 3.315446" in text
        assert "Impact" not in text and "Projected gain" not in text
    finally:
        window.close()


def test_v2_diagnostic_renders_exact_existing_transfer(qapp):
    window = MainWindow(ROOT)
    state = DesktopSquadState(bank_tenths=0, free_transfers=1)
    try:
        window._render_strategic_v2_diagnostic({
            "player_metadata": {
                "out": {"name": "Outgoing"}, "in": {"name": "Incoming"},
            },
            "strategic_action": {
                "action": "TRANSFER", "transfers_out": ["out"], "transfers_in": ["in"],
                "free_transfers_used": 1, "hit_cost": 0, "resulting_bank": 8,
                "free_transfers_before": 1, "free_transfers_after": 1, "utility": 4.0,
            },
        }, state)
        text = window.analysis_strategic_summary.text()
        assert "Strategic action: MAKE TRANSFER" in text
        assert "OUT: Outgoing" in text and "IN: Incoming" in text
        assert "Bank after: £0.8m" in text
        assert "V2 utility: 4.000000" in text
        assert "Impact" not in text
    finally:
        window.close()


def test_strategic_v3_and_roll_counterfactual_render_without_using_v2_utility(qapp):
    window = MainWindow(ROOT)
    state = DesktopSquadState(bank_tenths=3, free_transfers=2)
    report = {
        "player_metadata": {"out": {"name": "Outgoing"}, "in": {"name": "Incoming"}},
        "strategic_v3": {
            "current_action": {
                "action": "TRANSFER", "transfers_out": ["out"], "transfers_in": ["in"],
                "transfers_used": 1, "hit_cost_points": 0, "resulting_bank": 8,
                "free_transfers_before": 2, "free_transfers_after": 2,
            },
            "projected_next_action": {"action": "HOLD"},
            "projected_3gw_path_points": 123.4, "terminal_ft_value": 2.0,
            "delta_vs_hold_now": 1.5,
            "hold_now_counterfactual": {
                "projected_3gw_path_points": 121.9,
                "path": [
                    {"action": "HOLD", "free_transfers_before": 2, "free_transfers_after": 3},
                    {
                        "action": "TRANSFER", "transfers_out": ["out"], "transfers_in": ["in"],
                        "free_transfers_after": 2, "resulting_bank": 8,
                        "price_risk": {"level": "HIGH", "message": "Plan may become unaffordable."},
                    },
                ],
            },
        },
    }
    try:
        window._render_strategic_action(report, state)
        assert "Recommended now: TRANSFER" in window.analysis_strategic_summary.text()
        assert "3-GW path advantage vs Roll: +1.50" in window.analysis_strategic_summary.text()
        assert "V2 utility" not in window.analysis_strategic_summary.text()
        assert "Current GW: HOLD" in window.analysis_roll_summary.text()
        assert "Price risk: HIGH" in window.analysis_roll_summary.text()
        assert "Next-GW action is indicative" in window.analysis_strategic_summary.text()
    finally:
        window.close()


def test_roll_counterfactual_shows_later_first_transfer_without_replanning(qapp):
    window = MainWindow(ROOT)
    try:
        window._render_roll_counterfactual(
            {
                "path": [
                    {"gw": 6, "action": "HOLD", "free_transfers_before": 2, "free_transfers_after": 3},
                    {"gw": 7, "action": "HOLD", "free_transfers_before": 3, "free_transfers_after": 4},
                    {
                        "gw": 8, "action": "TRANSFER", "transfers_out": ["out"], "transfers_in": ["in"],
                        "free_transfers_before": 4, "free_transfers_after": 3, "resulting_bank": 8,
                    },
                ],
            },
            {"out": {"name": "Outgoing"}, "in": {"name": "Incoming"}}, 0.0,
        )
        rendered = window.analysis_roll_summary.text()
        assert "Projected next-GW action: HOLD" in rendered
        assert "First planned transfer: GW8" in rendered
        assert "OUT: Outgoing" in rendered and "IN: Incoming" in rendered
        assert "FT: 4 -> 3" in rendered and "Bank after: £0.8m" in rendered
    finally:
        window.close()


def test_roll_counterfactual_does_not_duplicate_next_gw_transfer_or_invent_one(qapp):
    window = MainWindow(ROOT)
    try:
        window._render_roll_counterfactual(
            {
                "path": [
                    {"gw": 6, "action": "HOLD", "free_transfers_before": 2, "free_transfers_after": 3},
                    {
                        "gw": 7, "action": "TRANSFER", "transfers_out": ["out"], "transfers_in": ["in"],
                        "free_transfers_before": 3, "free_transfers_after": 2, "resulting_bank": 8,
                    },
                ],
            },
            {"out": {"name": "Outgoing"}, "in": {"name": "Incoming"}}, 0.0,
        )
        rendered = window.analysis_roll_summary.text()
        assert "Projected next-GW action: OUT Outgoing" in rendered
        assert "First planned transfer:" not in rendered

        window._render_roll_counterfactual(
            {
                "path": [
                    {"gw": 6, "action": "HOLD", "free_transfers_before": 2, "free_transfers_after": 3},
                    {"gw": 7, "action": "HOLD", "free_transfers_before": 3, "free_transfers_after": 4},
                    {"gw": 8, "action": "HOLD", "free_transfers_before": 4, "free_transfers_after": 5},
                ],
            },
            {}, 0.0,
        )
        assert "First planned transfer: None within 3-GW horizon" in window.analysis_roll_summary.text()
    finally:
        window.close()


def test_successful_full_analysis_renders_existing_recommended_captaincy_and_replaces_stale_value(qapp):
    positions = ["GK"] * 2 + ["DEF"] * 5 + ["MID"] * 5 + ["FWD"] * 3
    players = {f"p{i}": PlayerRecord(f"p{i}", f"Player {i}", position, f"club_{i // 3}", 50) for i, position in enumerate(positions)}
    starters = ("p0", "p2", "p3", "p4", "p7", "p8", "p9", "p10", "p11", "p12", "p14")
    preview = RecommendedLineup(tuple(players), starters, ("p1", "p5", "p6", "p13"), "p11", "p12", (), ())

    class Fixtures:
        def entries_for(self, _player, _gameweek, count=1):
            assert count == 1
            return [FixtureBadgeData(5, "CHE", "H", 2, 0.37, 6.25)]

    window = MainWindow(ROOT)
    original_state = window.state_path.read_bytes()
    try:
        window._render_captaincy_result(preview=preview, players=players, fixtures=Fixtures(), recommendation={})
        rendered = window.analysis_captain_summary.text()
        assert "Captain: Player 11" in rendered
        assert "Vice-captain: Player 12" in rendered
        assert "Captain expected points: 6.25" in rendered
        assert "Captain p_5_plus: 37%" in rendered
        assert preview.captain_id != preview.vice_captain_id
        assert preview.captain_id in preview.starting_xi_ids and preview.vice_captain_id in preview.starting_xi_ids
        assert window.state_path.read_bytes() == original_state

        replacement = RecommendedLineup(tuple(players), starters, ("p1", "p5", "p6", "p13"), "p12", "p11", (), ())
        window._render_captaincy_result(preview=replacement, players=players, fixtures=Fixtures(), recommendation={})
        assert "Captain: Player 12" in window.analysis_captain_summary.text()
        assert "Vice-captain: Player 11" in window.analysis_captain_summary.text()
        assert "Captain: Player 11" not in window.analysis_captain_summary.text()
    finally:
        window.close()


def test_new_decision_run_clears_stale_captaincy_result(qapp, monkeypatch):
    window = MainWindow(ROOT)
    try:
        window.analysis_captain_summary.setText("Captain: stale player")
        monkeypatch.setattr(
            main_window_module, "decision_bundle_for_state",
            lambda *_: (_ for _ in ()).throw(DesktopEngineError("missing bundle")),
        )
        window.start_decision_run()
        assert window.analysis_captain_summary.text() == "Captain recommendation will appear here."
    finally:
        window.close()
