from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np
from scipy.optimize import (
    Bounds,
    LinearConstraint,
    milp,
)

from .horizon import DecisionError
from .transfers import (
    MAX_PLAYERS_PER_TEAM,
    SquadState,
)
from .value import PlayerValue
from .projection_adapter import (
    PlayerDecisionProjection,
    horizon_weights,
)


@dataclass(frozen=True)
class SquadTransferPlan:
    horizon: int
    transfer_count: int

    current_ev: float
    final_ev: float
    gain: float

    bank_before_tenths: int
    bank_after_tenths: int

    outgoing_player_ids: tuple[str, ...]
    incoming_player_ids: tuple[str, ...]
    final_player_ids: tuple[str, ...]


def optimize_squad_transfers(
    *,
    players: Iterable[PlayerValue],
    state: SquadState,
    horizon: int,
    exact_transfers: int,
) -> SquadTransferPlan | None:

    if horizon not in {3, 6}:
        raise DecisionError(
            "horizon must be 3 or 6"
        )

    if exact_transfers < 0:
        raise DecisionError(
            "exact_transfers cannot be negative"
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

    missing = (
        set(state.player_ids)
        - set(by_id)
    )

    if missing:
        raise DecisionError(
            "squad contains unknown players"
        )

    n = len(rows)

    current = set(
        state.player_ids
    )

    # Maximize EV by minimizing negative EV.
    if horizon == 3:
        ev = np.array(
            [
                row.ev_3
                for row in rows
            ],
            dtype=float,
        )
    else:
        ev = np.array(
            [
                row.ev_6
                for row in rows
            ],
            dtype=float,
        )

    c = -ev

    constraints = []

    # Preserve current FPL positional structure.
    position_counts = {}

    for player_id in current:
        position = by_id[
            player_id
        ].position

        position_counts[
            position
        ] = (
            position_counts.get(
                position,
                0,
            )
            + 1
        )

    for position, required in (
        position_counts.items()
    ):
        vector = np.array(
            [
                1.0
                if row.position
                == position
                else 0.0
                for row in rows
            ]
        )

        constraints.append(
            LinearConstraint(
                vector,
                lb=float(required),
                ub=float(required),
            )
        )

    # Maximum 3 players from one club
    # in the final squad.
    team_ids = {
        row.team_id
        for row in rows
    }

    for team_id in team_ids:
        vector = np.array(
            [
                1.0
                if row.team_id
                == team_id
                else 0.0
                for row in rows
            ]
        )

        constraints.append(
            LinearConstraint(
                vector,
                lb=-np.inf,
                ub=float(
                    MAX_PLAYERS_PER_TEAM
                ),
            )
        )

    # Exact number of transfers:
    # selected non-squad players = transfers.
    transfer_vector = np.array(
        [
            0.0
            if row.player_id
            in current
            else 1.0
            for row in rows
        ]
    )

    constraints.append(
        LinearConstraint(
            transfer_vector,
            lb=float(
                exact_transfers
            ),
            ub=float(
                exact_transfers
            ),
        )
    )

    # Budget:
    #
    # incoming current_price
    # <= bank + outgoing selling_price
    #
    # Rearranged into final-squad form:
    #
    # sum(noncurrent price*x)
    # + sum(current selling_price*x)
    # <= bank + sum(current selling prices)

    budget_coefficients = []

    total_liquidation_value = (
        state.bank_tenths
    )

    for row in rows:

        if row.player_id in current:

            selling_price = int(
                state
                .selling_prices_tenths[
                    row.player_id
                ]
            )

            budget_coefficients.append(
                float(
                    selling_price
                )
            )

            total_liquidation_value += (
                selling_price
            )

        else:
            budget_coefficients.append(
                float(
                    row.price_tenths
                )
            )

    constraints.append(
        LinearConstraint(
            np.array(
                budget_coefficients
            ),
            lb=-np.inf,
            ub=float(
                total_liquidation_value
            ),
        )
    )

    result = milp(
        c=c,
        integrality=np.ones(
            n,
            dtype=int,
        ),
        bounds=Bounds(
            np.zeros(n),
            np.ones(n),
        ),
        constraints=constraints,
        options={
            "disp": False,
        },
    )

    if not result.success:
        return None

    selected = {
        rows[index].player_id
        for index, value
        in enumerate(result.x)
        if value >= 0.5
    }

    outgoing = tuple(
        sorted(
            current - selected
        )
    )

    incoming = tuple(
        sorted(
            selected - current
        )
    )

    if (
        len(outgoing)
        != exact_transfers
        or len(incoming)
        != exact_transfers
    ):
        raise DecisionError(
            "optimizer returned unexpected "
            "transfer count"
        )

    current_ev = sum(
        (
            by_id[player_id].ev_3
            if horizon == 3
            else by_id[player_id].ev_6
        )
        for player_id in current
    )

    final_ev = sum(
        (
            by_id[player_id].ev_3
            if horizon == 3
            else by_id[player_id].ev_6
        )
        for player_id in selected
    )

    bank_after = (
        state.bank_tenths
        + sum(
            int(
                state
                .selling_prices_tenths[
                    player_id
                ]
            )
            for player_id in outgoing
        )
        - sum(
            by_id[
                player_id
            ].price_tenths
            for player_id in incoming
        )
    )

    if bank_after < 0:
        raise DecisionError(
            "optimizer produced "
            "negative bank"
        )

    return SquadTransferPlan(
        horizon=horizon,
        transfer_count=(
            exact_transfers
        ),
        current_ev=(
            current_ev
        ),
        final_ev=(
            final_ev
        ),
        gain=(
            final_ev
            - current_ev
        ),
        bank_before_tenths=(
            state.bank_tenths
        ),
        bank_after_tenths=(
            bank_after
        ),
        outgoing_player_ids=(
            outgoing
        ),
        incoming_player_ids=(
            incoming
        ),
        final_player_ids=tuple(
            sorted(
                selected
            )
        ),
    )



@dataclass(frozen=True)
class LineupTransferPlan:
    horizon: int
    transfer_count: int

    current_starting_xi_ev: float
    final_starting_xi_ev: float
    gain: float

    bank_before_tenths: int
    bank_after_tenths: int

    outgoing_player_ids: tuple[str, ...]
    incoming_player_ids: tuple[str, ...]

    starting_xi_player_ids: tuple[str, ...]
    bench_player_ids: tuple[str, ...]
    final_player_ids: tuple[str, ...]


def _lineup_position_constraints(
    rows,
    *,
    n: int,
):
    constraints = []

    # Variable layout:
    # x[0:n]     = final 15-player squad
    # x[n:2*n]   = starting XI

    starter_total = np.concatenate(
        (
            np.zeros(n),
            np.ones(n),
        )
    )

    constraints.append(
        LinearConstraint(
            starter_total,
            lb=11.0,
            ub=11.0,
        )
    )

    ranges = {
        "GK": (1, 1),
        "DEF": (3, 5),
        "MID": (2, 5),
        "FWD": (1, 3),
    }

    for position, (
        minimum,
        maximum,
    ) in ranges.items():

        starter_vector = np.concatenate(
            (
                np.zeros(n),
                np.array(
                    [
                        1.0
                        if row.position == position
                        else 0.0
                        for row in rows
                    ]
                ),
            )
        )

        constraints.append(
            LinearConstraint(
                starter_vector,
                lb=float(minimum),
                ub=float(maximum),
            )
        )

    # Starter can only be selected
    # if player is in final squad:
    #
    # starter_i - squad_i <= 0

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

    return constraints


def optimize_starting_xi_transfers(
    *,
    players: Iterable[PlayerValue],
    state: SquadState,
    horizon: int,
    exact_transfers: int,
) -> LineupTransferPlan | None:

    if horizon not in {3, 6}:
        raise DecisionError(
            "horizon must be 3 or 6"
        )

    if exact_transfers < 0:
        raise DecisionError(
            "exact_transfers cannot be negative"
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

    if (
        current
        - set(by_id)
    ):
        raise DecisionError(
            "squad contains unknown players"
        )

    n = len(rows)

    if horizon == 3:
        ev = np.array(
            [
                row.ev_3
                for row in rows
            ],
            dtype=float,
        )
    else:
        ev = np.array(
            [
                row.ev_6
                for row in rows
            ],
            dtype=float,
        )

    # Objective:
    # final squad variables have 0 EV.
    # Only starting XI contributes.
    c = np.concatenate(
        (
            np.zeros(n),
            -ev,
        )
    )

    constraints = []

    # Preserve 15-player positional composition.
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

    for position, required in (
        position_counts.items()
    ):

        squad_vector = np.concatenate(
            (
                np.array(
                    [
                        1.0
                        if row.position == position
                        else 0.0
                        for row in rows
                    ]
                ),
                np.zeros(n),
            )
        )

        constraints.append(
            LinearConstraint(
                squad_vector,
                lb=float(required),
                ub=float(required),
            )
        )

    # Maximum 3 from one club in final 15.
    for team_id in {
        row.team_id
        for row in rows
    }:

        vector = np.concatenate(
            (
                np.array(
                    [
                        1.0
                        if row.team_id == team_id
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
                lb=-np.inf,
                ub=float(
                    MAX_PLAYERS_PER_TEAM
                ),
            )
        )

    # Exact transfer count = selected
    # non-current players.
    transfer_vector = np.concatenate(
        (
            np.array(
                [
                    0.0
                    if row.player_id
                    in current
                    else 1.0
                    for row in rows
                ]
            ),
            np.zeros(n),
        )
    )

    constraints.append(
        LinearConstraint(
            transfer_vector,
            lb=float(
                exact_transfers
            ),
            ub=float(
                exact_transfers
            ),
        )
    )

    # Budget based on real selling prices.
    budget_coefficients = []

    total_liquidation_value = (
        state.bank_tenths
    )

    for row in rows:

        if row.player_id in current:

            selling_price = int(
                state
                .selling_prices_tenths[
                    row.player_id
                ]
            )

            budget_coefficients.append(
                float(
                    selling_price
                )
            )

            total_liquidation_value += (
                selling_price
            )

        else:
            budget_coefficients.append(
                float(
                    row.price_tenths
                )
            )

    budget_vector = np.concatenate(
        (
            np.array(
                budget_coefficients
            ),
            np.zeros(n),
        )
    )

    constraints.append(
        LinearConstraint(
            budget_vector,
            lb=-np.inf,
            ub=float(
                total_liquidation_value
            ),
        )
    )

    constraints.extend(
        _lineup_position_constraints(
            rows,
            n=n,
        )
    )

    result = milp(
        c=c,
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

    if not result.success:
        return None

    squad_selected = {
        rows[index].player_id
        for index in range(n)
        if result.x[index] >= 0.5
    }

    starters = {
        rows[index].player_id
        for index in range(n)
        if result.x[n + index] >= 0.5
    }

    outgoing = tuple(
        sorted(
            current
            - squad_selected
        )
    )

    incoming = tuple(
        sorted(
            squad_selected
            - current
        )
    )

    bench = tuple(
        sorted(
            squad_selected
            - starters
        )
    )

    def best_current_xi_ev():
        current_rows = [
            row
            for row in rows
            if row.player_id
            in current
        ]

        m = len(
            current_rows
        )

        current_ev = np.array(
            [
                (
                    row.ev_3
                    if horizon == 3
                    else row.ev_6
                )
                for row in current_rows
            ],
            dtype=float,
        )

        objective = -current_ev

        constraints_current = []

        constraints_current.append(
            LinearConstraint(
                np.ones(m),
                lb=11.0,
                ub=11.0,
            )
        )

        ranges = {
            "GK": (1, 1),
            "DEF": (3, 5),
            "MID": (2, 5),
            "FWD": (1, 3),
        }

        for position, (
            minimum,
            maximum,
        ) in ranges.items():

            vector = np.array(
                [
                    1.0
                    if row.position
                    == position
                    else 0.0
                    for row in current_rows
                ]
            )

            constraints_current.append(
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

        solved = milp(
            c=objective,
            integrality=np.ones(
                m,
                dtype=int,
            ),
            bounds=Bounds(
                np.zeros(m),
                np.ones(m),
            ),
            constraints=(
                constraints_current
            ),
            options={
                "disp": False,
            },
        )

        if not solved.success:
            raise DecisionError(
                "current squad has no "
                "legal starting XI"
            )

        return sum(
            current_ev[index]
            for index in range(m)
            if solved.x[index]
            >= 0.5
        )

    current_xi_ev = (
        best_current_xi_ev()
    )

    final_xi_ev = sum(
        (
            by_id[player_id].ev_3
            if horizon == 3
            else by_id[player_id].ev_6
        )
        for player_id in starters
    )

    bank_after = (
        state.bank_tenths
        + sum(
            int(
                state
                .selling_prices_tenths[
                    player_id
                ]
            )
            for player_id
            in outgoing
        )
        - sum(
            by_id[
                player_id
            ].price_tenths
            for player_id
            in incoming
        )
    )

    return LineupTransferPlan(
        horizon=horizon,
        transfer_count=(
            exact_transfers
        ),
        current_starting_xi_ev=(
            current_xi_ev
        ),
        final_starting_xi_ev=(
            final_xi_ev
        ),
        gain=(
            final_xi_ev
            - current_xi_ev
        ),
        bank_before_tenths=(
            state.bank_tenths
        ),
        bank_after_tenths=(
            bank_after
        ),
        outgoing_player_ids=(
            outgoing
        ),
        incoming_player_ids=(
            incoming
        ),
        starting_xi_player_ids=tuple(
            sorted(
                starters
            )
        ),
        bench_player_ids=(
            bench
        ),
        final_player_ids=tuple(
            sorted(
                squad_selected
            )
        ),
    )



@dataclass(frozen=True)
class MultiGameweekTransferPlan:
    horizon: int
    transfer_count: int

    first_gameweek: int
    last_gameweek: int

    current_weighted_lineup_ev: float
    final_weighted_lineup_ev: float
    gain: float

    bank_before_tenths: int
    bank_after_tenths: int

    outgoing_player_ids: tuple[str, ...]
    incoming_player_ids: tuple[str, ...]

    final_player_ids: tuple[str, ...]

    starting_xi_by_gameweek: tuple[
        tuple[
            int,
            tuple[str, ...],
        ],
        ...
    ]

    bench_by_gameweek: tuple[
        tuple[
            int,
            tuple[str, ...],
        ],
        ...
    ]


def _gameweek_points(
    projection: PlayerDecisionProjection,
) -> dict[int, float]:

    return {
        row.gameweek: float(
            row.expected_points
        )
        for row in projection.gameweeks
    }


def _best_fixed_squad_lineups(
    *,
    squad_ids: set[str],
    by_id: dict[str, PlayerValue],
    projections_by_id: dict[
        str,
        PlayerDecisionProjection,
    ],
    gameweeks: tuple[int, ...],
    weights: dict[int, float],
) -> tuple[
    float,
    tuple[
        tuple[int, tuple[str, ...]],
        ...
    ],
]:

    squad_rows = [
        by_id[player_id]
        for player_id in squad_ids
    ]

    total_weighted_ev = 0.0
    lineups = []

    for offset, gameweek in enumerate(
        gameweeks
    ):

        points = np.array(
            [
                _gameweek_points(
                    projections_by_id[
                        row.player_id
                    ]
                ).get(
                    gameweek,
                    0.0,
                )
                for row in squad_rows
            ],
            dtype=float,
        )

        constraints = [
            LinearConstraint(
                np.ones(
                    len(squad_rows)
                ),
                lb=11.0,
                ub=11.0,
            )
        ]

        for position, (
            minimum,
            maximum,
        ) in {
            "GK": (1, 1),
            "DEF": (3, 5),
            "MID": (2, 5),
            "FWD": (1, 3),
        }.items():

            vector = np.array(
                [
                    1.0
                    if row.position
                    == position
                    else 0.0
                    for row
                    in squad_rows
                ]
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

        result = milp(
            c=-points,
            integrality=np.ones(
                len(squad_rows),
                dtype=int,
            ),
            bounds=Bounds(
                np.zeros(
                    len(squad_rows)
                ),
                np.ones(
                    len(squad_rows)
                ),
            ),
            constraints=constraints,
            options={
                "disp": False,
            },
        )

        if not result.success:
            raise DecisionError(
                "fixed squad has no "
                "legal starting XI"
            )

        starters = tuple(
            sorted(
                squad_rows[index]
                .player_id
                for index, value
                in enumerate(result.x)
                if value >= 0.5
            )
        )

        raw_ev = sum(
            points[index]
            for index, value
            in enumerate(result.x)
            if value >= 0.5
        )

        total_weighted_ev += (
            raw_ev
            * weights[offset]
        )

        lineups.append(
            (
                gameweek,
                starters,
            )
        )

    return (
        total_weighted_ev,
        tuple(lineups),
    )


def optimize_multi_gameweek_transfers(
    *,
    players: Iterable[PlayerValue],
    projections_by_id: dict[
        str,
        PlayerDecisionProjection,
    ],
    state: SquadState,
    horizon: int,
    exact_transfers: int,
) -> MultiGameweekTransferPlan | None:

    if horizon not in {
        3,
        6,
    }:
        raise DecisionError(
            "horizon must be 3 or 6"
        )

    if exact_transfers < 0:
        raise DecisionError(
            "exact_transfers cannot be negative"
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

    if (
        current
        - set(by_id)
    ):
        raise DecisionError(
            "squad contains unknown players"
        )

    missing_projections = (
        set(by_id)
        - set(projections_by_id)
    )

    if missing_projections:
        raise DecisionError(
            "missing decision projections"
        )

    current_gws = {
        projection.current_gameweek
        for projection
        in projections_by_id.values()
    }

    if len(current_gws) != 1:
        raise DecisionError(
            "projection current_gameweek "
            "must be consistent"
        )

    first_gameweek = next(
        iter(current_gws)
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

    n = len(rows)
    total_variables = (
        n
        + n * horizon
    )

    def starter_index(
        offset: int,
        player_index: int,
    ) -> int:
        return (
            n
            + offset * n
            + player_index
        )

    objective = np.zeros(
        total_variables
    )

    points_by_player = {}

    for row in rows:
        points_by_player[
            row.player_id
        ] = _gameweek_points(
            projections_by_id[
                row.player_id
            ]
        )

    for offset, gameweek in enumerate(
        gameweeks
    ):
        weight = weights[
            offset
        ]

        for index, row in enumerate(
            rows
        ):
            objective[
                starter_index(
                    offset,
                    index,
                )
            ] = -(
                weight
                * points_by_player[
                    row.player_id
                ].get(
                    gameweek,
                    0.0,
                )
            )

    constraints = []

    # Keep the current 15-player positional
    # structure.
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

    for position, required in (
        position_counts.items()
    ):

        vector = np.zeros(
            total_variables
        )

        for index, row in enumerate(
            rows
        ):
            if row.position == position:
                vector[index] = 1.0

        constraints.append(
            LinearConstraint(
                vector,
                lb=float(required),
                ub=float(required),
            )
        )

    # Final squad maximum:
    # 3 players per club.
    for team_id in {
        row.team_id
        for row in rows
    }:

        vector = np.zeros(
            total_variables
        )

        for index, row in enumerate(
            rows
        ):
            if row.team_id == team_id:
                vector[index] = 1.0

        constraints.append(
            LinearConstraint(
                vector,
                lb=-np.inf,
                ub=float(
                    MAX_PLAYERS_PER_TEAM
                ),
            )
        )

    # Exact number of incoming players.
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
            vector[index] = 1.0

    constraints.append(
        LinearConstraint(
            vector,
            lb=float(
                exact_transfers
            ),
            ub=float(
                exact_transfers
            ),
        )
    )

    # Budget using actual selling prices
    # for owned players.
    budget_vector = np.zeros(
        total_variables
    )

    liquidation_value = (
        state.bank_tenths
    )

    for index, row in enumerate(
        rows
    ):

        if row.player_id in current:

            selling_price = int(
                state
                .selling_prices_tenths[
                    row.player_id
                ]
            )

            budget_vector[
                index
            ] = float(
                selling_price
            )

            liquidation_value += (
                selling_price
            )

        else:
            budget_vector[
                index
            ] = float(
                row.price_tenths
            )

    constraints.append(
        LinearConstraint(
            budget_vector,
            lb=-np.inf,
            ub=float(
                liquidation_value
            ),
        )
    )

    # Separate legal XI for every GW.
    for offset, gameweek in enumerate(
        gameweeks
    ):

        starter_total = np.zeros(
            total_variables
        )

        for index in range(n):
            starter_total[
                starter_index(
                    offset,
                    index,
                )
            ] = 1.0

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

            formation = np.zeros(
                total_variables
            )

            for index, row in enumerate(
                rows
            ):
                if row.position == position:
                    formation[
                        starter_index(
                            offset,
                            index,
                        )
                    ] = 1.0

            constraints.append(
                LinearConstraint(
                    formation,
                    lb=float(
                        minimum
                    ),
                    ub=float(
                        maximum
                    ),
                )
            )

        # starter_i,g <= squad_i
        for index in range(n):

            linked = np.zeros(
                total_variables
            )

            linked[index] = -1.0

            linked[
                starter_index(
                    offset,
                    index,
                )
            ] = 1.0

            constraints.append(
                LinearConstraint(
                    linked,
                    lb=-np.inf,
                    ub=0.0,
                )
            )

    result = milp(
        c=objective,
        integrality=np.ones(
            total_variables,
            dtype=int,
        ),
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

    selected = {
        rows[index].player_id
        for index in range(n)
        if result.x[index] >= 0.5
    }

    outgoing = tuple(
        sorted(
            current
            - selected
        )
    )

    incoming = tuple(
        sorted(
            selected
            - current
        )
    )

    final_lineups = []

    final_benches = []

    final_weighted_ev = 0.0

    for offset, gameweek in enumerate(
        gameweeks
    ):

        starters = tuple(
            sorted(
                rows[index].player_id
                for index in range(n)
                if (
                    result.x[
                        starter_index(
                            offset,
                            index,
                        )
                    ]
                    >= 0.5
                )
            )
        )

        starter_set = set(
            starters
        )

        bench = tuple(
            sorted(
                selected
                - starter_set
            )
        )

        raw_ev = sum(
            points_by_player[
                player_id
            ].get(
                gameweek,
                0.0,
            )
            for player_id
            in starters
        )

        final_weighted_ev += (
            raw_ev
            * weights[offset]
        )

        final_lineups.append(
            (
                gameweek,
                starters,
            )
        )

        final_benches.append(
            (
                gameweek,
                bench,
            )
        )

    (
        current_weighted_ev,
        _,
    ) = _best_fixed_squad_lineups(
        squad_ids=current,
        by_id=by_id,
        projections_by_id=(
            projections_by_id
        ),
        gameweeks=gameweeks,
        weights=weights,
    )

    bank_after = (
        state.bank_tenths
        + sum(
            int(
                state
                .selling_prices_tenths[
                    player_id
                ]
            )
            for player_id
            in outgoing
        )
        - sum(
            by_id[
                player_id
            ].price_tenths
            for player_id
            in incoming
        )
    )

    if bank_after < 0:
        raise DecisionError(
            "optimizer produced "
            "negative bank"
        )

    return MultiGameweekTransferPlan(
        horizon=horizon,
        transfer_count=(
            exact_transfers
        ),
        first_gameweek=(
            first_gameweek
        ),
        last_gameweek=(
            first_gameweek
            + horizon
            - 1
        ),
        current_weighted_lineup_ev=(
            current_weighted_ev
        ),
        final_weighted_lineup_ev=(
            final_weighted_ev
        ),
        gain=(
            final_weighted_ev
            - current_weighted_ev
        ),
        bank_before_tenths=(
            state.bank_tenths
        ),
        bank_after_tenths=(
            bank_after
        ),
        outgoing_player_ids=(
            outgoing
        ),
        incoming_player_ids=(
            incoming
        ),
        final_player_ids=tuple(
            sorted(
                selected
            )
        ),
        starting_xi_by_gameweek=tuple(
            final_lineups
        ),
        bench_by_gameweek=tuple(
            final_benches
        ),
    )



@dataclass(frozen=True)
class MultiGameweekCaptaincyTransferPlan:
    horizon: int
    transfer_count: int

    first_gameweek: int
    last_gameweek: int

    current_weighted_total_ev: float

    final_weighted_xi_ev: float
    final_weighted_captain_bonus_ev: float
    final_weighted_total_ev: float

    gain: float

    bank_before_tenths: int
    bank_after_tenths: int

    outgoing_player_ids: tuple[str, ...]
    incoming_player_ids: tuple[str, ...]
    final_player_ids: tuple[str, ...]

    starting_xi_by_gameweek: tuple[
        tuple[
            int,
            tuple[str, ...],
        ],
        ...
    ]

    captain_by_gameweek: tuple[
        tuple[int, str],
        ...
    ]


def optimize_multi_gameweek_transfers_with_captaincy(
    *,
    players: Iterable[PlayerValue],
    projections_by_id: dict[
        str,
        PlayerDecisionProjection,
    ],
    state: SquadState,
    horizon: int,
    exact_transfers: int,
) -> MultiGameweekCaptaincyTransferPlan | None:

    from .captaincy import (
        evaluate_squad_with_captaincy,
    )

    if horizon not in {
        3,
        6,
    }:
        raise DecisionError(
            "horizon must be 3 or 6"
        )

    if exact_transfers < 0:
        raise DecisionError(
            "exact_transfers cannot be negative"
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

    if current - set(by_id):
        raise DecisionError(
            "squad contains unknown players"
        )

    if current - set(
        projections_by_id
    ):
        raise DecisionError(
            "missing projections "
            "for current squad"
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

    points_by_player = {
        row.player_id: (
            _gameweek_points(
                projections_by_id[
                    row.player_id
                ]
            )
        )
        for row in rows
    }

    n = len(rows)

    # Variables:
    #
    # 0:n
    #   final 15-player squad
    #
    # next horizon*n
    #   starting XI per GW
    #
    # next horizon*n
    #   captain per GW

    starter_base = n

    captain_base = (
        n
        + horizon * n
    )

    total_variables = (
        n
        + 2 * horizon * n
    )

    def starter_index(
        offset,
        player_index,
    ):
        return (
            starter_base
            + offset * n
            + player_index
        )

    def captain_index(
        offset,
        player_index,
    ):
        return (
            captain_base
            + offset * n
            + player_index
        )

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
                points_by_player[
                    row.player_id
                ].get(
                    gameweek,
                    0.0,
                )
            )

            # Normal XI points.
            objective[
                starter_index(
                    offset,
                    index,
                )
            ] = -(
                weight
                * points
            )

            # Captain gets one extra copy.
            objective[
                captain_index(
                    offset,
                    index,
                )
            ] = -(
                weight
                * points
            )

    constraints = []

    #
    # FINAL SQUAD STRUCTURE
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
                vector[index] = 1.0

        constraints.append(
            LinearConstraint(
                vector,
                lb=float(required),
                ub=float(required),
            )
        )

    #
    # MAX 3 PER CLUB
    #

    for team_id in {
        row.team_id
        for row in rows
    }:

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
                vector[index] = 1.0

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
    # EXACT TRANSFER COUNT
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
            vector[index] = 1.0

    constraints.append(
        LinearConstraint(
            vector,
            lb=float(
                exact_transfers
            ),
            ub=float(
                exact_transfers
            ),
        )
    )

    #
    # BUDGET
    #

    budget_vector = np.zeros(
        total_variables
    )

    liquidation_value = (
        state.bank_tenths
    )

    for index, row in enumerate(
        rows
    ):

        if row.player_id in current:

            selling_price = int(
                state
                .selling_prices_tenths[
                    row.player_id
                ]
            )

            budget_vector[
                index
            ] = float(
                selling_price
            )

            liquidation_value += (
                selling_price
            )

        else:

            budget_vector[
                index
            ] = float(
                row.price_tenths
            )

    constraints.append(
        LinearConstraint(
            budget_vector,
            lb=-np.inf,
            ub=float(
                liquidation_value
            ),
        )
    )

    #
    # XI + CAPTAIN FOR EACH GW
    #

    for offset, gameweek in enumerate(
        gameweeks
    ):

        #
        # Exactly 11 starters.
        #

        starter_total = np.zeros(
            total_variables
        )

        for index in range(n):

            starter_total[
                starter_index(
                    offset,
                    index,
                )
            ] = 1.0

        constraints.append(
            LinearConstraint(
                starter_total,
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

            formation = np.zeros(
                total_variables
            )

            for index, row in enumerate(
                rows
            ):

                if (
                    row.position
                    == position
                ):
                    formation[
                        starter_index(
                            offset,
                            index,
                        )
                    ] = 1.0

            constraints.append(
                LinearConstraint(
                    formation,
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
        # to final squad.
        #

        for index in range(n):

            linked = np.zeros(
                total_variables
            )

            linked[index] = -1.0

            linked[
                starter_index(
                    offset,
                    index,
                )
            ] = 1.0

            constraints.append(
                LinearConstraint(
                    linked,
                    lb=-np.inf,
                    ub=0.0,
                )
            )

        #
        # Exactly one captain.
        #

        captain_total = np.zeros(
            total_variables
        )

        for index in range(n):

            captain_total[
                captain_index(
                    offset,
                    index,
                )
            ] = 1.0

        constraints.append(
            LinearConstraint(
                captain_total,
                lb=1.0,
                ub=1.0,
            )
        )

        #
        # Captain must be starter.
        #

        for index in range(n):

            linked = np.zeros(
                total_variables
            )

            linked[
                starter_index(
                    offset,
                    index,
                )
            ] = -1.0

            linked[
                captain_index(
                    offset,
                    index,
                )
            ] = 1.0

            constraints.append(
                LinearConstraint(
                    linked,
                    lb=-np.inf,
                    ub=0.0,
                )
            )

    result = milp(
        c=objective,
        integrality=np.ones(
            total_variables,
            dtype=int,
        ),
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

    selected = {
        rows[index].player_id
        for index in range(n)
        if (
            result.x[index]
            >= 0.5
        )
    }

    outgoing = tuple(
        sorted(
            current
            - selected
        )
    )

    incoming = tuple(
        sorted(
            selected
            - current
        )
    )

    final_lineups = []

    final_captains = []

    weighted_xi = 0.0
    weighted_captain = 0.0

    for offset, gameweek in enumerate(
        gameweeks
    ):

        starters = tuple(
            sorted(
                rows[index].player_id
                for index in range(n)
                if (
                    result.x[
                        starter_index(
                            offset,
                            index,
                        )
                    ]
                    >= 0.5
                )
            )
        )

        captains = [
            rows[index].player_id
            for index in range(n)
            if (
                result.x[
                    captain_index(
                        offset,
                        index,
                    )
                ]
                >= 0.5
            )
        ]

        if len(captains) != 1:
            raise DecisionError(
                "optimizer did not choose "
                "exactly one captain"
            )

        captain = captains[0]

        raw_xi = sum(
            points_by_player[
                player_id
            ].get(
                gameweek,
                0.0,
            )
            for player_id
            in starters
        )

        raw_captain = (
            points_by_player[
                captain
            ].get(
                gameweek,
                0.0,
            )
        )

        weight = weights[offset]

        weighted_xi += (
            weight
            * raw_xi
        )

        weighted_captain += (
            weight
            * raw_captain
        )

        final_lineups.append(
            (
                gameweek,
                starters,
            )
        )

        final_captains.append(
            (
                gameweek,
                captain,
            )
        )

    current_eval = (
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
        + weighted_captain
    )

    bank_after = (
        state.bank_tenths
        + sum(
            int(
                state
                .selling_prices_tenths[
                    player_id
                ]
            )
            for player_id
            in outgoing
        )
        - sum(
            by_id[
                player_id
            ].price_tenths
            for player_id
            in incoming
        )
    )

    if bank_after < 0:
        raise DecisionError(
            "optimizer produced "
            "negative bank"
        )

    return (
        MultiGameweekCaptaincyTransferPlan(
            horizon=horizon,
            transfer_count=(
                exact_transfers
            ),
            first_gameweek=(
                first_gameweek
            ),
            last_gameweek=(
                first_gameweek
                + horizon
                - 1
            ),
            current_weighted_total_ev=(
                current_eval
                .weighted_total_ev
            ),
            final_weighted_xi_ev=(
                weighted_xi
            ),
            final_weighted_captain_bonus_ev=(
                weighted_captain
            ),
            final_weighted_total_ev=(
                final_total
            ),
            gain=(
                final_total
                - current_eval
                .weighted_total_ev
            ),
            bank_before_tenths=(
                state.bank_tenths
            ),
            bank_after_tenths=(
                bank_after
            ),
            outgoing_player_ids=(
                outgoing
            ),
            incoming_player_ids=(
                incoming
            ),
            final_player_ids=tuple(
                sorted(
                    selected
                )
            ),
            starting_xi_by_gameweek=tuple(
                final_lineups
            ),
            captain_by_gameweek=tuple(
                final_captains
            ),
        )
    )
