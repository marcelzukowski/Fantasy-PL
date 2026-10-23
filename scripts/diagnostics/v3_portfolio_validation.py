"""Final frozen-context validation driver; diagnostic artifacts only."""
from dataclasses import asdict
import argparse
import json
from pathlib import Path
import sys
from time import perf_counter

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT),str(ROOT/'src')]
from scripts.diagnostics.v3_challenger_benchmark import peak_memory
from scripts.diagnostics.v3_guarded_portfolio import run_portfolio,validate_path
from scripts.diagnostics.v3_portfolio_contexts import OUT,load_frozen,inventory


def save_outcome(shared,outcome,destination,wall):
    output={'context_id':shared.context_id,'scope':'FROZEN_LOCAL_PRODUCTION_INPUT',
        'gw':shared.state.current_gameweek,'ft':shared.state.free_transfers,'bank':shared.state.bank,
        'wall_seconds':wall,'peak_memory_mib':peak_memory(),'selected_policy':outcome.selected_policy,
        'incumbent':outcome.incumbent.result.as_dict(),'incumbent_metrics':outcome.incumbent.metrics,
        'challenger':outcome.challenger.result.as_dict() if outcome.challenger else None,
        'challenger_metrics':outcome.challenger.metrics if outcome.challenger else None,
        'portfolio':outcome.as_v3_result().as_dict(),'diagnostics':outcome.diagnostics}
    assert output['portfolio']['total_path_value']>=output['incumbent']['total_path_value']
    destination.write_text(json.dumps(output,indent=2,default=str),encoding='utf-8')
    return output


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('analysis',type=Path)
    args=parser.parse_args()
    shared=load_frozen(args.analysis)
    started=perf_counter()
    outcome=run_portfolio(shared)
    wall=perf_counter()-started
    output=save_outcome(shared,outcome,OUT/('frozen-'+shared.context_id+'.json'),wall)
    if shared.context_id=='9362daa92b379107175befb935f70b38d755f7fd5c9196560e28791d3e0c1208':
        assert output['incumbent']['current_action']['action']=='HOLD'
        assert abs(output['incumbent']['total_path_value']-147.42035)<1e-9
        assert output['challenger'] is not None, output['diagnostics']
        assert abs(output['challenger']['total_path_value']-148.61620)<1e-9
        assert abs(output['portfolio']['total_path_value']-148.61620)<1e-9
    print(json.dumps({'context':shared.context_id,'gw':shared.state.current_gameweek,'seconds':wall,
        'memory_mib':output['peak_memory_mib'],'incumbent':output['incumbent']['total_path_value'],
        'challenger':output['challenger']['total_path_value'] if output['challenger'] else None,
        'portfolio':output['portfolio']['total_path_value'],'diagnostic':outcome.diagnostics.get('challenger_error')}),flush=True)


if __name__=='__main__':
    main()
