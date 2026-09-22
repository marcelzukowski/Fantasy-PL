"""Probabilistic, temporal role and set-piece context for ADV challengers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import math
from types import MappingProxyType
from typing import Iterable, Mapping

from fpl_engine.features.tactical_context import (
    RoleRecord, SetPieceRecord, SetPieceType, SquadRoleRecord, TacticalContext,
    TacticalContextEngine,
)
from fpl_engine.features.tactical_roles import TacticalRole
from fpl_engine.validation.leakage import LeakageError, TargetFixtureLeakageError


def _utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise LeakageError("prediction_timestamp must be aware")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class ProbabilityAllocation:
    probabilities: Mapping[str, float]
    unassigned_probability: float
    confidence: float
    evidence_count: int

    def __post_init__(self) -> None:
        total = sum(self.probabilities.values()) + self.unassigned_probability
        if abs(total - 1.0) > 1e-9:
            raise ValueError("probability allocation must sum to one")
        if any(not 0 <= value <= 1 for value in (*self.probabilities.values(), self.confidence)):
            raise ValueError("probabilities and confidence must be in [0, 1]")
        object.__setattr__(self, "probabilities", MappingProxyType(dict(self.probabilities)))


@dataclass(frozen=True)
class RoleDistribution:
    probabilities: Mapping[TacticalRole, float]
    unknown_probability: float
    confidence: float

    def __post_init__(self) -> None:
        total = sum(self.probabilities.values()) + self.unknown_probability
        if abs(total - 1.0) > 1e-9:
            raise ValueError("role probability distribution must sum to one")
        if any(not 0 <= value <= 1 for value in (
            *self.probabilities.values(), self.unknown_probability, self.confidence,
        )):
            raise ValueError("role probabilities and confidence must be in [0, 1]")
        object.__setattr__(self, "probabilities", MappingProxyType(dict(self.probabilities)))


@dataclass(frozen=True)
class TacticalContextV2:
    """V1 compatible context plus uncertainty-preserving distributions."""

    base_context: TacticalContext
    role_distribution: RoleDistribution
    set_piece_probabilities: Mapping[SetPieceType, ProbabilityAllocation]
    context_confidence: float
    model_version: str = "tactical_context_probabilistic_v2"


class TacticalContextV2Engine:
    """Resolve temporal V1 signals and add probabilistic role/set-piece state."""

    def __init__(self, base: TacticalContextEngine | None = None):
        self.base = base or TacticalContextEngine()

    def resolve(self, *, player_id: str, team_id: str,
                prediction_timestamp: datetime, roles: Iterable[RoleRecord] = (),
                set_pieces: Iterable[SetPieceRecord] = (),
                squad: Iterable[SquadRoleRecord] = (),
                target_fixture_id: str | None = None, **kwargs) -> TacticalContextV2:
        role_rows, piece_rows, squad_rows = tuple(roles), tuple(set_pieces), tuple(squad)
        base = self.base.resolve(
            player_id=player_id, team_id=team_id,
            prediction_timestamp=prediction_timestamp, target_fixture_id=target_fixture_id,
            roles=role_rows, set_pieces=piece_rows, squad=squad_rows, **kwargs,
        )
        availability = {row.player_id: row.availability_probability for row in squad_rows}
        role_state = role_distribution(
            role_rows, player_id=player_id, team_id=team_id,
            prediction_timestamp=prediction_timestamp, target_fixture_id=target_fixture_id,
        )
        piece_state = MappingProxyType({kind: set_piece_probabilities(
            piece_rows, team_id=team_id, set_piece_type=kind,
            prediction_timestamp=prediction_timestamp, availability=availability,
            target_fixture_id=target_fixture_id,
        ) for kind in SetPieceType})
        certainties = [
            role_state.confidence, base.availability.availability_confidence,
            max((value.confidence for value in piece_state.values()), default=0.0),
            base.regime_change_confidence,
        ]
        confidence = sum(certainties) / len(certainties)
        return TacticalContextV2(base, role_state, piece_state, confidence)


def set_piece_probabilities(
    records: Iterable[SetPieceRecord], *, team_id: str, set_piece_type: SetPieceType,
    prediction_timestamp: datetime, availability: Mapping[str, float | None] | None = None,
    target_fixture_id: str | None = None,
) -> ProbabilityAllocation:
    at = _utc(prediction_timestamp)
    latest: dict[str, SetPieceRecord] = {}
    for record in records:
        if record.team_id != team_id or record.set_piece_type != set_piece_type:
            continue
        if target_fixture_id is not None and record.fixture_id == target_fixture_id:
            raise TargetFixtureLeakageError("target-match set-piece hierarchy entered prediction")
        if record.known_at > at or record.effective_from > at:
            raise LeakageError("future set-piece hierarchy entered prediction")
        if record.effective_to is not None and at > record.effective_to:
            continue
        previous = latest.get(record.player_id)
        if previous is None or (record.effective_from, record.known_at) > (
            previous.effective_from, previous.known_at
        ):
            latest[record.player_id] = record
    candidates = []
    for record in latest.values():
        available = (availability or {}).get(record.player_id, 1.0)
        if available is None:
            available = 0.5
        if available <= 0:
            continue
        candidates.append((record.player_id, record.confidence * available / record.rank))
    if not candidates:
        return ProbabilityAllocation(MappingProxyType({}), 1.0, 0.0, 0)
    raw_total = sum(weight for _, weight in candidates)
    certainty = min(1.0, max(weight for _, weight in candidates))
    probabilities = {
        player_id: certainty * weight / raw_total for player_id, weight in candidates
    }
    return ProbabilityAllocation(
        MappingProxyType(probabilities), 1.0 - certainty, certainty, len(candidates),
    )


def role_distribution(
    records: Iterable[RoleRecord], *, player_id: str, team_id: str,
    prediction_timestamp: datetime, target_fixture_id: str | None = None,
    half_life_days: float = 60.0,
) -> RoleDistribution:
    at = _utc(prediction_timestamp)
    if half_life_days <= 0:
        raise ValueError("half_life_days must be positive")
    weights: dict[TacticalRole, float] = {}
    evidence = 0.0
    for record in records:
        if record.player_id != player_id or record.team_id != team_id:
            continue
        if target_fixture_id is not None and record.fixture_id == target_fixture_id:
            raise TargetFixtureLeakageError("target-match role entered prediction")
        if record.known_at > at or record.effective_from > at:
            raise LeakageError("future tactical role entered prediction")
        if record.effective_to is not None and at > record.effective_to:
            continue
        age = (at - record.effective_from.astimezone(timezone.utc)).total_seconds() / 86400
        weight = record.confidence * 0.5 ** (age / half_life_days)
        weights[record.tactical_role] = weights.get(record.tactical_role, 0.0) + weight
        evidence += weight
    if not weights:
        return RoleDistribution(MappingProxyType({}), 1.0, 0.0)
    confidence = 1.0 - math.exp(-evidence)
    total = sum(weights.values())
    return RoleDistribution(
        MappingProxyType({role: confidence * weight / total for role, weight in weights.items()}),
        1.0 - confidence, confidence,
    )
