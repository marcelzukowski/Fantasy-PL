"""MIN-001 point-in-time training rows for the Minutes Model."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable

from fpl_engine.validation.leakage import (
    LeakageError,
    TargetFixtureLeakageError,
    assert_information_known,
)


def _utc(value: datetime, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise LeakageError(f"{name} must be an aware datetime")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class MinutesObservation:
    """A post-fixture outcome. ``known_at`` is when that outcome became usable."""

    player_id: str
    fixture_id: str
    kickoff: datetime
    known_at: datetime
    minutes: int
    started: bool

    def __post_init__(self) -> None:
        if not self.player_id or not self.fixture_id:
            raise ValueError("player_id and fixture_id are required")
        _utc(self.kickoff, "kickoff")
        _utc(self.known_at, "known_at")
        if isinstance(self.minutes, bool) or not isinstance(self.minutes, int) or not 0 <= self.minutes <= 130:
            raise ValueError("minutes must be an integer in [0, 130]")
        if self.started and self.minutes == 0:
            raise ValueError("a starter cannot have zero recorded minutes")

    @property
    def appeared(self) -> bool:
        return self.minutes > 0


@dataclass(frozen=True)
class MinutesTrainingRow:
    player_id: str
    fixture_id: str
    prediction_timestamp: datetime
    history_count: int
    previous_match_minutes: float | None
    rolling_5_minutes: float | None
    rolling_5_start_rate: float | None
    appeared: bool
    started: bool
    minutes: int


def eligible_history(
    observations: Iterable[MinutesObservation],
    *,
    player_id: str,
    target_fixture_id: str,
    prediction_timestamp: datetime,
) -> tuple[MinutesObservation, ...]:
    """Return only outcomes available before a target prediction.

    A supplied future record is rejected instead of silently ignored. This makes
    accidental use of an unfrozen source fail fast.
    """

    prediction = _utc(prediction_timestamp, "prediction_timestamp")
    rows: list[MinutesObservation] = []
    for observation in observations:
        if observation.player_id != player_id:
            continue
        if observation.fixture_id == target_fixture_id:
            raise TargetFixtureLeakageError(
                f"target-match lineup/minutes for fixture {target_fixture_id} entered Minutes features"
            )
        assert_information_known(
            known_at=observation.known_at,
            prediction_timestamp=prediction,
            entity=observation.fixture_id,
            source="minutes_history",
        )
        if _utc(observation.kickoff, "kickoff") >= prediction:
            raise LeakageError(
                f"fixture {observation.fixture_id} kickoff must precede prediction_timestamp"
            )
        rows.append(observation)
    return tuple(sorted(rows, key=lambda row: (_utc(row.kickoff, "kickoff"), row.fixture_id)))


def build_minutes_training_rows(
    observations: Iterable[MinutesObservation],
    *,
    prediction_offset: timedelta = timedelta(microseconds=1),
) -> tuple[MinutesTrainingRow, ...]:
    """Build expanding-window rows; the current match supplies labels only."""

    if prediction_offset <= timedelta(0):
        raise ValueError("prediction_offset must be positive")
    ordered = sorted(observations, key=lambda row: (_utc(row.kickoff, "kickoff"), row.fixture_id))
    result: list[MinutesTrainingRow] = []
    for target in ordered:
        prediction = _utc(target.kickoff, "kickoff") - prediction_offset
        prior = [
            row
            for row in ordered
            if row.player_id == target.player_id
            and row.fixture_id != target.fixture_id
            and _utc(row.kickoff, "kickoff") < prediction
            and _utc(row.known_at, "known_at") <= prediction
        ]
        prior.sort(key=lambda row: (_utc(row.kickoff, "kickoff"), row.fixture_id))
        recent = prior[-5:]
        result.append(
            MinutesTrainingRow(
                player_id=target.player_id,
                fixture_id=target.fixture_id,
                prediction_timestamp=prediction,
                history_count=len(prior),
                previous_match_minutes=float(prior[-1].minutes) if prior else None,
                rolling_5_minutes=(sum(row.minutes for row in recent) / len(recent)) if recent else None,
                rolling_5_start_rate=(sum(row.started for row in recent) / len(recent)) if recent else None,
                appeared=target.appeared,
                started=target.started,
                minutes=target.minutes,
            )
        )
    return tuple(result)
