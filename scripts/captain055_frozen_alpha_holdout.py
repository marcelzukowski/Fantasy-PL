from pathlib import Path
import contextlib
import io
import math
import runpy


#
# Reuse CAPTAIN-054 definitions without
# printing its report again.
#
buffer = io.StringIO()

with contextlib.redirect_stdout(buffer):

    ns = runpy.run_path(
        "scripts/"
        "captain054_allocation_share_validation.py"
    )


ALPHAS = ns["ALPHAS"]
TRANSITIONS = ns["TRANSITIONS"]
data = ns["data"]

build_frozen_rates = ns[
    "build_frozen_rates"
]

aggregate_test = ns[
    "aggregate_test"
]

metrics = ns["metrics"]
fwd_only = ns["fwd_only"]
norm_name = ns["norm_name"]


TUNE_SOURCE, TUNE_TARGET = (
    TRANSITIONS[0]
)

TEST_SOURCE, TEST_TARGET = (
    TRANSITIONS[1]
)


#
# Select BOTH candidate alphas using
# ONLY the tuning transition.
#
tune_rates = build_frozen_rates(
    data[TUNE_SOURCE]
)


grid = []


for alpha in ALPHAS:

    rows = aggregate_test(
        data[TUNE_TARGET],
        tune_rates,
        alpha,
    )

    all_score = metrics(
        rows,
        "blend",
    )

    fwd_score = metrics(
        fwd_only(rows),
        "blend",
    )

    grid.append({
        "alpha": alpha,
        "all_ce": all_score["ce"],
        "fwd_ce": fwd_score["ce"],
    })


alpha_all = min(
    grid,
    key=lambda row:
        row["all_ce"],
)["alpha"]


alpha_fwd = min(
    grid,
    key=lambda row:
        row["fwd_ce"],
)["alpha"]


print(
    "=== CAPTAIN-055 "
    "FROZEN ALPHA HOLDOUT ==="
)

print(
    f"alpha_all={alpha_all:.2f}"
)

print(
    f"alpha_fwd={alpha_fwd:.2f}"
)

print(
    "Both selected ONLY on "
    "2023-24 -> 2024-25."
)


#
# Holdout rates.
#
test_rates = build_frozen_rates(
    data[TEST_SOURCE]
)


def simple_share_mae(
    rows,
    *,
    prefix,
    predicate,
):

    chosen = [
        row
        for row in rows
        if predicate(row)
    ]

    if not chosen:
        return math.nan

    weighted = 0.0
    weight = 0.0

    for row in chosen:

        team_weight = float(
            row["team_actual_xg"]
        )

        weighted += (
            abs(
                row["actual_share"]
                - row[
                    f"{prefix}_share"
                ]
            )
            * team_weight
        )

        weight += team_weight

    return (
        weighted / weight
        if weight
        else math.nan
    )


#
# Define a captaincy-relevant cohort
# using ONLY prior-season information:
# top quartile of frozen MID/FWD rates.
#
attacking_rates = sorted(
    [
        value["rate"]
        for value in test_rates.values()
        if value["position"]
        in {"MID", "FWD"}
        and value["minutes"] >= 900
    ]
)


if attacking_rates:

    q_index = int(
        0.75
        * (
            len(attacking_rates) - 1
        )
    )

    high_threat_threshold = (
        attacking_rates[q_index]
    )

else:

    high_threat_threshold = (
        math.inf
    )


print(
    f"high-threat threshold="
    f"{high_threat_threshold:.3f}"
)

print()


candidates = sorted(
    {
        0.0,
        alpha_fwd,
        alpha_all,
    }
)


for alpha in candidates:

    rows = aggregate_test(
        data[TEST_TARGET],
        test_rates,
        alpha,
    )


    all_score = metrics(
        rows,
        "blend",
    )

    fwd_score = metrics(
        fwd_only(rows),
        "blend",
    )


    prior_all = metrics(
        rows,
        "prior",
    )

    prior_fwd = metrics(
        fwd_only(rows),
        "prior",
    )


    def high_threat(row):

        source = test_rates.get(
            row["player_key"]
        )

        if source is None:
            return False

        return (
            source["position"]
            in {"MID", "FWD"}
            and source["minutes"]
            >= 900
            and source["rate"]
            >= high_threat_threshold
        )


    high_prior = (
        simple_share_mae(
            rows,
            prefix="prior",
            predicate=high_threat,
        )
    )

    high_blend = (
        simple_share_mae(
            rows,
            prefix="blend",
            predicate=high_threat,
        )
    )


    print(
        "-" * 68
    )

    print(
        f"alpha={alpha:.2f}"
    )

    print(
        "ALL CE       "
        f"prior={prior_all['ce']:.6f} "
        f"blend={all_score['ce']:.6f} "
        f"delta="
        f"{all_score['ce'] - prior_all['ce']:+.6f}"
    )

    print(
        "ALL shareMAE "
        f"prior={prior_all['mae']:.6f} "
        f"blend={all_score['mae']:.6f} "
        f"delta="
        f"{all_score['mae'] - prior_all['mae']:+.6f}"
    )

    print(
        "FWD CE       "
        f"prior={prior_fwd['ce']:.6f} "
        f"blend={fwd_score['ce']:.6f} "
        f"delta="
        f"{fwd_score['ce'] - prior_fwd['ce']:+.6f}"
    )

    print(
        "HIGH threat  "
        f"priorMAE={high_prior:.6f} "
        f"blendMAE={high_blend:.6f} "
        f"delta="
        f"{high_blend - high_prior:+.6f}"
    )


    haaland = [
        row
        for row in rows
        if "haaland"
        in norm_name(
            row["name"]
        )
    ]


    for row in haaland:

        print(
            "Haaland       "
            f"actual={row['actual_share']:.3f} "
            f"prior={row['prior_share']:.3f} "
            f"blend={row['blend_share']:.3f}"
        )


print()
print(
    "No production files changed."
)
