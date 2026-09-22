"""Immutable canonical entities, mappings and temporal spells (ID-001..006)."""
from datetime import datetime, timezone
from enum import StrEnum
from uuid import uuid4
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

class IdentityStatus(StrEnum): confirmed="confirmed"; auto_matched="auto_matched"; manual_review="manual_review"; unresolved="unresolved"; retired="retired"
class ReviewStatus(StrEnum): confirmed="confirmed"; flagged_for_review="flagged_for_review"; manual_review="manual_review"; unresolved="unresolved"
class MatchMethod(StrEnum):
    exact_external_id="exact_external_id"; exact_name_dob="exact_name_dob"; normalized_name_dob="normalized_name_dob"; name_team_dob="name_team_dob"; name_team="name_team"; fuzzy_name_dob="fuzzy_name_dob"; fuzzy_name_team="fuzzy_name_team"; cross_provider_bridge="cross_provider_bridge"; manual_override="manual_override"
def canonical_id(kind:str)->str: return f"{kind}_{uuid4().hex}"
def _utc(value):
    if not isinstance(value,datetime) or value.tzinfo is None or value.utcoffset() is None: raise ValueError("timestamps must be aware")
    return value.astimezone(timezone.utc)
class Contract(BaseModel):
    model_config=ConfigDict(frozen=True,strict=True,extra="forbid")
    @field_validator("created_at", "updated_at", "effective_from", "effective_to", "scheduled_kickoff", "provider_kickoff", "retrieved_at", check_fields=False)
    @classmethod
    def utc(cls,v): return _utc(v) if v is not None else None
class CanonicalEntity(Contract):
    created_at:datetime; updated_at:datetime
class Player(CanonicalEntity):
    player_id:str; canonical_name:str; first_name:str|None=None; last_name:str|None=None; known_as:str|None=None; date_of_birth:str|None=None; nationality:str|None=None; preferred_foot:str|None=None; identity_status:IdentityStatus
    @field_validator("player_id")
    @classmethod
    def canonical(cls,v):
        if not v.startswith("ply_"): raise ValueError("player_id must be a canonical ply_ ID")
        return v
class Team(CanonicalEntity):
    team_id:str; canonical_name:str; short_name:str|None=None; country:str|None=None; city:str|None=None
    @field_validator("team_id")
    @classmethod
    def canonical(cls,v):
        if not v.startswith("team_"): raise ValueError("team_id must be a canonical team_ ID")
        return v
class Competition(CanonicalEntity):
    competition_id:str; canonical_name:str; country:str|None=None
    @field_validator("competition_id")
    @classmethod
    def canonical(cls,v):
        if not v.startswith("comp_"): raise ValueError("competition_id must be a canonical comp_ ID")
        return v
class Manager(CanonicalEntity):
    manager_id:str; canonical_name:str
    @field_validator("manager_id")
    @classmethod
    def canonical(cls,v):
        if not v.startswith("mgr_"): raise ValueError("manager_id must be a canonical mgr_ ID")
        return v
class Fixture(CanonicalEntity):
    fixture_id:str; competition_id:str; season:str; home_team_id:str; away_team_id:str; scheduled_kickoff:datetime; status:str
    @model_validator(mode="after")
    def distinct(self):
        if self.home_team_id==self.away_team_id: raise ValueError("fixture teams must differ")
        return self
    @field_validator("fixture_id")
    @classmethod
    def canonical(cls,v):
        if not v.startswith("fix_"): raise ValueError("fixture_id must be a canonical fix_ ID")
        return v
class ProviderMapping(Contract):
    provider:str; provider_id:str; provider_name:str|None=None; effective_from:datetime; effective_to:datetime|None=None; match_method:MatchMethod; match_confidence:float=Field(ge=0,le=1); review_status:ReviewStatus; created_at:datetime; updated_at:datetime; source_record_id:str|None=None; retrieved_at:datetime|None=None
    @model_validator(mode="after")
    def interval(self):
        if self.effective_to is not None and self.effective_to < self.effective_from: raise ValueError("effective_to precedes effective_from")
        return self
class PlayerProviderMapping(ProviderMapping): player_id:str
class TeamProviderMapping(ProviderMapping): team_id:str
class FixtureProviderMapping(ProviderMapping): fixture_id:str; provider_kickoff:datetime|None=None
class ManagerProviderMapping(ProviderMapping): manager_id:str
class TemporalSpell(Contract):
    effective_from:datetime; effective_to:datetime|None=None; source:str; source_record_id:str|None=None; retrieved_at:datetime; confidence:float=Field(ge=0,le=1)
    @model_validator(mode="after")
    def interval(self):
        if self.effective_to is not None and self.effective_to < self.effective_from: raise ValueError("effective_to precedes effective_from")
        return self
class PlayerTeamSpell(TemporalSpell): player_id:str; team_id:str; competition_id:str|None=None; transfer_type:str|None=None
class ManagerTeamSpell(TemporalSpell): manager_id:str; team_id:str
