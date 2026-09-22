from __future__ import annotations

from dataclasses import dataclass
from math import isclose
from typing import Iterable, Mapping

from .horizon import (
    DEFAULT_WEIGHTS,
    DecisionError,
    GameweekProjection,
    HorizonValue,
    horizon_value,
)


@dataclass(frozen=True)
class PlayerDecisionProjection:
    player_id: str
    current_gameweek: int

    horizon_3: HorizonValue
    horizon_6: HorizonValue

    expected_minutes_next_3: float
    expected_minutes_next_6: float

    projection_confidence: float
    projection_uncertainty: float

    gameweeks: tuple[
        GameweekProjection,
        ...
    ] = ()


def horizon_weights(
    horizon: int,
) -> Mapping[int, float]:

    if horizon not in {
        1,
        3,
        6,
    }:
        raise DecisionError(
            "supported horizons are "
            "1, 3 and 6 gameweeks"
        )

    return {
        offset: DEFAULT_WEIGHTS[offset]
        for offset in range(horizon)
    }


def gameweek_projections_from_row(
    row: Mapping,
) -> tuple[
    GameweekProjection,
    ...,
]:

    player_id = str(
        row["player_id"]
    )

    raw_gameweeks = row.get(
        "gameweeks"
    )

    if not isinstance(
        raw_gameweeks,
        list,
    ):
        raise DecisionError(
            "player projection must contain "
            "a gameweeks list"
        )

    result = []

    for gameweek in raw_gameweeks:

        if not isinstance(
            gameweek,
            Mapping,
        ):
            raise DecisionError(
                "gameweek projection must "
                "be a mapping"
            )

        nested_player_id = str(
            gameweek.get(
                "player_id",
                player_id,
            )
        )

        if nested_player_id != player_id:
            raise DecisionError(
                "nested player_id does not "
                "match top-level player_id"
            )

        result.append(
            GameweekProjection(
                player_id=player_id,
                gameweek=int(
                    gameweek[
                        "target_gameweek"
                    ]
                ),
                expected_points=float(
                    gameweek[
                        "expected_points"
                    ]
                ),
            )
        )

    if not result:
        raise DecisionError(
            "player has no gameweek projections"
        )

    return tuple(
        result
    )


def _check_pipeline_value(
    *,
    calculated: float,
    stored,
    field: str,
    tolerance: float = 1e-8,
) -> None:

    if stored is None:
        return

    stored_value = float(
        stored
    )

    if not isclose(
        calculated,
        stored_value,
        rel_tol=tolerance,
        abs_tol=tolerance,
    ):
        raise DecisionError(
            f"{field} mismatch: "
            f"calculated={calculated:.12f}, "
            f"stored={stored_value:.12f}"
        )


def adapt_player_projection(
    row: Mapping,
    *,
    validate_pipeline_totals: bool = True,
) -> PlayerDecisionProjection:

    current_gameweek = int(
        row["current_gameweek"]
    )

    projections = (
        gameweek_projections_from_row(
            row
        )
    )

    horizon_3 = horizon_value(
        projections,
        first_gameweek=current_gameweek,
        weights=horizon_weights(
            3
        ),
    )

    horizon_6 = horizon_value(
        projections,
        first_gameweek=current_gameweek,
        weights=horizon_weights(
            6
        ),
    )

    if validate_pipeline_totals:

        _check_pipeline_value(
            calculated=(
                horizon_3
                .weighted_expected_points
            ),
            stored=row.get(
                "weighted_ev_next_3"
            ),
            field=(
                "weighted_ev_next_3"
            ),
        )

        _check_pipeline_value(
            calculated=(
                horizon_6
                .weighted_expected_points
            ),
            stored=row.get(
                "weighted_ev_next_6"
            ),
            field=(
                "weighted_ev_next_6"
            ),
        )

        _check_pipeline_value(
            calculated=(
                horizon_3
                .raw_expected_points
            ),
            stored=row.get(
                "ev_next_3"
            ),
            field="ev_next_3",
        )

        _check_pipeline_value(
            calculated=(
                horizon_6
                .raw_expected_points
            ),
            stored=row.get(
                "ev_next_6"
            ),
            field="ev_next_6",
        )

    return PlayerDecisionProjection(
        player_id=str(
            row["player_id"]
        ),
        current_gameweek=(
            current_gameweek
        ),
        horizon_3=horizon_3,
        horizon_6=horizon_6,
        expected_minutes_next_3=float(
            row.get(
                "expected_minutes_next_3",
                0.0,
            )
        ),
        expected_minutes_next_6=float(
            row.get(
                "expected_minutes_next_6",
                0.0,
            )
        ),
        projection_confidence=float(
            row.get(
                "projection_confidence",
                0.0,
            )
        ),
        projection_uncertainty=float(
            row.get(
                "projection_uncertainty",
                1.0,
            )
        ),
        gameweeks=projections,
    )


def adapt_player_projections(
    rows: Iterable[Mapping],
) -> tuple[
    PlayerDecisionProjection,
    ...,
]:
    return tuple(
        adapt_player_projection(
            row
        )
        for row in rows
    )


def rank_player_projections(
    players: Iterable[
        PlayerDecisionProjection
    ],
    *,
    horizon: int,
) -> tuple[
    PlayerDecisionProjection,
    ...,
]:

    if horizon == 3:
        key = lambda row: (
            row.horizon_3
            .weighted_expected_points
        )

    elif horizon == 6:
        key = lambda row: (
            row.horizon_6
            .weighted_expected_points
        )

    else:
        raise DecisionError(
            "ranking horizon must be 3 or 6"
        )

    return tuple(
        sorted(
            players,
            key=key,
            reverse=True,
        )
    )
