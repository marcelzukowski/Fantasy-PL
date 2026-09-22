from datetime import datetime, timezone
from pathlib import Path

import pytest

from fpl_engine.current import (
    CurrentInputError,
    CurrentPipelineConfig,
    _apply_goal_allocation_promotion_candidate,
    _build_goal_allocation_promotion_candidate,
)

from fpl_engine.models.events import (
    EventModels,
)

from fpl_engine.models.events.goal_allocation_v2 import (
    GoalAllocationEventModels,
)


class _FakeArtifact:

    source_season = "2025-26"
    matched_count = 1
    current_player_count = 1

    def evidence_proxy_by_player(
        self,
    ):

        return {
            "ply_test": 0.55,
        }


def _config(
    **kwargs,
):

    return CurrentPipelineConfig(
        canonical_database=Path(
            "scratch/test.duckdb"
        ),
        output_root=Path(
            "scratch/test-output"
        ),
        **kwargs,
    )


def test_goal_allocation_is_enabled_by_default():

    config = _config()

    assert (
        config.goal_allocation_proxy_enabled
        is True
    )

    assert (
        config.goal_allocation_source_season
        is None
    )


def test_disabled_builder_returns_before_filesystem_access():

    config = _config(
        goal_allocation_proxy_enabled=False,
    )

    result = (
        _build_goal_allocation_promotion_candidate(
            project_root=Path(
                "definitely-does-not-exist"
            ),
            config=config,
            players=[],
            prediction_timestamp=datetime(
                2026,
                9,
                12,
                tzinfo=timezone.utc,
            ),
        )
    )

    assert result is None


def test_disabled_event_boundary_is_identity():

    baseline = EventModels()

    result = (
        _apply_goal_allocation_promotion_candidate(
            baseline,
            None,
        )
    )

    assert result is baseline


def test_enabled_event_boundary_creates_challenger():

    result = (
        _apply_goal_allocation_promotion_candidate(
            EventModels(),
            _FakeArtifact(),
        )
    )

    assert isinstance(
        result,
        GoalAllocationEventModels,
    )

    assert dict(
        result.proxy_by_player
    ) == {
        "ply_test": 0.55,
    }


def test_enabled_event_boundary_rejects_unvalidated_runtime():

    class UnsupportedEventRuntime:
        pass


    with pytest.raises(
        CurrentInputError,
        match=(
            "validated only against "
            "EventModels V1"
        ),
    ):

        _apply_goal_allocation_promotion_candidate(
            UnsupportedEventRuntime(),
            _FakeArtifact(),
        )


def test_enabled_config_requires_prior_season_source():

    with pytest.raises(
        CurrentInputError,
        match=(
            "requires a prior STRICT season"
        ),
    ):

        _config(
            history_seasons=(),
            goal_allocation_proxy_enabled=True,
        )


def test_explicit_source_season_must_not_be_blank():

    with pytest.raises(
        CurrentInputError,
        match=(
            "must be a non-empty season string"
        ),
    ):

        _config(
            goal_allocation_source_season=" ",
        )
