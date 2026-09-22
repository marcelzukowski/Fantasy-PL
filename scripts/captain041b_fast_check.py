from pathlib import Path
from types import SimpleNamespace
import json
import re
import unicodedata

from fpl_engine.decision.appearance import (
    build_gameweek_appearance,
)

from fpl_engine.decision.captaincy import (
    evaluate_squad_with_captaincy,
)

from fpl_engine.decision.captaincy_v2 import (
    evaluate_squad_with_captaincy_v2,
)

from fpl_engine.decision.projection_adapter import (
    adapt_player_projections,
)


RUN = Path(
    "scratch/decision/"
    "production_minutes_v2_smoke_seed42_20260912T202455Z/"
    "output/2026-27/"
    "20260912T100351Z"
)


def rows(path):

    payload = json.loads(
        path.read_text(
            encoding="utf-8-sig"
        )
    )

    if isinstance(payload, list):
        return payload

    if isinstance(payload, dict):

        for key in (
            "rows",
            "data",
            "records",
            "players",
            "projections",
            "minutes",
        ):

            value = payload.get(key)

            if isinstance(value, list):
                return value

    raise RuntimeError(
        f"cannot resolve rows: {path}"
    )


projection_rows = rows(
    RUN / "player_projections.json"
)

minute_rows = rows(
    RUN / "minutes.json"
)

player_rows = rows(
    RUN / "current_players.json"
)


adapted = adapt_player_projections(
    projection_rows
)

projections_by_id = {
    row.player_id: row
    for row in adapted
}


appearance = build_gameweek_appearance(
    projection_rows=projection_rows,
    minutes_rows=minute_rows,
)


def normalize(value):

    value = unicodedata.normalize(
        "NFKD",
        str(value),
    )

    value = value.casefold()

    value = re.sub(
        r"[^a-z0-9]+",
        "",
        value,
    )

    return value


def display_name(row):

    for key in (
        "display_name",
        "web_name",
        "name",
    ):

        value = row.get(key)

        if value:
            return str(value)

    return str(
        row["player_id"]
    )


def position(row):

    value = (
        row.get("position")
        or row.get("position_name")
    )

    if value:

        value = str(value).upper()

        aliases = {
            "GKP": "GK",
            "GOALKEEPER": "GK",
            "DEFENDER": "DEF",
            "MIDFIELDER": "MID",
            "FORWARD": "FWD",
        }

        return aliases.get(
            value,
            value,
        )


    element_type = (
        row.get("element_type")
        or row.get("position_id")
    )

    mapping = {
        1: "GK",
        2: "DEF",
        3: "MID",
        4: "FWD",
        "1": "GK",
        "2": "DEF",
        "3": "MID",
        "4": "FWD",
    }

    if element_type in mapping:
        return mapping[element_type]


    raise RuntimeError(
        "cannot resolve position for "
        + display_name(row)
    )


metadata = {
    str(row["player_id"]): row
    for row in player_rows
}


players_by_id = {}

names_by_id = {}


for player_id, row in metadata.items():

    players_by_id[player_id] = (
        SimpleNamespace(
            player_id=player_id,
            position=position(row),
            team_id=(
                row.get("team_id")
                or row.get("team")
            ),
        )
    )

    names_by_id[player_id] = (
        display_name(row)
    )


#
# Final saved GW4 WC squad.
#
wanted = (
    ("Sels", "GK"),
    ("Maatsen", "DEF"),
    ("Justin", "DEF"),
    ("De Cuyper", "DEF"),
    ("Gross", "MID"),
    ("Tavernier", "MID"),
    ("B Fernandes", "MID"),
    ("Szoboszlai", "MID"),
    ("Palmer", "MID"),
    ("Calvert Lewin", "FWD"),
    ("Haaland", "FWD"),
    ("Kelleher", "GK"),
    ("Evanilson", "FWD"),
    ("Egan", "DEF"),
    ("Giles", "DEF"),
)


def resolve(
    query,
    expected_position,
):

    q = normalize(query)


    exact = [
        player_id
        for player_id, name
        in names_by_id.items()
        if (
            normalize(name) == q
            and position(
                metadata[player_id]
            ) == expected_position
        )
    ]

    if len(exact) == 1:
        return exact[0]


    partial = [
        player_id
        for player_id, name
        in names_by_id.items()
        if (
            q in normalize(name)
            and position(
                metadata[player_id]
            ) == expected_position
        )
    ]

    if len(partial) == 1:
        return partial[0]


    candidates = [
        (
            names_by_id[player_id],
            position(
                metadata[player_id]
            ),
            player_id,
        )
        for player_id in partial
    ]

    raise RuntimeError(
        f"cannot uniquely resolve "
        f"{query!r} "
        f"({expected_position}): "
        f"{candidates}"
    )


squad = frozenset(
    resolve(
        name,
        expected_position,
    )
    for (
        name,
        expected_position,
    )
    in wanted
)


if len(squad) != 15:

    raise RuntimeError(
        f"expected 15 players, "
        f"got {len(squad)}"
    )


old = evaluate_squad_with_captaincy(
    squad_player_ids=squad,
    players_by_id=players_by_id,
    projections_by_id=(
        projections_by_id
    ),
    horizon=6,
)


new = evaluate_squad_with_captaincy_v2(
    squad_player_ids=squad,
    players_by_id=players_by_id,
    projections_by_id=(
        projections_by_id
    ),
    appearance_by_player_gameweek=(
        appearance
    ),
    horizon=6,
)


print()
print("=== RESULT ===")

print(
    "XI EV:",
    round(
        new.weighted_xi_ev,
        3,
    ),
)

print(
    "OLD captain bonus:",
    round(
        old.weighted_captain_bonus_ev,
        3,
    ),
)

print(
    "NEW C+VC bonus:",
    round(
        new.weighted_captain_bonus_ev,
        3,
    ),
)

print(
    "NEW total EV:",
    round(
        new.weighted_total_ev,
        3,
    ),
)

print(
    "C+VC vs old bonus:",
    round(
        (
            new.weighted_captain_bonus_ev
            - old.weighted_captain_bonus_ev
        ),
        3,
    ),
)


print()
print("=== NEW C / VC ===")

for gw in new.gameweeks:

    print(
        f"GW{gw.gameweek}: "
        f"C={names_by_id[gw.captain_player_id]} | "
        f"VC={names_by_id[gw.vice_player_id]} | "
        f"bonus={gw.captain_bonus_ev:.3f}"
    )


print()
print("=== FAST CHECK PASS ===")
