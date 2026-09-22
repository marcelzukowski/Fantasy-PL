"""Focused V2 transfer economics using the existing projection and squad contracts."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import hashlib
import time
from typing import Iterable, Mapping

import numpy as np

from fpl_engine.models.projections import PlayerProjection

from .core import (
    Alternative, OptimizerError, OptimizerRules, Recommendation, SquadPlayer, SquadState,
    TransferPlan, next_free_transfers, optimize_lineup, selling_price,
    validate_projection_contract, validate_squad,
)


@dataclass(frozen=True)
class OptimizerV2Config:
    candidates_per_metric: int = 8
    maximum_candidates_per_position: int = 24
    second_transfer_beam_width: int = 24
    future_transfer_need_probability: float = 0.25
    lookahead_discount: float = 0.95
    indifference_margin: float = 0.25
    similar_projection_gain: float = 1.0
    sensitivity_runs: int = 24
    sensitivity_scale: float = 0.15

    @classmethod
    def from_rules(cls, rules: OptimizerRules) -> "OptimizerV2Config":
        raw = rules.value("decision_v2")
        candidates = raw["candidate_generation"]
        sensitivity = raw["sensitivity"]
        return cls(
            candidates_per_metric=int(candidates["candidates_per_metric"]),
            maximum_candidates_per_position=int(candidates["maximum_candidates_per_position"]),
            second_transfer_beam_width=int(candidates["second_transfer_beam_width"]),
            future_transfer_need_probability=float(
                raw["free_transfer_option_value"]["future_transfer_need_probability"]
            ),
            lookahead_discount=float(raw["lookahead"]["discount"]),
            indifference_margin=float(raw["indifference_margin_points"]),
            similar_projection_gain=float(raw["similar_projection_gain_points"]),
            sensitivity_runs=int(sensitivity["runs"]),
            sensitivity_scale=float(sensitivity["projection_uncertainty_scale"]),
        )

    def __post_init__(self):
        if min(self.candidates_per_metric, self.maximum_candidates_per_position,
               self.second_transfer_beam_width, self.sensitivity_runs) < 1:
            raise ValueError("V2 search and sensitivity sizes must be positive")
        for name in ("future_transfer_need_probability", "lookahead_discount", "sensitivity_scale"):
            value = getattr(self, name)
            if not 0 <= value <= 1:
                raise ValueError(f"{name} must be in [0, 1]")
        if self.indifference_margin < 0 or self.similar_projection_gain < 0:
            raise ValueError("decision margins must be non-negative")


@dataclass(frozen=True)
class CandidateGenerationReport:
    available: int
    selected: int
    selected_by_position: Mapping[str, int]
    top_weighted_coverage: float
    runtime_seconds: float


@dataclass(frozen=True)
class DecisionDiagnostic:
    action: str
    roll_utility: float
    best_transfer_utility: float | None
    gross_gain: float
    hit_cost: int
    net_gain: float
    transfer_count: int
    free_transfers_before: int
    free_transfers_after: int
    bank_before: int
    bank_after: int
    gain_1gw: float
    gain_3gw: float
    gain_6gw: float
    decision_margin: float
    projection_uncertainty: float
    action_stability: float
    lookahead_utility: float
    ft_option_value: float
    candidate_report: CandidateGenerationReport
    runtime_seconds: float


@dataclass(frozen=True)
class _Plan:
    transfer: TransferPlan
    objective: float
    lookahead: float
    ft_option: float
    resulting_players: tuple[SquadPlayer, ...]


def _value(projection: PlayerProjection, name: str) -> float:
    return float(getattr(projection, name))


def generate_candidates(
    state: SquadState,
    pool: Iterable[SquadPlayer],
    projections: Mapping[str, PlayerProjection],
    config: OptimizerV2Config,
) -> tuple[tuple[SquadPlayer, ...], CandidateGenerationReport]:
    """Create a broad deterministic union of horizon, value and price candidates."""
    started = time.perf_counter()
    owned = {player.player_id for player in state.players}
    available = tuple(player for player in pool if player.player_id not in owned and player.player_id in projections)
    selected: dict[str, SquadPlayer] = {}
    top_reference = set()
    for position in ("GK", "DEF", "MID", "FWD"):
        rows = [player for player in available if player.position == position]
        weighted = sorted(rows, key=lambda p: (-_value(projections[p.player_id], "weighted_ev_next_6"), p.player_id))
        top_reference.update(player.player_id for player in weighted[:config.candidates_per_metric])
        rankings = (
            weighted,
            sorted(rows, key=lambda p: (-_value(projections[p.player_id], "ev_next_1"), p.player_id)),
            sorted(rows, key=lambda p: (-_value(projections[p.player_id], "ev_next_3"), p.player_id)),
            sorted(rows, key=lambda p: (-_value(projections[p.player_id], "ev_next_6"), p.player_id)),
            sorted(rows, key=lambda p: (-_value(projections[p.player_id], "weighted_ev_next_6") / max(p.current_price, 1), p.player_id)),
            sorted(rows, key=lambda p: (p.current_price, p.player_id)),
        )
        union = {}
        for ranking in rankings:
            for player in ranking[:config.candidates_per_metric]:
                union[player.player_id] = player
        ordered = sorted(
            union.values(),
            key=lambda p: (-_value(projections[p.player_id], "weighted_ev_next_6"), p.current_price, p.player_id),
        )[:config.maximum_candidates_per_position]
        selected.update((player.player_id, player) for player in ordered)
    result = tuple(sorted(selected.values(), key=lambda player: player.player_id))
    coverage = len(top_reference & set(selected)) / len(top_reference) if top_reference else 1.0
    report = CandidateGenerationReport(
        len(available), len(result), dict(sorted(Counter(player.position for player in result).items())),
        coverage, time.perf_counter()-started,
    )
    return result, report


class OptimizerV2:
    VERSION = "optimizer_v2"

    def __init__(self, rules: OptimizerRules, config: OptimizerV2Config = OptimizerV2Config()):
        self.rules = rules
        self.config = config
        self.last_diagnostic: DecisionDiagnostic | None = None

    def recommend(
        self, state: SquadState, projections: Mapping[str, PlayerProjection],
        pool: Iterable[SquadPlayer] = (), *, max_transfers: int = 2, chip: str | None = None,
    ) -> Recommendation:
        if chip is not None:
            raise OptimizerError("OptimizerV2 transfer planner expects chip timing to be evaluated separately")
        started = time.perf_counter()
        validate_squad(state, self.rules)
        timestamp = validate_projection_contract(state, projections, (p.player_id for p in state.players))
        candidates, candidate_report = generate_candidates(state, pool, projections, self.config)
        validate_projection_contract(state, projections, (p.player_id for p in candidates)) if candidates else None
        plans = self._plans(state, candidates, projections, max_transfers=max_transfers)
        plans.sort(key=lambda item: (-item.objective, len(item.transfer.transfers_in),
                                     not item.transfer.roll_ft, item.transfer.transfers_out, item.transfer.transfers_in))
        best_value = plans[0].objective
        near = [plan for plan in plans if best_value-plan.objective <= self.config.indifference_margin]
        best = min(near, key=lambda item: (len(item.transfer.transfers_in), not item.transfer.roll_ft,
                                           -item.transfer.free_transfers_after,
                                           item.transfer.transfers_out, item.transfer.transfers_in))
        ordered = [best] + [plan for plan in plans if plan is not best]
        transfer = best.transfer
        working = SquadState(best.resulting_players, transfer.bank_after, transfer.free_transfers_after,
                             state.chips, state.current_gameweek, state.season, state.rule_version,
                             state.prediction_timestamp)
        lineup = optimize_lineup(working, projections, self.rules)
        alternatives = tuple(Alternative(
            "ROLL_FT" if plan.transfer.roll_ft else "TRANSFER", plan.objective,
            plan.transfer.transfers_out, plan.transfer.transfers_in,
        ) for plan in ordered[:5])
        runner_up = max((plan.objective for plan in plans if plan is not best), default=best.objective)
        # A negative value records that the lower-cost tie-break deliberately
        # gave up a sub-threshold amount of expected utility.
        margin = best.objective-runner_up
        stability = self._stability(ordered[:max(5, self.config.second_transfer_beam_width)], projections, best)
        action = "ROLL_FT" if transfer.roll_ft else "TRANSFER"
        recommendation = Recommendation(
            action, transfer.transfers_out, transfer.transfers_in, transfer.roll_ft, transfer.hit_cost,
            transfer.gross_gain, transfer.net_gain, transfer.bank_after, state.free_transfers,
            transfer.free_transfers_after, lineup.starting_xi, lineup.formation, lineup.bench_order,
            lineup.captain_id, lineup.vice_captain_id, None,
            sum(projections[p.player_id].ev_next_1 for p in working.players),
            sum(projections[p.player_id].ev_next_3 for p in working.players),
            sum(projections[p.player_id].ev_next_6 for p in working.players),
            sum(projections[p.player_id].weighted_ev_next_6 for p in working.players),
            alternatives, margin, stability, timestamp, self.rules.version, self.VERSION,
        )
        gain = lambda name: sum(_value(projections[x], name) for x in transfer.transfers_in)-sum(
            _value(projections[x], name) for x in transfer.transfers_out)
        involved = transfer.transfers_in+transfer.transfers_out
        uncertainty = sum(float(projections[x].projection_uncertainty) for x in involved)/len(involved) if involved else 0.0
        transfer_plans = [plan for plan in plans if not plan.transfer.roll_ft]
        roll = next(plan for plan in plans if plan.transfer.roll_ft)
        self.last_diagnostic = DecisionDiagnostic(
            action, roll.objective, max((plan.objective for plan in transfer_plans), default=None),
            transfer.gross_gain, transfer.hit_cost, transfer.net_gain, len(transfer.transfers_in),
            state.free_transfers, transfer.free_transfers_after, state.bank, transfer.bank_after,
            gain("ev_next_1"), gain("ev_next_3"), gain("ev_next_6"), margin, uncertainty,
            stability, best.lookahead, best.ft_option, candidate_report, time.perf_counter()-started,
        )
        return recommendation

    def _plans(self, state, candidates, projections, *, max_transfers):
        roll_transfer = TransferPlan((), (), 0.0, 0, 0.0, state.bank, 0,
                                     next_free_transfers(state.free_transfers, 0, self.rules), True)
        roll_players = state.players
        plans = [self._evaluate(roll_transfer, roll_players, state, candidates, projections,
                                include_lookahead=False)]
        singles = []
        for outgoing in state.players:
            for incoming in candidates:
                if incoming.position != outgoing.position:
                    continue
                plan = self._make_plan(state, (outgoing,), (incoming,), projections)
                if plan is None:
                    continue
                resulting = tuple(incoming if player.player_id == outgoing.player_id else player for player in state.players)
                singles.append(self._evaluate(
                    plan, resulting, state, candidates, projections, include_lookahead=False,
                ))
        plans.extend(singles)
        if max_transfers >= 2:
            beam = sorted(singles, key=lambda item: (-item.objective, item.transfer.transfers_out,
                                                     item.transfer.transfers_in))[:self.config.second_transfer_beam_width]
            seen = set()
            by_id = {player.player_id: player for player in state.players}
            candidate_by_id = {player.player_id: player for player in candidates}
            for first in beam:
                first_out = first.transfer.transfers_out[0]
                first_in = first.transfer.transfers_in[0]
                first_owned = {player.player_id for player in first.resulting_players}
                for outgoing in first.resulting_players:
                    if outgoing.player_id == first_in:
                        continue
                    for incoming in candidates:
                        if incoming.position != outgoing.position or incoming.player_id in first_owned:
                            continue
                        outs = tuple(sorted((first_out, outgoing.player_id)))
                        ins = tuple(sorted((first_in, incoming.player_id)))
                        key = (outs, ins)
                        if key in seen:
                            continue
                        seen.add(key)
                        outgoing_rows = tuple(by_id[player_id] for player_id in outs)
                        incoming_rows = tuple(candidate_by_id[player_id] for player_id in ins)
                        plan = self._make_plan(state, outgoing_rows, incoming_rows, projections)
                        if plan is None:
                            continue
                        result = {player.player_id: player for player in state.players}
                        for player_id in outs:
                            result.pop(player_id)
                        result.update((player.player_id, player) for player in incoming_rows)
                        plans.append(self._evaluate(
                            plan, tuple(result.values()), state, candidates, projections,
                            include_lookahead=False,
                        ))
        # Dominance pruning: current net value and explicit FT option value are
        # cheap to compute.  Only a bounded finalist set receives the more
        # expensive provisional next-GW action evaluation.
        roll = next(plan for plan in plans if plan.transfer.roll_ft)
        finalist_limit = self.config.second_transfer_beam_width * 4
        finalists = sorted(
            (plan for plan in plans if not plan.transfer.roll_ft),
            key=lambda item: (-item.objective, len(item.transfer.transfers_in),
                              item.transfer.transfers_out, item.transfer.transfers_in),
        )[:finalist_limit]
        return [self._evaluate(
            plan.transfer, plan.resulting_players, state, candidates, projections,
            include_lookahead=True,
        ) for plan in (roll, *finalists)]

    def _make_plan(self, state, outgoing, incoming, projections):
        result = {player.player_id: player for player in state.players}
        for player in outgoing:
            result.pop(player.player_id)
        result.update((player.player_id, player) for player in incoming)
        bank = state.bank+sum(
            player.selling_price if player.selling_price is not None else
            selling_price(player.purchase_price, player.current_price, self.rules) for player in outgoing
        )-sum(player.current_price for player in incoming)
        if bank < 0:
            return None
        temporary = SquadState(tuple(result.values()), bank, state.free_transfers, state.chips,
                               state.current_gameweek, state.season, state.rule_version, state.prediction_timestamp)
        try:
            validate_squad(temporary, self.rules)
        except OptimizerError:
            return None
        count = len(incoming)
        hit = max(0, count-state.free_transfers)*int(
            self.rules.value("transfers", "normal_gameweek", "points_cost_per_transfer_above_allowance")
        )
        gross = sum(projections[p.player_id].weighted_ev_next_6 for p in incoming)-sum(
            projections[p.player_id].weighted_ev_next_6 for p in outgoing
        )
        return TransferPlan(
            tuple(sorted(p.player_id for p in outgoing)), tuple(sorted(p.player_id for p in incoming)),
            gross, hit, gross-hit, bank, min(count, state.free_transfers),
            next_free_transfers(state.free_transfers, count, self.rules), False,
        )

    def _evaluate(self, transfer, players, state, candidates, projections, *, include_lookahead=True):
        hit_value = int(self.rules.value("transfers", "normal_gameweek", "points_cost_per_transfer_above_allowance"))
        ft_option = transfer.free_transfers_after*hit_value*self.config.future_transfer_need_probability
        lookahead = self._lookahead(players, transfer.bank_after, candidates, projections) if include_lookahead else 0.0
        objective = transfer.net_gain+ft_option+self.config.lookahead_discount*lookahead
        return _Plan(transfer, objective, lookahead, ft_option, tuple(players))

    def _lookahead(self, players, bank, candidates, projections):
        owned = {player.player_id for player in players}
        club_counts = Counter(player.club_id for player in players)
        club_limit = int(self.rules.value("initial_squad", "maximum_players_per_club"))
        best = 0.0
        for outgoing in players:
            sale = outgoing.selling_price if outgoing.selling_price is not None else selling_price(
                outgoing.purchase_price, outgoing.current_price, self.rules
            )
            for incoming in candidates:
                if incoming.player_id in owned or incoming.position != outgoing.position or incoming.current_price > bank+sale:
                    continue
                resulting_club_count = club_counts[incoming.club_id] + 1 - int(
                    outgoing.club_id == incoming.club_id
                )
                if resulting_club_count > club_limit:
                    continue
                future_gain = sum(
                    projections[incoming.player_id].gameweeks[index].expected_points
                    - projections[outgoing.player_id].gameweeks[index].expected_points
                    for index in range(1, min(6, len(projections[incoming.player_id].gameweeks)))
                )
                best = max(best, future_gain)
        return best

    def _stability(self, plans, projections, selected):
        seed_material = selected.transfer.transfers_out+selected.transfer.transfers_in
        digest = hashlib.sha256("|".join(seed_material or ("ROLL",)).encode()).digest()
        rng = np.random.default_rng(int.from_bytes(digest[:8], "big"))
        wins = 0
        selected_key = (selected.transfer.transfers_out, selected.transfer.transfers_in)
        for _ in range(self.config.sensitivity_runs):
            scored = []
            for plan in plans:
                direct = 0.0
                for sign, ids in ((1, plan.transfer.transfers_in), (-1, plan.transfer.transfers_out)):
                    for player_id in ids:
                        projection = projections[player_id]
                        scale = max(0.0, 1+rng.normal(0, projection.projection_uncertainty*self.config.sensitivity_scale))
                        direct += sign*projection.weighted_ev_next_6*scale
                score = direct-plan.transfer.hit_cost+plan.ft_option+self.config.lookahead_discount*plan.lookahead
                scored.append((score, -len(plan.transfer.transfers_in), plan.transfer.roll_ft,
                               plan.transfer.transfers_out, plan.transfer.transfers_in))
            winner = max(scored)
            wins += (winner[3], winner[4]) == selected_key
        return wins/self.config.sensitivity_runs
