import json
from pathlib import Path

from desktop_app.manual_scenario_runner import _player_metadata, _ready


def _source(tmp_path, players, fixtures):
    bundle_path = tmp_path / "shadow_projection_bundle.json"
    bundle_path.write_text("{}", encoding="utf-8")
    (tmp_path / "current_players.json").write_text(json.dumps(players), encoding="utf-8")
    (tmp_path / "fixture_horizon.json").write_text(json.dumps(fixtures), encoding="utf-8")
    return bundle_path


def test_metadata_uses_event_totals_and_lists_every_fixture_including_dgw(tmp_path):
    player = {
        "player_id": "p1",
        "display_name": "Player",
        "provider_payload": {"total_points": 42, "team": 1},
    }
    fixtures = [
        {
            "fixture_id": f"f{gw}{idx}",
            "target_gameweek": gw,
            "home_provider_team_id": "1",
            "away_provider_team_id": "2",
        }
        for gw, idx in [(8, 1), (8, 2), (9, 1), (10, 1), (11, 1), (12, 1)]
    ]
    gw_rows = [
        {
            "target_gameweek": 8,
            "expected_points": 8,
            "fixture_count": 2,
            "fixture_ids": ["f81", "f82"],
        },
        *[
            {
                "target_gameweek": gw,
                "expected_points": gw,
                "fixture_count": 1,
                "fixture_ids": [f"f{gw}1"],
            }
            for gw in range(9, 14)
        ],
    ]
    bundle = {
        "current_gameweek": 8,
        "projections": [{"player_id": "p1", "gameweeks": gw_rows}],
    }
    metadata = _player_metadata(_source(tmp_path, [player], fixtures), bundle)["p1"]

    assert metadata["points_so_far"] == 42
    assert metadata["next_gw_projection"] == 8
    assert metadata["next_5gw_total"] == sum(range(8, 13))
    assert metadata["projection_coverage"] == 5
    assert [
        (
            f["gameweek"],
            f["venue"],
            f["opponent"],
            f["projected_points"],
            f["projected_points_source"],
        )
        for f in metadata["fixtures_5gw"]
    ] == [
        (8, "H", "AVL", None, None),
        (8, "H", "AVL", None, None),
        (9, "H", "AVL", 9, "single_fixture_gw"),
        (10, "H", "AVL", 10, "single_fixture_gw"),
        (11, "H", "AVL", 11, "single_fixture_gw"),
        (12, "H", "AVL", 12, "single_fixture_gw"),
    ]


def test_metadata_keeps_missing_and_nonfinite_values_unknown(tmp_path):
    players = [
        {"player_id": "p1", "provider_payload": {"total_points": float("nan"), "team": 1}},
        {"player_id": "p2", "provider_payload": {"team": 2}},
    ]
    bundle = {
        "current_gameweek": 8,
        "projections": [
            {
                "player_id": "p1",
                "gameweeks": [
                    {"target_gameweek": 8, "expected_points": 2},
                    {"target_gameweek": 9, "expected_points": float("inf")},
                ],
            }
        ],
    }
    metadata = _player_metadata(_source(tmp_path, players, []), bundle)

    assert metadata["p1"]["points_so_far"] is None
    assert metadata["p1"]["next_5gw_total"] is None
    assert metadata["p1"]["projection_coverage"] == 1
    assert metadata["p2"]["points_so_far"] is None
    assert metadata["p2"]["next_gw_projection"] is None
    assert metadata["p2"]["fixtures_5gw"] == []


def test_ready_exposes_metadata_for_owned_and_unowned_rows():
    class Player:
        def __init__(self, player_id):
            self.player_id = player_id
            self.position, self.club_id, self.current_price = "MID", "club", 55
            self.selling_price = 54

    class State:
        players = [Player("owned")]
        bank, free_transfers = 3, 1

    class Shared:
        state, context_id = State(), "context"
        player_pool = [Player("owned"), Player("free")]

    ready = _ready(
        Shared(),
        {
            "owned": {
                "name": "Owned",
                "points_so_far": 1.0,
                "next_gw_projection": 2.0,
                "next_5gw_total": 3.0,
                "fixtures_5gw": [],
                "projection_coverage": 1,
            },
            "free": {
                "name": "Free",
                "points_so_far": 4.0,
                "next_gw_projection": 5.0,
                "next_5gw_total": 6.0,
                "fixtures_5gw": [],
                "projection_coverage": 5,
            },
        },
        "hash",
    )

    assert all(isinstance(row["next_5gw_total"], float) for row in ready["players"])
    assert {row["owned"] for row in ready["players"]} == {True, False}


def test_verified_bundle_metadata_probe_is_read_only():
    bundle_path = Path(
        "data/processed/predictions/2026-27/20261022T071806Z/shadow_projection_bundle.json"
    )
    if not bundle_path.exists():
        return
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    metadata = _player_metadata(bundle_path, bundle)

    assert len(metadata) >= len(bundle["projections"])
    assert all(0 <= row["projection_coverage"] <= 5 for row in metadata.values())
    assert all(row["next_5gw_total"] is not None for row in metadata.values())
