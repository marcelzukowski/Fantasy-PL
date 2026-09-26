"""Advisory-only player availability and minutes-risk snapshot."""
from __future__ import annotations
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import StrEnum
from hashlib import sha256
import json
from pathlib import Path
from time import perf_counter
from typing import Any, Mapping, Sequence

PLAYER_AVAILABILITY_SNAPSHOT_SCHEMA_V1 = "player_availability_snapshot_v1"
PLAYER_AVAILABILITY_RISK_METHOD_V1 = "player_availability_minutes_risk_v1"
FRESH_AFTER_HOURS, STALE_AFTER_HOURS = 36, 96

class PlayerAvailabilityRiskError(ValueError): pass
class AvailabilityStatus(StrEnum):
    AVAILABLE="AVAILABLE"; DOUBTFUL="DOUBTFUL"; INJURED="INJURED"; SUSPENDED="SUSPENDED"; UNAVAILABLE="UNAVAILABLE"; UNKNOWN="UNKNOWN"
class RiskLevel(StrEnum):
    LOW="LOW"; MEDIUM="MEDIUM"; HIGH="HIGH"; UNKNOWN="UNKNOWN"
class ConfidenceLevel(StrEnum):
    HIGH="HIGH"; MEDIUM="MEDIUM"; LOW="LOW"
class FreshnessStatus(StrEnum):
    FRESH="FRESH"; AGING="AGING"; STALE="STALE"; UNKNOWN="UNKNOWN"

def _utc(value: str|datetime, label: str) -> datetime:
    try: parsed=value if isinstance(value,datetime) else datetime.fromisoformat(str(value).replace("Z","+00:00"))
    except ValueError as exc: raise PlayerAvailabilityRiskError(f"{label} must be ISO-8601.") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None: raise PlayerAvailabilityRiskError(f"{label} must be timezone-aware.")
    return parsed.astimezone(timezone.utc)
def _iso(value: datetime|None)->str|None:return value.astimezone(timezone.utc).isoformat() if value else None
def _number(value: object)->float|None:return float(value) if isinstance(value,(int,float)) and not isinstance(value,bool) else None
def _integer(value: object)->int|None:return int(value) if isinstance(value,int) and not isinstance(value,bool) else None

@dataclass(frozen=True)
class RecentMinutesEvidence:
    minutes:int; started:bool|None; fixture_completed_at:str; known_at:str; source:str="HISTORICAL_MINUTES"
    def __post_init__(self):
        if not isinstance(self.minutes,int) or not 0<=self.minutes<=130: raise PlayerAvailabilityRiskError("recent minutes must be an integer in [0,130].")
        if self.started is not None and type(self.started) is not bool: raise PlayerAvailabilityRiskError("recent minutes started must be true, false, or unknown.")
        _utc(self.fixture_completed_at,"fixture_completed_at"); _utc(self.known_at,"recent minutes known_at")
    def to_dict(self)->dict[str,Any]:return asdict(self)
    @classmethod
    def from_dict(cls,raw:Mapping[str,Any])->"RecentMinutesEvidence":
        try:return cls(int(raw["minutes"]),raw.get("started") if type(raw.get("started")) is bool else None,str(raw["fixture_completed_at"]),str(raw["known_at"]),str(raw.get("source") or "HISTORICAL_MINUTES"))
        except (KeyError,TypeError,ValueError) as exc:raise PlayerAvailabilityRiskError("recent minutes evidence is invalid.") from exc

@dataclass(frozen=True)
class PlayerAvailabilityRisk:
    schema_version:str; context_id:str; player_id:str; player_name:str|None; evaluated_at:str; planning_gw:int
    availability_status:AvailabilityStatus; chance_of_playing:int|None; official_status_code:str|None; official_news:str|None; official_news_timestamp:str|None
    projected_minutes:float|None; recent_minutes:tuple[RecentMinutesEvidence,...]
    minutes_last_1:int|None; minutes_last_3:int|None; minutes_last_5:int|None; starts_last_3:int|None; starts_last_5:int|None; zero_minute_games_last_5:int|None; sub_appearances_last_5:int|None; average_minutes_when_started:float|None
    availability_risk:RiskLevel; minutes_risk:RiskLevel; overall_risk:RiskLevel; reasons:tuple[str,...]; confidence:ConfidenceLevel; freshness:FreshnessStatus
    observed_at:str|None; source_timestamp:str|None; age_hours:float|None; provenance:tuple[str,...]
    def __post_init__(self):
        if self.schema_version!=PLAYER_AVAILABILITY_SNAPSHOT_SCHEMA_V1 or not self.context_id or not self.player_id or self.planning_gw<1:raise PlayerAvailabilityRiskError("availability risk identity is invalid.")
        _utc(self.evaluated_at,"evaluated_at")
        for value,label in ((self.official_news_timestamp,"news timestamp"),(self.observed_at,"observed_at"),(self.source_timestamp,"source timestamp")):
            if value is not None:_utc(value,label)
        if self.chance_of_playing is not None and not 0<=self.chance_of_playing<=100:raise PlayerAvailabilityRiskError("chance_of_playing must be in [0,100].")
    def to_dict(self)->dict[str,Any]:
        raw=asdict(self)
        for key in ("availability_status","availability_risk","minutes_risk","overall_risk","confidence","freshness"):raw[key]=str(raw[key])
        return raw
    @classmethod
    def from_dict(cls,raw:Mapping[str,Any])->"PlayerAvailabilityRisk":
        try:return cls(
            str(raw["schema_version"]),str(raw["context_id"]),str(raw["player_id"]),str(raw["player_name"]) if raw.get("player_name") is not None else None,str(raw["evaluated_at"]),int(raw["planning_gw"]),
            AvailabilityStatus(str(raw["availability_status"])),_integer(raw.get("chance_of_playing")),str(raw["official_status_code"]) if raw.get("official_status_code") else None,str(raw["official_news"]) if raw.get("official_news") else None,str(raw["official_news_timestamp"]) if raw.get("official_news_timestamp") else None,
            _number(raw.get("projected_minutes")),tuple(RecentMinutesEvidence.from_dict(v) for v in raw.get("recent_minutes",()) if isinstance(v,Mapping)),
            *(_integer(raw.get(k)) for k in ("minutes_last_1","minutes_last_3","minutes_last_5","starts_last_3","starts_last_5","zero_minute_games_last_5","sub_appearances_last_5")),_number(raw.get("average_minutes_when_started")),
            RiskLevel(str(raw["availability_risk"])),RiskLevel(str(raw["minutes_risk"])),RiskLevel(str(raw["overall_risk"])),tuple(str(v) for v in raw.get("reasons",())),ConfidenceLevel(str(raw["confidence"])),FreshnessStatus(str(raw["freshness"])),
            str(raw["observed_at"]) if raw.get("observed_at") else None,str(raw["source_timestamp"]) if raw.get("source_timestamp") else None,_number(raw.get("age_hours")),tuple(str(v) for v in raw.get("provenance",())))
        except (KeyError,TypeError,ValueError) as exc:raise PlayerAvailabilityRiskError("availability risk payload is invalid.") from exc

@dataclass(frozen=True)
class PlayerAvailabilitySnapshot:
    schema_version:str; context_id:str; generated_at:str; planning_gw:int; method_version:str; entries:tuple[PlayerAvailabilityRisk,...]; coverage:Mapping[str,Any]; source:Mapping[str,Any]; warnings:tuple[str,...]; metrics:Mapping[str,Any]
    def __post_init__(self):
        if self.schema_version!=PLAYER_AVAILABILITY_SNAPSHOT_SCHEMA_V1 or not self.context_id or self.planning_gw<1:raise PlayerAvailabilityRiskError("availability snapshot identity is invalid.")
        _utc(self.generated_at,"generated_at")
        if any(v.context_id!=self.context_id or v.planning_gw!=self.planning_gw for v in self.entries):raise PlayerAvailabilityRiskError("snapshot context mismatch.")
    def to_dict(self)->dict[str,Any]:return {"schema_version":self.schema_version,"context_id":self.context_id,"generated_at":self.generated_at,"planning_gw":self.planning_gw,"method_version":self.method_version,"entries":[v.to_dict() for v in self.entries],"coverage":dict(self.coverage),"source":dict(self.source),"warnings":list(self.warnings),"metrics":dict(self.metrics)}
    @classmethod
    def from_dict(cls,raw:Mapping[str,Any])->"PlayerAvailabilitySnapshot":
        try:return cls(str(raw["schema_version"]),str(raw["context_id"]),str(raw["generated_at"]),int(raw["planning_gw"]),str(raw["method_version"]),tuple(PlayerAvailabilityRisk.from_dict(v) for v in raw.get("entries",()) if isinstance(v,Mapping)),dict(raw.get("coverage",{})),dict(raw.get("source",{})),tuple(str(v) for v in raw.get("warnings",())),dict(raw.get("metrics",{})))
        except (KeyError,TypeError,ValueError) as exc:raise PlayerAvailabilityRiskError("availability snapshot payload is invalid.") from exc

def _availability(provider:Mapping[str,Any],observed:datetime|None):
    code=str(provider.get("status") or "").strip().lower() or None; chance=_integer(provider.get("chance_of_playing_next_round")); chance=_integer(provider.get("chance_of_playing_this_round")) if chance is None else chance; news=str(provider.get("news") or "").strip() or None; news_at=_utc(provider["news_added"],"official news timestamp") if provider.get("news_added") else None
    if observed is None:return AvailabilityStatus.UNKNOWN,RiskLevel.UNKNOWN,chance,code,news,news_at,["Official FPL availability provenance is unavailable."]
    if code in {"i","s","u"}:
        status={"i":AvailabilityStatus.INJURED,"s":AvailabilityStatus.SUSPENDED,"u":AvailabilityStatus.UNAVAILABLE}[code]
        return status,RiskLevel.HIGH,chance,code,news,news_at,[f"Official FPL status: {status.value.lower()}."]
    if code=="d" or (chance is not None and chance<100):
        return AvailabilityStatus.DOUBTFUL,RiskLevel.HIGH if chance is not None and chance<=50 else RiskLevel.MEDIUM,chance,code,news,news_at,[f"Official FPL chance of playing: {chance}%." if chance is not None else "Official FPL status: doubtful."]
    if code=="a":return AvailabilityStatus.AVAILABLE,RiskLevel.LOW,chance,code,news,news_at,[]
    return AvailabilityStatus.UNKNOWN,RiskLevel.UNKNOWN,chance,code,news,news_at,["Official FPL status is unavailable."]

def _minutes(records:Sequence[RecentMinutesEvidence],prediction:datetime):
    rows=tuple(sorted(records,key=lambda x:(_utc(x.fixture_completed_at,"fixture"),_utc(x.known_at,"known")),reverse=True))
    for row in rows:
        if _utc(row.fixture_completed_at,"fixture")>=prediction or _utc(row.known_at,"known")>prediction:raise PlayerAvailabilityRiskError("future or target-fixture minutes cannot enter the snapshot.")
    last3,last5=rows[:3],rows[:5]; played=[x.minutes for x in last5]; starts=[x.minutes for x in last5 if x.started is True]
    features={"minutes_last_1":rows[0].minutes if rows else None,"minutes_last_3":sum(x.minutes for x in last3) if rows else None,"minutes_last_5":sum(played) if rows else None,"starts_last_3":sum(x.started is True for x in last3) if rows and all(x.started is not None for x in last3) else None,"starts_last_5":sum(x.started is True for x in last5) if rows and all(x.started is not None for x in last5) else None,"zero_minute_games_last_5":sum(x.minutes==0 for x in last5) if rows else None,"sub_appearances_last_5":sum(x.started is False and x.minutes>0 for x in last5) if rows else None,"average_minutes_when_started":sum(starts)/len(starts) if starts else None}
    if not rows:return features,RiskLevel.UNKNOWN,["Recent completed-fixture minutes are unavailable."]
    if len(last5)<3:return features,RiskLevel.MEDIUM,["Only a small completed-fixture minutes sample is available."]
    spread=max(played)-min(played); zeros=features["zero_minute_games_last_5"] or 0; subs=features["sub_appearances_last_5"] or 0; st=features["starts_last_5"] or 0
    if (zeros>=2 and spread>=60) or (spread>=55 and len(last5)>=4):return features,RiskLevel.HIGH,[f"Recent minutes vary from {min(played)} to {max(played)}."]
    if subs>=3 and (st or 0)<=2:return features,RiskLevel.MEDIUM,[f"Recent role is substitute-heavy ({subs} substitute appearances)."]
    if sum(0<x.minutes<60 for x in last5)>=2 and st>=2:return features,RiskLevel.MEDIUM,["Multiple recent early substitutions are present."]
    return features,RiskLevel.LOW,[]

def build_player_availability_risks(decision_input,*,player_metadata:Mapping[str,Mapping[str,Any]],player_ids:Sequence[str]|None=None,source_observed_at:datetime|str|None=None,source_provenance:Mapping[str,Any]|None=None,recent_minutes_by_player:Mapping[str,Sequence[RecentMinutesEvidence|Mapping[str,Any]]]|None=None,evaluated_at:datetime|str|None=None,advisory_cutoff:datetime|str|None=None)->dict[str,PlayerAvailabilityRisk]:
    planning_prediction=_utc(decision_input.planning_context.prediction_timestamp,"prediction timestamp")
    prediction=_utc(advisory_cutoff,"advisory cutoff") if advisory_cutoff is not None else planning_prediction
    evaluated=_utc(evaluated_at,"evaluated_at") if evaluated_at is not None else prediction
    if evaluated!=prediction:raise PlayerAvailabilityRiskError("availability evaluation must use its declared advisory cutoff.")
    observed=_utc(source_observed_at,"source observed_at") if source_observed_at is not None else None
    if observed and observed>prediction:raise PlayerAvailabilityRiskError("future official metadata cannot enter the snapshot.")
    age=None if observed is None else max(0.0,(evaluated-observed).total_seconds()/3600); freshness=FreshnessStatus.UNKNOWN if observed is None else FreshnessStatus.FRESH if age<=FRESH_AFTER_HOURS else FreshnessStatus.AGING if age<=STALE_AFTER_HOURS else FreshnessStatus.STALE
    output={}; selected=sorted({str(x) for x in (decision_input.player_by_id if player_ids is None else player_ids)})
    for pid in selected:
        meta=player_metadata.get(pid,{}) or {}; provider=meta.get("provider_payload") if isinstance(meta.get("provider_payload"),Mapping) else {}
        status,ar,chance,code,news,news_at,reasons=_availability(provider,observed)
        if news_at and news_at>prediction:raise PlayerAvailabilityRiskError("future official news cannot enter the snapshot.")
        records=tuple(x if isinstance(x,RecentMinutesEvidence) else RecentMinutesEvidence.from_dict(x) for x in (recent_minutes_by_player or {}).get(pid,()))
        features,mr,minutes_reasons=_minutes(records,prediction); projection=decision_input.projections.get(pid); projected=_number(getattr(projection,"expected_minutes_next_1",None))
        provenance=tuple(x for x,yes in (("OFFICIAL_FPL",observed is not None),("V22_MINUTES",projected is not None),("HISTORICAL_MINUTES",bool(records))) if yes)
        score=(2 if observed and status is not AvailabilityStatus.UNKNOWN else 0)+(2 if len(records)>=3 else 1 if records else 0)+(1 if projected is not None else 0)-(1 if freshness is FreshnessStatus.STALE else 0)
        confidence=ConfidenceLevel.HIGH if score>=4 else ConfidenceLevel.MEDIUM if score>=2 else ConfidenceLevel.LOW
        levels={RiskLevel.UNKNOWN:-1,RiskLevel.LOW:0,RiskLevel.MEDIUM:1,RiskLevel.HIGH:2}; overall=max((ar,mr),key=lambda x:levels[x])
        if news:reasons.append("Official FPL news is preserved without automatic text interpretation.")
        output[pid]=PlayerAvailabilityRisk(PLAYER_AVAILABILITY_SNAPSHOT_SCHEMA_V1,decision_input.context_id,pid,str(meta.get("display_name") or meta.get("name") or provider.get("web_name")) if (meta.get("display_name") or meta.get("name") or provider.get("web_name")) else None,evaluated.isoformat(),decision_input.state.current_gameweek,status,chance,code,news,_iso(news_at),projected,records,features["minutes_last_1"],features["minutes_last_3"],features["minutes_last_5"],features["starts_last_3"],features["starts_last_5"],features["zero_minute_games_last_5"],features["sub_appearances_last_5"],features["average_minutes_when_started"],ar,mr,overall,tuple(reasons+minutes_reasons),confidence,freshness,_iso(observed),_iso(observed),age,provenance)
    return output

def build_player_availability_snapshot(decision_input,**kwargs)->PlayerAvailabilitySnapshot:
    values=tuple(build_player_availability_risks(decision_input,**kwargs).values()); values=tuple(sorted(values,key=lambda x:x.player_id))
    counts={level.value:sum(x.overall_risk is level for x in values) for level in RiskLevel}; statuses={status.value:sum(x.availability_status is status for x in values) for status in AvailabilityStatus}; observed=next((x.observed_at for x in values if x.observed_at),None)
    provenance=kwargs.get("source_provenance") if isinstance(kwargs.get("source_provenance"),Mapping) else {}
    advisory_cutoff=kwargs.get("advisory_cutoff")
    generated=_utc(advisory_cutoff,"advisory cutoff").isoformat() if advisory_cutoff is not None else decision_input.planning_context.prediction_timestamp
    return PlayerAvailabilitySnapshot(PLAYER_AVAILABILITY_SNAPSHOT_SCHEMA_V1,decision_input.context_id,generated,decision_input.state.current_gameweek,PLAYER_AVAILABILITY_RISK_METHOD_V1,values,{"status":"AVAILABLE" if observed else "PARTIAL" if values else "UNAVAILABLE","players_evaluated":len(values),"overall_risk_counts":counts,"availability_status_counts":statuses,"official_availability_coverage":sum(x.observed_at is not None for x in values)/max(1,len(values)),"recent_minutes_coverage":sum(bool(x.recent_minutes) for x in values)/max(1,len(values))},{"projection_run_id":decision_input.bundle_identity,"prediction_timestamp":decision_input.planning_context.prediction_timestamp,"advisory_capture_cutoff":generated if advisory_cutoff is not None else None,"observed_at":observed,"source":provenance.get("source") or "OFFICIAL_FPL","source_snapshot_timestamp":provenance.get("source_snapshot_timestamp") or observed,"raw_snapshot_id":provenance.get("raw_snapshot_id"),"production_influence":False},tuple(sorted({"Recent completed-fixture minutes unavailable for one or more players." for x in values if not x.recent_minutes})),{"cache_hits":0})

def availability_snapshot_artifact_id(snapshot:PlayerAvailabilitySnapshot)->str:return "availability_snapshot_"+sha256(json.dumps(snapshot.to_dict(),sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()[:24]
def write_player_availability_snapshot(root:Path,snapshot:PlayerAvailabilitySnapshot)->Path:
    target=Path(root)/"data"/"processed"/"player_availability_snapshots"/str(snapshot.source.get("projection_run_id") or "unknown")/f"{availability_snapshot_artifact_id(snapshot)}.json"; target.parent.mkdir(parents=True,exist_ok=True); payload=json.dumps(snapshot.to_dict(),sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()+b"\n"
    if target.exists() and target.read_bytes()!=payload:raise PlayerAvailabilityRiskError("existing immutable availability snapshot conflicts.")
    target.write_bytes(payload);return target
def load_player_availability_snapshot(path:Path|Mapping[str,Any])->PlayerAvailabilitySnapshot:
    try:raw=path if isinstance(path,Mapping) else json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError,UnicodeError,json.JSONDecodeError) as exc:raise PlayerAvailabilityRiskError("availability snapshot artifact is unreadable.") from exc
    return PlayerAvailabilitySnapshot.from_dict(raw)
