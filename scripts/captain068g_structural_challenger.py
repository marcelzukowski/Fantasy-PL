from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from types import SimpleNamespace
from statistics import mean
import json
import math

import numpy as np

from fpl_engine.simulation.v22 import (
    FixtureSimulatorV22,
    _dependent_round,
)


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
    / "captain068g"
)

REPORT = (
    OUT_DIR
    / "structural_challenger.json"
)

DRAWS = 3000
SEED = 6807

EPS = 1e-12


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

players_json = load(
    RUN
    / "current_players.json"
)

fixtures = load(
    RUN
    / "fixture_horizon.json"
)


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
    for row in players_json
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


HAALAND = haaland_ids[
    0
]


fixture_info = {
    str(
        row[
            "fixture_id"
        ]
    ):
    row
    for row in fixtures
}


def fake_team(
    payload,
):

    fake_players = []

    for player in payload[
        "players"
    ]:

        rates = player[
            "rates"
        ]

        fake_rates = SimpleNamespace(
            player_id=str(
                rates[
                    "player_id"
                ]
            ),
            position=str(
                rates[
                    "position"
                ]
            ).upper(),
            p_start=float(
                rates[
                    "p_start"
                ]
            ),
            p_appearance=float(
                rates[
                    "p_appearance"
                ]
            ),
            expected_minutes=float(
                rates[
                    "expected_minutes"
                ]
            ),
            minute_distribution=tuple(
                float(value)
                for value in rates[
                    "minute_distribution"
                ]
            ),
            starter_minutes_distribution=tuple(
                float(value)
                for value in rates[
                    "starter_minutes_distribution"
                ]
            ),
            bench_minutes_distribution=tuple(
                float(value)
                for value in rates[
                    "bench_minutes_distribution"
                ]
            ),
        )

        fake_players.append(
            SimpleNamespace(
                rates=fake_rates
            )
        )

    return SimpleNamespace(
        team_id=str(
            payload.get(
                "team_id",
                "",
            )
        ),
        players=tuple(
            fake_players
        ),
    )


simulator = object.__new__(
    FixtureSimulatorV22
)

simulator._v22_team_plan_cache = {}


team_rows = []

player_rows = []

max_reconstruction_delta = 0.0
max_unchanged_raw_pmf_delta = 0.0
max_unchanged_expected_minutes_delta = 0.0

appearance_raised = []

haaland_rows = []


fake_teams = []


for fixture in events:

    fixture_id = str(
        fixture[
            "fixture_id"
        ]
    )

    gameweek = (
        fixture_info
        .get(
            fixture_id,
            {},
        )
        .get(
            "target_gameweek"
        )
    )


    for side in (
        "home",
        "away",
    ):

        team = fake_team(
            fixture[
                side
            ]
        )

        fake_teams.append(
            (
                fixture_id,
                gameweek,
                side,
                team,
            )
        )

        plan = (
            simulator
            ._build_team_plan(
                team
            )
        )


        gks = [
            player
            for player in team.players
            if player.rates.position
            == "GK"
        ]

        outfield = [
            player
            for player in team.players
            if player.rates.position
            != "GK"
        ]


        start_sum = sum(
            row.p_start
            for row in plan.values()
        )

        gk_sum = sum(
            plan[
                player.rates.player_id
            ].p_start
            for player in gks
        )

        outfield_sum = sum(
            plan[
                player.rates.player_id
            ].p_start
            for player in outfield
        )


        team_rows.append({
            "fixture_id":
                fixture_id,
            "gameweek":
                gameweek,
            "side":
                side,
            "start_sum":
                start_sum,
            "gk_start_sum":
                gk_sum,
            "outfield_start_sum":
                outfield_sum,
        })


        for player in team.players:

            rates = (
                player.rates
            )

            row = plan[
                rates.player_id
            ]


            starter = np.asarray(
                row.starter_minutes_distribution,
                dtype=float,
            )

            bench = np.asarray(
                row.bench_minutes_distribution,
                dtype=float,
            )

            adjusted = np.asarray(
                row.adjusted_minute_distribution,
                dtype=float,
            )


            reconstructed = np.zeros(
                91,
                dtype=float,
            )

            reconstructed[0] = (
                1.0
                - row.p_appearance
            )

            reconstructed += (
                row.p_start
                * starter
            )

            reconstructed += (
                (
                    row.p_appearance
                    - row.p_start
                )
                * bench
            )


            reconstruction_delta = float(
                np.max(
                    np.abs(
                        reconstructed
                        - adjusted
                    )
                )
            )

            max_reconstruction_delta = max(
                max_reconstruction_delta,
                reconstruction_delta,
            )


            raw_pmf = np.asarray(
                rates.minute_distribution,
                dtype=float,
            )

            appearance_delta = (
                row.p_appearance
                - row.raw_p_appearance
            )


            if (
                abs(
                    appearance_delta
                )
                <= 1e-12
            ):

                raw_delta = float(
                    np.max(
                        np.abs(
                            adjusted
                            - raw_pmf
                        )
                    )
                )

                max_unchanged_raw_pmf_delta = max(
                    max_unchanged_raw_pmf_delta,
                    raw_delta,
                )

                expected_delta = abs(
                    row.adjusted_expected_minutes
                    - rates.expected_minutes
                )

                max_unchanged_expected_minutes_delta = max(
                    max_unchanged_expected_minutes_delta,
                    expected_delta,
                )


            if appearance_delta > 1e-12:

                appearance_raised.append(
                    appearance_delta
                )


            player_record = {
                "fixture_id":
                    fixture_id,
                "gameweek":
                    gameweek,
                "side":
                    side,
                "player_id":
                    rates.player_id,
                "name":
                    names.get(
                        rates.player_id,
                        rates.player_id,
                    ),
                "position":
                    rates.position,
                "raw_p_start":
                    row.raw_p_start,
                "adjusted_p_start":
                    row.p_start,
                "raw_p_appearance":
                    row.raw_p_appearance,
                "adjusted_p_appearance":
                    row.p_appearance,
                "raw_expected_minutes":
                    row.raw_expected_minutes,
                "adjusted_expected_minutes":
                    row.adjusted_expected_minutes,
            }

            player_rows.append(
                player_record
            )


            if (
                rates.player_id
                == HAALAND
            ):

                haaland_rows.append(
                    player_record
                )


# ============================================================
# Monte Carlo inclusion-marginal audit.
#
# We test the exact fixed-size sampler directly. Minute PMFs
# have already been checked algebraically above.
# ============================================================

rng = np.random.default_rng(
    SEED
)

start_abs_errors = []

appearance_abs_errors = []

distortions_10pp = 0


for (
    fixture_id,
    gameweek,
    side,
    team,
) in fake_teams:

    plan = (
        simulator
        ._build_team_plan(
            team
        )
    )


    groups = (
        (
            [
                player
                for player
                in team.players
                if player.rates.position
                == "GK"
            ],
            1,
        ),
        (
            [
                player
                for player
                in team.players
                if player.rates.position
                != "GK"
            ],
            10,
        ),
    )


    start_counts = defaultdict(
        int
    )

    appearance_counts = defaultdict(
        int
    )


    for _ in range(
        DRAWS
    ):

        starters = set()


        for group, target in groups:

            probabilities = [
                plan[
                    player.rates.player_id
                ].p_start
                for player in group
            ]

            chosen = _dependent_round(
                probabilities,
                target=target,
                rng=rng,
            )

            starters.update(
                group[
                    index
                ].rates.player_id
                for index
                in chosen
            )


        for player in team.players:

            player_id = (
                player.rates.player_id
            )

            row = plan[
                player_id
            ]


            if player_id in starters:

                start_counts[
                    player_id
                ] += 1

                appearance_counts[
                    player_id
                ] += 1

                continue


            denominator = (
                1.0
                - row.p_start
            )

            if denominator <= EPS:

                q_bench = 0.0

            else:

                q_bench = (
                    (
                        row.p_appearance
                        - row.p_start
                    )
                    / denominator
                )

            q_bench = min(
                1.0,
                max(
                    0.0,
                    q_bench,
                ),
            )


            if (
                rng.random()
                < q_bench
            ):

                appearance_counts[
                    player_id
                ] += 1


    for player in team.players:

        player_id = (
            player.rates.player_id
        )

        row = plan[
            player_id
        ]

        empirical_start = (
            start_counts[
                player_id
            ]
            / DRAWS
        )

        empirical_appearance = (
            appearance_counts[
                player_id
            ]
            / DRAWS
        )

        start_error = abs(
            empirical_start
            - row.p_start
        )

        appearance_error = abs(
            empirical_appearance
            - row.p_appearance
        )

        start_abs_errors.append(
            start_error
        )

        appearance_abs_errors.append(
            appearance_error
        )

        if start_error >= 0.10:
            distortions_10pp += 1


# ============================================================
# Gates
# ============================================================

team_constraint_gate = all(
    math.isclose(
        row[
            "start_sum"
        ],
        11.0,
        abs_tol=1e-8,
        rel_tol=0.0,
    )
    and math.isclose(
        row[
            "gk_start_sum"
        ],
        1.0,
        abs_tol=1e-8,
        rel_tol=0.0,
    )
    and math.isclose(
        row[
            "outfield_start_sum"
        ],
        10.0,
        abs_tol=1e-8,
        rel_tol=0.0,
    )
    for row in team_rows
)


pmf_gate = (
    max_reconstruction_delta
    < 1e-9
)


unchanged_marginal_gate = (
    max_unchanged_raw_pmf_delta
    < 1e-9
)


unchanged_minutes_gate = (
    max_unchanged_expected_minutes_delta
    < 1e-8
)


start_marginal_mae = mean(
    start_abs_errors
)

appearance_marginal_mae = mean(
    appearance_abs_errors
)


monte_carlo_gate = all((
    start_marginal_mae
    < 0.015,
    appearance_marginal_mae
    < 0.015,
    distortions_10pp
    == 0,
))


haaland_gate = all(
    (
        abs(
            row[
                "adjusted_p_appearance"
            ]
            - row[
                "raw_p_appearance"
            ]
        )
        < 1e-12
        and abs(
            row[
                "adjusted_expected_minutes"
            ]
            - row[
                "raw_expected_minutes"
            ]
        )
        < 1e-8
    )
    for row in haaland_rows
)


gate = all((
    len(
        team_rows
    )
    == 120,

    team_constraint_gate,
    pmf_gate,
    unchanged_marginal_gate,
    unchanged_minutes_gate,
    monte_carlo_gate,
    haaland_gate,
))


report = {
    "status":
        "CAPTAIN_068G_A_"
        "STRUCTURAL_CHALLENGER",

    "simulator_version":
        FixtureSimulatorV22.VERSION,

    "historically_selected_reconciliation":
        "logit_shift",

    "production_modified":
        False,

    "current_pipeline_wired":
        False,

    "team_fixture_rows":
        len(
            team_rows
        ),

    "player_fixture_rows":
        len(
            player_rows
        ),

    "appearance_adjustments": {
        "rows":
            len(
                appearance_raised
            ),

        "rate":
            (
                len(
                    appearance_raised
                )
                / len(
                    player_rows
                )
            ),

        "mean_when_changed":
            (
                mean(
                    appearance_raised
                )
                if appearance_raised
                else 0.0
            ),

        "max":
            (
                max(
                    appearance_raised
                )
                if appearance_raised
                else 0.0
            ),
    },

    "minute_contract": {
        "max_reconstruction_delta":
            max_reconstruction_delta,

        "max_raw_pmf_delta_when_appearance_unchanged":
            max_unchanged_raw_pmf_delta,

        "max_expected_minutes_delta_when_appearance_unchanged":
            max_unchanged_expected_minutes_delta,
    },

    "monte_carlo": {
        "draws_per_team_fixture":
            DRAWS,

        "seed":
            SEED,

        "starter_mae":
            start_marginal_mae,

        "appearance_mae":
            appearance_marginal_mae,

        "starter_errors_ge_10pp":
            distortions_10pp,
    },

    "haaland":
        sorted(
            haaland_rows,
            key=lambda row:
                row[
                    "gameweek"
                ],
        ),

    "gates": {
        "team_constraints":
            team_constraint_gate,

        "minute_reconstruction":
            pmf_gate,

        "unchanged_full_pmf":
            unchanged_marginal_gate,

        "unchanged_expected_minutes":
            unchanged_minutes_gate,

        "marginal_sampling":
            monte_carlo_gate,

        "haaland_minutes_preserved":
            haaland_gate,

        "overall":
            gate,
    },
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
    "=== CAPTAIN-068G-A "
    "STRUCTURAL CHALLENGER ==="
)

print(
    "simulator:",
    FixtureSimulatorV22.VERSION,
)

print(
    "team-fixtures:",
    len(
        team_rows
    ),
)

print(
    "player-fixtures:",
    len(
        player_rows
    ),
)


print()
print(
    "=== STRUCTURAL CONSTRAINTS ==="
)

print(
    "1 GK + 10 outfield:",
    (
        "PASS"
        if team_constraint_gate
        else "FAIL"
    ),
)

print(
    "minute PMF reconstruction:",
    (
        "PASS"
        if pmf_gate
        else "FAIL"
    ),
)

print(
    "unchanged appearance -> "
    "exact full PMF:",
    (
        "PASS"
        if unchanged_marginal_gate
        else "FAIL"
    ),
)

print(
    "unchanged appearance -> "
    "expected minutes preserved:",
    (
        "PASS"
        if unchanged_minutes_gate
        else "FAIL"
    ),
)


print()
print(
    "=== APPEARANCE ADJUSTMENTS ==="
)

print(
    "rows raised:",
    len(
        appearance_raised
    ),
    "/",
    len(
        player_rows
    ),
)

print(
    "rate:",
    f"{len(appearance_raised) / len(player_rows):.4f}",
)

print(
    "max raise:",
    (
        f"{max(appearance_raised):.4f}"
        if appearance_raised
        else "0.0000"
    ),
)


print()
print(
    "=== FIXED-SIZE SAMPLING ==="
)

print(
    "draws/team-fixture:",
    DRAWS,
)

print(
    "starter marginal MAE:",
    f"{start_marginal_mae:.4f}",
)

print(
    "appearance marginal MAE:",
    f"{appearance_marginal_mae:.4f}",
)

print(
    "starter errors >=10pp:",
    distortions_10pp,
)

print(
    "sampling gate:",
    (
        "PASS"
        if monte_carlo_gate
        else "FAIL"
    ),
)


print()
print(
    "=== HAALAND ==="
)

for row in sorted(
    haaland_rows,
    key=lambda value:
        value[
            "gameweek"
        ],
):

    print(
        f"GW{row['gameweek']} "
        f"pStart "
        f"{row['raw_p_start']:.3f}"
        f" -> "
        f"{row['adjusted_p_start']:.3f} | "
        f"pApp "
        f"{row['raw_p_appearance']:.3f}"
        f" -> "
        f"{row['adjusted_p_appearance']:.3f} | "
        f"minutes "
        f"{row['raw_expected_minutes']:.2f}"
        f" -> "
        f"{row['adjusted_expected_minutes']:.2f}"
    )


print()
print(
    "STRUCTURAL CHALLENGER GATE:",
    (
        "PASS"
        if gate
        else "FAIL"
    ),
)

print(
    "production modified:",
    "NO",
)

print(
    "current pipeline wired:",
    "NO",
)

print(
    "report:",
    REPORT.relative_to(
        ROOT
    ),
)


if not gate:

    raise RuntimeError(
        "CAPTAIN-068G-A structural "
        "challenger gate failed."
    )
