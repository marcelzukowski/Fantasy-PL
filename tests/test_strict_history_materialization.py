from datetime import datetime, timezone
import hashlib
from types import SimpleNamespace

import pytest

from scripts.finalize_strict_holdout import _verify_frozen
from scripts.materialize_strict_history import _resolve_snapshot


def _snapshot(path, deadline):
    return SimpleNamespace(
        snapshot_path=path,
        data={"events": [{"id": 21, "deadline_time": deadline.isoformat()}]},
    )


def test_deadline_resolution_moves_strict_selection_back_when_deadline_changed_earlier():
    original = datetime(2024, 1, 13, 13, 30, tzinfo=timezone.utc)
    actual = datetime(2024, 1, 12, 18, 15, tzinfo=timezone.utc)
    calls = []

    class Adapter:
        def get_snapshot_before(self, deadline):
            calls.append(deadline)
            return _snapshot("after-change" if deadline == original else "strict", actual)

    deadline, snapshot = _resolve_snapshot(Adapter(), 21, original)
    assert deadline == actual
    assert snapshot.snapshot_path == "strict"
    assert calls == [original, actual]


def test_frozen_policy_integrity_fails_if_a_recorded_file_changes(tmp_path):
    policy = tmp_path / "policy.py"
    policy.write_text("frozen = True\n", encoding="utf-8")
    digest = hashlib.sha256(policy.read_bytes()).hexdigest()
    manifest = {"file_sha256": {"policy.py": digest}}
    assert _verify_frozen(tmp_path, manifest)["verified"] is True
    policy.write_text("frozen = False\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="frozen policy changed"):
        _verify_frozen(tmp_path, manifest)



def test_stale_future_fixture_is_removed_when_completed_result_is_pit_known():
    from datetime import datetime, timedelta, timezone
    from types import SimpleNamespace

    import pandas as pd

    from fpl_engine.current_history import (
        reconcile_current_targets_with_known_history,
    )

    at = datetime(
        2026, 4, 10, 12, 0,
        tzinfo=timezone.utc,
    )

    current_states = pd.DataFrame(
        [
            {
                "canonical_fixture_id": "fixture-completed",
                "scheduled_kickoff": pd.Timestamp(
                    at + timedelta(days=2)
                ),
            },
            {
                "canonical_fixture_id": "fixture-future",
                "scheduled_kickoff": pd.Timestamp(
                    at + timedelta(days=3)
                ),
            },
        ]
    )

    match_rows = [
        SimpleNamespace(
            fixture_id="fixture-completed",
            kickoff=at - timedelta(hours=6),
            known_at=at - timedelta(hours=2),
        ),
        SimpleNamespace(
            fixture_id="fixture-future",
            kickoff=at + timedelta(days=3),
            known_at=at + timedelta(days=3, hours=4),
        ),
    ]

    filtered, history = (
        reconcile_current_targets_with_known_history(
            current_states,
            match_rows,
            prediction_timestamp=at,
        )
    )

    assert set(
        filtered["canonical_fixture_id"]
    ) == {"fixture-future"}

    assert [
        row.fixture_id
        for row in history
    ] == ["fixture-completed"]


def test_fixture_is_not_treated_as_known_completed_before_known_at():
    from datetime import datetime, timedelta, timezone
    from types import SimpleNamespace

    import pandas as pd

    from fpl_engine.current_history import (
        reconcile_current_targets_with_known_history,
    )

    at = datetime(
        2026, 4, 10, 12, 0,
        tzinfo=timezone.utc,
    )

    current_states = pd.DataFrame(
        [
            {
                "canonical_fixture_id": "fixture-not-yet-known",
                "scheduled_kickoff": pd.Timestamp(
                    at + timedelta(days=2)
                ),
            },
        ]
    )

    match_rows = [
        SimpleNamespace(
            fixture_id="fixture-not-yet-known",
            kickoff=at - timedelta(hours=1),
            known_at=at + timedelta(hours=3),
        ),
    ]

    filtered, history = (
        reconcile_current_targets_with_known_history(
            current_states,
            match_rows,
            prediction_timestamp=at,
        )
    )

    assert list(
        filtered["canonical_fixture_id"]
    ) == ["fixture-not-yet-known"]

    assert history == []
