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


MIN_SIMULATIONS = 64
ACTIVE_GAMEWEEK = 4


def load_json(path):
    return json.loads(
        Path(path).read_text(
            encoding="utf-8"
        )
    )


def estimate_simulation_count(
    rows,
):
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

                if (
                    0.0 < value < 1.0
                ):
                    probabilities.append(
                        value
                    )

    if not probabilities:
        return 1

    return round(
        1.0
        / min(probabilities)
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

squad_ids = frozenset(
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

qualified_runs = []

for projection_path in base.glob(
    "*/player_projections.json"
):

    projection_rows = load_json(
        projection_path
    )

    if not projection_rows:
        continue

    if (
        projection_rows[0].get(
            "current_gameweek"
        )
        != ACTIVE_GAMEWEEK
    ):
        continue

    simulations = (
        estimate_simulation_count(
            projection_rows
        )
    )

    if (
        simulations
        < MIN_SIMULATIONS
    ):
        continue

    qualified_runs.append(
        (
            projection_path.parent,
            simulations,
        )
    )


qualified_runs.sort(
    key=lambda item: (
        item[0].name
    )
)


print()
print(
    "=== XI-ONLY TRANSFER ROBUSTNESS AUDIT ==="
)

print(
    "production-quality runs:",
    len(
        qualified_runs
    ),
)

audit = {}


for run_dir, simulations in (
    qualified_runs
):

    print()
    print(
        "================================"
    )

    print(
        "RUN:",
        run_dir.name,
        "| simulations:",
        simulations,
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

    missing = (
        set(squad_ids)
        - set(metadata)
    )

    if missing:
        raise SystemExit(
            f"{run_dir.name}: "
            "current squad IDs missing"
        )

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
        player_ids=squad_ids,
        bank_tenths=int(
            squad_payload[
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
        return tuple(
            by_id[
                player_id
            ].name
            for player_id in ids
        )


    audit[
        run_dir.name
    ] = {}

    for horizon in (
        3,
        6,
    ):

        print()
        print(
            f"--- HORIZON {horizon} GW ---"
        )

        horizon_results = []

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
                        squad_payload[
                            "free_transfers"
                        ]
                    ),
                    captaincy_weight=0.0,
                )
            )

            if result is None:
                continue

            horizon_results.append(
                result
            )

            print()
            print(
                f"{transfers_now} FT NOW"
            )

            print(
                "  GW4 OUT:",
                ", ".join(
                    names(
                        result
                        .outgoing_now_player_ids
                    )
                ),
            )

            print(
                "  GW4 IN: ",
                ", ".join(
                    names(
                        result
                        .incoming_now_player_ids
                    )
                ),
            )

            print(
                "  gain:",
                f"{result.gain:+.2f}",
            )

            print(
                "  GW5 FT:",
                result.transfers_next_week,
            )

        best = max(
            horizon_results,
            key=lambda row: (
                row.final_weighted_total_ev
            ),
        )

        by_count = {
            row.transfers_now: row
            for row in horizon_results
        }

        print()
        print(
            "BEST COUNT:",
            best.transfers_now,
            "FT",
        )

        if (
            2 in by_count
            and 3 in by_count
        ):

            margin = (
                by_count[3].gain
                - by_count[2].gain
            )

            print(
                "3FT vs 2FT margin:",
                f"{margin:+.2f}",
            )

        audit[
            run_dir.name
        ][
            horizon
        ] = {
            "best_count": (
                best.transfers_now
            ),
            "best_gain": (
                best.gain
            ),
            "out_now": names(
                best
                .outgoing_now_player_ids
            ),
            "in_now": names(
                best
                .incoming_now_player_ids
            ),
            "margin_3_vs_2": (
                (
                    by_count[3].gain
                    - by_count[2].gain
                )
                if (
                    2 in by_count
                    and 3 in by_count
                )
                else None
            ),
        }


print()
print(
    "================================"
)
print(
    "=== CONSENSUS ==="
)

for horizon in (
    3,
    6,
):

    records = [
        (
            run_name,
            data[horizon]
        )
        for run_name, data
        in audit.items()
        if horizon in data
    ]

    counts = [
        data[
            "best_count"
        ]
        for _, data
        in records
    ]

    print()
    print(
        f"HORIZON {horizon}:"
    )

    print(
        "best transfer counts:",
        counts,
    )

    print(
        "count consensus:",
        (
            len(
                set(counts)
            )
            == 1
        ),
    )

    for run_name, data in (
        records
    ):

        print(
            run_name,
            "|",
            data[
                "best_count"
            ],
            "FT",
            "| IN:",
            ", ".join(
                data[
                    "in_now"
                ]
            ),
            "| margin 3v2:",
            (
                f"{data['margin_3_vs_2']:+.2f}"
                if (
                    data[
                        "margin_3_vs_2"
                    ]
                    is not None
                )
                else "n/a"
            ),
        )
