"""TAL-001 point-in-time player-performance feature records."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable

from fpl_engine.features.tactical_roles import TacticalRole
from fpl_engine.validation.leakage import (
    LeakageError,
    TargetFixtureLeakageError,
    assert_allowed_source_feature,
    assert_information_known,
)


COUNT_FIELDS = (
    "npxg", "xa", "shots", "shots_in_box", "shots_on_target", "key_passes",
    "big_chances_created", "box_touches", "goals", "set_piece_npxg", "set_piece_xa",
    "tackles", "interceptions", "clearances", "blocks", "recoveries",
)
TEAM_FIELDS = ("team_npxg", "team_xa", "team_shots", "team_box_touches")


def _utc(value: datetime, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise LeakageError(f"{name} must be an aware datetime")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class PlayerPerformanceObservation:
    player_id: str
    fixture_id: str
    kickoff: datetime
    known_at: datetime
    minutes: int
    team_id: str
    competition_id: str
    fpl_position: str
    tactical_role: TacticalRole = TacticalRole.UNKNOWN
    opponent_strength: float | None = None
    npxg: float | None = None
    xa: float | None = None
    shots: float | None = None
    shots_in_box: float | None = None
    shots_on_target: float | None = None
    key_passes: float | None = None
    big_chances_created: float | None = None
    box_touches: float | None = None
    goals: float | None = None
    set_piece_npxg: float | None = None
    set_piece_xa: float | None = None
    tackles: float | None = None
    interceptions: float | None = None
    clearances: float | None = None
    blocks: float | None = None
    recoveries: float | None = None
    team_npxg: float | None = None
    team_xa: float | None = None
    team_shots: float | None = None
    team_box_touches: float | None = None
    source: str = "canonical_player_fixture"
    source_fields: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _utc(self.kickoff, "kickoff")
        _utc(self.known_at, "known_at")
        if not self.player_id or not self.fixture_id or not self.team_id or not self.competition_id:
            raise ValueError("canonical player, fixture, team and competition IDs are required")
        if isinstance(self.minutes, bool) or not isinstance(self.minutes, int) or not 0 <= self.minutes <= 130:
            raise ValueError("minutes must be an integer in [0, 130]")
        if self.opponent_strength is not None and self.opponent_strength <= 0:
            raise ValueError("opponent_strength must be positive")
        for name in (*COUNT_FIELDS, *TEAM_FIELDS):
            value = getattr(self, name)
            if value is not None and value < 0:
                raise ValueError(f"{name} cannot be negative")


@dataclass(frozen=True)
class TalentTrainingRow:
    player_id: str
    fixture_id: str
    prediction_timestamp: datetime
    history_count: int
    historical_minutes: int
    prior_npxg_per90: float | None
    prior_xa_per90: float | None
    tactical_role: TacticalRole
    opponent_strength: float | None
    target_npxg: float | None
    target_xa: float | None
    target_shots: float | None


def eligible_talent_history(
    observations: Iterable[PlayerPerformanceObservation], *, player_id: str,
    target_fixture_id: str, prediction_timestamp: datetime,
) -> tuple[PlayerPerformanceObservation, ...]:
    prediction = _utc(prediction_timestamp, "prediction_timestamp")
    result = []
    for observation in observations:
        if observation.player_id != player_id:
            continue
        if observation.fixture_id == target_fixture_id:
            raise TargetFixtureLeakageError(f"target-match statistics for {target_fixture_id} entered Player Talent")
        assert_information_known(known_at=observation.known_at, prediction_timestamp=prediction, entity=observation.fixture_id, source=observation.source)
        if observation.kickoff >= prediction:
            raise LeakageError(f"fixture {observation.fixture_id} is not historical at prediction_timestamp")
        for field in observation.source_fields:
            assert_allowed_source_feature(source=observation.source, field=field, known_at=observation.known_at, prediction_timestamp=prediction)
        result.append(observation)
    return tuple(sorted(result, key=lambda row: (row.kickoff, row.fixture_id)))


def build_player_talent_training_rows(
    observations: Iterable[PlayerPerformanceObservation], *, prediction_offset: timedelta = timedelta(microseconds=1)
) -> tuple[TalentTrainingRow, ...]:
    ordered = sorted(observations, key=lambda row: (row.kickoff, row.fixture_id, row.player_id))
    result = []
    for target in ordered:
        prediction = target.kickoff - prediction_offset
        history = [row for row in ordered if row.player_id == target.player_id and row.fixture_id != target.fixture_id and row.kickoff < prediction and row.known_at <= prediction]
        minutes = sum(row.minutes for row in history)
        rate = lambda field: (sum(getattr(row, field) for row in history if getattr(row, field) is not None) * 90 / sum(row.minutes for row in history if getattr(row, field) is not None)) if any(getattr(row, field) is not None and row.minutes > 0 for row in history) else None
        result.append(TalentTrainingRow(target.player_id, target.fixture_id, prediction, len(history), minutes, rate("npxg"), rate("xa"), target.tactical_role, target.opponent_strength, target.npxg, target.xa, target.shots))
    return tuple(result)
