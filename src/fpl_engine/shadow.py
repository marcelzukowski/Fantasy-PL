"""Auditable, non-mutating current-season recommendation shadow runs.

This module deliberately consumes ``PlayerProjection`` records created by the
existing inference/simulation/projection pipeline.  It does not estimate points
itself, infer FPL account state, or call any write endpoint.
"""

from __future__ import annotations

from dataclasses import asdict, replace
from contextlib import nullcontext
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Mapping

from fpl_engine.models.projections import GameweekPlayerProjection, PlayerProjection
from fpl_engine.planning import DecisionInput
from fpl_engine.optimizer import (
    ChipState, Optimizer, OptimizerError, OptimizerRules, OptimizerV2,
    OptimizerV2Config, Recommendation, SquadPlayer, SquadState, validate_squad,
)
from fpl_engine.validation.leakage import assert_information_known, assert_snapshot_before


class ShadowRunError(ValueError):
    """The local shadow input cannot support an auditable recommendation."""


MIN_SIMULATIONS_PER_FIXTURE = 1
MAX_SIMULATIONS_PER_FIXTURE = 50_000


def _utc(value: object, name: str) -> datetime:
    if not isinstance(value, str):
        raise ShadowRunError(f"{name} must be an ISO-8601 timestamp string")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ShadowRunError(f"{name} is not an ISO-8601 timestamp") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise ShadowRunError(f"{name} must be timezone-aware")
    return result.astimezone(timezone.utc)


def _require(mapping: Mapping[str, Any], key: str) -> Any:
    if key not in mapping:
        raise ShadowRunError(f"Missing required squad-state field: {key}")
    return mapping[key]


def _player(value: Mapping[str, Any]) -> SquadPlayer:
    required = ("player_id", "position", "club_id", "purchase_price", "current_price")
    missing = [key for key in required if key not in value]
    if missing:
        raise ShadowRunError(f"Player is missing explicit state: {', '.join(missing)}")
    try:
        return SquadPlayer(
            str(value["player_id"]), str(value["position"]), str(value["club_id"]),
            value["purchase_price"], value["current_price"], value.get("selling_price"),
        )
    except (TypeError, ValueError) as exc:
        raise ShadowRunError(f"Invalid player state for {value.get('player_id')!r}") from exc


def _chips(value: Mapping[str, Any]) -> ChipState:
    required = tuple(ChipState.__dataclass_fields__)
    missing = [key for key in required if key not in value]
    if missing:
        raise ShadowRunError(f"chip_state must explicitly contain: {', '.join(missing)}")
    try:
        return ChipState(**{key: value[key] for key in required})
    except TypeError as exc:
        raise ShadowRunError("Invalid chip_state") from exc


def _gameweek(value: Mapping[str, Any]) -> GameweekPlayerProjection:
    try:
        return GameweekPlayerProjection(
            season=str(value["season"]), rule_version=int(value["rule_version"]),
            player_id=str(value["player_id"]), target_gameweek=int(value["target_gameweek"]),
            prediction_timestamp=_utc(value["prediction_timestamp"], "projection.prediction_timestamp"),
            fixture_ids=tuple(value["fixture_ids"]), fixture_count=int(value["fixture_count"]),
            expected_points=float(value["expected_points"]), median_points=float(value["median_points"]),
            points_std=float(value["points_std"]),
            point_quantiles={float(key): float(item) for key, item in value["point_quantiles"].items()},
            p_blank=float(value["p_blank"]), p_return=float(value["p_return"]),
            p_5_plus=float(value["p_5_plus"]), p_8_plus=float(value["p_8_plus"]),
            p_10_plus=float(value["p_10_plus"]), p_15_plus=float(value["p_15_plus"]),
            expected_minutes=float(value["expected_minutes"]),
            points_distribution={int(key): float(item) for key, item in value["points_distribution"].items()},
            event_completeness=float(value["event_completeness"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ShadowRunError("Invalid GameweekPlayerProjection payload") from exc


def _projection(value: Mapping[str, Any]) -> PlayerProjection:
    try:
        return PlayerProjection(
            player_id=str(value["player_id"]), season=str(value["season"]),
            rule_version=int(value["rule_version"]),
            prediction_timestamp=_utc(value["prediction_timestamp"], "projection.prediction_timestamp"),
            current_gameweek=int(value["current_gameweek"]),
            gameweeks=tuple(_gameweek(row) for row in value["gameweeks"]),
            ev_next_1=float(value["ev_next_1"]), ev_next_3=float(value["ev_next_3"]),
            ev_next_6=float(value["ev_next_6"]),
            weighted_ev_next_1=float(value["weighted_ev_next_1"]),
            weighted_ev_next_3=float(value["weighted_ev_next_3"]),
            weighted_ev_next_6=float(value["weighted_ev_next_6"]),
            expected_minutes_next_1=float(value["expected_minutes_next_1"]),
            expected_minutes_next_3=float(value["expected_minutes_next_3"]),
            expected_minutes_next_6=float(value["expected_minutes_next_6"]),
            projection_uncertainty=float(value["projection_uncertainty"]),
            projection_confidence=float(value["projection_confidence"]),
            event_completeness=float(value["event_completeness"]),
            model_versions=tuple(value["model_versions"]), dataset_versions=tuple(value["dataset_versions"]),
            feature_versions=tuple(value["feature_versions"]), simulator_versions=tuple(value["simulator_versions"]),
            simulation_seeds=tuple(int(item) for item in value["simulation_seeds"]),
            scoring_versions=tuple(int(item) for item in value["scoring_versions"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ShadowRunError("Invalid PlayerProjection payload") from exc


def _json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ShadowRunError(f"Cannot read {label} JSON: {path}") from exc
    if not isinstance(raw, dict):
        raise ShadowRunError(f"{label} JSON root must be an object")
    return raw


def _validated_simulation_count(pipeline: Mapping[str, Any]) -> int:
    """Return the recorded count for a supported canonical projection bundle."""
    count = pipeline.get("simulations_per_fixture")
    if type(count) is not int or not (
        MIN_SIMULATIONS_PER_FIXTURE
        <= count
        <= MAX_SIMULATIONS_PER_FIXTURE
    ):
        raise ShadowRunError(
            "pipeline.simulations_per_fixture must be an integer "
            "between 1 and 50000"
        )
    return count


def load_squad_state(
    path: Path, *, project_root: Path, prediction_bundle_path: Path | None = None,
    allow_diagnostic: bool = False,
) -> tuple[SquadState, tuple[SquadPlayer, ...], dict[str, PlayerProjection], dict, list[str], OptimizerRules, object]:
    """Load explicit account state plus existing production projections.

    ``projections`` must be serialized ``PlayerProjection`` objects from the
    existing ProjectionBuilder.  The command refuses to estimate them from
    partial data, which prevents a shadow result from concealing a missing model
    input as a zero.
    """
    raw = _json_object(path, "squad-state")
    if prediction_bundle_path is not None:
        bundle = _json_object(prediction_bundle_path, "prediction bundle")
        for key in (
            "prediction_timestamp", "season", "current_gameweek", "candidate_pool",
            "projections", "pipeline", "data_freshness",
        ):
            if key not in bundle:
                raise ShadowRunError(f"Prediction bundle is missing required field: {key}")
        for key in ("prediction_timestamp", "season", "current_gameweek"):
            if key in raw and raw[key] != bundle[key]:
                raise ShadowRunError(f"squad-state {key} does not match prediction bundle")
            raw[key] = bundle[key]
        # Generated projection state is authoritative; stale hand-built payloads
        # in a squad file cannot override the current materialized run.
        for key in ("candidate_pool", "projections", "pipeline", "data_freshness"):
            raw[key] = bundle[key]
    players_raw = _require(raw, "players")
    if not isinstance(players_raw, list):
        raise ShadowRunError("players must be a JSON array")
    players = tuple(_player(item) for item in players_raw)
    season = _require(raw, "season")
    if not isinstance(season, str):
        raise ShadowRunError("season must be a string such as '2026/27'")
    # Current active rules are deliberately stored in the default configuration;
    # historical seasons are stored in explicit versioned files.  Loading the
    # active file is safe only when its declared season is an exact match.
    rules = OptimizerRules.load(project_root)
    if rules.season != season:
        try:
            rules = OptimizerRules.load(project_root, season=season)
        except Exception as exc:
            raise ShadowRunError(f"No explicit optimizer rules are available for season {season!r}") from exc
    if rules.season != season:
        raise ShadowRunError("optimizer rules season does not match squad state")
    timestamp = _utc(_require(raw, "prediction_timestamp"), "prediction_timestamp")
    chips = _chips(_require(raw, "chip_state"))
    try:
        state = SquadState(
            players=players, bank=_require(raw, "bank"), free_transfers=_require(raw, "free_transfers"),
            chips=chips, current_gameweek=_require(raw, "current_gameweek"), season=season,
            rule_version=rules.version, prediction_timestamp=timestamp,
        )
        validate_squad(state, rules)
    except (OptimizerError, TypeError, ValueError) as exc:
        raise ShadowRunError("Invalid explicit SquadState") from exc
    pool_raw = _require(raw, "candidate_pool")
    if not isinstance(pool_raw, list):
        raise ShadowRunError("candidate_pool must be a JSON array")
    pool = tuple(_player(item) for item in pool_raw)
    projections_raw = _require(raw, "projections")
    if not isinstance(projections_raw, list):
        raise ShadowRunError("projections must be a JSON array of PlayerProjection records")
    parsed_projections = tuple(_projection(item) for item in projections_raw)
    projections = {item.player_id: item for item in parsed_projections}
    if len(projections) != len(projections_raw):
        raise ShadowRunError("projections contain duplicate player IDs")
    required_ids = {row.player_id for row in state.players} | {row.player_id for row in pool}
    missing = sorted(required_ids - set(projections))
    if missing:
        raise ShadowRunError(f"Missing current production projections for: {missing}")
    for projection in projections.values():
        if projection.season != season or projection.rule_version != rules.version:
            raise ShadowRunError("projection season/rule version does not match squad state")
        if projection.prediction_timestamp != timestamp:
            raise ShadowRunError("projection timestamp does not match prediction_timestamp")
        if projection.current_gameweek != state.current_gameweek:
            raise ShadowRunError("projection current_gameweek does not match squad state")
    pipeline = _require(raw, "pipeline")
    if not isinstance(pipeline, dict):
        raise ShadowRunError("pipeline must be an object")
    _validated_simulation_count(pipeline)
    warnings = _validate_freshness(raw.get("data_freshness"), timestamp)
    return state, pool, projections, pipeline, warnings, rules, raw.get("data_freshness")


def _validate_freshness(value: object, prediction_timestamp: datetime) -> list[str]:
    if value is None:
        return ["No data_freshness records were supplied; source freshness cannot be audited."]
    if not isinstance(value, list) or not value:
        return ["data_freshness is empty; source freshness cannot be audited."]
    warnings: list[str] = []
    for record in value:
        if not isinstance(record, dict) or not record.get("source"):
            warnings.append("A data_freshness record is missing source identity.")
            continue
        source = str(record["source"])
        try:
            if record.get("snapshot_timestamp") is not None:
                assert_snapshot_before(
                    snapshot_timestamp=_utc(record["snapshot_timestamp"], f"{source}.snapshot_timestamp"),
                    prediction_timestamp=prediction_timestamp, source=source,
                )
            elif record.get("known_at") is not None:
                assert_information_known(
                    known_at=_utc(record["known_at"], f"{source}.known_at"),
                    prediction_timestamp=prediction_timestamp, entity=source, source=source,
                )
            else:
                warnings.append(f"{source} has no known_at or snapshot_timestamp provenance.")
        except Exception as exc:
            raise ShadowRunError(f"Unsafe data freshness record for {source}") from exc
        if not record.get("raw_snapshot_id"):
            warnings.append(f"{source} has no RawStore receipt identifier.")
    return warnings


def _recommendations(
    state: SquadState, pool: tuple[SquadPlayer, ...], projections: Mapping[str, PlayerProjection],
    rules: OptimizerRules, *, decision_input: DecisionInput | None = None,
) -> tuple[dict[str, Recommendation], dict[str, object]]:
    lineup_provider = None
    if decision_input is not None:
        lineup_provider = lambda working, **options: decision_input.lineup_for(working, **options)
    production = Optimizer(rules, lineup_provider=lineup_provider)
    greedy_rows = {player_id: replace(row, weighted_ev_next_6=row.ev_next_1) for player_id, row in projections.items()}
    try:
        v2_config = OptimizerV2Config.from_rules(rules)
    except KeyError:
        # The active rules document predates the V2-specific section.  Its
        # frozen V2 defaults are still a challenger, never the shadow default.
        v2_config = OptimizerV2Config()
    greedy = production.recommend(state, greedy_rows, pool, max_transfers=1)
    v1 = production.recommend(state, projections, pool, max_transfers=2)
    v1_diagnostics = production.last_search_diagnostics.snapshot() if production.last_search_diagnostics else None
    v2_engine = OptimizerV2(rules, v2_config, lineup_provider=lineup_provider)
    v2 = v2_engine.recommend(state, projections, pool, max_transfers=2)
    return ({"greedy_1gw": greedy, "optimizer_v1": v1, "optimizer_v2": v2}, {
        "optimizer_v1": v1_diagnostics,
        "optimizer_v2": dict(v2_engine.last_search_diagnostics),
    })


def _transfer_impacts(
    transfers_out: tuple[str, ...],
    transfers_in: tuple[str, ...],
    projections: Mapping[str, PlayerProjection],
) -> dict[str, float]:
    """Expose direct existing-projection deltas for an already feasible plan."""
    def delta(attribute: str) -> float:
        return float(sum(getattr(projections[player_id], attribute) for player_id in transfers_in) - sum(
            getattr(projections[player_id], attribute) for player_id in transfers_out
        ))
    return {"impact_1gw": delta("ev_next_1"), "impact_3gw": delta("ev_next_3"), "impact_6gw": delta("ev_next_6")}


def _recommendation_payload(row: Recommendation, projections: Mapping[str, PlayerProjection]) -> dict:
    alternatives = []
    for item in row.alternatives:
        payload = asdict(item)
        payload.update(_transfer_impacts(item.transfers_out, item.transfers_in, projections))
        alternatives.append(payload)
    return {
        "action": row.action, "transfers_out": list(row.transfers_out), "transfers_in": list(row.transfers_in),
        "roll_free_transfer": row.roll_ft, "hit_cost": row.hit_cost, "gross_projected_gain": row.gross_gain,
        "net_projected_gain": row.net_gain, "resulting_bank": row.resulting_bank,
        "free_transfers_before": row.free_transfers_before,
        "free_transfers_after": row.free_transfers_after,
        "raw_ev_1gw": row.raw_ev_1gw, "raw_ev_3gw": row.raw_ev_3gw,
        "raw_ev_6gw": row.raw_ev_6gw, "weighted_utility_6gw": row.weighted_utility_6gw,
        "starting_xi": list(row.starting_xi), "bench_order": list(row.bench_order),
        "captain": row.captain_id, "vice_captain": row.vice_captain_id,
        "confidence": row.action_stability, "decision_margin": row.decision_margin,
        "transfer_impacts": _transfer_impacts(row.transfers_out, row.transfers_in, projections),
        "alternatives": alternatives, "optimizer_version": row.optimizer_version,
    }


def run_shadow(
    squad_state_path: Path, *, project_root: Path, output_dir: Path | None = None,
    clock: Callable[[], datetime] | None = None,
    prediction_bundle_path: Path | None = None, allow_diagnostic: bool = False,
    decision_input: DecisionInput | None = None,
) -> tuple[Path, Path]:
    # Desktop callers may pass the single validated run input.  Standalone CLI
    # usage remains byte-for-byte compatible and loads the legacy request path.
    if decision_input is None:
        state, pool, projections, pipeline, warnings, rules, freshness = load_squad_state(
            squad_state_path, project_root=project_root,
            prediction_bundle_path=prediction_bundle_path, allow_diagnostic=allow_diagnostic,
        )
    else:
        state, pool, projections, pipeline, rules = (decision_input.state, decision_input.player_pool,
            decision_input.projections, dict(decision_input.pipeline), decision_input.rules)
        warnings, freshness = list(decision_input.warnings), decision_input.freshness
    with (decision_input.policy_timer("greedy_v1_v2") if decision_input is not None else nullcontext()):
        recommendations, optimizer_diagnostics = _recommendations(
            state, pool, projections, rules, decision_input=decision_input,
        )
    try:
        OptimizerV2Config.from_rules(rules)
    except KeyError:
        warnings.append("Active rules omit decision_v2; the frozen OptimizerV2 defaults are comparison-only.")
    now = (clock or (lambda: datetime.now(timezone.utc)))()
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ShadowRunError("clock must return an aware datetime")
    generated_at = now.astimezone(timezone.utc)
    destination = output_dir or project_root / "data" / "processed" / "shadow" / state.season.replace("/", "-")
    destination.mkdir(parents=True, exist_ok=True)
    run_id = generated_at.strftime("%Y%m%dT%H%M%SZ")
    machine = destination / f"shadow-{run_id}.json"
    human = destination / f"shadow-{run_id}.md"
    if machine.exists() or human.exists():
        raise ShadowRunError(f"Shadow report already exists for run timestamp {run_id}")
    owned = {
        player_id: {
            "ev_1gw": projections[player_id].ev_next_1, "ev_3gw": projections[player_id].ev_next_3,
            "ev_6gw": projections[player_id].ev_next_6,
            "expected_minutes_1gw": projections[player_id].expected_minutes_next_1,
            "confidence": projections[player_id].projection_confidence,
            "uncertainty": projections[player_id].projection_uncertainty,
        } for player_id in (player.player_id for player in state.players)
    }
    report = {
        "report_version": 1,
        "mode": "EXPERIMENTAL / SHADOW MODE",
        "promotion_status": "NOT PRODUCTION PROMOTED",
        "simulation_mode": pipeline.get("simulation_mode", "PRODUCTION"),
        "external_mutations": [],
        "generated_at": generated_at.isoformat(), "prediction_timestamp": state.prediction_timestamp.isoformat(),
        "season": state.season, "current_gameweek": state.current_gameweek,
        "model_rule_versions": {
            "optimizer_rule_version": state.rule_version,
            "model_versions": sorted({version for item in projections.values() for version in item.model_versions}),
            "simulator_versions": sorted({version for item in projections.values() for version in item.simulator_versions}),
            "scoring_versions": sorted({version for item in projections.values() for version in item.scoring_versions}),
            "pipeline": pipeline,
        },
        "data_freshness": {"records": freshness, "warnings": warnings},
        "current_squad": [asdict(item) for item in state.players], "bank": state.bank,
        "free_transfers": state.free_transfers, "chip_state": asdict(state.chips),
        "owned_player_projections": owned,
        "default_policy": "greedy_1gw",
        "recommendations": {name: _recommendation_payload(item, projections) for name, item in recommendations.items()},
        # Diagnostics are machine-only provenance for a run-scoped shared input.
        "decision_input_diagnostics": decision_input.diagnostics.snapshot() if decision_input is not None else None,
        "legacy_optimizer_diagnostics": optimizer_diagnostics,
    }
    machine.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    greedy = report["recommendations"]["greedy_1gw"]
    lines = [
        "# EXPERIMENTAL / SHADOW MODE", "", "NOT PRODUCTION PROMOTED.", "",
        f"Prediction timestamp: {report['prediction_timestamp']}",
        f"Season / GW: {state.season} / {state.current_gameweek}",
        f"Greedy 1GW: {greedy['action']} | OUT {greedy['transfers_out']} | IN {greedy['transfers_in']} | net gain {greedy['net_projected_gain']:.2f}",
        f"XI: {greedy['starting_xi']}", f"Bench: {greedy['bench_order']}",
        f"Captain / vice: {greedy['captain']} / {greedy['vice_captain']}", "",
        "## Challengers", "",
    ]
    for name in ("optimizer_v1", "optimizer_v2"):
        row = report["recommendations"][name]
        lines.append(f"- {name}: {row['action']}; OUT {row['transfers_out']}; IN {row['transfers_in']}; net gain {row['net_projected_gain']:.2f}")
    if warnings:
        lines += ["", "## Data warnings", ""] + [f"- {warning}" for warning in warnings]
    human.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return machine, human
