from pathlib import Path


def test_desktop_spec_collects_dynamic_player_risk_snapshot_readers():
    spec = (Path(__file__).resolve().parents[1] / "FPLControlCenter_PL.spec").read_text(encoding="utf-8")
    assert "fpl_engine.planning.player_availability_risk" in spec
    assert "fpl_engine.planning.player_minutes_history" in spec
