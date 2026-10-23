"""Exact reduced K<=5 universes versus the unchanged incumbent+C portfolio."""
from collections import Counter
from dataclasses import replace
from itertools import combinations, product
import json
from pathlib import Path
import sys
from time import perf_counter

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT),str(ROOT/'src')]
from fpl_engine.optimizer import OptimizerRules
from fpl_engine.strategy.strategic_planner_v3 import StrategicPlannerV3,StrategicPlannerV3Config,StrategicPath
from scripts.diagnostics.v3_multi_transfer_oracle import _hold,_solve,_fixture,_projection
from scripts.diagnostics.v3_challenger_oracle import _club_cycle_fixture,_funding_cycle_fixture,_five_transfer_fixture
from scripts.diagnostics.v3_beam_quality_oracle import _fixture_for
from scripts.diagnostics.v3_guarded_portfolio import run_portfolio,validate_path
from scripts.diagnostics.v3_portfolio_contexts import OUT,synthetic_input


class ExactActions:
    """Complete position-matched sets; only provably unaffordable sets are skipped."""
    def __init__(self,planner,pool,projections):
        self.planner,self.pool,self.projections=planner,pool,projections
        self.cache={}

    def __call__(self,state):
        # Financial identities may recur with different GW/FT; rebuild native hits.
        key=(state.bank,tuple(sorted((p.player_id,p.selling_price) for p in state.players)))
        owned={p.player_id:p for p in state.players}
        if key not in self.cache:
            by_pos={pos:tuple(sorted((p for p in self.pool.values() if p.player_id not in owned and p.position==pos),key=lambda p:p.player_id))
                for pos in ('GK','DEF','MID','FWD')}
            sets=[]
            for k in range(1,6):
                for outgoing in combinations(sorted(state.players,key=lambda p:p.player_id),k):
                    counts=Counter(p.position for p in outgoing)
                    if any(len(by_pos[pos])<n for pos,n in counts.items()):
                        continue
                    cheapest=sum(sum(sorted(p.current_price for p in by_pos[pos])[:n]) for pos,n in counts.items())
                    if cheapest>state.bank+sum(p.selling_price for p in outgoing):
                        continue
                    choices=[tuple(combinations(by_pos[pos],n)) for pos,n in sorted(counts.items())]
                    for groups in product(*choices):
                        incoming=tuple(p for group in groups for p in group)
                        action=self.planner._make_action(state,outgoing,incoming)
                        if action is not None:
                            sets.append((action.transfers_out,action.transfers_in))
            self.cache[key]=tuple(sorted(sets))
        actions=[_hold(state,self.planner.rules)]
        for outs,ins in self.cache[key]:
            incoming=tuple(self.pool[x] for x in ins)
            if any(self.planner._gameweek_projection(self.projections[p.player_id],state.current_gameweek) is None for p in incoming):
                continue
            action=self.planner._make_action(state,tuple(owned[x] for x in outs),incoming)
            assert action is not None
            actions.append(action)
        return actions


def run_case(name,fixture,rules):
    state,pool,projections=fixture
    started=perf_counter()
    exact=StrategicPlannerV3(rules,replace(StrategicPlannerV3Config(),max_transfers_per_action=5))
    provider=ExactActions(exact,pool,projections)
    optimum,counts=_solve(exact,state,pool,projections,provider)
    shared=synthetic_input(name,state,pool,projections,rules)
    current=state
    exact_steps=[]
    for offset,(_,outs,ins) in enumerate(optimum[3]):
        owned={p.player_id:p for p in current.players}
        action=exact._make_action(current,tuple(owned[x] for x in outs),tuple(pool[x] for x in ins)) if outs else _hold(current,rules)
        assert action is not None
        current,step=exact._evaluate_action(current,action,pool,projections,target_gameweek=current.current_gameweek,signals=None,offset=offset)
        exact_steps.append(step)
    exact_path=StrategicPath(tuple(exact_steps),optimum[1],optimum[2],optimum[0])
    exact_replay=validate_path(shared,exact_path,max_k=5)
    outcome=run_portfolio(shared)
    assert outcome.challenger is not None,outcome.diagnostics
    incumbent=outcome.incumbent.result.best_path.total_path_value
    challenger=outcome.challenger.result.best_path.total_path_value
    selected=outcome.selected.best_path.total_path_value
    assert selected>=incumbent
    assert selected<=optimum[0]+1e-9
    repeat=run_portfolio(shared)
    def semantic(result):
        payload=result.as_dict()
        payload.pop('diagnostics')
        return payload
    assert semantic(repeat.incumbent.result)==semantic(outcome.incumbent.result)
    assert semantic(repeat.challenger.result)==semantic(outcome.challenger.result)
    assert repeat.as_v3_result()==outcome.as_v3_result()
    return {'case':name,'scope':'SYNTHETIC_REDUCED_EXACT_K0_TO_K5_NOT_HISTORICAL_PIT',
        'ft':state.free_transfers,'bank':state.bank,'exact':optimum[0],
        'incumbent':incumbent,'challenger':challenger,'portfolio':selected,
        'challenger_gap':optimum[0]-challenger,'portfolio_gap':optimum[0]-selected,
        'optimum_retained':abs(optimum[0]-selected)<=1e-9,
        'root_by_k':dict(Counter(a.transfers_used for a in provider(state))),
        'exact_states':counts['states'],'exact_actions':counts['actions'],
        'exact_reconstruction':exact_replay,
        'exact_path':optimum[3],'selected':outcome.as_v3_result().as_dict(),
        'reconstruction':validate_path(shared,outcome.selected.best_path,max_k=5),
        'deterministic':True,'seconds':perf_counter()-started}


def main():
    rules=OptimizerRules.load(ROOT)
    cases=[(name,_fixture_for(name,rules)) for name in (
        'delayed_payoff','valuable_free_transfer','early_transfer_unlocks',
        'duplicate_path_crowding','horizon_vs_raw_points','transfer_vs_forced_hold',
        'seeded_adversarial_1','seeded_adversarial_3','ft_terminal_crowding')]
    cases += [('atomic_four_club',_club_cycle_fixture(rules)),
        ('funding_K3',_funding_cycle_fixture(rules,3)),('funding_K4',_funding_cycle_fixture(rules,4)),
        ('K5',_five_transfer_fixture(rules))]
    for ft in range(1,6):
        state,pool,projections=_fixture(900+ft,rules)
        state=replace(state,free_transfers=ft,bank=ft-1)
        if ft==5:
            projections={pid:_projection(pid,(20.,20.,20.) if pid.startswith('owned') else (1.,1.,1.)) for pid in projections}
        cases.append(('FT'+str(ft)+'_bank'+str(ft-1), (state,pool,projections)))
    rows=[]
    for name,fixture in cases:
        print('START '+name,flush=True)
        row=run_case(name,fixture,rules)
        rows.append(row)
        (OUT/'portfolio_oracles.json').write_text(json.dumps({'cases':rows},indent=2),encoding='utf-8')
        print(json.dumps({k:row[k] for k in ('case','exact','incumbent','challenger','portfolio','portfolio_gap','seconds')}),flush=True)
    assert next(row for row in rows if row['case']=='atomic_four_club')['portfolio']==237.0


if __name__=='__main__':
    main()
