"""Desktop bridge for the existing, non-mutating shadow decision runner."""

from __future__ import annotations

from dataclasses import asdict
from enum import Enum
import json
from pathlib import Path

from fpl_engine.planning import (
    PlanningContext,
    PlanningContextError,
    ProjectionArtifactIntegrityError,
    build_planning_context,
    verify_projection_artifacts,
)

from .orchestration import DesktopEngineError, latest_prediction_run
from .state import DesktopSquadState
from fpl_engine.reports import DecisionReportV2, ReportSchemaError, parse_decision_report


class DecisionRunState(str, Enum):
    IDLE = "IDLE"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    ERROR = "ERROR"


def _json_object(path: Path, label: str) -> dict:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DesktopEngineError(
            f"The saved production {label} is unreadable."
        ) from exc
    if not isinstance(value, dict):
        raise DesktopEngineError(f"The saved production {label} is invalid.")
    return value


def _simulation_count(payload: dict, label: str) -> int:
    count = payload.get("simulations_per_fixture")
    if type(count) is not int or not 1 <= count <= 50_000:
        raise DesktopEngineError(
            f"The saved production {label} must record an integer "
            "simulation count between 1 and 50000."
        )
    return count


def validate_decision_bundle(
    root: Path,
    bundle_path: Path,
    *,
    season: str,
    gameweek: int,
    require_canonical_path: bool = True,
) -> dict:
    """Validate an auditable bundle against its adjacent run metadata."""
    root = Path(root).resolve()
    bundle_path = Path(bundle_path).resolve()
    canonical_root = (root / "data" / "processed" / "predictions").resolve()
    if require_canonical_path:
        try:
            bundle_path.relative_to(canonical_root)
        except ValueError as exc:
            raise DesktopEngineError(
                "Decision Engine accepts only canonical production prediction bundles."
            ) from exc

    run_dir = bundle_path.parent
    bundle = _json_object(bundle_path, "projection bundle")
    context = _json_object(run_dir / "prediction_context.json", "prediction context")
    manifest = _json_object(run_dir / "run_manifest.json", "run manifest")

    expected_season = str(season)
    expected_gameweek = int(gameweek)
    identities = (
        ("bundle", bundle.get("season"), bundle.get("current_gameweek")),
        ("context", context.get("target_season"), context.get("target_gameweek")),
        ("manifest", manifest.get("season"), manifest.get("target_gameweek")),
    )
    for label, actual_season, actual_gameweek in identities:
        try:
            matches = (
                str(actual_season) == expected_season
                and int(actual_gameweek) == expected_gameweek
            )
        except (TypeError, ValueError):
            matches = False
        if not matches:
            raise DesktopEngineError(
                f"The saved production {label} does not match the selected season and gameweek."
            )

    bundle_pipeline = bundle.get("pipeline")
    manifest_simulation = manifest.get("simulation")
    if not isinstance(bundle_pipeline, dict) or not isinstance(manifest_simulation, dict):
        raise DesktopEngineError(
            "The saved production bundle is missing simulation provenance."
        )
    bundle_count = _simulation_count(bundle_pipeline, "bundle")
    manifest_count = _simulation_count(manifest_simulation, "manifest")
    if bundle_count != manifest_count:
        raise DesktopEngineError(
            "The saved production bundle and manifest have different simulation counts."
        )
    for key in ("simulation_mode", "simulator_version"):
        bundle_value = bundle_pipeline.get(key)
        manifest_value = manifest_simulation.get(key)
        if (
            bundle_value is not None
            and manifest_value is not None
            and bundle_value != manifest_value
        ):
            raise DesktopEngineError(
                f"The saved production bundle and manifest have different {key}."
            )
    try:
        # New manifests are verified here for every load. Legacy manifests
        # remain discoverable but cannot start a newly verified analysis.
        verify_projection_artifacts(bundle_path, manifest, require_hashes=False)
    except ProjectionArtifactIntegrityError as exc:
        raise DesktopEngineError(str(exc)) from exc
    return bundle


def planning_context_for_state(
    root: Path,
    state: DesktopSquadState | dict,
    bundle_path: Path,
    *,
    require_canonical_path: bool = True,
) -> PlanningContext:
    """Build one verified immutable context for decision, chip, and history use."""
    season = state["season"] if isinstance(state, dict) else state.season
    gameweek = state["gameweek"] if isinstance(state, dict) else state.gameweek
    bundle = validate_decision_bundle(
        root,
        bundle_path,
        season=str(season),
        gameweek=int(gameweek),
        require_canonical_path=require_canonical_path,
    )
    run_dir = Path(bundle_path).resolve().parent
    try:
        context_payload = _json_object(run_dir / "prediction_context.json", "prediction context")
        manifest = _json_object(run_dir / "run_manifest.json", "run manifest")
        return build_planning_context(
            state=state,
            bundle_path=bundle_path,
            bundle=bundle,
            manifest=manifest,
            prediction_context=context_payload,
        )
    except (PlanningContextError, ProjectionArtifactIntegrityError) as exc:
        raise DesktopEngineError(str(exc)) from exc


def decision_bundle_for_state(
    root: Path,
    state: DesktopSquadState,
    selected_bundle: Path | None = None,
) -> Path:
    """Return the selected compatible production bundle, never scratch data."""
    if selected_bundle is None:
        run = latest_prediction_run(root, state.season, gameweek=state.gameweek)
        if run is None:
            raise DesktopEngineError(
                "No saved production projection run matches the selected season and gameweek. "
                "Run projections first."
            )
        bundle = run / "shadow_projection_bundle.json"
    else:
        bundle = Path(selected_bundle)
    if not bundle.exists():
        raise DesktopEngineError("The matching production projection run has no decision bundle.")
    validate_decision_bundle(
        root,
        bundle,
        season=state.season,
        gameweek=state.gameweek,
    )
    return bundle


def write_decision_request(path: Path, state: DesktopSquadState) -> Path:
    """Persist a local UI snapshot for the child process without changing account state."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(state), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def decision_arguments(*, request_path: Path, prediction_bundle: Path, output_dir: Path) -> list[str]:
    return [
        "-m", "desktop_app.decision_runner",
        "--desktop-state", str(request_path),
        "--prediction-bundle", str(prediction_bundle),
        "--output-dir", str(output_dir),
    ]


def decision_report_path(output: str) -> Path | None:
    for line in output.splitlines():
        if line.startswith("DECISION_REPORT="):
            return Path(line.partition("=")[2].strip())
    return None


def load_decision_report(path: Path) -> DecisionReportV2:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        return parse_decision_report(payload)
    except (OSError, UnicodeError, json.JSONDecodeError, ReportSchemaError) as exc:
        raise DesktopEngineError("The decision engine did not produce a readable report.") from exc


def format_decision_summary(report: DecisionReportV2, selling_prices: dict[str, int]) -> str:
    """Render only fields supplied by the validated decision report."""
    recommendation = report.recommendation if isinstance(report, DecisionReportV2) else report["recommendation"]
    metadata = report.player_metadata if isinstance(report, DecisionReportV2) else report.get("player_metadata", {})

    def money(value) -> str:
        return "—" if value is None else f"£{int(value) / 10:.1f}m"

    outgoing = recommendation.get("transfers_out", [])
    incoming = recommendation.get("transfers_in", [])
    if recommendation.get("roll_free_transfer") or (not outgoing and not incoming):
        lines = ["ROLL FREE TRANSFER", "No transfer is recommended for this gameweek."]
    else:
        lines = []
        for player_id in outgoing:
            player = metadata.get(player_id, {})
            lines += [f"OUT: {player.get('name', player_id)}", f"{player.get('position', '—')} · sell {money(selling_prices.get(player_id))}"]
        for player_id in incoming:
            player = metadata.get(player_id, {})
            lines += [f"IN: {player.get('name', player_id)}", f"{player.get('position', '—')} · price {money(player.get('current_price'))}"]
    lines.append("Horizon: 1 GW")
    if recommendation.get("net_projected_gain") is not None:
        lines.append(f"Projected gain: {float(recommendation['net_projected_gain']):+.2f}")
    if recommendation.get("hit_cost") is not None:
        lines.append(f"Transfer cost: {int(recommendation['hit_cost'])} pts")
    if recommendation.get("resulting_bank") is not None:
        lines.append(f"Resulting bank: {money(recommendation['resulting_bank'])}")
    if recommendation.get("decision_margin") is not None:
        lines.append(f"Decision margin: {float(recommendation['decision_margin']):.2f}")
    return "\n".join(lines)
