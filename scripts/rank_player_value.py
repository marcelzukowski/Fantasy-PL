from __future__ import annotations

import argparse
import json
from pathlib import Path

from fpl_engine.decision import (
    adapt_player_projections,
    build_player_values,
    rank_player_values,
)


POSITIONS = (
    "GK",
    "DEF",
    "MID",
    "FWD",
)


def load_json(
    path: Path,
):
    return json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )


def latest_run(
    root: Path,
    season: str,
) -> Path:

    base = (
        root
        / "scratch"
        / "book003"
        / "current_market_shadow"
        / season.replace(
            "/",
            "-",
        )
    )

    candidates = [
        path.parent
        for path in base.glob(
            "*/player_projections.json"
        )
    ]

    if not candidates:
        raise SystemExit(
            "No projection run found"
        )

    return max(
        candidates,
        key=lambda path: (
            (
                path
                / "player_projections.json"
            ).stat().st_mtime
        ),
    )


def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--season",
        default="2026/27",
    )

    parser.add_argument(
        "--metric",
        choices=(
            "ev3",
            "ev6",
            "value3",
            "value6",
        ),
        default="ev6",
    )

    parser.add_argument(
        "--position",
        choices=POSITIONS,
    )

    parser.add_argument(
        "--max-price",
        type=float,
    )

    parser.add_argument(
        "--min-minutes",
        type=float,
        default=0.0,
    )

    parser.add_argument(
        "--top",
        type=int,
        default=5,
    )

    args = parser.parse_args()

    root = Path(
        __file__
    ).resolve().parents[1]

    run_dir = latest_run(
        root,
        args.season,
    )

    projection_rows = load_json(
        run_dir
        / "player_projections.json"
    )

    player_rows = load_json(
        run_dir
        / "current_players.json"
    )

    metadata = {
        row["player_id"]: row
        for row in player_rows
    }

    projections = (
        adapt_player_projections(
            projection_rows
        )
    )

    values = build_player_values(
        projections,
        metadata,
    )

    positions = (
        (args.position,)
        if args.position
        else POSITIONS
    )

    print()
    print(
        "=== DECISION VALUE RANKING ==="
    )

    print(
        "run:",
        run_dir.name,
    )

    print(
        "metric:",
        args.metric,
    )

    if args.max_price is not None:
        print(
            "max_price:",
            f"£{args.max_price:.1f}m",
        )

    if args.min_minutes:
        print(
            "min_minutes:",
            args.min_minutes,
        )

    report = {
        "run_dir": str(
            run_dir
        ),
        "metric": args.metric,
        "max_price": (
            args.max_price
        ),
        "min_minutes": (
            args.min_minutes
        ),
        "positions": {},
    }

    for position in positions:

        ranked = rank_player_values(
            values,
            position=position,
            metric=args.metric,
            max_price_m=(
                args.max_price
            ),
            min_minutes=(
                args.min_minutes
            ),
        )

        print()
        print(
            f"=== {position} ==="
        )

        report_rows = []

        for index, row in enumerate(
            ranked[:args.top],
            start=1,
        ):

            print(
                f"{index:>2}. "
                f"{row.name:<22} "
                f"£{row.price_m:>4.1f} "
                f"EV3={row.ev_3:>5.2f} "
                f"EV6={row.ev_6:>5.2f} "
                f"V3={row.value_3:>4.2f} "
                f"V6={row.value_6:>4.2f} "
                f"min6={row.minutes_6:>6.1f}"
            )

            report_rows.append({
                "player_id": (
                    row.player_id
                ),
                "name": row.name,
                "position": (
                    row.position
                ),
                "team_id": (
                    row.team_id
                ),
                "provider_team_id": (
                    row.provider_team_id
                ),
                "price_m": (
                    row.price_m
                ),
                "ev_3": (
                    row.ev_3
                ),
                "ev_6": (
                    row.ev_6
                ),
                "value_3": (
                    row.value_3
                ),
                "value_6": (
                    row.value_6
                ),
                "minutes_3": (
                    row.minutes_3
                ),
                "minutes_6": (
                    row.minutes_6
                ),
                "confidence": (
                    row.confidence
                ),
            })

        report[
            "positions"
        ][position] = report_rows

    output_path = (
        run_dir
        / "decision_value_rankings.json"
    )

    output_path.write_text(
        json.dumps(
            report,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    print()
    print(
        "saved:",
        output_path,
    )


if __name__ == "__main__":
    main()
