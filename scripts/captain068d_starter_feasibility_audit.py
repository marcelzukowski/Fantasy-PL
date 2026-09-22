from __future__ import annotations

from pathlib import Path
from statistics import mean, median
import json
import math


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
    / "starter_feasibility.json"
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

events = load(
    RUN
    / "event_projections.json"
)

fixtures = load(
    RUN
    / "fixture_horizon.json"
)

players = load(
    RUN
    / "current_players.json"
)


# ============================================================
# Names
# ============================================================

def display_name(row):

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

    return str(
        row.get(
            "player_id",
            "",
        )
    )


names = {
    str(
        row[
            "player_id"
        ]
    ):
    display_name(
        row
    )
    for row in players
}


haaland_ids = [
    player_id
    for player_id, name
    in names.items()
    if "haaland"
    in name.lower()
]


if len(
    haaland_ids
) != 1:

    raise RuntimeError(
        "Expected exactly one Haaland."
    )


HAALAND = (
    haaland_ids[
        0
    ]
)


fixture_info = {
    str(
        row[
            "fixture_id"
        ]
    ):
    row
    for row in fixtures
}


# ============================================================
# Exact Poisson-binomial distribution for independent
# appearances used by FixtureSimulator V1.
# ============================================================

def poisson_binomial(
    probabilities,
):

    dist = [
        1.0
    ]


    for probability in (
        probabilities
    ):

        p = float(
            probability
        )

        updated = [
            0.0
        ] * (
            len(
                dist
            )
            + 1
        )


        for count, mass in (
            enumerate(
                dist
            )
        ):

            updated[
                count
            ] += (
                mass
                * (
                    1.0
                    - p
                )
            )

            updated[
                count
                + 1
            ] += (
                mass
                * p
            )


        dist = updated


    return dist


# ============================================================
# Team-fixture audit
# ============================================================

rows = []


for fixture in events:

    fixture_id = str(
        fixture[
            "fixture_id"
        ]
    )

    info = fixture_info.get(
        fixture_id,
        {},
    )

    gameweek = info.get(
        "target_gameweek"
    )


    for side in (
        "home",
        "away",
    ):

        team = fixture[
            side
        ]

        rates = [
            player[
                "rates"
            ]
            for player
            in team[
                "players"
            ]
        ]


        if not rates:

            continue


        team_id = str(
            team.get(
                "team_id",
                rates[
                    0
                ].get(
                    "team_id"
                ),
            )
        )


        p_apps = [
            float(
                rate[
                    "p_appearance"
                ]
            )
            for rate in rates
        ]

        p_starts = [
            float(
                rate[
                    "p_start"
                ]
            )
            for rate in rates
        ]


        target_start_sum = sum(
            p_starts
        )

        target_app_sum = sum(
            p_apps
        )


        app_dist = (
            poisson_binomial(
                p_apps
            )
        )


        probability_lt_11 = sum(
            app_dist[
                :11
            ]
        )


        expected_current_starters = sum(
            min(
                count,
                11,
            )
            * mass
            for count, mass
            in enumerate(
                app_dist
            )
        )


        count_pressure = (
            expected_current_starters
            - target_start_sum
        )


        gks = [
            rate
            for rate in rates
            if str(
                rate.get(
                    "position",
                    "",
                )
            ).upper()
            == "GK"
        ]


        target_gk_start_sum = sum(
            float(
                rate[
                    "p_start"
                ]
            )
            for rate in gks
        )


        probability_any_gk_appears = (
            1.0
            - math.prod(
                (
                    1.0
                    - float(
                        rate[
                            "p_appearance"
                        ]
                    )
                )
                for rate in gks
            )
            if gks
            else 0.0
        )


        target_outfield_start_sum = (
            target_start_sum
            - target_gk_start_sum
        )


        contains_haaland = any(
            str(
                rate[
                    "player_id"
                ]
            )
            == HAALAND
            for rate in rates
        )


        rows.append({
            "fixture_id": (
                fixture_id
            ),
            "gameweek": (
                gameweek
            ),
            "side": (
                side
            ),
            "team_id": (
                team_id
            ),
            "player_count": len(
                rates
            ),
            "target_start_sum": (
                target_start_sum
            ),
            "target_appearance_sum": (
                target_app_sum
            ),
            "target_gk_start_sum": (
                target_gk_start_sum
            ),
            "target_outfield_start_sum": (
                target_outfield_start_sum
            ),
            "probability_any_gk_appears": (
                probability_any_gk_appears
            ),
            "probability_fewer_than_11_appear": (
                probability_lt_11
            ),
            "expected_current_simulator_starters": (
                expected_current_starters
            ),
            "current_count_pressure": (
                count_pressure
            ),
            "gap_to_exact_11": (
                11.0
                - target_start_sum
            ),
            "contains_haaland": (
                contains_haaland
            ),
        })


if len(
    rows
) != 120:

    raise RuntimeError(
        "Expected 120 team-fixture rows, "
        f"found {len(rows)}."
    )


# ============================================================
# Summary
# ============================================================

start_sums = [
    row[
        "target_start_sum"
    ]
    for row in rows
]

gaps_to_11 = [
    row[
        "gap_to_exact_11"
    ]
    for row in rows
]

pressures = [
    row[
        "current_count_pressure"
    ]
    for row in rows
]

prob_lt_11 = [
    row[
        "probability_fewer_than_11_appear"
    ]
    for row in rows
]

gk_sums = [
    row[
        "target_gk_start_sum"
    ]
    for row in rows
]

gk_current = [
    row[
        "probability_any_gk_appears"
    ]
    for row in rows
]


large_pressure = [
    row
    for row in rows
    if abs(
        row[
            "current_count_pressure"
        ]
    )
    >= 0.50
]


large_gap_11 = [
    row
    for row in rows
    if abs(
        row[
            "gap_to_exact_11"
        ]
    )
    >= 0.50
]


top_pressure = sorted(
    rows,
    key=lambda row:
        abs(
            row[
                "current_count_pressure"
            ]
        ),
    reverse=True,
)


top_11_gap = sorted(
    rows,
    key=lambda row:
        abs(
            row[
                "gap_to_exact_11"
            ]
        ),
    reverse=True,
)


haaland_rows = sorted(
    (
        row
        for row in rows
        if row[
            "contains_haaland"
        ]
    ),
    key=lambda row:
        (
            row[
                "gameweek"
            ]
            if row[
                "gameweek"
            ]
            is not None
            else 999
        ),
)


# ============================================================
# Interpretation flags
#
# These are descriptive, NOT promotion thresholds.
# ============================================================

exact_11_compatible = all(
    math.isclose(
        row[
            "target_start_sum"
        ],
        11.0,
        abs_tol=1e-6,
        rel_tol=0.0,
    )
    for row in rows
)


current_count_compatible = all(
    math.isclose(
        row[
            "target_start_sum"
        ],
        row[
            "expected_current_simulator_starters"
        ],
        abs_tol=1e-6,
        rel_tol=0.0,
    )
    for row in rows
)


report = {
    "team_fixture_rows": len(
        rows
    ),
    "target_start_sum": {
        "mean": mean(
            start_sums
        ),
        "median": median(
            start_sums
        ),
        "min": min(
            start_sums
        ),
        "max": max(
            start_sums
        ),
    },
    "gap_to_exact_11": {
        "mean": mean(
            gaps_to_11
        ),
        "median": median(
            gaps_to_11
        ),
        "mean_abs": mean(
            abs(value)
            for value in gaps_to_11
        ),
        "max_abs": max(
            abs(value)
            for value in gaps_to_11
        ),
        "count_abs_ge_0_5": len(
            large_gap_11
        ),
    },
    "current_simulator_count_pressure": {
        "mean": mean(
            pressures
        ),
        "median": median(
            pressures
        ),
        "mean_abs": mean(
            abs(value)
            for value in pressures
        ),
        "max_abs": max(
            abs(value)
            for value in pressures
        ),
        "count_abs_ge_0_5": len(
            large_pressure
        ),
    },
    "probability_fewer_than_11_appear": {
        "mean": mean(
            prob_lt_11
        ),
        "median": median(
            prob_lt_11
        ),
        "max": max(
            prob_lt_11
        ),
    },
    "goalkeeper_start_sum": {
        "mean_target": mean(
            gk_sums
        ),
        "mean_current_simulator": mean(
            gk_current
        ),
        "mean_delta": mean(
            current - target
            for current, target
            in zip(
                gk_current,
                gk_sums,
            )
        ),
    },
    "exact_11_marginals_compatible": (
        exact_11_compatible
    ),
    "current_count_rule_marginals_compatible": (
        current_count_compatible
    ),
    "haaland_team_rows": (
        haaland_rows
    ),
    "top_count_pressures": (
        top_pressure[
            :20
        ]
    ),
    "top_exact_11_gaps": (
        top_11_gap[
            :20
        ]
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


# ============================================================
# Console
# ============================================================

print(
    "=== CAPTAIN-068D "
    "STARTER FEASIBILITY AUDIT ==="
)

print(
    "team-fixture rows:",
    len(
        rows
    ),
)

print()

print(
    "=== TARGET pSTART SUM ==="
)

print(
    "mean:",
    f"{mean(start_sums):.3f}",
)

print(
    "median:",
    f"{median(start_sums):.3f}",
)

print(
    "range:",
    f"{min(start_sums):.3f}",
    "->",
    f"{max(start_sums):.3f}",
)

print(
    "mean |gap to 11|:",
    f"{mean(abs(x) for x in gaps_to_11):.3f}",
)

print(
    "|gap to 11| >=0.5:",
    len(
        large_gap_11
    ),
    "/",
    len(
        rows
    ),
)


print()
print(
    "=== CURRENT V1 COUNT PRESSURE ==="
)

print(
    "mean pressure:",
    f"{mean(pressures):+.3f}",
)

print(
    "median pressure:",
    f"{median(pressures):+.3f}",
)

print(
    "mean absolute:",
    f"{mean(abs(x) for x in pressures):.3f}",
)

print(
    "max absolute:",
    f"{max(abs(x) for x in pressures):.3f}",
)

print(
    "|pressure| >=0.5:",
    len(
        large_pressure
    ),
    "/",
    len(
        rows
    ),
)


print()
print(
    "=== APPEARANCE COUNT EFFECT ==="
)

print(
    "P(<11 appearances) mean:",
    f"{mean(prob_lt_11):.3f}",
)

print(
    "P(<11 appearances) median:",
    f"{median(prob_lt_11):.3f}",
)

print(
    "P(<11 appearances) max:",
    f"{max(prob_lt_11):.3f}",
)


print()
print(
    "=== GOALKEEPERS ==="
)

print(
    "target ΣpStart GK:",
    f"{mean(gk_sums):.3f}",
)

print(
    "current P(any GK appears):",
    f"{mean(gk_current):.3f}",
)

print(
    "mean GK start pressure:",
    f"{mean(current - target for current, target in zip(gk_current, gk_sums)):+.3f}",
)


print()
print(
    "exact 11 compatible:",
    (
        "YES"
        if exact_11_compatible
        else "NO"
    ),
)

print(
    "current min(11, appearances) "
    "compatible:",
    (
        "YES"
        if current_count_compatible
        else "NO"
    ),
)


print()
print(
    "=== HAALAND TEAM ==="
)


for row in (
    haaland_rows
):

    print(
        "GW"
        f"{row['gameweek']} "
        f"ΣpStart="
        f"{row['target_start_sum']:.3f} "
        f"E[current starters]="
        f"{row['expected_current_simulator_starters']:.3f} "
        f"pressure="
        f"{row['current_count_pressure']:+.3f} "
        f"P(<11 app)="
        f"{row['probability_fewer_than_11_appear']:.3f} "
        f"GKΣ="
        f"{row['target_gk_start_sum']:.3f}"
    )


print()
print(
    "=== TOP 12 COUNT PRESSURES ==="
)


for row in (
    top_pressure[
        :12
    ]
):

    print(
        f"GW{str(row['gameweek']):<2} "
        f"{row['side']:<4} "
        f"ΣpStart="
        f"{row['target_start_sum']:6.2f} "
        f"Ecurrent="
        f"{row['expected_current_simulator_starters']:6.2f} "
        f"pressure="
        f"{row['current_count_pressure']:+6.2f} "
        f"P<11="
        f"{row['probability_fewer_than_11_appear']:.2f}"
    )


print()
print(
    "report:",
    REPORT.relative_to(
        ROOT
    ),
)
