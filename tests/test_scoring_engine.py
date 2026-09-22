from dataclasses import replace
from pathlib import Path

import pytest

from fpl_engine.scoring import FPLScoringEngine, SimulatedPlayerEvents
from fpl_engine.simulation import PitchState, goals_conceded_while_on_pitch


ROOT = Path(__file__).resolve().parents[1]
ENGINE = FPLScoringEngine.from_project(ROOT)
HISTORICAL_ENGINE = FPLScoringEngine.from_project(ROOT, season="2024/25")
HOLDOUT_ENGINE = FPLScoringEngine.from_project(ROOT, season="2023/24")


def event(position="MID", minutes=90, **kwargs):
    return SimulatedPlayerEvents("player", "fixture", position, minutes, **kwargs)


@pytest.mark.parametrize("minutes,expected", [(0, 0), (1, 1), (59, 1), (60, 2), (90, 2)])
def test_appearance_thresholds(minutes, expected):
    assert ENGINE.score(event(minutes=minutes)).appearance_points == expected


@pytest.mark.parametrize("position,expected", [("GK", 10), ("DEF", 6), ("MID", 5), ("FWD", 4)])
def test_position_specific_goal_points(position, expected):
    assert ENGINE.score(event(position, goals=1)).goal_points == expected


def test_clean_sheet_eligibility_uses_player_minutes_and_on_pitch_conceding():
    assert ENGINE.score(event("DEF", 59)).clean_sheet_points == 0
    assert ENGINE.score(event("DEF", 60)).clean_sheet_points == 4
    assert ENGINE.score(event("MID", 60)).clean_sheet_points == 1
    substituted = PitchState(True, 0, 65, 65)
    assert goals_conceded_while_on_pitch((75,), substituted) == 0
    assert ENGINE.score(event("DEF", 65, goals_conceded_while_on_pitch=0)).clean_sheet_points == 4
    assert goals_conceded_while_on_pitch((75,), substituted, red_card_minute=65) == 1


@pytest.mark.parametrize("saves,expected", [(2, 0), (3, 1), (6, 2)])
def test_goalkeeper_save_floor_groups(saves, expected):
    assert ENGINE.score(event("GK", saves=saves)).save_points == expected


@pytest.mark.parametrize(
    "position,contributions,expected",
    [("DEF", 9, 0), ("DEF", 10, 2), ("DEF", 20, 2), ("MID", 11, 0),
     ("MID", 12, 2), ("FWD", 12, 2), ("GK", 20, 0)],
)
def test_defensive_contribution_threshold_and_cap(position, contributions, expected):
    score = ENGINE.score(event(position, defensive_contributions=contributions))
    assert score.defensive_contribution_points == expected


@pytest.mark.parametrize("conceded,expected", [(1, 0), (2, -1), (4, -2)])
def test_goals_conceded_floor_groups(conceded, expected):
    assert ENGINE.score(event("DEF", goals_conceded_while_on_pitch=conceded)).goals_conceded_points == expected


def test_cards_penalties_own_goal_and_captain_are_composed_downstream():
    score = ENGINE.score(event(
        "GK", penalty_saves=1, penalty_misses=1, yellow_cards=1,
        red_cards=1, own_goals=1,
    ), captain_multiplier=2)
    assert score.penalty_save_points == 5
    assert score.penalty_miss_points == -2
    assert score.yellow_card_points == -1
    assert score.red_card_points == -3
    assert score.own_goal_points == -2
    assert score.multiplied_points == score.total_points * 2


@pytest.mark.parametrize(
    "bps,expected",
    [
        ({"a": 40, "b": 35, "c": 30}, {"a": 3, "b": 2, "c": 1}),
        ({"a": 40, "b": 40, "c": 35}, {"a": 3, "b": 3, "c": 1}),
        ({"a": 40, "b": 35, "c": 35}, {"a": 3, "b": 2, "c": 2}),
        ({"a": 40, "b": 35, "c": 30, "d": 30}, {"a": 3, "b": 2, "c": 1, "d": 1}),
        ({"a": 40, "b": 40, "c": 40, "d": 35}, {"a": 3, "b": 3, "c": 3, "d": 0}),
    ],
)
def test_fixture_bonus_tie_rules(bps, expected):
    assert ENGINE.allocate_bonus(bps) == expected


def test_2026_27_bps_cumulative_save_and_three_cbi_rules():
    appearance = ENGINE.calculate_bps(event("GK", 90))
    ordinary = ENGINE.calculate_bps(event("GK", 90, saves=1))
    inside = ENGINE.calculate_bps(event("GK", 90, saves=1, saves_inside_box=1))
    big = ENGINE.calculate_bps(event("GK", 90, saves=1, saves_big_chance=1))
    penalty = ENGINE.calculate_bps(event(
        "GK", 90, saves=1, saves_inside_box=1, saves_big_chance=1, penalty_saves=1,
    ))
    assert ordinary - appearance == 2
    assert inside - appearance == 3
    assert big - appearance == 3
    assert penalty - appearance == 11
    defender = event("DEF", clearances_blocks_interceptions=3)
    assert ENGINE.calculate_bps(defender) - ENGINE.calculate_bps(event("DEF")) == 1
    assert ENGINE.calculate_bps(replace(defender, clearances_blocks_interceptions=6)) - ENGINE.calculate_bps(event("DEF")) == 2


def test_scoring_is_loaded_from_versioned_yaml_and_validates_event_contract(tmp_path):
    assert ENGINE.version == 1 and ENGINE.season == "2026/27"
    assert FPLScoringEngine.from_file(ROOT / "docs/03_SIMULATION/scoring_rules.yaml").season == "2026/27"
    customized = tmp_path / "rules.yaml"
    customized.write_text(
        (ROOT / "docs/03_SIMULATION/scoring_rules.yaml").read_text(encoding="utf-8")
        .replace("points_per_assist: 3", "points_per_assist: 7"),
        encoding="utf-8",
    )
    assert FPLScoringEngine.from_file(customized).score(event(assists=1)).assist_points == 7
    with pytest.raises(ValueError):
        event("UNKNOWN")
    with pytest.raises(ValueError):
        event(minutes=91)
    with pytest.raises(ValueError):
        event(goals=0, penalty_goals=1)
    with pytest.raises(ValueError):
        ENGINE.score(event(), bonus_points=4)


def test_unavailable_bps_components_are_not_observed_zeroes():
    observed_zero = event("MID", successful_dribbles=0)
    unavailable = event("MID", unavailable_bps_components=("successful_dribbles",))
    zero_assessment = ENGINE.assess_bps(observed_zero)
    missing_assessment = ENGINE.assess_bps(unavailable)
    assert zero_assessment.event_completeness == 1
    assert missing_assessment.event_completeness < 1
    assert missing_assessment.unavailable_components == ("successful_dribbles",)


def test_2024_25_scoring_is_explicitly_versioned_and_does_not_fall_back():
    assert HISTORICAL_ENGINE.season == "2024/25"
    assert HISTORICAL_ENGINE.version == 202425
    with pytest.raises(Exception, match="Configuration file not found"):
        FPLScoringEngine.from_project(ROOT, season="1999/00")


def test_2024_25_historical_scoring_differences_are_preserved():
    assert HISTORICAL_ENGINE.score(event("DEF", defensive_contributions=99)).defensive_contribution_points == 0
    assert HISTORICAL_ENGINE.score(event("GK", goals=1)).goal_points == 10
    baseline = HISTORICAL_ENGINE.calculate_bps(event("GK", 90))
    penalty_save = HISTORICAL_ENGINE.calculate_bps(event("GK", 90, saves=1, penalty_saves=1))
    assert penalty_save - baseline == 9
    assert HISTORICAL_ENGINE.calculate_bps(event("DEF", 59, goals_conceded_while_on_pitch=1)) - HISTORICAL_ENGINE.calculate_bps(event("DEF", 59)) == -4
    assert HISTORICAL_ENGINE.calculate_bps(event("DEF", goal_line_clearances=1)) - HISTORICAL_ENGINE.calculate_bps(event("DEF")) == 3
    assert HISTORICAL_ENGINE.calculate_bps(event("MID", fouls_won=1, shots_on_target=1)) - HISTORICAL_ENGINE.calculate_bps(event("MID")) == 3


def test_2023_24_pre_change_scoring_and_bps_are_preserved():
    assert HOLDOUT_ENGINE.version == 202324 and HOLDOUT_ENGINE.season == "2023/24"
    assert HOLDOUT_ENGINE.score(event("GK", goals=1)).goal_points == 6
    baseline = HOLDOUT_ENGINE.calculate_bps(event("GK", 90))
    penalty_save = HOLDOUT_ENGINE.calculate_bps(event("GK", 90, saves=1, penalty_saves=1))
    assert penalty_save - baseline == 15
    assert HOLDOUT_ENGINE.calculate_bps(event("DEF", 59, goals_conceded_while_on_pitch=1)) - HOLDOUT_ENGINE.calculate_bps(event("DEF", 59)) == 0
    assert HOLDOUT_ENGINE.calculate_bps(event("DEF", goal_line_clearances=1)) - HOLDOUT_ENGINE.calculate_bps(event("DEF")) == 0
    assert HOLDOUT_ENGINE.calculate_bps(event("MID", fouls_won=1, shots_on_target=1)) - HOLDOUT_ENGINE.calculate_bps(event("MID")) == 0
    assert HOLDOUT_ENGINE.score(event("DEF", defensive_contributions=99)).defensive_contribution_points == 0
