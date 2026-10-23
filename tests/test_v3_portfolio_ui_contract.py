from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "diagnostics" / "v3_portfolio_ui_audit.py"
SPEC = importlib.util.spec_from_file_location("v3_portfolio_ui_audit", SCRIPT)
AUDIT = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(AUDIT)


def test_synthetic_k3_k4_k5_typed_reports_render_complete_portfolios():
    result = AUDIT.run_audit()
    assert [case["case"] for case in result["cases"]] == ["K3", "K4", "K5"]
    for case in result["cases"]:
        assert case["status"] == "PASS"
        assert len(case["transfers_out"]) == len(case["transfers_in"]) == int(case["case"][1:])
        assert case["plan_id"].startswith("plan_")
        assert (case["xi"], case["bench"]) == (11, 4)
        assert case["captain"] != case["vice_captain"]
        assert case["report_context"] == "SYNTHETIC_DIAGNOSTIC"
    for case in (3, 4, 5):
        assert (AUDIT.OUT / f"ui_k{case}.png").is_file()
        assert (AUDIT.OUT / f"ui_k{case}.json").is_file()


def test_paid_k5_hit_and_ft_render_from_native_reconstructed_path():
    from PySide6.QtWidgets import QApplication
    app=QApplication.instance() or QApplication([])
    state,players,report,_=AUDIT.make_synthetic(5,free_transfers=2)
    payload=report.v3_result.to_dict()
    assert payload['current_action']['hit_cost_points']==12
    assert payload['current_action']['free_transfers_after']==1
    window=AUDIT.MainWindow(AUDIT.ROOT)
    window.players=players
    window._render_strategic_action(report,state)
    app.processEvents()
    text=window.analysis_strategic_summary.text()
    assert 'Hit: 12 pts' in text
    assert 'Free transfers: 2 -> 1 next GW' in text
    window.close()
