from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Iterable, Mapping

from .horizon import DecisionError
from .projection_adapter import (
    PlayerDecisionProjection,
)


VALID_POSITIONS = frozenset(
    {
        "GK",
        "DEF",
        "MID",
        "FWD",
    }
)


@dataclass(frozen=True)
class PlayerValue:
    player_id: str
    name: str
    position: str

    team_id: str
    provider_team_id: str | None

    price_tenths: int
    price_m: float

    ev_3: float
    ev_6: float

    value_3: float
    value_6: float

    minutes_3: float
    minutes_6: float

    confidence: float
    uncertainty: float


def build_player_value(
    projection: PlayerDecisionProjection,
    metadata: Mapping,
) -> PlayerValue:

    player_id = str(
        metadata.get(
            "player_id",
            projection.player_id,
        )
    )

    if player_id != projection.player_id:
        raise DecisionError(
            "projection/metadata player_id mismatch"
        )

    position = str(
        metadata.get(
            "position",
            "",
        )
    ).upper()

    if position not in VALID_POSITIONS:
        raise DecisionError(
            f"invalid FPL position: {position!r}"
        )

    price_tenths = int(
        metadata["current_price"]
    )

    if price_tenths <= 0:
        raise DecisionError(
            "current_price must be positive"
        )

    price_m = (
        price_tenths / 10.0
    )

    ev_3 = float(
        projection
        .horizon_3
        .weighted_expected_points
    )

    ev_6 = float(
        projection
        .horizon_6
        .weighted_expected_points
    )

    return PlayerValue(
        player_id=projection.player_id,
        name=str(
            metadata.get(
                "display_name",
                projection.player_id,
            )
        ),
        position=position,
        team_id=str(
            metadata["team_id"]
        ),
        provider_team_id=(
            str(
                metadata[
                    "provider_team_id"
                ]
            )
            if metadata.get(
                "provider_team_id"
            )
            is not None
            else None
        ),
        price_tenths=price_tenths,
        price_m=price_m,
        ev_3=ev_3,
        ev_6=ev_6,
        value_3=(
            ev_3 / price_m
        ),
        value_6=(
            ev_6 / price_m
        ),
        minutes_3=float(
            projection
            .expected_minutes_next_3
        ),
        minutes_6=float(
            projection
            .expected_minutes_next_6
        ),
        confidence=float(
            projection
            .projection_confidence
        ),
        uncertainty=float(
            projection
            .projection_uncertainty
        ),
    )


def build_player_values(
    projections: Iterable[
        PlayerDecisionProjection
    ],
    metadata_by_player: Mapping[
        str,
        Mapping,
    ],
) -> tuple[
    PlayerValue,
    ...,
]:

    result = []

    for projection in projections:

        metadata = (
            metadata_by_player.get(
                projection.player_id
            )
        )

        if metadata is None:
            raise DecisionError(
                "missing current-player metadata "
                f"for {projection.player_id}"
            )

        result.append(
            build_player_value(
                projection,
                metadata,
            )
        )

    return tuple(
        result
    )


def rank_player_values(
    players: Iterable[
        PlayerValue
    ],
    *,
    position: str,
    metric: str = "ev6",
    max_price_m: float | None = None,
    min_minutes: float = 0.0,
) -> tuple[
    PlayerValue,
    ...,
]:

    position = (
        position.upper()
    )

    if position not in VALID_POSITIONS:
        raise DecisionError(
            f"invalid FPL position: {position}"
        )

    valid_metrics = {
        "ev3",
        "ev6",
        "value3",
        "value6",
    }

    if metric not in valid_metrics:
        raise DecisionError(
            "metric must be one of "
            "ev3, ev6, value3, value6"
        )

    if (
        max_price_m is not None
        and (
            not isfinite(
                max_price_m
            )
            or max_price_m <= 0
        )
    ):
        raise DecisionError(
            "max_price_m must be positive"
        )

    if (
        not isfinite(
            min_minutes
        )
        or min_minutes < 0
    ):
        raise DecisionError(
            "min_minutes must be "
            "finite and non-negative"
        )

    rows = [
        player
        for player in players
        if player.position
        == position
    ]

    if max_price_m is not None:
        rows = [
            player
            for player in rows
            if player.price_m
            <= max_price_m
        ]

    horizon_minutes = (
        "minutes_3"
        if metric
        in {
            "ev3",
            "value3",
        }
        else "minutes_6"
    )

    rows = [
        player
        for player in rows
        if getattr(
            player,
            horizon_minutes,
        )
        >= min_minutes
    ]

    key_name = {
        "ev3": "ev_3",
        "ev6": "ev_6",
        "value3": "value_3",
        "value6": "value_6",
    }[metric]

    return tuple(
        sorted(
            rows,
            key=lambda player: (
                getattr(
                    player,
                    key_name,
                ),
                player.confidence,
                -player.price_m,
            ),
            reverse=True,
        )
    )
