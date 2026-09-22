import pytest

from fpl_engine.decision import (
    DecisionError,
    adapt_player_projection,
    rank_player_projections,
)


def sample_row(
    player_id="p1",
    *,
    multiplier=1.0,
):
    values = [
        2.109375,
        2.171875,
        2.25,
        2.265625,
        2.53125,
        2.0,
    ]

    values = [
        value * multiplier
        for value in values
    ]

    weighted_3 = (
        values[0]
        + values[1] * 0.95
        + values[2] * 0.90
    )

    weighted_6 = (
        values[0]
        + values[1] * 0.95
        + values[2] * 0.90
        + values[3] * 0.85
        + values[4] * 0.80
        + values[5] * 0.75
    )

    return {
        "player_id": player_id,
        "current_gameweek": 5,
        "ev_next_3": sum(
            values[:3]
        ),
        "ev_next_6": sum(
            values
        ),
        "weighted_ev_next_3": (
            weighted_3
        ),
        "weighted_ev_next_6": (
            weighted_6
        ),
        "expected_minutes_next_3": 155.0,
        "expected_minutes_next_6": 310.0,
        "projection_confidence": 0.70,
        "projection_uncertainty": 0.30,
        "gameweeks": [
            {
                "player_id": player_id,
                "target_gameweek": (
                    5 + index
                ),
                "expected_points": value,
            }
            for index, value in enumerate(
                values
            )
        ],
    }


def test_adapter_matches_pipeline_3gw_value():
    player = adapt_player_projection(
        sample_row()
    )

    assert (
        player.horizon_3
        .weighted_expected_points
        == pytest.approx(
            6.19765625
        )
    )


def test_adapter_matches_pipeline_6gw_value():
    player = adapt_player_projection(
        sample_row()
    )

    assert (
        player.horizon_6
        .weighted_expected_points
        == pytest.approx(
            11.6484375
        )
    )


def test_pipeline_mismatch_is_rejected():
    row = sample_row()

    row[
        "weighted_ev_next_3"
    ] += 1.0

    with pytest.raises(
        DecisionError
    ):
        adapt_player_projection(
            row
        )


def test_ranking_orders_by_selected_horizon():
    low = adapt_player_projection(
        sample_row(
            "low",
            multiplier=1.0,
        )
    )

    high = adapt_player_projection(
        sample_row(
            "high",
            multiplier=2.0,
        )
    )

    ranked = (
        rank_player_projections(
            [low, high],
            horizon=6,
        )
    )

    assert (
        ranked[0].player_id
        == "high"
    )
