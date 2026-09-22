import json

import pytest

from desktop_app.data_access import (
    PlayerRecord,
    bootstrap_saved_wc,
)
from desktop_app.state import (
    DesktopSquadState,
    DesktopStateError,
    load_state,
    save_state,
    validate_state,
)


def _players():

    positions = (
        ["GK"] * 2
        + ["DEF"] * 5
        + ["MID"] * 5
        + ["FWD"] * 3
    )


    return {
        f"p{index}":
            PlayerRecord(
                player_id=f"p{index}",

                display_name=(
                    f"Player {index}"
                ),

                position=position,

                team_id=(
                    f"team_{index // 2}"
                ),

                current_price=50,
            )
        for index, position
        in enumerate(
            positions
        )
    }


def test_valid_desktop_state():

    players = _players()


    state = DesktopSquadState(
        player_ids=list(
            players
        )
    )


    result = validate_state(
        state,
        players,
    )


    assert result[
        "positions"
    ] == {
        "GK": 2,
        "DEF": 5,
        "MID": 5,
        "FWD": 3,
    }


def test_duplicate_player_rejected():

    players = _players()

    ids = list(
        players
    )

    ids[-1] = ids[
        0
    ]


    with pytest.raises(
        DesktopStateError,
        match="duplicate",
    ):

        validate_state(
            DesktopSquadState(
                player_ids=ids
            ),
            players,
        )


def test_more_than_three_from_club_rejected():

    players = _players()


    ids = list(
        players
    )


    first_four = ids[
        :4
    ]


    players = dict(
        players
    )


    for player_id in first_four:

        player = players[
            player_id
        ]


        players[
            player_id
        ] = PlayerRecord(
            player_id=(
                player.player_id
            ),

            display_name=(
                player.display_name
            ),

            position=(
                player.position
            ),

            team_id="same_team",

            current_price=(
                player.current_price
            ),
        )


    with pytest.raises(
        DesktopStateError,
        match="More than three",
    ):

        validate_state(
            DesktopSquadState(
                player_ids=ids
            ),
            players,
        )


def test_state_roundtrip(
    tmp_path,
):

    path = (
        tmp_path
        / "state.json"
    )


    original = DesktopSquadState(
        gameweek=5,

        bank_tenths=1,

        free_transfers=1,

        player_ids=[
            f"p{i}"
            for i in range(
                15
            )
        ],
    )


    save_state(
        path,
        original,
    )


    restored = load_state(
        path
    )


    assert restored.gameweek == 5

    assert restored.bank_tenths == 1

    assert restored.player_ids == (
        original.player_ids
    )


def test_bootstrap_wc(
    tmp_path,
):

    reference = (
        tmp_path
        / "scratch"
        / "decision"
        / "captain068h"
        / "decision_42.json"
    )


    reference.parent.mkdir(
        parents=True,
        exist_ok=True,
    )


    reference.write_text(
        json.dumps({
            "saved_wc_resolution": [
                {
                    "player_id":
                        f"p{i}"
                }
                for i in range(
                    15
                )
            ]
        }),
        encoding="utf-8",
    )


    state = bootstrap_saved_wc(
        tmp_path
    )


    assert len(
        state.player_ids
    ) == 15

    assert (
        state
        .chips_used[
            "wildcard_h1"
        ]
        is True
    )
