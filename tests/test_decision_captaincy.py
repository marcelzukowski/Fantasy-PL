from fpl_engine.decision import (
    GameweekProjection,
    HorizonValue,
    PlayerDecisionProjection,
    PlayerValue,
    evaluate_squad_with_captaincy,
)


def make_player(
    player_id,
    position,
    scores,
):
    ev = sum(scores)

    value = PlayerValue(
        player_id=player_id,
        name=player_id,
        position=position,
        team_id=f"team_{player_id}",
        provider_team_id=None,
        price_tenths=50,
        price_m=5.0,
        ev_3=ev,
        ev_6=ev,
        value_3=ev / 5,
        value_6=ev / 5,
        minutes_3=270,
        minutes_6=540,
        confidence=0.7,
        uncertainty=0.3,
    )

    projection = (
        PlayerDecisionProjection(
            player_id=player_id,
            current_gameweek=5,
            horizon_3=HorizonValue(
                player_id=player_id,
                first_gameweek=5,
                last_gameweek=7,
                raw_expected_points=ev,
                weighted_expected_points=ev,
                gameweeks=3,
            ),
            horizon_6=HorizonValue(
                player_id=player_id,
                first_gameweek=5,
                last_gameweek=10,
                raw_expected_points=ev,
                weighted_expected_points=ev,
                gameweeks=6,
            ),
            expected_minutes_next_3=270,
            expected_minutes_next_6=540,
            projection_confidence=0.7,
            projection_uncertainty=0.3,
            gameweeks=tuple(
                GameweekProjection(
                    player_id=player_id,
                    gameweek=5 + index,
                    expected_points=score,
                )
                for index, score
                in enumerate(scores)
            ),
        )
    )

    return value, projection


def build_squad():
    specs = [
        ("gk1", "GK", [5, 5, 5]),
        ("gk2", "GK", [1, 1, 1]),

        ("d1", "DEF", [4, 4, 4]),
        ("d2", "DEF", [4, 4, 4]),
        ("d3", "DEF", [4, 4, 4]),
        ("d4", "DEF", [3, 3, 3]),
        ("d5", "DEF", [2, 2, 2]),

        ("m1", "MID", [10, 5, 5]),
        ("m2", "MID", [5, 11, 5]),
        ("m3", "MID", [5, 5, 12]),
        ("m4", "MID", [5, 5, 5]),
        ("m5", "MID", [2, 2, 2]),

        ("f1", "FWD", [8, 8, 8]),
        ("f2", "FWD", [6, 6, 6]),
        ("f3", "FWD", [3, 3, 3]),
    ]

    values = {}
    projections = {}

    for player_id, position, scores in specs:
        value, projection = make_player(
            player_id,
            position,
            scores,
        )

        values[player_id] = value
        projections[player_id] = projection

    return values, projections


def test_captain_changes_by_gameweek():
    values, projections = build_squad()

    result = evaluate_squad_with_captaincy(
        squad_player_ids=frozenset(
            values
        ),
        players_by_id=values,
        projections_by_id=projections,
        horizon=3,
    )

    captains = [
        row.captain_player_id
        for row in result.gameweeks
    ]

    assert captains == [
        "m1",
        "m2",
        "m3",
    ]


def test_captain_is_always_a_starter():
    values, projections = build_squad()

    result = evaluate_squad_with_captaincy(
        squad_player_ids=frozenset(
            values
        ),
        players_by_id=values,
        projections_by_id=projections,
        horizon=3,
    )

    for row in result.gameweeks:
        assert (
            row.captain_player_id
            in row.starting_xi_player_ids
        )


def test_captain_bonus_is_added_once():
    values, projections = build_squad()

    result = evaluate_squad_with_captaincy(
        squad_player_ids=frozenset(
            values
        ),
        players_by_id=values,
        projections_by_id=projections,
        horizon=3,
    )

    assert (
        result.weighted_total_ev
        ==
        result.weighted_xi_ev
        + result.weighted_captain_bonus_ev
    )
