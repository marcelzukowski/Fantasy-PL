"""Temporal development diagnostics for advanced Player Talent challengers."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import timedelta
import math
from typing import Iterable

from fpl_engine.features.player_talent_dataset import PlayerPerformanceObservation
from fpl_engine.models.player_talent import PlayerTalentModel, PlayerTalentV2
from fpl_engine.models.player_talent.baselines import (
    exponentially_weighted_per90, season_to_date_per90,
)
from fpl_engine.validation.metrics import MetricError, spearman


@dataclass(frozen=True)
class AdvancedRateMetrics:
    observations: int
    mae: float
    rmse: float
    bias: float
    spearman: float | None
    predicted_to_observed_ratio: float | None


@dataclass(frozen=True)
class AdvancedTalentCandidate:
    model_id: str
    xa: AdvancedRateMetrics | None
    npxg: AdvancedRateMetrics | None
    shots: AdvancedRateMetrics | None


@dataclass(frozen=True)
class AdvancedTalentWalkForwardReport:
    candidates: tuple[AdvancedTalentCandidate, ...]
    prediction_order: tuple[tuple[str, str], ...]
    minimum_history: int
    leakage_violations: int = 0


def walk_forward_advanced_talent(
    observations: Iterable[PlayerPerformanceObservation], *, minimum_history: int = 2,
) -> AdvancedTalentWalkForwardReport:
    """Compare frozen baselines, V1 and V2 with only prior player fixtures.

    Target minutes are used solely to put a pre-match per-90 prediction on the
    same exposure scale as the observed event count. They never enter model
    fitting or prediction.
    """
    if minimum_history < 1:
        raise ValueError("minimum_history must be positive")
    grouped: dict[str, list[PlayerPerformanceObservation]] = defaultdict(list)
    all_rows = list(observations)
    for row in all_rows:
        grouped[row.player_id].append(row)
    names = (
        "season_to_date_per90_v1", "exponentially_weighted_per90_v1",
        "player_talent_empirical_bayes_v1", "player_talent_reliability_v2",
    )
    values = {name: {field: [] for field in ("xa", "npxg", "shots")} for name in names}
    order = []
    v1, v2 = PlayerTalentModel(), PlayerTalentV2()
    for target in sorted(all_rows, key=lambda row: (row.kickoff, row.fixture_id, row.player_id)):
        player_id = target.player_id
        prediction_timestamp = target.kickoff - timedelta(microseconds=1)
        history = [
            row for row in grouped[player_id]
            if row.fixture_id != target.fixture_id and row.kickoff < prediction_timestamp
            and row.known_at <= prediction_timestamp
        ]
        if len(history) < minimum_history:
            continue
        order.append((target.fixture_id, target.player_id))
        std = season_to_date_per90(
            history, player_id, target.fixture_id, prediction_timestamp,
        )
        exp = exponentially_weighted_per90(
            history, player_id, target.fixture_id, prediction_timestamp,
        )
        old = v1.predict(
            history, player_id=player_id, target_fixture_id=target.fixture_id,
            prediction_timestamp=prediction_timestamp, current_team_id=target.team_id,
            current_competition_id=target.competition_id,
            fpl_position=target.fpl_position,
        )
        new = v2.predict(
            history, player_id=player_id, target_fixture_id=target.fixture_id,
            prediction_timestamp=prediction_timestamp, current_team_id=target.team_id,
            current_competition_id=target.competition_id,
            fpl_position=target.fpl_position,
        )
        candidates = {
            std.model_id: (std.xa_per90, std.npxg_per90, std.shots_per90),
            exp.model_id: (exp.xa_per90, exp.npxg_per90, exp.shots_per90),
            old.model_version: (
                old.talent_xa_per90, old.talent_npxg_per90, old.talent_shots_per90,
            ),
            new.model_version: (
                new.talent_xa_per90, new.talent_npxg_per90, new.talent_shots_per90,
            ),
        }
        scale = target.minutes / 90
        actuals = (target.xa, target.npxg, target.shots)
        for name, predictions in candidates.items():
            for field, actual, prediction in zip(("xa", "npxg", "shots"), actuals, predictions):
                if actual is not None and prediction is not None:
                    values[name][field].append((float(actual), float(prediction) * scale))
    if not order:
        raise ValueError("not enough observations for advanced temporal validation")
    results = tuple(AdvancedTalentCandidate(
        name, _metrics(values[name]["xa"]), _metrics(values[name]["npxg"]),
        _metrics(values[name]["shots"]),
    ) for name in names)
    return AdvancedTalentWalkForwardReport(
        results, tuple(order), minimum_history,
    )


def _metrics(rows: list[tuple[float, float]]) -> AdvancedRateMetrics | None:
    if not rows:
        return None
    actual, predicted = zip(*rows)
    errors = [estimate - observed for observed, estimate in rows]
    observed_total = sum(actual)
    try:
        rank = spearman(actual, predicted)
    except MetricError:
        rank = None
    return AdvancedRateMetrics(
        len(rows), sum(abs(value) for value in errors) / len(rows),
        math.sqrt(sum(value * value for value in errors) / len(rows)),
        sum(errors) / len(rows), rank,
        sum(predicted) / observed_total if observed_total > 0 else None,
    )
