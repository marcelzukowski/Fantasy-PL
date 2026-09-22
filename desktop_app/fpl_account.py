from __future__ import annotations

from dataclasses import (
    dataclass,
    replace,
)
from datetime import (
    datetime,
    timezone,
)
from enum import Enum
import socket
from typing import Mapping

import httpx

from .state import (
    DesktopSquadState,
    default_chip_state,
)


FPL_API_ROOT = (
    "https://fantasy.premierleague.com/api"
)


class FPLAccountError(
    RuntimeError
):
    pass


class AccountSyncState(str, Enum):
    DISCONNECTED = "DISCONNECTED"
    LOGIN_REQUIRED = "LOGIN_REQUIRED"
    CONNECTING = "CONNECTING"
    SYNCING = "SYNCING"
    CONNECTED = "CONNECTED"
    ERROR = "ERROR"


def cdp_debug_session_available(
    *,
    connector=socket.create_connection,
    address: tuple[str, int] = ("127.0.0.1", 9222),
    timeout_seconds: float = 0.25,
) -> bool:
    """Return whether the dedicated local Edge debugging endpoint is ready."""
    try:
        connection = connector(address, timeout_seconds)
    except OSError:
        return False
    close = getattr(connection, "close", None)
    if close is not None:
        close()
    return True


@dataclass(
    frozen=True
)
class FPLAccountSnapshot:

    entry_id: int

    player_ids: tuple[str, ...]

    selling_prices_tenths: dict[str, int]

    purchase_prices_tenths: dict[str, int]

    bank_tenths: int

    free_transfers: int | None

    chips_used: dict[str, bool]

    captain_player_id: str | None

    vice_captain_player_id: str | None

    starting_player_ids: tuple[str, ...]

    bench_player_ids: tuple[str, ...]

    transfer_limit: int | None

    transfers_made: int

    synced_at: str


def _provider_index(
    players_by_id,
) -> dict[str, str]:

    result = {}


    for canonical_id, player in (
        players_by_id.items()
    ):

        provider_id = getattr(
            player,
            "provider_id",
            None,
        )


        if provider_id is None:

            continue


        provider_id = str(
            provider_id
        )


        existing = result.get(
            provider_id
        )


        if (
            existing is not None
            and existing
            != str(
                canonical_id
            )
        ):

            raise FPLAccountError(
                "Duplicate provider player id "
                f"{provider_id}."
            )


        result[
            provider_id
        ] = str(
            canonical_id
        )


    if not result:

        raise FPLAccountError(
            "Current player pool does not "
            "contain provider ids."
        )


    return result


def _chip_state(
    chips,
):

    result = default_chip_state()


    name_map = {
        "wildcard":
            "wildcard",

        "freehit":
            "free_hit",

        "bboost":
            "bench_boost",

        "3xc":
            "triple_captain",
    }


    if not isinstance(
        chips,
        list,
    ):

        return result


    for chip in chips:

        if not isinstance(
            chip,
            Mapping,
        ):

            continue


        prefix = name_map.get(
            str(
                chip.get(
                    "name",
                    "",
                )
            ).casefold()
        )


        if prefix is None:

            continue


        played_gameweeks = (
            chip.get(
                "played_by_entry",
                [],
            )
        )


        if isinstance(
            played_gameweeks,
            list,
        ):

            for gameweek in (
                played_gameweeks
            ):

                try:

                    gameweek = int(
                        gameweek
                    )

                except (
                    TypeError,
                    ValueError,
                ):

                    continue


                half = (
                    "h1"
                    if gameweek <= 19
                    else "h2"
                )


                key = (
                    f"{prefix}_{half}"
                )


                if key in result:

                    result[
                        key
                    ] = True


        if (
            str(
                chip.get(
                    "status_for_entry",
                    "",
                )
            ).casefold()
            != "played"
        ):

            continue


        if played_gameweeks:

            continue


        try:

            start_event = int(
                chip.get(
                    "start_event"
                )
            )

        except (
            TypeError,
            ValueError,
        ):

            continue


        half = (
            "h1"
            if start_event <= 19
            else "h2"
        )


        key = (
            f"{prefix}_{half}"
        )


        if key in result:

            result[
                key
            ] = True


    return result


def _free_transfers(
    transfers,
) -> tuple[
    int | None,
    int | None,
    int,
]:

    if not isinstance(
        transfers,
        Mapping,
    ):

        raise FPLAccountError(
            "my-team response is missing "
            "transfer state."
        )


    raw_limit = transfers.get(
        "limit"
    )


    limit = (
        None
        if raw_limit is None
        else int(
            raw_limit
        )
    )


    made = int(
        transfers.get(
            "made",
            0,
        )
    )


    status = str(
        transfers.get(
            "status",
            "",
        )
    ).casefold()


    # Current FPL my-team semantics:
    #
    # - limit = free-transfer allowance
    # - made = transfers already made in the period
    # - cost = points charged for transfers beyond allowance
    # - status describes the transfer regime and must NOT
    #   be interpreted as "zero free transfers".
    #
    # Therefore, whenever FPL provides a finite limit,
    # remaining free transfers are limit - made.
    #
    # A null limit represents an unlimited transfer state
    # such as a transfer chip / special transfer period.

    if limit is None:

        remaining = None

    else:

        remaining = max(
            0,
            limit - made,
        )


    return (
        remaining,
        limit,
        made,
    )


def snapshot_from_my_team(
    payload: Mapping,
    *,
    entry_id: int,
    players_by_id,
) -> FPLAccountSnapshot:

    if not isinstance(
        payload,
        Mapping,
    ):

        raise FPLAccountError(
            "my-team response root must "
            "be an object."
        )


    picks = payload.get(
        "picks"
    )


    if not isinstance(
        picks,
        list,
    ) or len(
        picks
    ) != 15:

        raise FPLAccountError(
            "my-team response must contain "
            "exactly 15 picks."
        )


    provider_to_canonical = (
        _provider_index(
            players_by_id
        )
    )


    ordered = sorted(
        picks,
        key=lambda row:
            int(
                row.get(
                    "position",
                    999,
                )
            )
            if isinstance(
                row,
                Mapping,
            )
            else 999,
    )


    player_ids = []

    selling_prices = {}

    purchase_prices = {}

    captain = None

    vice_captain = None


    for pick in ordered:

        if not isinstance(
            pick,
            Mapping,
        ):

            raise FPLAccountError(
                "Invalid pick row in "
                "my-team response."
            )


        provider_id = str(
            pick.get(
                "element"
            )
        )


        canonical_id = (
            provider_to_canonical.get(
                provider_id
            )
        )


        if canonical_id is None:

            raise FPLAccountError(
                "FPL player id is missing "
                "from the current engine pool: "
                f"{provider_id}."
            )


        player = players_by_id[canonical_id]
        display_name = getattr(player, "display_name", canonical_id)
        prices = {}
        for field in ("selling_price", "purchase_price"):
            try:
                prices[field] = int(pick[field])
            except (KeyError, TypeError, ValueError) as exc:
                raise FPLAccountError(
                    f"FPL player {display_name} ({provider_id}) is missing a valid {field}."
                ) from exc
        selling_price = prices["selling_price"]
        purchase_price = prices["purchase_price"]


        if (
            selling_price <= 0
            or purchase_price <= 0
        ):

            raise FPLAccountError(
                "Personal player prices must "
                "be positive."
            )


        player_ids.append(
            canonical_id
        )

        selling_prices[
            canonical_id
        ] = selling_price

        purchase_prices[
            canonical_id
        ] = purchase_price


        if bool(
            pick.get(
                "is_captain",
                False,
            )
        ):

            captain = canonical_id


        if bool(
            pick.get(
                "is_vice_captain",
                False,
            )
        ):

            vice_captain = canonical_id


    if len(
        set(
            player_ids
        )
    ) != 15:

        raise FPLAccountError(
            "Mapped FPL squad contains "
            "duplicate players."
        )


    transfers = payload.get(
        "transfers"
    )


    remaining_ft, limit, made = (
        _free_transfers(
            transfers
        )
    )


    try:

        bank = int(
            transfers[
                "bank"
            ]
        )

    except (
        KeyError,
        TypeError,
        ValueError,
    ) as exc:

        raise FPLAccountError(
            "my-team response is missing "
            "the account bank."
        ) from exc


    if bank < 0:

        raise FPLAccountError(
            "Account bank cannot be negative."
        )


    return FPLAccountSnapshot(
        entry_id=int(
            entry_id
        ),

        player_ids=tuple(
            player_ids
        ),

        selling_prices_tenths=(
            selling_prices
        ),

        purchase_prices_tenths=(
            purchase_prices
        ),

        bank_tenths=bank,

        free_transfers=(
            remaining_ft
        ),

        chips_used=_chip_state(
            payload.get(
                "chips",
                [],
            )
        ),

        captain_player_id=(
            captain
        ),

        vice_captain_player_id=(
            vice_captain
        ),

        starting_player_ids=tuple(player_ids[:11]),

        bench_player_ids=tuple(player_ids[11:]),

        transfer_limit=limit,

        transfers_made=made,

        synced_at=(
            datetime.now(
                timezone.utc
            ).isoformat()
        ),
    )


def apply_account_snapshot(
    state: DesktopSquadState,
    snapshot: FPLAccountSnapshot,
) -> DesktopSquadState:

    return replace(
        state,

        bank_tenths=(
            snapshot.bank_tenths
        ),

        free_transfers=(
            state.free_transfers
            if snapshot.free_transfers
            is None
            else snapshot.free_transfers
        ),

        fpl_entry_id=(
            snapshot.entry_id
        ),

        selling_prices_tenths=dict(
            snapshot.selling_prices_tenths
        ),

        purchase_prices_tenths=dict(
            snapshot.purchase_prices_tenths
        ),

        player_ids=list(
            snapshot.player_ids
        ),

        starting_player_ids=list(snapshot.starting_player_ids),

        bench_player_ids=list(snapshot.bench_player_ids),

        chips_used=dict(
            snapshot.chips_used
        ),

        source=(
            "fpl-my-team:"
            + str(
                snapshot.entry_id
            )
        ),
    )


def account_state_issues(
    state: DesktopSquadState,
    players_by_id,
) -> tuple[str, ...]:
    """Describe why account data is not safe to present as a complete sync."""
    issues: list[str] = []
    owned = list(state.player_ids)
    owned_set = set(owned)
    if len(owned) != 15 or len(owned_set) != 15:
        issues.append(f"expected 15 unique players, received {len(owned_set)}")
    unresolved = [player_id for player_id in owned if player_id not in players_by_id]
    if unresolved:
        issues.append("unresolved player IDs: " + ", ".join(unresolved))

    def player_label(player_id: str) -> str:
        player = players_by_id.get(player_id)
        name = getattr(player, "display_name", player_id)
        provider = getattr(player, "provider_id", None)
        return f"{name} (FPL {provider})" if provider is not None else str(name)

    missing_selling = [player_id for player_id in owned if player_id not in state.selling_prices_tenths]
    if missing_selling:
        issues.append("missing selling price: " + ", ".join(player_label(player_id) for player_id in missing_selling))
    missing_purchase = [player_id for player_id in owned if player_id not in state.purchase_prices_tenths]
    if missing_purchase:
        issues.append("missing purchase price: " + ", ".join(player_label(player_id) for player_id in missing_purchase))
    if not isinstance(state.bank_tenths, int) or state.bank_tenths < 0:
        issues.append("bank is unavailable or invalid")
    if not isinstance(state.free_transfers, int) or not 0 <= state.free_transfers <= 5:
        issues.append("free-transfer state is unavailable or invalid")
    if not isinstance(state.gameweek, int) or not 1 <= state.gameweek <= 38:
        issues.append("gameweek is unavailable or invalid")

    starting = list(state.starting_player_ids)
    bench = list(state.bench_player_ids)
    if starting or bench:
        if len(starting) != 11 or len(bench) != 4:
            issues.append("official picks must contain 11 starters and 4 bench players")
        elif set(starting).isdisjoint(bench) is False or set(starting + bench) != owned_set:
            issues.append("official picks do not match the owned squad")
    return tuple(issues)


def fetch_my_team(
    *,
    entry_id: int,
    bearer_token: str,
    client: httpx.Client | None = None,
    timeout_seconds: float = 30.0,
) -> dict:

    token = str(
        bearer_token
    ).strip()


    if token.casefold().startswith(
        "bearer "
    ):

        token = token[
            7:
        ].strip()


    if not token:

        raise FPLAccountError(
            "Bearer token is empty."
        )


    headers = {
        "Accept":
            "application/json",

        "User-Agent":
            "FPLControlCenter/desktop",

        "X-API-Authorization":
            f"Bearer {token}",
    }


    owns_client = (
        client is None
    )


    if client is None:

        client = httpx.Client(
            timeout=timeout_seconds,
            follow_redirects=True,
        )


    try:

        response = client.get(
            (
                FPL_API_ROOT
                + "/my-team/"
                + str(
                    int(
                        entry_id
                    )
                )
                + "/"
            ),
            headers=headers,
        )


        if response.status_code in {
            401,
            403,
        }:

            raise FPLAccountError(
                "FPL authentication was rejected. "
                "Reconnect the account."
            )


        response.raise_for_status()


        payload = response.json()


        if not isinstance(
            payload,
            dict,
        ):

            raise FPLAccountError(
                "Unexpected my-team response."
            )


        return payload


    except httpx.HTTPError as exc:

        raise FPLAccountError(
            "Could not fetch authenticated "
            "FPL team data."
        ) from exc


    finally:

        if owns_client:

            client.close()
