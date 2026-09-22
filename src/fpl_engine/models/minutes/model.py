"""MIN-003..006 interpretable, point-in-time Minutes hurdle model."""

from dataclasses import dataclass
from datetime import datetime, timezone
import math
from types import MappingProxyType
from typing import Iterable, Mapping

from fpl_engine.features.minutes_dataset import MinutesObservation, eligible_history
from fpl_engine.validation.leakage import (
    LeakageError,
    TargetFixtureLeakageError,
    assert_feature_record,
    assert_information_known,
    assert_snapshot_before,
)

from .calibration import MinutesCalibrationArtifact


MINUTE_BUCKETS = ("0", "1-29", "30-59", "60-69", "70-79", "80-89", "90+")


def _utc(value: datetime, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise LeakageError(f"{name} must be an aware datetime")
    return value.astimezone(timezone.utc)


def _probability(value: float | None, name: str) -> None:
    if value is not None and (isinstance(value, bool) or not 0 <= value <= 1):
        raise ValueError(f"{name} must be in [0, 1]")


@dataclass(frozen=True)
class MinutesFeatureSignal:
    """A contextual feature with its own temporal provenance."""

    name: str
    value: object
    known_at: datetime
    effective_at: datetime
    source: str
    fixture_id: str | None = None
    source_snapshot_timestamp: datetime | None = None


@dataclass(frozen=True)
class MinutesContext:
    player_id: str
    fixture_id: str
    prediction_timestamp: datetime
    position: str | None = None
    availability_probability: float | None = None
    availability_known_at: datetime | None = None
    availability_confidence: float | None = None
    confirmed_suspension: bool = False
    definitely_unavailable: bool = False
    returning_from_injury: bool = False
    rotation_risk: float | None = None
    early_substitution_risk: float | None = None
    manager_change: bool | None = None
    tactical_role_change: bool | None = None
    fixture_congestion: float | None = None
    signals: tuple[MinutesFeatureSignal, ...] = ()

    def __post_init__(self) -> None:
        if not self.player_id or not self.fixture_id:
            raise ValueError("player_id and fixture_id are required")
        _utc(self.prediction_timestamp, "prediction_timestamp")
        for name in (
            "availability_probability",
            "availability_confidence",
            "rotation_risk",
            "early_substitution_risk",
            "fixture_congestion",
        ):
            _probability(getattr(self, name), name)
        has_availability = (
            self.availability_probability is not None
            or self.confirmed_suspension
            or self.definitely_unavailable
            or self.returning_from_injury
        )
        if has_availability and self.availability_known_at is None:
            raise ValueError("availability_known_at is required for availability information")
        if self.availability_known_at is not None:
            _utc(self.availability_known_at, "availability_known_at")


@dataclass(frozen=True)
class MinutesModelConfig:
    history_matches: int = 10
    match_half_life: float = 5.0
    appearance_prior_alpha: float = 2.0
    appearance_prior_beta: float = 1.0
    start_prior_alpha: float = 2.0
    start_prior_beta: float = 2.0
    distribution_prior_weight: float = 3.0
    unknown_availability_prior: float = 0.85
    model_version: str = "minutes_hurdle_v1"
    dataset_version: str = "minutes_dataset_v1"
    feature_version: str = "minutes_features_v1"

    def __post_init__(self) -> None:
        if self.history_matches < 1 or self.match_half_life <= 0 or self.distribution_prior_weight <= 0:
            raise ValueError("invalid Minutes model configuration")
        for name in ("appearance_prior_alpha", "appearance_prior_beta", "start_prior_alpha", "start_prior_beta"):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")
        _probability(self.unknown_availability_prior, "unknown_availability_prior")


@dataclass(frozen=True)
class MinutesPrediction:
    player_id: str
    fixture_id: str
    prediction_timestamp: datetime
    p_zero_minutes: float
    p_appearance: float
    p_start: float
    p_bench_appearance: float
    expected_minutes: float
    p_60_plus: float
    p_75_plus: float
    p_90: float
    minute_bucket_distribution: Mapping[str, float]
    minute_distribution: tuple[float, ...]
    starter_minutes_distribution: tuple[float, ...]
    bench_minutes_distribution: tuple[float, ...]
    minutes_uncertainty: float
    prediction_confidence: float
    availability_confidence: float
    rotation_risk: float
    early_substitution_risk: float
    model_version: str
    dataset_version: str
    feature_version: str

    @property
    def p_zero(self) -> float:
        return self.p_zero_minutes

    @property
    def p60(self) -> float:
        return self.p_60_plus

    @property
    def p75(self) -> float:
        return self.p_75_plus

    @property
    def p90(self) -> float:
        return self.p_90


class MinutesModel:
    """A shrinkage hurdle model with an exact discrete 0..90 mixture."""

    def __init__(self, config: MinutesModelConfig = MinutesModelConfig()):
        self.config = config

    def predict(
        self,
        observations: Iterable[MinutesObservation],
        context: MinutesContext,
        *,
        calibration: MinutesCalibrationArtifact | None = None,
    ) -> MinutesPrediction:
        prediction = _utc(context.prediction_timestamp, "prediction_timestamp")
        self._validate_context(context)
        rows = eligible_history(
            observations,
            player_id=context.player_id,
            target_fixture_id=context.fixture_id,
            prediction_timestamp=prediction,
        )[-self.config.history_matches :]
        weights = self._weights(len(rows))

        appearance_evidence = sum(weight * row.appeared for row, weight in zip(rows, weights))
        total_evidence = sum(weights)
        p_appearance_history = (appearance_evidence + self.config.appearance_prior_alpha) / (
            total_evidence + self.config.appearance_prior_alpha + self.config.appearance_prior_beta
        )
        starts = sum(weight * row.started for row, weight in zip(rows, weights))
        p_start_given_appearance = (starts + self.config.start_prior_alpha) / (
            appearance_evidence + self.config.start_prior_alpha + self.config.start_prior_beta
        )

        availability = (
            context.availability_probability
            if context.availability_probability is not None
            else self.config.unknown_availability_prior
        )
        if context.confirmed_suspension or context.definitely_unavailable:
            availability = 0.0
        if context.returning_from_injury:
            availability *= 0.9
            p_start_given_appearance *= 0.85

        historical_rotation = 4 * p_start_given_appearance * (1 - p_start_given_appearance)
        rotation_risk = max(context.rotation_risk or 0.0, historical_rotation)
        explicit_rotation_penalty = 1 - 0.25 * (context.rotation_risk or 0.0)
        if context.manager_change:
            explicit_rotation_penalty *= 0.93
        if context.tactical_role_change:
            explicit_rotation_penalty *= 0.95
        if context.fixture_congestion is not None:
            explicit_rotation_penalty *= 1 - 0.08 * context.fixture_congestion

        p_appearance = min(1.0, max(0.0, p_appearance_history * availability))
        p_start = min(p_appearance, max(0.0, p_appearance * p_start_given_appearance * explicit_rotation_penalty))
        p_bench = p_appearance - p_start

        starter = self.starter_minutes_distribution(rows, weights, context)
        bench = self.bench_minutes_distribution(rows, weights)
        minute_distribution = [0.0] * 91
        minute_distribution[0] = 1 - p_appearance
        for minute in range(1, 91):
            minute_distribution[minute] = p_start * starter[minute] + p_bench * bench[minute]

        if calibration is not None:
            minute_distribution, p_start = self._calibrate(
                minute_distribution, p_start, calibration, prediction
            )
            p_appearance = 1 - minute_distribution[0]
            p_bench = p_appearance - p_start

        early_history = [weight for row, weight in zip(rows, weights) if row.started and row.minutes < 75]
        start_weight = sum(weight for row, weight in zip(rows, weights) if row.started)
        inferred_early = (sum(early_history) + 1.0) / (start_weight + 3.0)
        early_risk = max(context.early_substitution_risk or 0.0, inferred_early)
        if context.returning_from_injury:
            early_risk = max(early_risk, 0.55)
        uncertainty = self._uncertainty(
            minute_distribution,
            total_evidence,
            context,
            rotation_risk,
        )
        buckets = MappingProxyType(self._buckets(minute_distribution))
        expected = sum(minute * probability for minute, probability in enumerate(minute_distribution))
        return MinutesPrediction(
            player_id=context.player_id,
            fixture_id=context.fixture_id,
            prediction_timestamp=prediction,
            p_zero_minutes=minute_distribution[0],
            p_appearance=p_appearance,
            p_start=p_start,
            p_bench_appearance=p_bench,
            expected_minutes=expected,
            p_60_plus=sum(minute_distribution[60:]),
            p_75_plus=sum(minute_distribution[75:]),
            p_90=minute_distribution[90],
            minute_bucket_distribution=buckets,
            minute_distribution=tuple(minute_distribution),
            starter_minutes_distribution=tuple(starter),
            bench_minutes_distribution=tuple(bench),
            minutes_uncertainty=uncertainty,
            prediction_confidence=1 - uncertainty,
            availability_confidence=context.availability_confidence or 0.0,
            rotation_risk=rotation_risk,
            early_substitution_risk=early_risk,
            model_version=self.config.model_version,
            dataset_version=self.config.dataset_version,
            feature_version=self.config.feature_version,
        )

    def starter_minutes_distribution(self, rows, weights, context: MinutesContext) -> list[float]:
        position = (context.position or "UNKNOWN").upper()
        prior_center = 88 if position == "GK" else 84 if position in {"DEF", "CB"} else 76
        prior = self._kernel(prior_center, 7 if position == "GK" else 11, minimum=30)
        empirical = [0.0] * 91
        evidence = 0.0
        for row, weight in zip(rows, weights):
            if row.started:
                kernel = self._kernel(min(90, row.minutes), 4, minimum=1)
                empirical = [value + weight * item for value, item in zip(empirical, kernel)]
                evidence += weight
        combined = [
            self.config.distribution_prior_weight * p + value
            for p, value in zip(prior, empirical)
        ]
        early = context.early_substitution_risk or 0.0
        if context.returning_from_injury:
            early = max(early, 0.55)
        if early:
            early_prior = self._kernel(62, 12, minimum=30)
            blend = min(0.45, early * 0.45)
            combined = [(1 - blend) * value + blend * (evidence + self.config.distribution_prior_weight) * p for value, p in zip(combined, early_prior)]
        return self._normalise(combined, allowed=range(1, 91))

    def bench_minutes_distribution(self, rows, weights) -> list[float]:
        prior = self._kernel(18, 9, minimum=1, maximum=59)
        empirical = [0.0] * 91
        for row, weight in zip(rows, weights):
            if row.appeared and not row.started:
                kernel = self._kernel(min(59, row.minutes), 4, minimum=1, maximum=59)
                empirical = [value + weight * item for value, item in zip(empirical, kernel)]
        combined = [self.config.distribution_prior_weight * p + value for p, value in zip(prior, empirical)]
        return self._normalise(combined, allowed=range(1, 60))

    def _validate_context(self, context: MinutesContext) -> None:
        prediction = context.prediction_timestamp
        if context.availability_known_at is not None:
            assert_information_known(
                known_at=context.availability_known_at,
                prediction_timestamp=prediction,
                entity=context.player_id,
                source="availability",
            )
        for signal in context.signals:
            if signal.fixture_id == context.fixture_id:
                raise TargetFixtureLeakageError(
                    f"target fixture {context.fixture_id} supplied contextual signal {signal.name}"
                )
            assert_feature_record(
                known_at=signal.known_at,
                effective_at=signal.effective_at,
                prediction_timestamp=prediction,
                target_fixture_id=context.fixture_id,
                record_fixture_id=signal.fixture_id,
                source=signal.source,
                feature_name=signal.name,
            )
            if signal.source_snapshot_timestamp is not None:
                assert_snapshot_before(
                    snapshot_timestamp=signal.source_snapshot_timestamp,
                    prediction_timestamp=prediction,
                    source=signal.source,
                )

    def _weights(self, size: int) -> list[float]:
        return [0.5 ** ((size - 1 - index) / self.config.match_half_life) for index in range(size)]

    @staticmethod
    def _kernel(center: int, scale: float, *, minimum: int = 1, maximum: int = 90) -> list[float]:
        values = [0.0] * 91
        for minute in range(minimum, maximum + 1):
            values[minute] = math.exp(-0.5 * ((minute - center) / scale) ** 2)
        return MinutesModel._normalise(values, allowed=range(minimum, maximum + 1))

    @staticmethod
    def _normalise(values: list[float], *, allowed) -> list[float]:
        result = [0.0] * 91
        total = sum(values[index] for index in allowed)
        if total <= 0:
            raise ValueError("minutes distribution has no probability mass")
        for index in allowed:
            result[index] = values[index] / total
        return result

    @staticmethod
    def _buckets(distribution: list[float]) -> dict[str, float]:
        return {
            "0": distribution[0],
            "1-29": sum(distribution[1:30]),
            "30-59": sum(distribution[30:60]),
            "60-69": sum(distribution[60:70]),
            "70-79": sum(distribution[70:80]),
            "80-89": sum(distribution[80:90]),
            "90+": distribution[90],
        }

    @staticmethod
    def _uncertainty(distribution, evidence, context, rotation_risk) -> float:
        entropy = -sum(p * math.log(p) for p in distribution if p > 0) / math.log(91)
        sparse = 1 / (1 + evidence / 5)
        unavailable_context = 1 - (context.availability_confidence or 0.0)
        regime = 0.15 * bool(context.manager_change) + 0.1 * bool(context.tactical_role_change)
        injury = 0.2 * context.returning_from_injury
        return min(1.0, max(0.0, 0.45 * entropy + 0.2 * sparse + 0.15 * unavailable_context + 0.1 * rotation_risk + regime + injury))

    @staticmethod
    def _calibrate(distribution, p_start, artifact, prediction):
        raw_appearance = 1 - distribution[0]
        appearance = artifact.appearance.predict(raw_appearance, prediction_timestamp=prediction)
        start = min(appearance, artifact.start.predict(p_start, prediction_timestamp=prediction))
        p60 = min(appearance, artifact.sixty_plus.predict(sum(distribution[60:]), prediction_timestamp=prediction))
        p75 = min(p60, artifact.seventy_five_plus.predict(sum(distribution[75:]), prediction_timestamp=prediction))
        p90 = min(p75, artifact.ninety.predict(distribution[90], prediction_timestamp=prediction))
        masses = (([0], 1 - appearance), (list(range(1, 60)), appearance - p60), (list(range(60, 75)), p60 - p75), (list(range(75, 90)), p75 - p90), ([90], p90))
        result = [0.0] * 91
        for indexes, target_mass in masses:
            old_mass = sum(distribution[index] for index in indexes)
            if old_mass > 0:
                for index in indexes:
                    result[index] = target_mass * distribution[index] / old_mass
            elif target_mass:
                each = target_mass / len(indexes)
                for index in indexes:
                    result[index] = each
        return result, start
