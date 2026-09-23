"""Desktop contracts for the existing read-only chip screen."""

from __future__ import annotations

from enum import Enum
import json
from pathlib import Path

from .decision_orchestration import decision_bundle_for_state
from .orchestration import DesktopEngineError
from .state import DesktopSquadState
from fpl_engine.reports import ChipReportV2, ReportSchemaError, parse_chip_report


class ChipRunState(str, Enum):
    IDLE = "IDLE"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    CANCELLED = "CANCELLED"
    ERROR = "ERROR"


def chip_arguments(*, request_path: Path, prediction_bundle: Path, decision_report: Path, output_dir: Path) -> list[str]:
    return [
        "-m", "desktop_app.chip_runner",
        "--desktop-state", str(request_path),
        "--prediction-bundle", str(prediction_bundle),
        "--decision-report", str(decision_report),
        "--output-dir", str(output_dir),
    ]


def chip_report_path(output: str) -> Path | None:
    for line in output.splitlines():
        if line.startswith("CHIP_REPORT="):
            return Path(line.partition("=")[2].strip())
    return None


def load_chip_report(path: Path) -> ChipReportV2:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        return parse_chip_report(payload)
    except (OSError, UnicodeError, json.JSONDecodeError, ReportSchemaError) as exc:
        raise DesktopEngineError("The chip screen did not produce a readable report.") from exc


def chip_bundle_for_state(
    root: Path,
    state: DesktopSquadState,
    selected_bundle: Path | None = None,
) -> Path:
    """Reuse the decision bridge's matching canonical production bundle gate."""
    return decision_bundle_for_state(root, state, selected_bundle)


def format_chip_summary(report: ChipReportV2 | dict) -> str:
    """Render validated reports; retain direct-dict support for existing unit-only fixtures."""
    recommendation = report.recommendation if isinstance(report, ChipReportV2) else report["recommendation"]
    chip = recommendation.get("chip")
    available = recommendation.get("available_chips", [])
    lines = ["Recommended: NO CHIP / ROLL" if chip is None else "Recommended: " + str(chip).replace("_", " ").upper()]
    if recommendation.get("reason"):
        lines.append(str(recommendation["reason"]))
    if recommendation.get("incremental_ev") is not None:
        lines.append(f"Projected gain: {float(recommendation['incremental_ev']):+.2f} EV")
    if recommendation.get("horizon_gameweeks") is not None:
        lines.append(f"Horizon: {int(recommendation['horizon_gameweeks'])} GW")
    near_start = recommendation.get("near_term_start_gameweek")
    near_end = recommendation.get("near_term_end_gameweek")
    if near_start is not None and near_end is not None:
        lines.append(f"Near-term horizon: GW{int(near_start)}–GW{int(near_end)}")
    strategy = report.strategic_evaluation if isinstance(report, ChipReportV2) else report.get("strategic")
    period = report.chip_period if isinstance(report, ChipReportV2) else report.get("chip_period")
    if isinstance(strategy, dict):
        stronger = strategy.get("materially_stronger_candidate")
        if isinstance(stronger, dict):
            lines.append(
                "Best later candidate: "
                f"GW{int(stronger['gameweek'])} — {str(stronger['chip']).replace('_', ' ').upper()}"
            )
            if stronger.get("incremental_ev") is not None:
                lines.append(f"Strategic estimate: {float(stronger['incremental_ev']):+.2f} EV")
        elif strategy.get("error"):
            lines.append("Best later candidate: strategic estimate unavailable")
        else:
            lines.append("Best later candidate: none stronger")
        if strategy.get("simulations_per_fixture") is not None:
            lines.append(f"Strategic simulations: {int(strategy['simulations_per_fixture'])}")
    if isinstance(period, dict) and period.get("end_gameweek") is not None:
        lines.append(f"Chip period ends: GW{int(period['end_gameweek'])}")
    lines.append("Available: " + (", ".join(str(value).replace("_", " ").title() for value in available) if available else "none"))
    return "\n".join(lines)
