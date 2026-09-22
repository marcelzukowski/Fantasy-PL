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

PLAN_PATH = (
    ROOT
    / "scratch"
    / "decision"
    / "final_wc_playing_plan.json"
)

GW = 4

TARGET_NAMES = (
    "Palmer",
    "Szoboszlai",
    "Groß",
    "Haaland",
    "B.Fernandes",
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
            "events",
        ):

            value = raw.get(key)

            if isinstance(value, list):
                return value

    return []


def row_fixture_id(row):

    for key in (
        "fixture_id",
        "canonical_fixture_id",
        "id",
    ):

        value = row.get(key)

        if value is not None:
            return str(value)

    return None


def row_gw(
    row,
    fixture_to_gw,
):

    for key in (
        "gameweek",
        "target_gameweek",
        "event",
    ):

        value = row.get(key)

        if value is not None:

            try:
                return int(value)
            except Exception:
                pass

    fid = row.get("fixture_id")

    if fid is not None:

        return fixture_to_gw.get(
            str(fid)
        )

    return None


def nested(
    row,
    side,
    field,
):

    value = row.get(side)

    if isinstance(value, dict):

        return value.get(field)

    return None


# ============================================================
# LOAD
# ============================================================

players = json.loads(
    (
        RUN_PATH
        / "current_players.json"
    ).read_text(
        encoding="utf-8"
    )
)

fixture_rows = rows(
    json.loads(
        (
            RUN_PATH
            / "fixture_horizon.json"
        ).read_text(
            encoding="utf-8"
        )
    )
)

minute_rows = rows(
    json.loads(
        (
            RUN_PATH
            / "minutes.json"
        ).read_text(
            encoding="utf-8"
        )
    )
)

strength_rows = rows(
    json.loads(
        (
            RUN_PATH
            / "team_strength.json"
        ).read_text(
            encoding="utf-8"
        )
    )
)

event_rows = rows(
    json.loads(
        (
            RUN_PATH
            / "event_projections.json"
        ).read_text(
            encoding="utf-8"
        )
    )
)


metadata = {
    str(row["player_id"]): row
    for row in players
}

names = {
    pid: row["display_name"]
    for pid, row
    in metadata.items()
}


# ============================================================
# BASE IDS — IMPORTANT: no name-only resolver
# ============================================================

plan = json.loads(
    PLAN_PATH.read_text(
        encoding="utf-8"
    )
)

base = next(
    candidate
    for candidate in plan["candidates"]
    if "BASE_CAND5"
    in candidate["labels"]
)

base_ids = set(
    base["player_ids"]
)


targets = {}

for target_name in TARGET_NAMES:

    matches = [
        pid
        for pid in base_ids
        if names.get(pid)
        == target_name
    ]

    if len(matches) != 1:

        raise RuntimeError(
            f"BASE resolution failed "
            f"{target_name}: {matches}"
        )

    targets[target_name] = (
        matches[0]
    )


# ============================================================
# DUPLICATE SANITY CHECK
# ============================================================

print()
print(
    "============================================"
)
print(
    "PLAYER RESOLUTION"
)
print(
    "============================================"
)

for target_name, pid in (
    targets.items()
):

    all_same_name = [
        other_id
        for other_id, display
        in names.items()
        if display == target_name
    ]

    row = metadata[pid]

    print(
        f"{target_name:<18} "
        f"BASE_ID={pid} "
        f"duplicates={len(all_same_name)} "
        f"team={row.get('team_id')} "
        f"provider={row.get('provider_team_id')}"
    )


# ============================================================
# FIXTURE MAP
# ============================================================

fixture_to_gw = {}

fixture_by_id = {}

for row in fixture_rows:

    fid = row_fixture_id(
        row
    )

    if fid is None:
        continue

    fixture_by_id[fid] = row

    for key in (
        "gameweek",
        "target_gameweek",
        "event",
    ):

        value = row.get(key)

        if value is not None:

            try:
                fixture_to_gw[fid] = int(value)
                break
            except Exception:
                pass


# ============================================================
# EXACT STRENGTH MATCH
# ============================================================

def exact_strength_row(
    fid,
    fixture,
):

    # Best option: exact fixture ID.
    direct = [
        row
        for row in strength_rows
        if row_fixture_id(row)
        == fid
    ]

    if len(direct) == 1:
        return direct[0], "fixture_id"

    # Fallback: exact home/away pair.
    home_id = str(
        fixture.get(
            "home_team_id"
        )
    )

    away_id = str(
        fixture.get(
            "away_team_id"
        )
    )

    pair = [
        row
        for row in strength_rows
        if (
            str(
                row.get(
                    "home_team_id"
                )
            ) == home_id
            and str(
                row.get(
                    "away_team_id"
                )
            ) == away_id
        )
    ]

    if len(pair) == 1:
        return pair[0], "team_pair"

    raise RuntimeError(
        f"Strength match failed "
        f"fixture={fid}, "
        f"direct={len(direct)}, "
        f"pair={len(pair)}"
    )


def exact_event_row(fid):

    matches = [
        row
        for row in event_rows
        if str(
            row.get(
                "fixture_id"
            )
        ) == fid
    ]

    if len(matches) != 1:

        raise RuntimeError(
            f"Event match failed "
            f"{fid}: {len(matches)}"
        )

    return matches[0]


# ============================================================
# REPORT
# ============================================================

print()
print(
    "============================================"
)
print(
    "EXACT GW4 FIXTURE TRACE"
)
print(
    "============================================"
)


for target_name, pid in (
    targets.items()
):

    player = metadata[pid]

    minute_matches = [
        row
        for row in minute_rows
        if (
            str(
                row.get(
                    "player_id"
                )
            ) == pid
            and row_gw(
                row,
                fixture_to_gw,
            ) == GW
        )
    ]

    if len(minute_matches) != 1:

        raise RuntimeError(
            f"{target_name}: "
            f"GW4 minute rows="
            f"{len(minute_matches)}"
        )

    minute = minute_matches[0]

    fid = str(
        minute["fixture_id"]
    )

    fixture = fixture_by_id[
        fid
    ]

    strength, match_method = (
        exact_strength_row(
            fid,
            fixture,
        )
    )

    event = exact_event_row(
        fid
    )


    player_team = str(
        player["team_id"]
    )

    home_team = str(
        fixture[
            "home_team_id"
        ]
    )

    away_team = str(
        fixture[
            "away_team_id"
        ]
    )


    if player_team == home_team:

        side = "home"
        opponent_side = "away"

    elif player_team == away_team:

        side = "away"
        opponent_side = "home"

    else:

        raise RuntimeError(
            f"{target_name}: "
            f"player team not in fixture"
        )


    own_expected_goals = (
        strength.get(
            "expected_home_goals"
        )
        if side == "home"
        else strength.get(
            "expected_away_goals"
        )
    )

    opp_expected_goals = (
        strength.get(
            "expected_away_goals"
        )
        if side == "home"
        else strength.get(
            "expected_home_goals"
        )
    )


    own_event = event[
        side
    ]

    opp_event = event[
        opponent_side
    ]


    own_fdr = (
        fixture.get(
            "provider_payload",
            {},
        ).get(
            "team_h_difficulty"
            if side == "home"
            else "team_a_difficulty"
        )
    )

    opp_fdr = (
        fixture.get(
            "provider_payload",
            {},
        ).get(
            "team_a_difficulty"
            if side == "home"
            else "team_h_difficulty"
        )
    )


    print()
    print(
        "--------------------------------------------"
    )
    print(
        target_name
    )
    print(
        "--------------------------------------------"
    )

    print(
        f"player_id       : {pid}"
    )

    print(
        f"team_id         : {player_team}"
    )

    print(
        f"side            : {side}"
    )

    print(
        f"fixture_id      : {fid}"
    )

    print(
        f"home_team       : {home_team}"
    )

    print(
        f"away_team       : {away_team}"
    )

    print(
        f"FDR own / opp   : "
        f"{own_fdr} / {opp_fdr}"
    )

    print(
        f"strength match  : "
        f"{match_method}"
    )

    print()

    print(
        f"attack_strength : "
        f"{nested(strength, side, 'attack_strength')}"
    )

    print(
        f"opp defence     : "
        f"{nested(strength, opponent_side, 'defence_strength')}"
    )

    print(
        f"reliability     : "
        f"{nested(strength, side, 'reliability')}"
    )

    print(
        f"sample_size     : "
        f"{nested(strength, side, 'sample_size')}"
    )

    print(
        f"effective_n     : "
        f"{nested(strength, side, 'effective_sample_size')}"
    )

    print()

    print(
        f"strength own xG : "
        f"{float(own_expected_goals):.4f}"
    )

    print(
        f"strength opp xG : "
        f"{float(opp_expected_goals):.4f}"
    )

    print(
        f"event own xG    : "
        f"{float(own_event['expected_team_goals']):.4f}"
    )

    print(
        f"event opp xG    : "
        f"{float(opp_event['expected_team_goals']):.4f}"
    )

    print()

    print(
        f"expected minutes: "
        f"{float(minute['expected_minutes']):.2f}"
    )

    print(
        f"p_appearance    : "
        f"{float(minute['p_appearance']):.3f}"
    )

    print(
        f"p_start         : "
        f"{float(minute['p_start']):.3f}"
    )


print()
print(
    "============================================"
)
print(
    "COMPACT"
)
print(
    "============================================"
)

print(
    f"{'PLAYER':<18} "
    f"{'SIDE':<5} "
    f"{'ATT':>6} "
    f"{'OPPDEF':>7} "
    f"{'xG':>6} "
    f"{'REL':>5} "
    f"{'N':>4}"
)


for target_name, pid in (
    targets.items()
):

    minute = next(
        row
        for row in minute_rows
        if (
            str(
                row.get(
                    "player_id"
                )
            ) == pid
            and row_gw(
                row,
                fixture_to_gw,
            ) == GW
        )
    )

    fid = str(
        minute[
            "fixture_id"
        ]
    )

    fixture = (
        fixture_by_id[
            fid
        ]
    )

    strength, _ = (
        exact_strength_row(
            fid,
            fixture,
        )
    )

    player_team = str(
        metadata[
            pid
        ][
            "team_id"
        ]
    )

    side = (
        "home"
        if player_team
        == str(
            fixture[
                "home_team_id"
            ]
        )
        else "away"
    )

    opp = (
        "away"
        if side == "home"
        else "home"
    )

    xg = (
        strength[
            "expected_home_goals"
        ]
        if side == "home"
        else strength[
            "expected_away_goals"
        ]
    )

    print(
        f"{target_name:<18} "
        f"{side:<5} "
        f"{nested(strength, side, 'attack_strength'):>6.3f} "
        f"{nested(strength, opp, 'defence_strength'):>7.3f} "
        f"{float(xg):>6.3f} "
        f"{nested(strength, side, 'reliability'):>5.2f} "
        f"{nested(strength, side, 'sample_size'):>4}"
    )


print()
print(
    "=== END ==="
)
