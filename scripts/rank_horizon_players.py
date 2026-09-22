from __future__ import annotations

import argparse
import json
from pathlib import Path

from fpl_engine.decision import (
    adapt_player_projections,
    rank_player_projections,
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
            "No player projection run found"
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
        "--top",
        type=int,
        default=20,
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

    current_players = load_json(
        run_dir
        / "current_players.json"
    )

    metadata = {
        row["player_id"]: row
        for row in current_players
    }

    adapted = (
        adapt_player_projections(
            projection_rows
        )
    )

    ranked_3 = (
        rank_player_projections(
            adapted,
            horizon=3,
        )
    )

    ranked_6 = (
        rank_player_projections(
            adapted,
            horizon=6,
        )
    )

    def output_row(
        player,
    ):
        meta = metadata.get(
            player.player_id,
            {},
        )

        return {
            "player_id": (
                player.player_id
            ),
            "name": meta.get(
                "display_name",
                player.player_id,
            ),
            "position": (
                meta.get("position")
                or meta.get(
                    "position_name"
                )
                or meta.get(
                    "element_type"
                )
            ),
            "team": (
                meta.get("team_name")
                or meta.get(
                    "team"
                )
                or meta.get(
                    "team_id"
                )
            ),
            "weighted_ev_3": (
                player.horizon_3
                .weighted_expected_points
            ),
            "weighted_ev_6": (
                player.horizon_6
                .weighted_expected_points
            ),
            "raw_ev_3": (
                player.horizon_3
                .raw_expected_points
            ),
            "raw_ev_6": (
                player.horizon_6
                .raw_expected_points
            ),
            "minutes_3": (
                player
                .expected_minutes_next_3
            ),
            "minutes_6": (
                player
                .expected_minutes_next_6
            ),
            "confidence": (
                player
                .projection_confidence
            ),
            "uncertainty": (
                player
                .projection_uncertainty
            ),
        }

    report = {
        "run_dir": str(
            run_dir
        ),
        "season": args.season,
        "player_count": len(
            adapted
        ),
        "top_3gw": [
            output_row(player)
            for player in ranked_3
        ],
        "top_6gw": [
            output_row(player)
            for player in ranked_6
        ],
    }

    output_path = (
        run_dir
        / "decision_horizon_rankings.json"
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
        "=== DECISION ENGINE HORIZON RANKING ==="
    )

    print(
        "run:",
        run_dir.name,
    )

    print(
        "players:",
        len(adapted),
    )

    print()
    print(
        "=== TOP 3 GW ==="
    )

    for index, player in enumerate(
        ranked_3[:args.top],
        start=1,
    ):
        row = output_row(
            player
        )

        print(
            f"{index:>2}. "
            f"{row['name']:<24} "
            f"EV3={row['weighted_ev_3']:>6.2f} "
            f"EV6={row['weighted_ev_6']:>6.2f} "
            f"min3={row['minutes_3']:>6.1f} "
            f"conf={row['confidence']:.2f}"
        )

    print()
    print(
        "=== TOP 6 GW ==="
    )

    for index, player in enumerate(
        ranked_6[:args.top],
        start=1,
    ):
        row = output_row(
            player
        )

        print(
            f"{index:>2}. "
            f"{row['name']:<24} "
            f"EV6={row['weighted_ev_6']:>6.2f} "
            f"EV3={row['weighted_ev_3']:>6.2f} "
            f"min6={row['minutes_6']:>6.1f} "
            f"conf={row['confidence']:.2f}"
        )

    print()
    print(
        "saved:",
        output_path,
    )


if __name__ == "__main__":
    main()
