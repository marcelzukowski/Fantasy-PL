"""CONTEXT-002..005 temporal tactical, set-piece, squad and availability context."""

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Iterable

from fpl_engine.data.manual_context import ManualContextRecord
from fpl_engine.data.schemas.entities import PlayerTeamSpell
from fpl_engine.validation.leakage import LeakageError, TargetFixtureLeakageError

from .tactical_roles import TACTICAL_ROLE_TAXONOMY_VERSION, TacticalRole, validate_fpl_position


def _utc(value: datetime, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise LeakageError(f"{name} must be an aware datetime")
    return value.astimezone(timezone.utc)


def _probability(value: float, name: str) -> None:
    if isinstance(value, bool) or not 0 <= value <= 1:
        raise ValueError(f"{name} must be in [0, 1]")


def normalize_formation(value: str) -> str:
    compact = value.strip().replace(" ", "").replace("_", "-")
    parts = compact.split("-") if "-" in compact else list(compact)
    if len(parts) not in {3, 4} or any(not part.isdigit() for part in parts) or sum(int(part) for part in parts) != 10:
        raise ValueError("formation must describe ten outfield players")
    return "-".join(parts)


@dataclass(frozen=True)
class TemporalContextRecord:
    effective_from: datetime
    known_at: datetime
    source: str
    confidence: float
    effective_to: datetime | None = None
    fixture_id: str | None = None
    source_record_id: str | None = None

    def __post_init__(self) -> None:
        start = _utc(self.effective_from, "effective_from")
        _utc(self.known_at, "known_at")
        _probability(self.confidence, "confidence")
        if self.effective_to is not None and _utc(self.effective_to, "effective_to") < start:
            raise ValueError("effective_to precedes effective_from")

    def available_at(self, timestamp: datetime) -> bool:
        at = _utc(timestamp, "prediction_timestamp")
        return self.known_at <= at and self.effective_from <= at and (self.effective_to is None or at <= self.effective_to)


@dataclass(frozen=True)
class RoleRecord(TemporalContextRecord):
    player_id: str = ""
    team_id: str = ""
    tactical_role: TacticalRole = TacticalRole.UNKNOWN
    fpl_position: str = "MID"

    def __post_init__(self) -> None:
        super().__post_init__()
        validate_fpl_position(self.fpl_position)


@dataclass(frozen=True)
class FormationRecord(TemporalContextRecord):
    team_id: str = ""
    formation: str = ""

    def __post_init__(self) -> None:
        super().__post_init__()
        object.__setattr__(self, "formation", normalize_formation(self.formation))


@dataclass(frozen=True)
class ManagerRegimeRecord(TemporalContextRecord):
    team_id: str = ""
    manager_id: str = ""


class SetPieceType(StrEnum):
    PENALTIES = "penalties"
    DIRECT_FREE_KICKS = "direct_free_kicks"
    INDIRECT_FREE_KICKS = "indirect_free_kicks"
    CORNERS_LEFT = "corners_left"
    CORNERS_RIGHT = "corners_right"


@dataclass(frozen=True)
class SetPieceRecord(TemporalContextRecord):
    team_id: str = ""
    player_id: str = ""
    set_piece_type: SetPieceType = SetPieceType.PENALTIES
    rank: int = 1

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.rank < 1:
            raise ValueError("set-piece rank must be positive")


@dataclass(frozen=True)
class SquadRoleRecord(TemporalContextRecord):
    team_id: str = ""
    player_id: str = ""
    tactical_role: TacticalRole = TacticalRole.UNKNOWN
    availability_probability: float | None = None
    recent_start_share: float | None = None
    manager_preference: float | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        for name in ("availability_probability", "recent_start_share", "manager_preference"):
            value = getattr(self, name)
            if value is not None:
                _probability(value, name)


@dataclass(frozen=True)
class AvailabilityRecord(TemporalContextRecord):
    player_id: str = ""
    status: str | None = None
    chance_of_playing: int | None = None
    confirmed_suspension: bool = False
    injury_severity_bucket: str | None = None
    workload_score: float | None = None
    returned_from_injury: bool = False
    snapshot_timestamp: datetime | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.chance_of_playing is not None and not 0 <= self.chance_of_playing <= 100:
            raise ValueError("chance_of_playing must be in [0, 100]")
        if self.workload_score is not None:
            _probability(self.workload_score, "workload_score")
        if self.snapshot_timestamp is not None:
            _utc(self.snapshot_timestamp, "snapshot_timestamp")


@dataclass(frozen=True)
class SetPieceRole:
    rank: int
    confidence: float


@dataclass(frozen=True)
class AvailabilityContext:
    availability_probability: float | None
    suspension_block: bool
    injury_severity_bucket: str | None
    workload_score: float | None
    availability_confidence: float
    injury_return_flag: bool


@dataclass(frozen=True)
class TacticalContext:
    player_id: str
    team_id: str
    prediction_timestamp: datetime
    fpl_position: str | None
    current_tactical_role: TacticalRole
    role_confidence: float
    dominant_formation: str | None
    formation_stability: float | None
    manager_id: str | None
    manager_regime_started_at: datetime | None
    manager_regime_matches: int
    club_change_flag: bool
    league_change_flag: bool
    manager_change_flag: bool
    formation_change_flag: bool
    role_change_flag: bool
    set_piece_change_flag: bool
    injury_return_flag: bool
    regime_change_types: tuple[str, ...]
    regime_change_confidence: float
    historical_weight_multiplier: float
    current_role_multiplier_goal: float
    current_role_multiplier_assist: float
    current_role_multiplier_minutes: float
    current_role_multiplier_defcon: float
    penalty_role: SetPieceRole | None
    direct_free_kick_role: SetPieceRole | None
    indirect_free_kick_role: SetPieceRole | None
    corner_role_left: SetPieceRole | None
    corner_role_right: SetPieceRole | None
    role_competitor_set: tuple[str, ...]
    squad_competition_score: float | None
    role_security_score: float | None
    availability: AvailabilityContext
    tactical_context_uncertainty: float
    model_version: str = "tactical_context_rules_v1"
    dataset_version: str = "tactical_context_dataset_v1"
    feature_version: str = TACTICAL_ROLE_TAXONOMY_VERSION


class TacticalContextEngine:
    """Resolve the latest information that was both effective and known at T."""

    def resolve(
        self,
        *,
        player_id: str,
        team_id: str,
        prediction_timestamp: datetime,
        target_fixture_id: str | None = None,
        roles: Iterable[RoleRecord] = (),
        formations: Iterable[FormationRecord] = (),
        managers: Iterable[ManagerRegimeRecord] = (),
        set_pieces: Iterable[SetPieceRecord] = (),
        squad: Iterable[SquadRoleRecord] = (),
        availability: Iterable[AvailabilityRecord] = (),
        player_team_spells: Iterable[PlayerTeamSpell] = (),
        manual_context: Iterable[ManualContextRecord] = (),
    ) -> TacticalContext:
        at = _utc(prediction_timestamp, "prediction_timestamp")
        role_history = self._history(roles, at, target_fixture_id, player_id=player_id, team_id=team_id)
        formation_history = self._history(formations, at, target_fixture_id, team_id=team_id)
        manager_history = self._history(managers, at, target_fixture_id, team_id=team_id)
        roles_now = [record for record in role_history if record.effective_to is None or at <= record.effective_to]
        formations_now = [record for record in formation_history if record.effective_to is None or at <= record.effective_to]
        managers_now = [record for record in manager_history if record.effective_to is None or at <= record.effective_to]
        set_piece_now = self._eligible(set_pieces, at, target_fixture_id, team_id=team_id)
        squad_now = self._eligible(squad, at, target_fixture_id, team_id=team_id)
        availability_now = self._eligible(availability, at, target_fixture_id, player_id=player_id)
        manual = [record for record in manual_context if record.subject_id in {player_id, team_id} and record.is_active_at(at)]

        current_role_record = self._latest(roles_now)
        role = current_role_record.tactical_role if current_role_record else TacticalRole.UNKNOWN
        role_confidence = current_role_record.confidence if current_role_record else 0.0
        fpl_position = current_role_record.fpl_position if current_role_record else None
        manual_role = self._manual_value(manual, "tactical_role", player_id)
        if manual_role is not None:
            role = TacticalRole(str(manual_role.value))
            role_confidence = manual_role.confidence

        current_formation = self._latest(formations_now)
        formation = current_formation.formation if current_formation else None
        manual_formation = self._manual_value(manual, "dominant_formation", team_id)
        if manual_formation is not None:
            formation = str(manual_formation.value)
        recent_formations = formation_history[-5:]
        stability = (
            sum(item.formation == formation for item in recent_formations) / len(recent_formations)
            if formation and recent_formations else None
        )

        manager = self._latest(managers_now)
        manager_id = manager.manager_id if manager else None
        manager_started_at = manager.effective_from if manager else None
        manual_manager = self._manual_value(manual, "manager_id", team_id)
        if manual_manager is not None:
            manager_id = str(manual_manager.value)
            manager_started_at = manual_manager.effective_from
        manager_matches = sum(item.effective_from >= manager_started_at for item in formation_history) if manager_started_at else 0
        role_changed = bool(current_role_record and any(item.tactical_role != role for item in role_history if item is not current_role_record))
        formation_changed = bool(current_formation and any(item.formation != formation for item in formation_history if item is not current_formation))
        manager_changed = bool(manager_id and any(item.manager_id != manager_id for item in manager_history if item is not manager))

        set_piece_roles = self._set_piece_roles(set_piece_now, squad_now, player_id)
        manual_names = {
            SetPieceType.PENALTIES: "penalty_rank", SetPieceType.DIRECT_FREE_KICKS: "direct_free_kick_rank",
            SetPieceType.INDIRECT_FREE_KICKS: "indirect_free_kick_rank", SetPieceType.CORNERS_LEFT: "corner_left_rank",
            SetPieceType.CORNERS_RIGHT: "corner_right_rank",
        }
        for kind, name in manual_names.items():
            override = self._manual_value(manual, name, player_id)
            if override is not None:
                value = override.value
                rank = int(value.get("rank", 1)) if isinstance(value, dict) else int(value)
                confidence = float(value.get("confidence", override.confidence)) if isinstance(value, dict) else override.confidence
                set_piece_roles[kind] = SetPieceRole(rank, confidence)
        competitors = tuple(sorted(
            item.player_id for item in squad_now
            if item.player_id != player_id and item.tactical_role == role and (item.availability_probability or 0) > 0
        ))
        competitor_values = [
            ((item.availability_probability or 0) * ((item.recent_start_share or 0.5) + (item.manager_preference or 0.5)) / 2)
            for item in squad_now if item.player_id in competitors
        ]
        competition = min(1.0, sum(competitor_values)) if squad_now else None
        own = next((item for item in squad_now if item.player_id == player_id), None)
        security = None if own is None else max(0.0, min(1.0, (own.recent_start_share or 0.5) * (1 - (competition or 0))))
        availability_context = self._availability(availability_now)
        known_spells = sorted(
            (
                spell for spell in player_team_spells
                if spell.player_id == player_id and spell.retrieved_at <= at and spell.effective_from <= at
            ),
            key=lambda spell: spell.effective_from,
        )
        active_spell = next(
            (spell for spell in reversed(known_spells) if spell.effective_to is None or at <= spell.effective_to),
            None,
        )
        prior_spells = [spell for spell in known_spells if active_spell and spell.effective_from < active_spell.effective_from]
        club_changed = bool(active_spell and active_spell.team_id == team_id and any(spell.team_id != team_id for spell in prior_spells))
        league_changed = bool(active_spell and any(spell.competition_id != active_spell.competition_id for spell in prior_spells))
        changes = tuple(name for name, active in (
            ("club_change", club_changed), ("league_change", league_changed),
            ("manager_change", manager_changed), ("formation_change", formation_changed),
            ("tactical_role_change", role_changed), ("injury_return", availability_context.injury_return_flag),
        ) if active)
        multiplier = max(0.4, 1 - 0.15 * len(changes))
        uncertainty = min(1.0, (1 - role_confidence) * 0.35 + (1 - availability_context.availability_confidence) * 0.25 + (competition or 0) * 0.15 + 0.15 * manager_changed + 0.1 * role_changed)
        return TacticalContext(
            player_id, team_id, at, fpl_position, role, role_confidence, formation, stability,
            manager_id, manager_started_at,
            manager_matches, club_changed, league_changed, manager_changed, formation_changed, role_changed,
            any(value is not None for value in set_piece_roles.values()), availability_context.injury_return_flag,
            changes, max([role_confidence, *(item.confidence for item in manual)], default=0.0), multiplier,
            1.0, 1.0, 1.0, 1.0, set_piece_roles[SetPieceType.PENALTIES],
            set_piece_roles[SetPieceType.DIRECT_FREE_KICKS], set_piece_roles[SetPieceType.INDIRECT_FREE_KICKS],
            set_piece_roles[SetPieceType.CORNERS_LEFT], set_piece_roles[SetPieceType.CORNERS_RIGHT],
            competitors, competition, security, availability_context, uncertainty,
        )

    @staticmethod
    def _history(records, at, target_fixture_id, **identities):
        result = []
        for record in records:
            if any(getattr(record, key, None) != value for key, value in identities.items()):
                continue
            if target_fixture_id is not None and record.fixture_id == target_fixture_id:
                raise TargetFixtureLeakageError(f"target fixture {target_fixture_id} entered tactical context")
            if isinstance(record, AvailabilityRecord) and record.snapshot_timestamp is not None and record.snapshot_timestamp >= at:
                continue
            if record.known_at <= at and record.effective_from <= at:
                result.append(record)
        return sorted(result, key=lambda item: (item.effective_from, item.known_at, item.source_record_id or ""))

    @classmethod
    def _eligible(cls, records, at, target_fixture_id, **identities):
        return [record for record in cls._history(records, at, target_fixture_id, **identities) if record.effective_to is None or at <= record.effective_to]

    @staticmethod
    def _latest(records):
        return records[-1] if records else None

    @staticmethod
    def _manual_value(records, context_type, subject_id):
        eligible = [item for item in records if item.context_type == context_type and item.subject_id == subject_id]
        return max(eligible, key=lambda item: (item.effective_from, item.created_at)) if eligible else None

    @staticmethod
    def _set_piece_roles(records, squad, player_id):
        availability = {item.player_id: item.availability_probability for item in squad}
        result = {}
        for kind in SetPieceType:
            hierarchy = sorted((item for item in records if item.set_piece_type == kind), key=lambda item: item.rank)
            active = [item for item in hierarchy if availability.get(item.player_id, 1.0) != 0]
            selected = next((item for item in active if item.player_id == player_id), None)
            result[kind] = SetPieceRole(active.index(selected) + 1, selected.confidence) if selected else None
        return result

    @staticmethod
    def _availability(records):
        record = records[-1] if records else None
        if record is None:
            return AvailabilityContext(None, False, None, None, 0.0, False)
        if record.confirmed_suspension:
            probability = 0.0
        elif record.chance_of_playing is not None:
            probability = 0.5 * (record.chance_of_playing / 100) + 0.5 * 0.85
        elif record.status == "a":
            probability = 0.95
        elif record.status in {"i", "u"}:
            probability = 0.1
        else:
            probability = None
        return AvailabilityContext(probability, record.confirmed_suspension, record.injury_severity_bucket, record.workload_score, record.confidence, record.returned_from_injury)
