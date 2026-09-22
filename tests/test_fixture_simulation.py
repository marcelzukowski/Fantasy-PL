from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from fpl_engine.models.events import (
    AssistEvents, BaseBpsParameters, CardEvents, CleanSheetEvents,
    DefensiveContributionEvents, FixtureEventProjection, GoalEvents,
    GoalkeeperEvents, PenaltyProcess, PlayerFixtureEvents, PlayerFixtureRate,
    TeamEventProjection,
)
from fpl_engine.models.team_strength.model import TeamEstimate, TeamStrengthResult
from fpl_engine.scoring import FPLScoringEngine
from fpl_engine.simulation import (
    ROADMAP_SIMULATION_COUNTS, FixtureSimulator, PitchState, SimulationConfig,
    SimulationRandom, benchmark_convergence, goals_conceded_while_on_pitch,
)


AT = datetime(2026, 9, 1, 12, tzinfo=timezone.utc)
ROOT = Path(__file__).resolve().parents[1]


def discrete(index, length=91):
    values = [0.0] * length
    values[index] = 1.0
    return tuple(values)


def player(pid, team, position, *, goals=.0, assists=.0, minutes=90, p_start=1.0,
           saves=0, defcon=0, yellow=0.0, red=0.0):
    rate = PlayerFixtureRate(
        pid, team, "fixture", AT, position, 1.0, p_start, float(minutes),
        discrete(minutes), discrete(minutes), discrete(minutes),
        goals * 90 / max(minutes, 1), 0.0, assists * 90 / max(minutes, 1),
        1.0, 0.5, float(defcon) * 90 / max(minutes, 1), goals, assists, 0.1, 0.9,
    )
    goalkeeper = GoalkeeperEvents(
        float(saves) if position == "GK" else None,
        discrete(saves, 13) if position == "GK" else None,
        float(saves >= 3) if position == "GK" else None,
        float(saves >= 6) if position == "GK" else None,
        float(saves >= 9) if position == "GK" else None,
        0.0 if position == "GK" else None,
        0.0 if position == "GK" else None,
        0.0 if position == "GK" else None,
        False,
    )
    defensive = DefensiveContributionEvents(float(defcon), discrete(defcon, 20))
    return PlayerFixtureEvents(
        rate, PenaltyProcess(0, 0, .78, 0, 0),
        GoalEvents(goals, goals, 0, min(1, goals), discrete(0, 6)),
        AssistEvents(assists, min(1, assists), discrete(0, 5)),
        CleanSheetEvents(.5, .5, 1, 1), goalkeeper, defensive,
        CardEvents(yellow, red, "test", "test"),
        BaseBpsParameters(goals, assists, .5, goalkeeper.expected_saves, float(defcon),
                          yellow, red, float(minutes), None, 0, 0, 1),
        .1, .9, "events-v1", "dataset-v1", "features-v1",
    )


def fixture(*, home_goals=2, away_goals=1, minutes=90):
    home_players = (
        player("home_gk", "home", "GK", minutes=minutes, saves=2),
        player("home_scorer", "home", "FWD", goals=1.6, minutes=minutes),
        player("home_creator", "home", "MID", goals=.4, assists=1.4, minutes=minutes),
    )
    away_players = (
        player("away_gk", "away", "GK", minutes=minutes, saves=3),
        player("away_scorer", "away", "FWD", goals=.8, minutes=minutes),
        player("away_creator", "away", "MID", goals=.2, assists=.7, minutes=minutes),
    )
    home = TeamEventProjection("fixture", "home", AT, float(home_goals), float(home_goals), 0, 0,
                               1.4, 0, 1, home_players)
    away = TeamEventProjection("fixture", "away", AT, float(away_goals), float(away_goals), 0, 0,
                               .7, 0, 1, away_players)
    max_goals = max(home_goals, away_goals) + 1
    matrix = [[0.0] * max_goals for _ in range(max_goals)]
    matrix[home_goals][away_goals] = 1.0
    estimate = TeamEstimate(1, 1, 10, 10, .9)
    strength = TeamStrengthResult("home", "away", float(home_goals), float(away_goals), estimate, estimate,
                                  tuple(tuple(row) for row in matrix), float(away_goals == 0),
                                  float(home_goals == 0), AT, "strength-v1")
    return FixtureEventProjection("fixture", AT, home, away), strength


def simulator(count=300, seed=42, retain=True):
    return FixtureSimulator(
        FPLScoringEngine.from_project(ROOT),
        SimulationConfig(count, seed, retain),
    )


def test_random_engine_is_reproducible_and_fixture_scoped():
    first = SimulationRandom(42)
    assert first.derived_seed("a") == SimulationRandom(42).derived_seed("a")
    assert first.derived_seed("a") != first.derived_seed("b")
    assert first.generator("a").integers(1_000_000) == SimulationRandom(42).generator("a").integers(1_000_000)


def test_joint_score_goal_and_assist_allocation_are_coherent():
    events, strength = fixture()
    result = simulator().simulate(events, strength)
    by_simulation = {row.simulation_id: [] for row in result.fixtures}
    for row in result.player_rows:
        by_simulation[row.simulation_id].append(row)
    for simulated in result.fixtures:
        assert (simulated.home_goals, simulated.away_goals) == (2, 1)
        rows = by_simulation[simulated.simulation_id]
        for team_id, goals in (("home", 2), ("away", 1)):
            player_goals = sum(row.goals for row in rows if row.team_id == team_id)
            unassigned = sum(goal.scorer_id is None for goal in simulated.goal_events if goal.team_id == team_id)
            assert player_goals + unassigned == goals
        assert all(goal.scorer_id != goal.assister_id for goal in simulated.goal_events if goal.assister_id)
        for goal in simulated.goal_events:
            for participant in (goal.scorer_id, goal.assister_id):
                if participant:
                    row = next(value for value in rows if value.player_id == participant)
                    assert row.entry_minute < goal.minute <= row.exit_minute
        assert simulated.home_shots_on_target >= simulated.home_goals
        assert simulated.away_shots_on_target >= simulated.away_goals
    assert result.diagnostics.goal_allocation_violations == 0
    assert result.diagnostics.off_pitch_event_violations == 0
    assert result.diagnostics.self_assist_violations == 0
    assert result.diagnostics.save_coherence_violations == 0


def test_minutes_follow_supplied_distribution_and_states_are_consistent():
    events, strength = fixture(home_goals=0, away_goals=0, minutes=60)
    result = simulator(40).simulate(events, strength)
    assert all(row.minutes == 60 and row.started and row.entry_minute == 0 and row.exit_minute == 60
               for row in result.player_rows)
    assert all(summary.simulated_expected_minutes == 60 for summary in result.summaries)


def test_joint_lineup_caps_starters_at_eleven_and_selects_one_goalkeeper():
    events, strength = fixture(home_goals=0, away_goals=0)
    squad = tuple(
        [player("home_gk_1", "home", "GK"), player("home_gk_2", "home", "GK", p_start=.2)]
        + [player(f"home_out_{index}", "home", "MID", p_start=.7) for index in range(12)]
    )
    events = replace(events, home=replace(events.home, players=squad))
    result = simulator(20).simulate(events, strength)
    for simulation_id in range(20):
        rows = [row for row in result.player_rows if row.simulation_id == simulation_id and row.team_id == "home"]
        assert sum(row.started for row in rows) == 11
        assert sum(row.started and row.player_id.startswith("home_gk") for row in rows) == 1


def test_scored_penalty_is_classified_inside_sampled_team_score():
    events, strength = fixture(home_goals=1, away_goals=0)
    updated = []
    for row in events.home.players:
        if row.rates.player_id == "home_scorer":
            row = replace(row, penalty=PenaltyProcess(1, 1, 1, 0, 1))
        updated.append(row)
    events = replace(events, home=replace(events.home, players=tuple(updated)))
    result = simulator(20).simulate(events, strength)
    assert all(item.home_goals == 1 and len(item.goal_events) == 1 for item in result.fixtures)
    assert all(item.goal_events[0].penalty for item in result.fixtures)
    assert all(item.penalty_events[0].outcome == "goal" for item in result.fixtures)


def test_unavailable_player_has_zero_minutes_and_points():
    events, strength = fixture(home_goals=1, away_goals=0)
    updated = []
    for row in events.home.players:
        if row.rates.player_id == "home_creator":
            rates = replace(
                row.rates, p_appearance=0, p_start=0, expected_minutes=0,
                minute_distribution=discrete(0), starter_minutes_distribution=discrete(0),
                bench_minutes_distribution=discrete(0),
            )
            row = replace(row, rates=rates)
        updated.append(row)
    events = replace(events, home=replace(events.home, players=tuple(updated)))
    result = simulator(20).simulate(events, strength)
    rows = [row for row in result.player_rows if row.player_id == "home_creator"]
    assert all(row.minutes == 0 and row.fpl_points == 0 and not row.started for row in rows)


def test_unassigned_scorer_is_explicit_instead_of_forced():
    events, strength = fixture(home_goals=1, away_goals=0)
    players = tuple(
        replace(row, goals=replace(row.goals, expected_goals=0, expected_open_play_goals=0))
        for row in events.home.players
    )
    events = replace(events, home=replace(
        events.home, players=players, allocated_player_goals=0,
        unassigned_expected_goals=1, expected_team_assists=0,
    ))
    result = simulator(20).simulate(events, strength)
    assert all(item.goal_events[0].scorer_id is None for item in result.fixtures)
    assert result.diagnostics.unallocated_home_goals == 20
    assert result.diagnostics.allocated_home_player_goals == 0


def test_penalty_miss_and_save_are_one_shared_event():
    events, strength = fixture(home_goals=0, away_goals=0)
    home = tuple(
        replace(row, penalty=PenaltyProcess(1, 1, 0, 1, 0))
        if row.rates.player_id == "home_scorer" else row
        for row in events.home.players
    )
    away = []
    for row in events.away.players:
        if row.rates.player_id == "away_gk":
            row = replace(row, goalkeeper=replace(
                row.goalkeeper, p_penalty_faced=1, p_penalty_saved_given_faced=1,
            ))
        away.append(row)
    events = replace(events, home=replace(events.home, players=home), away=replace(events.away, players=tuple(away)))
    result = simulator(20).simulate(events, strength)
    assert all(len(item.penalty_events) == 1 and item.penalty_events[0].outcome == "saved" for item in result.fixtures)
    assert all(item.penalty_events[0].taker_id == "home_scorer" and item.penalty_events[0].goalkeeper_id == "away_gk"
               for item in result.fixtures)
    takers = [row for row in result.player_rows if row.player_id == "home_scorer"]
    keepers = [row for row in result.player_rows if row.player_id == "away_gk"]
    assert all(row.penalties_missed == 1 for row in takers)
    assert all(row.penalties_faced == 1 and row.penalties_saved == 1 for row in keepers)


def test_clean_sheet_timing_handles_exit_and_late_entry_boundaries():
    starter = PitchState(True, 0, 60, 60)
    substitute = PitchState(False, 30, 90, 60)
    assert goals_conceded_while_on_pitch((61,), starter) == 0
    assert goals_conceded_while_on_pitch((20,), substitute) == 0
    assert goals_conceded_while_on_pitch((30, 31, 90), substitute) == 2


def test_cards_and_defcon_are_sampled_only_with_pitch_exposure():
    events, strength = fixture(home_goals=0, away_goals=0)
    updated = []
    for row in events.home.players:
        if row.rates.player_id == "home_creator":
            row = replace(
                row, cards=CardEvents(1, 0, "test", "test"),
                defensive_contributions=DefensiveContributionEvents(12, discrete(12, 20)),
            )
        updated.append(row)
    events = replace(events, home=replace(events.home, players=tuple(updated)))
    result = simulator(20).simulate(events, strength)
    rows = [row for row in result.player_rows if row.player_id == "home_creator"]
    assert all(row.yellow_cards == 1 and row.red_cards == 0 and row.defensive_contributions == 12 for row in rows)
    assert all(len(item.card_events) == 1 and item.card_events[0].card == "yellow" for item in result.fixtures)


def test_red_card_ends_participation_but_conceding_liability_continues():
    events, strength = fixture(home_goals=0, away_goals=1)
    updated = tuple(
        replace(row, cards=CardEvents(0, 1, "test", "test"))
        if row.rates.player_id == "home_creator" else row
        for row in events.home.players
    )
    events = replace(events, home=replace(events.home, players=updated))
    result = simulator(30).simulate(events, strength)
    for simulated in result.fixtures:
        red = next(card for card in simulated.card_events if card.player_id == "home_creator")
        row = next(value for value in result.player_rows
                   if value.simulation_id == simulated.simulation_id and value.player_id == "home_creator")
        assert row.red_cards == 1 and row.exit_minute == red.minute and row.minutes == red.minute
        assert row.goals_conceded_while_on_pitch == 1
        assert all(goal.scorer_id != "home_creator" or goal.minute <= red.minute for goal in simulated.goal_events)


def test_statistical_team_goal_and_minutes_means_approach_inputs():
    events, strength = fixture(home_goals=1, away_goals=0)
    matrix = ((.5,), (0.0,), (.5,))
    strength = replace(strength, expected_home_goals=1, score_distribution=matrix)
    target = events.home.players[1]
    rates = replace(
        target.rates, p_appearance=.5, p_start=.5, expected_minutes=45,
        minute_distribution=tuple([.5] + [0.0] * 89 + [.5]),
    )
    target = replace(target, rates=rates)
    events = replace(events, home=replace(
        events.home, players=(events.home.players[0], target, events.home.players[2]),
        expected_team_goals=1,
    ))
    result = simulator(3_000, seed=91, retain=False).simulate(events, strength)
    assert result.diagnostics.sampled_home_goals / 3_000 == pytest.approx(1, abs=.05)
    summary = next(row for row in result.summaries if row.player_id == "home_scorer")
    assert summary.simulated_expected_minutes == pytest.approx(45, abs=2)


def test_clean_sheet_frequency_comes_from_shared_score_and_goal_timing():
    events, strength = fixture(home_goals=0, away_goals=1)
    strength = replace(
        strength, expected_home_goals=0, expected_away_goals=.5,
        score_distribution=((.5, .5),),
    )
    result = simulator(3_000, seed=18, retain=False).simulate(events, strength)
    home = next(row for row in result.summaries if row.player_id == "home_gk")
    assert home.event_means["clean_sheets"] == pytest.approx(.5, abs=.04)


def test_deterministic_golden_nil_nil_fixture_integrates_bps_bonus_and_scoring():
    events, strength = fixture(home_goals=0, away_goals=0)
    result = simulator(10).simulate(events, strength)
    values = {summary.player_id: summary.expected_points for summary in result.summaries}
    assert values["home_gk"] == 8
    assert values["away_gk"] == 10
    assert values["home_scorer"] == values["away_scorer"] == 3
    assert values["home_creator"] == values["away_creator"] == 4
    assert all(row.fpl_points in {3, 4, 8, 10} for row in result.player_rows)


def test_aggregation_contract_probabilities_histogram_and_metadata():
    events, strength = fixture()
    result = simulator(500, seed=7, retain=False).simulate(events, strength)
    assert not result.fixtures and not result.player_rows
    for row in result.summaries:
        assert 0 <= row.p_15_plus <= row.p_10_plus <= row.p_8_plus <= row.p_5_plus <= 1
        assert 0 <= row.p_blank <= 1 and 0 <= row.p_return <= 1
        assert row.p_blank + row.p_return == pytest.approx(1)
        assert sum(row.points_histogram.values()) == 500
        assert row.point_quantiles[.1] <= row.median_points <= row.point_quantiles[.9]
        assert row.simulation_count == 500 and row.random_seed == 7
        assert row.scoring_version == 1 and row.dataset_version == "dataset-v1"
        assert row.event_completeness == .5
    assert result == simulator(500, seed=7, retain=False).simulate(events, strength)


def test_different_seed_changes_stochastic_result_and_default_is_ten_thousand():
    events, strength = fixture()
    first = simulator(200, seed=1, retain=False).simulate(events, strength)
    second = simulator(200, seed=2, retain=False).simulate(events, strength)
    assert first.summaries != second.summaries
    assert SimulationConfig().simulations_per_fixture == 10_000


def test_convergence_benchmark_is_deterministic_and_uses_requested_reference():
    events, strength = fixture()
    report = benchmark_convergence(simulator(10, retain=False), events, strength, counts=(50, 100), tolerance=10)
    assert report == benchmark_convergence(simulator(10, retain=False), events, strength, counts=(50, 100), tolerance=10)
    assert report.counts == (50, 100) and report.reference_count == 100 and report.recommended_count == 50
    assert all(row.rank >= 1 and row.reference_rank >= 1 for row in report.rows)
    assert all(row.rank_delta == row.rank-row.reference_rank for row in report.rows)
    assert {row.simulation_count for row in report.rows} == {50, 100}
    assert ROADMAP_SIMULATION_COUNTS == (1_000, 5_000, 10_000, 25_000)


def test_fixture_input_identity_and_timestamp_validation():
    events, strength = fixture()
    bad_time = TeamStrengthResult(
        strength.home_team_id, strength.away_team_id, strength.expected_home_goals,
        strength.expected_away_goals, strength.home, strength.away, strength.score_distribution,
        strength.home_clean_sheet_probability, strength.away_clean_sheet_probability,
        AT + timedelta(minutes=1), strength.model_id,
    )
    with pytest.raises(ValueError, match="timestamps differ"):
        simulator(1).simulate(events, bad_time)
