"""Season-aware, lower-cost strategic chip opportunity screening.

The detailed Chip Screen remains the sole exact near-term decision path.  This
module only extends its existing EV and timing contracts past that horizon,
without crossing an FPL chip reset boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

from .chip_screen import rank_unlimited_candidates_exact
from .chip_screen_exact import evaluate_exact_chip_squad
from .chip_timing import ExactFutureChipOpportunity, TIMED_CHIPS


STRATEGIC_SIMULATIONS_PER_FIXTURE = 3_000
EXACT_HORIZON_GAMEWEEKS = 6


class ChipStrategyError(ValueError):
    """Invalid season-aware chip strategy request."""


@dataclass(frozen=True)
class ChipStrategyHorizons:
    current_gameweek: int
    chip_period_end: int
    exact_gameweeks: tuple[int, ...]
    strategic_gameweeks: tuple[int, ...]

    @property
    def exact_horizon_gameweeks(self) -> int:
        return len(self.exact_gameweeks)


@dataclass(frozen=True)
class StrategicChipScan:
    opportunities: Mapping[str, tuple[ExactFutureChipOpportunity, ...]]
    unavailable_gameweeks: Mapping[int, str]


def chip_period_end(current_gameweek: int) -> int:
    """Return the final GW at which the current half's chips may be used."""
    gameweek = int(current_gameweek)
    if not 1 <= gameweek <= 38:
        raise ChipStrategyError("current_gameweek must be between 1 and 38")
    return 19 if gameweek <= 19 else 38


def chip_strategy_horizons(
    current_gameweek: int,
    *,
    exact_horizon_gameweeks: int = EXACT_HORIZON_GAMEWEEKS,
) -> ChipStrategyHorizons:
    """Split the active chip period into exact and strategic ranges."""
    gameweek = int(current_gameweek)
    if exact_horizon_gameweeks < 1:
        raise ChipStrategyError("exact_horizon_gameweeks must be positive")
    period_end = chip_period_end(gameweek)
    exact_end = min(period_end, gameweek + int(exact_horizon_gameweeks) - 1)
    return ChipStrategyHorizons(
        current_gameweek=gameweek,
        chip_period_end=period_end,
        exact_gameweeks=tuple(range(gameweek, exact_end + 1)),
        strategic_gameweeks=tuple(range(exact_end + 1, period_end + 1)),
    )


def discount_weights(horizon: int) -> tuple[float, ...]:
    if horizon < 1:
        raise ChipStrategyError("horizon must be positive")
    return tuple(0.95**offset for offset in range(horizon))


def _future_entry(*, chip: str, gameweek: int, baseline_ev: float, chip_ev: float) -> ExactFutureChipOpportunity:
    return ExactFutureChipOpportunity(
        chip=chip,
        gameweek=int(gameweek),
        baseline_ev=float(baseline_ev),
        chip_ev=float(chip_ev),
        incremental_ev=float(chip_ev - baseline_ev),
    )


def strategic_chip_opportunities(
    *,
    player_rows: Iterable[Mapping],
    positions: Mapping[str, str],
    projections_by_id: Mapping[str, object],
    p_appearance_by_gameweek: Mapping[tuple[str, int], float],
    current_player_ids: Iterable[str],
    selling_prices_tenths: Mapping[str, int],
    bank_tenths: int,
    strategic_gameweeks: Iterable[int],
    chip_period_end_gameweek: int,
    max_players_per_team: int = 3,
    available_chips: Iterable[str] = TIMED_CHIPS,
) -> StrategicChipScan:
    """Screen later opportunities with existing score/EV machinery.

    Triple Captain and Bench Boost use the established exact fixed-squad
    scorer.  Free Hit and Wildcard use the existing unlimited-squad MILP base
    plan followed by one exact evaluation.  This intentionally avoids the
    full local candidate portfolio used by the near-term exact screen.
    """
    current = tuple(str(player_id) for player_id in current_player_ids)
    rows = tuple(player_rows)
    period_end = int(chip_period_end_gameweek)
    if not 1 <= period_end <= 38:
        raise ChipStrategyError("chip_period_end_gameweek must be between 1 and 38")
    available = frozenset(str(chip) for chip in available_chips)

    output: dict[str, list[ExactFutureChipOpportunity]] = {chip: [] for chip in TIMED_CHIPS}
    unavailable: dict[int, str] = {}
    for raw_gameweek in strategic_gameweeks:
        gameweek = int(raw_gameweek)
        if gameweek > period_end:
            raise ChipStrategyError("strategic scan cannot cross the chip-period boundary")
        if gameweek < 1:
            raise ChipStrategyError("strategic gameweek must be positive")
        wildcard_horizon = min(EXACT_HORIZON_GAMEWEEKS, period_end - gameweek + 1)
        wildcard_weights = discount_weights(wildcard_horizon)
        try:
            normal_now = evaluate_exact_chip_squad(
                squad_player_ids=current,
                positions=positions,
                projections_by_id=projections_by_id,
                p_appearance_by_gameweek=p_appearance_by_gameweek,
                first_gameweek=gameweek,
                horizon=1,
                weights=(1.0,),
                chip="normal",
            )
            normal_horizon = normal_now
            if "wildcard" in available:
                normal_horizon = evaluate_exact_chip_squad(
                    squad_player_ids=current, positions=positions,
                    projections_by_id=projections_by_id,
                    p_appearance_by_gameweek=p_appearance_by_gameweek,
                    first_gameweek=gameweek, horizon=wildcard_horizon,
                    weights=wildcard_weights, chip="normal",
                )
            triple = None
            if "triple_captain" in available:
                triple = evaluate_exact_chip_squad(
                squad_player_ids=current,
                positions=positions,
                projections_by_id=projections_by_id,
                p_appearance_by_gameweek=p_appearance_by_gameweek,
                first_gameweek=gameweek,
                horizon=1,
                weights=(1.0,),
                chip="triple_captain",
                )
            bench = None
            if "bench_boost" in available:
                bench = evaluate_exact_chip_squad(
                squad_player_ids=current,
                positions=positions,
                projections_by_id=projections_by_id,
                p_appearance_by_gameweek=p_appearance_by_gameweek,
                first_gameweek=gameweek,
                horizon=1,
                weights=(1.0,),
                chip="bench_boost",
                )
            free_hit = None
            if "free_hit" in available:
                free_hit = rank_unlimited_candidates_exact(
                chip="free_hit",
                player_rows=rows,
                positions=positions,
                projections_by_id=projections_by_id,
                p_appearance_by_gameweek=p_appearance_by_gameweek,
                current_player_ids=current,
                selling_prices_tenths=selling_prices_tenths,
                bank_tenths=bank_tenths,
                first_gameweek=gameweek,
                horizon=1,
                weights=(1.0,),
                max_players_per_team=max_players_per_team,
                portfolio_limit=1,
                )
            wildcard = None
            if "wildcard" in available:
                wildcard = rank_unlimited_candidates_exact(
                chip="wildcard",
                player_rows=rows,
                positions=positions,
                projections_by_id=projections_by_id,
                p_appearance_by_gameweek=p_appearance_by_gameweek,
                current_player_ids=current,
                selling_prices_tenths=selling_prices_tenths,
                bank_tenths=bank_tenths,
                first_gameweek=gameweek,
                horizon=wildcard_horizon,
                weights=wildcard_weights,
                max_players_per_team=max_players_per_team,
                portfolio_limit=1,
                )
        except (RuntimeError, ValueError) as exc:
            # Missing future data is recorded as unavailable.  It is never
            # replaced by a later fixture, zero, or a fabricated estimate.
            unavailable[gameweek] = f"{type(exc).__name__}: {exc}"
            continue

        if triple is not None:
            output["triple_captain"].append(_future_entry(
                chip="triple_captain", gameweek=gameweek,
                baseline_ev=normal_now.weighted_total_ev, chip_ev=triple.weighted_total_ev,
            ))
        if bench is not None:
            output["bench_boost"].append(_future_entry(
                chip="bench_boost", gameweek=gameweek,
                baseline_ev=normal_now.weighted_total_ev, chip_ev=bench.weighted_total_ev,
            ))
        if free_hit is not None:
            output["free_hit"].append(_future_entry(
                chip="free_hit", gameweek=gameweek,
                baseline_ev=normal_now.weighted_total_ev, chip_ev=free_hit.selected.exact.weighted_total_ev,
            ))
        if wildcard is not None:
            output["wildcard"].append(_future_entry(
                chip="wildcard", gameweek=gameweek,
                baseline_ev=normal_horizon.weighted_total_ev, chip_ev=wildcard.selected.exact.weighted_total_ev,
            ))

    return StrategicChipScan(
        opportunities={chip: tuple(rows) for chip, rows in output.items()},
        unavailable_gameweeks=unavailable,
    )
