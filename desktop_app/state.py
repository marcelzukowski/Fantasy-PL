from __future__ import annotations

from dataclasses import (
    asdict,
    dataclass,
    field,
    replace,
)
from datetime import (
    datetime,
    timezone,
)
from pathlib import Path
from typing import Mapping
import json


POSITION_COUNTS = {
    "GK": 2,
    "DEF": 5,
    "MID": 5,
    "FWD": 3,
}


CHIP_KEYS = (
    "wildcard_h1",
    "free_hit_h1",
    "bench_boost_h1",
    "triple_captain_h1",

    "wildcard_h2",
    "free_hit_h2",
    "bench_boost_h2",
    "triple_captain_h2",
)


class DesktopStateError(
    RuntimeError
):
    pass


def default_chip_state():

    return {
        key: False
        for key
        in CHIP_KEYS
    }


@dataclass
class DesktopSquadState:

    season: str = "2026/27"

    gameweek: int = 5

    bank_tenths: int = 1

    free_transfers: int = 1

    fpl_entry_id: int | None = None

    selling_prices_tenths: dict[str, int] = field(
        default_factory=dict
    )

    purchase_prices_tenths: dict[str, int] = field(
        default_factory=dict
    )

    player_ids: list[str] = field(
        default_factory=list
    )

    chips_used: dict[str, bool] = field(
        default_factory=default_chip_state
    )

    source: str | None = None

    updated_at: str | None = None

    # DESKTOP-004E3F official FPL current lineup
    starting_player_ids: list[str] = field(
        default_factory=list
    )
    bench_player_ids: list[str] = field(
        default_factory=list
    )



    @classmethod
    def from_mapping(
        cls,
        payload: Mapping,
    ):

        chips = default_chip_state()


        raw_chips = payload.get(
            "chips_used",
            {},
        )


        if isinstance(
            raw_chips,
            Mapping,
        ):

            for key in CHIP_KEYS:

                chips[
                    key
                ] = bool(
                    raw_chips.get(
                        key,
                        False,
                    )
                )


        return cls(
            season=str(
                payload.get(
                    "season",
                    "2026/27",
                )
            ),

            gameweek=int(
                payload.get(
                    "gameweek",
                    5,
                )
            ),

            bank_tenths=int(
                payload.get(
                    "bank_tenths",
                    1,
                )
            ),

            free_transfers=int(
                payload.get(
                    "free_transfers",
                    1,
                )
            ),

            fpl_entry_id=(
                None
                if payload.get(
                    "fpl_entry_id"
                ) is None
                else int(
                    payload.get(
                        "fpl_entry_id"
                    )
                )
            ),

            selling_prices_tenths={
                str(key): int(value)
                for key, value
                in (
                    payload.get(
                        "selling_prices_tenths",
                        {},
                    ).items()
                    if isinstance(
                        payload.get(
                            "selling_prices_tenths",
                            {},
                        ),
                        Mapping,
                    )
                    else []
                )
            },

            purchase_prices_tenths={
                str(key): int(value)
                for key, value
                in (
                    payload.get(
                        "purchase_prices_tenths",
                        {},
                    ).items()
                    if isinstance(
                        payload.get(
                            "purchase_prices_tenths",
                            {},
                        ),
                        Mapping,
                    )
                    else []
                )
            },

            player_ids=[
                str(
                    value
                )
                for value
                in payload.get(
                    "player_ids",
                    [],
                )
            ],

            chips_used=chips,

            source=payload.get(
                "source"
            ),

            updated_at=payload.get(
                "updated_at"
            ),
            starting_player_ids=[
                str(value)
                for value in payload.get(
                    "starting_player_ids",
                    [],
                )
            ],
            bench_player_ids=[
                str(value)
                for value in payload.get(
                    "bench_player_ids",
                    [],
                )
            ],
        )


def preserve_account_state(
    previous: DesktopSquadState,
    current: DesktopSquadState,
) -> DesktopSquadState:

    selected = set(
        current.player_ids
    )


    same_squad = (
        len(
            previous.player_ids
        )
        == len(
            current.player_ids
        )
        and set(
            previous.player_ids
        )
        == selected
    )


    selling = {
        player_id: int(
            price
        )
        for player_id, price
        in previous.selling_prices_tenths.items()
        if player_id in selected
    }


    purchase = {
        player_id: int(
            price
        )
        for player_id, price
        in previous.purchase_prices_tenths.items()
        if player_id in selected
    }


    source = current.source


    if (
        previous.fpl_entry_id
        is not None
        and same_squad
    ):

        source = previous.source


    return replace(
        current,

        fpl_entry_id=(
            previous.fpl_entry_id
        ),

        selling_prices_tenths=(
            selling
        ),

        purchase_prices_tenths=(
            purchase
        ),

        source=source,
    )


def load_state(
    path: Path,
) -> DesktopSquadState:

    path = Path(
        path
    )


    try:

        payload = json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )

    except (
        OSError,
        json.JSONDecodeError,
    ) as exc:

        raise DesktopStateError(
            f"Could not load state: {path}"
        ) from exc


    if not isinstance(
        payload,
        Mapping,
    ):

        raise DesktopStateError(
            "Squad state root must be "
            "a JSON object."
        )


    return DesktopSquadState.from_mapping(
        payload
    )


def save_state(
    path: Path,
    state: DesktopSquadState,
):

    path = Path(
        path
    )


    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )


    state.updated_at = (
        datetime.now(
            timezone.utc
        ).isoformat()
    )


    temporary = path.with_suffix(
        ".tmp"
    )


    temporary.write_text(
        json.dumps(
            asdict(
                state
            ),
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


    temporary.replace(
        path
    )


def validate_state(
    state: DesktopSquadState,
    players_by_id,
):

    if len(
        state.player_ids
    ) != 15:

        raise DesktopStateError(
            "Squad must contain "
            "exactly 15 players."
        )


    if len(
        set(
            state.player_ids
        )
    ) != 15:

        raise DesktopStateError(
            "Squad contains duplicate players."
        )


    if not (
        1
        <= state.gameweek
        <= 38
    ):

        raise DesktopStateError(
            "Gameweek must be between "
            "1 and 38."
        )


    if not (
        0
        <= state.free_transfers
        <= 5
    ):

        raise DesktopStateError(
            "Free Transfers must be "
            "between 0 and 5."
        )


    if state.bank_tenths < 0:

        raise DesktopStateError(
            "Bank cannot be negative."
        )


    owned_ids = set(
        state.player_ids
    )


    for label, prices in (
        (
            "selling",
            state.selling_prices_tenths,
        ),
        (
            "purchase",
            state.purchase_prices_tenths,
        ),
    ):

        unknown = (
            set(
                prices
            )
            - owned_ids
        )


        if unknown:

            raise DesktopStateError(
                f"Unknown {label} price players: "
                + ", ".join(
                    sorted(
                        unknown
                    )
                )
            )


        invalid = [
            player_id
            for player_id, price
            in prices.items()
            if int(
                price
            ) <= 0
        ]


        if invalid:

            raise DesktopStateError(
                f"Invalid {label} prices for: "
                + ", ".join(
                    sorted(
                        invalid
                    )
                )
            )


    missing = [
        player_id
        for player_id
        in state.player_ids
        if player_id
        not in players_by_id
    ]


    if missing:

        raise DesktopStateError(
            "Missing players from current pool: "
            + ", ".join(
                missing
            )
        )


    position_counts = {
        position: 0
        for position
        in POSITION_COUNTS
    }


    team_counts = {}


    for player_id in state.player_ids:

        player = players_by_id[
            player_id
        ]


        position_counts[
            player.position
        ] += 1


        if player.team_id is not None:

            team_counts[
                player.team_id
            ] = (
                team_counts.get(
                    player.team_id,
                    0,
                )
                + 1
            )


    if (
        position_counts
        != POSITION_COUNTS
    ):

        raise DesktopStateError(
            "Invalid position structure. "
            f"Expected {POSITION_COUNTS}, "
            f"got {position_counts}."
        )


    overloaded = {
        team:
            count
        for team, count
        in team_counts.items()
        if count > 3
    }


    if overloaded:

        raise DesktopStateError(
            "More than three players "
            "from one club: "
            f"{overloaded}"
        )


    return {
        "positions":
            position_counts,

        "teams":
            team_counts,
    }
