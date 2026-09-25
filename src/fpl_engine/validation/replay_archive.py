"""Immutable pre-deadline archive for strict historical policy replay."""
from __future__ import annotations
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
import argparse
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from fpl_engine.planning import PlanningContext, context_from_report, verify_projection_artifacts
from fpl_engine.reports import AnalysisManifestV2, DecisionReportV2, parse_analysis_manifest, parse_decision_report
from fpl_engine.reports.common import canonical_json

REPLAY_ARCHIVE_SCHEMA_V1 = "replay_archive_case_v1"
REPLAY_OUTCOME_SCHEMA_V1 = "replay_outcome_v1"

class ReplayArchiveError(ValueError): pass
class ArchiveConflictError(ReplayArchiveError): pass
class ArchiveStatus(str, Enum):
    PRE_DEADLINE_COMPLETE="PRE_DEADLINE_COMPLETE"; PRE_DEADLINE_PARTIAL="PRE_DEADLINE_PARTIAL"; OUTCOME_COMPLETE="OUTCOME_COMPLETE"; REPLAY_READY="REPLAY_READY"; INVALID="INVALID"
class SnapshotStatus(str, Enum):
    AVAILABLE="AVAILABLE"; UNAVAILABLE="UNAVAILABLE"; STALE="STALE"

def _utc(value:datetime|str,label:str)->datetime:
    try: parsed=value if isinstance(value,datetime) else datetime.fromisoformat(str(value).replace("Z","+00:00"))
    except ValueError as exc: raise ReplayArchiveError(f"{label} must be an ISO-8601 timestamp.") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None: raise ReplayArchiveError(f"{label} must be timezone-aware.")
    return parsed.astimezone(timezone.utc)
def _sha(path:Path)->str: return sha256(Path(path).read_bytes()).hexdigest()
def _json(value:Any)->Any:
    if isinstance(value,PlanningContext):return _json(value.to_dict())
    if isinstance(value,Enum):return value.value
    if isinstance(value,datetime):return _utc(value,"timestamp").isoformat()
    if hasattr(value,"__dataclass_fields__"):return _json(asdict(value))
    if hasattr(value,"to_dict"):return _json(value.to_dict())
    if isinstance(value,Mapping):return {str(k):_json(v) for k,v in sorted(value.items(),key=lambda row:str(row[0]))}
    if isinstance(value,(tuple,list)):return [_json(v) for v in value]
    return value
def _safe(root:Path,relative:str)->Path:
    path=(Path(root).resolve()/relative).resolve()
    try:path.relative_to(Path(root).resolve())
    except ValueError as exc:raise ReplayArchiveError("Archive reference is outside the project root.") from exc
    return path
def _relative(root:Path,path:Path)->str:
    try:return str(Path(path).resolve().relative_to(Path(root).resolve()))
    except ValueError as exc:raise ReplayArchiveError("Archive reference must remain inside the project root.") from exc

@dataclass(frozen=True)
class ArchiveReference:
    path:str; sha256:str; schema_version:str|None=None
    def __post_init__(self)->None:
        if not self.path or len(self.sha256)!=64:raise ReplayArchiveError("Archive reference requires path and SHA-256.")
@dataclass(frozen=True)
class OptionalSnapshotReference:
    status:SnapshotStatus; path:str|None=None; sha256:str|None=None; observed_at:str|None=None; source:str|None=None; coverage:Mapping[str,Any]|None=None; production_influence:bool|None=None
    def __post_init__(self)->None:
        if self.status is SnapshotStatus.UNAVAILABLE:
            if any(value is not None for value in (self.path,self.sha256,self.observed_at,self.source)):raise ReplayArchiveError("Unavailable snapshot must not invent provenance.")
        else:
            if not self.path or not self.sha256 or not self.observed_at or not self.source:raise ReplayArchiveError("Available/stale snapshot requires exact reference and provenance.")
            if len(self.sha256)!=64:raise ReplayArchiveError("Snapshot SHA-256 is invalid.")
            _utc(self.observed_at,"snapshot observed_at")
@dataclass(frozen=True)
class ReplayArchiveCaseV1:
    schema_version:str; archive_case_id:str; season:str; planning_gameweek:int; official_deadline:str; deadline_source:str; archive_created_at:str; context_id:str; planning_context:PlanningContext; context_verification_status:str; projection_manifest:ArchiveReference; projection_bundle:ArchiveReference; decision_report:ArchiveReference; analysis_manifest:ArchiveReference; analysis_run_id:str; account_source:str|None; market_shadow:OptionalSnapshotReference; price_signals:OptionalSnapshotReference; policy_versions:Mapping[str,str]; source_artifact_hashes:tuple[tuple[str,str],...]; chip_opportunity_forecast:OptionalSnapshotReference=OptionalSnapshotReference(SnapshotStatus.UNAVAILABLE)
    def __post_init__(self)->None:
        if self.schema_version!=REPLAY_ARCHIVE_SCHEMA_V1 or not self.archive_case_id or not self.season or not 1<=self.planning_gameweek<=38:raise ReplayArchiveError("Replay archive identity is invalid.")
        if self.context_id!=self.planning_context.context_id or self.context_verification_status!="PASS":raise ReplayArchiveError("Archive PlanningContext verification failed.")
        if self.season!=self.planning_context.season or self.planning_gameweek!=self.planning_context.gameweek:raise ReplayArchiveError("Archive identity does not match PlanningContext.")
        deadline,prediction=_utc(self.official_deadline,"official deadline"),_utc(self.planning_context.prediction_timestamp,"prediction timestamp")
        if prediction>=deadline:raise ReplayArchiveError("Archive prediction timestamp must be strictly before the official deadline.")
        if tuple(sorted(self.source_artifact_hashes))!=tuple(sorted(self.planning_context.artifact_hashes)):raise ReplayArchiveError("Archive artifact hashes do not match PlanningContext.")
        if self.market_shadow.production_influence not in (None,False):raise ReplayArchiveError("Market Shadow archive must have production_influence=false.")
        for snapshot,label in ((self.market_shadow,"market shadow"),(self.price_signals,"price signal"),(self.chip_opportunity_forecast,"chip opportunity forecast")):
            if snapshot.status is not SnapshotStatus.UNAVAILABLE and _utc(snapshot.observed_at or "","snapshot observed_at")>prediction:raise ReplayArchiveError(f"Future {label} snapshot cannot enter the archive.")
        _utc(self.archive_created_at,"archive_created_at")
    def identity_payload(self)->dict[str,Any]:
        value=self.to_dict(); value.pop("archive_created_at",None); return value
    def to_dict(self)->dict[str,Any]:
        value=asdict(self)
        value["planning_context"]=self.planning_context.to_dict()
        return _json(value)
@dataclass(frozen=True)
class ReplayOutcomeV1:
    schema_version:str; outcome_id:str; archive_case_id:str; context_id:str; season:str; planning_gameweek:int; outcome_created_at:str; outcome_source:str; realised_outcomes:tuple[RealisedPlayerOutcome,...]; post_gameweek_prices:tuple[HistoricalPrice,...]=()
    def __post_init__(self)->None:
        if self.schema_version!=REPLAY_OUTCOME_SCHEMA_V1 or not self.outcome_id or not self.archive_case_id or not self.context_id or not self.outcome_source:raise ReplayArchiveError("Replay outcome identity is invalid.")
        if not self.realised_outcomes:raise ReplayArchiveError("Replay outcome requires realised records.")
        _utc(self.outcome_created_at,"outcome_created_at")
    def to_dict(self)->dict[str,Any]:return _json(self)
@dataclass(frozen=True)
class ArchiveValidation:
    archive_case_id:str; status:ArchiveStatus; checks:Mapping[str,bool]; reasons:tuple[str,...]
    def to_dict(self)->dict[str,Any]:return _json(self)

def _read_json(path:Path,label:str)->Mapping[str,Any]:
    try:value=json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError,UnicodeError,json.JSONDecodeError) as exc:raise ReplayArchiveError(f"{label} is unreadable.") from exc
    if not isinstance(value,Mapping):raise ReplayArchiveError(f"{label} is invalid.")
    return value
def _reference(root:Path,path:Path,schema:str|None=None)->ArchiveReference:return ArchiveReference(_relative(root,path),_sha(path),schema)
def _projection_paths(root:Path,context:PlanningContext)->tuple[Path,Path]:
    run=root/"data"/"processed"/"predictions"/context.season.replace("/","-")/context.projection_run_id
    return run/"shadow_projection_bundle.json",run/"run_manifest.json"
def _snapshot_from_manifest(root:Path,run_dir:Path,manifest:Mapping[str,Any],prediction:datetime)->OptionalSnapshotReference:
    artifacts=manifest.get("artifacts"); market=manifest.get("market_shadow")
    if not isinstance(artifacts,Mapping) or not isinstance(market,Mapping):return OptionalSnapshotReference(SnapshotStatus.UNAVAILABLE)
    meta=artifacts.get("market_shadow")
    if not isinstance(meta,Mapping) or not isinstance(meta.get("path"),str) or not isinstance(meta.get("sha256"),str):return OptionalSnapshotReference(SnapshotStatus.UNAVAILABLE)
    path=(run_dir/meta["path"]).resolve()
    if not path.is_file() or _sha(path)!=meta["sha256"]:return OptionalSnapshotReference(SnapshotStatus.UNAVAILABLE)
    raw=_read_json(path,"market shadow snapshot"); stamp=raw.get("shadow_prediction_timestamp",raw.get("market_snapshot_timestamp",raw.get("created_at")))
    source=raw.get("provider",raw.get("source")); influence=raw.get("production_influence")
    if not isinstance(stamp,str) or not isinstance(source,str) or influence is not False:return OptionalSnapshotReference(SnapshotStatus.UNAVAILABLE)
    if _utc(stamp,"market snapshot timestamp")>prediction:raise ReplayArchiveError("Future Market Shadow snapshot cannot be archived.")
    coverage=raw.get("coverage") if isinstance(raw.get("coverage"),Mapping) else {"status":market.get("status"),"selected_quote_count":market.get("selected_quote_count")}
    return OptionalSnapshotReference(SnapshotStatus.AVAILABLE,_relative(root,path),_sha(path),stamp,source,coverage,False)
def _chip_forecast_from_decision(root:Path,decision:DecisionReportV2,prediction:datetime)->OptionalSnapshotReference:
    reference=decision.chip_opportunity_forecast
    if reference is None:return OptionalSnapshotReference(SnapshotStatus.UNAVAILABLE)
    path=_safe(root,reference.path)
    if not path.is_file() or _sha(path)!=reference.sha256:return OptionalSnapshotReference(SnapshotStatus.UNAVAILABLE)
    try:
        from fpl_engine.planning import load_chip_opportunity_forecast
        forecast=load_chip_opportunity_forecast(path)
    except Exception as exc:raise ReplayArchiveError("Chip opportunity forecast artifact is invalid.") from exc
    if forecast.context_id!=decision.context_id or forecast.source.get("prediction_timestamp")!=prediction.isoformat():raise ReplayArchiveError("Chip opportunity forecast context/PIT mismatch.")
    return OptionalSnapshotReference(SnapshotStatus.AVAILABLE,reference.path,reference.sha256,prediction.isoformat(),forecast.schema_version,forecast.coverage,False)

def _price_signals_from_decision(root:Path,decision:DecisionReportV2,prediction:datetime)->OptionalSnapshotReference:
    # V3 currently serializes only availability, never a snapshot reference.  Do not infer one.
    raw=decision.v3_result.payload if decision.v3_result is not None else {}
    status=raw.get("price_signal_status") if isinstance(raw,Mapping) else None
    return OptionalSnapshotReference(SnapshotStatus.STALE if status=="STALE" else SnapshotStatus.UNAVAILABLE)
def _policy_versions(decision:DecisionReportV2)->dict[str,str]:
    return {"greedy":"persisted","optimizer_v1":"persisted_alternatives_only","optimizer_v2":"persisted","strategic_v3":"persisted" if decision.v3_result else "UNAVAILABLE"}
def _case_id(context:PlanningContext,analysis_hash:str,decision_hash:str)->str:
    return "archive_"+sha256(canonical_json({"context_id":context.context_id,"analysis_sha256":analysis_hash,"decision_sha256":decision_hash})).hexdigest()[:24]
def build_archive_case(root:Path,analysis_manifest_path:Path,archive_created_at:datetime|None=None)->ReplayArchiveCaseV1:
    root=Path(root).resolve(); analysis_path=Path(analysis_manifest_path).resolve(); raw=_read_json(analysis_path,"analysis manifest"); analysis=parse_analysis_manifest(raw)
    if analysis.legacy_unverified or analysis.planning_context is None or analysis.decision_report is None:raise ReplayArchiveError("Legacy or incomplete analysis cannot become a verified archive.")
    decision_path=_safe(root,analysis.decision_report.path)
    if not decision_path.is_file() or _sha(decision_path)!=analysis.decision_report.sha256:raise ReplayArchiveError("Decision report hash verification failed.")
    decision=parse_decision_report(_read_json(decision_path,"decision report")); context=analysis.planning_context
    if decision.legacy_unverified or decision.planning_context is None or decision.context_id!=analysis.context_id or decision.context_id!=context.context_id:raise ReplayArchiveError("Decision and analysis contexts do not match.")
    if decision.external_mutations:raise ReplayArchiveError("Archive rejects external mutations.")
    if context.deadline is None:raise ReplayArchiveError("Official deadline is unavailable; archive cannot prove strict PIT.")
    deadline,prediction=_utc(context.deadline,"official deadline"),_utc(context.prediction_timestamp,"prediction timestamp")
    if prediction>=deadline or _utc(decision.created_at,"decision created_at")>=deadline or _utc(analysis.created_at,"analysis created_at")>=deadline:raise ReplayArchiveError("Analysis was not fully created before the official deadline.")
    bundle_path,manifest_path=_projection_paths(root,context)
    manifest_raw=_read_json(manifest_path,"projection manifest")
    try:
        integrity=verify_projection_artifacts(bundle_path,manifest_raw,require_hashes=True)
    except ValueError as exc:
        raise ReplayArchiveError("Projection artifact integrity failed.") from exc
    if integrity is None or integrity.manifest_sha256!=context.manifest_sha256 or tuple(sorted(integrity.artifact_hashes))!=tuple(sorted(context.artifact_hashes)):raise ReplayArchiveError("Projection artifact hashes do not match PlanningContext.")
    market=_snapshot_from_manifest(root,manifest_path.parent,manifest_raw,prediction); price=_price_signals_from_decision(root,decision,prediction); forecast=_chip_forecast_from_decision(root,decision,prediction)
    created=(archive_created_at or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()
    analysis_ref=_reference(root,analysis_path,"analysis_manifest_v2"); decision_ref=_reference(root,decision_path,decision.schema_version); bundle_ref=_reference(root,bundle_path); manifest_ref=_reference(root,manifest_path)
    return ReplayArchiveCaseV1(REPLAY_ARCHIVE_SCHEMA_V1,_case_id(context,analysis_ref.sha256,decision_ref.sha256),context.season,context.gameweek,context.deadline,"PlanningContext.deadline",created,context.context_id,context,"PASS",manifest_ref,bundle_ref,decision_ref,analysis_ref,analysis.analysis_run_id,"PlanningContext.source_state_timestamp",market,price,_policy_versions(decision),context.artifact_hashes,forecast)
def archive_directory(root:Path,case:ReplayArchiveCaseV1)->Path:return Path(root).resolve()/"data"/"processed"/"historical_replay_cases"/case.season.replace("/","-")/f"GW{case.planning_gameweek:02d}"/case.archive_case_id
def write_archive_case(root:Path,case:ReplayArchiveCaseV1)->Path:
    directory=archive_directory(root,case); target=directory/"archive_case.json"; payload=canonical_json(case.to_dict())+b"\n"
    if target.exists():
        existing=parse_archive_case(target)
        if canonical_json(existing.identity_payload())!=canonical_json(case.identity_payload()):raise ArchiveConflictError("Existing archive case ID has conflicting immutable bytes.")
        return target
    directory.mkdir(parents=True,exist_ok=False); target.write_bytes(payload); return target
def archive_analysis(root:Path,analysis_manifest_path:Path)->Path:
    return write_archive_case(root,build_archive_case(root,analysis_manifest_path))
def parse_archive_case(path:Path|Mapping[str,Any])->ReplayArchiveCaseV1:
    raw=_read_json(path,"archive case") if isinstance(path,Path) else path
    if raw.get("schema_version")!=REPLAY_ARCHIVE_SCHEMA_V1:raise ReplayArchiveError("Unsupported replay archive schema version.")
    try:
        context_raw=raw["planning_context"]; context=context_from_report({"context_id":raw["context_id"],"planning_context":context_raw})
        if context is None:raise ReplayArchiveError("Archive PlanningContext is invalid.")
        def ref(key:str)->ArchiveReference:return ArchiveReference(**raw[key])
        def snapshot(key:str)->OptionalSnapshotReference:
            value=raw[key]; return OptionalSnapshotReference(SnapshotStatus(value["status"]),value.get("path"),value.get("sha256"),value.get("observed_at"),value.get("source"),value.get("coverage"),value.get("production_influence"))
        forecast=snapshot("chip_opportunity_forecast") if isinstance(raw.get("chip_opportunity_forecast"),Mapping) else OptionalSnapshotReference(SnapshotStatus.UNAVAILABLE)
        return ReplayArchiveCaseV1(raw["schema_version"],raw["archive_case_id"],raw["season"],int(raw["planning_gameweek"]),raw["official_deadline"],raw["deadline_source"],raw["archive_created_at"],raw["context_id"],context,raw["context_verification_status"],ref("projection_manifest"),ref("projection_bundle"),ref("decision_report"),ref("analysis_manifest"),raw["analysis_run_id"],raw.get("account_source"),snapshot("market_shadow"),snapshot("price_signals"),raw.get("policy_versions",{}),tuple((str(x[0]),str(x[1])) for x in raw["source_artifact_hashes"]),forecast)
    except (KeyError,TypeError,ValueError,IndexError) as exc:raise ReplayArchiveError("Archive case is invalid.") from exc

def validate_archive_case(root:Path,path:Path)->ArchiveValidation:
    checks:dict[str,bool]={}; reasons=[]
    try:case=parse_archive_case(path)
    except ReplayArchiveError as exc:return ArchiveValidation(Path(path).parent.name,ArchiveStatus.INVALID,{"schema":False},(str(exc),))
    root=Path(root).resolve()
    checks["schema"]=True; checks["context_fingerprint"]=case.context_id==case.planning_context.context_id
    for label,reference,parser in (("analysis",case.analysis_manifest,parse_analysis_manifest),("decision",case.decision_report,parse_decision_report)):
        try:
            target=_safe(root,reference.path); checks[f"{label}_hash"]=target.is_file() and _sha(target)==reference.sha256
            if not checks[f"{label}_hash"]:raise ReplayArchiveError(f"{label} reference hash mismatch.")
            parsed=parser(_read_json(target,label)); checks[f"{label}_schema"]=True
            if label=="analysis": analysis=parsed
            else: decision=parsed
        except (ReplayArchiveError,ValueError) as exc:checks[f"{label}_schema"]=False; reasons.append(str(exc))
    try:
        if not checks.get("analysis_hash") or not checks.get("decision_hash"):raise ReplayArchiveError("Required report references are invalid.")
        checks["report_context_compatibility"]=(analysis.context_id==case.context_id and decision.context_id==case.context_id and not decision.external_mutations)
        if not checks["report_context_compatibility"]:raise ReplayArchiveError("Archive reports do not share a read-only PlanningContext.")
        checks["deadline_pit"]=_utc(case.planning_context.prediction_timestamp,"prediction")<_utc(case.official_deadline,"deadline") and _utc(decision.created_at,"decision")<_utc(case.official_deadline,"deadline") and _utc(analysis.created_at,"analysis")<_utc(case.official_deadline,"deadline")
        if not checks["deadline_pit"]:raise ReplayArchiveError("Archive decision inputs are not strictly pre-deadline.")
        bundle=_safe(root,case.projection_bundle.path); manifest=_safe(root,case.projection_manifest.path); raw=_read_json(manifest,"projection manifest")
        try:
            integrity=verify_projection_artifacts(bundle,raw,require_hashes=True)
        except ValueError:
            integrity=None
        checks["projection_artifacts"]=bool(integrity and integrity.manifest_sha256==case.planning_context.manifest_sha256 and tuple(sorted(integrity.artifact_hashes))==tuple(sorted(case.source_artifact_hashes)) and _sha(bundle)==case.projection_bundle.sha256 and _sha(manifest)==case.projection_manifest.sha256)
        if not checks["projection_artifacts"]:raise ReplayArchiveError("Projection artifact integrity failed.")
        for label,snapshot in (("market_shadow",case.market_shadow),("price_signals",case.price_signals),("chip_opportunity_forecast",case.chip_opportunity_forecast)):
            if snapshot.status is SnapshotStatus.UNAVAILABLE: checks[label]=True; continue
            target=_safe(root,snapshot.path or ""); checks[label]=target.is_file() and _sha(target)==snapshot.sha256 and _utc(snapshot.observed_at or "",label)<=_utc(case.planning_context.prediction_timestamp,"prediction")
            if label=="market_shadow":checks[label]=checks[label] and snapshot.production_influence is False
            if label=="chip_opportunity_forecast" and checks[label]:
                from fpl_engine.planning import load_chip_opportunity_forecast
                forecast=load_chip_opportunity_forecast(target)
                checks[label]=forecast.context_id==case.context_id and forecast.source.get("prediction_timestamp")==case.planning_context.prediction_timestamp
            if not checks[label]:raise ReplayArchiveError(f"{label} snapshot integrity or PIT failed.")
    except ReplayArchiveError as exc:reasons.append(str(exc))
    status=ArchiveStatus.PRE_DEADLINE_COMPLETE if checks and all(checks.values()) else ArchiveStatus.INVALID
    return ArchiveValidation(case.archive_case_id,status,checks,tuple(reasons))
def _outcome_id(case:ReplayArchiveCaseV1,raw:Mapping[str,Any])->str:return "outcome_"+sha256(canonical_json({"archive_case_id":case.archive_case_id,"context_id":case.context_id,"source":raw.get("outcome_source"),"outcomes":raw.get("realised_outcomes")})).hexdigest()[:24]
def attach_outcome(root:Path,archive_path:Path,source_path:Path)->Path:
    case=parse_archive_case(archive_path); raw=_read_json(source_path,"outcome source")
    if raw.get("archive_case_id") not in (None,case.archive_case_id) or raw.get("context_id") not in (None,case.context_id) or raw.get("season") not in (None,case.season) or raw.get("planning_gameweek") not in (None,case.planning_gameweek):raise ReplayArchiveError("Outcome source does not match archive identity.")
    import importlib
    replay = importlib.import_module("fpl_engine.validation.policy_replay")
    HistoricalPrice, RealisedPlayerOutcome = replay.HistoricalPrice, replay.RealisedPlayerOutcome
    outcomes=tuple(RealisedPlayerOutcome(**row) for row in raw.get("realised_outcomes",()) if isinstance(row,Mapping)); prices=tuple(HistoricalPrice(**row) for row in raw.get("post_gameweek_prices",()) if isinstance(row,Mapping))
    outcome=ReplayOutcomeV1(REPLAY_OUTCOME_SCHEMA_V1,_outcome_id(case,raw),case.archive_case_id,case.context_id,case.season,case.planning_gameweek,datetime.now(timezone.utc).isoformat(),str(raw.get("outcome_source","local")),outcomes,prices)
    target=Path(archive_path).parent/"outcomes"/f"{outcome.outcome_id}.json"; payload=canonical_json(outcome.to_dict())+b"\n"; target.parent.mkdir(parents=True,exist_ok=True)
    if target.exists():
        if target.read_bytes()!=payload:raise ArchiveConflictError("Existing replay outcome has conflicting bytes.")
        return target
    target.write_bytes(payload); return target
def archive_status(root:Path,path:Path)->ArchiveValidation:
    validation=validate_archive_case(root,path)
    if validation.status is ArchiveStatus.INVALID:return validation
    outcomes=list(Path(path).parent.glob("outcomes/*.json"));
    if not outcomes:return validation
    try:
        raw=_read_json(outcomes[-1],"replay outcome")
        matches=raw.get("schema_version")==REPLAY_OUTCOME_SCHEMA_V1 and raw.get("archive_case_id")==validation.archive_case_id
        if not matches:raise ReplayArchiveError("Outcome companion does not match archive.")
        # Sequential replay additionally requires actual historical price evidence.
        has_prices=bool(raw.get("post_gameweek_prices")); return ArchiveValidation(validation.archive_case_id,ArchiveStatus.REPLAY_READY if has_prices else ArchiveStatus.OUTCOME_COMPLETE,validation.checks,validation.reasons)
    except ReplayArchiveError as exc:return ArchiveValidation(validation.archive_case_id,ArchiveStatus.INVALID,validation.checks,(str(exc),))
def discover_archives(root:Path,season:str|None=None,gameweek:int|None=None)->tuple[Path,...]:
    base=Path(root).resolve()/"data"/"processed"/"historical_replay_cases"
    if not base.exists():return ()
    rows=[]
    for path in base.glob("*/*/*/archive_case.json"):
        try:
            case=parse_archive_case(path)
            if (season is None or case.season.replace("/","-")==season.replace("/","-")) and (gameweek is None or case.planning_gameweek==gameweek):rows.append(path)
        except ReplayArchiveError:continue
    return tuple(sorted(rows))
def select_operational_archive(root:Path,season:str,gameweek:int,official_deadline:datetime|str)->Path|None:
    deadline=_utc(official_deadline,"official deadline"); candidates=[]
    for path in discover_archives(root,season,gameweek):
        validation=validate_archive_case(root,path)
        if validation.status is not ArchiveStatus.PRE_DEADLINE_COMPLETE:continue
        case=parse_archive_case(path)
        # Archive creation may happen after a deadline when preserving an already
        # persisted historical run.  Eligibility rests on verified frozen inputs.
        if _utc(case.planning_context.prediction_timestamp,"prediction")>=deadline:continue
        candidates.append((_utc(case.planning_context.prediction_timestamp,"prediction"),path))
    return max(candidates,key=lambda row:(row[0],str(row[1])))[1] if candidates else None
def _main(argv:Sequence[str]|None=None)->int:
    parser=argparse.ArgumentParser(description="Developer-only strict replay archive") ; subs=parser.add_subparsers(dest="command",required=True)
    for name in ("list","validate","status"):
        sub=subs.add_parser(name); sub.add_argument("--root",type=Path,default=Path.cwd()); sub.add_argument("--season"); sub.add_argument("--gw",type=int)
    create=subs.add_parser("create"); create.add_argument("--root",type=Path,default=Path.cwd()); create.add_argument("--analysis",type=Path,required=True)
    outcome=subs.add_parser("outcomes"); outcome.add_argument("--root",type=Path,default=Path.cwd()); outcome.add_argument("--archive",type=Path,required=True); outcome.add_argument("--source",type=Path,required=True)
    args=parser.parse_args(argv)
    if args.command=="create":print(archive_analysis(args.root,args.analysis));return 0
    if args.command=="outcomes":print(attach_outcome(args.root,args.archive,args.source));return 0
    rows=discover_archives(args.root,args.season,args.gw)
    output=[]
    for path in rows:
        item=archive_status(args.root,path) if args.command=="status" else validate_archive_case(args.root,path) if args.command=="validate" else {"archive_case":str(path)}
        output.append(_json(item))
    print(json.dumps(output,sort_keys=True)); return 0
if __name__=="__main__":raise SystemExit(_main())
