from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from statistics import mean, median
import ast
import contextlib
import hashlib
import inspect
import io
import json
import math


ROOT = Path(".").resolve()

HARNESS = (
    ROOT
    / "scripts"
    / "run_strict_model_backtest_sim_v21_512.py"
)

OUT_DIR = (
    ROOT
    / "scratch"
    / "decision"
    / "captain068f"
)

REPORT = (
    OUT_DIR
    / "historical_reconciliation.json"
)

CAPTURE_PATH = (
    OUT_DIR
    / "historical_v21_minutes_rows.json"
)

DEVELOPMENT_SEASON = "2024-25"
HOLDOUT_SEASON = "2025-26"

SEASONS = (
    DEVELOPMENT_SEASON,
    HOLDOUT_SEASON,
)

EPS = 1e-12


# ============================================================
# Generic helpers
# ============================================================

def jsonable(value):

    if isinstance(value, Path):
        return str(value)

    if isinstance(value, dict):
        return {
            str(key): jsonable(item)
            for key, item
            in value.items()
        }

    if isinstance(value, (list, tuple)):
        return [
            jsonable(item)
            for item in value
        ]

    return value


def sha256(path: Path):

    return hashlib.sha256(
        path.read_bytes()
    ).hexdigest()


def tree_hashes(root: Path):

    if not root.exists():
        return {}

    return {
        str(
            path.relative_to(ROOT)
        ): sha256(path)
        for path in sorted(
            item
            for item
            in root.rglob("*")
            if item.is_file()
        )
    }


BACKTEST_ROOT = (
    ROOT
    / "data"
    / "processed"
    / "backtests"
    / "strict"
)


# ============================================================
# Capture exception.
#
# BaseException rather than Exception so a broad historical
# `except Exception` cannot accidentally swallow it.
# ============================================================

class _Captain068FCaptureComplete(
    BaseException
):

    def __init__(self, rows):

        super().__init__(
            "CAPTAIN-068F capture complete"
        )

        self.rows = tuple(rows)


_CAPTURE_ROWS = []


# ============================================================
# Instrument historical STRICT harness in memory.
#
# We do NOT edit the source file.
#
# 1. after calibrated_minutes is produced, record current-GW
#    player probabilities and eventual outcome;
# 2. after all historical GW loops finish, stop BEFORE report
#    persistence.
# ============================================================

source_text = HARNESS.read_text(
    encoding="utf-8"
)

tree = ast.parse(
    source_text,
    filename=str(HARNESS),
)


RECORDER = ast.parse(
'''
if is_current:
    _CAPTAIN068F_ROWS.append({
        "season": SEASON,
        "gameweek": int(gw),
        "prediction_timestamp": at.isoformat(),
        "snapshot_timestamp": snapshot_at.isoformat(),
        "fixture_id": str(state.canonical_fixture_id),
        "provider_fixture_id": str(fixture_key),
        "side": str(side),
        "team_id": str(canonical_team),
        "player_id": str(player_id),
        "position": str(position).upper(),
        "model_version": str(calibrated_minutes.model_version),
        "p_start": float(calibrated_minutes.p_start),
        "p_appearance": float(calibrated_minutes.p_appearance),
        "expected_minutes": float(calibrated_minutes.expected_minutes),
        "calibration_used": calibration is not None,
        "calibration_trained_through": (
            calibration.trained_through.isoformat()
            if calibration is not None
            else None
        ),
        "prior_minutes_count": len(prior_minutes),
        "actual_available": actual_minutes is not None,
        "actual_started": (
            bool(actual_minutes.started)
            if actual_minutes is not None
            else None
        ),
        "actual_appeared": (
            bool(actual_minutes.appeared)
            if actual_minutes is not None
            else None
        ),
        "actual_minutes": (
            int(actual_minutes.minutes)
            if actual_minutes is not None
            else None
        ),
        "actual_known_at": (
            actual_minutes.known_at.isoformat()
            if actual_minutes is not None
            else None
        ),
        "scheduled_kickoff": (
            state.scheduled_kickoff.isoformat()
            if hasattr(state.scheduled_kickoff, "isoformat")
            else str(state.scheduled_kickoff)
        ),
    })
'''
).body


STOP = ast.parse(
'''
raise _Captain068FCaptureComplete(
    tuple(_CAPTAIN068F_ROWS)
)
'''
).body[0]


class HarnessTransformer(
    ast.NodeTransformer
):

    def __init__(self):

        self.in_run = False
        self.recorder_count = 0
        self.outer_loop_count = 0


    @staticmethod
    def _contains_calibrated_minutes(
        node,
    ):

        for child in ast.walk(
            node
        ):

            if not isinstance(
                child,
                ast.Assign,
            ):
                continue


            for target in child.targets:

                if (
                    isinstance(
                        target,
                        ast.Name,
                    )
                    and target.id
                    == "calibrated_minutes"
                ):

                    return True


        return False


    def visit_FunctionDef(
        self,
        node,
    ):

        if node.name != "run":

            return self.generic_visit(
                node
            )


        old = self.in_run

        self.in_run = True

        node = self.generic_visit(
            node
        )

        self.in_run = old


        #
        # The historical runner contains more than one
        # top-level:
        #
        #     for gw in sorted(...)
        #
        # We must stop only AFTER the actual prediction
        # loop -- the one containing calibrated_minutes.
        #
        # This avoids depending on loop order or incidental
        # syntax elsewhere in the harness.
        #
        candidates = [
            statement
            for statement in node.body
            if (
                isinstance(
                    statement,
                    ast.For,
                )
                and isinstance(
                    statement.target,
                    ast.Name,
                )
                and statement.target.id
                == "gw"
                and self._contains_calibrated_minutes(
                    statement
                )
            )
        ]


        if len(
            candidates
        ) != 1:

            raise RuntimeError(
                "Expected exactly one top-level "
                "historical GW prediction loop "
                "containing calibrated_minutes; "
                f"found {len(candidates)}."
            )


        selected_loop = candidates[
            0
        ]

        new_body = []


        for statement in node.body:

            new_body.append(
                statement
            )


            if statement is selected_loop:

                new_body.append(
                    STOP
                )

                self.outer_loop_count += 1


        node.body = new_body

        return node


    def visit_Assign(
        self,
        node,
    ):

        node = self.generic_visit(
            node
        )


        if not self.in_run:

            return node


        targets = [
            target.id
            for target in node.targets
            if isinstance(
                target,
                ast.Name,
            )
        ]


        if (
            "calibrated_minutes"
            in targets
        ):

            self.recorder_count += 1

            return [
                node,
                *RECORDER,
            ]


        return node


transformer = HarnessTransformer()

tree = transformer.visit(
    tree
)

ast.fix_missing_locations(
    tree
)


if transformer.recorder_count != 1:

    raise RuntimeError(
        "Expected exactly one "
        "calibrated_minutes assignment "
        "inside historical run(); found "
        f"{transformer.recorder_count}."
    )


if transformer.outer_loop_count != 1:

    raise RuntimeError(
        "Expected exactly one top-level "
        "historical GW loop; found "
        f"{transformer.outer_loop_count}."
    )


# ============================================================
# Load transformed harness.
# ============================================================

namespace = {
    "__name__":
        "_captain068f_historical_harness",

    "__file__":
        str(HARNESS),

    "_CAPTAIN068F_ROWS":
        _CAPTURE_ROWS,

    "_Captain068FCaptureComplete":
        _Captain068FCaptureComplete,
}


exec(
    compile(
        tree,
        str(HARNESS),
        "exec",
    ),
    namespace,
)


run = namespace.get(
    "run"
)


if not callable(run):

    raise RuntimeError(
        "Historical run() was not loaded."
    )


# ============================================================
# Force Minutes V2.1 ONLY inside this in-memory harness.
#
# `run()` resolves MinutesModel from its module globals at
# execution time, so this does not modify any source file.
# ============================================================

from fpl_engine.models.minutes.v2 import (
    HurdleTimeDecayMinutesModel,
)


namespace[
    "MinutesModel"
] = HurdleTimeDecayMinutesModel


# ============================================================
# Execute development + holdout.
#
# We use one fixture simulation only because the scoring target
# here is the Minutes output itself, not event EV. The historical
# loop and PIT source logic remain unchanged.
# ============================================================

signature = inspect.signature(
    run
)


all_rows = []

harness_stdout = {}


before_outputs = tree_hashes(
    BACKTEST_ROOT
)


for season in SEASONS:

    _CAPTURE_ROWS.clear()

    kwargs = {}


    if (
        "simulations_per_fixture"
        in signature.parameters
    ):

        kwargs[
            "simulations_per_fixture"
        ] = 1


    if (
        "random_seed"
        in signature.parameters
    ):

        kwargs[
            "random_seed"
        ] = 6806


    if (
        "skip_reference"
        in signature.parameters
    ):

        kwargs[
            "skip_reference"
        ] = True


    if (
        "skip_convergence"
        in signature.parameters
    ):

        kwargs[
            "skip_convergence"
        ] = True


    buffer = io.StringIO()


    try:

        with contextlib.redirect_stdout(
            buffer
        ):

            run(
                ROOT,
                season,
                **kwargs,
            )


    except _Captain068FCaptureComplete as exc:

        captured = list(
            exc.rows
        )


    else:

        raise RuntimeError(
            "Historical harness completed "
            "without the CAPTAIN-068F "
            "capture stop."
        )


    harness_stdout[
        season
    ] = buffer.getvalue()


    if not captured:

        raise RuntimeError(
            f"No historical rows captured "
            f"for {season}."
        )


    all_rows.extend(
        captured
    )


after_outputs = tree_hashes(
    BACKTEST_ROOT
)


historical_outputs_unchanged = (
    before_outputs
    == after_outputs
)


# ============================================================
# Basic capture audit
# ============================================================

duplicate_keys = []

seen = set()


for row in all_rows:

    key = (
        row[
            "season"
        ],
        row[
            "gameweek"
        ],
        row[
            "fixture_id"
        ],
        row[
            "side"
        ],
        row[
            "player_id"
        ],
    )


    if key in seen:

        duplicate_keys.append(
            key
        )

    seen.add(
        key
    )


unexpected_seasons = sorted({
    row[
        "season"
    ]
    for row in all_rows
    if row[
        "season"
    ]
    not in SEASONS
})


model_versions = sorted({
    row[
        "model_version"
    ]
    for row in all_rows
})


v21_model_gate = (
    bool(
        model_versions
    )
    and all(
        str(version).startswith(
            "minutes_hurdle_v2"
        )
        for version
        in model_versions
    )
)


snapshot_leaks = []

calibration_leaks = []

target_already_known = []


from datetime import datetime


def parse_dt(value):

    return datetime.fromisoformat(
        str(value).replace(
            "Z",
            "+00:00",
        )
    )


for row in all_rows:

    prediction = parse_dt(
        row[
            "prediction_timestamp"
        ]
    )

    snapshot = parse_dt(
        row[
            "snapshot_timestamp"
        ]
    )


    if not snapshot < prediction:

        snapshot_leaks.append(
            row
        )


    trained = row.get(
        "calibration_trained_through"
    )


    if (
        trained is not None
        and parse_dt(
            trained
        )
        > prediction
    ):

        calibration_leaks.append(
            row
        )


    actual_known = row.get(
        "actual_known_at"
    )


    if (
        actual_known is not None
        and parse_dt(
            actual_known
        )
        <= prediction
    ):

        target_already_known.append(
            row
        )


# ============================================================
# Reconciliation methods
# ============================================================

def bisect_root(
    fn,
    lo=-40.0,
    hi=40.0,
    iterations=120,
):

    flo = fn(
        lo
    )

    fhi = fn(
        hi
    )


    if (
        flo > 0.0
        or fhi < 0.0
    ):

        raise RuntimeError(
            "Root bracket failed."
        )


    for _ in range(
        iterations
    ):

        mid = (
            lo + hi
        ) / 2.0

        value = fn(
            mid
        )


        if value < 0.0:

            lo = mid

        else:

            hi = mid


    return (
        lo + hi
    ) / 2.0


def reconcile_logit(
    rows,
    target,
):

    def values(
        shift,
    ):

        output = {}


        for row in rows:

            raw = min(
                1.0 - EPS,
                max(
                    EPS,
                    float(
                        row[
                            "p_start"
                        ]
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


            output[
                row[
                    "player_id"
                ]
            ] = value


        return output


    shift = bisect_root(
        lambda value:
            sum(
                values(
                    value
                ).values()
            )
            - target
    )


    return values(
        shift
    )


def reconcile_scale(
    rows,
    target,
):

    def values(
        log_scale,
    ):

        scale = math.exp(
            log_scale
        )


        return {
            row[
                "player_id"
            ]:
            min(
                1.0,
                scale
                * max(
                    EPS,
                    float(
                        row[
                            "p_start"
                        ]
                    ),
                ),
            )
            for row in rows
        }


    shift = bisect_root(
        lambda value:
            sum(
                values(
                    value
                ).values()
            )
            - target
    )


    return values(
        shift
    )


def reconcile_l2(
    rows,
    target,
):

    def values(
        shift,
    ):

        return {
            row[
                "player_id"
            ]:
            min(
                1.0,
                max(
                    0.0,
                    float(
                        row[
                            "p_start"
                        ]
                    )
                    + shift,
                ),
            )
            for row in rows
        }


    shift = bisect_root(
        lambda value:
            sum(
                values(
                    value
                ).values()
            )
            - target
    )


    return values(
        shift
    )


METHODS = {
    "logit_shift":
        reconcile_logit,

    "capped_scale":
        reconcile_scale,

    "capped_l2":
        reconcile_l2,
}


# ============================================================
# Build team-fixture groups.
# ============================================================

groups = defaultdict(
    list
)


for row in all_rows:

    key = (
        row[
            "season"
        ],
        row[
            "gameweek"
        ],
        row[
            "fixture_id"
        ],
        row[
            "side"
        ],
        row[
            "team_id"
        ],
    )

    groups[
        key
    ].append(
        row
    )


invalid_groups = []

structural_failures = []

raw_team_start_sums = defaultdict(
    list
)

evaluation_rows = defaultdict(
    list
)


for key, rows in sorted(
    groups.items()
):

    (
        season,
        gameweek,
        fixture_id,
        side,
        team_id,
    ) = key


    gks = [
        row
        for row in rows
        if row[
            "position"
        ]
        == "GK"
    ]


    outfield = [
        row
        for row in rows
        if row[
            "position"
        ]
        != "GK"
    ]


    if (
        len(
            gks
        )
        < 1
        or len(
            outfield
        )
        < 10
    ):

        invalid_groups.append({
            "key": key,
            "goalkeepers": len(
                gks
            ),
            "outfield": len(
                outfield
            ),
        })

        continue


    raw_team_start_sums[
        season
    ].append(
        sum(
            float(
                row[
                    "p_start"
                ]
            )
            for row in rows
        )
    )


    #
    # RAW comparator
    #
    for row in rows:

        if not row[
            "actual_available"
        ]:

            continue


        evaluation_rows[
            (
                season,
                "raw",
            )
        ].append({
            **row,
            "raw_p_start":
                float(
                    row[
                        "p_start"
                    ]
                ),
            "pred_p_start":
                float(
                    row[
                        "p_start"
                    ]
                ),
            "pred_p_appearance":
                float(
                    row[
                        "p_appearance"
                    ]
                ),
            "p_start_delta":
                0.0,
            "p_appearance_delta":
                0.0,
        })


    #
    # Coherent candidates
    #
    for method_name, method in (
        METHODS.items()
    ):

        corrected = {}

        corrected.update(
            method(
                gks,
                1.0,
            )
        )

        corrected.update(
            method(
                outfield,
                10.0,
            )
        )


        start_sum = sum(
            corrected.values()
        )

        gk_sum = sum(
            corrected[
                row[
                    "player_id"
                ]
            ]
            for row in gks
        )

        outfield_sum = sum(
            corrected[
                row[
                    "player_id"
                ]
            ]
            for row in outfield
        )


        structural_pass = all((
            math.isclose(
                start_sum,
                11.0,
                abs_tol=1e-8,
                rel_tol=0.0,
            ),
            math.isclose(
                gk_sum,
                1.0,
                abs_tol=1e-8,
                rel_tol=0.0,
            ),
            math.isclose(
                outfield_sum,
                10.0,
                abs_tol=1e-8,
                rel_tol=0.0,
            ),
        ))


        if not structural_pass:

            structural_failures.append({
                "key": key,
                "method":
                    method_name,
                "sum":
                    start_sum,
                "gk_sum":
                    gk_sum,
                "outfield_sum":
                    outfield_sum,
            })


        for row in rows:

            if not row[
                "actual_available"
            ]:

                continue


            player_id = row[
                "player_id"
            ]

            new_start = float(
                corrected[
                    player_id
                ]
            )

            raw_app = float(
                row[
                    "p_appearance"
                ]
            )

            new_app = max(
                raw_app,
                new_start,
            )


            evaluation_rows[
                (
                    season,
                    method_name,
                )
            ].append({
                **row,
                "raw_p_start":
                    float(
                        row[
                            "p_start"
                        ]
                    ),
                "pred_p_start":
                    new_start,
                "pred_p_appearance":
                    new_app,
                "p_start_delta":
                    new_start
                    - float(
                        row[
                            "p_start"
                        ]
                    ),
                "p_appearance_delta":
                    new_app
                    - raw_app,
            })


# ============================================================
# Binary metrics
# ============================================================

def clip_probability(
    value,
):

    return min(
        1.0 - EPS,
        max(
            EPS,
            float(
                value
            ),
        ),
    )


def metric_block(
    rows,
):

    if not rows:

        return None


    start_brier = []

    start_logloss = []

    appearance_brier = []

    appearance_logloss = []


    for row in rows:

        y_start = float(
            bool(
                row[
                    "actual_started"
                ]
            )
        )

        y_app = float(
            bool(
                row[
                    "actual_appeared"
                ]
            )
        )


        p_start = clip_probability(
            row[
                "pred_p_start"
            ]
        )

        p_app = clip_probability(
            row[
                "pred_p_appearance"
            ]
        )


        start_brier.append(
            (
                p_start
                - y_start
            )
            ** 2
        )

        start_logloss.append(
            -(
                y_start
                * math.log(
                    p_start
                )
                + (
                    1.0
                    - y_start
                )
                * math.log(
                    1.0
                    - p_start
                )
            )
        )

        appearance_brier.append(
            (
                p_app
                - y_app
            )
            ** 2
        )

        appearance_logloss.append(
            -(
                y_app
                * math.log(
                    p_app
                )
                + (
                    1.0
                    - y_app
                )
                * math.log(
                    1.0
                    - p_app
                )
            )
        )


    return {
        "rows":
            len(
                rows
            ),

        "start_brier":
            mean(
                start_brier
            ),

        "start_log_loss":
            mean(
                start_logloss
            ),

        "appearance_brier":
            mean(
                appearance_brier
            ),

        "appearance_log_loss":
            mean(
                appearance_logloss
            ),
    }


def method_metrics(
    rows,
):

    if not rows:

        return None


    segments = {
        "all":
            rows,

        "goalkeepers":
            [
                row
                for row in rows
                if row[
                    "position"
                ]
                == "GK"
            ],

        "outfield":
            [
                row
                for row in rows
                if row[
                    "position"
                ]
                != "GK"
            ],

        "high_pstart":
            [
                row
                for row in rows
                if row[
                    "raw_p_start"
                ]
                >= 0.75
            ],
    }


    adjustments = [
        abs(
            row[
                "p_start_delta"
            ]
        )
        for row in rows
    ]

    app_raised = [
        row[
            "p_appearance_delta"
        ]
        for row in rows
        if row[
            "p_appearance_delta"
        ]
        > EPS
    ]


    return {
        "segments": {
            name:
                metric_block(
                    segment
                )
            for name, segment
            in segments.items()
        },

        "mean_abs_start_adjustment":
            mean(
                adjustments
            ),

        "max_abs_start_adjustment":
            max(
                adjustments
            ),

        "appearance_raised_rows":
            len(
                app_raised
            ),

        "appearance_raised_rate":
            (
                len(
                    app_raised
                )
                / len(
                    rows
                )
            ),

        "mean_appearance_raise_when_changed":
            (
                mean(
                    app_raised
                )
                if app_raised
                else 0.0
            ),

        "max_appearance_raise":
            (
                max(
                    app_raised
                )
                if app_raised
                else 0.0
            ),
    }


metrics = {}


for season in SEASONS:

    metrics[
        season
    ] = {}


    for method_name in (
        "raw",
        *METHODS.keys(),
    ):

        metrics[
            season
        ][
            method_name
        ] = method_metrics(
            evaluation_rows.get(
                (
                    season,
                    method_name,
                ),
                [],
            )
        )


# ============================================================
# Development selection policy.
#
# No arbitrary weighted score:
#
# Candidate must:
#   1. improve start log-loss,
#   2. not worsen start Brier,
#   3. not worsen appearance Brier.
#
# Among candidates satisfying all three, minimum start
# log-loss wins.
#
# Then that exact choice is frozen and checked on 2025/26.
# ============================================================

def primary(
    season,
    method,
):

    value = (
        metrics[
            season
        ][
            method
        ]
    )

    if value is None:

        return None

    return value[
        "segments"
    ][
        "all"
    ]


def qualifies(
    season,
    method,
):

    raw = primary(
        season,
        "raw",
    )

    candidate = primary(
        season,
        method,
    )


    if (
        raw is None
        or candidate is None
    ):

        return False


    return all((
        candidate[
            "start_log_loss"
        ]
        < raw[
            "start_log_loss"
        ],

        candidate[
            "start_brier"
        ]
        <= raw[
            "start_brier"
        ],

        candidate[
            "appearance_brier"
        ]
        <= raw[
            "appearance_brier"
        ],
    ))


development_qualified = [
    method
    for method in METHODS
    if qualifies(
        DEVELOPMENT_SEASON,
        method,
    )
]


if development_qualified:

    selected = min(
        development_qualified,
        key=lambda method: (
            primary(
                DEVELOPMENT_SEASON,
                method,
            )[
                "start_log_loss"
            ],
            primary(
                DEVELOPMENT_SEASON,
                method,
            )[
                "start_brier"
            ],
            primary(
                DEVELOPMENT_SEASON,
                method,
            )[
                "appearance_brier"
            ],
            method,
        ),
    )

else:

    selected = None


holdout_confirmed = (
    selected is not None
    and qualifies(
        HOLDOUT_SEASON,
        selected,
    )
)


if selected is None:

    decision = (
        "NO_RECONCILIATION_METHOD_"
        "PASSED_DEVELOPMENT"
    )

elif holdout_confirmed:

    decision = (
        "SELECTED_FOR_"
        "SIMULATOR_CHALLENGER"
    )

else:

    decision = (
        "REJECTED_BY_"
        "2025_26_HOLDOUT"
    )


# ============================================================
# Validation gates
# ============================================================

season_counts = {
    season: sum(
        row[
            "season"
        ]
        == season
        for row in all_rows
    )
    for season in SEASONS
}


actual_counts = {
    season: sum(
        row[
            "season"
        ]
        == season
        and row[
            "actual_available"
        ]
        for row in all_rows
    )
    for season in SEASONS
}


calibrated_counts = {
    season: sum(
        row[
            "season"
        ]
        == season
        and row[
            "calibration_used"
        ]
        for row in all_rows
    )
    for season in SEASONS
}


group_counts = {
    season: sum(
        key[
            0
        ]
        == season
        for key in groups
    )
    for season in SEASONS
}


raw_sum_stats = {}


for season, values in (
    raw_team_start_sums.items()
):

    raw_sum_stats[
        season
    ] = {
        "teams":
            len(
                values
            ),

        "mean":
            mean(
                values
            ),

        "median":
            median(
                values
            ),

        "min":
            min(
                values
            ),

        "max":
            max(
                values
            ),

        "mean_abs_gap_to_11":
            mean(
                abs(
                    value
                    - 11.0
                )
                for value in values
            ),
    }


data_gate = all(
    season_counts[
        season
    ]
    > 0
    and actual_counts[
        season
    ]
    > 0
    and group_counts[
        season
    ]
    > 0
    for season in SEASONS
)


leakage_gate = all((
    not snapshot_leaks,
    not calibration_leaks,
    not target_already_known,
    not unexpected_seasons,
))


identity_gate = (
    not duplicate_keys
)


structure_gate = all((
    not invalid_groups,
    not structural_failures,
))


side_effect_gate = (
    historical_outputs_unchanged
)


validation_gate = all((
    data_gate,
    leakage_gate,
    identity_gate,
    structure_gate,
    v21_model_gate,
    side_effect_gate,
))


# ============================================================
# Persist evidence
# ============================================================

CAPTURE_PATH.write_text(
    json.dumps(
        jsonable(
            all_rows
        ),
        indent=2,
        sort_keys=True,
    )
    + "\n",
    encoding="utf-8",
)


report = {
    "status":
        "CAPTAIN_068F_B_"
        "HISTORICAL_RECONCILIATION",

    "development_season":
        DEVELOPMENT_SEASON,

    "holdout_season":
        HOLDOUT_SEASON,

    "production_modified":
        False,

    "current_2026_27_outcomes_used":
        False,

    "historical_harness":
        str(
            HARNESS.relative_to(
                ROOT
            )
        ),

    "minutes_runtime_override":
        "HurdleTimeDecayMinutesModel",

    "model_versions":
        model_versions,

    "capture": {
        "rows_by_season":
            season_counts,

        "actual_rows_by_season":
            actual_counts,

        "calibrated_rows_by_season":
            calibrated_counts,

        "team_fixture_groups_by_season":
            group_counts,

        "duplicates":
            len(
                duplicate_keys
            ),

        "invalid_groups":
            len(
                invalid_groups
            ),
    },

    "point_in_time": {
        "snapshot_leaks":
            len(
                snapshot_leaks
            ),

        "calibration_leaks":
            len(
                calibration_leaks
            ),

        "already_known_target_outcomes":
            len(
                target_already_known
            ),

        "unexpected_seasons":
            unexpected_seasons,
    },

    "raw_team_pstart_sum":
        raw_sum_stats,

    "metrics":
        metrics,

    "selection": {
        "development_qualified":
            development_qualified,

        "selected_method":
            selected,

        "holdout_confirmed":
            holdout_confirmed,

        "decision":
            decision,

        "policy": (
            "2024/25: improve start log-loss, "
            "non-worse start Brier and appearance "
            "Brier; freeze best start log-loss. "
            "2025/26: same three conditions must "
            "hold without retuning."
        ),
    },

    "gates": {
        "data":
            data_gate,

        "point_in_time":
            leakage_gate,

        "identity":
            identity_gate,

        "structure":
            structure_gate,

        "minutes_v21":
            v21_model_gate,

        "historical_outputs_unchanged":
            side_effect_gate,

        "validation":
            validation_gate,
    },

    "artifacts": {
        "capture":
            str(
                CAPTURE_PATH.relative_to(
                    ROOT
                )
            ),
    },
}


REPORT.write_text(
    json.dumps(
        jsonable(
            report
        ),
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
    "=== CAPTAIN-068F-B "
    "HISTORICAL RECONCILIATION ==="
)

print(
    "minutes versions:",
    model_versions,
)

print(
    "2026/27 outcomes used:",
    "NO",
)

print(
    "historical outputs changed:",
    (
        "NO"
        if historical_outputs_unchanged
        else "YES"
    ),
)


print()
print(
    "=== COVERAGE ==="
)


for season in SEASONS:

    print(
        f"{season}: "
        f"rows={season_counts[season]} "
        f"actual={actual_counts[season]} "
        f"calibrated={calibrated_counts[season]} "
        f"team-fixtures={group_counts[season]}"
    )


print()
print(
    "=== PIT AUDIT ==="
)

print(
    "snapshot leaks:",
    len(
        snapshot_leaks
    ),
)

print(
    "calibration leaks:",
    len(
        calibration_leaks
    ),
)

print(
    "already-known targets:",
    len(
        target_already_known
    ),
)

print(
    "duplicates:",
    len(
        duplicate_keys
    ),
)

print(
    "invalid lineup groups:",
    len(
        invalid_groups
    ),
)

print(
    "structural failures:",
    len(
        structural_failures
    ),
)


print()
print(
    "=== RAW TEAM pSTART ==="
)


for season in SEASONS:

    values = raw_sum_stats[
        season
    ]

    print(
        f"{season}: "
        f"mean={values['mean']:.3f} "
        f"median={values['median']:.3f} "
        f"range="
        f"{values['min']:.3f}"
        f"->{values['max']:.3f} "
        f"mean|gap11|="
        f"{values['mean_abs_gap_to_11']:.3f}"
    )


print()
print(
    "=== DEVELOPMENT 2024/25 ==="
)


for method in (
    "raw",
    *METHODS.keys(),
):

    block = primary(
        DEVELOPMENT_SEASON,
        method,
    )

    print(
        f"{method:<14} "
        f"N={block['rows']:<5} "
        f"startBrier="
        f"{block['start_brier']:.6f} "
        f"startLL="
        f"{block['start_log_loss']:.6f} "
        f"appBrier="
        f"{block['appearance_brier']:.6f}"
    )


print()
print(
    "qualified:",
    (
        ", ".join(
            development_qualified
        )
        if development_qualified
        else "NONE"
    ),
)

print(
    "frozen selection:",
    (
        selected
        if selected is not None
        else "NONE"
    ),
)


print()
print(
    "=== HOLDOUT 2025/26 ==="
)


for method in (
    "raw",
    *METHODS.keys(),
):

    block = primary(
        HOLDOUT_SEASON,
        method,
    )

    print(
        f"{method:<14} "
        f"N={block['rows']:<5} "
        f"startBrier="
        f"{block['start_brier']:.6f} "
        f"startLL="
        f"{block['start_log_loss']:.6f} "
        f"appBrier="
        f"{block['appearance_brier']:.6f}"
    )


print()
print(
    "=== SEGMENTS FOR SELECTED ==="
)


if selected is None:

    print(
        "no method selected"
    )

else:

    for season in SEASONS:

        print()
        print(
            season
        )


        raw_segments = (
            metrics[
                season
            ][
                "raw"
            ][
                "segments"
            ]
        )

        selected_segments = (
            metrics[
                season
            ][
                selected
            ][
                "segments"
            ]
        )


        for segment in (
            "goalkeepers",
            "outfield",
            "high_pstart",
        ):

            raw = raw_segments[
                segment
            ]

            candidate = (
                selected_segments[
                    segment
                ]
            )


            print(
                f"{segment:<12} "
                f"N={candidate['rows']:<5} "
                f"dBrier="
                f"{candidate['start_brier'] - raw['start_brier']:+.6f} "
                f"dLL="
                f"{candidate['start_log_loss'] - raw['start_log_loss']:+.6f} "
                f"dAppBrier="
                f"{candidate['appearance_brier'] - raw['appearance_brier']:+.6f}"
            )


print()
print(
    "=== DECISION ==="
)

print(
    "selected method:",
    (
        selected
        if selected is not None
        else "NONE"
    ),
)

print(
    "holdout confirmed:",
    (
        "YES"
        if holdout_confirmed
        else "NO"
    ),
)

print(
    "decision:",
    decision,
)

print(
    "VALIDATION GATE:",
    (
        "PASS"
        if validation_gate
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


if not validation_gate:

    raise RuntimeError(
        "CAPTAIN-068F-B historical "
        "validation gate failed."
    )
