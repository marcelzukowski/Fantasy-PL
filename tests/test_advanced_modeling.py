from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path

import pytest

from fpl_engine.current import _load_active_model_manifest, _runtime_model_stack
from fpl_engine.features.advanced_context import (
    TacticalContextV2Engine, role_distribution, set_piece_probabilities,
)
from fpl_engine.features.advanced_event_data import (
    AvailabilityStatus, TemporalEventRecord, derived_npxg,
    development_feature_matrix, eligible_event_history, immutable_values,
    to_player_performance,
)
from fpl_engine.features.player_talent_dataset import PlayerPerformanceObservation
from fpl_engine.features.tactical_context import (
    RoleRecord, SetPieceRecord, SetPieceRole, SetPieceType, TacticalContextEngine,
)
from fpl_engine.features.tactical_roles import TacticalRole
from fpl_engine.models.data_quality import DataQualitySignals, assess_data_quality
from fpl_engine.models.events import (
    EventModels, EventModelsV2, PenaltyModelV2, PlayerFixtureInput,
    TeamPenaltyEvidence, load_bps_support_matrix,
)
from fpl_engine.models.minutes import MinutesContext, MinutesModel, MinutesObservation
from fpl_engine.models.player_talent import (
    LeagueTranslationEvidence, PlayerTalentModel, PlayerTalentV2,
    PlayerTalentV2Config,
)
from fpl_engine.validation.leakage import (
    FutureInformationError, LeakageError, TargetFixtureLeakageError,
)
from fpl_engine.validation.advanced import walk_forward_advanced_talent


ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 9, 10, 12, tzinfo=timezone.utc)


def observation(index, *, player="ply_a", team="team_a", competition="comp_pl",
                npxg=.3, xa=.2, shots=2.0, key_passes=2.0,
                big_chances_created=.2, role=TacticalRole.WINGER):
    kickoff = NOW - timedelta(days=(8 - index) * 7)
    return PlayerPerformanceObservation(
        player, f"fix_{player}_{index}", kickoff, kickoff + timedelta(hours=3),
        90, team, competition, "MID", role, 1.0, npxg, xa, shots,
        shots_in_box=1.2 if shots is not None else None,
        shots_on_target=.8 if shots is not None else None,
        key_passes=key_passes, big_chances_created=big_chances_created,
        box_touches=5.0 if shots is not None else None, goals=.25,
        team_npxg=1.5 if npxg is not None else None,
        team_xa=1.1 if xa is not None else None,
        team_shots=12 if shots is not None else None,
        team_box_touches=24 if shots is not None else None,
    )


def event_record(**changes):
    values = immutable_values({"xg": .8, "penalty_xg": .3, "xa": .2, "shots": 3.0})
    payload = dict(
        provider="api_football", season="2026/27", player_id="ply_a",
        fixture_id="fix_old", team_id="team_a", competition_id="comp_pl",
        fpl_position="MID", minutes=90, observed_at=NOW-timedelta(days=2),
        known_at=NOW-timedelta(days=2)+timedelta(hours=3),
        effective_at=NOW-timedelta(days=2)+timedelta(hours=3),
        retrieved_at=NOW, values=values, source_version="sha256:test",
    )
    payload.update(changes)
    return TemporalEventRecord(**payload)


def event_input(player, *, xa=.2, key_passes=2.0, big_created=.2, penalty_rank=None):
    rows = [observation(index, player=player, xa=xa, key_passes=key_passes,
                        big_chances_created=big_created) for index in range(6)]
    minutes_rows = [MinutesObservation(
        player, f"min_{player}_{index}", NOW-timedelta(days=(index+1)*7),
        NOW-timedelta(days=(index+1)*7)+timedelta(hours=3), 90, True,
    ) for index in range(6)]
    minutes = MinutesModel().predict(minutes_rows, MinutesContext(
        player, "fix_target", NOW, position="MID", availability_probability=1,
        availability_known_at=NOW-timedelta(hours=1), availability_confidence=1,
    ))
    common = dict(effective_from=NOW-timedelta(days=10), known_at=NOW-timedelta(days=10),
                  source="manual", confidence=.9, team_id="team_a")
    roles = [RoleRecord(player_id=player, tactical_role=TacticalRole.WINGER,
                        fpl_position="MID", **common)]
    pieces = [] if penalty_rank is None else [SetPieceRecord(
        player_id=player, set_piece_type=SetPieceType.PENALTIES,
        rank=penalty_rank, **common,
    )]
    tactical = TacticalContextEngine().resolve(
        player_id=player, team_id="team_a", prediction_timestamp=NOW,
        roles=roles, set_pieces=pieces,
    )
    if penalty_rank is not None:
        tactical = replace(tactical, penalty_role=SetPieceRole(penalty_rank, .9))
    talent = PlayerTalentV2().predict(
        rows, player_id=player, target_fixture_id="fix_target",
        prediction_timestamp=NOW, current_team_id="team_a",
        current_competition_id="comp_pl", fpl_position="MID",
        tactical_context=tactical,
    )
    return PlayerFixtureInput(
        player, "team_a", "fix_target", NOW, "MID", minutes, talent, tactical,
    )


def test_event_data_temporal_safety_and_derived_npxg_require_both_fields():
    row = event_record()
    assert derived_npxg(row) == pytest.approx(.5)
    converted = to_player_performance(row)
    assert converted.npxg == pytest.approx(.5) and converted.shots == 3
    missing = event_record(values=immutable_values({"xg": .8, "penalty_xg": None}))
    assert derived_npxg(missing) is None
    assert to_player_performance(missing).npxg is None
    with pytest.raises(TargetFixtureLeakageError):
        eligible_event_history([row], player_id="ply_a", target_fixture_id="fix_old",
                               prediction_timestamp=NOW)
    future = event_record(known_at=NOW+timedelta(seconds=1))
    with pytest.raises(FutureInformationError):
        eligible_event_history([future], player_id="ply_a", target_fixture_id="other",
                               prediction_timestamp=NOW)


def test_feature_availability_matrix_keeps_current_only_separate_from_strict():
    matrix = development_feature_matrix()
    assert matrix.status("vaastav", "2024/25", "xa") == AvailabilityStatus.STRICT_HISTORICAL
    assert matrix.status("vaastav", "2024/25", "npxg") == AvailabilityStatus.UNAVAILABLE
    assert matrix.status("api_football", "2026/27", "shots") == AvailabilityStatus.CURRENT_ONLY


def test_talent_v2_shrinkage_missing_vs_zero_and_role_prior():
    model = PlayerTalentV2()
    small = model.predict([observation(1, npxg=.9)], player_id="ply_a",
                          target_fixture_id="target", prediction_timestamp=NOW,
                          current_team_id="team_a", current_competition_id="comp_pl")
    large = model.predict([observation(index, npxg=.9) for index in range(7)],
                          player_id="ply_a", target_fixture_id="target",
                          prediction_timestamp=NOW, current_team_id="team_a",
                          current_competition_id="comp_pl")
    assert large.talent_npxg_per90 > small.talent_npxg_per90 > .22
    missing = model.predict([observation(1, xa=None)], player_id="ply_a",
                            target_fixture_id="target", prediction_timestamp=NOW,
                            current_team_id="team_a", current_competition_id="comp_pl")
    zero = model.predict([observation(1, xa=0)], player_id="ply_a",
                         target_fixture_id="target", prediction_timestamp=NOW,
                         current_team_id="team_a", current_competition_id="comp_pl")
    assert missing.talent_xa_per90 == pytest.approx(.18)
    assert zero.talent_xa_per90 < missing.talent_xa_per90
    assert not missing.data_quality["has_xa_data"] and zero.data_quality["has_xa_data"]
    common = dict(effective_from=NOW-timedelta(days=3), known_at=NOW-timedelta(days=3),
                  source="lineup", confidence=1, player_id="ply_new", team_id="team_a",
                  fpl_position="FWD")
    tactical = TacticalContextEngine().resolve(
        player_id="ply_new", team_id="team_a", prediction_timestamp=NOW,
        roles=[RoleRecord(tactical_role=TacticalRole.CENTRE_FORWARD, **common)],
    )
    centre = model.predict([], player_id="ply_new", target_fixture_id="target",
                           prediction_timestamp=NOW, current_team_id="team_a",
                           fpl_position="FWD", tactical_context=tactical)
    plain = model.predict([], player_id="ply_new2", target_fixture_id="target",
                          prediction_timestamp=NOW, current_team_id="team_a", fpl_position="FWD")
    assert centre.talent_npxg_per90 > plain.talent_npxg_per90
    repeat = model.predict([observation(1, npxg=.9)], player_id="ply_a",
                           target_fixture_id="target", prediction_timestamp=NOW,
                           current_team_id="team_a", current_competition_id="comp_pl")
    assert repeat == small


def test_talent_v2_cross_league_requires_evidence_cohort_and_time():
    history = [observation(1, competition="Bundesliga", npxg=.7)]
    weak = LeagueTranslationEvidence(.8, 5, NOW-timedelta(days=30), "transfer cohort")
    strong = LeagueTranslationEvidence(.8, 40, NOW-timedelta(days=30), "transfer cohort")
    fallback = PlayerTalentV2(PlayerTalentV2Config(
        translation_evidence={"Bundesliga->comp_pl": weak},
    )).predict(history, player_id="ply_a", target_fixture_id="target",
               prediction_timestamp=NOW, current_team_id="team_a",
               current_competition_id="comp_pl")
    translated = PlayerTalentV2(PlayerTalentV2Config(
        translation_evidence={"Bundesliga->comp_pl": strong},
    )).predict(history, player_id="ply_a", target_fixture_id="target",
               prediction_timestamp=NOW, current_team_id="team_a",
               current_competition_id="comp_pl")
    assert fallback.cross_league_status == "unsupported_fallback"
    assert translated.cross_league_status == "evidence_backed_translation"
    assert fallback.player_talent_uncertainty > translated.player_talent_uncertainty


def test_probabilistic_role_and_set_piece_hierarchy_are_temporal():
    common = dict(effective_from=NOW-timedelta(days=3), known_at=NOW-timedelta(days=3),
                  source="manual", confidence=.9, team_id="team_a")
    pieces = [
        SetPieceRecord(player_id="ply_a", set_piece_type=SetPieceType.PENALTIES, rank=1, **common),
        SetPieceRecord(player_id="ply_b", set_piece_type=SetPieceType.PENALTIES, rank=2, **common),
    ]
    allocation = set_piece_probabilities(
        pieces, team_id="team_a", set_piece_type=SetPieceType.PENALTIES,
        prediction_timestamp=NOW,
    )
    assert sum(allocation.probabilities.values()) + allocation.unassigned_probability == pytest.approx(1)
    assert allocation.probabilities["ply_a"] > allocation.probabilities["ply_b"] > 0
    roles = [RoleRecord(player_id="ply_a", tactical_role=TacticalRole.WINGER,
                        fpl_position="MID", **common)]
    distribution = role_distribution(roles, player_id="ply_a", team_id="team_a",
                                     prediction_timestamp=NOW)
    assert distribution.probabilities[TacticalRole.WINGER] > 0
    assert sum(distribution.probabilities.values()) + distribution.unknown_probability == pytest.approx(1)
    advanced = TacticalContextV2Engine().resolve(
        player_id="ply_a", team_id="team_a", prediction_timestamp=NOW,
        roles=roles, set_pieces=pieces,
    )
    assert advanced.base_context.player_id == "ply_a"
    assert advanced.role_distribution == distribution
    assert advanced.set_piece_probabilities[SetPieceType.PENALTIES] == allocation
    assert 0 <= advanced.context_confidence <= 1
    future = SetPieceRecord(
        player_id="ply_a", set_piece_type=SetPieceType.PENALTIES, rank=1,
        **{**common, "known_at": NOW+timedelta(days=1)},
    )
    with pytest.raises(LeakageError):
        set_piece_probabilities([future], team_id="team_a",
                                set_piece_type=SetPieceType.PENALTIES,
                                prediction_timestamp=NOW)


def test_assist_v2_is_coherent_feature_gated_and_deterministic():
    creator = event_input("ply_creator", key_passes=5, big_created=1)
    other = event_input("ply_other", key_passes=.5, big_created=0)
    kwargs = dict(fixture_id="fix_target", team_id="team_a", prediction_timestamp=NOW,
                  expected_team_goals=1.8, expected_opponent_goals=1.0, squad_coverage=.9)
    v1 = EventModels().predict_team([creator, other], **kwargs)
    model = EventModelsV2()
    opportunity = model.assist_opportunity(v1.allocated_player_goals)
    assert opportunity.expected_assist_eligible_goals == pytest.approx(
        v1.allocated_player_goals * model.config.assisted_goal_fraction
    )
    assert 0 < opportunity.probability_at_least_one_assist_eligible_goal < 1
    v2 = model.predict_team([creator, other], **kwargs)
    assert v2 == model.predict_team([creator, other], **kwargs)
    assert v2.players[0].assists.expected_assists > v1.players[0].assists.expected_assists
    assert sum(row.assists.expected_assists for row in v2.players) == pytest.approx(v2.expected_team_assists)
    assert v2.expected_team_assists <= v2.allocated_player_goals
    assert [row.goals for row in v2.players] == [row.goals for row in v1.players]
    lower_quality = replace(
        creator, talent=replace(creator.talent, sample_reliability=.01),
    )
    low = model.predict_team([lower_quality, other], **kwargs)
    assert low.players[0].assists.expected_assists == pytest.approx(
        v2.players[0].assists.expected_assists
    )
    assert low.players[0].confidence < v2.players[0].confidence


def test_penalty_v2_separates_team_rate_taker_and_conversion():
    primary = event_input("ply_primary", penalty_rank=1)
    secondary = event_input("ply_secondary", penalty_rank=2)
    evidence = [TeamPenaltyEvidence(
        "team_a", NOW-timedelta(days=2), NOW-timedelta(days=2)+timedelta(hours=3),
        10, 2, 1, "fix_old",
    )]
    result = PenaltyModelV2().predict(
        [primary, secondary], team_id="team_a", fixture_id="fix_target",
        prediction_timestamp=NOW, evidence=evidence,
    )
    assert result.taker_probabilities["ply_primary"] > result.taker_probabilities["ply_secondary"]
    assert sum(result.taker_probabilities.values()) + result.unassigned_taker_probability == pytest.approx(1)
    assert 0 < result.miss_probability < result.award_probability < 1
    with pytest.raises(TargetFixtureLeakageError):
        PenaltyModelV2().predict(
            [primary], team_id="team_a", fixture_id="fix_old",
            prediction_timestamp=NOW, evidence=evidence,
        )


def test_bps_matrix_and_confidence_preserve_unknowns_without_changing_ev():
    matrix = load_bps_support_matrix(ROOT)
    assert matrix.season == "2026/27" and 0 < matrix.completeness < 1
    unsupported = {row.component for row in matrix.entries if not row.supported}
    assert "passing.completion_90_plus_percent" in unsupported
    assert "goalkeeper.save_from_big_chance" in unsupported
    complete = assess_data_quality(DataQualitySignals(**{
        name: 1.0 for name in DataQualitySignals.__dataclass_fields__
    }))
    sparse = assess_data_quality(DataQualitySignals(minutes_confidence=1.0))
    assert complete.confidence == 1 and sparse.confidence < complete.confidence
    assert "bps_completeness" in sparse.missing_factors


def test_v1_files_remain_byte_reproducible_and_challengers_are_not_promoted():
    frozen = json.loads((ROOT / "data/processed/advanced/baseline_manifest_20260910T113453Z.json").read_text())
    for name, expected in frozen["file_sha256"].items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == expected
    champions = (ROOT / "config/v1_champions.yaml").read_text(encoding="utf-8")
    assert "status: KEEP_TESTING" in champions
    assert "player_talent_empirical_bayes_v1" in champions
    assert "coherent_assists_v2" not in champions


def test_advanced_walk_forward_is_temporal_and_deterministic():
    rows = [observation(index) for index in range(1, 8)]
    report = walk_forward_advanced_talent(rows, minimum_history=2)
    assert report == walk_forward_advanced_talent(reversed(rows), minimum_history=2)
    assert report.leakage_violations == 0
    assert len(report.prediction_order) == 5
    by_name = {candidate.model_id: candidate for candidate in report.candidates}
    assert set(by_name) == {
        "season_to_date_per90_v1", "exponentially_weighted_per90_v1",
        "player_talent_empirical_bayes_v1", "player_talent_reliability_v2",
    }
    assert all(candidate.xa.observations == 5 for candidate in report.candidates)


def test_current_runtime_is_manifest_driven_and_defaults_remain_v1():
    frozen = _load_active_model_manifest(ROOT, "2026/27")
    _, _, talent, events = _runtime_model_stack(frozen)
    assert isinstance(talent, PlayerTalentModel)
    assert type(events) is EventModels
    challenger = {
        **frozen,
        "active": {**frozen["active"], "event_models": {
            **frozen["active"]["event_models"],
        }},
    }
    challenger["active"]["player_talent"] = "player_talent_reliability_v2"
    challenger["active"]["event_models"]["assists"] = "coherent_assists_v2"
    _, _, talent, events = _runtime_model_stack(challenger)
    assert isinstance(talent, PlayerTalentV2)
    assert isinstance(events, EventModelsV2)
