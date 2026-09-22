from __future__ import annotations

from collections import defaultdict
from contextlib import redirect_stdout
from pathlib import Path
import io
import json
import math
import runpy
import statistics
import unicodedata
import re

import numpy as np
import pandas as pd

from fpl_engine.models.player_talent.model import (
    CORE_PRIORS,
)


ROOT = Path(".").resolve()

CAPTAIN054 = (
    ROOT
    / "scripts"
    / "captain054_allocation_share_validation.py"
)

OUT = (
    ROOT
    / "scratch"
    / "decision"
    / "captain065_deployable_exposure_holdout.json"
)

ALPHA = 0.55
PRIOR_MINUTES = 600.0

TRANSITIONS = (
    (
        "2023-24",
        "2024-25",
    ),
    (
        "2024-25",
        "2025-26",
    ),
)


def norm_name(
    value,
):

    text = unicodedata.normalize(
        "NFKD",
        str(
            value
            or ""
        ),
    )

    text = "".join(
        char
        for char in text
        if not unicodedata.combining(
            char
        )
    )

    return re.sub(
        r"[^a-z0-9]+",
        "",
        text.casefold(),
    )


def canonical_position(
    value,
):

    value = str(
        value
        or ""
    ).upper()

    return {
        "GKP": "GK",
        "GOALKEEPER": "GK",
        "DEFENDER": "DEF",
        "MIDFIELDER": "MID",
        "FORWARD": "FWD",
    }.get(
        value,
        value,
    )


#
# ============================================================
# 1. Reuse only the already-audited Vaastav loading from
#    CAPTAIN-054.
#
# Suppress its old report; no production code is touched.
# ============================================================
#

if not CAPTAIN054.exists():

    raise RuntimeError(
        "CAPTAIN-054 script missing."
    )


capture = io.StringIO()

with redirect_stdout(
    capture
):

    ns = runpy.run_path(
        str(
            CAPTAIN054
        ),
        run_name=(
            "captain054_for_"
            "captain065"
        ),
    )


data = ns.get(
    "data"
)


if not isinstance(
    data,
    dict,
):

    raise RuntimeError(
        "CAPTAIN-054 did not expose "
        "the expected data mapping."
    )


for season in (
    "2023-24",
    "2024-25",
    "2025-26",
):

    if season not in data:

        raise RuntimeError(
            f"CAPTAIN-054 data missing "
            f"{season}"
        )

    if not isinstance(
        data[
            season
        ],
        pd.DataFrame,
    ):

        raise RuntimeError(
            f"{season} data is not "
            "a DataFrame."
        )


#
# ============================================================
# 2. Normalize source frames
# ============================================================
#

REQUIRED = {
    "name",
    "team",
    "position",
    "minutes",
    "expected_goals",
    "fixture",
}


def prepare_frame(
    frame,
    season,
):

    frame = frame.copy()

    missing = (
        REQUIRED
        - set(
            frame.columns
        )
    )

    if missing:

        raise RuntimeError(
            f"{season} missing columns: "
            + ", ".join(
                sorted(
                    missing
                )
            )
        )


    frame[
        "player_key_internal"
    ] = frame[
        "name"
    ].map(
        norm_name
    )

    frame[
        "position_internal"
    ] = frame[
        "position"
    ].map(
        canonical_position
    )

    frame[
        "minutes_internal"
    ] = pd.to_numeric(
        frame[
            "minutes"
        ],
        errors="coerce",
    ).fillna(
        0.0
    )

    frame[
        "xg_internal"
    ] = pd.to_numeric(
        frame[
            "expected_goals"
        ],
        errors="coerce",
    ).fillna(
        0.0
    )

    frame[
        "fixture_internal"
    ] = pd.to_numeric(
        frame[
            "fixture"
        ],
        errors="coerce",
    )


    #
    # Prefer true kickoff ordering.
    #
    kickoff_column = None

    for candidate in (
        "kickoff_time",
        "kickoff",
    ):

        if candidate in frame.columns:

            kickoff_column = (
                candidate
            )

            break


    if kickoff_column is not None:

        frame[
            "kickoff_internal"
        ] = pd.to_datetime(
            frame[
                kickoff_column
            ],
            utc=True,
            errors="coerce",
        )

    else:

        frame[
            "kickoff_internal"
        ] = pd.NaT


    #
    # GW is only a deterministic fallback
    # if kickoff_time is unavailable.
    #
    if "GW" in frame.columns:

        frame[
            "gw_internal"
        ] = pd.to_numeric(
            frame[
                "GW"
            ],
            errors="coerce",
        )

    elif "gameweek" in frame.columns:

        frame[
            "gw_internal"
        ] = pd.to_numeric(
            frame[
                "gameweek"
            ],
            errors="coerce",
        )

    else:

        frame[
            "gw_internal"
        ] = np.nan


    if (
        frame[
            "kickoff_internal"
        ].notna().any()
    ):

        frame[
            "order_primary_internal"
        ] = (
            frame[
                "kickoff_internal"
            ]
            .astype(
                "int64",
                errors="ignore",
            )
        )

    elif (
        frame[
            "gw_internal"
        ].notna().any()
    ):

        frame[
            "order_primary_internal"
        ] = frame[
            "gw_internal"
        ]

    else:

        frame[
            "order_primary_internal"
        ] = frame[
            "fixture_internal"
        ]


    frame[
        "original_index_internal"
    ] = np.arange(
        len(
            frame
        )
    )


    return frame


prepared = {
    season:
        prepare_frame(
            data[
                season
            ],
            season,
        )
    for season in (
        "2023-24",
        "2024-25",
        "2025-26",
    )
}


#
# ============================================================
# 3. Frozen previous-season total-xG talent rate
# ============================================================
#

def position_prior(
    position,
):

    return float(
        CORE_PRIORS.get(
            position,
            CORE_PRIORS[
                "MID"
            ],
        )[
            "npxg"
        ]
    )


def frozen_rates(
    train,
):

    rates = {}


    grouped = train.groupby(
        [
            "player_key_internal",
            "position_internal",
        ],
        sort=False,
    )


    for (
        player_key,
        position,
    ), group in grouped:

        minutes = float(
            group[
                "minutes_internal"
            ].sum()
        )

        total_xg = float(
            group[
                "xg_internal"
            ].sum()
        )

        prior = position_prior(
            position
        )


        if minutes > 0.0:

            frozen = (
                total_xg
                * 90.0
                + prior
                * PRIOR_MINUTES
            ) / (
                minutes
                + PRIOR_MINUTES
            )

        else:

            frozen = prior


        rates[
            (
                player_key,
                position,
            )
        ] = {
            "rate": frozen,
            "minutes": minutes,
            "total_xg": total_xg,
            "position": position,
        }


    return rates


#
# ============================================================
# 4. Leakage-safe target exposure
#
# For every TARGET fixture:
#
# prediction uses ONLY previously observed minutes.
#
# train season is allowed because it is fully historical.
# target-season actual minutes are appended only AFTER that
# row's exposure has been predicted.
#
# No target-fixture minutes enter their own prediction.
# ============================================================
#

def position_fallbacks(
    train,
):

    result = {}


    for position, group in (
        train.groupby(
            "position_internal"
        )
    ):

        values = [
            float(
                value
            )
            for value in group[
                "minutes_internal"
            ]
            if math.isfinite(
                float(
                    value
                )
            )
        ]


        if values:

            result[
                position
            ] = float(
                statistics.mean(
                    values
                )
            )


    return result


def seed_history(
    train,
):

    history = defaultdict(
        list
    )


    ordered = train.sort_values(
        [
            "order_primary_internal",
            "fixture_internal",
            "original_index_internal",
        ],
        kind="stable",
    )


    for row in ordered.itertuples():

        key = (
            row.player_key_internal,
            row.position_internal,
        )

        history[
            key
        ].append(
            float(
                row.minutes_internal
            )
        )


    return history


def deployable_exposure(
    train,
    target,
    *,
    lookback,
):

    if lookback not in {
        1,
        5,
    }:

        raise ValueError(
            "lookback must be 1 or 5"
        )


    history = seed_history(
        train
    )

    fallbacks = position_fallbacks(
        train
    )

    exposure = {}


    ordered = target.sort_values(
        [
            "order_primary_internal",
            "fixture_internal",
            "original_index_internal",
        ],
        kind="stable",
    )


    fallback_rows = 0
    history_rows = 0


    for row in ordered.itertuples():

        key = (
            row.player_key_internal,
            row.position_internal,
        )

        prior = history.get(
            key,
            [],
        )


        if prior:

            values = prior[
                -lookback:
            ]

            predicted = float(
                statistics.mean(
                    values
                )
            )

            history_rows += 1

        else:

            predicted = float(
                fallbacks.get(
                    row.position_internal,
                    60.0,
                )
            )

            fallback_rows += 1


        predicted = max(
            0.0,
            min(
                90.0,
                predicted,
            ),
        )


        exposure[
            int(
                row.original_index_internal
            )
        ] = predicted


        #
        # Critical ordering:
        # actual target minutes become history
        # only AFTER prediction for this row.
        #
        history[
            key
        ].append(
            float(
                row.minutes_internal
            )
        )


    return (
        exposure,
        {
            "rows": len(
                target
            ),
            "history_rows": (
                history_rows
            ),
            "fallback_rows": (
                fallback_rows
            ),
            "fallback_rate": (
                fallback_rows
                / len(
                    target
                )
                if len(
                    target
                )
                else 0.0
            ),
        },
    )


#
# ============================================================
# 5. Team/player allocation rows
# ============================================================
#

def allocation_rows(
    train,
    target,
    *,
    exposure_mode,
):

    rates = frozen_rates(
        train
    )


    if exposure_mode == "oracle":

        exposure = {
            int(
                row.original_index_internal
            ):
            float(
                row.minutes_internal
            )
            for row in (
                target.itertuples()
            )
        }

        exposure_audit = {
            "rows": len(
                target
            ),
            "history_rows": 0,
            "fallback_rows": 0,
            "fallback_rate": 0.0,
            "oracle": True,
        }


    elif exposure_mode == "prev5":

        (
            exposure,
            exposure_audit,
        ) = deployable_exposure(
            train,
            target,
            lookback=5,
        )

        exposure_audit[
            "oracle"
        ] = False


    elif exposure_mode == "prev1":

        (
            exposure,
            exposure_audit,
        ) = deployable_exposure(
            train,
            target,
            lookback=1,
        )

        exposure_audit[
            "oracle"
        ] = False


    else:

        raise ValueError(
            exposure_mode
        )


    target = target.copy()

    target[
        "predicted_exposure_internal"
    ] = target[
        "original_index_internal"
    ].map(
        exposure
    )


    player_groups = []


    for (
        team,
        player_key,
        position,
    ), group in target.groupby(
        [
            "team",
            "player_key_internal",
            "position_internal",
        ],
        sort=False,
    ):

        actual_xg = float(
            group[
                "xg_internal"
            ].sum()
        )

        predicted_minutes = float(
            group[
                "predicted_exposure_internal"
            ].sum()
        )

        actual_minutes = float(
            group[
                "minutes_internal"
            ].sum()
        )

        display_name = str(
            group[
                "name"
            ].iloc[0]
        )


        prior = position_prior(
            position
        )


        frozen = rates.get(
            (
                player_key,
                position,
            )
        )


        if frozen is None:

            frozen_rate = prior
            source_minutes = 0.0
            used_history = False

        else:

            frozen_rate = float(
                frozen[
                    "rate"
                ]
            )

            source_minutes = float(
                frozen[
                    "minutes"
                ]
            )

            used_history = True


        blend_rate = (
            prior
            + ALPHA
            * (
                frozen_rate
                - prior
            )
        )


        player_groups.append({
            "team": str(
                team
            ),
            "player_key": (
                player_key
            ),
            "name": (
                display_name
            ),
            "position": (
                position
            ),
            "actual_xg": (
                actual_xg
            ),
            "actual_minutes": (
                actual_minutes
            ),
            "predicted_minutes": (
                predicted_minutes
            ),
            "prior_rate": (
                prior
            ),
            "frozen_rate": (
                frozen_rate
            ),
            "blend_rate": (
                blend_rate
            ),
            "source_minutes": (
                source_minutes
            ),
            "used_frozen_history": (
                used_history
            ),
            "prior_weight": (
                prior
                * predicted_minutes
            ),
            "blend_weight": (
                blend_rate
                * predicted_minutes
            ),
        })


    rows = []


    by_team = defaultdict(
        list
    )


    for row in player_groups:

        by_team[
            row[
                "team"
            ]
        ].append(
            row
        )


    for team, players in (
        by_team.items()
    ):

        team_xg = sum(
            row[
                "actual_xg"
            ]
            for row in players
        )

        prior_total = sum(
            row[
                "prior_weight"
            ]
            for row in players
        )

        blend_total = sum(
            row[
                "blend_weight"
            ]
            for row in players
        )


        if (
            team_xg <= 0.0
            or prior_total <= 0.0
            or blend_total <= 0.0
        ):

            continue


        for row in players:

            result = dict(
                row
            )

            result[
                "team_actual_xg"
            ] = team_xg

            result[
                "actual_share"
            ] = (
                row[
                    "actual_xg"
                ]
                / team_xg
            )

            result[
                "prior_share"
            ] = (
                row[
                    "prior_weight"
                ]
                / prior_total
            )

            result[
                "blend_share"
            ] = (
                row[
                    "blend_weight"
                ]
                / blend_total
            )

            rows.append(
                result
            )


    return (
        rows,
        exposure_audit,
        rates,
    )


#
# ============================================================
# 6. Metrics
# ============================================================
#

EPS = 1e-15


def allocation_metrics(
    rows,
):

    teams = defaultdict(
        list
    )


    for row in rows:

        teams[
            row[
                "team"
            ]
        ].append(
            row
        )


    prior_ce_num = 0.0
    blend_ce_num = 0.0
    ce_den = 0.0

    prior_abs = []
    blend_abs = []

    prior_abs_weighted = 0.0
    blend_abs_weighted = 0.0
    weighted_den = 0.0


    for team_rows in (
        teams.values()
    ):

        team_xg = float(
            team_rows[0][
                "team_actual_xg"
            ]
        )


        prior_ce = -sum(
            row[
                "actual_share"
            ]
            * math.log(
                max(
                    EPS,
                    row[
                        "prior_share"
                    ],
                )
            )
            for row in team_rows
            if row[
                "actual_share"
            ] > 0.0
        )


        blend_ce = -sum(
            row[
                "actual_share"
            ]
            * math.log(
                max(
                    EPS,
                    row[
                        "blend_share"
                    ],
                )
            )
            for row in team_rows
            if row[
                "actual_share"
            ] > 0.0
        )


        prior_ce_num += (
            team_xg
            * prior_ce
        )

        blend_ce_num += (
            team_xg
            * blend_ce
        )

        ce_den += team_xg


        for row in team_rows:

            prior_error = abs(
                row[
                    "prior_share"
                ]
                - row[
                    "actual_share"
                ]
            )

            blend_error = abs(
                row[
                    "blend_share"
                ]
                - row[
                    "actual_share"
                ]
            )

            prior_abs.append(
                prior_error
            )

            blend_abs.append(
                blend_error
            )

            prior_abs_weighted += (
                team_xg
                * prior_error
            )

            blend_abs_weighted += (
                team_xg
                * blend_error
            )

            weighted_den += (
                team_xg
            )


    return {
        "teams": len(
            teams
        ),
        "players": len(
            rows
        ),
        "prior_ce": (
            prior_ce_num
            / ce_den
        ),
        "blend_ce": (
            blend_ce_num
            / ce_den
        ),
        "ce_delta": (
            blend_ce_num
            / ce_den
            - prior_ce_num
            / ce_den
        ),
        "prior_share_mae": float(
            statistics.mean(
                prior_abs
            )
        ),
        "blend_share_mae": float(
            statistics.mean(
                blend_abs
            )
        ),
        "share_mae_delta": float(
            statistics.mean(
                blend_abs
            )
            - statistics.mean(
                prior_abs
            )
        ),
        "prior_xg_weighted_mae": (
            prior_abs_weighted
            / weighted_den
        ),
        "blend_xg_weighted_mae": (
            blend_abs_weighted
            / weighted_den
        ),
    }


def fwd_cross_entropy(
    rows,
):

    teams = defaultdict(
        list
    )


    for row in rows:

        if row[
            "position"
        ] == "FWD":

            teams[
                row[
                    "team"
                ]
            ].append(
                row
            )


    prior_num = 0.0
    blend_num = 0.0
    denominator = 0.0
    used_teams = 0


    for team_rows in (
        teams.values()
    ):

        if len(
            team_rows
        ) < 2:

            continue


        actual_total = sum(
            row[
                "actual_xg"
            ]
            for row in team_rows
        )

        prior_total = sum(
            row[
                "prior_weight"
            ]
            for row in team_rows
        )

        blend_total = sum(
            row[
                "blend_weight"
            ]
            for row in team_rows
        )


        if (
            actual_total <= 0.0
            or prior_total <= 0.0
            or blend_total <= 0.0
        ):

            continue


        prior_ce = 0.0
        blend_ce = 0.0


        for row in team_rows:

            actual = (
                row[
                    "actual_xg"
                ]
                / actual_total
            )

            if actual <= 0.0:
                continue


            prior = (
                row[
                    "prior_weight"
                ]
                / prior_total
            )

            blend = (
                row[
                    "blend_weight"
                ]
                / blend_total
            )


            prior_ce -= (
                actual
                * math.log(
                    max(
                        EPS,
                        prior,
                    )
                )
            )

            blend_ce -= (
                actual
                * math.log(
                    max(
                        EPS,
                        blend,
                    )
                )
            )


        prior_num += (
            actual_total
            * prior_ce
        )

        blend_num += (
            actual_total
            * blend_ce
        )

        denominator += (
            actual_total
        )

        used_teams += 1


    return {
        "teams": used_teams,
        "prior_ce": (
            prior_num
            / denominator
            if denominator
            else None
        ),
        "blend_ce": (
            blend_num
            / denominator
            if denominator
            else None
        ),
        "delta": (
            (
                blend_num
                - prior_num
            )
            / denominator
            if denominator
            else None
        ),
    }


def high_threat_metrics(
    rows,
    rates,
):

    candidates = [
        value[
            "rate"
        ]
        for (
            player_key,
            position,
        ), value in rates.items()
        if (
            position
            in {
                "MID",
                "FWD",
            }
            and value[
                "minutes"
            ] >= 900.0
        )
    ]


    if not candidates:

        return None


    threshold = float(
        np.quantile(
            candidates,
            0.75,
        )
    )


    selected = []


    for row in rows:

        frozen = rates.get(
            (
                row[
                    "player_key"
                ],
                row[
                    "position"
                ],
            )
        )


        if (
            frozen is None
            or frozen[
                "minutes"
            ] < 900.0
            or row[
                "position"
            ]
            not in {
                "MID",
                "FWD",
            }
            or frozen[
                "rate"
            ]
            < threshold
        ):

            continue


        selected.append(
            row
        )


    if not selected:

        return None


    denominator = sum(
        row[
            "team_actual_xg"
        ]
        for row in selected
    )


    prior = sum(
        row[
            "team_actual_xg"
        ]
        * abs(
            row[
                "prior_share"
            ]
            - row[
                "actual_share"
            ]
        )
        for row in selected
    ) / denominator


    blend = sum(
        row[
            "team_actual_xg"
        ]
        * abs(
            row[
                "blend_share"
            ]
            - row[
                "actual_share"
            ]
        )
        for row in selected
    ) / denominator


    return {
        "threshold": threshold,
        "players": len(
            selected
        ),
        "prior_weighted_mae": (
            prior
        ),
        "blend_weighted_mae": (
            blend
        ),
        "delta": (
            blend
            - prior
        ),
    }


def haaland_rows(
    rows,
):

    return [
        row
        for row in rows
        if (
            "haaland"
            in row[
                "player_key"
            ]
            and row[
                "position"
            ] == "FWD"
        )
    ]


#
# ============================================================
# 7. Run both transitions.
#
# alpha=0.55 is FROZEN.
# It is NOT selected or tuned here.
# ============================================================
#

report = {
    "status": (
        "DEVELOPMENT_ONLY_"
        "DEPLOYABLE_EXPOSURE_GATE"
    ),
    "alpha": ALPHA,
    "alpha_origin": (
        "selected_only_on_"
        "2023-24_to_2024-25"
    ),
    "prior_minutes": (
        PRIOR_MINUTES
    ),
    "target_outcomes_used_for_alpha": (
        False
    ),
    "exposure_modes": {
        "oracle": (
            "actual target minutes; "
            "reference only"
        ),
        "prev5": (
            "walk-forward mean of last "
            "up to 5 known prior fixture "
            "minutes"
        ),
        "prev1": (
            "walk-forward previous known "
            "fixture minutes"
        ),
    },
    "transitions": {},
}


for (
    train_season,
    target_season,
) in TRANSITIONS:

    train = prepared[
        train_season
    ]

    target = prepared[
        target_season
    ]


    transition_key = (
        f"{train_season}"
        f"->{target_season}"
    )

    report[
        "transitions"
    ][
        transition_key
    ] = {}


    print()
    print(
        "=" * 72
    )

    print(
        transition_key
    )

    print(
        "=" * 72
    )


    for mode in (
        "oracle",
        "prev5",
        "prev1",
    ):

        (
            rows,
            exposure_audit,
            rates,
        ) = allocation_rows(
            train,
            target,
            exposure_mode=mode,
        )


        all_metrics = (
            allocation_metrics(
                rows
            )
        )

        fwd_metrics = (
            fwd_cross_entropy(
                rows
            )
        )

        threat_metrics = (
            high_threat_metrics(
                rows,
                rates,
            )
        )

        haaland = (
            haaland_rows(
                rows
            )
        )


        mode_report = {
            "exposure": (
                exposure_audit
            ),
            "all": (
                all_metrics
            ),
            "fwd": (
                fwd_metrics
            ),
            "high_threat": (
                threat_metrics
            ),
            "haaland": (
                haaland
            ),
        }


        report[
            "transitions"
        ][
            transition_key
        ][
            mode
        ] = mode_report


        print()
        print(
            f"[{mode.upper()}]"
        )


        print(
            "ALL CE       "
            f"prior="
            f"{all_metrics['prior_ce']:.6f} "
            f"blend="
            f"{all_metrics['blend_ce']:.6f} "
            f"delta="
            f"{all_metrics['ce_delta']:+.6f}"
        )


        print(
            "ALL shareMAE "
            f"prior="
            f"{all_metrics['prior_share_mae']:.6f} "
            f"blend="
            f"{all_metrics['blend_share_mae']:.6f} "
            f"delta="
            f"{all_metrics['share_mae_delta']:+.6f}"
        )


        if (
            fwd_metrics[
                "delta"
            ]
            is not None
        ):

            print(
                "FWD CE       "
                f"prior="
                f"{fwd_metrics['prior_ce']:.6f} "
                f"blend="
                f"{fwd_metrics['blend_ce']:.6f} "
                f"delta="
                f"{fwd_metrics['delta']:+.6f}"
            )


        if (
            threat_metrics
            is not None
        ):

            print(
                "HIGH threat  "
                f"prior="
                f"{threat_metrics['prior_weighted_mae']:.6f} "
                f"blend="
                f"{threat_metrics['blend_weighted_mae']:.6f} "
                f"delta="
                f"{threat_metrics['delta']:+.6f}"
            )


        if not exposure_audit.get(
            "oracle",
            False,
        ):

            print(
                "Exposure      "
                f"history="
                f"{exposure_audit['history_rows']} "
                f"fallback="
                f"{exposure_audit['fallback_rows']} "
                f"fallback_rate="
                f"{exposure_audit['fallback_rate']:.3f}"
            )


        for row in haaland:

            print(
                "Haaland       "
                f"team="
                f"{row['team']} "
                f"actual="
                f"{row['actual_share']:.3f} "
                f"prior="
                f"{row['prior_share']:.3f} "
                f"blend="
                f"{row['blend_share']:.3f} "
                f"pred_min="
                f"{row['predicted_minutes']:.1f}"
            )


#
# ============================================================
# 8. Holdout gate:
#
# We do NOT tune anything on 2025-26.
#
# Require directionality only:
# - ALL CE improves
# - ALL share MAE improves
# - high-threat MAE improves
#
# for BOTH deployable exposure baselines.
#
# FWD CE is reported but is not allowed
# to select alpha on holdout.
# ============================================================
#

holdout = report[
    "transitions"
][
    "2024-25->2025-26"
]


gate_details = {}


for mode in (
    "prev5",
    "prev1",
):

    row = holdout[
        mode
    ]

    all_ce_ok = (
        row[
            "all"
        ][
            "ce_delta"
        ]
        < 0.0
    )

    all_mae_ok = (
        row[
            "all"
        ][
            "share_mae_delta"
        ]
        < 0.0
    )

    threat = row[
        "high_threat"
    ]

    threat_ok = (
        threat is not None
        and threat[
            "delta"
        ]
        < 0.0
    )


    gate_details[
        mode
    ] = {
        "all_ce_improves": (
            all_ce_ok
        ),
        "all_share_mae_improves": (
            all_mae_ok
        ),
        "high_threat_improves": (
            threat_ok
        ),
        "pass": all((
            all_ce_ok,
            all_mae_ok,
            threat_ok,
        )),
    }


gate_pass = all(
    row[
        "pass"
    ]
    for row in (
        gate_details.values()
    )
)


report[
    "holdout_gate"
] = {
    "transition": (
        "2024-25->2025-26"
    ),
    "criteria": (
        gate_details
    ),
    "pass": (
        gate_pass
    ),
}


OUT.parent.mkdir(
    parents=True,
    exist_ok=True,
)


OUT.write_text(
    json.dumps(
        report,
        indent=2,
        sort_keys=True,
    )
    + "\n",
    encoding="utf-8",
)


print()
print(
    "=== CAPTAIN-065 "
    "DEPLOYABLE EXPOSURE GATE ==="
)

for mode, values in (
    gate_details.items()
):

    print(
        f"{mode:<6} "
        f"ALL_CE="
        f"{'PASS' if values['all_ce_improves'] else 'FAIL'} "
        f"ALL_MAE="
        f"{'PASS' if values['all_share_mae_improves'] else 'FAIL'} "
        f"HIGH_THREAT="
        f"{'PASS' if values['high_threat_improves'] else 'FAIL'} "
        f"=> "
        f"{'PASS' if values['pass'] else 'FAIL'}"
    )


print(
    "DEPLOYABLE GATE:",
    (
        "PASS"
        if gate_pass
        else "FAIL"
    ),
)

print(
    "alpha retuned on holdout: NO"
)

print(
    "2026-27 outcomes used: NO"
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
