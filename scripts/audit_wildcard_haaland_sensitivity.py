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
    "20260911T212832Z",
    "20260911T214014Z",
)

FIRST_GW = 4

WEIGHTS = (
    1.00,
    0.95,
    0.90,
    0.85,
    0.80,
    0.75,
)


ROOT = Path.cwd()

BASE = (
    ROOT
    / "scratch"
    / "book003"
    / "current_market_shadow"
    / "2026-27"
)

SQUAD = json.loads(
    (
        ROOT
        / "scratch"
        / "decision"
        / "my_squad_gw4.json"
    ).read_text(
        encoding="utf-8"
    )
)

CURRENT = frozenset(
    row["player_id"]
    for row in SQUAD["players"]
)

SELLING = {
    row["player_id"]:
    int(
        row[
            "selling_price_tenths"
        ]
    )
    for row in SQUAD["players"]
}


def load(
    directory,
    name,
):
    return json.loads(
        (
            directory
            / name
        ).read_text(
            encoding="utf-8"
        )
    )


def gw_ev(
    projection,
    gameweek,
):

    for row in projection.gameweeks:

        if row.gameweek == gameweek:
            return float(
                row.expected_points
            )

    raise RuntimeError(
        "missing GW projection"
    )


def score(
    squad_ids,
    data,
):

    total = 0.0
    xi_total = 0.0
    autosub_total = 0.0

    for index, gameweek in enumerate(
        range(
            4,
            10,
        )
    ):

        points = {
            player_id:
            gw_ev(
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

        appearance = {
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
                expected_points=points,
                p_appearance=appearance,
            )
        )

        autosub = (
            lineup
            .expected_gk_autosub_ev
            + lineup
            .expected_outfield_autosub_ev
        )

        weight = WEIGHTS[index]

        xi_total += (
            weight
            * lineup.base_xi_ev
        )

        autosub_total += (
            weight
            * autosub
        )

        total += (
            weight
            * (
                lineup.base_xi_ev
                + autosub
            )
        )

    return {
        "total": total,
        "xi": xi_total,
        "autosub":
        autosub_total,
    }


def normal_2ft(
    data,
):

    plan = (
        optimize_rolling_free_transfers(
            players=data[
                "values"
            ],
            projections_by_id=data[
                "projections"
            ],
            state=data[
                "state"
            ],
            horizon=6,
            transfers_now=2,
            current_free_transfers=int(
                SQUAD[
                    "free_transfers"
                ]
            ),
            captaincy_weight=0.0,
        )
    )

    total = 0.0

    for index, gameweek in enumerate(
        range(
            4,
            10,
        )
    ):

        squad_ids = (
            plan.squad_now_player_ids
            if gameweek == 4
            else plan.squad_next_player_ids
        )

        points = {
            player_id:
            gw_ev(
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

        appearance = {
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
                expected_points=points,
                p_appearance=appearance,
            )
        )

        autosub = (
            lineup
            .expected_gk_autosub_ev
            + lineup
            .expected_outfield_autosub_ev
        )

        total += (
            WEIGHTS[index]
            * (
                lineup.base_xi_ev
                + autosub
            )
        )

    return total


prepared = {}


for run_name in RUNS:

    directory = (
        BASE
        / run_name
    )

    projection_rows = load(
        directory,
        "player_projections.json",
    )

    player_rows = load(
        directory,
        "current_players.json",
    )

    minute_rows = load(
        directory,
        "minutes.json",
    )

    metadata = {
        row["player_id"]:
        row
        for row in player_rows
    }

    adapted = (
        adapt_player_projections(
            projection_rows
        )
    )

    projections = {
        row.player_id:
        row
        for row in adapted
    }

    values = (
        build_player_values(
            adapted,
            metadata,
        )
    )

    by_id = {
        row.player_id:
        row
        for row in values
    }

    availability = (
        build_gameweek_availability(
            projection_rows,
            minute_rows,
        )
    )

    state = SquadState(
        player_ids=CURRENT,
        bank_tenths=int(
            SQUAD[
                "bank_tenths"
            ]
        ),
        selling_prices_tenths=(
            SELLING
        ),
        team_counts=(
            build_team_counts(
                CURRENT,
                by_id,
            )
        ),
    )

    haaland = next(
        player_id
        for player_id, row
        in metadata.items()
        if row[
            "display_name"
        ] == "Haaland"
    )

    prepared[
        run_name
    ] = {
        "player_rows":
        player_rows,
        "metadata":
        metadata,
        "projections":
        projections,
        "values":
        values,
        "availability":
        availability,
        "state":
        state,
        "haaland":
        haaland,
    }


print()
print(
    "=== DECISION-005B.1 "
    "HAALAND SENSITIVITY ==="
)


forced_candidates = []


for run_name, data in (
    prepared.items()
):

    unconstrained = (
        optimize_unlimited_squad(
            player_rows=data[
                "player_rows"
            ],
            projections_by_id=data[
                "projections"
            ],
            current_player_ids=(
                CURRENT
            ),
            selling_prices_tenths=(
                SELLING
            ),
            bank_tenths=int(
                SQUAD[
                    "bank_tenths"
                ]
            ),
            first_gameweek=4,
            horizon=6,
            weights=WEIGHTS,
        )
    )

    forced = (
        optimize_unlimited_squad(
            player_rows=data[
                "player_rows"
            ],
            projections_by_id=data[
                "projections"
            ],
            current_player_ids=(
                CURRENT
            ),
            selling_prices_tenths=(
                SELLING
            ),
            bank_tenths=int(
                SQUAD[
                    "bank_tenths"
                ]
            ),
            first_gameweek=4,
            horizon=6,
            weights=WEIGHTS,
            required_player_ids=(
                data[
                    "haaland"
                ],
            ),
        )
    )

    forced_candidates.append(
        forced.player_ids
    )

    raw = score(
        unconstrained.player_ids,
        data,
    )

    safe = score(
        forced.player_ids,
        data,
    )

    baseline = normal_2ft(
        data
    )

    haaland_projection = (
        data[
            "projections"
        ][
            data[
                "haaland"
            ]
        ]
    )

    haaland_wev = sum(
        WEIGHTS[index]
        * gw_ev(
            haaland_projection,
            gameweek,
        )
        for index, gameweek
        in enumerate(
            range(
                4,
                10,
            )
        )
    )

    print()
    print(
        "================================"
    )

    print(
        "RUN:",
        run_name,
    )

    print(
        "Haaland raw WEV6:",
        f"{haaland_wev:.2f}",
    )

    print(
        "normal 2FT:",
        f"{baseline:.2f}",
    )

    print(
        "WC unconstrained:",
        f"{raw['total']:.2f}",
        "| delta:",
        f"{raw['total']-baseline:+.2f}",
    )

    print(
        "WC + Haaland:",
        f"{safe['total']:.2f}",
        "| delta:",
        f"{safe['total']-baseline:+.2f}",
    )

    print(
        "cost of forcing Haaland:",
        f"{raw['total']-safe['total']:+.2f}",
    )

    print(
        "WC+H unused budget:",
        f"£{
            forced
            .remaining_budget_tenths
            / 10:.1f}m"
    )


unique_forced = []

for candidate in forced_candidates:

    if candidate not in unique_forced:
        unique_forced.append(
            candidate
        )


print()
print(
    "=== FORCED-HAALAND "
    "CANDIDATE STABILITY ==="
)

print(
    "unique candidates:",
    len(
        unique_forced
    ),
)


for index, candidate in enumerate(
    unique_forced,
    start=1,
):

    print()
    print(
        "--------------------------------"
    )

    print(
        "CANDIDATE",
        index,
    )

    deltas = []

    costs = []

    for run_name, data in (
        prepared.items()
    ):

        candidate_score = score(
            candidate,
            data,
        )["total"]

        baseline = normal_2ft(
            data
        )

        unconstrained = (
            optimize_unlimited_squad(
                player_rows=data[
                    "player_rows"
                ],
                projections_by_id=data[
                    "projections"
                ],
                current_player_ids=(
                    CURRENT
                ),
                selling_prices_tenths=(
                    SELLING
                ),
                bank_tenths=int(
                    SQUAD[
                        "bank_tenths"
                    ]
                ),
                first_gameweek=4,
                horizon=6,
                weights=WEIGHTS,
            )
        )

        raw_score = score(
            unconstrained.player_ids,
            data,
        )["total"]

        delta = (
            candidate_score
            - baseline
        )

        cost = (
            raw_score
            - candidate_score
        )

        deltas.append(
            delta
        )

        costs.append(
            cost
        )

        print(
            run_name,
            "| WC+H:",
            f"{candidate_score:.2f}",
            "| delta:",
            f"{delta:+.2f}",
            "| vs raw WC:",
            f"{-cost:+.2f}",
        )

    reference = prepared[
        RUNS[0]
    ]

    names = {
        player_id:
        row[
            "display_name"
        ]
        for player_id, row
        in reference[
            "metadata"
        ].items()
    }

    outgoing = (
        CURRENT
        - candidate
    )

    incoming = (
        candidate
        - CURRENT
    )

    print(
        "mean delta vs 2FT:",
        f"{statistics.mean(deltas):+.2f}",
    )

    print(
        "worst delta vs 2FT:",
        f"{min(deltas):+.2f}",
    )

    print(
        "mean Haaland retention cost:",
        f"{statistics.mean(costs):.2f}",
    )

    print(
        "KEEP HAALAND:",
        (
            reference[
                "haaland"
            ]
            in candidate
        ),
    )

    print(
        "OUT:",
        ", ".join(
            sorted(
                names[player_id]
                for player_id
                in outgoing
            )
        ),
    )

    print(
        "IN:",
        ", ".join(
            sorted(
                names[player_id]
                for player_id
                in incoming
            )
        ),
    )
