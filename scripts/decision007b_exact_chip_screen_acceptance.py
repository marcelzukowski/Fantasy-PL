from __future__ import annotations

from pathlib import Path
import json

from fpl_engine.decision.chip_screen import (
    screen_chips_exact,
)

from fpl_engine.decision.projection_adapter import (
    adapt_player_projections,
)


ROOT = Path(".").resolve()

RUN = (
    ROOT
    / "scratch"
    / "decision"
    / "captain068g"
    / "integrated_replay"
    / "v22_real"
)

REFERENCE = (
    ROOT
    / "scratch"
    / "decision"
    / "captain068h"
    / "decision_42.json"
)

REPORT = (
    ROOT
    / "scratch"
    / "decision"
    / "decision007b"
    / "acceptance.json"
)


def load(
    path,
):

    return json.loads(
        Path(path).read_text(
            encoding="utf-8"
        )
    )


reference = load(
    REFERENCE
)


projection_rows = load(
    RUN
    / "player_projections.json"
)


projections = {
    row.player_id:
        row
    for row
    in adapt_player_projections(
        projection_rows
    )
}


players = load(
    RUN
    / "current_players.json"
)


player_rows = []


positions = {}


for row in players:

    player_id = str(
        row[
            "player_id"
        ]
    )


    position = str(
        row[
            "position"
        ]
    ).upper()


    positions[
        player_id
    ] = position


    price = row.get(
        "current_price"
    )


    if price is None:

        payload = row.get(
            "provider_payload",
            {},
        )

        price = payload.get(
            "now_cost"
        )


    if price is None:

        raise RuntimeError(
            "missing current price for "
            f"{player_id}"
        )


    team_id = (
        row.get(
            "team_id"
        )
        or row.get(
            "provider_team_id"
        )
    )


    player_rows.append({
        "player_id":
            player_id,

        "position":
            position,

        "team_id":
            str(
                team_id
            ),

        "current_price":
            int(
                price
            ),
    })


fixture_horizon = load(
    RUN
    / "fixture_horizon.json"
)


fixture_to_gw = {
    str(
        row[
            "fixture_id"
        ]
    ):
        int(
            row[
                "target_gameweek"
            ]
        )
    for row
    in fixture_horizon
}


minutes = load(
    RUN
    / "minutes.json"
)


fixture_probabilities = {}


for row in minutes:

    fixture_id = str(
        row[
            "fixture_id"
        ]
    )


    gameweek = fixture_to_gw.get(
        fixture_id
    )


    if gameweek is None:

        continue


    key = (
        str(
            row[
                "player_id"
            ]
        ),
        gameweek,
    )


    fixture_probabilities.setdefault(
        key,
        [],
    ).append(
        float(
            row[
                "p_appearance"
            ]
        )
    )


papp = {}


for key, probabilities in (
    fixture_probabilities.items()
):

    no_appearance = 1.0


    for probability in probabilities:

        no_appearance *= (
            1.0
            - probability
        )


    papp[
        key
    ] = (
        1.0
        - no_appearance
    )


saved = (
    reference[
        "saved_wc_resolution"
    ]
)


current_ids = tuple(
    row[
        "player_id"
    ]
    for row
    in saved
)


#
# Saved final WC had £0.1 bank.
# For this structural replay use current price as
# selling price so liquidation accounting is explicit.
#
selling_prices = {
    player_id:
        int(
            next(
                row[
                    "current_price"
                ]
                for row
                in player_rows
                if row[
                    "player_id"
                ]
                == player_id
            )
        )
    for player_id
    in current_ids
}


screen = screen_chips_exact(
    player_rows=(
        player_rows
    ),

    positions=positions,

    projections_by_id=(
        projections
    ),

    p_appearance_by_gameweek=(
        papp
    ),

    current_player_ids=(
        current_ids
    ),

    selling_prices_tenths=(
        selling_prices
    ),

    bank_tenths=1,

    first_gameweek=4,

    wildcard_horizon=6,

    wildcard_weights=(
        1.00,
        0.95,
        0.90,
        0.85,
        0.80,
        0.75,
    ),
)


normal_week = (
    screen
    .normal_current_gameweek
    .gameweeks[
        0
    ]
)


expected_week = (
    reference[
        "decisions"
    ][
        "v22"
    ][
        "4"
    ]
)


gates = {
    "normal_reproduces_007a":
        abs(
            normal_week.total_ev
            - float(
                expected_week[
                    "total_ev"
                ]
            )
        )
        <= 1e-10,

    "tc_increment_positive":
        (
            screen
            .triple_captain
            .incremental_ev
            > 0.0
        ),

    "bb_increment_nonnegative":
        (
            screen
            .bench_boost
            .incremental_ev
            >= 0.0
        ),

    "fh_has_candidate_portfolio":
        (
            screen
            .free_hit
            .candidate_count
            >= 2
        ),

    "wc_has_candidate_portfolio":
        (
            screen
            .wildcard
            .candidate_count
            >= 2
        ),

    "fh_legal_15":
        (
            len(
                screen
                .free_hit
                .squad_player_ids
            )
            == 15
        ),

    "wc_legal_15":
        (
            len(
                screen
                .wildcard
                .squad_player_ids
            )
            == 15
        ),

    "captain_vice_distinct_all":
        all(
            row.captain_id
            != row.vice_id
            for row in (
                screen.triple_captain,
                screen.bench_boost,
                screen.free_hit,
                screen.wildcard,
            )
        ),
}


gate = all(
    gates.values()
)


def entry(
    row,
):

    return {
        "baseline_ev":
            row.baseline_ev,

        "chip_ev":
            row.chip_ev,

        "incremental_ev":
            row.incremental_ev,

        "candidate_count":
            row.candidate_count,

        "captain_id":
            row.captain_id,

        "vice_id":
            row.vice_id,

        "formation":
            row.formation,

        "squad_player_ids":
            sorted(
                row.squad_player_ids
            ),
    }


payload = {
    "status":
        "DECISION_007B_EXACT_CHIP_SCREEN",

    "network_refresh":
        False,

    "new_simulation":
        False,

    "realized_GW4_outcomes_used":
        False,

    "timing_thresholds_applied":
        False,

    "future_opportunity_logic_applied":
        False,

    "unlimited_squad_semantics":
        (
            "linear candidate generation "
            "+ exact nonlinear rescore"
        ),

    "normal_current_gameweek_ev":
        (
            screen
            .normal_current_gameweek
            .weighted_total_ev
        ),

    "normal_wildcard_horizon_ev":
        (
            screen
            .normal_wildcard_horizon
            .weighted_total_ev
        ),

    "chips": {
        "triple_captain":
            entry(
                screen
                .triple_captain
            ),

        "bench_boost":
            entry(
                screen
                .bench_boost
            ),

        "free_hit":
            entry(
                screen
                .free_hit
            ),

        "wildcard":
            entry(
                screen
                .wildcard
            ),
    },

    "gates": {
        **gates,
        "overall":
            gate,
    },
}


REPORT.write_text(
    json.dumps(
        payload,
        indent=2,
        sort_keys=True,
    )
    + "\n",
    encoding="utf-8",
)


print(
    "=== DECISION-007B EXACT CHIP SCREEN ==="
)

print(
    "network refresh: NO"
)

print(
    "new simulation: NO"
)

print(
    "GW4 outcomes used: NO"
)

print(
    "timing recommendation: NO"
)


print()
print(
    "NORMAL GW4:",
    f"{screen.normal_current_gameweek.weighted_total_ev:.3f}",
)


for label, row in (
    (
        "TC",
        screen.triple_captain,
    ),
    (
        "BB",
        screen.bench_boost,
    ),
    (
        "FH",
        screen.free_hit,
    ),
    (
        "WC",
        screen.wildcard,
    ),
):

    print()
    print(
        f"{label}:"
    )

    print(
        "  baseline:",
        f"{row.baseline_ev:.3f}",
    )

    print(
        "  chip EV :",
        f"{row.chip_ev:.3f}",
    )

    print(
        "  delta   :",
        f"{row.incremental_ev:+.3f}",
    )

    print(
        "  candidates:",
        row.candidate_count,
    )

    print(
        "  C / VC:",
        row.captain_id,
        "/",
        row.vice_id,
    )


print()
print(
    "=== GATES ==="
)


for name, value in payload[
    "gates"
].items():

    print(
        f"{name:<34}",
        (
            "PASS"
            if value
            else "FAIL"
        ),
    )


print()
print(
    "DECISION-007B GATE:",
    (
        "PASS"
        if gate
        else "FAIL"
    ),
)

print(
    "report:",
    REPORT.relative_to(
        ROOT
    ),
)


if not gate:

    raise RuntimeError(
        "DECISION-007B acceptance failed"
    )
