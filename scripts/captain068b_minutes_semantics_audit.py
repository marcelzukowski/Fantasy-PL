from __future__ import annotations

from pathlib import Path
from statistics import mean, median
import inspect
import json
import math

from fpl_engine.simulation import FixtureSimulator


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
    / "minutes_consistency.json"
)

SOURCE_OUT = (
    OUT_DIR
    / "fixture_simulator_v1_source.txt"
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


# ============================================================
# Player names
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


# ============================================================
# FixtureSimulator V1 source
# ============================================================

source = inspect.getsource(
    FixtureSimulator
)

SOURCE_OUT.write_text(
    source,
    encoding="utf-8",
)


interesting_source = []


source_lines = (
    source.splitlines()
)


tokens = (
    "p_appearance",
    "p_start",
    "minute_distribution",
    "starter_minutes_distribution",
    "bench_minutes_distribution",
    "minutes",
)


for index, line in enumerate(
    source_lines,
    start=1,
):

    if any(
        token in line
        for token in tokens
    ):

        lo = max(
            1,
            index - 3,
        )

        hi = min(
            len(
                source_lines
            ),
            index + 3,
        )


        interesting_source.append({
            "line": index,
            "context": [
                {
                    "line": number,
                    "text": (
                        source_lines[
                            number - 1
                        ]
                    ),
                }
                for number
                in range(
                    lo,
                    hi + 1,
                )
            ],
        })


# ============================================================
# Minutes artifact
# ============================================================

minute_map = {
    (
        str(
            row[
                "player_id"
            ]
        ),
        str(
            row[
                "fixture_id"
            ]
        ),
    ):
    row
    for row in minutes
}


if len(
    minute_map
) != len(
    minutes
):

    raise RuntimeError(
        "Duplicate player/fixture rows "
        "in minutes.json."
    )


# ============================================================
# Extract Event Model rate rows
# ============================================================

event_rates = {}


def walk(value):

    if isinstance(
        value,
        dict,
    ):

        required = {
            "player_id",
            "fixture_id",
            "expected_minutes",
            "p_appearance",
            "p_start",
            "minute_distribution",
        }


        if required.issubset(
            value.keys()
        ):

            key = (
                str(
                    value[
                        "player_id"
                    ]
                ),
                str(
                    value[
                        "fixture_id"
                    ]
                ),
            )


            event_rates[
                key
            ] = value


        for child in (
            value.values()
        ):

            walk(
                child
            )


    elif isinstance(
        value,
        list,
    ):

        for child in value:

            walk(
                child
            )


walk(
    events
)


# ============================================================
# Upstream consistency
# ============================================================

event_missing = []
event_differences = []


for key, minute_row in (
    minute_map.items()
):

    event_row = (
        event_rates.get(
            key
        )
    )


    if event_row is None:

        event_missing.append(
            key
        )

        continue


    for field in (
        "expected_minutes",
        "p_appearance",
        "p_start",
    ):

        left = float(
            minute_row[
                field
            ]
        )

        right = float(
            event_row[
                field
            ]
        )


        if not math.isclose(
            left,
            right,
            rel_tol=0.0,
            abs_tol=1e-12,
        ):

            event_differences.append({
                "key": key,
                "field": field,
                "minutes": left,
                "event": right,
            })


    for field in (
        "minute_distribution",
        "starter_minutes_distribution",
        "bench_minutes_distribution",
    ):

        left = (
            minute_row[
                field
            ]
        )

        right = (
            event_row[
                field
            ]
        )


        if len(
            left
        ) != len(
            right
        ):

            event_differences.append({
                "key": key,
                "field": field,
                "reason": (
                    "different_length"
                ),
            })

            continue


        delta = max(
            (
                abs(
                    float(a)
                    - float(b)
                )
                for a, b
                in zip(
                    left,
                    right,
                )
            ),
            default=0.0,
        )


        if delta > 1e-12:

            event_differences.append({
                "key": key,
                "field": field,
                "max_delta": delta,
            })


upstream_pass = (
    not event_missing
    and not event_differences
    and len(
        event_rates
    )
    == len(
        minute_map
    )
)


# ============================================================
# Minutes semantic contract
# ============================================================

semantic_rows = []
semantic_failures = []


for key, row in (
    minute_map.items()
):

    dist = [
        float(
            value
        )
        for value
        in row[
            "minute_distribution"
        ]
    ]

    starter = [
        float(
            value
        )
        for value
        in row[
            "starter_minutes_distribution"
        ]
    ]

    bench = [
        float(
            value
        )
        for value
        in row[
            "bench_minutes_distribution"
        ]
    ]


    model_expected = float(
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
        p_app
        - p_start,
    )


    dist_mean = sum(
        minute
        * probability
        for minute, probability
        in enumerate(
            dist
        )
    )


    starter_mean = sum(
        minute
        * probability
        for minute, probability
        in enumerate(
            starter
        )
    )


    bench_mean = sum(
        minute
        * probability
        for minute, probability
        in enumerate(
            bench
        )
    )


    mixture_mean = (
        p_start
        * starter_mean
        + p_bench
        * bench_mean
    )


    p_app_from_dist = (
        1.0
        - dist[
            0
        ]
    )


    row_pass = all((
        math.isclose(
            model_expected,
            dist_mean,
            rel_tol=0.0,
            abs_tol=1e-9,
        ),
        math.isclose(
            p_app,
            p_app_from_dist,
            rel_tol=0.0,
            abs_tol=1e-9,
        ),
        math.isclose(
            model_expected,
            mixture_mean,
            rel_tol=0.0,
            abs_tol=1e-7,
        ),
    ))


    if not row_pass:

        semantic_failures.append({
            "player_id": key[
                0
            ],
            "fixture_id": key[
                1
            ],
            "expected": (
                model_expected
            ),
            "dist_mean": (
                dist_mean
            ),
            "mixture_mean": (
                mixture_mean
            ),
            "p_app": p_app,
            "p_app_from_dist": (
                p_app_from_dist
            ),
        })


    semantic_rows.append({
        "player_id": key[
            0
        ],
        "fixture_id": key[
            1
        ],
        "expected": (
            model_expected
        ),
        "p_app": p_app,
        "p_start": p_start,
        "starter_mean": (
            starter_mean
        ),
        "bench_mean": (
            bench_mean
        ),
    })


semantic_pass = (
    len(
        semantic_failures
    )
    == 0
)


# ============================================================
# ProjectionBuilder / simulation comparison
#
# Only fixture_count == 1 rows are used, so there is a direct
# player+fixture correspondence.
# ============================================================

comparison = []


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
            )
            != 1
            or len(
                fixture_ids
            )
            != 1
        ):

            continue


        fixture_id = str(
            fixture_ids[
                0
            ]
        )

        row = minute_map.get(
            (
                player_id,
                fixture_id,
            )
        )


        if row is None:

            continue


        model_expected = float(
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


        starter = [
            float(
                value
            )
            for value
            in row[
                "starter_minutes_distribution"
            ]
        ]

        bench = [
            float(
                value
            )
            for value
            in row[
                "bench_minutes_distribution"
            ]
        ]


        starter_mean = sum(
            index
            * probability
            for index, probability
            in enumerate(
                starter
            )
        )

        bench_mean = sum(
            index
            * probability
            for index, probability
            in enumerate(
                bench
            )
        )


        sim_expected = float(
            gw[
                "expected_minutes"
            ]
        )


        hypotheses = {
            #
            # Correct expectation if simulator respects
            # the already-unconditional minute distribution.
            #
            "direct": (
                model_expected
            ),

            #
            # Signature of applying appearance a second time
            # to an already unconditional distribution.
            #
            "double_appearance": (
                p_app
                * model_expected
            ),

            #
            # Signature of treating unconditional p_start
            # as conditional after an appearance hurdle.
            #
            "nested_unconditional_start": (
                p_app
                * (
                    p_start
                    * starter_mean
                    + (
                        1.0
                        - p_start
                    )
                    * bench_mean
                )
            ),

            #
            # Simple diagnostic only.
            #
            "double_start": (
                p_start
                * model_expected
            ),
        }


        comparison.append({
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
            "gameweek": int(
                gw[
                    "target_gameweek"
                ]
            ),
            "model_expected": (
                model_expected
            ),
            "simulation_expected": (
                sim_expected
            ),
            "p_appearance": (
                p_app
            ),
            "p_start": (
                p_start
            ),
            "starter_mean": (
                starter_mean
            ),
            "bench_mean": (
                bench_mean
            ),
            "hypotheses": (
                hypotheses
            ),
        })


if not comparison:

    raise RuntimeError(
        "No single-fixture projection "
        "comparisons available."
    )


#
# Ignore near-zero minute players for ratio summaries.
#
meaningful = [
    row
    for row in comparison
    if row[
        "model_expected"
    ] >= 20.0
]


def mae(
    hypothesis,
):

    values = [
        abs(
            row[
                "simulation_expected"
            ]
            - row[
                "hypotheses"
            ][
                hypothesis
            ]
        )
        for row in meaningful
    ]


    return mean(
        values
    )


maes = {
    name: mae(
        name
    )
    for name in (
        "direct",
        "double_appearance",
        "nested_unconditional_start",
        "double_start",
    )
}


ratios = [
    row[
        "simulation_expected"
    ]
    / row[
        "model_expected"
    ]
    for row in meaningful
]


mean_ratio = mean(
    ratios
)

median_ratio = median(
    ratios
)


best_hypothesis = min(
    maes,
    key=maes.get,
)


#
# Largest absolute discrepancies.
#
largest = sorted(
    meaningful,
    key=lambda row:
        abs(
            row[
                "simulation_expected"
            ]
            - row[
                "model_expected"
            ]
        ),
    reverse=True,
)[:20]


#
# Haaland trace
#
haaland = [
    row
    for row in comparison
    if row[
        "player_id"
    ]
    == HAALAND
]


# ============================================================
# Report
# ============================================================

report = {
    "run": str(
        RUN.relative_to(
            ROOT
        )
    ),
    "minutes_rows": len(
        minute_map
    ),
    "event_rate_rows": len(
        event_rates
    ),
    "upstream_exact_pass": (
        upstream_pass
    ),
    "event_missing_count": len(
        event_missing
    ),
    "event_difference_count": len(
        event_differences
    ),
    "minutes_semantic_pass": (
        semantic_pass
    ),
    "minutes_semantic_failure_count": len(
        semantic_failures
    ),
    "single_fixture_comparisons": len(
        comparison
    ),
    "meaningful_comparisons": len(
        meaningful
    ),
    "simulation_to_model_mean_ratio": (
        mean_ratio
    ),
    "simulation_to_model_median_ratio": (
        median_ratio
    ),
    "hypothesis_mae": maes,
    "best_hypothesis": (
        best_hypothesis
    ),
    "haaland": haaland,
    "largest_discrepancies": (
        largest
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
    "=== CAPTAIN-068B "
    "MINUTES SEMANTICS AUDIT ==="
)

print(
    "minutes -> event exact:",
    (
        "PASS"
        if upstream_pass
        else "FAIL"
    ),
)

print(
    "minutes distribution semantics:",
    (
        "PASS"
        if semantic_pass
        else "FAIL"
    ),
)

print(
    "single-fixture comparisons:",
    len(
        comparison
    ),
)

print(
    "meaningful >=20 min:",
    len(
        meaningful
    ),
)

print()

print(
    "simulation/model mean ratio:",
    f"{mean_ratio:.4f}",
)

print(
    "simulation/model median ratio:",
    f"{median_ratio:.4f}",
)

print()

print(
    "=== HYPOTHESIS MAE ==="
)

for key, value in sorted(
    maes.items(),
    key=lambda item:
        item[
            1
        ],
):

    print(
        f"{key:<30} "
        f"{value:.4f} min"
    )


print(
    "best fit:",
    best_hypothesis,
)


print()
print(
    "=== HAALAND ==="
)


for row in sorted(
    haaland,
    key=lambda item:
        item[
            "gameweek"
        ],
):

    print(
        "GW"
        f"{row['gameweek']}: "
        f"model={row['model_expected']:.3f} "
        f"sim={row['simulation_expected']:.3f} "
        f"delta="
        f"{row['simulation_expected'] - row['model_expected']:+.3f} "
        f"pApp={row['p_appearance']:.3f} "
        f"pStart={row['p_start']:.3f}"
    )


print()
print(
    "=== TOP 12 DISCREPANCIES ==="
)


for row in largest[
    :12
]:

    print(
        f"GW{row['gameweek']} "
        f"{row['name'][:22]:<22} "
        f"model={row['model_expected']:6.2f} "
        f"sim={row['simulation_expected']:6.2f} "
        f"delta="
        f"{row['simulation_expected'] - row['model_expected']:+7.2f}"
    )


print()
print(
    "=== FIXTURE SIMULATOR SOURCE TRACE ==="
)


shown = set()


for match in (
    interesting_source
):

    key = tuple(
        item[
            "line"
        ]
        for item in match[
            "context"
        ]
    )


    if key in shown:

        continue


    shown.add(
        key
    )


    for item in match[
        "context"
    ]:

        print(
            f"{item['line']:04d}: "
            f"{item['text']}"
        )


    print(
        "----"
    )


print()
print(
    "report:",
    REPORT.relative_to(
        ROOT
    ),
)

print(
    "simulator source:",
    SOURCE_OUT.relative_to(
        ROOT
    ),
)
