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


TARGETS = (
    ("Haaland", "FWD"),
    ("B.Fernandes", "MID"),
    ("Palmer", "MID"),
    ("Sels", "GK"),
    ("Kelleher", "GK"),
    ("Raya", "GK"),
)


def load(name):
    return json.loads(
        (RUN / name).read_text(
            encoding="utf-8-sig"
        )
    )


def norm(value):
    value = unicodedata.normalize(
        "NFKD",
        str(value),
    ).casefold()

    return re.sub(
        r"[^a-z0-9]+",
        "",
        value,
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


def name(row):
    return str(
        row.get("display_name")
        or row.get("web_name")
        or row.get("name")
        or row.get("player_id")
    )


def position(row):
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


def resolve(
    wanted_name,
    wanted_position,
):
    matches = [
        row
        for row in players
        if (
            norm(name(row))
            == norm(wanted_name)
            and position(row)
            == wanted_position
        )
    ]

    if len(matches) != 1:
        raise RuntimeError(
            f"{wanted_name}/{wanted_position}: "
            f"{[(name(x), position(x)) for x in matches]}"
        )

    return str(
        matches[0]["player_id"]
    )


target_ids = {
    resolve(n, p): (n, p)
    for n, p in TARGETS
}


projection_by_id = {
    str(row["player_id"]): row
    for row in projections
}


#
# event_projections:
# fixture -> home/away -> players
#
event_player = {}


for fixture in events:

    fixture_id = str(
        fixture["fixture_id"]
    )

    for side_name in (
        "home",
        "away",
    ):

        side = fixture.get(
            side_name,
            {}
        )

        for row in side.get(
            "players",
            []
        ):

            rates = row.get(
                "rates",
                {},
            )

            player_id = (
                row.get("player_id")
                or rates.get("player_id")
            )

            if player_id is None:
                continue

            event_player[
                (
                    str(player_id),
                    fixture_id,
                )
            ] = row


def f(value, digits=3):
    if value is None:
        return "-"

    try:
        return (
            f"{float(value):.{digits}f}"
        )
    except Exception:
        return str(value)


for player_id, (
    player_name,
    pos,
) in target_ids.items():

    row = projection_by_id[
        player_id
    ]

    print()
    print(
        "=" * 76
    )

    print(
        f"{player_name} [{pos}]"
    )

    print(
        "=" * 76
    )


    for gwrow in row.get(
        "gameweeks",
        [],
    ):

        gw = gwrow.get(
            "target_gameweek",
            gwrow.get("gameweek"),
        )

        if gw not in range(
            4,
            10,
        ):
            continue


        print()
        print(
            f"GW{gw}  "
            f"EV={f(gwrow.get('expected_points'))}  "
            f"MIN={f(gwrow.get('expected_minutes'), 1)}  "
            f"blank={f(gwrow.get('p_blank'))}  "
            f"return={f(gwrow.get('p_return'))}  "
            f"5+={f(gwrow.get('p_5_plus'))}  "
            f"8+={f(gwrow.get('p_8_plus'))}  "
            f"10+={f(gwrow.get('p_10_plus'))}"
        )


        for fixture_id in gwrow.get(
            "fixture_ids",
            [],
        ):

            detail = event_player.get(
                (
                    player_id,
                    str(fixture_id),
                )
            )

            if detail is None:

                print(
                    "  fixture "
                    f"{fixture_id}: "
                    "NO EVENT PLAYER ROW"
                )

                continue


            rates = detail.get(
                "rates",
                {},
            )

            goals = detail.get(
                "goals",
                {},
            )

            assists = detail.get(
                "assists",
                {},
            )

            cs = detail.get(
                "clean_sheet",
                {},
            )

            goalkeeper = detail.get(
                "goalkeeper",
                {},
            )

            bps = detail.get(
                "bps",
                {},
            )

            penalty = detail.get(
                "penalty",
                {},
            )


            print(
                "  "
                f"pApp={f(rates.get('p_appearance'))}  "
                f"pStart={f(rates.get('p_start'))}  "
                f"min={f(rates.get('expected_minutes'), 1)}  "
                f"xG={f(goals.get('expected_goals'))}  "
                f"xA={f(assists.get('expected_assists'))}  "
                f"pGoal={f(goals.get('p_goal'))}  "
                f"pAst={f(assists.get('p_assist'))}"
            )

            print(
                "  "
                f"CS_team={f(cs.get('team_clean_sheet_probability'))}  "
                f"CS_player={f(cs.get('player_clean_sheet_probability'))}  "
                f"saves={f(goalkeeper.get('expected_saves'))}  "
                f"BPSraw={f(bps.get('raw_bps_expectation'))}  "
                f"pen_xG={f(penalty.get('expected_penalty_goals'))}"
            )
