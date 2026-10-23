"""Independent explicit GW8 references and replay of saved diagnostic paths."""
from dataclasses import fields,replace
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT),str(ROOT/'src')]
from fpl_engine.strategy.strategic_planner_v3 import (
    StrategicAction,StrategicPathStep,StrategicPath,StrategicPlannerV3,StrategicPlannerV3Result,StrategicPlannerV3Config,
)
from scripts.diagnostics.v3_multi_transfer_oracle import _hold
from scripts.diagnostics.v3_guarded_portfolio import validate_path,PortfolioResult,PolicyEnvelope,input_digest,validate_envelope
from scripts.diagnostics.v3_portfolio_contexts import OUT,inventory


def path_from_dict(payload):
    steps=[]
    for row in payload['path']:
        action={f.name:row[f.name] for f in fields(StrategicAction)}
        for key in ('transfers_out','transfers_in','resulting_squad'):
            action[key]=tuple(action[key])
        steps.append(StrategicPathStep(row['gw'],StrategicAction(**action),row['lineup_points'],
            row['points_after_hit'],tuple(row['starting_xi']),tuple(row['bench_order']),
            row['captain'],row['vice_captain'],row['price_risk']))
    return StrategicPath(tuple(steps),payload['projected_3gw_path_points'],payload['terminal_ft_value'],payload['total_path_value'])


def result_from_dict(payload):
    return StrategicPlannerV3Result(path_from_dict(payload),path_from_dict(payload['hold_now_counterfactual']),
        payload['diagnostics'],path_from_dict(payload['alternative_path']))


def main():
    contexts=inventory()
    for context,(_,shared) in contexts.items():
        saved=OUT/('frozen-'+context+'.json')
        payload=json.loads(saved.read_text())
        envelopes=[PolicyEnvelope(context,input_digest(shared),result_from_dict(payload[key]),payload[key+'_metrics'])
            for key in ('incumbent','challenger')]
        for envelope,cap in zip(envelopes,(2,5)):
            validate_envelope(shared,envelope,max_k=cap)
        composed=PortfolioResult(*envelopes,payload['selected_policy'],payload['diagnostics']).as_v3_result()
        for path in (composed.best_path,composed.hold_now_path,composed.alternative_path):
            validate_path(shared,path,max_k=5)
        payload['portfolio']=composed.as_dict()
        payload['composed_contract_replayed']=True
        saved.write_text(json.dumps(payload,indent=2),encoding='utf-8')
    shared=next(shared for _,shared in contexts.values() if shared.state.current_gameweek==8)
    players_path=ROOT/'data/processed/predictions/2026-27'/shared.bundle_identity/'current_players.json'
    names={p['player_id']:p['display_name'] for p in json.loads(players_path.read_text(encoding='utf-8'))}
    pool={p.player_id:p for p in shared.player_pool}
    references=[]
    saved_gw8=json.loads((OUT/('frozen-'+shared.context_id+'.json')).read_text())
    for label,outs,ins,expected in (
        ('incumbent',set(),set(),147.42035),
        ('known_K2',{'Giles','B.Fernandes'},{'Gabriel','Mbeumo'},148.26775),
        ('challenger_C',{'De Cuyper','Sels','B.Fernandes'},{'Gabriel','Mbeumo','Raya'},148.61620)):
        planner=StrategicPlannerV3(shared.rules,replace(StrategicPlannerV3Config(),max_transfers_per_action=5))
        current=shared.state
        owned={p.player_id:p for p in current.players}
        out_ids=tuple(sorted(pid for pid,name in names.items() if name in outs))
        in_ids=tuple(sorted(pid for pid,name in names.items() if name in ins))
        # Current metadata spelling is authoritative; fail rather than guess IDs.
        assert len(out_ids)==len(outs),(label,outs,[n for n in names.values() if 'Cuyper' in n])
        assert len(in_ids)==len(ins)
        first=planner._make_action(current,tuple(owned[x] for x in out_ids),tuple(pool[x] for x in in_ids)) if outs else _hold(current,shared.rules)
        assert first is not None
        steps=[]
        for offset in range(3):
            action=first if offset==0 else _hold(current,shared.rules)
            if label=='incumbent':
                row=saved_gw8['incumbent']['path'][offset]
                if row['transfers_out']:
                    current_owned={p.player_id:p for p in current.players}
                    action=planner._make_action(current,tuple(current_owned[x] for x in row['transfers_out']),
                        tuple(pool[x] for x in row['transfers_in']))
                    assert action is not None
            current,step=planner._evaluate_action(current,action,pool,shared.projections,
                target_gameweek=current.current_gameweek,signals=None,offset=offset)
            steps.append(step)
        points=sum(step.points_after_hit for step in steps)
        terminal=planner._terminal_ft_value(current)
        path=StrategicPath(tuple(steps),points,terminal,points+terminal)
        assert abs(path.total_path_value-expected)<1e-9,(label,path.total_path_value)
        references.append({'reference':label,'out':sorted(outs),'in':sorted(ins),
            **validate_path(shared,path,max_k=5)})
    (OUT/'gw8_reference_validation.json').write_text(json.dumps({'context_id':shared.context_id,
        'references':references},indent=2),encoding='utf-8')
    print(json.dumps(references),flush=True)


if __name__=='__main__':
    main()
