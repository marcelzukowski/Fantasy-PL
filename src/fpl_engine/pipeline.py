"""PIPE-001..007 reusable, fail-fast V1 production orchestration."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Callable, Mapping, Sequence

from fpl_engine.optimizer import Optimizer, OptimizerError, Recommendation, SquadPlayer, SquadState
from fpl_engine.validation.leakage import assert_information_known, assert_snapshot_before
from fpl_engine.validation.metrics import METRIC_REGISTRY_VERSION, metric


PIPELINE_VERSION = "pipeline_v1"


class PipelineError(RuntimeError):
    pass


class PipelineInputError(PipelineError):
    pass


@dataclass(frozen=True)
class RunContext:
    run_id: str
    season: str
    target_gameweek: int
    prediction_timestamp: datetime
    rule_version: int
    required_sources: tuple[str, ...]
    configuration_hash: str
    random_seed: int
    configuration: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.run_id or not self.season or self.target_gameweek < 1 or self.rule_version < 1:
            raise PipelineInputError("run id, season, target gameweek, and rule version are required")
        _utc(self.prediction_timestamp, "prediction_timestamp")
        if not self.configuration_hash:
            raise PipelineInputError("configuration_hash is required")


@dataclass(frozen=True)
class RefreshResult:
    payload: object
    source_snapshots: Mapping[str, datetime]
    dataset_versions: Mapping[str, str]
    retrieved_at: Mapping[str, datetime]
    unresolved_mappings: tuple[str, ...] = ()
    unavailable_optional_sources: tuple[str, ...] = ()


@dataclass(frozen=True)
class FeatureResult:
    payload: object
    known_at: datetime
    feature_versions: Mapping[str, str]
    fallback_usage: Mapping[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class InferenceResult:
    payload: object
    known_at: datetime
    model_versions: Mapping[str, str]


@dataclass(frozen=True)
class ProjectionResult:
    projections: Mapping[str, object]
    simulator_versions: tuple[str, ...]
    scoring_versions: tuple[int, ...]
    simulation_seeds: tuple[int, ...]
    simulation_counts: tuple[int, ...] = ()


@dataclass(frozen=True)
class PipelineRequest:
    context: RunContext
    squad: SquadState
    source_inputs: Mapping[str, object] = field(default_factory=dict)
    fixture_horizon: tuple[object, ...] = ()
    player_pool: tuple[SquadPlayer, ...] = ()
    chip: str | None = None
    max_transfers: int = 2


@dataclass(frozen=True)
class PipelineStages:
    refresh: Callable[[RunContext, Mapping[str, object]], RefreshResult]
    build_features: Callable[[RunContext, RefreshResult], FeatureResult]
    infer: Callable[[RunContext, FeatureResult], InferenceResult]
    project: Callable[[RunContext, InferenceResult, tuple[object, ...]], ProjectionResult]


@dataclass(frozen=True)
class RecommendationOutput:
    run_id: str
    season: str
    prediction_timestamp: datetime
    target_gameweek: int
    recommended_action: str
    transfers: tuple[Mapping[str, str], ...]
    starting_xi: tuple[str, ...]
    bench_order: tuple[str, ...]
    captain: str
    vice_captain: str
    chip: str | None
    expected_points: float
    net_expected_gain: float
    confidence: float | None
    alternatives: tuple[Mapping[str, object], ...]
    provisional_6gw_plan: tuple[Mapping[str, object], ...]
    provenance: Mapping[str, object]
    pipeline_version: str = PIPELINE_VERSION

    def to_dict(self) -> dict:
        return _jsonable(asdict(self))

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))


class PredictionPipeline:
    def __init__(self, stages: PipelineStages, optimizer: Optimizer):
        self.stages, self.optimizer = stages, optimizer

    def run(self, request: PipelineRequest) -> RecommendationOutput:
        context = request.context
        expected = _utc(context.prediction_timestamp, "prediction_timestamp")
        if request.squad.season != context.season or request.squad.rule_version != context.rule_version:
            raise PipelineInputError("squad season/rule version does not match run context")
        if request.squad.current_gameweek != context.target_gameweek:
            raise PipelineInputError("squad gameweek does not match target gameweek")
        if request.squad.prediction_timestamp is None or _utc(request.squad.prediction_timestamp, "squad prediction_timestamp") != expected:
            raise PipelineInputError("squad prediction timestamp does not match run context")
        if not request.fixture_horizon:
            raise PipelineInputError("fixture_horizon is required")

        refresh = self.stages.refresh(context, request.source_inputs)
        missing = set(context.required_sources) - set(refresh.source_snapshots)
        if missing:
            raise PipelineInputError(f"required source snapshots unavailable: {sorted(missing)}")
        if refresh.unresolved_mappings:
            raise PipelineInputError(f"unresolved canonical mappings: {sorted(refresh.unresolved_mappings)}")
        for source, snapshot in refresh.source_snapshots.items():
            assert_snapshot_before(snapshot_timestamp=snapshot, prediction_timestamp=expected, source=source)
        for source, retrieved in refresh.retrieved_at.items():
            _utc(retrieved, f"{source}.retrieved_at")

        features = self.stages.build_features(context, refresh)
        assert_information_known(known_at=features.known_at, prediction_timestamp=expected,
                                 entity="feature bundle", source="feature pipeline")
        inference = self.stages.infer(context, features)
        assert_information_known(known_at=inference.known_at, prediction_timestamp=expected,
                                 entity="model inputs", source="inference pipeline")
        if not inference.model_versions:
            raise PipelineInputError("model versions are required")
        projection = self.stages.project(context, inference, request.fixture_horizon)
        if not projection.projections:
            raise PipelineInputError("projection pipeline returned no player projections")
        try:
            recommendation = self.optimizer.recommend(
                request.squad, projection.projections, request.player_pool,
                max_transfers=request.max_transfers, chip=request.chip,
            )
        except OptimizerError as error:
            raise PipelineInputError(str(error)) from error
        return self._output(request, refresh, features, inference, projection, recommendation)

    def _output(self, request, refresh, features, inference, projection, recommendation):
        transfers = tuple({"out": outgoing, "in": incoming}
                          for outgoing, incoming in zip(recommendation.transfers_out, recommendation.transfers_in))
        alternatives = tuple({"action": row.action, "utility": row.utility,
                              "transfers_out": row.transfers_out, "transfers_in": row.transfers_in,
                              "chip": row.chip} for row in recommendation.alternatives)
        confidence = recommendation.action_stability
        if confidence is None:
            confidence = 1.0 / (1.0 + max(0.0, -recommendation.decision_margin))
        provenance = {
            "configuration_hash": request.context.configuration_hash,
            "configuration": dict(request.context.configuration),
            "random_seed": request.context.random_seed,
            "dataset_versions": dict(refresh.dataset_versions),
            "feature_versions": dict(features.feature_versions),
            "model_versions": dict(inference.model_versions),
            "simulator_versions": projection.simulator_versions,
            "simulation_seeds": projection.simulation_seeds,
            "simulation_counts": projection.simulation_counts,
            "scoring_versions": projection.scoring_versions,
            "optimizer_version": recommendation.optimizer_version,
            "optimizer_rule_version": recommendation.rule_version,
            "source_snapshots": refresh.source_snapshots,
            "retrieved_at": refresh.retrieved_at,
            "fallback_usage": dict(features.fallback_usage),
            "source_coverage": {
                "required": request.context.required_sources,
                "available": tuple(sorted(refresh.source_snapshots)),
                "optional_unavailable": refresh.unavailable_optional_sources,
            },
            "metric_registry_version": METRIC_REGISTRY_VERSION,
        }
        plan = tuple({"gameweek": request.context.target_gameweek + offset,
                      "status": "provisional", "expected_squad_points": None}
                     for offset in range(6))
        return RecommendationOutput(
            request.context.run_id, request.context.season, request.context.prediction_timestamp,
            request.context.target_gameweek, recommendation.action, transfers, recommendation.starting_xi,
            recommendation.bench_order, recommendation.captain_id, recommendation.vice_captain_id,
            recommendation.chip, recommendation.raw_ev_1gw, recommendation.net_gain, confidence,
            alternatives, plan, provenance,
        )


@dataclass(frozen=True)
class PostGameweekRecord:
    run_id: str
    season: str
    gameweek: int
    prediction_timestamp: datetime
    completed_at: datetime
    predicted_points: Mapping[str, float]
    actual_points: Mapping[str, float]
    output_hash: str


class PostGameweekEvaluator:
    """Append-only production outcomes plus 5/10-GW and season monitoring."""
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.records_path = self.root / "post_gameweek.jsonl"
        self.metrics_path = self.root / "monitoring_metrics.json"

    def append(self, record: PostGameweekRecord) -> Mapping[str, object]:
        prediction, completed = _utc(record.prediction_timestamp, "prediction_timestamp"), _utc(record.completed_at, "completed_at")
        if completed <= prediction:
            raise PipelineInputError("completed_at must be after prediction_timestamp")
        if set(record.predicted_points) != set(record.actual_points) or not record.predicted_points:
            raise PipelineInputError("predicted and actual player sets must match and be non-empty")
        records = self._read()
        identity = (record.run_id, record.season, record.gameweek)
        if any((row["run_id"], row["season"], row["gameweek"]) == identity for row in records):
            raise PipelineInputError("post-Gameweek result already exists")
        serialized = _jsonable(asdict(record))
        with self.records_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(serialized, sort_keys=True) + "\n")
        records.append(serialized)
        report = self._monitor(records, record.season)
        self.metrics_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return report

    def _read(self) -> list[dict]:
        if not self.records_path.exists():
            return []
        return [json.loads(line) for line in self.records_path.read_text(encoding="utf-8").splitlines() if line]

    @staticmethod
    def _monitor(records: Sequence[Mapping], season: str) -> Mapping[str, object]:
        rows = sorted((row for row in records if row["season"] == season), key=lambda row: row["gameweek"])
        def summarize(selected):
            actual = [value for row in selected for value in row["actual_points"].values()]
            predicted = [row["predicted_points"][key] for row in selected for key in row["actual_points"]]
            return {name: metric(name, actual, predicted).to_dict() for name in ("mae", "rmse", "bias")}
        return {"season": season, "registry_version": METRIC_REGISTRY_VERSION,
                "last_5_gameweeks": summarize(rows[-5:]), "last_10_gameweeks": summarize(rows[-10:]),
                "season_to_date": summarize(rows), "gameweeks": len(rows)}


def recommendation_hash(output: RecommendationOutput) -> str:
    return hashlib.sha256(output.to_json().encode("utf-8")).hexdigest()


def _utc(value: datetime, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise PipelineInputError(f"{name} must be an aware datetime")
    return value.astimezone(timezone.utc)


def _jsonable(value):
    if isinstance(value, datetime):
        return _utc(value, "timestamp").isoformat()
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    return value
