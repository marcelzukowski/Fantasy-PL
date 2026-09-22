"""Chronological V1 baseline/challenger evaluation for Player Talent."""

from dataclasses import dataclass
from datetime import timedelta

from fpl_engine.features.player_talent_dataset import PlayerPerformanceObservation

from .baselines import exponentially_weighted_per90, season_to_date_per90
from .model import CORE_PRIORS, PlayerTalentConfig, PlayerTalentModel


@dataclass(frozen=True)
class TalentCandidateMetrics:
    model_id: str
    fixtures: int
    mae_npxg: float | None
    mae_xa: float | None
    mae_shots: float | None
    mean_absolute_error: float


@dataclass(frozen=True)
class TalentSegmentResult:
    segment: str
    fixtures: int
    mean_absolute_error: float


@dataclass(frozen=True)
class TalentWalkForwardReport:
    candidates: tuple[TalentCandidateMetrics, ...]
    champion_model_id: str
    prediction_fixture_order: tuple[str, ...]
    challenger_segments: tuple[TalentSegmentResult, ...]


def walk_forward_talent(
    observations: list[PlayerPerformanceObservation], *, minimum_history: int = 2,
    config: PlayerTalentConfig = PlayerTalentConfig(),
) -> TalentWalkForwardReport:
    ordered = sorted(observations, key=lambda row: (row.kickoff, row.fixture_id, row.player_id))
    names = ("season_to_date_per90_v1", "exponentially_weighted_per90_v1", config.model_version)
    scores = {name: [] for name in names}
    segments: list[tuple[str, float]] = []
    fixture_order = []
    model = PlayerTalentModel(config)
    for target in ordered:
        prediction = target.kickoff - timedelta(microseconds=1)
        history = [row for row in ordered if row.player_id == target.player_id and row.fixture_id != target.fixture_id and row.kickoff < prediction and row.known_at <= prediction]
        if len(history) < minimum_history:
            continue
        fixture_order.append(target.fixture_id)
        baselines = (
            season_to_date_per90(history, target.player_id, target.fixture_id, prediction),
            exponentially_weighted_per90(history, target.player_id, target.fixture_id, prediction, half_life_days=config.half_life_days),
        )
        for baseline in baselines:
            scores[baseline.model_id].append(_errors(target, baseline.npxg_per90, baseline.xa_per90, baseline.shots_per90))
        challenger = model.predict(
            history, player_id=target.player_id, target_fixture_id=target.fixture_id,
            prediction_timestamp=prediction, current_team_id=target.team_id,
            current_competition_id=target.competition_id, fpl_position=target.fpl_position,
        )
        errors = _errors(target, challenger.talent_npxg_per90, challenger.talent_xa_per90, challenger.talent_shots_per90)
        scores[config.model_version].append(errors)
        changed_team = any(row.team_id != target.team_id for row in history)
        changed_role = any(row.tactical_role != target.tactical_role for row in history)
        segment = "transfer" if changed_team else "role_change" if changed_role else "low_sample" if len(history) < 5 else "established"
        segments.append((segment, _mean_available(errors)))
    metrics = tuple(_aggregate(name, values) for name, values in scores.items() if values)
    if not metrics:
        raise ValueError("not enough observations for Player Talent walk-forward validation")
    champion = metrics[0]
    for candidate in metrics[1:]:
        if candidate.mean_absolute_error < champion.mean_absolute_error * 0.99:
            champion = candidate
    segment_results = tuple(
        TalentSegmentResult(name, sum(segment == name for segment, _ in segments), sum(value for segment, value in segments if segment == name) / sum(segment == name for segment, _ in segments))
        for name in ("established", "low_sample", "transfer", "role_change") if any(segment == name for segment, _ in segments)
    )
    return TalentWalkForwardReport(metrics, champion.model_id, tuple(fixture_order), segment_results)


def _errors(target, npxg, xa, shots):
    scale = target.minutes / 90
    return tuple(
        abs(actual - predicted * scale) if actual is not None and predicted is not None else None
        for actual, predicted in ((target.npxg, npxg), (target.xa, xa), (target.shots, shots))
    )


def _mean_available(values):
    selected = [value for value in values if value is not None]
    return sum(selected) / len(selected) if selected else 0.0


def _aggregate(name, rows):
    metric = lambda index: sum(row[index] for row in rows if row[index] is not None) / sum(row[index] is not None for row in rows) if any(row[index] is not None for row in rows) else None
    return TalentCandidateMetrics(name, len(rows), metric(0), metric(1), metric(2), sum(_mean_available(row) for row in rows) / len(rows))
