from desktop_app.transfer_plans import horizon_transfer_plans, top_feasible_transfer_plans
from desktop_app.main_window import MainWindow


def _report():
    return {
        "recommendation": {
            "transfers_out": ["out_a"], "transfers_in": ["in_a"],
            "hit_cost": 0, "net_projected_gain": 2.5, "resulting_bank": 12,
            "free_transfers_before": 1,
            "transfer_impacts": {"impact_1gw": 1.0, "impact_3gw": 2.0, "impact_6gw": 3.0},
        },
        "feasible_plans": [
            {"transfers_out": ["out_a"], "transfers_in": ["in_a"], "resulting_bank": 12},
            {"transfers_out": ["out_b"], "transfers_in": ["in_b"], "hit_cost": 0, "net_gain": 1.5, "resulting_bank": 10, "free_transfers_used": 1, "impact_1gw": 4.0, "impact_3gw": 1.5, "impact_6gw": 2.5},
            {"transfers_out": ["out_c", "out_d"], "transfers_in": ["in_c", "in_d"], "hit_cost": 4, "net_gain": 1.0, "resulting_bank": 0, "free_transfers_used": 1, "impact_1gw": .2, "impact_3gw": 5.0, "impact_6gw": 2.2},
            {"transfers_out": ["out_e"], "transfers_in": ["in_e"], "hit_cost": 0, "resulting_bank": 1, "impact_1gw": .1, "impact_3gw": 1.2, "impact_6gw": 6.0},
            {"transfers_out": ["bad"], "transfers_in": ["invalid"], "hit_cost": 0, "resulting_bank": -1},
        ],
    }


def test_horizon_plans_use_comparable_impacts_for_each_independent_horizon():
    first = horizon_transfer_plans(_report())
    second = horizon_transfer_plans(_report())

    assert first == second
    assert [item.title for item in first] == ["Best short-term", "Best balanced", "Best long-term"]
    assert [item.horizon_label for item in first] == ["Impact 1GW", "Impact 3GW", "Impact 6GW"]
    assert [item.plan.transfers_in for item in first] == [("in_b",), ("in_c", "in_d"), ("in_e",)]
    assert [item.impact for item in first] == [4.0, 5.0, 6.0]
    assert all(item.plan.resulting_bank is None or item.plan.resulting_bank >= 0 for item in first)


def test_horizon_plans_allow_one_existing_plan_to_win_multiple_horizons():
    report = _report()
    report["feasible_plans"][1]["impact_1gw"] = 4.0
    report["feasible_plans"][1]["impact_3gw"] = 7.0
    report["feasible_plans"][1]["impact_6gw"] = 8.0

    plans = horizon_transfer_plans(report)

    assert [item.plan.transfers_in for item in plans] == [("in_b",), ("in_b",), ("in_b",)]
    assert [item.impact for item in plans] == [4.0, 7.0, 8.0]


def test_duplicate_horizon_transfer_sets_keep_independent_slots_and_order_insensitive_identity():
    report = _report()
    report["feasible_plans"][1]["impact_1gw"] = 9.0
    report["feasible_plans"][1]["impact_3gw"] = 9.0
    report["feasible_plans"][1]["impact_6gw"] = 1.0
    plans = horizon_transfer_plans(report)

    assert plans[0].plan.key == plans[1].plan.key
    assert plans[2].plan.key != plans[0].plan.key
    identities = {
        key: MainWindow._transfer_identity(plan.plan)
        for key, plan in zip(("short_term", "balanced", "long_term"), plans)
    }
    assert set(identities) == {"short_term", "balanced", "long_term"}
    assert identities["short_term"] == identities["balanced"]
    assert identities["long_term"] != identities["balanced"]
    reversed_payload = {
        "transfers_out": list(reversed(plans[1].plan.transfers_out)),
        "transfers_in": list(reversed(plans[1].plan.transfers_in)),
    }
    assert MainWindow._same_transfers(plans[1].plan, reversed_payload)
    assert MainWindow._same_plan_identity(plans[0].plan, identities["short_term"])
    assert MainWindow._same_plan_identity(plans[1].plan, identities["balanced"])
    assert MainWindow._same_plan_identity(plans[2].plan, identities["long_term"])
    assert not MainWindow._same_plan_identity(plans[2].plan, identities["balanced"])


def test_compatibility_accessor_retains_only_distinct_engine_validated_plans():
    plans = top_feasible_transfer_plans(_report())

    assert [plan.transfers_in for plan in plans] == [("in_a",), ("in_b",), ("in_c", "in_d")]
    assert all(plan.resulting_bank is None or plan.resulting_bank >= 0 for plan in plans)
