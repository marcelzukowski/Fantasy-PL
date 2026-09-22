import pytest

from fpl_engine.decision.availability_adapter import (
    AvailabilityError,
    build_gameweek_availability,
)


def projection(
    fixture_ids,
):
    return [
        {
            "player_id": "p1",
            "gameweeks": [
                {
                    "target_gameweek": 4,
                    "fixture_ids": fixture_ids,
                }
            ],
        }
    ]


def test_single_fixture_availability():

    result = build_gameweek_availability(
        projection(["f1"]),
        [
            {
                "player_id": "p1",
                "fixture_id": "f1",
                "expected_minutes": 72.0,
                "p_appearance": 0.8,
                "p_start": 0.7,
            }
        ],
    )[("p1", 4)]

    assert result.expected_minutes == 72.0
    assert result.p_appearance == pytest.approx(
        0.8
    )
    assert result.p_start == pytest.approx(
        0.7
    )
    assert result.p_zero_minutes == pytest.approx(
        0.2
    )


def test_double_gameweek_uses_any_fixture_probability():

    result = build_gameweek_availability(
        projection(
            [
                "f1",
                "f2",
            ]
        ),
        [
            {
                "player_id": "p1",
                "fixture_id": "f1",
                "expected_minutes": 60.0,
                "p_appearance": 0.8,
                "p_start": 0.5,
            },
            {
                "player_id": "p1",
                "fixture_id": "f2",
                "expected_minutes": 50.0,
                "p_appearance": 0.6,
                "p_start": 0.3,
            },
        ],
    )[("p1", 4)]

    assert result.expected_minutes == 110.0

    assert result.p_appearance == pytest.approx(
        0.92
    )

    assert result.p_zero_minutes == pytest.approx(
        0.08
    )

    assert result.p_start == pytest.approx(
        0.65
    )


def test_blank_gameweek_is_zero_availability():

    result = build_gameweek_availability(
        projection([]),
        [],
    )[("p1", 4)]

    assert result.expected_minutes == 0.0
    assert result.p_appearance == 0.0
    assert result.p_start == 0.0
    assert result.p_zero_minutes == 1.0


def test_missing_fixture_is_rejected():

    with pytest.raises(
        AvailabilityError
    ):
        build_gameweek_availability(
            projection(["f1"]),
            [],
        )
