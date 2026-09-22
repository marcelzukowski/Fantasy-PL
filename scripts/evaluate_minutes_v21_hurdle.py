from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean

from fpl_engine.current_history import (
    load_strict_historical_context,
)
from fpl_engine.features.minutes_dataset import (
    MinutesObservation,
    eligible_history,
)
from fpl_engine.models.minutes import (
    MinutesContext,
    MinutesModel,
    MinutesModelConfig,
)
from fpl_engine.models.minutes.calibration import (
    MinutesCalibrationPoint,
    fit_minutes_calibration,
)


ROOT = Path.cwd()

LOAD_AT = datetime(
    2026, 9, 12, 12, 0,
    tzinfo=timezone.utc,
)

VALIDATION_START = datetime(
    2025, 8, 1,
    tzinfo=timezone.utc,
)

VALIDATION_END = datetime(
    2025, 10, 15,
    tzinfo=timezone.utc,
)

FINAL_START = datetime(
    2026, 1, 1,
    tzinfo=timezone.utc,
)

FINAL_END = datetime(
    2026, 6, 1,
    tzinfo=timezone.utc,
)

MIN_HISTORY = 3


# ============================================================
# CONFIGS
# ============================================================

V1_CONFIG = MinutesModelConfig()

WEAK_CONFIG = MinutesModelConfig(
    history_matches=20,
    match_half_life=5.0,

    # Same prior means as V1,
    # lower pseudo-count / shrinkage strength.
    appearance_prior_alpha=1.0,
    appearance_prior_beta=0.5,

    start_prior_alpha=1.0,
    start_prior_beta=1.0,

    distribution_prior_weight=3.0,
    unknown_availability_prior=0.85,

    model_version="minutes_time_decay_v21",
    dataset_version="minutes_dataset_v1",
    feature_version="minutes_hurdle_time_decay_v21",
)


# ============================================================
# TIME-DECAY BASE
# ============================================================

class TimeDecayMinutesModel(
    MinutesModel
):

    def __init__(
        self,
        config,
        *,
        time_half_life_days=30.0,
        offseason_gap_days=60.0,
        offseason_carryover=0.50,
    ):

        super().__init__(
            config
        )

        self.time_half_life_days = float(
            time_half_life_days
        )

        self.offseason_gap_days = float(
            offseason_gap_days
        )

        self.offseason_carryover = float(
            offseason_carryover
        )

        self._time_rows = None
        self._time_prediction = None


    def predict(
        self,
        observations,
        context,
        *,
        calibration=None,
    ):

        prediction = (
            context.prediction_timestamp
            .astimezone(
                timezone.utc
            )
        )

        rows = eligible_history(
            observations,
            player_id=context.player_id,
            target_fixture_id=context.fixture_id,
            prediction_timestamp=prediction,
        )[
            -self.config.history_matches:
        ]

        self._time_rows = tuple(
            rows
        )

        self._time_prediction = (
            prediction
        )

        try:

            return super().predict(
                observations,
                context,
                calibration=calibration,
            )

        finally:

            self._time_rows = None
            self._time_prediction = None


    def _weights(
        self,
        size,
    ):

        rows = self._time_rows
        prediction = (
            self._time_prediction
        )

        if (
            rows is None
            or prediction is None
        ):
            raise RuntimeError(
                "missing time-decay context"
            )

        if len(rows) != size:
            raise RuntimeError(
                "history size mismatch"
            )

        weights = []

        for row in rows:

            kickoff = (
                row.kickoff.astimezone(
                    timezone.utc
                )
            )

            age_days = max(
                0.0,
                (
                    prediction
                    - kickoff
                ).total_seconds()
                / 86400.0,
            )

            weight = 0.5 ** (
                age_days
                / self.time_half_life_days
            )

            weights.append(
                weight
            )


        # Most recent long break inside
        # the retained history.
        boundary = None

        for index, row in enumerate(
            rows
        ):

            current = (
                row.kickoff.astimezone(
                    timezone.utc
                )
            )

            if index + 1 < len(rows):

                nxt = (
                    rows[index + 1]
                    .kickoff.astimezone(
                        timezone.utc
                    )
                )

            else:

                nxt = prediction

            gap = (
                nxt
                - current
            ).total_seconds() / 86400.0

            if (
                gap
                >= self.offseason_gap_days
            ):
                boundary = (
                    index + 1
                )


        if boundary is not None:

            for index in range(
                boundary
            ):

                weights[index] *= (
                    self.offseason_carryover
                )

        return weights


# ============================================================
# OLD COUPLED V2 REFERENCE
# ============================================================

class CoupledV2(
    TimeDecayMinutesModel
):
    pass


# ============================================================
# V2.1
#
# Time decay affects:
#   p_appearance
#   p_start_given_appearance
#
# Conditional starter/bench minutes remain V1-style:
#   last 10 rows
#   positional match weights
# ============================================================

class HurdleOnlyV21(
    TimeDecayMinutesModel
):

    def starter_minutes_distribution(
        self,
        rows,
        weights,
        context,
    ):

        v1_rows = list(
            rows[-10:]
        )

        v1_weights = (
            MinutesModel._weights(
                self,
                len(v1_rows),
            )
        )

        return (
            MinutesModel
            .starter_minutes_distribution(
                self,
                v1_rows,
                v1_weights,
                context,
            )
        )


    def bench_minutes_distribution(
        self,
        rows,
        weights,
    ):

        v1_rows = list(
            rows[-10:]
        )

        v1_weights = (
            MinutesModel._weights(
                self,
                len(v1_rows),
            )
        )

        return (
            MinutesModel
            .bench_minutes_distribution(
                self,
                v1_rows,
                v1_weights,
            )
        )


# ============================================================
# DATA
# ============================================================

historical = (
    load_strict_historical_context(
        ROOT,
        (
            "2024-25",
            "2025-26",
        ),
        prediction_timestamp=LOAD_AT,
    )
)

observations = []

for rows in (
    historical.minutes.values()
):
    observations.extend(
        rows
    )

observations.sort(
    key=lambda row: (
        row.kickoff,
        row.fixture_id,
        row.player_id,
    )
)

by_player = defaultdict(
    list
)

for row in observations:

    by_player[
        row.player_id
    ].append(
        row
    )


print(
    f"observations={len(observations)} "
    f"players={len(by_player)}"
)


# ============================================================
# RECORDS
# ============================================================

@dataclass
class Record:
    target: MinutesObservation
    history: tuple[
        MinutesObservation,
        ...
    ]
    context: MinutesContext
    raw: object
    regular_three: bool


def make_records(
    model,
):

    records = []

    for player_id, player_rows in (
        by_player.items()
    ):

        rows = sorted(
            player_rows,
            key=lambda row: (
                row.kickoff,
                row.fixture_id,
            ),
        )

        for target in rows:

            timestamp = (
                target.kickoff
                - timedelta(
                    microseconds=1
                )
            )

            history = [
                row
                for row in rows
                if (
                    row.fixture_id
                    != target.fixture_id
                    and row.kickoff
                    < timestamp
                    and row.known_at
                    <= timestamp
                )
            ]

            if (
                len(history)
                < MIN_HISTORY
            ):
                continue

            context = MinutesContext(
                target.player_id,
                target.fixture_id,
                timestamp,
                availability_probability=1.0,
                availability_known_at=timestamp,
                availability_confidence=1.0,
            )

            raw = model.predict(
                history,
                context,
            )

            recent = history[-3:]

            regular_three = (
                len(recent) == 3
                and all(
                    row.appeared
                    and row.started
                    for row in recent
                )
            )

            records.append(
                Record(
                    target=target,
                    history=tuple(
                        history
                    ),
                    context=context,
                    raw=raw,
                    regular_three=(
                        regular_three
                    ),
                )
            )

    records.sort(
        key=lambda record: (
            record.target.kickoff,
            record.target.fixture_id,
            record.target.player_id,
        )
    )

    return records


# ============================================================
# CALIBRATION
# ============================================================

def fit_artifact(
    records,
    cutoff,
):

    points = []

    for record in records:

        target = record.target

        if (
            target.known_at
            > cutoff
        ):
            continue

        raw = record.raw

        points.append(
            MinutesCalibrationPoint(
                raw.p_appearance,
                raw.p_start,
                raw.p60,
                raw.p75,
                raw.p90,
                target.appeared,
                target.started,
                target.minutes,
                target.known_at,
            )
        )

    if len(points) < 8:
        raise RuntimeError(
            "not enough calibration points"
        )

    return fit_minutes_calibration(
        points,
        training_cutoff=cutoff,
        method="platt",
    )


# ============================================================
# METRICS
# ============================================================

def clip_probability(
    value,
):

    return min(
        1 - 1e-7,
        max(
            1e-7,
            float(value),
        ),
    )


def binary_logloss(
    probability,
    observed,
):

    p = clip_probability(
        probability
    )

    y = float(
        observed
    )

    return -(
        y * math.log(p)
        + (1 - y)
        * math.log(
            1 - p
        )
    )


def evaluate(
    model,
    records,
    *,
    start,
    end,
    regular_only=False,
):

    artifact = fit_artifact(
        records,
        start,
    )

    scores = []

    for record in records:

        target = record.target

        if not (
            start
            <= target.kickoff
            < end
        ):
            continue

        if (
            regular_only
            and not record.regular_three
        ):
            continue

        prediction = model.predict(
            record.history,
            record.context,
            calibration=artifact,
        )

        appeared = float(
            target.appeared
        )

        started = float(
            target.started
        )

        sixty = float(
            target.minutes >= 60
        )

        error = abs(
            target.minutes
            - prediction.expected_minutes
        )

        scores.append(
            {
                "error": error,
                "app_brier": (
                    prediction.p_appearance
                    - appeared
                ) ** 2,
                "app_log": (
                    binary_logloss(
                        prediction.p_appearance,
                        appeared,
                    )
                ),
                "start_brier": (
                    prediction.p_start
                    - started
                ) ** 2,
                "start_log": (
                    binary_logloss(
                        prediction.p_start,
                        started,
                    )
                ),
                "b60": (
                    prediction.p60
                    - sixty
                ) ** 2,
            }
        )

    if not scores:
        raise RuntimeError(
            "empty evaluation window"
        )

    return {
        "n": len(scores),
        "mae": mean(
            row["error"]
            for row in scores
        ),
        "app_brier": mean(
            row["app_brier"]
            for row in scores
        ),
        "app_log": mean(
            row["app_log"]
            for row in scores
        ),
        "start_brier": mean(
            row["start_brier"]
            for row in scores
        ),
        "start_log": mean(
            row["start_log"]
            for row in scores
        ),
        "b60": mean(
            row["b60"]
            for row in scores
        ),
    }


# ============================================================
# MODELS
# ============================================================

MODELS = {
    "V1": MinutesModel(
        V1_CONFIG
    ),

    "V2_COUPLED": CoupledV2(
        WEAK_CONFIG,
        time_half_life_days=30,
        offseason_gap_days=60,
        offseason_carryover=0.50,
    ),

    "V21_HURDLE": HurdleOnlyV21(
        WEAK_CONFIG,
        time_half_life_days=30,
        offseason_gap_days=60,
        offseason_carryover=0.50,
    ),
}


all_records = {}

for name, model in (
    MODELS.items()
):

    print(
        f"building {name}..."
    )

    all_records[name] = (
        make_records(
            model
        )
    )


# ============================================================
# WINDOWS
# ============================================================

WINDOWS = {
    "VALIDATION": (
        VALIDATION_START,
        VALIDATION_END,
    ),

    "FINAL": (
        FINAL_START,
        FINAL_END,
    ),
}


results = {}

for window_name, (
    start,
    end,
) in WINDOWS.items():

    for name, model in (
        MODELS.items()
    ):

        records = (
            all_records[name]
        )

        results[
            (
                window_name,
                name,
                "ALL",
            )
        ] = evaluate(
            model,
            records,
            start=start,
            end=end,
            regular_only=False,
        )

        results[
            (
                window_name,
                name,
                "REGULAR",
            )
        ] = evaluate(
            model,
            records,
            start=start,
            end=end,
            regular_only=True,
        )


# ============================================================
# REPORT
# ============================================================

lines = []

lines.append(
    "============================================================"
)
lines.append(
    "MINUTES V2.1 | HURDLE-ONLY TIME DECAY"
)
lines.append(
    "============================================================"
)

lines.append(
    "VALIDATION = 2025-08-01 .. 2025-10-15"
)

lines.append(
    "FINAL      = 2026-01-01 .. 2026-06-01"
)

lines.append("")


for group in (
    "ALL",
    "REGULAR",
):

    lines.append(
        f"=== {group} ==="
    )

    lines.append(
        f"{'WINDOW':<12}"
        f"{'MODEL':<14}"
        f"{'N':>7}"
        f"{'MAE':>9}"
        f"{'APP_BRI':>10}"
        f"{'APP_LOG':>10}"
        f"{'START_B':>10}"
        f"{'B60':>9}"
    )

    for window_name in (
        "VALIDATION",
        "FINAL",
    ):

        for model_name in (
            "V1",
            "V2_COUPLED",
            "V21_HURDLE",
        ):

            row = results[
                (
                    window_name,
                    model_name,
                    group,
                )
            ]

            lines.append(
                f"{window_name:<12}"
                f"{model_name:<14}"
                f"{row['n']:>7}"
                f"{row['mae']:>9.3f}"
                f"{row['app_brier']:>10.4f}"
                f"{row['app_log']:>10.4f}"
                f"{row['start_brier']:>10.4f}"
                f"{row['b60']:>9.4f}"
            )

    lines.append("")


# ============================================================
# EXISTING JOINT GATE ON FINAL
# ============================================================

v1 = results[
    (
        "FINAL",
        "V1",
        "ALL",
    )
]

v21 = results[
    (
        "FINAL",
        "V21_HURDLE",
        "ALL",
    )
]

v1_joint = (
    v1["start_brier"]
    + v1["b60"]
) / 2

v21_joint = (
    v21["start_brier"]
    + v21["b60"]
) / 2


existing_gate = (
    (
        v21["mae"]
        < v1["mae"] * 0.99
        and v21_joint
        <= v1_joint
    )
    or
    (
        v21_joint
        < v1_joint * 0.98
        and v21["mae"]
        <= v1["mae"]
    )
)


lines.append(
    "FINAL JOINT GATE:"
)

lines.append(
    f"  V1 MAE    = "
    f"{v1['mae']:.3f}"
)

lines.append(
    f"  V2.1 MAE  = "
    f"{v21['mae']:.3f}"
)

lines.append(
    f"  V1 joint  = "
    f"{v1_joint:.4f}"
)

lines.append(
    f"  V2.1 joint= "
    f"{v21_joint:.4f}"
)

lines.append(
    f"  appearance Brier "
    f"{v1['app_brier']:.4f}"
    f" -> "
    f"{v21['app_brier']:.4f}"
)

lines.append(
    f"  RESULT = "
    f"{'PASS' if existing_gate else 'FAIL'}"
)

lines.append("")
lines.append(
    "=== END ==="
)


report = "\n".join(
    lines
)

output = (
    ROOT
    / "scratch"
    / "decision"
    / "minutes_v21_hurdle_report.txt"
)

output.write_text(
    report + "\n",
    encoding="utf-8",
)

print()
print(
    report
)
