from __future__ import annotations

from pathlib import Path
import json
import math

from fpl_engine.decision.chip_screen_exact import (
    evaluate_exact_chip_squad,
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
    / "decision007a"
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


if not RUN.exists():

    raise RuntimeError(
        "validated V22 seed42 run missing"
    )


if not REFERENCE.exists():

    raise RuntimeError(
        "CAPTAIN-068G-C reference missing"
    )


reference = load(
    REFERENCE
)


if (
    reference[
        "v22_pappearance_adjustments"
    ][
        "saved_squad_rows"
    ]
    != 0
):

    raise RuntimeError(
        "Saved WC squad had a V22 "
        "pAppearance raise; raw-minutes "
        "cross-check would not be exact."
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


resolution = (
    reference[
        "saved_wc_resolution"
    ]
)


squad_ids = tuple(
    row[
        "player_id"
    ]
    for row
    in resolution
)


positions = {
    row[
        "player_id"
    ]:
        row[
            "position"
        ]
    for row
    in resolution
}


actual = evaluate_exact_chip_squad(
    squad_player_ids=squad_ids,

    positions=positions,

    projections_by_id=(
        projections
    ),

    p_appearance_by_gameweek=(
        papp
    ),

    first_gameweek=4,

    horizon=1,

    weights=(1.0,),

    chip="normal",
)


actual_week = (
    actual.gameweeks[
        0
    ]
)


expected = (
    reference[
        "decisions"
    ][
        "v22"
    ][
        "4"
    ]
)


expected_starters = {
    row[
        "player_id"
    ]
    for row
    in expected[
        "starters"
    ]
}


expected_bench = tuple(
    row[
        "player_id"
    ]
    for row
    in expected[
        "bench_outfield"
    ]
)


gates = {
    "total_ev_exact":
        math.isclose(
            actual_week.total_ev,
            float(
                expected[
                    "total_ev"
                ]
            ),
            abs_tol=1e-10,
            rel_tol=0.0,
        ),

    "xi_exact":
        set(
            actual_week.starter_ids
        )
        == expected_starters,

    "bench_gk_exact":
        actual_week.bench_gk_id
        == expected[
            "bench_gk"
        ][
            "player_id"
        ],

    "bench_order_exact":
        actual_week.bench_outfield_ids
        == expected_bench,

    "captain_exact":
        actual_week.captain_id
        == expected[
            "captain"
        ][
            "player_id"
        ],

    "vice_exact":
        actual_week.vice_id
        == expected[
            "vice"
        ][
            "player_id"
        ],
}


gate = all(
    gates.values()
)


payload = {
    "status":
        "DECISION_007A_EXACT_CHIP_SCORER",

    "source":
        str(
            RUN.relative_to(
                ROOT
            )
        ),

    "network_refresh":
        False,

    "new_simulation":
        False,

    "realized_GW4_outcomes_used":
        False,

    "reference":
        (
            "CAPTAIN-068H preserved "
            "decision_42.json"
        ),

    "actual": {
        "total_ev":
            actual_week.total_ev,

        "formation":
            actual_week.formation,

        "starter_ids":
            list(
                actual_week.starter_ids
            ),

        "bench_gk_id":
            actual_week.bench_gk_id,

        "bench_outfield_ids":
            list(
                actual_week
                .bench_outfield_ids
            ),

        "captain_id":
            actual_week.captain_id,

        "vice_id":
            actual_week.vice_id,
    },

    "expected": {
        "total_ev":
            expected[
                "total_ev"
            ],

        "captain":
            expected[
                "captain"
            ][
                "name"
            ],

        "vice":
            expected[
                "vice"
            ][
                "name"
            ],
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
    "=== DECISION-007A ACCEPTANCE ==="
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


print()
print(
    "actual total EV :",
    f"{actual_week.total_ev:.12f}",
)

print(
    "expected total EV:",
    f"{float(expected['total_ev']):.12f}",
)

print(
    "formation:",
    actual_week.formation,
)

print(
    "captain / vice:",
    expected[
        "captain"
    ][
        "name"
    ],
    "/",
    expected[
        "vice"
    ][
        "name"
    ],
)


print()
print(
    "=== GATES ==="
)


for name, value in payload[
    "gates"
].items():

    print(
        f"{name:<24}",
        (
            "PASS"
            if value
            else "FAIL"
        ),
    )


print()
print(
    "DECISION-007A GATE:",
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
        "DECISION-007A acceptance failed"
    )
