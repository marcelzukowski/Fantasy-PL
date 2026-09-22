from datetime import datetime, timezone

import pytest

from fpl_engine.models.player_talent.goal_allocation_history import (
    GoalAllocationHistoryRow,
    GoalAllocationPlayerRef,
    GoalAllocationProxyArtifact,
)


def _row(
    player_id,
    *,
    used,
    proxy,
):

    return GoalAllocationHistoryRow(
        player_id=player_id,
        display_name=player_id,
        position="FWD",
        source_season=(
            "2025-26"
            if used
            else None
        ),
        source_provider_player_ids=(
            (1,)
            if used
            else ()
        ),
        source_total_xg=(
            10.0
            if used
            else None
        ),
        source_minutes=(
            2000.0
            if used
            else 0.0
        ),
        position_prior_per90=0.35,
        frozen_total_xg_rate_per90=(
            proxy
        ),
        goal_allocation_proxy_per90=(
            proxy
        ),
        alpha=0.55,
        used_historical_total_xg=(
            used
        ),
        identity_method=(
            "official_fpl_player_identity_key"
            "_to_canonical_player_id"
        ),
        source_metric=(
            "historical_total_xg_including_penalties"
        ),
        intended_use=(
            "relative_team_goal_allocation_only"
        ),
        model_version=(
            "goal_allocation_proxy_v1"
        ),
        feature_version=(
            "goal_allocation_proxy_total_xg_v1"
        ),
    )


def test_artifact_runtime_mapping_contains_only_evidence_rows():

    artifact = GoalAllocationProxyArtifact(
        artifact_version=(
            "goal_allocation_proxy_canonical_v1"
        ),
        source_season="2025-26",
        prediction_timestamp=datetime(
            2026,
            9,
            12,
            tzinfo=timezone.utc,
        ),
        alpha=0.55,
        prior_minutes=600.0,
        source_repository_ref="abc",
        source_checksum="def",
        current_player_count=2,
        strict_identity_player_count=2,
        historical_player_count=1,
        matched_count=1,
        position_mismatch_count=0,
        no_history_count=1,
        unresolved_vaastav_rows=0,
        rows=(
            _row(
                "p1",
                used=True,
                proxy=0.55,
            ),
            _row(
                "p2",
                used=False,
                proxy=0.35,
            ),
        ),
    )

    mapping = (
        artifact
        .evidence_proxy_by_player()
    )

    assert dict(
        mapping
    ) == {
        "p1": 0.55,
    }


    with pytest.raises(
        TypeError
    ):

        mapping[
            "p1"
        ] = 0.20


def test_artifact_match_rate():

    artifact = GoalAllocationProxyArtifact(
        artifact_version="v",
        source_season="2025-26",
        prediction_timestamp=datetime(
            2026,
            9,
            12,
            tzinfo=timezone.utc,
        ),
        alpha=0.55,
        prior_minutes=600.0,
        source_repository_ref="a",
        source_checksum="b",
        current_player_count=4,
        strict_identity_player_count=4,
        historical_player_count=3,
        matched_count=3,
        position_mismatch_count=0,
        no_history_count=1,
        unresolved_vaastav_rows=0,
        rows=(),
    )

    assert artifact.match_rate == pytest.approx(
        0.75
    )


def test_player_ref_is_frozen():

    row = GoalAllocationPlayerRef(
        player_id="p1",
        position="MID",
        display_name="Player",
    )

    with pytest.raises(
        Exception
    ):

        row.position = "FWD"
