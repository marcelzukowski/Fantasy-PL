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
    / "pstart_reconciliation_candidates.json"
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
    / acceptance["default_run"]
)

events = load(
    RUN
    / "event_projections.json"
)

players = load(
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
        value = row.get(key)

        if value:
            return str(value)

    return str(
        row.get(
            "player_id",
            "",
        )
    )


names = {
    str(row["player_id"]):
        display_name(row)
    for row in players
}


haaland_ids = [
    player_id
    for player_id, name
    in names.items()
    if "haaland" in name.lower()
]


if len(haaland_ids) != 1:
    raise RuntimeError(
        "Expected exactly one Haaland."
    )


HAALAND = haaland_ids[0]


fixture_info = {
    str(row["fixture_id"]): row
    for row in fixtures
}


EPS = 1e-12


# ============================================================
# Generic root solver
# ============================================================

def bisect_root(
    fn,
    lo=-40.0,
    hi=40.0,
    iterations=120,
):

    flo = fn(lo)
    fhi = fn(hi)

    if flo > 0 or fhi < 0:
        raise RuntimeError(
            "Bisection bracket does not "
            "contain a root."
        )

    for _ in range(iterations):

        mid = (
            lo + hi
        ) / 2.0

        value = fn(mid)

        if value < 0:
            lo = mid
        else:
            hi = mid

    return (
        lo + hi
    ) / 2.0


def validate_group(
    rows,
    target,
):

    if not rows:
        raise RuntimeError(
            "Empty positional group."
        )

    if target < 0:
        raise RuntimeError(
            "Negative target."
        )

    if target > len(rows) + 1e-9:
        raise RuntimeError(
            "Target exceeds number "
            "of available players."
        )


# ============================================================
# Candidate A:
#
# unconditional logit shift
#
# logit(pStart') =
#     logit(raw pStart) + lambda
#
# This is now based on unconditional pStart,
# matching its calibration semantics.
# ============================================================

def reconcile_logit(
    rows,
    target,
):

    validate_group(
        rows,
        target,
    )


    def values(shift):

        output = {}

        for row in rows:

            player_id = str(
                row["player_id"]
            )

            raw = min(
                1.0 - EPS,
                max(
                    EPS,
                    float(
                        row["p_start"]
                    ),
                ),
            )

            logit = math.log(
                raw
                / (
                    1.0 - raw
                )
            )

            value = (
                1.0
                / (
                    1.0
                    + math.exp(
                        -(
                            logit
                            + shift
                        )
                    )
                )
            )

            output[player_id] = value

        return output


    shift = bisect_root(
        lambda value:
            sum(
                values(value).values()
            )
            - target
    )

    return values(shift)


# ============================================================
# Candidate B:
#
# capped multiplicative scale
#
# pStart' =
#     min(1, scale * raw pStart)
# ============================================================

def reconcile_scale(
    rows,
    target,
):

    validate_group(
        rows,
        target,
    )


    def values(log_scale):

        scale = math.exp(
            log_scale
        )

        return {
            str(row["player_id"]):
                min(
                    1.0,
                    scale
                    * max(
                        EPS,
                        float(
                            row["p_start"]
                        ),
                    ),
                )
            for row in rows
        }


    shift = bisect_root(
        lambda value:
            sum(
                values(value).values()
            )
            - target
    )

    return values(shift)


# ============================================================
# Candidate C:
#
# Euclidean capped-simplex projection
#
# pStart' =
#     clip(raw pStart + lambda, 0, 1)
#
# This minimizes squared probability adjustment
# under the exact cardinality constraint.
# ============================================================

def reconcile_l2(
    rows,
    target,
):

    validate_group(
        rows,
        target,
    )


    def values(shift):

        return {
            str(row["player_id"]):
                min(
                    1.0,
                    max(
                        0.0,
                        float(
                            row["p_start"]
                        )
                        + shift,
                    ),
                )
            for row in rows
        }


    shift = bisect_root(
        lambda value:
            sum(
                values(value).values()
            )
            - target
    )

    return values(shift)


METHODS = {
    "logit_shift":
        reconcile_logit,
    "capped_scale":
        reconcile_scale,
    "capped_l2":
        reconcile_l2,
}


# ============================================================
# Coherent appearance:
#
# A starter necessarily appears.
#
# We keep calibrated pAppearance unchanged whenever possible:
#
# pAppearance' =
#     max(raw pAppearance, pStart')
#
# This is the minimum per-player change required to restore
# the logical relation:
#
#       P(start) <= P(appearance)
# ============================================================

team_results = []

adjustments = {
    name: []
    for name in METHODS
}

haaland_rows = []


for fixture in events:

    fixture_id = str(
        fixture["fixture_id"]
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

        rates = [
            player["rates"]
            for player
            in fixture[side]["players"]
        ]


        gks = [
            row
            for row in rates
            if str(
                row.get(
                    "position",
                    "",
                )
            ).upper()
            == "GK"
        ]


        outfield = [
            row
            for row in rates
            if str(
                row.get(
                    "position",
                    "",
                )
            ).upper()
            != "GK"
        ]


        if len(gks) < 1:
            raise RuntimeError(
                f"{fixture_id} {side}: "
                "no goalkeeper."
            )


        if len(outfield) < 10:
            raise RuntimeError(
                f"{fixture_id} {side}: "
                "fewer than 10 outfield "
                "players."
            )


        raw_start_sum = sum(
            float(
                row["p_start"]
            )
            for row in rates
        )

        raw_gk_start_sum = sum(
            float(
                row["p_start"]
            )
            for row in gks
        )

        raw_gk_app_sum = sum(
            float(
                row["p_appearance"]
            )
            for row in gks
        )


        method_summary = {}


        for method_name, method in (
            METHODS.items()
        ):

            corrected_start = {}

            corrected_start.update(
                method(
                    gks,
                    1.0,
                )
            )

            corrected_start.update(
                method(
                    outfield,
                    10.0,
                )
            )


            corrected_appearance = {
                str(row["player_id"]):
                    max(
                        float(
                            row["p_appearance"]
                        ),
                        corrected_start[
                            str(
                                row[
                                    "player_id"
                                ]
                            )
                        ],
                    )
                for row in rates
            }


            start_sum = sum(
                corrected_start.values()
            )

            gk_start_sum = sum(
                corrected_start[
                    str(row["player_id"])
                ]
                for row in gks
            )

            outfield_start_sum = sum(
                corrected_start[
                    str(row["player_id"])
                ]
                for row in outfield
            )


            logical_violations = []

            appearance_inflation = []


            for row in rates:

                player_id = str(
                    row["player_id"]
                )

                raw_start = float(
                    row["p_start"]
                )

                raw_app = float(
                    row["p_appearance"]
                )

                new_start = float(
                    corrected_start[
                        player_id
                    ]
                )

                new_app = float(
                    corrected_appearance[
                        player_id
                    ]
                )


                if (
                    new_start < -1e-10
                    or new_start > 1.0 + 1e-10
                    or new_app < new_start - 1e-10
                    or new_app > 1.0 + 1e-10
                ):
                    logical_violations.append(
                        player_id
                    )


                app_delta = (
                    new_app
                    - raw_app
                )

                appearance_inflation.append(
                    app_delta
                )


                adjustments[
                    method_name
                ].append({
                    "fixture_id":
                        fixture_id,
                    "gameweek":
                        gameweek,
                    "side":
                        side,
                    "player_id":
                        player_id,
                    "name":
                        names.get(
                            player_id,
                            player_id,
                        ),
                    "position":
                        row.get(
                            "position"
                        ),
                    "raw_p_start":
                        raw_start,
                    "adjusted_p_start":
                        new_start,
                    "p_start_delta":
                        new_start
                        - raw_start,
                    "raw_p_appearance":
                        raw_app,
                    "adjusted_p_appearance":
                        new_app,
                    "p_appearance_delta":
                        app_delta,
                })


                if player_id == HAALAND:

                    haaland_rows.append({
                        "method":
                            method_name,
                        "gameweek":
                            gameweek,
                        "fixture_id":
                            fixture_id,
                        "raw_start":
                            raw_start,
                        "adjusted_start":
                            new_start,
                        "raw_appearance":
                            raw_app,
                        "adjusted_appearance":
                            new_app,
                    })


            method_summary[
                method_name
            ] = {
                "start_sum":
                    start_sum,
                "gk_start_sum":
                    gk_start_sum,
                "outfield_start_sum":
                    outfield_start_sum,
                "appearance_inflation_sum":
                    sum(
                        appearance_inflation
                    ),
                "appearance_inflation_count":
                    sum(
                        delta > 1e-12
                        for delta
                        in appearance_inflation
                    ),
                "constraint_pass":
                    all((
                        math.isclose(
                            start_sum,
                            11.0,
                            abs_tol=1e-8,
                        ),
                        math.isclose(
                            gk_start_sum,
                            1.0,
                            abs_tol=1e-8,
                        ),
                        math.isclose(
                            outfield_start_sum,
                            10.0,
                            abs_tol=1e-8,
                        ),
                        not logical_violations,
                    )),
            }


        team_results.append({
            "fixture_id":
                fixture_id,
            "gameweek":
                gameweek,
            "side":
                side,
            "raw_start_sum":
                raw_start_sum,
            "raw_gk_start_sum":
                raw_gk_start_sum,
            "raw_gk_appearance_sum":
                raw_gk_app_sum,
            "methods":
                method_summary,
        })


# ============================================================
# Aggregate diagnostics
# ============================================================

method_metrics = {}


for method_name, rows in (
    adjustments.items()
):

    start_abs = [
        abs(
            row[
                "p_start_delta"
            ]
        )
        for row in rows
    ]

    start_sq = [
        row[
            "p_start_delta"
        ]
        ** 2
        for row in rows
    ]

    app_delta = [
        row[
            "p_appearance_delta"
        ]
        for row in rows
    ]

    app_positive = [
        value
        for value in app_delta
        if value > 1e-12
    ]


    high = [
        row
        for row in rows
        if row[
            "raw_p_start"
        ]
        >= 0.75
    ]


    low = [
        row
        for row in rows
        if row[
            "raw_p_start"
        ]
        <= 0.25
    ]


    method_metrics[
        method_name
    ] = {
        "mean_abs_start_adjustment":
            mean(start_abs),
        "median_abs_start_adjustment":
            median(start_abs),
        "rmse_start_adjustment":
            math.sqrt(
                mean(start_sq)
            ),
        "max_abs_start_adjustment":
            max(start_abs),

        "appearance_inflation_rows":
            len(app_positive),
        "appearance_inflation_rate":
            len(app_positive)
            / len(rows),

        "mean_appearance_inflation_all":
            mean(app_delta),

        "mean_appearance_inflation_when_changed":
            (
                mean(app_positive)
                if app_positive
                else 0.0
            ),

        "max_appearance_inflation":
            max(
                app_delta
            ),

        "mean_delta_high_pstart":
            (
                mean(
                    row[
                        "p_start_delta"
                    ]
                    for row in high
                )
                if high
                else None
            ),

        "mean_delta_low_pstart":
            (
                mean(
                    row[
                        "p_start_delta"
                    ]
                    for row in low
                )
                if low
                else None
            ),

        "constraint_pass":
            all(
                team[
                    "methods"
                ][
                    method_name
                ][
                    "constraint_pass"
                ]
                for team
                in team_results
            ),
    }


largest = {}


for method_name, rows in (
    adjustments.items()
):

    largest[
        method_name
    ] = sorted(
        rows,
        key=lambda row:
            abs(
                row[
                    "p_start_delta"
            ]
        ),
        reverse=True,
    )[:20]


gk_capacity_lt_1 = [
    row
    for row in team_results
    if row[
        "raw_gk_appearance_sum"
    ]
    < 1.0
]


gate = all(
    metrics[
        "constraint_pass"
    ]
    for metrics
    in method_metrics.values()
)


report = {
    "status":
        "CAPTAIN_068E_R_"
        "COHERENT_LINEUP_CANDIDATES",

    "production_modified":
        False,

    "team_fixture_rows":
        len(
            team_results
        ),

    "raw_gk_appearance_capacity_lt_1":
        len(
            gk_capacity_lt_1
        ),

    "methods":
        method_metrics,

    "haaland":
        sorted(
            haaland_rows,
            key=lambda row: (
                row[
                    "gameweek"
                ],
                row[
                    "method"
                ],
            ),
        ),

    "largest_start_adjustments":
        largest,

    "semantic_contract": {
        "starter_count":
            11,
        "goalkeeper_starters":
            1,
        "outfield_starters":
            10,
        "starter_implies_appearance":
            True,
        "appearance_adjustment":
            "max(raw_p_appearance, "
            "adjusted_p_start)",
    },

    "selection_policy": (
        "NO WINNER FROM 2026/27. "
        "Candidate selection requires "
        "historical known-before-target "
        "start/appearance validation."
    ),

    "gate":
        gate,
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
    "=== CAPTAIN-068E-R "
    "COHERENT LINEUP CANDIDATES ==="
)

print(
    "team-fixtures:",
    len(
        team_results
    ),
)

print(
    "raw GK appearance capacity <1:",
    len(
        gk_capacity_lt_1
    ),
    "/",
    len(
        team_results
    ),
)


print()
print(
    "=== CANDIDATE ADJUSTMENTS ==="
)


for method_name, metrics in (
    method_metrics.items()
):

    print(
        f"{method_name:<18} "
        f"startMAE="
        f"{metrics['mean_abs_start_adjustment']:.4f} "
        f"startRMSE="
        f"{metrics['rmse_start_adjustment']:.4f} "
        f"startMax="
        f"{metrics['max_abs_start_adjustment']:.4f} "
        f"appRaised="
        f"{metrics['appearance_inflation_rate']:.3f} "
        f"appMax="
        f"{metrics['max_appearance_inflation']:.4f} "
        f"constraint="
        f"{'PASS' if metrics['constraint_pass'] else 'FAIL'}"
    )


print()
print(
    "=== HAALAND ==="
)


for gameweek in sorted({
    row[
        "gameweek"
    ]
    for row in haaland_rows
}):

    selected = [
        row
        for row in haaland_rows
        if row[
            "gameweek"
        ]
        == gameweek
    ]


    print(
        f"GW{gameweek}:",
        " | ".join(
            (
                f"{row['method']} "
                f"S "
                f"{row['raw_start']:.3f}"
                f"->{row['adjusted_start']:.3f} "
                f"A "
                f"{row['raw_appearance']:.3f}"
                f"->{row['adjusted_appearance']:.3f}"
            )
            for row
            in selected
        ),
    )


print()
print(
    "=== TOP 5 START CHANGES / METHOD ==="
)


for method_name in METHODS:

    print()
    print(
        method_name
    )

    for row in (
        largest[
            method_name
        ][
            :5
        ]
    ):

        print(
            f"  "
            f"{row['name'][:22]:<22} "
            f"{str(row['position']):<3} "
            f"S "
            f"{row['raw_p_start']:.3f}"
            f" -> "
            f"{row['adjusted_p_start']:.3f} "
            f"delta="
            f"{row['p_start_delta']:+.3f} "
            f"A "
            f"{row['raw_p_appearance']:.3f}"
            f" -> "
            f"{row['adjusted_p_appearance']:.3f}"
        )


print()
print(
    "CURRENT DATA WINNER:",
    "NONE",
)

print(
    "CANDIDATE GATE:",
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
    "report:",
    REPORT.relative_to(
        ROOT
    ),
)


if not gate:
    raise RuntimeError(
        "CAPTAIN-068E-R candidate "
        "gate failed."
    )
