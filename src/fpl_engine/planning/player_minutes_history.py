"""Immutable, point-in-time-safe completed player-minute history.

This module deliberately normalizes only source observations that prove a
fixture outcome was known before the PlanningContext cutoff.  It never turns a
missing fixture into a zero-minute appearance and has no policy dependency.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import StrEnum
from hashlib import sha256
import json
import math
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


PLAYER_MINUTES_HISTORY_SCHEMA_V1 = "player_minutes_history_snapshot_v1"
PLAYER_MINUTES_HISTORY_METHOD_V1 = "official_fpl_completed_appearances_v1"


class PlayerMinutesHistoryError(ValueError):
    pass


class AppearanceType(StrEnum):
    START = "START"
    SUB = "SUB"
    NO_APPEARANCE = "NO_APPEARANCE"
    UNKNOWN = "UNKNOWN"


def _utc(value: datetime | str, label: str) -> datetime:
    try:
        result = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise PlayerMinutesHistoryError(f"{label} must be an ISO-8601 timestamp.") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise PlayerMinutesHistoryError(f"{label} must be timezone-aware.")
    return result.astimezone(timezone.utc)


def _iso(value: datetime | str) -> str:
    return _utc(value, "timestamp").isoformat()


def _int(value: object, label: str, *, lower: int = 0, upper: int = 130) -> int:
    if type(value) is not int or not lower <= value <= upper:
        raise PlayerMinutesHistoryError(f"{label} must be an integer in [{lower},{upper}].")
    return value


@dataclass(frozen=True)
class PlayerMinutesAppearance:
    player_id: str
    fixture_id: str
    gameweek: int | None
    kickoff_time: str
    fixture_completed: bool
    minutes: int | None
    started: bool | None
    appearance_type: AppearanceType
    source: str
    observed_at: str
    source_snapshot_id: str
    outcome_known_at: str
    fixture_completed_at: str | None = None

    def __post_init__(self) -> None:
        if not self.player_id or not self.fixture_id or not self.source or not self.source_snapshot_id:
            raise PlayerMinutesHistoryError("appearance identity and provenance are required.")
        if self.gameweek is not None and (type(self.gameweek) is not int or not 1 <= self.gameweek <= 38):
            raise PlayerMinutesHistoryError("appearance gameweek is invalid.")
        _utc(self.kickoff_time, "kickoff_time")
        _utc(self.observed_at, "observed_at")
        _utc(self.outcome_known_at, "outcome_known_at")
        if self.fixture_completed_at is not None:
            _utc(self.fixture_completed_at, "fixture_completed_at")
        if self.minutes is not None:
            _int(self.minutes, "minutes")
        if self.started is not None and type(self.started) is not bool:
            raise PlayerMinutesHistoryError("started must be true, false, or unknown.")
        if not self.fixture_completed:
            raise PlayerMinutesHistoryError("only completed fixtures can be normalized into minute history.")
        if self.appearance_type is AppearanceType.START and self.started is not True:
            raise PlayerMinutesHistoryError("START requires source-proven started=true.")
        if self.appearance_type in {AppearanceType.SUB, AppearanceType.NO_APPEARANCE} and self.started is not False:
            raise PlayerMinutesHistoryError("SUB/NO_APPEARANCE requires source-proven started=false.")
        if self.appearance_type is AppearanceType.SUB and (self.minutes is None or self.minutes <= 0):
            raise PlayerMinutesHistoryError("SUB requires positive minutes.")
        if self.appearance_type is AppearanceType.NO_APPEARANCE and self.minutes != 0:
            raise PlayerMinutesHistoryError("NO_APPEARANCE requires zero minutes.")

    def to_dict(self) -> dict[str, Any]:
        raw = asdict(self)
        raw["appearance_type"] = self.appearance_type.value
        return raw

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "PlayerMinutesAppearance":
        try:
            return cls(
                player_id=str(raw["player_id"]), fixture_id=str(raw["fixture_id"]),
                gameweek=int(raw["gameweek"]) if raw.get("gameweek") is not None else None,
                kickoff_time=str(raw["kickoff_time"]), fixture_completed=bool(raw["fixture_completed"]),
                minutes=int(raw["minutes"]) if raw.get("minutes") is not None else None,
                started=raw.get("started") if type(raw.get("started")) is bool else None,
                appearance_type=AppearanceType(str(raw.get("appearance_type", "UNKNOWN"))),
                source=str(raw["source"]), observed_at=str(raw["observed_at"]),
                source_snapshot_id=str(raw["source_snapshot_id"]), outcome_known_at=str(raw["outcome_known_at"]),
                fixture_completed_at=str(raw["fixture_completed_at"]) if raw.get("fixture_completed_at") else None,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise PlayerMinutesHistoryError("minutes appearance payload is invalid.") from exc

    def is_eligible_at(self, cutoff: datetime | str) -> bool:
        at = _utc(cutoff, "cutoff")
        # Outcome/source availability is the proof that values were knowable;
        # kickoff completion chronology independently prevents future/DGW leaks.
        return (
            _utc(self.kickoff_time, "kickoff_time") < at
            and _utc(self.outcome_known_at, "outcome_known_at") <= at
            and _utc(self.observed_at, "observed_at") <= at
            and (self.fixture_completed_at is None or _utc(self.fixture_completed_at, "fixture_completed_at") < at)
        )


@dataclass(frozen=True)
class PlayerMinutesFeatures:
    player_id: str
    appearances_used: int
    raw_recent_sequence: tuple[int | None, ...]
    minutes_last_1: int | None
    minutes_last_3: int | None
    minutes_last_5: int | None
    average_minutes_last_3: float | None
    average_minutes_last_5: float | None
    starts_last_3: int | None
    starts_last_5: int | None
    zero_minute_matches_last_5: int | None
    sub_appearances_last_5: int | None
    minutes_60_plus_last_5: int | None
    minutes_80_plus_last_5: int | None
    average_minutes_when_started: float | None
    minutes_variability_last_5: float | None
    start_coverage: str

    def to_dict(self) -> dict[str, Any]:
        raw = asdict(self)
        raw["raw_recent_sequence"] = list(self.raw_recent_sequence)
        return raw


def _features(player_id: str, rows: Sequence[PlayerMinutesAppearance]) -> PlayerMinutesFeatures:
    recent = tuple(sorted(rows, key=lambda row: (_utc(row.kickoff_time, "kickoff_time"), row.fixture_id), reverse=True)[:5])
    values = tuple(row.minutes for row in recent)
    known = tuple(value for value in values if value is not None)
    last3 = recent[:3]
    known3 = tuple(row.minutes for row in last3 if row.minutes is not None)
    def total(items: Sequence[int | None]) -> int | None:
        return sum(items) if items and all(item is not None for item in items) else None
    started3 = tuple(row for row in last3 if row.started is not None)
    started5 = tuple(row for row in recent if row.started is not None)
    started_minutes = tuple(row.minutes for row in recent if row.started is True and row.minutes is not None)
    return PlayerMinutesFeatures(
        player_id=player_id, appearances_used=len(recent), raw_recent_sequence=values,
        minutes_last_1=values[0] if values else None, minutes_last_3=total(tuple(row.minutes for row in last3)),
        minutes_last_5=total(values), average_minutes_last_3=(sum(known3) / len(known3)) if known3 else None,
        average_minutes_last_5=(sum(known) / len(known)) if known else None,
        starts_last_3=sum(row.started is True for row in started3) if len(started3) == len(last3) and last3 else None,
        starts_last_5=sum(row.started is True for row in started5) if len(started5) == len(recent) and recent else None,
        zero_minute_matches_last_5=sum(value == 0 for value in known) if known else None,
        sub_appearances_last_5=sum(row.appearance_type is AppearanceType.SUB for row in recent) if recent else None,
        minutes_60_plus_last_5=sum(value >= 60 for value in known) if known else None,
        minutes_80_plus_last_5=sum(value >= 80 for value in known) if known else None,
        average_minutes_when_started=(sum(started_minutes) / len(started_minutes)) if started_minutes else None,
        minutes_variability_last_5=(math.sqrt(sum((value - sum(known)/len(known)) ** 2 for value in known) / len(known))) if len(known) >= 2 else None,
        start_coverage="AVAILABLE" if recent and len(started5) == len(recent) else "PARTIAL" if started5 else "UNAVAILABLE",
    )


@dataclass(frozen=True)
class PlayerMinutesHistorySnapshot:
    schema_version: str
    context_id: str
    generated_at: str
    planning_gameweek: int
    cutoff: str
    players_requested: tuple[str, ...]
    appearances: tuple[PlayerMinutesAppearance, ...]
    features: tuple[PlayerMinutesFeatures, ...]
    coverage: Mapping[str, Any]
    provenance: Mapping[str, Any]
    warnings: tuple[str, ...]
    pit_validation: Mapping[str, Any]
    metrics: Mapping[str, Any]

    def __post_init__(self) -> None:
        if self.schema_version != PLAYER_MINUTES_HISTORY_SCHEMA_V1 or not self.context_id or not self.players_requested:
            raise PlayerMinutesHistoryError("minutes history snapshot identity is invalid.")
        _utc(self.generated_at, "generated_at"); _utc(self.cutoff, "cutoff")
        if self.generated_at != self.cutoff:
            raise PlayerMinutesHistoryError("minutes history must be generated at its decision cutoff.")
        if self.planning_gameweek < 1:
            raise PlayerMinutesHistoryError("planning_gameweek is invalid.")
        ids = {(row.player_id, row.fixture_id) for row in self.appearances}
        if len(ids) != len(self.appearances):
            raise PlayerMinutesHistoryError("duplicate player/fixture minute appearances are forbidden.")
        if any(not row.is_eligible_at(self.cutoff) for row in self.appearances):
            raise PlayerMinutesHistoryError("future or unavailable minutes were included in the snapshot.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version, "context_id": self.context_id,
            "generated_at": self.generated_at, "planning_gameweek": self.planning_gameweek, "cutoff": self.cutoff,
            "players_requested": list(self.players_requested), "appearances": [row.to_dict() for row in self.appearances],
            "features": [row.to_dict() for row in self.features], "coverage": dict(self.coverage),
            "provenance": dict(self.provenance), "warnings": list(self.warnings),
            "pit_validation": dict(self.pit_validation), "metrics": dict(self.metrics),
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "PlayerMinutesHistorySnapshot":
        try:
            features = tuple(PlayerMinutesFeatures(
                player_id=str(row["player_id"]), appearances_used=int(row["appearances_used"]),
                raw_recent_sequence=tuple(row.get("raw_recent_sequence", ())), minutes_last_1=row.get("minutes_last_1"),
                minutes_last_3=row.get("minutes_last_3"), minutes_last_5=row.get("minutes_last_5"),
                average_minutes_last_3=row.get("average_minutes_last_3"), average_minutes_last_5=row.get("average_minutes_last_5"),
                starts_last_3=row.get("starts_last_3"), starts_last_5=row.get("starts_last_5"),
                zero_minute_matches_last_5=row.get("zero_minute_matches_last_5"), sub_appearances_last_5=row.get("sub_appearances_last_5"),
                minutes_60_plus_last_5=row.get("minutes_60_plus_last_5"), minutes_80_plus_last_5=row.get("minutes_80_plus_last_5"),
                average_minutes_when_started=row.get("average_minutes_when_started"), minutes_variability_last_5=row.get("minutes_variability_last_5"), start_coverage=str(row.get("start_coverage", "UNAVAILABLE")),
            ) for row in raw.get("features", ()) if isinstance(row, Mapping))
            return cls(str(raw["schema_version"]), str(raw["context_id"]), str(raw["generated_at"]), int(raw["planning_gameweek"]), str(raw["cutoff"]),
                tuple(sorted(str(value) for value in raw.get("players_requested", ()))),
                tuple(PlayerMinutesAppearance.from_dict(row) for row in raw.get("appearances", ()) if isinstance(row, Mapping)),
                features, dict(raw.get("coverage", {})), dict(raw.get("provenance", {})), tuple(str(value) for value in raw.get("warnings", ())),
                dict(raw.get("pit_validation", {})), dict(raw.get("metrics", {})))
        except (KeyError, TypeError, ValueError) as exc:
            raise PlayerMinutesHistoryError("minutes history snapshot payload is invalid.") from exc


def appearances_from_official_element_history(*, player_id: str, history: Sequence[Mapping[str, Any]], fixtures_by_id: Mapping[str, Mapping[str, Any]], observed_at: datetime | str, source_snapshot_id: str, source: str = "OFFICIAL_FPL") -> tuple[PlayerMinutesAppearance, ...]:
    """Normalize a *locally retained* element-summary response.

    A fixture is eligible only when the same local fixture snapshot explicitly
    declares it finished.  ``observed_at`` records when that outcome became
    available in the retained source; no completion timestamp is guessed.
    """
    observed = _iso(observed_at); output: list[PlayerMinutesAppearance] = []
    for row in history:
        if not isinstance(row, Mapping) or row.get("fixture") is None:
            continue
        fixture = fixtures_by_id.get(str(row["fixture"]))
        if not isinstance(fixture, Mapping) or fixture.get("finished") is not True or not fixture.get("kickoff_time"):
            continue
        minutes = row.get("minutes") if type(row.get("minutes")) is int else None
        starts_raw = row.get("starts")
        started = starts_raw if type(starts_raw) is bool else bool(starts_raw) if type(starts_raw) is int and starts_raw in {0, 1} else None
        kind = AppearanceType.START if started is True else AppearanceType.SUB if started is False and minutes is not None and minutes > 0 else AppearanceType.NO_APPEARANCE if started is False and minutes == 0 else AppearanceType.UNKNOWN
        output.append(PlayerMinutesAppearance(str(player_id), str(row["fixture"]), int(row["round"]) if type(row.get("round")) is int else None,
            str(fixture["kickoff_time"]), True, minutes, started, kind, source, observed, str(source_snapshot_id), observed,
            str(fixture["finished_at"]) if fixture.get("finished_at") else None))
    return tuple(output)


def build_player_minutes_history_snapshot(decision_input: Any, *, player_ids: Sequence[str] | None = None,
                                          appearances: Iterable[PlayerMinutesAppearance | Mapping[str, Any]] = (),
                                          provenance: Mapping[str, Any] | None = None,
                                          advisory_cutoff: datetime | str | None = None) -> PlayerMinutesHistorySnapshot:
    planning_prediction = _utc(decision_input.planning_context.prediction_timestamp, "prediction timestamp")
    # Automatic capture happens after policy freeze. Its own cutoff is the
    # actual pre-deadline observation time; it is context-bound but never
    # context-defining and cannot alter the frozen production policy.
    cutoff = _utc(advisory_cutoff, "advisory cutoff") if advisory_cutoff is not None else planning_prediction
    requested = tuple(sorted({str(value) for value in (player_ids if player_ids is not None else decision_input.player_by_id)}))
    accepted: dict[tuple[str, str], PlayerMinutesAppearance] = {}
    rejected = 0
    for raw in appearances:
        row = raw if isinstance(raw, PlayerMinutesAppearance) else PlayerMinutesAppearance.from_dict(raw)
        if row.player_id not in requested:
            continue
        if not row.is_eligible_at(cutoff):
            rejected += 1
            continue
        key = (row.player_id, row.fixture_id)
        if key in accepted and accepted[key].to_dict() != row.to_dict():
            raise PlayerMinutesHistoryError("conflicting duplicate player/fixture appearance.")
        accepted[key] = row
    rows = tuple(sorted(accepted.values(), key=lambda row: (row.player_id, _utc(row.kickoff_time, "kickoff_time"), row.fixture_id)))
    by_player = {player_id: tuple(row for row in rows if row.player_id == player_id) for player_id in requested}
    features = tuple(_features(player_id, by_player[player_id]) for player_id in requested)
    depths = [feature.appearances_used for feature in features]
    usable = sum(feature.appearances_used > 0 for feature in features)
    status = "AVAILABLE" if usable == len(requested) and requested else "PARTIAL" if usable else "UNAVAILABLE"
    source = dict(provenance or {})
    source.setdefault("planning_prediction_timestamp", planning_prediction.isoformat())
    if cutoff != planning_prediction:
        source.setdefault("advisory_capture_cutoff", cutoff.isoformat())
    # A normal explicit desktop analysis may conservatively skip capture before
    # networking. Preserve that state for Trust/UI rather than presenting it as
    # a generic missing-data failure. Provider partial/unavailable states are
    # likewise advisory and never change the PlanningContext or policy result.
    capture_status = str(source.get("capture_status", "")).upper()
    if capture_status in {"SKIPPED_AFTER_DEADLINE", "SKIPPED_UNVERIFIED_DEADLINE"}:
        status = capture_status
    elif capture_status == "PARTIAL" and status == "UNAVAILABLE":
        status = "PARTIAL"
    elif capture_status == "UNAVAILABLE":
        status = "UNAVAILABLE"
    warnings: list[str] = []
    if not usable:
        warnings.append("No local point-in-time completed-fixture player minutes source is available.")
    if rejected:
        warnings.append(f"Excluded {rejected} future, current-fixture, or unproven appearance record(s).")
    for warning in source.get("warnings", ()) if isinstance(source.get("warnings"), (list, tuple)) else ():
        warnings.append(str(warning))
    source.setdefault("source", "LOCAL_OFFICIAL_FPL_CACHE")
    source.setdefault("production_influence", False)
    return PlayerMinutesHistorySnapshot(
        PLAYER_MINUTES_HISTORY_SCHEMA_V1, decision_input.context_id, cutoff.isoformat(), decision_input.state.current_gameweek, cutoff.isoformat(), requested, rows, features,
        {"status": status, "players_requested": len(requested), "players_with_usable_history": usable,
         "fixtures_represented": len({row.fixture_id for row in rows}), "minimum_history_depth": min(depths) if depths else 0,
         "maximum_history_depth": max(depths) if depths else 0, "start_coverage": "AVAILABLE" if features and all(row.start_coverage == "AVAILABLE" for row in features) else "PARTIAL" if any(row.start_coverage != "UNAVAILABLE" for row in features) else "UNAVAILABLE"},
        source, tuple(warnings), {"status": "PASS", "cutoff": cutoff.isoformat(), "accepted_appearances": len(rows), "rejected_appearances": rejected}, {"raw_load_seconds": 0.0, "normalization_seconds": 0.0, "cache_hits": 0},
    )


def recent_minutes_evidence(snapshot: PlayerMinutesHistorySnapshot) -> dict[str, tuple[Mapping[str, Any], ...]]:
    """Adapter for the advisory availability service; policy code never reads it."""
    result: dict[str, list[Mapping[str, Any]]] = {}
    for row in snapshot.appearances:
        if row.minutes is None:
            continue
        result.setdefault(row.player_id, []).append({"minutes": row.minutes, "started": row.started, "fixture_completed_at": row.fixture_completed_at or row.kickoff_time, "known_at": row.outcome_known_at, "source": row.source})
    return {player_id: tuple(values) for player_id, values in result.items()}


def minutes_history_artifact_id(snapshot: PlayerMinutesHistorySnapshot) -> str:
    return "minutes_history_" + sha256(json.dumps(snapshot.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()[:24]


def write_player_minutes_history_snapshot(root: Path, snapshot: PlayerMinutesHistorySnapshot) -> Path:
    target = Path(root) / "data" / "processed" / "player_minutes_history_snapshots" / str(snapshot.provenance.get("projection_run_id") or "unknown") / f"{minutes_history_artifact_id(snapshot)}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(snapshot.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode() + b"\n"
    if target.exists() and target.read_bytes() != payload:
        raise PlayerMinutesHistoryError("existing immutable minutes history snapshot conflicts.")
    target.write_bytes(payload)
    return target


def load_player_minutes_history_snapshot(path: Path | Mapping[str, Any]) -> PlayerMinutesHistorySnapshot:
    try:
        raw = path if isinstance(path, Mapping) else json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PlayerMinutesHistoryError("minutes history snapshot artifact is unreadable.") from exc
    return PlayerMinutesHistorySnapshot.from_dict(raw)
