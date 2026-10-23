"""Reduced native legality and boundary checks for V3-anchored neighborhoods."""

from types import SimpleNamespace

from hypothesis import given, strategies as st
import pytest

from fpl_engine.optimizer import OptimizerRules
from fpl_engine.strategy.strategic_planner_v3 import StrategicPlannerV3, StrategicPlannerV3Config
from scripts.diagnostics import cpsat_phase2b_candidates
from scripts.diagnostics.v3_challenger_oracle import _club_cycle_fixture
from scripts.diagnostics.v3_multi_transfer_oracle import ROOT, _fixture


RULES = OptimizerRules.load(ROOT)


def _anchor(state, pool):
    indices = (0, 2)
    out = sorted(state.players[index].player_id for index in indices)
    incoming = sorted(("incoming-gk", "incoming-def"))
    assert StrategicPlannerV3(RULES)._make_action(
        state,
        tuple(state.players[index] for index in indices),
        tuple(pool[player_id] for player_id in incoming),
    )
    return {"transfers_out": out, "transfers_in": incoming, "v3_objective": 10.0}


def test_reduced_real_worker_returns_bounded_native_legal_neighborhoods():
    state, pool, projections = _fixture(71, RULES)
    shared = SimpleNamespace(
        state=state,
        player_pool=tuple(pool.values()),
        projections=projections,
        rules=RULES,
        context_id="phase2b-reduced",
    )
    anchors = [_anchor(state, pool)]
    result = cpsat_phase2b_candidates.generate_neighborhoods(
        shared, anchors, time_limit_seconds=0.05
    )
    repeated = cpsat_phase2b_candidates.generate_neighborhoods(
        shared, anchors, time_limit_seconds=0.05
    )
    assert result["api_version"] == "cpsat_phase2b_neighborhoods_v1"
    assert result["context_id"] == "phase2b-reduced"
    assert result["candidates"]
    assert len(result["candidates"]) <= 72
    assert all(3 <= len(p["transfers_in"]) <= 5 for p in result["candidates"])
    assert all(p["native_legality"] == "PASS" for p in result["candidates"])
    assert all(p["anchor_v3_objective"] == 10.0 for p in result["candidates"])
    assert result["candidates"] == repeated["candidates"]
    assert len(result["attempts"]) <= 15
    assert all(
        p["free_transfers_after"]
        == result["problem"]["accounting_by_k"][str(p["k"])]["free_transfers_after"]
        for p in result["candidates"]
    )
    assert all(
        a["status"] in {"OPTIMAL", "FEASIBLE", "INFEASIBLE", "UNKNOWN", "MODEL_INVALID"}
        for a in result["attempts"]
    )


def test_cell_eligibility_explains_structural_misses():
    candidate = {
        "transfers_out": ["o1", "o3", "o4"],
        "transfers_in": ["i1", "i2", "i3"],
        "positions": {"i1": "MID", "i2": "DEF", "i3": "FWD"},
    }
    anchor = {"transfers_out": ["o1", "o2"], "transfers_in": ["i1", "i2"]}
    assert cpsat_phase2b_candidates.explain_cell_eligibility(
        candidate, anchor, target_k=3, position="FWD"
    )["eligible"]
    missed = cpsat_phase2b_candidates.explain_cell_eligibility(
        candidate, anchor, target_k=3, position="GK"
    )
    assert not missed["eligible"]
    assert "no_new_incoming_at_position:GK" in missed["cuts"]


def test_rejects_nonfinite_anchor_objective():
    with pytest.raises(ValueError, match="anchor objective"):
        cpsat_phase2b_candidates.validate_anchors(
            [
                {
                    "transfers_out": ["o1", "o2"],
                    "transfers_in": ["i1", "i2"],
                    "v3_objective": float("nan"),
                }
            ]
        )


@given(st.lists(st.text(min_size=1, max_size=8), min_size=2, max_size=2, unique=True))
def test_hypothesis_accepts_canonical_k2_anchor_ids(ids):
    assert cpsat_phase2b_candidates.validate_anchors(
        [
            {
                "transfers_out": sorted("out-" + value for value in ids),
                "transfers_in": sorted("in-" + value for value in ids),
                "v3_objective": 0.0,
            }
        ]
    )


def test_native_atomic_k4_rotation_can_be_legal_without_legal_prefixes():
    state, pool, _ = _club_cycle_fixture(RULES)
    indices = (0, 2, 7, 12)
    outgoing = tuple(state.players[index] for index in indices)
    incoming = tuple(pool[f"cycle-{position}"] for position in ("GK", "DEF", "MID", "FWD"))
    planner = StrategicPlannerV3(RULES, StrategicPlannerV3Config(max_transfers_per_action=5))
    assert planner._make_action(state, outgoing, incoming)
    assert all(
        planner._make_action(state, outgoing[:count], incoming[:count]) is None
        for count in range(1, 4)
    )
