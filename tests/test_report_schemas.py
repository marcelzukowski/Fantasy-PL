from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path

import pytest

from fpl_engine.planning.context import PLANNING_CONTEXT_SCHEMA, PlanningContext
from desktop_app.run_center import discover_analysis_runs, verify_analysis_report_references, write_analysis_run
from desktop_app.state import DesktopSquadState

from fpl_engine.reports import (
    AnalysisManifestV2, ChipReportV2, DecisionReportV2, ReportIntegrityError,
    ReportReference, ReportSchemaError, ReportStatus, StrategyPreview,
    UnsupportedReportSchemaVersion, parse_analysis_manifest, parse_chip_report,
    parse_decision_report,
)


AT = datetime(2026, 9, 10, 10, tzinfo=timezone.utc)


def _context() -> PlanningContext:
    ids = tuple(f"p{index}" for index in range(15))
    return PlanningContext(
        schema_version=PLANNING_CONTEXT_SCHEMA, season="2026/27", gameweek=6,
        deadline=AT.isoformat(), player_ids=ids,
        selling_prices_tenths=tuple((player_id, 50) for player_id in ids),
        bank_tenths=10, free_transfers=2, chips_used=(("wildcard_h1", False),),
        projection_run_id="run-a", prediction_timestamp=AT.isoformat(),
        simulator_version="fixture_simulator_v22", model_versions=("events_v22", "minutes_v1"),
        simulation_count=512, optimizer_rule_version=1, scoring_rule_version=1,
        manifest_sha256="a" * 64, artifact_hashes=(("minutes", "b" * 64),),
        fpl_sync_timestamp=AT.isoformat(), source_state_timestamp=AT.isoformat(), data_freshness=(),
    )


def _preview(strategy_key: str) -> dict:
    return {
        "transfers_out": [], "transfers_in": [], "resulting_bank": 10,
        "free_transfers_after": 3, "starting_xi": [f"p{index}" for index in range(11)],
        "bench_order": [f"p{index}" for index in range(11, 15)],
        "captain": "p0", "vice_captain": "p1",
    }


def _decision(context: PlanningContext | None = None) -> DecisionReportV2:
    context = context or _context()
    return DecisionReportV2.create(
        report_id="decision-a", created_at=AT, planning_context=context, mode="ADVISORY / READ ONLY",
        external_mutations=[], shadow_report="reports/shadow.json",
        recommendation={"roll_free_transfer": True, "transfers_out": [], "transfers_in": []},
        feasible_plans=[{"roll_free_transfer": True, "transfers_out": [], "transfers_in": [], "transfer_impacts": {"impact_1gw": 0.0}}],
        strategic_v2={"action": "ROLL_FT", "transfers_out": [], "transfers_in": []},
        strategic_v3={"current_action": {"action": "HOLD", "transfers_out": [], "transfers_in": []}, "path": []},
        strategic_v3_error=None,
        strategy_previews={"short_term": _preview("short_term"), "balanced": _preview("balanced")},
        strategy_preview_identities={}, strategy_unavailable={}, player_metadata={"p0": {"name": "Player 0"}},
    )


def _chip(context: PlanningContext, decision_hash: str = "c" * 64) -> ChipReportV2:
    return ChipReportV2.create(
        report_id="chip-a", created_at=AT, planning_context=context,
        decision_report_path="reports/decision.json", decision_report_sha256=decision_hash,
        mode="ADVISORY / READ ONLY", external_mutations=[],
        recommendation={"chip": None, "available_chips": ["free_hit"]}, evaluations={},
        strategic={"simulations_per_fixture": 3000}, chip_period={"end_gameweek": 19},
        timing_policy_version="exact-v1", candidate_generation={"count": 1},
    )


def test_decision_round_trip_is_deterministic_and_keeps_v3_and_duplicate_slots():
    report = _decision()
    left = report.to_dict()
    right = parse_decision_report(left)
    assert right.to_dict() == left
    assert parse_decision_report(right.to_dict()).to_dict() == left
    assert right.context_id == report.context_id
    assert right.v3_result is not None and right.v3_result.to_dict() == report.v3_result.to_dict()
    assert right.preview_for("short_term").plan_id == right.preview_for("balanced").plan_id
    assert right.preview_for("short_term").strategy_key != right.preview_for("balanced").strategy_key


def test_decision_rejects_unknown_version_and_malformed_preview():
    raw = _decision().to_dict()
    raw["schema_version"] = "decision_report_v999"
    with pytest.raises(UnsupportedReportSchemaVersion, match="Unsupported report schema version"):
        parse_decision_report(raw)
    raw = _decision().to_dict()
    raw["strategy_previews"][0]["starting_xi"] = ["p0"] * 11
    with pytest.raises(ReportSchemaError, match="starting_xi"):
        parse_decision_report(raw)


def test_chip_round_trip_preserves_context_hash_and_statuses():
    context = _context()
    report = _chip(context)
    parsed = parse_chip_report(report.to_dict())
    assert parsed.to_dict() == report.to_dict()
    assert parsed.context_id == context.context_id
    assert parsed.decision_report_sha256 == "c" * 64
    assert parsed.status is ReportStatus.COMPLETE
    partial = report.to_dict(); partial["status"] = "PARTIAL"; partial["decision_report_sha256"] = None
    assert parse_chip_report(partial).status is ReportStatus.PARTIAL
    cancelled = report.to_dict(); cancelled["status"] = "CANCELLED"; cancelled["decision_report_sha256"] = None
    assert parse_chip_report(cancelled).status is ReportStatus.CANCELLED


def test_analysis_round_trip_references_and_context_match():
    context = _context(); decision = _decision(context); decision_hash = sha256(json.dumps(decision.to_dict(), sort_keys=True).encode()).hexdigest()
    chip = _chip(context, decision_hash)
    manifest = AnalysisManifestV2.create(
        analysis_run_id="analysis-a", created_at=AT, status="COMPLETE", season="2026/27", gameweek=6,
        projection_run_id="run-a", decision_report=decision,
        decision_reference=ReportReference("data/decision.json", decision_hash), chip_report=chip,
        chip_reference=ReportReference("data/chip.json", "d" * 64), recommended_xi_available=True,
        captaincy_available=True, display_state={"player_ids": [f"p{index}" for index in range(15)]},
    )
    parsed = parse_analysis_manifest(manifest.to_dict())
    assert parsed.to_dict() == manifest.to_dict()
    assert parsed.chip_report is not None and parsed.chip_report.sha256 == "d" * 64


def test_analysis_rejects_context_and_decision_hash_mismatch():
    context = _context(); decision = _decision(context)
    with pytest.raises(ReportIntegrityError):
        AnalysisManifestV2.create(
            analysis_run_id="analysis-a", created_at=AT, status="COMPLETE", season="2026/27", gameweek=6,
            projection_run_id="run-a", decision_report=decision,
            decision_reference=ReportReference("data/decision.json", "a" * 64),
            chip_report=_chip(context, "b" * 64), chip_reference=ReportReference("data/chip.json", "c" * 64),
            recommended_xi_available=True, captaincy_available=True, display_state=None,
        )


def test_legacy_reports_do_not_fabricate_context_or_v3_identity():
    legacy = parse_decision_report({"recommendation": {"transfers_out": [], "transfers_in": []}})
    assert legacy.legacy_unverified
    assert legacy.context_id is None and legacy.v3_result is None
    legacy_manifest = parse_analysis_manifest({
        "analysis_manifest_version": 2, "analysis_run_id": "old", "projection_run_id": "old-run",
        "season": "2026/27", "gameweek": 6, "timestamp": AT.isoformat(), "status": "PARTIAL",
        "decision_report": "data/old.json", "chip_report": None, "squad_state": {"season": "2026/27"},
    })
    assert legacy_manifest.legacy_unverified
    assert legacy_manifest.context_id is None


def test_strategy_preview_identity_rejects_mismatched_plan():
    payload = _preview("short_term")
    payload["plan_id"] = "plan_wrong"
    with pytest.raises(ReportSchemaError, match="plan identity"):
        StrategyPreview.from_dict("short_term", payload)


def test_persisted_analysis_rejects_tampered_decision_bytes(tmp_path):
    context = _context(); decision = _decision(context)
    state = DesktopSquadState(
        season=context.season, gameweek=context.gameweek, bank_tenths=context.bank_tenths,
        free_transfers=context.free_transfers, player_ids=list(context.player_ids),
        selling_prices_tenths=dict(context.selling_prices_tenths),
        purchase_prices_tenths=dict(context.selling_prices_tenths), chips_used=dict(context.chips_used),
    )
    reports = tmp_path / "data" / "processed" / "reports"; reports.mkdir(parents=True)
    decision_path = reports / "decision.json"
    decision_path.write_text(json.dumps(decision.to_dict(), sort_keys=True), encoding="utf-8")
    chip = _chip(context, sha256(decision_path.read_bytes()).hexdigest())
    chip_path = reports / "chip.json"
    chip_path.write_text(json.dumps(chip.to_dict(), sort_keys=True), encoding="utf-8")
    write_analysis_run(
        tmp_path, analysis_run_id="analysis-a", projection_run_id=context.projection_run_id,
        state=state, status="COMPLETE", decision_report=decision_path, chip_report=chip_path,
        recommended_xi_available=True, captaincy_available=True,
    )
    loaded = discover_analysis_runs(tmp_path, season=context.season, gameweek=context.gameweek)[0]
    verify_analysis_report_references(tmp_path, loaded)
    decision_path.write_text(decision_path.read_text(encoding="utf-8") + " ", encoding="utf-8")
    with pytest.raises(Exception, match="integrity check"):
        verify_analysis_report_references(tmp_path, loaded)


def test_context_tampering_is_rejected_at_decision_boundary():
    raw = _decision().to_dict()
    raw["context_id"] = "f" * 64
    with pytest.raises(ReportSchemaError, match="planning_context"):
        parse_decision_report(raw)
