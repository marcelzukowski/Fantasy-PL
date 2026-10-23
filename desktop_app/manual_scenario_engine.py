"""Read-only manual transfer evaluation on the native production V3 engine."""

from __future__ import annotations

from hashlib import sha256
from dataclasses import asdict
from copy import deepcopy
from math import isfinite
import json
from time import monotonic

from fpl_engine.optimizer import next_free_transfers, validate_squad
from fpl_engine.strategy import StrategicPlannerV3, StrategicPlannerV3Config
from fpl_engine.strategy.strategic_planner_v3 import StrategicAction


class ManualScenarioError(ValueError):
    pass


class ManualScenarioEvaluator:
    """Validate atomic K0..5 packages and evaluate them with native V3 paths."""

    def __init__(self, shared, *, input_sha256: str | None = None):
        self.shared = shared
        self.context_id = str(shared.context_id)
        self._native_digest = self._digest(shared)
        self.input_sha256 = sha256(
            ((input_sha256 or "") + self._native_digest).encode()
        ).hexdigest()
        self._results: dict[tuple[str, str, tuple[str, ...], tuple[str, ...]], dict] = {}
        self._baseline: tuple[dict, dict] | None = None
        config = StrategicPlannerV3Config(max_transfers_per_action=5)
        self._validator = StrategicPlannerV3(shared.rules, config)

    @staticmethod
    def _digest(shared) -> str:
        payload = {
            "context_id": str(shared.context_id),
            "state": repr(shared.state),
            "players": [repr(row) for row in shared.player_pool],
            "projections": [
                (key, repr(value)) for key, value in sorted(shared.projections.items())
            ],
            "rules": shared.rules.raw,
            "config": asdict(StrategicPlannerV3Config()),
        }
        return sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

    def _check_context(self, context_id: str | None) -> None:
        if (
            str(self.shared.context_id) != self.context_id
            or self._digest(self.shared) != self._native_digest
            or context_id is not None
            and context_id != self.context_id
        ):
            raise ManualScenarioError("The selected PlanningContext does not match this worker.")

    def _package(self, transfers_out, transfers_in):
        outs, ins = tuple(map(str, transfers_out)), tuple(map(str, transfers_in))
        if (
            len(outs) != len(ins)
            or len(outs) > 5
            or len(set(outs)) != len(outs)
            or len(set(ins)) != len(ins)
        ):
            raise ManualScenarioError(
                "Transfers must contain matching, unique OUT and IN IDs with K between 0 and 5."
            )
        state = self.shared.state
        try:
            validate_squad(state, self.shared.rules)
        except ValueError as exc:
            raise ManualScenarioError("Current squad is invalid: " + str(exc)) from exc
        pool = {row.player_id: row for row in self.shared.player_pool}
        if any(player_id not in {row.player_id for row in state.players} for player_id in outs):
            raise ManualScenarioError(
                "Every outgoing player must be owned in the current PlanningContext."
            )
        if any(
            player_id not in pool or player_id in {row.player_id for row in state.players}
            for player_id in ins
        ):
            raise ManualScenarioError(
                "Every incoming player must be an unowned player in the verified projection pool."
            )
        for pid in ({p.player_id for p in state.players} - set(outs)) | set(ins):
            row = self.shared.projections.get(pid)
            if row is None or any(
                self._validator._gameweek_projection(row, state.current_gameweek + i) is None
                for i in range(3)
            ):
                raise ManualScenarioError(
                    "The verified projection bundle lacks the complete 3-GW horizon for " + pid
                )
        if not outs:
            return None
        try:
            action = self._validator._make_action(
                state,
                tuple(
                    next(row for row in state.players if row.player_id == player_id)
                    for player_id in outs
                ),
                tuple(pool[player_id] for player_id in ins),
            )
        except Exception as exc:
            raise ManualScenarioError(
                f"Could not validate the final simultaneous squad: {exc}"
            ) from exc
        if action is None:
            raise ManualScenarioError(
                "The final simultaneous squad is unaffordable or violates squad rules."
            )
        return action

    def validate(self, transfers_out, transfers_in, *, context_id: str | None = None) -> dict:
        self._check_context(context_id)
        outs, ins = tuple(map(str, transfers_out)), tuple(map(str, transfers_in))
        action = self._package(outs, ins)
        state = self.shared.state
        k = len(outs)
        if action is None:
            squad = tuple(sorted(player.player_id for player in state.players))
            bank = state.bank
            ft_after = next_free_transfers(state.free_transfers, 0, self.shared.rules)
        else:
            squad, bank, ft_after = (
                action.resulting_squad,
                action.resulting_bank,
                action.free_transfers_after,
            )
        return {
            "k": k,
            "initial_ft": state.free_transfers,
            "hit_points": 0 if action is None else action.hit_cost_points,
            "bank_after": bank,
            "ft_after": ft_after,
            "final_squad": list(squad),
        }

    def _deadline_hooks(self, planner, deadline, progress):
        original_actions = planner._actions_for_state
        original_evaluate = planner._evaluate_action
        count = 0

        def check():
            if monotonic() >= deadline:
                raise TimeoutError("Manual scenario evaluation timed out.")

        def actions(*args, **kwargs):
            nonlocal count
            check()
            count += 1
            if progress is not None and (count == 1 or count % 10 == 0):
                progress(f"Evaluating V3 paths ({count} search states)")
            return original_actions(*args, **kwargs)

        def evaluate(*args, **kwargs):
            check()
            return original_evaluate(*args, **kwargs)

        planner._actions_for_state = actions
        planner._evaluate_action = evaluate
        return check

    def _verify_path(self, path, max_current=5):
        verifier = StrategicPlannerV3(
            self.shared.rules, StrategicPlannerV3Config(max_transfers_per_action=5)
        )
        state = self.shared.state
        pool = {p.player_id: p for p in self.shared.player_pool}
        total = 0.0
        if len(path.steps) != 3:
            raise ManualScenarioError("Scenario horizon is not three gameweeks.")
        for offset, step in enumerate(path.steps):
            a = step.action
            owned = {p.player_id: p for p in state.players}
            if a.transfers_used > (max_current if offset == 0 else 2):
                raise ManualScenarioError("Scenario exceeds its transfer limit.")
            if a.transfers_out:
                expected = verifier._make_action(
                    state,
                    tuple(owned[x] for x in a.transfers_out),
                    tuple(pool[x] for x in a.transfers_in),
                )
            else:
                expected = StrategicAction(
                    "HOLD",
                    (),
                    (),
                    0,
                    0,
                    state.bank,
                    state.free_transfers,
                    next_free_transfers(state.free_transfers, 0, self.shared.rules),
                    tuple(sorted(owned)),
                )
            if a != expected or step.gameweek != state.current_gameweek:
                raise ManualScenarioError("Scenario accounting mismatch.")
            state, replayed = verifier._evaluate_action(
                state,
                a,
                pool,
                self.shared.projections,
                target_gameweek=state.current_gameweek,
                signals=None,
                offset=offset,
            )
            validate_squad(state, self.shared.rules)
            ids = {p.player_id for p in state.players}
            xi = set(step.starting_xi)
            bench = set(step.bench_order)
            if (
                len(xi) != 11
                or len(bench) != 4
                or xi & bench
                or xi | bench != ids
                or step.captain_id not in xi
                or step.vice_captain_id not in xi
                or step.captain_id == step.vice_captain_id
            ):
                raise ManualScenarioError("Scenario XI or captain identities are invalid.")
            if (
                abs(step.lineup_points - replayed.lineup_points) > 1e-9
                or abs(step.points_after_hit - replayed.points_after_hit) > 1e-9
            ):
                raise ManualScenarioError("Scenario lineup objective cannot be reconstructed.")
            total += step.points_after_hit
        terminal = verifier._terminal_ft_value(state)
        if (
            not isfinite(path.total_path_value)
            or abs(total - path.projected_3gw_path_points) > 1e-9
            or abs(terminal - path.terminal_ft_value) > 1e-9
            or abs(total + terminal - path.total_path_value) > 1e-9
        ):
            raise ManualScenarioError("Scenario complete objective cannot be reconstructed.")

    @staticmethod
    def _scenario(path, action, state, *, delta_hold=0.0, delta_production=0.0):
        steps = []
        for step in path.steps:
            steps.append(
                {
                    "gw": step.gameweek,
                    "transfers_out": list(step.action.transfers_out),
                    "transfers_in": list(step.action.transfers_in),
                    "lineup_points": step.lineup_points,
                    "hit_points": step.action.hit_cost_points,
                    "starting_xi": list(step.starting_xi),
                    "bench_order": list(step.bench_order),
                    "captain": step.captain_id,
                    "vice_captain": step.vice_captain_id,
                }
            )
        first = steps[0]
        k = len(first["transfers_in"])
        root_action = path.steps[0].action
        return {
            "transfers_out": list(first["transfers_out"]),
            "transfers_in": list(first["transfers_in"]),
            "k": k,
            "initial_ft": state.free_transfers,
            "hit_points": root_action.hit_cost_points,
            "bank_after": root_action.resulting_bank,
            "ft_after": root_action.free_transfers_after,
            "objective": path.total_path_value,
            "path_points": path.projected_3gw_path_points,
            "terminal_ft_value": path.terminal_ft_value,
            "starting_xi": first["starting_xi"],
            "bench_order": first["bench_order"],
            "captain": first["captain"],
            "vice_captain": first["vice_captain"],
            "path": steps,
            "delta_hold": delta_hold,
            "delta_production": delta_production,
        }

    def evaluate(
        self, transfers_out, transfers_in, *, progress=None, timeout_seconds=180, context_id=None
    ) -> dict:
        self._check_context(context_id)
        outs, ins = tuple(sorted(map(str, transfers_out))), tuple(sorted(map(str, transfers_in)))
        key = (self.context_id, self.input_sha256, outs, ins)
        if key in self._results:
            return deepcopy({**self._results[key], "cached": True})
        self.validate(outs, ins)
        action = self._package(outs, ins)
        deadline = monotonic() + timeout_seconds
        if self._baseline is None:
            if progress:
                progress("Computing the independent production V3 baseline")
            planner = StrategicPlannerV3(self.shared.rules)
            self._deadline_hooks(planner, deadline, progress)
            baseline_result = planner.plan(
                self.shared.state, self.shared.player_pool, self.shared.projections
            )
            self._verify_path(baseline_result.hold_now_path, 2)
            self._verify_path(baseline_result.best_path, 2)
            self._baseline = baseline_result.hold_now_path, baseline_result.best_path
        hold_path, production_path = self._baseline
        if action is None:
            scenario_path = hold_path
        else:
            planner = StrategicPlannerV3(self.shared.rules)
            check = self._deadline_hooks(planner, deadline, progress)
            original_actions = planner._actions_for_state
            root_ids = tuple(sorted(row.player_id for row in self.shared.state.players))

            def forced_current_action(state, pool, projections, *, target_gameweek):
                check()
                if (
                    target_gameweek == self.shared.state.current_gameweek
                    and tuple(sorted(row.player_id for row in state.players)) == root_ids
                ):
                    return [action]
                return original_actions(state, pool, projections, target_gameweek=target_gameweek)

            planner._actions_for_state = forced_current_action
            pool = {
                row.player_id: row
                for row in self.shared.player_pool
                if row.player_id in self.shared.projections
            }
            for player in self.shared.state.players:
                pool.setdefault(player.player_id, player)
            scenario_path = planner._search(
                self.shared.state,
                pool,
                self.shared.projections,
                signals=None,
                force_hold_now=False,
            )
        self._verify_path(scenario_path)
        scenario = self._scenario(scenario_path, action, self.shared.state)
        hold = self._scenario(hold_path, None, self.shared.state)
        production = self._scenario(production_path, None, self.shared.state)
        scenario["delta_hold"] = scenario["objective"] - hold["objective"]
        scenario["delta_production"] = scenario["objective"] - production["objective"]
        hold["delta_production"] = hold["objective"] - production["objective"]
        production["delta_hold"] = production["objective"] - hold["objective"]
        result = {
            "context_id": self.context_id,
            "input_sha256": self.input_sha256,
            "scenario": scenario,
            "hold": hold,
            "production": production,
            "cached": False,
        }
        self._results[key] = result
        return deepcopy(result)
