"""Read-only trust and freshness presentation model for Analysis.

The model deliberately has no Qt or filesystem dependency.  The desktop shell
supplies already parsed reports and already verified local facts; this module
only makes their safety meaning explicit for the user interface.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Mapping

from fpl_engine.planning import PlanningContext
from fpl_engine.reports import ChipReportV2, DecisionReportV2


class AnalysisTrustStatus(str, Enum):
    VERIFIED = "VERIFIED"
    STALE = "STALE"
    PARTIAL = "PARTIAL"
    LEGACY_UNVERIFIED = "LEGACY_UNVERIFIED"
    INVALID = "INVALID"


class ChipTrustStatus(str, Enum):
    NOT_RUN = "NOT RUN"
    RUNNING = "RUNNING"
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    CANCELLED = "CANCELLED"
    ERROR = "ERROR"


@dataclass(frozen=True)
class AnalysisTrustInputs:
    """Validated facts about one displayed Analysis result.

    ``current_context`` is intentionally optional: an inability to reproduce
    it from the selected local bundle is a fail-closed condition for an active
    recommendation, while a historic report is evaluated against itself.
    """

    decision: DecisionReportV2 | None
    chip: ChipReportV2 | None = None
    current_context: PlanningContext | None = None
    selected_season: str | None = None
    selected_gameweek: int | None = None
    analysis_timestamp: str | None = None
    fpl_sync_timestamp: str | None = None
    deadline: datetime | None = None
    artifact_verified: bool | None = None
    artifact_error: str | None = None
    chip_state: ChipTrustStatus = ChipTrustStatus.NOT_RUN
    market_status: str | None = None
    market_coverage: str | None = None
    price_signal_status: str | None = None
    archive_status: str | None = None
    chip_forecast_status: str | None = None
    historical: bool = False
    material_state_changed: bool = False
    projection_changed: bool = False
    report_status: str | None = None


@dataclass(frozen=True)
class AnalysisTrustViewModel:
    status: AnalysisTrustStatus
    historical: bool
    headline: str
    detail: str
    warning: str | None
    core_verified: bool
    fpl_sync_timestamp: str | None
    analysis_timestamp: str | None
    prediction_timestamp: str | None
    selected_gameweek: int | None
    deadline: datetime | None
    context_status: str
    artifact_status: str
    decision_status: str
    chip_status: ChipTrustStatus
    market_status: str
    market_coverage: str | None
    price_signal_status: str
    archive_status: str | None
    chip_forecast_status: str
    optional_notes: tuple[str, ...]

    @property
    def badge_text(self) -> str:
        return "VERIFIED HISTORICAL" if self.historical and self.status is AnalysisTrustStatus.VERIFIED else self.status.value.replace("_", " / ")


def _timestamp(value: str | None) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    if parsed.tzinfo is None:
        return value
    return parsed.astimezone(timezone.utc).isoformat()


def _price_status(decision: DecisionReportV2 | None, supplied: str | None) -> str:
    if supplied in {"AVAILABLE", "STALE", "UNAVAILABLE"}:
        return supplied
    raw: Mapping[str, object] = decision.v3_result.payload if decision and decision.v3_result else {}
    value = raw.get("price_signal_status") if isinstance(raw, Mapping) else None
    return str(value) if value in {"AVAILABLE", "STALE", "UNAVAILABLE"} else "UNAVAILABLE"


def _optional_notes(chip: ChipTrustStatus, market: str, coverage: str | None, price: str, forecast: str) -> tuple[str, ...]:
    notes: list[str] = []
    if chip is not ChipTrustStatus.COMPLETE:
        notes.append(f"Chip Strategy: {chip.value}")
    if market == "PARTIAL":
        notes.append(f"Market data: PARTIAL{f' {coverage}' if coverage else ''}")
    elif market in {"UNAVAILABLE", ""}:
        notes.append("Market data: UNAVAILABLE")
    elif coverage:
        notes.append(f"Market data: {market} {coverage}")
    if price != "AVAILABLE":
        notes.append("Price signals unavailable" if price == "UNAVAILABLE" else "Price signals stale")
    if forecast != "AVAILABLE":
        notes.append(f"Chip forecast: {forecast}")
    return tuple(notes)


def build_analysis_trust(inputs: AnalysisTrustInputs) -> AnalysisTrustViewModel:
    """Derive the concise status without changing recommendation semantics."""
    decision = inputs.decision
    report_context = decision.planning_context if decision else None
    prediction = report_context.prediction_timestamp if report_context else None
    selected_gw = inputs.selected_gameweek
    artifact = "VERIFIED" if inputs.artifact_verified else ("INVALID" if inputs.artifact_verified is False else "NOT VERIFIED")
    decision_status = "VALID" if decision and not decision.external_mutations else ("INVALID" if decision else "NOT RUN")
    market = str(inputs.market_status or "UNAVAILABLE").upper()
    price = _price_status(decision, inputs.price_signal_status)
    forecast = str(inputs.chip_forecast_status or ("AVAILABLE" if decision and getattr(decision, "chip_opportunity_forecast", None) else "UNAVAILABLE")).upper()
    if forecast not in {"AVAILABLE", "PARTIAL", "UNAVAILABLE", "STALE"}:
        forecast = "UNAVAILABLE"
    notes = _optional_notes(inputs.chip_state, market, inputs.market_coverage, price, forecast)
    common = dict(
        fpl_sync_timestamp=_timestamp(inputs.fpl_sync_timestamp),
        analysis_timestamp=_timestamp(inputs.analysis_timestamp) or (decision.created_at if decision else None),
        prediction_timestamp=prediction,
        selected_gameweek=selected_gw,
        deadline=inputs.deadline,
        artifact_status=artifact,
        decision_status=decision_status,
        chip_status=inputs.chip_state,
        market_status=market,
        market_coverage=inputs.market_coverage,
        price_signal_status=price,
        archive_status=inputs.archive_status,
        chip_forecast_status=forecast,
        optional_notes=notes,
    )
    if decision is None and (inputs.material_state_changed or inputs.projection_changed):
        return AnalysisTrustViewModel(AnalysisTrustStatus.STALE, False, "DATA STATUS: STALE", "The active analysis no longer matches the selected account state or projection run.", "Run a new analysis for the current selection.", False, context_status="STALE", **common)
    if decision is None:
        return AnalysisTrustViewModel(AnalysisTrustStatus.PARTIAL, False, "DATA STATUS: PARTIAL", "No Decision report is active.", None, False, context_status="NOT RUN", **common)
    if decision.legacy_unverified or report_context is None:
        return AnalysisTrustViewModel(AnalysisTrustStatus.LEGACY_UNVERIFIED, inputs.historical, "DATA STATUS: LEGACY / UNVERIFIED", "This analysis predates verified PlanningContext support.", "Run a new analysis before relying on this recommendation.", False, context_status="LEGACY / UNVERIFIED", **common)
    if decision.external_mutations:
        return AnalysisTrustViewModel(AnalysisTrustStatus.INVALID, inputs.historical, "DATA STATUS: INVALID", "The Decision report failed its read-only safety check.", "This recommendation is not valid for display.", False, context_status="INVALID", **common)
    if inputs.artifact_verified is False:
        return AnalysisTrustViewModel(AnalysisTrustStatus.INVALID, inputs.historical, "DATA STATUS: INVALID", "Projection/report artifacts failed integrity verification.", inputs.artifact_error or "Run a new analysis from a verified production bundle.", False, context_status="UNAVAILABLE", **common)
    if inputs.historical:
        return AnalysisTrustViewModel(AnalysisTrustStatus.VERIFIED, True, "DATA STATUS: VERIFIED HISTORICAL", "Historical integrity verified against its saved PlanningContext.", None, True, context_status="HISTORICAL MATCH", **common)
    if inputs.material_state_changed:
        return AnalysisTrustViewModel(AnalysisTrustStatus.STALE, False, "DATA STATUS: STALE", "FPL account state changed after this analysis.", "Run a new analysis for the current squad.", False, context_status="STALE ACCOUNT STATE", **common)
    if inputs.projection_changed or selected_gw != report_context.gameweek or inputs.selected_season != report_context.season:
        return AnalysisTrustViewModel(AnalysisTrustStatus.STALE, False, "DATA STATUS: STALE", "The selected projection run or gameweek differs from this analysis.", "Select the matching run or run a new analysis.", False, context_status="STALE SELECTION", **common)
    if inputs.current_context is None:
        return AnalysisTrustViewModel(AnalysisTrustStatus.INVALID, False, "DATA STATUS: INVALID", "Current PlanningContext could not be verified.", inputs.artifact_error or "This recommendation is not valid for the current squad.", False, context_status="UNAVAILABLE", **common)
    if inputs.current_context.context_id != report_context.context_id:
        return AnalysisTrustViewModel(AnalysisTrustStatus.INVALID, False, "DATA STATUS: INVALID", "Planning context mismatch.", "This recommendation is not valid for the current squad.", False, context_status="MISMATCH", **common)
    return AnalysisTrustViewModel(AnalysisTrustStatus.VERIFIED, False, "DATA STATUS: VERIFIED", "FPL sync, projections, and PlanningContext match.", None, True, context_status="MATCH", **common)
