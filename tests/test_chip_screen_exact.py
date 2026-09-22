from types import SimpleNamespace

import pytest

from fpl_engine.decision.chip_screen_exact import (
    ExactChipScreenError,
    evaluate_exact_chip_squad,
)


def _data(
    gameweeks=(5,),
):

    positions = {
        "gk1": "GK",
        "gk2": "GK",

        "d1": "DEF",
        "d2": "DEF",
        "d3": "DEF",
        "d4": "DEF",
        "d5": "DEF",

        "m1": "MID",
        "m2": "MID",
        "m3": "MID",
        "m4": "MID",
        "m5": "MID",

        "f1": "FWD",
        "f2": "FWD",
        "f3": "FWD",
    }


    squad = tuple(
        positions
    )


    base = {
        "gk1": 10.0,
        "gk2": 2.0,

        "d1": 9.0,
        "d2": 5.0,
        "d3": 4.8,
        "d4": 4.0,
        "d5": 2.0,

        "m1": 7.0,
        "m2": 6.5,
        "m3": 6.0,
        "m4": 5.5,
        "m5": 3.0,

        "f1": 8.0,
        "f2": 6.0,
        "f3": 3.5,
    }


    projections = {}


    papp = {}


    for player_id in squad:

        rows = []

        for offset, gameweek in enumerate(
            gameweeks
        ):

            rows.append(
                SimpleNamespace(
                    gameweek=gameweek,

                    expected_points=(
                        base[
                            player_id
                        ]
                        + 0.1
                        * offset
                    ),
                )
            )


            papp[
                (
                    player_id,
                    gameweek,
                )
            ] = 0.95


        projections[
            player_id
        ] = SimpleNamespace(
            player_id=player_id,
            gameweeks=tuple(
                rows
            ),
        )


    return (
        squad,
        positions,
        projections,
        papp,
    )


def test_exact_chip_regular_uses_all_positions_for_captaincy():

    (
        squad,
        positions,
        projections,
        papp,
    ) = _data()


    result = evaluate_exact_chip_squad(
        squad_player_ids=squad,

        positions=positions,

        projections_by_id=(
            projections
        ),

        p_appearance_by_gameweek=(
            papp
        ),

        first_gameweek=5,

        horizon=1,

        weights=(1.0,),
    )


    week = result.gameweeks[
        0
    ]


    assert week.captain_id == "gk1"

    assert week.vice_id == "d1"

    assert len(
        week.starter_ids
    ) == 11

    assert week.captain_id in (
        week.starter_ids
    )

    assert week.vice_id in (
        week.starter_ids
    )

    assert week.captain_id != (
        week.vice_id
    )


def test_exact_chip_triple_captain_doubles_effective_bonus():

    (
        squad,
        positions,
        projections,
        papp,
    ) = _data()


    normal = evaluate_exact_chip_squad(
        squad_player_ids=squad,

        positions=positions,

        projections_by_id=(
            projections
        ),

        p_appearance_by_gameweek=(
            papp
        ),

        first_gameweek=5,

        horizon=1,

        weights=(1.0,),

        chip="normal",
    )


    triple = evaluate_exact_chip_squad(
        squad_player_ids=squad,

        positions=positions,

        projections_by_id=(
            projections
        ),

        p_appearance_by_gameweek=(
            papp
        ),

        first_gameweek=5,

        horizon=1,

        weights=(1.0,),

        chip="triple_captain",
    )


    assert (
        triple.gameweeks[
            0
        ].captain_bonus_ev
        == pytest.approx(
            2.0
            * normal.gameweeks[
                0
            ].captain_bonus_ev
        )
    )


def test_exact_chip_bench_boost_counts_all_15():

    (
        squad,
        positions,
        projections,
        papp,
    ) = _data()


    result = evaluate_exact_chip_squad(
        squad_player_ids=squad,

        positions=positions,

        projections_by_id=(
            projections
        ),

        p_appearance_by_gameweek=(
            papp
        ),

        first_gameweek=5,

        horizon=1,

        weights=(1.0,),

        chip="bench_boost",
    )


    week = result.gameweeks[
        0
    ]


    all_player_ev = sum(
        projection.gameweeks[
            0
        ].expected_points
        for projection
        in projections.values()
    )


    assert (
        week.expected_autosub_ev
        == pytest.approx(
            0.0
        )
    )

    assert (
        week.base_xi_ev
        + week.bench_boost_bench_ev
        == pytest.approx(
            all_player_ev
        )
    )

    assert week.total_ev == pytest.approx(
        all_player_ev
        + week.captain_bonus_ev
    )


def test_exact_chip_horizon_weights_are_applied():

    (
        squad,
        positions,
        projections,
        papp,
    ) = _data(
        gameweeks=(
            5,
            6,
        )
    )


    result = evaluate_exact_chip_squad(
        squad_player_ids=squad,

        positions=positions,

        projections_by_id=(
            projections
        ),

        p_appearance_by_gameweek=(
            papp
        ),

        first_gameweek=5,

        horizon=2,

        weights=(
            1.0,
            0.5,
        ),
    )


    expected = (
        result.gameweeks[
            0
        ].total_ev
        + 0.5
        * result.gameweeks[
            1
        ].total_ev
    )


    assert result.weighted_total_ev == (
        pytest.approx(
            expected
        )
    )


def test_exact_chip_rejects_invalid_squad():

    (
        squad,
        positions,
        projections,
        papp,
    ) = _data()


    with pytest.raises(
        ExactChipScreenError,
        match="15-player",
    ):

        evaluate_exact_chip_squad(
            squad_player_ids=(
                squad[:-1]
            ),

            positions=positions,

            projections_by_id=(
                projections
            ),

            p_appearance_by_gameweek=(
                papp
            ),

            first_gameweek=5,

            horizon=1,

            weights=(1.0,),
        )
