from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from fpl_engine.optimizer import ChipState, Optimizer, OptimizerError, OptimizerRules, SquadPlayer, SquadState
from fpl_engine.pipeline import (
    FeatureResult, InferenceResult, PipelineInputError, PipelineRequest, PipelineStages,
    PostGameweekEvaluator, PostGameweekRecord, PredictionPipeline, ProjectionResult,
    RefreshResult, RunContext, recommendation_hash,
)
from fpl_engine.validation.backtesting import (
    BacktestMode, ChipOutcome, ComponentObservation, ExperimentMetadata, HistoricalPoint, OptimizerOutcome,
    PromotionDecision, ProjectionBacktestObservation, ReportStore, SimulationDistributionObservation,
    SeasonStep, V1ChampionManifest, WalkForwardRunner,
    backtest_chips, backtest_component, backtest_optimizer, backtest_player_projections, champion_challenger,
    backtest_team_strength, generate_synthetic_squads, simulate_season,
    validate_simulation_distributions, walk_forward_splits,
)
from fpl_engine.validation.leakage import FutureSnapshotError, LeakageError
from fpl_engine.validation.metrics import MetricError, brier, calibration, mae, metric, spearman


ROOT = Path(__file__).resolve().parents[1]
AT = datetime(2026, 9, 1, 12, tzinfo=timezone.utc)


def players(extra=False):
    positions = ["GK"] * 2 + ["DEF"] * 5 + ["MID"] * 5 + ["FWD"] * 3
    rows = [SquadPlayer(f"p{i}", position, f"c{i // 3}", 50, 50) for i, position in enumerate(positions)]
    if extra:
        rows.extend(SquadPlayer(f"x{i}", position, f"z{i // 3}", 45, 45)
                    for i, position in enumerate(positions))
    return tuple(rows)


def projections(rows, *, timestamp=AT, season="2026/27", rule_version=1):
    return {row.player_id: SimpleNamespace(
        player_id=row.player_id, season=season, rule_version=rule_version,
        prediction_timestamp=timestamp,
        gameweeks=(SimpleNamespace(expected_points=float(index + 1)),),
        weighted_ev_next_6=float(index + 1), ev_next_1=float(index + 1),
        ev_next_3=float(index + 1), ev_next_6=float(index + 1),
    ) for index, row in enumerate(rows)}


def metadata(component="MINUTES"):
    return ExperimentMetadata("exp-1", component, BacktestMode.STRICT, AT, AT - timedelta(days=30), AT,
                              ("2025/26",), ("data-v1",), ("features-v1",), ("model-v1",),
                              "config-hash", 7, "commit")


def test_metric_registry_perfect_predictions_calibration_and_rank_contracts():
    assert mae([1, 2], [1, 2]) == 0
    assert brier([0, 1], [0, 1]) == 0
    assert spearman([1, 2, 3], [1, 2, 3]) == pytest.approx(1)
    assert spearman([1, 2, 3], [3, 2, 1]) == pytest.approx(-1)
    table = calibration([True] * 7 + [False] * 3, [.7] * 10)
    assert table[0].observed_rate == pytest.approx(.7) and table[0].sample_size == 10
    assert metric("rmse", [1], [1]).sample_size == 1
    assert metric("minutes_mae", [10, 20], [10, 20]).value == 0
    with pytest.raises(MetricError):
        metric("unknown", [1], [1])


def test_walk_forward_is_chronological_and_enforces_strict_point_in_time_boundaries():
    points = tuple(HistoricalPoint(str(index), AT + timedelta(days=index), AT + timedelta(days=index),
                                   "2025/26", index + 1, AT + timedelta(days=index, seconds=-1))
                   for index in range(4))
    folds = walk_forward_splits(reversed(points), minimum_train_periods=2)
    assert folds[0].train_keys == ("0", "1") and folds[0].test_keys == ("2",)
    assert all(key not in fold.train_keys for fold in folds for key in fold.test_keys)
    with pytest.raises(FutureSnapshotError):
        walk_forward_splits((replace(points[0], snapshot_timestamp=points[0].prediction_timestamp), points[1]))
    weak = replace(points[0], point_in_time_quality="research")
    with pytest.raises(LeakageError):
        walk_forward_splits((weak, points[1]))
    assert walk_forward_splits((weak, points[1]), mode=BacktestMode.RESEARCH)


def test_component_and_projection_backtests_report_baselines_segments_horizons_and_ci():
    rows = tuple(ComponentObservation(str(i), AT + timedelta(days=i), AT + timedelta(days=i + 1),
                                      float(i), float(i) + .5, baseline=float(i) + 1,
                                      binary_actual=i % 2 == 0, probability=.6,
                                      segment="transfer" if i == 0 else "regular", block=f"gw{i}")
                 for i in range(4))
    report = backtest_component("PLAYER_TALENT", rows, metadata("PLAYER_TALENT"), bootstrap_samples=30)
    assert report.valid and report.metrics["mae"].value == .5
    assert report.baseline_metrics["mae"].value == 1
    assert report.baseline_deltas["mae"].improvement == .5
    assert set(report.segments) == {"regular", "transfer"}
    assert report.metrics["mae"].confidence_interval_low is not None

    projection_rows = tuple(ProjectionBacktestObservation(
        f"{h}-{i}", h, AT, AT + timedelta(days=h * 7), 5, 4 + i, .5, bool(i), .2, False,
        "MID", "rotation", f"gw{i}") for h in (1, 3, 6) for i in (0, 1))
    reports = backtest_player_projections(projection_rows, metadata("PLAYER_PROJECTION"), bootstrap_samples=10)
    assert set(reports) == {"1", "3", "6"}
    assert all("return_brier" in report.metrics and "haul_10_brier" in report.metrics for report in reports.values())

    candidates = {name: rows for name in ("league_average", "rolling_xg", "poisson", "dixon_coles")}
    team = backtest_team_strength(candidates, metadata("TEAM_STRENGTH"), bootstrap_samples=5)
    assert set(team) == set(candidates) and all(value.metadata.mode is BacktestMode.STRICT for value in team.values())


def test_walk_forward_runner_reports_coverage_without_future_fallback():
    points = tuple(HistoricalPoint(str(index), AT + timedelta(days=index), AT + timedelta(days=index),
                                   "2025/26", index + 1, AT + timedelta(days=index, seconds=-1))
                   for index in range(3))
    result = WalkForwardRunner().run(points, lambda point, train: None if point.key == "1" else len(train),
                                     require_complete=False)
    assert result.coverage.missing_keys == ("1",) and "1" not in result.predictions


def test_simulation_distribution_validation_and_synthetic_squads_are_reproducible():
    result = validate_simulation_distributions((
        SimulationDistributionObservation("a", {0: .5, 2: .5}, 2),
        SimulationDistributionObservation("b", {0: .5, 2: .5}, 0),
    ))
    assert result["mean_mae"].value == 1 and result["distribution_nll"].sample_size == 2
    rules = OptimizerRules.load(ROOT)
    pool = players(extra=True)
    first = generate_synthetic_squads(pool, rules, season=rules.season, prediction_timestamp=AT,
                                      count=3, seed=9, budgets=(1000,), free_transfer_states=(1, 2, 5))
    second = generate_synthetic_squads(pool, rules, season=rules.season, prediction_timestamp=AT,
                                       count=3, seed=9, budgets=(1000,), free_transfer_states=(1, 2, 5))
    assert first == second and {row.free_transfers for row in first} == {1, 2, 5}


def test_optimizer_report_champion_decisions_and_machine_readable_store(tmp_path):
    recommendation = SimpleNamespace(hit_cost=4, gross_gain=6, net_gain=2, decision_margin=1.5,
                                     action_stability=.8, action="TRANSFER", chip=None)
    report = backtest_optimizer((OptimizerOutcome("a", recommendation, 60, 55, 57, 58, 50, 52, 8, 10),))
    assert report.gain_vs_roll == 5 and report.gain_vs_greedy_1gw == 3
    assert report.lineup_regret == 2 and report.captain_regret == 2
    assert report.action_selection_frequency == {"TRANSFER": 1.0}
    chips = backtest_chips((ChipOutcome("a", "bench_boost", 80, 70), ChipOutcome("b", "bench_boost", 60, 65)))
    assert chips.by_chip["bench_boost"]["sample_size"] == 2
    manifest = champion_challenger(
        component="MINUTES", champion_version="v1", challenger_version="v2", primary_metric="mae",
        direction="lower", champion_value=10, challenger_value=9, confidence_interval=(.2, 1.8),
        practical_threshold=.5, evaluated_at=AT, period_start=AT - timedelta(days=10), period_end=AT,
        seasons=("2025/26",), sample_size=100, leakage_violations=0, configuration_hash="hash",
    )
    assert manifest.decision is PromotionDecision.PROMOTE
    target = ReportStore(tmp_path).write("champion", manifest)
    assert json.loads(target.read_text())["decision"] == "PROMOTE"
    rejected = champion_challenger(
        component="MINUTES", champion_version="v1", challenger_version="v2", primary_metric="mae",
        direction="lower", champion_value=10, challenger_value=9, confidence_interval=(.2, 1.8),
        practical_threshold=.5, evaluated_at=AT, period_start=AT - timedelta(days=10), period_end=AT,
        seasons=("2025/26",), sample_size=100, leakage_violations=1, configuration_hash="hash",
    )
    assert rejected.decision is PromotionDecision.REJECT
    active = V1ChampionManifest(AT, "2026/27", "team-v1", "minutes-v1", "talent-v1",
                                {"goals": "events-v1"}, "simulation-v1", 1, "projection-v1",
                                "optimizer-v1", 1, "metrics_v1", BacktestMode.STRICT, ("exp-1",), 0)
    assert json.loads(ReportStore(tmp_path).write("active", active).read_text())["team_strength"] == "team-v1"


def pipeline_fixture(*, snapshot=AT - timedelta(seconds=1), feature_known=AT, unresolved=(),
                     projection_timestamp=AT, projection_season="2026/27", projection_rule=1):
    rules = OptimizerRules.load(ROOT)
    owned = players()
    state = SquadState(owned, 10, 1, ChipState(), 5, rules.season, rules.version, AT)
    context = RunContext("run-1", rules.season, 5, AT, rules.version, ("fpl",), "config", 17)
    project_rows = projections(owned, timestamp=projection_timestamp, season=projection_season,
                               rule_version=projection_rule)
    stages = PipelineStages(
        lambda *_: RefreshResult({}, {"fpl": snapshot}, {"fpl": "snapshot-v1"}, {"fpl": AT + timedelta(minutes=1)}, unresolved),
        lambda *_: FeatureResult({}, feature_known, {"core": "features-v1"}),
        lambda *_: InferenceResult({}, feature_known, {"minutes": "minutes-v1"}),
        lambda *_: ProjectionResult(project_rows, ("sim-v1",), (1,), (17,)),
    )
    return PredictionPipeline(stages, Optimizer(rules)), PipelineRequest(context, state, {"canonical": {}}, (5, 6, 7, 8, 9, 10))


def test_full_pipeline_is_deterministic_machine_readable_and_keeps_provenance():
    pipeline, request = pipeline_fixture()
    first, second = pipeline.run(request), pipeline.run(request)
    assert first == second and first.target_gameweek == 5 and len(first.starting_xi) == 11
    payload = json.loads(first.to_json())
    assert payload["provenance"]["dataset_versions"] == {"fpl": "snapshot-v1"}
    assert payload["provisional_6gw_plan"][-1]["gameweek"] == 10
    assert recommendation_hash(first) == recommendation_hash(second)


@pytest.mark.parametrize("change,match", [
    ({"snapshot": AT}, "strictly before"),
    ({"feature_known": AT + timedelta(seconds=1)}, "after prediction_timestamp"),
    ({"unresolved": ("player:9",)}, "unresolved canonical mappings"),
    ({"projection_timestamp": AT + timedelta(seconds=1)}, "prediction_timestamp mismatch"),
    ({"projection_season": "2025/26"}, "season mismatch"),
    ({"projection_rule": 2}, "rule version mismatch"),
])
def test_pipeline_fails_fast_for_point_in_time_identity_and_contract_errors(change, match):
    pipeline, request = pipeline_fixture(**change)
    with pytest.raises((PipelineInputError, LeakageError), match=match):
        pipeline.run(request)


def test_post_gameweek_evaluation_is_append_only_and_updates_monitoring(tmp_path):
    evaluator = PostGameweekEvaluator(tmp_path)
    record = PostGameweekRecord("run-1", "2026/27", 5, AT, AT + timedelta(days=7),
                                {"p1": 4.0, "p2": 2.0}, {"p1": 5.0, "p2": 2.0}, "digest")
    report = evaluator.append(record)
    assert report["season_to_date"]["mae"]["value"] == .5
    assert evaluator.records_path.read_text().count("\n") == 1
    with pytest.raises(PipelineInputError, match="already exists"):
        evaluator.append(record)


def test_season_simulation_carries_own_squad_and_free_hit_restores_it():
    rules = OptimizerRules.load(ROOT)
    all_players = players(extra=True)
    initial_players = all_players[:15]
    initial = SquadState(initial_players, 250, 1, ChipState(), 5, rules.season, rules.version, AT)
    all_projections = projections(all_players)
    points = {row.player_id: 2.0 for row in all_players}
    minutes = {row.player_id: 90.0 for row in all_players}
    prices = {row.player_id: row.current_price for row in all_players}
    step = SeasonStep(5, AT, all_projections, all_players[15:], points, minutes, prices, AT, "free_hit")
    result = simulate_season(initial, (step,), Optimizer(rules))
    assert {row.player_id for row in result.final_state.players} == {row.player_id for row in initial.players}
    assert result.chip_gameweeks == {"free_hit": 5}

    incoming = all_players[-1]
    high = dict(all_projections)
    high[incoming.player_id] = SimpleNamespace(**{**vars(high[incoming.player_id]),
                                                  "weighted_ev_next_6": 100., "ev_next_1": 100.,
                                                  "ev_next_3": 100., "ev_next_6": 100.,
                                                  "gameweeks": (SimpleNamespace(expected_points=100.),)})
    step_one = SeasonStep(5, AT, high, (incoming,), points, minutes, prices, AT)
    later = AT + timedelta(days=7)
    step_two = SeasonStep(6, later, projections(all_players, timestamp=later), (), points, minutes, prices, later)
    first = simulate_season(initial, (step_one, step_two), Optimizer(rules), starting_state_kind="synthetic")
    assert incoming.player_id in {row.player_id for row in first.final_state.players}
    assert first.final_state.free_transfers == 2 and first.starting_state_kind == "synthetic"
    with pytest.raises(LeakageError):
        simulate_season(initial, (replace(step_one, prices_known_at=AT + timedelta(seconds=1)),), Optimizer(rules))

    missing_price = replace(step_one, current_prices={
        key: value for key, value in prices.items() if key != initial.players[0].player_id
    })
    with pytest.raises(OptimizerError, match="missing point-in-time current prices"):
        simulate_season(initial, (missing_price,), Optimizer(rules), starting_state_kind="reference")


def test_season_simulation_honors_strategy_selected_chip_and_records_gameweek_points():
    rules = OptimizerRules.load(ROOT)
    all_players = players(extra=True)
    initial_players = all_players[:15]
    initial = SquadState(initial_players, 250, 1, ChipState(), 5, rules.season, rules.version, AT)
    all_projections = projections(all_players)
    points = {row.player_id: 2.0 for row in all_players}
    minutes = {row.player_id: 90.0 for row in all_players}
    prices = {row.player_id: row.current_price for row in all_players}
    step = SeasonStep(5, AT, all_projections, all_players[15:], points, minutes, prices, AT)

    class TripleCaptainPolicy:
        def __init__(self):
            self.rules = rules
            self.optimizer = Optimizer(rules)

        def recommend(self, state, projections, pool, *, chip=None):
            return self.optimizer.recommend(state, projections, pool, chip="triple_captain")

    result = simulate_season(initial, (step,), TripleCaptainPolicy(), starting_state_kind="reference")
    assert result.chip_gameweeks == {"triple_captain": 5}
    assert result.gameweek_points[5] == result.total_points
    assert result.final_state.chips.triple_captain_h1 is False
