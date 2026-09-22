from __future__ import annotations

import json
import statistics
from pathlib import Path

from fpl_engine.decision import (
    SquadState,
    adapt_player_projections,
    build_player_values,
    build_team_counts,
    optimize_rolling_free_transfers,
)


ACTIVE_GAMEWEEK = 4
MIN_SIMULATIONS = 64
HORIZON = 6
TRANSFER_COUNTS = (2, 3)


def load_json(path):
    return json.loads(
        Path(path).read_text(
            encoding="utf-8"
        )
    )


def simulation_count(rows):
    probabilities = []

    for player in rows:
        for gw in player.get(
            "gameweeks",
            []
        ):
            for value in gw.get(
                "points_distribution",
                {}
            ).values():

                value = float(value)

                if 0.0 < value < 1.0:
                    probabilities.append(
                        value
                    )

    if not probabilities:
        return 1

    return round(
        1.0 / min(
            probabilities
        )
    )


root = Path.cwd()

base = (
    root
    / "scratch"
    / "book003"
    / "current_market_shadow"
    / "2026-27"
)

squad_payload = load_json(
    root
    / "scratch"
    / "decision"
    / "my_squad_gw4.json"
)

current_ids = frozenset(
    row["player_id"]
    for row in squad_payload[
        "players"
    ]
)

selling_prices = {
    row["player_id"]: int(
        row[
            "selling_price_tenths"
        ]
    )
    for row in squad_payload[
        "players"
    ]
}


runs = []

for path in base.glob(
    "*/player_projections.json"
):

    rows = load_json(
        path
    )

    if not rows:
        continue

    if (
        rows[0].get(
            "current_gameweek"
        )
        != ACTIVE_GAMEWEEK
    ):
        continue

    simulations = (
        simulation_count(
            rows
        )
    )

    if simulations >= MIN_SIMULATIONS:
        runs.append(
            (
                path.parent,
                simulations,
            )
        )


runs.sort(
    key=lambda item: item[0].name
)


prepared = {}


for run_dir, simulations in runs:

    projection_rows = load_json(
        run_dir
        / "player_projections.json"
    )

    player_rows = load_json(
        run_dir
        / "current_players.json"
    )

    metadata = {
        row["player_id"]: row
        for row in player_rows
    }

    projections = (
        adapt_player_projections(
            projection_rows
        )
    )

    projections_by_id = {
        row.player_id: row
        for row in projections
    }

    values = build_player_values(
        projections,
        metadata,
    )

    by_id = {
        row.player_id: row
        for row in values
    }

    state = SquadState(
        player_ids=current_ids,
        bank_tenths=int(
            squad_payload[
                "bank_tenths"
            ]
        ),
        selling_prices_tenths=(
            selling_prices
        ),
        team_counts=build_team_counts(
            current_ids,
            by_id,
        ),
    )

    prepared[
        run_dir.name
    ] = {
        "run_dir": run_dir,
        "simulations": simulations,
        "values": values,
        "by_id": by_id,
        "projections": (
            projections_by_id
        ),
        "state": state,
    }


#
# PHASE 1:
# collect every unique best GW4 plan
# suggested by any production run.
#

candidate_squads = {}


for run_name, data in (
    prepared.items()
):

    for count in TRANSFER_COUNTS:

        result = (
            optimize_rolling_free_transfers(
                players=data["values"],
                projections_by_id=(
                    data["projections"]
                ),
                state=data["state"],
                horizon=HORIZON,
                transfers_now=count,
                current_free_transfers=int(
                    squad_payload[
                        "free_transfers"
                    ]
                ),
                captaincy_weight=0.0,
            )
        )

        if result is None:
            continue

        key = tuple(
            sorted(
                result
                .squad_now_player_ids
            )
        )

        candidate_squads.setdefault(
            key,
            {
                "count": count,
                "origins": [],
            },
        )

        candidate_squads[
            key
        ]["origins"].append(
            run_name
        )


print()
print(
    "=== FIXED-PLAN CROSS-RUN AUDIT ==="
)

print(
    "runs:",
    len(prepared),
)

print(
    "unique candidate plans:",
    len(candidate_squads),
)


evaluated = []


for candidate_index, (
    fixed_squad_tuple,
    candidate_meta,
) in enumerate(
    candidate_squads.items(),
    start=1,
):

    fixed_squad = set(
        fixed_squad_tuple
    )

    count = candidate_meta[
        "count"
    ]

    gains = []

    results_by_run = {}

    for run_name, data in (
        prepared.items()
    ):

        result = (
            optimize_rolling_free_transfers(
                players=data["values"],
                projections_by_id=(
                    data["projections"]
                ),
                state=data["state"],
                horizon=HORIZON,
                transfers_now=count,
                current_free_transfers=int(
                    squad_payload[
                        "free_transfers"
                    ]
                ),
                captaincy_weight=0.0,
                fixed_squad_now_player_ids=(
                    fixed_squad
                ),
            )
        )

        if result is None:
            gains.append(
                float("-inf")
            )

            continue

        gains.append(
            result.gain
        )

        results_by_run[
            run_name
        ] = result


    finite_gains = [
        value
        for value in gains
        if value != float("-inf")
    ]

    if (
        len(finite_gains)
        != len(prepared)
    ):
        mean_gain = float("-inf")
        worst_gain = float("-inf")
        spread = float("inf")

    else:
        mean_gain = statistics.mean(
            finite_gains
        )

        worst_gain = min(
            finite_gains
        )

        spread = (
            statistics.pstdev(
                finite_gains
            )
            if len(finite_gains) > 1
            else 0.0
        )

    first_run = next(
        iter(prepared.values())
    )

    by_id = first_run[
        "by_id"
    ]

    outgoing = (
        current_ids
        - fixed_squad
    )

    incoming = (
        fixed_squad
        - current_ids
    )


    def grouped(ids):
        output = {}

        for player_id in ids:

            row = by_id[
                player_id
            ]

            output.setdefault(
                row.position,
                [],
            ).append(
                row.name
            )

        return output


    out_grouped = grouped(
        outgoing
    )

    in_grouped = grouped(
        incoming
    )

    print()
    print(
        "================================"
    )

    print(
        f"PLAN {candidate_index}"
    )

    print(
        "transfers:",
        count,
    )

    print(
        "origin:",
        ", ".join(
            candidate_meta[
                "origins"
            ]
        ),
    )

    print(
        "TRANSFERS:"
    )

    for position in (
        "GK",
        "DEF",
        "MID",
        "FWD",
    ):

        outs = sorted(
            out_grouped.get(
                position,
                [],
            )
        )

        ins = sorted(
            in_grouped.get(
                position,
                [],
            )
        )

        if len(outs) != len(ins):
            raise RuntimeError(
                f"position mismatch "
                f"for {position}"
            )

        for player_out, player_in in zip(
            outs,
            ins,
        ):

            print(
                f"  {position}: "
                f"{player_out}"
                " -> "
                f"{player_in}"
            )


    for run_name, data in (
        prepared.items()
    ):

        result = results_by_run.get(
            run_name
        )

        if result is None:

            print(
                run_name,
                "| INVALID",
            )

        else:

            print(
                run_name,
                "| gain",
                f"{result.gain:+.2f}",
                "| GW5 FT used",
                result.transfers_next_week,
            )


    print(
        "mean gain:",
        f"{mean_gain:+.2f}",
    )

    print(
        "worst-run gain:",
        f"{worst_gain:+.2f}",
    )

    print(
        "run spread:",
        f"{spread:.2f}",
    )


    evaluated.append(
        {
            "index": candidate_index,
            "count": count,
            "mean": mean_gain,
            "worst": worst_gain,
            "spread": spread,
            "outgoing": outgoing,
            "incoming": incoming,
        }
    )


#
# Ranking:
# first by worst-run EV,
# then mean EV,
# then lower instability,
# then fewer transfers.
#

ranking = sorted(
    evaluated,
    key=lambda row: (
        row["worst"],
        row["mean"],
        -row["spread"],
        -row["count"],
    ),
    reverse=True,
)


print()
print(
    "================================"
)
print(
    "=== ROBUST RANKING ==="
)


first_run = next(
    iter(prepared.values())
)

by_id = first_run[
    "by_id"
]


for rank, row in enumerate(
    ranking,
    start=1,
):

    outgoing_names = sorted(
        by_id[player_id].name
        for player_id
        in row["outgoing"]
    )

    incoming_names = sorted(
        by_id[player_id].name
        for player_id
        in row["incoming"]
    )

    print()
    print(
        f"{rank}. PLAN {row['index']}"
    )

    print(
        "   transfers:",
        row["count"],
    )

    print(
        "   OUT:",
        ", ".join(
            outgoing_names
        ),
    )

    print(
        "   IN: ",
        ", ".join(
            incoming_names
        ),
    )

    print(
        "   mean:",
        f"{row['mean']:+.2f}",
        "| worst:",
        f"{row['worst']:+.2f}",
        "| spread:",
        f"{row['spread']:.2f}",
    )
