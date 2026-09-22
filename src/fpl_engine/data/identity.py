"""In-memory identity contracts for ID-002..006; persistence starts at DATA-011."""
from dataclasses import dataclass
from datetime import datetime, timedelta
import re, unicodedata
from typing import Mapping
from .schemas.entities import *
class IdentityResolutionError(Exception): pass
def official_fpl_player_identity_key(record: Mapping[str, object]) -> str:
    """Return a deterministic identity key from Official FPL stable player code.

    Player names are display metadata only and must never be used as an
    automatic unique identity key. Different players can share the same name,
    while names of one player can change between seasons.

    A code change is deliberately NOT bridged automatically here. Such a
    cross-code merge requires separately evidenced identity resolution.
    """
    raw = record.get("code")
    if isinstance(raw, bool) or raw is None:
        raise IdentityResolutionError("official FPL player code is missing")

    if isinstance(raw, int):
        code = raw
    elif isinstance(raw, str) and raw.strip().isdigit():
        code = int(raw.strip())
    else:
        raise IdentityResolutionError("official FPL player code is invalid")

    if code <= 0:
        raise IdentityResolutionError("official FPL player code must be positive")

    return f"Premier League player code|{code}"

def normalize_name(value:str)->str:
    if type(value) is not str: raise IdentityResolutionError("name must be a string")
    return re.sub(r"[^a-z0-9]+","",unicodedata.normalize("NFKD",value).encode("ascii","ignore").decode().lower())
def review_status(confidence:float,method:MatchMethod)->ReviewStatus:
    if method is MatchMethod.manual_override or method is MatchMethod.exact_external_id: return ReviewStatus.confirmed
    if confidence>=.98: return ReviewStatus.confirmed
    if confidence>=.90: return ReviewStatus.flagged_for_review
    if confidence>=.75: return ReviewStatus.manual_review
    return ReviewStatus.unresolved
@dataclass(frozen=True)
class Candidate: canonical_id:str; confidence:float; method:MatchMethod
class IdentityRegistry:
    """Explicit registry: fuzzy candidates never create/confirm a mapping themselves."""
    def __init__(self): self.players={};self.teams={};self.fixtures={};self.managers={};self.player_maps=[];self.team_maps=[];self.fixture_maps=[];self.manager_maps=[];self.player_spells=[];self.manager_spells=[]
    def add_player(self,p:Player): self.players.setdefault(p.player_id,p); return self.players[p.player_id]
    def add_team(self,t:Team): self.teams.setdefault(t.team_id,t); return self.teams[t.team_id]
    def add_fixture(self,f:Fixture): self.fixtures.setdefault(f.fixture_id,f); return self.fixtures[f.fixture_id]
    def add_manager(self,m:Manager): self.managers.setdefault(m.manager_id,m); return self.managers[m.manager_id]
    def add_mapping(self,mapping):
        target= self.player_maps if isinstance(mapping,PlayerProviderMapping) else self.team_maps if isinstance(mapping,TeamProviderMapping) else self.fixture_maps if isinstance(mapping,FixtureProviderMapping) else self.manager_maps if isinstance(mapping,ManagerProviderMapping) else None
        if target is None: raise IdentityResolutionError("unsupported mapping")
        for old in target:
            if old.provider==mapping.provider and old.provider_id==mapping.provider_id and old.effective_from==mapping.effective_from and old!=mapping: raise IdentityResolutionError("provider mapping already exists")
        target.append(mapping); return mapping
    def resolve_player(self,provider,provider_id,at): return self._resolve(self.player_maps,provider,provider_id,at,"player_id")
    def resolve_team(self,provider,provider_id,at): return self._resolve(self.team_maps,provider,provider_id,at,"team_id")
    def resolve_fixture(self,provider,provider_id,at): return self._resolve(self.fixture_maps,provider,provider_id,at,"fixture_id")
    def _resolve(self,maps,provider,pid,at,field):
        eligible=[m for m in maps if m.provider==provider and m.provider_id==pid and m.effective_from<=at and (m.effective_to is None or at<=m.effective_to) and m.review_status is ReviewStatus.confirmed]
        return getattr(eligible[0],field) if len(eligible)==1 else None
    def candidate(self,canonical,confidence,method): return Candidate(canonical,confidence,method)
    def add_player_spell(self,spell:PlayerTeamSpell): self._spell(self.player_spells,spell,"player_id");return spell
    def add_manager_spell(self,spell:ManagerTeamSpell): self._spell(self.manager_spells,spell,"manager_id");return spell
    def _spell(self,items,spell,key):
        for old in items:
            if getattr(old,key)==getattr(spell,key) and (old.competition_id if hasattr(old,"competition_id") else None)==(spell.competition_id if hasattr(spell,"competition_id") else None):
                if (old.effective_to is None or spell.effective_from<=old.effective_to) and (spell.effective_to is None or old.effective_from<=spell.effective_to): raise IdentityResolutionError("temporal spells overlap")
        items.append(spell)
    def team_for_player(self,player_id,at): return self._spell_at(self.player_spells,"player_id",player_id,at,"team_id")
    def manager_for_team(self,team_id,at): return self._spell_at(self.manager_spells,"team_id",team_id,at,"manager_id")
    def _spell_at(self,spells,key,value,at,out):
        found=[s for s in spells if getattr(s,key)==value and s.effective_from<=at and (s.effective_to is None or at<=s.effective_to)]
        return getattr(found[0],out) if len(found)==1 else None
    def match_fixture(self,competition_id,season,home_team_id,away_team_id,kickoff):
        candidates=[f for f in self.fixtures.values() if (f.competition_id,f.season,f.home_team_id,f.away_team_id)==(competition_id,season,home_team_id,away_team_id) and abs(f.scheduled_kickoff-kickoff)<=timedelta(hours=48)]
        return candidates[0] if len(candidates)==1 else None
    def reschedule_fixture(self,fixture_id,kickoff,updated_at):
        old=self.fixtures[fixture_id]; updated=old.model_copy(update={"scheduled_kickoff":kickoff,"updated_at":updated_at});self.fixtures[fixture_id]=updated;return updated
