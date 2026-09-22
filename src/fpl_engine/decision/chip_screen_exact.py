from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations, permutations
from typing import Iterable, Mapping

from .autosubs import (
    evaluate_autosub_lineup,
)
from .captaincy_value import (
    best_captaincy_pair,
)


ALL_CAPTAIN_POSITIONS = (
    "GK",
    "DEF",
    "MID",
    "FWD",
)

SUPPORTED_CHIPS = {
    "normal",
    "wildcard",
    "free_hit",
    "bench_boost",
    "triple_captain",
}


class ExactChipScreenError(
    RuntimeError
):
    pass


@dataclass(
    frozen=True
)
class ExactChipGameweekEvaluation:

    gameweek: int
    chip: str

    starter_ids: tuple[
        str,
        ...,
    ]

    bench_gk_id: str

    bench_outfield_ids: tuple[
        str,
        ...,
    ]

    formation: str

    captain_id: str
    vice_id: str

    base_xi_ev: float

    expected_autosub_ev: float

    bench_boost_bench_ev: float

    captain_bonus_ev: float

    total_ev: float


@dataclass(
    frozen=True
)
class ExactChipSquadEvaluation:

    chip: str

    horizon: int

    first_gameweek: int

    last_gameweek: int

    weighted_base_xi_ev: float

    weighted_sub_or_bench_ev: float

    weighted_captain_bonus_ev: float

    weighted_total_ev: float

    gameweeks: tuple[
        ExactChipGameweekEvaluation,
        ...,
    ]


def _gameweek_ev(
    projection,
    gameweek: int,
) -> float:

    for row in projection.gameweeks:

        if int(
            row.gameweek
        ) == gameweek:

            return float(
                row.expected_points
            )


    raise ExactChipScreenError(
        "missing gameweek projection "
        f"{projection.player_id} "
        f"GW{gameweek}"
    )


def _legal_xi(
    player_ids: Iterable[str],
    positions: Mapping[
        str,
        str,
    ],
) -> bool:

    ids = tuple(
        player_ids
    )


    if len(
        ids
    ) != 11:

        return False


    counts = {
        position:
            sum(
                positions[
                    player_id
                ] == position
                for player_id
                in ids
            )
        for position
        in ALL_CAPTAIN_POSITIONS
    }


    return all((
        counts[
            "GK"
        ] == 1,

        3
        <= counts[
            "DEF"
        ]
        <= 5,

        2
        <= counts[
            "MID"
        ]
        <= 5,

        1
        <= counts[
            "FWD"
        ]
        <= 3,
    ))


def _formation(
    player_ids: Iterable[str],
    positions: Mapping[
        str,
        str,
    ],
) -> str:

    ids = tuple(
        player_ids
    )

    return (
        f"{sum(positions[p] == 'DEF' for p in ids)}-"
        f"{sum(positions[p] == 'MID' for p in ids)}-"
        f"{sum(positions[p] == 'FWD' for p in ids)}"
    )


def _candidate_key(
    result: ExactChipGameweekEvaluation,
):

    return (
        tuple(
            sorted(
                result.starter_ids
            )
        ),

        result.bench_gk_id,

        result.bench_outfield_ids,

        result.captain_id,

        result.vice_id,
    )


def _validate_squad(
    *,
    squad_player_ids,
    positions,
):

    squad = tuple(
        str(
            player_id
        )
        for player_id
        in squad_player_ids
    )


    if len(
        squad
    ) != 15:

        raise ExactChipScreenError(
            "exact chip scoring requires "
            "a 15-player FPL squad"
        )


    if len(
        set(
            squad
        )
    ) != 15:

        raise ExactChipScreenError(
            "squad contains duplicate players"
        )


    missing_positions = [
        player_id
        for player_id
        in squad
        if player_id
        not in positions
    ]


    if missing_positions:

        raise ExactChipScreenError(
            "missing positions for: "
            + ", ".join(
                sorted(
                    missing_positions
                )
            )
        )


    counts = {
        position:
            sum(
                positions[
                    player_id
                ] == position
                for player_id
                in squad
            )
        for position
        in ALL_CAPTAIN_POSITIONS
    }


    expected = {
        "GK": 2,
        "DEF": 5,
        "MID": 5,
        "FWD": 3,
    }


    if counts != expected:

        raise ExactChipScreenError(
            "invalid FPL squad structure: "
            f"{counts}"
        )


    return squad


def _evaluate_gameweek(
    *,
    chip: str,
    gameweek: int,
    squad: tuple[str, ...],
    positions: Mapping[str, str],
    expected_points: Mapping[str, float],
    p_appearance: Mapping[str, float],
    allowed_captain_positions,
) -> ExactChipGameweekEvaluation:

    goalkeepers = tuple(
        player_id
        for player_id
        in squad
        if positions[
            player_id
        ] == "GK"
    )


    outfield = tuple(
        player_id
        for player_id
        in squad
        if positions[
            player_id
        ] != "GK"
    )


    best = None


    for starting_gk in goalkeepers:

        bench_gk = next(
            player_id
            for player_id
            in goalkeepers
            if player_id
            != starting_gk
        )


        for starting_outfield in combinations(
            outfield,
            10,
        ):

            starters = (
                starting_gk,
                *starting_outfield,
            )


            if not _legal_xi(
                starters,
                positions,
            ):

                continue


            pair = (
                best_captaincy_pair(
                    player_ids=starters,

                    expected_points=(
                        expected_points
                    ),

                    p_appearance=(
                        p_appearance
                    ),

                    positions=positions,

                    allowed_positions=(
                        allowed_captain_positions
                    ),
                )
            )


            captain_multiplier = (
                2.0
                if chip
                == "triple_captain"
                else 1.0
            )


            captain_bonus = (
                captain_multiplier
                * float(
                    pair.captain_bonus
                )
            )


            bench_outfield = tuple(
                player_id
                for player_id
                in outfield
                if player_id
                not in starting_outfield
            )


            if len(
                bench_outfield
            ) != 3:

                raise ExactChipScreenError(
                    "expected three "
                    "outfield substitutes"
                )


            #
            # BENCH BOOST:
            #
            # all 15 players score.
            # Bench order / autosub probability
            # therefore does not affect EV.
            #
            if chip == "bench_boost":

                ordered_bench = tuple(
                    sorted(
                        bench_outfield,
                        key=lambda player_id: (
                            -expected_points[
                                player_id
                            ],
                            player_id,
                        ),
                    )
                )


                base_xi = sum(
                    expected_points[
                        player_id
                    ]
                    for player_id
                    in starters
                )


                bench_ev = (
                    expected_points[
                        bench_gk
                    ]
                    + sum(
                        expected_points[
                            player_id
                        ]
                        for player_id
                        in ordered_bench
                    )
                )


                candidate = (
                    ExactChipGameweekEvaluation(
                        gameweek=gameweek,

                        chip=chip,

                        starter_ids=tuple(
                            starters
                        ),

                        bench_gk_id=(
                            bench_gk
                        ),

                        bench_outfield_ids=(
                            ordered_bench
                        ),

                        formation=_formation(
                            starters,
                            positions,
                        ),

                        captain_id=(
                            pair.captain_id
                        ),

                        vice_id=(
                            pair.vice_id
                        ),

                        base_xi_ev=float(
                            base_xi
                        ),

                        expected_autosub_ev=0.0,

                        bench_boost_bench_ev=float(
                            bench_ev
                        ),

                        captain_bonus_ev=float(
                            captain_bonus
                        ),

                        total_ev=float(
                            base_xi
                            + bench_ev
                            + captain_bonus
                        ),
                    )
                )


                if (
                    best is None
                    or candidate.total_ev
                    > best.total_ev
                    + 1e-12
                    or (
                        abs(
                            candidate.total_ev
                            - best.total_ev
                        )
                        <= 1e-12
                        and _candidate_key(
                            candidate
                        )
                        < _candidate_key(
                            best
                        )
                    )
                ):

                    best = candidate


                continue


            #
            # NORMAL / WC / FH / TC:
            #
            # enumerate all three outfield bench orders.
            #
            for bench_order in permutations(
                bench_outfield
            ):

                autosub = (
                    evaluate_autosub_lineup(
                        gameweek=gameweek,

                        starter_ids=(
                            starters
                        ),

                        bench_gk_id=(
                            bench_gk
                        ),

                        bench_outfield_ids=(
                            bench_order
                        ),

                        positions=positions,

                        expected_points=(
                            expected_points
                        ),

                        p_appearance=(
                            p_appearance
                        ),
                    )
                )


                autosub_ev = (
                    float(
                        autosub
                        .expected_gk_autosub_ev
                    )
                    + float(
                        autosub
                        .expected_outfield_autosub_ev
                    )
                )


                total = (
                    float(
                        autosub.total_ev
                    )
                    + captain_bonus
                )


                candidate = (
                    ExactChipGameweekEvaluation(
                        gameweek=gameweek,

                        chip=chip,

                        starter_ids=tuple(
                            autosub.starter_ids
                        ),

                        bench_gk_id=(
                            autosub.bench_gk_id
                        ),

                        bench_outfield_ids=tuple(
                            autosub
                            .bench_outfield_ids
                        ),

                        formation=_formation(
                            autosub.starter_ids,
                            positions,
                        ),

                        captain_id=(
                            pair.captain_id
                        ),

                        vice_id=(
                            pair.vice_id
                        ),

                        base_xi_ev=float(
                            autosub.base_xi_ev
                        ),

                        expected_autosub_ev=(
                            autosub_ev
                        ),

                        bench_boost_bench_ev=0.0,

                        captain_bonus_ev=float(
                            captain_bonus
                        ),

                        total_ev=float(
                            total
                        ),
                    )
                )


                if (
                    best is None
                    or candidate.total_ev
                    > best.total_ev
                    + 1e-12
                    or (
                        abs(
                            candidate.total_ev
                            - best.total_ev
                        )
                        <= 1e-12
                        and _candidate_key(
                            candidate
                        )
                        < _candidate_key(
                            best
                        )
                    )
                ):

                    best = candidate


    if best is None:

        raise ExactChipScreenError(
            f"no legal exact lineup for "
            f"GW{gameweek}"
        )


    return best


def evaluate_exact_chip_squad(
    *,
    squad_player_ids: Iterable[str],
    positions: Mapping[str, str],
    projections_by_id: Mapping[
        str,
        object,
    ],
    p_appearance_by_gameweek: Mapping[
        tuple[str, int],
        float,
    ],
    first_gameweek: int,
    horizon: int,
    weights: tuple[float, ...],
    chip: str | None = None,
    allowed_captain_positions=(
        ALL_CAPTAIN_POSITIONS
    ),
) -> ExactChipSquadEvaluation:
    """
    Exact fixed-15 scoring under the existing decision assumptions.

    Jointly searches, per Gameweek:
      - legal XI,
      - ordered outfield bench,
      - exact marginal-independence autosub EV,
      - captain + vice captain.

    For Bench Boost all 15 score.
    For Triple Captain the effective captain bonus is doubled.

    IMPORTANT:
    This scores a GIVEN 15-player squad exactly under those assumptions.
    It does not claim that an upstream unlimited-squad MILP selected the
    globally optimal 15 when autosubs/captaincy are nonlinear.
    """

    normalized_chip = (
        "normal"
        if chip is None
        else str(
            chip
        ).strip().lower()
    )


    if normalized_chip not in SUPPORTED_CHIPS:

        raise ExactChipScreenError(
            "unsupported chip: "
            f"{normalized_chip}"
        )


    if horizon < 1:

        raise ExactChipScreenError(
            "horizon must be positive"
        )


    if len(
        weights
    ) < horizon:

        raise ExactChipScreenError(
            "not enough horizon weights"
        )


    if (
        normalized_chip
        in {
            "free_hit",
            "bench_boost",
            "triple_captain",
        }
        and horizon != 1
    ):

        raise ExactChipScreenError(
            f"{normalized_chip} must be "
            "evaluated on one Gameweek"
        )


    squad = _validate_squad(
        squad_player_ids=(
            squad_player_ids
        ),

        positions=positions,
    )


    gameweek_results = []


    weighted_base = 0.0

    weighted_sub_or_bench = 0.0

    weighted_captain = 0.0

    weighted_total = 0.0


    for offset in range(
        horizon
    ):

        gameweek = (
            first_gameweek
            + offset
        )


        points = {}

        appearance = {}


        for player_id in squad:

            projection = (
                projections_by_id.get(
                    player_id
                )
            )


            if projection is None:

                raise ExactChipScreenError(
                    "missing projection for "
                    f"{player_id}"
                )


            points[
                player_id
            ] = _gameweek_ev(
                projection,
                gameweek,
            )


            key = (
                player_id,
                gameweek,
            )


            if key not in (
                p_appearance_by_gameweek
            ):

                raise ExactChipScreenError(
                    "missing appearance probability "
                    f"for {player_id} GW{gameweek}"
                )


            probability = float(
                p_appearance_by_gameweek[
                    key
                ]
            )


            if not (
                0.0
                <= probability
                <= 1.0
            ):

                raise ExactChipScreenError(
                    "appearance probability "
                    "outside [0, 1]"
                )


            appearance[
                player_id
            ] = probability


        result = _evaluate_gameweek(
            chip=normalized_chip,

            gameweek=gameweek,

            squad=squad,

            positions=positions,

            expected_points=points,

            p_appearance=appearance,

            allowed_captain_positions=(
                allowed_captain_positions
            ),
        )


        weight = float(
            weights[
                offset
            ]
        )


        weighted_base += (
            weight
            * result.base_xi_ev
        )


        weighted_sub_or_bench += (
            weight
            * (
                result.expected_autosub_ev
                + result.bench_boost_bench_ev
            )
        )


        weighted_captain += (
            weight
            * result.captain_bonus_ev
        )


        weighted_total += (
            weight
            * result.total_ev
        )


        gameweek_results.append(
            result
        )


    return ExactChipSquadEvaluation(
        chip=normalized_chip,

        horizon=horizon,

        first_gameweek=(
            first_gameweek
        ),

        last_gameweek=(
            first_gameweek
            + horizon
            - 1
        ),

        weighted_base_xi_ev=float(
            weighted_base
        ),

        weighted_sub_or_bench_ev=float(
            weighted_sub_or_bench
        ),

        weighted_captain_bonus_ev=float(
            weighted_captain
        ),

        weighted_total_ev=float(
            weighted_total
        ),

        gameweeks=tuple(
            gameweek_results
        ),
    )
