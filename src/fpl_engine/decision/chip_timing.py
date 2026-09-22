from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

from .chip_screen import (
    ExactChipScreen,
    ExactChipScreenEntry,
)
from .chip_screen_exact import (
    evaluate_exact_chip_squad,
)


TIMED_CHIPS = (
    "triple_captain",
    "bench_boost",
    "free_hit",
    "wildcard",
)


@dataclass(frozen=True)
class ExactChipTimingConfig:

    evaluation_horizon_gameweeks: int

    minimum_incremental_ev: float

    future_opportunity_tolerance: float

    wildcard_minimum_weighted_gain: float

    free_hit_minimum_single_gameweek_gain: float

    @classmethod
    def from_rules(
        cls,
        rules,
    ) -> "ExactChipTimingConfig":

        raw = rules.value(
            "chip_timing_v2"
        )

        return cls(
            evaluation_horizon_gameweeks=int(
                raw[
                    "evaluation_horizon_gameweeks"
                ]
            ),

            minimum_incremental_ev=float(
                raw[
                    "minimum_incremental_ev"
                ]
            ),

            future_opportunity_tolerance=float(
                raw[
                    "future_opportunity_tolerance"
                ]
            ),

            wildcard_minimum_weighted_gain=float(
                raw[
                    "wildcard_minimum_weighted_gain"
                ]
            ),

            free_hit_minimum_single_gameweek_gain=float(
                raw[
                    "free_hit_minimum_single_gameweek_gain"
                ]
            ),
        )


@dataclass(frozen=True)
class ExactFutureChipOpportunity:

    chip: str

    gameweek: int

    baseline_ev: float

    chip_ev: float

    incremental_ev: float


@dataclass(frozen=True)
class ExactChipTimingEvaluation:

    chip: str

    available: bool

    incremental_ev: float

    baseline_ev: float

    chip_ev: float

    threshold: float

    future_best_incremental_ev: (
        float
        | None
    )

    clears_threshold: bool

    competitive_with_future: bool

    use_now: bool

    reason: str


@dataclass(frozen=True)
class ExactChipTimingDecision:

    chosen_chip: str | None

    evaluations: tuple[
        ExactChipTimingEvaluation,
        ...,
    ]


class ExactChipTimingPolicy:

    VERSION = (
        "exact_chip_timing_v1"
    )

    def __init__(
        self,
        config: ExactChipTimingConfig,
    ):

        self.config = config


    def _threshold(
        self,
        chip: str,
    ) -> float:

        if chip == "wildcard":

            return float(
                self.config
                .wildcard_minimum_weighted_gain
            )


        if chip == "free_hit":

            return float(
                self.config
                .free_hit_minimum_single_gameweek_gain
            )


        return float(
            self.config
            .minimum_incremental_ev
        )


    def decide(
        self,
        *,
        screen: ExactChipScreen,
        future_opportunities: Mapping[
            str,
            Iterable[
                ExactFutureChipOpportunity
            ],
        ] = {},
        available_chips: Iterable[
            str
        ] = TIMED_CHIPS,
    ) -> ExactChipTimingDecision:

        available = frozenset(
            str(
                chip
            )
            for chip
            in available_chips
        )


        entries = {
            "triple_captain":
                screen.triple_captain,

            "bench_boost":
                screen.bench_boost,

            "free_hit":
                screen.free_hit,

            "wildcard":
                screen.wildcard,
        }


        evaluations = []


        for chip in TIMED_CHIPS:

            entry = entries[
                chip
            ]


            opportunities = tuple(
                future_opportunities.get(
                    chip,
                    (),
                )
            )


            future_best = (
                max(
                    (
                        float(
                            row.incremental_ev
                        )
                        for row
                        in opportunities
                    ),
                    default=None,
                )
            )


            threshold = (
                self._threshold(
                    chip
                )
            )


            incremental = float(
                entry.incremental_ev
            )


            clears = (
                incremental
                >= threshold
            )


            competitive = (
                future_best is None
                or incremental
                >= (
                    future_best
                    - self.config
                    .future_opportunity_tolerance
                )
            )


            is_available = (
                chip in available
            )


            use_now = all((
                is_available,
                clears,
                competitive,
            ))


            if not is_available:

                reason = (
                    "chip is not available "
                    "in the supplied chip state"
                )

            elif not clears:

                reason = (
                    "incremental EV is below "
                    "the configured threshold"
                )

            elif not competitive:

                reason = (
                    "a better known future "
                    "opportunity exists inside "
                    "the evaluation horizon"
                )

            else:

                reason = (
                    "incremental EV clears the "
                    "configured threshold and is "
                    "competitive with known "
                    "future opportunities"
                )


            evaluations.append(
                ExactChipTimingEvaluation(
                    chip=chip,

                    available=(
                        is_available
                    ),

                    incremental_ev=(
                        incremental
                    ),

                    baseline_ev=float(
                        entry.baseline_ev
                    ),

                    chip_ev=float(
                        entry.chip_ev
                    ),

                    threshold=threshold,

                    future_best_incremental_ev=(
                        future_best
                    ),

                    clears_threshold=(
                        clears
                    ),

                    competitive_with_future=(
                        competitive
                    ),

                    use_now=use_now,

                    reason=reason,
                )
            )


        eligible = [
            row
            for row
            in evaluations
            if row.use_now
        ]


        chosen = (
            max(
                eligible,
                key=lambda row: (
                    row.incremental_ev,
                    row.chip,
                ),
            ).chip

            if eligible
            else None
        )


        return ExactChipTimingDecision(
            chosen_chip=chosen,

            evaluations=tuple(
                evaluations
            ),
        )


def _supports_gameweek(
    *,
    squad_player_ids,
    projections_by_id,
    p_appearance_by_gameweek,
    gameweek,
) -> bool:

    for player_id in squad_player_ids:

        projection = (
            projections_by_id.get(
                player_id
            )
        )


        if projection is None:

            return False


        if not any(
            int(
                row.gameweek
            ) == gameweek
            for row
            in projection.gameweeks
        ):

            return False


        if (
            player_id,
            gameweek,
        ) not in p_appearance_by_gameweek:

            return False


    return True


def future_fixed_squad_chip_opportunities_exact(
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
    evaluation_horizon_gameweeks: int,
    available_chips: Iterable[str] = ("triple_captain", "bench_boost"),
) -> Mapping[
    str,
    tuple[
        ExactFutureChipOpportunity,
        ...,
    ],
]:
    """
    Known-at-prediction-time future opportunity screen.

    Mirrors the old timing-policy scope:
      - future Triple Captain: evaluated
      - future Bench Boost: evaluated
      - future Free Hit: not inferred here
      - future Wildcard: not inferred here

    No future prices, injuries, lineups or schedule changes
    are invented.
    """

    squad = tuple(
        str(
            player_id
        )
        for player_id
        in squad_player_ids
    )


    available = frozenset(str(chip) for chip in available_chips)
    output = {"triple_captain": [], "bench_boost": []}


    for offset in range(
        1,
        evaluation_horizon_gameweeks,
    ):

        gameweek = (
            first_gameweek
            + offset
        )


        if not _supports_gameweek(
            squad_player_ids=squad,

            projections_by_id=(
                projections_by_id
            ),

            p_appearance_by_gameweek=(
                p_appearance_by_gameweek
            ),

            gameweek=gameweek,
        ):

            break


        normal = (
            evaluate_exact_chip_squad(
                squad_player_ids=squad,

                positions=positions,

                projections_by_id=(
                    projections_by_id
                ),

                p_appearance_by_gameweek=(
                    p_appearance_by_gameweek
                ),

                first_gameweek=gameweek,

                horizon=1,

                weights=(1.0,),

                chip="normal",
            )
        )


        baseline = float(
            normal.weighted_total_ev
        )


        for chip in ("triple_captain", "bench_boost"):
            if chip not in available:
                continue

            chipped = (
                evaluate_exact_chip_squad(
                    squad_player_ids=squad,

                    positions=positions,

                    projections_by_id=(
                        projections_by_id
                    ),

                    p_appearance_by_gameweek=(
                        p_appearance_by_gameweek
                    ),

                    first_gameweek=gameweek,

                    horizon=1,

                    weights=(1.0,),

                    chip=chip,
                )
            )


            chip_ev = float(
                chipped
                .weighted_total_ev
            )


            output[
                chip
            ].append(
                ExactFutureChipOpportunity(
                    chip=chip,

                    gameweek=(
                        gameweek
                    ),

                    baseline_ev=(
                        baseline
                    ),

                    chip_ev=(
                        chip_ev
                    ),

                    incremental_ev=(
                        chip_ev
                        - baseline
                    ),
                )
            )


    return {
        chip:
            tuple(
                rows
            )
        for chip, rows
        in output.items()
    }
