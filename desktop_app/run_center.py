"""Read-only discovery and provenance contracts for desktop production runs."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Mapping

from .decision_orchestration import validate_decision_bundle
from .orchestration import DesktopEngineError, projection_run_summary
from .state import DesktopSquadState


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
    root = Path(root).resolve()
    base = root / "data" / "processed" / "desktop_analyses" / str(season).replace("/", "-")
    if not base.exists():
        return ()
    found: list[AnalysisRun] = []
    for path in base.glob("*.json"):
        try:
            payload = _object(path, "analysis manifest")
            status = str(payload.get("status", ""))
            if status not in ANALYSIS_STATUSES:
                continue
            if str(payload.get("season")) != str(season) or int(payload.get("gameweek")) != int(gameweek):
                continue
            analysis_run_id = str(payload["analysis_run_id"])
            projection_run_id = str(payload["projection_run_id"])
            state = _squad_state(payload.get("squad_state"))
            decision = _safe_reference(root, payload.get("decision_report"))
            chip = _safe_reference(root, payload.get("chip_report"))
            if status in {"COMPLETE", "PARTIAL"} and (state is None or decision is None or not decision.exists()):
                continue
            if chip is not None and not chip.exists():
                chip = None
            found.append(AnalysisRun(
                analysis_run_id=analysis_run_id, path=path, projection_run_id=projection_run_id,
                season=str(season), gameweek=int(gameweek), timestamp=_timestamp(payload.get("timestamp"), path),
                status=status, decision_report=decision, chip_report=chip,
                recommended_xi_available=bool(payload.get("recommended_xi_available")),
                captain_available=bool(payload.get("captain_available", payload.get("captaincy_available"))),
                vice_captain_available=bool(payload.get("vice_captain_available", payload.get("captaincy_available"))),
                captaincy_available=bool(payload.get("captaincy_available")), squad_state=state,
            ))
        except (KeyError, TypeError, ValueError, RunCenterError):
            continue
    return tuple(sorted(found, key=lambda run: (run.timestamp, run.analysis_run_id), reverse=True))


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
) -> Path:
    if status not in ANALYSIS_STATUSES:
        raise RunCenterError("Analysis status is invalid.")
    root = Path(root).resolve()
    directory = root / "data" / "processed" / "desktop_analyses" / state.season.replace("/", "-")
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / f"{analysis_run_id}.json"
    payload = {
        "analysis_manifest_version": 1,
        "analysis_run_id": analysis_run_id,
        "projection_run_id": projection_run_id,
        "season": state.season,
        "gameweek": state.gameweek,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "decision_report": _relative_reference(root, decision_report),
        "chip_report": _relative_reference(root, chip_report),
        "recommended_xi_available": bool(recommended_xi_available),
        "captain_available": bool(captaincy_available),
        "vice_captain_available": bool(captaincy_available),
        "captaincy_available": bool(captaincy_available),
        "squad_state": asdict(state),
    }
    destination.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return destination
