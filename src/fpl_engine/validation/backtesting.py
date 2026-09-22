"""BT-001..014: reproducible point-in-time model and decision backtests."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field, is_dataclass, replace
from datetime import datetime, timezone
from enum import Enum
import json
from pathlib import Path
from typing import Iterable, Mapping, Sequence

import numpy as np

from fpl_engine.optimizer import (
    Alternative, ChipState, Optimizer, OptimizerError, OptimizerRules, Recommendation,
    SquadPlayer, SquadState, autosub_points, optimizer_baselines, validate_squad,
)
from fpl_engine.validation.leakage import LeakageError, assert_information_known, assert_snapshot_before
from fpl_engine.validation.metrics import (
    METRIC_REGISTRY_VERSION, MetricDelta, MetricError, MetricValue, bootstrap_delta, bootstrap_metric,
    calibration_error, metric,
)


BACKTEST_VERSION = "backtest_v1"


def _utc(value: datetime, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be an aware datetime")
    return value.astimezone(timezone.utc)


class BacktestMode(str, Enum):
    STRICT = "STRICT"
    STANDARD = "STANDARD"
    RESEARCH = "RESEARCH"


@dataclass(frozen=True)
class HistoricalPoint:
    key: str
    prediction_timestamp: datetime
    known_at: datetime
    season: str
    gameweek: int
    snapshot_timestamp: datetime | None = None
    point_in_time_quality: str = "strong"

    def validate(self, mode: BacktestMode) -> None:
        prediction = _utc(self.prediction_timestamp, "prediction_timestamp")
        assert_information_known(known_at=self.known_at, prediction_timestamp=prediction,
                                 entity=self.key, source="historical_backtest")
        if self.snapshot_timestamp is not None:
            assert_snapshot_before(snapshot_timestamp=self.snapshot_timestamp,
                                   prediction_timestamp=prediction, source=self.key)
        if mode is BacktestMode.STRICT and self.point_in_time_quality != "strong":
            raise LeakageError(f"{self.key} lacks strong point-in-time evidence in STRICT mode")


@dataclass(frozen=True)
class TemporalFold:
    prediction_timestamp: datetime
    train_keys: tuple[str, ...]
    test_keys: tuple[str, ...]


def walk_forward_splits(points: Iterable[HistoricalPoint], *, minimum_train_periods: int = 1,
                        mode: BacktestMode = BacktestMode.STRICT) -> tuple[TemporalFold, ...]:
    """Expanding-window production split. Random splitting is intentionally unavailable."""
    rows = sorted(points, key=lambda row: (_utc(row.prediction_timestamp, "prediction_timestamp"), row.key))
    if minimum_train_periods < 1:
        raise ValueError("minimum_train_periods must be positive")
    if len({row.key for row in rows}) != len(rows):
        raise ValueError("historical point keys must be unique")
    for row in rows:
        row.validate(mode)
    by_time: dict[datetime, list[HistoricalPoint]] = defaultdict(list)
    for row in rows:
        by_time[_utc(row.prediction_timestamp, "prediction_timestamp")].append(row)
    times = sorted(by_time)
    folds = []
    for index in range(minimum_train_periods, len(times)):
        test_time = times[index]
        train = tuple(row.key for time in times[:index] for row in by_time[time])
        test = tuple(row.key for row in by_time[test_time])
        folds.append(TemporalFold(test_time, train, test))
    return tuple(folds)


@dataclass(frozen=True)
class CoverageReport:
    requested: int
    evaluated: int
    missing_keys: tuple[str, ...] = ()

    @property
    def fraction(self) -> float:
        return self.evaluated / self.requested if self.requested else 0.0


@dataclass(frozen=True)
class ExperimentMetadata:
    experiment_id: str
    component: str
    mode: BacktestMode
    started_at: datetime
    period_start: datetime
    period_end: datetime
    seasons: tuple[str, ...]
    data_versions: tuple[str, ...]
    feature_versions: tuple[str, ...]
    model_versions: tuple[str, ...]
    configuration_hash: str
    random_seed: int
    git_commit: str | None = None

    def __post_init__(self) -> None:
        for name in ("started_at", "period_start", "period_end"):
            _utc(getattr(self, name), name)
        if not self.experiment_id or not self.component or not self.seasons or not self.model_versions:
            raise ValueError("experiment id, component, seasons, and model versions are required")
        if self.period_end < self.period_start:
            raise ValueError("period_end precedes period_start")


@dataclass(frozen=True)
class ComponentObservation:
    key: str
    prediction_timestamp: datetime
    outcome_known_at: datetime
    actual: float
    predicted: float
    baseline: float | None = None
    binary_actual: bool | None = None
    probability: float | None = None
    segment: str | None = None
    block: str | None = None

    def validate(self) -> None:
        prediction = _utc(self.prediction_timestamp, "prediction_timestamp")
        if _utc(self.outcome_known_at, "outcome_known_at") <= prediction:
            raise LeakageError(f"outcome for {self.key} must become known after prediction")
        if self.probability is not None and not 0 <= self.probability <= 1:
            raise ValueError("probability must be in [0, 1]")


@dataclass(frozen=True)
class ComponentReport:
    component: str
    metrics: Mapping[str, MetricValue]
    baseline_metrics: Mapping[str, MetricValue]
    baseline_deltas: Mapping[str, MetricDelta]
    segments: Mapping[str, Mapping[str, MetricValue]]
    coverage: CoverageReport
    leakage_violations: int
    metadata: ExperimentMetadata
    runtime_seconds: float | None = None
    registry_version: str = METRIC_REGISTRY_VERSION
    backtest_version: str = BACKTEST_VERSION

    @property
    def valid(self) -> bool:
        return self.leakage_violations == 0 and self.coverage.evaluated > 0

    def to_dict(self) -> dict:
        return _jsonable(asdict(self))


def _score_rows(rows: Sequence[ComponentObservation], bootstrap_samples: int, seed: int) -> dict[str, MetricValue]:
    actual, predicted = [row.actual for row in rows], [row.predicted for row in rows]
    blocks = [row.block or row.key for row in rows]
    output = {
        name: bootstrap_metric(name, actual, predicted, blocks=blocks, samples=bootstrap_samples, seed=seed)
        for name in ("mae", "rmse", "bias")
    }
    try:
        output["spearman"] = bootstrap_metric("spearman", actual, predicted, blocks=blocks,
                                                samples=bootstrap_samples, seed=seed)
    except MetricError:
        pass
    probability_rows = [row for row in rows if row.probability is not None and row.binary_actual is not None]
    if probability_rows:
        outcomes = [float(row.binary_actual) for row in probability_rows]
        probabilities = [float(row.probability) for row in probability_rows]
        output["brier"] = bootstrap_metric("brier", outcomes, probabilities,
                                             blocks=[row.block or row.key for row in probability_rows],
                                             samples=bootstrap_samples, seed=seed)
        output["calibration_error"] = MetricValue(
            "calibration_error", calibration_error(outcomes, probabilities), len(probability_rows), "lower"
        )
    return output


def backtest_component(component: str, observations: Iterable[ComponentObservation], metadata: ExperimentMetadata,
                       *, requested_keys: Iterable[str] = (), bootstrap_samples: int = 500) -> ComponentReport:
    rows = tuple(sorted(observations, key=lambda row: (_utc(row.prediction_timestamp, "prediction_timestamp"), row.key)))
    for row in rows:
        row.validate()
    if not rows:
        raise ValueError("at least one observation is required")
    requested = tuple(requested_keys) or tuple(row.key for row in rows)
    evaluated = {row.key for row in rows}
    metrics = _score_rows(rows, bootstrap_samples, metadata.random_seed)
    baselines = {}
    deltas = {}
    baseline_rows = [replace(row, predicted=float(row.baseline)) for row in rows if row.baseline is not None]
    if baseline_rows:
        baselines = _score_rows(baseline_rows, bootstrap_samples, metadata.random_seed)
        actual = [row.actual for row in rows]
        candidate = [row.predicted for row in rows]
        baseline_values = [float(row.baseline) for row in rows]
        blocks = [row.block or row.key for row in rows]
        for name in ("mae", "rmse", "bias"):
            deltas[name] = bootstrap_delta(name, actual, candidate, baseline_values, blocks=blocks,
                                           samples=bootstrap_samples, seed=metadata.random_seed)
    segments = {
        name: _score_rows(group, bootstrap_samples, metadata.random_seed)
        for name, group in sorted(_group(rows, lambda row: row.segment).items()) if name is not None
    }
    coverage = CoverageReport(len(requested), len(evaluated), tuple(sorted(set(requested) - evaluated)))
    return ComponentReport(component, metrics, baselines, deltas, segments, coverage, 0, metadata)


def backtest_model_candidates(component: str, candidates: Mapping[str, Iterable[ComponentObservation]],
                              metadata: ExperimentMetadata, *, required: Sequence[str] = (),
                              bootstrap_samples: int = 500) -> Mapping[str, ComponentReport]:
    missing = set(required) - set(candidates)
    if missing:
        raise ValueError(f"missing required {component} baselines/challengers: {sorted(missing)}")
    return {name: backtest_component(component, rows, replace(metadata, model_versions=(name,)),
                                     bootstrap_samples=bootstrap_samples)
            for name, rows in sorted(candidates.items())}


def backtest_team_strength(candidates, metadata, *, bootstrap_samples: int = 500):
    return backtest_model_candidates("TEAM_STRENGTH", candidates, metadata,
                                     required=("league_average", "rolling_xg", "poisson", "dixon_coles"),
                                     bootstrap_samples=bootstrap_samples)


def backtest_minutes(candidates, metadata, *, bootstrap_samples: int = 500):
    return backtest_model_candidates("MINUTES", candidates, metadata, bootstrap_samples=bootstrap_samples)


def backtest_player_talent(candidates, metadata, *, bootstrap_samples: int = 500):
    return backtest_model_candidates("PLAYER_TALENT", candidates, metadata, bootstrap_samples=bootstrap_samples)


def backtest_event_models(candidates, metadata, *, bootstrap_samples: int = 500):
    return backtest_model_candidates("EVENT_MODELS", candidates, metadata, bootstrap_samples=bootstrap_samples)


def _group(rows, key):
    output = defaultdict(list)
    for row in rows:
        output[key(row)].append(row)
    return output


@dataclass(frozen=True)
class ProjectionBacktestObservation:
    key: str
    horizon: int
    prediction_timestamp: datetime
    outcome_known_at: datetime
    expected_points: float
    actual_points: float
    p_return: float
    returned: bool
    p_10_plus: float
    scored_10_plus: bool
    position: str | None = None
    risk: str | None = None
    block: str | None = None


def backtest_player_projections(observations: Iterable[ProjectionBacktestObservation], metadata: ExperimentMetadata,
                                *, bootstrap_samples: int = 500) -> Mapping[str, ComponentReport]:
    rows = tuple(observations)
    invalid = {row.horizon for row in rows} - {1, 3, 6}
    if invalid or not rows:
        raise ValueError("projection horizons must be 1, 3, or 6")
    reports = {}
    for horizon, group in sorted(_group(rows, lambda row: row.horizon).items()):
        converted = tuple(ComponentObservation(
            row.key, row.prediction_timestamp, row.outcome_known_at, row.actual_points,
            row.expected_points, binary_actual=row.returned, probability=row.p_return,
            segment="|".join(value for value in (row.position, row.risk) if value) or None,
            block=row.block,
        ) for row in group)
        report = backtest_component(f"PLAYER_PROJECTION_{horizon}GW", converted, metadata,
                                    bootstrap_samples=bootstrap_samples)
        haul_rows = tuple(ComponentObservation(
            row.key, row.prediction_timestamp, row.outcome_known_at, row.actual_points,
            row.expected_points, binary_actual=row.scored_10_plus, probability=row.p_10_plus,
            segment=row.position, block=row.block,
        ) for row in group)
        haul = backtest_component(f"PLAYER_PROJECTION_{horizon}GW_HAUL", haul_rows, metadata,
                                  bootstrap_samples=bootstrap_samples)
        merged = dict(report.metrics)
        merged["return_brier"] = merged.pop("brier")
        merged["return_calibration_error"] = merged.pop("calibration_error")
        merged["haul_10_brier"] = haul.metrics["brier"]
        merged["haul_10_calibration_error"] = haul.metrics["calibration_error"]
        reports[str(horizon)] = replace(report, metrics=merged)
    return reports


@dataclass(frozen=True)
class SimulationDistributionObservation:
    key: str
    probabilities: Mapping[int, float]
    actual: int


def validate_simulation_distributions(rows: Iterable[SimulationDistributionObservation]) -> Mapping[str, MetricValue]:
    rows = tuple(rows)
    if not rows:
        raise ValueError("at least one simulation distribution is required")
    nll, means, actual = [], [], []
    for row in rows:
        if any(probability < 0 for probability in row.probabilities.values()) or abs(sum(row.probabilities.values()) - 1) > 1e-9:
            raise ValueError(f"invalid PMF for {row.key}")
        nll.append(-np.log(max(row.probabilities.get(row.actual, 0.0), 1e-15)))
        means.append(sum(value * probability for value, probability in row.probabilities.items()))
        actual.append(row.actual)
    return {
        "distribution_nll": MetricValue("distribution_nll", float(np.mean(nll)), len(rows), "lower"),
        "mean_mae": metric("mae", actual, means),
        "mean_bias": metric("bias", actual, means),
    }


def generate_synthetic_squads(pool: Iterable[SquadPlayer], rules: OptimizerRules, *, season: str,
                              prediction_timestamp: datetime, count: int, seed: int = 42,
                              budgets: Sequence[int] = (980, 1000, 1020),
                              free_transfer_states: Sequence[int] = (1, 2, 5)) -> tuple[SquadState, ...]:
    """BT-009 deterministic valid squad states with varied budgets and FT balances."""
    candidates = tuple(sorted(pool, key=lambda row: row.player_id))
    if count < 1 or not candidates or not budgets or not free_transfer_states:
        raise ValueError("count, pool, budgets, and FT states are required")
    timestamp = _utc(prediction_timestamp, "prediction_timestamp")
    needed = {value["canonical_code"]: int(value["squad_count"]) for value in rules.value("positions").values()}
    rng, output, attempts = np.random.default_rng(seed), [], 0
    while len(output) < count and attempts < count * 500:
        attempts += 1
        selected = []
        for position, number in needed.items():
            options = [row for row in candidates if row.position == position]
            if len(options) < number:
                raise OptimizerError(f"insufficient {position} candidates")
            for index in rng.permutation(len(options)):
                player = options[int(index)]
                if Counter(row.club_id for row in selected)[player.club_id] < int(rules.value("initial_squad", "maximum_players_per_club")):
                    selected.append(player)
                    if sum(row.position == position for row in selected) == number:
                        break
        if len(selected) != sum(needed.values()):
            continue
        budget = int(budgets[len(output) % len(budgets)])
        cost = sum(row.current_price for row in selected)
        if cost > budget:
            continue
        state = SquadState(tuple(selected), budget - cost,
                           int(free_transfer_states[len(output) % len(free_transfer_states)]), ChipState(), 1,
                           season, rules.version, timestamp)
        validate_squad(state, rules)
        signature = tuple(sorted(row.player_id for row in state.players)) + (str(state.bank), str(state.free_transfers))
        if signature not in {tuple(sorted(row.player_id for row in item.players)) + (str(item.bank), str(item.free_transfers)) for item in output}:
            output.append(state)
    if len(output) != count:
        raise OptimizerError("unable to generate requested valid synthetic squads within budgets")
    return tuple(output)


@dataclass(frozen=True)
class OptimizerOutcome:
    key: str
    recommendation: Recommendation
    realized_recommended: float
    realized_roll: float
    realized_greedy_1gw: float
    realized_static_6gw: float
    realized_lineup: float | None = None
    realized_best_lineup: float | None = None
    realized_captain: float | None = None
    realized_best_captain: float | None = None


@dataclass(frozen=True)
class OptimizerBacktestReport:
    sample_size: int
    gain_vs_roll: float
    gain_vs_greedy_1gw: float
    gain_vs_static_6gw: float
    recommendation_win_rate_vs_roll: float
    average_hit_cost: float
    average_gross_gain: float
    average_net_gain: float
    lineup_regret: float | None
    captain_regret: float | None
    average_decision_margin: float
    average_stability: float | None
    action_selection_frequency: Mapping[str, float]
    chip_selection_frequency: Mapping[str, float]


def backtest_optimizer(rows: Iterable[OptimizerOutcome]) -> OptimizerBacktestReport:
    rows = tuple(rows)
    if not rows:
        raise ValueError("at least one optimizer outcome is required")
    gain = lambda attr: [row.realized_recommended - getattr(row, attr) for row in rows]
    lineup = [row.realized_best_lineup - row.realized_lineup for row in rows
              if row.realized_best_lineup is not None and row.realized_lineup is not None]
    captain = [row.realized_best_captain - row.realized_captain for row in rows
               if row.realized_best_captain is not None and row.realized_captain is not None]
    stability = [row.recommendation.action_stability for row in rows if row.recommendation.action_stability is not None]
    roll_gain = gain("realized_roll")
    return OptimizerBacktestReport(
        len(rows), float(np.mean(roll_gain)), float(np.mean(gain("realized_greedy_1gw"))),
        float(np.mean(gain("realized_static_6gw"))), float(np.mean(np.asarray(roll_gain) > 0)),
        float(np.mean([row.recommendation.hit_cost for row in rows])),
        float(np.mean([row.recommendation.gross_gain for row in rows])),
        float(np.mean([row.recommendation.net_gain for row in rows])),
        float(np.mean(lineup)) if lineup else None, float(np.mean(captain)) if captain else None,
        float(np.mean([row.recommendation.decision_margin for row in rows])),
        float(np.mean(stability)) if stability else None,
        {key: count / len(rows) for key, count in sorted(Counter(row.recommendation.action for row in rows).items())},
        {key: count / len(rows) for key, count in sorted(Counter(row.recommendation.chip or "NONE" for row in rows).items())},
    )


@dataclass(frozen=True)
class ChipOutcome:
    key: str
    chip: str
    points_with_chip: float
    points_without_chip: float


@dataclass(frozen=True)
class ChipBacktestReport:
    by_chip: Mapping[str, Mapping[str, float | int]]


def backtest_chips(rows: Iterable[ChipOutcome]) -> ChipBacktestReport:
    rows = tuple(rows)
    if not rows:
        raise ValueError("at least one chip outcome is required")
    output = {}
    for chip, group in sorted(_group(rows, lambda row: row.chip).items()):
        gains = np.asarray([row.points_with_chip - row.points_without_chip for row in group])
        output[chip] = {"sample_size": len(group), "mean_gain": float(np.mean(gains)),
                        "win_rate": float(np.mean(gains > 0))}
    return ChipBacktestReport(output)


@dataclass(frozen=True)
class SeasonStep:
    gameweek: int
    prediction_timestamp: datetime
    projections: Mapping[str, object]
    player_pool: tuple[SquadPlayer, ...]
    realized_points: Mapping[str, float]
    realized_minutes: Mapping[str, float]
    current_prices: Mapping[str, int]
    prices_known_at: datetime
    chip: str | None = None


@dataclass(frozen=True)
class SeasonStrategyResult:
    total_points: float
    transfer_count: int
    hit_points: int
    captain_points: float
    chip_gameweeks: Mapping[str, int]
    final_state: SquadState
    recommendations: tuple[Recommendation, ...]
    starting_state_kind: str
    gameweek_points: Mapping[int, float] = field(default_factory=dict)


def simulate_season(initial_state: SquadState, steps: Iterable[SeasonStep], optimizer: Optimizer, *,
                    starting_state_kind: str = "historical") -> SeasonStrategyResult:
    """BT-013 sequential counterfactual state; future prices enter only at each new step."""
    ordered = tuple(sorted(steps, key=lambda row: (_utc(row.prediction_timestamp, "prediction_timestamp"), row.gameweek)))
    if not ordered:
        raise ValueError("at least one season step is required")
    if starting_state_kind not in {"historical", "synthetic", "reference"}:
        raise ValueError("starting_state_kind must be historical, synthetic, or reference")
    if [row.gameweek for row in ordered] != sorted({row.gameweek for row in ordered}):
        raise ValueError("season steps must have unique increasing gameweeks")
    state, total, transfer_count, hits, captain_total, recommendations = initial_state, 0.0, 0, 0, 0.0, []
    chip_gameweeks = {}
    gameweek_points = {}
    for step in ordered:
        assert_information_known(known_at=step.prices_known_at, prediction_timestamp=step.prediction_timestamp,
                                 entity=f"GW{step.gameweek} prices", source="historical_price_snapshot")
        missing_owned_prices = sorted(player.player_id for player in state.players
                                      if player.player_id not in step.current_prices)
        if missing_owned_prices:
            raise OptimizerError(
                f"missing point-in-time current prices for owned players: {missing_owned_prices}"
            )
        players = tuple(replace(player, current_price=int(step.current_prices.get(player.player_id, player.current_price)), selling_price=None)
                        for player in state.players)
        state = replace(state, players=players, current_gameweek=step.gameweek,
                        prediction_timestamp=_utc(step.prediction_timestamp, "prediction_timestamp"))
        recommendation = optimizer.recommend(state, step.projections, step.player_pool,
                                             chip=step.chip)
        recommendations.append(recommendation)
        active_chip = recommendation.chip or step.chip
        by_id = {row.player_id: row for row in state.players}
        pool = {row.player_id: row for row in step.player_pool}
        for player_id in recommendation.transfers_out:
            by_id.pop(player_id)
        for player_id in recommendation.transfers_in:
            incoming = pool[player_id]
            by_id[player_id] = replace(incoming, purchase_price=incoming.current_price, selling_price=None)
        decision_state = replace(state, players=tuple(by_id.values()), bank=recommendation.resulting_bank,
                                 free_transfers=recommendation.free_transfers_after)
        points = autosub_points(
            type("L", (), {"starting_xi": recommendation.starting_xi, "bench_order": recommendation.bench_order,
                            "captain_id": recommendation.captain_id, "vice_captain_id": recommendation.vice_captain_id})(),
            decision_state, step.realized_points, step.realized_minutes, optimizer.rules,
        )
        if active_chip == "triple_captain" and step.realized_minutes.get(recommendation.captain_id, 0) > 0:
            points += step.realized_points.get(recommendation.captain_id, 0.0)
        if active_chip == "bench_boost":
            active = set(recommendation.starting_xi)
            points += sum(step.realized_points.get(player_id, 0.0) for player_id in recommendation.bench_order
                          if step.realized_minutes.get(player_id, 0) > 0 and player_id not in active)
        points -= recommendation.hit_cost
        total += points
        gameweek_points[step.gameweek] = points
        captain_total += step.realized_points.get(recommendation.captain_id, 0.0)
        transfer_count += len(recommendation.transfers_in)
        hits += recommendation.hit_cost
        if active_chip:
            chip_gameweeks[active_chip] = step.gameweek
            half = "h1" if step.gameweek <= int(optimizer.rules.value("chip_periods", "first_half", "gameweeks", "through")) else "h2"
            chip_field = f"{active_chip}_{half}"
            chips = replace(state.chips, **{chip_field: False})
            if active_chip == "free_hit":
                chips = replace(chips, last_free_hit_gameweek=step.gameweek)
        else:
            chips = state.chips
        if active_chip != "free_hit":
            state = replace(decision_state, chips=chips)
        else:
            state = replace(state, chips=chips, free_transfers=recommendation.free_transfers_after)
    return SeasonStrategyResult(total, transfer_count, hits, captain_total, chip_gameweeks, state,
                                tuple(recommendations), starting_state_kind, gameweek_points)


def compare_season_strategies(initial_state: SquadState, steps: Iterable[SeasonStep],
                              strategies: Mapping[str, Optimizer], *, starting_state_kind: str = "historical"):
    frozen_steps = tuple(steps)
    if not strategies:
        raise ValueError("at least one strategy is required")
    return {name: simulate_season(initial_state, frozen_steps, optimizer,
                                  starting_state_kind=starting_state_kind)
            for name, optimizer in sorted(strategies.items())}


class PromotionDecision(str, Enum):
    PROMOTE = "PROMOTE"
    REJECT = "REJECT"
    KEEP_TESTING = "KEEP_TESTING"


@dataclass(frozen=True)
class ChampionManifest:
    component: str
    champion_version: str
    challenger_version: str
    primary_metric: str
    direction: str
    champion_value: float
    challenger_value: float
    delta: float
    confidence_interval_low: float | None
    confidence_interval_high: float | None
    practical_threshold: float
    decision: PromotionDecision
    reason: str
    evaluated_at: datetime
    period_start: datetime
    period_end: datetime
    seasons: tuple[str, ...]
    sample_size: int
    leakage_violations: int
    configuration_hash: str


def champion_challenger(*, component: str, champion_version: str, challenger_version: str,
                        primary_metric: str, direction: str, champion_value: float, challenger_value: float,
                        confidence_interval: tuple[float, float] | None, practical_threshold: float,
                        evaluated_at: datetime, period_start: datetime, period_end: datetime,
                        seasons: Sequence[str], sample_size: int, leakage_violations: int,
                        configuration_hash: str) -> ChampionManifest:
    if direction not in {"lower", "higher"} or practical_threshold < 0:
        raise ValueError("invalid promotion direction or threshold")
    improvement = champion_value - challenger_value if direction == "lower" else challenger_value - champion_value
    low, high = confidence_interval if confidence_interval else (None, None)
    if leakage_violations:
        decision, reason = PromotionDecision.REJECT, "leakage detected"
    elif sample_size < 1:
        decision, reason = PromotionDecision.KEEP_TESTING, "no out-of-sample observations"
    elif improvement < 0:
        decision, reason = PromotionDecision.REJECT, "challenger is worse than champion"
    elif improvement < practical_threshold or (low is not None and low <= 0):
        decision, reason = PromotionDecision.KEEP_TESTING, "improvement is not yet practically and statistically clear"
    else:
        decision, reason = PromotionDecision.PROMOTE, "challenger clears configured practical and uncertainty thresholds"
    return ChampionManifest(component, champion_version, challenger_version, primary_metric, direction,
                            champion_value, challenger_value, improvement, low, high, practical_threshold,
                            decision, reason, _utc(evaluated_at, "evaluated_at"),
                            _utc(period_start, "period_start"), _utc(period_end, "period_end"),
                            tuple(seasons), sample_size, leakage_violations, configuration_hash)


class ReportStore:
    """Deterministic machine-readable experiment and champion manifest persistence."""
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def write(self, name: str, report: object) -> Path:
        if not name or Path(name).name != name:
            raise ValueError("report name must be a simple file stem")
        target = self.root / f"{name}.json"
        target.write_text(json.dumps(_jsonable(asdict(report) if is_dataclass(report) else report),
                                     indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return target


@dataclass(frozen=True)
class V1ChampionManifest:
    created_at: datetime
    season: str
    team_strength: str
    minutes: str
    player_talent: str
    event_models: Mapping[str, str]
    simulation_version: str
    scoring_version: int
    projection_version: str
    optimizer_version: str
    optimizer_rule_version: int
    metric_registry_version: str
    evidence_mode: BacktestMode
    experiment_ids: tuple[str, ...]
    leakage_violations: int
    notes: tuple[str, ...] = ()

    def __post_init__(self):
        _utc(self.created_at, "created_at")
        required = (self.season, self.team_strength, self.minutes, self.player_talent,
                    self.simulation_version, self.projection_version, self.optimizer_version)
        if not all(required) or not self.event_models or self.scoring_version < 1 or self.optimizer_rule_version < 1:
            raise ValueError("complete active V1 component versions are required")
        if self.evidence_mode is not BacktestMode.STRICT:
            raise ValueError("the production champion manifest requires STRICT evidence")
        if self.leakage_violations:
            raise LeakageError("cannot create a champion manifest with leakage violations")


@dataclass(frozen=True)
class WalkForwardResult:
    predictions: Mapping[str, object]
    folds: tuple[TemporalFold, ...]
    coverage: CoverageReport
    mode: BacktestMode


class HistoricalCoverageError(RuntimeError):
    def __init__(self, coverage: CoverageReport):
        self.coverage = coverage
        super().__init__(f"historical source coverage unavailable for {coverage.missing_keys}")


class WalkForwardRunner:
    """Freeze and evaluate each point in chronological order with prior periods only."""
    def __init__(self, *, mode: BacktestMode = BacktestMode.STRICT, minimum_train_periods: int = 1):
        self.mode, self.minimum_train_periods = mode, minimum_train_periods

    def run(self, points: Iterable[HistoricalPoint], predict, *, require_complete: bool = True) -> WalkForwardResult:
        rows = tuple(points)
        folds = walk_forward_splits(rows, minimum_train_periods=self.minimum_train_periods, mode=self.mode)
        by_key = {row.key: row for row in rows}
        predictions, missing = {}, []
        for fold in folds:
            for key in fold.test_keys:
                value = predict(by_key[key], fold.train_keys)
                if value is None:
                    missing.append(key)
                else:
                    predictions[key] = value
        requested = sum((list(fold.test_keys) for fold in folds), [])
        coverage = CoverageReport(len(requested), len(predictions), tuple(sorted(missing)))
        if require_complete and missing:
            raise HistoricalCoverageError(coverage)
        return WalkForwardResult(predictions, folds, coverage, self.mode)


def _jsonable(value):
    if isinstance(value, datetime):
        return _utc(value, "timestamp").isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    return value
