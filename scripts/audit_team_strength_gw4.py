from __future__ import annotations

import json
from pathlib import Path

ROOT = Path.cwd()

RUN_ROOT = (
    ROOT
    / "scratch"
    / "book003"
    / "current_market_shadow"
    / "2026-27"
)

RUN_ID = "20260912T100351Z"

RUN_PATH = RUN_ROOT / RUN_ID

TEAM_STRENGTH = (
    RUN_PATH
    / "team_strength.json"
)

CURRENT_PLAYERS = (
    RUN_PATH
    / "current_players.json"
)

FIXTURES = (
    RUN_PATH
    / "fixture_horizon.json"
)


def rows(raw):

    if isinstance(raw, list):
        return raw

    if isinstance(raw, dict):

        for key in (
            "rows",
            "data",
            "records",
            "teams",
            "fixtures",
        ):

            value = raw.get(key)

            if isinstance(value, list):
                return value

    return []


def flatten(
    value,
    prefix="",
    out=None,
):

    if out is None:
        out = {}

    if isinstance(value, dict):

        for key, child in value.items():

            path = (
                f"{prefix}.{key}"
                if prefix
                else str(key)
            )

            flatten(
                child,
                path,
                out,
            )

    elif isinstance(value, (list, tuple)):

        if len(value) <= 8:

            for i, child in enumerate(value):

                flatten(
                    child,
                    f"{prefix}[{i}]",
                    out,
                )

    elif isinstance(
        value,
        (str, int, float, bool),
    ) or value is None:

        out[prefix] = value

    return out


players = json.loads(
    CURRENT_PLAYERS.read_text(
        encoding="utf-8"
    )
)

fixtures = rows(
    json.loads(
        FIXTURES.read_text(
            encoding="utf-8"
        )
    )
)

strength_raw = json.loads(
    TEAM_STRENGTH.read_text(
        encoding="utf-8"
    )
)

strength_rows = rows(
    strength_raw
)


targets = {
    "Palmer",
    "Szoboszlai",
    "Groß",
    "Haaland",
    "B.Fernandes",
}


player_map = {}

for row in players:

    name = row.get(
        "display_name"
    )

    if name in targets:

        player_map[name] = {
            "team_id": str(
                row.get("team_id")
            ),
            "provider_team_id": str(
                row.get(
                    "provider_team_id"
                )
            ),
        }


print()
print(
    "TEAM STRENGTH TOP LEVEL:"
)

print(
    type(
        strength_raw
    ).__name__
)

if isinstance(
    strength_raw,
    dict,
):

    print(
        "keys:",
        sorted(
            strength_raw.keys()
        ),
    )

print(
    "strength rows:",
    len(
        strength_rows
    ),
)


# ------------------------------------------------------------
# GW4 fixtures for target teams
# ------------------------------------------------------------

target_team_ids = {
    data["team_id"]
    for data in player_map.values()
}


relevant_fixtures = []

for row in fixtures:

    gw = (
        row.get("gameweek")
        or row.get("target_gameweek")
        or row.get("event")
    )

    if gw is None:
        continue

    if int(gw) != 4:
        continue

    home = str(
        row.get("home_team_id")
    )

    away = str(
        row.get("away_team_id")
    )

    if (
        home in target_team_ids
        or away in target_team_ids
    ):

        relevant_fixtures.append(
            row
        )


print()
print(
    "========================================"
)
print(
    "GW4 FIXTURES"
)
print(
    "========================================"
)

fixture_team_ids = set()

for row in relevant_fixtures:

    flat = flatten(
        row
    )

    print()

    print(
        "fixture_id:",
        row.get("fixture_id"),
    )

    for key in (
        "home_team_id",
        "away_team_id",
        "home_provider_team_id",
        "away_provider_team_id",
        "provider_payload.team_h",
        "provider_payload.team_a",
        "provider_payload.team_h_difficulty",
        "provider_payload.team_a_difficulty",
    ):

        if key in flat:

            print(
                f"  {key:<42} "
                f"{flat[key]}"
            )

    fixture_team_ids.add(
        str(
            row.get(
                "home_team_id"
            )
        )
    )

    fixture_team_ids.add(
        str(
            row.get(
                "away_team_id"
            )
        )
    )


# ------------------------------------------------------------
# strength rows
# ------------------------------------------------------------

print()
print(
    "========================================"
)
print(
    "RELEVANT TEAM STRENGTH ROWS"
)
print(
    "========================================"
)


matches = []

for row in strength_rows:

    if not isinstance(
        row,
        dict,
    ):
        continue

    flat = flatten(
        row
    )

    values = {
        str(v)
        for v in flat.values()
        if v is not None
    }

    if values & fixture_team_ids:

        matches.append(
            row
        )


print(
    "matching rows:",
    len(matches),
)


for i, row in enumerate(
    matches,
    start=1,
):

    print()
    print(
        f"TEAM ROW {i}"
    )

    flat = flatten(
        row
    )

    for key in sorted(
        flat
    ):

        low = key.casefold()

        if any(
            token in low
            for token in (
                "team",
                "attack",
                "defen",
                "strength",
                "rating",
                "goal",
                "xg",
                "home",
                "away",
                "offen",
            )
        ):

            print(
                f"  {key:<46} "
                f"{flat[key]}"
            )


print()
print(
    "========================================"
)
print(
    "PLAYER -> TEAM MAP"
)
print(
    "========================================"
)

for name, data in (
    player_map.items()
):

    print(
        f"{name:<18} "
        f"team={data['team_id']} "
        f"provider={data['provider_team_id']}"
    )


print()
print(
    "=== END ==="
)
