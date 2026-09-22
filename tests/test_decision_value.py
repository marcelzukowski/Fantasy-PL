import pytest

from fpl_engine.decision import (
    DecisionError,
    PlayerDecisionProjection,
    build_player_value,
    rank_player_values,
)
from fpl_engine.decision.horizon import (
    HorizonValue,
)


def projection(
    player_id="p1",
    *,
    ev3=12.0,
    ev6=20.0,
    min3=220.0,
    min6=440.0,
):
    return PlayerDecisionProjection(
        player_id=player_id,
        current_gameweek=5,
        horizon_3=HorizonValue(
            player_id=player_id,
            first_gameweek=5,
            last_gameweek=7,
            raw_expected_points=13.0,
            weighted_expected_points=ev3,
            gameweeks=3,
        ),
        horizon_6=HorizonValue(
            player_id=player_id,
            first_gameweek=5,
            last_gameweek=10,
            raw_expected_points=23.0,
            weighted_expected_points=ev6,
            gameweeks=6,
        ),
        expected_minutes_next_3=min3,
        expected_minutes_next_6=min6,
        projection_confidence=0.7,
        projection_uncertainty=0.3,
    )


def metadata(
    player_id="p1",
    *,
    price=60,
    position="MID",
):
    return {
        "player_id": player_id,
        "display_name": "Player",
        "position": position,
        "current_price": price,
        "team_id": "team_1",
        "provider_team_id": "1",
    }


def test_price_is_converted_to_millions():
    player = build_player_value(
        projection(),
        metadata(
            price=65
        ),
    )

    assert player.price_m == 6.5


def test_value_is_ev_per_million():
    player = build_player_value(
        projection(
            ev3=13.0,
            ev6=26.0,
        ),
        metadata(
            price=65
        ),
    )

    assert (
        player.value_3
        == pytest.approx(2.0)
    )

    assert (
        player.value_6
        == pytest.approx(4.0)
    )


def test_positions_are_kept_separate():
    mid = build_player_value(
        projection("mid"),
        metadata(
            "mid",
            position="MID",
        ),
    )

    fwd = build_player_value(
        projection("fwd"),
        metadata(
            "fwd",
            position="FWD",
        ),
    )

    ranked = rank_player_values(
        [mid, fwd],
        position="MID",
    )

    assert len(ranked) == 1
    assert ranked[0].player_id == "mid"


def test_budget_filter():
    cheap = build_player_value(
        projection(
            "cheap",
            ev6=18.0,
        ),
        metadata(
            "cheap",
            price=60,
        ),
    )

    expensive = build_player_value(
        projection(
            "expensive",
            ev6=30.0,
        ),
        metadata(
            "expensive",
            price=100,
        ),
    )

    ranked = rank_player_values(
        [
            cheap,
            expensive,
        ],
        position="MID",
        max_price_m=8.0,
    )

    assert [
        row.player_id
        for row in ranked
    ] == [
        "cheap"
    ]


def test_value_ranking_can_beat_raw_ev():
    cheap = build_player_value(
        projection(
            "cheap",
            ev6=20.0,
        ),
        metadata(
            "cheap",
            price=50,
        ),
    )

    premium = build_player_value(
        projection(
            "premium",
            ev6=30.0,
        ),
        metadata(
            "premium",
            price=100,
        ),
    )

    ranked = rank_player_values(
        [
            cheap,
            premium,
        ],
        position="MID",
        metric="value6",
    )

    assert ranked[0].player_id == "cheap"


def test_minutes_filter():
    low_minutes = (
        build_player_value(
            projection(
                "low",
                min6=100.0,
            ),
            metadata(
                "low"
            ),
        )
    )

    regular = build_player_value(
        projection(
            "regular",
            min6=450.0,
        ),
        metadata(
            "regular"
        ),
    )

    ranked = rank_player_values(
        [
            low_minutes,
            regular,
        ],
        position="MID",
        metric="ev6",
        min_minutes=300.0,
    )

    assert [
        row.player_id
        for row in ranked
    ] == [
        "regular"
    ]


def test_invalid_position_rejected():
    with pytest.raises(
        DecisionError
    ):
        build_player_value(
            projection(),
            metadata(
                position="XYZ"
            ),
        )
