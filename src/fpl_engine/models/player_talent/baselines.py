"""TAL-002 exposure-aware Player Talent baselines."""

from dataclasses import dataclass
from datetime import datetime, timezone
import math

from fpl_engine.features.player_talent_dataset import PlayerPerformanceObservation, eligible_talent_history


@dataclass(frozen=True)
class TalentBaseline:
    model_id: str
    npxg_per90: float | None
    xa_per90: float | None
    shots_per90: float | None


def _rates(rows, weights=None):
    weights = weights or [1.0] * len(rows)
    def rate(field):
        selected = [(row, weight) for row, weight in zip(rows, weights) if getattr(row, field) is not None and row.minutes > 0]
        denominator = sum(row.minutes * weight for row, weight in selected)
        return sum(getattr(row, field) * weight for row, weight in selected) * 90 / denominator if denominator else None
    return rate("npxg"), rate("xa"), rate("shots")


def season_to_date_per90(observations, player_id, fixture_id, prediction_timestamp):
    rows = eligible_talent_history(observations, player_id=player_id, target_fixture_id=fixture_id, prediction_timestamp=prediction_timestamp)
    values = _rates(rows)
    return TalentBaseline("season_to_date_per90_v1", *values)


def exponentially_weighted_per90(observations, player_id, fixture_id, prediction_timestamp, *, half_life_days=120):
    rows = eligible_talent_history(observations, player_id=player_id, target_fixture_id=fixture_id, prediction_timestamp=prediction_timestamp)
    at = prediction_timestamp.astimezone(timezone.utc)
    weights = [0.5 ** ((at - row.kickoff.astimezone(timezone.utc)).total_seconds() / 86400 / half_life_days) for row in rows]
    return TalentBaseline("exponentially_weighted_per90_v1", *_rates(rows, weights))
