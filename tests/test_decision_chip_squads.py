from types import SimpleNamespace

from fpl_engine.decision.chip_squads import (
    optimize_unlimited_squad,
)


def projection(
    player_id,
    ev,
):
    return SimpleNamespace(
        player_id=player_id,
        gameweeks=(
            SimpleNamespace(
                gameweek=4,
                expected_points=ev,
            ),
        ),
    )


def universe(
    extra_mid_price=50,
    extra_mid_team="T9",
):

    shape = (
        ("GK", 2),
        ("DEF", 5),
        ("MID", 5),
        ("FWD", 3),
    )

    rows = []
    projections = {}
    current = []
    selling = {}

    counter = 0

    for position, count in shape:

        for index in range(
            count
        ):

            counter += 1

            player_id = (
                f"p{counter}"
            )

            rows.append(
                {
                    "player_id":
                    player_id,
                    "position":
                    position,
                    "team_id":
                    f"T{counter % 8}",
                    "current_price":
                    50,
                }
            )

            projections[
                player_id
            ] = projection(
                player_id,
                2.0,
            )

            current.append(
                player_id
            )

            selling[
                player_id
            ] = 50

    rows.append(
        {
            "player_id": "upgrade",
            "position": "MID",
            "team_id":
            extra_mid_team,
            "current_price":
            extra_mid_price,
        }
    )

    projections[
        "upgrade"
    ] = projection(
        "upgrade",
        10.0,
    )

    return (
        rows,
        projections,
        current,
        selling,
    )


def test_unlimited_squad_can_replace_player():

    (
        rows,
        projections,
        current,
        selling,
    ) = universe()

    result = optimize_unlimited_squad(
        player_rows=rows,
        projections_by_id=projections,
        current_player_ids=current,
        selling_prices_tenths=(
            selling
        ),
        bank_tenths=0,
        first_gameweek=4,
        horizon=1,
        weights=(1.0,),
    )

    assert (
        "upgrade"
        in result.player_ids
    )

    assert len(
        result.player_ids
    ) == 15

    assert len(
        result.starting_xi_by_gameweek[
            4
        ]
    ) == 11


def test_unlimited_squad_respects_budget():

    (
        rows,
        projections,
        current,
        selling,
    ) = universe(
        extra_mid_price=51,
    )

    result = optimize_unlimited_squad(
        player_rows=rows,
        projections_by_id=projections,
        current_player_ids=current,
        selling_prices_tenths=(
            selling
        ),
        bank_tenths=0,
        first_gameweek=4,
        horizon=1,
        weights=(1.0,),
    )

    assert (
        "upgrade"
        not in result.player_ids
    )
