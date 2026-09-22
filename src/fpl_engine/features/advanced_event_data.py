"""Point-in-time contracts for optional multi-source attacking event evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
import math
from types import MappingProxyType
from typing import Iterable, Mapping

from fpl_engine.features.player_talent_dataset import PlayerPerformanceObservation
from fpl_engine.features.tactical_roles import TacticalRole
from fpl_engine.validation.leakage import (
    LeakageError, TargetFixtureLeakageError, assert_allowed_source_feature,
    assert_information_known,
)


ATTACKING_EVENT_FEATURES = (
    "npxg", "xg", "penalty_xg", "xa", "shots", "shots_in_box",
    "shots_on_target", "key_passes", "big_chances", "big_chances_created",
    "box_touches", "penalty_area_touches", "set_piece_npxg", "set_piece_xa",
    "goals", "assists",
)


class AvailabilityStatus(StrEnum):
    STRICT_HISTORICAL = "strict_historical"
    CURRENT_ONLY = "current_only"
    UNAVAILABLE = "unavailable"


def _utc(value: datetime, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise LeakageError(f"{name} must be an aware datetime")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class TemporalEventRecord:
    provider: str
    season: str
    player_id: str
    fixture_id: str
    team_id: str
    competition_id: str
    fpl_position: str
    minutes: int
    observed_at: datetime
    known_at: datetime
    effective_at: datetime
    retrieved_at: datetime
    values: Mapping[str, float | None]
    source_version: str
    tactical_role: TacticalRole = TacticalRole.UNKNOWN

    def __post_init__(self) -> None:
        observed = _utc(self.observed_at, "observed_at")
        known = _utc(self.known_at, "known_at")
        effective = _utc(self.effective_at, "effective_at")
        retrieved = _utc(self.retrieved_at, "retrieved_at")
        object.__setattr__(self, "observed_at", observed)
        object.__setattr__(self, "known_at", known)
        object.__setattr__(self, "effective_at", effective)
        object.__setattr__(self, "retrieved_at", retrieved)
        if not all((self.provider, self.season, self.player_id, self.fixture_id,
                    self.team_id, self.competition_id, self.source_version)):
            raise ValueError("provider, season, canonical IDs and source_version are required")
        if known < observed or effective < observed:
            raise ValueError("known_at/effective_at cannot precede the observed event")
        if isinstance(self.minutes, bool) or not 0 <= self.minutes <= 130:
            raise ValueError("minutes must be in [0, 130]")
        unknown = set(self.values) - set(ATTACKING_EVENT_FEATURES)
        if unknown:
            raise ValueError(f"unsupported event feature names: {sorted(unknown)}")
        for name, value in self.values.items():
            if value is not None and (
                isinstance(value, bool) or not math.isfinite(value) or value < 0
            ):
                raise ValueError(f"{name} must be finite and non-negative or NULL")
        object.__setattr__(self, "values", MappingProxyType(dict(self.values)))


@dataclass(frozen=True)
class FeatureAvailabilityEntry:
    provider: str
    season: str
    feature: str
    status: AvailabilityStatus
    evidence: str
    source_version: str | None = None


class FeatureAvailabilityMatrix:
    def __init__(self, entries: Iterable[FeatureAvailabilityEntry]):
        rows = tuple(entries)
        keys = [(row.provider, row.season, row.feature) for row in rows]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate provider/season/feature availability entry")
        self.entries = tuple(sorted(rows, key=lambda row: (row.provider, row.season, row.feature)))

    def status(self, provider: str, season: str, feature: str) -> AvailabilityStatus:
        selected = [
            row.status for row in self.entries
            if (row.provider, row.season, row.feature) == (provider, season, feature)
        ]
        return selected[0] if selected else AvailabilityStatus.UNAVAILABLE


def eligible_event_history(
    records: Iterable[TemporalEventRecord], *, player_id: str,
    target_fixture_id: str, prediction_timestamp: datetime,
) -> tuple[TemporalEventRecord, ...]:
    """Return observations defensibly available at T; retrieval may occur later.

    Immutable repository history can be retrieved after T when its commit/source
    version proves ``known_at``. Retrieval time remains recorded and distinct.
    """
    at = _utc(prediction_timestamp, "prediction_timestamp")
    result = []
    for record in records:
        if record.player_id != player_id:
            continue
        if record.fixture_id == target_fixture_id:
            raise TargetFixtureLeakageError(
                f"target fixture {target_fixture_id} entered advanced event history"
            )
        assert_information_known(
            known_at=record.known_at, prediction_timestamp=at,
            entity=record.fixture_id, source=record.provider,
        )
        if record.effective_at > at or record.observed_at >= at:
            raise LeakageError(
                f"event {record.fixture_id} was not effective before prediction_timestamp"
            )
        for feature, value in record.values.items():
            if value is not None:
                assert_allowed_source_feature(
                    source=record.provider, field=feature,
                    known_at=record.known_at, prediction_timestamp=at,
                )
        result.append(record)
    return tuple(sorted(result, key=lambda row: (row.observed_at, row.fixture_id)))


def derived_npxg(record: TemporalEventRecord) -> float | None:
    """Derive npxG only when independently observed xG and penalty xG coexist."""
    xg, penalty_xg = record.values.get("xg"), record.values.get("penalty_xg")
    if xg is None or penalty_xg is None:
        return None
    if penalty_xg > xg + 1e-9:
        raise ValueError("penalty_xg cannot exceed total xg")
    return xg - penalty_xg


def to_player_performance(record: TemporalEventRecord) -> PlayerPerformanceObservation:
    values = record.values
    npxg = values.get("npxg")
    if npxg is None:
        npxg = derived_npxg(record)
    supported = {
        "npxg": npxg,
        "xa": values.get("xa"),
        "shots": values.get("shots"),
        "shots_in_box": values.get("shots_in_box"),
        "shots_on_target": values.get("shots_on_target"),
        "key_passes": values.get("key_passes"),
        "big_chances_created": values.get("big_chances_created"),
        "box_touches": values.get("box_touches"),
        "goals": values.get("goals"),
        "set_piece_npxg": values.get("set_piece_npxg"),
        "set_piece_xa": values.get("set_piece_xa"),
    }
    source_fields = tuple(sorted(name for name, value in values.items() if value is not None))
    return PlayerPerformanceObservation(
        record.player_id, record.fixture_id, record.observed_at, record.known_at,
        record.minutes, record.team_id, record.competition_id, record.fpl_position,
        tactical_role=record.tactical_role, source=record.provider,
        source_fields=source_fields, **supported,
    )


def development_feature_matrix() -> FeatureAvailabilityMatrix:
    """Audited matrix for sources already supported by this repository."""
    entries = []
    for season in ("2023/24", "2024/25"):
        for feature in ("xa", "goals", "assists"):
            entries.append(FeatureAvailabilityEntry(
                "vaastav", season, feature, AvailabilityStatus.STRICT_HISTORICAL,
                "per-fixture row known conservatively after match completion",
            ))
        for feature in ("npxg", "shots", "shots_in_box", "shots_on_target",
                        "key_passes", "big_chances_created", "box_touches"):
            entries.append(FeatureAvailabilityEntry(
                "vaastav", season, feature, AvailabilityStatus.UNAVAILABLE,
                "merged_gw source has no independently evidenced field",
            ))
    for feature in ATTACKING_EVENT_FEATURES:
        entries.append(FeatureAvailabilityEntry(
            "api_football", "2026/27", feature,
            AvailabilityStatus.CURRENT_ONLY if feature in {
                "shots", "shots_on_target", "goals", "assists", "key_passes"
            } else AvailabilityStatus.UNAVAILABLE,
            "current response only; no pre-deadline historical archive is materialized",
        ))
        for season in ("2023/24", "2024/25", "2026/27"):
            entries.append(FeatureAvailabilityEntry(
                "statsbomb_open", season, feature, AvailabilityStatus.UNAVAILABLE,
                "supported adapter exists but required EPL competition coverage is absent",
            ))
        for season in ("2023/24", "2024/25"):
            status = (AvailabilityStatus.STRICT_HISTORICAL if feature in {"goals", "assists"}
                      else AvailabilityStatus.UNAVAILABLE)
            entries.append(FeatureAvailabilityEntry(
                "official_fpl", season, feature, status,
                "fixture outcomes are historical; no independent shot/xG event feed",
            ))
        entries.append(FeatureAvailabilityEntry(
            "official_fpl", "2026/27", feature,
            AvailabilityStatus.CURRENT_ONLY if feature in {"goals", "assists"}
            else AvailabilityStatus.UNAVAILABLE,
            "event-live values become available only after each current fixture",
        ))
    return FeatureAvailabilityMatrix(entries)


def immutable_values(values: Mapping[str, float | None]) -> Mapping[str, float | None]:
    return MappingProxyType(dict(values))
