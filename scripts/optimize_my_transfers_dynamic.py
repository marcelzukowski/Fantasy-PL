from __future__ import annotations

import json
from pathlib import Path

from fpl_engine.decision import (
    SquadState,
    adapt_player_projections,
    build_player_values,
    build_team_counts,
    optimize_multi_gameweek_transfers,
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
    run_dir = root / run_dir

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
        row["selling_price_tenths"]
    )
    for row in squad_rows
}

state = SquadState(
    player_ids=squad_ids,
    bank_tenths=int(
        state_payload["bank_tenths"]
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
    "=== DYNAMIC MULTI-GW TRANSFER OPTIMIZER ==="
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

        result = (
            optimize_multi_gameweek_transfers(
                players=values,
                projections_by_id=(
                    projections_by_id
                ),
                state=state,
                horizon=horizon,
                exact_transfers=count,
            )
        )

        print()
        print(
            f"-- {count} TRANSFER"
            f"{'S' if count != 1 else ''} --"
        )

        if result is None:
            print(
                "NO FEASIBLE PLAN"
            )
            continue

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
            "weighted XI EV:",
            f"{result.current_weighted_lineup_ev:.2f}",
            "->",
            f"{result.final_weighted_lineup_ev:.2f}",
        )

        print(
            "gain:",
            f"{result.gain:+.2f}",
        )

        print(
            "bank after:",
            f"£{result.bank_after_tenths / 10:.1f}m",
        )

        rotations = []

        for gameweek, starters in (
            result
            .starting_xi_by_gameweek
        ):
            rotations.append(
                f"GW{gameweek}:"
                + "/".join(
                    names(starters)
                )
            )

        print(
            "lineups optimized:",
            len(rotations),
            "gameweeks",
        )
