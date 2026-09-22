"""MIN-002..007 chronological, expanding-window Minutes validation."""

from dataclasses import dataclass
from datetime import timedelta
import math

from fpl_engine.features.minutes_dataset import MinutesObservation

from .baselines import empirical_hurdle, previous_match_minutes, rolling_5_minutes, rolling_5_start_rate
from .calibration import MinutesCalibrationPoint, fit_minutes_calibration
from .model import MinutesContext, MinutesModel, MinutesModelConfig


@dataclass(frozen=True)
class MinutesCandidateMetrics:
    model_id: str
    fixtures: int
    mae_minutes: float
    rmse_minutes: float
    median_absolute_error: float
    brier_start: float
    log_loss_start: float
    brier_60_plus: float
    brier_75_plus: float | None
    brier_90: float | None


@dataclass(frozen=True)
class MinutesWalkForwardReport:
    candidates: tuple[MinutesCandidateMetrics, ...]
    champion_model_id: str
    prediction_fixture_order: tuple[str, ...]
    calibration_method: str


def walk_forward_minutes(
    observations: list[MinutesObservation],
    *,
    minimum_history: int = 3,
    config: MinutesModelConfig = MinutesModelConfig(),
    calibration_method: str = "platt",
    minimum_calibration_points: int = 8,
) -> MinutesWalkForwardReport:
    """Predict each fixture using only outcomes known before its kickoff."""

    if minimum_history < 0 or minimum_calibration_points < 2:
        raise ValueError("invalid validation window")
    ordered = sorted(observations, key=lambda row: (row.kickoff, row.fixture_id, row.player_id))
    names = (
        "previous_match_minutes_v1",
        "rolling_5_minutes_v1",
        "rolling_5_start_rate_v1",
        "empirical_hurdle_v1",
        config.model_version,
        f"{config.model_version}_{calibration_method}_calibrated",
    )
    scores: dict[str, list[tuple[float, ...]]] = {name: [] for name in names}
    raw_calibration: list[MinutesCalibrationPoint] = []
    fixture_order: list[str] = []
    model = MinutesModel(config)
    for target in ordered:
        prediction_timestamp = target.kickoff - timedelta(microseconds=1)
        history = [
            row
            for row in ordered
            if row.player_id == target.player_id
            and row.fixture_id != target.fixture_id
            and row.kickoff < prediction_timestamp
            and row.known_at <= prediction_timestamp
        ]
        if len(history) < minimum_history:
            continue
        fixture_order.append(target.fixture_id)
        baseline_predictions = (
            previous_match_minutes(history, target.player_id, target.fixture_id, prediction_timestamp),
            rolling_5_minutes(history, target.player_id, target.fixture_id, prediction_timestamp),
            rolling_5_start_rate(history, target.player_id, target.fixture_id, prediction_timestamp),
            empirical_hurdle(history, target.player_id, target.fixture_id, prediction_timestamp),
        )
        for item in baseline_predictions:
            scores[item.model_id].append(
                _score(target, item.expected_minutes, item.p_start, item.p_60_plus, None, None)
            )
        context = MinutesContext(
            target.player_id,
            target.fixture_id,
            prediction_timestamp,
            availability_probability=1.0,
            availability_known_at=prediction_timestamp,
            availability_confidence=1.0,
        )
        raw = model.predict(history, context)
        scores[config.model_version].append(
            _score(target, raw.expected_minutes, raw.p_start, raw.p60, raw.p75, raw.p90)
        )
        known_points = [point for point in raw_calibration if point.known_at <= prediction_timestamp]
        if len(known_points) >= minimum_calibration_points:
            artifact = fit_minutes_calibration(
                known_points, training_cutoff=prediction_timestamp, method=calibration_method
            )
            calibrated = model.predict(history, context, calibration=artifact)
            scores[names[-1]].append(
                _score(
                    target,
                    calibrated.expected_minutes,
                    calibrated.p_start,
                    calibrated.p60,
                    calibrated.p75,
                    calibrated.p90,
                )
            )
        else:
            # This is the deployable warm-up behaviour before a historical-only
            # calibrator can be fitted, keeping every candidate on identical folds.
            scores[names[-1]].append(
                _score(target, raw.expected_minutes, raw.p_start, raw.p60, raw.p75, raw.p90)
            )
        raw_calibration.append(
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
    metrics = tuple(_aggregate(name, rows) for name, rows in scores.items() if rows)
    if not metrics:
        raise ValueError("not enough observations for walk-forward validation")
    # Accuracy and calibration are joint gates. Complexity needs a material gain.
    champion = metrics[0]
    for candidate in metrics[1:]:
        incumbent_brier = (champion.brier_start + champion.brier_60_plus) / 2
        candidate_brier = (candidate.brier_start + candidate.brier_60_plus) / 2
        materially_better = (
            candidate.mae_minutes < champion.mae_minutes * 0.99 and candidate_brier <= incumbent_brier
        ) or (
            candidate_brier < incumbent_brier * 0.98 and candidate.mae_minutes <= champion.mae_minutes
        )
        if materially_better:
            champion = candidate
    return MinutesWalkForwardReport(metrics, champion.model_id, tuple(fixture_order), calibration_method)


def _score(target, expected, p_start, p60, p75, p90):
    error = abs(target.minutes - expected)
    clipped = min(1 - 1e-7, max(1e-7, p_start))
    start = float(target.started)
    return (
        error,
        error * error,
        (p_start - start) ** 2,
        -(start * math.log(clipped) + (1 - start) * math.log(1 - clipped)),
        (p60 - float(target.minutes >= 60)) ** 2,
        (p75 - float(target.minutes >= 75)) ** 2 if p75 is not None else math.nan,
        (p90 - float(target.minutes >= 90)) ** 2 if p90 is not None else math.nan,
    )


def _aggregate(name, rows):
    absolute = sorted(row[0] for row in rows)
    middle = len(absolute) // 2
    median = absolute[middle] if len(absolute) % 2 else (absolute[middle - 1] + absolute[middle]) / 2
    optional = lambda index: sum(row[index] for row in rows if not math.isnan(row[index])) / sum(
        not math.isnan(row[index]) for row in rows
    ) if any(not math.isnan(row[index]) for row in rows) else None
    return MinutesCandidateMetrics(
        name,
        len(rows),
        sum(row[0] for row in rows) / len(rows),
        math.sqrt(sum(row[1] for row in rows) / len(rows)),
        median,
        sum(row[2] for row in rows) / len(rows),
        sum(row[3] for row in rows) / len(rows),
        sum(row[4] for row in rows) / len(rows),
        optional(5),
        optional(6),
    )
