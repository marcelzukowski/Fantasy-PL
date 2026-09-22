from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np
from scipy.optimize import (
    Bounds,
    LinearConstraint,
    milp,
)

from .captaincy import (
    evaluate_squad_with_captaincy,
)
from .captaincy_milp import (
    add_captaincy_objective,
    allocate_captaincy_layout,
    append_captaincy_constraints,
    captaincy_integrality,
    extract_captaincy_pair,
)
from .captaincy_v2 import (
    evaluate_squad_with_captaincy_v2,
)
from .horizon import DecisionError
from .projection_adapter import (
    PlayerDecisionProjection,
    horizon_weights,
)
from .transfers import (
    MAX_PLAYERS_PER_TEAM,
    SquadState,
)
from .value import PlayerValue


@dataclass(frozen=True)
class RollingTransferPlan:
    horizon: int

    first_gameweek: int
    next_gameweek: int
    last_gameweek: int

    free_transfers_before: int
    transfers_now: int

    next_week_ft_available: int
    transfers_next_week: int

    baseline_weighted_total_ev: float
    final_weighted_xi_ev: float
    final_weighted_captain_ev: float
    final_weighted_total_ev: float
    gain: float

    bank_after_now_tenths: int
    bank_after_next_tenths: int

    outgoing_now_player_ids: tuple[str, ...]
    incoming_now_player_ids: tuple[str, ...]

    outgoing_next_player_ids: tuple[str, ...]
    incoming_next_player_ids: tuple[str, ...]

    squad_now_player_ids: tuple[str, ...]
    squad_next_player_ids: tuple[str, ...]

    starting_xi_by_gameweek: tuple[
        tuple[int, tuple[str, ...]],
        ...
    ]

    captain_by_gameweek: tuple[
        tuple[int, str],
        ...
    ]

    vice_by_gameweek: tuple[
        tuple[int, str],
        ...
    ] = ()


def _gw_points(
    projection: PlayerDecisionProjection,
) -> dict[int, float]:

    return {
        row.gameweek: float(
            row.expected_points
        )
        for row in projection.gameweeks
    }


def optimize_rolling_free_transfers(
    *,
    players: Iterable[PlayerValue],
    projections_by_id: dict[
        str,
        PlayerDecisionProjection,
    ],
    state: SquadState,
    horizon: int,
    transfers_now: int,
    current_free_transfers: int,
    max_free_transfers: int = 5,
    captaincy_weight: float = 1.0,
    fixed_squad_now_player_ids: (
        set[str]
        | frozenset[str]
        | None
    ) = None,
    appearance_by_player_gameweek=None,
) -> RollingTransferPlan | None:

    if horizon not in {
        3,
        6,
    }:
        raise DecisionError(
            "horizon must be 3 or 6"
        )

    if transfers_now < 0:
        raise DecisionError(
            "transfers_now cannot be negative"
        )

    if (
        transfers_now
        > current_free_transfers
    ):
        raise DecisionError(
            "this optimizer only models "
            "free transfers in current GW"
        )

    rows = tuple(players)

    if not rows:
        raise DecisionError(
            "players cannot be empty"
        )

    by_id = {
        row.player_id: row
        for row in rows
    }

    current = set(
        state.player_ids
    )

    if len(current) != 15:
        raise DecisionError(
            "rolling optimizer requires "
            "15-player squad"
        )

    if current - set(by_id):
        raise DecisionError(
            "unknown current player"
        )

    if set(by_id) - set(
        projections_by_id
    ):
        raise DecisionError(
            "missing player projections"
        )

    current_gws = {
        projections_by_id[
            player_id
        ].current_gameweek
        for player_id in current
    }

    if len(current_gws) != 1:
        raise DecisionError(
            "inconsistent current_gameweek"
        )

    first_gameweek = next(
        iter(current_gws)
    )

    next_gameweek = (
        first_gameweek + 1
    )

    gameweeks = tuple(
        first_gameweek + offset
        for offset in range(
            horizon
        )
    )

    weights = dict(
        horizon_weights(
            horizon
        )
    )

    next_week_ft_available = min(
        max_free_transfers,
        (
            current_free_transfers
            - transfers_now
            + 1
        ),
    )

    n = len(rows)

    #
    # VARIABLES
    #
    # x0 = squad after current-GW transfers
    # x1 = squad after next-GW transfers
    # y  = incoming transfer in next GW
    #
    # plus XI + captain variables
    # for every GW in the horizon.
    #

    x0_base = 0
    x1_base = n
    y_base = 2 * n

    starter_base = 3 * n

    captain_base = (
        starter_base
        + horizon * n
    )

    total_variables = (
        captain_base
        + horizon * n
    )

    captaincy_v2_enabled = (
        appearance_by_player_gameweek
        is not None
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


    def x0(index):
        return x0_base + index

    def x1(index):
        return x1_base + index

    def y(index):
        return y_base + index

    def starter(
        offset,
        index,
    ):
        return (
            starter_base
            + offset * n
            + index
        )

    def captain(
        offset,
        index,
    ):
        return (
            captain_base
            + offset * n
            + index
        )

    points_by_id = {
        row.player_id: _gw_points(
            projections_by_id[
                row.player_id
            ]
        )
        for row in rows
    }

    objective = np.zeros(
        total_variables
    )

    for offset, gameweek in enumerate(
        gameweeks
    ):

        weight = weights[offset]

        for index, row in enumerate(
            rows
        ):

            points = (
                points_by_id[
                    row.player_id
                ].get(
                    gameweek,
                    0.0,
                )
            )

            objective[
                starter(
                    offset,
                    index,
                )
            ] = -(
                weight
                * points
            )

            objective[
                captain(
                    offset,
                    index,
                )
            ] = -(
                captaincy_weight
                * weight
                * points
            )

    # Tiny tie-break:
    # if two paths have identical EV,
    # prefer using fewer GW+1 transfers.
    for index in range(n):
        objective[
            y(index)
        ] = 1e-6


    if captaincy_v2_enabled:

        player_ids_for_captaincy = [
            row.player_id
            for row in rows
        ]

        add_captaincy_objective(
            objective=objective,
            layout=captaincy_layout,
            gameweeks=gameweeks,
            weights=weights,
            player_ids=(
                player_ids_for_captaincy
            ),
            points_by_player_gameweek=(
                points_by_id
            ),
            captaincy_weight=(
                captaincy_weight
            ),
            legacy_captain_index=(
                captain
            ),
        )

    constraints = []

    #
    # POSITION STRUCTURE
    #

    position_counts = {}

    for player_id in current:

        position = (
            by_id[
                player_id
            ].position
        )

        position_counts[
            position
        ] = (
            position_counts.get(
                position,
                0,
            )
            + 1
        )

    for stage_base in (
        x0_base,
        x1_base,
    ):

        for position, required in (
            position_counts.items()
        ):

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
                        stage_base
                        + index
                    ] = 1.0

            constraints.append(
                LinearConstraint(
                    vector,
                    lb=float(
                        required
                    ),
                    ub=float(
                        required
                    ),
                )
            )

    #
    # CLUB LIMIT AT BOTH STAGES
    #

    team_ids = {
        row.team_id
        for row in rows
    }

    for stage_base in (
        x0_base,
        x1_base,
    ):

        for team_id in team_ids:

            vector = np.zeros(
                total_variables
            )

            for index, row in enumerate(
                rows
            ):

                if (
                    row.team_id
                    == team_id
                ):
                    vector[
                        stage_base
                        + index
                    ] = 1.0

            constraints.append(
                LinearConstraint(
                    vector,
                    lb=-np.inf,
                    ub=float(
                        MAX_PLAYERS_PER_TEAM
                    ),
                )
            )

    #
    # EXACT NUMBER OF TRANSFERS NOW
    #

    vector = np.zeros(
        total_variables
    )

    for index, row in enumerate(
        rows
    ):

        if (
            row.player_id
            not in current
        ):
            vector[
                x0(index)
            ] = 1.0

    constraints.append(
        LinearConstraint(
            vector,
            lb=float(
                transfers_now
            ),
            ub=float(
                transfers_now
            ),
        )
    )

    #
    # OPTIONAL FIXED CURRENT-GW PLAN
    #
    # Used for cross-run robustness:
    # force exactly the same GW4 squad
    # and let GW5+ adapt normally.
    #

    if (
        fixed_squad_now_player_ids
        is not None
    ):

        fixed_squad_now = set(
            fixed_squad_now_player_ids
        )

        if len(
            fixed_squad_now
        ) != 15:
            raise DecisionError(
                "fixed_squad_now must "
                "contain 15 players"
            )

        unknown_fixed = (
            fixed_squad_now
            - set(by_id)
        )

        if unknown_fixed:
            raise DecisionError(
                "fixed_squad_now contains "
                "unknown players"
            )

        fixed_incoming = (
            fixed_squad_now
            - current
        )

        fixed_outgoing = (
            current
            - fixed_squad_now
        )

        if (
            len(fixed_incoming)
            != transfers_now
            or len(fixed_outgoing)
            != transfers_now
        ):
            raise DecisionError(
                "fixed_squad_now does not "
                "match transfers_now"
            )

        for index, row in enumerate(
            rows
        ):

            vector = np.zeros(
                total_variables
            )

            vector[
                x0(index)
            ] = 1.0

            required = (
                1.0
                if row.player_id
                in fixed_squad_now
                else 0.0
            )

            constraints.append(
                LinearConstraint(
                    vector,
                    lb=required,
                    ub=required,
                )
            )

    #
    # FROZEN-PRICE BUDGET
    #
    # Existing owned players use their
    # actual current selling prices.
    #
    # New players use current market price.
    #

    frozen_cost = {}

    initial_budget = (
        state.bank_tenths
    )

    for row in rows:

        if row.player_id in current:

            cost = int(
                state
                .selling_prices_tenths[
                    row.player_id
                ]
            )

            initial_budget += cost

        else:
            cost = int(
                row.price_tenths
            )

        frozen_cost[
            row.player_id
        ] = cost

    for stage_base in (
        x0_base,
        x1_base,
    ):

        vector = np.zeros(
            total_variables
        )

        for index, row in enumerate(
            rows
        ):

            vector[
                stage_base
                + index
            ] = float(
                frozen_cost[
                    row.player_id
                ]
            )

        constraints.append(
            LinearConstraint(
                vector,
                lb=-np.inf,
                ub=float(
                    initial_budget
                ),
            )
        )

    #
    # Do not sell an originally owned
    # player now and buy him straight
    # back one GW later.
    #
    # x1 <= x0 for original players
    # whenever x0 was already 0.
    #

    for index, row in enumerate(
        rows
    ):

        if (
            row.player_id
            in current
        ):

            vector = np.zeros(
                total_variables
            )

            vector[
                x1(index)
            ] = 1.0

            vector[
                x0(index)
            ] = -1.0

            constraints.append(
                LinearConstraint(
                    vector,
                    lb=-np.inf,
                    ub=0.0,
                )
            )

    #
    # y_i = 1 exactly when player
    # is newly brought in at GW+1.
    #
    # y >= x1 - x0
    # y <= x1
    # y <= 1 - x0
    #

    for index in range(n):

        vector = np.zeros(
            total_variables
        )

        vector[
            y(index)
        ] = 1.0

        vector[
            x1(index)
        ] = -1.0

        vector[
            x0(index)
        ] = 1.0

        constraints.append(
            LinearConstraint(
                vector,
                lb=0.0,
                ub=np.inf,
            )
        )

        vector = np.zeros(
            total_variables
        )

        vector[
            y(index)
        ] = 1.0

        vector[
            x1(index)
        ] = -1.0

        constraints.append(
            LinearConstraint(
                vector,
                lb=-np.inf,
                ub=0.0,
            )
        )

        vector = np.zeros(
            total_variables
        )

        vector[
            y(index)
        ] = 1.0

        vector[
            x0(index)
        ] = 1.0

        constraints.append(
            LinearConstraint(
                vector,
                lb=-np.inf,
                ub=1.0,
            )
        )

    #
    # Next-GW FT capacity.
    #

    vector = np.zeros(
        total_variables
    )

    for index in range(n):
        vector[
            y(index)
        ] = 1.0

    constraints.append(
        LinearConstraint(
            vector,
            lb=0.0,
            ub=float(
                next_week_ft_available
            ),
        )
    )

    #
    # XI + CAPTAIN FOR EACH GW
    #

    for offset, gameweek in enumerate(
        gameweeks
    ):

        # Current GW uses squad x0.
        # Later GWs use squad x1.
        if offset == 0:
            squad_base = x0_base
        else:
            squad_base = x1_base

        #
        # Exactly 11 starters.
        #

        vector = np.zeros(
            total_variables
        )

        for index in range(n):
            vector[
                starter(
                    offset,
                    index,
                )
            ] = 1.0

        constraints.append(
            LinearConstraint(
                vector,
                lb=11.0,
                ub=11.0,
            )
        )

        #
        # Legal formation.
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
                        starter(
                            offset,
                            index,
                        )
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
        # Starter must belong
        # to active squad.
        #

        for index in range(n):

            vector = np.zeros(
                total_variables
            )

            vector[
                starter(
                    offset,
                    index,
                )
            ] = 1.0

            vector[
                squad_base
                + index
            ] = -1.0

            constraints.append(
                LinearConstraint(
                    vector,
                    lb=-np.inf,
                    ub=0.0,
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
                captain(
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
        # Captain must start.
        #

        for index in range(n):

            vector = np.zeros(
                total_variables
            )

            vector[
                captain(
                    offset,
                    index,
                )
            ] = 1.0

            vector[
                starter(
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


    if captaincy_v2_enabled:

        append_captaincy_constraints(
            constraints=constraints,
            layout=captaincy_layout,
            total_variables=(
                total_variables
            ),
            gameweeks=gameweeks,
            player_ids=[
                row.player_id
                for row in rows
            ],
            starter_index=starter,
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
            "disp": False,
        },
    )

    if not result.success:
        return None

    squad_now = {
        rows[index].player_id
        for index in range(n)
        if (
            result.x[
                x0(index)
            ]
            >= 0.5
        )
    }

    squad_next = {
        rows[index].player_id
        for index in range(n)
        if (
            result.x[
                x1(index)
            ]
            >= 0.5
        )
    }

    outgoing_now = tuple(
        sorted(
            current
            - squad_now
        )
    )

    incoming_now = tuple(
        sorted(
            squad_now
            - current
        )
    )

    outgoing_next = tuple(
        sorted(
            squad_now
            - squad_next
        )
    )

    incoming_next = tuple(
        sorted(
            squad_next
            - squad_now
        )
    )

    lineups = []
    captains = []
    vices = []

    weighted_xi = 0.0
    weighted_captain = 0.0

    for offset, gameweek in enumerate(
        gameweeks
    ):

        starter_ids = tuple(
            sorted(
                rows[index].player_id
                for index in range(n)
                if (
                    result.x[
                        starter(
                            offset,
                            index,
                        )
                    ]
                    >= 0.5
                )
            )
        )

        captain_ids = [
            rows[index].player_id
            for index in range(n)
            if (
                result.x[
                    captain(
                        offset,
                        index,
                    )
                ]
                >= 0.5
            )
        ]

        if len(captain_ids) != 1:
            raise DecisionError(
                "expected one captain"
            )

        captain_id = (
            captain_ids[0]
        )

        vice_id = None
        captain_bonus_v2 = None

        if captaincy_v2_enabled:

            (
                captain_id,
                vice_id,
                captain_bonus_v2,
            ) = extract_captaincy_pair(
                solution=result.x,
                layout=(
                    captaincy_layout
                ),
                offset=offset,
                gameweek=gameweek,
                player_ids=[
                    row.player_id
                    for row in rows
                ],
                points_by_player_gameweek=(
                    points_by_id
                ),
                appearance_by_player_gameweek=(
                    appearance_by_player_gameweek
                ),
            )

            if (
                captain_id
                not in starter_ids
                or vice_id
                not in starter_ids
            ):
                raise DecisionError(
                    "V2 C/VC must both "
                    "belong to XI"
                )

        weight = weights[
            offset
        ]

        raw_xi = sum(
            points_by_id[
                player_id
            ].get(
                gameweek,
                0.0,
            )
            for player_id
            in starter_ids
        )

        if captaincy_v2_enabled:

            raw_captain = float(
                captain_bonus_v2
            )

        else:

            raw_captain = (
                points_by_id[
                    captain_id
                ].get(
                    gameweek,
                    0.0,
                )
            )

        weighted_xi += (
            weight
            * raw_xi
        )

        weighted_captain += (
            weight
            * raw_captain
        )

        lineups.append(
            (
                gameweek,
                starter_ids,
            )
        )

        captains.append(
            (
                gameweek,
                captain_id,
            )
        )

        if captaincy_v2_enabled:

            vices.append(
                (
                    gameweek,
                    vice_id,
                )
            )

    if captaincy_v2_enabled:

        baseline = (
            evaluate_squad_with_captaincy_v2(
                squad_player_ids=current,
                players_by_id=by_id,
                projections_by_id=(
                    projections_by_id
                ),
                appearance_by_player_gameweek=(
                    appearance_by_player_gameweek
                ),
                horizon=horizon,
            )
        )

    else:

        baseline = (
            evaluate_squad_with_captaincy(
            squad_player_ids=current,
            players_by_id=by_id,
            projections_by_id=(
                projections_by_id
            ),
                horizon=horizon,
            )
        )

    final_total = (
        weighted_xi
        + (
            captaincy_weight
            * weighted_captain
        )
    )

    baseline_total = (
        baseline.weighted_xi_ev
        + (
            captaincy_weight
            * baseline
            .weighted_captain_bonus_ev
        )
    )

    bank_after_now = (
        initial_budget
        - sum(
            frozen_cost[
                player_id
            ]
            for player_id
            in squad_now
        )
    )

    bank_after_next = (
        initial_budget
        - sum(
            frozen_cost[
                player_id
            ]
            for player_id
            in squad_next
        )
    )

    return RollingTransferPlan(
        horizon=horizon,
        first_gameweek=(
            first_gameweek
        ),
        next_gameweek=(
            next_gameweek
        ),
        last_gameweek=(
            first_gameweek
            + horizon
            - 1
        ),
        free_transfers_before=(
            current_free_transfers
        ),
        transfers_now=(
            transfers_now
        ),
        next_week_ft_available=(
            next_week_ft_available
        ),
        transfers_next_week=(
            len(
                incoming_next
            )
        ),
        baseline_weighted_total_ev=(
            baseline_total
        ),
        final_weighted_xi_ev=(
            weighted_xi
        ),
        final_weighted_captain_ev=(
            weighted_captain
        ),
        final_weighted_total_ev=(
            final_total
        ),
        gain=(
            final_total
            - baseline_total
        ),
        bank_after_now_tenths=(
            bank_after_now
        ),
        bank_after_next_tenths=(
            bank_after_next
        ),
        outgoing_now_player_ids=(
            outgoing_now
        ),
        incoming_now_player_ids=(
            incoming_now
        ),
        outgoing_next_player_ids=(
            outgoing_next
        ),
        incoming_next_player_ids=(
            incoming_next
        ),
        squad_now_player_ids=tuple(
            sorted(
                squad_now
            )
        ),
        squad_next_player_ids=tuple(
            sorted(
                squad_next
            )
        ),
        starting_xi_by_gameweek=tuple(
            lineups
        ),
        captain_by_gameweek=tuple(
            captains
        ),
        vice_by_gameweek=tuple(
            vices
        ),
    )
