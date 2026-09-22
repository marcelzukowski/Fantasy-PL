from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

from .chip_screen_exact import (
    ExactChipSquadEvaluation,
    evaluate_exact_chip_squad,
)
from .chip_squads import (
    ChipSquadError,
    UnlimitedSquadPlan,
    optimize_unlimited_squad,
)


@dataclass(frozen=True)
class ExactUnlimitedCandidate:

    player_ids: frozenset[str]

    generator_weighted_xi_ev: float

    exact: ExactChipSquadEvaluation


@dataclass(frozen=True)
class ExactUnlimitedCandidateRanking:

    chip: str

    generated_count: int

    unique_count: int

    selected: ExactUnlimitedCandidate

    candidates: tuple[
        ExactUnlimitedCandidate,
        ...,
    ]


@dataclass(frozen=True)
class ExactChipScreenEntry:

    chip: str

    baseline_ev: float

    chip_ev: float

    incremental_ev: float

    squad_player_ids: frozenset[str]

    captain_id: str
    vice_id: str

    formation: str

    candidate_count: int


@dataclass(frozen=True)
class ExactChipScreen:

    first_gameweek: int

    wildcard_horizon: int

    normal_current_gameweek: (
        ExactChipSquadEvaluation
    )

    normal_wildcard_horizon: (
        ExactChipSquadEvaluation
    )

    triple_captain: ExactChipScreenEntry

    bench_boost: ExactChipScreenEntry

    free_hit: ExactChipScreenEntry

    wildcard: ExactChipScreenEntry


def _exact_rank_key(
    candidate: ExactUnlimitedCandidate,
):

    return (
        float(
            candidate
            .exact
            .weighted_total_ev
        ),

        float(
            candidate
            .generator_weighted_xi_ev
        ),

        tuple(
            sorted(
                candidate.player_ids
            )
        ),
    )


def _generate_unlimited_portfolio(
    *,
    player_rows,
    projections_by_id,
    current_player_ids,
    selling_prices_tenths,
    bank_tenths,
    first_gameweek,
    horizon,
    weights,
    max_players_per_team,
    portfolio_limit: int | None = None,
) -> tuple[
    UnlimitedSquadPlan,
    ...,
]:
    """
    Candidate generation only.

    1. Solve the normal linear XI-based unlimited-squad MILP.
    2. Re-solve once while forbidding each player from the
       base 15.

    The returned set is therefore a deterministic local
    candidate portfolio. Final ranking happens with the
    nonlinear exact scorer, not the generator objective.
    """

    base = optimize_unlimited_squad(
        player_rows=player_rows,

        projections_by_id=(
            projections_by_id
        ),

        current_player_ids=(
            current_player_ids
        ),

        selling_prices_tenths=(
            selling_prices_tenths
        ),

        bank_tenths=(
            bank_tenths
        ),

        first_gameweek=(
            first_gameweek
        ),

        horizon=horizon,

        weights=weights,

        max_players_per_team=(
            max_players_per_team
        ),
    )


    if portfolio_limit is not None and portfolio_limit < 1:
        raise ValueError("portfolio_limit must be positive when supplied")

    by_squad = {
        frozenset(
            base.player_ids
        ):
            base
    }


    # Strategic scans deliberately use only the base MILP solution.  The
    # regular exact screen retains the complete one-player-exclusion
    # portfolio and its exact nonlinear ranking.
    if portfolio_limit == 1:
        return (base,)

    for forbidden_id in sorted(
        base.player_ids
    ):

        try:

            alternative = (
                optimize_unlimited_squad(
                    player_rows=player_rows,

                    projections_by_id=(
                        projections_by_id
                    ),

                    current_player_ids=(
                        current_player_ids
                    ),

                    selling_prices_tenths=(
                        selling_prices_tenths
                    ),

                    bank_tenths=(
                        bank_tenths
                    ),

                    first_gameweek=(
                        first_gameweek
                    ),

                    horizon=horizon,

                    weights=weights,

                    forbidden_player_ids=(
                        forbidden_id,
                    ),

                    max_players_per_team=(
                        max_players_per_team
                    ),
                )
            )

        except ChipSquadError:
            continue


        by_squad.setdefault(
            frozenset(
                alternative.player_ids
            ),
            alternative,
        )


    return tuple(
        by_squad[
            key
        ]
        for key
        in sorted(
            by_squad,
            key=lambda squad: tuple(
                sorted(
                    squad
                )
            ),
        )
    )


def rank_unlimited_candidates_exact(
    *,
    chip: str,
    player_rows,
    positions,
    projections_by_id,
    p_appearance_by_gameweek,
    current_player_ids,
    selling_prices_tenths,
    bank_tenths,
    first_gameweek,
    horizon,
    weights,
    max_players_per_team=3,
    portfolio_limit: int | None = None,
) -> ExactUnlimitedCandidateRanking:
    """
    Generate candidate 15s with the linear MILP, then rank
    those candidates with exact autosub + exact C/VC scoring.

    This is deliberately NOT called a globally exact
    unlimited-squad optimizer.
    """

    if chip not in {
        "wildcard",
        "free_hit",
    }:

        raise ValueError(
            "unlimited exact ranking supports "
            "wildcard or free_hit"
        )


    plans = _generate_unlimited_portfolio(
        player_rows=player_rows,

        projections_by_id=(
            projections_by_id
        ),

        current_player_ids=(
            current_player_ids
        ),

        selling_prices_tenths=(
            selling_prices_tenths
        ),

        bank_tenths=bank_tenths,

        first_gameweek=(
            first_gameweek
        ),

        horizon=horizon,

        weights=weights,

        max_players_per_team=(
            max_players_per_team
        ),
        portfolio_limit=portfolio_limit,
    )


    exact_candidates = []


    for plan in plans:

        exact = evaluate_exact_chip_squad(
            squad_player_ids=(
                plan.player_ids
            ),

            positions=positions,

            projections_by_id=(
                projections_by_id
            ),

            p_appearance_by_gameweek=(
                p_appearance_by_gameweek
            ),

            first_gameweek=(
                first_gameweek
            ),

            horizon=horizon,

            weights=weights,

            chip=chip,
        )


        exact_candidates.append(
            ExactUnlimitedCandidate(
                player_ids=frozenset(
                    plan.player_ids
                ),

                generator_weighted_xi_ev=float(
                    plan.weighted_xi_ev
                ),

                exact=exact,
            )
        )


    if not exact_candidates:

        raise RuntimeError(
            "unlimited candidate portfolio "
            "is empty"
        )


    selected = max(
        exact_candidates,
        key=_exact_rank_key,
    )


    ordered = tuple(
        sorted(
            exact_candidates,
            key=_exact_rank_key,
            reverse=True,
        )
    )


    return ExactUnlimitedCandidateRanking(
        chip=chip,

        generated_count=len(plans),

        unique_count=len(
            exact_candidates
        ),

        selected=selected,

        candidates=ordered,
    )


def _entry_from_evaluation(
    *,
    chip,
    baseline,
    chipped,
    squad_player_ids,
    candidate_count,
) -> ExactChipScreenEntry:

    week = chipped.gameweeks[
        0
    ]


    return ExactChipScreenEntry(
        chip=chip,

        baseline_ev=float(
            baseline
        ),

        chip_ev=float(
            chipped
            .weighted_total_ev
        ),

        incremental_ev=float(
            chipped
            .weighted_total_ev
            - baseline
        ),

        squad_player_ids=frozenset(
            squad_player_ids
        ),

        captain_id=week.captain_id,

        vice_id=week.vice_id,

        formation=week.formation,

        candidate_count=int(
            candidate_count
        ),
    )


def screen_chips_exact(
    *,
    player_rows: Iterable[Mapping],
    positions: Mapping[str, str],
    projections_by_id: Mapping[
        str,
        object,
    ],
    p_appearance_by_gameweek: Mapping[
        tuple[str, int],
        float,
    ],
    current_player_ids: Iterable[str],
    selling_prices_tenths: Mapping[
        str,
        int,
    ],
    bank_tenths: int,
    first_gameweek: int,
    wildcard_horizon: int,
    wildcard_weights: tuple[
        float,
        ...,
    ],
    max_players_per_team: int = 3,
    available_chips: Iterable[str] | None = None,
    progress=None,
) -> ExactChipScreen:
    """
    Exact chip-value snapshot.

    No timing threshold is applied here.
    No future-opportunity suppression is applied here.

    This function answers only:
      "What is the model EV of using each chip NOW?"

    Timing policy is intentionally a later layer.
    """

    current = frozenset(
        str(
            player_id
        )
        for player_id
        in current_player_ids
    )


    if len(
        current
    ) != 15:

        raise ValueError(
            "chip screen requires current "
            "15-player squad"
        )

    available = frozenset(
        {"triple_captain", "bench_boost", "free_hit", "wildcard"}
        if available_chips is None else (str(chip) for chip in available_chips)
    )


    if progress is not None:
        progress("evaluating current squad")
    normal_now = evaluate_exact_chip_squad(
        squad_player_ids=current,

        positions=positions,

        projections_by_id=(
            projections_by_id
        ),

        p_appearance_by_gameweek=(
            p_appearance_by_gameweek
        ),

        first_gameweek=(
            first_gameweek
        ),

        horizon=1,

        weights=(1.0,),

        chip="normal",
    )


    if "wildcard" in available:
        if progress is not None:
            progress("evaluating current squad horizon")
        normal_horizon = evaluate_exact_chip_squad(
            squad_player_ids=current,

            positions=positions,

            projections_by_id=(
                projections_by_id
            ),

            p_appearance_by_gameweek=(
                p_appearance_by_gameweek
            ),

            first_gameweek=(
                first_gameweek
            ),

            horizon=wildcard_horizon,

            weights=wildcard_weights,

            chip="normal",
        )
    else:
        if progress is not None:
            progress("skipping Wildcard (already used)")
        normal_horizon = normal_now


    triple = None
    if "triple_captain" in available:
        if progress is not None:
            progress("evaluating Triple Captain")
        triple = evaluate_exact_chip_squad(
        squad_player_ids=current,

        positions=positions,

        projections_by_id=(
            projections_by_id
        ),

        p_appearance_by_gameweek=(
            p_appearance_by_gameweek
        ),

        first_gameweek=(
            first_gameweek
        ),

        horizon=1,

        weights=(1.0,),

        chip="triple_captain",
        )
    elif progress is not None:
        progress("skipping Triple Captain (already used)")
    if triple is None:
        triple = normal_now


    bench = None
    if "bench_boost" in available:
        if progress is not None:
            progress("evaluating Bench Boost")
        bench = evaluate_exact_chip_squad(
        squad_player_ids=current,

        positions=positions,

        projections_by_id=(
            projections_by_id
        ),

        p_appearance_by_gameweek=(
            p_appearance_by_gameweek
        ),

        first_gameweek=(
            first_gameweek
        ),

        horizon=1,

        weights=(1.0,),

        chip="bench_boost",
        )
    elif progress is not None:
        progress("skipping Bench Boost (already used)")
    if bench is None:
        bench = normal_now


    free_hit_ranking = None
    if "free_hit" in available:
        if progress is not None:
            progress("evaluating Free Hit")
        free_hit_ranking = (
        rank_unlimited_candidates_exact(
            chip="free_hit",

            player_rows=player_rows,

            positions=positions,

            projections_by_id=(
                projections_by_id
            ),

            p_appearance_by_gameweek=(
                p_appearance_by_gameweek
            ),

            current_player_ids=current,

            selling_prices_tenths=(
                selling_prices_tenths
            ),

            bank_tenths=bank_tenths,

            first_gameweek=(
                first_gameweek
            ),

            horizon=1,

            weights=(1.0,),

            max_players_per_team=(
                max_players_per_team
            ),
        )
        )
    elif progress is not None:
        progress("skipping Free Hit (already used)")
    if free_hit_ranking is None:
        free_hit_ranking = ExactUnlimitedCandidateRanking(
            chip="free_hit", generated_count=0, unique_count=0,
            selected=ExactUnlimitedCandidate(current, float(normal_now.weighted_total_ev), normal_now),
            candidates=(),
        )


    wildcard_ranking = None
    if "wildcard" in available:
        if progress is not None:
            progress("evaluating Wildcard")
        wildcard_ranking = (
        rank_unlimited_candidates_exact(
            chip="wildcard",

            player_rows=player_rows,

            positions=positions,

            projections_by_id=(
                projections_by_id
            ),

            p_appearance_by_gameweek=(
                p_appearance_by_gameweek
            ),

            current_player_ids=current,

            selling_prices_tenths=(
                selling_prices_tenths
            ),

            bank_tenths=bank_tenths,

            first_gameweek=(
                first_gameweek
            ),

            horizon=wildcard_horizon,

            weights=wildcard_weights,

            max_players_per_team=(
                max_players_per_team
            ),
        )
        )

    if wildcard_ranking is None:
        wildcard_ranking = ExactUnlimitedCandidateRanking(
            chip="wildcard", generated_count=0, unique_count=0,
            selected=ExactUnlimitedCandidate(current, float(normal_horizon.weighted_total_ev), normal_horizon),
            candidates=(),
        )


    normal_now_ev = float(
        normal_now.weighted_total_ev
    )

    normal_horizon_ev = float(
        normal_horizon
        .weighted_total_ev
    )


    return ExactChipScreen(
        first_gameweek=(
            first_gameweek
        ),

        wildcard_horizon=(
            wildcard_horizon
        ),

        normal_current_gameweek=(
            normal_now
        ),

        normal_wildcard_horizon=(
            normal_horizon
        ),

        triple_captain=(
            _entry_from_evaluation(
                chip="triple_captain",

                baseline=normal_now_ev,

                chipped=triple,

                squad_player_ids=current,

                candidate_count=1 if "triple_captain" in available else 0,
            )
        ),

        bench_boost=(
            _entry_from_evaluation(
                chip="bench_boost",

                baseline=normal_now_ev,

                chipped=bench,

                squad_player_ids=current,

                candidate_count=1 if "bench_boost" in available else 0,
            )
        ),

        free_hit=(
            _entry_from_evaluation(
                chip="free_hit",

                baseline=normal_now_ev,

                chipped=(
                    free_hit_ranking
                    .selected
                    .exact
                ),

                squad_player_ids=(
                    free_hit_ranking
                    .selected
                    .player_ids
                ),

                candidate_count=(
                    free_hit_ranking
                    .unique_count
                ),
            )
        ),

        wildcard=(
            ExactChipScreenEntry(
                chip="wildcard",

                baseline_ev=(
                    normal_horizon_ev
                ),

                chip_ev=float(
                    wildcard_ranking
                    .selected
                    .exact
                    .weighted_total_ev
                ),

                incremental_ev=float(
                    wildcard_ranking
                    .selected
                    .exact
                    .weighted_total_ev
                    - normal_horizon_ev
                ),

                squad_player_ids=(
                    wildcard_ranking
                    .selected
                    .player_ids
                ),

                captain_id=(
                    wildcard_ranking
                    .selected
                    .exact
                    .gameweeks[
                        0
                    ]
                    .captain_id
                ),

                vice_id=(
                    wildcard_ranking
                    .selected
                    .exact
                    .gameweeks[
                        0
                    ]
                    .vice_id
                ),

                formation=(
                    wildcard_ranking
                    .selected
                    .exact
                    .gameweeks[
                        0
                    ]
                    .formation
                ),

                candidate_count=(
                    wildcard_ranking
                    .unique_count
                ),
            )
        ),
    )
