from desktop_app.state import (
    DesktopSquadState,
    preserve_account_state,
)


def _ids():

    return [
        f"player_{index}"
        for index in range(
            15
        )
    ]


def test_account_data_survives_same_squad():

    player_ids = _ids()


    previous = DesktopSquadState(
        player_ids=player_ids,

        fpl_entry_id=123,

        selling_prices_tenths={
            player_id:
                50 + index
            for index, player_id
            in enumerate(
                player_ids
            )
        },

        purchase_prices_tenths={
            player_id:
                49 + index
            for index, player_id
            in enumerate(
                player_ids
            )
        },

        source="fpl-my-team:123",
    )


    current = DesktopSquadState(
        player_ids=list(
            reversed(
                player_ids
            )
        ),

        bank_tenths=7,

        free_transfers=3,

        source="desktop-ui",
    )


    merged = preserve_account_state(
        previous,
        current,
    )


    assert (
        merged.fpl_entry_id
        == 123
    )

    assert len(
        merged.selling_prices_tenths
    ) == 15

    assert len(
        merged.purchase_prices_tenths
    ) == 15

    assert (
        merged.source
        == "fpl-my-team:123"
    )


def test_account_prices_are_trimmed_after_manual_squad_change():

    player_ids = _ids()


    previous = DesktopSquadState(
        player_ids=player_ids,

        fpl_entry_id=123,

        selling_prices_tenths={
            player_id:
                50 + index
            for index, player_id
            in enumerate(
                player_ids
            )
        },

        purchase_prices_tenths={
            player_id:
                49 + index
            for index, player_id
            in enumerate(
                player_ids
            )
        },

        source="fpl-my-team:123",
    )


    changed = (
        player_ids[
            :-1
        ]
        + [
            "replacement_player"
        ]
    )


    current = DesktopSquadState(
        player_ids=changed,
        source="desktop-ui",
    )


    merged = preserve_account_state(
        previous,
        current,
    )


    assert (
        merged.fpl_entry_id
        == 123
    )

    assert len(
        merged.selling_prices_tenths
    ) == 14

    assert len(
        merged.purchase_prices_tenths
    ) == 14

    assert (
        merged.source
        == "desktop-ui"
    )
