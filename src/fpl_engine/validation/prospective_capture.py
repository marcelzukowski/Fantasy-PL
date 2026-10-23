"""Archive an already frozen Decision without running models, Chip or providers."""

from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path

from fpl_engine.planning import verify_projection_artifacts
from fpl_engine.reports import (
    AnalysisManifestV2,
    ReportReference,
    parse_analysis_manifest,
    parse_decision_report,
)
from fpl_engine.reports.common import canonical_json
from fpl_engine.validation.replay_archive import (
    ReplayArchiveError,
    _projection_paths,
    build_archive_case,
    write_archive_case,
)


def capture_decision(root: Path, decision_path: Path, *, now: datetime | None = None) -> Path:
    """Capture at actual worker completion; `now` is injectable for clock tests."""
    root, decision_path = Path(root).resolve(), Path(decision_path).resolve()
    if not decision_path.is_relative_to(root):
        raise ReplayArchiveError("Decision report is outside the project.")
    created = now or datetime.now(timezone.utc)
    if created.tzinfo is None or created.utcoffset() is None:
        raise ReplayArchiveError("Capture time must be timezone-aware.")
    content = decision_path.read_bytes()
    try:
        decision = parse_decision_report(json.loads(content))
    except ValueError as exc:
        raise ReplayArchiveError("Decision report is invalid.") from exc
    context = decision.planning_context
    if context is None or context.deadline is None or decision.external_mutations:
        raise ReplayArchiveError("Capture requires a verified read-only context and deadline.")
    deadline = datetime.fromisoformat(context.deadline.replace("Z", "+00:00"))
    if (
        created >= deadline
        or datetime.fromisoformat(decision.created_at.replace("Z", "+00:00")) > created
    ):
        raise ReplayArchiveError(
            "Capture must complete before the deadline and after the Decision."
        )
    bundle_path, manifest_path = _projection_paths(root, context)
    try:
        integrity = verify_projection_artifacts(
            bundle_path,
            json.loads(manifest_path.read_bytes()),
            require_hashes=True,
        )
        if (
            integrity is None
            or integrity.manifest_sha256 != context.manifest_sha256
            or tuple(sorted(integrity.artifact_hashes)) != tuple(sorted(context.artifact_hashes))
        ):
            raise ValueError("PlanningContext artifact mismatch")
    except ValueError as exc:
        raise ReplayArchiveError("Projection artifact integrity failed.") from exc
    digest = sha256(content).hexdigest()
    reference = ReportReference(str(decision_path.relative_to(root)), digest)
    run_id = "prospective-" + digest[:24]
    # This manifest has no GUI display-state snapshot; keep it out of Run Center history.
    directory = root / "data/processed/prospective_captures" / context.season.replace("/", "-")
    destination = directory / f"{run_id}.json"
    if destination.exists():
        try:
            existing = parse_analysis_manifest(json.loads(destination.read_bytes()))
        except ValueError as exc:
            raise ReplayArchiveError(
                "Existing capture manifest is invalid; refusing overwrite."
            ) from exc
        if (
            existing.context_id != context.context_id
            or existing.decision_report != reference
            or existing.analysis_run_id != run_id
            or existing.chip_report is not None
        ):
            raise ReplayArchiveError("Existing capture manifest conflicts; refusing overwrite.")
    else:
        analysis = AnalysisManifestV2.create(
            analysis_run_id=run_id,
            created_at=created,
            status="PARTIAL",
            season=context.season,
            gameweek=context.gameweek,
            projection_run_id=context.projection_run_id,
            decision_report=decision,
            decision_reference=reference,
            chip_report=None,
            chip_reference=None,
            recommended_xi_available=decision.preview_for("strategic") is not None,
            captaincy_available=decision.preview_for("strategic") is not None,
            display_state=None,
        )
        payload = analysis.to_dict()
        # These identities are captured at worker completion, never backfilled on old reports.
        payload["prospective_capture"] = {
            "schema_version": "prospective_capture_v1",
            "source_hashes_at_capture": {
                name: sha256((root / name).read_bytes()).hexdigest()
                for name in (
                    "desktop_app/decision_runner.py",
                    "src/fpl_engine/strategy/strategic_planner_v3.py",
                    "src/fpl_engine/optimizer/core.py",
                )
                if (root / name).is_file()
            },
        }
        directory.mkdir(parents=True, exist_ok=True)
        # Exclusive creation prevents a concurrent capture from overwriting evidence.
        try:
            with destination.open("xb") as stream:
                stream.write(canonical_json(payload) + b"\n")
        except FileExistsError as exc:
            raise ReplayArchiveError(
                "Concurrent capture exists; retry without overwriting."
            ) from exc
    finished = now or datetime.now(timezone.utc)
    if finished >= deadline:
        raise ReplayArchiveError("Capture did not finish before the deadline.")
    case = build_archive_case(root, destination, archive_created_at=finished)
    return write_archive_case(root, case)
