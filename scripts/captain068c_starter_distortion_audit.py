from __future__ import annotations

from pathlib import Path
from statistics import mean, median
import json
import math

import numpy as np


ROOT = Path(".").resolve()

ACCEPTANCE = (
    ROOT
    / "scratch"
    / "decision"
    / "captain067c"
    / "default_runtime_acceptance.json"
)

OUT_DIR = (
    ROOT
    / "scratch"
    / "decision"
    / "captain068"
)

REPORT = (
    OUT_DIR
    / "starter_distortion.json"
)


def load(path):
    return json.loads(
        Path(path).read_text(
            encoding="utf-8"
        )
    )


acceptance = load(
    ACCEPTANCE
)

RUN = (
    ROOT
    / acceptance[
        "default_run"
    ]
)

players = load(
    RUN
    / "current_players.json"
)

minutes = load(
    RUN
    / "minutes.json"
)

events = load(
    RUN
    / "event_projections.json"
)

projections = load(
    RUN
    / "player_projections.json"
)


def player_name(row):

    for key in (
        "display_name",
        "web_name",
        "name",
        "player_name",
    ):

        if row.get(key):
            return str(
                row[key]
            )

    return str(
        row["player_id"]
    )


names = {
    str(row["player_id"]):
        player_name(row)
    for row in players
}


haaland_ids = [
    player_id
    for player_id, name
    in names.items()
    if "haaland"
    in name.lower()
]


if len(haaland_ids) != 1:
    raise RuntimeError(
        "Expected exactly one Haaland."
    )


HAALAND = haaland_ids[0]


# ============================================================
# Authoritative Minutes V2.1 artifact
# ============================================================

minute_map = {
    (
        str(row["player_id"]),
        str(row["fixture_id"]),
    ):
    row
    for row in minutes
}


#
# Correct semantic checks for the CALIBRATED marginal.
#
# We do NOT require starter/bench conditional shapes to
# reconstruct the calibrated marginal here.
#
pmf_failures = []
conditional_mixture_gaps = []


def dist_mean(dist):

    return sum(
        minute * float(probability)
        for minute, probability
        in enumerate(dist)
    )


for key, row in minute_map.items():

    full = [
        float(x)
        for x in row[
            "minute_distribution"
        ]
    ]

    starter = [
        float(x)
        for x in row[
            "starter_minutes_distribution"
        ]
    ]

    bench = [
        float(x)
        for x in row[
            "bench_minutes_distribution"
        ]
    ]

    expected = float(
        row[
            "expected_minutes"
        ]
    )

    p_app = float(
        row[
            "p_appearance"
        ]
    )

    p_start = float(
        row[
            "p_start"
        ]
    )

    p_bench = max(
        0.0,
        p_app - p_start,
    )

    full_expected = (
        dist_mean(full)
    )

    p_app_from_full = (
        1.0 - full[0]
    )


    if not (
        math.isclose(
            expected,
            full_expected,
            abs_tol=1e-9,
            rel_tol=0.0,
        )
        and math.isclose(
            p_app,
            p_app_from_full,
            abs_tol=1e-9,
            rel_tol=0.0,
        )
    ):

        pmf_failures.append({
            "player_id": key[0],
            "fixture_id": key[1],
            "expected": expected,
            "pmf_expected": (
                full_expected
            ),
            "p_app": p_app,
            "pmf_p_app": (
                p_app_from_full
            ),
        })


    mixture = (
        p_start
        * dist_mean(starter)
        + p_bench
        * dist_mean(bench)
    )


    conditional_mixture_gaps.append(
        abs(
            mixture
            - expected
        )
    )


pmf_contract_pass = (
    len(pmf_failures) == 0
)


# ============================================================
# Projection result map
# ============================================================

projection_minutes = {}


for player in projections:

    player_id = str(
        player[
            "player_id"
        ]
    )

    for gw in player.get(
        "gameweeks",
        [],
    ):

        fixture_ids = (
            gw.get(
                "fixture_ids",
                [],
            )
        )


        if (
            int(
                gw.get(
                    "fixture_count",
                    0,
                )
            ) == 1
            and len(
                fixture_ids
            ) == 1
        ):

            projection_minutes[
                (
                    player_id,
                    str(
                        fixture_ids[0]
                    ),
                )
            ] = float(
                gw[
                    "expected_minutes"
                ]
            )


# ============================================================
# Exact reproduction of current V1 starter-selection algorithm
#
# We reproduce ONLY:
#   appearance
#   GK selection
#   weighted top-k starter selection
#
# We don't simulate goals / points.
# ============================================================

RNG = np.random.default_rng(
    6803
)

DRAWS = 5000

rows = []


for fixture in events:

    fixture_id = str(
        fixture[
            "fixture_id"
        ]
    )


    for side_name in (
        "home",
        "away",
    ):

        team = fixture[
            side_name
        ]

        team_players = (
            team[
                "players"
            ]
        )


        rates = [
            player[
                "rates"
            ]
            for player
            in team_players
        ]


        counts_app = {
            str(row["player_id"]): 0
            for row in rates
        }

        counts_start = {
            str(row["player_id"]): 0
            for row in rates
        }


        for _ in range(
            DRAWS
        ):

            appearing = [
                row
                for row in rates
                if (
                    RNG.random()
                    < float(
                        row[
                            "p_appearance"
                        ]
                    )
                )
            ]


            appearing_ids = {
                str(
                    row[
                        "player_id"
                    ]
                )
                for row
                in appearing
            }


            for player_id in (
                appearing_ids
            ):

                counts_app[
                    player_id
                ] += 1


            target_starters = min(
                11,
                len(
                    appearing
                ),
            )

            starters = set()


            goalkeepers = [
                row
                for row in appearing
                if str(
                    row[
                        "position"
                    ]
                ).upper()
                == "GK"
            ]


            if (
                goalkeepers
                and target_starters
            ):

                weights = np.asarray(
                    [
                        max(
                            float(
                                row[
                                    "p_start"
                                ]
                            ),
                            1e-9,
                        )
                        for row
                        in goalkeepers
                    ],
                    dtype=float,
                )


                chosen = goalkeepers[
                    int(
                        RNG.choice(
                            len(
                                goalkeepers
                            ),
                            p=(
                                weights
                                / weights.sum()
                            ),
                        )
                    )
                ]


                starters.add(
                    str(
                        chosen[
                            "player_id"
                        ]
                    )
                )


            candidates = [
                row
                for row in appearing
                if str(
                    row[
                        "player_id"
                    ]
                )
                not in starters
            ]


            remaining = (
                target_starters
                - len(
                    starters
                )
            )


            if remaining:

                keys = [
                    (
                        RNG.random()
                        ** (
                            1.0
                            / max(
                                float(
                                    row[
                                        "p_start"
                                    ]
                                ),
                                1e-9,
                            )
                        ),
                        str(
                            row[
                                "player_id"
                            ]
                        ),
                    )
                    for row
                    in candidates
                ]


                starters.update(
                    player_id
                    for _, player_id
                    in sorted(
                        keys,
                        reverse=True,
                    )[
                        :remaining
                    ]
                )


            for player_id in (
                starters
            ):

                counts_start[
                    player_id
                ] += 1


        for rate in rates:

            player_id = str(
                rate[
                    "player_id"
                ]
            )

            key = (
                player_id,
                fixture_id,
            )

            minute_row = (
                minute_map[
                    key
                ]
            )

            model_p_app = float(
                minute_row[
                    "p_appearance"
                ]
            )

            model_p_start = float(
                minute_row[
                    "p_start"
                ]
            )

            empirical_p_app = (
                counts_app[
                    player_id
                ]
                / DRAWS
            )

            empirical_p_start = (
                counts_start[
                    player_id
                ]
                / DRAWS
            )


            rows.append({
                "player_id": (
                    player_id
                ),
                "name": names.get(
                    player_id,
                    player_id,
                ),
                "fixture_id": (
                    fixture_id
                ),
                "side": (
                    side_name
                ),
                "model_p_appearance": (
                    model_p_app
                ),
                "empirical_p_appearance": (
                    empirical_p_app
                ),
                "appearance_delta": (
                    empirical_p_app
                    - model_p_app
                ),
                "model_p_start": (
                    model_p_start
                ),
                "empirical_p_start": (
                    empirical_p_start
                ),
                "start_delta": (
                    empirical_p_start
                    - model_p_start
                ),
                "model_expected_minutes": float(
                    minute_row[
                        "expected_minutes"
                    ]
                ),
                "projection_expected_minutes": (
                    projection_minutes.get(
                        key
                    )
                ),
            })


# ============================================================
# Summary
# ============================================================

meaningful = [
    row
    for row in rows
    if row[
        "model_p_appearance"
    ] >= 0.20
]


start_abs = [
    abs(
        row[
            "start_delta"
        ]
    )
    for row
    in meaningful
]


appearance_abs = [
    abs(
        row[
            "appearance_delta"
        ]
    )
    for row
    in meaningful
]


mean_start_abs = mean(
    start_abs
)

median_start_abs = median(
    start_abs
)

mean_app_abs = mean(
    appearance_abs
)


large_start = [
    row
    for row in meaningful
    if abs(
        row[
            "start_delta"
        ]
    ) >= 0.10
]


top_start = sorted(
    meaningful,
    key=lambda row:
        abs(
            row[
                "start_delta"
            ]
        ),
    reverse=True,
)[:20]


haaland = sorted(
    (
        row
        for row in rows
        if row[
            "player_id"
        ]
        == HAALAND
    ),
    key=lambda row:
        row[
            "fixture_id"
        ],
)


#
# The appearance hurdle should be reproduced almost exactly
# by this V1 algorithm. Starter marginals need not be.
#
appearance_gate = (
    mean_app_abs
    < 0.01
)


starter_distortion_found = (
    mean_start_abs
    > 0.02
    or len(
        large_start
    )
    > 0
)


report = {
    "draws_per_team_fixture": (
        DRAWS
    ),
    "minute_pmf_contract_pass": (
        pmf_contract_pass
    ),
    "minute_pmf_failure_count": (
        len(
            pmf_failures
        )
    ),
    "conditional_mixture_gap": {
        "mean_abs_minutes": (
            mean(
                conditional_mixture_gaps
            )
        ),
        "median_abs_minutes": (
            median(
                conditional_mixture_gaps
            )
        ),
        "max_abs_minutes": (
            max(
                conditional_mixture_gaps
            )
        ),
    },
    "appearance_mean_abs_error": (
        mean_app_abs
    ),
    "start_mean_abs_error": (
        mean_start_abs
    ),
    "start_median_abs_error": (
        median_start_abs
    ),
    "start_distortion_10pp_count": (
        len(
            large_start
        )
    ),
    "appearance_gate": (
        appearance_gate
    ),
    "starter_distortion_found": (
        starter_distortion_found
    ),
    "haaland": (
        haaland
    ),
    "top_start_distortions": (
        top_start
    ),
}


REPORT.write_text(
    json.dumps(
        report,
        indent=2,
        sort_keys=True,
    )
    + "\n",
    encoding="utf-8",
)


print(
    "=== CAPTAIN-068C "
    "STARTER DISTORTION AUDIT ==="
)

print(
    "calibrated minute PMF:",
    (
        "PASS"
        if pmf_contract_pass
        else "FAIL"
    ),
)

print(
    "conditional mixture mean gap:",
    f"{mean(conditional_mixture_gaps):.3f}",
    "min",
)

print(
    "conditional mixture max gap:",
    f"{max(conditional_mixture_gaps):.3f}",
    "min",
)

print()

print(
    "appearance MAE:",
    f"{mean_app_abs:.4f}",
)

print(
    "starter MAE:",
    f"{mean_start_abs:.4f}",
)

print(
    "starter median AE:",
    f"{median_start_abs:.4f}",
)

print(
    "starter distortions >=10pp:",
    len(
        large_start
    ),
)

print(
    "appearance hurdle:",
    (
        "PASS"
        if appearance_gate
        else "FAIL"
    ),
)

print(
    "starter distortion:",
    (
        "CONFIRMED"
        if starter_distortion_found
        else "NOT CONFIRMED"
    ),
)


print()
print(
    "=== HAALAND ==="
)


for row in haaland:

    projection = (
        row[
            "projection_expected_minutes"
        ]
    )


    print(
        f"{row['fixture_id'][-8:]} "
        f"pApp "
        f"{row['model_p_appearance']:.3f}"
        f" -> "
        f"{row['empirical_p_appearance']:.3f} | "
        f"pStart "
        f"{row['model_p_start']:.3f}"
        f" -> "
        f"{row['empirical_p_start']:.3f} | "
        f"minutes "
        f"{row['model_expected_minutes']:.2f}"
        f" -> "
        f"{projection:.2f}"
    )


print()
print(
    "=== TOP 15 START DISTORTIONS ==="
)


for row in top_start[
    :15
]:

    print(
        f"{row['name'][:22]:<22} "
        f"pStart "
        f"{row['model_p_start']:.3f}"
        f" -> "
        f"{row['empirical_p_start']:.3f} "
        f"delta="
        f"{row['start_delta']:+.3f} "
        f"minutes="
        f"{row['model_expected_minutes']:.1f}"
        f" -> "
        f"{row['projection_expected_minutes']:.1f}"
    )


print()
print(
    "report:",
    REPORT.relative_to(
        ROOT
    ),
)
