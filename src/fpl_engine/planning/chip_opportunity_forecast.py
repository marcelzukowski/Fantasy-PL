"""Read-only, run-scoped chip opportunity advisory forecast.

This module intentionally does not influence any transfer or chip decision.
It only records what the already materialized projection context suggests.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
from pathlib import Path
from time import perf_counter
from typing import TYPE_CHECKING, Any, Mapping
import json

import importlib

EXACT_HORIZON_GAMEWEEKS = 6  # Canonical chip-strategy default; verified when the builder runs.
if TYPE_CHECKING:
    from .decision_input import DecisionInput

CHIP_OPPORTUNITY_FORECAST_SCHEMA_V1 = "chip_opportunity_forecast_v1"


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")

CHIP_OPPORTUNITY_FORECAST_VERSION = "chip_opportunity_forecast_v1"


class ChipOpportunityForecastError(ValueError):
    pass


class ChipForecastStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    PARTIAL = "PARTIAL"
    UNAVAILABLE = "UNAVAILABLE"
    STALE = "STALE"


@dataclass(frozen=True)
class ChipOpportunityForecastConfig:
    horizon_gameweeks: int = EXACT_HORIZON_GAMEWEEKS
    free_hit_screen_minimum: float = 1.0
    version: str = CHIP_OPPORTUNITY_FORECAST_VERSION

    def __post_init__(self) -> None:
        if self.horizon_gameweeks < 1:
            raise ChipOpportunityForecastError("forecast horizon must be positive")
        if self.free_hit_screen_minimum < 0:
            raise ChipOpportunityForecastError("free-hit screen minimum must be non-negative")


@dataclass(frozen=True)
class ChipOpportunity:
    gameweek: int
    chip_type: str
    chip_available: bool
    estimated_incremental_ev: float | None
    baseline_value: float | None
    chip_value: float | None
    confidence: str
    confidence_score: float
    coverage: float
    method: str
    source_context: str
    assumptions: tuple[str, ...]
    candidate_captain_id: str | None = None
    opportunity_level: str | None = None
    screening_score: float | None = None
    realised_incremental_ev: float | None = None
    timing_regret: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "gameweek": self.gameweek, "chip_type": self.chip_type,
            "chip_available": self.chip_available,
            "estimated_incremental_ev": self.estimated_incremental_ev,
            "baseline_value": self.baseline_value, "chip_value": self.chip_value,
            "confidence": self.confidence, "confidence_score": self.confidence_score,
            "coverage": self.coverage, "method": self.method,
            "source_context": self.source_context, "assumptions": list(self.assumptions),
            "candidate_captain_id": self.candidate_captain_id,
            "opportunity_level": self.opportunity_level, "screening_score": self.screening_score,
            "realised_incremental_ev": self.realised_incremental_ev,
            "timing_regret": self.timing_regret,
        }


@dataclass(frozen=True)
class ChipOpportunityForecast:
    schema_version: str
    context_id: str
    generated_at: str
    forecast_start_gw: int
    forecast_end_gw: int
    config_version: str
    opportunities: tuple[ChipOpportunity, ...]
    source: Mapping[str, Any]
    coverage: Mapping[str, Any]
    confidence: str
    warnings: tuple[str, ...]
    status: ChipForecastStatus
    metrics: Mapping[str, Any]

    def __post_init__(self) -> None:
        if self.schema_version != CHIP_OPPORTUNITY_FORECAST_SCHEMA_V1:
            raise ChipOpportunityForecastError("unsupported chip opportunity forecast schema")
        if not self.context_id or self.forecast_start_gw < 1 or self.forecast_end_gw < self.forecast_start_gw:
            raise ChipOpportunityForecastError("forecast identity is invalid")
        parsed = datetime.fromisoformat(self.generated_at.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ChipOpportunityForecastError("forecast generated_at must be aware")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version, "context_id": self.context_id,
            "generated_at": self.generated_at, "forecast_start_gw": self.forecast_start_gw,
            "forecast_end_gw": self.forecast_end_gw, "config_version": self.config_version,
            "opportunities": [row.to_dict() for row in self.opportunities],
            "source": dict(self.source), "coverage": dict(self.coverage),
            "confidence": self.confidence, "warnings": list(self.warnings),
            "status": self.status.value, "metrics": dict(self.metrics),
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "ChipOpportunityForecast":
        if not isinstance(raw, Mapping):
            raise ChipOpportunityForecastError("forecast must be an object")
        try:
            rows = []
            for item in raw.get("opportunities", []):
                if not isinstance(item, Mapping):
                    raise TypeError
                rows.append(ChipOpportunity(
                    int(item["gameweek"]), str(item["chip_type"]), bool(item["chip_available"]),
                    _number(item.get("estimated_incremental_ev")), _number(item.get("baseline_value")),
                    _number(item.get("chip_value")), str(item["confidence"]), float(item["confidence_score"]),
                    float(item["coverage"]), str(item["method"]), str(item["source_context"]),
                    tuple(str(value) for value in item.get("assumptions", [])),
                    str(item["candidate_captain_id"]) if item.get("candidate_captain_id") is not None else None,
                    str(item["opportunity_level"]) if item.get("opportunity_level") is not None else None,
                    _number(item.get("screening_score")),
                    _number(item.get("realised_incremental_ev")),
                    _number(item.get("timing_regret")),
                ))
            return cls(
                str(raw["schema_version"]), str(raw["context_id"]), str(raw["generated_at"]),
                int(raw["forecast_start_gw"]), int(raw["forecast_end_gw"]), str(raw["config_version"]),
                tuple(rows), dict(raw.get("source", {})), dict(raw.get("coverage", {})),
                str(raw["confidence"]), tuple(str(value) for value in raw.get("warnings", [])),
                ChipForecastStatus(str(raw["status"])), dict(raw.get("metrics", {})),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ChipOpportunityForecastError("forecast payload is invalid") from exc


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


class ChipOpportunityForecastCache:
    """Explicit context-scoped cache; never shared implicitly with another run."""

    def __init__(self) -> None:
        self._values: dict[tuple[object, ...], ChipOpportunityForecast] = {}
        self.hits = 0

    def get(self, key: tuple[object, ...]) -> ChipOpportunityForecast | None:
        value = self._values.get(key)
        if value is not None:
            self.hits += 1
        return value

    def put(self, key: tuple[object, ...], value: ChipOpportunityForecast) -> None:
        self._values[key] = value


def _projection_for_gameweek(row: object, gameweek: int) -> object | None:
    return next((item for item in getattr(row, "gameweeks", ()) if getattr(item, "target_gameweek", None) == gameweek), None)


def _target_projections(decision_input: "DecisionInput", gameweek: int) -> tuple[dict[str, object], float]:
    result: dict[str, object] = {}
    owned = {player.player_id for player in decision_input.state.players}
    complete = 0
    for player_id, projection in decision_input.projections.items():
        target = _projection_for_gameweek(projection, gameweek)
        if target is None:
            continue
        result[player_id] = replace(
            projection, gameweeks=(target,), ev_next_1=float(target.expected_points),
            ev_next_3=float(target.expected_points), ev_next_6=float(target.expected_points),
            weighted_ev_next_1=float(target.expected_points), weighted_ev_next_3=float(target.expected_points),
            weighted_ev_next_6=float(target.expected_points),
            expected_minutes_next_1=float(target.expected_minutes),
            expected_minutes_next_3=float(target.expected_minutes),
            expected_minutes_next_6=float(target.expected_minutes),
        )
        if player_id in owned:
            complete += 1
    return result, complete / max(1, len(owned))


def _confidence(coverage: float, projections: Mapping[str, object], owned_ids: tuple[str, ...], distance: int) -> tuple[str, float]:
    values = [float(getattr(projections.get(player_id), "projection_confidence", 0.0)) for player_id in owned_ids if player_id in projections]
    mean_confidence = sum(values) / len(values) if values else 0.0
    score = max(0.0, min(1.0, 0.65 * coverage + 0.25 * mean_confidence + 0.10 * max(0.0, 1.0 - distance / 8)))
    return ("HIGH" if score >= .80 else "MEDIUM" if score >= .55 else "LOW"), score


def _state_for_gameweek(decision_input: "DecisionInput", gameweek: int):
    return replace(decision_input.state, current_gameweek=gameweek)


def _fh_screen(target: Mapping[str, object], state, baseline: float) -> float:
    owned = {player.player_id for player in state.players}
    owned_floor = min((float(target[player_id].gameweeks[0].expected_points) for player_id in owned if player_id in target), default=0.0)
    pool_ceiling = max((float(row.gameweeks[0].expected_points) for player_id, row in target.items() if player_id not in owned), default=owned_floor)
    return max(0.0, pool_ceiling - owned_floor)


def _lineup_value(lineup, projections: Mapping[str, object]) -> float:
    points = {player_id: float(row.gameweeks[0].expected_points) for player_id, row in projections.items()}
    return sum(points[player_id] for player_id in lineup.starting_xi) + points[lineup.captain_id]


def _free_hit_exact(decision_input: "DecisionInput", state, target: Mapping[str, object], baseline: float) -> tuple[float, str] | None:
    from fpl_engine.optimizer import Optimizer, OptimizerError
    pool = tuple(player for player in decision_input.player_pool if player.player_id in target)
    try:
        recommendation = Optimizer(decision_input.rules).recommend(state, target, pool, chip="free_hit")
    except OptimizerError:
        return None
    value = sum(float(target[player_id].gameweeks[0].expected_points) for player_id in recommendation.starting_xi)
    value += float(target[recommendation.captain_id].gameweeks[0].expected_points)
    return value, recommendation.captain_id


def _wildcard_level(state, target: Mapping[str, object], pool: tuple[object, ...]) -> tuple[str, float]:
    by_position: dict[str, list[float]] = {}
    for player in pool:
        row = target.get(player.player_id)
        if row is not None:
            by_position.setdefault(player.position, []).append(float(row.gameweeks[0].expected_points))
    weak = 0
    for player in state.players:
        values = sorted(by_position.get(player.position, []))
        current = target.get(player.player_id)
        if current is None or not values:
            continue
        median = values[len(values) // 2]
        if float(current.gameweeks[0].expected_points) < median:
            weak += 1
    pressure = weak + max(0, weak - state.free_transfers)
    return ("HIGH" if pressure >= 6 else "MEDIUM" if pressure >= 3 else "LOW"), float(pressure)


def build_chip_opportunity_forecast(
    decision_input: "DecisionInput",
    chip_state=None,
    *,
    config: ChipOpportunityForecastConfig = ChipOpportunityForecastConfig(),
    cache: ChipOpportunityForecastCache | None = None,
    generated_at: datetime | None = None,
) -> ChipOpportunityForecast:
    """Build an advisory-only forecast from one frozen DecisionInput.

    It performs no I/O, provider request, account mutation, or V3 mutation.
    """
    from fpl_engine.optimizer import chip_available, optimize_lineup
    if chip_state is not None and chip_state != decision_input.state.chips:
        raise ChipOpportunityForecastError("chip state does not match the frozen DecisionInput")
    chip_strategy = importlib.import_module("fpl_engine.decision.chip_strategy")
    horizons = chip_strategy.chip_strategy_horizons(decision_input.state.current_gameweek, exact_horizon_gameweeks=config.horizon_gameweeks)
    gameweeks = horizons.exact_gameweeks
    signature = tuple(getattr(decision_input.state.chips, name) for name in decision_input.state.chips.__dataclass_fields__)
    key = (decision_input.context_id, gameweeks, signature, config.version, config.free_hit_screen_minimum)
    if cache is not None and (cached := cache.get(key)) is not None:
        return replace(cached, metrics={**cached.metrics, "cache_hits": cache.hits})
    started = perf_counter(); opportunities: list[ChipOpportunity] = []; warnings: list[str] = []
    chip_runtime_seconds = {"triple_captain": 0.0, "bench_boost": 0.0, "free_hit": 0.0, "wildcard": 0.0}
    owned_ids = tuple(player.player_id for player in decision_input.state.players)
    fh_candidates: list[tuple[float, int, object, dict[str, object], float, float, str, float]] = []
    available_coverage = 0
    for offset, gameweek in enumerate(gameweeks):
        state = _state_for_gameweek(decision_input, gameweek)
        target, coverage = _target_projections(decision_input, gameweek)
        confidence, confidence_score = _confidence(coverage, target, owned_ids, offset)
        if coverage == 1.0:
            available_coverage += 1
        source = f"{decision_input.context_id}:GW{gameweek}"
        baseline = None
        if coverage == 1.0:
            baseline = optimize_lineup(state, target, decision_input.rules)
        for chip in ("triple_captain", "bench_boost"):
            chip_started = perf_counter()
            available = chip_available(chip, state, decision_input.rules)
            if not available:
                opportunities.append(ChipOpportunity(gameweek, chip, False, None, None, None, "LOW", confidence_score, coverage, "CHIP_UNAVAILABLE", source, ("Canonical chip-state/rule eligibility rejected this chip.",)))
            elif baseline is None:
                opportunities.append(ChipOpportunity(gameweek, chip, True, None, None, None, confidence, confidence_score, coverage, "UNAVAILABLE_INCOMPLETE_PROJECTIONS", source, ("Missing target-GW owned-player projections; no zero imputation.",)))
            else:
                enabled = optimize_lineup(state, target, decision_input.rules, triple_captain=chip == "triple_captain", bench_boost=chip == "bench_boost")
                method = "EXACT_FROM_EXISTING_CAPTAINCY_MODEL" if chip == "triple_captain" else "STATIC_SQUAD_APPROXIMATION"
                assumptions = (() if chip == "triple_captain" else ("Current squad is held static; future transfers are not forecast.",))
                opportunities.append(ChipOpportunity(gameweek, chip, True, enabled.expected_points - baseline.expected_points, baseline.expected_points, enabled.expected_points, confidence, confidence_score, coverage, method, source, assumptions, enabled.captain_id if chip == "triple_captain" else None))
            chip_runtime_seconds[chip] += perf_counter() - chip_started
        fh_started = perf_counter()
        available_fh = chip_available("free_hit", state, decision_input.rules)
        if not available_fh:
            opportunities.append(ChipOpportunity(gameweek, "free_hit", False, None, None, None, "LOW", confidence_score, coverage, "CHIP_UNAVAILABLE", source, ("Canonical chip-state/rule eligibility rejected this chip.",)))
        elif baseline is None:
            opportunities.append(ChipOpportunity(gameweek, "free_hit", True, None, None, None, confidence, confidence_score, coverage, "UNAVAILABLE_INCOMPLETE_PROJECTIONS", source, ("Missing target-GW owned-player projections; no zero imputation.",)))
        else:
            screen = _fh_screen(target, state, baseline.expected_points)
            fh_candidates.append((screen, gameweek, state, target, baseline.expected_points, coverage, confidence, confidence_score))
            opportunities.append(ChipOpportunity(gameweek, "free_hit", True, None, baseline.expected_points, None, confidence, confidence_score, coverage, "SCREENED_OUT_NO_EXACT_EVALUATION", source, ("Only the strongest cheap Free Hit screen is eligible for one exact static-squad evaluation.",), screening_score=screen))
        chip_runtime_seconds["free_hit"] += perf_counter() - fh_started
        wc_started = perf_counter()
        available_wc = chip_available("wildcard", state, decision_input.rules)
        if not available_wc:
            opportunities.append(ChipOpportunity(gameweek, "wildcard", False, None, None, None, "LOW", confidence_score, coverage, "CHIP_UNAVAILABLE", source, ("Canonical chip-state/rule eligibility rejected this chip.",)))
        elif coverage < 1.0:
            opportunities.append(ChipOpportunity(gameweek, "wildcard", True, None, None, None, confidence, confidence_score, coverage, "UNAVAILABLE_INCOMPLETE_PROJECTIONS", source, ("No precise Wildcard EV is inferred from incomplete projections.",)))
        else:
            level, pressure = _wildcard_level(state, target, tuple(decision_input.player_pool))
            opportunities.append(ChipOpportunity(gameweek, "wildcard", True, None, None, None, confidence, confidence_score, coverage, "DIAGNOSTIC_ONLY", source, ("Static-squad pressure only; no Wildcard optimizer is run.",), opportunity_level=level, screening_score=pressure))
        chip_runtime_seconds["wildcard"] += perf_counter() - wc_started
    exact_evaluations = 0
    if fh_candidates:
        screen, gameweek, state, target, baseline, coverage, confidence, confidence_score = max(fh_candidates, key=lambda row: (row[0], -row[1]))
        if screen >= config.free_hit_screen_minimum:
            exact_started = perf_counter()
            exact = _free_hit_exact(decision_input, state, target, baseline)
            chip_runtime_seconds["free_hit"] += perf_counter() - exact_started
            if exact is not None:
                exact_evaluations = 1
                chip_value, captain = exact
                opportunities = [
                    replace(row, estimated_incremental_ev=chip_value - baseline, chip_value=chip_value, method="SCREENED_EXACT_STATIC_SQUAD", assumptions=("Strongest cheap screen only; exact existing Free Hit optimizer evaluated static target-GW projections.",), candidate_captain_id=captain)
                    if row.chip_type == "free_hit" and row.gameweek == gameweek else row
                    for row in opportunities
                ]
    if not available_coverage:
        status = ChipForecastStatus.UNAVAILABLE
        warnings.append("No forecast gameweek has complete owned-player projection coverage.")
    elif available_coverage < len(gameweeks):
        status = ChipForecastStatus.PARTIAL
        warnings.append("Only complete target-GW coverage was evaluated; missing values were not imputed.")
    else:
        status = ChipForecastStatus.AVAILABLE
    overall_confidence = "HIGH" if status is ChipForecastStatus.AVAILABLE else "MEDIUM" if status is ChipForecastStatus.PARTIAL else "LOW"
    timestamp = (generated_at or decision_input.state.prediction_timestamp or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()
    forecast = ChipOpportunityForecast(
        CHIP_OPPORTUNITY_FORECAST_SCHEMA_V1, decision_input.context_id, timestamp, gameweeks[0], gameweeks[-1], config.version, tuple(sorted(opportunities, key=lambda row: (row.gameweek, row.chip_type))),
        {"planning_context": decision_input.context_id, "prediction_timestamp": decision_input.planning_context.prediction_timestamp, "projection_run_id": decision_input.bundle_identity, "production_influence": False},
        {"evaluated_gameweeks": list(gameweeks), "complete_gameweeks": available_coverage, "total_gameweeks": len(gameweeks), "owned_player_projection_coverage": available_coverage / len(gameweeks)},
        overall_confidence, tuple(warnings), status, {"total_runtime_seconds": perf_counter() - started, "exact_evaluations": exact_evaluations, "screened_out_gameweeks": max(0, len(fh_candidates) - exact_evaluations), "cache_hits": 0, "per_chip_runtime_seconds": chip_runtime_seconds},
    )
    if cache is not None:
        cache.put(key, forecast)
    return forecast


def forecast_artifact_id(forecast: ChipOpportunityForecast) -> str:
    return "chip_forecast_" + sha256(_canonical_json(forecast.to_dict())).hexdigest()[:24]


def write_chip_opportunity_forecast(root: Path, forecast: ChipOpportunityForecast) -> Path:
    directory = Path(root) / "data" / "processed" / "chip_opportunity_forecasts" / forecast.source.get("projection_run_id", "unknown")
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{forecast_artifact_id(forecast)}.json"
    payload = _canonical_json(forecast.to_dict()) + b"\n"
    if target.exists() and target.read_bytes() != payload:
        raise ChipOpportunityForecastError("existing immutable chip forecast artifact conflicts")
    target.write_bytes(payload)
    return target


def load_chip_opportunity_forecast(path: Path | Mapping[str, Any]) -> ChipOpportunityForecast:
    if isinstance(path, Mapping):
        return ChipOpportunityForecast.from_dict(path)
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ChipOpportunityForecastError("chip opportunity forecast artifact is unreadable") from exc
    return ChipOpportunityForecast.from_dict(raw)


