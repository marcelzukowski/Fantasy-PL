"""Bounded, read-only three-gameweek transfer-path challenger.

V3 is intentionally separate from Optimizer V2.  It compares complete paths
in a single unit: projected lineup points minus transfer hits over three
gameweeks, plus a separately reported small terminal free-transfer value.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import time
from typing import Iterable, Mapping

from fpl_engine.models.projections import PlayerProjection
from fpl_engine.optimizer import (
    OptimizerError,
    OptimizerRules,
    SquadPlayer,
    SquadState,
    next_free_transfers,
    optimize_lineup,
    selling_price,
    validate_squad,
)

from .price_signals import PriceChangeSignal


class StrategicPlannerV3Error(ValueError):
    pass


@dataclass(frozen=True)
class StrategicPlannerV3Config:
    planning_horizon: int = 3
    diagnostic_horizon: bool = False
    beam_width: int = 40
    candidates_per_position: int = 8
    max_actions_per_state: int = 24
    max_transfers_per_action: int = 2
    terminal_ft_need_probability: float = 0.25

    def __post_init__(self) -> None:
        if self.planning_horizon not in {3, 4}:
            raise ValueError("V3 supports only three GW production planning and a four-GW diagnostic control")
        if self.planning_horizon != 3 and not self.diagnostic_horizon:
            raise ValueError("A non-production V3 horizon requires diagnostic_horizon=True")
        if min(self.beam_width, self.candidates_per_position, self.max_actions_per_state, self.max_transfers_per_action) < 1:
            raise ValueError("V3 search limits must be positive")
        if not 0.0 <= self.terminal_ft_need_probability <= 1.0:
            raise ValueError("terminal_ft_need_probability must be in [0, 1]")


@dataclass(frozen=True)
class StrategicAction:
    action: str
    transfers_out: tuple[str, ...]
    transfers_in: tuple[str, ...]
    transfers_used: int
    hit_cost_points: int
    resulting_bank: int
    free_transfers_before: int
    free_transfers_after: int
    resulting_squad: tuple[str, ...]

    @property
    def is_hold(self) -> bool:
        return self.action == "HOLD"


@dataclass(frozen=True)
class StrategicPathStep:
    gameweek: int
    action: StrategicAction
    lineup_points: float
    points_after_hit: float
    starting_xi: tuple[str, ...]
    bench_order: tuple[str, ...]
    captain_id: str
    vice_captain_id: str
    price_risk: Mapping[str, object]


@dataclass(frozen=True)
class StrategicPath:
    steps: tuple[StrategicPathStep, ...]
    projected_3gw_path_points: float
    terminal_ft_value: float
    total_path_value: float


@dataclass(frozen=True)
class StrategicPlannerV3Result:
    best_path: StrategicPath
    hold_now_path: StrategicPath
    diagnostics: Mapping[str, object]

    @property
    def delta_vs_hold_now(self) -> float:
        return self.best_path.total_path_value - self.hold_now_path.total_path_value

    def as_dict(self) -> dict:
        def action(row: StrategicAction) -> dict:
            return {
                "action": row.action,
                "transfers_out": list(row.transfers_out),
                "transfers_in": list(row.transfers_in),
                "transfers_used": row.transfers_used,
                "hit_cost_points": row.hit_cost_points,
                "resulting_bank": row.resulting_bank,
                "free_transfers_before": row.free_transfers_before,
                "free_transfers_after": row.free_transfers_after,
                "resulting_squad": list(row.resulting_squad),
            }

        def path(row: StrategicPath) -> dict:
            steps = []
            for step in row.steps:
                steps.append({
                    "gw": step.gameweek,
                    **action(step.action),
                    "lineup_points": step.lineup_points,
                    "points_after_hit": step.points_after_hit,
                    "starting_xi": list(step.starting_xi),
                    "bench_order": list(step.bench_order),
                    "captain": step.captain_id,
                    "vice_captain": step.vice_captain_id,
                    "price_risk": dict(step.price_risk),
                })
            return {
                "path": steps,
                "projected_3gw_path_points": row.projected_3gw_path_points,
                "terminal_ft_value": row.terminal_ft_value,
                "total_path_value": row.total_path_value,
            }

        best = path(self.best_path)
        hold = path(self.hold_now_path)
        return {
            "version": "strategic_planner_v3",
            "current_action": action(self.best_path.steps[0].action),
            "projected_next_action": action(self.best_path.steps[1].action),
            **best,
            "hold_now_counterfactual": path(self.hold_now_path),
            "delta_vs_hold_now": self.delta_vs_hold_now,
            "price_risk": dict(self.best_path.steps[1].price_risk),
            "diagnostics": dict(self.diagnostics),
        }


@dataclass(frozen=True)
class _Node:
    state: SquadState
    steps: tuple[StrategicPathStep, ...]
    points: float


class StrategicPlannerV3:
    """Exact-on-the-beam sequential planner; never activates chips or mutates state."""

    VERSION = "strategic_planner_v3"

    def __init__(self, rules: OptimizerRules, config: StrategicPlannerV3Config | None = None) -> None:
        self.rules = rules
        self.config = config or StrategicPlannerV3Config()
        self._lineup_cache: dict[tuple[int, tuple[str, ...]], object] = {}
        self._timing = {"candidate_generation_seconds": 0.0, "beam_expansion_seconds": 0.0, "lineup_evaluation_seconds": 0.0}
        self._states_expanded = 0
        self._actions_evaluated = 0

    def plan(
        self,
        state: SquadState,
        pool: Iterable[SquadPlayer],
        projections: Mapping[str, PlayerProjection],
        *,
        price_signals: Mapping[str, PriceChangeSignal] | None = None,
    ) -> StrategicPlannerV3Result:
        try:
            validate_squad(state, self.rules)
        except OptimizerError as exc:
            raise StrategicPlannerV3Error("V3 requires a valid current SquadState") from exc
        if state.season != self.rules.season or state.rule_version != self.rules.version:
            raise StrategicPlannerV3Error("V3 squad and optimizer-rule versions do not match")
        self._lineup_cache = {}
        self._timing = {"candidate_generation_seconds": 0.0, "beam_expansion_seconds": 0.0, "lineup_evaluation_seconds": 0.0}
        self._states_expanded = 0
        self._actions_evaluated = 0
        started = time.perf_counter()
        signals = dict(price_signals) if price_signals is not None else None
        if signals is not None and state.prediction_timestamp is not None:
            future = [
                player_id for player_id, signal in signals.items()
                if signal.observed_at_utc > state.prediction_timestamp
            ]
            if future:
                raise StrategicPlannerV3Error(
                    "V3 price signals must be observed no later than the prediction timestamp: "
                    + ", ".join(sorted(future))
                )
        pool_by_id = {player.player_id: player for player in pool if player.player_id in projections}
        for player in state.players:
            pool_by_id.setdefault(player.player_id, player)
        best = self._search(state, pool_by_id, projections, signals=signals, force_hold_now=False)
        hold = self._search(state, pool_by_id, projections, signals=signals, force_hold_now=True)
        diagnostics = {
            "planner_version": self.VERSION,
            "planning_horizon": self.config.planning_horizon,
            "beam_width": self.config.beam_width,
            "max_actions_per_state": self.config.max_actions_per_state,
            "candidates_per_position": self.config.candidates_per_position,
            "states_expanded": self._states_expanded,
            "candidate_actions_evaluated": self._actions_evaluated,
            **self._timing,
            "total_runtime_seconds": time.perf_counter() - started,
            "price_signal_status": "UNAVAILABLE" if signals is None else "AVAILABLE",
        }
        return StrategicPlannerV3Result(best, hold, diagnostics)

    def _search(self, state, pool_by_id, projections, *, signals, force_hold_now: bool) -> StrategicPath:
        beam = [_Node(state, (), 0.0)]
        for offset in range(self.config.planning_horizon):
            expanded: list[_Node] = []
            for node in beam:
                self._states_expanded += 1
                candidate_started = time.perf_counter()
                actions = self._actions_for_state(node.state, pool_by_id, projections, target_gameweek=node.state.current_gameweek)
                self._timing["candidate_generation_seconds"] += time.perf_counter() - candidate_started
                if offset == 0 and force_hold_now:
                    actions = [row for row in actions if row.is_hold]
                expansion_started = time.perf_counter()
                for action in actions:
                    self._actions_evaluated += 1
                    next_state, step = self._evaluate_action(
                        node.state, action, pool_by_id, projections,
                        target_gameweek=node.state.current_gameweek, signals=signals, offset=offset,
                    )
                    expanded.append(_Node(next_state, node.steps + (step,), node.points + step.points_after_hit))
                self._timing["beam_expansion_seconds"] += time.perf_counter() - expansion_started
            if not expanded:
                raise StrategicPlannerV3Error("V3 could not construct a legal action path")
            # At the horizon boundary, terminal FT value is already part of
            # the documented V3 objective.  Include it *before* beam trimming
            # so a marginal final-GW transfer cannot evict a superior HOLD
            # path and prevent the final objective comparison from happening.
            if offset == self.config.planning_horizon - 1:
                expanded.sort(
                    key=lambda node: (
                        -(node.points + self._terminal_ft_value(node.state)),
                        self._path_key(node.steps),
                    )
                )
            else:
                expanded.sort(key=lambda node: (-node.points, self._path_key(node.steps)))
            beam = expanded[:self.config.beam_width]
        candidates = []
        for node in beam:
            terminal = self._terminal_ft_value(node.state)
            candidates.append((node.points + terminal, node.points, terminal, node))
        candidates.sort(key=lambda row: (-row[0], self._path_key(row[3].steps)))
        total, points, terminal, node = candidates[0]
        return StrategicPath(node.steps, points, terminal, total)

    @staticmethod
    def _path_key(steps: tuple[StrategicPathStep, ...]) -> tuple:
        return tuple((step.action.action, step.action.transfers_out, step.action.transfers_in) for step in steps)

    def _actions_for_state(self, state, pool_by_id, projections, *, target_gameweek: int) -> list[StrategicAction]:
        hold = StrategicAction(
            "HOLD", (), (), 0, 0, state.bank, state.free_transfers,
            next_free_transfers(state.free_transfers, 0, self.rules),
            tuple(sorted(player.player_id for player in state.players)),
        )
        owned = {player.player_id: player for player in state.players}
        shortlist: dict[str, tuple[SquadPlayer, ...]] = {}
        for position in ("GK", "DEF", "MID", "FWD"):
            rows = [
                player for player in pool_by_id.values()
                if player.player_id not in owned and player.position == position
                and self._gameweek_projection(projections[player.player_id], target_gameweek) is not None
            ]
            shortlist[position] = tuple(sorted(
                rows,
                key=lambda player: (-self._points(projections[player.player_id], target_gameweek), player.current_price, player.player_id),
            )[:self.config.candidates_per_position])
        singles: list[StrategicAction] = []
        for outgoing in state.players:
            for incoming in shortlist[outgoing.position]:
                candidate = self._make_action(state, (outgoing,), (incoming,))
                if candidate is not None:
                    singles.append(candidate)
        singles.sort(key=lambda action: (-self._quick_gain(action, owned, pool_by_id, projections, target_gameweek), action.transfers_out, action.transfers_in))
        actions: dict[tuple[tuple[str, ...], tuple[str, ...]], StrategicAction] = {((), ()): hold}
        for action in singles[:self.config.max_actions_per_state - 1]:
            actions[(action.transfers_out, action.transfers_in)] = action
        if self.config.max_transfers_per_action >= 2:
            seed = singles[: min(len(singles), 12)]
            for index, left in enumerate(seed):
                for right in seed[index + 1:]:
                    if set(left.transfers_out) & set(right.transfers_out) or set(left.transfers_in) & set(right.transfers_in):
                        continue
                    outgoing = tuple(owned[player_id] for player_id in (*left.transfers_out, *right.transfers_out))
                    incoming = tuple(pool_by_id[player_id] for player_id in (*left.transfers_in, *right.transfers_in))
                    action = self._make_action(state, outgoing, incoming)
                    if action is not None:
                        actions[(action.transfers_out, action.transfers_in)] = action
        ranked = sorted(
            (action for action in actions.values() if not action.is_hold),
            key=lambda action: (-self._quick_gain(action, owned, pool_by_id, projections, target_gameweek), action.transfers_out, action.transfers_in),
        )
        return [hold, *ranked[: self.config.max_actions_per_state - 1]]

    def _make_action(self, state, outgoing, incoming) -> StrategicAction | None:
        if len(outgoing) != len(incoming) or not outgoing or len(incoming) > self.config.max_transfers_per_action:
            return None
        current = {player.player_id: player for player in state.players}
        if any(player.player_id not in current for player in outgoing) or any(player.player_id in current for player in incoming):
            return None
        next_players = dict(current)
        proceeds = 0
        for player in outgoing:
            next_players.pop(player.player_id)
            proceeds += player.selling_price if player.selling_price is not None else selling_price(player.purchase_price, player.current_price, self.rules)
        spend = sum(player.current_price for player in incoming)
        bank = state.bank + proceeds - spend
        if bank < 0:
            return None
        for player in incoming:
            # Buying today establishes a real acquisition price.  Later actions
            # calculate the normal selling price from it; no future quote is invented.
            next_players[player.player_id] = replace(player, purchase_price=player.current_price, selling_price=player.current_price)
        try:
            validate_squad(replace(state, players=tuple(next_players.values()), bank=bank), self.rules)
        except OptimizerError:
            return None
        count = len(incoming)
        hit_unit = int(self.rules.value("transfers", "normal_gameweek", "points_cost_per_transfer_above_allowance"))
        hit = max(0, count - state.free_transfers) * hit_unit
        return StrategicAction(
            "TRANSFER", tuple(sorted(player.player_id for player in outgoing)), tuple(sorted(player.player_id for player in incoming)),
            count, hit, bank, state.free_transfers, next_free_transfers(state.free_transfers, count, self.rules),
            tuple(sorted(next_players)),
        )

    def _quick_gain(self, action, owned, pool_by_id, projections, target_gameweek) -> float:
        return sum(self._points(projections[player_id], target_gameweek) for player_id in action.transfers_in) - sum(
            self._points(projections[player_id], target_gameweek) for player_id in action.transfers_out
        ) - action.hit_cost_points

    def _evaluate_action(self, state, action, pool_by_id, projections, *, target_gameweek, signals, offset):
        next_players = {player.player_id: player for player in state.players}
        for player_id in action.transfers_out:
            next_players.pop(player_id)
        for player_id in action.transfers_in:
            player = pool_by_id[player_id]
            next_players[player_id] = replace(player, purchase_price=player.current_price, selling_price=player.current_price)
        current_state = replace(state, players=tuple(next_players.values()), bank=action.resulting_bank)
        key = (target_gameweek, tuple(sorted(next_players)))
        lineup_started = time.perf_counter()
        lineup = self._lineup_cache.get(key)
        if lineup is None:
            gw_projections = self._projections_for_gameweek(projections, target_gameweek)
            try:
                lineup = optimize_lineup(current_state, gw_projections, self.rules)
            except OptimizerError as exc:
                raise StrategicPlannerV3Error("V3 could not optimize a legal current-GW lineup") from exc
            self._lineup_cache[key] = lineup
        self._timing["lineup_evaluation_seconds"] += time.perf_counter() - lineup_started
        next_state = replace(
            current_state,
            free_transfers=action.free_transfers_after,
            current_gameweek=target_gameweek + 1,
        )
        step = StrategicPathStep(
            target_gameweek, action, float(lineup.expected_points), float(lineup.expected_points) - action.hit_cost_points,
            tuple(lineup.starting_xi), tuple(lineup.bench_order), lineup.captain_id, lineup.vice_captain_id,
            self._price_risk(state, action, signals=signals, offset=offset),
        )
        return next_state, step

    def _projections_for_gameweek(self, projections, gameweek):
        result = {}
        for player_id, row in projections.items():
            selected = self._gameweek_projection(row, gameweek)
            if selected is None:
                raise StrategicPlannerV3Error(f"V3 projection bundle has no GW{gameweek} row for {player_id}")
            points = float(selected.expected_points)
            result[player_id] = replace(
                row, gameweeks=(selected,), ev_next_1=points, ev_next_3=points, ev_next_6=points,
                weighted_ev_next_1=points, weighted_ev_next_3=points, weighted_ev_next_6=points,
                expected_minutes_next_1=float(selected.expected_minutes), expected_minutes_next_3=float(selected.expected_minutes),
                expected_minutes_next_6=float(selected.expected_minutes),
            )
        return result

    @staticmethod
    def _gameweek_projection(row: PlayerProjection, gameweek: int):
        return next((item for item in row.gameweeks if item.target_gameweek == gameweek), None)

    def _points(self, row: PlayerProjection, gameweek: int) -> float:
        selected = self._gameweek_projection(row, gameweek)
        return float(selected.expected_points) if selected is not None else float("-inf")

    def _terminal_ft_value(self, state: SquadState) -> float:
        """Small, isolated V2-style option value after the final simulated GW."""
        hit = int(self.rules.value("transfers", "normal_gameweek", "points_cost_per_transfer_above_allowance"))
        return state.free_transfers * hit * self.config.terminal_ft_need_probability

    @staticmethod
    def _price_risk(state, action, *, signals, offset: int) -> dict[str, object]:
        if offset != 1:
            return {"level": "UNAVAILABLE" if signals is None else "STATIC_ASSUMPTION", "message": "Future price is not estimated for this gameweek."}
        if signals is None:
            return {"level": "UNAVAILABLE", "message": "Price risk unavailable."}
        rises = [signals.get(player_id) for player_id in action.transfers_in]
        rises = [signal for signal in rises if signal is not None and signal.direction == "rise"]
        if not rises:
            return {"level": "LOW", "message": "No supplied next-GW rise risk for this action."}
        rise = sum(max(0, signal.expected_next_change or 0) for signal in rises)
        # ``resulting_bank`` is the exact current-price feasibility margin for
        # this action. A supplied rise exceeds it only in the sensitivity flag;
        # the planner never substitutes a hypothetical future price.
        high = rise > 0 and action.resulting_bank < rise
        return {
            "level": "HIGH" if high else "MEDIUM",
            "message": "Plan may become unaffordable if the target rises before the next deadline." if high else "Target has supplied near-term rise risk.",
            "sensitive_player_ids": [signal.player_id for signal in rises],
            "uses_current_price_only": True,
        }
