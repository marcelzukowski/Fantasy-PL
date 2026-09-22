from __future__ import annotations

import json
from pathlib import Path

from fpl_engine.decision import (
    SquadState,
    adapt_player_projections,
    build_player_values,
    build_team_counts,
    evaluate_squad_with_captaincy,
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

projections = adapt_player_projections(
    projection_rows
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
    "=== TRANSFER PLANS + CAPTAINCY ==="
)

print(
    "projection_run:",
    run_dir.name,
)

for horizon in (
    3,
    6,
):

    current_eval = (
        evaluate_squad_with_captaincy(
            squad_player_ids=squad_ids,
            players_by_id=by_id,
            projections_by_id=(
                projections_by_id
            ),
            horizon=horizon,
        )
    )

    print()
    print(
        f"=== HORIZON {horizon} GW ==="
    )

    print(
        "current XI+C weighted EV:",
        f"{current_eval.weighted_total_ev:.2f}",
    )

    for count in (
        1,
        2,
        3,
    ):

        plan = (
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

        if plan is None:
            continue

        final_eval = (
            evaluate_squad_with_captaincy(
                squad_player_ids=set(
                    plan.final_player_ids
                ),
                players_by_id=by_id,
                projections_by_id=(
                    projections_by_id
                ),
                horizon=horizon,
            )
        )

        captaincy_gain = (
            final_eval.weighted_total_ev
            - current_eval.weighted_total_ev
        )

        print()
        print(
            f"-- {count} TRANSFER"
            f"{'S' if count != 1 else ''} --"
        )

        print(
            "OUT:",
            ", ".join(
                names(
                    plan.outgoing_player_ids
                )
            ),
        )

        print(
            "IN: ",
            ", ".join(
                names(
                    plan.incoming_player_ids
                )
            ),
        )

        print(
            "XI-only gain:",
            f"{plan.gain:+.2f}",
        )

        print(
            "XI+C gain:",
            f"{captaincy_gain:+.2f}",
        )

        print(
            "bank after:",
            f"£{plan.bank_after_tenths / 10:.1f}m",
        )

        print(
            "captains:",
            ", ".join(
                f"GW{row.gameweek} "
                f"{by_id[row.captain_player_id].name}"
                for row in final_eval.gameweeks
            ),
        )
