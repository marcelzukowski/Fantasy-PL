from __future__ import annotations

import json
import statistics
from collections import Counter
from pathlib import Path

from fpl_engine.optimizer import (
    OptimizerRules,
)

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


ROOT = Path.cwd()

BASE = (
    ROOT
    / "scratch"
    / "book003"
    / "current_market_shadow"
    / "2026-27"
)


SQUAD_PAYLOAD = json.loads(
    (
        ROOT
        / "scratch"
        / "decision"
        / "my_squad_gw4.json"
    ).read_text(
        encoding="utf-8"
    )
)


CURRENT_IDS = frozenset(
    row["player_id"]
    for row in SQUAD_PAYLOAD[
        "players"
    ]
)


SELLING_PRICES = {
    row["player_id"]:
    int(
        row[
            "selling_price_tenths"
        ]
    )
    for row in SQUAD_PAYLOAD[
        "players"
    ]
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
        f"missing projection "
        f"{projection.player_id} "
        f"GW{gameweek}"
    )


def weighted_player_ev(
    projection,
):
    total = 0.0

    for index, gameweek in enumerate(
        range(
            FIRST_GAMEWEEK,
            FIRST_GAMEWEEK
            + HORIZON,
        )
    ):
        total += (
            WEIGHTS[index]
            * gw_ev(
                projection,
                gameweek,
            )
        )

    return total


def score_squad(
    *,
    squad_ids,
    data,
):
    weighted_xi = 0.0
    weighted_autosub = 0.0
    lineups = {}

    for index, gameweek in enumerate(
        range(
            FIRST_GAMEWEEK,
            FIRST_GAMEWEEK
            + HORIZON,
        )
    ):

        expected_points = {
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
            lineup
            .expected_gk_autosub_ev
            + lineup
            .expected_outfield_autosub_ev
        )

        weight = WEIGHTS[
            index
        ]

        weighted_xi += (
            weight
            * lineup.base_xi_ev
        )

        weighted_autosub += (
            weight
            * autosub_ev
        )

        lineups[
            gameweek
        ] = lineup

    return {
        "xi":
        weighted_xi,
        "autosub":
        weighted_autosub,
        "total":
        (
            weighted_xi
            + weighted_autosub
        ),
        "lineups":
        lineups,
    }


def score_normal_2ft(
    data,
):

    result = (
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
                SQUAD_PAYLOAD[
                    "free_transfers"
                ]
            ),
            captaincy_weight=0.0,
        )
    )

    if result is None:
        raise RuntimeError(
            "normal 2FT plan missing"
        )

    weighted_xi = 0.0
    weighted_autosub = 0.0

    for index, gameweek in enumerate(
        range(
            FIRST_GAMEWEEK,
            FIRST_GAMEWEEK
            + HORIZON,
        )
    ):

        squad_ids = (
            result
            .squad_now_player_ids
            if gameweek
            == FIRST_GAMEWEEK
            else result
            .squad_next_player_ids
        )

        expected_points = {
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
            lineup
            .expected_gk_autosub_ev
            + lineup
            .expected_outfield_autosub_ev
        )

        weighted_xi += (
            WEIGHTS[index]
            * lineup.base_xi_ev
        )

        weighted_autosub += (
            WEIGHTS[index]
            * autosub_ev
        )

    return {
        "plan":
        result,
        "xi":
        weighted_xi,
        "autosub":
        weighted_autosub,
        "total":
        (
            weighted_xi
            + weighted_autosub
        ),
    }


#
# Rules audit
#

print()
print(
    "=== CHIP RULES ==="
)

print()
print(
    "RULE CONFIG:"
    " unavailable at default path;"
    " continuing DECISION-005B "
    "without rules audit."
)

rules_candidates = sorted(
    {
        candidate
        for pattern in (
            "*.yaml",
            "*.yml",
        )
        for candidate in Path.cwd().rglob(
            pattern
        )
        if (
            "rule" in str(
                candidate
            ).casefold()
            or "2026" in str(
                candidate
            ).casefold()
        )
    }
)

print()
print(
    "Possible rule/config files:"
)

if rules_candidates:

    for candidate in (
        rules_candidates[:30]
    ):
        print(
            " ",
            candidate
        )

else:
    print(
        "  NONE FOUND"
    )



#
# Prepare both runs
#

prepared = {}


for run_name in RUNS:

    run_dir = (
        BASE
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
        row["player_id"]:
        row
        for row in player_rows
    }

    projections = (
        adapt_player_projections(
            projection_rows
        )
    )

    projections_by_id = {
        row.player_id:
        row
        for row in projections
    }

    availability = (
        build_gameweek_availability(
            projection_rows,
            minute_rows,
        )
    )

    values = build_player_values(
        projections,
        metadata,
    )

    by_id = {
        row.player_id:
        row
        for row in values
    }

    state = SquadState(
        player_ids=CURRENT_IDS,
        bank_tenths=int(
            SQUAD_PAYLOAD[
                "bank_tenths"
            ]
        ),
        selling_prices_tenths=(
            SELLING_PRICES
        ),
        team_counts=(
            build_team_counts(
                CURRENT_IDS,
                by_id,
            )
        ),
    )

    wildcard = (
        optimize_unlimited_squad(
            player_rows=player_rows,
            projections_by_id=(
                projections_by_id
            ),
            current_player_ids=(
                CURRENT_IDS
            ),
            selling_prices_tenths=(
                SELLING_PRICES
            ),
            bank_tenths=int(
                SQUAD_PAYLOAD[
                    "bank_tenths"
                ]
            ),
            first_gameweek=(
                FIRST_GAMEWEEK
            ),
            horizon=HORIZON,
            weights=WEIGHTS,
        )
    )

    prepared[
        run_name
    ] = {
        "run_dir":
        run_dir,
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
        "wildcard":
        wildcard,
    }


#
# Candidate identity
#

print()
print(
    "=== WILDCARD CANDIDATE IDENTITY ==="
)


wc_sets = {
    run_name:
    data[
        "wildcard"
    ].player_ids
    for run_name, data
    in prepared.items()
}


same_squad = (
    wc_sets[
        RUNS[0]
    ]
    == wc_sets[
        RUNS[1]
    ]
)


print(
    "same 15-player squad:",
    same_squad,
)

print(
    "intersection:",
    len(
        wc_sets[
            RUNS[0]
        ]
        & wc_sets[
            RUNS[1]
        ]
    ),
    "/ 15",
)


unique_candidates = []

for squad in wc_sets.values():

    if squad not in (
        unique_candidates
    ):
        unique_candidates.append(
            squad
        )


#
# Normal baseline
#

normal_scores = {
    run_name:
    score_normal_2ft(
        data
    )
    for run_name, data
    in prepared.items()
}


#
# Cross-run WC scoring
#

print()
print(
    "=== FIXED WILDCARD CROSS-RUN ==="
)


candidate_results = []


for candidate_index, squad in enumerate(
    unique_candidates,
    start=1,
):

    print()
    print(
        "--------------------------------"
    )

    print(
        "WC CANDIDATE",
        candidate_index,
    )

    deltas = []

    totals = []

    for run_name, data in (
        prepared.items()
    ):

        score = score_squad(
            squad_ids=squad,
            data=data,
        )

        baseline = (
            normal_scores[
                run_name
            ]["total"]
        )

        delta = (
            score["total"]
            - baseline
        )

        deltas.append(
            delta
        )

        totals.append(
            score["total"]
        )

        print(
            run_name,
            "| WC:",
            f"{score['total']:.2f}",
            "| normal:",
            f"{baseline:.2f}",
            "| delta:",
            f"{delta:+.2f}",
            "| autosub:",
            f"+{score['autosub']:.2f}",
        )

    print(
        "mean delta:",
        f"{statistics.mean(deltas):+.2f}",
    )

    print(
        "worst delta:",
        f"{min(deltas):+.2f}",
    )

    candidate_results.append(
        (
            statistics.mean(
                deltas
            ),
            min(
                deltas
            ),
            squad,
        )
    )


candidate_results.sort(
    reverse=True,
    key=lambda row: (
        row[1],
        row[0],
    ),
)

best_squad = (
    candidate_results[
        0
    ][2]
)


#
# Detailed squad decomposition
#

print()
print(
    "=== BEST WC SQUAD DECOMPOSITION ==="
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


starter_counts = Counter()

for run_name, data in (
    prepared.items()
):

    score = score_squad(
        squad_ids=best_squad,
        data=data,
    )

    for lineup in (
        score[
            "lineups"
        ].values()
    ):

        starter_counts.update(
            lineup.starter_ids
        )


rows = []


for player_id in best_squad:

    meta = reference[
        "metadata"
    ][player_id]

    raw_weighted_values = []

    app_values = []

    for run_name, data in (
        prepared.items()
    ):

        raw_weighted_values.append(
            weighted_player_ev(
                data[
                    "projections"
                ][player_id]
            )
        )

        app_values.append(
            data[
                "availability"
            ][
                (
                    player_id,
                    4,
                )
            ].p_appearance
        )

    if player_id in CURRENT_IDS:

        accounting_price = (
            SELLING_PRICES[
                player_id
            ]
        )

        status = "KEEP"

    else:

        accounting_price = int(
            meta[
                "current_price"
            ]
        )

        status = "NEW"

    rows.append(
        {
            "position":
            meta[
                "position"
            ],
            "name":
            names[
                player_id
            ],
            "status":
            status,
            "price":
            accounting_price,
            "weighted_ev":
            statistics.mean(
                raw_weighted_values
            ),
            "app":
            statistics.mean(
                app_values
            ),
            "starts":
            starter_counts[
                player_id
            ],
            "player_id":
            player_id,
        }
    )


position_order = {
    "GK": 0,
    "DEF": 1,
    "MID": 2,
    "FWD": 3,
}


rows.sort(
    key=lambda row: (
        position_order[
            row[
                "position"
            ]
        ],
        -row[
            "weighted_ev"
        ],
        row[
            "name"
        ],
    )
)


print(
    "POS | PLAYER"
    " | STATUS"
    " | PRICE"
    " | MEAN WEV6"
    " | APP"
    " | XI COUNT / 12"
)


for row in rows:

    print(
        f"{row['position']:3} | "
        f"{row['name']:<20} | "
        f"{row['status']:4} | "
        f"£{row['price']/10:4.1f} | "
        f"{row['weighted_ev']:7.2f} | "
        f"{row['app']:.3f} | "
        f"{row['starts']:2}/12"
    )


#
# Budget decomposition
#

liquidation_budget = (
    int(
        SQUAD_PAYLOAD[
            "bank_tenths"
        ]
    )
    + sum(
        SELLING_PRICES.values()
    )
)


accounting_cost = sum(
    row[
        "price"
    ]
    for row in rows
)


print()
print(
    "=== WC BUDGET ==="
)

print(
    "liquidation budget:",
    f"£{liquidation_budget/10:.1f}m",
)

print(
    "selected cost:",
    f"£{accounting_cost/10:.1f}m",
)

print(
    "unused:",
    f"£{(
        liquidation_budget
        - accounting_cost
    )/10:.1f}m",
)


#
# Retained / replaced
#

print()
print(
    "=== WC STRUCTURE ==="
)


kept = (
    CURRENT_IDS
    & best_squad
)

outgoing = (
    CURRENT_IDS
    - best_squad
)

incoming = (
    best_squad
    - CURRENT_IDS
)


print(
    "KEEP:",
    ", ".join(
        sorted(
            names[
                player_id
            ]
            for player_id
            in kept
        )
    ),
)

print(
    "OUT:",
    ", ".join(
        sorted(
            names[
                player_id
            ]
            for player_id
            in outgoing
        )
    ),
)

print(
    "IN:",
    ", ".join(
        sorted(
            names[
                player_id
            ]
            for player_id
            in incoming
        )
    ),
)


print()
print(
    "=== DECISION-005B SUMMARY ==="
)

print(
    "unique WC candidates:",
    len(
        unique_candidates
    ),
)

print(
    "best cross-run mean delta:",
    f"{candidate_results[0][0]:+.2f}",
)

print(
    "best cross-run worst delta:",
    f"{candidate_results[0][1]:+.2f}",
)
