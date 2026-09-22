from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import numpy as np

from scipy.optimize import (
    Bounds,
    LinearConstraint,
    milp,
)

from .appearance import (
    gameweek_appearance,
)

from .captaincy_value import (
    effective_captain_bonus,
)

from .horizon import (
    DecisionError,
)

from .projection_adapter import (
    PlayerDecisionProjection,
    horizon_weights,
)


@dataclass(frozen=True)
class GameweekCaptaincyV2:
    """
    Joint XI + captain + vice-captain solution
    for one gameweek.
    """

    gameweek: int

    starting_xi_player_ids: tuple[
        str,
        ...,
    ]

    captain_player_id: str

    vice_player_id: str

    xi_ev: float

    captain_bonus_ev: float

    total_ev: float


@dataclass(frozen=True)
class CaptaincyHorizonEvaluationV2:
    horizon: int

    first_gameweek: int

    last_gameweek: int

    weighted_xi_ev: float

    weighted_captain_bonus_ev: float

    weighted_total_ev: float

    gameweeks: tuple[
        GameweekCaptaincyV2,
        ...,
    ]


def _points_by_gameweek(
    projection: PlayerDecisionProjection,
) -> dict[int, float]:

    return {
        row.gameweek: float(
            row.expected_points
        )
        for row
        in projection.gameweeks
    }


def evaluate_squad_with_captaincy_v2(
    *,
    squad_player_ids: set[str]
        | frozenset[str],
    players_by_id: Mapping[
        str,
        object,
    ],
    projections_by_id: Mapping[
        str,
        PlayerDecisionProjection,
    ],
    appearance_by_player_gameweek:
        Mapping[
            str,
            Mapping[int, float],
        ],
    horizon: int,
) -> CaptaincyHorizonEvaluationV2:
    """
    Exact fixed-squad XI + C + VC optimization.

    Objective per GW:

        XI EV
        + EV(C)
        + P(C DNP) * EV(VC)

    where EV(C) and EV(VC) are unconditional
    projection EVs.

    Captain and vice-captain must both belong
    to the starting XI and must be different.

    All FPL positions are eligible for C/VC.
    """

    if horizon not in {
        1,
        3,
        6,
    }:

        raise DecisionError(
            "captaincy V2 horizon must "
            "be 1, 3 or 6"
        )


    squad_ids = frozenset(
        str(player_id)
        for player_id
        in squad_player_ids
    )


    if len(squad_ids) != 15:

        raise DecisionError(
            "captaincy evaluation requires "
            "a 15-player FPL squad"
        )


    missing_players = (
        squad_ids
        - set(players_by_id)
    )

    if missing_players:

        raise DecisionError(
            "missing player values for: "
            + ", ".join(
                sorted(
                    missing_players
                )
            )
        )


    missing_projections = (
        squad_ids
        - set(projections_by_id)
    )

    if missing_projections:

        raise DecisionError(
            "missing player projections for: "
            + ", ".join(
                sorted(
                    missing_projections
                )
            )
        )


    current_gameweeks = {
        projections_by_id[
            player_id
        ].current_gameweek
        for player_id
        in squad_ids
    }


    if len(current_gameweeks) != 1:

        raise DecisionError(
            "inconsistent current_gameweek"
        )


    first_gameweek = next(
        iter(
            current_gameweeks
        )
    )


    weights = dict(
        horizon_weights(
            horizon
        )
    )


    rows = sorted(
        (
            players_by_id[
                player_id
            ]
            for player_id
            in squad_ids
        ),
        key=lambda row: str(
            row.player_id
        ),
    )


    n = len(rows)


    projection_points = {
        row.player_id:
        _points_by_gameweek(
            projections_by_id[
                row.player_id
            ]
        )
        for row
        in rows
    }


    results = []

    weighted_xi = 0.0

    weighted_captain_bonus = 0.0


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
                for row
                in rows
            ],
            dtype=float,
        )


        p_appearance = np.array(
            [
                gameweek_appearance(
                    appearance_by_player_gameweek,
                    player_id=(
                        row.player_id
                    ),
                    gameweek=gameweek,
                )
                for row
                in rows
            ],
            dtype=float,
        )


        p_dnp = (
            1.0
            - p_appearance
        )


        #
        # Variables
        # ---------
        #
        # [0:n]     starter_i
        # [n:2n]    captain_i
        # [2n:3n]   vice_i
        # [3n:4n]   fallback_i
        #
        # fallback_i =
        #
        #   vice_i
        #   *
        #   P(selected captain DNP)
        #
        # It is continuous [0,1].
        #
        starter_base = 0

        captain_base = n

        vice_base = 2 * n

        fallback_base = 3 * n

        total_variables = (
            4 * n
        )


        def starter(index):
            return (
                starter_base
                + index
            )


        def captain(index):
            return (
                captain_base
                + index
            )


        def vice(index):
            return (
                vice_base
                + index
            )


        def fallback(index):
            return (
                fallback_base
                + index
            )


        #
        # We minimize in scipy.milp.
        #
        # XI:
        #   starter_i * EV_i
        #
        # Captain:
        #   captain_i * EV_i
        #
        # Vice fallback:
        #   fallback_i * EV_i
        #
        objective = np.zeros(
            total_variables,
            dtype=float,
        )


        for index in range(n):

            objective[
                starter(index)
            ] = -points[index]

            objective[
                captain(index)
            ] = -points[index]

            objective[
                fallback(index)
            ] = -points[index]


        constraints = []


        #
        # Exactly 11 starters.
        #
        vector = np.zeros(
            total_variables
        )

        for index in range(n):
            vector[
                starter(index)
            ] = 1.0

        constraints.append(
            LinearConstraint(
                vector,
                lb=11.0,
                ub=11.0,
            )
        )


        #
        # Legal FPL formation.
        #
        for position, (
            minimum,
            maximum,
        ) in {
            "GK": (1, 1),
            "DEF": (3, 5),
            "MID": (2, 5),
            "FWD": (1, 3),
        }.items():

            vector = np.zeros(
                total_variables
            )

            for index, row in enumerate(
                rows
            ):

                if (
                    row.position
                    == position
                ):

                    vector[
                        starter(index)
                    ] = 1.0


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


        #
        # Exactly one captain.
        #
        vector = np.zeros(
            total_variables
        )

        for index in range(n):
            vector[
                captain(index)
            ] = 1.0

        constraints.append(
            LinearConstraint(
                vector,
                lb=1.0,
                ub=1.0,
            )
        )


        #
        # Exactly one vice.
        #
        vector = np.zeros(
            total_variables
        )

        for index in range(n):
            vector[
                vice(index)
            ] = 1.0

        constraints.append(
            LinearConstraint(
                vector,
                lb=1.0,
                ub=1.0,
            )
        )


        for index in range(n):

            #
            # Captain must start:
            #
            # captain_i <= starter_i
            #
            vector = np.zeros(
                total_variables
            )

            vector[
                captain(index)
            ] = 1.0

            vector[
                starter(index)
            ] = -1.0

            constraints.append(
                LinearConstraint(
                    vector,
                    lb=-np.inf,
                    ub=0.0,
                )
            )


            #
            # Vice must start:
            #
            # vice_i <= starter_i
            #
            vector = np.zeros(
                total_variables
            )

            vector[
                vice(index)
            ] = 1.0

            vector[
                starter(index)
            ] = -1.0

            constraints.append(
                LinearConstraint(
                    vector,
                    lb=-np.inf,
                    ub=0.0,
                )
            )


            #
            # C != VC
            #
            # captain_i + vice_i <= 1
            #
            vector = np.zeros(
                total_variables
            )

            vector[
                captain(index)
            ] = 1.0

            vector[
                vice(index)
            ] = 1.0

            constraints.append(
                LinearConstraint(
                    vector,
                    lb=-np.inf,
                    ub=1.0,
                )
            )


        #
        # Exact vice fallback linearization.
        #
        # d =
        #   sum_j
        #   P(DNP_j) * captain_j
        #
        # Since exactly one captain is selected,
        # d is exactly P(selected captain DNP).
        #
        # fallback_i = vice_i * d
        #
        for index in range(n):

            #
            # fallback_i <= vice_i
            #
            vector = np.zeros(
                total_variables
            )

            vector[
                fallback(index)
            ] = 1.0

            vector[
                vice(index)
            ] = -1.0

            constraints.append(
                LinearConstraint(
                    vector,
                    lb=-np.inf,
                    ub=0.0,
                )
            )


            #
            # fallback_i <= d
            #
            vector = np.zeros(
                total_variables
            )

            vector[
                fallback(index)
            ] = 1.0

            for captain_index in range(
                n
            ):

                vector[
                    captain(
                        captain_index
                    )
                ] -= (
                    p_dnp[
                        captain_index
                    ]
                )


            constraints.append(
                LinearConstraint(
                    vector,
                    lb=-np.inf,
                    ub=0.0,
                )
            )


            #
            # fallback_i >=
            # d + vice_i - 1
            #
            # equivalent:
            #
            # fallback_i
            # - d
            # - vice_i
            # >= -1
            #
            vector = np.zeros(
                total_variables
            )

            vector[
                fallback(index)
            ] = 1.0

            vector[
                vice(index)
            ] = -1.0

            for captain_index in range(
                n
            ):

                vector[
                    captain(
                        captain_index
                    )
                ] -= (
                    p_dnp[
                        captain_index
                    ]
                )


            constraints.append(
                LinearConstraint(
                    vector,
                    lb=-1.0,
                    ub=np.inf,
                )
            )


        #
        # starter / captain / vice are binary.
        #
        # fallback is continuous.
        #
        integrality = np.ones(
            total_variables,
            dtype=int,
        )

        integrality[
            fallback_base:
            fallback_base + n
        ] = 0


        solved = milp(
            c=objective,
            integrality=integrality,
            bounds=Bounds(
                np.zeros(
                    total_variables
                ),
                np.ones(
                    total_variables
                ),
            ),
            constraints=constraints,
        )


        if not solved.success:

            raise DecisionError(
                "no legal C+VC XI for "
                f"GW{gameweek}: "
                f"{solved.message}"
            )


        starters = tuple(
            sorted(
                rows[index].player_id
                for index
                in range(n)
                if solved.x[
                    starter(index)
                ] >= 0.5
            )
        )


        captain_ids = [
            rows[index].player_id
            for index
            in range(n)
            if solved.x[
                captain(index)
            ] >= 0.5
        ]


        vice_ids = [
            rows[index].player_id
            for index
            in range(n)
            if solved.x[
                vice(index)
            ] >= 0.5
        ]


        if len(
            captain_ids
        ) != 1:

            raise DecisionError(
                "optimizer did not select "
                "exactly one captain"
            )


        if len(
            vice_ids
        ) != 1:

            raise DecisionError(
                "optimizer did not select "
                "exactly one vice-captain"
            )


        captain_id = (
            captain_ids[0]
        )

        vice_id = (
            vice_ids[0]
        )


        if (
            captain_id
            == vice_id
        ):

            raise DecisionError(
                "captain and vice-captain "
                "must differ"
            )


        if (
            captain_id
            not in starters
            or vice_id
            not in starters
        ):

            raise DecisionError(
                "captain and vice-captain "
                "must belong to XI"
            )


        xi_ev = sum(
            projection_points[
                player_id
            ].get(
                gameweek,
                0.0,
            )
            for player_id
            in starters
        )


        captain_ev = (
            projection_points[
                captain_id
            ].get(
                gameweek,
                0.0,
            )
        )


        vice_ev = (
            projection_points[
                vice_id
            ].get(
                gameweek,
                0.0,
            )
        )


        captain_p_appearance = (
            gameweek_appearance(
                appearance_by_player_gameweek,
                player_id=captain_id,
                gameweek=gameweek,
            )
        )


        captain_bonus = (
            effective_captain_bonus(
                captain_ev=captain_ev,
                vice_ev=vice_ev,
                captain_p_appearance=(
                    captain_p_appearance
                ),
            )
        )


        weight = weights[
            offset
        ]


        weighted_xi += (
            weight
            * xi_ev
        )


        weighted_captain_bonus += (
            weight
            * captain_bonus
        )


        results.append(
            GameweekCaptaincyV2(
                gameweek=gameweek,
                starting_xi_player_ids=(
                    starters
                ),
                captain_player_id=(
                    captain_id
                ),
                vice_player_id=(
                    vice_id
                ),
                xi_ev=float(
                    xi_ev
                ),
                captain_bonus_ev=float(
                    captain_bonus
                ),
                total_ev=float(
                    xi_ev
                    + captain_bonus
                ),
            )
        )


    return (
        CaptaincyHorizonEvaluationV2(
            horizon=horizon,
            first_gameweek=(
                first_gameweek
            ),
            last_gameweek=(
                first_gameweek
                + horizon
                - 1
            ),
            weighted_xi_ev=float(
                weighted_xi
            ),
            weighted_captain_bonus_ev=float(
                weighted_captain_bonus
            ),
            weighted_total_ev=float(
                weighted_xi
                + weighted_captain_bonus
            ),
            gameweeks=tuple(
                results
            ),
        )
    )
