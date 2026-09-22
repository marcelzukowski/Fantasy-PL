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

RUN_MAP = (
    ROOT
    / "scratch"
    / "decision"
    / "final_wc_256_run_map.txt"
)

PLAN_PATH = (
    ROOT
    / "scratch"
    / "decision"
    / "final_wc_playing_plan.json"
)

TARGETS = (
    "Palmer",
    "Szoboszlai",
    "Groß",
    "Haaland",
    "B.Fernandes",
)

GW = 4


def rows(raw):

    if isinstance(raw, list):
        return raw

    if isinstance(raw, dict):

        for key in (
            "rows",
            "data",
            "records",
            "events",
            "projections",
            "minutes",
            "fixtures",
        ):

            value = raw.get(key)

            if isinstance(value, list):
                return value

    return []


def flatten_scalars(
    value,
    prefix="",
    output=None,
):

    if output is None:
        output = {}

    if isinstance(value, dict):

        for key, child in value.items():

            path = (
                f"{prefix}.{key}"
                if prefix
                else str(key)
            )

            flatten_scalars(
                child,
                path,
                output,
            )

    elif isinstance(value, (list, tuple)):

        # Only expand small structures.
        if len(value) <= 6:

            for i, child in enumerate(value):

                flatten_scalars(
                    child,
                    f"{prefix}[{i}]",
                    output,
                )

    elif isinstance(
        value,
        (str, int, float, bool),
    ) or value is None:

        output[prefix] = value

    return output


def contains_value(
    value,
    target,
):

    if isinstance(value, dict):

        return any(
            contains_value(child, target)
            for child in value.values()
        )

    if isinstance(value, (list, tuple)):

        return any(
            contains_value(child, target)
            for child in value
        )

    return str(value) == str(target)


def fixture_id(row):

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


# ------------------------------------------------------------
# FIRST FINAL RUN
# ------------------------------------------------------------

run_ids = [
    line.split("run=", 1)[1].strip()
    for line in RUN_MAP.read_text(
        encoding="utf-8-sig"
    ).splitlines()
    if "run=" in line
]

run_id = run_ids[0]
run_path = RUN_ROOT / run_id

print()
print(
    "RUN:",
    run_id,
)


# ------------------------------------------------------------
# AVAILABLE FILES
# ------------------------------------------------------------

print()
print(
    "============================================"
)
print(
    "RUN JSON FILES"
)
print(
    "============================================"
)

for path in sorted(
    run_path.glob("*.json")
):

    print(
        " ",
        path.name,
    )


# ------------------------------------------------------------
# PLAYERS
# ------------------------------------------------------------

player_rows = json.loads(
    (
        run_path
        / "current_players.json"
    ).read_text(
        encoding="utf-8"
    )
)

metadata = {
    str(row["player_id"]): row
    for row in player_rows
}

names = {
    pid: row["display_name"]
    for pid, row
    in metadata.items()
}


plan = json.loads(
    PLAN_PATH.read_text(
        encoding="utf-8"
    )
)

base = next(
    c
    for c in plan["candidates"]
    if "BASE_CAND5"
    in c["labels"]
)

base_ids = set(
    base["player_ids"]
)


targets = {}

for display_name in TARGETS:

    matches = [
        pid
        for pid in base_ids
        if names.get(pid)
        == display_name
    ]

    if len(matches) != 1:

        raise RuntimeError(
            f"Cannot resolve "
            f"{display_name}: "
            f"{matches}"
        )

    targets[display_name] = (
        matches[0]
    )


# ------------------------------------------------------------
# FIXTURES
# ------------------------------------------------------------

fixture_raw = json.loads(
    (
        run_path
        / "fixture_horizon.json"
    ).read_text(
        encoding="utf-8"
    )
)

fixture_rows = rows(
    fixture_raw
)

fixture_to_gw = {}
fixture_by_id = {}

for row in fixture_rows:

    if not isinstance(row, dict):
        continue

    fid = fixture_id(row)

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


# ------------------------------------------------------------
# MINUTES
# ------------------------------------------------------------

minute_rows = rows(
    json.loads(
        (
            run_path
            / "minutes.json"
        ).read_text(
            encoding="utf-8"
        )
    )
)


# ------------------------------------------------------------
# EVENT PROJECTIONS
# ------------------------------------------------------------

event_path = (
    run_path
    / "event_projections.json"
)

event_raw = json.loads(
    event_path.read_text(
        encoding="utf-8"
    )
)

event_rows = rows(
    event_raw
)


print()
print(
    "============================================"
)
print(
    "EVENT_PROJECTIONS SCHEMA"
)
print(
    "============================================"
)

print(
    "top-level type:",
    type(event_raw).__name__,
)

if isinstance(event_raw, dict):

    print(
        "top-level keys:",
        sorted(
            event_raw.keys()
        ),
    )

print(
    "row count:",
    len(event_rows),
)

if event_rows:

    print(
        "first row keys:",
        sorted(
            event_rows[0].keys()
        )
        if isinstance(
            event_rows[0],
            dict,
        )
        else type(
            event_rows[0]
        ).__name__,
    )


# ------------------------------------------------------------
# TARGET TRACE
# ------------------------------------------------------------

for display_name, pid in (
    targets.items()
):

    print()
    print()
    print(
        "============================================================"
    )
    print(display_name)
    print(
        "============================================================"
    )

    player = metadata[pid]

    print(
        "PLAYER ID:",
        pid,
    )

    print(
        "POSITION:",
        player.get("position"),
    )

    print()
    print(
        "TEAM-RELATED PLAYER FIELDS"
    )

    player_flat = flatten_scalars(
        player
    )

    team_fields = [
        (key, value)
        for key, value
        in player_flat.items()
        if (
            "team" in key.casefold()
            or "club" in key.casefold()
        )
    ]

    for key, value in sorted(
        team_fields
    ):

        print(
            f"  {key:<38} "
            f"{value}"
        )


    # --------------------------------------------------------
    # Find GW4 minutes / fixture ids
    # --------------------------------------------------------

    player_minute_rows = [
        row
        for row in minute_rows
        if (
            isinstance(row, dict)
            and str(
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

    print()
    print(
        "GW4 MINUTES ROWS:",
        len(
            player_minute_rows
        ),
    )

    target_fixture_ids = []

    for row in player_minute_rows:

        fid = row.get(
            "fixture_id"
        )

        if fid is not None:

            target_fixture_ids.append(
                str(fid)
            )

        flat = flatten_scalars(
            row
        )

        for key in sorted(flat):

            if any(
                token in key.casefold()
                for token in (
                    "fixture",
                    "appearance",
                    "start",
                    "minute",
                )
            ):

                print(
                    f"  {key:<38} "
                    f"{flat[key]}"
                )


    # --------------------------------------------------------
    # Fixture row
    # --------------------------------------------------------

    for fid in sorted(
        set(target_fixture_ids)
    ):

        fixture = (
            fixture_by_id.get(fid)
        )

        print()
        print(
            "FIXTURE:",
            fid,
        )

        if fixture is None:

            print(
                "  <fixture row missing>"
            )

            continue

        flat = flatten_scalars(
            fixture
        )

        # Print all scalar fixture fields,
        # but keep output bounded.
        for key in sorted(flat)[:60]:

            print(
                f"  {key:<38} "
                f"{flat[key]}"
            )


    # --------------------------------------------------------
    # Event projection matching rows
    # --------------------------------------------------------

    matching_events = []

    for row in event_rows:

        if not isinstance(
            row,
            dict,
        ):
            continue

        if not contains_value(
            row,
            pid,
        ):
            continue

        event_gw = row_gw(
            row,
            fixture_to_gw,
        )

        if (
            event_gw is not None
            and event_gw != GW
        ):
            continue

        matching_events.append(
            row
        )


    print()
    print(
        "MATCHING EVENT ROWS:",
        len(
            matching_events
        ),
    )

    for index, row in enumerate(
        matching_events[:3],
        start=1,
    ):

        print()
        print(
            f"EVENT ROW {index}"
        )

        flat = flatten_scalars(
            row
        )

        for key in sorted(flat)[:80]:

            print(
                f"  {key:<42} "
                f"{flat[key]}"
            )


print()
print(
    "=== DATA TRACE END ==="
)
