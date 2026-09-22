from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import numpy as np
from scipy.optimize import (
    Bounds,
    LinearConstraint,
    milp,
)

from .horizon import DecisionError
from .projection_adapter import (
    PlayerDecisionProjection,
    horizon_weights,
)
from .value import PlayerValue


@dataclass(frozen=True)
class GameweekCaptaincy:
    gameweek: int

    starting_xi_player_ids: tuple[
        str,
        ...
    ]

    captain_player_id: str

    xi_ev: float
    captain_bonus_ev: float
    total_ev: float


@dataclass(frozen=True)
class CaptaincyHorizonEvaluation:
    horizon: int

    first_gameweek: int
    last_gameweek: int

    weighted_xi_ev: float
    weighted_captain_bonus_ev: float
    weighted_total_ev: float

    gameweeks: tuple[
        GameweekCaptaincy,
        ...
    ]


def _points_by_gameweek(
    projection: PlayerDecisionProjection,
) -> dict[int, float]:

    return {
        row.gameweek: float(
            row.expected_points
        )
        for row in projection.gameweeks
    }


def evaluate_squad_with_captaincy(
    *,
    squad_player_ids: set[str]
        | frozenset[str],
    players_by_id: Mapping[
        str,
        PlayerValue,
    ],
    projections_by_id: Mapping[
        str,
        PlayerDecisionProjection,
    ],
    horizon: int,
) -> CaptaincyHorizonEvaluation:

    if horizon not in {
        3,
        6,
    }:
        raise DecisionError(
            "horizon must be 3 or 6"
        )

    squad_ids = set(
        squad_player_ids
    )

    if len(squad_ids) != 15:
        raise DecisionError(
            "captaincy evaluation requires "
            "a 15-player FPL squad"
        )

    missing_values = (
        squad_ids
        - set(players_by_id)
    )

    if missing_values:
        raise DecisionError(
            "missing player values"
        )

    missing_projections = (
        squad_ids
        - set(projections_by_id)
    )

    if missing_projections:
        raise DecisionError(
            "missing player projections"
        )

    current_gws = {
        projections_by_id[
            player_id
        ].current_gameweek
        for player_id in squad_ids
    }

    if len(current_gws) != 1:
        raise DecisionError(
            "inconsistent current_gameweek"
        )

    first_gameweek = next(
        iter(current_gws)
    )

    weights = dict(
        horizon_weights(
            horizon
        )
    )

    rows = [
        players_by_id[
            player_id
        ]
        for player_id in sorted(
            squad_ids
        )
    ]

    n = len(rows)

    projection_points = {
        row.player_id: (
            _points_by_gameweek(
                projections_by_id[
                    row.player_id
                ]
            )
        )
        for row in rows
    }

    results = []

    weighted_xi = 0.0
    weighted_captain = 0.0

    for offset in range(
        horizon
    ):

        gameweek = (
            first_gameweek
            + offset
        )

        points = np.array(
            [
                projection_points[
                    row.player_id
                ].get(
                    gameweek,
                    0.0,
                )
                for row in rows
            ],
            dtype=float,
        )

        # Variables:
        # [0:n]   = starting XI
        # [n:2n]  = captain
        #
        # Objective:
        # XI points + captain's extra copy.
        objective = np.concatenate(
            (
                -points,
                -points,
            )
        )

        constraints = []

        starter_total = np.concatenate(
            (
                np.ones(n),
                np.zeros(n),
            )
        )

        constraints.append(
            LinearConstraint(
                starter_total,
                lb=11.0,
                ub=11.0,
            )
        )

        for position, (
            minimum,
            maximum,
        ) in {
            "GK": (1, 1),
            "DEF": (3, 5),
            "MID": (2, 5),
            "FWD": (1, 3),
        }.items():

            vector = np.concatenate(
                (
                    np.array(
                        [
                            1.0
                            if row.position
                            == position
                            else 0.0
                            for row in rows
                        ]
                    ),
                    np.zeros(n),
                )
            )

            constraints.append(
                LinearConstraint(
                    vector,
                    lb=float(
                        minimum
                    ),
                    ub=float(
                        maximum
                    ),
                )
            )

        captain_total = np.concatenate(
            (
                np.zeros(n),
                np.ones(n),
            )
        )

        constraints.append(
            LinearConstraint(
                captain_total,
                lb=1.0,
                ub=1.0,
            )
        )

        # Captain must be in starting XI:
        # captain_i <= starter_i
        for index in range(n):

            vector = np.zeros(
                2 * n
            )

            vector[index] = -1.0
            vector[n + index] = 1.0

            constraints.append(
                LinearConstraint(
                    vector,
                    lb=-np.inf,
                    ub=0.0,
                )
            )

        solved = milp(
            c=objective,
            integrality=np.ones(
                2 * n,
                dtype=int,
            ),
            bounds=Bounds(
                np.zeros(
                    2 * n
                ),
                np.ones(
                    2 * n
                ),
            ),
            constraints=constraints,
            options={
                "disp": False,
            },
        )

        if not solved.success:
            raise DecisionError(
                f"no legal XI for GW"
                f"{gameweek}"
            )

        starters = tuple(
            sorted(
                rows[index].player_id
                for index in range(n)
                if solved.x[
                    index
                ] >= 0.5
            )
        )

        captains = [
            rows[index].player_id
            for index in range(n)
            if solved.x[
                n + index
            ] >= 0.5
        ]

        if len(captains) != 1:
            raise DecisionError(
                "optimizer did not select "
                "exactly one captain"
            )

        captain = captains[0]

        xi_ev = sum(
            projection_points[
                player_id
            ].get(
                gameweek,
                0.0,
            )
            for player_id in starters
        )

        captain_ev = (
            projection_points[
                captain
            ].get(
                gameweek,
                0.0,
            )
        )

        weight = weights[
            offset
        ]

        weighted_xi += (
            xi_ev
            * weight
        )

        weighted_captain += (
            captain_ev
            * weight
        )

        results.append(
            GameweekCaptaincy(
                gameweek=gameweek,
                starting_xi_player_ids=(
                    starters
                ),
                captain_player_id=(
                    captain
                ),
                xi_ev=xi_ev,
                captain_bonus_ev=(
                    captain_ev
                ),
                total_ev=(
                    xi_ev
                    + captain_ev
                ),
            )
        )

    return CaptaincyHorizonEvaluation(
        horizon=horizon,
        first_gameweek=(
            first_gameweek
        ),
        last_gameweek=(
            first_gameweek
            + horizon
            - 1
        ),
        weighted_xi_ev=(
            weighted_xi
        ),
        weighted_captain_bonus_ev=(
            weighted_captain
        ),
        weighted_total_ev=(
            weighted_xi
            + weighted_captain
        ),
        gameweeks=tuple(
            results
        ),
    )
