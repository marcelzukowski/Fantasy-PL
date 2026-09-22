from __future__ import annotations

import pytest

from fpl_engine.decision.appearance import (
    build_gameweek_appearance,
    gameweek_appearance,
)

from fpl_engine.decision.horizon import (
    DecisionError,
)


PLAYER = "player_1"


def projection(
    fixture_ids,
    *,
    gameweek=4,
):
    return {
        "player_id": PLAYER,
        "gameweeks": [
            {
                "target_gameweek": gameweek,
                "fixture_ids": list(
                    fixture_ids
                ),
            }
        ],
    }


def minute(
    fixture_id,
    probability,
):
    return {
        "player_id": PLAYER,
        "fixture_id": fixture_id,
        "p_appearance": probability,
    }


def test_single_fixture_uses_fixture_probability():

    result = build_gameweek_appearance(
        projection_rows=[
            projection(
                ["fixture_1"]
            )
        ],
        minutes_rows=[
            minute(
                "fixture_1",
                0.82,
            )
        ],
    )

    assert (
        result[PLAYER][4]
        == pytest.approx(
            0.82
        )
    )


def test_double_gameweek_uses_at_least_once_probability():

    result = build_gameweek_appearance(
        projection_rows=[
            projection(
                [
                    "fixture_1",
                    "fixture_2",
                ]
            )
        ],
        minutes_rows=[
            minute(
                "fixture_1",
                0.80,
            ),
            minute(
                "fixture_2",
                0.70,
            ),
        ],
    )

    assert (
        result[PLAYER][4]
        == pytest.approx(
            1.0
            - (
                (1.0 - 0.80)
                * (1.0 - 0.70)
            )
        )
    )

    assert (
        result[PLAYER][4]
        == pytest.approx(
            0.94
        )
    )


def test_blank_gameweek_is_zero():

    result = build_gameweek_appearance(
        projection_rows=[
            projection([])
        ],
        minutes_rows=[],
    )

    assert (
        result[PLAYER][4]
        == 0.0
    )


def test_missing_fixture_minutes_is_error():

    with pytest.raises(
        DecisionError,
        match="missing minutes",
    ):

        build_gameweek_appearance(
            projection_rows=[
                projection(
                    [
                        "fixture_1",
                        "fixture_2",
                    ]
                )
            ],
            minutes_rows=[
                minute(
                    "fixture_1",
                    0.80,
                )
            ],
        )


def test_duplicate_minutes_row_is_error():

    with pytest.raises(
        DecisionError,
        match="duplicate minutes",
    ):

        build_gameweek_appearance(
            projection_rows=[
                projection(
                    ["fixture_1"]
                )
            ],
            minutes_rows=[
                minute(
                    "fixture_1",
                    0.80,
                ),
                minute(
                    "fixture_1",
                    0.80,
                ),
            ],
        )


def test_accessor_never_guesses_missing_probability():

    mapping = {
        PLAYER: {
            4: 0.91,
        }
    }

    assert gameweek_appearance(
        mapping,
        player_id=PLAYER,
        gameweek=4,
    ) == pytest.approx(
        0.91
    )

    with pytest.raises(
        DecisionError,
        match="GW5",
    ):

        gameweek_appearance(
            mapping,
            player_id=PLAYER,
            gameweek=5,
        )
