from fpl_engine.decision import (
    GameweekProjection,
    HorizonValue,
    PlayerDecisionProjection,
    PlayerValue,
    SquadState,
    optimize_multi_gameweek_transfers,
    optimize_multi_gameweek_transfers_with_captaincy,
)


def make_value(
    player_id,
    position,
    *,
    team,
    scores,
):
    ev3 = sum(
        scores[:3]
    )

    return (
        PlayerValue(
            player_id=player_id,
            name=player_id,
            position=position,
            team_id=team,
            provider_team_id=None,
            price_tenths=50,
            price_m=5.0,
            ev_3=ev3,
            ev_6=ev3,
            value_3=ev3 / 5.0,
            value_6=ev3 / 5.0,
            minutes_3=270,
            minutes_6=270,
            confidence=0.7,
            uncertainty=0.3,
        ),
        PlayerDecisionProjection(
            player_id=player_id,
            current_gameweek=5,
            horizon_3=HorizonValue(
                player_id=player_id,
                first_gameweek=5,
                last_gameweek=7,
                raw_expected_points=ev3,
                weighted_expected_points=ev3,
                gameweeks=3,
            ),
            horizon_6=HorizonValue(
                player_id=player_id,
                first_gameweek=5,
                last_gameweek=10,
                raw_expected_points=ev3,
                weighted_expected_points=ev3,
                gameweeks=6,
            ),
            expected_minutes_next_3=270,
            expected_minutes_next_6=270,
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
        ),
    )


def test_dynamic_optimizer_rotates_starting_xi():
    specs = [
        ("gk1", "GK", [10, 10, 10]),
        ("gk2", "GK", [0, 0, 0]),

        ("d1", "DEF", [10, 10, 10]),
        ("d2", "DEF", [10, 10, 10]),
        ("d3", "DEF", [20, 0, 0]),
        ("d4", "DEF", [0, 20, 0]),
        ("d5", "DEF", [0, 0, 20]),

        ("m1", "MID", [10, 10, 10]),
        ("m2", "MID", [10, 10, 10]),
        ("m3", "MID", [10, 10, 10]),
        ("m4", "MID", [10, 10, 10]),
        ("m5", "MID", [0, 0, 0]),

        ("f1", "FWD", [10, 10, 10]),
        ("f2", "FWD", [10, 10, 10]),
        ("f3", "FWD", [10, 10, 10]),
    ]

    values = []
    projections = {}

    for index, (
        player_id,
        position,
        scores,
    ) in enumerate(specs):

        value, projection = (
            make_value(
                player_id,
                position,
                team=f"team_{index}",
                scores=scores,
            )
        )

        values.append(
            value
        )

        projections[
            player_id
        ] = projection

    squad = frozenset(
        row.player_id
        for row in values
    )

    state = SquadState(
        player_ids=squad,
        bank_tenths=0,
        selling_prices_tenths={
            player_id: 50
            for player_id
            in squad
        },
        team_counts={
            row.team_id: 1
            for row in values
        },
    )

    result = (
        optimize_multi_gameweek_transfers(
            players=values,
            projections_by_id=projections,
            state=state,
            horizon=3,
            exact_transfers=0,
        )
    )

    assert result is not None

    lineups = {
        gw: set(players)
        for gw, players
        in result.starting_xi_by_gameweek
    }

    assert "d3" in lineups[5]
    assert "d4" in lineups[6]
    assert "d5" in lineups[7]

    assert result.gain == 0.0


def test_dynamic_optimizer_respects_transfer_count():
    specs = [
        ("gk1", "GK", [5, 5, 5]),
        ("gk2", "GK", [0, 0, 0]),

        ("d1", "DEF", [5, 5, 5]),
        ("d2", "DEF", [5, 5, 5]),
        ("d3", "DEF", [5, 5, 5]),
        ("d4", "DEF", [1, 1, 1]),
        ("d5", "DEF", [1, 1, 1]),

        ("m1", "MID", [5, 5, 5]),
        ("m2", "MID", [5, 5, 5]),
        ("m3", "MID", [5, 5, 5]),
        ("m4", "MID", [5, 5, 5]),
        ("bad", "MID", [1, 1, 1]),

        ("f1", "FWD", [5, 5, 5]),
        ("f2", "FWD", [5, 5, 5]),
        ("f3", "FWD", [5, 5, 5]),

        ("great", "MID", [10, 10, 10]),
    ]

    values = []
    projections = {}

    for index, (
        player_id,
        position,
        scores,
    ) in enumerate(specs):

        value, projection = (
            make_value(
                player_id,
                position,
                team=f"team_{index}",
                scores=scores,
            )
        )

        values.append(value)
        projections[
            player_id
        ] = projection

    squad = frozenset(
        row.player_id
        for row in values
        if row.player_id
        != "great"
    )

    state = SquadState(
        player_ids=squad,
        bank_tenths=0,
        selling_prices_tenths={
            player_id: 50
            for player_id
            in squad
        },
        team_counts={
            row.team_id: 1
            for row in values
            if row.player_id
            in squad
        },
    )

    result = (
        optimize_multi_gameweek_transfers(
            players=values,
            projections_by_id=projections,
            state=state,
            horizon=3,
            exact_transfers=1,
        )
    )

    assert result is not None
    assert result.transfer_count == 1
    assert result.incoming_player_ids == (
        "great",
    )

# typo guard: write clean file



def test_captaincy_optimizer_selects_one_captain_per_gw():
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

    values = []
    projections = {}

    for index, (
        player_id,
        position,
        scores,
    ) in enumerate(specs):

        value, projection = (
            make_value(
                player_id,
                position,
                team=f"cap_team_{index}",
                scores=scores,
            )
        )

        values.append(value)

        projections[
            player_id
        ] = projection

    squad = frozenset(
        row.player_id
        for row in values
    )

    state = SquadState(
        player_ids=squad,
        bank_tenths=0,
        selling_prices_tenths={
            player_id: 50
            for player_id
            in squad
        },
        team_counts={
            row.team_id: 1
            for row in values
        },
    )

    result = (
        optimize_multi_gameweek_transfers_with_captaincy(
            players=values,
            projections_by_id=projections,
            state=state,
            horizon=3,
            exact_transfers=0,
        )
    )

    assert result is not None

    assert len(
        result.captain_by_gameweek
    ) == 3

    lineups = {
        gw: set(player_ids)
        for gw, player_ids
        in result.starting_xi_by_gameweek
    }

    for gw, captain in (
        result.captain_by_gameweek
    ):
        assert captain in lineups[gw]

    assert (
        result.final_weighted_total_ev
        ==
        result.final_weighted_xi_ev
        + result.final_weighted_captain_bonus_ev
    )


def test_captaincy_optimizer_changes_captain_by_fixture():
    specs = [
        ("gk1", "GK", [5, 5, 5]),
        ("gk2", "GK", [1, 1, 1]),

        ("d1", "DEF", [4, 4, 4]),
        ("d2", "DEF", [4, 4, 4]),
        ("d3", "DEF", [4, 4, 4]),
        ("d4", "DEF", [3, 3, 3]),
        ("d5", "DEF", [2, 2, 2]),

        ("m1", "MID", [12, 5, 5]),
        ("m2", "MID", [5, 13, 5]),
        ("m3", "MID", [5, 5, 14]),
        ("m4", "MID", [5, 5, 5]),
        ("m5", "MID", [2, 2, 2]),

        ("f1", "FWD", [8, 8, 8]),
        ("f2", "FWD", [6, 6, 6]),
        ("f3", "FWD", [3, 3, 3]),
    ]

    values = []
    projections = {}

    for index, (
        player_id,
        position,
        scores,
    ) in enumerate(specs):

        value, projection = (
            make_value(
                player_id,
                position,
                team=f"fixture_team_{index}",
                scores=scores,
            )
        )

        values.append(value)

        projections[
            player_id
        ] = projection

    squad = frozenset(
        row.player_id
        for row in values
    )

    state = SquadState(
        player_ids=squad,
        bank_tenths=0,
        selling_prices_tenths={
            player_id: 50
            for player_id
            in squad
        },
        team_counts={
            row.team_id: 1
            for row in values
        },
    )

    result = (
        optimize_multi_gameweek_transfers_with_captaincy(
            players=values,
            projections_by_id=projections,
            state=state,
            horizon=3,
            exact_transfers=0,
        )
    )

    assert result is not None

    captains = [
        player_id
        for _, player_id
        in result.captain_by_gameweek
    ]

    assert captains == [
        "m1",
        "m2",
        "m3",
    ]
