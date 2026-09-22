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


RUNS = (
    "20260911T212832Z",
    "20260911T214014Z",
)

FIRST_GAMEWEEK = 4
HORIZON = 6

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
        row["selling_price_tenths"]
    )
    for row
    in squad_payload["players"]
}


def load(
    run_dir,
    filename,
):
    return json.loads(
        (
            run_dir
            / filename
        ).read_text(
            encoding="utf-8"
        )
    )


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
        "projections": (
            projections_by_id
        ),
        "values": values,
        "by_id": by_id,
        "availability": availability,
        "state": state,
    }


#
# Collect unique best 2-FT / 3-FT
# GW4 squads proposed by either run.
#

candidate_squads = {}


for run_name, data in (
    prepared.items()
):

    for count in (
        2,
        3,
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
        "missing projection "
        f"{projection.player_id} "
        f"GW{gameweek}"
    )


def score_rolling_plan(
    *,
    data,
    result,
):

    weighted_base = 0.0
    weighted_autosub = 0.0
    weighted_total = 0.0

    lineup_rows = {}

    for index in range(
        HORIZON
    ):

        gameweek = (
            FIRST_GAMEWEEK
            + index
        )

        weight = WEIGHTS[
            index
        ]

        squad_ids = (
            result.squad_now_player_ids
            if gameweek
            == FIRST_GAMEWEEK
            else result.squad_next_player_ids
        )

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
            data["by_id"][
                player_id
            ].position
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

        autosub_ev = (
            lineup.expected_gk_autosub_ev
            + lineup.expected_outfield_autosub_ev
        )

        weighted_base += (
            lineup.base_xi_ev
            * weight
        )

        weighted_autosub += (
            autosub_ev
            * weight
        )

        weighted_total += (
            lineup.total_ev
            * weight
        )

        lineup_rows[
            gameweek
        ] = lineup

    return {
        "base": weighted_base,
        "autosub": weighted_autosub,
        "total": weighted_total,
        "lineups": lineup_rows,
    }


first_data = prepared[
    RUNS[0]
]

names = {
    player_id: row.name
    for player_id, row
    in first_data[
        "by_id"
    ].items()
}

positions_all = {
    player_id: row.position
    for player_id, row
    in first_data[
        "by_id"
    ].items()
}


evaluated = []


print()
print(
    "=== BENCH-AWARE FIXED-PLAN AUDIT ==="
)

print(
    "candidate plans:",
    len(candidate_squads),
)


for plan_index, (
    squad_tuple,
    meta,
) in enumerate(
    candidate_squads.items(),
    start=1,
):

    fixed_squad = frozenset(
        squad_tuple
    )

    outgoing = (
        current_ids
        - fixed_squad
    )

    incoming = (
        fixed_squad
        - current_ids
    )

    print()
    print(
        "================================"
    )

    print(
        f"PLAN {plan_index}"
    )

    print(
        "transfers:",
        meta["count"],
    )

    print(
        "origins:",
        ", ".join(
            meta["origins"]
        ),
    )


    for position in (
        "GK",
        "DEF",
        "MID",
        "FWD",
    ):

        outs = sorted(
            names[player_id]
            for player_id
            in outgoing
            if positions_all[
                player_id
            ]
            == position
        )

        ins = sorted(
            names[player_id]
            for player_id
            in incoming
            if positions_all[
                player_id
            ]
            == position
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


    run_totals = []
    run_scores = {}


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
                transfers_now=(
                    meta["count"]
                ),
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

            print(
                run_name,
                "| INVALID",
            )
            continue

        score = score_rolling_plan(
            data=data,
            result=result,
        )

        run_scores[
            run_name
        ] = score

        run_totals.append(
            score["total"]
        )

        print()
        print(
            run_name
        )

        print(
            "  weighted XI:",
            f"{score['base']:.2f}",
        )

        print(
            "  weighted autosub:",
            f"+{score['autosub']:.2f}",
        )

        print(
            "  weighted total:",
            f"{score['total']:.2f}",
        )

        print(
            "  GW5 FT used:",
            result.transfers_next_week,
        )

        gw4 = score[
            "lineups"
        ][4]

        print(
            "  GW4 bench GK:",
            names[
                gw4.bench_gk_id
            ],
        )

        print(
            "  GW4 bench 1-3:",
            " | ".join(
                names[player_id]
                for player_id
                in gw4.bench_outfield_ids
            ),
        )

        print(
            "  GW4 autosub EV:",
            f"+{(
                gw4.expected_gk_autosub_ev
                + gw4.expected_outfield_autosub_ev
            ):.3f}",
        )


    if len(run_totals) != len(
        prepared
    ):
        mean_total = float("-inf")
        worst_total = float("-inf")
        spread = float("inf")

    else:

        mean_total = statistics.mean(
            run_totals
        )

        worst_total = min(
            run_totals
        )

        spread = (
            statistics.pstdev(
                run_totals
            )
        )


    print()
    print(
        "ROBUST METRICS"
    )

    print(
        "  mean:",
        f"{mean_total:.2f}",
    )

    print(
        "  worst:",
        f"{worst_total:.2f}",
    )

    print(
        "  spread:",
        f"{spread:.2f}",
    )


    evaluated.append(
        {
            "index": plan_index,
            "count": meta[
                "count"
            ],
            "mean": mean_total,
            "worst": worst_total,
            "spread": spread,
            "run_scores": run_scores,
            "outgoing": outgoing,
            "incoming": incoming,
        }
    )


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
    "=== BENCH-AWARE ROBUST RANKING ==="
)


for rank, row in enumerate(
    ranking,
    start=1,
):

    print()
    print(
        f"{rank}. PLAN "
        f"{row['index']} "
        f"| {row['count']} FT"
    )

    print(
        "   OUT:",
        ", ".join(
            sorted(
                names[player_id]
                for player_id
                in row["outgoing"]
            )
        ),
    )

    print(
        "   IN: ",
        ", ".join(
            sorted(
                names[player_id]
                for player_id
                in row["incoming"]
            )
        ),
    )

    print(
        "   mean:",
        f"{row['mean']:.2f}",
        "| worst:",
        f"{row['worst']:.2f}",
        "| spread:",
        f"{row['spread']:.2f}",
    )


best_two = max(
    (
        row
        for row in evaluated
        if row["count"] == 2
    ),
    key=lambda row: (
        row["worst"],
        row["mean"],
    ),
)

best_three = max(
    (
        row
        for row in evaluated
        if row["count"] == 3
    ),
    key=lambda row: (
        row["worst"],
        row["mean"],
    ),
)


print()
print(
    "================================"
)
print(
    "=== 3 FT VS 2 FT ==="
)


differences = []

for run_name in RUNS:

    difference = (
        best_three[
            "run_scores"
        ][run_name]["total"]
        - best_two[
            "run_scores"
        ][run_name]["total"]
    )

    differences.append(
        difference
    )

    print(
        run_name,
        "| 3FT - 2FT:",
        f"{difference:+.2f}",
    )


print(
    "mean advantage:",
    f"{statistics.mean(differences):+.2f}",
)

print(
    "worst-run advantage:",
    f"{min(differences):+.2f}",
)
