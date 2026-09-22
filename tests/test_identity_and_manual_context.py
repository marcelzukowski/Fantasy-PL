from datetime import datetime,timedelta,timezone
from pathlib import Path
import pytest
from fpl_engine.data.manual_context import ManualContextRecord,active_context,load_manual_context
from fpl_engine.data.identity import IdentityRegistry,IdentityResolutionError,review_status
from fpl_engine.data.schemas.entities import *
NOW=datetime(2026,1,1,tzinfo=timezone.utc)
def player(pid="ply_a"):return Player(player_id=pid,canonical_name="Alex",created_at=NOW,updated_at=NOW,identity_status=IdentityStatus.confirmed)
def team(tid):return Team(team_id=tid,canonical_name=tid,created_at=NOW,updated_at=NOW)
def test_canonical_contracts_mappings_thresholds_and_no_fuzzy_confirmation():
    assert canonical_id("ply").startswith("ply_") and canonical_id("ply")!="123"
    assert review_status(.99,MatchMethod.fuzzy_name_dob) is ReviewStatus.confirmed
    assert review_status(.95,MatchMethod.fuzzy_name_dob) is ReviewStatus.flagged_for_review
    assert review_status(.8,MatchMethod.fuzzy_name_dob) is ReviewStatus.manual_review
    r=IdentityRegistry();r.add_player(player());m=PlayerProviderMapping(player_id="ply_a",provider="official_fpl_api",provider_id="44",provider_name="Alex",effective_from=NOW,effective_to=None,match_method=MatchMethod.exact_external_id,match_confidence=1,review_status=ReviewStatus.confirmed,created_at=NOW,updated_at=NOW,retrieved_at=NOW)
    r.add_mapping(m);assert r.resolve_player("official_fpl_api","44",NOW)=="ply_a"
    assert r.candidate("ply_a",.8,MatchMethod.fuzzy_name_dob).canonical_id=="ply_a"
def test_transfers_spells_fixture_reschedule_and_gameweek_absence():
    r=IdentityRegistry();r.add_team(team("team_a"));r.add_team(team("team_b"));r.add_player(player())
    a=PlayerTeamSpell(player_id="ply_a",team_id="team_a",effective_from=NOW,effective_to=NOW+timedelta(days=2),source="x",retrieved_at=NOW,confidence=1)
    b=PlayerTeamSpell(player_id="ply_a",team_id="team_b",effective_from=NOW+timedelta(days=3),source="x",retrieved_at=NOW,confidence=1)
    r.add_player_spell(a);r.add_player_spell(b);assert r.team_for_player("ply_a",NOW+timedelta(days=4))=="team_b"
    f=Fixture(fixture_id="fix_a",competition_id="comp",season="2025",home_team_id="team_a",away_team_id="team_b",scheduled_kickoff=NOW,status="scheduled",created_at=NOW,updated_at=NOW);r.add_fixture(f)
    assert r.match_fixture("comp","2025","team_a","team_b",NOW+timedelta(hours=47)).fixture_id=="fix_a"
    assert r.reschedule_fixture("fix_a",NOW+timedelta(days=7),NOW).fixture_id=="fix_a"
def test_manual_context_created_and_effective_time_are_both_required_for_historical_use():
    record=ManualContextRecord(context_type="manager_change",subject_type="team",subject_id="team_a",value="x",effective_from=NOW,effective_to=NOW+timedelta(days=2),created_at=NOW+timedelta(days=1),confidence=.9,reason="announcement",author="editor")
    assert not record.is_active_at(NOW) and record.is_active_at(NOW+timedelta(days=1))
    assert not active_context((record,),NOW+timedelta(days=3))

def test_manual_context_loader_reads_empty_versioned_default():
    assert load_manual_context(Path("config/manual_context.yaml")) == ()
