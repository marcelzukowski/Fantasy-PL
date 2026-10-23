"""Diagnostic-only incumbent+C adapter. No production entrypoint imports this."""
from copy import deepcopy
from collections import Counter
from dataclasses import asdict, dataclass, replace
from hashlib import sha256
import json
from math import isfinite
from time import perf_counter

from fpl_engine.optimizer import validate_squad, next_free_transfers
from fpl_engine.planning import DecisionInput
from fpl_engine.strategy.strategic_planner_v3 import (
    StrategicAction, StrategicPlannerV3, StrategicPlannerV3Config, StrategicPlannerV3Result,
)
from scripts.diagnostics.v3_beam_quality import BeamAuditPlanner


class PortfolioValidationError(ValueError):
    pass


def input_digest(shared):
    payload = {'context':shared.planning_context.to_dict(),'state':asdict(shared.state),
        'pool':[asdict(p) for p in sorted(shared.player_pool,key=lambda p:p.player_id)],
        'projections':{pid:asdict(row) for pid,row in sorted(shared.projections.items())},
        'rules':shared.rules.raw}
    return sha256(json.dumps(payload,sort_keys=True,default=str,separators=(',',':')).encode()).hexdigest()


def isolated_input(shared):
    state,pool,projections,rules = deepcopy((shared.state,shared.player_pool,dict(shared.projections),shared.rules))
    return DecisionInput.create(planning_context=shared.planning_context,state=state,player_pool=pool,
        projections=projections,pipeline=dict(shared.pipeline),warnings=shared.warnings,rules=rules,
        freshness=shared.freshness,bundle_identity=shared.bundle_identity)


@dataclass(frozen=True)
class PolicyEnvelope:
    context_id: str
    input_sha256: str
    result: StrategicPlannerV3Result
    metrics: dict


def execute_policy(shared, *, challenger=False):
    before=input_digest(shared)
    planner=BeamAuditPlanner(shared.rules,strategy='horizon',candidate_mode='k5') if challenger else StrategicPlannerV3(shared.rules)
    started=perf_counter()
    result=planner.plan(shared.state,shared.player_pool,shared.projections)
    metrics={'search_seconds':perf_counter()-started,'native_diagnostics':dict(result.diagnostics)}
    metrics['lineup_computations']=len(planner._lineup_cache)
    if not challenger:
        metrics['lineup_cache_hits']=result.diagnostics['candidate_actions_evaluated']-len(planner._lineup_cache)
    if challenger:
        metrics['counters']=planner.stats
    if input_digest(shared)!=before:
        raise PortfolioValidationError('Policy mutated its canonical inputs')
    return PolicyEnvelope(shared.context_id,before,result,metrics)


def _close(actual,expected,label):
    if not isinstance(actual,(int,float)) or not isfinite(actual) or abs(actual-expected)>1e-9:
        raise PortfolioValidationError(label+' mismatch')


def validate_path(shared,path,*,max_k):
    """Replay every final package with native legality, pricing, hits and lineups."""
    if len(path.steps)!=3:
        raise PortfolioValidationError('Path horizon must be three gameweeks')
    verifier=StrategicPlannerV3(shared.rules,replace(StrategicPlannerV3Config(),max_transfers_per_action=max_k))
    pool={p.player_id:p for p in shared.player_pool}
    state=shared.state
    points=0.0
    rows=[]
    for offset,step in enumerate(path.steps):
        validate_squad(state,shared.rules)
        action=step.action
        outs,ins=action.transfers_out,action.transfers_in
        if (len(outs)!=len(ins) or len(set(outs))!=len(outs) or len(set(ins))!=len(ins)
                or set(outs)&set(ins) or len(outs)>max_k or tuple(sorted(outs))!=outs or tuple(sorted(ins))!=ins):
            raise PortfolioValidationError('Invalid transfer-set identity')
        owned={p.player_id:p for p in state.players}
        if not set(outs)<=set(owned) or set(ins)&set(owned) or not set(ins)<=set(pool):
            raise PortfolioValidationError('Transfer membership mismatch')
        if outs:
            expected=verifier._make_action(state,tuple(owned[x] for x in outs),tuple(pool[x] for x in ins))
        else:
            expected=StrategicAction('HOLD',(),(),0,0,state.bank,state.free_transfers,
                next_free_transfers(state.free_transfers,0,shared.rules),tuple(sorted(owned)))
        if expected is None or action!=expected or step.gameweek!=state.current_gameweek:
            raise PortfolioValidationError('Action/finance/FT/hit contract mismatch')
        next_state,recomputed=verifier._evaluate_action(state,expected,pool,shared.projections,
            target_gameweek=state.current_gameweek,signals=None,offset=offset)
        validate_squad(next_state,shared.rules)
        _close(step.lineup_points,recomputed.lineup_points,'Lineup objective')
        _close(step.points_after_hit,recomputed.points_after_hit,'Points after hits')
        xi,bench=step.starting_xi,step.bench_order
        players={p.player_id:p for p in next_state.players}
        if (len(xi)!=11 or len(set(xi))!=11 or len(bench)!=4 or len(set(bench))!=4
                or set(xi)&set(bench) or set(xi)|set(bench)!=set(players)
                or step.captain_id not in xi or step.vice_captain_id not in xi or step.captain_id==step.vice_captain_id):
            raise PortfolioValidationError('Lineup membership/captain identity mismatch')
        counts=Counter(players[pid].position for pid in xi)
        if counts['GK']!=1 or not 3<=counts['DEF']<=5 or not 2<=counts['MID']<=5 or not 1<=counts['FWD']<=3:
            raise PortfolioValidationError('Illegal XI formation')
        ev={pid:verifier._points(shared.projections[pid],state.current_gameweek) for pid in players}
        # Native cache may retain a different tied optimum/player order. Check its
        # exact legal score and bench contract rather than rejecting valid ties.
        multiplier=int(shared.rules.value('captaincy','captain_multiplier'))
        _close(sum(ev[pid] for pid in xi)+ev[step.captain_id]*(multiplier-1),step.lineup_points,'Reported XI score')
        _close(ev[step.captain_id],max(ev[pid] for pid in xi),'Captain maximum')
        _close(ev[step.vice_captain_id],max(ev[pid] for pid in xi if pid!=step.captain_id),'Vice-captain maximum')
        expected_bench=tuple(pid for pid in bench if players[pid].position=='GK')+tuple(sorted(
            (pid for pid in bench if players[pid].position!='GK'),key=lambda pid:(-ev[pid],pid)))
        if bench!=expected_bench:
            raise PortfolioValidationError('Bench ordering mismatch')
        points+=recomputed.points_after_hit
        rows.append({'gw':step.gameweek,'k':len(outs),'bank':next_state.bank,'ft_before':state.free_transfers,
            'ft_after':next_state.free_transfers,'hit':expected.hit_cost_points,'lineup_points':recomputed.lineup_points})
        state=next_state
    terminal=verifier._terminal_ft_value(state)
    _close(path.projected_3gw_path_points,points,'Path points')
    _close(path.terminal_ft_value,terminal,'Terminal FT')
    _close(path.total_path_value,points+terminal,'Complete objective')
    return {'steps':rows,'path_points':points,'terminal_ft_value':terminal,'objective':points+terminal}


def validate_envelope(shared,envelope,*,max_k):
    if not isinstance(envelope,PolicyEnvelope) or envelope.context_id!=shared.context_id:
        raise PortfolioValidationError('Policy PlanningContext mismatch')
    if envelope.input_sha256!=input_digest(shared):
        raise PortfolioValidationError('Policy input/artifact integrity mismatch')
    result=envelope.result
    if not isinstance(result,StrategicPlannerV3Result):
        raise PortfolioValidationError('Invalid policy result type')
    checks={name:validate_path(shared,path,max_k=max_k) for name,path in (
        ('selected',result.best_path),('forced_hold',result.hold_now_path),
        ('alternative',result.alternative_path or result.hold_now_path))}
    if not result.hold_now_path.steps[0].action.is_hold:
        raise PortfolioValidationError('Forced-HOLD path is not HOLD')
    if result.best_path.total_path_value+1e-9<result.hold_now_path.total_path_value:
        raise PortfolioValidationError('Policy selected inferior path over forced HOLD')
    if (abs(result.best_path.total_path_value-result.hold_now_path.total_path_value)<=1e-9
            and not result.best_path.steps[0].action.is_hold):
        raise PortfolioValidationError('Policy HOLD tie preference violated')
    return checks


def select_complete(incumbent,challenger):
    """Strict argmax; never discard a positive improvement, even below 1e-9."""
    if challenger.total_path_value>incumbent.total_path_value:
        return challenger
    if (challenger.total_path_value==incumbent.total_path_value
            and challenger.steps[0].action.is_hold and not incumbent.steps[0].action.is_hold):
        return challenger
    return incumbent


@dataclass(frozen=True)
class PortfolioResult:
    incumbent: PolicyEnvelope
    challenger: PolicyEnvelope | None
    selected_policy: str
    diagnostics: dict

    @property
    def selected(self):
        return self.challenger.result if self.selected_policy=='challenger_C' else self.incumbent.result

    def as_v3_result(self):
        results=[self.incumbent.result]+([self.challenger.result] if self.challenger is not None else [])
        best=self.selected.best_path
        hold=results[0].hold_now_path
        alternatives=[]
        for result in results:
            hold=select_complete(hold,result.hold_now_path)
            alternatives.extend(path for path in (result.best_path,result.hold_now_path,result.alternative_path)
                if path is not None and path!=best)
        alternative=alternatives[0] if alternatives else hold
        for path in alternatives[1:]:
            alternative=select_complete(alternative,path)
        return StrategicPlannerV3Result(best,hold,{'portfolio_diagnostic':True,'selected_policy':self.selected_policy,
            'context_id':self.incumbent.context_id,'challenger_status':self.diagnostics['challenger_status']},alternative)


def run_portfolio(shared,*,incumbent_runner=None,challenger_runner=None):
    """Run isolated policies; only context-bound, replay-validated outputs may win."""
    started=perf_counter()
    if shared.context_id!=shared.planning_context.context_id or shared.artifact_identities!=shared.planning_context.artifact_hashes:
        raise PortfolioValidationError('Canonical context/artifact identity mismatch')
    canonical=isolated_input(shared)
    for name,used in canonical.planning_context.chips_used:
        if hasattr(canonical.state.chips,name) and getattr(canonical.state.chips,name)==used:
            raise PortfolioValidationError('Chip availability does not match PlanningContext')
    digest=input_digest(canonical)
    incumbent_runner=incumbent_runner or (lambda data:execute_policy(data))
    challenger_runner=challenger_runner or (lambda data:execute_policy(data,challenger=True))
    incumbent=incumbent_runner(isolated_input(canonical))
    incumbent_checks=validate_envelope(canonical,incumbent,max_k=2)
    diagnostics={'challenger_status':'FAILED','challenger_error':None,'incumbent_validation':incumbent_checks}
    challenger=None
    try:
        challenger=challenger_runner(isolated_input(canonical))
        challenger_checks=validate_envelope(canonical,challenger,max_k=5)
        diagnostics['challenger_validation']=challenger_checks
        diagnostics['challenger_status']='PASS'
    except Exception as exc:
        diagnostics['challenger_error']=type(exc).__name__+': '+str(exc)
        challenger=None
    winner='incumbent'
    if challenger is not None:
        selected=select_complete(incumbent.result.best_path,challenger.result.best_path)
        if selected is not incumbent.result.best_path:
            winner='challenger_C'
    if input_digest(canonical)!=digest:
        raise PortfolioValidationError('Canonical portfolio input was mutated')
    outcome=PortfolioResult(incumbent,challenger,winner,diagnostics)
    # Validate the composed report contract, not only its numeric guard.
    validate_path(canonical,outcome.as_v3_result().best_path,max_k=5)
    diagnostics['total_seconds']=perf_counter()-started
    return outcome
