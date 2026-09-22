import pytest

from fpl_engine.decision import (
    PlayerValue,
    SquadState,
    optimize_squad_transfers,
    optimize_starting_xi_transfers,
)


def player(
    player_id,
    *,
    team,
    position,
    price,
    ev3,
    ev6,
):
    return PlayerValue(
        player_id=player_id,
        name=player_id,
        position=position,
        team_id=team,
        provider_team_id=None,
        price_tenths=price,
        price_m=price / 10,
        ev_3=ev3,
        ev_6=ev6,
        value_3=ev3 / (price / 10),
        value_6=ev6 / (price / 10),
        minutes_3=200,
        minutes_6=400,
        confidence=0.7,
        uncertainty=0.3,
    )


def test_joint_optimizer_can_use_two_transfers():
    players = [
        player(
            "a",
            team="t1",
            position="MID",
            price=100,
            ev3=5,
            ev6=10,
        ),
        player(
            "b",
            team="t2",
            position="FWD",
            price=50,
            ev3=5,
            ev6=10,
        ),
        player(
            "new_mid",
            team="t3",
            position="MID",
            price=60,
            ev3=8,
            ev6=16,
        ),
        player(
            "new_fwd",
            team="t4",
            position="FWD",
            price=90,
            ev3=9,
            ev6=18,
        ),
    ]

    state = SquadState(
        player_ids=frozenset(
            {"a", "b"}
        ),
        bank_tenths=0,
        selling_prices_tenths={
            "a": 100,
            "b": 50,
        },
        team_counts={
            "t1": 1,
            "t2": 1,
        },
    )

    result = optimize_squad_transfers(
        players=players,
        state=state,
        horizon=6,
        exact_transfers=2,
    )

    assert result is not None

    assert set(
        result.incoming_player_ids
    ) == {
        "new_mid",
        "new_fwd",
    }

    assert result.gain == pytest.approx(
        14.0
    )


def test_budget_uses_selling_price():
    players = [
        player(
            "old",
            team="t1",
            position="MID",
            price=80,
            ev3=5,
            ev6=10,
        ),
        player(
            "buy",
            team="t2",
            position="MID",
            price=80,
            ev3=10,
            ev6=20,
        ),
    ]

    state = SquadState(
        player_ids=frozenset(
            {"old"}
        ),
        bank_tenths=0,
        selling_prices_tenths={
            "old": 70,
        },
        team_counts={
            "t1": 1,
        },
    )

    result = optimize_squad_transfers(
        players=players,
        state=state,
        horizon=6,
        exact_transfers=1,
    )

    assert result is None


def test_optimizer_resolves_club_violation():
    players = [
        player(
            "c1",
            team="city",
            position="GK",
            price=50,
            ev3=5,
            ev6=10,
        ),
        player(
            "c2",
            team="city",
            position="DEF",
            price=50,
            ev3=5,
            ev6=10,
        ),
        player(
            "c3",
            team="city",
            position="MID",
            price=50,
            ev3=5,
            ev6=10,
        ),
        player(
            "c4",
            team="city",
            position="FWD",
            price=50,
            ev3=5,
            ev6=10,
        ),
        player(
            "replacement",
            team="other",
            position="DEF",
            price=50,
            ev3=8,
            ev6=16,
        ),
    ]

    state = SquadState(
        player_ids=frozenset(
            {
                "c1",
                "c2",
                "c3",
                "c4",
            }
        ),
        bank_tenths=0,
        selling_prices_tenths={
            "c1": 50,
            "c2": 50,
            "c3": 50,
            "c4": 50,
        },
        team_counts={
            "city": 4,
        },
    )

    result = optimize_squad_transfers(
        players=players,
        state=state,
        horizon=6,
        exact_transfers=1,
    )

    assert result is not None

    assert "replacement" in (
        result.incoming_player_ids
    )

    assert "c2" in (
        result.outgoing_player_ids
    )


def test_exact_transfer_count_is_respected():
    players = [
        player(
            "a",
            team="t1",
            position="MID",
            price=50,
            ev3=5,
            ev6=10,
        ),
        player(
            "b",
            team="t2",
            position="MID",
            price=50,
            ev3=4,
            ev6=8,
        ),
        player(
            "x",
            team="t3",
            position="MID",
            price=50,
            ev3=8,
            ev6=16,
        ),
        player(
            "y",
            team="t4",
            position="MID",
            price=50,
            ev3=7,
            ev6=14,
        ),
    ]

    state = SquadState(
        player_ids=frozenset(
            {"a", "b"}
        ),
        bank_tenths=0,
        selling_prices_tenths={
            "a": 50,
            "b": 50,
        },
        team_counts={
            "t1": 1,
            "t2": 1,
        },
    )

    result = optimize_squad_transfers(
        players=players,
        state=state,
        horizon=6,
        exact_transfers=2,
    )

    assert result is not None
    assert result.transfer_count == 2
    assert len(
        result.outgoing_player_ids
    ) == 2
    assert len(
        result.incoming_player_ids
    ) == 2



def test_bench_upgrade_does_not_fake_lineup_gain():
    players = []

    # Current legal XI / squad skeleton.
    for index in range(2):
        players.append(
            player(
                f"gk{index}",
                team=f"gkt{index}",
                position="GK",
                price=50,
                ev3=(
                    10
                    if index == 0
                    else 1
                ),
                ev6=(
                    20
                    if index == 0
                    else 2
                ),
            )
        )

    for index in range(5):
        players.append(
            player(
                f"d{index}",
                team=f"dt{index}",
                position="DEF",
                price=50,
                ev3=8,
                ev6=16,
            )
        )

    for index in range(5):
        players.append(
            player(
                f"m{index}",
                team=f"mt{index}",
                position="MID",
                price=50,
                ev3=9,
                ev6=18,
            )
        )

    for index in range(3):
        players.append(
            player(
                f"f{index}",
                team=f"ft{index}",
                position="FWD",
                price=50,
                ev3=8,
                ev6=16,
            )
        )

    # Expensive-looking upgrade to backup GK.
    players.append(
        player(
            "bench_gk_upgrade",
            team="newgk",
            position="GK",
            price=50,
            ev3=7,
            ev6=14,
        )
    )

    squad_ids = {
        row.player_id
        for row in players
        if row.player_id
        != "bench_gk_upgrade"
    }

    state = SquadState(
        player_ids=frozenset(
            squad_ids
        ),
        bank_tenths=0,
        selling_prices_tenths={
            player_id: 50
            for player_id in squad_ids
        },
        team_counts={
            row.team_id: 1
            for row in players
            if row.player_id
            in squad_ids
        },
    )

    result = (
        optimize_starting_xi_transfers(
            players=players,
            state=state,
            horizon=6,
            exact_transfers=1,
        )
    )

    assert result is not None

    # Replacing the unused backup goalkeeper
    # cannot create starting-XI EV gain.
    if (
        "bench_gk_upgrade"
        in result.incoming_player_ids
    ):
        assert result.gain == pytest.approx(
            0.0
        )


def test_lineup_optimizer_returns_11_starters():
    players = []

    structure = {
        "GK": 2,
        "DEF": 5,
        "MID": 5,
        "FWD": 3,
    }

    index = 0

    for position, count in structure.items():
        for _ in range(count):
            players.append(
                player(
                    f"p{index}",
                    team=f"t{index}",
                    position=position,
                    price=50,
                    ev3=5 + index,
                    ev6=10 + index,
                )
            )
            index += 1

    players.append(
        player(
            "newdef",
            team="newteam",
            position="DEF",
            price=50,
            ev3=30,
            ev6=40,
        )
    )

    current = {
        row.player_id
        for row in players
        if row.player_id
        != "newdef"
    }

    state = SquadState(
        player_ids=frozenset(
            current
        ),
        bank_tenths=0,
        selling_prices_tenths={
            player_id: 50
            for player_id
            in current
        },
        team_counts={
            row.team_id: 1
            for row in players
            if row.player_id
            in current
        },
    )

    result = (
        optimize_starting_xi_transfers(
            players=players,
            state=state,
            horizon=6,
            exact_transfers=1,
        )
    )

    assert result is not None

    assert len(
        result.starting_xi_player_ids
    ) == 11

    assert len(
        result.bench_player_ids
    ) == 4
