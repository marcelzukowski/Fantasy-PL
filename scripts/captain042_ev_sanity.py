from pathlib import Path
import json

from fpl_engine.decision.appearance import (
    build_gameweek_appearance,
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


projections = adapt_player_projections(
    projection_rows
)

appearance = build_gameweek_appearance(
    projection_rows=projection_rows,
    minutes_rows=minute_rows,
)


meta = {
    str(row["player_id"]): row
    for row in player_rows
}


def name(player_id):
    row = meta[player_id]

    return str(
        row.get("display_name")
        or row.get("web_name")
        or row.get("name")
        or player_id
    )


def position(player_id):
    row = meta[player_id]

    value = (
        row.get("position")
        or row.get("position_name")
    )

    if value:
        value = str(value).upper()

        return {
            "GKP": "GK",
            "GOALKEEPER": "GK",
            "DEFENDER": "DEF",
            "MIDFIELDER": "MID",
            "FORWARD": "FWD",
        }.get(
            value,
            value,
        )

    return {
        1: "GK",
        2: "DEF",
        3: "MID",
        4: "FWD",
        "1": "GK",
        "2": "DEF",
        "3": "MID",
        "4": "FWD",
    }.get(
        row.get("element_type"),
        "?",
    )


for gw in range(4, 10):

    ranked = []

    for player in projections:

        for row in player.gameweeks:

            if row.gameweek != gw:
                continue

            player_id = player.player_id

            ranked.append(
                (
                    float(row.expected_points),
                    float(
                        appearance[player_id][gw]
                    ),
                    position(player_id),
                    name(player_id),
                )
            )

    ranked.sort(
        reverse=True
    )

    print()
    print(
        f"=== GW{gw} TOP 10 ==="
    )

    for ev, p_app, pos, player_name in ranked[:10]:

        print(
            f"{player_name:<22} "
            f"{pos:<3} "
            f"EV={ev:5.2f} "
            f"p_app={p_app:.3f}"
        )
