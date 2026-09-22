from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean, median

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

MINIMUM_HISTORY = 3
MINIMUM_CALIBRATION_POINTS = 8

# Development:
# calibrator trained only on outcomes known before Jan 2025,
# score Jan-May 2025.
DEV_CUTOFF = datetime(
    2025, 1, 1,
    tzinfo=timezone.utc,
)
DEV_END = datetime(
    2025, 6, 1,
    tzinfo=timezone.utc,
)

# Genuine season-boundary holdout.
# Nothing from Aug-Oct 2025 is used to choose the candidate.
HOLDOUT_CUTOFF = datetime(
    2025, 8, 1,
    tzinfo=timezone.utc,
)
HOLDOUT_END = datetime(
    2025, 10, 15,
    tzinfo=timezone.utc,
)

LOAD_AT = datetime(
    2026, 9, 12,
    12, 0,
    tzinfo=timezone.utc,
)


# ============================================================
# V2 challenger
# ============================================================

class TimeDecayMinutesModel(MinutesModel):

    def __init__(
        self,
        config: MinutesModelConfig,
        *,
        time_half_life_days: float,
        offseason_gap_days: float = 60.0,
        offseason_carryover: float = 0.5,
    ):

        super().__init__(
            config
        )

        if time_half_life_days <= 0:
            raise ValueError(
                "time_half_life_days "
                "must be positive"
            )

        if offseason_gap_days <= 0:
            raise ValueError(
                "offseason_gap_days "
                "must be positive"
            )

        if not (
            0 < offseason_carryover <= 1
        ):
            raise ValueError(
                "offseason_carryover "
                "must be in (0,1]"
            )

        self.time_half_life_days = (
            float(
                time_half_life_days
            )
        )

        self.offseason_gap_days = (
            float(
                offseason_gap_days
            )
        )

        self.offseason_carryover = (
            float(
                offseason_carryover
            )
        )

        self._v2_rows = None
        self._v2_prediction = None


    def predict(
        self,
        observations,
        context,
        *,
        calibration=None,
    ):

        prediction = (
            context
            .prediction_timestamp
            .astimezone(
                timezone.utc
            )
        )

        rows = eligible_history(
            observations,
            player_id=(
                context.player_id
            ),
            target_fixture_id=(
                context.fixture_id
            ),
            prediction_timestamp=(
                prediction
            ),
        )[
            -self.config.history_matches:
        ]

        self._v2_rows = tuple(
            rows
        )

        self._v2_prediction = (
            prediction
        )

        try:

            return super().predict(
                observations,
                context,
                calibration=calibration,
            )

        finally:

            self._v2_rows = None
            self._v2_prediction = None


    def _weights(
        self,
        size: int,
    ) -> list[float]:

        rows = self._v2_rows
        prediction = (
            self._v2_prediction
        )

        if (
            rows is None
            or prediction is None
        ):
            raise RuntimeError(
                "V2 weight context "
                "is unavailable"
            )

        if len(rows) != size:
            raise RuntimeError(
                "V2 history size mismatch"
            )

        weights = []

        for row in rows:

            kickoff = (
                row.kickoff
                .astimezone(
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

            weights.append(
                0.5 ** (
                    age_days
                    / self.time_half_life_days
                )
            )

        # Find the most recent long break.
        #
        # Because MinutesObservation contains a row for
        # zero-minute fixtures too, a ~60+ day break is
        # normally a competition/off-season boundary rather
        # than an injury absence.
        boundary = None

        for index, row in enumerate(
            rows
        ):

            current = (
                row.kickoff
                .astimezone(
                    timezone.utc
                )
            )

            if index + 1 < len(rows):

                nxt = (
                    rows[index + 1]
                    .kickoff
                    .astimezone(
                        timezone.utc
                    )
                )

            else:

                nxt = prediction

            gap_days = (
                nxt
                - current
            ).total_seconds() / 86400.0

            if (
                gap_days
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
# Candidate definitions
# ============================================================

@dataclass(frozen=True)
class Candidate:
    name: str
    half_life: float | None
    carryover: float | None
    prior_kind: str


def config_for(
    candidate: Candidate,
):

    if candidate.name == "V1":

        return MinutesModelConfig()

    if candidate.prior_kind == "weak":

        app_a = 1.0
        app_b = 0.5

        start_a = 1.0
        start_b = 1.0

    elif candidate.prior_kind == "regular":

        app_a = 1.8
        app_b = 0.2

        start_a = 1.5
        start_b = 0.5

    else:

        raise ValueError(
            candidate.prior_kind
        )

    return MinutesModelConfig(
        history_matches=20,
        match_half_life=5.0,
        appearance_prior_alpha=app_a,
        appearance_prior_beta=app_b,
        start_prior_alpha=start_a,
        start_prior_beta=start_b,
        distribution_prior_weight=3.0,
        unknown_availability_prior=0.85,
        model_version=(
            "minutes_time_decay_v2_"
            + candidate.name
        ),
        dataset_version=(
            "minutes_dataset_v1"
        ),
        feature_version=(
            "minutes_time_decay_features_v2"
        ),
    )


CANDIDATES = [
    Candidate(
        "V1",
        None,
        None,
        "v1",
    ),
]

for prior in (
    "weak",
    "regular",
):

    for half_life in (
        30.0,
        45.0,
        60.0,
    ):

        for carryover in (
            0.25,
            0.50,
        ):

            CANDIDATES.append(
                Candidate(
                    (
                        f"V2_H{int(half_life)}"
                        f"_C{int(carryover*100)}"
                        f"_{prior.upper()}"
                    ),
                    half_life,
                    carryover,
                    prior,
                )
            )


def build_model(
    candidate: Candidate,
):

    config = config_for(
        candidate
    )

    if candidate.name == "V1":

        return MinutesModel(
            config
        )

    return TimeDecayMinutesModel(
        config,
        time_half_life_days=(
            candidate.half_life
        ),
        offseason_gap_days=60.0,
        offseason_carryover=(
            candidate.carryover
        ),
    )


# ============================================================
# Historical data
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

for player_rows in (
    historical.minutes.values()
):

    observations.extend(
        player_rows
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


# ============================================================
# Prediction records
# ============================================================

@dataclass
class PredictionRecord:
    target: MinutesObservation
    history: tuple[
        MinutesObservation,
        ...
    ]
    context: MinutesContext
    raw: object


def make_records(
    candidate: Candidate,
):

    model = build_model(
        candidate
    )

    output = []

    for player_id, rows in (
        by_player.items()
    ):

        ordered = sorted(
            rows,
            key=lambda row: (
                row.kickoff,
                row.fixture_id,
            ),
        )

        for target in ordered:

            prediction_timestamp = (
                target.kickoff
                - timedelta(
                    microseconds=1
                )
            )

            history = [
                row
                for row in ordered
                if (
                    row.fixture_id
                    != target.fixture_id
                    and row.kickoff
                    < prediction_timestamp
                    and row.known_at
                    <= prediction_timestamp
                )
            ]

            if (
                len(history)
                < MINIMUM_HISTORY
            ):
                continue

            context = MinutesContext(
                target.player_id,
                target.fixture_id,
                prediction_timestamp,
                availability_probability=1.0,
                availability_known_at=(
                    prediction_timestamp
                ),
                availability_confidence=1.0,
            )

            raw = model.predict(
                history,
                context,
            )

            output.append(
                PredictionRecord(
                    target=target,
                    history=tuple(
                        history
                    ),
                    context=context,
                    raw=raw,
                )
            )

    output.sort(
        key=lambda row: (
            row.target.kickoff,
            row.target.fixture_id,
            row.target.player_id,
        )
    )

    return model, output


# ============================================================
# Calibration + scoring
# ============================================================

def calibration_points(
    records,
    cutoff,
):

    points = []

    for record in records:

        target = record.target

        if target.known_at > cutoff:
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

    return points


def score_prediction(
    target,
    prediction,
):

    p_start = min(
        1 - 1e-7,
        max(
            1e-7,
            prediction.p_start,
        ),
    )

    actual_start = float(
        target.started
    )

    error = abs(
        target.minutes
        - prediction.expected_minutes
    )

    return {
        "abs": error,
        "sq": error * error,
        "brier_start": (
            prediction.p_start
            - actual_start
        ) ** 2,
        "logloss_start": -(
            actual_start
            * math.log(
                p_start
            )
            + (
                1
                - actual_start
            )
            * math.log(
                1
                - p_start
            )
        ),
        "brier60": (
            prediction.p60
            - float(
                target.minutes >= 60
            )
        ) ** 2,
        "brier75": (
            prediction.p75
            - float(
                target.minutes >= 75
            )
        ) ** 2,
        "brier90": (
            prediction.p90
            - float(
                target.minutes >= 90
            )
        ) ** 2,
    }


def aggregate(
    scores,
):

    if not scores:
        raise RuntimeError(
            "empty score window"
        )

    return {
        "n": len(scores),
        "mae": mean(
            row["abs"]
            for row in scores
        ),
        "rmse": math.sqrt(
            mean(
                row["sq"]
                for row in scores
            )
        ),
        "median": median(
            row["abs"]
            for row in scores
        ),
        "brier_start": mean(
            row["brier_start"]
            for row in scores
        ),
        "logloss_start": mean(
            row["logloss_start"]
            for row in scores
        ),
        "brier60": mean(
            row["brier60"]
            for row in scores
        ),
        "brier75": mean(
            row["brier75"]
            for row in scores
        ),
        "brier90": mean(
            row["brier90"]
            for row in scores
        ),
    }


def evaluate_window(
    candidate,
    model,
    records,
    *,
    calibration_cutoff,
    score_start,
    score_end,
):

    points = calibration_points(
        records,
        calibration_cutoff,
    )

    if (
        len(points)
        < MINIMUM_CALIBRATION_POINTS
    ):

        raise RuntimeError(
            f"{candidate.name}: "
            "not enough calibration points"
        )

    artifact = (
        fit_minutes_calibration(
            points,
            training_cutoff=(
                calibration_cutoff
            ),
            method="platt",
        )
    )

    scores = []

    for record in records:

        target = record.target

        if not (
            score_start
            <= target.kickoff
            < score_end
        ):
            continue

        calibrated = model.predict(
            record.history,
            record.context,
            calibration=artifact,
        )

        scores.append(
            score_prediction(
                target,
                calibrated,
            )
        )

    return aggregate(
        scores
    )


# ============================================================
# Run candidates
# ============================================================

results = {}

for index, candidate in enumerate(
    CANDIDATES,
    start=1,
):

    print(
        f"[{index}/{len(CANDIDATES)}] "
        f"{candidate.name}"
    )

    model, records = (
        make_records(
            candidate
        )
    )

    dev = evaluate_window(
        candidate,
        model,
        records,
        calibration_cutoff=(
            DEV_CUTOFF
        ),
        score_start=(
            DEV_CUTOFF
        ),
        score_end=(
            DEV_END
        ),
    )

    holdout = evaluate_window(
        candidate,
        model,
        records,
        calibration_cutoff=(
            HOLDOUT_CUTOFF
        ),
        score_start=(
            HOLDOUT_CUTOFF
        ),
        score_end=(
            HOLDOUT_END
        ),
    )

    results[
        candidate.name
    ] = {
        "candidate": candidate,
        "dev": dev,
        "holdout": holdout,
    }


# ============================================================
# Development selection
# ============================================================

v1_dev = results[
    "V1"
]["dev"]

v1_brier = (
    v1_dev["brier_start"]
    + v1_dev["brier60"]
) / 2


def passes_dev_gate(
    metrics,
):

    candidate_brier = (
        metrics["brier_start"]
        + metrics["brier60"]
    ) / 2

    return (
        (
            metrics["mae"]
            < v1_dev["mae"]
            * 0.99
            and candidate_brier
            <= v1_brier
        )
        or
        (
            candidate_brier
            < v1_brier
            * 0.98
            and metrics["mae"]
            <= v1_dev["mae"]
        )
    )


promotable = []

for name, result in (
    results.items()
):

    if name == "V1":
        continue

    if passes_dev_gate(
        result["dev"]
    ):

        brier = (
            result["dev"][
                "brier_start"
            ]
            + result["dev"][
                "brier60"
            ]
        ) / 2

        composite = (
            result["dev"]["mae"]
            / v1_dev["mae"]
            + brier
            / v1_brier
        )

        promotable.append(
            (
                composite,
                name,
            )
        )


promotable.sort()

winner_name = (
    promotable[0][1]
    if promotable
    else None
)


# ============================================================
# Report
# ============================================================

report = []

report.append(
    "============================================================"
)
report.append(
    "MINUTES V2 | HISTORICAL CHALLENGER"
)
report.append(
    "============================================================"
)

report.append(
    f"observations={len(observations)} "
    f"players={len(by_player)}"
)

report.append(
    "DEV: 2025-01-01 .. 2025-06-01"
)

report.append(
    "HOLDOUT: 2025-08-01 .. 2025-10-15"
)

report.append("")

report.append(
    f"{'MODEL':<26}"
    f"{'D_MAE':>8}"
    f"{'D_BRI':>8}"
    f"{'H_MAE':>8}"
    f"{'H_BRI':>8}"
    f"{'H_LOG':>8}"
    f"{'GATE':>7}"
)

ordered_names = [
    "V1"
]

ordered_names.extend(
    sorted(
        (
            name
            for name in results
            if name != "V1"
        ),
        key=lambda name: (
            results[name]["dev"][
                "mae"
            ],
            (
                results[name]["dev"][
                    "brier_start"
                ]
                + results[name]["dev"][
                    "brier60"
                ]
            ) / 2,
            name,
        ),
    )
)

for name in ordered_names:

    dev = results[name]["dev"]
    hold = (
        results[name]["holdout"]
    )

    dev_brier = (
        dev["brier_start"]
        + dev["brier60"]
    ) / 2

    hold_brier = (
        hold["brier_start"]
        + hold["brier60"]
    ) / 2

    gate = (
        "-"
        if name == "V1"
        else (
            "PASS"
            if passes_dev_gate(dev)
            else "FAIL"
        )
    )

    report.append(
        f"{name:<26}"
        f"{dev['mae']:>8.3f}"
        f"{dev_brier:>8.4f}"
        f"{hold['mae']:>8.3f}"
        f"{hold_brier:>8.4f}"
        f"{hold['logloss_start']:>8.4f}"
        f"{gate:>7}"
    )


report.append("")

if winner_name is None:

    report.append(
        "DEV WINNER: NONE"
    )

    report.append(
        "No V2 candidate cleared "
        "the existing material-gain gate."
    )

else:

    report.append(
        f"DEV WINNER: {winner_name}"
    )

    v1_hold = (
        results["V1"]["holdout"]
    )

    win_hold = (
        results[
            winner_name
        ]["holdout"]
    )

    v1_hold_brier = (
        v1_hold["brier_start"]
        + v1_hold["brier60"]
    ) / 2

    win_hold_brier = (
        win_hold["brier_start"]
        + win_hold["brier60"]
    ) / 2

    holdout_gate = (
        (
            win_hold["mae"]
            < v1_hold["mae"]
            * 0.99
            and win_hold_brier
            <= v1_hold_brier
        )
        or
        (
            win_hold_brier
            < v1_hold_brier
            * 0.98
            and win_hold["mae"]
            <= v1_hold["mae"]
        )
    )

    report.append(
        "HOLDOUT vs V1:"
    )

    report.append(
        f"  MAE   "
        f"{v1_hold['mae']:.3f}"
        f" -> "
        f"{win_hold['mae']:.3f}"
        f" "
        f"({win_hold['mae']-v1_hold['mae']:+.3f})"
    )

    report.append(
        f"  BRIER "
        f"{v1_hold_brier:.4f}"
        f" -> "
        f"{win_hold_brier:.4f}"
        f" "
        f"({win_hold_brier-v1_hold_brier:+.4f})"
    )

    report.append(
        f"  RESULT: "
        f"{'PASS' if holdout_gate else 'FAIL'}"
    )


report.append("")
report.append(
    "=== END ==="
)

text = "\n".join(
    report
)

output = (
    ROOT
    / "scratch"
    / "decision"
    / "minutes_v2_candidate_report.txt"
)

output.write_text(
    text + "\n",
    encoding="utf-8",
)

print()
print(text)
