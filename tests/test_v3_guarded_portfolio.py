from dataclasses import replace
import math
import pytest

from fpl_engine.optimizer import OptimizerRules
from scripts.diagnostics.v3_multi_transfer_oracle import _fixture
from scripts.diagnostics.v3_challenger_oracle import _exhaustive_actions_with_hits
from scripts.diagnostics.v3_guarded_portfolio import (
    PortfolioResult,PortfolioValidationError,execute_policy,run_portfolio,select_complete,validate_path,
)
from scripts.diagnostics.v3_portfolio_contexts import ROOT,synthetic_input
from scripts.diagnostics.v3_portfolio_oracle import ExactActions


@pytest.fixture(scope='module')
def valid():
    rules=OptimizerRules.load(ROOT)
    state,pool,projections=_fixture(1,rules)
    shared=synthetic_input('fallback',state,pool,projections,rules)
    envelope=execute_policy(shared)
    return shared,envelope


@pytest.mark.parametrize('delta',[-5e-10,0.,5e-10,1.])
def test_strict_complete_argmax_never_discards_micro_improvement(valid,delta):
    path=valid[1].result.best_path
    challenger=replace(path,total_path_value=path.total_path_value+delta)
    selected=select_complete(path,challenger)
    assert selected.total_path_value==max(path.total_path_value,challenger.total_path_value)


def test_exact_tie_prefers_hold(valid):
    transfer=valid[1].result.best_path
    hold=replace(valid[1].result.hold_now_path,total_path_value=transfer.total_path_value)
    assert select_complete(transfer,hold) is hold
    assert select_complete(hold,transfer) is hold


def corrupt(envelope,kind):
    if kind=='context':
        return replace(envelope,context_id='wrong-context')
    if kind=='integrity':
        return replace(envelope,input_sha256='0'*64)
    path=envelope.result.best_path
    if kind=='nan':
        path=replace(path,total_path_value=math.nan)
    elif kind=='objective':
        path=replace(path,total_path_value=path.total_path_value+1)
    elif kind=='xi':
        path=replace(path,steps=(replace(path.steps[0],starting_xi=('invalid',)*11),*path.steps[1:]))
    elif kind=='captain':
        path=replace(path,steps=(replace(path.steps[0],captain_id='invalid'),*path.steps[1:]))
    else:
        step=path.steps[0]
        field={'hit':'hit_cost_points','ft':'free_transfers_after','bank':'resulting_bank'}[kind]
        action=replace(step.action,**{field:getattr(step.action,field)+1})
        path=replace(path,steps=(replace(step,action=action),*path.steps[1:]))
    return replace(envelope,result=replace(envelope.result,best_path=path))


@pytest.mark.parametrize('kind',['context','integrity','nan','objective','xi','captain','hit','ft','bank','exception'])
def test_actual_adapter_rejects_bad_challenger_and_retains_independent_incumbent(valid,kind):
    shared,envelope=valid
    def challenger(_):
        if kind=='exception':
            raise RuntimeError('controlled challenger failure')
        return corrupt(envelope,kind)
    result=run_portfolio(shared,incumbent_runner=lambda _:envelope,challenger_runner=challenger)
    assert result.incumbent is envelope
    assert result.selected is envelope.result
    assert result.challenger is None
    assert result.diagnostics['challenger_status']=='FAILED'
    assert result.diagnostics['challenger_error']


def test_invalid_incumbent_is_fatal(valid):
    shared,envelope=valid
    with pytest.raises(PortfolioValidationError):
        run_portfolio(shared,incumbent_runner=lambda _:corrupt(envelope,'objective'))


def test_valid_replay_and_same_result_guard(valid):
    shared,envelope=valid
    result=run_portfolio(shared,incumbent_runner=lambda _:envelope,challenger_runner=lambda _:envelope)
    assert result.selected is envelope.result
    assert result.diagnostics['challenger_status']=='PASS'
    checked=validate_path(shared,result.selected.best_path,max_k=2)
    assert abs(checked['objective']-result.selected.best_path.total_path_value)<1e-9


def test_hold_selection_retains_distinct_transfer_alternative(valid):
    _,envelope=valid
    result=envelope.result
    assert result.best_path!=result.hold_now_path
    hold_result=replace(result,best_path=result.hold_now_path,alternative_path=result.best_path)
    hold_envelope=replace(envelope,result=hold_result)
    composite=PortfolioResult(hold_envelope,None,'incumbent',{'challenger_status':'FAILED'}).as_v3_result()
    assert composite.best_path is result.hold_now_path
    assert composite.alternative_path is result.best_path


def test_k0_through_k5_sets_and_paid_hit_progression(valid):
    from scripts.diagnostics.v3_challenger_oracle import _five_transfer_fixture
    from fpl_engine.strategy.strategic_planner_v3 import StrategicPlannerV3,StrategicPlannerV3Config
    rules=valid[0].rules
    state,pool,projections=_five_transfer_fixture(rules)
    state=replace(state,free_transfers=1)
    planner=StrategicPlannerV3(rules,replace(StrategicPlannerV3Config(),max_transfers_per_action=5))
    actions=ExactActions(planner,pool,projections)(state)
    assert {a.transfers_used for a in actions}==set(range(6))
    for action in actions:
        assert action.hit_cost_points==max(0,action.transfers_used-1)*4
        assert action.free_transfers_after==(2 if action.is_hold else 1)


def test_exact_enumerator_matches_independent_bruteforce_with_paid_hits(valid):
    shared,_=valid
    from fpl_engine.strategy.strategic_planner_v3 import StrategicPlannerV3,StrategicPlannerV3Config
    planner=StrategicPlannerV3(shared.rules,replace(StrategicPlannerV3Config(),max_transfers_per_action=5))
    state=replace(shared.state,free_transfers=1)
    pool={p.player_id:p for p in shared.player_pool}
    actual=ExactActions(planner,pool,shared.projections)(state)
    expected=_exhaustive_actions_with_hits(planner,state,pool,shared.projections,max_k=5)
    key=lambda a:(a.transfers_out,a.transfers_in,a.hit_cost_points,a.free_transfers_after,a.resulting_bank)
    assert {key(a) for a in actual}=={key(a) for a in expected}
    assert any(a.transfers_used==4 and a.hit_cost_points==12 for a in actual)
