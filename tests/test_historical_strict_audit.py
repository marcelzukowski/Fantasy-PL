from datetime import datetime, timedelta, timezone
import json

from scripts.audit_strict_history import REQUIRED_VAASTAV_OUTCOMES, audit


AT = datetime(2024, 8, 16, 17, 30, tzinfo=timezone.utc)


def test_strict_audit_stops_at_missing_fixture_schedule_without_fabricating_metrics(tmp_path):
    source = tmp_path / "data" / "interim" / "strict" / "2024-25"
    source.mkdir(parents=True)
    source.joinpath("source_manifest.json").write_text(json.dumps({
        "fplcache_repository_ref": "fpl-ref",
        "vaastav_repository_ref": "vaastav-ref",
        "prediction_points": [{
            "gameweek": 1,
            "prediction_timestamp": AT.isoformat(),
            "snapshot_timestamp": (AT - timedelta(hours=1)).isoformat(),
            "contains_fixture_schedule": False,
            "player_count": 600,
        }],
        "vaastav": {"columns": sorted(REQUIRED_VAASTAV_OUTCOMES), "rows": 500,
                     "unsafe_columns": ["xP"]},
    }), encoding="utf-8")
    report = json.loads(audit(tmp_path, "2024-25").read_text(encoding="utf-8"))
    assert report["status"] == "BLOCKED_AT_MISSING_STRICT_INPUT"
    assert report["prediction_points_evaluated"] == 0
    assert report["leakage_violations"] == 0
    assert report["component_metrics"] is None and report["optimizer_results"] is None
    assert report["source_coverage"]["snapshot_lag_hours_min"] == 1


def test_strict_audit_counts_equality_as_snapshot_leakage(tmp_path):
    source = tmp_path / "data" / "interim" / "strict" / "2024-25"
    source.mkdir(parents=True)
    source.joinpath("source_manifest.json").write_text(json.dumps({
        "fplcache_repository_ref": "fpl-ref", "vaastav_repository_ref": "vaastav-ref",
        "prediction_points": [{"gameweek": 1, "prediction_timestamp": AT.isoformat(),
                               "snapshot_timestamp": AT.isoformat(), "contains_fixture_schedule": True,
                               "player_count": 600}],
        "vaastav": {"columns": sorted(REQUIRED_VAASTAV_OUTCOMES), "rows": 1,
                     "unsafe_columns": ["xP"]},
    }), encoding="utf-8")
    report = json.loads(audit(tmp_path, "2024-25").read_text(encoding="utf-8"))
    assert report["leakage_violations"] == 1
    assert report["source_coverage"]["pre_deadline_fplcache_snapshots"] == 0
