from datetime import datetime, timedelta, timezone

import pytest

from fpl_engine.data.manual_context import ManualContextRecord
from fpl_engine.data.schemas.entities import PlayerTeamSpell
from fpl_engine.features.player_talent_dataset import PlayerPerformanceObservation, build_player_talent_training_rows
from fpl_engine.features.tactical_context import (
    AvailabilityRecord, FormationRecord, ManagerRegimeRecord, RoleRecord, SetPieceRecord,
    SetPieceType, SquadRoleRecord, TacticalContextEngine, normalize_formation,
)
from fpl_engine.features.tactical_roles import TacticalRole
from fpl_engine.models.minutes import MinutesContext, MinutesModel
from fpl_engine.models.player_talent import PlayerTalentConfig, PlayerTalentModel, walk_forward_talent
from fpl_engine.models.player_talent.baselines import exponentially_weighted_per90, season_to_date_per90
from fpl_engine.models.team_strength import MatchObservation, TeamRegimeContext, TeamStrengthModel, walk_forward_regime
from fpl_engine.validation.leakage import ForbiddenFeatureError, FutureInformationError, TargetFixtureLeakageError


NOW = datetime(2025, 8, 1, 12, tzinfo=timezone.utc)


def role(days, value, *, player="ply_1", team="team_a", known=None, fixture=None, confidence=.9):
    at = NOW + timedelta(days=days)
    return RoleRecord(effective_from=at, known_at=known or at, source="lineup", confidence=confidence,
                      fixture_id=fixture, player_id=player, team_id=team, tactical_role=value, fpl_position="MID")


def formation(days, value, *, team="team_a"):
    at = NOW + timedelta(days=days)
    return FormationRecord(effective_from=at, known_at=at, source="lineup", confidence=.9, team_id=team, formation=value)


def manager(days, manager_id, *, team="team_a", known=None):
    at = NOW + timedelta(days=days)
    return ManagerRegimeRecord(effective_from=at, known_at=known or at, source="api_football", confidence=.9, team_id=team, manager_id=manager_id)


def performance(index, *, player="ply_1", team="team_a", competition="Premier League", role_value=TacticalRole.WINGER,
                minutes=90, npxg=.2, xa=.1, shots=2.0, shots_box=None, defensive=None, source_fields=()):
    kickoff = NOW + timedelta(days=index * 7)
    kwargs = dict(tackles=None, interceptions=None, clearances=None, blocks=None, recoveries=None)
    if defensive is not None:
        kwargs.update(tackles=defensive, interceptions=defensive, clearances=defensive, blocks=defensive, recoveries=defensive)
    return PlayerPerformanceObservation(
        player, f"fix_{index}_{player}", kickoff, kickoff + timedelta(hours=2), minutes, team,
        competition, "MID", role_value, 1.0, npxg, xa, shots, shots_box,
        shots_on_target=None, key_passes=xa * 10 if xa is not None else None,
        team_npxg=1.5, team_xa=1.2, team_shots=12, source_fields=source_fields, **kwargs,
    )


def test_role_taxonomy_keeps_fpl_position_distinct_and_role_is_temporal():
    engine = TacticalContextEngine()
    roles = [role(-20, TacticalRole.WINGER), role(10, TacticalRole.CENTRE_FORWARD)]
    before = engine.resolve(player_id="ply_1", team_id="team_a", prediction_timestamp=NOW, roles=roles)
    after = engine.resolve(player_id="ply_1", team_id="team_a", prediction_timestamp=NOW + timedelta(days=11), roles=roles)
    assert before.fpl_position == "MID" and before.current_tactical_role == TacticalRole.WINGER
    assert after.fpl_position == "MID" and after.current_tactical_role == TacticalRole.CENTRE_FORWARD
    assert after.role_change_flag


def test_future_target_lineup_is_rejected_and_future_context_is_not_selected():
    engine = TacticalContextEngine()
    with pytest.raises(TargetFixtureLeakageError):
        engine.resolve(player_id="ply_1", team_id="team_a", prediction_timestamp=NOW,
                       target_fixture_id="target", roles=[role(-1, TacticalRole.WINGER, fixture="target")])
    result = engine.resolve(player_id="ply_1", team_id="team_a", prediction_timestamp=NOW,
                            roles=[role(-2, TacticalRole.WINGER), role(2, TacticalRole.CENTRE_FORWARD)])
    assert result.current_tactical_role == TacticalRole.WINGER


def test_manual_context_requires_creation_and_effective_time():
    future = ManualContextRecord(context_type="tactical_role", subject_type="player", subject_id="ply_1",
        value="centre_forward", effective_from=NOW - timedelta(days=1), effective_to=None,
        created_at=NOW + timedelta(hours=1), confidence=.99, reason="future discovery")
    historical = ManualContextRecord(context_type="tactical_role", subject_type="player", subject_id="ply_1",
        value="winger", effective_from=NOW - timedelta(days=2), effective_to=None,
        created_at=NOW - timedelta(days=2), confidence=.8, reason="known lineup")
    result = TacticalContextEngine().resolve(player_id="ply_1", team_id="team_a", prediction_timestamp=NOW,
                                              roles=[role(-3, TacticalRole.ATTACKING_MIDFIELDER)], manual_context=[future, historical])
    assert result.current_tactical_role == TacticalRole.WINGER


def test_formation_manager_regime_and_transfer_context_are_temporal():
    spell_kwargs = dict(source="manual", source_record_id=None, retrieved_at=NOW - timedelta(days=30), confidence=.9)
    spells = [
        PlayerTeamSpell(player_id="ply_1", team_id="team_old", competition_id="comp_old", effective_from=NOW-timedelta(days=100), effective_to=NOW-timedelta(days=20), **spell_kwargs),
        PlayerTeamSpell(player_id="ply_1", team_id="team_a", competition_id="comp_pl", effective_from=NOW-timedelta(days=19), effective_to=None, **spell_kwargs),
    ]
    result = TacticalContextEngine().resolve(
        player_id="ply_1", team_id="team_a", prediction_timestamp=NOW,
        formations=[formation(-30, "4-3-3"), formation(-10, "3-4-2-1")],
        managers=[manager(-100, "mgr_old"), manager(-12, "mgr_new")], player_team_spells=spells,
    )
    assert result.manager_id == "mgr_new" and result.manager_change_flag
    assert result.dominant_formation == "3-4-2-1" and result.formation_change_flag
    assert result.club_change_flag and result.league_change_flag
    assert result.historical_weight_multiplier < 1
    assert normalize_formation("4231") == "4-2-3-1"


def test_set_piece_hierarchy_is_temporal_and_skips_unavailable_first_taker():
    common = dict(effective_from=NOW-timedelta(days=2), known_at=NOW-timedelta(days=2), source="manual", confidence=.9, team_id="team_a")
    hierarchy = [
        SetPieceRecord(player_id="ply_1", set_piece_type=SetPieceType.PENALTIES, rank=1, **common),
        SetPieceRecord(player_id="ply_2", set_piece_type=SetPieceType.PENALTIES, rank=2, **common),
    ]
    squad = [
        SquadRoleRecord(player_id="ply_1", tactical_role=TacticalRole.CENTRE_FORWARD, availability_probability=0, **common),
        SquadRoleRecord(player_id="ply_2", tactical_role=TacticalRole.CENTRE_FORWARD, availability_probability=1, **common),
    ]
    result = TacticalContextEngine().resolve(player_id="ply_2", team_id="team_a", prediction_timestamp=NOW,
                                              set_pieces=hierarchy, squad=squad)
    assert result.penalty_role.rank == 1


def test_future_and_future_created_set_piece_context_cannot_rewrite_history():
    common = dict(source="manual", confidence=.9, team_id="team_a", player_id="ply_1",
                  set_piece_type=SetPieceType.PENALTIES)
    records = [
        SetPieceRecord(effective_from=NOW-timedelta(days=5), known_at=NOW-timedelta(days=5), rank=1,
                       **{**common, "player_id": "ply_2"}),
        SetPieceRecord(effective_from=NOW-timedelta(days=5), known_at=NOW-timedelta(days=5), rank=2, **common),
        SetPieceRecord(effective_from=NOW+timedelta(days=1), known_at=NOW+timedelta(days=1), rank=1, **common),
    ]
    future_manual = ManualContextRecord(context_type="penalty_rank", subject_type="player", subject_id="ply_1",
        value=1, effective_from=NOW-timedelta(days=1), effective_to=None, created_at=NOW+timedelta(hours=1),
        confidence=1, reason="learned later")
    result = TacticalContextEngine().resolve(player_id="ply_1", team_id="team_a", prediction_timestamp=NOW,
                                              set_pieces=records, manual_context=[future_manual])
    assert result.penalty_role.rank == 2


def test_squad_competition_is_role_specific_and_availability_preserves_unknown():
    common = dict(effective_from=NOW-timedelta(days=2), known_at=NOW-timedelta(days=2), source="canonical", confidence=.8, team_id="team_a")
    squad = [
        SquadRoleRecord(player_id="ply_1", tactical_role=TacticalRole.WINGER, availability_probability=1, recent_start_share=.8, **common),
        SquadRoleRecord(player_id="ply_2", tactical_role=TacticalRole.WINGER, availability_probability=1, recent_start_share=.5, **common),
        SquadRoleRecord(player_id="ply_3", tactical_role=TacticalRole.CENTRE_BACK, availability_probability=1, recent_start_share=1, **common),
    ]
    result = TacticalContextEngine().resolve(player_id="ply_1", team_id="team_a", prediction_timestamp=NOW,
                                              roles=[role(-3, TacticalRole.WINGER)], squad=squad)
    assert result.role_competitor_set == ("ply_2",)
    assert result.squad_competition_score is not None and result.role_security_score is not None
    assert result.availability.availability_probability is None


def test_availability_strict_snapshot_and_confirmed_suspension():
    old = AvailabilityRecord(effective_from=NOW-timedelta(days=1), known_at=NOW-timedelta(days=1), source="fplcache",
        confidence=.8, player_id="ply_1", status="a", snapshot_timestamp=NOW-timedelta(seconds=1))
    equal = AvailabilityRecord(effective_from=NOW, known_at=NOW, source="fplcache", confidence=1,
        player_id="ply_1", status="u", snapshot_timestamp=NOW)
    result = TacticalContextEngine().resolve(player_id="ply_1", team_id="team_a", prediction_timestamp=NOW,
                                              availability=[old, equal])
    assert result.availability.availability_probability == .95
    suspended = AvailabilityRecord(effective_from=NOW-timedelta(days=1), known_at=NOW-timedelta(days=1), source="api",
        confidence=1, player_id="ply_1", confirmed_suspension=True)
    blocked = TacticalContextEngine().resolve(player_id="ply_1", team_id="team_a", prediction_timestamp=NOW, availability=[suspended])
    assert blocked.availability.suspension_block and blocked.availability.availability_probability == 0


def test_team_strength_regime_retains_old_history_and_preserves_default_api():
    matches = []
    for index in range(6):
        kickoff = NOW - timedelta(days=(6-index)*10)
        matches.append(MatchObservation(f"m{index}", kickoff, kickoff+timedelta(hours=2), "A", "B", 2, 1, 2.1, .9))
    model = TeamStrengthModel()
    plain = model.predict(matches, "A", "B", NOW)
    regime = TeamRegimeContext("mgr_new", NOW-timedelta(days=15), NOW-timedelta(days=15), .8, .9)
    adjusted = model.predict(matches, "A", "B", NOW, regime_context={"A": regime})
    assert plain.model_id.startswith("dixon_coles_v1")
    assert adjusted.model_id.startswith("dixon_coles_regime_v1")
    assert 0 < adjusted.home.effective_sample_size < plain.home.effective_sample_size
    assert adjusted.score_distribution and sum(map(sum, adjusted.score_distribution)) == pytest.approx(1)
    with pytest.raises(FutureInformationError):
        model.predict(matches, "A", "B", NOW, regime_context={"A": TeamRegimeContext("mgr", NOW+timedelta(1), NOW)})


def test_team_strength_regime_challenger_requires_material_walk_forward_gain():
    matches = []
    for index in range(9):
        kickoff = NOW + timedelta(days=index*7)
        matches.append(MatchObservation(f"wf{index}", kickoff, kickoff+timedelta(hours=2), "A", "B", 2, 1, 2.0, 1.0))
    regime = TeamRegimeContext("mgr", NOW+timedelta(days=20), NOW+timedelta(days=20), 0.0, .8)
    report = walk_forward_regime(matches, {"A": (regime,)}, minimum_history=3)
    assert report.champion_model_id == (report.challenger.model_id if report.promoted else "rolling_xg_v1")
    assert report.existing_champion.fixtures == report.challenger.fixtures


def test_talent_zero_is_evidence_while_missing_optional_data_stays_missing():
    rows = [performance(-3, npxg=0, xa=0, shots=0), performance(-2, npxg=0, xa=0, shots=0)]
    prediction = PlayerTalentModel().predict(rows, player_id="ply_1", target_fixture_id="target",
        prediction_timestamp=NOW, current_team_id="team_a")
    assert prediction.data_quality["has_xg_data"]
    assert prediction.talent_npxg_per90 < .22
    assert prediction.talent_shots_in_box_per90 is None
    assert prediction.defensive_contribution_rate is None


def test_small_samples_shrink_more_and_uncertainty_declines_with_evidence():
    small = [performance(-2, npxg=.9, xa=.4, shots=6)]
    large = [performance(index-20, npxg=.9, xa=.4, shots=6) for index in range(15)]
    model = PlayerTalentModel()
    a = model.predict(small, player_id="ply_1", target_fixture_id="target", prediction_timestamp=NOW, current_team_id="team_a")
    b = model.predict(large, player_id="ply_1", target_fixture_id="target", prediction_timestamp=NOW, current_team_id="team_a")
    assert b.talent_npxg_per90 > a.talent_npxg_per90 > .22
    assert b.sample_reliability > a.sample_reliability
    assert b.player_talent_uncertainty < a.player_talent_uncertainty


def test_new_player_fallback_is_transparent_and_high_uncertainty():
    prediction = PlayerTalentModel().predict([], player_id="ply_new", target_fixture_id="target",
        prediction_timestamp=NOW, current_team_id="team_a", fpl_position="FWD")
    assert prediction.talent_npxg_per90 == .35
    assert prediction.sample_size == 0 and prediction.sample_reliability == 0
    assert prediction.player_talent_uncertainty == 1
    assert prediction.talent_shots_in_box_per90 is None


def test_transfer_retains_identity_without_destination_strength_rewriting_talent():
    history = [performance(-8, team="team_old", npxg=.5), performance(-7, team="team_old", npxg=.4)]
    model = PlayerTalentModel()
    a = model.predict(history, player_id="ply_1", target_fixture_id="a", prediction_timestamp=NOW,
                      current_team_id="team_new", current_competition_id="Premier League")
    b = model.predict(history, player_id="ply_1", target_fixture_id="b", prediction_timestamp=NOW,
                      current_team_id="team_stronger", current_competition_id="Premier League")
    assert a.player_id == b.player_id == "ply_1"
    assert a.talent_npxg_per90 == b.talent_npxg_per90
    assert a.sample_size == 2


def test_unsupported_cross_league_has_no_invented_coefficient():
    history = [performance(-4, competition="Bundesliga", npxg=.7)]
    fallback = PlayerTalentModel().predict(history, player_id="ply_1", target_fixture_id="target",
        prediction_timestamp=NOW, current_team_id="team_a", current_competition_id="Premier League")
    configured = PlayerTalentModel(PlayerTalentConfig(translation_coefficients={"Bundesliga->Premier League": .8})).predict(
        history, player_id="ply_1", target_fixture_id="target", prediction_timestamp=NOW,
        current_team_id="team_a", current_competition_id="Premier League")
    assert fallback.cross_league_status == "unsupported_fallback"
    assert fallback.player_talent_uncertainty > configured.player_talent_uncertainty
    assert configured.cross_league_status == "configured_translation"


def test_talent_rejects_future_target_and_vaastav_xp():
    target = performance(-1)
    with pytest.raises(TargetFixtureLeakageError):
        PlayerTalentModel().predict([target], player_id="ply_1", target_fixture_id=target.fixture_id,
                                    prediction_timestamp=NOW, current_team_id="team_a")
    unsafe = performance(-1, source_fields=("xP",))
    unsafe = PlayerPerformanceObservation(**{**unsafe.__dict__, "source": "vaastav"})
    with pytest.raises(ForbiddenFeatureError):
        PlayerTalentModel().predict([unsafe], player_id="ply_1", target_fixture_id="target",
                                    prediction_timestamp=NOW, current_team_id="team_a")


def test_talent_dataset_baselines_walk_forward_and_determinism():
    rows = [performance(index-12, npxg=.1 + (index % 4)*.1, xa=.05, shots=1+index%3) for index in range(10)]
    training = build_player_talent_training_rows(rows)
    assert [row.history_count for row in training] == list(range(10))
    prediction_time = NOW
    assert season_to_date_per90(rows, "ply_1", "target", prediction_time).model_id == "season_to_date_per90_v1"
    assert exponentially_weighted_per90(rows, "ply_1", "target", prediction_time).model_id == "exponentially_weighted_per90_v1"
    first = walk_forward_talent(rows, minimum_history=2)
    assert first == walk_forward_talent(rows, minimum_history=2)
    assert first.prediction_fixture_order == tuple(row.fixture_id for row in rows[2:])
    assert first.champion_model_id in {candidate.model_id for candidate in first.candidates}


def test_tactical_context_maps_into_existing_minutes_optional_contract():
    tactical = TacticalContextEngine().resolve(player_id="ply_1", team_id="team_a", prediction_timestamp=NOW,
        roles=[role(-2, TacticalRole.WINGER)], managers=[manager(-5, "mgr")])
    minutes_context = MinutesContext("ply_1", "target", NOW, position=tactical.fpl_position,
        availability_probability=tactical.availability.availability_probability,
        availability_confidence=tactical.availability.availability_confidence,
        rotation_risk=tactical.squad_competition_score, manager_change=tactical.manager_change_flag,
        tactical_role_change=tactical.role_change_flag)
    prediction = MinutesModel().predict([], minutes_context)
    assert prediction.player_id == tactical.player_id and 0 <= prediction.expected_minutes <= 90
