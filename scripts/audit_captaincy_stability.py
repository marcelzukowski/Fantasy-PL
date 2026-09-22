from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from fpl_engine.decision import (
    adapt_player_projections,
)


ACTIVE_GAMEWEEK = 4
MIN_SIMULATIONS = 64
HORIZON = 6


def load_json(path):
    return json.loads(
        Path(path).read_text(
            encoding="utf-8"
        )
    )


def estimate_simulation_count(
    rows,
):
    probabilities = []

    for player in rows:
        for gw in player.get(
            "gameweeks",
            []
        ):
            for value in gw.get(
                "points_distribution",
                {}
            ).values():

                value = float(value)

                if 0.0 < value < 1.0:
                    probabilities.append(
                        value
                    )

    if not probabilities:
        return 1

    return round(
        1.0
        / min(probabilities)
    )


root = Path.cwd()

base = (
    root
    / "scratch"
    / "book003"
    / "current_market_shadow"
    / "2026-27"
)

runs = []

for path in base.glob(
    "*/player_projections.json"
):

    raw_rows = load_json(
        path
    )

    if not raw_rows:
        continue

    if (
        raw_rows[0].get(
            "current_gameweek"
        )
        != ACTIVE_GAMEWEEK
    ):
        continue

    simulations = (
        estimate_simulation_count(
            raw_rows
        )
    )

    if simulations >= MIN_SIMULATIONS:
        runs.append(
            (
                path.parent,
                simulations,
            )
        )


runs.sort(
    key=lambda item: item[0].name
)


consensus = {
    gameweek: []
    for gameweek in range(
        ACTIVE_GAMEWEEK,
        ACTIVE_GAMEWEEK + HORIZON,
    )
}


print()
print(
    "=== CAPTAINCY STABILITY AUDIT ==="
)


for run_dir, simulations in runs:

    raw_projections = load_json(
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

    projections = (
        adapt_player_projections(
            raw_projections
        )
    )

    print()
    print(
        "================================"
    )

    print(
        "RUN:",
        run_dir.name,
        "| simulations:",
        simulations,
    )

    for gameweek in range(
        ACTIVE_GAMEWEEK,
        ACTIVE_GAMEWEEK + HORIZON,
    ):

        candidates = []

        for projection in projections:

            meta = metadata.get(
                projection.player_id
            )

            if meta is None:
                continue

            gw_projection = next(
                (
                    gw
                    for gw
                    in projection.gameweeks
                    if gw.gameweek
                    == gameweek
                ),
                None,
            )

            if gw_projection is None:
                continue

            candidates.append(
                {
                    "player_id": (
                        projection.player_id
                    ),
                    "name": (
                        meta["display_name"]
                    ),
                    "position": (
                        meta["position"]
                    ),
                    "points": float(
                        gw_projection
                        .expected_points
                    ),
                    "confidence": float(
                        projection
                        .projection_confidence
                    ),
                }
            )

        candidates.sort(
            key=lambda row: (
                row["points"]
            ),
            reverse=True,
        )

        top = candidates[:5]

        print()
        print(
            f"GW{gameweek}"
        )

        if not top:
            print(
                " NO PROJECTIONS FOUND"
            )
            continue

        for index, row in enumerate(
            top,
            start=1,
        ):

            print(
                f" {index}. "
                f"{row['name']} "
                f"({row['position']}) "
                f"EV={row['points']:.2f} "
                f"conf={row['confidence']:.2f}"
            )

        margin = (
            top[0]["points"]
            - top[1]["points"]
            if len(top) >= 2
            else 0.0
        )

        consensus[
            gameweek
        ].append(
            {
                "run": (
                    run_dir.name
                ),
                "name": (
                    top[0]["name"]
                ),
                "position": (
                    top[0]["position"]
                ),
                "ev": (
                    top[0]["points"]
                ),
                "margin": (
                    margin
                ),
            }
        )


print()
print(
    "================================"
)
print(
    "=== CAPTAIN CONSENSUS ==="
)

for gameweek, records in (
    consensus.items()
):

    names = [
        row["name"]
        for row in records
    ]

    print()
    print(
        f"GW{gameweek}:",
        names,
    )

    if not names:
        print(
            "top-1 consensus: NO DATA"
        )
        continue

    counts = Counter(
        names
    )

    top_name, top_count = (
        counts.most_common(1)[0]
    )

    print(
        "top-1 consensus:",
        len(set(names)) == 1,
    )

    print(
        "consensus leader:",
        top_name,
        f"({top_count}/{len(names)})",
    )

    for row in records:

        print(
            " ",
            row["run"],
            "|",
            row["name"],
            f"({row['position']})",
            "| EV",
            f"{row['ev']:.2f}",
            "| margin",
            f"{row['margin']:+.2f}",
        )
