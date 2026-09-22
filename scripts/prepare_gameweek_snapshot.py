from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import time

import httpx


FPL_BOOTSTRAP_URL = (
    "https://fantasy.premierleague.com/"
    "api/bootstrap-static/"
)

FPL_FIXTURES_URL = (
    "https://fantasy.premierleague.com/"
    "api/fixtures/"
)

LIVE_MARKET_COUNT = 2
LIVE_REGION_COUNT = 1

DEFAULT_LIVE_ODDS_WINDOW_HOURS = 36.0


def parse_time(value: str) -> datetime:
    value = str(value).replace(
        "Z",
        "+00:00",
    )

    result = datetime.fromisoformat(
        value
    )

    if (
        result.tzinfo is None
        or result.utcoffset() is None
    ):
        raise ValueError(
            "timestamp must be timezone-aware"
        )

    return result.astimezone(
        timezone.utc
    )


def load_json(path: Path):
    return json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )


def season_slug(
    season: str,
) -> str:
    return season.replace(
        "/",
        "-",
    )


def fetch_fpl_deadline(
    gameweek: int,
) -> datetime:

    with httpx.Client(
        timeout=20.0,
    ) as client:
        response = client.get(
            FPL_BOOTSTRAP_URL
        )
        response.raise_for_status()

    payload = response.json()

    for event in payload.get(
        "events",
        [],
    ):
        if event.get("id") == gameweek:

            deadline = event.get(
                "deadline_time"
            )

            if not deadline:
                break

            return parse_time(
                deadline
            )

    raise RuntimeError(
        f"Could not determine FPL "
        f"deadline for GW{gameweek}"
    )


def fetch_fpl_fixture_count(
    gameweek: int,
) -> int:

    with httpx.Client(
        timeout=20.0,
    ) as client:
        response = client.get(
            FPL_FIXTURES_URL,
            params={
                "event": gameweek,
            },
        )
        response.raise_for_status()

    payload = response.json()

    if not isinstance(
        payload,
        list,
    ):
        raise RuntimeError(
            "Official FPL fixtures "
            "payload is not a list"
        )

    return len(
        payload
    )


def estimate_odds_credits(
    fixture_count: int,
    *,
    market_count: int = (
        LIVE_MARKET_COUNT
    ),
    region_count: int = (
        LIVE_REGION_COUNT
    ),
) -> int:
    """Maximum event-odds cost if all requested markets are returned."""

    if fixture_count < 0:
        raise ValueError(
            "fixture_count cannot be negative"
        )

    if market_count < 0:
        raise ValueError(
            "market_count cannot be negative"
        )

    if region_count < 0:
        raise ValueError(
            "region_count cannot be negative"
        )

    return (
        fixture_count
        * market_count
        * region_count
    )


def live_odds_window_open(
    *,
    now: datetime,
    deadline: datetime,
    window_hours: float,
) -> bool:

    if window_hours <= 0:
        raise ValueError(
            "window_hours must be positive"
        )

    seconds = (
        deadline - now
    ).total_seconds()

    return (
        seconds
        <= window_hours * 3600.0
    )


def shadow_base(
    root: Path,
    season: str,
) -> Path:
    return (
        root
        / "scratch"
        / "book003"
        / "current_market_shadow"
        / season_slug(season)
    )


def run_dirs(
    root: Path,
    season: str,
) -> set[Path]:

    base = shadow_base(
        root,
        season,
    )

    if not base.exists():
        return set()

    return {
        path
        for path in base.iterdir()
        if path.is_dir()
    }


def latest_run_dir(
    root: Path,
    season: str,
    *,
    created_after: float | None = None,
) -> Path:

    candidates = []

    for path in run_dirs(
        root,
        season,
    ):
        shadow = (
            path
            / "market_shadow.json"
        )

        if not shadow.exists():
            continue

        modified = shadow.stat().st_mtime

        if (
            created_after is not None
            and modified < created_after
        ):
            continue

        candidates.append(
            (
                modified,
                path,
            )
        )

    if not candidates:
        raise RuntimeError(
            "No completed market shadow "
            "run found"
        )

    return max(
        candidates,
        key=lambda item: item[0],
    )[1]


@dataclass(frozen=True)
class CoverageResult:
    eligible: int
    covered: int
    rate: float


@dataclass(frozen=True)
class SnapshotReadiness:
    status: str
    reasons: tuple[str, ...]

    season: str
    gameweek: int

    run_dir: str

    prediction_timestamp: str
    deadline: str

    fixture_count: int
    player_fixture_rows: int

    market_prior_count: int

    minutes_30: CoverageResult
    minutes_60: CoverageResult
    p_start_050: CoverageResult
    p_appearance_075: CoverageResult

    goals_available: int
    assists_available: int


def coverage(
    *,
    rows_by_key: dict,
    minute_rows: list[dict],
    predicate,
) -> CoverageResult:

    eligible = []

    for row in minute_rows:

        if not predicate(row):
            continue

        key = (
            row["fixture_id"],
            row["player_id"],
        )

        eligible.append(
            rows_by_key.get(key)
        )

    eligible = [
        row
        for row in eligible
        if row is not None
    ]

    covered = sum(
        row.get("market")
        is not None
        for row in eligible
    )

    count = len(
        eligible
    )

    rate = (
        covered / count
        if count
        else 0.0
    )

    return CoverageResult(
        eligible=count,
        covered=covered,
        rate=rate,
    )


def build_readiness_report(
    run_dir: Path,
    *,
    season: str,
    gameweek: int,
    deadline: datetime,
    minimum_coverage: float = 0.80,
) -> SnapshotReadiness:

    required = (
        "market_shadow.json",
        "fixture_horizon.json",
        "minutes.json",
        "run_manifest.json",
    )

    missing = [
        name
        for name in required
        if not (
            run_dir / name
        ).exists()
    ]

    if missing:
        raise RuntimeError(
            "Missing required artifacts: "
            + ", ".join(missing)
        )

    shadow = load_json(
        run_dir
        / "market_shadow.json"
    )

    fixtures = load_json(
        run_dir
        / "fixture_horizon.json"
    )

    minutes = load_json(
        run_dir
        / "minutes.json"
    )

    prediction_timestamp = (
        parse_time(
            shadow[
                "prediction_timestamp"
            ]
        )
    )

    gw_fixtures = [
        row
        for row in fixtures
        if row.get(
            "target_gameweek"
        ) == gameweek
    ]

    fixture_ids = {
        row["fixture_id"]
        for row in gw_fixtures
    }

    player_rows = [
        row
        for row in shadow.get(
            "players",
            []
        )
        if row.get(
            "fixture_id"
        ) in fixture_ids
    ]

    rows_by_key = {
        (
            row["fixture_id"],
            row["player_id"],
        ): row
        for row in player_rows
    }

    minute_rows = [
        row
        for row in minutes
        if row.get(
            "fixture_id"
        ) in fixture_ids
    ]

    min30 = coverage(
        rows_by_key=rows_by_key,
        minute_rows=minute_rows,
        predicate=lambda r: (
            float(
                r.get(
                    "expected_minutes",
                    0.0,
                )
            )
            >= 30.0
        ),
    )

    min60 = coverage(
        rows_by_key=rows_by_key,
        minute_rows=minute_rows,
        predicate=lambda r: (
            float(
                r.get(
                    "expected_minutes",
                    0.0,
                )
            )
            >= 60.0
        ),
    )

    start50 = coverage(
        rows_by_key=rows_by_key,
        minute_rows=minute_rows,
        predicate=lambda r: (
            float(
                r.get(
                    "p_start",
                    0.0,
                )
            )
            >= 0.50
        ),
    )

    app75 = coverage(
        rows_by_key=rows_by_key,
        minute_rows=minute_rows,
        predicate=lambda r: (
            float(
                r.get(
                    "p_appearance",
                    0.0,
                )
            )
            >= 0.75
        ),
    )

    market_rows = [
        row
        for row in player_rows
        if row.get(
            "market"
        ) is not None
    ]

    goals_available = sum(
        row["market"].get(
            "expected_goals"
        )
        is not None
        for row in market_rows
    )

    assists_available = sum(
        row["market"].get(
            "expected_assists"
        )
        is not None
        for row in market_rows
    )

    reasons = []

    if not gw_fixtures:
        reasons.append(
            "no fixtures for target GW"
        )

    if not player_rows:
        reasons.append(
            "no player-fixture projections"
        )

    if prediction_timestamp >= deadline:
        reasons.append(
            "snapshot created at or "
            "after official FPL deadline"
        )

    blocked = bool(
        reasons
    )

    warnings = []

    if (
        not blocked
        and min30.rate
        < minimum_coverage
    ):
        warnings.append(
            "market coverage for "
            "expected_minutes>=30 "
            f"is only {min30.rate:.1%}"
        )

    if (
        not blocked
        and start50.rate
        < minimum_coverage
    ):
        warnings.append(
            "market coverage for "
            "p_start>=0.50 "
            f"is only {start50.rate:.1%}"
        )

    if (
        not blocked
        and app75.rate
        < minimum_coverage
    ):
        warnings.append(
            "market coverage for "
            "p_appearance>=0.75 "
            f"is only {app75.rate:.1%}"
        )

    if (
        not blocked
        and goals_available == 0
    ):
        warnings.append(
            "no goal market priors"
        )

    if (
        not blocked
        and assists_available == 0
    ):
        warnings.append(
            "no assist market priors"
        )

    if blocked:
        status = "BLOCKED"
        all_reasons = tuple(
            reasons
        )

    elif warnings:
        status = "WARN"
        all_reasons = tuple(
            warnings
        )

    else:
        status = "READY"
        all_reasons = ()

    return SnapshotReadiness(
        status=status,
        reasons=all_reasons,
        season=season,
        gameweek=gameweek,
        run_dir=str(
            run_dir
        ),
        prediction_timestamp=(
            prediction_timestamp
            .isoformat()
        ),
        deadline=(
            deadline.isoformat()
        ),
        fixture_count=len(
            gw_fixtures
        ),
        player_fixture_rows=len(
            player_rows
        ),
        market_prior_count=len(
            market_rows
        ),
        minutes_30=min30,
        minutes_60=min60,
        p_start_050=start50,
        p_appearance_075=app75,
        goals_available=(
            goals_available
        ),
        assists_available=(
            assists_available
        ),
    )


def print_coverage(
    label: str,
    result: CoverageResult,
):
    print(
        f"{label:<23} "
        f"{result.covered}/"
        f"{result.eligible} "
        f"({result.rate:.1%})"
    )


def main() -> int:

    parser = argparse.ArgumentParser(
        description=(
            "Prepare one complete "
            "pre-deadline FPL market snapshot."
        )
    )

    parser.add_argument(
        "--season",
        default="2026/27",
    )

    parser.add_argument(
        "--gameweek",
        type=int,
        required=True,
    )

    parser.add_argument(
        "--simulation-count",
        type=int,
        default=64,
    )

    parser.add_argument(
        "--minimum-coverage",
        type=float,
        default=0.80,
    )

    parser.add_argument(
        "--max-odds-credits",
        type=int,
        default=30,
        help=(
            "Maximum estimated The Odds API "
            "credits allowed for this snapshot."
        ),
    )

    parser.add_argument(
        "--allow-live-odds-spend",
        action="store_true",
        help=(
            "Explicit opt-in required before "
            "a live paid odds request."
        ),
    )

    parser.add_argument(
        "--live-odds-window-hours",
        type=float,
        default=(
            DEFAULT_LIVE_ODDS_WINDOW_HOURS
        ),
        help=(
            "Live bookmaker requests are "
            "blocked before this many hours "
            "to the FPL deadline."
        ),
    )

    parser.add_argument(
        "--allow-early-live-odds",
        action="store_true",
        help=(
            "Override the early live-odds "
            "safety block."
        ),
    )

    parser.add_argument(
        "--offline-odds-cache",
        action="store_true",
    )

    args = parser.parse_args()

    root = Path(
        __file__
    ).resolve().parents[1]

    deadline = fetch_fpl_deadline(
        args.gameweek
    )

    now = datetime.now(
        timezone.utc
    )

    if args.max_odds_credits < 0:
        raise SystemExit(
            "--max-odds-credits "
            "cannot be negative"
        )

    if args.live_odds_window_hours <= 0:
        raise SystemExit(
            "--live-odds-window-hours "
            "must be positive"
        )

    hours_to_deadline = (
        deadline - now
    ).total_seconds() / 3600.0

    target_fixture_count = (
        fetch_fpl_fixture_count(
            args.gameweek
        )
    )

    estimated_odds_credits = (
        0
        if args.offline_odds_cache
        else estimate_odds_credits(
            target_fixture_count
        )
    )

    print()
    print(
        "=== GAMEWEEK SNAPSHOT PRECHECK ==="
    )

    print(
        "season:",
        args.season,
    )

    print(
        "gameweek:",
        args.gameweek,
    )

    print(
        "deadline:",
        deadline.isoformat(),
    )

    print(
        "now:",
        now.isoformat(),
    )

    print(
        "target_fixtures:",
        target_fixture_count,
    )

    print(
        "live_markets:",
        (
            0
            if args.offline_odds_cache
            else LIVE_MARKET_COUNT
        ),
    )

    print(
        "estimated_max_odds_credits:",
        estimated_odds_credits,
    )

    print(
        "configured_credit_limit:",
        args.max_odds_credits,
    )

    print(
        "hours_to_deadline:",
        f"{hours_to_deadline:.1f}",
    )

    print(
        "live_odds_window_hours:",
        args.live_odds_window_hours,
    )

    print(
        "odds_mode:",
        (
            "OFFLINE CACHE"
            if args.offline_odds_cache
            else "LIVE"
        ),
    )

    if now >= deadline:
        print()
        print(
            "BLOCKED"
        )
        print(
            "Official FPL deadline has "
            "already passed."
        )
        print(
            "No bookmaker request was made."
        )
        return 2

    if (
        not args.offline_odds_cache
        and not args.allow_early_live_odds
        and not live_odds_window_open(
            now=now,
            deadline=deadline,
            window_hours=(
                args.live_odds_window_hours
            ),
        )
    ):
        print()
        print(
            "BLOCKED"
        )
        print(
            "Live player-prop request is "
            "too early."
        )
        print(
            "hours_to_deadline:",
            f"{hours_to_deadline:.1f}",
        )
        print(
            "configured_live_window:",
            args.live_odds_window_hours,
            "hours",
        )
        print(
            "Additional player markets often "
            "open closer to kickoff."
        )
        print(
            "No paid odds request was made."
        )
        return 2

    if (
        not args.offline_odds_cache
        and estimated_odds_credits
        > args.max_odds_credits
    ):
        print()
        print(
            "BLOCKED"
        )
        print(
            "Estimated The Odds API cost "
            "exceeds configured limit."
        )
        print(
            "estimated:",
            estimated_odds_credits,
        )
        print(
            "limit:",
            args.max_odds_credits,
        )
        print(
            "No paid odds request was made."
        )
        return 2

    if (
        not args.offline_odds_cache
        and not args.allow_live_odds_spend
    ):
        print()
        print(
            "BLOCKED"
        )
        print(
            "Live The Odds API spending "
            "requires explicit opt-in."
        )
        print()
        print(
            "Re-run with:"
        )
        print(
            "  --allow-live-odds-spend"
        )
        print()
        print(
            "Estimated maximum cost:",
            estimated_odds_credits,
            "credits",
        )
        print(
            "No paid odds request was made."
        )
        return 2

    child = (
        root
        / "scripts"
        / "run_live_market_shadow_current.py"
    )

    command = [
        sys.executable,
        str(child),
        "--season",
        args.season,
        "--gameweek",
        str(args.gameweek),
        "--simulation-count",
        str(args.simulation_count),
    ]

    if args.offline_odds_cache:
        command.append(
            "--offline-odds-cache"
        )

    started = time.time()

    print()
    print(
        "=== BUILDING SNAPSHOT ==="
    )

    result = subprocess.run(
        command,
        cwd=root,
        check=False,
    )

    if result.returncode != 0:
        print()
        print(
            "BLOCKED"
        )
        print(
            "Snapshot pipeline failed "
            f"with exit code "
            f"{result.returncode}."
        )
        return result.returncode

    run_dir = latest_run_dir(
        root,
        args.season,
        created_after=(
            started - 2.0
        ),
    )

    report = build_readiness_report(
        run_dir,
        season=args.season,
        gameweek=args.gameweek,
        deadline=deadline,
        minimum_coverage=(
            args.minimum_coverage
        ),
    )

    report_path = (
        run_dir
        / "snapshot_readiness.json"
    )

    payload = asdict(
        report
    )

    report_path.write_text(
        json.dumps(
            payload,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    print()
    print(
        "=== SNAPSHOT READINESS ==="
    )

    print(
        "status:",
        report.status,
    )

    print(
        "fixtures:",
        report.fixture_count,
    )

    print(
        "player_fixture_rows:",
        report.player_fixture_rows,
    )

    print(
        "market_priors:",
        report.market_prior_count,
    )

    print()
    print_coverage(
        "minutes >= 30",
        report.minutes_30,
    )

    print_coverage(
        "minutes >= 60",
        report.minutes_60,
    )

    print_coverage(
        "p_start >= 0.50",
        report.p_start_050,
    )

    print_coverage(
        "p_appearance >= 0.75",
        report.p_appearance_075,
    )

    print()
    print(
        "goal_priors:",
        report.goals_available,
    )

    print(
        "assist_priors:",
        report.assists_available,
    )

    if report.reasons:
        print()
        print(
            "reasons:"
        )

        for reason in report.reasons:
            print(
                " -",
                reason,
            )

    print()
    print(
        "run_dir:",
        run_dir,
    )

    print(
        "readiness_report:",
        report_path,
    )

    print()
    print(
        "=== FINAL STATUS:",
        report.status,
        "===",
    )

    if report.status == "BLOCKED":
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
