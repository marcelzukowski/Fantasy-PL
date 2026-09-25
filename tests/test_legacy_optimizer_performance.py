from dataclasses import asdict
from datetime import datetime, timezone
from itertools import count
from types import SimpleNamespace
import random

import pytest

from fpl_engine.optimizer import (
    ChipState, Optimizer, OptimizerRules, OptimizerV2, SquadPlayer, SquadState,
    legacy_reference_search, optimized_search, optimize_lineup,
)

ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]
AT = datetime(2026, 9, 1, tzinfo=timezone.utc)


def _squad():
    positions = ["GK"] * 2 + ["DEF"] * 5 + ["MID"] * 5 + ["FWD"] * 3
    return tuple(SquadPlayer(f"p{i}", pos, f"club{i // 3}", 50, 50, 50) for i, pos in enumerate(positions))


def _projection(player_id, value):
    return SimpleNamespace(
        player_id=player_id, season="2026/27", rule_version=1, prediction_timestamp=AT,
        weighted_ev_next_6=float(value), ev_next_1=float(value), ev_next_3=float(value),
        ev_next_6=float(value), projection_uncertainty=.2,
        gameweeks=(SimpleNamespace(expected_points=float(value)),),
    )


def _state(*, bank=10, ft=1):
    return SquadState(_squad(), bank, ft, ChipState(), 5, "2026/27", 1, AT)


def _pool(*, per_position=2, premium=False, same_club=False):
    rows = []
    for position_index, position in enumerate(("GK", "DEF", "MID", "FWD")):
        for index in range(per_position):
            price = 90 if premium and position == "MID" and index == 0 else 50
            club = "club0" if same_club else f"new_{position}_{index}"
            rows.append(SquadPlayer(f"{position.lower()}_{index}", position, club, price, price))
    return tuple(rows)


def _projections(state, pool):
    values = {player.player_id: _projection(player.player_id, 5 + index / 10)
              for index, player in enumerate(state.players)}
    values.update({player.player_id: _projection(player.player_id, 10 + index)
                   for index, player in enumerate(pool)})
    return values


def _plans(result):
    return tuple(asdict(plan) for plan in result.plans)


@pytest.mark.parametrize("bank,ft,premium,same_club", [
    (0, 1, False, False),  # exact zero-bank and one FT/hit paths
    (10, 2, False, False), # two FT no-hit path
    (0, 1, True, False),   # expensive premium needs an exact funding move
    (10, 1, False, True),  # club-limit exact boundary
])
def test_v1_reference_and_optimized_search_have_identical_golden_plan_portfolio(bank, ft, premium, same_club):
    rules = OptimizerRules.load(ROOT)
    state = _state(bank=bank, ft=ft)
    pool = _pool(premium=premium, same_club=same_club)
    projections = _projections(state, pool)
    reference = legacy_reference_search(state, projections, pool, rules, max_transfers=2)
    optimized = optimized_search(state, projections, pool, rules, max_transfers=2)
    assert _plans(optimized) == _plans(reference)
    assert optimized.plans[0] == reference.plans[0]
    assert optimized.diagnostics.raw_single_combinations == reference.diagnostics.raw_single_combinations
    assert optimized.diagnostics.raw_two_combinations == reference.diagnostics.raw_two_combinations


def test_three_transfer_path_matches_reference_when_the_existing_rules_allow_it():
    rules = OptimizerRules.load(ROOT)
    state = _state(bank=10, ft=3)
    pool = _pool(per_position=1)
    projections = _projections(state, pool)
    reference = legacy_reference_search(state, projections, pool, rules, max_transfers=3)
    optimized = optimized_search(state, projections, pool, rules, max_transfers=3)
    assert _plans(optimized) == _plans(reference)
    assert any(len(plan.transfers_in) == 3 for plan in optimized.plans)


def test_hold_tie_and_exact_affordability_keep_existing_winner_and_order():
    rules = OptimizerRules.load(ROOT)
    state = _state(bank=0, ft=1)
    exact = SquadPlayer("exact", "FWD", "new", 50, 50)
    tied = SquadPlayer("tied", "FWD", "new2", 50, 50)
    projections = _projections(state, (exact, tied))
    projections["exact"] = _projection("exact", 99)
    projections["tied"] = _projection("tied", 5.0)
    reference = legacy_reference_search(state, projections, (exact, tied), rules, max_transfers=1)
    optimized = optimized_search(state, projections, (exact, tied), rules, max_transfers=1)
    assert _plans(optimized) == _plans(reference)
    assert optimized.plans[0].transfers_in == ("exact",)
    # Equal score with HOLD retains the historic explicit sort tie-break.
    projections["exact"] = _projection("exact", 5.0)
    assert optimized_search(state, projections, (exact, tied), rules, max_transfers=1).plans[0].roll_ft


def test_defensive_duplicate_or_owned_pool_rows_keep_legacy_portfolio_semantics():
    rules = OptimizerRules.load(ROOT)
    state = _state(bank=10, ft=2)
    duplicate = SquadPlayer("duplicate-fwd", "FWD", "new", 50, 50)
    pool = (state.players[0], duplicate, duplicate)
    projections = _projections(state, pool)
    reference = legacy_reference_search(state, projections, pool, rules, max_transfers=2)
    optimized = optimized_search(state, projections, pool, rules, max_transfers=2)
    assert _plans(optimized) == _plans(reference)
    assert optimized.diagnostics.rejected_duplicate_incoming == 3


def test_position_prefilter_avoids_impossible_pairs_but_keeps_legal_set():
    rules = OptimizerRules.load(ROOT)
    state = _state()
    pool = _pool(per_position=4)
    projections = _projections(state, pool)
    reference = legacy_reference_search(state, projections, pool, rules, max_transfers=2)
    optimized = optimized_search(state, projections, pool, rules, max_transfers=2)
    assert _plans(optimized) == _plans(reference)
    assert optimized.diagnostics.position_prefiltered < (
        optimized.diagnostics.raw_single_combinations + optimized.diagnostics.raw_two_combinations
    )
    assert optimized.diagnostics.canonical_legality_checks < reference.diagnostics.canonical_legality_checks


def test_seeded_random_small_pools_match_exhaustive_reference():
    rules = OptimizerRules.load(ROOT)
    for seed in range(24):
        rng = random.Random(seed)
        state = _state(bank=rng.randrange(0, 21), ft=rng.randrange(1, 4))
        rows = []
        for position in ("GK", "DEF", "MID", "FWD"):
            for index in range(3):
                price = rng.randrange(40, 101)
                rows.append(SquadPlayer(f"{position}-{seed}-{index}", position, f"club-{rng.randrange(3, 12)}", price, price))
        projections = _projections(state, rows)
        for player in rows:
            projections[player.player_id] = _projection(player.player_id, rng.uniform(0, 25))
        reference = legacy_reference_search(state, projections, rows, rules, max_transfers=2)
        optimized = optimized_search(state, projections, rows, rules, max_transfers=2)
        assert _plans(optimized) == _plans(reference), seed


def test_optimizer_recommendation_matches_exhaustive_reference_winner_and_keeps_typed_contract():
    rules = OptimizerRules.load(ROOT)
    state = _state(bank=10, ft=2)
    pool = _pool(per_position=3)
    projections = _projections(state, pool)
    reference = legacy_reference_search(state, projections, pool, rules, max_transfers=2)
    recommendation = Optimizer(rules).recommend(state, projections, pool, max_transfers=2)
    winner = reference.plans[0]
    assert (recommendation.transfers_out, recommendation.transfers_in) == (winner.transfers_out, winner.transfers_in)
    assert recommendation.resulting_bank == winner.bank_after
    assert recommendation.free_transfers_after == winner.free_transfers_after
    assert recommendation.hit_cost == winner.hit_cost



def test_v1_and_v2_reuse_one_run_scoped_lineup_provider_for_the_same_resulting_squad():
    rules = OptimizerRules.load(ROOT)
    state = _state(bank=10, ft=2)
    pool = _pool(per_position=1)
    projections = _projections(state, pool)
    cache = {}
    calls = {"evaluations": 0, "hits": 0}

    def cached_lineup(working, **options):
        normalized_options = {"triple_captain": False, "bench_boost": False, **options}
        key = (tuple(sorted(player.player_id for player in working.players)), tuple(sorted(normalized_options.items())))
        if key in cache:
            calls["hits"] += 1
            return cache[key]
        calls["evaluations"] += 1
        cache[key] = optimize_lineup(working, projections, rules, **options)
        return cache[key]

    v1 = Optimizer(rules, lineup_provider=cached_lineup).recommend(state, projections, (), max_transfers=0)
    v2 = OptimizerV2(rules, lineup_provider=cached_lineup).recommend(state, projections, (), max_transfers=0)
    assert calls == {"evaluations": 1, "hits": 1}
    assert (v1.starting_xi, v1.bench_order, v1.captain_id, v1.vice_captain_id) == (
        v2.starting_xi, v2.bench_order, v2.captain_id, v2.vice_captain_id,
    )
    alternate = pool[-1]
    different_state = SquadState(
        state.players[:-1] + (alternate,), state.bank, state.free_transfers, state.chips,
        state.current_gameweek, state.season, state.rule_version, state.prediction_timestamp,
    )
    cached_lineup(different_state)
    assert calls == {"evaluations": 2, "hits": 1}


def test_v2_generator_pool_is_equivalent_to_a_tuple_pool():
    rules = OptimizerRules.load(ROOT)
    state = _state(bank=10, ft=2)
    pool = _pool(per_position=3)
    projections = _projections(state, pool)
    tuple_result = OptimizerV2(rules).recommend(state, projections, pool, max_transfers=2)
    generator_result = OptimizerV2(rules).recommend(state, projections, (row for row in pool), max_transfers=2)
    assert asdict(generator_result) == asdict(tuple_result)
