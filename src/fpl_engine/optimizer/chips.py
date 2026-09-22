"""Point-in-time player-chip timing against an explicit no-chip counterfactual."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Iterable, Mapping

from fpl_engine.models.projections import PlayerProjection

from .core import (
    Optimizer, OptimizerRules, Recommendation, SquadPlayer, SquadState,
    chip_available, optimize_lineup,
)
from .v2 import OptimizerV2Config, generate_candidates


@dataclass(frozen=True)
class ChipEvaluation:
    chip: str
    incremental_ev: float
    no_chip_ev: float
    chip_ev: float
    best_known_future_opportunity_ev: float | None
    use_now: bool
    reason: str


@dataclass(frozen=True)
class ChipTimingDecision:
    chip: str | None
    evaluations: tuple[ChipEvaluation, ...]


class ChipTimingPlanner:
    """Evaluate each supported chip against doing the same GW without it.

    Future opportunity checks use only the already-known projection horizon at
    the prediction timestamp. They do not assume a double Gameweek or consume
    future prices, injuries, lineups, or schedules.
    """

    VERSION = "chip_timing_v2"

    def __init__(self, rules: OptimizerRules):
        self.rules = rules
        raw = rules.value("chip_timing_v2")
        self.horizon = int(raw["evaluation_horizon_gameweeks"])
        self.minimum = float(raw["minimum_incremental_ev"])
        self.tolerance = float(raw["future_opportunity_tolerance"])
        self.wildcard_minimum = float(raw["wildcard_minimum_weighted_gain"])
        self.free_hit_minimum = float(raw["free_hit_minimum_single_gameweek_gain"])

    def decide(
        self,
        state: SquadState,
        projections: Mapping[str, PlayerProjection],
        pool: Iterable[SquadPlayer],
    ) -> ChipTimingDecision:
        pool = tuple(pool)
        candidate_pool, _ = generate_candidates(
            state, pool, projections, OptimizerV2Config.from_rules(self.rules),
        )
        baseline = optimize_lineup(state, projections, self.rules)
        evaluations: list[ChipEvaluation] = []
        if chip_available("triple_captain", state, self.rules):
            current = optimize_lineup(state, projections, self.rules, triple_captain=True)
            future = self._future_lineup_increments(state, projections, "triple_captain")
            evaluations.append(self._evaluation(
                "triple_captain", current.expected_points-baseline.expected_points,
                baseline.expected_points, current.expected_points, future, self.minimum,
            ))
        if chip_available("bench_boost", state, self.rules):
            current = optimize_lineup(state, projections, self.rules, bench_boost=True)
            future = self._future_lineup_increments(state, projections, "bench_boost")
            evaluations.append(self._evaluation(
                "bench_boost", current.expected_points-baseline.expected_points,
                baseline.expected_points, current.expected_points, future, self.minimum,
            ))
        production = Optimizer(self.rules)
        if chip_available("free_hit", state, self.rules):
            recommendation = production.recommend(state, projections, candidate_pool, chip="free_hit")
            increment = self._chip_lineup_ev(state, candidate_pool, projections, recommendation)-baseline.expected_points
            evaluations.append(self._evaluation(
                "free_hit", increment, baseline.expected_points, baseline.expected_points+increment,
                None, self.free_hit_minimum,
            ))
        if chip_available("wildcard", state, self.rules):
            recommendation = production.recommend(state, projections, candidate_pool, chip="wildcard")
            baseline_weighted = sum(projections[player.player_id].weighted_ev_next_6 for player in state.players)
            increment = recommendation.weighted_utility_6gw-baseline_weighted
            evaluations.append(self._evaluation(
                "wildcard", increment, baseline_weighted, recommendation.weighted_utility_6gw,
                None, self.wildcard_minimum,
            ))
        eligible = [row for row in evaluations if row.use_now]
        chosen = max(eligible, key=lambda row: (row.incremental_ev, row.chip)).chip if eligible else None
        return ChipTimingDecision(chosen, tuple(evaluations))

    def _evaluation(self, chip, increment, baseline, chip_ev, future, threshold):
        competitive = future is None or increment >= future-self.tolerance
        use = increment >= threshold and competitive
        reason = (
            "incremental EV clears the configured threshold and is competitive with known horizon opportunities"
            if use else "incremental EV is below the configured threshold or a better known horizon opportunity exists"
        )
        return ChipEvaluation(chip, increment, baseline, chip_ev, future, use, reason)

    def _future_lineup_increments(self, state, projections, chip):
        available = min(self.horizon, min(len(row.gameweeks) for row in projections.values()))
        increments = []
        for index in range(1, available):
            shifted = {}
            for player_id, row in projections.items():
                try:
                    shifted[player_id] = replace(row, gameweeks=(row.gameweeks[index],))
                except TypeError:  # Lightweight test/adapter records are also supported.
                    shifted[player_id] = type(row)(**{
                        **vars(row), "gameweeks": (row.gameweeks[index],),
                    })
            baseline = optimize_lineup(state, shifted, self.rules)
            chipped = optimize_lineup(
                state, shifted, self.rules,
                triple_captain=chip == "triple_captain", bench_boost=chip == "bench_boost",
            )
            increments.append(chipped.expected_points-baseline.expected_points)
        return max(increments) if increments else None

    def _chip_lineup_ev(self, state, pool, projections, recommendation):
        owned = {player.player_id: player for player in state.players}
        available = {player.player_id: player for player in pool}
        for player_id in recommendation.transfers_out:
            owned.pop(player_id)
        for player_id in recommendation.transfers_in:
            owned[player_id] = available[player_id]
        working = replace(state, players=tuple(owned.values()), bank=recommendation.resulting_bank)
        return optimize_lineup(working, projections, self.rules).expected_points
