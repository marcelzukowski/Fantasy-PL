"""SIM-002..011 coherent fixture Monte Carlo simulation."""

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
import math
from typing import Mapping, Sequence

import numpy as np

from fpl_engine.models.events import FixtureEventProjection, PlayerFixtureEvents, TeamEventProjection
from fpl_engine.models.team_strength import TeamStrengthResult
from fpl_engine.scoring import FPLScoringEngine, SimulatedPlayerEvents
from fpl_engine.simulation.random import SimulationRandom


@dataclass(frozen=True)
class SimulationConfig:
    simulations_per_fixture: int = 10_000
    random_seed: int = 42
    retain_simulations: bool = False
    point_quantiles: tuple[float, ...] = (0.10, 0.25, 0.50, 0.75, 0.90)
    goal_timing_weights: tuple[float, ...] = (0.15, 0.16, 0.19, 0.17, 0.16, 0.17)

    def __post_init__(self) -> None:
        if self.simulations_per_fixture <= 0:
            raise ValueError("simulations_per_fixture must be positive")
        if self.random_seed < 0:
            raise ValueError("random_seed must be non-negative")
        if not self.point_quantiles or any(not 0 <= value <= 1 for value in self.point_quantiles):
            raise ValueError("point_quantiles must be probabilities")
        if len(self.goal_timing_weights) != 6 or any(value < 0 for value in self.goal_timing_weights) or sum(self.goal_timing_weights) <= 0:
            raise ValueError("goal_timing_weights must contain six non-negative bucket weights")


@dataclass(frozen=True)
class GoalEvent:
    minute: int
    team_id: str
    scorer_id: str | None
    assister_id: str | None
    penalty: bool = False
    own_goal_player_id: str | None = None


@dataclass(frozen=True)
class PenaltyEvent:
    minute: int
    team_id: str
    taker_id: str | None
    outcome: str
    goalkeeper_id: str | None = None


@dataclass(frozen=True)
class CardEvent:
    minute: int
    player_id: str
    card: str


@dataclass(frozen=True)
class SimulatedPlayerFixture:
    simulation_id: int
    fixture_id: str
    player_id: str
    team_id: str
    started: bool
    entry_minute: int | None
    exit_minute: int | None
    minutes: int
    goals: int
    assists: int
    fpl_assists: int
    clean_sheet_eligible: bool
    goals_conceded_while_on_pitch: int
    saves: int
    penalties_faced: int
    penalties_saved: int
    defensive_contributions: int
    yellow_cards: int
    red_cards: int
    own_goals: int
    penalties_missed: int
    bps: int
    bonus: int
    fpl_points: int
    simulation_seed: int


@dataclass(frozen=True)
class SimulatedFixture:
    simulation_id: int
    fixture_id: str
    home_goals: int
    away_goals: int
    goal_events: tuple[GoalEvent, ...]
    penalty_events: tuple[PenaltyEvent, ...]
    card_events: tuple[CardEvent, ...]
    home_shots_on_target: int
    away_shots_on_target: int
    simulation_seed: int


@dataclass(frozen=True)
class PlayerSimulationSummary:
    player_id: str
    fixture_id: str
    expected_points: float
    median_points: float
    points_std: float
    point_quantiles: Mapping[float, float]
    p_blank: float
    p_return: float
    p_5_plus: float
    p_8_plus: float
    p_10_plus: float
    p_15_plus: float
    model_expected_minutes: float
    simulated_expected_minutes: float
    event_means: Mapping[str, float]
    points_histogram: Mapping[int, int]
    simulation_count: int
    random_seed: int
    derived_fixture_seed: int
    simulator_version: str
    scoring_version: int
    dataset_version: str
    feature_version: str
    event_completeness: float = 1.0


@dataclass(frozen=True)
class SimulationDiagnostics:
    sampled_home_goals: int
    sampled_away_goals: int
    allocated_home_player_goals: int
    allocated_away_player_goals: int
    unallocated_home_goals: int
    unallocated_away_goals: int
    goal_allocation_violations: int
    off_pitch_event_violations: int
    self_assist_violations: int
    save_coherence_violations: int


@dataclass(frozen=True)
class FixtureSimulationResult:
    fixture_id: str
    prediction_timestamp: datetime
    summaries: tuple[PlayerSimulationSummary, ...]
    diagnostics: SimulationDiagnostics
    simulation_count: int
    random_seed: int
    derived_fixture_seed: int
    simulator_version: str
    model_version: str
    scoring_version: int
    fixtures: tuple[SimulatedFixture, ...] = ()
    player_rows: tuple[SimulatedPlayerFixture, ...] = ()


@dataclass(frozen=True)
class PitchState:
    started: bool
    entry: int | None
    exit: int | None
    minutes: int


def on_pitch_interval(minutes: int, started: bool) -> tuple[int | None, int | None]:
    """Return regulation-minute boundaries; added time is represented as 90."""
    if not 0 <= minutes <= 90:
        raise ValueError("minutes must be in [0, 90]")
    if minutes == 0:
        return None, None
    return (0, minutes) if started else (90 - minutes, 90)


def is_on_pitch(state: PitchState, minute: int) -> bool:
    return state.entry is not None and state.exit is not None and state.entry < minute <= state.exit


def goals_conceded_while_on_pitch(
    goal_minutes: Sequence[int], state: PitchState, *, red_card_minute: int | None = None
) -> int:
    """Count opponent goals; a dismissal keeps the player liable until full time."""
    if state.entry is None:
        return 0
    end = 90 if red_card_minute is not None else state.exit
    return sum(state.entry < minute <= end for minute in goal_minutes)


class FixtureSimulator:
    """Create shared fixture states and score them using season rules."""

    VERSION = "fixture_simulator_v1"

    def __init__(self, scoring: FPLScoringEngine, config: SimulationConfig = SimulationConfig()):
        self.scoring = scoring
        self.config = config

    def simulate(
        self, events: FixtureEventProjection, team_strength: TeamStrengthResult
    ) -> FixtureSimulationResult:
        self._validate_inputs(events, team_strength)
        seed_engine = SimulationRandom(self.config.random_seed)
        derived_seed = seed_engine.derived_seed(events.fixture_id)
        rng = seed_engine.generator(events.fixture_id)
        all_players = tuple(events.home.players + events.away.players)
        totals = {
            player.rates.player_id: Counter(
                minutes=0, goals=0, assists=0, returns=0, saves=0,
                penalty_saves=0, penalty_misses=0, clean_sheets=0, conceded=0,
                defcon=0, yellow=0, red=0, bonus=0,
            )
            for player in all_players
        }
        points = {player.rates.player_id: [] for player in all_players}
        raw_fixtures: list[SimulatedFixture] = []
        raw_players: list[SimulatedPlayerFixture] = []
        diag = Counter()

        score_probabilities = np.asarray(team_strength.score_distribution, dtype=float)
        flat_scores = score_probabilities.ravel()
        flat_scores = flat_scores / flat_scores.sum()
        dimensions = score_probabilities.shape

        for simulation_id in range(self.config.simulations_per_fixture):
            flat_index = int(rng.choice(flat_scores.size, p=flat_scores))
            home_goals, away_goals = (int(value) for value in np.unravel_index(flat_index, dimensions))
            diag["home_goals"] += home_goals
            diag["away_goals"] += away_goals

            pitch = {}
            pitch.update(self._sample_team_minutes(events.home, rng))
            pitch.update(self._sample_team_minutes(events.away, rng))
            home_times = tuple(sorted(self._sample_goal_minute(rng) for _ in range(home_goals)))
            away_times = tuple(sorted(self._sample_goal_minute(rng) for _ in range(away_goals)))
            counters = {player.rates.player_id: Counter() for player in all_players}
            goal_events: list[GoalEvent] = []
            penalty_events: list[PenaltyEvent] = []
            card_events: list[CardEvent] = []
            red_minutes: dict[str, int | None] = {}
            for player in all_players:
                pid = player.rates.player_id
                state = pitch[pid]
                if state.minutes == 0:
                    red_minutes[pid] = None
                    continue
                counters[pid]["yellow"] = int(rng.random() < player.cards.p_yellow)
                counters[pid]["red"] = int(rng.random() < player.cards.p_red)
                red_minutes[pid] = (
                    int(rng.integers(state.entry + 1, state.exit + 1))
                    if counters[pid]["red"] and state.entry is not None and state.exit is not None
                    else None
                )
                if counters[pid]["yellow"]:
                    card_end = red_minutes[pid] or state.exit
                    card_events.append(CardEvent(int(rng.integers(state.entry + 1, card_end + 1)), pid, "yellow"))
                if red_minutes[pid] is not None:
                    card_events.append(CardEvent(red_minutes[pid], pid, "red"))
                distribution = player.defensive_contributions.defcon_distribution
                if distribution is not None:
                    sampled_defcon = self._sample_distribution(distribution, rng)
                    if red_minutes[pid] is not None:
                        actual_minutes = red_minutes[pid] - state.entry
                        sampled_defcon = int(rng.binomial(sampled_defcon, actual_minutes / state.minutes))
                    counters[pid]["defcon"] = sampled_defcon
                if red_minutes[pid] is not None:
                    actual_minutes = red_minutes[pid] - state.entry
                    pitch[pid] = PitchState(state.started, state.entry, red_minutes[pid], actual_minutes)

            for team, opponent, times in (
                (events.home, events.away, home_times),
                (events.away, events.home, away_times),
            ):
                for minute in times:
                    goal = self._allocate_goal(team, opponent, minute, pitch, red_minutes, rng)
                    goal_events.append(goal)
                    if goal.scorer_id is not None:
                        counters[goal.scorer_id]["goals"] += 1
                        counters[goal.scorer_id]["penalty_goals"] += int(goal.penalty)
                    else:
                        diag[f"unallocated_{'home' if team is events.home else 'away'}"] += 1
                    if goal.assister_id is not None:
                        counters[goal.assister_id]["assists"] += 1
                    if goal.own_goal_player_id is not None:
                        counters[goal.own_goal_player_id]["own_goals"] += 1
                    if goal.penalty:
                        keepers = [
                            player for player in opponent.players
                            if player.rates.position == "GK"
                            and self._event_eligible(pitch[player.rates.player_id], red_minutes[player.rates.player_id], minute)
                        ]
                        goalkeeper_id = keepers[0].rates.player_id if keepers else None
                        if goalkeeper_id is not None:
                            counters[goalkeeper_id]["penalties_faced"] += 1
                        penalty_events.append(PenaltyEvent(
                            minute, team.team_id, goal.scorer_id, "goal", goalkeeper_id
                        ))

            for penalty_event in (
                self._sample_missed_penalty(events.home, events.away, pitch, red_minutes, counters, rng),
                self._sample_missed_penalty(events.away, events.home, pitch, red_minutes, counters, rng),
            ):
                if penalty_event is not None:
                    penalty_events.append(penalty_event)

            for goalkeeper in all_players:
                if goalkeeper.rates.position != "GK" or pitch[goalkeeper.rates.player_id].minutes == 0:
                    continue
                distribution = goalkeeper.goalkeeper.save_distribution
                if distribution is not None:
                    counters[goalkeeper.rates.player_id]["saves"] += self._sample_distribution(distribution, rng)

            goal_minutes_by_team = {
                events.home.team_id: away_times,
                events.away.team_id: home_times,
            }
            score_events: dict[str, SimulatedPlayerEvents] = {}
            for player in all_players:
                pid = player.rates.player_id
                state = pitch[pid]
                conceded = goals_conceded_while_on_pitch(
                    goal_minutes_by_team[player.rates.team_id], state, red_card_minute=red_minutes[pid]
                )
                save_count = int(counters[pid]["saves"])
                score_events[pid] = SimulatedPlayerEvents(
                    player_id=pid,
                    fixture_id=events.fixture_id,
                    position=player.rates.position,
                    minutes=state.minutes,
                    goals=int(counters[pid]["goals"]),
                    penalty_goals=int(counters[pid]["penalty_goals"]),
                    assists=int(counters[pid]["assists"]),
                    goals_conceded_while_on_pitch=conceded,
                    saves=save_count,
                    saves_inside_box=save_count,
                    saves_big_chance=int(counters[pid]["penalty_saves"]),
                    penalty_saves=int(counters[pid]["penalty_saves"]),
                    penalty_misses=int(counters[pid]["penalty_misses"]),
                    yellow_cards=int(counters[pid]["yellow"]),
                    red_cards=int(counters[pid]["red"]),
                    own_goals=int(counters[pid]["own_goals"]),
                    defensive_contributions=int(counters[pid]["defcon"]),
                    unavailable_bps_components=(
                        "cbi_breakdown", "recoveries", "tackles", "crosses", "chances_created",
                        "dribbles", "shots_on_target", "passes", "goal_line_clearances", "errors",
                    ),
                )

            bps = {pid: self.scoring.calculate_bps(row) for pid, row in score_events.items() if row.minutes > 0}
            bonus = self.scoring.allocate_bonus(bps)
            for player in all_players:
                pid = player.rates.player_id
                state = pitch[pid]
                result = self.scoring.score(score_events[pid], bonus_points=bonus.get(pid, 0))
                counter = counters[pid]
                totals[pid].update(
                    minutes=state.minutes,
                    goals=counter["goals"],
                    assists=counter["assists"],
                    returns=int(counter["goals"] + counter["assists"] > 0),
                    saves=counter["saves"],
                    penalty_saves=counter["penalty_saves"],
                    penalty_misses=counter["penalty_misses"],
                    clean_sheets=int(state.minutes >= 60 and score_events[pid].goals_conceded_while_on_pitch == 0),
                    conceded=score_events[pid].goals_conceded_while_on_pitch,
                    defcon=counter["defcon"],
                    yellow=counter["yellow"],
                    red=counter["red"],
                    bonus=bonus.get(pid, 0),
                )
                points[pid].append(result.total_points)
                if self.config.retain_simulations:
                    raw_players.append(SimulatedPlayerFixture(
                        simulation_id, events.fixture_id, pid, player.rates.team_id,
                        state.started, state.entry, state.exit, state.minutes,
                        int(counter["goals"]), int(counter["assists"]), int(counter["assists"]),
                        state.minutes >= 60 and score_events[pid].goals_conceded_while_on_pitch == 0,
                        score_events[pid].goals_conceded_while_on_pitch, int(counter["saves"]),
                        int(counter["penalties_faced"]), int(counter["penalty_saves"]),
                        int(counter["defcon"]), int(counter["yellow"]), int(counter["red"]),
                        int(counter["own_goals"]), int(counter["penalty_misses"]),
                        bps.get(pid, 0), bonus.get(pid, 0), result.total_points, derived_seed,
                    ))

            allocated_home = sum(counters[p.rates.player_id]["goals"] for p in events.home.players)
            allocated_away = sum(counters[p.rates.player_id]["goals"] for p in events.away.players)
            diag["allocated_home"] += allocated_home
            diag["allocated_away"] += allocated_away
            if allocated_home + sum(g.scorer_id is None for g in goal_events if g.team_id == events.home.team_id) != home_goals:
                diag["goal_violations"] += 1
            if allocated_away + sum(g.scorer_id is None for g in goal_events if g.team_id == events.away.team_id) != away_goals:
                diag["goal_violations"] += 1
            for goal in goal_events:
                if goal.scorer_id is not None and not self._event_eligible(
                    pitch[goal.scorer_id], red_minutes[goal.scorer_id], goal.minute
                ):
                    diag["off_pitch"] += 1
                if goal.assister_id is not None and not self._event_eligible(
                    pitch[goal.assister_id], red_minutes[goal.assister_id], goal.minute
                ):
                    diag["off_pitch"] += 1
                if goal.scorer_id is not None and goal.scorer_id == goal.assister_id:
                    diag["self_assist"] += 1

            home_saves = sum(counters[p.rates.player_id]["saves"] for p in events.away.players if p.rates.position == "GK")
            away_saves = sum(counters[p.rates.player_id]["saves"] for p in events.home.players if p.rates.position == "GK")
            home_sot = home_goals + home_saves
            away_sot = away_goals + away_saves
            if home_sot < home_goals or away_sot < away_goals:
                diag["save_violations"] += 1
            if self.config.retain_simulations:
                raw_fixtures.append(SimulatedFixture(
                    simulation_id, events.fixture_id, home_goals, away_goals,
                    tuple(sorted(goal_events, key=lambda event: event.minute)),
                    tuple(sorted(penalty_events, key=lambda event: event.minute)),
                    tuple(sorted(card_events, key=lambda event: event.minute)),
                    home_sot, away_sot, derived_seed,
                ))

        summaries = tuple(
            self._summarize(player, totals[player.rates.player_id], points[player.rates.player_id], derived_seed)
            for player in sorted(all_players, key=lambda value: value.rates.player_id)
        )
        return FixtureSimulationResult(
            events.fixture_id, events.prediction_timestamp, summaries,
            SimulationDiagnostics(
                diag["home_goals"], diag["away_goals"], diag["allocated_home"], diag["allocated_away"],
                diag["unallocated_home"], diag["unallocated_away"], diag["goal_violations"],
                diag["off_pitch"], diag["self_assist"], diag["save_violations"],
            ),
            self.config.simulations_per_fixture, self.config.random_seed, derived_seed,
            self.VERSION, events.model_version, self.scoring.version,
            tuple(raw_fixtures), tuple(raw_players),
        )

    def _sample_team_minutes(self, team: TeamEventProjection, rng: np.random.Generator) -> dict[str, PitchState]:
        players = team.players
        appearing = [player for player in players if rng.random() < player.rates.p_appearance]
        target_starters = min(11, len(appearing))
        starters: set[str] = set()
        goalkeepers = [player for player in appearing if player.rates.position == "GK"]
        if goalkeepers and target_starters:
            weights = np.asarray([max(player.rates.p_start, 1e-9) for player in goalkeepers], dtype=float)
            starters.add(goalkeepers[int(rng.choice(len(goalkeepers), p=weights / weights.sum()))].rates.player_id)
        candidates = [
            player for player in appearing
            if player.rates.player_id not in starters and player.rates.position != "GK"
        ]
        remaining = target_starters - len(starters)
        if remaining:
            keys = [
                (rng.random() ** (1 / max(player.rates.p_start, 1e-9)), player.rates.player_id)
                for player in candidates
            ]
            starters.update(player_id for _, player_id in sorted(keys, reverse=True)[:remaining])
        result = {}
        appearing_ids = {player.rates.player_id for player in appearing}
        for player in players:
            pid = player.rates.player_id
            started = pid in starters
            if pid not in appearing_ids:
                minutes = 0
            else:
                distribution = (
                    player.rates.starter_minutes_distribution if started
                    else player.rates.bench_minutes_distribution
                )
                minutes = self._sample_distribution(distribution, rng)
                if minutes == 0:
                    fallback = player.rates.minute_distribution
                    positive = np.asarray(fallback[1:], dtype=float)
                    minutes = int(rng.choice(np.arange(1, 91), p=positive / positive.sum())) if positive.sum() else 1
            entry, exit_minute = on_pitch_interval(minutes, started)
            result[pid] = PitchState(started, entry, exit_minute, minutes)
        return result

    def _allocate_goal(
        self, team: TeamEventProjection, opponent: TeamEventProjection, minute: int,
        pitch: Mapping[str, PitchState], red_minutes: Mapping[str, int | None], rng: np.random.Generator,
    ) -> GoalEvent:
        penalty_expected = sum(player.penalty.expected_penalty_goals for player in team.players)
        penalty = team.expected_team_goals > 0 and rng.random() < min(1.0, penalty_expected / team.expected_team_goals)
        own_goal = not penalty and team.expected_team_goals > 0 and rng.random() < min(
            1.0, team.own_goal_expected_goals / team.expected_team_goals
        )
        own_goal_player = None
        if own_goal:
            eligible_opponents = [
                player for player in opponent.players
                if self._event_eligible(pitch[player.rates.player_id], red_minutes[player.rates.player_id], minute)
            ]
            if eligible_opponents:
                own_goal_player = eligible_opponents[int(rng.integers(len(eligible_opponents)))].rates.player_id
            return GoalEvent(minute, team.team_id, None, None, False, own_goal_player)

        eligible = [
            player for player in team.players
            if self._event_eligible(pitch[player.rates.player_id], red_minutes[player.rates.player_id], minute)
        ]
        weights = [
            player.penalty.expected_penalty_goals if penalty else player.goals.expected_open_play_goals
            for player in eligible
        ]
        unassigned = max(team.unassigned_expected_goals, 0.0)
        scorer = self._weighted_player_or_none(eligible, weights, unassigned, rng)
        if scorer is None:
            return GoalEvent(minute, team.team_id, None, None, penalty)

        assister = None
        if not penalty:
            assist_probability = min(1.0, team.expected_team_assists / max(team.allocated_player_goals, 1e-12))
            if rng.random() < assist_probability:
                candidates = [
                    player for player in eligible if player.rates.player_id != scorer.rates.player_id
                ]
                assist_weights = [player.assists.expected_assists for player in candidates]
                selected = self._weighted_player_or_none(
                    candidates, assist_weights, team.unassigned_expected_assists, rng
                )
                assister = selected.rates.player_id if selected is not None else None
        return GoalEvent(minute, team.team_id, scorer.rates.player_id, assister, penalty)

    def _sample_missed_penalty(
        self, team: TeamEventProjection, opponent: TeamEventProjection,
        pitch: Mapping[str, PitchState], red_minutes: Mapping[str, int | None],
        counters: Mapping[str, Counter], rng: np.random.Generator,
    ) -> PenaltyEvent | None:
        probability = min(1.0, sum(player.penalty.miss_probability for player in team.players))
        if rng.random() >= probability:
            return None
        minute = int(rng.integers(1, 91))
        candidates = [
            player for player in team.players
            if self._event_eligible(pitch[player.rates.player_id], red_minutes[player.rates.player_id], minute)
        ]
        selected = self._weighted_player_or_none(
            candidates, [player.penalty.taker_selection_probability for player in candidates], 0.0, rng
        )
        if selected is None:
            return PenaltyEvent(minute, team.team_id, None, "unassigned_miss")
        counters[selected.rates.player_id]["penalty_misses"] += 1
        keepers = [
            player for player in opponent.players
            if player.rates.position == "GK"
            and self._event_eligible(pitch[player.rates.player_id], red_minutes[player.rates.player_id], minute)
        ]
        if not keepers:
            return PenaltyEvent(minute, team.team_id, selected.rates.player_id, "miss")
        keeper = keepers[0]
        counters[keeper.rates.player_id]["penalties_faced"] += 1
        save_probability = keeper.goalkeeper.p_penalty_saved_given_faced or 0.0
        if rng.random() < save_probability:
            counters[keeper.rates.player_id]["penalty_saves"] += 1
            counters[keeper.rates.player_id]["saves"] += 1
            return PenaltyEvent(minute, team.team_id, selected.rates.player_id, "saved", keeper.rates.player_id)
        return PenaltyEvent(minute, team.team_id, selected.rates.player_id, "miss", keeper.rates.player_id)

    def _sample_goal_minute(self, rng: np.random.Generator) -> int:
        buckets = ((1, 15), (16, 30), (31, 45), (46, 60), (61, 75), (76, 90))
        probabilities = np.asarray(self.config.goal_timing_weights, dtype=float)
        lower, upper = buckets[int(rng.choice(6, p=probabilities / probabilities.sum()))]
        return int(rng.integers(lower, upper + 1))

    @staticmethod
    def _event_eligible(state: PitchState, red_card_minute: int | None, minute: int) -> bool:
        return is_on_pitch(state, minute) and (red_card_minute is None or minute <= red_card_minute)

    @staticmethod
    def _sample_distribution(distribution: Sequence[float], rng: np.random.Generator) -> int:
        probabilities = np.asarray(distribution, dtype=float)
        if probabilities.ndim != 1 or len(probabilities) == 0 or np.any(probabilities < 0):
            raise ValueError("invalid discrete probability distribution")
        total = probabilities.sum()
        if not math.isfinite(float(total)) or total <= 0:
            raise ValueError("probability distribution has no mass")
        return int(rng.choice(len(probabilities), p=probabilities / total))

    @staticmethod
    def _weighted_player_or_none(players, weights, unassigned, rng):
        probabilities = np.asarray([max(0.0, float(value)) for value in weights] + [max(0.0, unassigned)], dtype=float)
        if probabilities.sum() <= 0:
            return None
        index = int(rng.choice(len(probabilities), p=probabilities / probabilities.sum()))
        return None if index == len(players) else players[index]

    def _summarize(self, player: PlayerFixtureEvents, totals: Counter, values: list[int], seed: int) -> PlayerSimulationSummary:
        samples = np.asarray(values, dtype=float)
        count = self.config.simulations_per_fixture
        event_names = (
            "goals", "assists", "saves", "penalty_saves", "penalty_misses",
            "clean_sheets", "conceded", "defcon", "yellow", "red", "bonus",
        )
        return PlayerSimulationSummary(
            player.rates.player_id, player.rates.fixture_id,
            float(samples.mean()), float(np.median(samples)), float(samples.std(ddof=0)),
            {q: float(np.quantile(samples, q)) for q in self.config.point_quantiles},
            1 - totals["returns"] / count, totals["returns"] / count,
            float(np.mean(samples >= 5)), float(np.mean(samples >= 8)),
            float(np.mean(samples >= 10)), float(np.mean(samples >= 15)),
            player.rates.expected_minutes, totals["minutes"] / count,
            {name: totals[name] / count for name in event_names},
            dict(sorted(Counter(int(value) for value in values).items())), count,
            self.config.random_seed, seed, self.VERSION, self.scoring.version,
            player.dataset_version, player.feature_version, .5,
        )

    @staticmethod
    def _validate_inputs(events: FixtureEventProjection, strength: TeamStrengthResult) -> None:
        if events.prediction_timestamp.tzinfo is None or strength.prediction_timestamp.tzinfo is None:
            raise ValueError("prediction timestamps must be aware")
        event_time = events.prediction_timestamp.astimezone(timezone.utc)
        strength_time = strength.prediction_timestamp.astimezone(timezone.utc)
        if event_time != strength_time:
            raise ValueError("event and team-strength timestamps differ")
        if events.home.team_id != strength.home_team_id or events.away.team_id != strength.away_team_id:
            raise ValueError("event and team-strength teams differ")
        if not events.fixture_id or events.home.fixture_id != events.fixture_id or events.away.fixture_id != events.fixture_id:
            raise ValueError("fixture identities differ")
        score_distribution = np.asarray(strength.score_distribution, dtype=float)
        if (
            score_distribution.ndim != 2 or score_distribution.size == 0
            or np.any(~np.isfinite(score_distribution)) or np.any(score_distribution < 0)
            or score_distribution.sum() <= 0
        ):
            raise ValueError("joint score distribution is invalid")
        player_ids = [player.rates.player_id for player in events.home.players + events.away.players]
        if len(player_ids) != len(set(player_ids)):
            raise ValueError("player IDs must be unique within a fixture")
        for team in (events.home, events.away):
            for player in team.players:
                rates = player.rates
                if rates.team_id != team.team_id or rates.fixture_id != events.fixture_id:
                    raise ValueError("player event identity differs from fixture context")
                if rates.prediction_timestamp.tzinfo is None or rates.prediction_timestamp.astimezone(timezone.utc) != event_time:
                    raise ValueError("player event timestamp differs from fixture context")
