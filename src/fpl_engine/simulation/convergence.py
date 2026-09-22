"""SIM-012 simulation-count convergence benchmark."""

from dataclasses import dataclass, replace
from typing import Iterable

from fpl_engine.models.events import FixtureEventProjection
from fpl_engine.models.team_strength import TeamStrengthResult
from fpl_engine.simulation.fixture import FixtureSimulator, SimulationConfig


ROADMAP_SIMULATION_COUNTS = (1_000, 5_000, 10_000, 25_000)


@dataclass(frozen=True)
class ConvergencePlayerResult:
    player_id: str
    simulation_count: int
    expected_points: float
    p_return: float
    p_10_plus: float
    expected_points_delta: float
    p_return_delta: float
    p_10_plus_delta: float
    rank: int
    reference_rank: int
    rank_delta: int


@dataclass(frozen=True)
class ConvergenceReport:
    fixture_id: str
    counts: tuple[int, ...]
    rows: tuple[ConvergencePlayerResult, ...]
    reference_count: int
    recommended_count: int | None
    tolerance: float


def benchmark_convergence(
    simulator: FixtureSimulator,
    events: FixtureEventProjection,
    team_strength: TeamStrengthResult,
    *,
    counts: Iterable[int] = ROADMAP_SIMULATION_COUNTS,
    tolerance: float = 0.05,
) -> ConvergenceReport:
    """Compare each requested count with the largest deterministic reference run."""
    normalized = tuple(sorted(set(int(value) for value in counts)))
    if not normalized or normalized[0] <= 0:
        raise ValueError("counts must contain positive integers")
    if tolerance < 0:
        raise ValueError("tolerance must be non-negative")
    results = {}
    for count in normalized:
        config = replace(simulator.config, simulations_per_fixture=count, retain_simulations=False)
        result = FixtureSimulator(simulator.scoring, config).simulate(events, team_strength)
        results[count] = {summary.player_id: summary for summary in result.summaries}
    reference_count = normalized[-1]
    reference = results[reference_count]
    ranks = {
        count: {
            player_id: rank for rank, player_id in enumerate(
                sorted(result, key=lambda player_id: (-result[player_id].expected_points, player_id)),
                start=1,
            )
        }
        for count, result in results.items()
    }
    rows = []
    recommended = None
    for count in normalized:
        stable = True
        for player_id in sorted(reference):
            current = results[count][player_id]
            target = reference[player_id]
            deltas = (
                abs(current.expected_points - target.expected_points),
                abs(current.p_return - target.p_return),
                abs(current.p_10_plus - target.p_10_plus),
            )
            stable = stable and max(deltas) <= tolerance
            rows.append(ConvergencePlayerResult(
                player_id, count, current.expected_points, current.p_return, current.p_10_plus,
                deltas[0], deltas[1], deltas[2],
                ranks[count][player_id], ranks[reference_count][player_id],
                ranks[count][player_id]-ranks[reference_count][player_id],
            ))
        if stable and recommended is None:
            recommended = count
    return ConvergenceReport(
        events.fixture_id, normalized, tuple(rows), reference_count, recommended, tolerance
    )
