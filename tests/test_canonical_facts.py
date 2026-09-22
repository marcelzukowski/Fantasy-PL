from datetime import datetime,timedelta,timezone
import pytest
from fpl_engine.data.database import CanonicalDatabase,CanonicalIntegrityError
from fpl_engine.data.canonical_facts import CanonicalFactBuilder,CanonicalFactResolutionError
from fpl_engine.data.schemas.entities import *
N=datetime(2026,1,1,tzinfo=timezone.utc)
def mapping(cls,field,ident,provider_id):return cls(**{field:ident,"provider":"fpl","provider_id":provider_id,"effective_from":N,"effective_to":None,"match_method":MatchMethod.exact_external_id,"match_confidence":1,"review_status":ReviewStatus.confirmed,"created_at":N,"updated_at":N,"retrieved_at":N})
def test_player_team_facts_dgw_and_rescheduled_fixture_keep_identity(tmp_path):
 d=CanonicalDatabase(tmp_path/'x.duckdb');d.persist_player(Player(player_id='ply_a',canonical_name='a',identity_status=IdentityStatus.confirmed,created_at=N,updated_at=N));d.persist_team(Team(team_id='team_a',canonical_name='a',created_at=N,updated_at=N));d.persist_team(Team(team_id='team_b',canonical_name='b',created_at=N,updated_at=N));d.persist_fixture(Fixture(fixture_id='fix_a',competition_id='comp_a',season='2025',home_team_id='team_a',away_team_id='team_b',scheduled_kickoff=N,status='scheduled',created_at=N,updated_at=N));d.persist_player_mapping(mapping(PlayerProviderMapping,'player_id','ply_a','1'));d.persist_team_mapping(mapping(TeamProviderMapping,'team_id','team_a','10'));d.persist_fixture_mapping(mapping(FixtureProviderMapping,'fixture_id','fix_a','99'))
 b=CanonicalFactBuilder(d);assert b.player_fixture(provider='fpl',provider_player_id='1',provider_fixture_id='99',effective_at=N,retrieved_at=N,gameweek=2,payload={'xP':9})==('ply_a','fix_a');assert b.team_fixture(provider='fpl',provider_team_id='10',provider_fixture_id='99',effective_at=N,retrieved_at=N,gameweek=2)==('team_a','fix_a')
 d.persist_fixture(Fixture(fixture_id='fix_a',competition_id='comp_a',season='2025',home_team_id='team_a',away_team_id='team_b',scheduled_kickoff=N+timedelta(days=3),status='rescheduled',created_at=N,updated_at=N));assert d.connection.execute('select fixture_id,gameweek from fact_player_fixture').fetchone()==('fix_a',2)
 with pytest.raises(CanonicalIntegrityError):b.player_fixture(provider='fpl',provider_player_id='1',provider_fixture_id='99',effective_at=N,retrieved_at=N,gameweek=2)
def test_snapshot_resolver_never_falls_forward(tmp_path):
 d=CanonicalDatabase(tmp_path/'x.duckdb');b=CanonicalFactBuilder(d);b.fpl_snapshot(snapshot_id='a',snapshot_timestamp=N,retrieved_at=N,source_provider='local_fpl_archive',payload={'xP':'unsafe'});b.fpl_snapshot(snapshot_id='b',snapshot_timestamp=N+timedelta(hours=2),retrieved_at=N+timedelta(hours=2),source_provider='local_fpl_archive')
 assert b.resolve_state('bootstrap_static',N+timedelta(hours=1))[0]=='a';assert b.resolve_state('bootstrap_static',N-timedelta(seconds=1)) is None
 assert b.resolve_state('bootstrap_static',N) is None
