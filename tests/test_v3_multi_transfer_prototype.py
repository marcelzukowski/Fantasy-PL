from dataclasses import replace
from datetime import datetime, timezone
import pytest

from fpl_engine.models.projections import GameweekPlayerProjection, PlayerProjection
from fpl_engine.optimizer import ChipState, OptimizerRules, SquadPlayer, SquadState, next_free_transfers, validate_squad
from scripts.diagnostics.v3_multi_transfer import generate_actions


ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]
AT = datetime(2026, 9, 20, 10, tzinfo=timezone.utc)


def _projection(player_id, points):
    weeks = tuple(GameweekPlayerProjection(
        "2026/27", 1, player_id, gw, AT, (f"fixture-{gw}",), 1,
        points, points, 1.0, {0.5: points}, .2, .5, .4, .2, .1, .05, 80.0, {int(points): 1.0}, 1.0,
    ) for gw in (6, 7, 8))
    return PlayerProjection(
        player_id, "2026/27", 1, AT, 6, weeks, points, points * 3, points * 3,
        points, points * 3, points * 3, 80.0, 240.0, 240.0, .2, .8, 1.0,
        ("test",), ("test",), ("test",), ("test",), (42,), (1,),
    )


def _inputs(free_transfers=4):
    rules = OptimizerRules.load(ROOT)
    positions = ["GK"] * 2 + ["DEF"] * 5 + ["MID"] * 5 + ["FWD"] * 3
    owned = tuple(SquadPlayer(f"o{i}", pos, f"owned-club-{i}", 50, 50, 50) for i, pos in enumerate(positions))
    pool = {p.player_id: p for p in owned}
    projections = {p.player_id: _projection(p.player_id, 4.0) for p in owned}
    incoming_positions = ("GK", "DEF", "MID", "FWD")
    for pos in incoming_positions:
        for i in range(8):
            player = SquadPlayer(f"{pos.lower()}-in-{i}", pos, f"new-{pos}-{i}", 50, 50, 50)
            pool[player.player_id] = player
            projections[player.player_id] = _projection(player.player_id, 10.0 - i / 10)
    state = SquadState(owned, 500, free_transfers, ChipState(), 6, rules.season, rules.version, AT)
    return rules, state, pool, projections


def _assert_legal_actions(actions, state, pool, rules, *, free_transfers):
    assert actions[0].is_hold
    identities = [(action.transfers_out, action.transfers_in) for action in actions]
    assert len(identities) == len(set(identities))
    owned_ids = {p.player_id for p in state.players}
    for action in actions[1:]:
        assert len(set(action.transfers_out)) == len(action.transfers_out) == len(action.transfers_in)
        assert not (set(action.transfers_out) & set(action.transfers_in))
        assert set(action.transfers_out) <= owned_ids
        assert not (set(action.transfers_in) & owned_ids)
        validate_squad(replace(state, players=tuple(pool[p] for p in action.resulting_squad),
                               bank=action.resulting_bank), rules)
        assert action.hit_cost_points == max(0, action.transfers_used - free_transfers) * int(
            rules.value("transfers", "normal_gameweek", "points_cost_per_transfer_above_allowance")
        )


def test_incremental_returns_deterministic_legal_k3_k4_k5_and_paid_fifth_transfer():
    rules, state, pool, projections = _inputs(4)
    stats = {}
    actions = generate_actions(state, pool, projections, rules, max_transfers=5,
                               partial_width=64, max_actions=24, stats=stats)
    second = generate_actions(state, pool, projections, rules, max_transfers=5,
                              partial_width=64, max_actions=24)
    assert actions == second
    _assert_legal_actions(actions, state, pool, rules, free_transfers=4)
    assert {action.transfers_used for action in actions} == {0, 1, 2, 3, 4, 5}
    five = next(a for a in actions if a.transfers_used == 5)
    assert five.hit_cost_points == int(rules.value("transfers", "normal_gameweek", "points_cost_per_transfer_above_allowance"))
    assert stats["legal_by_k"][3] and stats["legal_by_k"][4] and stats["legal_by_k"][5]


def test_compose_strategy_keeps_hold_and_generates_k3_plus():
    rules, state, pool, projections = _inputs(5)
    actions = generate_actions(state, pool, projections, rules, strategy="compose", max_transfers=5,
                               partial_width=64, max_actions=24)
    _assert_legal_actions(actions, state, pool, rules, free_transfers=5)
    assert {3, 4, 5} <= {action.transfers_used for action in actions}


def test_zero_transfer_cap_returns_hold_only():
    rules, state, pool, projections = _inputs(4)
    actions = generate_actions(state, pool, projections, rules, max_transfers=0)
    assert len(actions) == 1 and actions[0].is_hold


@pytest.mark.parametrize("strategy", ("incremental", "compose"))
def test_five_available_free_transfers_have_no_hit_and_use_existing_rollover(strategy):
    rules, state, pool, projections = _inputs(5)
    actions = generate_actions(state, pool, projections, rules, strategy=strategy,
                               max_transfers=5, partial_width=16, max_actions=24)
    assert {a.transfers_used for a in actions} == set(range(6))
    for action in actions:
        assert action.hit_cost_points == 0
        assert action.free_transfers_after == next_free_transfers(5, action.transfers_used, rules)
