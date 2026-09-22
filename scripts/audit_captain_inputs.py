from __future__ import annotations

import json
import math
import statistics
from collections import Counter, defaultdict
from pathlib import Path

from fpl_engine.decision.projection_adapter import (
    adapt_player_projections,
)


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

TARGET_NAMES = (
    "Palmer",
    "Szoboszlai",
    "Groß",
    "Haaland",
    "B.Fernandes",
)

TARGET_GW = 4


# ============================================================
# GENERIC HELPERS
# ============================================================

def rows_from_json(raw):

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


def flatten(
    value,
    prefix="",
):

    output = {}

    if isinstance(value, dict):

        for key, child in value.items():

            path = (
                f"{prefix}.{key}"
                if prefix
                else str(key)
            )

            output.update(
                flatten(
                    child,
                    path,
                )
            )

    elif isinstance(
        value,
        (list, tuple),
    ):

        # Avoid dumping long arrays.
        if len(value) <= 4:

            for i, child in enumerate(value):

                output.update(
                    flatten(
                        child,
                        f"{prefix}[{i}]",
                    )
                )

    elif isinstance(
        value,
        (
            str,
            int,
            float,
            bool,
        ),
    ) or value is None:

        output[prefix] = value

    return output


def gw_ev(
    projection,
    gw,
):

    for row in projection.gameweeks:

        if int(row.gameweek) == int(gw):

            return float(
                row.expected_points
            )

    return 0.0


def fixture_id_from_row(row):

    for key in (
        "fixture_id",
        "canonical_fixture_id",
        "id",
    ):

        value = row.get(key)

        if value is not None:
            return str(value)

    return None


def gw_from_fixture_row(row):

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

    fixture_id = row.get(
        "fixture_id"
    )

    if fixture_id is not None:

        return fixture_to_gw.get(
            str(fixture_id)
        )

    return None


# ============================================================
# LOAD RUN IDS
# ============================================================

run_ids = [
    line.split(
        "run=",
        1,
    )[1].strip()

    for line in RUN_MAP.read_text(
        encoding="utf-8-sig"
    ).splitlines()

    if "run=" in line
]

if len(run_ids) != 4:

    raise RuntimeError(
        f"Expected 4 final runs, got {run_ids}"
    )


# ============================================================
# BASE SQUAD -> SAFE PLAYER RESOLUTION
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


first_path = (
    RUN_ROOT
    / run_ids[0]
)

player_rows = json.loads(
    (
        first_path
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
            f"Cannot uniquely resolve "
            f"{target_name} inside BASE: "
            f"{matches}"
        )

    targets[
        target_name
    ] = matches[0]


# ============================================================
# FIELD SELECTION
# ============================================================

IMPORTANT_TOKENS = (
    "expected",
    "point",
    "goal",
    "assist",
    "xg",
    "xa",
    "attack",
    "clean",
    "bonus",
    "fixture",
    "difficulty",
    "opponent",
    "home",
    "away",
    "minute",
    "appearance",
    "start",
    "prob",
    "score",
    "rating",
    "strength",
    "adjust",
    "penalt",
    "set_piece",
    "setpiece",
)


IGNORE_TOKENS = (
    "player_id",
    "canonical_player",
)


def interesting(
    path,
):

    low = path.casefold()

    if any(
        token in low
        for token in IGNORE_TOKENS
    ):
        return False

    return any(
        token in low
        for token in IMPORTANT_TOKENS
    )


# ============================================================
# COLLECT
# ============================================================

summary = {
    name: {
        "final_ev": [],
        "p_app": [],
        "p_start": [],
        "event_numeric": defaultdict(list),
        "event_text": defaultdict(list),
        "fixture_text": defaultdict(list),
    }
    for name in TARGET_NAMES
}


for run_id in run_ids:

    path = (
        RUN_ROOT
        / run_id
    )

    # --------------------------------------------------------
    # projections
    # --------------------------------------------------------

    projections = (
        adapt_player_projections(
            json.loads(
                (
                    path
                    / "player_projections.json"
                ).read_text(
                    encoding="utf-8"
                )
            )
        )
    )

    projections_by_id = {
        p.player_id: p
        for p in projections
    }

    # --------------------------------------------------------
    # fixtures
    # --------------------------------------------------------

    fixture_raw = json.loads(
        (
            path
            / "fixture_horizon.json"
        ).read_text(
            encoding="utf-8"
        )
    )

    fixture_rows = (
        rows_from_json(
            fixture_raw
        )
    )

    fixture_to_gw = {}

    fixture_by_id = {}

    for row in fixture_rows:

        if not isinstance(
            row,
            dict,
        ):
            continue

        fixture_id = (
            fixture_id_from_row(
                row
            )
        )

        gw = gw_from_fixture_row(
            row
        )

        if fixture_id is not None:

            fixture_by_id[
                fixture_id
            ] = row

            if gw is not None:

                fixture_to_gw[
                    fixture_id
                ] = gw

    # --------------------------------------------------------
    # minutes
    # --------------------------------------------------------

    minute_raw = json.loads(
        (
            path
            / "minutes.json"
        ).read_text(
            encoding="utf-8"
        )
    )

    minute_rows = rows_from_json(
        minute_raw
    )

    # --------------------------------------------------------
    # event projections
    # --------------------------------------------------------

    event_path = (
        path
        / "event_projections.json"
    )

    if event_path.exists():

        event_rows = rows_from_json(
            json.loads(
                event_path.read_text(
                    encoding="utf-8"
                )
            )
        )

    else:

        event_rows = []

    # --------------------------------------------------------
    # target players
    # --------------------------------------------------------

    for target_name, pid in (
        targets.items()
    ):

        target = summary[
            target_name
        ]

        target[
            "final_ev"
        ].append(
            gw_ev(
                projections_by_id[
                    pid
                ],
                TARGET_GW,
            )
        )

        # ---------------- minutes ----------------

        gw_minute_rows = []

        for row in minute_rows:

            if not isinstance(
                row,
                dict,
            ):
                continue

            if str(
                row.get(
                    "player_id"
                )
            ) != pid:

                continue

            if row_gw(
                row,
                fixture_to_gw,
            ) != TARGET_GW:

                continue

            gw_minute_rows.append(
                row
            )

        if gw_minute_rows:

            p_apps = [
                float(
                    row[
                        "p_appearance"
                    ]
                )
                for row in gw_minute_rows
                if row.get(
                    "p_appearance"
                )
                is not None
            ]

            p_starts = [
                float(
                    row[
                        "p_start"
                    ]
                )
                for row in gw_minute_rows
                if row.get(
                    "p_start"
                )
                is not None
            ]

            if p_apps:

                p_any = (
                    1.0
                    - math.prod(
                        1.0 - p
                        for p in p_apps
                    )
                )

                target[
                    "p_app"
                ].append(
                    p_any
                )

            if p_starts:

                p_start_any = (
                    1.0
                    - math.prod(
                        1.0 - p
                        for p in p_starts
                    )
                )

                target[
                    "p_start"
                ].append(
                    p_start_any
                )

        # ---------------- event rows ----------------

        player_event_rows = []

        for row in event_rows:

            if not isinstance(
                row,
                dict,
            ):
                continue

            if str(
                row.get(
                    "player_id"
                )
            ) != pid:

                continue

            if row_gw(
                row,
                fixture_to_gw,
            ) != TARGET_GW:

                continue

            player_event_rows.append(
                row
            )

        for row in player_event_rows:

            flat = flatten(
                row
            )

            for key, value in (
                flat.items()
            ):

                if not interesting(
                    key
                ):
                    continue

                if isinstance(
                    value,
                    bool,
                ):

                    target[
                        "event_text"
                    ][key].append(
                        str(value)
                    )

                elif isinstance(
                    value,
                    (int, float),
                ):

                    target[
                        "event_numeric"
                    ][key].append(
                        float(value)
                    )

                elif value is not None:

                    target[
                        "event_text"
                    ][key].append(
                        str(value)
                    )

            fixture_id = row.get(
                "fixture_id"
            )

            if fixture_id is not None:

                fixture = (
                    fixture_by_id.get(
                        str(
                            fixture_id
                        )
                    )
                )

                if fixture:

                    flat_fixture = (
                        flatten(
                            fixture
                        )
                    )

                    for key, value in (
                        flat_fixture.items()
                    ):

                        if not interesting(
                            key
                        ):
                            continue

                        if value is None:
                            continue

                        target[
                            "fixture_text"
                        ][key].append(
                            str(value)
                        )


# ============================================================
# REPORT
# ============================================================

print()
print(
    "============================================================"
)
print(
    "CAPTAIN INPUT AUDIT | GW4"
)
print(
    "4 x 256 production runs"
)
print(
    "============================================================"
)


for target_name in TARGET_NAMES:

    data = summary[
        target_name
    ]

    print()
    print(
        "------------------------------------------------------------"
    )
    print(
        target_name
    )
    print(
        "------------------------------------------------------------"
    )

    ev = data[
        "final_ev"
    ]

    print(
        "FINAL GW4 EV:"
    )

    print(
        "  seeds :",
        " | ".join(
            f"{x:.3f}"
            for x in ev
        )
    )

    print(
        f"  mean  : "
        f"{statistics.mean(ev):.3f}"
    )

    print(
        f"  spread: "
        f"{max(ev)-min(ev):.3f}"
    )

    if data[
        "p_app"
    ]:

        print(
            f"P_APP   : "
            f"{statistics.mean(data['p_app']):.3f}"
        )

    if data[
        "p_start"
    ]:

        print(
            f"P_START : "
            f"{statistics.mean(data['p_start']):.3f}"
        )

    # --------------------------------------------------------
    # EVENT NUMERIC COMPONENTS
    # --------------------------------------------------------

    numeric_rows = []

    for key, values in (
        data[
            "event_numeric"
        ].items()
    ):

        if not values:
            continue

        numeric_rows.append(
            (
                key,
                statistics.mean(
                    values
                ),
                min(values),
                max(values),
            )
        )

    numeric_rows.sort(
        key=lambda x: (
            # Put expected/point/goal/assist first.
            0
            if any(
                token
                in x[0].casefold()
                for token in (
                    "expected_point",
                    "point",
                    "goal",
                    "assist",
                    "xg",
                    "xa",
                    "minute",
                    "appearance",
                    "start",
                    "adjust",
                )
            )
            else 1,
            x[0],
        )
    )

    print()
    print(
        "EVENT PROJECTION COMPONENTS:"
    )

    if numeric_rows:

        for (
            key,
            mean_value,
            min_value,
            max_value,
        ) in numeric_rows[:30]:

            print(
                f"  {key:<42} "
                f"{mean_value:>8.4f} "
                f"[{min_value:.4f}, "
                f"{max_value:.4f}]"
            )

    else:

        print(
            "  <no matching numeric "
            "fields found>"
        )

    # --------------------------------------------------------
    # EVENT TEXT
    # --------------------------------------------------------

    if data[
        "event_text"
    ]:

        print()
        print(
            "EVENT CONTEXT:"
        )

        for key in sorted(
            data[
                "event_text"
            ]
        )[:20]:

            values = (
                data[
                    "event_text"
                ][key]
            )

            value = Counter(
                values
            ).most_common(
                1
            )[0][0]

            print(
                f"  {key:<42} "
                f"{value}"
            )

    # --------------------------------------------------------
    # FIXTURE INFO
    # --------------------------------------------------------

    if data[
        "fixture_text"
    ]:

        print()
        print(
            "FIXTURE CONTEXT:"
        )

        shown = 0

        for key in sorted(
            data[
                "fixture_text"
            ]
        ):

            values = (
                data[
                    "fixture_text"
                ][key]
            )

            value = Counter(
                values
            ).most_common(
                1
            )[0][0]

            print(
                f"  {key:<42} "
                f"{value}"
            )

            shown += 1

            if shown >= 20:
                break


# ============================================================
# COMPARISON TABLE
# ============================================================

print()
print(
    "============================================================"
)
print(
    "COMPACT COMPARISON"
)
print(
    "============================================================"
)

print(
    f"{'PLAYER':<18} "
    f"{'EV':>7} "
    f"{'P_APP':>7} "
    f"{'P_START':>8}"
)

for target_name in TARGET_NAMES:

    data = summary[
        target_name
    ]

    ev = statistics.mean(
        data[
            "final_ev"
        ]
    )

    p_app = (
        statistics.mean(
            data[
                "p_app"
            ]
        )
        if data[
            "p_app"
        ]
        else float("nan")
    )

    p_start = (
        statistics.mean(
            data[
                "p_start"
            ]
        )
        if data[
            "p_start"
        ]
        else float("nan")
    )

    print(
        f"{target_name:<18} "
        f"{ev:>7.3f} "
        f"{p_app:>7.3f} "
        f"{p_start:>8.3f}"
    )


print()
print(
    "=== END ==="
)
