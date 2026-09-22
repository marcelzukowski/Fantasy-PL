import pytest

from fpl_engine.models.player_talent.goal_allocation import (
    GoalAllocationProxyConfig,
    fixture_goal_allocation_weight,
    predict_goal_allocation_proxy,
)


def test_proxy_reproduces_validated_alpha():

    result = predict_goal_allocation_proxy(
        player_id="haaland",
        position="FWD",
        source_season="2024-25",
        source_total_xg=21.90,
        source_minutes=2736.0,
    )

    frozen = (
        21.90 * 90.0
        + 0.35 * 600.0
    ) / (
        2736.0 + 600.0
    )

    expected = (
        0.35
        + 0.55 * (frozen - 0.35)
    )

    assert (
        result.frozen_total_xg_rate_per90
        == pytest.approx(frozen)
    )

    assert (
        result.goal_allocation_proxy_per90
        == pytest.approx(expected)
    )

    assert result.alpha == pytest.approx(0.55)


def test_proxy_semantics_are_explicit():

    result = predict_goal_allocation_proxy(
        player_id="p1",
        position="MID",
        source_season="2024-25",
        source_total_xg=10.0,
        source_minutes=2000.0,
    )

    assert (
        result.source_metric
        == "historical_total_xg_including_penalties"
    )

    assert (
        result.intended_use
        == "relative_team_goal_allocation_only"
    )


def test_missing_history_uses_position_prior():

    result = predict_goal_allocation_proxy(
        player_id="p1",
        position="FWD",
        source_season=None,
        source_total_xg=None,
        source_minutes=0.0,
    )

    assert (
        result.goal_allocation_proxy_per90
        == pytest.approx(0.35)
    )

    assert (
        result.used_historical_total_xg
        is False
    )


def test_invalid_alpha_rejected():

    with pytest.raises(ValueError):

        GoalAllocationProxyConfig(
            alpha=1.1
        )


def test_negative_total_xg_rejected():

    with pytest.raises(ValueError):

        predict_goal_allocation_proxy(
            player_id="p1",
            position="FWD",
            source_season="2024-25",
            source_total_xg=-1.0,
            source_minutes=1000.0,
        )


def test_fixture_bridge_preserves_legacy():

    value = fixture_goal_allocation_weight(
        goal_allocation_proxy_per90=None,
        legacy_raw_expected_npxg=0.314159,
        expected_minutes=45.0,
        opponent_defence_strength=2.0,
    )

    assert value == pytest.approx(
        0.314159
    )


def test_fixture_bridge_uses_proxy():

    value = fixture_goal_allocation_weight(
        goal_allocation_proxy_per90=0.80,
        legacy_raw_expected_npxg=0.10,
        expected_minutes=45.0,
        opponent_defence_strength=2.0,
    )

    assert value == pytest.approx(
        0.20
    )


def test_fixture_bridge_applies_role_multiplier():

    value = fixture_goal_allocation_weight(
        goal_allocation_proxy_per90=0.80,
        legacy_raw_expected_npxg=0.10,
        expected_minutes=45.0,
        opponent_defence_strength=2.0,
        goal_multiplier=1.5,
    )

    assert value == pytest.approx(
        0.30
    )
