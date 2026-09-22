import pytest

from desktop_app.data_access import (
    PlayerRecord,
)
from desktop_app.fpl_account import (
    FPLAccountError,
    apply_account_snapshot,
    fetch_my_team,
    snapshot_from_my_team,
)
from desktop_app.state import (
    DesktopSquadState,
    load_state,
    save_state,
)


def _players():

    positions = (
        ["GK"] * 2
        + ["DEF"] * 5
        + ["MID"] * 5
        + ["FWD"] * 3
    )


    return {
        f"canonical_{index}":
            PlayerRecord(
                player_id=(
                    f"canonical_{index}"
                ),

                display_name=(
                    f"Player {index}"
                ),

                position=position,

                team_id=(
                    f"team_{index // 2}"
                ),

                current_price=(
                    50 + index
                ),

                provider_id=str(
                    index + 1
                ),
            )
        for index, position
        in enumerate(
            positions
        )
    }


def _payload():

    return {
        "picks": [
            {
                "element": index,
                "position": index,

                "selling_price":
                    49 + index,

                "purchase_price":
                    48 + index,

                "is_captain":
                    index == 1,

                "is_vice_captain":
                    index == 2,
            }
            for index in range(
                1,
                16,
            )
        ],

        "chips": [
            {
                "name":
                    "wildcard",

                "status_for_entry":
                    "played",

                "played_by_entry":
                    [3],

                "start_event":
                    1,

                "stop_event":
                    19,
            },
            {
                "name":
                    "bboost",

                "status_for_entry":
                    "played",

                "played_by_entry":
                    [24],

                "start_event":
                    20,

                "stop_event":
                    38,
            },
            {
                "name":
                    "freehit",

                "status_for_entry":
                    "available",

                "played_by_entry":
                    [],

                "start_event":
                    1,

                "stop_event":
                    19,
            },
        ],

        "transfers": {
            "cost":
                0,

            "status":
                "free",

            "limit":
                3,

            "made":
                1,

            "bank":
                7,

            "value":
                1007,
        },
    }


def test_snapshot_maps_personal_prices():

    snapshot = snapshot_from_my_team(
        _payload(),
        entry_id=123456,
        players_by_id=_players(),
    )


    assert len(
        snapshot.player_ids
    ) == 15


    assert (
        snapshot.selling_prices_tenths[
            "canonical_0"
        ]
        == 50
    )


    assert (
        snapshot.purchase_prices_tenths[
            "canonical_0"
        ]
        == 49
    )


    assert (
        snapshot.bank_tenths
        == 7
    )


    assert (
        snapshot.free_transfers
        == 2
    )


    assert (
        snapshot.chips_used[
            "wildcard_h1"
        ]
        is True
    )


    assert (
        snapshot.chips_used[
            "bench_boost_h2"
        ]
        is True
    )


    assert (
        snapshot.chips_used[
            "free_hit_h1"
        ]
        is False
    )


    assert (
        snapshot.captain_player_id
        == "canonical_0"
    )


    assert (
        snapshot.vice_captain_player_id
        == "canonical_1"
    )


def test_snapshot_can_update_desktop_state():

    players = _players()


    snapshot = snapshot_from_my_team(
        _payload(),
        entry_id=123456,
        players_by_id=players,
    )


    state = apply_account_snapshot(
        DesktopSquadState(
            player_ids=list(
                players
            )
        ),
        snapshot,
    )


    assert (
        state.fpl_entry_id
        == 123456
    )


    assert (
        state.bank_tenths
        == 7
    )


    assert (
        state.free_transfers
        == 2
    )


    assert len(
        state.selling_prices_tenths
    ) == 15


    assert (
        state.source
        == "fpl-my-team:123456"
    )


def test_snapshot_rejects_unknown_provider_player():

    payload = _payload()


    payload[
        "picks"
    ][0][
        "element"
    ] = 99999


    with pytest.raises(
        FPLAccountError,
        match="missing",
    ):

        snapshot_from_my_team(
            payload,
            entry_id=123456,
            players_by_id=_players(),
        )


def test_account_price_state_roundtrip(
    tmp_path,
):

    players = _players()


    snapshot = snapshot_from_my_team(
        _payload(),
        entry_id=123456,
        players_by_id=players,
    )


    state = apply_account_snapshot(
        DesktopSquadState(
            player_ids=list(
                players
            )
        ),
        snapshot,
    )


    path = (
        tmp_path
        / "squad_state.json"
    )


    save_state(
        path,
        state,
    )


    restored = load_state(
        path
    )


    assert (
        restored.fpl_entry_id
        == 123456
    )


    assert (
        restored.selling_prices_tenths
        == state.selling_prices_tenths
    )


    assert (
        restored.purchase_prices_tenths
        == state.purchase_prices_tenths
    )

def test_cost_status_does_not_zero_free_transfers():

    payload = _payload()

    payload[
        "transfers"
    ].update({
        "status":
            "cost",

        "cost":
            4,

        "limit":
            3,

        "made":
            0,

        "bank":
            1,
    })


    snapshot = snapshot_from_my_team(
        payload,
        entry_id=123456,
        players_by_id=_players(),
    )


    assert (
        snapshot.free_transfers
        == 3
    )


    assert (
        snapshot.transfer_limit
        == 3
    )


    assert (
        snapshot.transfers_made
        == 0
    )


def test_fetch_my_team_uses_only_a_read_request():
    calls = []

    class Response:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"picks": []}

    class ReadOnlyClient:
        def get(self, url, *, headers):
            calls.append((url, headers))
            return Response()

        def post(self, *args, **kwargs):
            raise AssertionError("FPL account sync must never POST")

        def put(self, *args, **kwargs):
            raise AssertionError("FPL account sync must never PUT")

        def delete(self, *args, **kwargs):
            raise AssertionError("FPL account sync must never DELETE")

    assert fetch_my_team(entry_id=123456, bearer_token="test-token", client=ReadOnlyClient()) == {"picks": []}
    assert len(calls) == 1
    assert calls[0][0].endswith("/api/my-team/123456/")
    assert calls[0][1]["X-API-Authorization"] == "Bearer test-token"
