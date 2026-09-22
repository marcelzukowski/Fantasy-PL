from __future__ import annotations

from PySide6.QtWidgets import QApplication

from desktop_app.data_access import PlayerRecord
from desktop_app.squad_pitch import SquadPitchWidget, StrategyLineupPreview


def _players() -> dict[str, PlayerRecord]:
    positions = ["GK"] * 2 + ["DEF"] * 5 + ["MID"] * 5 + ["FWD"] * 3
    result = {
        f"p{index}": PlayerRecord(f"p{index}", f"Player {index}", position, f"club_{index // 3}", 50)
        for index, position in enumerate(positions)
    }
    for index in (1, 2, 3):
        result[f"in{index}"] = PlayerRecord(f"in{index}", f"Incoming {index}", "FWD", f"incoming_{index}", 50)
    return result


class _Fixtures:
    def __init__(self):
        self.first_gameweeks = []

    def entries_for(self, _player, first_gameweek, **_kwargs):
        self.first_gameweeks.append(first_gameweek)
        return []


def _preview(incoming: str, *, captain: str = "p11") -> StrategyLineupPreview:
    starters = ("p0", "p2", "p3", "p4", "p7", "p8", "p9", "p10", "p11", "p12", incoming)
    return StrategyLineupPreview(
        starting_xi_ids=starters,
        bench_ids=("p1", "p5", "p6", "p13"),
        captain_id=captain,
        vice_captain_id="p12" if captain != "p12" else "p11",
        transfers_out=("p14",),
        transfers_in=(incoming,),
    )


def _hold_preview() -> StrategyLineupPreview:
    return StrategyLineupPreview(
        starting_xi_ids=("p0", "p2", "p3", "p4", "p7", "p8", "p9", "p10", "p11", "p12", "p14"),
        bench_ids=("p1", "p5", "p6", "p13"),
        captain_id="p11", vice_captain_id="p12", transfers_out=(), transfers_in=(), action_label="ROLL FT",
    )


def test_strategy_previews_switch_exact_plan_without_changing_current_xi():
    app = QApplication.instance() or QApplication([])
    del app
    players = _players()
    pitch = SquadPitchWidget(_Fixtures())
    current = ["p0", "p2", "p3", "p4", "p7", "p8", "p9", "p10", "p11", "p12", "p14"]
    pitch._players = players
    pitch._owned_ids = [f"p{index}" for index in range(15)]
    pitch._current_xi_ids = list(current)
    pitch._bench_ids = ["p1", "p5", "p6", "p13"]
    previews = {
        "strategic": _hold_preview(),
        "short_term": _preview("in1"),
        "balanced": _preview("in2", captain="p12"),
        "long_term": _preview("in3"),
    }

    pitch.set_strategy_recommendations(previews, players=players, fixture_repository=_Fixtures())
    assert pitch._current_xi_ids == current
    assert pitch.strategic_button.isEnabled()
    assert pitch.short_term_button.isEnabled()
    assert pitch.balanced_button.isEnabled()
    assert pitch.long_term_button.isEnabled()

    pitch._show_strategy("balanced")
    assert pitch._showing_recommended
    assert pitch._active_strategy == "balanced"
    assert pitch._transfers_out == ["p14"]
    assert pitch._transfers_in == ["in2"]
    assert pitch._recommended_xi_ids == list(previews["balanced"].starting_xi_ids)
    assert pitch._recommended_bench_ids == list(previews["balanced"].bench_ids)
    assert pitch._recommended_captain_id == "p12"
    assert pitch._recommended_vice_id == "p11"
    assert pitch._current_xi_ids == current

    pitch._show_strategy("strategic")
    assert pitch._showing_recommended
    assert pitch._active_strategy == "strategic"
    assert pitch._transfers_out == [] and pitch._transfers_in == []
    assert pitch._recommended_xi_ids == current
    assert pitch._recommended_bench_ids == ["p1", "p5", "p6", "p13"]
    assert pitch._recommended_captain_id in pitch._recommended_xi_ids
    assert pitch._recommended_vice_id in pitch._recommended_xi_ids
    assert pitch._recommended_captain_id != pitch._recommended_vice_id

    pitch._show_current()
    assert not pitch._showing_recommended
    assert pitch._current_xi_ids == current


def test_clearing_strategy_previews_removes_stale_transfer_and_disables_selectors():
    app = QApplication.instance() or QApplication([])
    del app
    pitch = SquadPitchWidget(_Fixtures())
    players = _players()
    pitch._players = players
    pitch._owned_ids = [f"p{index}" for index in range(15)]
    pitch._current_xi_ids = ["p0", "p2", "p3", "p4", "p7", "p8", "p9", "p10", "p11", "p12", "p14"]
    pitch._bench_ids = ["p1", "p5", "p6", "p13"]
    pitch.set_strategy_recommendations({"short_term": _preview("in1")})
    pitch._show_strategy("short_term")
    pitch.clear_recommendations()

    assert not pitch._showing_recommended
    assert pitch._strategy_previews == {}
    assert pitch._transfers_out == [] and pitch._transfers_in == []
    assert not pitch.short_term_button.isEnabled()
    assert not pitch.strategic_button.isEnabled()
    assert not pitch.balanced_button.isEnabled()
    assert not pitch.long_term_button.isEnabled()


def test_current_xi_hides_recommendation_transfer_state_and_selected_preview_uses_analysis_gw():
    app = QApplication.instance() or QApplication([])
    del app
    fixtures = _Fixtures()
    pitch = SquadPitchWidget(fixtures)
    players = _players()
    pitch._players = players
    pitch._owned_ids = [f"p{index}" for index in range(15)]
    pitch._current_xi_ids = ["p0", "p2", "p3", "p4", "p7", "p8", "p9", "p10", "p11", "p12", "p14"]
    pitch._bench_ids = ["p1", "p5", "p6", "p13"]

    pitch.set_strategy_recommendations(
        {"short_term": _preview("in1")}, players=players,
        fixture_repository=fixtures, first_gameweek=6,
    )
    pitch._show_strategy("short_term")
    assert 6 in fixtures.first_gameweeks
    assert pitch.out_label.text().startswith("OUT: Player 14")

    pitch._show_current()
    assert pitch.transfer_bar.isHidden()
    assert pitch.out_label.text() == ""
    assert pitch.in_label.text() == ""
    assert all(row["status"].text() != "OUT" for row in pitch.owned_rows)
