from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Iterable, Mapping


class DecisionError(ValueError):
    """Invalid input to the decision layer."""


@dataclass(frozen=True)
class GameweekProjection:
    player_id: str
    gameweek: int
    expected_points: float

    def __post_init__(self) -> None:
        if not self.player_id:
            raise DecisionError(
                "player_id cannot be empty"
            )

        if self.gameweek <= 0:
            raise DecisionError(
                "gameweek must be positive"
            )

        if not isfinite(
            self.expected_points
        ):
            raise DecisionError(
                "expected_points must be finite"
            )


@dataclass(frozen=True)
class HorizonValue:
    player_id: str
    first_gameweek: int
    last_gameweek: int

    raw_expected_points: float
    weighted_expected_points: float

    gameweeks: int


@dataclass(frozen=True)
class TransferComparison:
    sell_player_id: str
    buy_player_id: str

    sell_value: float
    buy_value: float

    gross_gain: float
    hit_cost: float
    net_gain: float


DEFAULT_WEIGHTS: dict[int, float] = {
    0: 1.00,
    1: 0.95,
    2: 0.90,
    3: 0.85,
    4: 0.80,
    5: 0.75,
}


def _validated_weights(
    weights: Mapping[int, float],
) -> dict[int, float]:

    result = {}

    for offset, weight in weights.items():

        if offset < 0:
            raise DecisionError(
                "gameweek weight offset "
                "cannot be negative"
            )

        value = float(
            weight
        )

        if (
            not isfinite(value)
            or value < 0.0
        ):
            raise DecisionError(
                "gameweek weights must be "
                "finite and non-negative"
            )

        result[int(offset)] = value

    if not result:
        raise DecisionError(
            "at least one gameweek weight "
            "is required"
        )

    return result


def horizon_value(
    projections: Iterable[
        GameweekProjection
    ],
    *,
    first_gameweek: int,
    weights: Mapping[int, float] | None = None,
) -> HorizonValue:

    if first_gameweek <= 0:
        raise DecisionError(
            "first_gameweek must be positive"
        )

    resolved_weights = _validated_weights(
        weights or DEFAULT_WEIGHTS
    )

    rows = list(
        projections
    )

    if not rows:
        raise DecisionError(
            "projections cannot be empty"
        )

    player_ids = {
        row.player_id
        for row in rows
    }

    if len(player_ids) != 1:
        raise DecisionError(
            "horizon_value accepts exactly "
            "one player"
        )

    player_id = next(
        iter(player_ids)
    )

    by_gameweek = {}

    for row in rows:

        if row.gameweek in by_gameweek:
            raise DecisionError(
                "duplicate gameweek projection "
                f"for {player_id}: "
                f"GW{row.gameweek}"
            )

        by_gameweek[
            row.gameweek
        ] = row.expected_points

    raw = 0.0
    weighted = 0.0
    included = 0

    for offset, weight in sorted(
        resolved_weights.items()
    ):

        gameweek = (
            first_gameweek + offset
        )

        points = float(
            by_gameweek.get(
                gameweek,
                0.0,
            )
        )

        raw += points
        weighted += (
            points * weight
        )

        included += 1

    return HorizonValue(
        player_id=player_id,
        first_gameweek=(
            first_gameweek
        ),
        last_gameweek=(
            first_gameweek
            + max(
                resolved_weights
            )
        ),
        raw_expected_points=raw,
        weighted_expected_points=weighted,
        gameweeks=included,
    )


def compare_transfer(
    sell: HorizonValue,
    buy: HorizonValue,
    *,
    hit_cost: float = 0.0,
) -> TransferComparison:

    if not isfinite(
        hit_cost
    ):
        raise DecisionError(
            "hit_cost must be finite"
        )

    if hit_cost < 0.0:
        raise DecisionError(
            "hit_cost cannot be negative"
        )

    if (
        sell.first_gameweek
        != buy.first_gameweek
        or sell.last_gameweek
        != buy.last_gameweek
    ):
        raise DecisionError(
            "sell and buy horizons "
            "must match"
        )

    sell_value = (
        sell.weighted_expected_points
    )

    buy_value = (
        buy.weighted_expected_points
    )

    gross_gain = (
        buy_value
        - sell_value
    )

    net_gain = (
        gross_gain
        - hit_cost
    )

    return TransferComparison(
        sell_player_id=(
            sell.player_id
        ),
        buy_player_id=(
            buy.player_id
        ),
        sell_value=sell_value,
        buy_value=buy_value,
        gross_gain=gross_gain,
        hit_cost=hit_cost,
        net_gain=net_gain,
    )
