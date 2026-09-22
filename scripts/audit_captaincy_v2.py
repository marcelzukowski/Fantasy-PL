from __future__ import annotations

import json
import math
import statistics
from pathlib import Path

from fpl_engine.decision.captaincy_value import (
    best_captaincy_pair,
)
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

FINAL_RUN_MAP = (
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

LONG_RUN_IDS = (
    "20260912T091754Z",
    "20260912T092118Z",
)


def rows(raw):

    if isinstance(raw, list):
        return raw

    if isinstance(raw, dict):

        for key in (
            "rows",
            "data",
            "records",
            "minutes",
            "fixtures",
        ):

            value = raw.get(key)

            if isinstance(value, list):
                return value

    raise RuntimeError(
        "Unsupported JSON structure"
    )


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


def load_availability(path):

    minute_rows = rows(
        json.loads(
            (
                path
                / "minutes.json"
            ).read_text(
                encoding="utf-8"
            )
        )
    )

    fixture_rows = rows(
        json.loads(
            (
                path
                / "fixture_horizon.json"
            ).read_text(
                encoding="utf-8"
            )
        )
    )

    fixture_to_gw = {}

    for row in fixture_rows:

        gw = (
            row.get("gameweek")
            or row.get("target_gameweek")
            or row.get("event")
        )

        if gw is None:
            continue

        for key in (
            "fixture_id",
            "canonical_fixture_id",
            "id",
        ):

            value = row.get(key)

            if value is not None:

                fixture_to_gw[
                    str(value)
                ] = int(gw)

    grouped = {}

    for row in minute_rows:

        pid = row.get(
            "player_id"
        )

        p = row.get(
            "p_appearance"
        )

        if pid is None or p is None:
            continue

        gw = (
            row.get("gameweek")
            or row.get("target_gameweek")
        )

        if gw is None:

            fixture_id = row.get(
                "fixture_id"
            )

            if fixture_id is not None:

                gw = fixture_to_gw.get(
                    str(fixture_id)
                )

        if gw is None:
            continue

        grouped.setdefault(
            (
                str(pid),
                int(gw),
            ),
            [],
        ).append(
            float(p)
        )

    return {
        key:
            1.0
            - math.prod(
                1.0 - p
                for p in values
            )

        for key, values
        in grouped.items()
    }


def load_run(run_id):

    path = RUN_ROOT / run_id

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

    players = json.loads(
        (
            path
            / "current_players.json"
        ).read_text(
            encoding="utf-8"
        )
    )

    return {
        "id": run_id,
        "path": path,
        "projections": {
            p.player_id: p
            for p in projections
        },
        "players": players,
        "availability": (
            load_availability(path)
        ),
    }


# ------------------------------------------------------------
# DATASETS
# ------------------------------------------------------------

final_run_ids = [
    line.split(
        "run=",
        1,
    )[1].strip()

    for line in FINAL_RUN_MAP.read_text(
        encoding="utf-8-sig"
    ).splitlines()

    if "run=" in line
]

if len(final_run_ids) != 4:

    raise RuntimeError(
        f"Expected 4 final runs, "
        f"got {final_run_ids}"
    )


final_runs = [
    load_run(run_id)
    for run_id in final_run_ids
]

long_runs = [
    load_run(run_id)
    for run_id in LONG_RUN_IDS
]


metadata = {
    str(row["player_id"]): row
    for row in final_runs[0]["players"]
}

names = {
    pid: row["display_name"]
    for pid, row
    in metadata.items()
}

positions = {
    pid: row["position"]
    for pid, row
    in metadata.items()
}


# ------------------------------------------------------------
# CURRENT WC15
# ------------------------------------------------------------

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

squad = frozenset(
    base["player_ids"]
)

weekly = {
    int(row["gameweek"]): row
    for row in base["weekly"]
}


# ------------------------------------------------------------
# CAPTAINCY AUDIT
# ------------------------------------------------------------

print()
print(
    "=============================================="
)
print(
    "CAPTAINCY V2 AUDIT | FINAL WC15"
)
print(
    "GW4-GW9 = 4x256 | GW10 = 2x64"
)
print(
    "Captain pool = MID/FWD"
)
print(
    "=============================================="
)


for gw in range(4, 11):

    source_runs = (
        final_runs
        if gw <= 9
        else long_runs
    )

    ev = {}
    papp = {}

    for pid in squad:

        ev[pid] = statistics.mean(
            gw_ev(
                run["projections"][pid],
                gw,
            )
            for run in source_runs
        )

        values = [
            run["availability"][
                (pid, gw)
            ]
            for run in source_runs
            if (
                pid,
                gw,
            )
            in run["availability"]
        ]

        if values:

            papp[pid] = (
                statistics.mean(
                    values
                )
            )

        elif abs(ev[pid]) < 1e-9:

            papp[pid] = 0.0

        else:

            raise RuntimeError(
                "Missing p_appearance: "
                f"{names[pid]} GW{gw}"
            )


    eligible = [
        pid
        for pid in squad
        if positions[pid]
        in (
            "MID",
            "FWD",
        )
    ]


    pair = best_captaincy_pair(
        player_ids=eligible,
        expected_points=ev,
        p_appearance=papp,
        positions=positions,
    )


    # For every captain candidate,
    # use his best possible vice.
    ranked = []

    for captain_id in eligible:

        best_vice = max(
            (
                vice_id
                for vice_id in eligible
                if vice_id != captain_id
            ),
            key=lambda vice_id:
                ev[vice_id],
        )

        bonus = (
            ev[captain_id]
            + (
                1.0
                - papp[captain_id]
            )
            * ev[best_vice]
        )

        ranked.append(
            (
                bonus,
                captain_id,
                best_vice,
            )
        )

    ranked.sort(
        reverse=True
    )


    static_starters = set()

    if gw in weekly:

        static_starters = set(
            weekly[gw][
                "starter_ids"
            ]
        )


    print()
    print(
        f"GW{gw}"
    )

    print(
        f"  C : "
        f"{names[pair.captain_id]:<18} "
        f"EV={pair.captain_ev:.2f} "
        f"Papp={pair.captain_p_appearance:.3f}"
    )

    print(
        f"  VC: "
        f"{names[pair.vice_id]:<18} "
        f"EV={pair.vice_ev:.2f}"
    )

    print(
        f"  captain bonus="
        f"{pair.captain_bonus:.2f}"
    )

    if len(ranked) >= 2:

        leverage = (
            ranked[0][0]
            - ranked[1][0]
        )

        print(
            f"  edge vs #2="
            f"{leverage:+.2f}"
        )

    print(
        "  TOP 5:"
    )

    for rank, (
        bonus,
        captain_id,
        vice_id,
    ) in enumerate(
        ranked[:5],
        start=1,
    ):

        if gw in weekly:

            xi = (
                "XI"
                if captain_id
                in static_starters
                else "BENCH"
            )

        else:

            xi = "-"

        print(
            f"    {rank}. "
            f"{names[captain_id]:<18} "
            f"EV={ev[captain_id]:>5.2f} "
            f"Papp={papp[captain_id]:.3f} "
            f"bonus={bonus:>5.2f} "
            f"[{xi}]"
        )


print()
print(
    "=== END ==="
)
