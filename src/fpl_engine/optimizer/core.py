"""OPT-001..016 rule-driven V1 FPL optimizer contracts and algorithms."""
from collections import Counter
from dataclasses import dataclass,replace
from datetime import datetime,timezone
from itertools import combinations,product
from pathlib import Path
from time import perf_counter
import math
from typing import Iterable,Mapping
import numpy as np
from scipy.optimize import Bounds,LinearConstraint,milp
from fpl_engine.config.loader import FPLRulesConfig,load_fpl_rules_config
from fpl_engine.models.projections import PlayerProjection

class OptimizerError(ValueError):pass
@dataclass(frozen=True)
class OptimizerRules:
 raw:Mapping;version:int;season:str
 @classmethod
 def load(cls,root:Path|None=None,*,season:str|None=None):
  x=load_fpl_rules_config(root,season=season);return cls(x.model_dump(),x.version,x.season)
 def value(self,*path):
  x=self.raw
  for key in path:x=x[key]
  return x

@dataclass(frozen=True)
class SquadPlayer:
 player_id:str;position:str;club_id:str;purchase_price:int;current_price:int;selling_price:int|None=None
 def __post_init__(self):
  if not self.player_id or not self.club_id or self.position not in {'GK','DEF','MID','FWD'}:raise OptimizerError('invalid player metadata')
  if type(self.purchase_price)is not int or type(self.current_price)is not int or min(self.purchase_price,self.current_price)<0:raise OptimizerError('prices must be non-negative integer 0.1m units')
  if self.selling_price is not None and(type(self.selling_price)is not int or self.selling_price<0):raise OptimizerError('invalid selling price')
@dataclass(frozen=True)
class ChipState:
 wildcard_h1:bool=True;wildcard_h2:bool=True;free_hit_h1:bool=True;free_hit_h2:bool=True;bench_boost_h1:bool=True;bench_boost_h2:bool=True;triple_captain_h1:bool=True;triple_captain_h2:bool=True;last_free_hit_gameweek:int|None=None
@dataclass(frozen=True)
class SquadState:
 players:tuple[SquadPlayer,...];bank:int;free_transfers:int;chips:ChipState;current_gameweek:int;season:str;rule_version:int;prediction_timestamp:datetime|None=None
 def __post_init__(self):
  if type(self.bank)is not int or self.bank<0:raise OptimizerError('bank must be non-negative integer units')
  if self.prediction_timestamp is not None and (not isinstance(self.prediction_timestamp,datetime) or self.prediction_timestamp.tzinfo is None or self.prediction_timestamp.utcoffset() is None):raise OptimizerError('prediction_timestamp must be aware')
@dataclass(frozen=True)
class Lineup:
 starting_xi:tuple[str,...];formation:str;bench_order:tuple[str,...];captain_id:str;vice_captain_id:str;expected_points:float
@dataclass(frozen=True)
class TransferPlan:
 transfers_out:tuple[str,...];transfers_in:tuple[str,...];gross_gain:float;hit_cost:int;net_gain:float;bank_after:int;free_transfers_used:int;free_transfers_after:int;roll_ft:bool
@dataclass(frozen=True)
class Alternative:
 action:str;utility:float;transfers_out:tuple[str,...]=();transfers_in:tuple[str,...]=();chip:str|None=None
 # These are the values already calculated for the corresponding
 # TransferPlan.  Keeping them on the serialized alternative exposes the
 # existing feasible-plan portfolio without re-running or changing the
 # optimizer in a desktop presentation layer.
 hit_cost:int|None=None;gross_gain:float|None=None;net_gain:float|None=None
 resulting_bank:int|None=None;free_transfers_used:int|None=None;free_transfers_after:int|None=None
 roll_ft:bool=False
@dataclass(frozen=True)
class Recommendation:
 action:str;transfers_out:tuple[str,...];transfers_in:tuple[str,...];roll_ft:bool;hit_cost:int;gross_gain:float;net_gain:float;resulting_bank:int;free_transfers_before:int;free_transfers_after:int;starting_xi:tuple[str,...];formation:str;bench_order:tuple[str,...];captain_id:str;vice_captain_id:str;chip:str|None;raw_ev_1gw:float;raw_ev_3gw:float;raw_ev_6gw:float;weighted_utility_6gw:float;alternatives:tuple[Alternative,...];decision_margin:float;action_stability:float|None;prediction_timestamp:datetime;rule_version:int;optimizer_version:str

def selling_price(purchase:int,current:int,rules:OptimizerRules)->int:
 if type(purchase)is not int or type(current)is not int or min(purchase,current)<0:raise OptimizerError('prices use integer units')
 return current if current<=purchase else purchase+(current-purchase)//2
def next_free_transfers(current:int,transfers:int,rules:OptimizerRules,chip:str|None=None)->int:
 cap=int(rules.value('free_transfer_state','maximum'))
 if chip in {'wildcard','free_hit'}:
  chip_rules=rules.value(chip,'free_transfer_state')
  if not bool(chip_rules.get('banked_transfers_retained',True)):
   return int(chip_rules.get('reset_to',1))
  return min(cap,current)
 return min(cap,max(0,current-transfers)+int(rules.value('transfers','normal_gameweek','free_transfers_granted_per_gameweek')))
def validate_squad(state:SquadState,rules:OptimizerRules)->None:
 expected=int(rules.value('initial_squad','squad_size'))
 if len(state.players)!=expected or len({p.player_id for p in state.players})!=expected:raise OptimizerError('squad must contain distinct configured squad size')
 codes={v['canonical_code']:v['squad_count'] for v in rules.value('positions').values()}
 if Counter(p.position for p in state.players)!=Counter(codes):raise OptimizerError('invalid positional composition')
 if max(Counter(p.club_id for p in state.players).values())>int(rules.value('initial_squad','maximum_players_per_club')):raise OptimizerError('club limit exceeded')
 if not 1<=state.free_transfers<=int(rules.value('free_transfer_state','maximum')):raise OptimizerError('invalid FT state')
 if state.season!=rules.season or state.rule_version!=rules.version:raise OptimizerError('squad/rule version mismatch')

def validate_projection_contract(state:SquadState,projections:Mapping[str,PlayerProjection],player_ids:Iterable[str])->datetime:
 ids=tuple(player_ids)
 missing=set(ids)-set(projections)
 if missing:raise OptimizerError(f"missing player projection: {sorted(missing)}")
 rows=[projections[player_id] for player_id in ids]
 if not rows:raise OptimizerError('at least one player projection is required')
 seasons={getattr(row,'season',None) for row in rows}
 rules={getattr(row,'rule_version',None) for row in rows}
 timestamps={getattr(row,'prediction_timestamp',None) for row in rows}
 if seasons!={state.season}:raise OptimizerError('projection/squad season mismatch')
 if rules!={state.rule_version}:raise OptimizerError('projection/squad rule version mismatch')
 if len(timestamps)!=1:raise OptimizerError('incompatible projection prediction_timestamps')
 timestamp=timestamps.pop()
 if not isinstance(timestamp,datetime) or timestamp.tzinfo is None or timestamp.utcoffset() is None:raise OptimizerError('projection prediction_timestamp must be aware')
 timestamp=timestamp.astimezone(timezone.utc)
 if state.prediction_timestamp is not None and timestamp!=state.prediction_timestamp.astimezone(timezone.utc):raise OptimizerError('projection/run prediction_timestamp mismatch')
 return timestamp

def _gw(p:PlayerProjection,index=0):return p.gameweeks[index]
def optimize_lineup(state:SquadState,projections:Mapping[str,PlayerProjection],rules:OptimizerRules,*,triple_captain=False,bench_boost=False)->Lineup:
 validate_squad(state,rules);players=state.players;n=len(players)
 validate_projection_contract(state,projections,(p.player_id for p in players))
 ev=np.array([_gw(projections[p.player_id]).expected_points for p in players]);c=-ev-1e-9*np.arange(n,0,-1)
 constraints=[LinearConstraint(np.ones((1,n)),11,11)]
 for pos,lo,hi in [('GK',1,1),('DEF',3,5),('MID',2,5),('FWD',1,3)]:constraints.append(LinearConstraint(np.array([[p.position==pos for p in players]],float),lo,hi))
 result=milp(c,integrality=np.ones(n),bounds=Bounds(0,1),constraints=constraints,options={'presolve':True})
 if not result.success:raise OptimizerError('no legal starting XI')
 xi=[i for i,x in enumerate(result.x) if x>.5];bench=[i for i in range(n) if i not in xi]
 gkbench=[i for i in bench if players[i].position=='GK'];outfield=sorted((i for i in bench if players[i].position!='GK'),key=lambda i:(-ev[i],players[i].player_id));order=gkbench+outfield
 captain=max(xi,key=lambda i:(ev[i],-i));vice=max((i for i in xi if i!=captain),key=lambda i:(ev[i],-i));mult=int(rules.value('triple_captain','captain_multiplier') if triple_captain else rules.value('captaincy','captain_multiplier'))
 points=float(ev[xi].sum()+ev[captain]*(mult-1)+(ev[bench].sum() if bench_boost else 0))
 counts=Counter(players[i].position for i in xi);formation=f"{counts['DEF']}-{counts['MID']}-{counts['FWD']}"
 return Lineup(tuple(players[i].player_id for i in xi),formation,tuple(players[i].player_id for i in order),players[captain].player_id,players[vice].player_id,points)

def autosub_points(lineup:Lineup,state:SquadState,points:Mapping[str,float],minutes:Mapping[str,float],rules:OptimizerRules)->float:
 byid={p.player_id:p for p in state.players};active=[pid for pid in lineup.starting_xi if minutes.get(pid,0)>0];bench=list(lineup.bench_order)
 start_gk=next(pid for pid in lineup.starting_xi if byid[pid].position=='GK');bench_gk=next(pid for pid in bench if byid[pid].position=='GK')
 if minutes.get(start_gk,0)==0 and minutes.get(bench_gk,0)>0:active.append(bench_gk)
 for missing in [pid for pid in lineup.starting_xi if byid[pid].position!='GK' and minutes.get(pid,0)==0]:
  for candidate in bench:
   if byid[candidate].position=='GK' or minutes.get(candidate,0)==0 or candidate in active:continue
   trial=active+[candidate];cnt=Counter(byid[x].position for x in trial)
   if cnt['DEF']>=3 and cnt['MID']>=2 and cnt['FWD']>=1:active.append(candidate);break
 captain=lineup.captain_id if minutes.get(lineup.captain_id,0)>0 else lineup.vice_captain_id if minutes.get(lineup.vice_captain_id,0)>0 else None
 return sum(points.get(pid,0) for pid in active)+(points.get(captain,0) if captain else 0)

def chip_available(chip:str,state:SquadState,rules:OptimizerRules)->bool:
 if chip not in rules.value('chips','types'):return False
 half='h1' if state.current_gameweek<=int(rules.value('chip_periods','first_half','gameweeks','through')) else 'h2'
 if not getattr(state.chips,f'{chip}_{half}'):return False
 if chip in {'wildcard','free_hit'} and state.current_gameweek==1:return False
 if chip=='free_hit' and state.chips.last_free_hit_gameweek==state.current_gameweek-1:return False
 return True

@dataclass
class LegacySearchDiagnostics:
 candidate_pool_size:int=0;outgoing_candidate_count:int=0;incoming_candidate_count:int=0
 raw_single_combinations:int=0;raw_two_combinations:int=0;position_prefiltered:int=0;rejected_position_mismatch:int=0
 rejected_same_player:int=0;rejected_duplicate_incoming:int=0;rejected_owned:int=0
 rejected_club_limit:int=0;rejected_affordability:int=0;rejected_squad_legality:int=0
 rejected_missing_projection:int=0;canonical_legality_checks:int=0;legal_plans:int=0
 duplicate_resulting_squads:int=0;lineup_evaluations:int=0;lineup_cache_hits:int=0
 candidate_sort_seconds:float=0.0;runtime_seconds:float=0.0;mode:str="optimized"
 def snapshot(self):
  return {key:getattr(self,key) for key in self.__dataclass_fields__}

@dataclass(frozen=True)
class LegacySearchResult:
 plans:tuple[TransferPlan,...]
 diagnostics:LegacySearchDiagnostics

def _regular_transfer_limit(rules,max_transfers,chip):
 if chip in {'wildcard','free_hit'}:return 0
 return min(max_transfers,int(rules.value('transfers','normal_gameweek','maximum_regular_transfers_per_gameweek')))

def _sale(player,rules):
 return player.selling_price if player.selling_price is not None else selling_price(player.purchase_price,player.current_price,rules)

def _plan(state,outs,ins,projections,rules,bank):
 count=len(ins);hit=max(0,count-state.free_transfers)*int(rules.value('transfers','normal_gameweek','points_cost_per_transfer_above_allowance'))
 gross=sum(projections[p.player_id].weighted_ev_next_6 for p in ins)-sum(projections[p.player_id].weighted_ev_next_6 for p in outs)
 return TransferPlan(tuple(sorted(p.player_id for p in outs)),tuple(sorted(p.player_id for p in ins)),gross,hit,gross-hit,bank,min(count,state.free_transfers),next_free_transfers(state.free_transfers,count,rules),False)

def _temporary(state,outs,ins):
 return SquadState(tuple([p for p in state.players if p not in outs]+list(ins)),0,state.free_transfers,state.chips,state.current_gameweek,state.season,state.rule_version,state.prediction_timestamp)

def _sorted_result(plans,diagnostics):
 started=perf_counter(); plans.sort(key=lambda p:(-p.net_gain,p.transfers_out,p.transfers_in));diagnostics.candidate_sort_seconds=perf_counter()-started
 return tuple(plans)

def legacy_reference_search(state:SquadState,projections:Mapping[str,PlayerProjection],pool:Iterable[SquadPlayer],rules:OptimizerRules,*,max_transfers:int=2)->LegacySearchResult:
 """Exhaustive pre-P1.4 V1 enumeration retained for bounded differential tests."""
 started=perf_counter(); pool=tuple(pool);owned={p.player_id for p in state.players};incoming=tuple(p for p in pool if p.player_id not in owned)
 d=LegacySearchDiagnostics(candidate_pool_size=len(pool),outgoing_candidate_count=len(state.players),incoming_candidate_count=len(incoming),mode='reference')
 plans=[TransferPlan((),(),0,0,0,state.bank,0,next_free_transfers(state.free_transfers,0,rules),True)]
 limit=_regular_transfer_limit(rules,max_transfers,None)
 for count in range(1,limit+1):
  raw=len(tuple(combinations(state.players,count)))*len(tuple(combinations(incoming,count)))
  if count==1:d.raw_single_combinations=raw
  elif count==2:d.raw_two_combinations=raw
  for outs in combinations(state.players,count):
   for ins in combinations(incoming,count):
    temp=_temporary(state,outs,ins);d.canonical_legality_checks+=1
    try:validate_squad(temp,rules)
    except OptimizerError:d.rejected_squad_legality+=1;continue
    bank=state.bank+sum(_sale(p,rules) for p in outs)-sum(p.current_price for p in ins)
    if bank<0:d.rejected_affordability+=1;continue
    if any(p.player_id not in projections for p in ins):d.rejected_missing_projection+=1;continue
    plans.append(_plan(state,outs,ins,projections,rules,bank));d.legal_plans+=1
 result=_sorted_result(plans,d);d.runtime_seconds=perf_counter()-started
 return LegacySearchResult(result,d)

def _structural_incoming(outs,incoming_by_position,diagnostics):
 # A legal regular transfer preserves positional squad counts.  Build exactly
 # the required combination for each position, then take their Cartesian
 # product.  This works for the existing 1/2-transfer production path and the
 # already-supported bounded 3+ transfer test path without enumerating any
 # impossible cross-position permutation.
 counts=Counter(p.position for p in outs)
 groups=tuple(combinations(incoming_by_position[position],count) for position,count in sorted(counts.items()))
 return (tuple(player for group in selection for player in group) for selection in product(*groups))

def optimized_search(state:SquadState,projections:Mapping[str,PlayerProjection],pool:Iterable[SquadPlayer],rules:OptimizerRules,*,max_transfers:int=2)->LegacySearchResult:
 """Exact V1 search with only deterministic pre-validation rejections.

 The canonical ``validate_squad`` remains the final authority.  Plan sorting is
 intentionally the historic ``(-net, sorted OUT, sorted IN)`` key, so equal
 score tie-breaking does not depend on the faster enumeration order.
 """
 started=perf_counter(); pool=tuple(pool);owned={p.player_id for p in state.players}
 incoming=tuple(p for p in pool if p.player_id not in owned)
 d=LegacySearchDiagnostics(candidate_pool_size=len(pool),outgoing_candidate_count=len(state.players),incoming_candidate_count=len(incoming))
 limit=_regular_transfer_limit(rules,max_transfers,None)
 for count in range(1,limit+1):
  raw=len(tuple(combinations(state.players,count)))*len(tuple(combinations(incoming,count)))
  if count==1:d.raw_single_combinations=raw
  elif count==2:d.raw_two_combinations=raw
 by_position={position:tuple(p for p in incoming if p.position==position) for position in ('GK','DEF','MID','FWD')}
 club_counts=Counter(p.club_id for p in state.players);club_limit=int(rules.value('initial_squad','maximum_players_per_club'))
 plans=[TransferPlan((),(),0,0,0,state.bank,0,next_free_transfers(state.free_transfers,0,rules),True)]
 for count in range(1,limit+1):
  for outs in combinations(state.players,count):
   for ins in _structural_incoming(outs,by_position,d):
    d.position_prefiltered+=1
    ids=tuple(p.player_id for p in ins)
    if len(ids)!=len(set(ids)):
     d.rejected_duplicate_incoming+=1;continue
    if any(pid in owned for pid in ids):
     d.rejected_owned+=1;continue
    if any(pid not in projections for pid in ids):
     d.rejected_missing_projection+=1;continue
    bank=state.bank+sum(_sale(p,rules) for p in outs)-sum(p.current_price for p in ins)
    if bank<0:
     d.rejected_affordability+=1;continue
    updated=club_counts.copy()
    for player in outs:updated[player.club_id]-=1
    for player in ins:updated[player.club_id]+=1
    if any(value>club_limit for value in updated.values()):
     d.rejected_club_limit+=1;continue
    temp=_temporary(state,outs,ins)
    # Do not collapse repeated source-pool rows here: historic V1 exposed every
    # legal enumeration, including equal plans from malformed duplicate input.
    # Valid production pools are unique; preserving this behavior keeps the
    # differential reference exact even for defensive test inputs.
    d.canonical_legality_checks+=1
    try:validate_squad(temp,rules)
    except OptimizerError:
     d.rejected_squad_legality+=1;continue
    plans.append(_plan(state,outs,ins,projections,rules,bank));d.legal_plans+=1
 d.rejected_position_mismatch=d.raw_single_combinations+d.raw_two_combinations-d.position_prefiltered
 result=_sorted_result(plans,d);d.runtime_seconds=perf_counter()-started
 return LegacySearchResult(result,d)

class Optimizer:
 VERSION='optimizer_v1'
 def __init__(self,rules:OptimizerRules,*,lineup_provider=None):
  self.rules=rules;self.lineup_provider=lineup_provider;self.last_search_diagnostics:LegacySearchDiagnostics|None=None
 def recommend(self,state:SquadState,projections:Mapping[str,PlayerProjection],pool:Iterable[SquadPlayer]=(),*,max_transfers=2,chip:str|None=None)->Recommendation:
  validate_squad(state,self.rules);pool=tuple(pool)
  timestamp=validate_projection_contract(state,projections,(p.player_id for p in state.players+pool))
  if chip and not chip_available(chip,state,self.rules):raise OptimizerError('chip unavailable')
  if chip in {'wildcard','free_hit'}:
   selected=self._unlimited_squad(state,projections,pool);old={p.player_id:p for p in state.players};new={p.player_id:p for p in selected};outs=tuple(sorted(set(old)-set(new)));ins=tuple(sorted(set(new)-set(old)));bank=state.bank+sum(_sale(old[x],self.rules) for x in outs)-sum(new[x].current_price for x in ins);working=SquadState(selected,bank,state.free_transfers,state.chips,state.current_gameweek,state.season,state.rule_version,state.prediction_timestamp)
   gross=sum(projections[x].weighted_ev_next_6 for x in ins)-sum(projections[x].weighted_ev_next_6 for x in outs);plans=[TransferPlan(outs,ins,gross,0,gross,bank,0,next_free_transfers(state.free_transfers,len(outs),self.rules,chip),False)]
   self.last_search_diagnostics=None
  else:
   search=optimized_search(state,projections,pool,self.rules,max_transfers=max_transfers);plans=list(search.plans);self.last_search_diagnostics=search.diagnostics;working=state
  best=plans[0]
  if chip not in {'wildcard','free_hit'} and best.transfers_out:
   byid={p.player_id:p for p in state.players};incoming={p.player_id:p for p in pool}
   for player_id in best.transfers_out:byid.pop(player_id)
   for player_id in best.transfers_in:byid[player_id]=incoming[player_id]
   working=SquadState(tuple(byid.values()),best.bank_after,best.free_transfers_after,state.chips,state.current_gameweek,state.season,state.rule_version,state.prediction_timestamp)
  if self.lineup_provider is None:lineup=optimize_lineup(working,projections,self.rules,triple_captain=chip=='triple_captain',bench_boost=chip=='bench_boost')
  else:lineup=self.lineup_provider(working,triple_captain=chip=='triple_captain',bench_boost=chip=='bench_boost')
  if self.last_search_diagnostics is not None:self.last_search_diagnostics.lineup_evaluations=1
  alts=tuple(Alternative('ROLL_FT' if p.roll_ft else 'TRANSFER',p.net_gain,p.transfers_out,p.transfers_in,None,p.hit_cost,p.gross_gain,p.net_gain,p.bank_after,p.free_transfers_used,p.free_transfers_after,p.roll_ft) for p in plans[:5]);margin=best.net_gain-(plans[1].net_gain if len(plans)>1 else 0);ts=timestamp
  action=f"USE_{chip.upper()}" if chip else ('ROLL_FT' if best.roll_ft else 'TRANSFER')
  return Recommendation(action,best.transfers_out,best.transfers_in,best.roll_ft,best.hit_cost,best.gross_gain,best.net_gain,best.bank_after,state.free_transfers,best.free_transfers_after,lineup.starting_xi,lineup.formation,lineup.bench_order,lineup.captain_id,lineup.vice_captain_id,chip,sum(projections[p.player_id].ev_next_1 for p in working.players),sum(projections[p.player_id].ev_next_3 for p in working.players),sum(projections[p.player_id].ev_next_6 for p in working.players),sum(projections[p.player_id].weighted_ev_next_6 for p in working.players),alts,margin,None,ts,self.rules.version,self.VERSION)
 def _unlimited_squad(self,state,projections,pool):
  candidates=tuple({p.player_id:p for p in state.players+pool}.values());n=len(candidates);owned={p.player_id:p for p in state.players};values=np.array([projections[p.player_id].weighted_ev_next_6 for p in candidates]);cost=np.array([(_sale(owned[p.player_id],self.rules)) if p.player_id in owned else p.current_price for p in candidates]);funds=state.bank+sum(_sale(p,self.rules) for p in state.players);constraints=[LinearConstraint(np.ones((1,n)),15,15),LinearConstraint(cost.reshape(1,-1),-np.inf,funds)]
  for pos,count in {'GK':2,'DEF':5,'MID':5,'FWD':3}.items():constraints.append(LinearConstraint(np.array([[p.position==pos for p in candidates]],float),count,count))
  for club in sorted({p.club_id for p in candidates}):constraints.append(LinearConstraint(np.array([[p.club_id==club for p in candidates]],float),0,int(self.rules.value('initial_squad','maximum_players_per_club'))))
  result=milp(-values-1e-9*np.arange(n,0,-1),integrality=np.ones(n),bounds=Bounds(0,1),constraints=constraints)
  if not result.success:raise OptimizerError('no legal unlimited-transfer squad')
  return tuple(candidates[i] for i,x in enumerate(result.x) if x>.5)

def sensitivity(optimizer:Optimizer,state:SquadState,projections:Mapping[str,PlayerProjection],pool=(),*,runs=500,seed=42):
 if runs<=0:raise OptimizerError('runs must be positive')
 rng=np.random.default_rng(seed);counts=Counter();base=optimizer.recommend(state,projections,pool)
 for _ in range(runs):
  perturbed={}
  for pid,p in projections.items():
   scale=max(0.0,1+rng.normal(0,getattr(p,'projection_uncertainty',0)*.15));
   try:perturbed[pid]=replace(p,weighted_ev_next_6=p.weighted_ev_next_6*scale)
   except TypeError:perturbed[pid]=p
  rec=optimizer.recommend(state,perturbed,pool);counts[(rec.action,rec.transfers_out,rec.transfers_in)]+=1
 key=(base.action,base.transfers_out,base.transfers_in);return {'runs':runs,'seed':seed,'action_selection_frequency':{str(k):v/runs for k,v in counts.items()},'recommended_action_stability':counts[key]/runs,'decision_margin':base.decision_margin}

def optimizer_baselines(state:SquadState,projections:Mapping[str,PlayerProjection],pool:Iterable[SquadPlayer],rules:OptimizerRules):
 """Permanent roll, greedy 1-GW, and static weighted-6GW comparison baselines."""
 roll=Alternative('ROLL_FT',0.0)
 owned={p.player_id:p for p in state.players};candidates=[p for p in pool if p.player_id not in owned]
 def best(metric):
  rows=[]
  for outgoing in state.players:
   for incoming in candidates:
    if incoming.position!=outgoing.position:continue
    bank=state.bank+(outgoing.selling_price if outgoing.selling_price is not None else selling_price(outgoing.purchase_price,outgoing.current_price,rules))-incoming.current_price
    if bank<0:continue
    gain=metric(projections[incoming.player_id])-metric(projections[outgoing.player_id]);rows.append((gain,outgoing.player_id,incoming.player_id))
  if not rows:return roll
  gain,outgoing,incoming=max(rows,key=lambda x:(x[0],x[1],x[2]));return Alternative('TRANSFER',gain,(outgoing,),(incoming,))
 return {'roll':roll,'greedy_1gw':best(lambda p:p.ev_next_1),'static_6gw':best(lambda p:p.weighted_ev_next_6)}
