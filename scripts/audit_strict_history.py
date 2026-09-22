"""Audit materialized sources and stop at the first missing STRICT dependency."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import hashlib
from pathlib import Path

import pandas as pd


REQUIRED_VAASTAV_OUTCOMES = {
    "element", "fixture", "team", "opponent_team", "kickoff_time", "minutes", "starts",
    "goals_scored", "assists", "saves", "yellow_cards", "red_cards", "total_points",
    "team_h_score", "team_a_score", "expected_goals", "expected_assists", "value", "GW",
}


def _utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("manifest timestamps must be aware")
    return parsed.astimezone(timezone.utc)


def audit(root: Path, season: str) -> Path:
    source_path = root / "data" / "interim" / "strict" / season / "source_manifest.json"
    source = json.loads(source_path.read_text(encoding="utf-8"))
    points = source["prediction_points"]
    leakage = []
    for point in points:
        if _utc(point["snapshot_timestamp"]) >= _utc(point["prediction_timestamp"]):
            leakage.append({"gameweek": point["gameweek"], "rule": "snapshot_timestamp < prediction_timestamp"})
    columns = set(source["vaastav"]["columns"])
    missing_outcomes = sorted(REQUIRED_VAASTAV_OUTCOMES - columns)
    fixture_manifest_path = source_path.with_name("fixture_schedule_manifest.json")
    fixture_manifest = json.loads(fixture_manifest_path.read_text(encoding="utf-8")) if fixture_manifest_path.exists() else None
    fixture_coverage = fixture_manifest.get("coverage", []) if fixture_manifest else []
    fixture_by_gw = {int(point["gameweek"]): point for point in fixture_coverage}
    fixture_schedule_coverage = 0
    if fixture_manifest:
        for point in points:
            schedule = fixture_by_gw.get(int(point["gameweek"]))
            if not schedule or not schedule.get("covered"):
                continue
            fixture_schedule_coverage += 1
            if _utc(schedule["commit_timestamp"]) >= _utc(point["prediction_timestamp"]):
                leakage.append({"gameweek": point["gameweek"], "rule": "commit_timestamp < prediction_timestamp"})
        for revision in fixture_manifest.get("revisions", []):
            payload = root / revision["raw_payload_path"] if revision["raw_payload_path"].startswith("data/") else root / "data" / "raw" / revision["raw_payload_path"]
            body = payload.read_bytes()
            if hashlib.sha256(body).hexdigest() != revision["raw_checksum"]:
                leakage.append({"commit_sha": revision["commit_sha"], "rule": "RawStore checksum integrity"})
        state_path = root / fixture_manifest["canonical_fixture_state"]["path"]
        states = pd.read_parquet(state_path)
        future_states = states[pd.to_datetime(states["information_known_at"], utc=True) >= pd.to_datetime(states["prediction_timestamp"], utc=True)]
        for gameweek in sorted(set(future_states["prediction_gameweek"].astype(int))):
            leakage.append({"gameweek": gameweek, "rule": "fixture information_known_at < prediction_timestamp"})
    snapshot_lags = [(_utc(point["prediction_timestamp"]) - _utc(point["snapshot_timestamp"])).total_seconds() / 3600
                     for point in points]
    player_counts = [int(point.get("player_count", 0)) for point in points]
    blockers = []
    if fixture_schedule_coverage != len(points):
        blockers.append({
            "boundary": "canonical target fixture construction",
            "missing": "versioned fixture schedule observed before each historical prediction timestamp",
            "impact": ["Team Strength target construction", "Minutes targets", "Player Talent targets",
                       "Event Models", "1/3/6 GW projections", "optimizer"],
            "reason": "Vaastav fixture rows are outcome data retrieved after the season and cannot evidence the schedule known at T",
        })
    if missing_outcomes:
        blockers.append({"boundary": "provider outcome materialization", "missing_columns": missing_outcomes})
    limitations = [
        {
            "boundary": "historical squad-state reconstruction",
            "missing": "pre-deadline manager squad snapshots with purchase prices, bank, FT and chips",
            "impact": ["real-manager optimizer backtest", "historical sequential strategy"],
        },
        {
            "boundary": "strict Player Talent target contract",
            "missing": "non-penalty xG and shot-event history with evidenced availability time",
            "impact": ["npxG/shot talent evaluation", "downstream Event Models"],
        },
    ]
    valid_source_points = len(points) - len({item["gameweek"] for item in leakage if "gameweek" in item})
    report = {
        "report_version": 1,
        "mode": "STRICT",
        "season": season,
        "status": "BLOCKED_AT_MISSING_STRICT_INPUT" if blockers or leakage else "READY_FOR_MODEL_BACKTEST",
        "source_versions": {
            "fplcache": source["fplcache_repository_ref"],
            "vaastav": source["vaastav_repository_ref"],
        },
        "source_coverage": {
            "prediction_points_requested": len(points),
            "pre_deadline_fplcache_snapshots": valid_source_points,
            "pre_deadline_snapshot_fraction": valid_source_points / len(points) if points else 0,
            "snapshot_lag_hours_min": min(snapshot_lags) if snapshot_lags else None,
            "snapshot_lag_hours_max": max(snapshot_lags) if snapshot_lags else None,
            "snapshot_player_count_min": min(player_counts) if player_counts else None,
            "snapshot_player_count_max": max(player_counts) if player_counts else None,
            "fixture_schedule_snapshots": fixture_schedule_coverage,
            "fixture_schedule_missing_gameweeks": sorted(
                {int(point["gameweek"]) for point in points}
                - {gw for gw, item in fixture_by_gw.items() if item.get("covered")}
            ),
            "fixture_schedule_unique_commits": fixture_manifest.get("unique_commits_materialized", 0) if fixture_manifest else 0,
            "vaastav_gameweeks": len({int(value["gameweek"]) for value in points}),
            "vaastav_rows": source["vaastav"]["rows"],
            "vaastav_required_outcome_columns_missing": missing_outcomes,
            "unsafe_columns_excluded": source["vaastav"]["unsafe_columns"],
        },
        "leakage_violations": len(leakage),
        "leakage_details": leakage,
        "prediction_points_evaluated": 0 if blockers or leakage else len(points),
        "component_metrics": None,
        "projection_metrics": {"1GW": None, "3GW": None, "6GW": None},
        "optimizer_results": None,
        "sequential_strategy_result": None,
        "blockers": blockers,
        "limitations": limitations,
        "model_backtesting_unlocked": not blockers and not leakage,
        "separation": {"STRICT": "this report", "STANDARD": None, "SYNTHETIC_REFERENCE": None},
        "champion_update_allowed": False,
        "champion_decision": "KEEP_TESTING",
    }
    output = root / "data" / "processed" / "backtests" / "strict" / season
    output.mkdir(parents=True, exist_ok=True)
    target = output / "coverage_boundary_report.json"
    target.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--season", default="2024-25")
    arguments = parser.parse_args()
    print(audit(arguments.root.resolve(), arguments.season))
