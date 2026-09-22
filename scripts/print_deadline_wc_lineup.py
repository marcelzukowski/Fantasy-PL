import json
from dataclasses import asdict
from pathlib import Path
from pprint import pprint

from fpl_engine.decision import (
    adapt_player_projections,
)

from fpl_engine.decision.availability_adapter import (
    build_gameweek_availability,
)

from fpl_engine.decision.autosubs import (
    optimize_autosub_lineup,
)


ROOT = Path.cwd()

RUN = (
    ROOT
    / "scratch"
    / "book003"
    / "current_market_shadow"
    / "2026-27"
    / "20260912T082141Z"
)


def load(name):
    return json.loads(
        (RUN / name).read_text(
            encoding="utf-8"
        )
    )


players = load(
    "current_players.json"
)

projection_rows = load(
    "player_projections.json"
)

minutes = load(
    "minutes.json"
)


metadata = {
    row["player_id"]: row
    for row in players
}

TARGET = (
    ("Kelleher", "GK"),
    ("Kinsky", "GK"),

    ("Ajayi", "DEF"),
    ("Egan", "DEF"),
    ("Giles", "DEF"),
    ("Hall", "DEF"),
    ("N.Williams", "DEF"),

    ("B.Fernandes", "MID"),
    ("Gro\u00df", "MID"),
    ("Palmer", "MID"),
    ("Tielemans", "MID"),
    ("Wharton", "MID"),

    ("Haaland", "FWD"),
    ("Jo\u00e3o Pedro", "FWD"),
    ("Evanilson", "FWD"),
)


def resolve_player(
    display_name,
    position,
):

    matches = [
        row
        for row in players
        if (
            row["display_name"]
            == display_name
            and row["position"]
            == position
        )
    ]

    if len(matches) != 1:

        print()
        print(
            "LOOKUP FAILURE:",
            display_name,
            position,
        )

        print(
            "all same-name rows:",
        )

        for row in players:

            if (
                row["display_name"]
                == display_name
            ):
                print(
                    row["player_id"],
                    row["display_name"],
                    row["position"],
                    row.get("team_id"),
                )

        raise RuntimeError(
            f"Expected exactly one "
            f"{display_name} ({position}), "
            f"found {len(matches)}"
        )

    return matches[0]["player_id"]


squad_ids = tuple(
    resolve_player(
        display_name,
        position,
    )
    for display_name, position
    in TARGET
)


print()
print(
    "=== RESOLVED WC SQUAD ==="
)

for (
    display_name,
    expected_position,
), player_id in zip(
    TARGET,
    squad_ids,
):
    row = metadata[player_id]

    print(
        f"{expected_position:3} | "
        f"{display_name:15} | "
        f"id={player_id} | "
        f"actual={row['position']}"
    )


shape = {}

for player_id in squad_ids:

    position = metadata[
        player_id
    ]["position"]

    shape[position] = (
        shape.get(position, 0)
        + 1
    )


print()
print(
    "resolved shape:",
    shape,
)


expected_shape = {
    "GK": 2,
    "DEF": 5,
    "MID": 5,
    "FWD": 3,
}

if shape != expected_shape:
    raise RuntimeError(
        f"Still invalid squad shape: "
        f"{shape}"
    )



projections = {
    row.player_id: row
    for row in adapt_player_projections(
        projection_rows
    )
}


availability = (
    build_gameweek_availability(
        projection_rows,
        minutes,
    )
)


def gw4_ev(player_id):

    for row in (
        projections[
            player_id
        ].gameweeks
    ):

        if row.gameweek == 4:
            return float(
                row.expected_points
            )

    raise RuntimeError(
        f"GW4 missing: {player_id}"
    )


points = {
    player_id:
    gw4_ev(player_id)
    for player_id
    in squad_ids
}


positions = {
    player_id:
    metadata[
        player_id
    ]["position"]
    for player_id
    in squad_ids
}


appearance = {
    player_id:
    availability[
        (
            player_id,
            4,
        )
    ].p_appearance
    for player_id
    in squad_ids
}


lineup = optimize_autosub_lineup(
    gameweek=4,
    squad_ids=squad_ids,
    positions=positions,
    expected_points=points,
    p_appearance=appearance,
)


names = {
    player_id:
    metadata[
        player_id
    ]["display_name"]
    for player_id
    in squad_ids
}


def convert(value):

    if isinstance(value, str):
        return names.get(
            value,
            value,
        )

    if isinstance(value, tuple):
        return tuple(
            convert(x)
            for x in value
        )

    if isinstance(value, list):
        return [
            convert(x)
            for x in value
        ]

    if isinstance(value, dict):
        return {
            key:
            convert(item)
            for key, item
            in value.items()
        }

    return value


print()
print(
    "=== FINAL WC GW4 LINEUP ==="
)
print()

pprint(
    convert(
        asdict(lineup)
    ),
    sort_dicts=False,
)
