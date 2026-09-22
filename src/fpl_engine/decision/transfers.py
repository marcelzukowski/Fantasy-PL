from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Iterable, Mapping

from .horizon import DecisionError
from .value import PlayerValue


MAX_PLAYERS_PER_TEAM = 3


@dataclass(frozen=True)
class SquadState:
    player_ids: frozenset[str]

    bank_tenths: int

    selling_prices_tenths: Mapping[
        str,
        int,
    ]

    team_counts: Mapping[
        str,
        int,
    ]


@dataclass(frozen=True)
class TransferOption:
    sell_player_id: str
    sell_name: str

    buy_player_id: str
    buy_name: str

    position: str

    sell_price_tenths: int
    buy_price_tenths: int

    bank_before_tenths: int
    bank_after_tenths: int

    gross_gain_3: float
    gross_gain_6: float

    hit_cost: float

    net_gain_3: float
    net_gain_6: float


def build_team_counts(
    squad_player_ids: Iterable[str],
    players_by_id: Mapping[
        str,
        PlayerValue,
    ],
) -> dict[str, int]:

    counts: dict[str, int] = {}

    for player_id in squad_player_ids:

        player = players_by_id.get(
            player_id
        )

        if player is None:
            raise DecisionError(
                "squad contains unknown player: "
                f"{player_id}"
            )

        counts[
            player.team_id
        ] = (
            counts.get(
                player.team_id,
                0,
            )
            + 1
        )

    return counts


def _validate_state(
    state: SquadState,
) -> None:

    if state.bank_tenths < 0:
        raise DecisionError(
            "bank_tenths cannot be negative"
        )

    for player_id in state.player_ids:

        if player_id not in (
            state.selling_prices_tenths
        ):
            raise DecisionError(
                "missing selling price for "
                f"{player_id}"
            )

        if (
            int(
                state.selling_prices_tenths[
                    player_id
                ]
            )
            <= 0
        ):
            raise DecisionError(
                "selling prices must be positive"
            )

    for team_id, count in (
        state.team_counts.items()
    ):

        if count < 0:
            raise DecisionError(
                "team count cannot be negative"
            )

        # Existing squad may temporarily exceed
        # the club limit after real-world player
        # transfers. Candidate transfers must
        # resolve the violation rather than
        # rejecting the state up front.


def single_transfer_options(
    *,
    sell_player_id: str,
    players: Iterable[
        PlayerValue
    ],
    state: SquadState,
    hit_cost: float = 0.0,
) -> tuple[
    TransferOption,
    ...,
]:

    _validate_state(
        state
    )

    if (
        not isfinite(hit_cost)
        or hit_cost < 0
    ):
        raise DecisionError(
            "hit_cost must be finite "
            "and non-negative"
        )

    players_by_id = {
        player.player_id: player
        for player in players
    }

    seller = players_by_id.get(
        sell_player_id
    )

    if seller is None:
        raise DecisionError(
            "sell player not found"
        )

    if (
        sell_player_id
        not in state.player_ids
    ):
        raise DecisionError(
            "sell player is not in squad"
        )

    sell_price = int(
        state.selling_prices_tenths[
            sell_player_id
        ]
    )

    available_budget = (
        state.bank_tenths
        + sell_price
    )

    # Team counts after removing seller.
    counts_after_sell = dict(
        state.team_counts
    )

    seller_team_count = (
        counts_after_sell.get(
            seller.team_id,
            0,
        )
    )

    if seller_team_count <= 0:
        raise DecisionError(
            "team_counts inconsistent "
            "with sell player"
        )

    counts_after_sell[
        seller.team_id
    ] = (
        seller_team_count - 1
    )

    result = []

    for buyer in players:

        if (
            buyer.player_id
            in state.player_ids
        ):
            continue

        if (
            buyer.position
            != seller.position
        ):
            continue

        if (
            buyer.price_tenths
            > available_budget
        ):
            continue

        final_counts = dict(
            counts_after_sell
        )

        final_counts[
            buyer.team_id
        ] = (
            final_counts.get(
                buyer.team_id,
                0,
            )
            + 1
        )

        if any(
            count > MAX_PLAYERS_PER_TEAM
            for count in final_counts.values()
        ):
            continue

        bank_after = (
            available_budget
            - buyer.price_tenths
        )

        gain_3 = (
            buyer.ev_3
            - seller.ev_3
        )

        gain_6 = (
            buyer.ev_6
            - seller.ev_6
        )

        result.append(
            TransferOption(
                sell_player_id=(
                    seller.player_id
                ),
                sell_name=(
                    seller.name
                ),
                buy_player_id=(
                    buyer.player_id
                ),
                buy_name=(
                    buyer.name
                ),
                position=(
                    seller.position
                ),
                sell_price_tenths=(
                    sell_price
                ),
                buy_price_tenths=(
                    buyer.price_tenths
                ),
                bank_before_tenths=(
                    state.bank_tenths
                ),
                bank_after_tenths=(
                    bank_after
                ),
                gross_gain_3=(
                    gain_3
                ),
                gross_gain_6=(
                    gain_6
                ),
                hit_cost=float(
                    hit_cost
                ),
                net_gain_3=(
                    gain_3
                    - hit_cost
                ),
                net_gain_6=(
                    gain_6
                    - hit_cost
                ),
            )
        )

    return tuple(
        result
    )


def rank_transfer_options(
    options: Iterable[
        TransferOption
    ],
    *,
    horizon: int,
) -> tuple[
    TransferOption,
    ...,
]:

    if horizon == 3:
        key = lambda row: (
            row.net_gain_3,
            row.gross_gain_3,
            row.bank_after_tenths,
        )

    elif horizon == 6:
        key = lambda row: (
            row.net_gain_6,
            row.gross_gain_6,
            row.bank_after_tenths,
        )

    else:
        raise DecisionError(
            "transfer horizon must "
            "be 3 or 6"
        )

    return tuple(
        sorted(
            options,
            key=key,
            reverse=True,
        )
    )
