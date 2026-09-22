from __future__ import annotations

import json
from pathlib import Path

from fpl_engine.decision.availability_adapter import (
    build_gameweek_availability,
)


RUN = "20260911T214014Z"

TARGETS = {
    "N.Williams",
    "Shaw",
    "Hall",
    "Xhaka",
    "Groß",
    "Mbeumo",
    "Diop",
}


root = Path.cwd()

run_dir = (
    root
    / "scratch"
    / "book003"
    / "current_market_shadow"
    / "2026-27"
    / RUN
)


def load(name):
    return json.loads(
        (
            run_dir
            / name
        ).read_text(
            encoding="utf-8"
        )
    )


projections = load(
    "player_projections.json"
)

minutes = load(
    "minutes.json"
)

players = load(
    "current_players.json"
)

availability = (
    build_gameweek_availability(
        projections,
        minutes,
    )
)

names = {
    row["player_id"]:
    row["display_name"]
    for row in players
}


print()
print(
    "=== DECISION AVAILABILITY AUDIT ==="
)


for player_id, name in sorted(
    names.items(),
    key=lambda item: item[1],
):

    if name not in TARGETS:
        continue

    print()
    print(
        "================================"
    )
    print(name)

    for gw in range(
        4,
        10,
    ):

        row = availability.get(
            (
                player_id,
                gw,
            )
        )

        if row is None:
            print(
                f"GW{gw}: MISSING"
            )
            continue

        print(
            f"GW{gw}: "
            f"mins={row.expected_minutes:6.2f} | "
            f"app={row.p_appearance:.3f} | "
            f"start={row.p_start:.3f} | "
            f"zero={row.p_zero_minutes:.3f}"
        )
