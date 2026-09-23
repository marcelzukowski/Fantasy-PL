from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path
import pytest
from fpl_engine.planning.context import PLANNING_CONTEXT_SCHEMA, PlanningContext
from fpl_engine.reports import AnalysisManifestV2, DecisionReportV2, ReportReference
from fpl_engine.validation.policy_replay import (
 HistoricalPrice, HistoricalReplayCase, RealisedPlayerOutcome, ReplayLeakageError, ReplayPolicy,
 FrozenPolicyAction, SequentialAccountState, apply_sequential_action, frozen_policy_action,
 replay_sequential_framework, replay_single_decision, select_operational_run, summarize_replays, projection_metrics,
)

AT=datetime(2025,8,1,9,tzinfo=timezone.utc); DEADLINE=AT+timedelta(hours=1)
def _context():
 ids=tuple(f'p{i}' for i in range(15))
 return PlanningContext(PLANNING_CONTEXT_SCHEMA,'2024/25',1,None,ids,tuple((x,50) for x in ids),20,2,(('wildcard_h1',False),),'run-1',AT.isoformat(),'v22',('v22',),512,1,1,'a'*64,(('minutes','b'*64),),AT.isoformat(),AT.isoformat(),())
def _preview(out=(),inn=()):
 ids=[f'p{i}' for i in range(15) if f'p{i}' not in out]+list(inn)
 return {'transfers_out':list(out),'transfers_in':list(inn),'resulting_bank':10 if inn else 20,'free_transfers_after':1,'starting_xi':ids[:11],'bench_order':ids[11:],'captain':ids[0],'vice_captain':ids[1]}
def _decision():
 context=_context(); rec={'transfers_out':['p14'],'transfers_in':['p15'],'hit_cost':0,'resulting_bank':10,'free_transfers_before':2,'free_transfers_after':1,'transfer_impacts':{'impact_1gw':3.,'impact_3gw':5.,'impact_6gw':8.}}
 return DecisionReportV2.create(report_id='frozen',created_at=AT+timedelta(minutes=1),planning_context=context,mode='READ ONLY',external_mutations=[],shadow_report=None,recommendation=rec,feasible_plans=[],strategic_v2={'action':'TRANSFER',**rec},strategic_v3={'current_action':{'action':'TRANSFER','transfers_out':['p14'],'transfers_in':['p15'],'hit_cost_points':0,'resulting_bank':10,'free_transfers_before':2,'free_transfers_after':1},'path':[],'delta_vs_hold':2.0},strategic_v3_error=None,strategy_previews={'short_term':_preview(('p14',),('p15',)),'strategic':_preview(('p14',),('p15',))},strategy_preview_identities={},strategy_unavailable={},player_metadata={})
def _case(**changes):
 rows=[]
 for gw in range(1,7):
  for player in [f'p{i}' for i in range(16)]: rows.append(RealisedPlayerOutcome(player,gw,f'f-{player}-{gw}',5. if player=='p15' else 1.,90.,(AT+timedelta(days=gw)).isoformat(),'local'))
 data=dict(replay_case_id='case-1',season='2024/25',decision_gameweek=1,official_deadline=DEADLINE.isoformat(),decision_report=_decision(),realised_outcomes=tuple(rows),price_snapshots=(),outcome_source_id='local',source_artifact_hashes=(('minutes','b'*64),))
 data.update(changes); return HistoricalReplayCase(**data)
def test_single_decision_compares_frozen_transfer_to_hold_for_1_3_6():
 report=replay_single_decision(_case(),(ReplayPolicy.HOLD,ReplayPolicy.GREEDY_1GW,ReplayPolicy.OPTIMIZER_V1,ReplayPolicy.OPTIMIZER_V2,ReplayPolicy.STRATEGIC_V3))
 greedy=next(x for x in report.policy_results if x.policy is ReplayPolicy.GREEDY_1GW)
 assert greedy.realised_gain_vs_hold == {1:4.,3:12.,6:24.}
 assert greedy.hit_adjusted_gain_vs_hold[6] == 24.
 assert report.leakage_checks['realised_outcomes_not_policy_inputs']
 assert next(x for x in report.policy_results if x.policy is ReplayPolicy.OPTIMIZER_V1).availability.value == 'UNAVAILABLE'
def test_hits_and_missing_outcomes_are_explicit_not_zero():
 decision=_decision(); raw=decision.to_dict(); raw['policy_results']['greedy']['hit_cost']=4; case=_case(decision_report=DecisionReportV2.create(report_id='hit',created_at=AT+timedelta(minutes=1),planning_context=_context(),mode='READ ONLY',external_mutations=[],shadow_report=None,recommendation={**raw['recommendation'],'hit_cost':4},feasible_plans=[],strategic_v2=raw['policy_results']['optimizer_v2'],strategic_v3=raw['policy_results']['strategic_v3'],strategic_v3_error=None,strategy_previews={'short_term':_preview(('p14',),('p15',)),'strategic':_preview(('p14',),('p15',))},strategy_preview_identities={},strategy_unavailable={},player_metadata={}),realised_outcomes=tuple(x for x in _case().realised_outcomes if not (x.player_id=='p15' and x.gameweek==6)))
 result=next(x for x in replay_single_decision(case,(ReplayPolicy.GREEDY_1GW,)).policy_results if x.policy is ReplayPolicy.GREEDY_1GW)
 assert result.hit_adjusted_gain_vs_hold[1] == 0. and result.realised_gain_vs_hold[6] is None
def test_pit_future_bundle_price_market_and_outcome_are_rejected():
 with pytest.raises(ReplayLeakageError): _case(official_deadline=AT.isoformat())
 with pytest.raises(ReplayLeakageError): _case(price_snapshots=(HistoricalPrice('p0',50,50,(AT+timedelta(minutes=1)).isoformat(),'x'),))
 with pytest.raises(ReplayLeakageError): _case(market_quote_timestamps=((AT+timedelta(minutes=1)).isoformat(),))
 bad=list(_case().realised_outcomes); bad[0]=RealisedPlayerOutcome('p0',1,'f',1,90,AT.isoformat(),'x')
 with pytest.raises(ReplayLeakageError): _case(realised_outcomes=tuple(bad))
def test_context_hash_mismatch_is_rejected():
 with pytest.raises(ReplayLeakageError): _case(source_artifact_hashes=(('minutes','c'*64),))
def test_sequential_state_rolls_ft_and_uses_historical_selling_prices():
 state=SequentialAccountState.from_context(_context()); prices=[HistoricalPrice(f'p{i}',50,50,AT.isoformat(),'prices') for i in range(16)]; prices[-1]=HistoricalPrice('p15',60,60,AT.isoformat(),'prices')
 action=FrozenPolicyAction(ReplayPolicy.GREEDY_1GW,'test',('p14',),('p15',),0,10,2,1)
 next_state=apply_sequential_action(state,action,prices,AT)
 assert next_state.bank_tenths == 10 and next_state.free_transfers == 1 and 'p15' in next_state.player_ids
 hold=FrozenPolicyAction(ReplayPolicy.HOLD,'test')
 assert apply_sequential_action(next_state,hold,prices,AT).free_transfers == 2
 with pytest.raises(Exception,match='PRICE_INCOMPLETE'): apply_sequential_action(state,action,prices[:-1],AT)
def test_sequential_framework_requires_executor_instead_of_replaying_stale_decisions():
 assert replay_sequential_framework((_case(),),ReplayPolicy.HOLD)[0] is None
 def executor(case,state,policy): return FrozenPolicyAction(policy,'test')
 prices=tuple(HistoricalPrice(f'p{i}',50,50,AT.isoformat(),'prices') for i in range(15))
 state,warnings=replay_sequential_framework((_case(price_snapshots=prices),),ReplayPolicy.HOLD,executor)
 assert state is not None and not warnings
def test_operational_selection_uses_last_verified_predeadline_run(tmp_path):
 decision=_decision(); context=_context(); decision_path=tmp_path/'d.json'; decision_path.write_text(json.dumps(decision.to_dict(),sort_keys=True),encoding='utf-8'); digest=sha256(decision_path.read_bytes()).hexdigest()
 def manifest(name,stamp): return AnalysisManifestV2.create(analysis_run_id=name,created_at=stamp,status='COMPLETE',season='2024/25',gameweek=1,projection_run_id='run-1',decision_report=decision,decision_reference=ReportReference('decision.json',digest),chip_report=None,chip_reference=None,recommended_xi_available=True,captaincy_available=True,display_state=None)
 older=manifest('old',AT-timedelta(minutes=1)); later=manifest('late',AT+timedelta(minutes=2))
 chosen=select_operational_run(((tmp_path/'old.json',older,decision_path,decision),(tmp_path/'late.json',later,decision_path,decision)),DEADLINE)
 assert chosen and chosen.analysis_run_id=='late' and chosen.selection_reason=='LAST_VALID_FULLY_VERIFIED_PRE_DEADLINE_RUN'
 decision_path.write_text('{}',encoding='utf-8')
 assert select_operational_run(((tmp_path/'late.json',later,decision_path,decision),),DEADLINE) is None
def test_summary_labels_small_samples_and_is_deterministic():
 reports=[replay_single_decision(_case(replay_case_id=f'case-{i}'),(ReplayPolicy.HOLD,ReplayPolicy.GREEDY_1GW)) for i in range(4)]
 summary=summarize_replays(reports); greedy=next(x for x in summary.policy_metrics if x.policy is ReplayPolicy.GREEDY_1GW)
 assert greedy.label=='INSUFFICIENT SAMPLE' and summary.to_dict()==summarize_replays(reports).to_dict()

def test_regret_sign_and_projection_metrics_are_separate():
 report=replay_single_decision(_case(),(ReplayPolicy.HOLD,ReplayPolicy.GREEDY_1GW))
 greedy=next(x for x in report.policy_results if x.policy is ReplayPolicy.GREEDY_1GW)
 hold=next(x for x in report.policy_results if x.policy is ReplayPolicy.HOLD)
 assert greedy.sign_accuracy is True and greedy.transfer_regret[1] == 0.
 assert hold.hold_regret[1] == 4.
 metrics=projection_metrics([{'expected_points':4.,'realised_points':6.,'p_5_plus':.4},{'expected_points':6.,'realised_points':4.,'p_5_plus':.6}])
 assert metrics['sample_size']==2 and metrics['brier_5_plus'] is not None
