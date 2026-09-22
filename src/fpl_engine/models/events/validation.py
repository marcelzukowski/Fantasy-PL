"""Chronological baseline/challenger validation for V1 Event Models."""

from dataclasses import dataclass
from datetime import datetime
from bisect import bisect_right, insort
import math

from fpl_engine.validation.leakage import LeakageError

from .model import PlayerFixtureEvents


@dataclass(frozen=True)
class EventOutcome:
    prediction: PlayerFixtureEvents
    outcome_known_at: datetime
    goals: int
    assists: int
    saves: int | None = None
    defensive_contributions: int | None = None
    yellow: bool = False
    red: bool = False

    def __post_init__(self) -> None:
        if self.outcome_known_at.tzinfo is None or self.outcome_known_at.utcoffset() is None:
            raise LeakageError("outcome_known_at must be aware")
        if self.outcome_known_at <= self.prediction.rates.prediction_timestamp:
            raise LeakageError("event outcome must become known after its prediction")
        if self.goals < 0 or self.assists < 0 or (self.saves is not None and self.saves < 0):
            raise ValueError("event outcomes cannot be negative")


@dataclass(frozen=True)
class EventCandidateMetrics:
    model_id: str
    observations: int
    goal_brier: float
    goal_log_loss: float
    goal_poisson_deviance: float
    assist_brier: float
    assist_log_loss: float
    save_mae: float | None
    defcon_mae: float | None
    yellow_brier: float
    red_brier: float
    goal_calibration_error: float
    assist_calibration_error: float


@dataclass(frozen=True)
class EventWalkForwardReport:
    candidates: tuple[EventCandidateMetrics, ...]
    goal_champion_model_id: str
    assist_champion_model_id: str
    prediction_order: tuple[tuple[str, str], ...]


def walk_forward_events(
    outcomes: list[EventOutcome], *, minimum_history: int = 2,
    baseline_model_id: str = "raw_per90_baseline_v1",
) -> EventWalkForwardReport:
    ordered = sorted(outcomes, key=lambda item: (item.prediction.rates.prediction_timestamp, item.prediction.rates.fixture_id, item.prediction.rates.player_id))
    model_ids = {item.prediction.model_version for item in ordered}
    if len(model_ids) != 1:
        raise ValueError("event walk-forward requires one coherent candidate version per run")
    coherent_model_id = next(iter(model_ids))
    if baseline_model_id == coherent_model_id:
        raise ValueError("baseline and coherent event model IDs must differ")
    rows = {baseline_model_id: [], coherent_model_id: []}
    order = []
    prior_known_times = []
    for outcome in ordered:
        history_count = bisect_right(prior_known_times, outcome.prediction.rates.prediction_timestamp)
        if history_count < minimum_history:
            insort(prior_known_times, outcome.outcome_known_at)
            continue
        order.append((outcome.prediction.rates.fixture_id, outcome.prediction.rates.player_id))
        baseline_goal = outcome.prediction.rates.raw_expected_npxg
        baseline_assist = outcome.prediction.rates.raw_expected_xa
        rows[baseline_model_id].append(_score(outcome, baseline_goal, baseline_assist))
        rows[coherent_model_id].append(_score(outcome, outcome.prediction.goals.expected_goals, outcome.prediction.assists.expected_assists))
        insort(prior_known_times, outcome.outcome_known_at)
    metrics = tuple(_aggregate(name, values) for name, values in rows.items() if values)
    if not metrics:
        raise ValueError("not enough chronological event outcomes")
    baseline, challenger = metrics
    goal_promoted = challenger.goal_log_loss < baseline.goal_log_loss * .99 and challenger.goal_poisson_deviance <= baseline.goal_poisson_deviance
    assist_promoted = challenger.assist_log_loss < baseline.assist_log_loss * .99
    return EventWalkForwardReport(metrics, challenger.model_id if goal_promoted else baseline.model_id,
        challenger.model_id if assist_promoted else baseline.model_id, tuple(order))


def _score(outcome, goal_expected, assist_expected):
    p_goal = 1-math.exp(-goal_expected); p_assist = 1-math.exp(-assist_expected)
    binary = lambda p, y: ((p-float(y))**2, -(float(y)*math.log(max(p,1e-7))+(1-float(y))*math.log(max(1-p,1e-7))))
    goal_binary = binary(p_goal, outcome.goals > 0); assist_binary = binary(p_assist, outcome.assists > 0)
    deviance = 2*(outcome.goals*math.log(outcome.goals/max(goal_expected,1e-7))-(outcome.goals-goal_expected)) if outcome.goals else 2*goal_expected
    prediction = outcome.prediction
    save_error = abs(outcome.saves-prediction.goalkeeper.expected_saves) if outcome.saves is not None and prediction.goalkeeper.expected_saves is not None else None
    defcon_error = abs(outcome.defensive_contributions-prediction.defensive_contributions.expected_defensive_contributions) if outcome.defensive_contributions is not None and prediction.defensive_contributions.expected_defensive_contributions is not None else None
    return (*goal_binary, deviance, *assist_binary, save_error, defcon_error,
        (prediction.cards.p_yellow-float(outcome.yellow))**2, (prediction.cards.p_red-float(outcome.red))**2,
        p_goal, float(outcome.goals>0), p_assist, float(outcome.assists>0))


def _aggregate(name, rows):
    mean = lambda index: sum(row[index] for row in rows)/len(rows)
    optional = lambda index: sum(row[index] for row in rows if row[index] is not None)/sum(row[index] is not None for row in rows) if any(row[index] is not None for row in rows) else None
    return EventCandidateMetrics(name, len(rows), mean(0), mean(1), mean(2), mean(3), mean(4), optional(5), optional(6), mean(7), mean(8), _ece(rows,9,10), _ece(rows,11,12))


def _ece(rows, probability_index, outcome_index):
    bins = [[] for _ in range(5)]
    for row in rows:
        bins[min(4, int(row[probability_index]*5))].append(row)
    return sum(len(bucket)/len(rows)*abs(sum(row[probability_index] for row in bucket)/len(bucket)-sum(row[outcome_index] for row in bucket)/len(bucket)) for bucket in bins if bucket)
