"""Offline frozen-GW8 path-retention audit. Never used by production."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT),str(ROOT/'src')]
OUT = ROOT/'scratch/v3_beam_quality_20261022'
import scripts.diagnostics.v3_challenger_benchmark as inputs
inputs.OUT = OUT
from fpl_engine.strategy.strategic_planner_v3 import StrategicPlannerV3, _Node
from scripts.diagnostics.v3_beam_quality import BeamAuditPlanner
from scripts.diagnostics.v3_incumbent_challenger import compare_paths


def known_nodes(state,pool,projections,rules,names):
    """Observation target only; never supplied to pruning or candidate selection."""
    planner = StrategicPlannerV3(rules)
    owned = {p.player_id:p for p in state.players}
    outs = {pid for pid,name in names.items() if name in {'Giles','B.Fernandes'}}
    ins = {pid for pid,name in names.items() if name in {'Gabriel','Mbeumo'}}
    first = planner._make_action(state,tuple(owned[x] for x in sorted(outs)),tuple(pool[x] for x in sorted(ins)))
    assert first is not None
    nodes,steps,points = [],(),0.0
    for offset in range(3):
        action = first if not offset else next(a for a in planner._actions_for_state(state,pool,projections,target_gameweek=state.current_gameweek) if a.is_hold)
        state,step = planner._evaluate_action(state,action,pool,projections,target_gameweek=state.current_gameweek,signals=None,offset=offset)
        steps += (step,)
        points += step.points_after_hit
        nodes.append(_Node(state,steps,points))
    assert abs(points+planner._terminal_ft_value(state)-148.26775)<1e-9
    return nodes


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--candidate-mode',choices=('native','k2','k5'),required=True)
    parser.add_argument('--strategy',choices=('raw','dominance','diversity','horizon'),required=True)
    args = parser.parse_args()
    OUT.mkdir(parents=True,exist_ok=True)
    state,pool,projections,rules,names = inputs.load_inputs()
    targets = known_nodes(state,pool,projections,rules,names)
    planner = BeamAuditPlanner(rules,strategy=args.strategy,candidate_mode=args.candidate_mode,trace_target=targets)
    started = perf_counter()
    result = planner.plan(state,pool.values(),projections)
    elapsed = perf_counter()-started
    payload = result.as_dict()
    assert abs(result.best_path.total_path_value-(result.best_path.projected_3gw_path_points+result.best_path.terminal_ft_value))<1e-9
    assert result.best_path.total_path_value >= result.hold_now_path.total_path_value-1e-9
    benchmark = {'mode':args.candidate_mode,'strategy':args.strategy,'wall_seconds':elapsed,
        'peak_working_set_mb':inputs.peak_memory(),'diagnostics':dict(result.diagnostics),
        'stats':planner.stats,'selected':inputs.describe(result.best_path,names),
        'forced_hold':inputs.describe(result.hold_now_path,names),'result':payload,
        'context_id':'9362daa92b379107175befb935f70b38d755f7fd5c9196560e28791d3e0c1208'}
    if args.candidate_mode=='native' and args.strategy=='raw':
        expected=json.loads((ROOT/'scratch/v3_challenger_20261022/incumbent.json').read_text())['result']
        for key in ('current_action','path','hold_now_counterfactual','total_path_value','terminal_ft_value'):
            assert payload[key]==expected[key], 'Raw diagnostic search differs from native baseline: '+key
    if args.candidate_mode=='k5' and args.strategy=='raw':
        expected=json.loads((ROOT/'scratch/v3_challenger_20261022/package_beam.json').read_text())['result']
        for key in ('current_action','path','hold_now_counterfactual','total_path_value','terminal_ft_value'):
            assert payload[key]==expected[key], 'Raw diagnostic search differs from original challenger: '+key
    destination=OUT/(args.candidate_mode+'_'+args.strategy+'.json')
    destination.write_text(json.dumps(benchmark,indent=2),encoding='utf-8')
    print(json.dumps({'mode':args.candidate_mode,'strategy':args.strategy,'wall_seconds':elapsed,
        'memory':benchmark['peak_working_set_mb'],'objective':result.best_path.total_path_value,
        'action':{k:v for k,v in benchmark['selected'].items() if k!='path'},
        'dominated':planner.stats['dominated'],'equal_duplicates':planner.stats['equal_duplicates'],
        'trace':[{k:v for k,v in row.items() if k!='state'} for row in planner.stats['trace']]}),flush=True)


if __name__=='__main__':
    main()
