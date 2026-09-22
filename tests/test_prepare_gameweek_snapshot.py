from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(
    __file__
).resolve().parents[1]

sys.path.insert(
    0,
    str(
        ROOT / "scripts"
    ),
)

from prepare_gameweek_snapshot import (
    build_readiness_report,
    estimate_odds_credits,
    live_odds_window_open,
)


def write_json(
    path: Path,
    payload,
):
    path.write_text(
        json.dumps(payload),
        encoding="utf-8",
    )


def build_run(
    tmp_path: Path,
    *,
    prediction_timestamp: str,
    covered_second_player: bool = True,
):
    run = tmp_path / "run"
    run.mkdir()

    write_json(
        run / "fixture_horizon.json",
        [
            {
                "fixture_id": "f1",
                "target_gameweek": 5,
                "kickoff": (
                    "2026-09-19T14:00:00Z"
                ),
            }
        ],
    )

    write_json(
        run / "minutes.json",
        [
            {
                "fixture_id": "f1",
                "player_id": "p1",
                "expected_minutes": 80.0,
                "p_start": 0.90,
                "p_appearance": 0.95,
            },
            {
                "fixture_id": "f1",
                "player_id": "p2",
                "expected_minutes": 70.0,
                "p_start": 0.80,
                "p_appearance": 0.90,
            },
        ],
    )

    write_json(
        run / "market_shadow.json",
        {
            "prediction_timestamp": (
                prediction_timestamp
            ),
            "players": [
                {
                    "fixture_id": "f1",
                    "player_id": "p1",
                    "market": {
                        "expected_goals": 0.4,
                        "expected_assists": 0.2,
                    },
                },
                {
                    "fixture_id": "f1",
                    "player_id": "p2",
                    "market": (
                        {
                            "expected_goals": 0.3,
                            "expected_assists": 0.1,
                        }
                        if covered_second_player
                        else None
                    ),
                },
            ],
        },
    )

    write_json(
        run / "run_manifest.json",
        {
            "ok": True
        },
    )

    return run


def test_ready_snapshot(
    tmp_path,
):
    run = build_run(
        tmp_path,
        prediction_timestamp=(
            "2026-09-18T12:00:00Z"
        ),
    )

    report = build_readiness_report(
        run,
        season="2026/27",
        gameweek=5,
        deadline=datetime(
            2026,
            9,
            19,
            12,
            30,
            tzinfo=timezone.utc,
        ),
    )

    assert report.status == "READY"
    assert report.minutes_30.rate == 1.0
    assert report.p_start_050.rate == 1.0
    assert report.market_prior_count == 2
    assert report.goals_available == 2
    assert report.assists_available == 2


def test_low_coverage_warns(
    tmp_path,
):
    run = build_run(
        tmp_path,
        prediction_timestamp=(
            "2026-09-18T12:00:00Z"
        ),
        covered_second_player=False,
    )

    report = build_readiness_report(
        run,
        season="2026/27",
        gameweek=5,
        deadline=datetime(
            2026,
            9,
            19,
            12,
            30,
            tzinfo=timezone.utc,
        ),
    )

    assert report.status == "WARN"
    assert report.minutes_30.rate == 0.5
    assert report.market_prior_count == 1


def test_after_deadline_is_blocked(
    tmp_path,
):
    run = build_run(
        tmp_path,
        prediction_timestamp=(
            "2026-09-19T13:00:00Z"
        ),
    )

    report = build_readiness_report(
        run,
        season="2026/27",
        gameweek=5,
        deadline=datetime(
            2026,
            9,
            19,
            12,
            30,
            tzinfo=timezone.utc,
        ),
    )

    assert report.status == "BLOCKED"

    assert any(
        "deadline" in reason
        for reason in report.reasons
    )



def test_credit_estimate_standard_gw():
    assert estimate_odds_credits(
        10
    ) == 20


def test_credit_estimate_blank_gw():
    assert estimate_odds_credits(
        7
    ) == 14


def test_live_odds_window_closed_early():
    assert not live_odds_window_open(
        now=datetime(
            2026,
            9,
            11,
            22,
            0,
            tzinfo=timezone.utc,
        ),
        deadline=datetime(
            2026,
            9,
            18,
            17,
            30,
            tzinfo=timezone.utc,
        ),
        window_hours=36.0,
    )


def test_live_odds_window_open_close_to_deadline():
    assert live_odds_window_open(
        now=datetime(
            2026,
            9,
            17,
            12,
            0,
            tzinfo=timezone.utc,
        ),
        deadline=datetime(
            2026,
            9,
            18,
            17,
            30,
            tzinfo=timezone.utc,
        ),
        window_hours=36.0,
    )

