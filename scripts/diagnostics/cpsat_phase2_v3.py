"""Diagnostic forced-root adapter. Native V3 search, scoring and future actions are unchanged."""

from collections import Counter
from dataclasses import asdict, replace
from math import isfinite
from time import perf_counter

from fpl_engine.optimizer import next_free_transfers, validate_squad
from fpl_engine.strategy.strategic_planner_v3 import (
    StrategicAction,
    StrategicPlannerV3,
    StrategicPlannerV3Config,
)
from scripts.diagnostics.cpsat_packages import digest
from scripts.diagnostics.v3_guarded_portfolio import input_digest, validate_path


class EvaluationCache:
    def __init__(self, shared):
        self.context_id = shared.context_id
        self.input_sha256 = input_digest(shared)
        self.config = asdict(StrategicPlannerV3Config())
        self.packages, self.actions, self.evaluations, self.projections, self.lineups = (
            {},
            {},
            {},
            {},
            {},
        )
        self.hits = Counter()
        self.seconds = Counter()

    def check(self, shared):
        if (
            shared.context_id != self.context_id
            or shared.context_id != shared.planning_context.context_id
            or input_digest(shared) != self.input_sha256
            or self.config != asdict(StrategicPlannerV3Config())
        ):
            raise ValueError("Evaluation cache context/integrity mismatch")

    def metrics(self):
        return {
            "hits": dict(self.hits),
            "seconds": dict(self.seconds),
            "completed_packages": len(self.packages),
            "future_states": len(self.actions),
            "action_evaluations": len(self.evaluations),
            "lineups": len(self.lineups),
            "projection_views": len(self.projections),
        }


def _state_key(state):
    # Preserve player order too: tied native lineups/action ordering can depend on it.
    return digest(asdict(state))


class ForcedRootPlanner(StrategicPlannerV3):
    def __init__(self, rules, root_gw, action, cache, deadline):
        super().__init__(rules)
        self.root_gw, self.root_action, self.cache, self.deadline = root_gw, action, cache, deadline
        self._lineup_cache = cache.lineups

    def _check_budget(self):
        if self.deadline is not None and perf_counter() >= self.deadline:
            raise TimeoutError("Phase2 evaluation budget exceeded; incomplete path discarded")

    def _actions_for_state(self, state, pool_by_id, projections, *, target_gameweek):
        self._check_budget()
        if target_gameweek == self.root_gw:
            return [self.root_action]
        key = (_state_key(state), target_gameweek)
        if key in self.cache.actions:
            self.cache.hits["future_state"] += 1
            return self.cache.actions[key]
        value = super()._actions_for_state(
            state, pool_by_id, projections, target_gameweek=target_gameweek
        )
        self.cache.actions[key] = value
        return value

    def _evaluate_action(
        self, state, action, pool_by_id, projections, *, target_gameweek, signals, offset
    ):
        self._check_budget()
        if signals is not None:
            raise ValueError("Phase2 frozen evaluation expects unavailable price signals")
        key = (_state_key(state), action, target_gameweek, offset)
        if key in self.cache.evaluations:
            self.cache.hits["action_evaluation"] += 1
            return self.cache.evaluations[key]
        lineup_key = (target_gameweek, action.resulting_squad)
        if lineup_key in self._lineup_cache:
            self.cache.hits["resulting_squad_lineup"] += 1
        value = super()._evaluate_action(
            state,
            action,
            pool_by_id,
            projections,
            target_gameweek=target_gameweek,
            signals=signals,
            offset=offset,
        )
        self.cache.evaluations[key] = value
        return value

    def _projections_for_gameweek(self, projections, gameweek):
        if gameweek in self.cache.projections:
            self.cache.hits["projection_view"] += 1
            return self.cache.projections[gameweek]
        value = super()._projections_for_gameweek(projections, gameweek)
        self.cache.projections[gameweek] = value
        return value


def root_action(shared, package):
    outs, ins = package["transfers_out"], package["transfers_in"]
    owned = {p.player_id: p for p in shared.state.players}
    pool = {p.player_id: p for p in shared.player_pool}
    if (
        len(outs) != len(ins)
        or len(outs) > 5
        or len(set(outs)) != len(outs)
        or len(set(ins)) != len(ins)
        or outs != sorted(outs)
        or ins != sorted(ins)
        or not set(outs) <= owned.keys()
        or set(ins) & owned.keys()
        or not set(ins) <= pool.keys()
    ):
        raise ValueError("Invalid current package identity")
    validate_squad(shared.state, shared.rules)
    if not outs:
        state = shared.state
        return StrategicAction(
            "HOLD",
            (),
            (),
            0,
            0,
            state.bank,
            state.free_transfers,
            next_free_transfers(state.free_transfers, 0, shared.rules),
            tuple(sorted(owned)),
        )
    planner = StrategicPlannerV3(
        shared.rules, replace(StrategicPlannerV3Config(), max_transfers_per_action=5)
    )
    action = planner._make_action(
        shared.state, tuple(owned[x] for x in outs), tuple(pool[x] for x in ins)
    )
    if action is None:
        raise ValueError("Natively illegal simultaneous current package")
    return action


def evaluate_package(shared, package, cache, *, deadline=None):
    cache.check(shared)
    if deadline is not None and perf_counter() >= deadline:
        raise TimeoutError("Phase2 evaluation deadline exceeded")
    action = root_action(shared, package)
    key = (action.transfers_out, action.transfers_in)
    if key in cache.packages:
        cache.hits["package"] += 1
        return cache.packages[key]
    planner = ForcedRootPlanner(
        shared.rules, shared.state.current_gameweek, action, cache, deadline
    )
    pool = {p.player_id: p for p in shared.player_pool if p.player_id in shared.projections}
    for player in shared.state.players:
        pool.setdefault(player.player_id, player)
    # Call native search once: plan() would also attempt a forced-HOLD branch on a transfer-only root.
    started = perf_counter()
    path = planner._search(
        shared.state, pool, shared.projections, signals=None, force_hold_now=False
    )
    cache.seconds["native_search"] += perf_counter() - started
    if path.steps[0].action != action or any(s.action.transfers_used > 2 for s in path.steps[1:]):
        raise ValueError("Forced root / future K<=2 contract violated")
    started = perf_counter()
    validate_path(shared, path, max_k=5)
    cache.seconds["independent_replay"] += perf_counter() - started
    cache.check(shared)
    cache.packages[key] = path
    return path


def guarded_selection(incumbent, challenger_runner):
    try:
        challenger = challenger_runner()
        if not isfinite(challenger.total_path_value):
            raise ValueError("Nonfinite challenger objective")
        return (
            challenger if challenger.total_path_value > incumbent.total_path_value else incumbent
        ), None
    except Exception as exc:
        return incumbent, type(exc).__name__ + ": " + str(exc)
