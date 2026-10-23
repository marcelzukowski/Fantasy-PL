"""Exact small-universe checks for the isolated CP-SAT transfer package generator."""

from dataclasses import replace
from itertools import combinations, product
import json
from types import SimpleNamespace

from hypothesis import given, settings, strategies as st
import pytest

from fpl_engine.optimizer import OptimizerRules, validate_squad
from fpl_engine.strategy.strategic_planner_v3 import StrategicPlannerV3, StrategicPlannerV3Config
from scripts.diagnostics import cpsat_packages
from scripts.diagnostics.v3_challenger_oracle import (
    ROOT,
    _club_cycle_fixture,
    _five_transfer_fixture,
    _funding_cycle_fixture,
)
from scripts.diagnostics.v3_multi_transfer_oracle import _fixture, _hold


RULES = OptimizerRules.load(ROOT)


@pytest.mark.parametrize(
    "signal,scaled", [(1.0000005, 1000000), (1.0000015, 1000002), (-1.0000005, -1000000)]
)
def test_declared_projection_integer_scaling_is_half_even(signal, scaled):
    state, pool, projections = _fixture(53, RULES)
    pid = state.players[0].player_id
    changed = {**projections, pid: replace(projections[pid], ev_next_3=signal)}
    problem = cpsat_packages.prepare_problem(state, pool, changed, RULES)
    assert next(row["weight"] for row in problem["players"] if row["player_id"] == pid) == scaled


def test_feasible_status_is_not_promoted_and_invalid_bounds_are_rejected():
    from copy import deepcopy

    state, pool, projections = _fixture(51, RULES)
    result = _generate(state, pool, projections, candidates_per_k=1)
    prepared = cpsat_packages.prepare_problem(state, pool, projections, RULES)
    for attempt in result["attempts"]:
        if attempt["status"] == "OPTIMAL":
            attempt["status"] = "FEASIBLE"
            attempt["objective_bound_scaled"] += prepared["objective_scale"]
    for packages in result["packages_by_k"].values():
        for package in packages:
            package["status"] = "FEASIBLE"
            package["objective_bound_scaled"] += prepared["objective_scale"]
    checked = cpsat_packages.validate_packages(prepared, state, pool, RULES, result)
    assert checked["packages_by_k"]["0"][0]["status"] == "FEASIBLE"
    invalid = deepcopy(result)
    invalid["packages_by_k"]["0"][0]["objective_bound_scaled"] = float("nan")
    with pytest.raises(ValueError, match="bound"):
        cpsat_packages.validate_packages(prepared, state, pool, RULES, invalid)


def test_input_integrity_rejects_duplicate_pool_and_nonfinite_projection():
    state, pool, projections = _fixture(52, RULES)
    duplicate = [*pool.values(), next(iter(pool.values()))]
    with pytest.raises(ValueError, match="Duplicate"):
        cpsat_packages.prepare_problem(state, duplicate, projections, RULES)
    pid = state.players[0].player_id
    changed = {**projections, pid: replace(projections[pid], ev_next_3=float("nan"))}
    with pytest.raises(ValueError, match="Nonfinite"):
        cpsat_packages.prepare_problem(state, pool, changed, RULES)


def _exact_by_k(state, pool, projections, rules, prepared):
    """Enumerate the prepared player universe while delegating legality to native V3."""
    planner = StrategicPlannerV3(rules, StrategicPlannerV3Config(max_transfers_per_action=5))
    owned_ids = {player.player_id for player in state.players}
    incoming_by_position = {
        position: tuple(
            sorted(
                (
                    player
                    for player in pool.values()
                    if player.player_id not in owned_ids
                    and player.position == position
                    and planner._gameweek_projection(
                        projections[player.player_id], state.current_gameweek
                    )
                    is not None
                ),
                key=lambda player: player.player_id,
            )
        )
        for position in ("GK", "DEF", "MID", "FWD")
    }
    actions = {0: [_hold(state, rules)]}
    for k in range(1, min(5, len(state.players)) + 1):
        rows = {}
        for outgoing in combinations(state.players, k):
            choices = [incoming_by_position[player.position] for player in outgoing]
            if any(not group for group in choices):
                continue
            for incoming in product(*choices):
                if len({player.player_id for player in incoming}) != k:
                    continue
                action = planner._make_action(state, outgoing, incoming)
                if action is not None:
                    rows[(action.transfers_out, action.transfers_in)] = action
        actions[k] = list(rows.values())

    weights = {row["player_id"]: row["weight"] for row in prepared["players"]}
    objectives = {}
    for k, rows in actions.items():
        scored = []
        for action in rows:
            squad_points = sum(weights[player_id] for player_id in action.resulting_squad)
            objective = squad_points - action.hit_cost_points * prepared["objective_scale"]
            scored.append((objective, action.transfers_out, action.transfers_in))
        objectives[k] = sorted(scored, key=lambda row: (-row[0], row[1], row[2]))
    return objectives


def _generate(state, pool, projections, *, candidates_per_k=5):
    return cpsat_packages.generate_packages(
        state,
        pool,
        projections,
        RULES,
        candidates_per_k=candidates_per_k,
        time_limit_seconds=1.0,
    )


def test_solver_optima_match_exhaustive_native_v3_surrogate_per_transfer_count():
    state, pool, projections = _fixture(19, RULES)
    prepared = cpsat_packages.prepare_problem(state, pool, projections, RULES)
    exact = _exact_by_k(state, pool, projections, RULES, prepared)
    result = _generate(state, pool, projections)

    assert result["packages_by_k"].keys() == {str(k) for k in range(6)}
    assert result["packages_by_k"]["0"][0]["objective_scaled"] == exact[0][0][0]
    for k in range(1, 5):
        attempt = next(row for row in result["attempts"] if row["k"] == k)
        assert attempt["status"] == "OPTIMAL"
        packages = result["packages_by_k"][str(k)]
        assert len(packages) == min(len(exact[k]), 5)
        assert packages[0]["objective_scaled"] == exact[k][0][0]
        assert [row["objective_scaled"] for row in packages] == [
            row[0] for row in exact[k][: len(packages)]
        ]
        assert all(row["objective_bound_scaled"] == row["objective_scaled"] for row in packages)
        assert len(
            {(tuple(row["transfers_out"]), tuple(row["transfers_in"])) for row in packages}
        ) == len(packages)
        assert [row["objective_scaled"] for row in packages] == [row[0] for row in exact[k][:5]]


def test_emitted_packages_are_native_v3_legal_across_club_funding_and_insufficient_cases():
    state, pool, projections = _fixture(11, RULES)
    pool = dict(pool)
    for player_id, player in tuple(pool.items()):
        if player_id.startswith("incoming-"):
            pool[player_id] = replace(
                player, current_price=100, purchase_price=100, selling_price=100
            )
    insufficient = (state, pool, projections)
    fixtures = [
        ("club", *_club_cycle_fixture(RULES)),
        ("funding", *_funding_cycle_fixture(RULES, 3)),
        ("insufficient", *insufficient),
    ]
    for name, state, pool, projections in fixtures:
        prepared = cpsat_packages.prepare_problem(state, pool, projections, RULES)
        exact = _exact_by_k(state, pool, projections, RULES, prepared)
        result = cpsat_packages.generate_packages(
            state,
            pool,
            projections,
            RULES,
            candidates_per_k=2,
            time_limit_seconds=1.0,
        )
        for k, legal in exact.items():
            if legal:
                attempt = next(row for row in result["attempts"] if row["k"] == k)
                assert attempt["status"] == "OPTIMAL"
                assert len(result["packages_by_k"][str(k)]) == min(len(legal), 2)
                assert result["packages_by_k"][str(k)][0]["objective_scaled"] == legal[0][0]
                assert [p["objective_scaled"] for p in result["packages_by_k"][str(k)]] == [
                    r[0] for r in legal[:2]
                ]
        native = {
            (action.transfers_out, action.transfers_in): action
            for rows in exact.values()
            for _, outs, ins in rows
            for action in [
                StrategicPlannerV3(
                    RULES, StrategicPlannerV3Config(max_transfers_per_action=5)
                )._make_action(
                    state,
                    tuple(
                        next(player for player in state.players if player.player_id == player_id)
                        for player_id in outs
                    ),
                    tuple(pool[player_id] for player_id in ins),
                )
            ]
            if action is not None
        }
        for k, packages in result["packages_by_k"].items():
            for package in packages:
                if k == "0":
                    assert package["transfers_out"] == []
                    assert package["transfers_in"] == []
                    assert package["resulting_bank"] == state.bank
                    continue
                action = native[(tuple(package["transfers_out"]), tuple(package["transfers_in"]))]
                assert tuple(package["resulting_squad"]) == action.resulting_squad
                assert package["resulting_bank"] == action.resulting_bank
                assert package["hit_cost_points"] == action.hit_cost_points
                assert package["free_transfers_after"] == action.free_transfers_after
        if name == "club":
            assert result["packages_by_k"]["4"]
        elif name == "funding":
            assert result["packages_by_k"]["3"]
        elif name == "insufficient":
            assert result["packages_by_k"]["0"][0]["transfers_out"] == []
            assert result["packages_by_k"]["1"] == []


def test_five_transfer_fixture_preserves_ft_and_hit_semantics_and_repeatability():
    state, pool, projections = _five_transfer_fixture(RULES)
    validate_squad(state, RULES)
    at_five = _generate(state, pool, projections, candidates_per_k=2)
    repeat = _generate(state, pool, projections, candidates_per_k=2)
    assert (
        cpsat_packages.prepare_problem(state, pool, projections, RULES)["input_sha256"]
        == cpsat_packages.prepare_problem(
            state,
            pool,
            projections,
            RULES,
        )["input_sha256"]
    )
    assert at_five["packages_by_k"] == repeat["packages_by_k"]
    assert all(row["free_transfers_before"] == 5 for row in at_five["packages_by_k"]["5"])
    assert all(row["hit_cost_points"] == 0 for row in at_five["packages_by_k"]["5"])
    prepared = cpsat_packages.prepare_problem(state, pool, projections, RULES)
    exact = _exact_by_k(state, pool, projections, RULES, prepared)
    assert next(row for row in at_five["attempts"] if row["k"] == 5)["status"] == "OPTIMAL"
    assert at_five["packages_by_k"]["5"]
    assert at_five["packages_by_k"]["5"][0]["objective_scaled"] == exact[5][0][0]

    at_four_state = replace(state, free_transfers=4)
    at_four = _generate(at_four_state, pool, projections, candidates_per_k=1)
    assert next(row for row in at_four["attempts"] if row["k"] == 5)["status"] == "OPTIMAL"
    assert at_four["packages_by_k"]["5"]
    hit_unit = int(
        RULES.value("transfers", "normal_gameweek", "points_cost_per_transfer_above_allowance")
    )
    assert all(row["hit_cost_points"] == hit_unit for row in at_four["packages_by_k"]["5"])
    assert all(row["free_transfers_before"] == 4 for row in at_four["packages_by_k"]["5"])


@settings(max_examples=5, derandomize=True, deadline=None)
@given(bank=st.integers(0, 100), free_transfers=st.integers(1, 5), sale_price=st.integers(40, 60))
def test_hypothesis_state_bank_free_transfers_and_personal_sale_price_keep_packages_legal(
    bank,
    free_transfers,
    sale_price,
):
    state, pool, projections = _fixture(23, RULES)
    changed_players = list(state.players)
    changed_players[0] = replace(changed_players[0], selling_price=sale_price)
    state = replace(state, players=tuple(changed_players), bank=bank, free_transfers=free_transfers)
    pool.update({player.player_id: player for player in changed_players})
    validate_squad(state, RULES)

    prepared = cpsat_packages.prepare_problem(state, pool, projections, RULES)
    owned_gk = next(
        row for row in prepared["players"] if row["player_id"] == changed_players[0].player_id
    )
    assert owned_gk["price"] == sale_price
    result = _generate(state, pool, projections, candidates_per_k=1)
    exact = _exact_by_k(state, pool, projections, RULES, prepared)
    assert result["packages_by_k"]["0"]
    for k, legal in exact.items():
        packages = result["packages_by_k"][str(k)]
        if legal:
            assert packages and packages[0]["status"] == "OPTIMAL"
            assert packages[0]["objective_scaled"] == legal[0][0]
        else:
            assert not packages
    planner = StrategicPlannerV3(RULES, StrategicPlannerV3Config(max_transfers_per_action=5))
    for package in result["packages_by_k"][str(min(free_transfers, 5))]:
        outgoing = tuple(
            next(player for player in state.players if player.player_id == player_id)
            for player_id in package["transfers_out"]
        )
        incoming = tuple(pool[player_id] for player_id in package["transfers_in"])
        action = planner._make_action(state, outgoing, incoming)
        assert action is not None
        assert package["resulting_bank"] == action.resulting_bank


def test_unknown_and_model_invalid_worker_attempts_are_preserved_without_packages(monkeypatch):
    state, pool, projections = _fixture(31, RULES)

    def worker(_args, **kwargs):
        problem = json.loads(kwargs["input"])["problem"]
        return SimpleNamespace(
            stdout=json.dumps(
                {
                    "input_sha256": problem["input_sha256"],
                    "packages_by_k": {str(k): [] for k in range(6)},
                    "attempts": [
                        {"k": 1, "rank": 1, "status": "UNKNOWN"},
                        {"k": 2, "rank": 1, "status": "MODEL_INVALID"},
                    ],
                }
            )
        )

    monkeypatch.setattr(cpsat_packages.subprocess, "run", worker)
    result = _generate(state, pool, projections, candidates_per_k=1)
    assert [row["status"] for row in result["attempts"]] == ["UNKNOWN", "MODEL_INVALID"]
    assert all(not packages for packages in result["packages_by_k"].values())


def test_malformed_worker_package_fails_native_replay(monkeypatch):
    state, pool, projections = _fixture(37, RULES)

    def worker(_args, **kwargs):
        problem = json.loads(kwargs["input"])["problem"]
        return SimpleNamespace(
            stdout=json.dumps(
                {
                    "input_sha256": problem["input_sha256"],
                    "packages_by_k": {
                        **{str(k): [] for k in range(6)},
                        "1": [{"transfers_out": ["forged-out"], "transfers_in": ["forged-in"]}],
                    },
                    "attempts": [{"k": 1, "rank": 1, "status": "UNKNOWN"}],
                }
            )
        )

    monkeypatch.setattr(cpsat_packages.subprocess, "run", worker)
    with pytest.raises(ValueError, match="Invalid OUT/IN identity"):
        _generate(state, pool, projections, candidates_per_k=1)
