"""PROJ-001..005 canonical, point-in-time player projections."""

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
import json
import math
from typing import Iterable, Mapping

import duckdb
import numpy as np

from fpl_engine.simulation import FixtureSimulationResult, PlayerSimulationSummary
from fpl_engine.validation.leakage import FutureInformationError, assert_information_known


DEFAULT_HORIZON_WEIGHTS: tuple[float, ...] = (1.00, .95, .90, .85, .80, .75)


def _utc(value: datetime, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be an aware datetime")
    return value.astimezone(timezone.utc)


def _distribution(histogram: Mapping[int, int]) -> dict[int, float]:
    total = sum(histogram.values())
    if total <= 0 or any(type(points) is not int or count < 0 for points, count in histogram.items()):
        raise ValueError("points histogram must contain non-negative integer counts")
    return {points: count / total for points, count in histogram.items() if count}


def _convolve(left: Mapping[int, float], right: Mapping[int, float]) -> dict[int, float]:
    result: dict[int, float] = defaultdict(float)
    for left_points, left_probability in left.items():
        for right_points, right_probability in right.items():
            result[left_points + right_points] += left_probability * right_probability
    return dict(result)


def _metrics(pmf: Mapping[int, float]) -> tuple[float, float, float, dict[float, float], dict[str, float]]:
    values = np.asarray(sorted(pmf), dtype=float)
    probabilities = np.asarray([pmf[int(value)] for value in values], dtype=float)
    mean = float(np.dot(values, probabilities))
    variance = float(np.dot((values - mean) ** 2, probabilities))
    cdf = np.cumsum(probabilities)
    quantiles = {q: float(values[np.searchsorted(cdf, q, side="left")]) for q in (.10, .25, .50, .75, .90)}
    chances = {
        "p_blank": sum(probability for points, probability in pmf.items() if points <= 2),
        "p_5_plus": sum(probability for points, probability in pmf.items() if points >= 5),
        "p_8_plus": sum(probability for points, probability in pmf.items() if points >= 8),
        "p_10_plus": sum(probability for points, probability in pmf.items() if points >= 10),
        "p_15_plus": sum(probability for points, probability in pmf.items() if points >= 15),
    }
    return mean, quantiles[.50], math.sqrt(max(variance, 0.0)), quantiles, chances


@dataclass(frozen=True)
class FixtureProjectionInput:
    season: str
    rule_version: int
    target_gameweek: int
    fixture_kickoff: datetime
    fixture_known_at: datetime
    simulation: FixtureSimulationResult

    def __post_init__(self) -> None:
        if not isinstance(self.season, str) or not self.season.strip():
            raise ValueError("season must be explicit")
        if type(self.rule_version) is not int or self.rule_version < 1:
            raise ValueError("rule_version must be a positive integer")
        if self.target_gameweek < 1:
            raise ValueError("target_gameweek must be positive")
        prediction = _utc(self.simulation.prediction_timestamp, "simulation prediction_timestamp")
        known = _utc(self.fixture_known_at, "fixture_known_at")
        kickoff = _utc(self.fixture_kickoff, "fixture_kickoff")
        assert_information_known(known_at=known, prediction_timestamp=prediction,
                                 entity=self.simulation.fixture_id, source="fixture_schedule")
        if kickoff <= prediction:
            raise FutureInformationError("target fixture kickoff must be after prediction_timestamp")
        if self.simulation.scoring_version != self.rule_version:
            raise ValueError("simulation scoring/rule version mismatch")


@dataclass(frozen=True)
class FixturePlayerProjection:
    season: str
    rule_version: int
    player_id: str
    fixture_id: str
    target_gameweek: int
    prediction_timestamp: datetime
    expected_points: float
    median_points: float
    points_std: float
    point_quantiles: Mapping[float, float]
    p_blank: float
    p_return: float
    p_5_plus: float
    p_8_plus: float
    p_10_plus: float
    p_15_plus: float
    expected_minutes: float
    points_distribution: Mapping[int, float]
    simulation_count: int
    random_seed: int
    derived_fixture_seed: int
    simulator_version: str
    model_version: str
    dataset_version: str
    feature_version: str
    scoring_version: int
    event_completeness: float


@dataclass(frozen=True)
class GameweekPlayerProjection:
    season: str
    rule_version: int
    player_id: str
    target_gameweek: int
    prediction_timestamp: datetime
    fixture_ids: tuple[str, ...]
    fixture_count: int
    expected_points: float
    median_points: float
    points_std: float
    point_quantiles: Mapping[float, float]
    p_blank: float
    p_return: float
    p_5_plus: float
    p_8_plus: float
    p_10_plus: float
    p_15_plus: float
    expected_minutes: float
    points_distribution: Mapping[int, float]
    event_completeness: float


@dataclass(frozen=True)
class PlayerProjection:
    """Stable optimizer-facing projection; all player IDs are canonical IDs."""
    player_id: str
    season: str
    rule_version: int
    prediction_timestamp: datetime
    current_gameweek: int
    gameweeks: tuple[GameweekPlayerProjection, ...]
    ev_next_1: float
    ev_next_3: float
    ev_next_6: float
    weighted_ev_next_1: float
    weighted_ev_next_3: float
    weighted_ev_next_6: float
    expected_minutes_next_1: float
    expected_minutes_next_3: float
    expected_minutes_next_6: float
    projection_uncertainty: float
    projection_confidence: float
    event_completeness: float
    model_versions: tuple[str, ...]
    dataset_versions: tuple[str, ...]
    feature_versions: tuple[str, ...]
    simulator_versions: tuple[str, ...]
    simulation_seeds: tuple[int, ...]
    scoring_versions: tuple[int, ...]


class ProjectionBuilder:
    """PROJ-002..004 aggregation using independent fixture PMFs in V1."""
    VERSION = "projection_builder_v1"

    def __init__(self, horizon_weights: tuple[float, ...] = DEFAULT_HORIZON_WEIGHTS):
        if not horizon_weights or any(not math.isfinite(weight) or weight < 0 for weight in horizon_weights):
            raise ValueError("horizon_weights must be finite and non-negative")
        self.horizon_weights = horizon_weights

    def fixture_projections(self, inputs: Iterable[FixtureProjectionInput]) -> tuple[FixturePlayerProjection, ...]:
        output = []
        for item in inputs:
            simulation = item.simulation
            for summary in simulation.summaries:
                pmf = _distribution(summary.points_histogram)
                completeness = float(getattr(summary, "event_completeness", 1.0))
                output.append(FixturePlayerProjection(
                    item.season, item.rule_version, summary.player_id, simulation.fixture_id, item.target_gameweek,
                    simulation.prediction_timestamp, summary.expected_points, summary.median_points,
                    summary.points_std, dict(summary.point_quantiles), summary.p_blank, summary.p_return,
                    summary.p_5_plus, summary.p_8_plus, summary.p_10_plus, summary.p_15_plus,
                    summary.simulated_expected_minutes, pmf, summary.simulation_count,
                    summary.random_seed, summary.derived_fixture_seed, summary.simulator_version,
                    simulation.model_version, summary.dataset_version, summary.feature_version,
                    summary.scoring_version, completeness,
                ))
        return tuple(sorted(output, key=lambda row: (row.target_gameweek, row.fixture_id, row.player_id)))

    def build(self, inputs: Iterable[FixtureProjectionInput], *, current_gameweek: int,
              player_ids: Iterable[str] = ()) -> tuple[PlayerProjection, ...]:
        if current_gameweek < 1:
            raise ValueError("current_gameweek must be positive")
        fixture_rows = self.fixture_projections(inputs)
        timestamps = {row.prediction_timestamp.astimezone(timezone.utc) for row in fixture_rows}
        seasons = {row.season for row in fixture_rows}
        rule_versions = {row.rule_version for row in fixture_rows}
        if len(timestamps) > 1:
            raise ValueError("incompatible simulation prediction timestamps")
        if not timestamps:
            raise ValueError("at least one fixture simulation is required to establish prediction timestamp")
        prediction_timestamp = timestamps.pop()
        if len(seasons) != 1:
            raise ValueError("incompatible projection seasons")
        season = seasons.pop()
        if len(rule_versions) != 1:
            raise ValueError("incompatible projection rule versions")
        rule_version = rule_versions.pop()
        by_player: dict[str, list[FixturePlayerProjection]] = defaultdict(list)
        for row in fixture_rows:
            if row.target_gameweek < current_gameweek:
                raise FutureInformationError("fixture gameweek precedes current_gameweek")
            by_player[row.player_id].append(row)
        for player_id in player_ids:
            if not isinstance(player_id, str) or not player_id:
                raise ValueError("player_ids must contain canonical non-empty IDs")
            by_player.setdefault(player_id, [])
        return tuple(self._player_projection(player_id, rows, season, rule_version, prediction_timestamp, current_gameweek)
                     for player_id, rows in sorted(by_player.items()))

    def _player_projection(self, player_id, rows, season, rule_version, prediction_timestamp, current_gameweek):
        rows_by_gw: dict[int, list[FixturePlayerProjection]] = defaultdict(list)
        for row in rows:
            rows_by_gw[row.target_gameweek].append(row)
        gameweeks = []
        for gameweek in range(current_gameweek, current_gameweek + len(self.horizon_weights)):
            fixture_rows = rows_by_gw.get(gameweek, [])
            pmf = {0: 1.0}
            for fixture in sorted(fixture_rows, key=lambda item: item.fixture_id):
                pmf = _convolve(pmf, fixture.points_distribution)
            mean, median, std, quantiles, chances = _metrics(pmf)
            p_return = 1 - math.prod(1 - fixture.p_return for fixture in fixture_rows) if fixture_rows else 0.0
            p_blank = math.prod(fixture.p_blank for fixture in fixture_rows) if fixture_rows else 1.0
            gameweeks.append(GameweekPlayerProjection(
                season, rule_version, player_id, gameweek, prediction_timestamp,
                tuple(item.fixture_id for item in fixture_rows), len(fixture_rows), mean, median, std,
                quantiles, p_blank, p_return, chances["p_5_plus"], chances["p_8_plus"],
                chances["p_10_plus"], chances["p_15_plus"], sum(item.expected_minutes for item in fixture_rows),
                pmf, sum(item.event_completeness for item in fixture_rows) / len(fixture_rows) if fixture_rows else 1.0,
            ))
        def horizon(count): return gameweeks[:count]
        def ev(count): return sum(row.expected_points for row in horizon(count))
        def mins(count): return sum(row.expected_minutes for row in horizon(count))
        def weighted(count): return sum(row.expected_points * self.horizon_weights[index] for index, row in enumerate(horizon(count)))
        completeness = sum(row.event_completeness for row in gameweeks) / len(gameweeks)
        uncertainty = min(1.0, max(row.points_std for row in gameweeks) / (max(row.points_std for row in gameweeks) + 5) + (1 - completeness) * .5)
        return PlayerProjection(
            player_id, season, rule_version, prediction_timestamp, current_gameweek, tuple(gameweeks), ev(1), ev(3), ev(6),
            weighted(1), weighted(3), weighted(6), mins(1), mins(3), mins(6), uncertainty,
            1 - uncertainty, completeness,
            tuple(sorted({row.model_version for row in rows})), tuple(sorted({row.dataset_version for row in rows})),
            tuple(sorted({row.feature_version for row in rows})), tuple(sorted({row.simulator_version for row in rows})),
            tuple(sorted({row.derived_fixture_seed for row in rows})), tuple(sorted({row.scoring_version for row in rows})),
        )


@dataclass(frozen=True)
class ProjectionOutcome:
    player_id: str
    prediction_timestamp: datetime
    realized_at: datetime
    expected_points: float
    realized_points: float
    p_return: float
    returned: bool
    p_10_plus: float
    scored_10_plus: bool
    position: str | None = None
    minutes_risk: str | None = None


@dataclass(frozen=True)
class ProjectionValidationReport:
    observations: int
    mae: float
    rmse: float
    bias: float
    spearman_rank: float | None
    return_brier: float
    haul_10_brier: float
    by_position: Mapping[str, int]
    by_minutes_risk: Mapping[str, int]


def validate_projections(outcomes: Iterable[ProjectionOutcome]) -> ProjectionValidationReport:
    rows = sorted(outcomes, key=lambda row: _utc(row.prediction_timestamp, "prediction_timestamp"))
    if not rows:
        raise ValueError("at least one projection outcome is required")
    for row in rows:
        if _utc(row.realized_at, "realized_at") < _utc(row.prediction_timestamp, "prediction_timestamp"):
            raise ValueError("realized_at precedes prediction_timestamp")
        if not 0 <= row.p_return <= 1 or not 0 <= row.p_10_plus <= 1:
            raise ValueError("probabilities must be in [0, 1]")
    errors = np.asarray([row.expected_points - row.realized_points for row in rows], dtype=float)
    expected = np.asarray([row.expected_points for row in rows], dtype=float)
    actual = np.asarray([row.realized_points for row in rows], dtype=float)
    ranks_expected = np.argsort(np.argsort(expected))
    ranks_actual = np.argsort(np.argsort(actual))
    spearman = float(np.corrcoef(ranks_expected, ranks_actual)[0, 1]) if len(rows) > 1 and np.std(ranks_expected) and np.std(ranks_actual) else None
    return ProjectionValidationReport(
        len(rows), float(np.mean(np.abs(errors))), float(np.sqrt(np.mean(errors ** 2))), float(np.mean(errors)), spearman,
        float(np.mean([(row.p_return - float(row.returned)) ** 2 for row in rows])),
        float(np.mean([(row.p_10_plus - float(row.scored_10_plus)) ** 2 for row in rows])),
        dict(Counter(row.position for row in rows if row.position)), dict(Counter(row.minutes_risk for row in rows if row.minutes_risk)),
    )


class ProjectionStore:
    """PROJ-005 deterministic DuckDB storage with a Parquet export."""
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = duckdb.connect(str(self.path))
        self.connection.execute("SET TimeZone='UTC'")
        self.connection.execute("""CREATE TABLE IF NOT EXISTS player_projection (
            player_id VARCHAR NOT NULL, season VARCHAR NOT NULL, rule_version INTEGER NOT NULL,
            prediction_timestamp TIMESTAMPTZ NOT NULL, current_gameweek INTEGER NOT NULL, payload JSON NOT NULL,
            PRIMARY KEY(player_id, season, rule_version, prediction_timestamp, current_gameweek))""")

    def close(self) -> None: self.connection.close()

    def persist(self, projections: Iterable[PlayerProjection]) -> None:
        for projection in projections:
            payload = json.dumps(asdict(projection), default=lambda value: value.isoformat() if isinstance(value, datetime) else value, sort_keys=True)
            self.connection.execute("INSERT INTO player_projection VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(player_id, season, rule_version, prediction_timestamp, current_gameweek) DO UPDATE SET payload=excluded.payload", [projection.player_id, projection.season, projection.rule_version, projection.prediction_timestamp, projection.current_gameweek, payload])

    def export_parquet(self, root: Path) -> Path:
        root = Path(root); root.mkdir(parents=True, exist_ok=True); target = root / "player_projection.parquet"
        self.connection.execute("COPY player_projection TO ? (FORMAT PARQUET)", [str(target)])
        return target
