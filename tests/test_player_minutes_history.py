from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from fpl_engine.planning import (
    AppearanceType, PlayerMinutesAppearance, PlayerMinutesHistoryError,
    appearances_from_official_element_history, build_player_minutes_history_snapshot,
    load_player_minutes_history_snapshot, recent_minutes_evidence,
    write_player_minutes_history_snapshot,
)
from fpl_engine.planning.player_availability_risk import RiskLevel, build_player_availability_risks

CUT = datetime(2026, 9, 20, 12, tzinfo=timezone.utc)


def _input():
    return SimpleNamespace(
        context_id="minutes-context", bundle_identity="run-minutes",
        planning_context=SimpleNamespace(prediction_timestamp=CUT.isoformat()),
        state=SimpleNamespace(current_gameweek=6), player_by_id={"p": object(), "q": object()},
        projections={"p": SimpleNamespace(expected_minutes_next_1=70), "q": SimpleNamespace(expected_minutes_next_1=70)},
    )


def _row(player="p", fixture="f", days=1, minutes=90, started=True, gw=5, *, observed_days=0):
    at = CUT - timedelta(days=days)
    observed = CUT - timedelta(days=observed_days)
    kind = AppearanceType.START if started is True else AppearanceType.SUB if started is False and minutes else AppearanceType.NO_APPEARANCE if started is False else AppearanceType.UNKNOWN
    return PlayerMinutesAppearance(player, fixture, gw, at.isoformat(), True, minutes, started, kind, "OFFICIAL_FPL", observed.isoformat(), "raw-" + fixture, observed.isoformat(), at.isoformat())


def test_completed_past_fixture_is_kept_and_snapshot_is_immutable(tmp_path: Path):
    snapshot = build_player_minutes_history_snapshot(_input(), player_ids=("p",), appearances=(_row(),), provenance={"projection_run_id": "run-minutes"})
    assert snapshot.coverage["status"] == "AVAILABLE"
    assert snapshot.features[0].raw_recent_sequence == (90,)
    target = write_player_minutes_history_snapshot(tmp_path, snapshot)
    assert load_player_minutes_history_snapshot(target).to_dict() == snapshot.to_dict()
    assert write_player_minutes_history_snapshot(tmp_path, snapshot) == target


def test_future_current_and_rescheduled_after_cutoff_are_excluded():
    future = _row(fixture="future", days=-1)
    current_future = _row(fixture="current", days=-2, gw=6)
    rescheduled = _row(fixture="rescheduled", days=-2, gw=4, observed_days=-1)
    snapshot = build_player_minutes_history_snapshot(_input(), player_ids=("p",), appearances=(future, current_future, rescheduled))
    assert snapshot.appearances == ()
    assert snapshot.coverage["status"] == "UNAVAILABLE"
    assert snapshot.pit_validation["rejected_appearances"] == 3


def test_dgw_is_distinct_by_fixture_and_bgw_does_not_create_zero():
    snapshot = build_player_minutes_history_snapshot(_input(), player_ids=("p", "q"), appearances=(
        _row(fixture="dgw-1", days=2, minutes=90, gw=5), _row(fixture="dgw-2", days=1, minutes=30, started=False, gw=5),
    ))
    assert [row.fixture_id for row in snapshot.appearances] == ["dgw-1", "dgw-2"]
    assert snapshot.features[0].minutes_last_3 == 120
    assert snapshot.features[1].appearances_used == 0
    assert snapshot.features[1].zero_minute_matches_last_5 is None


def test_feature_patterns_and_unknown_start_are_transparent():
    stable = build_player_minutes_history_snapshot(_input(), player_ids=("p",), appearances=tuple(_row(fixture=f"f{i}", days=i + 1, minutes=60) for i in range(5)))
    feature = stable.features[0]
    assert feature.minutes_last_5 == 300 and feature.average_minutes_last_5 == 60
    assert feature.minutes_variability_last_5 == 0 and feature.starts_last_5 == 5
    volatile = build_player_minutes_history_snapshot(_input(), player_ids=("p",), appearances=tuple(_row(fixture=f"v{i}", days=i + 1, minutes=90 if i % 2 else 0, started=False) for i in range(5)))
    assert volatile.features[0].zero_minute_matches_last_5 == 3
    unknown = PlayerMinutesAppearance("p", "unknown", 5, (CUT-timedelta(days=1)).isoformat(), True, 90, None, AppearanceType.UNKNOWN, "OFFICIAL_FPL", CUT.isoformat(), "raw-u", CUT.isoformat())
    partial = build_player_minutes_history_snapshot(_input(), player_ids=("p",), appearances=(unknown,))
    assert partial.features[0].starts_last_3 is None
    assert partial.features[0].start_coverage == "UNAVAILABLE"


def test_official_adapter_never_infers_start_from_minutes():
    rows = appearances_from_official_element_history(
        player_id="p", history=({"fixture": 1, "round": 5, "minutes": 90},),
        fixtures_by_id={"1": {"finished": True, "kickoff_time": (CUT-timedelta(days=1)).isoformat()}},
        observed_at=CUT, source_snapshot_id="raw-1",
    )
    assert rows[0].started is None and rows[0].appearance_type is AppearanceType.UNKNOWN


def test_risk_uses_history_without_changing_availability_or_projection():
    decision = _input()
    snapshot = build_player_minutes_history_snapshot(decision, player_ids=("p",), appearances=tuple(
        _row(fixture=f"r{i}", days=i+1, minutes=90 if i % 2 else 0, started=False) for i in range(5)
    ))
    result = build_player_availability_risks(
        decision, player_metadata={"p": {"provider_payload": {"status": "a"}}}, player_ids=("p",),
        source_observed_at=CUT, recent_minutes_by_player=recent_minutes_evidence(snapshot),
    )["p"]
    assert result.availability_risk is RiskLevel.LOW
    assert result.minutes_risk is RiskLevel.HIGH
    assert decision.projections["p"].expected_minutes_next_1 == 70


def test_conflicting_duplicate_fixture_and_wrong_context_data_are_not_accepted():
    with pytest.raises(PlayerMinutesHistoryError, match="conflicting duplicate"):
        build_player_minutes_history_snapshot(_input(), player_ids=("p",), appearances=(_row(minutes=90), _row(minutes=60)))

@pytest.mark.parametrize("capture_status", ("SKIPPED_AFTER_DEADLINE", "SKIPPED_UNVERIFIED_DEADLINE"))
def test_advisory_deadline_skip_is_explicit_not_generic_missing_data(capture_status):
    snapshot = build_player_minutes_history_snapshot(
        _input(), player_ids=("p",), appearances=(),
        provenance={"capture_status": capture_status, "warnings": ["automatic capture skipped"]},
    )
    assert snapshot.coverage["status"] == capture_status
    assert "automatic capture skipped" in snapshot.warnings
