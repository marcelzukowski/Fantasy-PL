from datetime import datetime, timedelta, timezone
import math

import pytest

from fpl_engine.features.player_talent_dataset import PlayerPerformanceObservation
from fpl_engine.features.tactical_context import RoleRecord, SetPieceRecord, SetPieceType, TacticalContextEngine
from fpl_engine.features.tactical_roles import TacticalRole
from fpl_engine.models.events import EventFeatureSignal, EventModels, PlayerFixtureInput
from fpl_engine.models.events.validation import EventOutcome, walk_forward_events
from fpl_engine.models.minutes import MinutesContext, MinutesModel, MinutesObservation
from fpl_engine.models.player_talent import PlayerTalentModel
from fpl_engine.models.team_strength import TeamStrengthModel
from fpl_engine.validation.leakage import ForbiddenFeatureError, FutureInformationError, TargetFixtureLeakageError


BASE = datetime(2025, 10, 1, 12, tzinfo=timezone.utc)


def make_input(player, *, timestamp=BASE, fixture="fix_target", team="team_a", npxg=.3, xa=.15,
               minutes_pattern=(90, 88, 82, 90), position="MID", defence=1.0, penalty=False,
               shots_on_target=None, save_rate=None, unavailable=False, with_defcon=True):
    minute_rows = []
    talent_rows = []
    for index, minutes in enumerate(minutes_pattern):
        kickoff = timestamp - timedelta(days=(len(minutes_pattern)-index)*7)
        known = kickoff + timedelta(hours=2)
        minute_rows.append(MinutesObservation(player, f"old_{player}_{index}", kickoff, known, minutes, minutes >= 60))
        talent_rows.append(PlayerPerformanceObservation(
            player, f"old_{player}_{index}", kickoff, known, minutes, team, "Premier League", position,
            TacticalRole.GOALKEEPER if position == "GK" else TacticalRole.WINGER, defence,
            npxg=npxg*minutes/90, xa=xa*minutes/90, shots=2*minutes/90,
            shots_on_target=1*minutes/90, key_passes=1*minutes/90,
            tackles=1 if with_defcon else None, interceptions=1 if with_defcon else None,
            clearances=1 if with_defcon else None, blocks=0 if with_defcon else None, recoveries=2 if with_defcon else None,
            team_npxg=1.5, team_xa=1.2, team_shots=12,
        ))
    minutes_context = MinutesContext(player, fixture, timestamp, position=position,
        availability_probability=0.0 if unavailable else 1.0, availability_known_at=timestamp-timedelta(hours=1),
        availability_confidence=1.0, definitely_unavailable=unavailable)
    minutes = MinutesModel().predict(minute_rows, minutes_context)
    tactical = None
    if penalty:
        common = dict(effective_from=timestamp-timedelta(days=30), known_at=timestamp-timedelta(days=30), source="manual", confidence=.95)
        tactical = TacticalContextEngine().resolve(player_id=player, team_id=team, prediction_timestamp=timestamp,
            roles=[RoleRecord(player_id=player, team_id=team, tactical_role=TacticalRole.WINGER, fpl_position=position, **common)],
            set_pieces=[SetPieceRecord(team_id=team, player_id=player, set_piece_type=SetPieceType.PENALTIES, rank=1, **common)])
    talent = PlayerTalentModel().predict(talent_rows, player_id=player, target_fixture_id=fixture,
        prediction_timestamp=timestamp, current_team_id=team, current_competition_id="Premier League",
        fpl_position=position, tactical_context=tactical)
    return PlayerFixtureInput(player, team, fixture, timestamp, position, minutes, talent, tactical,
        defence, shots_on_target, save_rate, historical_bps_per90=12)


def projection(players, *, team_xg=1.8, opponent_xg=1.1, coverage=.85, timestamp=BASE, fixture="fix_target"):
    return EventModels().predict_team(players, fixture_id=fixture, team_id="team_a", prediction_timestamp=timestamp,
        expected_team_goals=team_xg, expected_opponent_goals=opponent_xg, squad_coverage=coverage)


def test_player_goals_reconcile_to_team_envelope_with_residual():
    result = projection([make_input("ply_a", npxg=.5), make_input("ply_b", npxg=.2)], coverage=.7)
    assert result.allocated_player_goals + result.unassigned_expected_goals + result.own_goal_expected_goals == pytest.approx(result.expected_team_goals)
    assert sum(player.goals.expected_goals for player in result.players) == pytest.approx(result.allocated_player_goals)
    assert result.unassigned_expected_goals > 0
    assert all(sum(player.goals.goal_distribution) == pytest.approx(1) for player in result.players)


def test_better_talent_and_more_minutes_raise_goal_allocation_share():
    strong = make_input("ply_strong", npxg=.65, minutes_pattern=(90,90,90,90))
    weak = make_input("ply_weak", npxg=.08, minutes_pattern=(90,90,90,90))
    result = projection([strong, weak])
    assert result.players[0].goals.expected_goals > result.players[1].goals.expected_goals
    regular = make_input("ply_regular", npxg=.3, minutes_pattern=(90,90,90,90))
    bench = make_input("ply_bench", npxg=.3, minutes_pattern=(0,12,0,20))
    minutes_result = projection([regular, bench])
    assert minutes_result.players[0].goals.expected_goals > minutes_result.players[1].goals.expected_goals


def test_unavailable_player_has_zero_event_exposure():
    unavailable = make_input("ply_out", unavailable=True)
    active = make_input("ply_active")
    player = projection([unavailable, active]).players[0]
    assert player.rates.expected_minutes == 0
    assert player.goals.expected_goals == player.assists.expected_assists == 0
    assert player.clean_sheet.player_clean_sheet_probability == 0
    assert player.cards.p_yellow == player.cards.p_red == 0


def test_assists_are_bounded_by_assisted_goal_envelope():
    result = projection([make_input("ply_a", xa=.6), make_input("ply_b", xa=.2)])
    assert result.expected_team_assists <= result.allocated_player_goals
    assert sum(player.assists.expected_assists for player in result.players) == pytest.approx(result.expected_team_assists)
    assert all(0 <= player.assists.p_assist <= 1 and sum(player.assists.assist_distribution) == pytest.approx(1) for player in result.players)


def test_stronger_opposition_reduces_fixture_rate_and_team_strength_envelope():
    ordinary_input = make_input("ply_a", defence=1.0)
    strong_input = make_input("ply_a", defence=2.0)
    ordinary = projection([ordinary_input], team_xg=1.8).players[0]
    strong = projection([strong_input], team_xg=.9).players[0]
    assert strong.rates.fixture_npxg_per90 < ordinary.rates.fixture_npxg_per90
    assert strong.goals.expected_goals < ordinary.goals.expected_goals


def test_clean_sheet_comes_from_opponent_poisson_process():
    result = projection([make_input("ply_a")], opponent_xg=.8).players[0]
    assert result.clean_sheet.team_clean_sheet_probability == pytest.approx(math.exp(-.8))
    assert result.clean_sheet.player_clean_sheet_probability == pytest.approx(math.exp(-.8)*result.clean_sheet.p_60_plus)


def test_fixture_api_consumes_team_strength_and_ranks_bps_across_both_teams():
    strength = TeamStrengthModel().predict([], "team_a", "team_b", BASE)
    fixture = EventModels().predict_fixture(
        [make_input("ply_home", team="team_a", npxg=.6)],
        [make_input("ply_away", team="team_b", npxg=.1)],
        fixture_id="fix_target", prediction_timestamp=BASE, team_strength=strength,
        home_squad_coverage=1, away_squad_coverage=1,
    )
    assert fixture.home.players[0].clean_sheet.team_clean_sheet_probability == pytest.approx(strength.home_clean_sheet_probability)
    assert fixture.away.players[0].clean_sheet.team_clean_sheet_probability == pytest.approx(strength.away_clean_sheet_probability)
    ranks = {fixture.home.players[0].bps.fixture_rank, fixture.away.players[0].bps.fixture_rank}
    assert ranks == {1, 2}


def test_goalkeeper_saves_and_penalty_saves_are_coherent_with_fallbacks():
    fallback = projection([make_input("ply_gk", position="GK", shots_on_target=None)], opponent_xg=1.2).players[0].goalkeeper
    observed = projection([make_input("ply_gk", position="GK", shots_on_target=5, save_rate=.8)], opponent_xg=1.2).players[0].goalkeeper
    assert fallback.used_shots_fallback and not observed.used_shots_fallback
    for result in (fallback, observed):
        assert math.isfinite(result.expected_saves) and result.expected_saves >= 0
        assert sum(result.save_distribution) == pytest.approx(1)
        assert 0 <= result.expected_penalty_saves <= result.p_penalty_faced <= 1


def test_penalty_process_uses_temporal_taker_and_stays_inside_goal_envelope():
    taker = make_input("ply_taker", penalty=True)
    other = make_input("ply_other")
    result = projection([taker, other])
    assert result.players[0].penalty.taker_selection_probability == 1
    assert result.players[0].penalty.expected_penalty_goals > 0
    assert result.players[0].rates.fixture_penalty_xg_per90 > 0
    assert result.players[1].penalty.expected_penalty_goals == 0
    assert 0 <= result.players[0].penalty.miss_probability <= 1


def test_defcon_cards_and_missing_fallbacks_are_explicit():
    full = projection([make_input("ply_a", with_defcon=True)]).players[0]
    missing = projection([make_input("ply_b", with_defcon=False)]).players[0]
    assert full.defensive_contributions.expected_defensive_contributions >= 0
    assert sum(full.defensive_contributions.defcon_distribution) == pytest.approx(1)
    assert missing.defensive_contributions.expected_defensive_contributions is None
    assert 0 <= full.cards.p_red <= 1 and 0 <= full.cards.p_yellow <= 1
    assert full.cards.yellow_rate_source == "position_prior"


def test_bps_is_fixture_relative_and_does_not_award_bonus_points():
    result = projection([make_input("ply_star", npxg=.7), make_input("ply_other", npxg=.05)])
    star, other = result.players
    assert star.bps.fixture_rank == 1 and other.bps.fixture_rank == 2
    assert star.bps.fixture_relative_score > other.bps.fixture_relative_score
    assert not hasattr(star.bps, "bonus_points")


def test_future_target_and_vaastav_xp_signals_are_rejected():
    item = make_input("ply_a")
    target = EventFeatureSignal("lineup", True, BASE-timedelta(hours=1), BASE-timedelta(hours=1), "api", "fix_target")
    with pytest.raises(TargetFixtureLeakageError):
        projection([PlayerFixtureInput(**{**item.__dict__, "signals": (target,)})])
    future = EventFeatureSignal("injury", False, BASE+timedelta(1), BASE, "api")
    with pytest.raises(FutureInformationError):
        projection([PlayerFixtureInput(**{**item.__dict__, "signals": (future,)})])
    xp = EventFeatureSignal("xP", 10, BASE-timedelta(1), BASE-timedelta(1), "vaastav")
    with pytest.raises(ForbiddenFeatureError):
        projection([PlayerFixtureInput(**{**item.__dict__, "signals": (xp,)})])


def test_predictions_are_bounded_numerically_stable_and_deterministic():
    inputs = [make_input("ply_a", npxg=0, xa=0), make_input("ply_b", npxg=2, xa=1)]
    first = projection(inputs, team_xg=4, opponent_xg=0)
    assert first == projection(inputs, team_xg=4, opponent_xg=0)
    for player in first.players:
        assert 0 <= player.goals.p_goal <= 1 and 0 <= player.assists.p_assist <= 1
        assert math.isfinite(player.goals.expected_goals) and math.isfinite(player.rates.fixture_npxg_per90)
        assert 0 <= player.confidence <= 1 and 0 <= player.uncertainty <= 1


def test_walk_forward_ordering_metrics_and_champion_gate():
    outcomes = []
    for index in range(6):
        timestamp = BASE + timedelta(days=index*7)
        fixture = f"fix_wf_{index}"
        item = make_input(f"ply_{index}", timestamp=timestamp, fixture=fixture, npxg=.15+index*.05)
        result = projection([item], timestamp=timestamp, fixture=fixture).players[0]
        outcomes.append(EventOutcome(result, timestamp+timedelta(hours=3), int(index%3==0), int(index%4==0),
                                     defensive_contributions=4, yellow=index==2))
    report = walk_forward_events(outcomes, minimum_history=2)
    assert report == walk_forward_events(outcomes, minimum_history=2)
    assert report.prediction_order == tuple((f"fix_wf_{index}", f"ply_{index}") for index in range(2,6))
    assert report.goal_champion_model_id in {item.model_id for item in report.candidates}
    assert report.assist_champion_model_id in {item.model_id for item in report.candidates}
    assert all(item.observations == 4 and item.goal_brier >= 0 and item.assist_brier >= 0 for item in report.candidates)
