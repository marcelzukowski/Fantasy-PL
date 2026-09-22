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


def universe():

    rows = []
    projections = {}
    current = []
    selling = {}

    counter = 0

    for position, count in (
        ("GK", 2),
        ("DEF", 5),
        ("MID", 5),
        ("FWD", 3),
    ):

        for _ in range(count):

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
                    f"T{counter}",
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
            "player_id":
            "premium",
            "position":
            "FWD",
            "team_id":
            "TP",
            "current_price":
            50,
        }
    )

    projections[
        "premium"
    ] = projection(
        "premium",
        1.0,
    )

    return (
        rows,
        projections,
        current,
        selling,
    )


def test_required_player_is_selected():

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
        selling_prices_tenths=selling,
        bank_tenths=0,
        first_gameweek=4,
        horizon=1,
        weights=(1.0,),
        required_player_ids=(
            "premium",
        ),
    )

    assert (
        "premium"
        in result.player_ids
    )


def test_forbidden_player_is_not_selected():

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
        selling_prices_tenths=selling,
        bank_tenths=0,
        first_gameweek=4,
        horizon=1,
        weights=(1.0,),
        forbidden_player_ids=(
            "p13",
        ),
    )

    assert (
        "p13"
        not in result.player_ids
    )
