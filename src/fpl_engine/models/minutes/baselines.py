"""MIN-002 deterministic Minutes baselines."""

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

from fpl_engine.features.minutes_dataset import MinutesObservation, eligible_history


@dataclass(frozen=True)
class MinutesBaselinePrediction:
    model_id: str
    expected_minutes: float
    p_start: float
    p_60_plus: float


def _history(observations, player_id, fixture_id, prediction_timestamp):
    return eligible_history(
        observations,
        player_id=player_id,
        target_fixture_id=fixture_id,
        prediction_timestamp=prediction_timestamp,
    )


def previous_match_minutes(
    observations: Iterable[MinutesObservation], player_id: str, fixture_id: str, prediction_timestamp: datetime
) -> MinutesBaselinePrediction:
    rows = _history(observations, player_id, fixture_id, prediction_timestamp)
    if not rows:
        return MinutesBaselinePrediction("previous_match_minutes_v1", 45.0, 0.5, 0.5)
    last = rows[-1]
    return MinutesBaselinePrediction(
        "previous_match_minutes_v1", float(last.minutes), float(last.started), float(last.minutes >= 60)
    )


def rolling_5_minutes(
    observations: Iterable[MinutesObservation], player_id: str, fixture_id: str, prediction_timestamp: datetime
) -> MinutesBaselinePrediction:
    rows = _history(observations, player_id, fixture_id, prediction_timestamp)[-5:]
    if not rows:
        return MinutesBaselinePrediction("rolling_5_minutes_v1", 45.0, 0.5, 0.5)
    return MinutesBaselinePrediction(
        "rolling_5_minutes_v1",
        sum(row.minutes for row in rows) / len(rows),
        sum(row.started for row in rows) / len(rows),
        sum(row.minutes >= 60 for row in rows) / len(rows),
    )


def rolling_5_start_rate(
    observations: Iterable[MinutesObservation], player_id: str, fixture_id: str, prediction_timestamp: datetime
) -> MinutesBaselinePrediction:
    rows = _history(observations, player_id, fixture_id, prediction_timestamp)[-5:]
    if not rows:
        return MinutesBaselinePrediction("rolling_5_start_rate_v1", 45.0, 0.5, 0.5)
    start_rate = sum(row.started for row in rows) / len(rows)
    starter = [row.minutes for row in rows if row.started]
    bench = [row.minutes for row in rows if row.appeared and not row.started]
    starter_mean = sum(starter) / len(starter) if starter else 75.0
    bench_mean = sum(bench) / len(bench) if bench else 18.0
    return MinutesBaselinePrediction(
        "rolling_5_start_rate_v1",
        start_rate * starter_mean + (1 - start_rate) * bench_mean,
        start_rate,
        start_rate,
    )


def empirical_hurdle(
    observations: Iterable[MinutesObservation], player_id: str, fixture_id: str, prediction_timestamp: datetime
) -> MinutesBaselinePrediction:
    rows = _history(observations, player_id, fixture_id, prediction_timestamp)[-10:]
    appearances = sum(row.appeared for row in rows)
    p_appearance = (appearances + 2.0) / (len(rows) + 3.0)
    p_start_given_appearance = (sum(row.started for row in rows) + 2.0) / (appearances + 3.0)
    p_start = p_appearance * p_start_given_appearance
    start_minutes = [row.minutes for row in rows if row.started]
    bench_minutes = [row.minutes for row in rows if row.appeared and not row.started]
    starter_mean = (sum(start_minutes) + 3 * 78.0) / (len(start_minutes) + 3)
    bench_mean = (sum(bench_minutes) + 3 * 18.0) / (len(bench_minutes) + 3)
    expected = p_start * starter_mean + (p_appearance - p_start) * bench_mean
    return MinutesBaselinePrediction("empirical_hurdle_v1", expected, p_start, p_start)
