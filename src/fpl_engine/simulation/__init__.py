"""Coherent fixture simulation."""

from .convergence import (
    ROADMAP_SIMULATION_COUNTS,
    ConvergencePlayerResult,
    ConvergenceReport,
    benchmark_convergence,
)
from .fixture import (
    FixtureSimulationResult,
    FixtureSimulator,
    CardEvent,
    GoalEvent,
    PitchState,
    PenaltyEvent,
    PlayerSimulationSummary,
    SimulatedFixture,
    SimulatedPlayerFixture,
    SimulationConfig,
    SimulationDiagnostics,
    goals_conceded_while_on_pitch,
    on_pitch_interval,
)
from .random import SimulationRandom

__all__ = [
    "ConvergencePlayerResult",
    "ConvergenceReport",
    "CardEvent",
    "FixtureSimulationResult",
    "FixtureSimulator",
    "GoalEvent",
    "PitchState",
    "PenaltyEvent",
    "PlayerSimulationSummary",
    "ROADMAP_SIMULATION_COUNTS",
    "SimulatedFixture",
    "SimulatedPlayerFixture",
    "SimulationConfig",
    "SimulationDiagnostics",
    "SimulationRandom",
    "benchmark_convergence",
    "goals_conceded_while_on_pitch",
    "on_pitch_interval",
]
