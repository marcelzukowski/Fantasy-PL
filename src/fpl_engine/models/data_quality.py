"""Confidence metadata for challenger models; never modifies risk-neutral EV."""

from __future__ import annotations

from dataclasses import dataclass
import math
from types import MappingProxyType
from typing import Mapping


@dataclass(frozen=True)
class DataQualitySignals:
    provider_coverage: float | None = None
    event_feature_coverage: float | None = None
    minutes_confidence: float | None = None
    talent_reliability: float | None = None
    role_certainty: float | None = None
    set_piece_certainty: float | None = None
    availability_certainty: float | None = None
    bps_completeness: float | None = None
    cross_league_certainty: float | None = None

    def __post_init__(self) -> None:
        for name, value in self.__dict__.items():
            if value is not None and (
                isinstance(value, bool) or not math.isfinite(value) or not 0 <= value <= 1
            ):
                raise ValueError(f"{name} must be in [0, 1] or NULL")


@dataclass(frozen=True)
class DataQualityAssessment:
    confidence: float
    uncertainty: float
    observed_factors: Mapping[str, float]
    missing_factors: tuple[str, ...]
    factor_coverage: float


def assess_data_quality(signals: DataQualitySignals) -> DataQualityAssessment:
    """Aggregate evidence conservatively without changing any model mean."""
    values = signals.__dict__
    observed = {name: value for name, value in values.items() if value is not None}
    missing = tuple(name for name, value in values.items() if value is None)
    coverage = len(observed) / len(values)
    if not observed:
        confidence = 0.0
    else:
        # Geometric mean prevents one weak supplied dimension being hidden by
        # several strong dimensions. Missing dimensions lower metadata only.
        geometric = math.prod(max(value, 1e-9) for value in observed.values()) ** (1 / len(observed))
        confidence = geometric * (0.5 + 0.5 * coverage)
    confidence = min(1.0, max(0.0, confidence))
    return DataQualityAssessment(
        confidence, 1.0 - confidence, MappingProxyType(observed), missing, coverage,
    )

