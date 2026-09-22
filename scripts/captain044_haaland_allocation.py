from pathlib import Path
import json
import re
import unicodedata


RUN = Path(
    "scratch/decision/"
    "production_minutes_v2_smoke_seed42_20260912T202455Z/"
    "output/2026-27/"
    "20260912T100351Z"
)


def load(name):
    return json.loads(
        (RUN / name).read_text(
            encoding="utf-8-sig"
        )
    )


def norm(x):
    x = unicodedata.normalize(
        "NFKD",
        str(x),
    ).casefold()

    return re.sub(
        r"[^a-z0-9]+",
        "",
        x,
    )


players = load(
    "current_players.json"
)

projections = load(
    "player_projections.json"
)

events = load(
    "event_projections.json"
)


def display(row):
    return str(
        row.get("display_name")
        or row.get("web_name")
        or row.get("name")
        or ""
    )


haaland_rows = [
    row
    for row in players
    if norm(display(row))
    == norm("Haaland")
]

assert len(haaland_rows) == 1

HAALAND = str(
    haaland_rows[0]["player_id"]
)


projection = next(
    row
    for row in projections
    if str(row["player_id"])
    == HAALAND
)


event_by_fixture = {
    str(row["fixture_id"]): row
    for row in events
}


print(
    "=== HAALAND ATTACK ALLOCATION ==="
)


for gw in projection["gameweeks"]:

    gameweek = gw.get(
        "target_gameweek"
    )

    if gameweek not in range(
        4,
        10,
    ):
        continue


    fixture_id = str(
        gw["fixture_ids"][0]
    )

    fixture = event_by_fixture[
        fixture_id
    ]


    found = None
    opponent = None


    for side_name, other_name in (
        ("home", "away"),
        ("away", "home"),
    ):

        side = fixture[
            side_name
        ]

        for player in side.get(
            "players",
            [],
        ):

            player_id = (
                player.get("player_id")
                or player.get(
                    "rates",
                    {}
                ).get("player_id")
            )

            if str(player_id) == HAALAND:

                found = (
                    side_name,
                    side,
                    player,
                )

                opponent = fixture[
                    other_name
                ]

                break

        if found:
            break


    if not found:

        raise RuntimeError(
            f"Haaland missing in "
            f"{fixture_id}"
        )


    side_name, side, player = found

    goals = player.get(
        "goals",
        {},
    )

    assists = player.get(
        "assists",
        {},
    )

    rates = player.get(
        "rates",
        {},
    )


    team_xg = float(
        side.get(
            "expected_team_goals",
            0.0,
        )
    )

    allocated_goals = float(
        side.get(
            "allocated_player_goals",
            0.0,
        )
    )

    player_xg = float(
        goals.get(
            "expected_goals",
            0.0,
        )
    )

    player_npxg_raw = float(
        rates.get(
            "raw_expected_npxg",
            0.0,
        )
    )

    player_xa = float(
        assists.get(
            "expected_assists",
            0.0,
        )
    )

    share_team = (
        player_xg / team_xg
        if team_xg > 0
        else 0.0
    )

    share_allocated = (
        player_xg
        / allocated_goals
        if allocated_goals > 0
        else 0.0
    )


    print()
    print(
        f"GW{gameweek} "
        f"{side_name.upper()}"
    )

    print(
        f"  team xG:              "
        f"{team_xg:.3f}"
    )

    print(
        f"  allocated player xG:  "
        f"{allocated_goals:.3f}"
    )

    print(
        f"  Haaland total xG:     "
        f"{player_xg:.3f}"
    )

    print(
        f"  Haaland raw npxG:     "
        f"{player_npxg_raw:.3f}"
    )

    print(
        f"  Haaland xA:           "
        f"{player_xa:.3f}"
    )

    print(
        f"  share of team xG:     "
        f"{share_team:.1%}"
    )

    print(
        f"  share allocated xG:   "
        f"{share_allocated:.1%}"
    )

    print(
        f"  opponent team xG:     "
        f"{float(opponent.get('expected_team_goals', 0.0)):.3f}"
    )
