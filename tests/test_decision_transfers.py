import pytest

from fpl_engine.decision import (
    DecisionError,
    PlayerValue,
    SquadState,
    rank_transfer_options,
    single_transfer_options,
)


def player(
    player_id,
    *,
    team,
    position="MID",
    price=70,
    ev3=10.0,
    ev6=18.0,
):
    return PlayerValue(
        player_id=player_id,
        name=player_id,
        position=position,
        team_id=team,
        provider_team_id=None,
        price_tenths=price,
        price_m=price / 10.0,
        ev_3=ev3,
        ev_6=ev6,
        value_3=(
            ev3 / (price / 10.0)
        ),
        value_6=(
            ev6 / (price / 10.0)
        ),
        minutes_3=220.0,
        minutes_6=440.0,
        confidence=0.7,
        uncertainty=0.3,
    )


def state(
    *,
    bank=10,
):
    return SquadState(
        player_ids=frozenset(
            {
                "sell",
                "mate1",
                "mate2",
            }
        ),
        bank_tenths=bank,
        selling_prices_tenths={
            "sell": 70,
            "mate1": 50,
            "mate2": 50,
        },
        team_counts={
            "team_a": 1,
            "team_b": 2,
        },
    )


def base_players():
    return [
        player(
            "sell",
            team="team_a",
            price=75,
            ev3=10.0,
            ev6=18.0,
        ),
        player(
            "mate1",
            team="team_b",
            position="DEF",
            price=50,
        ),
        player(
            "mate2",
            team="team_b",
            position="GK",
            price=50,
        ),
        player(
            "buy",
            team="team_c",
            price=80,
            ev3=13.0,
            ev6=24.0,
        ),
    ]


def test_same_position_replacement():
    options = single_transfer_options(
        sell_player_id="sell",
        players=base_players(),
        state=state(),
    )

    assert [
        row.buy_player_id
        for row in options
    ] == [
        "buy"
    ]


def test_budget_uses_actual_selling_price():
    players = base_players()

    players.append(
        player(
            "too_expensive",
            team="team_d",
            price=81,
            ev6=30.0,
        )
    )

    options = single_transfer_options(
        sell_player_id="sell",
        players=players,
        state=state(
            bank=10
        ),
    )

    ids = {
        row.buy_player_id
        for row in options
    }

    # Selling price = 7.0,
    # bank = 1.0,
    # max buy = 8.0.
    assert "buy" in ids
    assert "too_expensive" not in ids


def test_current_market_price_of_seller_not_used():
    options = single_transfer_options(
        sell_player_id="sell",
        players=base_players(),
        state=state(
            bank=10
        ),
    )

    option = options[0]

    # Seller current market price is 7.5,
    # but actual selling price in state is 7.0.
    assert option.sell_price_tenths == 70
    assert option.buy_price_tenths == 80
    assert option.bank_after_tenths == 0


def test_existing_squad_player_not_candidate():
    players = base_players()

    players.append(
        player(
            "mate1",
            team="team_b",
            position="MID",
            price=50,
            ev6=99.0,
        )
    )

    options = single_transfer_options(
        sell_player_id="sell",
        players=players,
        state=state(),
    )

    assert all(
        row.buy_player_id != "mate1"
        for row in options
    )


def test_club_limit_is_enforced():
    players = base_players()

    players.append(
        player(
            "third_team_b",
            team="team_b",
            price=75,
            ev6=40.0,
        )
    )

    custom_state = SquadState(
        player_ids=frozenset(
            {
                "sell",
                "mate1",
                "mate2",
                "b3",
            }
        ),
        bank_tenths=10,
        selling_prices_tenths={
            "sell": 70,
            "mate1": 50,
            "mate2": 50,
            "b3": 50,
        },
        team_counts={
            "team_a": 1,
            "team_b": 3,
        },
    )

    options = single_transfer_options(
        sell_player_id="sell",
        players=players,
        state=custom_state,
    )

    assert all(
        row.buy_player_id
        != "third_team_b"
        for row in options
    )


def test_selling_from_same_team_frees_slot():
    players = [
        player(
            "sell",
            team="team_b",
            price=70,
            ev6=18.0,
        ),
        player(
            "mate1",
            team="team_b",
            position="DEF",
        ),
        player(
            "mate2",
            team="team_b",
            position="GK",
        ),
        player(
            "replacement",
            team="team_b",
            price=70,
            ev6=25.0,
        ),
    ]

    custom_state = SquadState(
        player_ids=frozenset(
            {
                "sell",
                "mate1",
                "mate2",
            }
        ),
        bank_tenths=0,
        selling_prices_tenths={
            "sell": 70,
            "mate1": 50,
            "mate2": 50,
        },
        team_counts={
            "team_b": 3,
        },
    )

    options = single_transfer_options(
        sell_player_id="sell",
        players=players,
        state=custom_state,
    )

    assert (
        options[0].buy_player_id
        == "replacement"
    )


def test_hit_is_subtracted_from_gain():
    options = single_transfer_options(
        sell_player_id="sell",
        players=base_players(),
        state=state(),
        hit_cost=4.0,
    )

    option = options[0]

    assert (
        option.gross_gain_6
        == pytest.approx(6.0)
    )

    assert (
        option.net_gain_6
        == pytest.approx(2.0)
    )


def test_ranking_prefers_larger_net_gain():
    players = base_players()

    players.append(
        player(
            "best",
            team="team_d",
            price=80,
            ev3=15.0,
            ev6=30.0,
        )
    )

    options = single_transfer_options(
        sell_player_id="sell",
        players=players,
        state=state(),
    )

    ranked = rank_transfer_options(
        options,
        horizon=6,
    )

    assert (
        ranked[0].buy_player_id
        == "best"
    )


def test_sell_player_must_be_in_squad():
    bad_state = SquadState(
        player_ids=frozenset(),
        bank_tenths=10,
        selling_prices_tenths={},
        team_counts={},
    )

    with pytest.raises(
        DecisionError
    ):
        single_transfer_options(
            sell_player_id="sell",
            players=base_players(),
            state=bad_state,
        )



def test_existing_over_limit_squad_must_be_resolved():
    players = [
        player(
            "sell",
            team="team_city",
            price=60,
            ev6=15.0,
        ),
        player(
            "city2",
            team="team_city",
            position="DEF",
        ),
        player(
            "city3",
            team="team_city",
            position="GK",
        ),
        player(
            "city4",
            team="team_city",
            position="FWD",
        ),
        player(
            "replacement",
            team="team_other",
            price=60,
            ev6=20.0,
        ),
    ]

    custom_state = SquadState(
        player_ids=frozenset(
            {
                "sell",
                "city2",
                "city3",
                "city4",
            }
        ),
        bank_tenths=0,
        selling_prices_tenths={
            "sell": 60,
            "city2": 50,
            "city3": 50,
            "city4": 50,
        },
        team_counts={
            "team_city": 4,
        },
    )

    options = single_transfer_options(
        sell_player_id="sell",
        players=players,
        state=custom_state,
    )

    assert (
        options[0].buy_player_id
        == "replacement"
    )


def test_unrelated_transfer_cannot_leave_club_violation():
    players = [
        player(
            "sell",
            team="team_other",
            price=60,
            ev6=15.0,
        ),
        player(
            "city1",
            team="team_city",
            position="DEF",
        ),
        player(
            "city2",
            team="team_city",
            position="GK",
        ),
        player(
            "city3",
            team="team_city",
            position="FWD",
        ),
        player(
            "city4",
            team="team_city",
            position="DEF",
        ),
        player(
            "replacement",
            team="team_x",
            price=60,
            ev6=20.0,
        ),
    ]

    custom_state = SquadState(
        player_ids=frozenset(
            {
                "sell",
                "city1",
                "city2",
                "city3",
                "city4",
            }
        ),
        bank_tenths=0,
        selling_prices_tenths={
            "sell": 60,
            "city1": 50,
            "city2": 50,
            "city3": 50,
            "city4": 50,
        },
        team_counts={
            "team_other": 1,
            "team_city": 4,
        },
    )

    options = single_transfer_options(
        sell_player_id="sell",
        players=players,
        state=custom_state,
    )

    assert options == ()
