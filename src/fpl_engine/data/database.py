"""DATA-011 canonical DuckDB schema and reproducible Parquet exports."""
from pathlib import Path
from typing import Any
import duckdb
from .schemas.entities import (
    Competition, Fixture, Manager, Player, PlayerProviderMapping, PlayerTeamSpell,
    Team, TeamProviderMapping, ManagerTeamSpell, FixtureProviderMapping, ManagerProviderMapping,
)

class CanonicalDatabaseError(Exception): pass
class CanonicalIntegrityError(CanonicalDatabaseError): pass
_TABLES=("dim_player","dim_team","dim_fixture","dim_manager","dim_competition","dim_player_provider_map","dim_team_provider_map","dim_fixture_provider_map","dim_manager_provider_map","dim_player_team_spell","dim_manager_team_spell","fact_player_fixture","fact_team_fixture","fact_fpl_snapshot")
_DDL="""
CREATE TABLE IF NOT EXISTS dim_player (player_id VARCHAR PRIMARY KEY, canonical_name VARCHAR NOT NULL, first_name VARCHAR, last_name VARCHAR, known_as VARCHAR, date_of_birth VARCHAR, nationality VARCHAR, preferred_foot VARCHAR, identity_status VARCHAR NOT NULL, created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL);
CREATE TABLE IF NOT EXISTS dim_team (team_id VARCHAR PRIMARY KEY, canonical_name VARCHAR NOT NULL, short_name VARCHAR, country VARCHAR, city VARCHAR, created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL);
CREATE TABLE IF NOT EXISTS dim_competition (competition_id VARCHAR PRIMARY KEY, canonical_name VARCHAR NOT NULL, country VARCHAR, created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL);
CREATE TABLE IF NOT EXISTS dim_manager (manager_id VARCHAR PRIMARY KEY, canonical_name VARCHAR NOT NULL, created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL);
CREATE TABLE IF NOT EXISTS dim_fixture (fixture_id VARCHAR PRIMARY KEY, competition_id VARCHAR NOT NULL, season VARCHAR NOT NULL, home_team_id VARCHAR NOT NULL, away_team_id VARCHAR NOT NULL, scheduled_kickoff TIMESTAMPTZ NOT NULL, status VARCHAR NOT NULL, created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL, CHECK(home_team_id <> away_team_id));
CREATE TABLE IF NOT EXISTS dim_player_provider_map (player_id VARCHAR NOT NULL, provider VARCHAR NOT NULL, provider_id VARCHAR NOT NULL, provider_name VARCHAR, effective_from TIMESTAMPTZ NOT NULL, effective_to TIMESTAMPTZ, match_method VARCHAR NOT NULL, match_confidence DOUBLE NOT NULL CHECK(match_confidence BETWEEN 0 AND 1), review_status VARCHAR NOT NULL, created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL, source_record_id VARCHAR, retrieved_at TIMESTAMPTZ, UNIQUE(provider,provider_id,effective_from));
CREATE TABLE IF NOT EXISTS dim_team_provider_map (team_id VARCHAR NOT NULL, provider VARCHAR NOT NULL, provider_id VARCHAR NOT NULL, provider_name VARCHAR, effective_from TIMESTAMPTZ NOT NULL, effective_to TIMESTAMPTZ, match_method VARCHAR NOT NULL, match_confidence DOUBLE NOT NULL CHECK(match_confidence BETWEEN 0 AND 1), review_status VARCHAR NOT NULL, created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL, source_record_id VARCHAR, retrieved_at TIMESTAMPTZ, UNIQUE(provider,provider_id,effective_from));
CREATE TABLE IF NOT EXISTS dim_fixture_provider_map (fixture_id VARCHAR NOT NULL, provider VARCHAR NOT NULL, provider_id VARCHAR NOT NULL, provider_name VARCHAR, effective_from TIMESTAMPTZ NOT NULL, effective_to TIMESTAMPTZ, match_method VARCHAR NOT NULL, match_confidence DOUBLE NOT NULL CHECK(match_confidence BETWEEN 0 AND 1), review_status VARCHAR NOT NULL, created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL, source_record_id VARCHAR, retrieved_at TIMESTAMPTZ, provider_kickoff TIMESTAMPTZ, UNIQUE(provider,provider_id,effective_from));
CREATE TABLE IF NOT EXISTS dim_manager_provider_map (manager_id VARCHAR NOT NULL, provider VARCHAR NOT NULL, provider_id VARCHAR NOT NULL, provider_name VARCHAR, effective_from TIMESTAMPTZ NOT NULL, effective_to TIMESTAMPTZ, match_method VARCHAR NOT NULL, match_confidence DOUBLE NOT NULL CHECK(match_confidence BETWEEN 0 AND 1), review_status VARCHAR NOT NULL, created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL, source_record_id VARCHAR, retrieved_at TIMESTAMPTZ, UNIQUE(provider,provider_id,effective_from));
CREATE TABLE IF NOT EXISTS dim_player_team_spell (player_id VARCHAR NOT NULL, team_id VARCHAR NOT NULL, competition_id VARCHAR, effective_from TIMESTAMPTZ NOT NULL, effective_to TIMESTAMPTZ, transfer_type VARCHAR, source VARCHAR NOT NULL, source_record_id VARCHAR, retrieved_at TIMESTAMPTZ NOT NULL, confidence DOUBLE NOT NULL CHECK(confidence BETWEEN 0 AND 1), PRIMARY KEY(player_id,team_id,effective_from));
CREATE TABLE IF NOT EXISTS dim_manager_team_spell (manager_id VARCHAR NOT NULL, team_id VARCHAR NOT NULL, effective_from TIMESTAMPTZ NOT NULL, effective_to TIMESTAMPTZ, source VARCHAR NOT NULL, source_record_id VARCHAR, retrieved_at TIMESTAMPTZ NOT NULL, confidence DOUBLE NOT NULL CHECK(confidence BETWEEN 0 AND 1), PRIMARY KEY(manager_id,team_id,effective_from));
CREATE TABLE IF NOT EXISTS fact_player_fixture (player_id VARCHAR NOT NULL, fixture_id VARCHAR NOT NULL, source_provider VARCHAR, source_record_id VARCHAR, retrieved_at TIMESTAMPTZ, PRIMARY KEY(player_id,fixture_id));
CREATE TABLE IF NOT EXISTS fact_team_fixture (team_id VARCHAR NOT NULL, fixture_id VARCHAR NOT NULL, source_provider VARCHAR, source_record_id VARCHAR, retrieved_at TIMESTAMPTZ, PRIMARY KEY(team_id,fixture_id));
CREATE TABLE IF NOT EXISTS fact_fpl_snapshot (snapshot_id VARCHAR PRIMARY KEY, snapshot_timestamp TIMESTAMPTZ NOT NULL, source_provider VARCHAR NOT NULL, source_record_id VARCHAR, retrieved_at TIMESTAMPTZ NOT NULL);
ALTER TABLE fact_player_fixture ADD COLUMN IF NOT EXISTS gameweek INTEGER;
ALTER TABLE fact_player_fixture ADD COLUMN IF NOT EXISTS effective_at TIMESTAMPTZ;
ALTER TABLE fact_player_fixture ADD COLUMN IF NOT EXISTS provider_payload JSON;
ALTER TABLE fact_team_fixture ADD COLUMN IF NOT EXISTS gameweek INTEGER;
ALTER TABLE fact_team_fixture ADD COLUMN IF NOT EXISTS effective_at TIMESTAMPTZ;
ALTER TABLE fact_team_fixture ADD COLUMN IF NOT EXISTS provider_payload JSON;
ALTER TABLE fact_fpl_snapshot ADD COLUMN IF NOT EXISTS entity VARCHAR;
ALTER TABLE fact_fpl_snapshot ADD COLUMN IF NOT EXISTS effective_at TIMESTAMPTZ;
ALTER TABLE fact_fpl_snapshot ADD COLUMN IF NOT EXISTS provider_payload JSON;
"""
class CanonicalDatabase:
    def __init__(self,path:Path): self.path=Path(path); self.connection=duckdb.connect(str(self.path)); self.connection.execute("SET TimeZone='UTC'"); self.create_schema()
    def close(self): self.connection.close()
    def create_schema(self): self.connection.execute(_DDL)
    def tables(self): return tuple(row[0] for row in self.connection.execute("SHOW TABLES").fetchall())
    def _insert(self,table:str,obj,columns):
        values=obj.model_dump(mode="python")
        try:self.connection.execute(f"INSERT INTO {table} ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",[values.get(c) for c in columns])
        except duckdb.ConstraintException as exc: raise CanonicalIntegrityError(f"Conflicting canonical record in {table}") from exc
    def persist_player(self,x:Player): self._insert("dim_player",x,("player_id","canonical_name","first_name","last_name","known_as","date_of_birth","nationality","preferred_foot","identity_status","created_at","updated_at"))
    def persist_team(self,x:Team): self._insert("dim_team",x,("team_id","canonical_name","short_name","country","city","created_at","updated_at"))
    def persist_competition(self,x:Competition): self._insert("dim_competition",x,("competition_id","canonical_name","country","created_at","updated_at"))
    def persist_manager(self,x:Manager): self._insert("dim_manager",x,("manager_id","canonical_name","created_at","updated_at"))
    def persist_fixture(self,x:Fixture):
        v=x.model_dump(mode="python"); self.connection.execute("INSERT INTO dim_fixture VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(fixture_id) DO UPDATE SET scheduled_kickoff=excluded.scheduled_kickoff,status=excluded.status,updated_at=excluded.updated_at",[v[k] for k in ("fixture_id","competition_id","season","home_team_id","away_team_id","scheduled_kickoff","status","created_at","updated_at")])
    def persist_player_mapping(self,x:PlayerProviderMapping): self._mapping("dim_player_provider_map",x,"player_id")
    def persist_team_mapping(self,x:TeamProviderMapping): self._mapping("dim_team_provider_map",x,"team_id")
    def persist_fixture_mapping(self,x:FixtureProviderMapping): self._mapping("dim_fixture_provider_map",x,"fixture_id",True)
    def persist_manager_mapping(self,x:ManagerProviderMapping): self._mapping("dim_manager_provider_map",x,"manager_id")
    def _mapping(self,table,x,idcol,fixture=False):
        cols=(idcol,"provider","provider_id","provider_name","effective_from","effective_to","match_method","match_confidence","review_status","created_at","updated_at","source_record_id","retrieved_at")+( ("provider_kickoff",) if fixture else ())
        self._insert(table,x,cols)
    def _spell(self,table,x,idcol,cols):
        v=x.model_dump(mode="python"); condition=f"{idcol}=? AND ((effective_to IS NULL OR ? <= effective_to) AND (? IS NULL OR effective_from <= ?))"
        args=[v[idcol],v["effective_from"],v["effective_to"],v["effective_to"]]
        if self.connection.execute(f"SELECT 1 FROM {table} WHERE {condition}",args).fetchone(): raise CanonicalIntegrityError(f"Overlapping temporal spell in {table}")
        self._insert(table,x,cols)
    def persist_player_team_spell(self,x:PlayerTeamSpell): self._spell("dim_player_team_spell",x,"player_id",("player_id","team_id","competition_id","effective_from","effective_to","transfer_type","source","source_record_id","retrieved_at","confidence"))
    def persist_manager_team_spell(self,x:ManagerTeamSpell): self._spell("dim_manager_team_spell",x,"manager_id",("manager_id","team_id","effective_from","effective_to","source","source_record_id","retrieved_at","confidence"))
    def export_parquet(self,root:Path):
        root=Path(root);root.mkdir(parents=True,exist_ok=True)
        for table in _TABLES: self.connection.execute(f"COPY {table} TO ? (FORMAT PARQUET)",[str(root/f"{table}.parquet")])
    def resolve_mapping(self,entity,provider,provider_id,effective_at):
        table={"player":"dim_player_provider_map","team":"dim_team_provider_map","fixture":"dim_fixture_provider_map"}[entity]; col=f"{entity}_id"
        rows=self.connection.execute(f"SELECT {col} FROM {table} WHERE provider=? AND provider_id=? AND review_status='confirmed' AND effective_from<=? AND (effective_to IS NULL OR effective_to>=?)",[provider,str(provider_id),effective_at,effective_at]).fetchall()
        return rows[0][0] if len(rows)==1 else None
