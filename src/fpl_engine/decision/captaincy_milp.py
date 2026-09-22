from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping

import numpy as np

from scipy.optimize import LinearConstraint

from .appearance import gameweek_appearance

from .captaincy_value import (
    effective_captain_bonus,
)

from .horizon import DecisionError


@dataclass(frozen=True)
class CaptaincyMILPLayout:
    enabled: bool
    horizon: int
    n_players: int

    captain_base: int
    vice_base: int
    fallback_base: int

    total_variables: int

    def captain(
        self,
        offset: int,
        index: int,
    ) -> int:

        if not self.enabled:
            raise DecisionError(
                "captaincy MILP layout disabled"
            )

        return (
            self.captain_base
            + offset * self.n_players
            + index
        )

    def vice(
        self,
        offset: int,
        index: int,
    ) -> int:

        if not self.enabled:
            raise DecisionError(
                "captaincy MILP layout disabled"
            )

        return (
            self.vice_base
            + offset * self.n_players
            + index
        )

    def fallback(
        self,
        offset: int,
        index: int,
    ) -> int:

        if not self.enabled:
            raise DecisionError(
                "captaincy MILP layout disabled"
            )

        return (
            self.fallback_base
            + offset * self.n_players
            + index
        )


def allocate_captaincy_layout(
    *,
    base_total_variables: int,
    horizon: int,
    n_players: int,
    enabled: bool,
) -> CaptaincyMILPLayout:

    if not enabled:

        return CaptaincyMILPLayout(
            enabled=False,
            horizon=horizon,
            n_players=n_players,
            captain_base=-1,
            vice_base=-1,
            fallback_base=-1,
            total_variables=(
                base_total_variables
            ),
        )


    captain_base = (
        base_total_variables
    )

    vice_base = (
        captain_base
        + horizon * n_players
    )

    fallback_base = (
        vice_base
        + horizon * n_players
    )

    total_variables = (
        fallback_base
        + horizon * n_players
    )


    return CaptaincyMILPLayout(
        enabled=True,
        horizon=horizon,
        n_players=n_players,
        captain_base=captain_base,
        vice_base=vice_base,
        fallback_base=fallback_base,
        total_variables=total_variables,
    )


def add_captaincy_objective(
    *,
    objective: np.ndarray,
    layout: CaptaincyMILPLayout,
    gameweeks,
    weights,
    player_ids,
    points_by_player_gameweek,
    captaincy_weight: float,
    legacy_captain_index: (
        Callable[[int, int], int]
        | None
    ) = None,
) -> None:

    if not layout.enabled:
        return


    for offset, gameweek in enumerate(
        gameweeks
    ):

        weight = float(
            weights[offset]
        )


        for index, player_id in enumerate(
            player_ids
        ):

            points = float(
                points_by_player_gameweek[
                    player_id
                ].get(
                    gameweek,
                    0.0,
                )
            )


            #
            # Disable the old captain-only
            # objective when rolling transfers
            # uses the V2 path.
            #
            if (
                legacy_captain_index
                is not None
            ):

                objective[
                    legacy_captain_index(
                        offset,
                        index,
                    )
                ] = 0.0


            objective[
                layout.captain(
                    offset,
                    index,
                )
            ] = -(
                captaincy_weight
                * weight
                * points
            )


            objective[
                layout.fallback(
                    offset,
                    index,
                )
            ] = -(
                captaincy_weight
                * weight
                * points
            )


def append_captaincy_constraints(
    *,
    constraints: list,
    layout: CaptaincyMILPLayout,
    total_variables: int,
    gameweeks,
    player_ids,
    starter_index:
        Callable[[int, int], int],
    appearance_by_player_gameweek:
        Mapping[
            str,
            Mapping[int, float],
        ],
) -> None:

    if not layout.enabled:
        return


    n = layout.n_players


    for offset, gameweek in enumerate(
        gameweeks
    ):

        #
        # Exactly one captain.
        #
        vector = np.zeros(
            total_variables
        )

        for index in range(n):

            vector[
                layout.captain(
                    offset,
                    index,
                )
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
                layout.vice(
                    offset,
                    index,
                )
            ] = 1.0


        constraints.append(
            LinearConstraint(
                vector,
                lb=1.0,
                ub=1.0,
            )
        )


        p_dnp = np.array(
            [
                1.0
                - gameweek_appearance(
                    appearance_by_player_gameweek,
                    player_id=player_id,
                    gameweek=gameweek,
                )
                for player_id
                in player_ids
            ],
            dtype=float,
        )


        for index in range(n):

            #
            # C <= XI
            #
            vector = np.zeros(
                total_variables
            )

            vector[
                layout.captain(
                    offset,
                    index,
                )
            ] = 1.0

            vector[
                starter_index(
                    offset,
                    index,
                )
            ] = -1.0


            constraints.append(
                LinearConstraint(
                    vector,
                    lb=-np.inf,
                    ub=0.0,
                )
            )


            #
            # VC <= XI
            #
            vector = np.zeros(
                total_variables
            )

            vector[
                layout.vice(
                    offset,
                    index,
                )
            ] = 1.0

            vector[
                starter_index(
                    offset,
                    index,
                )
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
            vector = np.zeros(
                total_variables
            )

            vector[
                layout.captain(
                    offset,
                    index,
                )
            ] = 1.0

            vector[
                layout.vice(
                    offset,
                    index,
                )
            ] = 1.0


            constraints.append(
                LinearConstraint(
                    vector,
                    lb=-np.inf,
                    ub=1.0,
                )
            )


            #
            # z_i =
            # VC_i * P(selected captain DNP)
            #
            # McCormick is exact here because
            # VC_i is binary and d is in [0,1].
            #

            # z_i <= VC_i
            vector = np.zeros(
                total_variables
            )

            vector[
                layout.fallback(
                    offset,
                    index,
                )
            ] = 1.0

            vector[
                layout.vice(
                    offset,
                    index,
                )
            ] = -1.0


            constraints.append(
                LinearConstraint(
                    vector,
                    lb=-np.inf,
                    ub=0.0,
                )
            )


            # z_i <= d
            vector = np.zeros(
                total_variables
            )

            vector[
                layout.fallback(
                    offset,
                    index,
                )
            ] = 1.0


            for captain_index in range(
                n
            ):

                vector[
                    layout.captain(
                        offset,
                        captain_index,
                    )
                ] -= p_dnp[
                    captain_index
                ]


            constraints.append(
                LinearConstraint(
                    vector,
                    lb=-np.inf,
                    ub=0.0,
                )
            )


            # z_i >= d + VC_i - 1
            vector = np.zeros(
                total_variables
            )

            vector[
                layout.fallback(
                    offset,
                    index,
                )
            ] = 1.0

            vector[
                layout.vice(
                    offset,
                    index,
                )
            ] = -1.0


            for captain_index in range(
                n
            ):

                vector[
                    layout.captain(
                        offset,
                        captain_index,
                    )
                ] -= p_dnp[
                    captain_index
                ]


            constraints.append(
                LinearConstraint(
                    vector,
                    lb=-1.0,
                    ub=np.inf,
                )
            )


def captaincy_integrality(
    *,
    total_variables: int,
    layout: CaptaincyMILPLayout,
) -> np.ndarray:

    integrality = np.ones(
        total_variables,
        dtype=int,
    )


    if layout.enabled:

        start = (
            layout.fallback_base
        )

        end = (
            start
            + layout.horizon
            * layout.n_players
        )

        #
        # McCormick fallback variables
        # are continuous.
        #
        integrality[
            start:end
        ] = 0


    return integrality


def extract_captaincy_pair(
    *,
    solution,
    layout: CaptaincyMILPLayout,
    offset: int,
    gameweek: int,
    player_ids,
    points_by_player_gameweek,
    appearance_by_player_gameweek,
):

    if not layout.enabled:

        raise DecisionError(
            "captaincy solution requested "
            "from disabled layout"
        )


    captain_ids = [
        player_ids[index]
        for index
        in range(
            layout.n_players
        )
        if solution[
            layout.captain(
                offset,
                index,
            )
        ] >= 0.5
    ]


    vice_ids = [
        player_ids[index]
        for index
        in range(
            layout.n_players
        )
        if solution[
            layout.vice(
                offset,
                index,
            )
        ] >= 0.5
    ]


    if len(captain_ids) != 1:

        raise DecisionError(
            "expected exactly one V2 captain"
        )


    if len(vice_ids) != 1:

        raise DecisionError(
            "expected exactly one "
            "V2 vice-captain"
        )


    captain_id = captain_ids[0]

    vice_id = vice_ids[0]


    if captain_id == vice_id:

        raise DecisionError(
            "captain and vice must differ"
        )


    captain_ev = float(
        points_by_player_gameweek[
            captain_id
        ].get(
            gameweek,
            0.0,
        )
    )


    vice_ev = float(
        points_by_player_gameweek[
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


    bonus = (
        effective_captain_bonus(
            captain_ev=captain_ev,
            vice_ev=vice_ev,
            captain_p_appearance=(
                captain_p_appearance
            ),
        )
    )


    return (
        captain_id,
        vice_id,
        float(bonus),
    )
