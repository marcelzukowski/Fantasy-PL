import importlib

from .context import *
from .context import (
    PlanningContext, PlanningContextError, ProjectionArtifactIntegrityError,
    ProjectionArtifactIntegrity, build_planning_context, context_from_report,
    verify_projection_artifacts,
)

__all__ = [
    "PlanningContext", "PlanningContextError", "ProjectionArtifactIntegrityError",
    "ProjectionArtifactIntegrity", "build_planning_context", "context_from_report",
    "verify_projection_artifacts", "DecisionInput", "DecisionInputCache",
    "DecisionInputDiagnostics", "DecisionInputError", "CHIP_OPPORTUNITY_FORECAST_SCHEMA_V1",
    "ChipForecastStatus", "ChipOpportunity", "ChipOpportunityForecast",
    "ChipOpportunityForecastCache", "ChipOpportunityForecastConfig",
    "ChipOpportunityForecastError", "build_chip_opportunity_forecast",
    "load_chip_opportunity_forecast", "write_chip_opportunity_forecast", "AppearanceType", "PlayerMinutesAppearance", "PlayerMinutesFeatures", "PlayerMinutesHistorySnapshot", "PlayerMinutesHistoryError", "PLAYER_MINUTES_HISTORY_SCHEMA_V1", "appearances_from_official_element_history", "build_player_minutes_history_snapshot", "recent_minutes_evidence", "load_player_minutes_history_snapshot", "write_player_minutes_history_snapshot", "OFFICIAL_PLAYER_HISTORY_ACQUISITION_SCHEMA_V1", "DEFAULT_HISTORY_CACHE_TTL", "OfficialPlayerHistoryError", "OfficialPlayerHistoryAcquisition", "OfficialPlayerHistoryAcquirer", "write_official_player_history_acquisition", "AvailabilityStatus", "RiskLevel", "ConfidenceLevel", "FreshnessStatus", "RecentMinutesEvidence", "PlayerAvailabilityRisk", "PlayerAvailabilitySnapshot", "PlayerAvailabilityRiskError", "PLAYER_AVAILABILITY_SNAPSHOT_SCHEMA_V1", "build_player_availability_risks", "build_player_availability_snapshot", "load_player_availability_snapshot", "write_player_availability_snapshot",
]
_DECISION_INPUT_EXPORTS = {"DecisionInput", "DecisionInputCache", "DecisionInputDiagnostics", "DecisionInputError"}
_MINUTES_HISTORY_EXPORTS = {"AppearanceType", "PlayerMinutesAppearance", "PlayerMinutesFeatures", "PlayerMinutesHistorySnapshot", "PlayerMinutesHistoryError", "PLAYER_MINUTES_HISTORY_SCHEMA_V1", "appearances_from_official_element_history", "build_player_minutes_history_snapshot", "recent_minutes_evidence", "load_player_minutes_history_snapshot", "write_player_minutes_history_snapshot"}
_OFFICIAL_HISTORY_EXPORTS = {"OFFICIAL_PLAYER_HISTORY_ACQUISITION_SCHEMA_V1", "DEFAULT_HISTORY_CACHE_TTL", "OfficialPlayerHistoryError", "OfficialPlayerHistoryAcquisition", "OfficialPlayerHistoryAcquirer", "write_official_player_history_acquisition"}
_RISK_EXPORTS = {"AvailabilityStatus", "RiskLevel", "ConfidenceLevel", "FreshnessStatus", "RecentMinutesEvidence", "PlayerAvailabilityRisk", "PlayerAvailabilitySnapshot", "PlayerAvailabilityRiskError", "PLAYER_AVAILABILITY_SNAPSHOT_SCHEMA_V1", "build_player_availability_risks", "build_player_availability_snapshot", "load_player_availability_snapshot", "write_player_availability_snapshot"}
_FORECAST_EXPORTS = {"CHIP_OPPORTUNITY_FORECAST_SCHEMA_V1", "ChipForecastStatus", "ChipOpportunity", "ChipOpportunityForecast", "ChipOpportunityForecastCache", "ChipOpportunityForecastConfig", "ChipOpportunityForecastError", "build_chip_opportunity_forecast", "load_chip_opportunity_forecast", "write_chip_opportunity_forecast"}
def __getattr__(name: str):
    if name in _DECISION_INPUT_EXPORTS:
        return getattr(importlib.import_module(".decision_input", __name__), name)
    if name in _MINUTES_HISTORY_EXPORTS:
        return getattr(importlib.import_module(".player_minutes_history", __name__), name)
    if name in _OFFICIAL_HISTORY_EXPORTS:
        return getattr(importlib.import_module(".official_player_history", __name__), name)
    if name in _RISK_EXPORTS:
        return getattr(importlib.import_module(".player_availability_risk", __name__), name)
    if name in _FORECAST_EXPORTS:
        return getattr(importlib.import_module(".chip_opportunity_forecast", __name__), name)
    raise AttributeError(name)
