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

from fpl_engine.decision.availability_adapter import (
    build_gameweek_availability,
)

from fpl_engine.decision.autosubs import (
    optimize_autosub_lineup,
)

from fpl_engine.decision.chip_squads import (
    optimize_unlimited_squad,
)


RUNS = (
    "20260912T082141Z",
    "20260912T082424Z",
)

FIRST_GAMEWEEK = 4

WEIGHTS = (
    1.00,
    0.95,
    0.90,
    0.85,
    0.80,
    0.75,
)


root = Path.cwd()

base = (
    root
    / "scratch"
    / "book003"
    / "current_market_shadow"
    / "2026-27"
)

squad_payload = json.loads(
    (
        root
        / "scratch"
        / "decision"
        / "my_squad_gw4.json"
    ).read_text(
        encoding="utf-8"
    )
)

current_ids = frozenset(
    row["player_id"]
    for row
    in squad_payload["players"]
)

selling_prices = {
    row["player_id"]:
    int(
        row[
            "selling_price_tenths"
        ]
    )
    for row
    in squad_payload["players"]
}


def load(
    run_dir,
    name,
):
    return json.loads(
        (
            run_dir
            / name
        ).read_text(
            encoding="utf-8"
        )
    )


def gameweek_ev(
    projection,
    gameweek,
):

    for row in projection.gameweeks:

        if row.gameweek == gameweek:
            return float(
                row.expected_points
            )

    raise RuntimeError(
        f"missing GW{gameweek}"
    )


def score_squad(
    *,
    squad_ids,
    data,
    gameweeks,
):

    weighted_xi = 0.0
    weighted_autosub = 0.0

    details = {}

    for index, gameweek in enumerate(
        gameweeks
    ):

        expected_points = {
            player_id:
            gameweek_ev(
                data[
                    "projections"
                ][player_id],
                gameweek,
            )
            for player_id
            in squad_ids
        }

        positions = {
            player_id:
            data[
                "metadata"
            ][player_id][
                "position"
            ]
            for player_id
            in squad_ids
        }

        p_appearance = {
            player_id:
            data[
                "availability"
            ][
                (
                    player_id,
                    gameweek,
                )
            ].p_appearance
            for player_id
            in squad_ids
        }

        lineup = (
            optimize_autosub_lineup(
                gameweek=gameweek,
                squad_ids=squad_ids,
                positions=positions,
                expected_points=(
                    expected_points
                ),
                p_appearance=(
                    p_appearance
                ),
            )
        )

        autosub = (
            lineup
            .expected_gk_autosub_ev
            + lineup
            .expected_outfield_autosub_ev
        )

        weight = WEIGHTS[
            gameweek
            - FIRST_GAMEWEEK
        ]

        weighted_xi += (
            lineup.base_xi_ev
            * weight
        )

        weighted_autosub += (
            autosub
            * weight
        )

        details[
            gameweek
        ] = lineup

    return {
        "xi": weighted_xi,
        "autosub":
        weighted_autosub,
        "total":
        weighted_xi
        + weighted_autosub,
        "details":
        details,
    }


def score_normal_rolling(
    *,
    data,
):

    result = (
        optimize_rolling_free_transfers(
            players=data["values"],
            projections_by_id=(
                data["projections"]
            ),
            state=data["state"],
            horizon=6,
            transfers_now=2,
            current_free_transfers=int(
                squad_payload[
                    "free_transfers"
                ]
            ),
            captaincy_weight=0.0,
        )
    )

    if result is None:
        raise RuntimeError(
            "normal 2FT plan unavailable"
        )

    total_xi = 0.0
    total_autosub = 0.0

    details = {}

    for index, gameweek in enumerate(
        range(
            FIRST_GAMEWEEK,
            FIRST_GAMEWEEK + 6,
        )
    ):

        if gameweek == 4:
            squad_ids = (
                result
                .squad_now_player_ids
            )
        else:
            squad_ids = (
                result
                .squad_next_player_ids
            )

        score = score_squad(
            squad_ids=squad_ids,
            data=data,
            gameweeks=(
                gameweek,
            ),
        )

        #
        # score_squad applies correct
        # weight using actual GW index.
        #

        total_xi += score["xi"]
        total_autosub += (
            score["autosub"]
        )

        details[
            gameweek
        ] = score[
            "details"
        ][gameweek]

    return {
        "plan": result,
        "xi": total_xi,
        "autosub":
        total_autosub,
        "total":
        total_xi
        + total_autosub,
        "details":
        details,
    }


prepared = {}


for run_name in RUNS:

    run_dir = (
        base
        / run_name
    )

    projection_rows = load(
        run_dir,
        "player_projections.json",
    )

    player_rows = load(
        run_dir,
        "current_players.json",
    )

    minute_rows = load(
        run_dir,
        "minutes.json",
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

    availability = (
        build_gameweek_availability(
            projection_rows,
            minute_rows,
        )
    )

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
        run_name
    ] = {
        "run_dir": run_dir,
        "projection_rows":
        projection_rows,
        "player_rows":
        player_rows,
        "metadata":
        metadata,
        "projections":
        projections_by_id,
        "availability":
        availability,
        "values":
        values,
        "by_id":
        by_id,
        "state":
        state,
    }


print()
print(
    "=== DECISION-005A CHIP SCREEN ==="
)

print(
    "NOTE: screening only."
)

print(
    "WC = static post-WC squad "
    "for 6 GW; no future transfers."
)

print(
    "FH = immediate GW4 comparison "
    "only."
)


fh_gains = []
wc_deltas = []


for run_name, data in (
    prepared.items()
):

    names = {
        player_id:
        row[
            "display_name"
        ]
        for player_id, row
        in data[
            "metadata"
        ].items()
    }

    normal = (
        score_normal_rolling(
            data=data
        )
    )

    fh_plan = (
        optimize_unlimited_squad(
            player_rows=(
                data[
                    "player_rows"
                ]
            ),
            projections_by_id=(
                data[
                    "projections"
                ]
            ),
            current_player_ids=(
                current_ids
            ),
            selling_prices_tenths=(
                selling_prices
            ),
            bank_tenths=int(
                squad_payload[
                    "bank_tenths"
                ]
            ),
            first_gameweek=4,
            horizon=1,
            weights=WEIGHTS,
        )
    )

    wc_plan = (
        optimize_unlimited_squad(
            player_rows=(
                data[
                    "player_rows"
                ]
            ),
            projections_by_id=(
                data[
                    "projections"
                ]
            ),
            current_player_ids=(
                current_ids
            ),
            selling_prices_tenths=(
                selling_prices
            ),
            bank_tenths=int(
                squad_payload[
                    "bank_tenths"
                ]
            ),
            first_gameweek=4,
            horizon=6,
            weights=WEIGHTS,
        )
    )

    fh_score = score_squad(
        squad_ids=(
            fh_plan.player_ids
        ),
        data=data,
        gameweeks=(4,),
    )

    wc_score = score_squad(
        squad_ids=(
            wc_plan.player_ids
        ),
        data=data,
        gameweeks=tuple(
            range(
                4,
                10,
            )
        ),
    )

    normal_gw4 = (
        normal[
            "details"
        ][4]
    )

    normal_gw4_total = (
        normal_gw4.base_xi_ev
        + normal_gw4
        .expected_gk_autosub_ev
        + normal_gw4
        .expected_outfield_autosub_ev
    )

    fh_gain = (
        fh_score[
            "total"
        ]
        - normal_gw4_total
    )

    wc_delta = (
        wc_score[
            "total"
        ]
        - normal[
            "total"
        ]
    )

    fh_gains.append(
        fh_gain
    )

    wc_deltas.append(
        wc_delta
    )

    print()
    print(
        "================================"
    )
    print(
        "RUN:",
        run_name
    )

    print()
    print(
        "NORMAL 2FT ROLLING"
    )

    normal_plan = (
        normal["plan"]
    )

    print(
        "GW4 OUT:",
        ", ".join(
            names[player_id]
            for player_id
            in normal_plan
            .outgoing_now_player_ids
        ),
    )

    print(
        "GW4 IN: ",
        ", ".join(
            names[player_id]
            for player_id
            in normal_plan
            .incoming_now_player_ids
        ),
    )

    print(
        "6GW bench-aware:",
        f"{normal['total']:.2f}",
    )

    print()
    print(
        "FREE HIT SCREEN"
    )

    fh_out = (
        current_ids
        - fh_plan.player_ids
    )

    fh_in = (
        fh_plan.player_ids
        - current_ids
    )

    print(
        "changes:",
        len(fh_in),
    )

    print(
        "GW4 bench-aware:",
        f"{fh_score['total']:.2f}",
    )

    print(
        "normal GW4:",
        f"{normal_gw4_total:.2f}",
    )

    print(
        "immediate gain:",
        f"{fh_gain:+.2f}",
    )

    print(
        "IN:",
        ", ".join(
            sorted(
                names[player_id]
                for player_id
                in fh_in
            )
        ),
    )

    print()
    print(
        "WILDCARD SCREEN"
    )

    wc_out = (
        current_ids
        - wc_plan.player_ids
    )

    wc_in = (
        wc_plan.player_ids
        - current_ids
    )

    print(
        "changes:",
        len(wc_in),
    )

    print(
        "6GW static "
        "bench-aware:",
        f"{wc_score['total']:.2f}",
    )

    print(
        "normal rolling:",
        f"{normal['total']:.2f}",
    )

    print(
        "conservative delta:",
        f"{wc_delta:+.2f}",
    )

    print(
        "remaining budget:",
        f"£{
            wc_plan
            .remaining_budget_tenths
            / 10:.1f}m"
    )

    print(
        "IN:",
        ", ".join(
            sorted(
                names[player_id]
                for player_id
                in wc_in
            )
        ),
    )


print()
print(
    "================================"
)
print(
    "=== CHIP SCREEN CONSENSUS ==="
)

print(
    "FH immediate gain:",
    " | ".join(
        f"{value:+.2f}"
        for value in fh_gains
    ),
)

print(
    "FH mean:",
    f"{statistics.mean(fh_gains):+.2f}",
)

print(
    "FH worst:",
    f"{min(fh_gains):+.2f}",
)

print()

print(
    "WC conservative delta:",
    " | ".join(
        f"{value:+.2f}"
        for value in wc_deltas
    ),
)

print(
    "WC mean:",
    f"{statistics.mean(wc_deltas):+.2f}",
)

print(
    "WC worst:",
    f"{min(wc_deltas):+.2f}",
)
