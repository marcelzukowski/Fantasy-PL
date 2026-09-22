from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys

import pytest

from fpl_engine.models.projections import GameweekPlayerProjection, PlayerProjection
from fpl_engine.__main__ import main
from fpl_engine.shadow import ShadowRunError, run_shadow


ROOT = Path(__file__).resolve().parents[1]
AT = datetime(2026, 9, 10, 10, tzinfo=timezone.utc)


def _projection(player_id: str, *, ev: float) -> PlayerProjection:
    gameweeks = tuple(
        GameweekPlayerProjection(
            "2026/27", 1, player_id, 5 + offset, AT, (f"fix_{offset}",), 1,
            ev, ev, 1.0, {0.5: ev}, 0.25, 0.5, 0.5, 0.25, 0.1, 0.05, 80.0,
            {int(ev): 1.0}, 1.0,
        ) for offset in range(6)
    )
    return PlayerProjection(
        player_id, "2026/27", 1, AT, 5, gameweeks, ev, ev * 3, ev * 6,
        ev, ev * 3, ev * 6, 80.0, 240.0, 480.0, 0.2, 0.8, 1.0,
        ("team_strength_v1", "minutes_hurdle_v1", "event_models_v1", "projection_builder_v1"),
        ("current_dataset_v1",), ("current_features_v1",), ("fixture_simulator_v1",),
        (42,), (1,),
    )


def _player(player_id: str, position: str, club: str, *, price: int = 50) -> dict:
    return {"player_id": player_id, "position": position, "club_id": club,
            "purchase_price": price, "current_price": price, "selling_price": price}


def _jsonable(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    return value


def _payload() -> dict:
    positions = ["GK"] * 2 + ["DEF"] * 5 + ["MID"] * 5 + ["FWD"] * 3
    players = [_player(f"p{index}", position, f"club_{index // 3}") for index, position in enumerate(positions)]
    candidate = _player("candidate", "FWD", "club_candidate", price=50)
    projections = [_projection(item["player_id"], ev=1.0 if item["player_id"] == "p14" else 5.0) for item in players]
    projections.append(_projection("candidate", ev=12.0))
    return {
        "prediction_timestamp": AT.isoformat(), "season": "2026/27", "current_gameweek": 5,
        "players": players, "candidate_pool": players + [candidate], "bank": 20, "free_transfers": 1,
        "chip_state": {
            "wildcard_h1": True, "wildcard_h2": True, "free_hit_h1": True, "free_hit_h2": True,
            "bench_boost_h1": True, "bench_boost_h2": True, "triple_captain_h1": True,
            "triple_captain_h2": True, "last_free_hit_gameweek": None,
        },
        "pipeline": {"simulations_per_fixture": 10_000, "seed_strategy": "fixture-scoped"},
        "data_freshness": [{"source": "official_fpl", "known_at": AT.isoformat(), "raw_snapshot_id": "raw_1"}],
        "projections": [_jsonable(asdict(item)) for item in projections],
    }


def _write(tmp_path: Path, payload: dict) -> Path:
    target = tmp_path / "squad-state.json"
    target.write_text(json.dumps(payload), encoding="utf-8")
    return target


def test_shadow_run_is_non_mutating_and_reports_greedy_with_v1_v2_challengers(tmp_path):
    state = _write(tmp_path, _payload())
    machine, human = run_shadow(
        state, project_root=ROOT, output_dir=tmp_path / "reports",
        clock=lambda: AT + timedelta(minutes=1),
    )
    report = json.loads(machine.read_text(encoding="utf-8"))
    assert report["mode"] == "EXPERIMENTAL / SHADOW MODE"
    assert report["promotion_status"] == "NOT PRODUCTION PROMOTED"
    assert report["external_mutations"] == []
    assert report["default_policy"] == "greedy_1gw"
    assert set(report["recommendations"]) == {"greedy_1gw", "optimizer_v1", "optimizer_v2"}
    assert report["recommendations"]["greedy_1gw"]["transfers_in"] == ["candidate"]
    primary = report["recommendations"]["greedy_1gw"]
    assert primary["transfer_impacts"]["impact_1gw"] > 0
    assert primary["alternatives"][0]["resulting_bank"] is not None
    assert primary["alternatives"][0]["free_transfers_used"] is not None
    assert "NOT PRODUCTION PROMOTED" in human.read_text(encoding="utf-8")


def test_shadow_rejects_missing_explicit_purchase_price(tmp_path):
    payload = _payload()
    del payload["players"][0]["purchase_price"]
    with pytest.raises(ShadowRunError, match="purchase_price"):
        run_shadow(_write(tmp_path, payload), project_root=ROOT, output_dir=tmp_path / "reports")


@pytest.mark.parametrize("simulation_count", (1, 10_000, 25_000, 50_000))
def test_shadow_accepts_supported_canonical_simulation_counts(
    tmp_path,
    simulation_count,
):
    payload = _payload()
    payload["pipeline"]["simulations_per_fixture"] = simulation_count
    machine, _ = run_shadow(
        _write(tmp_path, payload),
        project_root=ROOT,
        output_dir=tmp_path / "reports",
        clock=lambda: AT + timedelta(minutes=simulation_count),
    )
    report = json.loads(machine.read_text(encoding="utf-8"))
    assert report["model_rule_versions"]["pipeline"]["simulations_per_fixture"] == simulation_count


def test_shadow_rejects_unsupported_simulation_count(tmp_path):
    payload = _payload()
    payload["pipeline"]["simulations_per_fixture"] = 50_001
    with pytest.raises(ShadowRunError, match="between 1 and 50000"):
        run_shadow(_write(tmp_path, payload), project_root=ROOT, output_dir=tmp_path / "reports")


def test_shadow_rejects_future_current_data_provenance(tmp_path):
    payload = _payload()
    payload["data_freshness"][0]["known_at"] = (AT + timedelta(seconds=1)).isoformat()
    with pytest.raises(ShadowRunError, match="Unsafe data freshness"):
        run_shadow(_write(tmp_path, payload), project_root=ROOT, output_dir=tmp_path / "reports")


def test_module_shadow_command_uses_only_local_input(tmp_path, monkeypatch, capsys):
    state = _write(tmp_path, _payload())
    monkeypatch.setattr(sys, "argv", [
        "python -m fpl_engine", "shadow", "--squad-state", str(state),
        "--output-dir", str(tmp_path / "reports"),
    ])
    assert main() == 0
    output = capsys.readouterr().out.splitlines()
    assert len(output) == 2
    assert Path(output[0]).exists() and Path(output[1]).exists()
