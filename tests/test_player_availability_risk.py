from __future__ import annotations
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from fpl_engine.planning.player_availability_risk import (
    AvailabilityStatus, PlayerAvailabilityRiskError, RecentMinutesEvidence,
    RiskLevel, build_player_availability_risks, build_player_availability_snapshot,
    load_player_availability_snapshot, write_player_availability_snapshot,
)

NOW = datetime(2026, 9, 20, 12, tzinfo=timezone.utc)


def _input():
    projection = lambda minutes: SimpleNamespace(expected_minutes_next_1=minutes)
    return SimpleNamespace(
        context_id="ctx-risk",
        bundle_identity="run-risk",
        planning_context=SimpleNamespace(prediction_timestamp=NOW.isoformat()),
        state=SimpleNamespace(current_gameweek=6),
        player_by_id={"a": object(), "b": object(), "c": object(), "d": object()},
        projections={"a": projection(90), "b": projection(65), "c": projection(65), "d": projection(80)},
    )


def _records(values, *, started=True):
    return tuple(
        RecentMinutesEvidence(
            minutes=value,
            started=started if not isinstance(started, tuple) else started[index],
            fixture_completed_at=(NOW - timedelta(days=index + 1)).isoformat(),
            known_at=(NOW - timedelta(days=index + 1)).isoformat(),
        )
        for index, value in enumerate(values)
    )


def _metadata(status="a", chance=None, news="", news_added=None):
    return {"provider_payload": {
        "status": status, "chance_of_playing_next_round": chance,
        "news": news, "news_added": news_added,
    }}


def test_official_availability_states_are_explicit():
    values = build_player_availability_risks(
        _input(), player_metadata={
            "a": _metadata("a"), "b": _metadata("d", 75),
            "c": _metadata("i", 0), "d": _metadata(None),
        }, source_observed_at=NOW,
    )
    assert values["a"].availability_status is AvailabilityStatus.AVAILABLE
    assert values["b"].availability_status is AvailabilityStatus.DOUBTFUL
    assert values["c"].availability_status is AvailabilityStatus.INJURED
    assert values["c"].availability_risk is RiskLevel.HIGH
    assert values["d"].availability_status is AvailabilityStatus.UNKNOWN


def test_minutes_risk_distinguishes_stable_role_from_variance():
    values = build_player_availability_risks(
        _input(), player_metadata={key: _metadata() for key in "abcd"},
        source_observed_at=NOW,
        recent_minutes_by_player={
            "a": _records((90, 90, 90, 90, 90)),
            "b": _records((60, 60, 60, 60, 60)),
            "c": _records((0, 90, 0, 90, 0)),
            "d": _records((25, 18, 30, 22, 15), started=(False, False, False, False, False)),
        },
    )
    assert values["a"].minutes_risk is RiskLevel.LOW
    assert values["b"].minutes_risk is RiskLevel.LOW  # stable 60 minutes is not injury/uncertainty
    assert values["c"].minutes_risk is RiskLevel.HIGH
    assert values["d"].minutes_risk is RiskLevel.MEDIUM


def test_future_minutes_and_news_are_rejected():
    future = RecentMinutesEvidence(90, True, (NOW + timedelta(minutes=1)).isoformat(), NOW.isoformat())
    with pytest.raises(PlayerAvailabilityRiskError):
        build_player_availability_risks(
            _input(), player_metadata={"a": _metadata()},
            source_observed_at=NOW, player_ids=("a",), recent_minutes_by_player={"a": (future,)},
        )
    with pytest.raises(PlayerAvailabilityRiskError):
        build_player_availability_risks(
            _input(), player_metadata={"a": _metadata("d", 75, "Late update", (NOW + timedelta(minutes=1)).isoformat())},
            source_observed_at=NOW, player_ids=("a",),
        )


def test_snapshot_is_deterministic_and_immutable(tmp_path: Path):
    first = build_player_availability_snapshot(
        _input(), player_metadata={"a": _metadata()}, player_ids=("a",), source_observed_at=NOW,
    )
    second = build_player_availability_snapshot(
        _input(), player_metadata={"a": _metadata()}, player_ids=("a",), source_observed_at=NOW,
    )
    assert first.to_dict() == second.to_dict()
    target = write_player_availability_snapshot(tmp_path, first)
    assert load_player_availability_snapshot(target).to_dict() == first.to_dict()
    assert first.coverage["recent_minutes_coverage"] == 0.0


def test_layer_is_advisory_and_does_not_change_projection_values():
    decision = _input()
    before = tuple(row.expected_minutes_next_1 for row in decision.projections.values())
    snapshot = build_player_availability_snapshot(
        decision, player_metadata={"a": _metadata("i", 0)}, player_ids=("a",), source_observed_at=NOW,
    )
    assert tuple(row.expected_minutes_next_1 for row in decision.projections.values()) == before
    assert snapshot.entries[0].overall_risk is RiskLevel.HIGH
