from __future__ import annotations

import json
from pathlib import Path

from fpl_engine.decision import (
    SquadState,
    adapt_player_projections,
    build_player_values,
    build_team_counts,
    rank_transfer_options,
    single_transfer_options,
)


def load_json(path: Path):
    return json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )


root = Path.cwd()

state_path = (
    root
    / "scratch"
    / "decision"
    / "my_squad_gw4.json"
)

state_payload = load_json(
    state_path
)

run_dir = Path(
    state_payload[
        "projection_run"
    ]
)

if not run_dir.is_absolute():
    run_dir = (
        root
        / run_dir
    )

projection_rows = load_json(
    run_dir
    / "player_projections.json"
)

current_players = load_json(
    run_dir
    / "current_players.json"
)

metadata = {
    row["player_id"]: row
    for row in current_players
}

projections = (
    adapt_player_projections(
        projection_rows
    )
)

values = build_player_values(
    projections,
    metadata,
)

values_by_id = {
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

team_counts = build_team_counts(
    squad_ids,
    values_by_id,
)

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
    team_counts=team_counts,
)

over_limit_teams = {
    team_id
    for team_id, count
    in team_counts.items()
    if count > 3
}

if not over_limit_teams:
    raise SystemExit(
        "Squad has no club-limit violation."
    )

forced_sellers = [
    row
    for row in squad_rows
    if row["team_id"]
    in over_limit_teams
]

all_options = []

for seller in forced_sellers:

    options = single_transfer_options(
        sell_player_id=(
            seller["player_id"]
        ),
        players=values,
        state=state,
        hit_cost=0.0,
    )

    all_options.extend(
        options
    )

ranked_3 = (
    rank_transfer_options(
        all_options,
        horizon=3,
    )
)

ranked_6 = (
    rank_transfer_options(
        all_options,
        horizon=6,
    )
)


def print_option(
    index,
    row,
):
    seller = values_by_id[
        row.sell_player_id
    ]

    buyer = values_by_id[
        row.buy_player_id
    ]

    print(
        f"{index:>2}. "
        f"{row.sell_name} -> "
        f"{row.buy_name}"
    )

    print(
        f"    {row.position} | "
        f"sell £{row.sell_price_tenths / 10:.1f} "
        f"-> buy £{row.buy_price_tenths / 10:.1f} "
        f"| bank after "
        f"£{row.bank_after_tenths / 10:.1f}"
    )

    print(
        f"    EV3 "
        f"{seller.ev_3:.2f} -> "
        f"{buyer.ev_3:.2f} "
        f"| gain {row.net_gain_3:+.2f}"
    )

    print(
        f"    EV6 "
        f"{seller.ev_6:.2f} -> "
        f"{buyer.ev_6:.2f} "
        f"| gain {row.net_gain_6:+.2f}"
    )

    print(
        f"    buyer minutes6="
        f"{buyer.minutes_6:.1f} "
        f"conf={buyer.confidence:.2f}"
    )


print()
print(
    "=== REQUIRED CLUB-LIMIT TRANSFER ==="
)

print(
    "free_transfers:",
    state_payload[
        "free_transfers"
    ],
)

print(
    "bank:",
    f"£{state.bank_tenths / 10:.1f}m",
)

print()
print(
    "must sell one of:"
)

for seller in forced_sellers:
    value = values_by_id[
        seller["player_id"]
    ]

    print(
        " -",
        value.name,
        f"({value.position}, "
        f"sell £"
        f"{selling_prices[value.player_id] / 10:.1f})"
    )

print()
print(
    "legal_single_transfer_options:",
    len(all_options),
)

print()
print(
    "=== TOP 10 BY 3-GW GAIN ==="
)

for index, row in enumerate(
    ranked_3[:10],
    start=1,
):
    print_option(
        index,
        row,
    )

print()
print(
    "=== TOP 10 BY 6-GW GAIN ==="
)

for index, row in enumerate(
    ranked_6[:10],
    start=1,
):
    print_option(
        index,
        row,
    )


report = {
    "active_gameweek": (
        state_payload[
            "active_gameweek"
        ]
    ),
    "projection_run": str(
        run_dir
    ),
    "free_transfers": (
        state_payload[
            "free_transfers"
        ]
    ),
    "bank_tenths": (
        state.bank_tenths
    ),
    "forced_sellers": [
        {
            "player_id": (
                row["player_id"]
            ),
            "name": (
                values_by_id[
                    row["player_id"]
                ].name
            ),
            "position": (
                values_by_id[
                    row["player_id"]
                ].position
            ),
            "selling_price_tenths": (
                selling_prices[
                    row["player_id"]
                ]
            ),
        }
        for row in forced_sellers
    ],
    "top_3gw": [
        row.__dict__
        for row in ranked_3
    ],
    "top_6gw": [
        row.__dict__
        for row in ranked_6
    ],
}

output_path = (
    root
    / "scratch"
    / "decision"
    / "gw4_required_transfer_ranking.json"
)

output_path.write_text(
    json.dumps(
        report,
        indent=2,
        ensure_ascii=False,
    ),
    encoding="utf-8",
)

print()
print(
    "saved:",
    output_path,
)
