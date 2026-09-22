from __future__ import annotations

import json
from pathlib import Path

from fpl_engine.decision import (
    SquadState,
    adapt_player_projections,
    build_player_values,
    build_team_counts,
    optimize_rolling_free_transfers,
)


def load_json(path):
    return json.loads(
        Path(path).read_text(
            encoding="utf-8"
        )
    )


root = Path.cwd()

state_payload = load_json(
    root
    / "scratch"
    / "decision"
    / "my_squad_gw4.json"
)

run_dir = Path(
    state_payload[
        "projection_run"
    ]
)

if not run_dir.is_absolute():
    run_dir = (
        root / run_dir
    )

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

squad_rows = (
    state_payload["players"]
)

squad_ids = frozenset(
    row["player_id"]
    for row in squad_rows
)

selling_prices = {
    row["player_id"]: int(
        row[
            "selling_price_tenths"
        ]
    )
    for row in squad_rows
}

state = SquadState(
    player_ids=squad_ids,
    bank_tenths=int(
        state_payload[
            "bank_tenths"
        ]
    ),
    selling_prices_tenths=(
        selling_prices
    ),
    team_counts=build_team_counts(
        squad_ids,
        by_id,
    ),
)


def names(ids):
    return [
        by_id[player_id].name
        for player_id in ids
    ]


print()
print(
    "=== ROLLING FREE-TRANSFER VALUE ==="
)

print(
    "projection_run:",
    run_dir.name,
)

print(
    "current free transfers:",
    state_payload[
        "free_transfers"
    ],
)

for horizon in (
    3,
    6,
):

    print()
    print(
        f"=== HORIZON {horizon} GW ==="
    )

    results = []

    for transfers_now in (
        1,
        2,
        3,
    ):

        result = (
            optimize_rolling_free_transfers(
                players=values,
                projections_by_id=(
                    projections_by_id
                ),
                state=state,
                horizon=horizon,
                transfers_now=(
                    transfers_now
                ),
                current_free_transfers=int(
                    state_payload[
                        "free_transfers"
                    ]
                ),
            )
        )

        results.append(
            result
        )

        print()
        print(
            f"-- USE {transfers_now} FT NOW --"
        )

        if result is None:
            print(
                "NO FEASIBLE PLAN"
            )
            continue

        outgoing_now = list(
            result
            .outgoing_now_player_ids
        )

        incoming_now = list(
            result
            .incoming_now_player_ids
        )

        outgoing_positions = {
            position: [
                player_id
                for player_id
                in outgoing_now
                if (
                    by_id[
                        player_id
                    ].position
                    == position
                )
            ]
            for position in (
                "GK",
                "DEF",
                "MID",
                "FWD",
            )
        }

        incoming_positions = {
            position: [
                player_id
                for player_id
                in incoming_now
                if (
                    by_id[
                        player_id
                    ].position
                    == position
                )
            ]
            for position in (
                "GK",
                "DEF",
                "MID",
                "FWD",
            )
        }

        for position in (
            "GK",
            "DEF",
            "MID",
            "FWD",
        ):
            if (
                len(
                    outgoing_positions[
                        position
                    ]
                )
                != len(
                    incoming_positions[
                        position
                    ]
                )
            ):
                raise RuntimeError(
                    "POSITION BALANCE ERROR: "
                    f"{position}: "
                    f"{len(outgoing_positions[position])} OUT "
                    f"vs "
                    f"{len(incoming_positions[position])} IN"
                )

        print(
            "GW4 TRANSFERS:"
        )

        for position in (
            "GK",
            "DEF",
            "MID",
            "FWD",
        ):

            outs = outgoing_positions[
                position
            ]

            ins = incoming_positions[
                position
            ]

            for player_out, player_in in zip(
                outs,
                ins,
            ):
                print(
                    f"  {position}: "
                    f"{by_id[player_out].name}"
                    " -> "
                    f"{by_id[player_in].name}"
                )

        print(
            "bank after GW4:",
            f"£"
            f"{result.bank_after_now_tenths / 10:.1f}m",
        )

        print(
            "GW5 FT available:",
            result.next_week_ft_available,
        )

        print(
            "GW5 FT used:",
            result.transfers_next_week,
        )

        if (
            result.transfers_next_week
            > 0
        ):

            print(
                "GW5 OUT:",
                ", ".join(
                    names(
                        result
                        .outgoing_next_player_ids
                    )
                ),
            )

            print(
                "GW5 IN: ",
                ", ".join(
                    names(
                        result
                        .incoming_next_player_ids
                    )
                ),
            )

        print(
            "bank after GW5:",
            f"£"
            f"{result.bank_after_next_tenths / 10:.1f}m",
        )

        print(
            "XI+C EV:",
            f"{result.baseline_weighted_total_ev:.2f}",
            "->",
            f"{result.final_weighted_total_ev:.2f}",
        )

        print(
            "total gain:",
            f"{result.gain:+.2f}",
        )

        print(
            "captains:",
            ", ".join(
                f"GW{gw} "
                f"{by_id[player_id].name}"
                for gw, player_id
                in result
                .captain_by_gameweek
            ),
        )

    valid = [
        row
        for row in results
        if row is not None
    ]

    if valid:

        best = max(
            valid,
            key=lambda row: (
                row.final_weighted_total_ev
            ),
        )

        print()
        print(
            "BEST:",
            f"use {best.transfers_now} FT now",
            "| gain",
            f"{best.gain:+.2f}",
        )
