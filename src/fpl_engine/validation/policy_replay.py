"""Strict, developer-only replay of frozen historical FPL planning decisions."""
from __future__ import annotations
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
import argparse, json
from hashlib import sha256
from pathlib import Path
from statistics import median
from time import perf_counter
from typing import Any, Iterable, Mapping, Protocol, Sequence
import numpy as np
from fpl_engine.planning import PlanningContext
from fpl_engine.reports import AnalysisManifestV2, DecisionReportV2, ReportStatus, parse_decision_report
from fpl_engine.reports.common import canonical_json, normalize_json, plan_id
from fpl_engine.validation.leakage import FutureInformationError, assert_information_known

HISTORICAL_REPLAY_SCHEMA_V1 = "historical_replay_report_v1"
HISTORICAL_REPLAY_SUMMARY_SCHEMA_V1 = "historical_replay_summary_v1"
MIN_BOOTSTRAP_SAMPLE = 5

class HistoricalReplayError(ValueError): pass
class ReplayLeakageError(HistoricalReplayError): pass
class ReplayUnavailableError(HistoricalReplayError): pass
class ReplayMode(str, Enum):
    SINGLE_DECISION_COUNTERFACTUAL = "SINGLE_DECISION_COUNTERFACTUAL"
    SEQUENTIAL_POLICY_REPLAY = "SEQUENTIAL_POLICY_REPLAY"
class ReplayPolicy(str, Enum):
    HOLD = "HOLD"
    GREEDY_1GW = "GREEDY_1GW"
    OPTIMIZER_V1 = "OPTIMIZER_V1"
    OPTIMIZER_V2 = "OPTIMIZER_V2"
    STRATEGIC_V3 = "STRATEGIC_V3"
class ReplayAvailability(str, Enum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    PRICE_INCOMPLETE = "PRICE_INCOMPLETE"

def _utc(value: datetime | str, label: str) -> datetime:
    try: parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc: raise HistoricalReplayError(f"{label} must be an ISO-8601 timestamp.") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None: raise HistoricalReplayError(f"{label} must be timezone-aware.")
    return parsed.astimezone(timezone.utc)
def _ids(value: object, label: str, exact: int | None = None) -> tuple[str, ...]:
    if not isinstance(value, (tuple, list)): raise HistoricalReplayError(f"{label} must be a player-ID list.")
    result = tuple(str(row) for row in value)
    if not all(result) or len(result) != len(set(result)) or (exact is not None and len(result) != exact): raise HistoricalReplayError(f"{label} must contain unique player IDs.")
    return result
def _finite(value: object, label: str, optional: bool = False) -> float | None:
    if value is None and optional: return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not np.isfinite(value): raise HistoricalReplayError(f"{label} must be finite.")
    return float(value)
def _int(value: object, label: str) -> int | None:
    if value is None: return None
    if type(value) is not int: raise HistoricalReplayError(f"{label} must be an integer.")
    return value
def _json(value: Any) -> Any:
    if isinstance(value, Enum): return value.value
    if isinstance(value, datetime): return _utc(value, "timestamp").isoformat()
    if hasattr(value, "__dataclass_fields__"): return _json(asdict(value))
    if hasattr(value, "to_dict"): return _json(value.to_dict())
    if isinstance(value, Mapping): return {str(k): _json(v) for k,v in sorted(value.items(), key=lambda row: str(row[0]))}
    if isinstance(value, (tuple,list)): return [_json(v) for v in value]
    return value

@dataclass(frozen=True)
class HistoricalPrice:
    player_id: str; current_price_tenths: int; selling_price_tenths: int | None; known_at: str; source_id: str
    def __post_init__(self) -> None:
        if not self.player_id or self.current_price_tenths <= 0 or not self.source_id: raise HistoricalReplayError("Historical price requires ID, source and positive current price.")
        if self.selling_price_tenths is not None and self.selling_price_tenths <= 0: raise HistoricalReplayError("Historical selling price must be positive.")
        _utc(self.known_at, "historical price known_at")
@dataclass(frozen=True)
class RealisedPlayerOutcome:
    player_id: str; gameweek: int; fixture_id: str; points: float; minutes: float | None; outcome_known_at: str; source_id: str; position: str | None = None; fixture_type: str | None = None
    def __post_init__(self) -> None:
        if not self.player_id or not self.fixture_id or not self.source_id or not 1 <= self.gameweek <= 38: raise HistoricalReplayError("Realised outcome identity is invalid.")
        _finite(self.points, "realised points"); _finite(self.minutes, "realised minutes", True); _utc(self.outcome_known_at, "outcome_known_at")
@dataclass(frozen=True)
class FrozenLineup:
    starting_xi: tuple[str, ...]; bench_order: tuple[str, ...]; captain: str; vice_captain: str
    def __post_init__(self) -> None:
        starters, bench = _ids(self.starting_xi, "starting_xi", 11), _ids(self.bench_order, "bench_order", 4)
        if set(starters) & set(bench) or self.captain not in starters or self.vice_captain not in starters or self.captain == self.vice_captain: raise HistoricalReplayError("Frozen lineup captain/vice or players are invalid.")
@dataclass(frozen=True)
class FrozenPolicyAction:
    policy: ReplayPolicy; policy_version: str; transfers_out: tuple[str, ...] = (); transfers_in: tuple[str, ...] = (); hit_cost: int = 0; resulting_bank_tenths: int | None = None; free_transfers_before: int | None = None; free_transfers_after: int | None = None; projected_impact_1gw: float | None = None; projected_impact_3gw: float | None = None; projected_impact_6gw: float | None = None; lineup: FrozenLineup | None = None; config_snapshot: Mapping[str, Any] = field(default_factory=dict); warnings: tuple[str, ...] = (); runtime_ms: float | None = None
    def __post_init__(self) -> None:
        out, inc = _ids(self.transfers_out,"transfers_out"), _ids(self.transfers_in,"transfers_in")
        if len(out) != len(inc) or set(out)&set(inc) or type(self.hit_cost) is not int or self.hit_cost < 0: raise HistoricalReplayError("Frozen policy action transfer or hit data is invalid.")
        for field_name in ("free_transfers_before","free_transfers_after"):
            value=_int(getattr(self,field_name),field_name)
            if value is not None and not 0 <= value <= 5: raise HistoricalReplayError(f"{field_name} must be 0..5.")
        _int(self.resulting_bank_tenths,"resulting_bank_tenths")
        for field_name in ("projected_impact_1gw","projected_impact_3gw","projected_impact_6gw","runtime_ms"): _finite(getattr(self,field_name),field_name,True)
        if not self.policy_version: raise HistoricalReplayError("Frozen policy action requires policy_version.")
        normalize_json(dict(self.config_snapshot),label="frozen policy configuration")
    @property
    def action_id(self) -> str: return plan_id(self.transfers_out,self.transfers_in)
    @property
    def is_hold(self) -> bool: return not self.transfers_in
    def impact(self,horizon:int)->float|None: return {1:self.projected_impact_1gw,3:self.projected_impact_3gw,6:self.projected_impact_6gw}.get(horizon)

@dataclass(frozen=True)
class HistoricalReplayCase:
    replay_case_id: str; season: str; decision_gameweek: int; official_deadline: str; decision_report: DecisionReportV2; realised_outcomes: tuple[RealisedPlayerOutcome,...]; price_snapshots: tuple[HistoricalPrice,...] = (); outcome_source_id: str = ""; market_quote_timestamps: tuple[str,...] = (); planning_rules: Mapping[str,Any] = field(default_factory=dict); source_artifact_hashes: tuple[tuple[str,str],...] = (); fixture_type: str | None = None
    def __post_init__(self) -> None:
        if not self.replay_case_id or not self.season or not 1 <= self.decision_gameweek <= 38: raise HistoricalReplayError("Historical replay case identity is invalid.")
        if self.decision_report.legacy_unverified or self.decision_report.planning_context is None: raise HistoricalReplayError("Strict replay requires a verified DecisionReportV2 PlanningContext.")
        context=self.decision_report.planning_context
        if context.season != self.season or context.gameweek != self.decision_gameweek: raise HistoricalReplayError("Replay case identity does not match frozen PlanningContext.")
        if self.decision_report.external_mutations: raise HistoricalReplayError("Strict replay rejects reports with external mutations.")
        deadline,prediction=_utc(self.official_deadline,"official_deadline"),_utc(context.prediction_timestamp,"prediction_timestamp")
        if prediction >= deadline: raise ReplayLeakageError("Frozen prediction_timestamp must be strictly before the official deadline.")
        if _utc(self.decision_report.created_at,"decision created_at") >= deadline: raise ReplayLeakageError("Frozen decision report was created at or after the official deadline.")
        for price in self.price_snapshots:
            try: assert_information_known(known_at=_utc(price.known_at,"price known_at"),prediction_timestamp=prediction,entity=f"historical price {price.player_id}",source=price.source_id)
            except FutureInformationError as exc: raise ReplayLeakageError(str(exc)) from exc
        for quote in self.market_quote_timestamps:
            if _utc(quote,"market quote timestamp") > prediction: raise ReplayLeakageError("Later market quote cannot enter a historical decision.")
        for outcome in self.realised_outcomes:
            if _utc(outcome.outcome_known_at,"outcome_known_at") <= prediction: raise ReplayLeakageError("Realised outcome cannot be available to frozen policy execution.")
        if self.source_artifact_hashes and tuple(sorted(self.source_artifact_hashes)) != tuple(sorted(context.artifact_hashes)): raise ReplayLeakageError("Replay case artifact hashes do not match frozen PlanningContext.")
        normalize_json(dict(self.planning_rules),label="planning rules")
    @property
    def context(self)->PlanningContext:
        assert self.decision_report.planning_context is not None
        return self.decision_report.planning_context
    @property
    def context_id(self)->str: return self.context.context_id
    @property
    def prediction_timestamp(self)->str: return self.context.prediction_timestamp
    def to_dict(self,include_report:bool=True)->dict[str,Any]:
        result={"replay_case_id":self.replay_case_id,"season":self.season,"decision_gameweek":self.decision_gameweek,"official_deadline":self.official_deadline,"context_id":self.context_id,"prediction_timestamp":self.prediction_timestamp,"projection_run_id":self.context.projection_run_id,"artifact_hashes":[list(x) for x in self.context.artifact_hashes],"realised_outcomes":_json(self.realised_outcomes),"price_snapshots":_json(self.price_snapshots),"outcome_source_id":self.outcome_source_id,"market_quote_timestamps":list(self.market_quote_timestamps),"planning_rules":_json(self.planning_rules),"fixture_type":self.fixture_type}
        if include_report: result["decision_report"]=self.decision_report.to_dict()
        return result
@dataclass(frozen=True)
class PolicyReplayResult:
    policy: ReplayPolicy; availability: ReplayAvailability; unavailable_reason: str|None; action: FrozenPolicyAction|None; resulting_squad: tuple[str,...]; realised_squad_points: Mapping[int,float|None]; realised_gain_vs_hold: Mapping[int,float|None]; hit_adjusted_gain_vs_hold: Mapping[int,float|None]; captaincy: Mapping[str,float|str|None]; v3_diagnostics: Mapping[str,Any]; warnings: tuple[str,...]=(); runtime_ms:float=0.0; sign_accuracy: bool|None=None; transfer_regret: Mapping[int,float|None]=field(default_factory=dict); hold_regret: Mapping[int,float|None]=field(default_factory=dict); transfer_churn: bool=False
    def to_dict(self)->dict[str,Any]: return _json(self)
@dataclass(frozen=True)
class OperationalHistoricalRun:
    analysis_path:str; decision_path:str; analysis_run_id:str; created_at:str; official_deadline:str; context_id:str; prediction_timestamp:str; selection_reason:str
    def to_dict(self)->dict[str,Any]: return _json(self)
@dataclass(frozen=True)
class HistoricalReplayReportV1:
    schema_version:str; replay_mode:ReplayMode; replay_case:HistoricalReplayCase; selected_operational_run:OperationalHistoricalRun|None; policy_results:tuple[PolicyReplayResult,...]; leakage_checks:Mapping[str,bool]; unavailable_data_reasons:tuple[str,...]; warnings:tuple[str,...]; runtime_ms:float
    def __post_init__(self)->None:
        if self.schema_version != HISTORICAL_REPLAY_SCHEMA_V1: raise HistoricalReplayError("Unsupported historical replay report schema.")
        if not all(self.leakage_checks.values()): raise ReplayLeakageError("Replay report cannot persist failed leakage checks.")
    def to_dict(self)->dict[str,Any]: return _json(self)
    def canonical_bytes(self)->bytes: return canonical_json(self.to_dict())
@dataclass(frozen=True)
class PolicyAggregate:
    policy:ReplayPolicy; sample_size:int; mean_realised_gain:float|None; median_realised_gain:float|None; ci_low:float|None; ci_high:float|None; win_rate_vs_hold:float|None; win_rate_vs_greedy:float|None; label:str
@dataclass(frozen=True)
class HistoricalReplaySummaryV1:
    schema_version:str; replay_mode:ReplayMode; included_case_ids:tuple[str,...]; excluded_cases:Mapping[str,str]; policy_metrics:tuple[PolicyAggregate,...]; segment_metrics:Mapping[str,Mapping[str,Any]]
    def to_dict(self)->dict[str,Any]: return _json(self)

def _lineup(report:DecisionReportV2,*keys:str)->FrozenLineup|None:
    for key in keys:
        preview=report.preview_for(key)
        if preview is not None: return FrozenLineup(preview.starting_xi,preview.bench_order,preview.captain,preview.vice_captain)
    return None
def _number(raw:Mapping[str,Any],*names:str)->float|None:
    for name in names:
        value=raw.get(name)
        if isinstance(value,(int,float)) and not isinstance(value,bool) and np.isfinite(value): return float(value)
    impacts=raw.get("transfer_impacts")
    if isinstance(impacts,Mapping): return _number(impacts,*names)
    return None
def _action(policy:ReplayPolicy,raw:Mapping[str,Any],version:str,lineup:FrozenLineup|None,source:str)->FrozenPolicyAction:
    out=tuple(str(x) for x in raw.get("transfers_out",()) if str(x)); inc=tuple(str(x) for x in raw.get("transfers_in",()) if str(x))
    if bool(raw.get("roll_free_transfer")) or str(raw.get("action","")).upper() in {"ROLL_FT","HOLD"}: out,inc=(),()
    hit=raw.get("hit_cost",raw.get("hit_cost_points",0)); hit=hit if type(hit) is int else 0
    return FrozenPolicyAction(policy,version,out,inc,hit,_int(raw.get("resulting_bank"),"resulting_bank"),_int(raw.get("free_transfers_before"),"free_transfers_before"),_int(raw.get("free_transfers_after"),"free_transfers_after"),_number(raw,"impact_1gw"),_number(raw,"impact_3gw"),_number(raw,"impact_6gw"),lineup,{"source":source})
def frozen_policy_action(case:HistoricalReplayCase,policy:ReplayPolicy)->FrozenPolicyAction|None:
    report,context=case.decision_report,case.context
    if policy is ReplayPolicy.HOLD: return FrozenPolicyAction(policy,"hold_baseline_v1",resulting_bank_tenths=context.bank_tenths,free_transfers_before=context.free_transfers,free_transfers_after=min(5,context.free_transfers+1),lineup=_lineup(report,"short_term","balanced","long_term","strategic"),config_snapshot={"action":"HOLD","max_free_transfers":5})
    if policy is ReplayPolicy.GREEDY_1GW: return _action(policy,report.greedy_result,"greedy_1gw_frozen",_lineup(report,"short_term"),"policy_results.greedy")
    if policy is ReplayPolicy.OPTIMIZER_V1:
        raw=report.v1_result.get("recommendation") if isinstance(report.v1_result,Mapping) else None
        return _action(policy,raw,"optimizer_v1_frozen",_lineup(report,"balanced"),"policy_results.optimizer_v1.recommendation") if isinstance(raw,Mapping) else None
    if policy is ReplayPolicy.OPTIMIZER_V2: return _action(policy,report.v2_result,"optimizer_v2_frozen",_lineup(report,"strategic"),"policy_results.optimizer_v2") if isinstance(report.v2_result,Mapping) else None
    if policy is ReplayPolicy.STRATEGIC_V3: return _action(policy,report.v3_result.current_action,"strategic_v3_frozen",_lineup(report,"strategic"),"policy_results.strategic_v3") if report.v3_result and isinstance(report.v3_result.current_action,Mapping) else None
    raise HistoricalReplayError(f"Unknown replay policy {policy}")

def _resulting_squad(case:HistoricalReplayCase,action:FrozenPolicyAction)->tuple[str,...]:
    current=set(case.context.player_ids)
    if not set(action.transfers_out) <= current or set(action.transfers_in)&current: raise ReplayUnavailableError("Frozen action cannot be applied to the frozen squad.")
    result=tuple(sorted((current-set(action.transfers_out))|set(action.transfers_in)))
    if len(result)!=15: raise ReplayUnavailableError("Frozen action does not produce a 15-player squad.")
    return result
def _outcome_total(outcomes:Iterable[RealisedPlayerOutcome],squad:Sequence[str],start:int,horizon:int)->float|None:
    wanted=set(squad); values:dict[tuple[str,int],float]={}
    for row in outcomes:
        if row.player_id in wanted and start <= row.gameweek < start+horizon: values[(row.player_id,row.gameweek)]=values.get((row.player_id,row.gameweek),0.0)+row.points
    if any((player,gw) not in values for player in wanted for gw in range(start,start+horizon)): return None
    return float(sum(values.values()))
def _captaincy(action:FrozenPolicyAction,outcomes:Iterable[RealisedPlayerOutcome],gw:int,squad:Sequence[str])->dict[str,float|str|None]:
    if action.lineup is None: return {"captain":None,"vice_captain":None,"realised_captain_points":None,"best_owned_points":None,"captain_regret":None}
    values:dict[str,float]={}
    for row in outcomes:
        if row.gameweek==gw and row.player_id in squad: values[row.player_id]=values.get(row.player_id,0.0)+row.points
    actual=values.get(action.lineup.captain); best=max(values.values()) if values else None
    return {"captain":action.lineup.captain,"vice_captain":action.lineup.vice_captain,"realised_captain_points":actual,"best_owned_points":best,"captain_regret":None if actual is None or best is None else best-actual}
def _v3(case:HistoricalReplayCase,action:FrozenPolicyAction|None)->dict[str,Any]:
    if action is None or action.policy is not ReplayPolicy.STRATEGIC_V3 or case.decision_report.v3_result is None: return {}
    payload=case.decision_report.v3_result.payload
    return {"predicted_best_path_value":_number(payload,"best_path_value","path_value","total_value"),"predicted_forced_hold_value":_number(payload,"forced_hold_value","hold_value"),"predicted_delta_vs_hold":_number(payload,"delta_vs_hold","delta_vs_forced_hold"),"current_action":"HOLD" if action.is_hold else "TRANSFER","path_length":len(case.decision_report.v3_result.path),"path_stability":"UNAVAILABLE_FROZEN_NEXT_SYNC_REQUIRED","beam_regret":"UNAVAILABLE_EXHAUSTIVE_COMPARISON_REQUIRED"}
def replay_single_decision(case:HistoricalReplayCase,policies:Iterable[ReplayPolicy]=tuple(ReplayPolicy))->HistoricalReplayReportV1:
    started=perf_counter(); selected=tuple(dict.fromkeys(ReplayPolicy(row) for row in policies)); hold=frozen_policy_action(case,ReplayPolicy.HOLD); assert hold
    hold_squad=_resulting_squad(case,hold); hold_scores={h:_outcome_total(case.realised_outcomes,hold_squad,case.decision_gameweek,h) for h in (1,3,6)}; results=[]; unavailable=[]
    for policy in selected:
        then=perf_counter(); action=frozen_policy_action(case,policy)
        if action is None:
            reason="No separately identified frozen policy action is persisted for this policy."
            results.append(PolicyReplayResult(policy,ReplayAvailability.UNAVAILABLE,reason,None,(),{1:None,3:None,6:None},{1:None,3:None,6:None},{1:None,3:None,6:None},{},{},(reason,),(perf_counter()-then)*1000)); unavailable.append(f"{policy.value}: {reason}"); continue
        try: squad=_resulting_squad(case,action)
        except ReplayUnavailableError as exc:
            reason=str(exc); results.append(PolicyReplayResult(policy,ReplayAvailability.UNAVAILABLE,reason,action,(),{1:None,3:None,6:None},{1:None,3:None,6:None},{1:None,3:None,6:None},{},_v3(case,action),(reason,),(perf_counter()-then)*1000)); unavailable.append(f"{policy.value}: {reason}"); continue
        scores={h:_outcome_total(case.realised_outcomes,squad,case.decision_gameweek,h) for h in (1,3,6)}
        gains={h:None if scores[h] is None or hold_scores[h] is None else scores[h]-hold_scores[h] for h in (1,3,6)}; hit={h:None if gains[h] is None else gains[h]-action.hit_cost for h in (1,3,6)}
        warnings=tuple(f"missing realised outcomes for {h}GW" for h in (1,3,6) if scores[h] is None)
        results.append(PolicyReplayResult(policy,ReplayAvailability.AVAILABLE,None,action,squad,scores,gains,hit,_captaincy(action,case.realised_outcomes,case.decision_gameweek,squad),_v3(case,action),warnings,(perf_counter()-then)*1000))
    # Realised FPL points are the only common external metric.  V2 utility and V3 path
    # values remain diagnostics and are never ranked against transfer impacts.
    best={h:max((row.hit_adjusted_gain_vs_hold.get(h) for row in results if row.hit_adjusted_gain_vs_hold.get(h) is not None),default=None) for h in (1,3,6)}
    hold_regret={h:best[h] for h in (1,3,6)}
    enriched=[]
    for row in results:
        actual=row.hit_adjusted_gain_vs_hold.get(1); predicted=row.action.impact(1) if row.action else None
        sign=None if actual is None or predicted is None else ((predicted > 0) == (actual > 0))
        regret={h:None if best[h] is None or row.hit_adjusted_gain_vs_hold.get(h) is None else best[h]-row.hit_adjusted_gain_vs_hold[h] for h in (1,3,6)}
        enriched.append(replace(row,sign_accuracy=sign,transfer_regret=regret,hold_regret=hold_regret if row.policy is ReplayPolicy.HOLD else {},transfer_churn=bool(row.action and row.action.transfers_in)))
    results=enriched
    checks={"prediction_strictly_before_deadline":_utc(case.prediction_timestamp,"prediction_timestamp")<_utc(case.official_deadline,"official_deadline"),"decision_created_before_deadline":_utc(case.decision_report.created_at,"decision created_at")<_utc(case.official_deadline,"official_deadline"),"future_prices_rejected":True,"realised_outcomes_not_policy_inputs":True,"later_market_quotes_rejected":True,"context_and_artifacts_match":True}
    return HistoricalReplayReportV1(HISTORICAL_REPLAY_SCHEMA_V1,ReplayMode.SINGLE_DECISION_COUNTERFACTUAL,case,None,tuple(results),checks,tuple(unavailable),(),(perf_counter()-started)*1000)

@dataclass(frozen=True)
class SequentialAccountState:
    player_ids:tuple[str,...]; purchase_prices_tenths:tuple[tuple[str,int],...]; selling_prices_tenths:tuple[tuple[str,int],...]; bank_tenths:int; free_transfers:int; chips_used:tuple[tuple[str,bool],...]
    def __post_init__(self)->None:
        _ids(self.player_ids,"sequential player_ids",15)
        if self.bank_tenths<0 or not 0<=self.free_transfers<=5: raise HistoricalReplayError("Sequential account bank or free transfers is invalid.")
    @classmethod
    def from_context(cls,context:PlanningContext)->"SequentialAccountState": return cls(context.player_ids,tuple(context.selling_prices_tenths),tuple(context.selling_prices_tenths),context.bank_tenths,context.free_transfers,context.chips_used)
class SequentialPolicyExecutor(Protocol):
    def __call__(self,case:HistoricalReplayCase,state:SequentialAccountState,policy:ReplayPolicy)->FrozenPolicyAction: ...
def apply_sequential_action(state:SequentialAccountState,action:FrozenPolicyAction,prices:Iterable[HistoricalPrice],prediction_timestamp:datetime|str)->SequentialAccountState:
    prediction=_utc(prediction_timestamp,"prediction_timestamp"); price_map={row.player_id:row for row in prices}; required=set(state.player_ids)|set(action.transfers_in); missing=sorted(required-set(price_map))
    if missing: raise ReplayUnavailableError("PRICE_INCOMPLETE: missing historical current price for "+", ".join(missing))
    for player_id in required:
        row=price_map[player_id]
        try: assert_information_known(known_at=_utc(row.known_at,"price known_at"),prediction_timestamp=prediction,entity=f"historical price {player_id}",source=row.source_id)
        except FutureInformationError as exc: raise ReplayLeakageError(str(exc)) from exc
    owned=set(state.player_ids)
    if not set(action.transfers_out)<=owned or set(action.transfers_in)&owned: raise HistoricalReplayError("Sequential action does not apply to replay account state.")
    selling,purchase=dict(state.selling_prices_tenths),dict(state.purchase_prices_tenths); bank=state.bank_tenths
    for player_id in action.transfers_out:
        if player_id not in selling: raise ReplayUnavailableError(f"PRICE_INCOMPLETE: missing historical selling price for {player_id}")
        bank+=selling.pop(player_id); purchase.pop(player_id,None)
    for player_id in action.transfers_in:
        price=price_map[player_id].current_price_tenths
        if price>bank: raise HistoricalReplayError("Sequential action is not affordable using frozen historical prices.")
        bank-=price; purchase[player_id]=price; selling[player_id]=price
    if action.resulting_bank_tenths is not None and action.resulting_bank_tenths != bank: raise HistoricalReplayError("Sequential action bank conflicts with frozen historical economics.")
    player_ids=tuple(sorted((owned-set(action.transfers_out))|set(action.transfers_in)))
    if len(player_ids)!=15: raise HistoricalReplayError("Sequential action did not retain a 15-player squad.")
    ft=action.free_transfers_after if action.free_transfers_after is not None else min(5,max(0,state.free_transfers-len(action.transfers_in))+1)
    return SequentialAccountState(player_ids,tuple(sorted(purchase.items())),tuple(sorted(selling.items())),bank,ft,state.chips_used)
def replay_sequential_framework(cases:Iterable[HistoricalReplayCase],policy:ReplayPolicy,executor:SequentialPolicyExecutor|None=None)->tuple[SequentialAccountState|None,tuple[str,...]]:
    ordered=tuple(sorted(cases,key=lambda row:(row.season,row.decision_gameweek,_utc(row.prediction_timestamp,"prediction_timestamp"))))
    if not ordered:return None,("No replay cases supplied.",)
    if executor is None:return None,("SEQUENTIAL_POLICY_REPLAY unavailable: frozen policies must be rerun against the carried replay account; no executor was supplied.",)
    state=SequentialAccountState.from_context(ordered[0].context)
    for case in ordered: state=apply_sequential_action(state,executor(case,state,policy),case.price_snapshots,case.prediction_timestamp)
    return state,()

def projection_metrics(rows: Iterable[Mapping[str, Any]]) -> Mapping[str, Any]:
    """Separate V22 quality metrics; policy outcomes are intentionally excluded."""
    values=[row for row in rows if isinstance(row,Mapping)]
    pairs=[(float(row["expected_points"]),float(row["realised_points"])) for row in values if isinstance(row.get("expected_points"),(int,float)) and isinstance(row.get("realised_points"),(int,float))]
    result={"sample_size":len(pairs),"mae":None,"rmse":None,"bias":None,"spearman":None,"brier_5_plus":None,"calibration":{}}
    if not pairs:return result
    predicted=np.asarray([x for x,_ in pairs]); actual=np.asarray([x for _,x in pairs]); error=predicted-actual
    result.update({"mae":float(np.mean(np.abs(error))),"rmse":float(np.sqrt(np.mean(error**2))),"bias":float(np.mean(error))})
    if len(pairs)>1: result["spearman"]=float(np.corrcoef(np.argsort(np.argsort(predicted)),np.argsort(np.argsort(actual)))[0,1])
    brier=[(float(row["p_5_plus"]),(1.0 if float(row["realised_points"])>=5 else 0.0)) for row in values if isinstance(row.get("p_5_plus"),(int,float)) and isinstance(row.get("realised_points"),(int,float))]
    if brier:
        result["brier_5_plus"]=float(np.mean([(p-y)**2 for p,y in brier]))
        for low,high in ((0,.25),(.25,.5),(.5,.75),(.75,1.01)):
            group=[(p,y) for p,y in brier if low<=p<high]
            if group: result["calibration"][f"{low:.2f}-{min(high,1):.2f}"]={"n":len(group),"mean_prediction":float(np.mean([p for p,_ in group])),"observed_rate":float(np.mean([y for _,y in group]))}
    return result

def select_operational_run(candidates:Iterable[tuple[Path,AnalysisManifestV2,Path,DecisionReportV2]],official_deadline:datetime|str)->OperationalHistoricalRun|None:
    """Strict operational choice: last verified context before the official deadline."""
    deadline=_utc(official_deadline,"official_deadline"); accepted=[]
    for analysis_path,manifest,decision_path,decision in candidates:
        if manifest.legacy_unverified or decision.legacy_unverified or manifest.status not in {ReportStatus.COMPLETE,ReportStatus.PARTIAL}: continue
        # A manifest reference is verified against the exact persisted bytes before it is
        # eligible.  A caller cannot substitute an in-memory decision after outcomes.
        if manifest.decision_report is None or not decision_path.is_file(): continue
        if sha256(decision_path.read_bytes()).hexdigest() != manifest.decision_report.sha256: continue
        try:
            persisted=parse_decision_report(json.loads(decision_path.read_text(encoding="utf-8")))
        except (OSError, ValueError): continue
        if persisted.to_dict() != decision.to_dict(): continue
        if manifest.context_id != decision.context_id or manifest.planning_context is None or decision.planning_context is None or decision.external_mutations: continue
        if manifest.planning_context.context_id != decision.planning_context.context_id: continue
        created=max(_utc(manifest.created_at,"analysis created_at"),_utc(decision.created_at,"decision created_at")); prediction=_utc(decision.planning_context.prediction_timestamp,"prediction_timestamp")
        if created >= deadline or prediction >= deadline: continue
        accepted.append((created,analysis_path,manifest,decision_path,decision))
    if not accepted:return None
    created,analysis_path,manifest,decision_path,decision=max(accepted,key=lambda row:(row[0],str(row[1]))); assert decision.planning_context and decision.context_id
    return OperationalHistoricalRun(str(analysis_path),str(decision_path),manifest.analysis_run_id,created.isoformat(),deadline.isoformat(),decision.context_id,decision.planning_context.prediction_timestamp,"LAST_VALID_FULLY_VERIFIED_PRE_DEADLINE_RUN")
def _ci(values:Sequence[float],seed:int)->tuple[float,float]|None:
    if len(values)<MIN_BOOTSTRAP_SAMPLE:return None
    generator=np.random.default_rng(seed); sample=np.asarray(values,float); means=np.mean(generator.choice(sample,size=(2000,len(sample)),replace=True),axis=1); low,high=np.quantile(means,[.025,.975]); return float(low),float(high)
def summarize_replays(reports:Iterable[HistoricalReplayReportV1],horizon:int=1)->HistoricalReplaySummaryV1:
    rows=tuple(reports); values={policy:[] for policy in ReplayPolicy}; greedy={}; excluded={}
    for report in rows:
        if report.replay_mode is not ReplayMode.SINGLE_DECISION_COUNTERFACTUAL: excluded[report.replay_case.replay_case_id]="not a single-decision replay"; continue
        result_map={row.policy:row for row in report.policy_results}; g=result_map.get(ReplayPolicy.GREEDY_1GW)
        if g and g.hit_adjusted_gain_vs_hold.get(horizon) is not None:greedy[report.replay_case.replay_case_id]=float(g.hit_adjusted_gain_vs_hold[horizon])
        for policy,result in result_map.items():
            value=result.hit_adjusted_gain_vs_hold.get(horizon)
            if value is not None:values[policy].append(float(value))
    metrics=[]
    for policy in ReplayPolicy:
        rows_for_policy=[]
        for report in rows:
            item=next((x for x in report.policy_results if x.policy is policy),None)
            if item and item.hit_adjusted_gain_vs_hold.get(horizon) is not None:rows_for_policy.append((report.replay_case.replay_case_id,float(item.hit_adjusted_gain_vs_hold[horizon])))
        sample=[x[1] for x in rows_for_policy]
        if len(sample)<MIN_BOOTSTRAP_SAMPLE:metrics.append(PolicyAggregate(policy,len(sample),None,None,None,None,None,None,"INSUFFICIENT SAMPLE"));continue
        ci=_ci(sample,sum(map(ord,policy.value))); deltas=[value-greedy[case_id] for case_id,value in rows_for_policy if case_id in greedy]
        metrics.append(PolicyAggregate(policy,len(sample),float(np.mean(sample)),float(median(sample)),ci[0] if ci else None,ci[1] if ci else None,float(np.mean(np.asarray(sample)>0)),float(np.mean(np.asarray(deltas)>0)) if deltas else None,"AVAILABLE"))
    return HistoricalReplaySummaryV1(HISTORICAL_REPLAY_SUMMARY_SCHEMA_V1,ReplayMode.SINGLE_DECISION_COUNTERFACTUAL,tuple(row.replay_case.replay_case_id for row in rows if row.replay_case.replay_case_id not in excluded),excluded,tuple(metrics),{})
def load_replay_case(path:Path)->HistoricalReplayCase:
    raw=json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw,Mapping) or not isinstance(raw.get("decision_report"),Mapping):raise HistoricalReplayError("Replay case requires a typed decision_report.")
    decision=parse_decision_report(raw["decision_report"]); outcomes=tuple(RealisedPlayerOutcome(**row) for row in raw.get("realised_outcomes",()) if isinstance(row,Mapping)); prices=tuple(HistoricalPrice(**row) for row in raw.get("price_snapshots",()) if isinstance(row,Mapping)); hashes=tuple((str(row[0]),str(row[1])) for row in raw.get("artifact_hashes",()) if isinstance(row,(list,tuple)) and len(row)==2)
    return HistoricalReplayCase(str(raw["replay_case_id"]),str(raw["season"]),int(raw["decision_gameweek"]),str(raw["official_deadline"]),decision,outcomes,prices,str(raw.get("outcome_source_id","")),tuple(str(row) for row in raw.get("market_quote_timestamps",())),raw.get("planning_rules",{}),hashes,raw.get("fixture_type"))
def _policies(raw:str)->tuple[ReplayPolicy,...]: return tuple(ReplayPolicy) if raw.strip().lower()=="all" else tuple(ReplayPolicy(item.strip().upper()) for item in raw.split(",") if item.strip())
def main(argv:Sequence[str]|None=None)->int:
    parser=argparse.ArgumentParser(description="Strict developer-only historical policy replay")
    parser.add_argument("--case",type=Path,action="append",default=[],help="Frozen replay-case JSON; repeatable."); parser.add_argument("--season"); parser.add_argument("--gw-start",type=int); parser.add_argument("--gw-end",type=int); parser.add_argument("--policies",default="all"); parser.add_argument("--mode",choices=("single","sequential"),default="single"); parser.add_argument("--output-dir",type=Path,required=True)
    args=parser.parse_args(argv); cases=[load_replay_case(path) for path in args.case]; cases=[case for case in cases if (not args.season or case.season==args.season) and (args.gw_start is None or case.decision_gameweek>=args.gw_start) and (args.gw_end is None or case.decision_gameweek<=args.gw_end)]; args.output_dir.mkdir(parents=True,exist_ok=True)
    if args.mode=="sequential":
        _state,warnings=replay_sequential_framework(cases,ReplayPolicy.HOLD); payload={"schema_version":HISTORICAL_REPLAY_SCHEMA_V1,"replay_mode":ReplayMode.SEQUENTIAL_POLICY_REPLAY.value,"status":"UNAVAILABLE","warnings":list(warnings)}; (args.output_dir/"sequential-replay-unavailable.json").write_bytes(canonical_json(payload)); print(json.dumps(payload,sort_keys=True)); return 0
    reports=[replay_single_decision(case,_policies(args.policies)) for case in cases]
    for report in reports:(args.output_dir/f"{report.replay_case.replay_case_id}.json").write_bytes(report.canonical_bytes())
    summary=summarize_replays(reports); (args.output_dir/"summary.json").write_bytes(canonical_json(summary.to_dict())); print(json.dumps({"cases":len(reports),"output_dir":str(args.output_dir),"schema_version":HISTORICAL_REPLAY_SCHEMA_V1},sort_keys=True)); return 0
if __name__ == "__main__": raise SystemExit(main())

