"""DATA-012..014 provider-to-canonical fact ingestion and snapshot selection."""
from datetime import datetime, timezone
import json
from .database import CanonicalDatabase, CanonicalIntegrityError
class CanonicalFactError(Exception): pass
class CanonicalFactResolutionError(CanonicalFactError): pass
def _utc(v):
    if not isinstance(v,datetime) or v.tzinfo is None or v.utcoffset() is None: raise CanonicalFactError("timestamps must be aware")
    return v.astimezone(timezone.utc)
class CanonicalFactBuilder:
    def __init__(self,database:CanonicalDatabase): self.db=database
    def player_fixture(self,*,provider,provider_player_id,provider_fixture_id,effective_at,retrieved_at,gameweek=None,payload=None):
        at=_utc(effective_at); player=self.db.resolve_mapping("player",provider,provider_player_id,at); fixture=self.db.resolve_mapping("fixture",provider,provider_fixture_id,at)
        if player is None or fixture is None: raise CanonicalFactResolutionError("provider player/fixture mapping is unresolved at effective time")
        self._insert("fact_player_fixture",[player,fixture,provider,str(provider_fixture_id),_utc(retrieved_at),gameweek,at,json.dumps(payload or {})])
        return player,fixture
    def team_fixture(self,*,provider,provider_team_id,provider_fixture_id,effective_at,retrieved_at,gameweek=None,payload=None):
        at=_utc(effective_at); team=self.db.resolve_mapping("team",provider,provider_team_id,at); fixture=self.db.resolve_mapping("fixture",provider,provider_fixture_id,at)
        if team is None or fixture is None: raise CanonicalFactResolutionError("provider team/fixture mapping is unresolved at effective time")
        self._insert("fact_team_fixture",[team,fixture,provider,str(provider_fixture_id),_utc(retrieved_at),gameweek,at,json.dumps(payload or {})]);return team,fixture
    def fpl_snapshot(self,*,snapshot_id,snapshot_timestamp,retrieved_at,source_provider,source_record_id=None,entity="bootstrap_static",payload=None):
        at=_utc(snapshot_timestamp);self.db.connection.execute("INSERT INTO fact_fpl_snapshot VALUES (?,?,?,?,?,?,?,?)",[snapshot_id,at,source_provider,source_record_id,_utc(retrieved_at),entity,at,json.dumps(payload or {})]);return snapshot_id
    def resolve_state(self,entity,prediction_timestamp):
        at=_utc(prediction_timestamp)
        row=self.db.connection.execute("SELECT snapshot_id,CAST(snapshot_timestamp AS VARCHAR),source_provider,source_record_id,CAST(retrieved_at AS VARCHAR),entity,CAST(effective_at AS VARCHAR),provider_payload FROM fact_fpl_snapshot WHERE entity=? AND snapshot_timestamp<? ORDER BY snapshot_timestamp DESC LIMIT 1",[entity,at]).fetchone()
        return row
    def _insert(self,table,values):
        try:self.db.connection.execute(f"INSERT INTO {table} VALUES ({','.join('?' for _ in values)})",values)
        except Exception as exc: raise CanonicalIntegrityError(f"Duplicate/conflicting fact in {table}") from exc
