import pytest

from fpl_engine.decision.horizon import (
    DecisionError,
    GameweekProjection,
    compare_transfer,
    horizon_value,
)


def projections(
    player_id,
    values,
    *,
    start_gw=5,
):
    return [
        GameweekProjection(
            player_id=player_id,
            gameweek=start_gw + index,
            expected_points=value,
        )
        for index, value in enumerate(
            values
        )
    ]


def test_horizon_value_uses_discount_weights():
    value = horizon_value(
        projections(
            "p1",
            [
                5.0,
                5.0,
                5.0,
            ],
        ),
        first_gameweek=5,
        weights={
            0: 1.0,
            1: 0.5,
            2: 0.25,
        },
    )

    assert (
        value.raw_expected_points
        == pytest.approx(15.0)
    )

    assert (
        value.weighted_expected_points
        == pytest.approx(8.75)
    )


def test_missing_future_projection_is_zero():
    value = horizon_value(
        projections(
            "p1",
            [
                5.0,
                4.0,
            ],
        ),
        first_gameweek=5,
        weights={
            0: 1.0,
            1: 1.0,
            2: 1.0,
        },
    )

    assert (
        value.raw_expected_points
        == pytest.approx(9.0)
    )


def test_transfer_gain_without_hit():
    sell = horizon_value(
        projections(
            "sell",
            [
                4.0,
                4.0,
                4.0,
            ],
        ),
        first_gameweek=5,
        weights={
            0: 1.0,
            1: 1.0,
            2: 1.0,
        },
    )

    buy = horizon_value(
        projections(
            "buy",
            [
                6.0,
                5.0,
                5.0,
            ],
        ),
        first_gameweek=5,
        weights={
            0: 1.0,
            1: 1.0,
            2: 1.0,
        },
    )

    result = compare_transfer(
        sell,
        buy,
    )

    assert result.gross_gain == 4.0
    assert result.net_gain == 4.0


def test_transfer_hit_is_subtracted():
    sell = horizon_value(
        projections(
            "sell",
            [4.0],
        ),
        first_gameweek=5,
        weights={
            0: 1.0,
        },
    )

    buy = horizon_value(
        projections(
            "buy",
            [7.0],
        ),
        first_gameweek=5,
        weights={
            0: 1.0,
        },
    )

    result = compare_transfer(
        sell,
        buy,
        hit_cost=4.0,
    )

    assert result.gross_gain == 3.0
    assert result.net_gain == -1.0


def test_mixed_players_are_rejected():
    rows = [
        GameweekProjection(
            player_id="p1",
            gameweek=5,
            expected_points=5.0,
        ),
        GameweekProjection(
            player_id="p2",
            gameweek=6,
            expected_points=5.0,
        ),
    ]

    with pytest.raises(
        DecisionError
    ):
        horizon_value(
            rows,
            first_gameweek=5,
        )
