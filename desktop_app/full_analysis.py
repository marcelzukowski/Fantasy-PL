"""Small state contract for the read-only desktop Full GW workflow."""

from __future__ import annotations

from enum import Enum


class FullAnalysisState(str, Enum):
    IDLE = "IDLE"
    VALIDATING = "VALIDATING"
    PROJECTIONS = "PROJECTIONS"
    DECISION = "DECISION"
    RECOMMENDED_XI = "RECOMMENDED_XI"
    CHIP_SCREEN = "CHIP_SCREEN"
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    ERROR = "ERROR"


RUNNING_FULL_ANALYSIS_STATES = frozenset({
    FullAnalysisState.VALIDATING,
    FullAnalysisState.PROJECTIONS,
    FullAnalysisState.DECISION,
    FullAnalysisState.RECOMMENDED_XI,
    FullAnalysisState.CHIP_SCREEN,
})


def full_analysis_summary(*, state: FullAnalysisState, gameweek: int | None = None,
                          bundle_label: str | None = None, chip_status: str | None = None) -> str:
    """Return a compact user-facing status without exposing process/CDP details."""
    lines = [f"Full GW Analysis: {state.value.replace('_', ' ')}"]
    if gameweek is not None:
        lines.append(f"GW {int(gameweek)}")
    if bundle_label:
        lines.append(f"Production bundle: {bundle_label}")
    if chip_status:
        lines.append(f"Chip screen: {chip_status}")
    return " · ".join(lines)
