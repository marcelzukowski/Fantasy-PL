"""Season-versioned real-data STRICT V1/V2 backtest orchestration.

This module only adapts already materialized source evidence to existing V1
contracts. It does not train a new model family or synthesize missing features.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
import json
import lzma
import math
import hashlib
from pathlib import Path
import time
from uuid import NAMESPACE_URL, uuid5

import pandas as pd

from fpl_engine.config.loader import load_fpl_rules_config, load_scoring_rules_config
from fpl_engine.data.raw_store import RawSnapshot, RawStore
from fpl_engine.data.identity import (
    IdentityResolutionError, official_fpl_player_identity_key,
)
from fpl_engine.features.minutes_dataset import MinutesObservation
from fpl_engine.features.player_talent_dataset import PlayerPerformanceObservation
from fpl_engine.features.tactical_context import AvailabilityRecord, TacticalContextEngine
from fpl_engine.models.events import EventModels, EventModelsV2, PlayerFixtureInput
from fpl_engine.models.events.validation import EventOutcome, _score as event_score, walk_forward_events
from fpl_engine.models.minutes import MinutesContext, MinutesFeatureSignal, MinutesModel
from fpl_engine.models.minutes.baselines import (
    empirical_hurdle, previous_match_minutes, rolling_5_minutes, rolling_5_start_rate,
)
from fpl_engine.models.minutes.calibration import MinutesCalibrationPoint, fit_minutes_calibration
from fpl_engine.models.player_talent import PlayerTalentModel, PlayerTalentV2
from fpl_engine.models.player_talent.baselines import exponentially_weighted_per90, season_to_date_per90
from fpl_engine.models.team_strength import MatchObservation, TeamStrengthModel
from fpl_engine.models.team_strength.baselines import league_average, rolling_goals, rolling_xg
from fpl_engine.models.team_strength.validation import _metrics as team_metrics
from fpl_engine.models.projections import FixtureProjectionInput, ProjectionBuilder, _convolve
from fpl_engine.optimizer import (
    ChipState, ChipTimingPlanner, Optimizer, OptimizerError, OptimizerRules,
    OptimizerV2, OptimizerV2Config, SquadPlayer, SquadState, generate_candidates,
    validate_squad,
)
from fpl_engine.scoring import FPLScoringEngine
from fpl_engine.simulation import FixtureSimulator, SimulationConfig, benchmark_convergence
from fpl_engine.simulation.v2 import FixtureSimulatorV2

class FixtureSimulatorV21Audit(FixtureSimulatorV2):

    audit_team_count = 0
    audit_infeasible_p60 = 0
    audit_infeasible_papp = 0
    audit_player_p60_gt_pstart = 0

    audit_max_gk_p60 = 0.0
    audit_max_out_p60 = 0.0

    audit_max_gk_pstart = 0.0
    audit_max_out_pstart = 0.0

    audit_max_gk_papp = 0.0
    audit_max_out_papp = 0.0

    def simulate(self, events, team_strength):

        for team in (events.home, events.away):

            cls = type(self)
            cls.audit_team_count += 1

            groups = (
                (
                    "GK",
                    [
                        p for p in team.players
                        if p.rates.position == "GK"
                    ],
                    1,
                ),
                (
                    "OUT",
                    [
                        p for p in team.players
                        if p.rates.position != "GK"
                    ],
                    10,
                ),
            )

            for label, players, target in groups:

                p60 = sum(
                    float(p.clean_sheet.p_60_plus)
                    for p in players
                )

                pstart = sum(
                    float(p.rates.p_start)
                    for p in players
                )

                papp = sum(
                    float(p.rates.p_appearance)
                    for p in players
                )

                if label == "GK":
                    cls.audit_max_gk_p60 = max(
                        cls.audit_max_gk_p60,
                        p60,
                    )
                    cls.audit_max_gk_pstart = max(
                        cls.audit_max_gk_pstart,
                        pstart,
                    )
                    cls.audit_max_gk_papp = max(
                        cls.audit_max_gk_papp,
                        papp,
                    )
                else:
                    cls.audit_max_out_p60 = max(
                        cls.audit_max_out_p60,
                        p60,
                    )
                    cls.audit_max_out_pstart = max(
                        cls.audit_max_out_pstart,
                        pstart,
                    )
                    cls.audit_max_out_papp = max(
                        cls.audit_max_out_papp,
                        papp,
                    )

                if p60 > target + 1e-9:
                    cls.audit_infeasible_p60 += 1

                if papp < target - 1e-9:
                    cls.audit_infeasible_papp += 1

            for player in team.players:

                if (
                    float(player.clean_sheet.p_60_plus)
                    >
                    float(player.rates.p_start)
                    + 1e-9
                ):
                    cls.audit_player_p60_gt_pstart += 1

        return super().simulate(
            events,
            team_strength,
        )

from fpl_engine.validation.backtesting import (
    BacktestMode, ExperimentMetadata, ProjectionBacktestObservation, SeasonStep,
    backtest_player_projections, simulate_season,
)
from fpl_engine.validation.leakage import assert_snapshot_before


SEASON = "2024-25"
COMPETITION_ID = "comp_" + str(uuid5(NAMESPACE_URL, "Premier League"))
BACKTEST_SIMULATIONS_PER_FIXTURE = 512
BACKTEST_RANDOM_SEED = 202425
CONVERGENCE_SIMULATION_COUNTS = (32, 128, 512, 2_000, 10_000)
CONVERGENCE_REPRESENTATIVE_GAMEWEEKS = (1, 19, 38)
CONVERGENCE_PLAYER_METRIC_TOLERANCE = 0.30
CONVERGENCE_PROBABILITY_TOLERANCE = 0.03
CONVERGENCE_MINIMUM_RANK_SPEARMAN = 0.90
CONVERGENCE_MINIMUM_TOP_10_OVERLAP = 0.80


def _utc(value) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must be aware")
    return parsed.astimezone(timezone.utc)


def _identifier(kind: str, value: str) -> str:
    return f"{kind}_{uuid5(NAMESPACE_URL, value.casefold().strip())}"


def _raw_receipt(raw_root: Path, source_record_id: str, checksum: str) -> RawSnapshot:
    for path in raw_root.rglob("snapshot.metadata.json"):
        try:
            metadata = json.loads(path.read_text(encoding="utf-8"))
        except OSError:
            # A separately materialized provider receipt may be unavailable to
            # this process.  It is not evidence for the requested source; keep
            # searching and still fail if that requested receipt is absent.
            continue
        record = metadata.get("source_record_id") or ""
        if (record == source_record_id or record.endswith(f":{source_record_id}")) and metadata["checksum"] == checksum:
            metadata["source"] = metadata.pop("source_provider")
            return RawSnapshot.model_validate_json(json.dumps(metadata))
    raise RuntimeError(f"missing RawStore receipt for {source_record_id}")


def _snapshots(root: Path, source: dict) -> dict[int, dict]:
    raw = RawStore(root / "data" / "raw")
    output = {}
    for point in source["prediction_points"]:
        prediction = _utc(point["prediction_timestamp"])
        snapshot_at = _utc(point["snapshot_timestamp"])
        assert_snapshot_before(snapshot_timestamp=snapshot_at, prediction_timestamp=prediction,
                               source=f"fplcache GW{point['gameweek']}")
        receipt = _raw_receipt(raw.root, point["snapshot_path"], point["checksum"])
        body = raw.read_bytes(receipt)
        payload = json.loads(lzma.decompress(body))
        output[int(point["gameweek"])] = {
            "prediction_timestamp": prediction,
            "snapshot_timestamp": snapshot_at,
            "payload": payload,
        }
    return output


def _vaastav(root: Path, source: dict) -> pd.DataFrame:
    raw = RawStore(root / "data" / "raw")
    ref = source["vaastav_repository_ref"]
    receipt = _raw_receipt(raw.root, f"{ref}:{SEASON}:merged_gw", source["vaastav"]["checksum"])
    data = pd.read_csv(raw.root / receipt.payload_path)
    if "xP" not in data.columns:
        raise RuntimeError("expected Vaastav xP provenance column is absent")
    # xP is deliberately retained in raw evidence but never copied below.
    return data


def _float(value):
    return None if pd.isna(value) else float(value)


def _availability(element: dict) -> tuple[float | None, bool]:
    chance = element.get("chance_of_playing_next_round")
    if chance is not None:
        return float(chance) / 100.0, False
    status = element.get("status")
    if status == "a":
        return 1.0, False
    if status in {"s", "u"}:
        return 0.0, True
    return None, False


def _mean(rows, index):
    values = [row[index] for row in rows if row[index] is not None and not math.isnan(row[index])]
    return sum(values) / len(values) if values else None


def _ci95(values):
    selected = [float(value) for value in values if value is not None and math.isfinite(value)]
    if len(selected) < 2:
        return None
    mean = sum(selected) / len(selected)
    variance = sum((value - mean) ** 2 for value in selected) / (len(selected) - 1)
    margin = 1.96 * math.sqrt(variance / len(selected))
    return [mean - margin, mean + margin]


def _json_safe(value):
    if isinstance(value, float) and not math.isfinite(value):
        return "Infinity" if value > 0 else "-Infinity"
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def _aggregate_team(scores):
    return {name: {
        "sample_size": len(rows), "mae_goals": _mean(rows, 0),
        "poisson_deviance": _mean(rows, 1), "negative_log_likelihood": _mean(rows, 2),
        "negative_log_likelihood_ci95": _ci95(row[2] for row in rows),
        "brier_clean_sheet": _mean(rows, 3),
    } for name, rows in scores.items() if rows}


def _minutes_score(actual, expected, p_start, p60, p75=None, p90=None):
    return (abs(actual.minutes-expected), (actual.minutes-expected)**2,
            (p_start-float(actual.started))**2, (p60-float(actual.minutes >= 60))**2,
            None if p75 is None else (p75-float(actual.minutes >= 75))**2,
            None if p90 is None else (p90-float(actual.minutes >= 90))**2)


def _aggregate_minutes(scores):
    return {name: {
        "sample_size": len(rows), "mae_minutes": _mean(rows, 0),
        "mae_minutes_ci95": _ci95(row[0] for row in rows),
        "rmse_minutes": math.sqrt(_mean(rows, 1)), "brier_start": _mean(rows, 2),
        "brier_60_plus": _mean(rows, 3), "brier_75_plus": _mean(rows, 4),
        "brier_90": _mean(rows, 5),
    } for name, rows in scores.items() if rows}


def _projection_observations(
    projections, *, current_gameweek, provider_player_by_canonical,
    provider_fixture_by_canonical, outcome_by_fixture_player, positions_by_player,
):
    """Adapt production PlayerProjection output to the existing validation contract."""
    output = []
    for projection in projections:
        provider_player = provider_player_by_canonical.get(projection.player_id)
        if provider_player is None:
            continue
        for horizon, expected in ((1, projection.ev_next_1), (3, projection.ev_next_3), (6, projection.ev_next_6)):
            gameweeks = projection.gameweeks[:horizon]
            fixture_schedule = tuple((row.target_gameweek, fixture_id) for row in gameweeks for fixture_id in row.fixture_ids)
            fixture_ids = tuple(fixture_id for _, fixture_id in fixture_schedule)
            if not fixture_ids:
                continue
            targets = []
            for target_gameweek, fixture_id in fixture_schedule:
                provider_fixture = provider_fixture_by_canonical.get(fixture_id)
                target = outcome_by_fixture_player.get((provider_fixture, provider_player))
                # A fixture moved to another GW after T is not credited to the
                # originally predicted horizon.  The incomplete target is
                # excluded instead of borrowing its later result.
                if target is None or int(target[0]["GW"]) != target_gameweek:
                    targets = []
                    break
                targets.append(target)
            if not targets:
                continue
            pmf = {0: 1.0}
            for row in gameweeks:
                pmf = _convolve(pmf, row.points_distribution)
            actual_points = sum(float(target[0]["total_points"]) for target in targets)
            actual_returns = sum(int(target[0]["goals_scored"]) + int(target[0]["assists"]) for target in targets)
            fixture_count = len(fixture_ids)
            expected_minutes = sum(row.expected_minutes for row in gameweeks) / fixture_count
            risk = "high" if expected_minutes < 45 else "medium" if expected_minutes < 70 else "low"
            output.append(ProjectionBacktestObservation(
                key=f"GW{current_gameweek}:{projection.player_id}:{horizon}", horizon=horizon,
                prediction_timestamp=projection.prediction_timestamp,
                outcome_known_at=max(target[1].known_at for target in targets),
                expected_points=expected, actual_points=actual_points,
                p_return=1-math.prod(1-row.p_return for row in gameweeks), returned=actual_returns > 0,
                p_10_plus=sum(probability for points, probability in pmf.items() if points >= 10),
                scored_10_plus=actual_points >= 10,
                position=positions_by_player.get(projection.player_id), risk=risk,
                block=f"GW{current_gameweek}",
            ))
    return output


class _ReferenceStrategy:
    """Stateful historical policy wrapper with auditable decision records."""
    def __init__(self, rules, policy, *, pools_by_gameweek=None, use_player_chips=False):
        self.rules = rules
        self.policy = policy
        self.optimizer = Optimizer(rules)
        self.v2 = OptimizerV2(rules, OptimizerV2Config.from_rules(rules)) if policy == "optimizer_v2" else None
        self.pools_by_gameweek = pools_by_gameweek or {}
        self.chip_planner = ChipTimingPlanner(rules) if use_player_chips else None
        self.decision_records = []

    def recommend(self, state, projections, pool, *, chip=None):
        effective_pool = self.pools_by_gameweek.get(state.current_gameweek, pool)
        started = time.perf_counter()
        if state.current_gameweek == 1 or self.policy == "roll":
            recommendation = self.optimizer.recommend(state, projections, effective_pool, max_transfers=0)
        elif self.policy == "greedy_1gw":
            greedy = {player_id: replace(row, weighted_ev_next_6=row.ev_next_1)
                      for player_id, row in projections.items()}
            recommendation = self.optimizer.recommend(state, greedy, effective_pool, max_transfers=1)
        elif self.policy == "static_weighted_6gw":
            recommendation = self.optimizer.recommend(state, projections, effective_pool, max_transfers=1)
        elif self.policy == "optimizer_v2":
            recommendation = self.v2.recommend(state, projections, effective_pool, max_transfers=2)
        else:
            recommendation = self.optimizer.recommend(state, projections, effective_pool, max_transfers=2)
        chip_decision = None
        if self.chip_planner is not None:
            chip_decision = self.chip_planner.decide(state, projections, effective_pool)
            if chip_decision.chip is not None:
                chip_pool, _ = generate_candidates(
                    state, effective_pool, projections, OptimizerV2Config.from_rules(self.rules),
                )
                recommendation = self.optimizer.recommend(
                    state, projections, chip_pool, chip=chip_decision.chip,
                )
        v2_diagnostic = asdict(self.v2.last_diagnostic) if self.v2 and self.v2.last_diagnostic else None
        self.decision_records.append({
            "gameweek": state.current_gameweek,
            "state": state,
            "recommendation": recommendation,
            "v2_diagnostic": v2_diagnostic,
            "chip_evaluations": [asdict(row) for row in chip_decision.evaluations] if chip_decision else [],
            "runtime_seconds": time.perf_counter()-started,
        })
        return recommendation


def _snapshot_pool(payload, player_ids, team_ids):
    positions = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}
    output = []
    for element in payload["elements"]:
        element_id = int(element["id"])
        position = positions.get(int(element.get("element_type", 0)))
        team_id = team_ids.get(str(element.get("team")))
        price = element.get("now_cost")
        if element_id not in player_ids or position is None or team_id is None or price is None:
            continue
        output.append(SquadPlayer(player_ids[element_id], position, team_id, int(price), int(price)))
    return tuple(sorted(output, key=lambda row: row.player_id))


def _legal_seed_squad(pool, rules):
    required = {value["canonical_code"]: int(value["squad_count"])
                for value in rules.value("positions").values()}
    club_counts = defaultdict(int)
    selected = []
    for position, count in required.items():
        candidates = sorted((row for row in pool if row.position == position),
                            key=lambda row: (row.current_price, row.player_id))
        for player in candidates:
            if club_counts[player.club_id] >= int(rules.value("initial_squad", "maximum_players_per_club")):
                continue
            selected.append(player)
            club_counts[player.club_id] += 1
            if sum(row.position == position for row in selected) == count:
                break
    if len(selected) != int(rules.value("initial_squad", "squad_size")):
        raise RuntimeError("point-in-time GW1 pool cannot construct a legal 15-player seed squad")
    return tuple(selected)


def _initial_chip_state(rules):
    """Represent each season's configured chip count in the existing H1/H2 state."""
    totals = rules.value("chips", "total_per_season")
    return ChipState(
        wildcard_h2=int(totals.get("wildcard", 0)) >= 2,
        free_hit_h2=int(totals.get("free_hit", 0)) >= 2,
        bench_boost_h2=int(totals.get("bench_boost", 0)) >= 2,
        triple_captain_h2=int(totals.get("triple_captain", 0)) >= 2,
    )


def _finalist_stability(recommendation, projections, *, gameweek, runs=24):
    """Sensitivity of the recorded finalist set; never changes the EV objective."""
    if recommendation.action_stability is not None:
        return float(recommendation.action_stability)
    alternatives = recommendation.alternatives
    if len(alternatives) < 2:
        return 1.0
    seed = int.from_bytes(hashlib.sha256(
        f"{gameweek}|{recommendation.action}|{recommendation.transfers_out}|{recommendation.transfers_in}".encode()
    ).digest()[:8], "big")
    import random
    rng = random.Random(seed)
    target = (recommendation.transfers_out, recommendation.transfers_in)
    wins = 0
    for _ in range(runs):
        scored = []
        for alternative in alternatives:
            involved = alternative.transfers_out + alternative.transfers_in
            uncertainty = sum(float(getattr(projections[player_id], "projection_uncertainty", 0.0))
                              for player_id in involved) / len(involved) if involved else 0.0
            value = alternative.utility * max(0.0, 1+rng.gauss(0, uncertainty*.15))
            scored.append((value, -len(alternative.transfers_in), alternative.action == "ROLL_FT",
                           alternative.transfers_out, alternative.transfers_in))
        winner = max(scored)
        wins += (winner[3], winner[4]) == target
    return wins/runs


def _decision_diagnostics(strategy, steps, realized_by_gameweek, *, indifference_margin,
                          similar_projection_gain):
    rows = []
    records = strategy.decision_records
    for index, (record, step) in enumerate(zip(records, steps)):
        recommendation = record["recommendation"]
        projections = step.projections
        gain = lambda name: sum(float(getattr(projections[player_id], name)) for player_id in recommendation.transfers_in) - sum(
            float(getattr(projections[player_id], name)) for player_id in recommendation.transfers_out
        )
        involved = recommendation.transfers_in + recommendation.transfers_out
        uncertainty = sum(float(getattr(projections[player_id], "projection_uncertainty", 0.0))
                          for player_id in involved) / len(involved) if involved else 0.0
        outcome_keys = [
            (future_gw, player_id)
            for future_gw in range(step.gameweek, min(38, step.gameweek+2)+1)
            for player_id in involved
        ]
        missing_outcomes = [key for key in outcome_keys if key not in realized_by_gameweek]
        realized_gain = None if missing_outcomes else (
            sum(realized_by_gameweek[(future_gw, player_id)]
                for future_gw in range(step.gameweek, min(38, step.gameweek+2)+1)
                for player_id in recommendation.transfers_in)
            - sum(realized_by_gameweek[(future_gw, player_id)]
                  for future_gw in range(step.gameweek, min(38, step.gameweek+2)+1)
                  for player_id in recommendation.transfers_out)
            - recommendation.hit_cost
        )
        future_records = records[index+1:index+4]
        reversed_soon = any(
            player_id in later["recommendation"].transfers_out
            for player_id in recommendation.transfers_in for later in future_records
        )
        alternatives = recommendation.alternatives
        roll_utility = max((row.utility for row in alternatives if row.action == "ROLL_FT"), default=0.0)
        transfer_utility = max((row.utility for row in alternatives if row.action != "ROLL_FT"), default=None)
        if record["v2_diagnostic"] is not None:
            roll_utility = record["v2_diagnostic"]["roll_utility"]
            transfer_utility = record["v2_diagnostic"]["best_transfer_utility"]
        stability = _finalist_stability(recommendation, projections, gameweek=step.gameweek)
        weighted_gain = gain("weighted_ev_next_6")
        row = {
            "gameweek": step.gameweek, "action": recommendation.action,
            "roll_utility": roll_utility, "best_transfer_utility": transfer_utility,
            "gross_gain": recommendation.gross_gain, "hit_cost": recommendation.hit_cost,
            "net_gain": recommendation.net_gain, "transfer_count": len(recommendation.transfers_in),
            "transfers_out": list(recommendation.transfers_out),
            "transfers_in": list(recommendation.transfers_in),
            "free_transfers_before": recommendation.free_transfers_before,
            "free_transfers_after": recommendation.free_transfers_after,
            "bank_before": record["state"].bank, "bank_after": recommendation.resulting_bank,
            "gain_1gw": gain("ev_next_1"), "gain_3gw": gain("ev_next_3"),
            "gain_6gw": gain("ev_next_6"), "weighted_6gw_gain": weighted_gain,
            "decision_margin": recommendation.decision_margin,
            "projection_uncertainty": uncertainty, "sensitivity_stability": stability,
            "realized_subsequent_3gw_gain_after_hit": realized_gain,
            "realized_outcome_complete": not missing_outcomes,
            "missing_realized_outcomes": [f"GW{gw}:{player_id}" for gw, player_id in missing_outcomes],
            "beneficial_ex_post": None if realized_gain is None else realized_gain > 0,
            "unnecessary_hit_ex_post": None if realized_gain is None else recommendation.hit_cost > 0 and realized_gain <= 0,
            "reversed_within_3gw": reversed_soon,
            "tiny_margin": abs(recommendation.decision_margin) <= indifference_margin,
            "roll_better_ex_post": None if realized_gain is None else bool(recommendation.transfers_in) and realized_gain <= 0,
            "similar_projection_replacement": bool(involved) and abs(weighted_gain) <= similar_projection_gain,
            "chip": recommendation.chip,
            "chip_evaluations": record["chip_evaluations"],
            "runtime_seconds": record["runtime_seconds"],
        }
        if record["v2_diagnostic"] is not None:
            row["v2_search"] = record["v2_diagnostic"]
        rows.append(row)
    return rows


def _convergence_audit(
    simulator, representatives, action_inputs, *, projection_builder, snapshot,
    player_ids, team_ids, rules,
):
    fixture_reports = []
    for gameweek in CONVERGENCE_REPRESENTATIVE_GAMEWEEKS:
        events, strength = representatives[gameweek]
        report = benchmark_convergence(
            simulator, events, strength, counts=CONVERGENCE_SIMULATION_COUNTS,
            tolerance=CONVERGENCE_PLAYER_METRIC_TOLERANCE,
        )
        fixture_reports.append({"gameweek": gameweek, **asdict(report)})
    by_count = {}
    for count in CONVERGENCE_SIMULATION_COUNTS:
        rows = [row for report in fixture_reports for row in report["rows"]
                if row["simulation_count"] == count]
        rank_spearman = []
        top_ten_overlap = []
        for report in fixture_reports:
            fixture_rows = [row for row in report["rows"] if row["simulation_count"] == count]
            n = len(fixture_rows)
            rank_spearman.append(
                1-(6*sum(row["rank_delta"]**2 for row in fixture_rows))/(n*(n*n-1)) if n > 1 else 1.0
            )
            current_top = {row["player_id"] for row in fixture_rows if row["rank"] <= 10}
            reference_top = {row["player_id"] for row in fixture_rows if row["reference_rank"] <= 10}
            top_ten_overlap.append(len(current_top & reference_top)/max(1, len(reference_top)))
        by_count[str(count)] = {
            "maximum_player_ev_delta": max(row["expected_points_delta"] for row in rows),
            "maximum_return_probability_delta": max(row["p_return_delta"] for row in rows),
            "maximum_haul_probability_delta": max(row["p_10_plus_delta"] for row in rows),
            "maximum_absolute_rank_change": max(abs(row["rank_delta"]) for row in rows),
            "minimum_fixture_rank_spearman": min(rank_spearman),
            "minimum_top_10_overlap": min(top_ten_overlap),
        }

    projections_by_count = {}
    at = snapshot["prediction_timestamp"]
    for count in CONVERGENCE_SIMULATION_COUNTS:
        convergence_simulator = FixtureSimulator(
            simulator.scoring,
            replace(simulator.config, simulations_per_fixture=count, retain_simulations=False),
        )
        inputs = []
        for scheduled_gameweek, kickoff, known_at, events, strength in action_inputs:
            simulation = convergence_simulator.simulate(events, strength)
            inputs.append(FixtureProjectionInput(
                simulator.scoring.season, simulator.scoring.version, scheduled_gameweek,
                kickoff, known_at, simulation,
            ))
        projections = projection_builder.build(
            inputs, current_gameweek=19, player_ids=tuple(player_ids.values()),
        )
        projections_by_count[count] = {row.player_id: row for row in projections}
    pool = _snapshot_pool(snapshot["payload"], player_ids, team_ids)
    initial_budget = int(rules.value("initial_squad", "initial_budget"))
    seed_players = _legal_seed_squad(pool, rules)
    seed = SquadState(
        seed_players, initial_budget-sum(row.current_price for row in seed_players), 1,
        _initial_chip_state(rules), 19, rules.season, rules.version, at,
    )
    reference_players = Optimizer(rules)._unlimited_squad(
        seed, projections_by_count[10_000], pool,
    )
    fixed_state = replace(
        seed, players=reference_players,
        bank=initial_budget-sum(row.current_price for row in reference_players),
    )
    actions = {}
    for count, projections in projections_by_count.items():
        recommendation = OptimizerV2(
            rules, OptimizerV2Config.from_rules(rules),
        ).recommend(fixed_state, projections, pool, max_transfers=2)
        actions[str(count)] = {
            "action": recommendation.action,
            "transfers_out": list(recommendation.transfers_out),
            "transfers_in": list(recommendation.transfers_in),
            "decision_margin": recommendation.decision_margin,
            "matches_10000_action": (
                recommendation.action, recommendation.transfers_out, recommendation.transfers_in
            ),
        }
    reference_action = actions["10000"]["matches_10000_action"]
    for row in actions.values():
        row["matches_10000_action"] = row["matches_10000_action"] == reference_action
    practical = next((
        count for count in CONVERGENCE_SIMULATION_COUNTS
        if by_count[str(count)]["maximum_player_ev_delta"] <= CONVERGENCE_PLAYER_METRIC_TOLERANCE
        and by_count[str(count)]["maximum_return_probability_delta"] <= CONVERGENCE_PROBABILITY_TOLERANCE
        and by_count[str(count)]["maximum_haul_probability_delta"] <= CONVERGENCE_PROBABILITY_TOLERANCE
        and by_count[str(count)]["minimum_fixture_rank_spearman"] >= CONVERGENCE_MINIMUM_RANK_SPEARMAN
        and by_count[str(count)]["minimum_top_10_overlap"] >= CONVERGENCE_MINIMUM_TOP_10_OVERLAP
        and actions[str(count)]["matches_10000_action"]
    ), 10_000)
    return {
        "counts": list(CONVERGENCE_SIMULATION_COUNTS),
        "representative_gameweeks": list(CONVERGENCE_REPRESENTATIVE_GAMEWEEKS),
        "fixture_reports": fixture_reports,
        "summary_by_count": by_count,
        "optimizer_action_gameweek": 19,
        "optimizer_actions": actions,
        "practical_strict_count": practical,
        "production_default_unchanged": 10_000,
        "interpretation": "Smallest count with <=0.30 player-EV deviation, <=0.03 return/haul probability deviation, >=0.90 minimum fixture rank Spearman, >=0.80 top-10 overlap, and the same optimizer action as 10,000 at GW19.",
    }


def _run_reference_strategy(snapshots, outcomes, projections_by_gameweek, player_ids, team_ids, rules):
    gameweeks = tuple(sorted(snapshots))
    if set(projections_by_gameweek) != set(gameweeks):
        return {"label": "PLAYER_CHIPS_ONLY_REFERENCE", "status": "BLOCKED",
                "blocking_fields": ["complete projection sequence for every materialized Gameweek"]}
    pools = {gw: _snapshot_pool(snapshots[gw]["payload"], player_ids, team_ids) for gw in gameweeks}
    initial_budget = int(rules.value("initial_squad", "initial_budget"))
    seed_players = _legal_seed_squad(pools[1], rules)
    seed_state = SquadState(
        seed_players, initial_budget-sum(row.current_price for row in seed_players), 1,
        _initial_chip_state(rules), 1, rules.season, rules.version, snapshots[1]["prediction_timestamp"],
    )
    validate_squad(seed_state, rules)
    candidate_ids = {row.player_id for row in pools[1]}
    missing = candidate_ids-set(projections_by_gameweek[1])
    if missing:
        return {"label": "PLAYER_CHIPS_ONLY_REFERENCE", "status": "BLOCKED",
                "blocking_fields": [f"GW1 projections for {len(missing)} priced players"]}
    initial_players = Optimizer(rules)._unlimited_squad(
        seed_state, projections_by_gameweek[1], pools[1],
    )
    initial_state = replace(
        seed_state, players=initial_players,
        bank=initial_budget-sum(row.current_price for row in initial_players),
    )
    by_gw_player = defaultdict(lambda: {"points": 0.0, "minutes": 0.0})
    for row in outcomes.itertuples():
        element_id = int(row.element)
        if element_id not in player_ids:
            continue
        key = (int(row.GW), player_ids[element_id])
        by_gw_player[key]["points"] += float(row.total_points)
        by_gw_player[key]["minutes"] += float(row.minutes)
    steps = []
    shortlists = {}
    for gw in gameweeks:
        pool = pools[gw]
        ranked = []
        for position in ("GK", "DEF", "MID", "FWD"):
            positional = [row for row in pool if row.position == position]
            ranked.extend(sorted(
                positional,
                key=lambda row: (-projections_by_gameweek[gw][row.player_id].weighted_ev_next_6,
                                 row.current_price, row.player_id),
            )[:6])
            ranked.extend(sorted(positional, key=lambda row: (row.current_price, row.player_id))[:2])
        shortlist = tuple({row.player_id: row for row in ranked}.values())
        shortlists[gw] = shortlist
        current_prices = {row.player_id: row.current_price for row in pool}
        realized_points = {player_id: value["points"] for (actual_gw, player_id), value in by_gw_player.items()
                           if actual_gw == gw}
        realized_minutes = {player_id: value["minutes"] for (actual_gw, player_id), value in by_gw_player.items()
                            if actual_gw == gw}
        steps.append(SeasonStep(
            gw, snapshots[gw]["prediction_timestamp"], projections_by_gameweek[gw], pool,
            realized_points, realized_minutes, current_prices, snapshots[gw]["snapshot_timestamp"], None,
        ))
    strategies = {
        "ROLL": _ReferenceStrategy(rules, "roll", pools_by_gameweek=shortlists),
        "greedy_1GW": _ReferenceStrategy(rules, "greedy_1gw", pools_by_gameweek=shortlists),
        "static_weighted_6GW": _ReferenceStrategy(rules, "static_weighted_6gw", pools_by_gameweek=shortlists),
        "optimizer_V1": _ReferenceStrategy(rules, "optimizer_v1", pools_by_gameweek=shortlists),
        "optimizer_V2": _ReferenceStrategy(
            rules, "optimizer_v2", pools_by_gameweek=pools,
        ),
        "optimizer_V2_player_chips": _ReferenceStrategy(
            rules, "optimizer_v2", pools_by_gameweek=pools, use_player_chips=True,
        ),
    }
    results = {}
    realized_by_gameweek = {(gw, player_id): values["points"]
                            for (gw, player_id), values in by_gw_player.items()}
    roll_result = None
    for name, strategy in strategies.items():
        result = simulate_season(initial_state, steps, strategy, starting_state_kind="reference")
        if name == "ROLL":
            roll_result = result
        config = OptimizerV2Config.from_rules(rules)
        diagnostics = _decision_diagnostics(
            strategy, steps, realized_by_gameweek, indifference_margin=config.indifference_margin,
            similar_projection_gain=config.similar_projection_gain,
        )
        results[name] = {
            "total_points": result.total_points, "transfer_count": result.transfer_count,
            "hit_points": result.hit_points, "captain_points": result.captain_points,
            "hit_gameweeks": sum(row["hit_cost"] > 0 for row in diagnostics),
            "paid_transfers": result.hit_points // int(rules.value(
                "transfers", "normal_gameweek", "points_cost_per_transfer_above_allowance"
            )),
            "chip_gameweeks": dict(result.chip_gameweeks), "final_bank": result.final_state.bank,
            "final_free_transfers": result.final_state.free_transfers,
            "average_decision_margin": sum(abs(row["decision_margin"]) for row in diagnostics)/len(diagnostics),
            "average_action_stability": sum(row["sensitivity_stability"] for row in diagnostics)/len(diagnostics),
            "diagnostic_counts": {
                key: sum(bool(row[key]) for row in diagnostics) for key in (
                    "unnecessary_hit_ex_post", "reversed_within_3gw", "tiny_margin",
                    "roll_better_ex_post", "similar_projection_replacement",
                )
            },
            "decision_diagnostics": diagnostics,
            "gameweek_points": dict(result.gameweek_points),
        }
    roll_points = roll_result.total_points
    roll_by_gw = roll_result.gameweek_points
    for result in results.values():
        result["points_per_transfer"] = (
            (result["total_points"]-roll_points)/result["transfer_count"]
            if result["transfer_count"] else None
        )
        cumulative, difference = 0.0, {}
        for gw in gameweeks:
            cumulative += result["gameweek_points"].get(gw, 0.0)-roll_by_gw.get(gw, 0.0)
            difference[str(gw)] = cumulative
        result["cumulative_difference_vs_roll_by_gameweek"] = difference
    v1_counts = results["optimizer_V1"]["diagnostic_counts"]
    v2_counts = results["optimizer_V2"]["diagnostic_counts"]
    candidate_rows = [
        row["v2_search"]["candidate_report"]
        for row in results["optimizer_V2"]["decision_diagnostics"]
        if row.get("v2_search")
    ]
    return {
        "label": "PLAYER_CHIPS_ONLY_REFERENCE", "status": "EVALUATED",
        "assistant_manager_excluded": True,
        "chip_policy": "Optimizer V2 player-chip variant selects Wildcard, Free Hit, Bench Boost or Triple Captain only when configured incremental EV versus no chip clears its threshold and is competitive with known horizon opportunities; no DGW trigger is used.",
        "starting_squad": [row.player_id for row in initial_state.players],
        "starting_bank": initial_state.bank, "starting_free_transfers": initial_state.free_transfers,
        "candidate_generation": {
            "baselines_and_v1": "top 6 weighted-6GW plus 2 cheapest per position at each deadline",
            "optimizer_v2": "deterministic union of top 1GW, 3GW, 6GW, weighted-6GW, value-efficiency and low-price candidates; configured cap per position",
            "benchmark": {
                "average_available_players": sum(row["available"] for row in candidate_rows)/len(candidate_rows),
                "average_selected_players": sum(row["selected"] for row in candidate_rows)/len(candidate_rows),
                "average_top_weighted_coverage": sum(row["top_weighted_coverage"] for row in candidate_rows)/len(candidate_rows),
                "average_generation_runtime_seconds": sum(row["runtime_seconds"] for row in candidate_rows)/len(candidate_rows),
                "maximum_selected_per_position": OptimizerV2Config.from_rules(rules).maximum_candidates_per_position,
            },
        },
        "decision_quality": {
            "v1_root_causes": {
                "hits_without_positive_subsequent_3gw_gain": v1_counts["unnecessary_hit_ex_post"],
                "short_term_reversals": v1_counts["reversed_within_3gw"],
                "roll_better_ex_post": v1_counts["roll_better_ex_post"],
                "tiny_margin_actions": v1_counts["tiny_margin"],
            },
            "v2_change": {
                "transfer_reduction": results["optimizer_V1"]["transfer_count"]-results["optimizer_V2"]["transfer_count"],
                "hit_point_reduction": results["optimizer_V1"]["hit_points"]-results["optimizer_V2"]["hit_points"],
                "short_term_reversal_reduction": v1_counts["reversed_within_3gw"]-v2_counts["reversed_within_3gw"],
                "strict_points_delta": results["optimizer_V2"]["total_points"]-results["optimizer_V1"]["total_points"],
            },
        },
        "gameweeks": list(gameweeks), "strategies": results,
    }


def _talent_error(actual, rate):
    if actual.xa is None or rate is None:
        return None
    return abs(actual.xa - rate * actual.minutes / 90)


def _markdown(report: dict) -> str:
    lines = [
        f"# {report['season']} STRICT real-data backtest", "",
        f"- Status: **{report['status']}**",
        f"- Leakage violations: **{report['leakage_violations']}**",
        f"- Prediction deadlines: **{report['coverage']['prediction_points']}**", "",
    ]
    for title, key in (("Team Strength", "team_strength"), ("Minutes", "minutes"),
                       ("Player Talent", "player_talent"), ("Event Models", "event_models")):
        item = report["components"][key]
        lines += [f"## {title}", "", f"Status: `{item['status']}`. Champion decision: `{item.get('champion_decision', 'KEEP_TESTING')}`.", ""]
        for name, metrics in item.get("candidates", {}).items():
            lines.append(f"- `{name}`: {json.dumps(metrics, sort_keys=True)}")
        if item.get("unavailable_fields"):
            lines += ["", "Unavailable: " + ", ".join(item["unavailable_fields"]) + "."]
        lines.append("")
    lines += ["## Player projections", "", report["components"]["projections"]["reason"], ""]
    for horizon, result in report["components"]["projections"].get("horizons", {}).items():
        metrics = {name: value["value"] for name, value in result.get("metrics", {}).items()}
        lines.append(f"- `{horizon}GW`: {json.dumps(metrics, sort_keys=True)}")
    reference = report["reference_strategy"]
    lines += ["", "## Reference optimizer", "",
              f"Status: `{reference['status']}`. Label: `{reference['label']}`.", ""]
    if reference.get("reason"):
        lines.append(reference["reason"])
    for name, result in reference.get("strategies", {}).items():
        summary = {key: value for key, value in result.items() if key not in {
            "decision_diagnostics", "gameweek_points", "cumulative_difference_vs_roll_by_gameweek",
        }}
        lines.append(f"- `{name}`: {json.dumps(summary, sort_keys=True)}")
    if reference.get("decision_quality"):
        lines += ["", "## Optimizer decision quality", "",
                  "V1 diagnosis: `" + json.dumps(reference["decision_quality"]["v1_root_causes"], sort_keys=True) + "`.", "",
                  "V2 change: `" + json.dumps(reference["decision_quality"]["v2_change"], sort_keys=True) + "`.", "",
                  "Candidate benchmark: `" + json.dumps(reference["candidate_generation"]["benchmark"], sort_keys=True) + "`."]
    convergence = report["components"]["projections"].get("convergence_audit")
    if convergence:
        lines += ["", "## Monte Carlo convergence", "",
                  f"Practical STRICT count: **{convergence['practical_strict_count']}**; production remains **10,000**.", ""]
        for count, metrics in convergence["summary_by_count"].items():
            lines.append(f"- `{count}`: {json.dumps(metrics, sort_keys=True)}")
    lines.append("")
    return "\n".join(lines)


def run(
    root: Path, season: str = SEASON, *, simulations_per_fixture: int | None = None,
    random_seed: int | None = None, advanced_challenger: bool = False,
    talent_v2_only: bool = False,
    skip_reference: bool = False, skip_convergence: bool = False,
    bootstrap_samples: int = 200,
) -> tuple[Path, Path]:
    runtime_started = time.perf_counter()
    global SEASON, BACKTEST_SIMULATIONS_PER_FIXTURE, BACKTEST_RANDOM_SEED
    SEASON = season
    season_label = season.replace("-", "/")
    BACKTEST_SIMULATIONS_PER_FIXTURE = simulations_per_fixture or 32
    BACKTEST_RANDOM_SEED = random_seed if random_seed is not None else int(season.replace("-", ""))
    use_talent_v2 = advanced_challenger or talent_v2_only
    use_assist_v2 = advanced_challenger
    if bootstrap_samples < 0:
        raise ValueError("bootstrap_samples must be >= 0")
    interim = root / "data" / "interim" / "strict" / season
    source = json.loads((interim / "source_manifest.json").read_text(encoding="utf-8"))
    fixture_manifest = json.loads((interim / "fixture_schedule_manifest.json").read_text(encoding="utf-8"))
    if fixture_manifest["missing_gameweeks"]:
        raise RuntimeError("fixture schedule coverage is incomplete")
    snapshots = _snapshots(root, source)
    outcomes = _vaastav(root, source)
    states = pd.read_parquet(interim / "canonical_fixture_states.parquet")
    states["prediction_timestamp"] = pd.to_datetime(states["prediction_timestamp"], utc=True)
    states["information_known_at"] = pd.to_datetime(states["information_known_at"], utc=True)
    if (states["information_known_at"] >= states["prediction_timestamp"]).any():
        raise RuntimeError("fixture state violates strict commit_timestamp < prediction_timestamp")

    first_states = states.sort_values("prediction_gameweek").drop_duplicates("provider_fixture_id")
    fixture_ids = dict(zip(first_states.provider_fixture_id.astype(str), first_states.canonical_fixture_id))
    team_ids = {}
    for row in first_states.itertuples():
        team_ids[str(row.provider_home_team_id)] = row.canonical_home_team_id
        team_ids[str(row.provider_away_team_id)] = row.canonical_away_team_id
    first_elements = {}
    for gw in sorted(snapshots):
        for element in snapshots[gw]["payload"]["elements"]:
            first_elements.setdefault(int(element["id"]), element)
    player_ids = {}
    seen_player_keys = {}
    for element_id, element in first_elements.items():
        try:
            identity_key = official_fpl_player_identity_key(element)
        except IdentityResolutionError as exc:
            raise RuntimeError(
                f"Official FPL player {element_id} lacks a safe identity key: {exc}"
            ) from exc

        previous = seen_player_keys.get(identity_key)
        if previous is not None and previous != element_id:
            raise RuntimeError(
                f"Official FPL player code identity collision: "
                f"{previous} and {element_id} share {identity_key}"
            )

        seen_player_keys[identity_key] = element_id
        player_ids[element_id] = _identifier("player", identity_key)

    team_name_to_provider = {}
    for team in snapshots[1]["payload"]["teams"]:
        for name in (team.get("name"), team.get("short_name")):
            if name:
                team_name_to_provider[str(name)] = str(team["id"])

    outcomes["fixture_key"] = outcomes["fixture"].astype(int).astype(str)
    outcomes["kickoff_dt"] = pd.to_datetime(outcomes["kickoff_time"], utc=True)
    outcome_by_fixture_player = {}
    minutes_history = defaultdict(list)
    talent_history = defaultdict(list)
    match_rows = []
    for fixture_key, group in outcomes.groupby("fixture_key", sort=False):
        if fixture_key not in fixture_ids:
            continue
        kickoff = group["kickoff_dt"].iloc[0].to_pydatetime()
        known_at = kickoff + timedelta(hours=4)
        home = group[group["was_home"] == True]
        away = group[group["was_home"] == False]
        state = first_states[first_states.provider_fixture_id.astype(str) == fixture_key].iloc[0]
        home_xg = home["expected_goals"].sum(min_count=1)
        away_xg = away["expected_goals"].sum(min_count=1)
        match_rows.append(MatchObservation(
            fixture_ids[fixture_key], kickoff, known_at,
            state.canonical_home_team_id, state.canonical_away_team_id,
            float(group["team_h_score"].dropna().iloc[0]), float(group["team_a_score"].dropna().iloc[0]),
            _float(home_xg), _float(away_xg), season,
        ))
        team_xa = {True: _float(home["expected_assists"].sum(min_count=1)),
                   False: _float(away["expected_assists"].sum(min_count=1))}
        for _, row in group.iterrows():
            element_id = int(row["element"])
            if element_id not in player_ids:
                continue
            pid = player_ids[element_id]
            minutes = int(row["minutes"])
            started = bool(int(row["starts"]))
            minute = MinutesObservation(pid, fixture_ids[fixture_key], kickoff, known_at, minutes, started)
            provider_team = team_name_to_provider.get(str(row["team"]))
            if provider_team is None:
                continue
            talent = PlayerPerformanceObservation(
                pid, fixture_ids[fixture_key], kickoff, known_at, minutes, team_ids[provider_team],
                COMPETITION_ID, str(row["position"]), npxg=None,
                xa=_float(row["expected_assists"]), shots=None, goals=_float(row["goals_scored"]),
                team_xa=team_xa[bool(row["was_home"])], source="vaastav",
                source_fields=("expected_assists",),
            )
            minutes_history[element_id].append(minute)
            talent_history[element_id].append(talent)
            outcome_by_fixture_player[(fixture_key, element_id)] = (row, minute, talent)

    team_scores = defaultdict(list)
    minutes_scores = defaultdict(list)
    talent_scores = defaultdict(list)
    event_outcomes = []
    projection_outcomes = []
    projections_by_gameweek = {}
    simulation_fixture_count = 0
    player_fixture_simulations = 0
    monte_carlo_player_draws = 0
    calibration_points = []
    coverage = {name: {} for name in ("team_strength", "minutes", "player_talent", "event_models", "projections")}
    team_model, minute_model = TeamStrengthModel(), MinutesModel()
    talent_model = PlayerTalentV2() if use_talent_v2 else PlayerTalentModel()
    event_model = EventModelsV2() if use_assist_v2 else EventModels()
    tactical_model = TacticalContextEngine()
    historical_scoring_engine = FPLScoringEngine.from_project(root, season=season_label)
    simulator = FixtureSimulatorV21Audit(historical_scoring_engine, SimulationConfig(
        simulations_per_fixture=BACKTEST_SIMULATIONS_PER_FIXTURE,
        random_seed=BACKTEST_RANDOM_SEED,
        retain_simulations=False,
    ))
    projection_builder = ProjectionBuilder()
    fixture_actual = {row.fixture_id: row for row in match_rows}
    provider_player_by_canonical = {value: key for key, value in player_ids.items()}
    provider_fixture_by_canonical = {value: key for key, value in fixture_ids.items()}
    positions = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}
    convergence_representatives = {}
    convergence_action_inputs = []

    for gw in sorted(snapshots):
        snapshot = snapshots[gw]
        at, snapshot_at, payload = snapshot["prediction_timestamp"], snapshot["snapshot_timestamp"], snapshot["payload"]
        current_states = states[
            (states.prediction_gameweek == gw)
            & (states.scheduled_gameweek >= gw)
            & (states.scheduled_gameweek <= gw + 5)
        ]
        current_states = current_states[current_states.scheduled_kickoff > pd.Timestamp(at)]

        # PIT hardening for rescheduled fixtures:
        # a stale schedule snapshot may still place a fixture in the future
        # even though the match has already been played and its result was
        # known before the prediction timestamp.
        known_completed_fixture_ids = {
            row.fixture_id
            for row in match_rows
            if row.known_at <= at and row.kickoff < at
        }

        current_states = current_states[
            ~current_states.canonical_fixture_id.isin(
                known_completed_fixture_ids
            )
        ]

        history_matches = [
            row
            for row in match_rows
            if row.known_at <= at and row.kickoff < at
        ]
        element_by_team = defaultdict(list)
        for element in payload["elements"]:
            element_by_team[str(element["team"])].append(element)
        eligible_calibration = [point for point in calibration_points if point.known_at <= at]
        calibration = fit_minutes_calibration(eligible_calibration, training_cutoff=at) if len(eligible_calibration) >= 200 else None
        counts = defaultdict(int)
        projection_inputs = []
        positions_by_player = {}
        talent_cache = {}
        for state in current_states.itertuples():
            fixture_key = str(state.provider_fixture_id)
            actual_match = fixture_actual.get(state.canonical_fixture_id)
            is_current = int(state.scheduled_gameweek) == gw
            strength = team_model.predict(
                history_matches, state.canonical_home_team_id, state.canonical_away_team_id, at,
                target_fixture_id=state.canonical_fixture_id,
            )
            if is_current and actual_match is not None:
                predictions = (
                    league_average(history_matches, at),
                    rolling_goals(history_matches, state.canonical_home_team_id, state.canonical_away_team_id, at),
                    rolling_xg(history_matches, state.canonical_home_team_id, state.canonical_away_team_id, at),
                )
                for candidate_name, prediction in zip(
                    ("league_average_v1", "rolling_goals_v1", "rolling_xg_v1", strength.model_id),
                    (*predictions, strength),
                ):
                    team_scores[candidate_name].append(team_metrics(
                        actual_match, prediction.expected_home_goals, prediction.expected_away_goals,
                    ))
                counts["team_strength"] += 1
            player_inputs = {"home": [], "away": []}
            for side, provider_team, canonical_team in (
                ("home", str(state.provider_home_team_id), state.canonical_home_team_id),
                ("away", str(state.provider_away_team_id), state.canonical_away_team_id),
            ):
                for element in element_by_team.get(provider_team, []):
                    element_id = int(element["id"])
                    if int(element["element_type"]) not in positions:
                        # Assistant-manager entries are outside the V1 player models.
                        continue
                    target = outcome_by_fixture_player.get((fixture_key, element_id))
                    if element_id not in player_ids:
                        continue
                    actual_row, actual_minutes, actual_talent = target if target is not None else (None, None, None)
                    position = positions[int(element["element_type"])]
                    player_id = player_ids[element_id]
                    positions_by_player[player_id] = position
                    prior_minutes = [row for row in minutes_history[element_id] if row.known_at <= at and row.fixture_id != state.canonical_fixture_id]
                    probability, definitely_unavailable = _availability(element)
                    context = MinutesContext(
                        player_id, state.canonical_fixture_id, at,
                        position=position, availability_probability=probability,
                        availability_known_at=snapshot_at, availability_confidence=1.0 if probability is not None else None,
                        definitely_unavailable=definitely_unavailable,
                        signals=(MinutesFeatureSignal(
                            "status", element.get("status"), snapshot_at, snapshot_at, "fplcache",
                            source_snapshot_timestamp=snapshot_at,
                        ),),
                    )
                    raw_minutes = minute_model.predict(prior_minutes, context)
                    calibrated_minutes = minute_model.predict(prior_minutes, context, calibration=calibration) if calibration else raw_minutes
                    if is_current and actual_minutes is not None:
                        minute_candidates = (
                            previous_match_minutes(prior_minutes, player_id, state.canonical_fixture_id, at),
                            rolling_5_minutes(prior_minutes, player_id, state.canonical_fixture_id, at),
                            rolling_5_start_rate(prior_minutes, player_id, state.canonical_fixture_id, at),
                            empirical_hurdle(prior_minutes, player_id, state.canonical_fixture_id, at),
                        )
                        for prediction in minute_candidates:
                            minutes_scores[prediction.model_id].append(_minutes_score(
                                actual_minutes, prediction.expected_minutes, prediction.p_start, prediction.p_60_plus,
                            ))
                        minutes_scores[raw_minutes.model_version].append(_minutes_score(
                            actual_minutes, raw_minutes.expected_minutes, raw_minutes.p_start, raw_minutes.p60,
                            raw_minutes.p75, raw_minutes.p90,
                        ))
                        minutes_scores["minutes_hurdle_v1_platt_calibrated"].append(_minutes_score(
                            actual_minutes, calibrated_minutes.expected_minutes, calibrated_minutes.p_start,
                            calibrated_minutes.p60, calibrated_minutes.p75, calibrated_minutes.p90,
                        ))
                        calibration_points.append(MinutesCalibrationPoint(
                            raw_minutes.p_appearance, raw_minutes.p_start, raw_minutes.p60, raw_minutes.p75,
                            raw_minutes.p90, actual_minutes.appeared, actual_minutes.started, actual_minutes.minutes,
                            actual_minutes.known_at,
                        ))
                        counts["minutes"] += 1

                    prior_talent = [row for row in talent_history[element_id] if row.known_at <= at and row.fixture_id != state.canonical_fixture_id]
                    talent_key = (player_id, canonical_team, position)
                    talent = talent_cache.get(talent_key)
                    if talent is None:
                        talent = talent_model.predict(
                            prior_talent, player_id=player_id,
                            target_fixture_id=state.canonical_fixture_id,
                            prediction_timestamp=at, current_team_id=canonical_team,
                            current_competition_id=COMPETITION_ID, fpl_position=position,
                        )
                        talent_cache[talent_key] = talent
                    if is_current and actual_talent is not None:
                        baselines = (
                            season_to_date_per90(prior_talent, player_id, state.canonical_fixture_id, at),
                            exponentially_weighted_per90(prior_talent, player_id, state.canonical_fixture_id, at),
                        )
                        baseline_errors = [_talent_error(actual_talent, baseline.xa_per90) for baseline in baselines]
                        model_error = _talent_error(actual_talent, talent.talent_xa_per90)
                        if model_error is not None and all(error is not None for error in baseline_errors):
                            for baseline, error in zip(baselines, baseline_errors):
                                talent_scores[baseline.model_id].append(error)
                            talent_scores[talent.model_version].append(model_error)
                            counts["player_talent"] += 1
                    availability_record = AvailabilityRecord(
                        effective_from=snapshot_at, known_at=snapshot_at, source="fplcache",
                        confidence=1.0, player_id=player_id, status=element.get("status"),
                        chance_of_playing=element.get("chance_of_playing_next_round"),
                        confirmed_suspension=element.get("status") == "s", snapshot_timestamp=snapshot_at,
                    )
                    tactical = tactical_model.resolve(
                        player_id=player_id, team_id=canonical_team, prediction_timestamp=at,
                        target_fixture_id=state.canonical_fixture_id, availability=(availability_record,),
                    )
                    player_inputs[side].append(PlayerFixtureInput(
                        player_id, canonical_team, state.canonical_fixture_id, at, position,
                        calibrated_minutes, talent, tactical_context=tactical,
                    ))
            fixture_events = event_model.predict_fixture(
                player_inputs["home"], player_inputs["away"], fixture_id=state.canonical_fixture_id,
                prediction_timestamp=at, team_strength=strength,
            )
            if is_current and gw in CONVERGENCE_REPRESENTATIVE_GAMEWEEKS:
                convergence_representatives.setdefault(gw, (fixture_events, strength))
            if is_current and gw == 19:
                convergence_action_inputs.append((
                    int(state.scheduled_gameweek), _utc(state.scheduled_kickoff),
                    _utc(state.information_known_at), fixture_events, strength,
                ))
            simulation = simulator.simulate(fixture_events, strength)
            projection_inputs.append(FixtureProjectionInput(
                season_label, historical_scoring_engine.version, int(state.scheduled_gameweek),
                _utc(state.scheduled_kickoff), _utc(state.information_known_at), simulation,
            ))
            simulation_fixture_count += 1
            player_fixture_simulations += len(simulation.summaries)
            monte_carlo_player_draws += len(simulation.summaries) * BACKTEST_SIMULATIONS_PER_FIXTURE
            for prediction in (*fixture_events.home.players, *fixture_events.away.players):
                provider_player = provider_player_by_canonical.get(prediction.rates.player_id)
                target = outcome_by_fixture_player.get((fixture_key, provider_player)) if provider_player is not None else None
                if not is_current or target is None:
                    continue
                row = target[0]
                event_outcomes.append(EventOutcome(
                    prediction, target[1].known_at, int(row["goals_scored"]), int(row["assists"]),
                    saves=int(row["saves"]) if prediction.rates.position == "GK" else None,
                    defensive_contributions=None, yellow=bool(int(row["yellow_cards"])),
                    red=bool(int(row["red_cards"])),
                ))
                counts["event_models"] += 1
        if projection_inputs:
            projections = projection_builder.build(
                projection_inputs, current_gameweek=gw,
                player_ids=tuple(player_ids[int(element["id"])] for element in payload["elements"]
                                 if int(element.get("element_type", 0)) in positions and int(element["id"]) in player_ids),
            )
            projections_by_gameweek[gw] = {projection.player_id: projection for projection in projections}
            observations = _projection_observations(
                projections, current_gameweek=gw,
                provider_player_by_canonical=provider_player_by_canonical,
                provider_fixture_by_canonical=provider_fixture_by_canonical,
                outcome_by_fixture_player=outcome_by_fixture_player,
                positions_by_player=positions_by_player,
            )
            projection_outcomes.extend(observations)
            counts["projections"] = len(observations)
        for component in coverage:
            coverage[component][str(gw)] = counts[component]

    team_candidates = _aggregate_team(team_scores)
    minute_candidates = _aggregate_minutes(minutes_scores)
    talent_candidates = {name: {"sample_size": len(values), "mae_xa": sum(values)/len(values),
                                "mae_xa_ci95": _ci95(values)}
                         for name, values in talent_scores.items() if values}
    event_baseline_id = "raw_per90_talent_v2" if use_talent_v2 else "raw_per90_baseline_v1"
    event_report = walk_forward_events(
        event_outcomes, minimum_history=2, baseline_model_id=event_baseline_id,
    ) if event_outcomes else None
    event_candidates = {item.model_id: asdict(item) for item in event_report.candidates} if event_report else {}
    if event_report:
        first_event_prediction = min(item.prediction.rates.prediction_timestamp for item in event_outcomes)
        eligible_events = [item for item in event_outcomes
                           if item.prediction.rates.prediction_timestamp > first_event_prediction]
        coherent_name = next(name for name in event_candidates if name != event_baseline_id)
        for name, coherent in ((event_baseline_id, False), (coherent_name, True)):
            scored = [event_score(
                outcome,
                outcome.prediction.goals.expected_goals if coherent else outcome.prediction.rates.raw_expected_npxg,
                outcome.prediction.assists.expected_assists if coherent else outcome.prediction.rates.raw_expected_xa,
            ) for outcome in eligible_events]
            event_candidates[name]["goal_log_loss_ci95"] = _ci95(row[1] for row in scored)
            event_candidates[name]["assist_log_loss_ci95"] = _ci95(row[4] for row in scored)
    team_winner = min(team_candidates, key=lambda key: team_candidates[key]["negative_log_likelihood"])
    minute_winner = min(minute_candidates, key=lambda key: minute_candidates[key]["mae_minutes"])
    talent_winner = min(talent_candidates, key=lambda key: talent_candidates[key]["mae_xa"])
    projection_metadata = ExperimentMetadata(
        experiment_id=f"strict-{season}-player-projections",
        component="PLAYER_PROJECTIONS", mode=BacktestMode.STRICT,
        started_at=max(item["prediction_timestamp"] for item in snapshots.values()),
        period_start=min(item["prediction_timestamp"] for item in snapshots.values()),
        period_end=max(item["prediction_timestamp"] for item in snapshots.values()),
        seasons=(season_label,),
        data_versions=(source["fplcache_repository_ref"], source["vaastav_repository_ref"],
                       fixture_manifest["repository_head_examined"]),
        feature_versions=("minutes_features_v1", "tactical_roles_v1",
                          "assist_allocation_features_v2" if use_assist_v2 else "event_features_v1"),
        model_versions=("team_strength_v1", "minutes_hurdle_v1",
                        "player_talent_reliability_v2" if use_talent_v2 else "player_talent_v1",
                        "coherent_assists_v2" if use_assist_v2 else "event_models_v1",
                        FixtureSimulatorV2.VERSION, "projection_builder_v1"),
        configuration_hash=f"scoring-{historical_scoring_engine.version}-sim-{BACKTEST_SIMULATIONS_PER_FIXTURE}",
        random_seed=BACKTEST_RANDOM_SEED,
    )
    projection_reports = backtest_player_projections(
        projection_outcomes, projection_metadata, bootstrap_samples=bootstrap_samples,
    ) if projection_outcomes else {}
    projection_metrics = {horizon: component.to_dict() for horizon, component in projection_reports.items()}
    # Explicit seasonal loads are also a guard against an accidental current-season fallback.
    historical_scoring = load_scoring_rules_config(root, season=season_label)
    historical_optimizer = load_fpl_rules_config(root, season=season_label)
    optimizer_rules = OptimizerRules.load(root, season=season_label)
    convergence_configuration = {
        "counts": list(CONVERGENCE_SIMULATION_COUNTS),
        "representative_gameweeks": list(CONVERGENCE_REPRESENTATIVE_GAMEWEEKS),
        "player_ev_tolerance": CONVERGENCE_PLAYER_METRIC_TOLERANCE,
        "probability_tolerance": CONVERGENCE_PROBABILITY_TOLERANCE,
        "minimum_rank_spearman": CONVERGENCE_MINIMUM_RANK_SPEARMAN,
        "minimum_top_10_overlap": CONVERGENCE_MINIMUM_TOP_10_OVERLAP,
        "random_seed": BACKTEST_RANDOM_SEED,
        "scoring_version": historical_scoring_engine.version,
        "model_versions": ["coherent_assists_v2" if use_assist_v2 else "events_v1",
                           FixtureSimulatorV2.VERSION, "projection_builder_v1", "optimizer_v2"],
        "fplcache_repository_ref": source["fplcache_repository_ref"],
        "vaastav_repository_ref": source["vaastav_repository_ref"],
        "fixture_repository_head": fixture_manifest["repository_head_examined"],
    }
    previous_report_path = root / "data" / "processed" / "backtests" / "strict" / season / "real_model_backtest.json"
    convergence = None
    if not skip_convergence and previous_report_path.exists():
        previous = json.loads(previous_report_path.read_text(encoding="utf-8"))
        candidate = previous.get("components", {}).get("projections", {}).get("convergence_audit")
        if candidate and candidate.get("configuration") == convergence_configuration:
            convergence = candidate
            convergence["reused_deterministic_artifact"] = True
    if convergence is None and not skip_convergence:
        convergence = _convergence_audit(
            simulator, convergence_representatives, convergence_action_inputs,
            projection_builder=projection_builder, snapshot=snapshots[19],
            player_ids=player_ids, team_ids=team_ids, rules=optimizer_rules,
        )
        convergence["configuration"] = convergence_configuration
        convergence["reused_deterministic_artifact"] = False
    try:
        if skip_reference:
            raise RuntimeError("reference strategy intentionally omitted from component challenger run")
        reference_strategy = _run_reference_strategy(
            snapshots, outcomes, projections_by_gameweek, player_ids, team_ids, optimizer_rules,
        )
    except (RuntimeError, OptimizerError) as exc:
        reference_strategy = {
            "label": "PLAYER_CHIPS_ONLY_REFERENCE", "status": "BLOCKED",
            "assistant_manager_excluded": True,
            "blocking_fields": [str(exc)],
            "reason": "The sequential runner stopped at the first missing point-in-time state contract.",
        }
    leakage_report = json.loads((root / "data" / "processed" / "backtests" / "strict" / season / "coverage_boundary_report.json").read_text(encoding="utf-8"))
    leakage = int(leakage_report["leakage_violations"])
    report = {
        "report_version": 4, "mode": "STRICT", "season": season,
        "candidate_mode": (
            "ADV_CHALLENGER" if advanced_challenger
            else "TALENT_V2_ONLY" if talent_v2_only
            else "SIM_V2_RECONCILED_512"
        ),
        "status": "END_TO_END_PROJECTIONS_EVALUATED" if projection_reports else "COMPONENTS_EVALUATED_WITH_DOCUMENTED_GAPS",
        "leakage_violations": leakage,
        "coverage": {"prediction_points": len(snapshots), "gameweeks": sorted(snapshots), "by_component": coverage},
        "source_versions": {
            "fplcache": source["fplcache_repository_ref"], "vaastav": source["vaastav_repository_ref"],
            "fixture_repository_head": fixture_manifest["repository_head_examined"],
            "fixture_unique_commits": fixture_manifest["unique_commits_materialized"],
        },
        "temporal_policy": {
            "fplcache": "snapshot_timestamp < prediction_timestamp",
            "fixture_schedule": "commit_timestamp < prediction_timestamp",
            "outcomes": "target labels only; training rows require match kickoff + 4 hours <= prediction_timestamp",
            "vaastav_xP": "forbidden and unused",
        },
        "components": {
            "team_strength": {
                "status": "EVALUATED", "available_fields": ["goals", "team expected_goals", "home/away", "kickoff"],
                "unavailable_fields": ["pre-match odds", "manager regimes with complete PIT provenance"],
                "candidates": team_candidates, "oos_winner": team_winner,
                "champion_decision": "KEEP_TESTING",
            },
            "minutes": {
                "status": "EVALUATED", "available_fields": ["minutes", "starts", "status", "news", "chance_of_playing_next_round", "position", "team"],
                "unavailable_fields": ["historical confirmed lineups before kickoff", "PIT manager formations"],
                "candidates": minute_candidates, "oos_winner": minute_winner,
                "calibration": {"method": "Platt", "minimum_prior_points": 200, "strictly_prior_outcomes_only": True},
                "champion_decision": "KEEP_TESTING",
            },
            "player_talent": {
                "status": "PARTIAL_XA_ONLY", "available_fields": ["expected_assists", "goals", "minutes", "team"],
                "unavailable_fields": ["non-penalty xG", "shots", "shots in box", "shots on target", "key passes", "box touches"],
                "candidates": talent_candidates, "oos_winner_xa": talent_winner,
                "champion_decision": "KEEP_TESTING",
            },
            "event_models": {
                "status": "EVALUATED_WITH_PRIORS", "available_fields": ["goals", "assists", "saves", "yellow cards", "red cards"],
                "unavailable_fields": ["defensive contributions", "non-penalty xG", "shots on target", "penalty taker history"],
                "documented_fallbacks": ["position npxG prior", "position shots prior", "shots-on-target-per-xG goalkeeper fallback", "card priors"],
                "candidates": event_candidates,
                "goal_oos_winner": event_report.goal_champion_model_id if event_report else None,
                "assist_oos_winner": event_report.assist_champion_model_id if event_report else None,
                "champion_decision": "KEEP_TESTING",
            },
            "projections": {
                "status": "EVALUATED" if projection_reports else "UNAVAILABLE",
                "horizons": projection_metrics,
                "scoring_season": historical_scoring.season,
                "scoring_rule_version": historical_scoring.version,
                "simulation": {
                    "simulations_per_fixture": BACKTEST_SIMULATIONS_PER_FIXTURE,
                    "production_default_unchanged": 10000,
                    "base_seed": BACKTEST_RANDOM_SEED,
                    "seed_strategy": "SimulationRandom deterministic fixture-scoped derived seed",
                    "fixture_runs": simulation_fixture_count,
                    "player_fixture_summaries": player_fixture_simulations,
                    "monte_carlo_player_draws": monte_carlo_player_draws,
                    "bootstrap_samples": bootstrap_samples,
                },
                "convergence_audit": convergence,
                "reason": "Existing Event Models, FixtureSimulator, historical scoring and ProjectionBuilder were executed without hand-calculated FPL points." if projection_reports else "No complete future-fixture outcomes were available for validation.",
            },
        },
        "reference_strategy": {
            **reference_strategy, "prices_available": True,
            "optimizer_season": historical_optimizer.season,
            "optimizer_rule_version": historical_optimizer.version,
        },
        "runtime_seconds": time.perf_counter() - runtime_started,
        "champion_manifest": {
            "updated": False, "status": "KEEP_TESTING",
            "reason": "Promotion is deferred to the explicit cross-season frozen-policy decision step.",
        },
        "optimizer_validation_seasons": {
            "development": "2024/25",
            "holdout": {
                "status": "EVALUATED" if season == "2023-24" else "UNAVAILABLE",
                "season": "2023/24",
                "reason": "This report is the frozen holdout." if season == "2023-24" else "The holdout is reported separately.",
            },
        },
    }
    output = root / "data" / "processed" / "backtests" / "strict" / season / "simulator_ab" / "v2_512"
    if advanced_challenger:
        output = output / "advanced_challenger"
    elif talent_v2_only:
        output = output / "talent_v2_only"
    output.mkdir(parents=True, exist_ok=True)
    machine = output / "real_model_backtest.json"
    human = output / "real_model_backtest.md"
    machine.write_text(json.dumps(_json_safe(report), indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    human.write_text(_markdown(report), encoding="utf-8")
    return machine, human


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--season", default=SEASON)
    parser.add_argument("--simulations-per-fixture", type=int)
    parser.add_argument("--random-seed", type=int)
    parser.add_argument("--bootstrap-samples", type=int, default=200)
    parser.add_argument("--advanced-challenger", action="store_true")
    parser.add_argument("--talent-v2-only", action="store_true")
    parser.add_argument("--skip-reference", action="store_true")
    parser.add_argument("--skip-convergence", action="store_true")
    args = parser.parse_args()
    _paths = run(
        args.root.resolve(), args.season,
        simulations_per_fixture=args.simulations_per_fixture,
        random_seed=args.random_seed,
        bootstrap_samples=args.bootstrap_samples,
        advanced_challenger=args.advanced_challenger,
        talent_v2_only=args.talent_v2_only,
        skip_reference=args.skip_reference,
        skip_convergence=args.skip_convergence,
    )
    print(*(str(path) for path in _paths), sep="\n")

    print()
    print("=" * 72)
    print("SIM-V2.1 FEASIBILITY AUDIT")
    print("=" * 72)

    cls = FixtureSimulatorV21Audit

    print("team simulations:", cls.audit_team_count)
    print("groups with sum(p60) > slots:", cls.audit_infeasible_p60)
    print("groups with sum(p_app) < slots:", cls.audit_infeasible_papp)
    print(
        "players with p60 > p_start:",
        cls.audit_player_p60_gt_pstart,
    )

    print()
    print("max GK  sum p60   :", round(cls.audit_max_gk_p60, 6))
    print("max GK  sum pstart:", round(cls.audit_max_gk_pstart, 6))
    print("max GK  sum papp  :", round(cls.audit_max_gk_papp, 6))

    print()
    print("max OUT sum p60   :", round(cls.audit_max_out_p60, 6))
    print("max OUT sum pstart:", round(cls.audit_max_out_pstart, 6))
    print("max OUT sum papp  :", round(cls.audit_max_out_papp, 6))

