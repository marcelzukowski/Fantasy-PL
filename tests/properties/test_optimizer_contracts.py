from collections import Counter
from dataclasses import replace

from hypothesis import given, strategies as st
import pytest

from fpl_engine.optimizer import OptimizerError, SquadPlayer, next_free_transfers, validate_squad
from fpl_engine.strategy.strategic_planner_v3 import StrategicPlannerV3, StrategicPlannerV3Config

from .strategies import FAST, RULES, legal_squads


@FAST
@given(legal_squads())
def test_generated_squad_obeys_native_validation_and_permutation_invariance(state):
    validate_squad(state, RULES)
    validate_squad(replace(state, players=tuple(reversed(state.players))), RULES)
    assert len(state.players) == len({p.player_id for p in state.players}) == 15
    assert Counter(p.position for p in state.players) == Counter(
        {row["canonical_code"]: row["squad_count"] for row in RULES.value("positions").values()}
    )


@FAST
@given(legal_squads())
def test_native_validator_rejects_duplicate_ids_position_club_and_zero_ft(state):
    players = state.players
    with pytest.raises(OptimizerError):
        validate_squad(replace(state, players=(*players[:-1], players[0])), RULES)
    with pytest.raises(OptimizerError):
        validate_squad(
            replace(state, players=(replace(players[0], position="FWD"), *players[1:])), RULES
        )
    with pytest.raises(OptimizerError):
        validate_squad(
            replace(state, players=tuple(replace(p, club_id="same-club") for p in players)), RULES
        )
    # Canonical SquadState currently permits FT1..5; zero is only an accounting input.
    with pytest.raises(OptimizerError):
        validate_squad(replace(state, free_transfers=0), RULES)


@FAST
@given(current=st.integers(0, 5), count=st.integers(0, 5))
def test_native_ft_rollover_stays_in_supported_accounting_range(current, count):
    assert 0 <= next_free_transfers(current, count, RULES) <= 5


@FAST
@given(legal_squads(), st.integers(1, 5), st.integers(20, 100))
def test_transfer_packages_use_personal_sales_current_buys_and_native_hits(state, count, price):
    planner = StrategicPlannerV3(
        RULES, replace(StrategicPlannerV3Config(), max_transfers_per_action=5)
    )
    outgoing = state.players[:count]
    incoming = tuple(
        SquadPlayer(f"new-{i}", p.position, f"new-club-{i}", 1, price, 1)
        for i, p in enumerate(outgoing)
    )
    bank = (
        state.bank + sum(p.selling_price for p in outgoing) - sum(p.current_price for p in incoming)
    )
    action = planner._make_action(state, outgoing, incoming)
    if bank < 0:
        assert action is None
        return
    assert action is not None
    assert action.resulting_bank == bank
    assert len(action.transfers_out) == len(set(action.transfers_out)) == count
    assert len(action.transfers_in) == len(set(action.transfers_in)) == count
    assert not set(action.transfers_out) & set(action.transfers_in)
    assert action.free_transfers_after == next_free_transfers(state.free_transfers, count, RULES)
    hit_unit = RULES.value(
        "transfers", "normal_gameweek", "points_cost_per_transfer_above_allowance"
    )
    assert action.hit_cost_points == max(0, count - state.free_transfers) * hit_unit


@FAST
@given(st.permutations(("GK", "DEF", "MID", "FWD")))
def test_atomic_four_club_final_package_does_not_require_legal_prefixes(order):
    # Reuse the accepted diagnostic fixture; native validation remains the oracle.
    from scripts.diagnostics.v3_challenger_oracle import _club_cycle_fixture

    state, pool, _ = _club_cycle_fixture(RULES)
    planner = StrategicPlannerV3(
        RULES, replace(StrategicPlannerV3Config(), max_transfers_per_action=5)
    )
    outgoing = tuple(next(p for p in state.players if p.position == pos) for pos in order)
    incoming = tuple(pool[f"cycle-{pos}"] for pos in order)
    assert planner._make_action(state, outgoing, incoming) is not None
    assert all(
        planner._make_action(state, (out,), (into,)) is None
        for out, into in zip(outgoing, incoming)
    )
