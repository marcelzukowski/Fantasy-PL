from __future__ import annotations

from pathlib import Path

from desktop_app.data_access import load_players
from desktop_app.fixture_display import FixtureDisplayRepository
from desktop_app.state import load_state


ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "scratch" / "decision" / "captain068g" / "integrated_replay" / "v22_real"


def test_fixture_display_uses_v22_p5_plus_values():
    players = load_players(RUN / "current_players.json")
    repository = FixtureDisplayRepository(RUN / "current_players.json")
    state = load_state(ROOT / "data" / "user" / "squad_state.json")
    selected = {players[player_id].display_name: players[player_id] for player_id in state.player_ids}

    expected = {"Sels": 31, "Haaland": 37, "Palmer": 31, "Evanilson": 29}
    for name, percentage in expected.items():
        entries = repository.entries_for(selected[name], 5)
        assert len(entries) == 3
        assert entries[0].percentage == percentage
        assert "Chance of 5+ FPL points" in entries[0].tooltip
        assert "Expected points" in entries[0].tooltip
        assert "FPL FDR" in entries[0].tooltip


def test_fixture_display_missing_values_are_not_zero(tmp_path):
    (tmp_path / "fixture_horizon.json").write_text("[]", encoding="utf-8")
    (tmp_path / "player_projections.json").write_text("[]", encoding="utf-8")
    player_source = tmp_path / "current_players.json"
    player_source.write_text("[]", encoding="utf-8")
    repository = FixtureDisplayRepository(player_source)

    class Player:
        player_id = "unknown"
        team_id = "unknown"

    entry = repository.entries_for(Player(), 5)[0]
    assert entry.opponent == "BGW"
    assert entry.p_5_plus is None
    assert entry.expected_points is None
    assert entry.percentage is None
    assert entry.label.endswith("--")
