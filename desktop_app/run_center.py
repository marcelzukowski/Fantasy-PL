"""Read-only discovery and provenance contracts for desktop production runs."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Mapping
import logging

from .decision_orchestration import validate_decision_bundle
from .orchestration import DesktopEngineError, projection_run_summary
from .state import DesktopSquadState
from fpl_engine.validation.replay_archive import ReplayArchiveError, archive_analysis

LOGGER = logging.getLogger(__name__)

from fpl_engine.reports import (
    AnalysisManifestV2, ReportIntegrityError, ReportReference, ReportSchemaError,
    parse_analysis_manifest, parse_chip_report, parse_decision_report,
)


class RunCenterError(RuntimeError):
    """A saved projection or analysis record cannot be used safely."""


ANALYSIS_STATUSES = frozenset({"COMPLETE", "PARTIAL", "ERROR"})


@dataclass(frozen=True)
class ProjectionRun:
    run_id: str
    run_dir: Path
    bundle_path: Path
    season: str
    gameweek: int
    timestamp: datetime
    simulation_count: int
    seed: int | None
    simulator_version: str | None
    market_shadow_status: str | None
    market_shadow_coverage: str | None

    @property
    def label(self) -> str:
        sims = f"{self.simulation_count // 1000}k" if self.simulation_count % 1000 == 0 else f"{self.simulation_count:,}"
        simulator = self.simulator_version or "model"
        if simulator.startswith("fixture_simulator_"):
            simulator = simulator.removeprefix("fixture_simulator_").upper()
        return f"{self.timestamp.astimezone().strftime('%Y-%m-%d %H:%M')} · GW{self.gameweek} · {sims} · {simulator}"

    @property
    def detail(self) -> str:
        shadow = "Shadow: unavailable"
        if self.market_shadow_status:
            coverage = f" · coverage {self.market_shadow_coverage}" if self.market_shadow_coverage else ""
            shadow = f"Shadow: {self.market_shadow_status.lower()}{coverage}"
        seed = "—" if self.seed is None else str(self.seed)
        return f"Active: {self.label} · seed {seed} · {shadow}"


@dataclass(frozen=True)
class AnalysisRun:
    analysis_run_id: str
    path: Path
    projection_run_id: str
    season: str
    gameweek: int
    timestamp: datetime
    status: str
    decision_report: Path | None
    chip_report: Path | None
    recommended_xi_available: bool
    captain_available: bool
    vice_captain_available: bool
    captaincy_available: bool
    squad_state: DesktopSquadState | None
    context_id: str | None
    legacy_unverified: bool
    manifest: AnalysisManifestV2 | None = None

    @property
    def label(self) -> str:
        return f"{self.timestamp.astimezone().strftime('%Y-%m-%d %H:%M')} · {self.status} · GW{self.gameweek}"


def _object(path: Path, label: str) -> Mapping[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RunCenterError(f"The saved {label} is unreadable.") from exc
    if not isinstance(value, Mapping):
        raise RunCenterError(f"The saved {label} is invalid.")
    return value


def _timestamp(value: object, fallback: Path) -> datetime:
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return datetime.fromtimestamp(fallback.stat().st_mtime, tz=timezone.utc)


def _optional_int(value: object) -> int | None:
    try:
        return None if value is None else int(value)
    except (TypeError, ValueError):
        return None


def _safe_reference(root: Path, value: object) -> Path | None:
    if not isinstance(value, str) or not value:
        return None
    candidate = (Path(root).resolve() / value).resolve()
    try:
        candidate.relative_to(Path(root).resolve())
    except ValueError as exc:
        raise RunCenterError("The saved analysis has an unsafe report reference.") from exc
    return candidate


def _relative_reference(root: Path, path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        return str(Path(path).resolve().relative_to(Path(root).resolve()))
    except ValueError as exc:
        raise RunCenterError("Analysis reports must remain inside the project.") from exc


def discover_projection_runs(root: Path, *, season: str, gameweek: int) -> tuple[ProjectionRun, ...]:
    """Return only complete, canonical bundles compatible with the active season/GW."""
    root = Path(root).resolve()
    base = root / "data" / "processed" / "predictions" / str(season).replace("/", "-")
    if not base.exists():
        return ()
    found: list[ProjectionRun] = []
    for run_dir in base.iterdir():
        if not run_dir.is_dir():
            continue
        bundle_path = run_dir / "shadow_projection_bundle.json"
        try:
            bundle = validate_decision_bundle(root, bundle_path, season=season, gameweek=gameweek)
            projection_run_summary(run_dir)
            manifest = _object(run_dir / "run_manifest.json", "projection manifest")
        except (DesktopEngineError, RunCenterError):
            continue
        simulation = manifest.get("simulation")
        if not isinstance(simulation, Mapping):
            continue
        count = _optional_int(simulation.get("simulations_per_fixture"))
        if count is None:
            continue
        market = manifest.get("market_shadow")
        if not isinstance(market, Mapping):
            market = {}
        mapped = _optional_int(market.get("mapped_fixture_count"))
        total = _optional_int(market.get("current_gameweek_fixture_count"))
        coverage = f"{mapped}/{total}" if mapped is not None and total is not None else None
        found.append(ProjectionRun(
            run_id=run_dir.name,
            run_dir=run_dir,
            bundle_path=bundle_path,
            season=str(bundle.get("season")),
            gameweek=int(bundle.get("current_gameweek")),
            timestamp=_timestamp(manifest.get("prediction_timestamp") or bundle.get("prediction_timestamp"), bundle_path),
            simulation_count=count,
            seed=_optional_int(simulation.get("base_seed")),
            simulator_version=str(simulation["simulator_version"]) if simulation.get("simulator_version") is not None else None,
            market_shadow_status=str(market["status"]) if market.get("status") is not None else None,
            market_shadow_coverage=coverage,
        ))
    return tuple(sorted(found, key=lambda run: (run.timestamp, run.run_id), reverse=True))


def _squad_state(value: object) -> DesktopSquadState | None:
    if not isinstance(value, Mapping):
        return None
    try:
        return DesktopSquadState(**dict(value))
    except (TypeError, ValueError):
        return None


def discover_analysis_runs(root: Path, *, season: str, gameweek: int) -> tuple[AnalysisRun, ...]:
    """Discover version-dispatched history records without promoting legacy data."""
    root = Path(root).resolve()
    base = root / "data" / "processed" / "desktop_analyses" / str(season).replace("/", "-")
    if not base.exists():
        return ()
    found: list[AnalysisRun] = []
    for path in base.glob("*.json"):
        try:
            manifest = parse_analysis_manifest(_object(path, "analysis manifest"))
            if manifest.status.value not in ANALYSIS_STATUSES:
                continue
            if manifest.season != str(season) or manifest.gameweek != int(gameweek):
                continue
            state = _squad_state(manifest.display_state)
            decision = _safe_reference(root, manifest.decision_report.path if manifest.decision_report else None)
            chip = _safe_reference(root, manifest.chip_report.path if manifest.chip_report else None)
            if manifest.status.value in {"COMPLETE", "PARTIAL"} and (state is None or decision is None or not decision.exists()):
                continue
            if chip is not None and not chip.exists():
                chip = None
            found.append(AnalysisRun(
                analysis_run_id=manifest.analysis_run_id, path=path, projection_run_id=manifest.projection_run_id,
                season=manifest.season, gameweek=manifest.gameweek,
                timestamp=_timestamp(manifest.created_at, path), status=manifest.status.value,
                decision_report=decision, chip_report=chip,
                recommended_xi_available=manifest.recommended_xi_available,
                captain_available=manifest.captain_available,
                vice_captain_available=manifest.vice_captain_available,
                captaincy_available=manifest.captaincy_available, squad_state=state,
                context_id=manifest.context_id, legacy_unverified=manifest.legacy_unverified,
                manifest=manifest,
            ))
        except (KeyError, TypeError, ValueError, RunCenterError, ReportSchemaError):
            continue
    return tuple(sorted(found, key=lambda run: (run.timestamp, run.analysis_run_id), reverse=True))


def _report_reference(root: Path, path: Path | None) -> ReportReference | None:
    if path is None:
        return None
    return ReportReference(
        path=_relative_reference(root, path),
        sha256=sha256(Path(path).read_bytes()).hexdigest(),
    )


def verify_analysis_report_references(root: Path, analysis: AnalysisRun) -> None:
    """Fail closed if an immutable typed manifest no longer points at exact bytes."""
    manifest = analysis.manifest
    if manifest is None or manifest.legacy_unverified:
        raise RunCenterError("Saved analysis is LEGACY / UNVERIFIED. Run a new analysis.")
    for label, reference, path in (
        ("decision", manifest.decision_report, analysis.decision_report),
        ("chip", manifest.chip_report, analysis.chip_report),
    ):
        if reference is None:
            continue
        if path is None or not path.is_file():
            raise RunCenterError(f"The saved {label} report is missing.")
        if sha256(path.read_bytes()).hexdigest() != reference.sha256:
            raise RunCenterError(f"The saved {label} report failed its integrity check.")

def write_analysis_run(
    root: Path,
    *,
    analysis_run_id: str,
    projection_run_id: str,
    state: DesktopSquadState,
    status: str,
    decision_report: Path | None,
    chip_report: Path | None,
    recommended_xi_available: bool,
    captaincy_available: bool,
    context_id: str | None = None,
) -> Path:
    """Persist references to validated reports; no arbitrary result copies are stored."""
    root = Path(root).resolve()
    try:
        decision = parse_decision_report(_object(decision_report, "decision report")) if decision_report is not None else None
        chip = parse_chip_report(_object(chip_report, "chip report")) if chip_report is not None else None
        decision_reference = _report_reference(root, decision_report)
        chip_reference = _report_reference(root, chip_report)
        if context_id is not None and decision is not None and decision.context_id is not None and context_id != decision.context_id:
            raise RunCenterError("Saved analysis does not match the current planning context.")
        if decision is not None and decision.planning_context is not None and projection_run_id != decision.planning_context.projection_run_id:
            raise RunCenterError("Saved analysis does not match the selected projection run.")
        manifest = AnalysisManifestV2.create(
            analysis_run_id=analysis_run_id,
            created_at=datetime.now(timezone.utc),
            status=status,
            season=state.season,
            gameweek=state.gameweek,
            projection_run_id=projection_run_id,
            decision_report=decision,
            decision_reference=decision_reference,
            chip_report=chip,
            chip_reference=chip_reference,
            recommended_xi_available=recommended_xi_available,
            captaincy_available=captaincy_available,
            display_state=asdict(state),
        )
    except (ReportSchemaError, ReportIntegrityError) as exc:
        raise RunCenterError(str(exc)) from exc
    directory = root / "data" / "processed" / "desktop_analyses" / state.season.replace("/", "-")
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / f"{analysis_run_id}.json"
    destination.write_text(json.dumps(manifest.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    # A strict archive is an additional immutable pre-deadline record.  It never
    # fetches data or changes the outcome of a completed desktop analysis.
    if manifest.planning_context is not None and manifest.planning_context.deadline is not None:
        try:
            archive_analysis(root, destination)
        except ReplayArchiveError as exc:
            LOGGER.info("Replay archive not created for %s: %s", analysis_run_id, exc)
    return destination
