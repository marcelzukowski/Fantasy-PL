from fpl_engine.decision.captaincy_value import (
    best_captaincy_pair,
    effective_captain_bonus,
)


def test_effective_captain_bonus():

    value = effective_captain_bonus(
        captain_ev=7.0,
        vice_ev=5.0,
        captain_p_appearance=0.90,
    )

    assert abs(
        value - 7.5
    ) < 1e-9


def test_best_pair_prefers_high_captain_ev():

    result = best_captaincy_pair(
        player_ids=(
            "a",
            "b",
            "c",
        ),
        expected_points={
            "a": 7.0,
            "b": 5.0,
            "c": 8.0,
        },
        p_appearance={
            "a": 0.95,
            "b": 0.95,
            "c": 0.95,
        },
        positions={
            "a": "MID",
            "b": "FWD",
            "c": "GK",
        },
    )

    assert result.captain_id == "a"
    assert result.vice_id == "b"


def test_goalkeeper_not_in_default_pool():

    result = best_captaincy_pair(
        player_ids=(
            "gk",
            "mid",
            "fwd",
        ),
        expected_points={
            "gk": 10.0,
            "mid": 5.0,
            "fwd": 4.0,
        },
        p_appearance={
            "gk": 1.0,
            "mid": 1.0,
            "fwd": 1.0,
        },
        positions={
            "gk": "GK",
            "mid": "MID",
            "fwd": "FWD",
        },
    )

    assert result.captain_id == "mid"
    assert result.vice_id == "fwd"
