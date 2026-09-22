from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path


RUN = "20260911T214014Z"

TARGETS = {
    "Diop",
    "Groß",
    "Hall",
    "Mbeumo",
    "N.Williams",
    "Shaw",
    "Xhaka",
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


players = load(
    "current_players.json"
)

minutes = load(
    "minutes.json"
)

events = load(
    "event_projections.json"
)

projections = load(
    "player_projections.json"
)


names = {
    row["player_id"]:
    row["display_name"]
    for row in players
}


#
# minute-model rows
#

minute_by_key = {
    (
        str(row["player_id"]),
        str(row["fixture_id"]),
    ): row
    for row in minutes
}


#
# actual rates supplied to fixture simulation
#

event_by_key = {}

for fixture in events:

    for side in (
        "home",
        "away",
    ):

        team = fixture.get(
            side,
            {}
        )

        for player in team.get(
            "players",
            []
        ):

            rates = player.get(
                "rates",
                {}
            )

            if (
                "player_id" not in rates
                or "fixture_id" not in rates
            ):
                continue

            key = (
                str(rates["player_id"]),
                str(rates["fixture_id"]),
            )

            event_by_key[key] = rates


#
# map fixture -> GW per player
#

fixture_gw = {}

projection_gw = {}

for player in projections:

    player_id = str(
        player["player_id"]
    )

    for gw in player.get(
        "gameweeks",
        []
    ):

        gameweek = int(
            gw["target_gameweek"]
        )

        projection_gw[
            (
                player_id,
                gameweek,
            )
        ] = gw

        for fixture_id in gw.get(
            "fixture_ids",
            []
        ):

            fixture_gw[
                (
                    player_id,
                    str(fixture_id),
                )
            ] = gameweek


#
# global agreement audit
#

common = (
    set(minute_by_key)
    & set(event_by_key)
)

print()
print(
    "=== MINUTES -> SIMULATION RATE CONSISTENCY ==="
)

print(
    "minute rows:",
    len(minute_by_key),
)

print(
    "event-rate rows:",
    len(event_by_key),
)

print(
    "common rows:",
    len(common),
)


for field in (
    "expected_minutes",
    "p_appearance",
    "p_start",
):

    differences = []

    for key in common:

        left = float(
            minute_by_key[key][field]
        )

        right = float(
            event_by_key[key][field]
        )

        differences.append(
            abs(left - right)
        )

    print(
        field,
        "| max abs diff:",
        (
            f"{max(differences):.12f}"
            if differences
            else "N/A"
        ),
    )


#
# target-player fixture detail
#

print()
print(
    "=== TARGET PLAYER DETAIL ==="
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

    rows = []

    for (
        pid,
        fixture_id,
    ), minute_row in minute_by_key.items():

        if pid != player_id:
            continue

        gameweek = fixture_gw.get(
            (
                player_id,
                fixture_id,
            )
        )

        if gameweek is None:
            continue

        event_row = event_by_key.get(
            (
                player_id,
                fixture_id,
            )
        )

        rows.append(
            (
                gameweek,
                fixture_id,
                minute_row,
                event_row,
            )
        )

    rows.sort(
        key=lambda item: (
            item[0],
            item[1],
        )
    )

    for (
        gameweek,
        fixture_id,
        minute_row,
        event_row,
    ) in rows:

        projection_row = (
            projection_gw.get(
                (
                    player_id,
                    gameweek,
                )
            )
        )

        simulated_minutes = (
            float(
                projection_row[
                    "expected_minutes"
                ]
            )
            if projection_row
            else float("nan")
        )

        if event_row is None:

            print(
                f"GW{gameweek} "
                "| EVENT RATE MISSING"
            )

            continue

        print(
            f"GW{gameweek} "
            f"| model mins "
            f"{float(minute_row['expected_minutes']):6.2f} "
            f"| sim mins "
            f"{simulated_minutes:6.2f} "
            f"| app "
            f"{float(event_row['p_appearance']):.3f} "
            f"| start "
            f"{float(event_row['p_start']):.3f}"
        )


print()
print(
    "=== VARIATION CHECK ==="
)


for player_id, name in sorted(
    names.items(),
    key=lambda item: item[1],
):

    if name not in TARGETS:
        continue

    appearance = []
    starts = []
    model_minutes = []

    for (
        pid,
        fixture_id,
    ), row in event_by_key.items():

        if pid != player_id:
            continue

        if (
            player_id,
            fixture_id,
        ) not in fixture_gw:
            continue

        appearance.append(
            round(
                float(
                    row[
                        "p_appearance"
                    ]
                ),
                12,
            )
        )

        starts.append(
            round(
                float(
                    row[
                        "p_start"
                    ]
                ),
                12,
            )
        )

        model_minutes.append(
            round(
                float(
                    row[
                        "expected_minutes"
                    ]
                ),
                8,
            )
        )

    print(
        name,
        "| unique app:",
        len(set(appearance)),
        "| unique start:",
        len(set(starts)),
        "| unique mins:",
        len(set(model_minutes)),
    )
