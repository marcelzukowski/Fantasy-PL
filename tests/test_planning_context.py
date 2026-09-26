from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path

import pytest

from desktop_app.chip_runner import DesktopChipError, _validate_decision
from desktop_app.decision_runner import _deadline_capture_status
from desktop_app.decision_orchestration import DesktopEngineError, planning_context_for_state, validate_decision_bundle
from desktop_app.state import DesktopSquadState, default_chip_state, planning_state_changed
from desktop_app.run_center import RunCenterError, discover_analysis_runs, write_analysis_run
from fpl_engine.planning import ProjectionArtifactIntegrityError, build_planning_context, context_from_report
from fpl_engine.reports import ChipReportV2, DecisionReportV2


AT = datetime(2026, 9, 10, 10, tzinfo=timezone.utc)
REQUIRED = {
    "prediction_context": "prediction_context.json",
    "shadow_bundle": "shadow_projection_bundle.json",
    "current_players": "current_players.json",
    "fixture_horizon": "fixture_horizon.json",
    "minutes": "minutes.json",
}


def _sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _state(*, reverse: bool = False) -> dict:
    ids = [f"p{index}" for index in range(15)]
    prices = {player_id: 50 + index for index, player_id in enumerate(ids)}
    if reverse:
        ids.reverse()
    return {
        "season": "2026/27",
        "gameweek": 6,
        "player_ids": ids,
        "selling_prices_tenths": prices,
        "purchase_prices_tenths": dict(prices),
        "bank_tenths": 0,
        "free_transfers": 2,
        "chips_used": default_chip_state(),
        "updated_at": AT.isoformat(),
    }


def _run(root: Path, *, run_id: str = "run-a", gameweek: int = 6) -> tuple[Path, dict, dict, dict]:
    run = root / "data" / "processed" / "predictions" / "2026-27" / run_id
    run.mkdir(parents=True)
    bundle = {
        "season": "2026/27", "current_gameweek": gameweek,
        "prediction_timestamp": AT.isoformat(),
        "candidate_pool": [], "projections": [],
        "pipeline": {"simulations_per_fixture": 10_000, "simulator_version": "fixture_simulator_v22"},
        "data_freshness": [{"source": "official_fpl.bootstrap", "known_at": AT.isoformat(), "raw_snapshot_id": "raw-1"}],
    }
    prediction_context = {"target_season": "2026/27", "target_gameweek": gameweek, "deadline": AT.isoformat()}
    files = {
        "shadow_projection_bundle.json": bundle,
        "prediction_context.json": prediction_context,
        "current_players.json": [],
        "fixture_horizon.json": [],
        "minutes.json": [],
    }
    for name, value in files.items():
        (run / name).write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    manifest = {
        "season": "2026/27", "target_gameweek": gameweek,
        "prediction_timestamp": AT.isoformat(),
        "optimizer_rule_version": 1, "scoring_rule_version": 1,
        "model_versions": ["minutes_v1", "events_v22"],
        "simulation": dict(bundle["pipeline"]),
        "artifacts": {
            key: {"path": name, "sha256": _sha(run / name)}
            for key, name in REQUIRED.items()
        },
    }
    (run / "run_manifest.json").write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
    return run / "shadow_projection_bundle.json", bundle, manifest, prediction_context


def _context(root: Path, *, state: dict | None = None, run_id: str = "run-a", gameweek: int = 6):
    bundle_path, bundle, manifest, prediction_context = _run(root, run_id=run_id, gameweek=gameweek)
    value = _state() if state is None else state
    return build_planning_context(
        state=value, bundle_path=bundle_path, bundle=bundle,
        manifest=manifest, prediction_context=prediction_context,
    ), bundle_path, value


def test_context_is_deterministic_and_path_independent(tmp_path):
    left, _, _ = _context(tmp_path / "left", state=_state())
    right, _, _ = _context(tmp_path / "right", state=_state(reverse=True))
    assert left.context_id == right.context_id
    assert left.context_id == left.context_id


@pytest.mark.parametrize("change", [
    "squad", "bank", "free_transfers", "selling_price", "chips", "projection_run", "rule", "gameweek",
])
def test_every_material_planning_field_changes_context_id(tmp_path, change):
    baseline, _, state = _context(tmp_path / "base")
    if change == "projection_run":
        changed, _, _ = _context(tmp_path / "other", run_id="run-b")
    elif change == "rule":
        bundle_path, bundle, manifest, prediction_context = _run(tmp_path / "other")
        manifest["optimizer_rule_version"] = 2
        (bundle_path.parent / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        changed = build_planning_context(state=state, bundle_path=bundle_path, bundle=bundle, manifest=manifest, prediction_context=prediction_context)
    elif change == "gameweek":
        changed_state = deepcopy(state); changed_state["gameweek"] = 7
        changed, _, _ = _context(tmp_path / "other", state=changed_state, gameweek=7)
    else:
        changed_state = deepcopy(state)
        if change == "squad":
            changed_state["player_ids"][0] = "p15"
            changed_state["selling_prices_tenths"]["p15"] = 60
        elif change == "bank":
            changed_state["bank_tenths"] = 1
        elif change == "free_transfers":
            changed_state["free_transfers"] = 1
        elif change == "selling_price":
            changed_state["selling_prices_tenths"]["p0"] = 51
        elif change == "chips":
            changed_state["chips_used"]["wildcard_h1"] = True
        changed, _, _ = _context(tmp_path / "other", state=changed_state)
    assert changed.context_id != baseline.context_id


def test_artifact_mutation_or_missing_file_fails_closed(tmp_path):
    context, bundle_path, state = _context(tmp_path)
    assert context.context_id
    (bundle_path.parent / "minutes.json").write_text("corrupted", encoding="utf-8")
    with pytest.raises(DesktopEngineError, match="minutes hash mismatch"):
        planning_context_for_state(tmp_path, state, bundle_path)
    (bundle_path.parent / "minutes.json").unlink()
    with pytest.raises(DesktopEngineError, match="Projection artifact integrity check failed"):
        validate_decision_bundle(tmp_path, bundle_path, season="2026/27", gameweek=6)


def test_decision_context_matches_chip_and_legacy_reports_are_unverified(tmp_path):
    context, bundle_path, state = _context(tmp_path)
    shadow = tmp_path / "shadow.json"
    shadow.write_text(json.dumps({"season": "2026/27", "current_gameweek": 6, "prediction_timestamp": AT.isoformat(), "external_mutations": []}), encoding="utf-8")
    decision = tmp_path / "decision.json"
    decision.write_text(json.dumps({
        "context_id": context.context_id, "planning_context": context.to_dict(),
        "shadow_report": str(shadow), "external_mutations": [], "recommendation": {},
    }), encoding="utf-8")
    assert _validate_decision(decision, season="2026/27", gameweek=6, prediction_timestamp=AT.isoformat(), context_id=context.context_id)["context_id"] == context.context_id
    with pytest.raises(DesktopChipError, match="current planning context"):
        _validate_decision(decision, season="2026/27", gameweek=6, prediction_timestamp=AT.isoformat(), context_id="0" * 64)
    legacy = {"recommendation": {}, "shadow_report": str(shadow), "external_mutations": []}
    assert context_from_report(legacy) is None


def test_sync_material_change_invalidates_but_reordering_does_not():
    base = DesktopSquadState(**_state())
    reordered = DesktopSquadState(**_state(reverse=True))
    assert not planning_state_changed(base, reordered)
    changed = DesktopSquadState(**_state())
    changed.free_transfers = 1
    assert planning_state_changed(base, changed)


def test_analysis_manifest_cross_checks_decision_and_chip_context_ids(tmp_path):
    context, _, state_mapping = _context(tmp_path)
    state = DesktopSquadState(**state_mapping)
    reports = tmp_path / "data" / "processed" / "reports"
    reports.mkdir(parents=True)
    decision = reports / "decision.json"
    decision_report = DecisionReportV2.create(
        report_id="decision", created_at=AT, planning_context=context, mode="READ ONLY",
        external_mutations=[], shadow_report=None, recommendation={}, feasible_plans=[],
        strategic_v2={}, strategic_v3=None, strategic_v3_error=None,
        strategy_previews={}, strategy_preview_identities={}, strategy_unavailable={}, player_metadata={},
    )
    decision.write_text(json.dumps(decision_report.to_dict(), sort_keys=True), encoding="utf-8")
    chip = reports / "chip.json"
    chip_report = ChipReportV2.create(
        report_id="chip", created_at=AT, planning_context=context, decision_report_path=str(decision),
        decision_report_sha256=_sha(decision), mode="READ ONLY", external_mutations=[], recommendation={"available_chips": []},
        evaluations={}, strategic={}, chip_period={}, timing_policy_version="v1", candidate_generation={},
    )
    chip.write_text(json.dumps(chip_report.to_dict(), sort_keys=True), encoding="utf-8")
    manifest = write_analysis_run(
        tmp_path, analysis_run_id="verified", projection_run_id="run-a", state=state,
        status="COMPLETE", decision_report=decision, chip_report=chip,
        recommended_xi_available=True, captaincy_available=True,
    )
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert payload["context_id"] == context.context_id
    discovered = discover_analysis_runs(tmp_path, season="2026/27", gameweek=6)
    assert discovered[0].context_id == context.context_id and not discovered[0].legacy_unverified

    chip_payload = json.loads(chip.read_text(encoding="utf-8"))
    chip_payload["context_id"] = "f" * 64
    chip.write_text(json.dumps(chip_payload), encoding="utf-8")
    with pytest.raises(RunCenterError):
        write_analysis_run(
            tmp_path, analysis_run_id="mixed", projection_run_id="run-a", state=state,
            status="COMPLETE", decision_report=decision, chip_report=chip,
            recommended_xi_available=True, captaincy_available=True,
        )



def test_verified_official_deadline_propagates_to_context_changes_identity_and_tampering_fails(tmp_path):
    bundle_path, bundle, manifest, prediction_context = _run(tmp_path)
    run = bundle_path.parent
    prediction_context.pop("deadline")
    prediction_context.update({
        "planning_gameweek": 6,
        "official_deadline": "2026-09-11T17:00:00+00:00",
        "deadline_source": "official_fpl_api.bootstrap_static.local_snapshot",
        "deadline_verification_status": "VERIFIED",
        "deadline_observed_at": "2026-09-10T09:00:00+00:00",
    })
    context_path = run / "prediction_context.json"
    context_path.write_text(json.dumps(prediction_context, sort_keys=True), encoding="utf-8")
    manifest["artifacts"]["prediction_context"]["sha256"] = _sha(context_path)
    (run / "run_manifest.json").write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
    state = _state()
    verified = build_planning_context(
        state=state, bundle_path=bundle_path, bundle=bundle,
        manifest=manifest, prediction_context=prediction_context,
    )
    assert verified.deadline == "2026-09-11T17:00:00+00:00"
    assert _deadline_capture_status(verified.deadline, observed_at=AT)[0] == "ELIGIBLE"

    changed_context = dict(prediction_context)
    changed_context["official_deadline"] = "2026-09-12T17:00:00+00:00"
    context_path.write_text(json.dumps(changed_context, sort_keys=True), encoding="utf-8")
    manifest["artifacts"]["prediction_context"]["sha256"] = _sha(context_path)
    (run / "run_manifest.json").write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
    changed = build_planning_context(
        state=state, bundle_path=bundle_path, bundle=bundle,
        manifest=manifest, prediction_context=changed_context,
    )
    assert changed.context_id != verified.context_id

    context_path.write_text(json.dumps({**changed_context, "official_deadline": "2026-09-13T17:00:00+00:00"}), encoding="utf-8")
    with pytest.raises(ProjectionArtifactIntegrityError, match="prediction_context hash mismatch"):
        build_planning_context(
            state=state, bundle_path=bundle_path, bundle=bundle,
            manifest=manifest, prediction_context=changed_context,
        )


def test_unverified_context_keeps_deadline_empty_and_p2_gate_skips(tmp_path):
    bundle_path, bundle, manifest, prediction_context = _run(tmp_path)
    prediction_context.pop("deadline")
    prediction_context.update({
        "planning_gameweek": 6,
        "official_deadline": "2026-09-11T17:00:00+00:00",
        "deadline_verification_status": "UNVERIFIED",
    })
    path = bundle_path.parent / "prediction_context.json"
    path.write_text(json.dumps(prediction_context), encoding="utf-8")
    manifest["artifacts"]["prediction_context"]["sha256"] = _sha(path)
    (bundle_path.parent / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    context = build_planning_context(
        state=_state(), bundle_path=bundle_path, bundle=bundle,
        manifest=manifest, prediction_context=prediction_context,
    )
    assert context.deadline is None
    assert _deadline_capture_status(context.deadline, observed_at=AT)[0] == "SKIPPED_UNVERIFIED_DEADLINE"
