from __future__ import annotations

import json
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QFrame, QScrollArea

import desktop_app.main_window as main_window_module
from desktop_app.main_window import MainWindow
from desktop_app.data_access import PlayerRecord
from desktop_app.state import DesktopSquadState, default_chip_state
from desktop_app.transfer_targets import (
    TransferTarget,
    affordability_status,
    filter_transfer_targets,
    format_transfer_targets,
    load_transfer_targets,
)
from desktop_app.analysis_views import DetailSummary, TransferPlanCards


ROOT = Path(__file__).resolve().parents[1]


def _bundle(tmp_path: Path) -> tuple[Path, DesktopSquadState]:
    run = tmp_path / "data" / "processed" / "predictions" / "2026-27" / "targets"
    run.mkdir(parents=True)
    current_players = [
        {
            "player_id": "owned", "display_name": "Owned Player", "position": "MID",
            "team_id": "1", "provider_team_id": "1", "current_price": 60,
            "provider_payload": {"can_select": True},
        },
        {
            "player_id": "mid", "display_name": "Target Mid", "position": "MID",
            "team_id": "2", "provider_team_id": "2", "current_price": 75,
            "provider_payload": {"can_select": True},
        },
        {
            "player_id": "def", "display_name": "Target Def", "position": "DEF",
            "team_id": "3", "provider_team_id": "3", "current_price": 50,
            "provider_payload": {"can_select": True},
        },
        {
            "player_id": "unavailable", "display_name": "Unavailable", "position": "FWD",
            "team_id": "4", "provider_team_id": "4", "current_price": 65,
            "provider_payload": {"can_select": False},
        },
    ]
    candidate_pool = [
        {"player_id": "owned", "position": "MID", "club_id": "club-1", "current_price": 60},
        {"player_id": "mid", "position": "MID", "club_id": "club-2", "current_price": 75},
        {"player_id": "def", "position": "DEF", "club_id": "club-3", "current_price": 50},
        {"player_id": "unavailable", "position": "FWD", "club_id": "club-4", "current_price": 65},
    ]

    def projection(player_id: str, weighted: float, position_value: float) -> dict:
        return {
            "player_id": player_id,
            "weighted_ev_next_6": weighted,
            "ev_next_3": position_value * 3,
            "ev_next_6": position_value * 6,
            "gameweeks": [{
                "target_gameweek": 5,
                "expected_points": position_value,
                "p_5_plus": 0.4,
                "expected_minutes": 80.0,
            }],
        }

    projections = [
        projection("owned", 100.0, 9.0),
        projection("mid", 48.0, 7.0),
        projection("def", 39.0, 5.5),
        projection("unavailable", 90.0, 8.0),
    ]
    bundle = run / "shadow_projection_bundle.json"
    bundle.write_text(json.dumps({
        "season": "2026/27", "current_gameweek": 5,
        "candidate_pool": candidate_pool, "projections": projections,
    }), encoding="utf-8")
    (run / "current_players.json").write_text(json.dumps(current_players), encoding="utf-8")
    (run / "player_projections.json").write_text(json.dumps(projections), encoding="utf-8")
    (run / "fixture_horizon.json").write_text(json.dumps([
        {
            "target_gameweek": 5, "home_team_id": "2", "away_team_id": "3",
            "away_provider_team_id": "3", "home_provider_team_id": "2", "provider_payload": {},
        },
    ]), encoding="utf-8")
    state = DesktopSquadState(
        season="2026/27", gameweek=5, bank_tenths=10, free_transfers=1,
        player_ids=["owned"], chips_used=default_chip_state(),
    )
    return bundle, state


def test_targets_use_the_selected_bundle_and_rank_deterministically(tmp_path):
    bundle, _ = _bundle(tmp_path)
    before = {path.name: path.read_bytes() for path in bundle.parent.iterdir()}

    first = load_transfer_targets(bundle, owned_player_ids=["owned"])
    second = load_transfer_targets(bundle, owned_player_ids=["owned"])

    assert [target.player_id for target in first] == ["mid", "def"]
    assert first == second
    assert first[0].rank_metric == 48.0
    assert first[0].gameweek_expected_points == 7.0
    assert first[0].p_5_plus == 0.4
    assert first[0].expected_minutes == 80.0
    assert first[0].ev_next_3 == 21.0
    assert first[0].ev_next_6 == 42.0
    assert len(first[0].fixtures) == 6
    assert first[0].fixtures[0] == "BOU H"
    assert first[0].fixtures[1:] == ("BGW -",) * 5
    assert "unavailable" not in {target.player_id for target in first}
    assert {path.name: path.read_bytes() for path in bundle.parent.iterdir()} == before


def test_targets_support_position_filters_and_selected_in_highlight(tmp_path):
    bundle, _ = _bundle(tmp_path)
    targets = load_transfer_targets(bundle, owned_player_ids=["owned"])

    assert [target.player_id for target in filter_transfer_targets(targets, position="ALL")] == ["mid", "def"]
    assert [target.player_id for target in filter_transfer_targets(targets, position="MID")] == ["mid"]
    assert [target.player_id for target in filter_transfer_targets(targets, position="DEF")] == ["def"]
    assert filter_transfer_targets(targets, position="GK") == ()
    rendered = format_transfer_targets(targets, selected_in_ids=["def"])
    assert "Target Def ★ IN" in rendered
    assert "£7.5m" in rendered
    assert "p_5_plus 40%" in rendered


def test_target_search_and_affordability_status_are_informational_and_deterministic():
    target = TransferTarget(40.0, "target", "Target Mid", "MID", "Target Club", 75, None, 6.0, .4, 80.0, 18.0, 36.0, "club_target")
    other = TransferTarget(39.0, "other", "Other Def", "DEF", "Other Club", 50, None, 5.0, .3, 75.0, 15.0, 30.0, "club_other")
    assert filter_transfer_targets((target, other), query="target") == (target,)
    assert filter_transfer_targets((target, other), query="other club") == (other,)
    assert filter_transfer_targets((target, other), position="MID", query="club") == (target,)
    players = {
        "owned_mid": PlayerRecord("owned_mid", "Owned", "MID", "club_owned", 70),
        "owned_def": PlayerRecord("owned_def", "Owned defender", "DEF", "club_def", 50),
    }
    assert affordability_status(
        target, owned_player_ids=["owned_mid", "owned_def"], bank_tenths=10,
        selling_prices_tenths={"owned_mid": 70, "owned_def": 50}, players_by_id=players,
    ) == "AFFORDABLE"
    assert affordability_status(
        target, owned_player_ids=["owned_mid", "owned_def"], bank_tenths=0,
        selling_prices_tenths={"owned_mid": 60, "owned_def": 50}, players_by_id=players,
    ) == "NEEDS FUNDING"
    assert affordability_status(
        target, owned_player_ids=["target"], bank_tenths=0,
        selling_prices_tenths={}, players_by_id=players,
    ) == "OWNED"


def test_recommended_transfers_shows_engine_plan_and_two_feasible_plans(qapp):
    window = MainWindow(ROOT)
    try:
        report = {
            "recommendation": {
                "transfers_out": ["owned_mid"], "transfers_in": ["primary"],
                "hit_cost": 0, "net_projected_gain": 1.2, "resulting_bank": 15,
                "free_transfers_before": 1,
                "transfer_impacts": {"impact_1gw": 1.0, "impact_3gw": 2.0, "impact_6gw": 3.0},
            },
            "feasible_plans": [
                {"transfers_out": ["owned_mid"], "transfers_in": ["alternative_one"], "hit_cost": 0, "net_gain": 1.0, "resulting_bank": 12, "free_transfers_used": 1, "impact_1gw": .8, "impact_3gw": 1.8, "impact_6gw": 2.8},
                {"transfers_out": ["owned_def", "owned_mid"], "transfers_in": ["cheap_def", "expensive_mid"], "hit_cost": 4, "net_gain": .5, "resulting_bank": 0, "free_transfers_used": 1, "impact_1gw": .5, "impact_3gw": 1.5, "impact_6gw": 2.5},
            ],
            "player_metadata": {
                "owned_mid": {"name": "Owned midfielder", "position": "MID"},
                "primary": {"name": "Engine target", "position": "MID", "current_price": 70},
                "alternative_one": {"name": "Affordable alternative", "position": "MID", "current_price": 68},
                "owned_def": {"name": "Owned defender", "position": "DEF", "current_price": 50},
                "cheap_def": {"name": "Cheap defender", "position": "DEF", "current_price": 20},
                "expensive_mid": {"name": "Expensive target", "position": "MID", "current_price": 90},
            },
        }
        rendered = window._format_transfer_plans(report, {"owned_mid": 65, "owned_def": 55})
        assert "Plan 1 | Best short-term" in rendered
        assert "Engine target" in rendered
        assert "Plan 2 | Best balanced" in rendered and "Plan 3 | Best long-term" in rendered
        assert rendered.count("Engine target") == 3
        assert "Affordable alternative" not in rendered and "Expensive target" not in rendered
        assert "Funding released" not in rendered and "Vs recommended" not in rendered
        assert "Projected gain" not in rendered and "Selected horizon impact" in rendered
        assert " ? " not in rendered
        window._render_transfer_plans(report, {"owned_mid": 65, "owned_def": 55})
        assert len(window.analysis_transfer_summary.findChildren(QFrame, "TransferPlanPrimary")) == 1
        assert len(window.analysis_transfer_summary.findChildren(QFrame, "TransferPlanSecondary")) == 2
        assert "Plan 1 | Best short-term" in window.analysis_transfer_summary.text()
    finally:
        window.close()


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def test_analysis_target_list_uses_decision_bundle_without_mutating_account_state(qapp, tmp_path, monkeypatch):
    bundle, state = _bundle(tmp_path)
    window = MainWindow(ROOT)
    state_bytes = window.state_path.read_bytes() if window.state_path.exists() else None
    try:
        monkeypatch.setattr(window, "_state_from_ui", lambda: state)
        monkeypatch.setattr(main_window_module, "decision_bundle_for_state", lambda *_args: bundle)
        window._render_transfer_targets({"recommendation": {"transfers_in": ["def"]}})
        assert "Target Mid" in window.analysis_targets_summary.toPlainText()
        assert window.analysis_targets_summary.rowCount() == 3
        assert "Target Def  IN" in window.analysis_targets_summary.toPlainText()
        assert "Fixtures (6GW)" in [window.analysis_targets_summary.horizontalHeaderItem(column).text() for column in range(window.analysis_targets_summary.columnCount())]
        assert "BOU H | BGW - | BGW - | BGW - | BGW - | BGW -" in window.analysis_targets_summary.toPlainText()

        window.target_position_filter.setCurrentIndex(window.target_position_filter.findData("MID"))
        assert "Target Mid" in window.analysis_targets_summary.toPlainText()
        assert "Target Def" not in window.analysis_targets_summary.toPlainText()
        window.target_search.setText("Target Mid")
        assert window.analysis_targets_summary.rowCount() == 1
        assert "Target Mid" in window.analysis_targets_summary.toPlainText()
        window.target_search.clear()
        assert window.analysis_targets_summary.rowCount() == 2
        assert (window.state_path.read_bytes() if window.state_path.exists() else None) == state_bytes
    finally:
        window.close()


@pytest.mark.parametrize("width,height", ((1600, 820), (1600, 900), (1900, 1080)))
def test_analysis_layout_prioritizes_feasible_plans_without_clipping(qapp, width, height):
    window = MainWindow(ROOT)
    try:
        window.resize(width, height)
        window.tabs.setCurrentIndex(1)
        window.show()
        qapp.processEvents()

        assert window.analysis_transfer_card.minimumHeight() >= 360
        assert window.analysis_transfer_card.width() > window.analysis_captain_card.width()
        assert window.analysis_captain_card.minimumHeight() >= 205
        assert window.analysis_chip_card.minimumHeight() >= 205
        assert window.analysis_targets_summary.columnCount() == 12
        assert window.target_search.placeholderText() == "Player or club"
        assert window.analysis_targets_summary.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        assert window.analysis_targets_summary.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        assert not isinstance(window.analysis_transfer_summary, QScrollArea)
        assert not isinstance(window.analysis_captain_summary, QScrollArea)
        assert not isinstance(window.analysis_chip_summary, QScrollArea)
        assert isinstance(window.analysis_transfer_summary, TransferPlanCards)
        assert isinstance(window.analysis_captain_summary, DetailSummary)
        assert window.analysis_targets_summary.height() >= window.analysis_targets_summary.horizontalHeader().sizeHint().height()
        assert window.analysis_targets_summary.width() > 600
    finally:
        window.close()


def test_analysis_side_cards_render_existing_summary_fields_as_structured_rows(qapp):
    window = MainWindow(ROOT)
    try:
        window.analysis_captain_summary.setText(
            "Captain: Haaland\nVice-captain: Palmer\nCaptain expected points: 4.46\nCaptain p_5_plus: 36%"
        )
        window.analysis_chip_summary.setText(
            "Recommended: BENCH BOOST\nProjected gain: +8.11 EV\nHorizon: 6 GW\nAvailable: Free Hit, Bench Boost"
        )
        assert len(window.analysis_captain_summary.findChildren(QFrame, "DetailHighlight")) == 1
        assert len(window.analysis_captain_summary.findChildren(QFrame, "DetailRow")) == 3
        assert len(window.analysis_chip_summary.findChildren(QFrame, "DetailHighlight")) == 1
        assert "?" not in window.analysis_captain_summary.text()
        assert "?" not in window.analysis_chip_summary.text()
    finally:
        window.close()
