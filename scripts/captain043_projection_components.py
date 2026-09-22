from pathlib import Path
import json
import math
import unicodedata
import re


RUN = Path(
    "scratch/decision/"
    "production_minutes_v2_smoke_seed42_20260912T202455Z/"
    "output/2026-27/"
    "20260912T100351Z"
)


TARGETS = (
    "Haaland",
    "B.Fernandes",
    "Palmer",
    "Sels",
    "Kelleher",
    "Raya",
)


def load(path):
    return json.loads(
        path.read_text(
            encoding="utf-8-sig"
        )
    )


def rows(payload):

    if isinstance(payload, list):
        return payload

    if isinstance(payload, dict):

        for key in (
            "rows",
            "data",
            "records",
            "players",
            "projections",
            "events",
        ):

            value = payload.get(key)

            if isinstance(value, list):
                return value

    return []


def norm(value):

    value = unicodedata.normalize(
        "NFKD",
        str(value),
    )

    value = value.casefold()

    return re.sub(
        r"[^a-z0-9]+",
        "",
        value,
    )


players = rows(
    load(
        RUN / "current_players.json"
    )
)

player_by_id = {
    str(row["player_id"]): row
    for row in players
}


def display(row):

    return str(
        row.get("display_name")
        or row.get("web_name")
        or row.get("name")
        or row.get("player_id")
    )


target_ids = {}


for target in TARGETS:

    matches = [
        str(row["player_id"])
        for row in players
        if norm(display(row))
        == norm(target)
    ]

    if len(matches) != 1:

        #
        # Palmer may be duplicated;
        # prefer MID.
        #
        matches = [
            str(row["player_id"])
            for row in players
            if (
                norm(display(row))
                == norm(target)
                and str(
                    row.get("position")
                    or row.get("position_name")
                    or ""
                ).upper()
                in (
                    "MID",
                    "MIDFIELDER",
                )
            )
        ]

    if len(matches) != 1:

        raise RuntimeError(
            f"{target}: matches={matches}"
        )

    target_ids[
        matches[0]
    ] = target


def numeric_fields(row):

    result = {}

    for key, value in row.items():

        if isinstance(
            value,
            (int, float),
        ) and not isinstance(
            value,
            bool,
        ):

            if math.isfinite(
                float(value)
            ):

                result[key] = float(
                    value
                )

    return result


print(
    "=== PLAYER PROJECTIONS ==="
)


projection_rows = rows(
    load(
        RUN / "player_projections.json"
    )
)


for row in projection_rows:

    player_id = str(
        row.get("player_id")
    )

    if player_id not in target_ids:
        continue

    gameweeks = row.get(
        "gameweeks",
        []
    )

    for gw in gameweeks:

        number = gw.get(
            "gameweek"
        )

        if number not in range(
            4,
            10,
        ):
            continue

        print()
        print(
            f"{target_ids[player_id]} "
            f"GW{number}"
        )

        fields = numeric_fields(
            gw
        )

        for key in sorted(
            fields
        ):

            print(
                f"  {key:<32} "
                f"{fields[key]:.6f}"
            )


event_path = (
    RUN
    / "event_projections.json"
)


if event_path.exists():

    print()
    print(
        "=== EVENT PROJECTIONS ==="
    )

    event_rows = rows(
        load(
            event_path
        )
    )

    for row in event_rows:

        player_id = str(
            row.get("player_id")
        )

        if player_id not in target_ids:
            continue

        gw = (
            row.get("gameweek")
            or row.get("event")
            or row.get(
                "target_gameweek"
            )
        )

        if gw not in range(
            4,
            10,
        ):
            continue

        print()
        print(
            f"{target_ids[player_id]} "
            f"GW{gw}"
        )

        fields = numeric_fields(
            row
        )

        for key in sorted(
            fields
        ):

            print(
                f"  {key:<32} "
                f"{fields[key]:.6f}"
            )

else:

    print()
    print(
        "event_projections.json "
        "not present"
    )
