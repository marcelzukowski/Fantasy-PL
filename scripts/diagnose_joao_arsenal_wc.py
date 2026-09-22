from __future__ import annotations

import json
import math
import statistics
import unicodedata

from collections import Counter
from dataclasses import replace
from pathlib import Path

from fpl_engine.decision.projection_adapter import (
    adapt_player_projections,
)

from fpl_engine.decision.chip_squads import (
    optimize_unlimited_squad,
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

RESULTS = (
    ROOT
    / "scratch"
    / "decision"
    / "final_wc_robust_results.json"
)

SQUAD_STATE = (
    ROOT
    / "scratch"
    / "decision"
    / "my_squad_gw4.json"
)

GAMEWEEKS = range(4, 10)

WEIGHTS = (
    1.00,
    0.95,
    0.90,
    0.85,
    0.80,
    0.75,
)


def norm(value):

    text = unicodedata.normalize(
        "NFKD",
        str(value or ""),
    )

    text = "".join(
        c
        for c in text
        if not unicodedata.combining(c)
    )

    return "".join(
        c.casefold()
        for c in text
        if c.isalnum()
    )


def ev_for(
    projection,
    gw,
):

    for row in projection.gameweeks:

        if row.gameweek == gw:
            return float(
                row.expected_points
            )

    return 0.0


# ------------------------------------------------------------
# RUNS
# ------------------------------------------------------------

run_lines = RUN_MAP.read_text(
    encoding="utf-8-sig"
).splitlines()

run_ids = [
    line.split("run=", 1)[1].strip()
    for line in run_lines
    if "run=" in line
]

runs = []

for run_id in run_ids:

    path = (
        RUN_ROOT
        / run_id
    )

    player_rows = json.loads(
        (
            path
            / "current_players.json"
        ).read_text(
            encoding="utf-8"
        )
    )

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

    runs.append(
        {
            "run_id": run_id,
            "player_rows": player_rows,
            "projections": {
                p.player_id: p
                for p in projections
            },
        }
    )


reference = runs[0]

metadata = {
    str(row["player_id"]): row
    for row
    in reference["player_rows"]
}

name_by_id = {
    pid: row["display_name"]
    for pid, row
    in metadata.items()
}

price_by_id = {
    pid: int(
        round(
            float(
                row["current_price"]
            )
            * 10
        )
    )
    if float(
        row["current_price"]
    ) < 20
    else int(
        row["current_price"]
    )
    for pid, row
    in metadata.items()
}


# ------------------------------------------------------------
# CONSENSUS COUNTS
# ------------------------------------------------------------

result_data = json.loads(
    RESULTS.read_text(
        encoding="utf-8"
    )
)

selection_count = Counter()

for candidate in result_data[
    "source_candidates"
]:

    selection_count.update(
        candidate[
            "player_ids"
        ]
    )


# ------------------------------------------------------------
# PLAYER STATS
# ------------------------------------------------------------

def player_world_values(
    player_id,
):

    values = []

    for run in runs:

        projection = (
            run[
                "projections"
            ][player_id]
        )

        total = sum(
            WEIGHTS[index]
            * ev_for(
                projection,
                gw,
            )
            for index, gw
            in enumerate(
                GAMEWEEKS
            )
        )

        values.append(
            total
        )

    return values


def player_stats(
    player_id,
):

    values = (
        player_world_values(
            player_id
        )
    )

    return {
        "mean": statistics.mean(
            values
        ),
        "worst": min(
            values
        ),
        "spread": (
            max(values)
            - min(values)
        ),
    }


# ------------------------------------------------------------
# RESOLVE JOAO PEDRO
# ------------------------------------------------------------

joao_ids = [
    pid
    for pid, name
    in name_by_id.items()
    if norm(name)
    == "joaopedro"
]

if len(joao_ids) != 1:

    raise RuntimeError(
        f"Joao Pedro resolution: "
        f"{joao_ids}"
    )

JOAO = joao_ids[0]


haaland_ids = [
    pid
    for pid, name
    in name_by_id.items()
    if norm(name)
    == "haaland"
]

if len(haaland_ids) != 1:
    raise RuntimeError(
        "Haaland resolution failed"
    )

HAALAND = haaland_ids[0]


# ------------------------------------------------------------
# FIND ARSENAL TEAM
# ------------------------------------------------------------

arsenal_team_id = None


# First try metadata fields.

for row in reference[
    "player_rows"
]:

    for key, value in row.items():

        if (
            "team" in key.casefold()
            and isinstance(
                value,
                str,
            )
            and "arsenal"
            in value.casefold()
        ):

            arsenal_team_id = str(
                row["team_id"]
            )

            break

    if arsenal_team_id:
        break


# Fallback via well-known Arsenal names.

if arsenal_team_id is None:

    arsenal_names = {
        "saliba",
        "gabriel",
        "timber",
        "calafiori",
        "raya",
        "lewisskelly",
    }

    for pid, name in (
        name_by_id.items()
    ):

        if norm(name) in arsenal_names:

            arsenal_team_id = str(
                metadata[
                    pid
                ][
                    "team_id"
                ]
            )

            break


if arsenal_team_id is None:

    raise RuntimeError(
        "Could not identify Arsenal team"
    )


arsenal_defs = [
    pid
    for pid, row
    in metadata.items()
    if (
        str(
            row["team_id"]
        )
        == arsenal_team_id
        and row["position"]
        == "DEF"
    )
]


arsenal_defs.sort(
    key=lambda pid: (
        player_stats(
            pid
        )[
            "mean"
        ]
    ),
    reverse=True,
)


# ------------------------------------------------------------
# CURRENT SQUAD / SELLING PRICES
# ------------------------------------------------------------

known_ids = set(
    metadata
)


def collect_ids(value):

    output = set()

    if isinstance(
        value,
        str,
    ):

        if value in known_ids:
            output.add(value)

    elif isinstance(
        value,
        dict,
    ):

        for child in (
            value.values()
        ):
            output.update(
                collect_ids(
                    child
                )
            )

    elif isinstance(
        value,
        list,
    ):

        for child in value:
            output.update(
                collect_ids(
                    child
                )
            )

    return output


current_ids = collect_ids(
    json.loads(
        SQUAD_STATE.read_text(
            encoding="utf-8"
        )
    )
)

if len(current_ids) != 15:

    raise RuntimeError(
        f"Current squad IDs: "
        f"{len(current_ids)}"
    )


selling_by_name = {
    "donnarumma": 55,
    "dubravka": 40,
    "thomas": 40,
    "diop": 40,
    "virgil": 65,
    "gvardiol": 55,
    "shaw": 44,
    "ndiaye": 59,
    "szoboszlai": 70,
    "bfernandes": 120,
    "mbeumo": 79,
    "xhaka": 55,
    "joaopedro": 76,
    "kusiasare": 45,
    "haaland": 155,
}


selling_prices = {}

for pid in current_ids:

    key = norm(
        name_by_id[
            pid
        ]
    )

    selling_prices[
        pid
    ] = selling_by_name[
        key
    ]


# ------------------------------------------------------------
# MEAN PROJECTION WORLD
# ------------------------------------------------------------

mean_projections = {}


for player_id in (
    reference[
        "projections"
    ]
):

    base = (
        reference[
            "projections"
        ][player_id]
    )

    gameweeks = []


    for gw in GAMEWEEKS:

        values = [
            ev_for(
                run[
                    "projections"
                ][player_id],
                gw,
            )
            for run in runs
        ]

        template = next(
            row
            for row in base.gameweeks
            if row.gameweek == gw
        )

        gameweeks.append(
            replace(
                template,
                expected_points=(
                    statistics.mean(
                        values
                    )
                ),
            )
        )


    raw3 = sum(
        x.expected_points
        for x in gameweeks[:3]
    )

    weighted3 = sum(
        x.expected_points
        * WEIGHTS[i]
        for i, x
        in enumerate(
            gameweeks[:3]
        )
    )

    raw6 = sum(
        x.expected_points
        for x in gameweeks
    )

    weighted6 = sum(
        x.expected_points
        * WEIGHTS[i]
        for i, x
        in enumerate(
            gameweeks
        )
    )


    mean_projections[
        player_id
    ] = replace(
        base,
        current_gameweek=4,
        gameweeks=tuple(
            gameweeks
        ),
        horizon_3=replace(
            base.horizon_3,
            first_gameweek=4,
            last_gameweek=6,
            raw_expected_points=raw3,
            weighted_expected_points=(
                weighted3
            ),
            gameweeks=3,
        ),
        horizon_6=replace(
            base.horizon_6,
            first_gameweek=4,
            last_gameweek=9,
            raw_expected_points=raw6,
            weighted_expected_points=(
                weighted6
            ),
            gameweeks=6,
        ),
    )


# ------------------------------------------------------------
# OPTIMIZER
# ------------------------------------------------------------

def optimize(
    required,
):

    return optimize_unlimited_squad(
        player_rows=(
            reference[
                "player_rows"
            ]
        ),
        projections_by_id=(
            mean_projections
        ),
        current_player_ids=(
            current_ids
        ),
        selling_prices_tenths=(
            selling_prices
        ),
        bank_tenths=0,
        first_gameweek=4,
        horizon=6,
        weights=WEIGHTS,
        required_player_ids=(
            tuple(
                required
            )
        ),
    )


base = optimize(
    {
        HAALAND,
    }
)


def diff_names(plan):

    base_ids = set(
        base.player_ids
    )

    plan_ids = set(
        plan.player_ids
    )

    out_names = sorted(
        name_by_id[pid]
        for pid
        in (
            base_ids
            - plan_ids
        )
    )

    in_names = sorted(
        name_by_id[pid]
        for pid
        in (
            plan_ids
            - base_ids
        )
    )

    return (
        out_names,
        in_names,
    )


print()
print(
    "=== JOAO PEDRO DIAGNOSTIC ==="
)

for target_name in (
    "Calvert-Lewin",
    "Evanilson",
    "João Pedro",
    "Thiago",
    "Barry",
):

    matches = [
        pid
        for pid, name
        in name_by_id.items()
        if norm(name)
        == norm(target_name)
    ]

    if len(matches) != 1:
        continue

    pid = matches[0]

    stats = player_stats(
        pid
    )

    print(
        f"{name_by_id[pid]:<18} "
        f"price={price_by_id[pid]/10:.1f} "
        f"sel={selection_count[pid]}/6 "
        f"mean6={stats['mean']:.2f} "
        f"worst6={stats['worst']:.2f}"
    )


joao_plan = optimize(
    {
        HAALAND,
        JOAO,
    }
)

out_names, in_names = (
    diff_names(
        joao_plan
    )
)

print()
print(
    "FORCE JOAO:"
)

print(
    f"XI EV={joao_plan.weighted_xi_ev:.2f} "
    f"delta="
    f"{joao_plan.weighted_xi_ev-base.weighted_xi_ev:+.2f}"
)

print(
    "OUT:",
    ", ".join(out_names)
    or "-",
)

print(
    "IN :",
    ", ".join(in_names)
    or "-",
)


print()
print(
    "=== ARSENAL DEFENDERS ==="
)


top_arsenal = (
    arsenal_defs[:5]
)


for pid in top_arsenal:

    stats = player_stats(
        pid
    )

    print(
        f"{name_by_id[pid]:<18} "
        f"price={price_by_id[pid]/10:.1f} "
        f"sel={selection_count[pid]}/6 "
        f"mean6={stats['mean']:.2f} "
        f"worst6={stats['worst']:.2f}"
    )


print()
print(
    "=== FORCED ARSENAL TESTS ==="
)


for pid in top_arsenal[:3]:

    plan = optimize(
        {
            HAALAND,
            pid,
        }
    )

    out_names, in_names = (
        diff_names(
            plan
        )
    )

    print(
        f"{name_by_id[pid]:<18} "
        f"delta="
        f"{plan.weighted_xi_ev-base.weighted_xi_ev:+.2f} "
        f"bank={plan.remaining_budget_tenths/10:.1f}"
    )

    print(
        "  OUT:",
        ", ".join(out_names)
        or "-",
    )

    print(
        "  IN :",
        ", ".join(in_names)
        or "-",
    )


print()
print(
    "=== JOAO + ARSENAL DEF ==="
)


for pid in top_arsenal[:3]:

    plan = optimize(
        {
            HAALAND,
            JOAO,
            pid,
        }
    )

    out_names, in_names = (
        diff_names(
            plan
        )
    )

    print(
        f"Joao + {name_by_id[pid]:<14} "
        f"delta="
        f"{plan.weighted_xi_ev-base.weighted_xi_ev:+.2f} "
        f"bank={plan.remaining_budget_tenths/10:.1f}"
    )

    print(
        "  OUT:",
        ", ".join(out_names)
        or "-",
    )

    print(
        "  IN :",
        ", ".join(in_names)
        or "-",
    )


print()
print(
    "BASE MEAN XI EV:",
    f"{base.weighted_xi_ev:.2f}",
)

print(
    "=== END ==="
)
