from __future__ import annotations

from collections import defaultdict
from pathlib import Path
import hashlib
import json
import math


ROOT = Path(".").resolve()

MULTI = (
    ROOT
    / "scratch"
    / "decision"
    / "captain063_same_source_multiseed"
)

STAMP = "20260912T100351Z"

SEEDS = (
    42,
    202627,
    606,
    91991,
)

OUT = (
    ROOT
    / "scratch"
    / "decision"
    / "captain064_penalty_isolation_audit.json"
)


def load(path: Path):

    return json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )


def digest(path: Path):

    return hashlib.sha256(
        path.read_bytes()
    ).hexdigest()


def run_dir(
    seed: int,
    mode: str,
):

    return (
        MULTI
        / f"seed_{seed}"
        / mode
        / "output"
        / "2026-27"
        / STAMP
    )


#
# ============================================================
# 1. Event projections must be deterministic across seeds.
# ============================================================
#

baseline_hashes = {}

challenger_hashes = {}


for seed in SEEDS:

    baseline_path = (
        run_dir(
            seed,
            "baseline",
        )
        / "event_projections.json"
    )

    challenger_path = (
        run_dir(
            seed,
            "challenger",
        )
        / "event_projections.json"
    )

    if not baseline_path.exists():

        raise RuntimeError(
            f"Missing baseline events: {seed}"
        )

    if not challenger_path.exists():

        raise RuntimeError(
            f"Missing challenger events: {seed}"
        )


    baseline_hashes[
        seed
    ] = digest(
        baseline_path
    )

    challenger_hashes[
        seed
    ] = digest(
        challenger_path
    )


baseline_deterministic = (
    len(
        set(
            baseline_hashes.values()
        )
    )
    == 1
)

challenger_deterministic = (
    len(
        set(
            challenger_hashes.values()
        )
    )
    == 1
)


#
# ============================================================
# 2. Detailed comparison on seed 42.
#
# Simulation seed is irrelevant to Event projection,
# so one deterministic event pair is enough here.
# ============================================================
#

BASE = run_dir(
    42,
    "baseline",
)

CHALLENGER = run_dir(
    42,
    "challenger",
)


baseline_events = load(
    BASE
    / "event_projections.json"
)

challenger_events = load(
    CHALLENGER
    / "event_projections.json"
)

players = load(
    BASE
    / "current_players.json"
)


names = {
    str(
        row["player_id"]
    ):
    (
        row.get(
            "display_name"
        )
        or str(
            row["player_id"]
        )
    )
    for row in players
}


def fixture_map(rows):

    return {
        str(
            row["fixture_id"]
        ):
        row
        for row in rows
    }


base_by_fixture = fixture_map(
    baseline_events
)

challenger_by_fixture = fixture_map(
    challenger_events
)


if (
    set(
        base_by_fixture
    )
    != set(
        challenger_by_fixture
    )
):

    raise RuntimeError(
        "Fixture universes differ."
    )


#
# These components MUST remain identical.
#
# BPS is intentionally excluded:
# changing expected goals should change BPS.
#
UNCHANGED_PLAYER_COMPONENTS = (
    "rates",
    "penalty",
    "assists",
    "clean_sheet",
    "goalkeeper",
    "defensive",
    "cards",
)


component_mismatches = (
    defaultdict(
        int
    )
)

team_envelope_mismatches = 0
penalty_goal_mismatches = 0
penalty_goal_max_abs_delta = 0.0

total_rows = 0


#
# Penalty-bias cohorts.
#
cohorts = {
    "PRIMARY": {
        "count": 0,
        "open_delta": 0.0,
        "abs_open_delta": 0.0,
    },
    "SECONDARY": {
        "count": 0,
        "open_delta": 0.0,
        "abs_open_delta": 0.0,
    },
    "NONE": {
        "count": 0,
        "open_delta": 0.0,
        "abs_open_delta": 0.0,
    },
}


player_full_delta = defaultdict(
    float
)

player_stress_delta = defaultdict(
    float
)

player_penalty_rows = defaultdict(
    lambda: {
        "primary": 0,
        "secondary": 0,
        "none": 0,
    }
)


for fixture_id in sorted(
    base_by_fixture
):

    base_fixture = (
        base_by_fixture[
            fixture_id
        ]
    )

    challenger_fixture = (
        challenger_by_fixture[
            fixture_id
        ]
    )


    for side in (
        "home",
        "away",
    ):

        base_team = (
            base_fixture[
                side
            ]
        )

        challenger_team = (
            challenger_fixture[
                side
            ]
        )


        #
        # Team goal envelope itself must
        # be exactly preserved.
        #
        for field in (
            "expected_team_goals",
            "own_goal_expected_goals",
            "allocated_player_goals",
            "unassigned_expected_goals",
        ):

            a = float(
                base_team[
                    field
                ]
            )

            b = float(
                challenger_team[
                    field
                ]
            )

            if not math.isclose(
                a,
                b,
                rel_tol=0.0,
                abs_tol=1e-12,
            ):

                team_envelope_mismatches += 1


        base_players = {
            str(
                row[
                    "rates"
                ][
                    "player_id"
                ]
            ):
            row
            for row in base_team[
                "players"
            ]
        }

        challenger_players = {
            str(
                row[
                    "rates"
                ][
                    "player_id"
                ]
            ):
            row
            for row in challenger_team[
                "players"
            ]
        }


        if (
            set(
                base_players
            )
            != set(
                challenger_players
            )
        ):

            raise RuntimeError(
                "Player universe differs "
                f"in {fixture_id} {side}."
            )


        #
        # We also build a deliberately harsh
        # stress scenario:
        #
        # for current PRIMARY penalty takers,
        # keep only HALF of the challenger
        # movement from baseline share.
        #
        # This is NOT another model candidate.
        # It is only a sensitivity diagnostic.
        #
        open_envelope = sum(
            float(
                row[
                    "goals"
                ][
                    "expected_open_play_goals"
                ]
            )
            for row in base_players.values()
        )


        stress_weights = {}


        for player_id in base_players:

            base_player = (
                base_players[
                    player_id
                ]
            )

            challenger_player = (
                challenger_players[
                    player_id
                ]
            )

            total_rows += 1


            for component in (
                UNCHANGED_PLAYER_COMPONENTS
            ):

                if (
                    base_player.get(
                        component
                    )
                    != challenger_player.get(
                        component
                    )
                ):

                    component_mismatches[
                        component
                    ] += 1


            base_penalty = float(
                base_player[
                    "goals"
                ][
                    "expected_penalty_goals"
                ]
            )

            challenger_penalty = float(
                challenger_player[
                    "goals"
                ][
                    "expected_penalty_goals"
                ]
            )


            penalty_delta = (
                challenger_penalty
                - base_penalty
            )

            penalty_goal_max_abs_delta = max(
                penalty_goal_max_abs_delta,
                abs(
                    penalty_delta
                ),
            )


            if not math.isclose(
                base_penalty,
                challenger_penalty,
                rel_tol=0.0,
                abs_tol=1e-12,
            ):

                penalty_goal_mismatches += 1


            taker_probability = float(
                base_player[
                    "penalty"
                ][
                    "taker_selection_probability"
                ]
            )


            if taker_probability >= 0.5:

                cohort = "PRIMARY"

                player_penalty_rows[
                    player_id
                ][
                    "primary"
                ] += 1

            elif taker_probability > 0.0:

                cohort = "SECONDARY"

                player_penalty_rows[
                    player_id
                ][
                    "secondary"
                ] += 1

            else:

                cohort = "NONE"

                player_penalty_rows[
                    player_id
                ][
                    "none"
                ] += 1


            base_open = float(
                base_player[
                    "goals"
                ][
                    "expected_open_play_goals"
                ]
            )

            challenger_open = float(
                challenger_player[
                    "goals"
                ][
                    "expected_open_play_goals"
                ]
            )

            delta = (
                challenger_open
                - base_open
            )


            cohorts[
                cohort
            ][
                "count"
            ] += 1

            cohorts[
                cohort
            ][
                "open_delta"
            ] += delta

            cohorts[
                cohort
            ][
                "abs_open_delta"
            ] += abs(
                delta
            )


            player_full_delta[
                player_id
            ] += delta


            if open_envelope > 0.0:

                base_share = (
                    base_open
                    / open_envelope
                )

                challenger_share = (
                    challenger_open
                    / open_envelope
                )

            else:

                base_share = 0.0
                challenger_share = 0.0


            if cohort == "PRIMARY":

                #
                # Halfway back toward V1.
                #
                stress_share = (
                    base_share
                    + 0.5
                    * (
                        challenger_share
                        - base_share
                    )
                )

            else:

                stress_share = (
                    challenger_share
                )


            stress_weights[
                player_id
            ] = max(
                0.0,
                stress_share,
            )


        stress_total = sum(
            stress_weights.values()
        )


        for player_id in base_players:

            base_open = float(
                base_players[
                    player_id
                ][
                    "goals"
                ][
                    "expected_open_play_goals"
                ]
            )


            if (
                open_envelope > 0.0
                and stress_total > 0.0
            ):

                stressed_open = (
                    open_envelope
                    * stress_weights[
                        player_id
                    ]
                    / stress_total
                )

            else:

                stressed_open = (
                    base_open
                )


            player_stress_delta[
                player_id
            ] += (
                stressed_open
                - base_open
            )


#
# ============================================================
# 3. Structural PASS gate
# ============================================================
#

component_pass = all(
    value == 0
    for value in (
        component_mismatches.values()
    )
)


structural_pass = all((
    baseline_deterministic,
    challenger_deterministic,
    team_envelope_mismatches == 0,
    penalty_goal_mismatches == 0,
    component_pass,
))


#
# ============================================================
# 4. Key players
# ============================================================
#

def find_name(
    token,
):

    token = token.casefold()

    matches = [
        player_id
        for player_id, name
        in names.items()
        if token
        in str(
            name
        ).casefold()
    ]

    return matches


key_tokens = (
    "Haaland",
    "Palmer",
    "B.Fernandes",
    "Tavernier",
)


key_rows = []


for token in key_tokens:

    matches = find_name(
        token
    )


    for player_id in matches:

        roles = (
            player_penalty_rows[
                player_id
            ]
        )

        key_rows.append({
            "name": (
                names[
                    player_id
                ]
            ),
            "player_id": (
                player_id
            ),
            "full_open_delta": (
                player_full_delta[
                    player_id
                ]
            ),
            "half_primary_stress_delta": (
                player_stress_delta[
                    player_id
                ]
            ),
            "primary_rows": (
                roles[
                    "primary"
                ]
            ),
            "secondary_rows": (
                roles[
                    "secondary"
                ]
            ),
            "none_rows": (
                roles[
                    "none"
                ]
            ),
        })


report = {
    "status": (
        "DEVELOPMENT_ONLY_"
        "PROMOTION_GATE"
    ),
    "event_determinism": {
        "baseline": (
            baseline_deterministic
        ),
        "challenger": (
            challenger_deterministic
        ),
        "baseline_hashes": (
            baseline_hashes
        ),
        "challenger_hashes": (
            challenger_hashes
        ),
    },
    "structural": {
        "pass": (
            structural_pass
        ),
        "player_rows": (
            total_rows
        ),
        "team_envelope_mismatches": (
            team_envelope_mismatches
        ),
        "penalty_goal_mismatches": (
            penalty_goal_mismatches
        ),
        "penalty_goal_max_abs_delta": (
            penalty_goal_max_abs_delta
        ),
        "unchanged_component_mismatches": (
            dict(
                component_mismatches
            )
        ),
    },
    "penalty_cohorts": (
        cohorts
    ),
    "key_players": (
        key_rows
    ),
}


OUT.write_text(
    json.dumps(
        report,
        indent=2,
        sort_keys=True,
    )
    + "\n",
    encoding="utf-8",
)


print(
    "=== CAPTAIN-064 "
    "PROMOTION ISOLATION AUDIT ==="
)

print(
    "baseline event deterministic:",
    (
        "PASS"
        if baseline_deterministic
        else "FAIL"
    ),
)

print(
    "challenger event deterministic:",
    (
        "PASS"
        if challenger_deterministic
        else "FAIL"
    ),
)

print(
    "team envelope unchanged:",
    (
        "PASS"
        if team_envelope_mismatches == 0
        else "FAIL"
    ),
)

print(
    "penalty goals unchanged:",
    (
        "PASS"
        if penalty_goal_mismatches == 0
        else "FAIL"
    ),
)

print(
    "penalty max abs delta:",
    f"{penalty_goal_max_abs_delta:.12f}",
)

print(
    "non-goal components unchanged:",
    (
        "PASS"
        if component_pass
        else "FAIL"
    ),
)

print(
    "STRUCTURAL GATE:",
    (
        "PASS"
        if structural_pass
        else "FAIL"
    ),
)


print()
print(
    "=== OPEN-GOAL DELTA "
    "BY CURRENT PENALTY ROLE ==="
)


for name in (
    "PRIMARY",
    "SECONDARY",
    "NONE",
):

    row = cohorts[
        name
    ]

    count = int(
        row[
            "count"
        ]
    )

    mean = (
        row[
            "open_delta"
        ]
        / count
        if count
        else 0.0
    )

    print(
        f"{name:<10} "
        f"rows={count:<5} "
        f"sum={row['open_delta']:+.3f} "
        f"mean={mean:+.4f} "
        f"abs={row['abs_open_delta']:.3f}"
    )


print()
print(
    "=== PENALTY-TAKER "
    "HALF-EFFECT STRESS ==="
)


for row in key_rows:

    print(
        f"{row['name']:<24} "
        f"full={row['full_open_delta']:+.3f} "
        f"stress={row['half_primary_stress_delta']:+.3f} "
        f"primary="
        f"{row['primary_rows']} "
        f"secondary="
        f"{row['secondary_rows']}"
    )


print()
print(
    "report:",
    OUT.relative_to(
        ROOT
    ),
)

print(
    "Production/frozen artifacts modified: NO"
)
