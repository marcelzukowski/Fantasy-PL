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
    "load_chip_opportunity_forecast", "write_chip_opportunity_forecast",
]
_DECISION_INPUT_EXPORTS = {"DecisionInput", "DecisionInputCache", "DecisionInputDiagnostics", "DecisionInputError"}
_FORECAST_EXPORTS = {"CHIP_OPPORTUNITY_FORECAST_SCHEMA_V1", "ChipForecastStatus", "ChipOpportunity", "ChipOpportunityForecast", "ChipOpportunityForecastCache", "ChipOpportunityForecastConfig", "ChipOpportunityForecastError", "build_chip_opportunity_forecast", "load_chip_opportunity_forecast", "write_chip_opportunity_forecast"}
def __getattr__(name: str):
    if name in _DECISION_INPUT_EXPORTS:
        return getattr(importlib.import_module(".decision_input", __name__), name)
    if name in _FORECAST_EXPORTS:
        return getattr(importlib.import_module(".chip_opportunity_forecast", __name__), name)
    raise AttributeError(name)
