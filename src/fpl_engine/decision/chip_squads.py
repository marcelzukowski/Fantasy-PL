from __future__ import annotations

from .captaincy_milp import (
    add_captaincy_objective,
    allocate_captaincy_layout,
    append_captaincy_constraints,
    captaincy_integrality,
    extract_captaincy_pair,
)

from dataclasses import dataclass
import math
from typing import Iterable, Mapping, Any

import numpy as np
from scipy.optimize import (
    Bounds,
    LinearConstraint,
    milp,
)


class ChipSquadError(ValueError):
    pass


@dataclass(frozen=True)
class UnlimitedSquadPlan:
    horizon: int
    first_gameweek: int
    last_gameweek: int
    player_ids: frozenset[str]
    starting_xi_by_gameweek: Mapping[
        int,
        tuple[str, ...],
    ]
    weighted_xi_ev: float
    liquidation_budget_tenths: int
    accounting_cost_tenths: int
    remaining_budget_tenths: int

    weighted_captain_bonus_ev: float = 0.0
    weighted_total_ev: float = 0.0

    captain_by_gameweek: tuple[
        tuple[int, str],
        ...
    ] = ()

    vice_by_gameweek: tuple[
        tuple[int, str],
        ...
    ] = ()


def _gameweek_ev(
    projection,
    gameweek: int,
) -> float:

    for row in projection.gameweeks:

        if row.gameweek == gameweek:
            return float(
                row.expected_points
            )

    raise ChipSquadError(
        "missing gameweek projection "
        f"{projection.player_id} "
        f"GW{gameweek}"
    )


def optimize_unlimited_squad(
    *,
    player_rows: Iterable[
        Mapping[str, Any]
    ],
    projections_by_id: Mapping[
        str,
        object,
    ],
    current_player_ids: Iterable[str],
    selling_prices_tenths: Mapping[
        str,
        int,
    ],
    bank_tenths: int,
    first_gameweek: int,
    horizon: int,
    weights: tuple[float, ...],
    required_player_ids: Iterable[str] = (),
    forbidden_player_ids: Iterable[str] = (),
    max_players_per_team: int = 3,
    appearance_by_player_gameweek=None,
    captaincy_weight: float = 0.0,
) -> UnlimitedSquadPlan:

    if horizon < 1:
        raise ChipSquadError(
            "horizon must be positive"
        )

    if len(weights) < horizon:
        raise ChipSquadError(
            "not enough horizon weights"
        )

    current = frozenset(
        current_player_ids
    )

    required = frozenset(
        str(player_id)
        for player_id
        in required_player_ids
    )

    forbidden = frozenset(
        str(player_id)
        for player_id
        in forbidden_player_ids
    )

    if required & forbidden:
        raise ChipSquadError(
            "player cannot be both "
            "required and forbidden"
        )

    rows_by_id = {}

    for row in player_rows:

        player_id = str(
            row["player_id"]
        )

        if player_id in rows_by_id:
            raise ChipSquadError(
                f"duplicate player {player_id}"
            )

        if player_id not in projections_by_id:
            continue

        position = str(
            row["position"]
        )

        team_id = row.get(
            "team_id"
        )

        if team_id is None:
            raise ChipSquadError(
                f"missing team_id for "
                f"{player_id}"
            )

        price = int(
            row["current_price"]
        )

        rows_by_id[
            player_id
        ] = {
            "player_id": player_id,
            "position": position,
            "team_id": str(
                team_id
            ),
            "current_price": price,
        }

    missing_current = (
        current
        - set(rows_by_id)
    )

    if missing_current:
        raise ChipSquadError(
            "current players missing "
            "from candidate universe"
        )

    if (
        set(current)
        - set(selling_prices_tenths)
    ):
        raise ChipSquadError(
            "missing current selling price"
        )

    rows = tuple(
        rows_by_id[
            player_id
        ]
        for player_id in sorted(
            rows_by_id
        )
    )

    n = len(rows)

    index_by_id = {
        row["player_id"]: index
        for index, row
        in enumerate(rows)
    }

    unknown_required = (
        required
        - set(index_by_id)
    )

    unknown_forbidden = (
        forbidden
        - set(index_by_id)
    )

    if unknown_required:
        raise ChipSquadError(
            "required players missing "
            "from candidate universe: "
            f"{sorted(unknown_required)}"
        )

    if unknown_forbidden:
        raise ChipSquadError(
            "forbidden players missing "
            "from candidate universe: "
            f"{sorted(unknown_forbidden)}"
        )

    gameweeks = tuple(
        first_gameweek + index
        for index in range(
            horizon
        )
    )

    #
    # VARIABLES
    #
    # x_i = selected in 15
    # y_g_i = starting XI in GW g
    #

    x_offset = 0

    y_offsets = {
        gameweek:
        n * (
            1 + index
        )
        for index, gameweek
        in enumerate(
            gameweeks
        )
    }

    total_variables = (
        n
        * (
            1 + horizon
        )
    )

    if captaincy_weight < 0.0:

        raise ChipSquadError(
            "captaincy_weight must "
            "be non-negative"
        )

    captaincy_v2_enabled = (
        appearance_by_player_gameweek
        is not None
        and captaincy_weight > 0.0
    )

    captaincy_layout = (
        allocate_captaincy_layout(
            base_total_variables=(
                total_variables
            ),
            horizon=horizon,
            n_players=n,
            enabled=(
                captaincy_v2_enabled
            ),
        )
    )

    total_variables = (
        captaincy_layout
        .total_variables
    )


    def x(index):
        return (
            x_offset
            + index
        )

    def y(
        gameweek,
        index,
    ):
        return (
            y_offsets[
                gameweek
            ]
            + index
        )

    objective = np.zeros(
        total_variables,
        dtype=float,
    )

    for index, row in enumerate(
        rows
    ):

        projection = (
            projections_by_id[
                row["player_id"]
            ]
        )

        for gw_index, gameweek in enumerate(
            gameweeks
        ):

            objective[
                y(
                    gameweek,
                    index,
                )
            ] = (
                -weights[
                    gw_index
                ]
                * _gameweek_ev(
                    projection,
                    gameweek,
                )
            )


    if captaincy_v2_enabled:

        captaincy_points_by_id = {
            row["player_id"]: {
                gameweek: _gameweek_ev(
                    projections_by_id[
                        row["player_id"]
                    ],
                    gameweek,
                )
                for gameweek
                in gameweeks
            }
            for row
            in rows
        }

        add_captaincy_objective(
            objective=objective,
            layout=captaincy_layout,
            gameweeks=gameweeks,
            weights=weights,
            player_ids=[
                row["player_id"]
                for row in rows
            ],
            points_by_player_gameweek=(
                captaincy_points_by_id
            ),
            captaincy_weight=(
                captaincy_weight
            ),
        )

    constraints = []

    #
    # Squad size = 15
    #

    vector = np.zeros(
        total_variables
    )

    for index in range(n):
        vector[x(index)] = 1.0

    constraints.append(
        LinearConstraint(
            vector,
            15.0,
            15.0,
        )
    )

    #
    # Exact FPL positional shape
    #

    squad_shape = {
        "GK": 2,
        "DEF": 5,
        "MID": 5,
        "FWD": 3,
    }

    for position, required_count in (
        squad_shape.items()
    ):

        vector = np.zeros(
            total_variables
        )

        for index, row in enumerate(
            rows
        ):

            if (
                row["position"]
                == position
            ):
                vector[
                    x(index)
                ] = 1.0

        constraints.append(
            LinearConstraint(
                vector,
                float(required_count),
                float(required_count),
            )
        )

    #
    # Max 3 per club
    #

    team_ids = sorted(
        {
            row["team_id"]
            for row in rows
        }
    )

    for team_id in team_ids:

        vector = np.zeros(
            total_variables
        )

        for index, row in enumerate(
            rows
        ):

            if (
                row["team_id"]
                == team_id
            ):
                vector[
                    x(index)
                ] = 1.0

        constraints.append(
            LinearConstraint(
                vector,
                -np.inf,
                float(
                    max_players_per_team
                ),
            )
        )

    #
    # Wildcard / Free Hit budget.
    #
    # Current owned players use their
    # actual selling value as their
    # opportunity cost.
    #
    # New players use current price.
    #

    liquidation_budget = (
        int(bank_tenths)
        + sum(
            int(
                selling_prices_tenths[
                    player_id
                ]
            )
            for player_id
            in current
        )
    )

    accounting_costs = []

    vector = np.zeros(
        total_variables
    )

    for index, row in enumerate(
        rows
    ):

        player_id = row[
            "player_id"
        ]

        if player_id in current:

            cost = int(
                selling_prices_tenths[
                    player_id
                ]
            )

        else:

            cost = int(
                row[
                    "current_price"
                ]
            )

        accounting_costs.append(
            cost
        )

        vector[
            x(index)
        ] = float(cost)

    constraints.append(
        LinearConstraint(
            vector,
            -np.inf,
            float(
                liquidation_budget
            ),
        )
    )

    #
    # Optional hard squad constraints.
    #
    # Useful for sensitivity analysis,
    # not for changing the base model.
    #

    for player_id in sorted(
        required
    ):

        vector = np.zeros(
            total_variables
        )

        vector[
            x(
                index_by_id[
                    player_id
                ]
            )
        ] = 1.0

        constraints.append(
            LinearConstraint(
                vector,
                1.0,
                1.0,
            )
        )

    for player_id in sorted(
        forbidden
    ):

        vector = np.zeros(
            total_variables
        )

        vector[
            x(
                index_by_id[
                    player_id
                ]
            )
        ] = 1.0

        constraints.append(
            LinearConstraint(
                vector,
                0.0,
                0.0,
            )
        )


    #
    # Legal XI independently
    # in every GW.
    #

    for gameweek in gameweeks:

        #
        # 11 starters
        #

        vector = np.zeros(
            total_variables
        )

        for index in range(n):
            vector[
                y(
                    gameweek,
                    index,
                )
            ] = 1.0

        constraints.append(
            LinearConstraint(
                vector,
                11.0,
                11.0,
            )
        )

        #
        # y_i <= x_i
        #

        for index in range(n):

            vector = np.zeros(
                total_variables
            )

            vector[
                y(
                    gameweek,
                    index,
                )
            ] = 1.0

            vector[
                x(index)
            ] = -1.0

            constraints.append(
                LinearConstraint(
                    vector,
                    -np.inf,
                    0.0,
                )
            )

        for (
            position,
            lower,
            upper,
        ) in (
            (
                "GK",
                1,
                1,
            ),
            (
                "DEF",
                3,
                5,
            ),
            (
                "MID",
                2,
                5,
            ),
            (
                "FWD",
                1,
                3,
            ),
        ):

            vector = np.zeros(
                total_variables
            )

            for index, row in enumerate(
                rows
            ):

                if (
                    row["position"]
                    == position
                ):
                    vector[
                        y(
                            gameweek,
                            index,
                        )
                    ] = 1.0

            constraints.append(
                LinearConstraint(
                    vector,
                    float(lower),
                    float(upper),
                )
            )


    if captaincy_v2_enabled:

        append_captaincy_constraints(
            constraints=constraints,
            layout=captaincy_layout,
            total_variables=(
                total_variables
            ),
            gameweeks=gameweeks,
            player_ids=[
                row["player_id"]
                for row in rows
            ],
            starter_index=(
                lambda offset, index:
                y(
                    gameweeks[offset],
                    index,
                )
            ),
            appearance_by_player_gameweek=(
                appearance_by_player_gameweek
            ),
        )

    integrality = (
        captaincy_integrality(
            total_variables=(
                total_variables
            ),
            layout=captaincy_layout,
        )
    )

    result = milp(
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
        options={
            "presolve": True,
        },
    )

    if not result.success:
        raise ChipSquadError(
            "no feasible unlimited squad"
        )

    selected_indices = tuple(
        index
        for index in range(n)
        if result.x[
            x(index)
        ] > 0.5
    )

    if len(
        selected_indices
    ) != 15:
        raise ChipSquadError(
            "MILP did not return "
            "15 players"
        )

    selected = frozenset(
        rows[index][
            "player_id"
        ]
        for index
        in selected_indices
    )

    starting_xi = {}

    weighted_ev = 0.0

    for gw_index, gameweek in enumerate(
        gameweeks
    ):

        xi = tuple(
            rows[index][
                "player_id"
            ]
            for index
            in range(n)
            if result.x[
                y(
                    gameweek,
                    index,
                )
            ] > 0.5
        )

        if len(xi) != 11:
            raise ChipSquadError(
                "MILP returned invalid XI"
            )

        starting_xi[
            gameweek
        ] = xi

        weighted_ev += (
            weights[
                gw_index
            ]
            * sum(
                _gameweek_ev(
                    projections_by_id[
                        player_id
                    ],
                    gameweek,
                )
                for player_id
                in xi
            )
        )


    captain_pairs = []
    vice_pairs = []

    weighted_captain_bonus = 0.0

    if captaincy_v2_enabled:

        for gw_index, gameweek in enumerate(
            gameweeks
        ):

            (
                captain_id,
                vice_id,
                captain_bonus,
            ) = extract_captaincy_pair(
                solution=result.x,
                layout=(
                    captaincy_layout
                ),
                offset=gw_index,
                gameweek=gameweek,
                player_ids=[
                    row["player_id"]
                    for row in rows
                ],
                points_by_player_gameweek=(
                    captaincy_points_by_id
                ),
                appearance_by_player_gameweek=(
                    appearance_by_player_gameweek
                ),
            )

            xi = starting_xi[
                gameweek
            ]

            if (
                captain_id
                not in xi
                or vice_id
                not in xi
            ):

                raise ChipSquadError(
                    "C/VC must both "
                    "belong to optimized XI"
                )

            captain_pairs.append(
                (
                    gameweek,
                    captain_id,
                )
            )

            vice_pairs.append(
                (
                    gameweek,
                    vice_id,
                )
            )

            weighted_captain_bonus += (
                weights[
                    gw_index
                ]
                * captain_bonus
            )

    weighted_total_ev = (
        weighted_ev
        + captaincy_weight
        * weighted_captain_bonus
    )

    accounting_cost = sum(
        accounting_costs[
            index
        ]
        for index
        in selected_indices
    )

    return UnlimitedSquadPlan(
        horizon=horizon,
        first_gameweek=(
            first_gameweek
        ),
        last_gameweek=(
            first_gameweek
            + horizon
            - 1
        ),
        player_ids=selected,
        starting_xi_by_gameweek=(
            starting_xi
        ),
        weighted_xi_ev=(
            weighted_ev
        ),
        liquidation_budget_tenths=(
            liquidation_budget
        ),
        accounting_cost_tenths=(
            accounting_cost
        ),
        remaining_budget_tenths=(
            liquidation_budget
            - accounting_cost
        ),
        weighted_captain_bonus_ev=(
            weighted_captain_bonus
        ),
        weighted_total_ev=(
            weighted_total_ev
        ),
        captain_by_gameweek=tuple(
            captain_pairs
        ),
        vice_by_gameweek=tuple(
            vice_pairs
        ),
    )
