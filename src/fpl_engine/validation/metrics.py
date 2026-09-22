"""Versioned canonical metrics shared by backtests and production monitoring."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Callable, Iterable, Mapping, Sequence

import numpy as np


METRIC_REGISTRY_VERSION = "metrics_v1"


class MetricError(ValueError):
    pass


@dataclass(frozen=True)
class MetricDefinition:
    name: str
    direction: str
    function: Callable[[Sequence[float], Sequence[float]], float]


@dataclass(frozen=True)
class MetricValue:
    name: str
    value: float
    sample_size: int
    direction: str
    confidence_interval_low: float | None = None
    confidence_interval_high: float | None = None
    registry_version: str = METRIC_REGISTRY_VERSION

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class CalibrationBin:
    lower: float
    upper: float
    mean_prediction: float
    observed_rate: float
    sample_size: int


@dataclass(frozen=True)
class MetricDelta:
    name: str
    candidate_value: float
    baseline_value: float
    improvement: float
    sample_size: int
    confidence_interval_low: float | None
    confidence_interval_high: float | None
    direction: str


def _pair(actual: Sequence[float], predicted: Sequence[float]) -> tuple[np.ndarray, np.ndarray]:
    a, p = np.asarray(actual, dtype=float), np.asarray(predicted, dtype=float)
    if a.ndim != 1 or p.ndim != 1 or len(a) != len(p) or not len(a):
        raise MetricError("actual and predicted must be non-empty one-dimensional arrays of equal length")
    if not np.isfinite(a).all() or not np.isfinite(p).all():
        raise MetricError("metrics require finite values; unavailable metrics remain absent")
    return a, p


def mae(actual: Sequence[float], predicted: Sequence[float]) -> float:
    a, p = _pair(actual, predicted)
    return float(np.mean(np.abs(p - a)))


def rmse(actual: Sequence[float], predicted: Sequence[float]) -> float:
    a, p = _pair(actual, predicted)
    return float(np.sqrt(np.mean((p - a) ** 2)))


def bias(actual: Sequence[float], predicted: Sequence[float]) -> float:
    a, p = _pair(actual, predicted)
    return float(np.mean(p - a))


def brier(actual: Sequence[float], predicted: Sequence[float]) -> float:
    a, p = _pair(actual, predicted)
    if np.any((a < 0) | (a > 1)) or np.any((p < 0) | (p > 1)):
        raise MetricError("Brier score requires values in [0, 1]")
    return float(np.mean((p - a) ** 2))


def log_loss(actual: Sequence[float], predicted: Sequence[float]) -> float:
    a, p = _pair(actual, predicted)
    if np.any((a < 0) | (a > 1)) or np.any((p < 0) | (p > 1)):
        raise MetricError("log loss requires values in [0, 1]")
    clipped = np.clip(p, 1e-15, 1 - 1e-15)
    return float(-np.mean(a * np.log(clipped) + (1 - a) * np.log(1 - clipped)))


def poisson_deviance(actual: Sequence[float], predicted: Sequence[float]) -> float:
    a, p = _pair(actual, predicted)
    if np.any(a < 0) or np.any(p <= 0):
        raise MetricError("Poisson deviance requires actual >= 0 and predicted > 0")
    terms = p.copy()
    positive = a > 0
    terms[positive] = p[positive] - a[positive] + a[positive] * np.log(a[positive] / p[positive])
    return float(2 * np.mean(terms))


def poisson_nll(actual: Sequence[float], predicted: Sequence[float]) -> float:
    a, p = _pair(actual, predicted)
    if np.any(a < 0) or np.any(p <= 0):
        raise MetricError("Poisson NLL requires actual >= 0 and predicted > 0")
    return float(np.mean(p - a * np.log(p) + np.asarray([math.lgamma(value + 1) for value in a])))


def spearman(actual: Sequence[float], predicted: Sequence[float]) -> float:
    a, p = _pair(actual, predicted)
    if len(a) < 2 or np.all(a == a[0]) or np.all(p == p[0]):
        raise MetricError("Spearman correlation is unavailable for fewer than two or constant observations")
    # Average ranks preserve the standard tie semantics without another dependency.
    def ranks(values: np.ndarray) -> np.ndarray:
        order = np.argsort(values, kind="mergesort")
        result = np.empty(len(values), dtype=float)
        start = 0
        while start < len(values):
            end = start + 1
            while end < len(values) and values[order[end]] == values[order[start]]:
                end += 1
            result[order[start:end]] = (start + end - 1) / 2
            start = end
        return result
    return float(np.corrcoef(ranks(a), ranks(p))[0, 1])


def calibration(actual: Sequence[float], predicted: Sequence[float], *, bins: int = 10) -> tuple[CalibrationBin, ...]:
    a, p = _pair(actual, predicted)
    if bins < 1 or np.any((a < 0) | (a > 1)) or np.any((p < 0) | (p > 1)):
        raise MetricError("calibration requires bins >= 1 and values in [0, 1]")
    result = []
    for index in range(bins):
        lower, upper = index / bins, (index + 1) / bins
        mask = (p >= lower) & (p <= upper if index == bins - 1 else p < upper)
        if mask.any():
            result.append(CalibrationBin(lower, upper, float(np.mean(p[mask])), float(np.mean(a[mask])), int(mask.sum())))
    return tuple(result)


def calibration_error(actual: Sequence[float], predicted: Sequence[float], *, bins: int = 10) -> float:
    table = calibration(actual, predicted, bins=bins)
    total = sum(row.sample_size for row in table)
    return sum(row.sample_size * abs(row.mean_prediction - row.observed_rate) for row in table) / total


REGISTRY: Mapping[str, MetricDefinition] = {
    "mae": MetricDefinition("mae", "lower", mae),
    "rmse": MetricDefinition("rmse", "lower", rmse),
    "bias": MetricDefinition("bias", "zero", bias),
    "brier": MetricDefinition("brier", "lower", brier),
    "log_loss": MetricDefinition("log_loss", "lower", log_loss),
    "spearman": MetricDefinition("spearman", "higher", spearman),
    "poisson_deviance": MetricDefinition("poisson_deviance", "lower", poisson_deviance),
    "poisson_nll": MetricDefinition("poisson_nll", "lower", poisson_nll),
}

# Stable public names from metrics.md. Aliases retain one tested implementation.
_ALIASES = {
    "team_score_nll": ("lower", poisson_nll), "team_goal_poisson_deviance": ("lower", poisson_deviance),
    "team_cs_brier": ("lower", brier), "minutes_mae": ("lower", mae),
    "start_brier": ("lower", brier), "p60_brier": ("lower", brier),
    "future_npxg90_mae": ("lower", mae), "future_xa90_mae": ("lower", mae),
    "future_npxg90_spearman": ("higher", spearman), "future_xa90_spearman": ("higher", spearman),
    "goal_log_loss": ("lower", log_loss), "goal_brier": ("lower", brier),
    "assist_log_loss": ("lower", log_loss), "assist_brier": ("lower", brier),
    "player_cs_brier": ("lower", brier), "saves_mae": ("lower", mae),
    "saves_nll": ("lower", poisson_nll), "saves_3plus_brier": ("lower", brier),
    "defcon_mae": ("lower", mae), "defcon_threshold_brier": ("lower", brier),
    "bonus_mae": ("lower", mae), "bonus_any_brier": ("lower", brier),
    "bps_rank_quality": ("higher", spearman), "player_ev_bias": ("zero", bias),
    "player_ev_spearman": ("higher", spearman), "player_return_brier": ("lower", brier),
    "player_10plus_brier": ("lower", brier),
}
REGISTRY = {**REGISTRY, **{name: MetricDefinition(name, direction, function)
                           for name, (direction, function) in _ALIASES.items()}}

CANONICAL_COMPONENT_METRICS: Mapping[str, tuple[str, ...]] = {
    "TEAM_STRENGTH": ("team_score_nll", "team_goal_poisson_deviance", "team_cs_brier"),
    "MINUTES": ("minutes_mae", "start_brier", "p60_brier"),
    "PLAYER_TALENT": ("future_npxg90_mae", "future_xa90_mae", "future_npxg90_spearman", "future_xa90_spearman"),
    "GOALS": ("goal_log_loss", "goal_brier"), "ASSISTS": ("assist_log_loss", "assist_brier"),
    "CLEAN_SHEET": ("team_cs_brier", "player_cs_brier"),
    "SAVES": ("saves_mae", "saves_nll", "saves_3plus_brier"),
    "DEFCON": ("defcon_mae", "defcon_threshold_brier"),
    "BONUS": ("bonus_mae", "bonus_any_brier", "bps_rank_quality"),
    "PLAYER_PROJECTION": ("player_ev_bias", "player_ev_spearman", "player_return_brier", "player_10plus_brier"),
    "OPTIMIZER": ("gain_vs_roll_baseline", "gain_vs_greedy_1gw", "gain_vs_static_6gw", "decision_margin", "recommendation_stability"),
}


def metric(name: str, actual: Sequence[float], predicted: Sequence[float]) -> MetricValue:
    try:
        definition = REGISTRY[name]
    except KeyError as error:
        raise MetricError(f"unknown metric: {name}") from error
    a, p = _pair(actual, predicted)
    return MetricValue(name, definition.function(a, p), len(a), definition.direction)


def bootstrap_metric(name: str, actual: Sequence[float], predicted: Sequence[float], *,
                     blocks: Sequence[str] | None = None, samples: int = 500,
                     seed: int = 42) -> MetricValue:
    """Block bootstrap a metric; repeated block labels remain together."""
    base = metric(name, actual, predicted)
    if samples < 1:
        return base
    a, p = _pair(actual, predicted)
    labels = tuple(blocks) if blocks is not None else tuple(str(index) for index in range(len(a)))
    if len(labels) != len(a):
        raise MetricError("blocks must match observation count")
    unique = tuple(dict.fromkeys(labels))
    indices = {block: np.asarray([index for index, label in enumerate(labels) if label == block]) for block in unique}
    rng, values = np.random.default_rng(seed), []
    for _ in range(samples):
        sampled = rng.choice(unique, size=len(unique), replace=True)
        selected = np.concatenate([indices[block] for block in sampled])
        try:
            values.append(REGISTRY[name].function(a[selected], p[selected]))
        except MetricError:
            continue
    if not values:
        return base
    low, high = np.quantile(values, [.025, .975])
    return MetricValue(base.name, base.value, base.sample_size, base.direction, float(low), float(high))


def bootstrap_delta(name: str, actual: Sequence[float], candidate: Sequence[float], baseline: Sequence[float], *,
                    blocks: Sequence[str] | None = None, samples: int = 500, seed: int = 42) -> MetricDelta:
    candidate_value, baseline_value = metric(name, actual, candidate), metric(name, actual, baseline)
    if candidate_value.direction == "lower":
        improve = lambda c, b: b - c
    elif candidate_value.direction == "higher":
        improve = lambda c, b: c - b
    else:
        improve = lambda c, b: abs(b) - abs(c)
    improvement = improve(candidate_value.value, baseline_value.value)
    a, c = _pair(actual, candidate)
    _, b = _pair(actual, baseline)
    labels = tuple(blocks) if blocks is not None else tuple(str(index) for index in range(len(a)))
    if len(labels) != len(a):
        raise MetricError("blocks must match observation count")
    unique = tuple(dict.fromkeys(labels))
    indices = {block: np.asarray([index for index, label in enumerate(labels) if label == block]) for block in unique}
    rng, deltas = np.random.default_rng(seed), []
    for _ in range(max(0, samples)):
        selected = np.concatenate([indices[block] for block in rng.choice(unique, len(unique), replace=True)])
        try:
            deltas.append(improve(REGISTRY[name].function(a[selected], c[selected]),
                                  REGISTRY[name].function(a[selected], b[selected])))
        except MetricError:
            continue
    low, high = (tuple(float(value) for value in np.quantile(deltas, [.025, .975])) if deltas else (None, None))
    return MetricDelta(name, candidate_value.value, baseline_value.value, improvement, len(a), low, high,
                       candidate_value.direction)

