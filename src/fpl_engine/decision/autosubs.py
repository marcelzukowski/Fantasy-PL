from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from itertools import combinations, permutations
import math
from typing import Mapping, Iterable


POSITIONS = (
    "GK",
    "DEF",
    "MID",
    "FWD",
)


class AutosubError(ValueError):
    pass


@dataclass(frozen=True)
class AutosubLineupEvaluation:
    gameweek: int
    starter_ids: tuple[str, ...]
    bench_gk_id: str
    bench_outfield_ids: tuple[str, ...]
    base_xi_ev: float
    expected_gk_autosub_ev: float
    expected_outfield_autosub_ev: float
    total_ev: float


def _probability(
    value: float,
    label: str,
) -> float:

    result = float(value)

    if (
        not math.isfinite(result)
        or not 0.0 <= result <= 1.0
    ):
        raise AutosubError(
            f"{label} must be in [0, 1]"
        )

    return result


def _valid_formation(
    counts: Mapping[str, int],
) -> bool:

    return (
        3 <= counts.get("DEF", 0) <= 5
        and 2 <= counts.get("MID", 0) <= 5
        and 1 <= counts.get("FWD", 0) <= 3
        and (
            counts.get("DEF", 0)
            + counts.get("MID", 0)
            + counts.get("FWD", 0)
        )
        == 10
    )


def _dnp_count_distribution(
    player_ids: Iterable[str],
    p_appearance: Mapping[str, float],
) -> dict[int, float]:

    distribution = {
        0: 1.0
    }

    for player_id in player_ids:

        p = _probability(
            p_appearance[player_id],
            f"p_appearance[{player_id}]",
        )

        q = 1.0 - p

        updated = {}

        for count, probability in (
            distribution.items()
        ):

            updated[count] = (
                updated.get(
                    count,
                    0.0,
                )
                + probability * p
            )

            updated[count + 1] = (
                updated.get(
                    count + 1,
                    0.0,
                )
                + probability * q
            )

        distribution = updated

    return distribution


def _selected_subset_feasible(
    *,
    starting_counts: Mapping[str, int],
    dnp_counts: Mapping[str, int],
    selected_positions: tuple[str, ...],
) -> bool:

    replacement_count = len(
        selected_positions
    )

    if replacement_count == 0:
        return True

    if replacement_count > sum(
        dnp_counts.values()
    ):
        return False

    bench_counts = {
        "DEF": selected_positions.count(
            "DEF"
        ),
        "MID": selected_positions.count(
            "MID"
        ),
        "FWD": selected_positions.count(
            "FWD"
        ),
    }

    #
    # Choose which missing starter
    # position(s) the bench players
    # replace.
    #

    for replace_def in range(
        min(
            dnp_counts.get(
                "DEF",
                0,
            ),
            replacement_count,
        )
        + 1
    ):

        for replace_mid in range(
            min(
                dnp_counts.get(
                    "MID",
                    0,
                ),
                replacement_count
                - replace_def,
            )
            + 1
        ):

            replace_fwd = (
                replacement_count
                - replace_def
                - replace_mid
            )

            if replace_fwd < 0:
                continue

            if replace_fwd > dnp_counts.get(
                "FWD",
                0,
            ):
                continue

            counts = {
                "DEF": (
                    starting_counts["DEF"]
                    - replace_def
                    + bench_counts["DEF"]
                ),
                "MID": (
                    starting_counts["MID"]
                    - replace_mid
                    + bench_counts["MID"]
                ),
                "FWD": (
                    starting_counts["FWD"]
                    - replace_fwd
                    + bench_counts["FWD"]
                ),
            }

            if _valid_formation(
                counts
            ):
                return True

    return False


def _select_outfield_bench(
    *,
    bench_order: tuple[str, ...],
    appeared: set[str],
    positions: Mapping[str, str],
    starting_counts: Mapping[str, int],
    dnp_counts: Mapping[str, int],
) -> tuple[str, ...]:
    bench_positions = tuple(positions[player_id] for player_id in bench_order)
    appeared_mask = sum(1 << index for index, player_id in enumerate(bench_order) if player_id in appeared)
    selected_indexes = _select_outfield_bench_indexes(
        bench_positions, appeared_mask,
        (starting_counts["DEF"], starting_counts["MID"], starting_counts["FWD"]),
        (dnp_counts.get("DEF", 0), dnp_counts.get("MID", 0), dnp_counts.get("FWD", 0)),
    )
    return tuple(bench_order[index] for index in selected_indexes)


@lru_cache(maxsize=300_000)
def _select_outfield_bench_indexes(
    bench_positions: tuple[str, str, str],
    appeared_mask: int,
    starting_counts_tuple: tuple[int, int, int],
    dnp_counts_tuple: tuple[int, int, int],
) -> tuple[int, ...]:
    """Exact bench selection based only on the structural autosub state."""
    available = tuple(index for index in range(3) if appeared_mask & (1 << index))
    maximum = min(len(available), sum(dnp_counts_tuple))
    starting_counts = dict(zip(("DEF", "MID", "FWD"), starting_counts_tuple, strict=True))
    dnp_counts = dict(zip(("DEF", "MID", "FWD"), dnp_counts_tuple, strict=True))
    for count in range(maximum, -1, -1):
        for selected in combinations(available, count):
            if _selected_subset_feasible(
                starting_counts=starting_counts,
                dnp_counts=dnp_counts,
                selected_positions=tuple(bench_positions[index] for index in selected),
            ):
                return selected
    return ()


def _conditional_ev(
    *,
    player_id: str,
    expected_points: Mapping[
        str,
        float,
    ],
    p_appearance: Mapping[
        str,
        float,
    ],
) -> float:

    ev = float(
        expected_points[player_id]
    )

    p = _probability(
        p_appearance[player_id],
        f"p_appearance[{player_id}]",
    )

    if p <= 1e-12:

        if abs(ev) > 1e-9:
            raise AutosubError(
                "non-zero EV with zero "
                "appearance probability "
                f"for {player_id}"
            )

        return 0.0

    return ev / p


def evaluate_autosub_lineup(
    *,
    gameweek: int,
    starter_ids: Iterable[str],
    bench_gk_id: str,
    bench_outfield_ids: Iterable[str],
    positions: Mapping[str, str],
    expected_points: Mapping[str, float],
    p_appearance: Mapping[str, float],
) -> AutosubLineupEvaluation:

    starters = tuple(
        starter_ids
    )

    bench_outfield = tuple(
        bench_outfield_ids
    )

    if len(starters) != 11:
        raise AutosubError(
            "starting XI must contain 11 players"
        )

    if len(bench_outfield) != 3:
        raise AutosubError(
            "outfield bench must contain 3 players"
        )

    all_ids = (
        starters
        + (bench_gk_id,)
        + bench_outfield
    )

    if len(set(all_ids)) != 15:
        raise AutosubError(
            "lineup must contain "
            "15 unique players"
        )

    starting_gks = tuple(
        player_id
        for player_id in starters
        if positions[player_id] == "GK"
    )

    if len(starting_gks) != 1:
        raise AutosubError(
            "starting XI must contain 1 GK"
        )

    if positions[bench_gk_id] != "GK":
        raise AutosubError(
            "bench goalkeeper must be GK"
        )

    outfield_starters = tuple(
        player_id
        for player_id in starters
        if positions[player_id] != "GK"
    )

    starting_counts = {
        "DEF": sum(
            positions[player_id] == "DEF"
            for player_id
            in outfield_starters
        ),
        "MID": sum(
            positions[player_id] == "MID"
            for player_id
            in outfield_starters
        ),
        "FWD": sum(
            positions[player_id] == "FWD"
            for player_id
            in outfield_starters
        ),
    }

    if not _valid_formation(
        starting_counts
    ):
        raise AutosubError(
            "illegal starting formation"
        )

    for player_id in bench_outfield:

        if positions[player_id] == "GK":
            raise AutosubError(
                "GK cannot be on "
                "outfield bench"
            )

    base_xi_ev = sum(
        float(
            expected_points[player_id]
        )
        for player_id in starters
    )

    #
    # GK autosub:
    #
    # P(starting GK DNP)
    # × unconditional bench-GK EV.
    #

    starting_gk = starting_gks[0]

    starting_gk_q = (
        1.0
        - _probability(
            p_appearance[
                starting_gk
            ],
            "starting GK appearance",
        )
    )

    expected_gk_autosub_ev = (
        starting_gk_q
        * float(
            expected_points[
                bench_gk_id
            ]
        )
    )

    #
    # Outfield DNP-count distributions
    # by position.
    #

    by_position = {
        position: tuple(
            player_id
            for player_id
            in outfield_starters
            if positions[player_id]
            == position
        )
        for position in (
            "DEF",
            "MID",
            "FWD",
        )
    }

    dnp_distributions = {
        position:
        _dnp_count_distribution(
            ids,
            p_appearance,
        )
        for position, ids
        in by_position.items()
    }

    conditional_bench_ev = {
        player_id:
        _conditional_ev(
            player_id=player_id,
            expected_points=(
                expected_points
            ),
            p_appearance=(
                p_appearance
            ),
        )
        for player_id
        in bench_outfield
    }

    expected_outfield_autosub_ev = 0.0

    for dnp_def, prob_def in (
        dnp_distributions[
            "DEF"
        ].items()
    ):

        for dnp_mid, prob_mid in (
            dnp_distributions[
                "MID"
            ].items()
        ):

            for dnp_fwd, prob_fwd in (
                dnp_distributions[
                    "FWD"
                ].items()
            ):

                dnp_probability = (
                    prob_def
                    * prob_mid
                    * prob_fwd
                )

                if dnp_probability == 0.0:
                    continue

                dnp_counts = {
                    "DEF": dnp_def,
                    "MID": dnp_mid,
                    "FWD": dnp_fwd,
                }

                #
                # Only three outfield bench
                # players => 8 appearance
                # states.
                #

                for mask in range(8):

                    appeared = set()
                    bench_probability = 1.0

                    for index, player_id in enumerate(
                        bench_outfield
                    ):

                        p = _probability(
                            p_appearance[
                                player_id
                            ],
                            (
                                "bench appearance "
                                f"{player_id}"
                            ),
                        )

                        if mask & (
                            1 << index
                        ):

                            appeared.add(
                                player_id
                            )

                            bench_probability *= p

                        else:

                            bench_probability *= (
                                1.0 - p
                            )

                    if bench_probability == 0.0:
                        continue

                    selected = (
                        _select_outfield_bench(
                            bench_order=(
                                bench_outfield
                            ),
                            appeared=appeared,
                            positions=positions,
                            starting_counts=(
                                starting_counts
                            ),
                            dnp_counts=(
                                dnp_counts
                            ),
                        )
                    )

                    bench_points = sum(
                        conditional_bench_ev[
                            player_id
                        ]
                        for player_id
                        in selected
                    )

                    expected_outfield_autosub_ev += (
                        dnp_probability
                        * bench_probability
                        * bench_points
                    )

    total_ev = (
        base_xi_ev
        + expected_gk_autosub_ev
        + expected_outfield_autosub_ev
    )

    return AutosubLineupEvaluation(
        gameweek=gameweek,
        starter_ids=starters,
        bench_gk_id=bench_gk_id,
        bench_outfield_ids=bench_outfield,
        base_xi_ev=base_xi_ev,
        expected_gk_autosub_ev=(
            expected_gk_autosub_ev
        ),
        expected_outfield_autosub_ev=(
            expected_outfield_autosub_ev
        ),
        total_ev=total_ev,
    )


def optimize_autosub_lineup(
    *,
    gameweek: int,
    squad_ids: Iterable[str],
    positions: Mapping[str, str],
    expected_points: Mapping[str, float],
    p_appearance: Mapping[str, float],
) -> AutosubLineupEvaluation:

    squad = tuple(
        sorted(
            squad_ids
        )
    )

    if len(squad) != 15:
        raise AutosubError(
            "squad must contain 15 players"
        )

    groups = {
        position: tuple(
            player_id
            for player_id in squad
            if positions[player_id]
            == position
        )
        for position in POSITIONS
    }

    expected_shape = {
        "GK": 2,
        "DEF": 5,
        "MID": 5,
        "FWD": 3,
    }

    actual_shape = {
        position: len(ids)
        for position, ids
        in groups.items()
    }

    if actual_shape != expected_shape:
        raise AutosubError(
            "invalid squad position shape: "
            f"{actual_shape}"
        )

    best = None

    for starting_gk in groups["GK"]:

        bench_gk = next(
            player_id
            for player_id
            in groups["GK"]
            if player_id
            != starting_gk
        )

        for defenders_count in range(
            3,
            6,
        ):

            for midfielders_count in range(
                2,
                6,
            ):

                forwards_count = (
                    10
                    - defenders_count
                    - midfielders_count
                )

                if not (
                    1
                    <= forwards_count
                    <= 3
                ):
                    continue

                for defenders in combinations(
                    groups["DEF"],
                    defenders_count,
                ):

                    for midfielders in combinations(
                        groups["MID"],
                        midfielders_count,
                    ):

                        for forwards in combinations(
                            groups["FWD"],
                            forwards_count,
                        ):

                            outfield_starters = (
                                defenders
                                + midfielders
                                + forwards
                            )

                            starters = (
                                (starting_gk,)
                                + outfield_starters
                            )

                            starter_set = set(
                                starters
                            )

                            bench_pool = tuple(
                                player_id
                                for player_id
                                in squad
                                if (
                                    player_id
                                    not in starter_set
                                    and positions[
                                        player_id
                                    ]
                                    != "GK"
                                )
                            )

                            for bench_order in permutations(
                                bench_pool
                            ):

                                evaluation = (
                                    evaluate_autosub_lineup(
                                        gameweek=(
                                            gameweek
                                        ),
                                        starter_ids=(
                                            starters
                                        ),
                                        bench_gk_id=(
                                            bench_gk
                                        ),
                                        bench_outfield_ids=(
                                            bench_order
                                        ),
                                        positions=(
                                            positions
                                        ),
                                        expected_points=(
                                            expected_points
                                        ),
                                        p_appearance=(
                                            p_appearance
                                        ),
                                    )
                                )

                                if (
                                    best is None
                                    or evaluation.total_ev
                                    > best.total_ev
                                    + 1e-12
                                ):
                                    best = evaluation

    if best is None:
        raise AutosubError(
            "no legal lineup found"
        )

    return best
