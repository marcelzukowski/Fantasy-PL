from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, pstdev
import json
import unicodedata


ROOT = Path(".").resolve()

OUT = (
    ROOT
    / "scratch"
    / "decision"
    / "captain068h"
)

RUNS = {
    42:
        ROOT
        / "scratch"
        / "decision"
        / "captain068g"
        / "integrated_replay"
        / "v22_real",

    202627:
        OUT
        / "seed_202627",

    606:
        OUT
        / "seed_606",

    91991:
        OUT
        / "seed_91991",
}

V1 = (
    ROOT
    / "scratch"
    / "decision"
    / "captain068g"
    / "integrated_replay"
    / "v1"
)

FINAL = (
    OUT
    / "multiseed_summary.json"
)


UPSTREAM = (
    "current_players.json",
    "fixture_horizon.json",
    "team_strength.json",
    "minutes.json",
    "tactical_context.json",
    "player_talent.json",
    "candidate_pool.json",
    "event_projections.json",
    "goal_allocation_proxy.json",
)


def load(
    path,
):

    return json.loads(
        Path(path).read_text(
            encoding="utf-8"
        )
    )


def recursive_values(
    value,
    key,
):

    found = []

    if isinstance(
        value,
        dict,
    ):

        for current_key, item in (
            value.items()
        ):

            if current_key == key:

                found.append(
                    item
                )


            found.extend(
                recursive_values(
                    item,
                    key,
                )
            )


    elif isinstance(
        value,
        list,
    ):

        for item in value:

            found.extend(
                recursive_values(
                    item,
                    key,
                )
            )


    return found


def projections(
    path,
):

    payload = load(
        path
        / "player_projections.json"
    )

    output = {}


    def visit(
        value,
    ):

        if isinstance(
            value,
            dict,
        ):

            if all(
                key in value
                for key in (
                    "player_id",
                    "target_gameweek",
                    "expected_points",
                    "expected_minutes",
                )
            ):

                output[
                    (
                        str(
                            value[
                                "player_id"
                            ]
                        ),
                        int(
                            value[
                                "target_gameweek"
                            ]
                        ),
                    )
                ] = {
                    "points":
                        float(
                            value[
                                "expected_points"
                            ]
                        ),

                    "minutes":
                        float(
                            value[
                                "expected_minutes"
                            ]
                        ),
                }


            for item in value.values():

                visit(
                    item
                )


        elif isinstance(
            value,
            list,
        ):

            for item in value:

                visit(
                    item
                )


    visit(
        payload
    )

    return output


# ------------------------------------------------------------
# Upstream exact across seeds.
# ------------------------------------------------------------

reference = RUNS[
    42
]


upstream_by_seed = {}


for seed, run in RUNS.items():

    statuses = {}


    for filename in UPSTREAM:

        left = (
            reference
            / filename
        )

        right = (
            run
            / filename
        )


        if (
            not left.exists()
            and not right.exists()
        ):

            statuses[
                filename
            ] = "ABSENT_BOTH"

        elif (
            not left.exists()
            or not right.exists()
        ):

            statuses[
                filename
            ] = "FAIL"

        else:

            statuses[
                filename
            ] = (
                "PASS"
                if load(
                    left
                )
                == load(
                    right
                )
                else "FAIL"
            )


    upstream_by_seed[
        seed
    ] = statuses


upstream_gate = all(
    status
    in {
        "PASS",
        "ABSENT_BOTH",
    }
    for statuses
    in upstream_by_seed.values()
    for status
    in statuses.values()
)


# ------------------------------------------------------------
# Simulator identities.
# ------------------------------------------------------------

simulator_versions = {}


for seed, run in RUNS.items():

    manifest = load(
        run
        / "run_manifest.json"
    )

    simulator_versions[
        seed
    ] = sorted({
        str(
            value
        )
        for value
        in recursive_values(
            manifest,
            "simulator_version",
        )
    })


simulator_gate = all(
    any(
        "fixture_simulator_v22"
        in value
        for value
        in versions
    )
    for versions
    in simulator_versions.values()
)


# ------------------------------------------------------------
# Authoritative model minutes.
# ------------------------------------------------------------

horizon = load(
    reference
    / "fixture_horizon.json"
)

minutes = load(
    reference
    / "minutes.json"
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
    for row in horizon
}


grouped = defaultdict(
    list
)


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


    grouped[
        (
            str(
                row[
                    "player_id"
                ]
            ),
            gameweek,
        )
    ].append(
        row
    )


model = {
    key:
        rows[
            0
        ]
    for key, rows
    in grouped.items()
    if len(
        rows
    )
    == 1
}


# ------------------------------------------------------------
# Player names + Haaland.
# ------------------------------------------------------------

players = load(
    reference
    / "current_players.json"
)


def name_of(
    row,
):

    for key in (
        "display_name",
        "web_name",
        "name",
        "player_name",
    ):

        value = row.get(
            key
        )

        if value:
            return str(
                value
            )


    payload = row.get(
        "provider_payload"
    )


    if isinstance(
        payload,
        dict,
    ):

        value = payload.get(
            "web_name"
        )

        if value:
            return str(
                value
            )


    return str(
        row[
            "player_id"
        ]
    )


names = {
    str(
        row[
            "player_id"
        ]
    ):
    name_of(
        row
    )
    for row in players
}


def normalized(
    value,
):

    value = unicodedata.normalize(
        "NFKD",
        str(
            value
        ),
    )

    return "".join(
        char
        for char in value
        if not unicodedata.combining(
            char
        )
    ).casefold()


haaland_matches = [
    player_id
    for player_id, name
    in names.items()
    if "haaland"
    in normalized(
        name
    )
]


if len(
    haaland_matches
) != 1:

    raise RuntimeError(
        "Could not uniquely resolve Haaland."
    )


haaland_id = haaland_matches[
    0
]


# ------------------------------------------------------------
# Minute alignment: V1 baseline and each V22 seed.
# ------------------------------------------------------------

projection_v1 = projections(
    V1
)


def alignment(
    projection,
):

    keys = (
        set(
            projection
        )
        & set(
            model
        )
    )


    all_errors = []

    high_errors = []

    haaland_errors = []


    for key in keys:

        error = abs(
            projection[
                key
            ][
                "minutes"
            ]
            - float(
                model[
                    key
                ][
                    "expected_minutes"
                ]
            )
        )


        all_errors.append(
            error
        )


        if float(
            model[
                key
            ][
                "p_start"
            ]
        ) >= 0.75:

            high_errors.append(
                error
            )


        if key[
            0
        ] == haaland_id:

            haaland_errors.append(
                error
            )


    return {
        "rows":
            len(
                all_errors
            ),

        "mae":
            mean(
                all_errors
            ),

        "high_rows":
            len(
                high_errors
            ),

        "high_pstart_mae":
            mean(
                high_errors
            ),

        "haaland_mae":
            mean(
                haaland_errors
            ),
    }


v1_alignment = alignment(
    projection_v1
)


v22_alignment = {
    seed:
        alignment(
            projections(
                run
            )
        )
    for seed, run
    in RUNS.items()
}


minute_gate = all(
    row[
        "mae"
    ]
    < v1_alignment[
        "mae"
    ]
    for row
    in v22_alignment.values()
)


high_gate = all(
    row[
        "high_pstart_mae"
    ]
    < v1_alignment[
        "high_pstart_mae"
    ]
    for row
    in v22_alignment.values()
)


haaland_gate = all(
    row[
        "haaland_mae"
    ]
    < v1_alignment[
        "haaland_mae"
    ]
    for row
    in v22_alignment.values()
)


# ------------------------------------------------------------
# Decision stability.
# ------------------------------------------------------------

decision_reports = {
    str(seed):
        load(
            OUT
            / f"decision_{seed}.json"
        )
    for seed
    in RUNS
}


ensemble_report = load(
    OUT
    / "decision_ensemble.json"
)


decision_gate = all(
    report[
        "gates"
    ][
        "overall"
    ]
    for report
    in decision_reports.values()
) and ensemble_report[
    "gates"
][
    "overall"
]


decision_stability = {}


for gameweek in range(
    4,
    10,
):

    rows = []


    for seed in RUNS:

        decision = (
            decision_reports[
                str(
                    seed
                )
            ][
                "decisions"
            ][
                "v22"
            ][
                str(
                    gameweek
                )
            ]
        )


        xi = tuple(
            sorted(
                player[
                    "name"
                ]
                for player
                in decision[
                    "starters"
                ]
            )
        )


        bench = (
            decision[
                "bench_gk"
            ][
                "name"
            ],
            *tuple(
                player[
                    "name"
                ]
                for player
                in decision[
                    "bench_outfield"
                ]
            ),
        )


        captain = (
            decision[
                "captain"
            ][
                "name"
            ]
        )

        vice = (
            decision[
                "vice"
            ][
                "name"
            ]
        )


        rows.append({
            "seed":
                seed,

            "xi":
                xi,

            "bench":
                bench,

            "captain":
                captain,

            "vice":
                vice,

            "total_ev":
                float(
                    decision[
                        "total_ev"
                    ]
                ),
        })


    xi_counter = Counter(
        row[
            "xi"
        ]
        for row in rows
    )

    c_counter = Counter(
        row[
            "captain"
        ]
        for row in rows
    )

    vc_counter = Counter(
        row[
            "vice"
        ]
        for row in rows
    )


    ensemble_decision = (
        ensemble_report[
            "decisions"
        ][
            "v22"
        ][
            str(
                gameweek
            )
        ]
    )


    decision_stability[
        gameweek
    ] = {
        "worlds":
            rows,

        "unique_xi":
            len(
                xi_counter
            ),

        "xi_consensus":
            xi_counter
            .most_common(
                1
            )[
                0
            ][
                1
            ],

        "captain_consensus":
            c_counter
            .most_common(
                1
            )[
                0
            ],

        "vice_consensus":
            vc_counter
            .most_common(
                1
            )[
                0
            ],

        "ev_mean":
            mean(
                row[
                    "total_ev"
                ]
                for row
                in rows
            ),

        "ev_sd":
            pstdev(
                row[
                    "total_ev"
                ]
                for row
                in rows
            ),

        "ensemble": {
            "formation":
                ensemble_decision[
                    "formation"
                ],

            "xi":
                [
                    player[
                        "name"
                    ]
                    for player
                    in ensemble_decision[
                        "starters"
                    ]
                ],

            "bench_gk":
                ensemble_decision[
                    "bench_gk"
                ][
                    "name"
                ],

            "bench":
                [
                    player[
                        "name"
                    ]
                    for player
                    in ensemble_decision[
                        "bench_outfield"
                    ]
                ],

            "captain":
                ensemble_decision[
                    "captain"
                ][
                    "name"
                ],

            "vice":
                ensemble_decision[
                    "vice"
                ][
                    "name"
                ],

            "total_ev":
                ensemble_decision[
                    "total_ev"
                ],
        },
    }


overall_gate = all((
    simulator_gate,
    upstream_gate,
    minute_gate,
    high_gate,
    haaland_gate,
    decision_gate,
))


report = {
    "status":
        "CAPTAIN_068H_MULTISEED",

    "network_refresh":
        False,

    "2026_27_outcomes_used":
        False,

    "production_default_changed":
        False,

    "seeds":
        list(
            RUNS
        ),

    "simulator_versions":
        simulator_versions,

    "upstream_exact":
        upstream_by_seed,

    "v1_alignment":
        v1_alignment,

    "v22_alignment":
        v22_alignment,

    "decision_stability":
        decision_stability,

    "gates": {
        "v22_identity":
            simulator_gate,

        "upstream_exact":
            upstream_gate,

        "minute_mae_improved_every_seed":
            minute_gate,

        "high_pstart_improved_every_seed":
            high_gate,

        "haaland_improved_every_seed":
            haaland_gate,

        "decision_structural":
            decision_gate,

        "overall":
            overall_gate,
    },
}


FINAL.write_text(
    json.dumps(
        report,
        indent=2,
        sort_keys=True,
        ensure_ascii=False,
    )
    + "\n",
    encoding="utf-8",
)


print(
    "=== CAPTAIN-068H MULTISEED ==="
)

print(
    "network refresh:",
    "NO",
)

print(
    "2026/27 outcomes used:",
    "NO",
)

print(
    "production default changed:",
    "NO",
)


print()
print(
    "=== MINUTE ALIGNMENT ==="
)

print(
    "V1 baseline:"
)

print(
    "  MAE             ",
    f"{v1_alignment['mae']:.3f}",
)

print(
    "  high-pStart MAE ",
    f"{v1_alignment['high_pstart_mae']:.3f}",
)

print(
    "  Haaland MAE     ",
    f"{v1_alignment['haaland_mae']:.3f}",
)


for seed in RUNS:

    row = v22_alignment[
        seed
    ]

    print()
    print(
        f"V22 seed {seed}:"
    )

    print(
        "  MAE             ",
        f"{row['mae']:.3f}",
    )

    print(
        "  high-pStart MAE ",
        f"{row['high_pstart_mae']:.3f}",
    )

    print(
        "  Haaland MAE     ",
        f"{row['haaland_mae']:.3f}",
    )


print()
print(
    "=== DECISION STABILITY ==="
)


for gameweek in range(
    4,
    10,
):

    row = decision_stability[
        gameweek
    ]


    print()
    print(
        f"GW{gameweek}"
    )

    print(
        "  unique XI:",
        row[
            "unique_xi"
        ],
        "| consensus:",
        f"{row['xi_consensus']}/4",
    )

    print(
        "  captain consensus:",
        row[
            "captain_consensus"
        ][
            0
        ],
        f"{row['captain_consensus'][1]}/4",
    )

    print(
        "  vice consensus:",
        row[
            "vice_consensus"
        ][
            0
        ],
        f"{row['vice_consensus'][1]}/4",
    )

    print(
        "  decision EV:",
        f"{row['ev_mean']:.3f}",
        "+/-",
        f"{row['ev_sd']:.3f}",
    )

    print(
        "  ENSEMBLE:",
        row[
            "ensemble"
        ][
            "formation"
        ],
        "| C",
        row[
            "ensemble"
        ][
            "captain"
        ],
        "| VC",
        row[
            "ensemble"
        ][
            "vice"
        ],
    )

    print(
        "  XI:",
        ", ".join(
            row[
                "ensemble"
            ][
                "xi"
            ]
        ),
    )

    print(
        "  BENCH:",
        row[
            "ensemble"
        ][
            "bench_gk"
        ],
        "|",
        " | ".join(
            row[
                "ensemble"
            ][
                "bench"
            ]
        ),
    )


print()
print(
    "=== GATES ==="
)

for name, value in report[
    "gates"
].items():

    print(
        f"{name:<36}",
        (
            "PASS"
            if value
            else "FAIL"
        ),
    )


print()
print(
    "MULTISEED GATE:",
    (
        "PASS"
        if overall_gate
        else "FAIL"
    ),
)

print(
    "report:",
    FINAL.relative_to(
        ROOT
    ),
)


if not overall_gate:

    raise RuntimeError(
        "CAPTAIN-068H multiseed "
        "gate failed."
    )
