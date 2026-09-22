from __future__ import annotations

import json
from pathlib import Path

from fpl_engine.decision import (
    SquadState,
    adapt_player_projections,
    build_player_values,
    build_team_counts,
    optimize_starting_xi_transfers,
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

projections_raw = load_json(
    run_dir
    / "player_projections.json"
)

players_raw = load_json(
    run_dir
    / "current_players.json"
)

metadata = {
    row["player_id"]: row
    for row in players_raw
}

projections = (
    adapt_player_projections(
        projections_raw
    )
)

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


def print_plan(
    result,
):
    if result is None:
        print(
            "NO FEASIBLE PLAN"
        )
        return

    print(
        f"transfers: "
        f"{result.transfer_count}"
    )

    print(
        "OUT:",
        ", ".join(
            names(
                result
                .outgoing_player_ids
            )
        ),
    )

    print(
        "IN: ",
        ", ".join(
            names(
                result
                .incoming_player_ids
            )
        ),
    )

    print(
        "starting XI EV:",
        f"{result.current_starting_xi_ev:.2f}",
        "->",
        f"{result.final_starting_xi_ev:.2f}",
    )

    print(
        "XI gain:",
        f"{result.gain:+.2f}",
    )

    print(
        "START XI:",
        ", ".join(
            names(
                result
                .starting_xi_player_ids
            )
        ),
    )

    print(
        "BENCH:",
        ", ".join(
            names(
                result
                .bench_player_ids
            )
        ),
    )

    print(
        "bank after:",
        f"£"
        f"{result.bank_after_tenths / 10:.1f}m",
    )


print()
print(
    "=== JOINT TRANSFER OPTIMIZER ==="
)

print(
    "projection_run:",
    run_dir.name,
)

print(
    "free_transfers:",
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

    for count in range(
        1,
        min(
            3,
            int(
                state_payload[
                    "free_transfers"
                ]
            ),
        )
        + 1,
    ):
        print()
        print(
            f"-- EXACTLY {count} TRANSFER"
            f"{'S' if count != 1 else ''} --"
        )

        result = (
            optimize_starting_xi_transfers(
                players=values,
                state=state,
                horizon=horizon,
                exact_transfers=count,
            )
        )

        print_plan(
            result
        )
