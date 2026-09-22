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

ABS_TOL = 1e-12

OUT = (
    ROOT
    / "scratch"
    / "decision"
    / "captain064r_structural_audit.json"
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
# Recursive structural comparison
# ============================================================
#

def compare_values(
    left,
    right,
    path="root",
):

    issues = []
    max_numeric_delta = 0.0


    if isinstance(
        left,
        bool,
    ) or isinstance(
        right,
        bool,
    ):

        if left != right:

            issues.append({
                "path": path,
                "left": left,
                "right": right,
                "reason": "boolean_mismatch",
            })

        return (
            issues,
            max_numeric_delta,
        )


    numeric_types = (
        int,
        float,
    )


    if (
        isinstance(
            left,
            numeric_types,
        )
        and isinstance(
            right,
            numeric_types,
        )
    ):

        a = float(
            left
        )

        b = float(
            right
        )

        if (
            not math.isfinite(a)
            or not math.isfinite(b)
        ):

            if a != b:

                issues.append({
                    "path": path,
                    "left": a,
                    "right": b,
                    "reason": "nonfinite_mismatch",
                })

            return (
                issues,
                max_numeric_delta,
            )


        delta = abs(
            a - b
        )

        max_numeric_delta = delta


        if delta > ABS_TOL:

            issues.append({
                "path": path,
                "left": a,
                "right": b,
                "abs_delta": delta,
                "reason": "numeric_delta",
            })


        return (
            issues,
            max_numeric_delta,
        )


    if isinstance(
        left,
        dict,
    ) and isinstance(
        right,
        dict,
    ):

        left_keys = set(
            left
        )

        right_keys = set(
            right
        )


        if left_keys != right_keys:

            issues.append({
                "path": path,
                "left_only": sorted(
                    left_keys
                    - right_keys
                ),
                "right_only": sorted(
                    right_keys
                    - left_keys
                ),
                "reason": "key_mismatch",
            })


        for key in sorted(
            left_keys
            & right_keys
        ):

            child_issues, child_max = (
                compare_values(
                    left[
                        key
                    ],
                    right[
                        key
                    ],
                    f"{path}.{key}",
                )
            )

            issues.extend(
                child_issues
            )

            max_numeric_delta = max(
                max_numeric_delta,
                child_max,
            )


        return (
            issues,
            max_numeric_delta,
        )


    if isinstance(
        left,
        list,
    ) and isinstance(
        right,
        list,
    ):

        if len(
            left
        ) != len(
            right
        ):

            issues.append({
                "path": path,
                "left_length": len(
                    left
                ),
                "right_length": len(
                    right
                ),
                "reason": "length_mismatch",
            })


        for index, (
            left_item,
            right_item,
        ) in enumerate(
            zip(
                left,
                right,
            )
        ):

            child_issues, child_max = (
                compare_values(
                    left_item,
                    right_item,
                    f"{path}[{index}]",
                )
            )

            issues.extend(
                child_issues
            )

            max_numeric_delta = max(
                max_numeric_delta,
                child_max,
            )


        return (
            issues,
            max_numeric_delta,
        )


    if left != right:

        issues.append({
            "path": path,
            "left": left,
            "right": right,
            "reason": "value_mismatch",
        })


    return (
        issues,
        max_numeric_delta,
    )


#
# ============================================================
# Event determinism across simulation seeds
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
            f"Missing baseline events "
            f"for seed {seed}"
        )


    if not challenger_path.exists():

        raise RuntimeError(
            f"Missing challenger events "
            f"for seed {seed}"
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
# Seed 42 deterministic structural pair
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


def fixture_map(rows):

    return {
        str(
            row[
                "fixture_id"
            ]
        ):
        row
        for row in rows
    }


base_by_fixture = fixture_map(
    baseline_events
)

new_by_fixture = fixture_map(
    challenger_events
)


if (
    set(
        base_by_fixture
    )
    != set(
        new_by_fixture
    )
):

    raise RuntimeError(
        "Fixture universe differs."
    )


#
# Correct serialized Event artifact keys.
#
UNCHANGED_COMPONENTS = (
    "rates",
    "penalty",
    "assists",
    "clean_sheet",
    "goalkeeper",
    "defensive_contributions",
    "cards",
)


component_stats = {
    component: {
        "rows": 0,
        "exact_mismatch_rows": 0,
        "material_mismatch_rows": 0,
        "max_abs_numeric_delta": 0.0,
        "examples": [],
    }
    for component in (
        UNCHANGED_COMPONENTS
    )
}


top_level_stats = {
    "uncertainty": {
        "material_mismatch_rows": 0,
        "max_abs_numeric_delta": 0.0,
        "examples": [],
    },
    "confidence": {
        "material_mismatch_rows": 0,
        "max_abs_numeric_delta": 0.0,
        "examples": [],
    },
}


team_envelope_mismatches = 0
team_envelope_max_delta = 0.0

penalty_goal_mismatches = 0
penalty_goal_max_delta = 0.0

missing_component_keys = (
    defaultdict(
        int
    )
)

player_rows = 0


for fixture_id in sorted(
    base_by_fixture
):

    base_fixture = (
        base_by_fixture[
            fixture_id
        ]
    )

    new_fixture = (
        new_by_fixture[
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

        new_team = (
            new_fixture[
                side
            ]
        )


        #
        # Team envelope invariants.
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
                new_team[
                    field
                ]
            )

            delta = abs(
                a - b
            )

            team_envelope_max_delta = max(
                team_envelope_max_delta,
                delta,
            )

            if delta > ABS_TOL:

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

        new_players = {
            str(
                row[
                    "rates"
                ][
                    "player_id"
                ]
            ):
            row
            for row in new_team[
                "players"
            ]
        }


        if (
            set(
                base_players
            )
            != set(
                new_players
            )
        ):

            raise RuntimeError(
                "Player universe differs "
                f"in {fixture_id} {side}."
            )


        for player_id in sorted(
            base_players
        ):

            player_rows += 1

            base_player = (
                base_players[
                    player_id
                ]
            )

            new_player = (
                new_players[
                    player_id
                ]
            )


            #
            # Penalty expected goals must
            # stay unchanged.
            #
            base_penalty_goal = float(
                base_player[
                    "goals"
                ][
                    "expected_penalty_goals"
                ]
            )

            new_penalty_goal = float(
                new_player[
                    "goals"
                ][
                    "expected_penalty_goals"
                ]
            )


            penalty_delta = abs(
                base_penalty_goal
                - new_penalty_goal
            )

            penalty_goal_max_delta = max(
                penalty_goal_max_delta,
                penalty_delta,
            )


            if penalty_delta > ABS_TOL:

                penalty_goal_mismatches += 1


            #
            # Component isolation.
            #
            for component in (
                UNCHANGED_COMPONENTS
            ):

                stats = (
                    component_stats[
                        component
                    ]
                )

                stats[
                    "rows"
                ] += 1


                if (
                    component
                    not in base_player
                    or component
                    not in new_player
                ):

                    missing_component_keys[
                        component
                    ] += 1

                    stats[
                        "material_mismatch_rows"
                    ] += 1

                    if len(
                        stats[
                            "examples"
                        ]
                    ) < 3:

                        stats[
                            "examples"
                        ].append({
                            "fixture_id": (
                                fixture_id
                            ),
                            "side": side,
                            "player_id": (
                                player_id
                            ),
                            "reason": (
                                "component_missing"
                            ),
                        })

                    continue


                left = (
                    base_player[
                        component
                    ]
                )

                right = (
                    new_player[
                        component
                    ]
                )


                if left != right:

                    stats[
                        "exact_mismatch_rows"
                    ] += 1


                issues, max_delta = (
                    compare_values(
                        left,
                        right,
                        path=component,
                    )
                )


                stats[
                    "max_abs_numeric_delta"
                ] = max(
                    stats[
                        "max_abs_numeric_delta"
                    ],
                    max_delta,
                )


                if issues:

                    stats[
                        "material_mismatch_rows"
                    ] += 1

                    if len(
                        stats[
                            "examples"
                        ]
                    ) < 3:

                        stats[
                            "examples"
                        ].append({
                            "fixture_id": (
                                fixture_id
                            ),
                            "side": side,
                            "player_id": (
                                player_id
                            ),
                            "issues": (
                                issues[:3]
                            ),
                        })


            #
            # Top-level uncertainty/confidence
            # also should not move.
            #
            for field in (
                "uncertainty",
                "confidence",
            ):

                issues, max_delta = (
                    compare_values(
                        base_player.get(
                            field
                        ),
                        new_player.get(
                            field
                        ),
                        path=field,
                    )
                )

                stats = (
                    top_level_stats[
                        field
                    ]
                )

                stats[
                    "max_abs_numeric_delta"
                ] = max(
                    stats[
                        "max_abs_numeric_delta"
                    ],
                    max_delta,
                )

                if issues:

                    stats[
                        "material_mismatch_rows"
                    ] += 1

                    if len(
                        stats[
                            "examples"
                        ]
                    ) < 3:

                        stats[
                            "examples"
                        ].append({
                            "fixture_id": (
                                fixture_id
                            ),
                            "side": side,
                            "player_id": (
                                player_id
                            ),
                            "issues": (
                                issues[:3]
                            ),
                        })


#
# ============================================================
# Gate
# ============================================================
#

components_pass = all(
    row[
        "material_mismatch_rows"
    ]
    == 0
    for row in (
        component_stats.values()
    )
)

top_level_pass = all(
    row[
        "material_mismatch_rows"
    ]
    == 0
    for row in (
        top_level_stats.values()
    )
)


structural_pass = all((
    baseline_deterministic,
    challenger_deterministic,
    team_envelope_mismatches == 0,
    penalty_goal_mismatches == 0,
    components_pass,
    top_level_pass,
    not missing_component_keys,
))


report = {
    "status": (
        "DEVELOPMENT_ONLY_"
        "STRUCTURAL_PROMOTION_GATE"
    ),
    "absolute_tolerance": (
        ABS_TOL
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
    "player_rows": (
        player_rows
    ),
    "team_envelope": {
        "mismatches": (
            team_envelope_mismatches
        ),
        "max_abs_delta": (
            team_envelope_max_delta
        ),
    },
    "penalty_goals": {
        "mismatches": (
            penalty_goal_mismatches
        ),
        "max_abs_delta": (
            penalty_goal_max_delta
        ),
    },
    "components": (
        component_stats
    ),
    "top_level": (
        top_level_stats
    ),
    "missing_component_keys": (
        dict(
            missing_component_keys
        )
    ),
    "structural_pass": (
        structural_pass
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
    "=== CAPTAIN-064R "
    "TOLERANT STRUCTURAL AUDIT ==="
)

print(
    "tolerance:",
    ABS_TOL,
)

print(
    "baseline deterministic:",
    (
        "PASS"
        if baseline_deterministic
        else "FAIL"
    ),
)

print(
    "challenger deterministic:",
    (
        "PASS"
        if challenger_deterministic
        else "FAIL"
    ),
)

print(
    "team envelope:",
    (
        "PASS"
        if team_envelope_mismatches == 0
        else "FAIL"
    ),
    "max_delta=",
    f"{team_envelope_max_delta:.3e}",
)

print(
    "penalty goals:",
    (
        "PASS"
        if penalty_goal_mismatches == 0
        else "FAIL"
    ),
    "max_delta=",
    f"{penalty_goal_max_delta:.3e}",
)


print()
print(
    "=== COMPONENT ISOLATION ==="
)


for component in (
    UNCHANGED_COMPONENTS
):

    row = (
        component_stats[
            component
        ]
    )

    print(
        f"{component:<26} "
        f"exact_rows="
        f"{row['exact_mismatch_rows']:<5} "
        f"material_rows="
        f"{row['material_mismatch_rows']:<5} "
        f"max_delta="
        f"{row['max_abs_numeric_delta']:.3e}"
    )


print()
print(
    "=== TOP-LEVEL ISOLATION ==="
)


for field, row in (
    top_level_stats.items()
):

    print(
        f"{field:<26} "
        f"material_rows="
        f"{row['material_mismatch_rows']:<5} "
        f"max_delta="
        f"{row['max_abs_numeric_delta']:.3e}"
    )


if missing_component_keys:

    print()
    print(
        "MISSING COMPONENT KEYS:"
    )

    for key, count in sorted(
        missing_component_keys.items()
    ):

        print(
            key,
            count,
        )


material_examples = []


for component, row in (
    component_stats.items()
):

    if row[
        "material_mismatch_rows"
    ]:

        material_examples.append(
            (
                component,
                row[
                    "examples"
                ],
            )
        )


for field, row in (
    top_level_stats.items()
):

    if row[
        "material_mismatch_rows"
    ]:

        material_examples.append(
            (
                field,
                row[
                    "examples"
                ],
            )
        )


if material_examples:

    print()
    print(
        "=== MATERIAL DIFFERENCE EXAMPLES ==="
    )

    for component, examples in (
        material_examples
    ):

        print()
        print(
            component
        )

        for example in examples:

            print(
                json.dumps(
                    example,
                    ensure_ascii=False,
                )
            )


print()
print(
    "STRUCTURAL GATE:",
    (
        "PASS"
        if structural_pass
        else "FAIL"
    ),
)

print(
    "report:",
    OUT.relative_to(
        ROOT
    ),
)

print(
    "Production/frozen artifacts modified: NO"
)
