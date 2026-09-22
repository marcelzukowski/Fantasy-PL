from datetime import datetime,timedelta,timezone
import duckdb,pytest
from fpl_engine.data.database import CanonicalDatabase,CanonicalIntegrityError
from fpl_engine.data.schemas.entities import *
NOW=datetime(2026,1,1,tzinfo=timezone.utc)
def p():return Player(player_id="ply_a",canonical_name="Alex",identity_status=IdentityStatus.confirmed,created_at=NOW,updated_at=NOW)
def t(id):return Team(team_id=id,canonical_name=id,created_at=NOW,updated_at=NOW)
def test_schema_is_idempotent_roundtrip_nulls_constraints_and_parquet(tmp_path):
    db=CanonicalDatabase(tmp_path/"canonical.duckdb");db.create_schema();assert set(db.tables())>= {"dim_player","dim_fixture","fact_fpl_snapshot"}
    db.persist_player(p());db.persist_team(t("team_a"));db.persist_team(t("team_b"));db.persist_competition(Competition(competition_id="comp_a",canonical_name="League",created_at=NOW,updated_at=NOW))
    assert db.connection.execute("select first_name from dim_player").fetchone()==(None,)
    mapping=PlayerProviderMapping(player_id="ply_a",provider="official_fpl_api",provider_id="44",effective_from=NOW,effective_to=None,match_method=MatchMethod.exact_external_id,match_confidence=1,review_status=ReviewStatus.confirmed,created_at=NOW,updated_at=NOW,retrieved_at=NOW)
    db.persist_player_mapping(mapping)
    with pytest.raises(CanonicalIntegrityError):db.persist_player_mapping(mapping)
    spell=PlayerTeamSpell(player_id="ply_a",team_id="team_a",effective_from=NOW,effective_to=NOW+timedelta(days=2),source="official_fpl_api",retrieved_at=NOW,confidence=1);db.persist_player_team_spell(spell)
    with pytest.raises(CanonicalIntegrityError):db.persist_player_team_spell(PlayerTeamSpell(player_id="ply_a",team_id="team_b",effective_from=NOW+timedelta(days=1),source="x",retrieved_at=NOW,confidence=1))
    fixture=Fixture(fixture_id="fix_a",competition_id="comp_a",season="2025",home_team_id="team_a",away_team_id="team_b",scheduled_kickoff=NOW,status="scheduled",created_at=NOW,updated_at=NOW);db.persist_fixture(fixture);db.persist_fixture(fixture.model_copy(update={"scheduled_kickoff":NOW+timedelta(days=3),"updated_at":NOW+timedelta(days=1)}))
    assert db.connection.execute("select count(*),strftime(scheduled_kickoff, '%Y-%m-%dT%H:%M:%SZ') from dim_fixture group by scheduled_kickoff").fetchone()==(1,"2026-01-04T00:00:00Z")
    out=tmp_path/"parquet";db.export_parquet(out);assert (out/"dim_player.parquet").exists() and duckdb.connect().execute("select player_id from read_parquet(?)",[str(out/"dim_player.parquet")]).fetchone()==("ply_a",)
    db.close()
