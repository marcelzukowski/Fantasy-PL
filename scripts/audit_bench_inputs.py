from __future__ import annotations

import json
import unicodedata
from pathlib import Path


RUN = "20260911T214014Z"

TARGETS = {
    "shaw",
    "diop",
    "mbeumo",
    "xhaka",
    "hall",
    "nwilliams",
    "gross",
}


def norm(value):
    text = unicodedata.normalize(
        "NFKD",
        str(value),
    )

    text = "".join(
        c
        for c in text
        if not unicodedata.combining(c)
    )

    return (
        text.casefold()
        .replace(".", "")
        .replace("-", "")
        .replace(" ", "")
    )


root = Path.cwd()

run_dir = (
    root
    / "scratch"
    / "book003"
    / "current_market_shadow"
    / "2026-27"
    / RUN
)

projections = json.loads(
    (
        run_dir
        / "player_projections.json"
    ).read_text(
        encoding="utf-8"
    )
)

players = json.loads(
    (
        run_dir
        / "current_players.json"
    ).read_text(
        encoding="utf-8"
    )
)

metadata = {
    row["player_id"]: row
    for row in players
}

print()
print(
    "=== BENCH / APPEARANCE DATA AUDIT ==="
)


for row in projections:

    player_id = row[
        "player_id"
    ]

    meta = metadata.get(
        player_id
    )

    if meta is None:
        continue

    name = meta[
        "display_name"
    ]

    if norm(name) not in TARGETS:
        continue

    print()
    print(
        "================================"
    )

    print(
        name,
        "|",
        meta["position"],
        "| price",
        meta["current_price"],
    )

    print()
    print(
        "TOP-LEVEL PROJECTION KEYS:"
    )

    print(
        sorted(
            row.keys()
        )
    )

    print()
    print(
        "TOP-LEVEL AVAILABILITY FIELDS:"
    )

    for key in sorted(
        row.keys()
    ):
        lower = key.lower()

        if any(
            token in lower
            for token in (
                "minute",
                "start",
                "appear",
                "play",
                "avail",
                "prob",
            )
        ):
            print(
                f"  {key}:",
                row[key],
            )

    print()
    print(
        "PER-GW:"
    )

    for gw in row.get(
        "gameweeks",
        []
    ):

        gameweek = gw.get(
            "gameweek"
        )

        if (
            gameweek is None
            or not (
                4
                <= int(gameweek)
                <= 9
            )
        ):
            continue

        print()
        print(
            f"  GW{gameweek}"
        )

        print(
            "   keys:",
            sorted(
                key
                for key in gw.keys()
                if key
                != "points_distribution"
            ),
        )

        for key in sorted(
            gw.keys()
        ):

            if key == "points_distribution":
                continue

            lower = key.lower()

            if (
                key
                == "expected_points"
                or any(
                    token in lower
                    for token in (
                        "minute",
                        "start",
                        "appear",
                        "play",
                        "avail",
                        "prob",
                    )
                )
            ):
                print(
                    f"   {key}:",
                    gw[key],
                )
