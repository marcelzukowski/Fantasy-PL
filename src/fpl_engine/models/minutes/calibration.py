"""MIN-007 time-frozen Platt and isotonic probability calibration."""

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
from pathlib import Path

import numpy as np
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression

from fpl_engine.validation.leakage import FutureInformationError, LeakageError, assert_information_known


@dataclass(frozen=True)
class CalibrationPoint:
    probability: float
    observed: bool
    known_at: datetime


@dataclass(frozen=True)
class ProbabilityCalibrator:
    method: str
    trained_through: datetime
    x: tuple[float, ...]
    y: tuple[float, ...]

    def predict(self, probability: float, *, prediction_timestamp: datetime) -> float:
        assert_information_known(
            known_at=self.trained_through,
            prediction_timestamp=prediction_timestamp,
            entity="minutes calibration artifact",
            source=self.method,
        )
        p = min(1.0, max(0.0, float(probability)))
        if self.method == "constant":
            return self.y[0]
        if self.method == "platt":
            logit = math.log(min(1 - 1e-7, max(1e-7, p)) / (1 - min(1 - 1e-7, max(1e-7, p))))
            return 1.0 / (1.0 + math.exp(-(self.x[0] * logit + self.y[0])))
        return float(np.interp(p, self.x, self.y))


def fit_probability_calibrator(
    points: list[CalibrationPoint], *, training_cutoff: datetime, method: str = "platt"
) -> ProbabilityCalibrator:
    if method not in {"platt", "isotonic"}:
        raise ValueError("method must be platt or isotonic")
    if not points:
        raise ValueError("at least one calibration point is required")
    if training_cutoff.tzinfo is None or training_cutoff.utcoffset() is None:
        raise LeakageError("training_cutoff must be an aware datetime")
    cutoff = training_cutoff.astimezone(timezone.utc)
    for point in points:
        if not 0 <= point.probability <= 1:
            raise ValueError("calibration probabilities must be in [0, 1]")
        assert_information_known(
            known_at=point.known_at,
            prediction_timestamp=cutoff,
            entity="calibration outcome",
            source="minutes_validation",
        )
    trained_through = max(point.known_at.astimezone(timezone.utc) for point in points)
    labels = np.array([int(point.observed) for point in points])
    if len(set(labels.tolist())) == 1:
        return ProbabilityCalibrator("constant", trained_through, (), (float(labels[0]),))
    probabilities = np.array([point.probability for point in points], dtype=float)
    if method == "platt":
        clipped = np.clip(probabilities, 1e-7, 1 - 1e-7)
        logits = np.log(clipped / (1 - clipped)).reshape(-1, 1)
        estimator = LogisticRegression(random_state=0, solver="lbfgs").fit(logits, labels)
        return ProbabilityCalibrator(
            "platt", trained_through, (float(estimator.coef_[0, 0]),), (float(estimator.intercept_[0]),)
        )
    estimator = IsotonicRegression(out_of_bounds="clip").fit(probabilities, labels)
    return ProbabilityCalibrator(
        "isotonic",
        trained_through,
        tuple(float(value) for value in estimator.X_thresholds_),
        tuple(float(value) for value in estimator.y_thresholds_),
    )


@dataclass(frozen=True)
class MinutesCalibrationArtifact:
    appearance: ProbabilityCalibrator
    start: ProbabilityCalibrator
    sixty_plus: ProbabilityCalibrator
    seventy_five_plus: ProbabilityCalibrator
    ninety: ProbabilityCalibrator

    @property
    def trained_through(self) -> datetime:
        return max(
            item.trained_through
            for item in (self.appearance, self.start, self.sixty_plus, self.seventy_five_plus, self.ninety)
        )


@dataclass(frozen=True)
class MinutesCalibrationPoint:
    p_appearance: float
    p_start: float
    p_60_plus: float
    p_75_plus: float
    p_90: float
    appeared: bool
    started: bool
    minutes: int
    known_at: datetime


def fit_minutes_calibration(
    points: list[MinutesCalibrationPoint], *, training_cutoff: datetime, method: str = "platt"
) -> MinutesCalibrationArtifact:
    """Fit all threshold calibrators from outcomes known by one cutoff."""

    def series(probability: str, outcome) -> list[CalibrationPoint]:
        return [
            CalibrationPoint(getattr(point, probability), bool(outcome(point)), point.known_at)
            for point in points
        ]

    return MinutesCalibrationArtifact(
        appearance=fit_probability_calibrator(
            series("p_appearance", lambda p: p.appeared), training_cutoff=training_cutoff, method=method
        ),
        start=fit_probability_calibrator(
            series("p_start", lambda p: p.started), training_cutoff=training_cutoff, method=method
        ),
        sixty_plus=fit_probability_calibrator(
            series("p_60_plus", lambda p: p.minutes >= 60), training_cutoff=training_cutoff, method=method
        ),
        seventy_five_plus=fit_probability_calibrator(
            series("p_75_plus", lambda p: p.minutes >= 75), training_cutoff=training_cutoff, method=method
        ),
        ninety=fit_probability_calibrator(
            series("p_90", lambda p: p.minutes >= 90), training_cutoff=training_cutoff, method=method
        ),
    )


def save_minutes_calibration(artifact: MinutesCalibrationArtifact, path: Path) -> None:
    """Persist a calibration artifact without serialising sklearn objects."""

    def encoded(item: ProbabilityCalibrator) -> dict[str, object]:
        return {
            "method": item.method,
            "trained_through": item.trained_through.astimezone(timezone.utc).isoformat(),
            "x": list(item.x),
            "y": list(item.y),
        }

    payload = {
        "artifact_version": "minutes_calibration_v1",
        **{
            name: encoded(getattr(artifact, name))
            for name in ("appearance", "start", "sixty_plus", "seventy_five_plus", "ninety")
        },
    }
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")), encoding="utf-8")


def load_minutes_calibration(path: Path) -> MinutesCalibrationArtifact:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("artifact_version") != "minutes_calibration_v1":
        raise ValueError("unsupported Minutes calibration artifact version")

    def decoded(name: str) -> ProbabilityCalibrator:
        item = payload[name]
        return ProbabilityCalibrator(
            str(item["method"]),
            datetime.fromisoformat(str(item["trained_through"])).astimezone(timezone.utc),
            tuple(float(value) for value in item["x"]),
            tuple(float(value) for value in item["y"]),
        )

    return MinutesCalibrationArtifact(
        decoded("appearance"),
        decoded("start"),
        decoded("sixty_plus"),
        decoded("seventy_five_plus"),
        decoded("ninety"),
    )
