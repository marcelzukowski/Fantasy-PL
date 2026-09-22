from __future__ import annotations

from types import (
    SimpleNamespace,
)

import pytest

from fpl_engine.decision.captaincy_v2 import (
    evaluate_squad_with_captaincy_v2,
)


def _squad():

    specs = (
        ("gk1", "GK"),
        ("gk2", "GK"),

        ("d1", "DEF"),
        ("d2", "DEF"),
        ("d3", "DEF"),
        ("d4", "DEF"),
        ("d5", "DEF"),

        ("m1", "MID"),
        ("m2", "MID"),
        ("m3", "MID"),
        ("m4", "MID"),
        ("m5", "MID"),

        ("f1", "FWD"),
        ("f2", "FWD"),
        ("f3", "FWD"),
    )

    return {
        player_id:
        SimpleNamespace(
            player_id=player_id,
            position=position,
        )
        for player_id, position
        in specs
    }


def _projection(
    player_id,
    values,
):

    gameweeks = tuple(
        SimpleNamespace(
            player_id=player_id,
            gameweek=gameweek,
            expected_points=float(
                points
            ),
        )
        for gameweek, points
        in values.items()
    )

    return SimpleNamespace(
        player_id=player_id,
        current_gameweek=4,
        gameweeks=gameweeks,
    )


def _projections(
    overrides=None,
):

    overrides = (
        overrides
        or {}
    )

    output = {}

    for player_id in _squad():

        values = {
            4: 2.0,
            5: 2.0,
            6: 2.0,
        }

        if player_id in overrides:

            values.update(
                overrides[
                    player_id
                ]
            )

        output[
            player_id
        ] = _projection(
            player_id,
            values,
        )

    return output


def _appearance(
    overrides=None,
):

    overrides = (
        overrides
        or {}
    )

    output = {}

    for player_id in _squad():

        output[
            player_id
        ] = {
            4: 0.95,
            5: 0.95,
            6: 0.95,
        }

    for player_id, rows in (
        overrides.items()
    ):

        output[
            player_id
        ].update(
            rows
        )

    return output


def test_exact_captain_vice_bonus():

    players = _squad()

    projections = _projections(
        {
            "m1": {
                4: 10.0,
            },
            "m2": {
                4: 8.0,
            },
        }
    )

    appearance = _appearance(
        {
            "m1": {
                4: 0.80,
            },
        }
    )

    result = (
        evaluate_squad_with_captaincy_v2(
            squad_player_ids=set(
                players
            ),
            players_by_id=players,
            projections_by_id=projections,
            appearance_by_player_gameweek=(
                appearance
            ),
            horizon=1,
        )
    )

    gw = result.gameweeks[0]

    assert (
        gw.captain_player_id
        == "m1"
    )

    assert (
        gw.vice_player_id
        == "m2"
    )

    assert (
        gw.captain_bonus_ev
        == pytest.approx(
            10.0
            + 0.20 * 8.0
        )
    )


def test_captain_and_vice_are_distinct_starters():

    players = _squad()

    projections = _projections(
        {
            "f1": {
                4: 8.0,
            },
            "m1": {
                4: 7.5,
            },
        }
    )

    result = (
        evaluate_squad_with_captaincy_v2(
            squad_player_ids=set(
                players
            ),
            players_by_id=players,
            projections_by_id=projections,
            appearance_by_player_gameweek=(
                _appearance()
            ),
            horizon=1,
        )
    )

    gw = result.gameweeks[0]

    assert (
        gw.captain_player_id
        != gw.vice_player_id
    )

    assert (
        gw.captain_player_id
        in gw.starting_xi_player_ids
    )

    assert (
        gw.vice_player_id
        in gw.starting_xi_player_ids
    )

    assert len(
        gw.starting_xi_player_ids
    ) == 11


def test_all_positions_are_captain_eligible():

    players = _squad()

    projections = _projections(
        {
            "gk1": {
                4: 12.0,
            },
            "m1": {
                4: 8.0,
            },
        }
    )

    result = (
        evaluate_squad_with_captaincy_v2(
            squad_player_ids=set(
                players
            ),
            players_by_id=players,
            projections_by_id=projections,
            appearance_by_player_gameweek=(
                _appearance()
            ),
            horizon=1,
        )
    )

    gw = result.gameweeks[0]

    assert (
        gw.captain_player_id
        == "gk1"
    )


def test_horizon_uses_existing_weights():

    players = _squad()

    projections = _projections(
        {
            "m1": {
                4: 10.0,
                5: 10.0,
                6: 10.0,
            },
            "m2": {
                4: 8.0,
                5: 8.0,
                6: 8.0,
            },
        }
    )

    appearance = _appearance(
        {
            "m1": {
                4: 0.80,
                5: 0.80,
                6: 0.80,
            },
        }
    )

    result = (
        evaluate_squad_with_captaincy_v2(
            squad_player_ids=set(
                players
            ),
            players_by_id=players,
            projections_by_id=projections,
            appearance_by_player_gameweek=(
                appearance
            ),
            horizon=3,
        )
    )

    per_gw_bonus = (
        10.0
        + 0.20 * 8.0
    )

    assert (
        result.weighted_captain_bonus_ev
        == pytest.approx(
            per_gw_bonus
            * (
                1.0
                + 0.95
                + 0.90
            )
        )
    )


def test_missing_appearance_is_not_guessed():

    players = _squad()

    appearance = _appearance()

    del appearance[
        "m1"
    ][4]

    with pytest.raises(
        Exception,
        match="appearance",
    ):

        evaluate_squad_with_captaincy_v2(
            squad_player_ids=set(
                players
            ),
            players_by_id=players,
            projections_by_id=(
                _projections()
            ),
            appearance_by_player_gameweek=(
                appearance
            ),
            horizon=1,
        )
