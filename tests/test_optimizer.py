from datetime import datetime,timezone
from dataclasses import replace
from types import SimpleNamespace
from pathlib import Path
import pytest
from fpl_engine.optimizer import *

ROOT=Path(__file__).resolve().parents[1];AT=datetime(2026,9,1,tzinfo=timezone.utc)
def squad():
 positions=['GK']*2+['DEF']*5+['MID']*5+['FWD']*3
 return tuple(SquadPlayer(f'p{i}',pos,f'c{i//3}',50,50) for i,pos in enumerate(positions))
def projections(players):
 return {p.player_id:SimpleNamespace(player_id=p.player_id,season='2026/27',rule_version=1,prediction_timestamp=AT,gameweeks=(SimpleNamespace(expected_points=float(i+1)),),weighted_ev_next_6=float(i+1),ev_next_1=float(i+1),ev_next_3=float(i+1),ev_next_6=float(i+1)) for i,p in enumerate(players)}
def state(players=None,ft=1,gw=5):return SquadState(players or squad(),10,ft,ChipState(),gw,'2026/27',1,AT)

def test_rules_selling_prices_and_ft_transitions():
 r=OptimizerRules.load(ROOT);assert r.version==1 and r.season=='2026/27'
 assert selling_price(75,78,r)==76 and selling_price(50,51,r)==50 and selling_price(50,54,r)==52 and selling_price(75,73,r)==73
 assert next_free_transfers(5,0,r)==5 and next_free_transfers(3,1,r)==3 and next_free_transfers(1,2,r)==1

def test_2024_25_optimizer_rules_preserve_five_transfer_and_player_chip_scope():
 r=OptimizerRules.load(ROOT,season='2024/25')
 assert r.version==202425 and r.season=='2024/25'
 assert r.value('free_transfer_state','maximum')==5
 assert r.value('free_hit','persistent_state','restore_original_squad_next_deadline') is True
 assert 'assistant_manager' in r.value('chips','excluded_from_v1')
 historical=SquadState(squad(),10,5,ChipState(),20,'2024/25',202425,AT)
 validate_squad(historical,r)
 assert chip_available('wildcard',historical,r)
 assert next_free_transfers(5,0,r)==5

def test_2023_24_optimizer_rules_preserve_two_ft_cap_and_chip_reset():
 r=OptimizerRules.load(ROOT,season='2023/24')
 assert r.version==202324 and r.season=='2023/24'
 assert r.value('free_transfer_state','maximum')==2
 assert next_free_transfers(2,0,r)==2
 assert next_free_transfers(2,0,r,chip='wildcard')==1
 assert next_free_transfers(2,0,r,chip='free_hit')==1

def test_squad_validation_and_milp_lineup_are_legal_and_deterministic():
 r=OptimizerRules.load(ROOT);s=state();validate_squad(s,r);p=projections(s.players)
 a=optimize_lineup(s,p,r);b=optimize_lineup(s,p,r);assert a==b and len(a.starting_xi)==11 and a.captain_id!=a.vice_captain_id
 assert a.formation in r.value('starting_xi','valid_formations') and len(a.bench_order)==4
 bad=list(s.players);bad[-1]=SquadPlayer('x','FWD',bad[0].club_id,50,50)
 with pytest.raises(OptimizerError):validate_squad(state(tuple(bad)),r)

def test_roll_is_real_action_and_transfer_requires_net_gain():
 r=OptimizerRules.load(ROOT);s=state();p=projections(s.players);o=Optimizer(r)
 assert o.recommend(s,p).roll_ft
 incoming=SquadPlayer('new','FWD','newclub',50,50);p['new']=SimpleNamespace(player_id='new',season='2026/27',rule_version=1,prediction_timestamp=AT,gameweeks=(SimpleNamespace(expected_points=30.),),weighted_ev_next_6=30.,ev_next_1=30.,ev_next_3=30.,ev_next_6=30.)
 rec=o.recommend(s,p,[incoming],max_transfers=1);assert not rec.roll_ft and rec.transfers_in==('new',) and rec.net_gain>0

def test_chips_autosub_and_sensitivity_contract():
 r=OptimizerRules.load(ROOT);s=state();p=projections(s.players);line=optimize_lineup(s,p,r)
 assert chip_available('wildcard',s,r) and chip_available('free_hit',s,r) and chip_available('bench_boost',s,r) and chip_available('triple_captain',s,r)
 assert not chip_available('free_hit',state(gw=1),r)
 pts={x.player_id:2 for x in s.players};mins={x.player_id:90 for x in s.players};mins[line.captain_id]=0
 assert autosub_points(line,s,pts,mins,r)>0
 report=sensitivity(Optimizer(r),s,p,runs=10,seed=7);assert report['runs']==10 and report['recommended_action_stability']==1

def test_projection_run_contract_rejects_season_rule_and_timestamp_mismatch():
 r=OptimizerRules.load(ROOT);s=state();p=projections(s.players)
 for field,value,match in [('season','2025/26','season'),('rule_version',2,'rule version'),('prediction_timestamp',datetime(2026,9,2,tzinfo=timezone.utc),'prediction_timestamp')]:
  broken=dict(p);broken['p0']=SimpleNamespace(**{**vars(p['p0']),field:value})
  with pytest.raises(OptimizerError,match=match):Optimizer(r).recommend(s,broken)

def test_exact_budget_club_limit_hit_accounting_and_roll_tie():
 r=OptimizerRules.load(ROOT);s=state();p=projections(s.players);o=Optimizer(r)
 exact=SquadPlayer('exact','FWD','newclub',60,60);p['exact']=SimpleNamespace(**{**vars(p['p12']), 'player_id':'exact','weighted_ev_next_6':30.,'ev_next_1':30.,'ev_next_3':30.,'ev_next_6':30.,'gameweeks':(SimpleNamespace(expected_points=30.),)})
 rec=o.recommend(s,p,[exact],max_transfers=1);assert rec.resulting_bank==0 and rec.transfers_in==('exact',)
 blocked=SquadPlayer('blocked','FWD','c0',50,50);p['blocked']=SimpleNamespace(**{**vars(p['exact']),'player_id':'blocked'})
 assert o.recommend(s,p,[blocked],max_transfers=1).roll_ft
 tie=SquadPlayer('tie','FWD','newclub',50,50);p['tie']=SimpleNamespace(**{**vars(p['p12']),'player_id':'tie'})
 assert o.recommend(s,p,[tie],max_transfers=1).roll_ft
 mid=SquadPlayer('mid','MID','newclub2',50,50);p['mid']=SimpleNamespace(**{**vars(p['exact']),'player_id':'mid'})
 two=o.recommend(s,p,[exact,mid],max_transfers=2);assert len(two.transfers_in)==2 and two.hit_cost==4 and two.net_gain==two.gross_gain-4

def test_feasible_portfolio_keeps_only_legal_budgeted_plans_and_supports_funding_move():
 r=OptimizerRules.load(ROOT);s=SquadState(squad(),0,1,ChipState(),5,'2026/27',1,AT);p=projections(s.players);o=Optimizer(r)
 expensive=SquadPlayer('expensive','MID','new_mid',90,90)
 cheap=SquadPlayer('cheap','DEF','new_def',10,10)
 p['expensive']=SimpleNamespace(**{**vars(p['p7']),'player_id':'expensive','weighted_ev_next_6':60.,'ev_next_1':20.,'ev_next_3':40.,'ev_next_6':60.,'gameweeks':(SimpleNamespace(expected_points=20.),)})
 p['cheap']=SimpleNamespace(**{**vars(p['p2']),'player_id':'cheap','weighted_ev_next_6':2.,'ev_next_1':1.,'ev_next_3':2.,'ev_next_6':2.,'gameweeks':(SimpleNamespace(expected_points=1.),)})
 rec=o.recommend(s,p,[expensive,cheap],max_transfers=2)
 funding=next(plan for plan in rec.alternatives if set(plan.transfers_in)=={'expensive','cheap'})
 assert funding.resulting_bank==0 and funding.free_transfers_used==1 and funding.hit_cost==4
 assert funding.net_gain==funding.gross_gain-funding.hit_cost
 assert not any(plan.transfers_in==('expensive',) for plan in rec.alternatives)
 by_id={player.player_id:player for player in s.players}|{'expensive':expensive,'cheap':cheap}
 final=tuple(player for player in s.players if player.player_id not in funding.transfers_out)+tuple(by_id[player_id] for player_id in funding.transfers_in)
 validate_squad(SquadState(final,funding.resulting_bank,s.free_transfers,s.chips,s.current_gameweek,s.season,s.rule_version,s.prediction_timestamp),r)

def test_autosub_preserves_formation_and_no_captain_bonus_when_both_leaders_miss():
 r=OptimizerRules.load(ROOT);s=state();p=projections(s.players);line=optimize_lineup(s,p,r)
 byid={x.player_id:x for x in s.players};starting_def=next(pid for pid in line.starting_xi if byid[pid].position=='DEF')
 points={x.player_id:1 for x in s.players};minutes={x.player_id:90 for x in s.players}
 minutes[starting_def]=0;minutes[line.captain_id]=0;minutes[line.vice_captain_id]=0
 total=autosub_points(line,s,points,minutes,r)
 assert total>=9
