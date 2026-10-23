"""Fast synthetic typed-report/UI smoke; never runs projections or writes account state."""
from __future__ import annotations

from datetime import datetime, timezone
from dataclasses import replace
import json
from pathlib import Path

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtGui import QFontDatabase, QFont

from desktop_app.data_access import PlayerRecord
from desktop_app.main_window import MainWindow
from desktop_app.recommended_lineup import build_recommended_lineup
from desktop_app.squad_pitch import StrategyLineupPreview
from desktop_app.state import DesktopSquadState, default_chip_state
from fpl_engine.models.projections import GameweekPlayerProjection, PlayerProjection
from fpl_engine.optimizer import ChipState, OptimizerRules, SquadPlayer, SquadState, optimize_lineup
from fpl_engine.planning.context import PLANNING_CONTEXT_SCHEMA, PlanningContext
from fpl_engine.reports import DecisionReportV2, plan_id, parse_decision_report
from fpl_engine.strategy.strategic_planner_v3 import StrategicPlannerV3, StrategicPlannerV3Config, StrategicPath, StrategicPlannerV3Result


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "scratch" / "v3_portfolio_20261022"
AT = datetime(2026, 10, 22, 10, tzinfo=timezone.utc)


def _optimizer_projection(player_id: str, value: float, *, season: str, rule_version: int) -> PlayerProjection:
    gameweek = GameweekPlayerProjection(
        season, rule_version, player_id, 8, AT, (f"synthetic-fixture-{player_id}",), 1,
        value, value, 1.0, {0.5: value}, .2, .5, .4, .2, .1, .05,
        80.0, {int(value): 1.0}, 1.0,
    )
    return PlayerProjection(
        player_id, season, rule_version, AT, 8, tuple(replace(gameweek,target_gameweek=8+i) for i in range(3)), value, 3*value, 3*value,
        value, 3*value, 3*value, 80.0, 240.0, 240.0, .2, .8, 1.0,
        ("synthetic",), ("synthetic",), ("synthetic",), ("synthetic",), (1,), (1,),
    )


def make_synthetic(case: int, *, free_transfers=None):
    """Build K3/K4/K5 synthetic portfolio shapes with stable full IDs."""
    positions = ["GK"] * 2 + ["DEF"] * 5 + ["MID"] * 5 + ["FWD"] * 3
    owned = []
    position_index = {key: 0 for key in ("GK", "DEF", "MID", "FWD")}
    for position in positions:
        i = position_index[position]
        position_index[position] += 1
        owned.append(f"SYNTH_2026_{position}_{i:02d}_FULL")
    pool: dict[str, PlayerRecord] = {}
    for index, (player_id, position) in enumerate(zip(owned, positions)):
        pool[player_id] = PlayerRecord(player_id, f"Synthetic Owned {position} {index:02d}", position, f"CLUB_{index:02d}", 50)
    # Three FWD, then add legal DEF/MID replacements to cover four- and five-transfer shapes.
    outs_by_case = {
        3: (owned[12], owned[13], owned[14]),
        4: (owned[4], owned[9], owned[12], owned[13]),
        5: (owned[3], owned[4], owned[8], owned[12], owned[13]),
    }
    outgoing = outs_by_case[case]
    incoming = []
    for index, out_id in enumerate(outgoing):
        position = pool[out_id].position
        player_id = f"SYNTH_2026_{position}_IN_{case}_{index}_COMPLETE_ID"
        incoming.append(player_id)
        pool[player_id] = PlayerRecord(player_id, f"Synthetic Incoming {position} {case}-{index} Complete Name", position, f"NEW_CLUB_{case}_{index}", 50)
    result = [player for player in owned if player not in outgoing] + incoming
    state = DesktopSquadState(
        season="2026/27", gameweek=8, bank_tenths=20, free_transfers=case if free_transfers is None else free_transfers,
        player_ids=owned, chips_used=default_chip_state(),
        selling_prices_tenths={key: 50 for key in owned}, purchase_prices_tenths={key: 50 for key in owned},
    )
    # Build complete native paths; previews retain the optimizer's actual choices.
    rules = OptimizerRules.load(ROOT)
    optimizer_state = SquadState(
        players=tuple(SquadPlayer(key, pool[key].position, pool[key].team_id, 50, 50, 50) for key in owned),
        bank=state.bank_tenths, free_transfers=state.free_transfers, chips=ChipState(),
        current_gameweek=state.gameweek, season=rules.season, rule_version=rules.version,
        prediction_timestamp=AT,
    )
    projections = {
        key: _optimizer_projection(key, 2.0+(index%13) if key in owned else 20.0+index, season=rules.season, rule_version=rules.version)
        for index, key in enumerate(pool)
    }
    native_pool={key:SquadPlayer(key,p.position,p.team_id,50,50,50) for key,p in pool.items()}
    planner=StrategicPlannerV3(rules,replace(StrategicPlannerV3Config(),max_transfers_per_action=5))
    first=planner._make_action(optimizer_state,tuple(native_pool[x] for x in sorted(outgoing)),tuple(native_pool[x] for x in sorted(incoming)))
    assert first is not None
    def simulate(initial):
        current=optimizer_state
        steps=[]
        for offset in range(3):
            selected=initial if not offset else next(a for a in planner._actions_for_state(current,native_pool,projections,target_gameweek=current.current_gameweek) if a.is_hold)
            current,step=planner._evaluate_action(current,selected,native_pool,projections,target_gameweek=current.current_gameweek,signals=None,offset=offset)
            steps.append(step)
        points=sum(s.points_after_hit for s in steps)
        terminal=planner._terminal_ft_value(current)
        return StrategicPath(tuple(steps),points,terminal,points+terminal)
    transfer_path=simulate(first)
    hold_path=simulate(next(a for a in planner._actions_for_state(optimizer_state,native_pool,projections,target_gameweek=8) if a.is_hold))
    assert transfer_path.total_path_value>hold_path.total_path_value
    optimized=transfer_path.steps[0]
    starters=optimized.starting_xi
    bench=optimized.bench_order
    assert len(starters) == 11 and len(bench) == 4
    assert len(result) == 15 and len(set(result)) == 15
    assert all(pool[player].position for player in result)
    cap, vice = optimized.captain_id, optimized.vice_captain_id
    preview = {
        "transfers_out": list(outgoing), "transfers_in": incoming,
        "resulting_bank": state.bank_tenths, "free_transfers_after": 1,
        "starting_xi": list(starters), "bench_order": list(bench),
        "captain": cap, "vice_captain": vice,
    }
    # This synthetic advisory context is deliberately not a production run identity.
    context = PlanningContext(
        schema_version=PLANNING_CONTEXT_SCHEMA, season=state.season, gameweek=state.gameweek,
        deadline=AT.isoformat(), player_ids=tuple(owned),
        selling_prices_tenths=tuple((key, 50) for key in owned), bank_tenths=state.bank_tenths,
        free_transfers=state.free_transfers, chips_used=(("wildcard_h1", False),),
        projection_run_id=f"SYNTHETIC-K{case}", prediction_timestamp=AT.isoformat(),
        simulator_version="SYNTHETIC_DIAGNOSTIC", model_versions=("synthetic",), simulation_count=1,
        optimizer_rule_version=1, scoring_rule_version=1, manifest_sha256="a" * 64,
        artifact_hashes=(("synthetic", "b" * 64),), fpl_sync_timestamp=AT.isoformat(),
        source_state_timestamp=AT.isoformat(), data_freshness=(),
    )
    action = {
        "action": "TRANSFER", "transfers_out": list(outgoing), "transfers_in": incoming,
        "transfers_used": case, "hit_cost_points": max(0, case - state.free_transfers) * 4,
        "resulting_bank": state.bank_tenths, "free_transfers_before": state.free_transfers,
        "free_transfers_after": 1,
    }
    strategic=StrategicPlannerV3Result(transfer_path,hold_path,{},hold_path).as_dict()
    typed = DecisionReportV2.create(
        report_id=f"synthetic-k{case}", created_at=AT, planning_context=context,
        mode="SYNTHETIC DIAGNOSTIC / READ ONLY", external_mutations=[], shadow_report=None,
        recommendation={"transfers_out": list(outgoing), "transfers_in": incoming, "roll_free_transfer": False},
        feasible_plans=[{"transfers_out": list(outgoing), "transfers_in": incoming,
                         "resulting_bank": state.bank_tenths, "free_transfers_after": 1,
                         "transfers_used": case, "hit_cost_points": action["hit_cost_points"],
                         "transfer_impacts": {"impact_1gw": 3.0, "impact_3gw": 8.0, "impact_6gw": 14.0}}],
        strategic_v2={"action": "TRANSFER", **action}, strategic_v3=strategic,
        strategic_v3_error=None,
        strategy_previews={key: preview for key in ("strategic", "short_term", "balanced", "long_term")},
        strategy_preview_identities={key: {"plan_id": plan_id(tuple(outgoing), tuple(incoming))} for key in ("strategic", "short_term", "balanced", "long_term")},
        strategy_unavailable={}, player_metadata={key: {"name": player.display_name} for key, player in pool.items()},
    )
    parsed = parse_decision_report(typed.to_dict())
    lineup = build_recommended_lineup(state, pool, parsed.preview_for("strategic").lineup_payload())
    assert set(lineup.transfers_out) == set(outgoing) and set(lineup.transfers_in) == set(incoming)
    assert len(lineup.starting_xi_ids) == 11 and len(lineup.bench_ids) == 4
    assert lineup.captain_id == cap and lineup.vice_captain_id == vice
    return state, pool, parsed, lineup


def run_audit() -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    for filename in ('segoeui.ttf','segoeuib.ttf','arial.ttf'):
        QFontDatabase.addApplicationFont(str(Path('C:/Windows/Fonts')/filename))
    app.setFont(QFont('Segoe UI',10))
    results = []
    window = MainWindow(ROOT)
    window.show()
    for case in (3, 4, 5):
        window.tabs.setCurrentIndex(0)
        state, players, report, lineup = make_synthetic(case)
        window.players = players
        window._current_state = state
        window.pitch_widget.refresh(window.player_boxes, players, state=state, first_gameweek=state.gameweek)
        window._render_strategic_action(report, state)
        window.pitch_widget.set_strategy_recommendations(
            {"strategic": StrategyLineupPreview(
                lineup.starting_xi_ids, lineup.bench_ids, lineup.captain_id,
                lineup.vice_captain_id, lineup.transfers_out, lineup.transfers_in,
                "V3 TRANSFER",
            )}, players=players, fixture_repository=window.fixture_repository,
            active_strategy="strategic", first_gameweek=state.gameweek,
        )
        window.pitch_widget._show_strategy("strategic")
        window._render_captaincy_result(
            preview=window.pitch_widget._strategy_previews["strategic"], players=players,
            fixtures=window.fixture_repository, recommendation={}, first_gameweek=state.gameweek,
        )
        app.processEvents()
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        app.processEvents()
        transfer_text = window.pitch_widget.out_label.text() + " | " + window.pitch_widget.in_label.text()
        assert all(player.display_name in transfer_text for player in (players[key] for key in lineup.transfers_out + lineup.transfers_in))
        strategic_text = window.analysis_strategic_summary.text()
        assert all(players[key].display_name in strategic_text for key in lineup.transfers_out + lineup.transfers_in)
        assert f"Transfers used: {case}" in strategic_text
        assert "Hit: 0 pts" in strategic_text
        assert f"Free transfers: {case} -> 1 next GW" in strategic_text
        captaincy_text = window.analysis_captain_summary.text()
        assert f"Captain: {players[lineup.captain_id].display_name}" in captaincy_text
        assert f"Vice-captain: {players[lineup.vice_captain_id].display_name}" in captaincy_text
        cards = window.pitch_widget.findChildren(__import__("desktop_app.squad_pitch", fromlist=["PlayerCard"]).PlayerCard)
        card_ids = [card.player_id for card in cards]
        assert len([key for key in lineup.starting_xi_ids if key in card_ids]) == 11
        assert len([key for key in lineup.bench_ids if key in card_ids]) == 4
        assert "C" in next(card.meta.text() for card in cards if card.player_id == lineup.captain_id)
        assert "VC" in next(card.meta.text() for card in cards if card.player_id == lineup.vice_captain_id)
        for incoming_id in lineup.transfers_in:
            card = next(card for card in cards if card.player_id == incoming_id)
            assert card.findChildren(__import__("PySide6.QtWidgets", fromlist=["QLabel"]).QLabel, "TransferIn")
        assert "alternative" in window.analysis_strategic_summary.text()
        window.grab().save(str(OUT / f"ui_k{case}.png"))
        transfer_geometry={name:{'available_width':label.width(),
            'unwrapped_text_width':label.fontMetrics().horizontalAdvance(label.text()),
            'word_wrap':label.wordWrap()}
            for name,label in (('out',window.pitch_widget.out_label),('in',window.pitch_widget.in_label))}
        window.tabs.setCurrentIndex(1)
        app.processEvents()
        window.grab().save(str(OUT / f"ui_analysis_k{case}.png"))
        payload = report.to_dict()
        (OUT / f"ui_k{case}.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
        results.append({"case": f"K{case}", "status": "PASS", "transfers_out": list(lineup.transfers_out),
                        "transfers_in": list(lineup.transfers_in), "plan_id": report.preview_for("strategic").plan_id,
                        "xi": len(lineup.starting_xi_ids), "bench": len(lineup.bench_ids),
                        "captain": lineup.captain_id, "vice_captain": lineup.vice_captain_id,
                        "lineup_source": "fpl_engine.optimizer.optimize_lineup",
                        "transfer_geometry":transfer_geometry,
                        "gap":"Squad transfer bar and Analysis IN row clip long K3/K4/K5 names; data IDs remain complete",
                        "report_context": "SYNTHETIC_DIAGNOSTIC"})
    window.close()
    output = {"scope": "synthetic UI contract audit only", "production_integration": False, "cases": results}
    (OUT / "ui_audit.log").write_text(json.dumps(output, indent=2), encoding="utf-8")
    return output


if __name__ == "__main__":
    print(json.dumps(run_audit(), indent=2))
